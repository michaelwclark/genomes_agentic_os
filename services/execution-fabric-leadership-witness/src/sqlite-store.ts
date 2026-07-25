import { randomUUID } from "node:crypto";
import {
  chmodSync,
  copyFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  statSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { dirname } from "node:path";
import { DatabaseSync } from "node:sqlite";
import type {
  AuditRecord,
  CandidateRecord,
  ConfigDigestRotationAbortReceipt,
  ConfigDigestRotationPreparation,
  ConfigDigestRotationReceipt,
  FailbackPlan,
  LeadershipState,
  PromotionReceipt,
} from "./contracts.js";
import {
  InMemoryWitnessStore,
  type WitnessStoreSnapshot,
} from "./store.js";

type SnapshotRow = {
  version: number;
  payload: string;
};

type BootstrapSentinel = {
  schemaVersion: "execution-fabric-witness-bootstrap/v1";
  clusterId: string;
  initializedAt: string;
  database: string;
  backup: string;
};

export type SqliteWitnessOptions = {
  allowInitialBootstrap?: boolean;
  leaseDurationMs?: number;
  now?: () => number;
};

function snapshotFromJson(payload: string): WitnessStoreSnapshot {
  const decoded: unknown = JSON.parse(payload);
  if (
    typeof decoded !== "object" ||
    decoded === null ||
    !("schemaVersion" in decoded) ||
    decoded.schemaVersion !== "execution-fabric-witness-store/v2"
  ) {
    throw new Error("portable witness state has an unsupported schema");
  }
  const record = decoded as Record<string, unknown>;
  for (const field of [
    "promotions",
    "candidates",
    "plans",
    "configRotations",
    "configRotationAborts",
    "configRotationPreparations",
    "audit",
  ]) {
    if (!(field in record) || !Array.isArray(record[field])) {
      throw new Error(`portable witness state field ${field} must be an array`);
    }
  }
  return decoded as WitnessStoreSnapshot;
}

function quickCheck(database: DatabaseSync, label: string): void {
  const rows = database.prepare("PRAGMA quick_check").all() as Array<{
    quick_check: string;
  }>;
  if (rows.length !== 1 || rows[0]?.quick_check !== "ok") {
    throw new Error(`${label} failed SQLite quick_check`);
  }
}

/**
 * Durable provider-neutral storage for one independent witness process.
 *
 * A bootstrap sentinel prevents a missing or corrupt initialized database from
 * silently becoming a fresh epoch-one authority. Every state mutation uses a
 * stale-local-version CAS and writes its replay receipt in the same SQLite
 * transaction. A renewable database lease fences a paused or duplicate
 * process before it can mutate authority.
 */
export class SqliteWitnessStore extends InMemoryWitnessStore {
  private readonly database: DatabaseSync;
  private readonly ownerToken = randomUUID();
  private readonly now: () => number;
  private readonly leaseDurationMs: number;
  private readonly sentinelPath: string;
  private readonly backupPath: string;
  private readonly bootstrapPending: boolean;
  private readonly leaseTimer: NodeJS.Timeout;
  private version = 0;
  private storageFailure?: Error;
  private closed = false;
  private lastPersistedSnapshot: WitnessStoreSnapshot = {
    schemaVersion: "execution-fabric-witness-store/v2",
    promotions: [],
    candidates: [],
    plans: [],
    configRotations: [],
    configRotationAborts: [],
    configRotationPreparations: [],
    audit: [],
  };

  constructor(
    private readonly databasePath: string,
    private readonly clusterId: string,
    options: SqliteWitnessOptions = {},
  ) {
    super();
    this.now = options.now ?? Date.now;
    this.leaseDurationMs = options.leaseDurationMs ?? 30_000;
    if (this.leaseDurationMs < 3_000) {
      throw new Error("portable witness process lease must be at least 3000ms");
    }
    this.sentinelPath = `${databasePath}.initialized`;
    this.backupPath = `${databasePath}.backup`;
    const databaseExists =
      existsSync(databasePath) && statSync(databasePath).size > 0;
    const sentinelExists = existsSync(this.sentinelPath);
    if (sentinelExists && !databaseExists) {
      throw new Error(
        `initialized portable witness database is missing; restore ${this.backupPath} before restart`,
      );
    }
    if (databaseExists && !sentinelExists) {
      throw new Error(
        "portable witness database exists without its bootstrap sentinel; refusing ambiguous authority state",
      );
    }
    if (!databaseExists && !sentinelExists && !options.allowInitialBootstrap) {
      throw new Error(
        "portable witness has never been initialized; set WITNESS_BOOTSTRAP_ONCE=true for the first start only",
      );
    }
    this.bootstrapPending = !databaseExists;
    if (sentinelExists) this.validateSentinel();

    mkdirSync(dirname(databasePath), { recursive: true, mode: 0o700 });
    this.database = new DatabaseSync(databasePath);
    chmodSync(databasePath, 0o600);
    try {
      this.database.exec(`
        PRAGMA journal_mode = WAL;
        PRAGMA synchronous = FULL;
        PRAGMA foreign_keys = ON;
        PRAGMA busy_timeout = 5000;
        CREATE TABLE IF NOT EXISTS witness_snapshot (
          cluster_id TEXT PRIMARY KEY,
          version INTEGER NOT NULL CHECK (version >= 1),
          payload TEXT NOT NULL,
          updated_at TEXT NOT NULL
        ) STRICT;
        CREATE TABLE IF NOT EXISTS witness_audit (
          cluster_id TEXT NOT NULL,
          occurred_at TEXT NOT NULL,
          audit_id TEXT NOT NULL,
          payload TEXT NOT NULL,
          PRIMARY KEY (cluster_id, occurred_at, audit_id)
        ) STRICT;
        CREATE INDEX IF NOT EXISTS witness_audit_recent
          ON witness_audit (cluster_id, occurred_at DESC, audit_id DESC);
        CREATE TABLE IF NOT EXISTS witness_process_lease (
          cluster_id TEXT PRIMARY KEY,
          owner_token TEXT NOT NULL,
          lease_expires_at INTEGER NOT NULL,
          acquired_at TEXT NOT NULL
        ) STRICT;
      `);
      quickCheck(this.database, "portable witness database");
      this.claimLease();
      const row = this.database
        .prepare(
          "SELECT version, payload FROM witness_snapshot WHERE cluster_id = ?",
        )
        .get(clusterId) as SnapshotRow | undefined;
      if (row) {
        this.version = Number(row.version);
        this.lastPersistedSnapshot = snapshotFromJson(String(row.payload));
        this.restoreSnapshot(this.lastPersistedSnapshot);
      } else if (!this.bootstrapPending) {
        throw new Error(
          "initialized portable witness database has no state for the configured cluster",
        );
      }
      if (!this.bootstrapPending) this.validateBackup();
    } catch (error) {
      try {
        this.database
          .prepare(
            "DELETE FROM witness_process_lease WHERE cluster_id=? AND owner_token=?",
          )
          .run(this.clusterId, this.ownerToken);
      } catch {
        // The original corruption or configuration error remains authoritative.
      }
      this.database.close();
      throw error;
    }
    this.leaseTimer = setInterval(() => {
      try {
        this.refreshLease();
      } catch (error) {
        this.storageFailure =
          error instanceof Error ? error : new Error(String(error));
      }
    }, Math.floor(this.leaseDurationMs / 3));
    this.leaseTimer.unref();
  }

  private validateSentinel(): void {
    let sentinel: BootstrapSentinel;
    try {
      sentinel = JSON.parse(
        readFileSync(this.sentinelPath, "utf8"),
      ) as BootstrapSentinel;
    } catch {
      throw new Error("portable witness bootstrap sentinel is corrupt");
    }
    if (
      sentinel.schemaVersion !== "execution-fabric-witness-bootstrap/v1" ||
      sentinel.clusterId !== this.clusterId ||
      sentinel.database !== this.databasePath ||
      sentinel.backup !== this.backupPath
    ) {
      throw new Error(
        "portable witness bootstrap sentinel does not match this cluster or database",
      );
    }
  }

  private validateBackup(): void {
    if (!existsSync(this.backupPath) || statSync(this.backupPath).size === 0) {
      throw new Error(
        "initialized portable witness recovery backup is missing",
      );
    }
    const backup = new DatabaseSync(this.backupPath, { readOnly: true });
    try {
      quickCheck(backup, "portable witness recovery backup");
      const row = backup
        .prepare("SELECT version FROM witness_snapshot WHERE cluster_id = ?")
        .get(this.clusterId) as { version: number } | undefined;
      if (!row) {
        throw new Error(
          "portable witness recovery backup has no configured cluster state",
        );
      }
    } finally {
      backup.close();
    }
  }

  private claimLease(): void {
    const now = this.now();
    const expires = now + this.leaseDurationMs;
    this.database.exec("BEGIN IMMEDIATE");
    try {
      const result = this.database
        .prepare(
          `INSERT INTO witness_process_lease
             (cluster_id,owner_token,lease_expires_at,acquired_at)
           VALUES(?,?,?,?)
           ON CONFLICT(cluster_id) DO UPDATE SET
             owner_token=excluded.owner_token,
             lease_expires_at=excluded.lease_expires_at,
             acquired_at=excluded.acquired_at
           WHERE witness_process_lease.lease_expires_at <= ?`,
        )
        .run(
          this.clusterId,
          this.ownerToken,
          expires,
          new Date(now).toISOString(),
          now,
        );
      if (result.changes !== 1) {
        throw new Error(
          "another portable witness process holds the singleton storage lease",
        );
      }
      this.database.exec("COMMIT");
    } catch (error) {
      this.database.exec("ROLLBACK");
      throw error;
    }
  }

  private refreshLease(inTransaction = false): void {
    if (this.closed) return;
    const result = this.database
      .prepare(
        `UPDATE witness_process_lease
            SET lease_expires_at=?
          WHERE cluster_id=? AND owner_token=?`,
      )
      .run(
        this.now() + this.leaseDurationMs,
        this.clusterId,
        this.ownerToken,
      );
    if (result.changes !== 1) {
      throw new Error(
        "portable witness singleton storage lease was lost to another process",
      );
    }
    if (!inTransaction) this.assertStorageHealthy();
  }

  private writeRecoveryArtifacts(): void {
    this.database.exec("PRAGMA wal_checkpoint(TRUNCATE)");
    const backupTemporary = `${this.backupPath}.${this.ownerToken}.tmp`;
    const sentinelTemporary = `${this.sentinelPath}.${this.ownerToken}.tmp`;
    try {
      copyFileSync(this.databasePath, backupTemporary);
      chmodSync(backupTemporary, 0o600);
      const backup = new DatabaseSync(backupTemporary, { readOnly: true });
      try {
        quickCheck(backup, "new portable witness recovery backup");
        const row = backup
          .prepare("SELECT version FROM witness_snapshot WHERE cluster_id = ?")
          .get(this.clusterId) as { version: number } | undefined;
        if (!row || Number(row.version) !== this.version) {
          throw new Error(
            "new portable witness recovery backup is stale or incomplete",
          );
        }
      } finally {
        backup.close();
      }
      renameSync(backupTemporary, this.backupPath);
      writeFileSync(
        sentinelTemporary,
        `${JSON.stringify({
          schemaVersion: "execution-fabric-witness-bootstrap/v1",
          clusterId: this.clusterId,
          initializedAt: new Date(this.now()).toISOString(),
          database: this.databasePath,
          backup: this.backupPath,
        } satisfies BootstrapSentinel)}\n`,
        { mode: 0o600 },
      );
      renameSync(sentinelTemporary, this.sentinelPath);
    } finally {
      for (const path of [backupTemporary, sentinelTemporary]) {
        try {
          unlinkSync(path);
        } catch {
          // Atomic rename normally consumed it.
        }
      }
    }
  }

  private assertStorageHealthy(): void {
    if (this.closed) throw new Error("portable witness store is closed");
    if (this.storageFailure) throw this.storageFailure;
  }

  protected override didMutate(): void {
    this.assertStorageHealthy();
    const snapshot = this.exportSnapshot();
    const pendingAudit = structuredClone(snapshot.audit);
    snapshot.audit = [];
    const payload = JSON.stringify(snapshot);
    const previousVersion = this.version;
    try {
      this.database.exec("BEGIN IMMEDIATE");
      this.refreshLease(true);
      const current = this.database
        .prepare(
          "SELECT version FROM witness_snapshot WHERE cluster_id = ?",
        )
        .get(this.clusterId) as { version: number } | undefined;
      if (!current) {
        if (this.version !== 0 || !this.bootstrapPending) {
          throw new Error(
            "portable witness state disappeared after initialization",
          );
        }
        this.database
          .prepare(
            `INSERT INTO witness_snapshot
              (cluster_id, version, payload, updated_at)
             VALUES (?, 1, ?, ?)`,
          )
          .run(this.clusterId, payload, new Date(this.now()).toISOString());
        this.version = 1;
      } else {
        if (Number(current.version) !== this.version) {
          throw new Error(
            "portable witness local state version is stale; refusing authority overwrite",
          );
        }
        const nextVersion = this.version + 1;
        const result = this.database
          .prepare(
            `UPDATE witness_snapshot
                SET version = ?, payload = ?, updated_at = ?
              WHERE cluster_id = ? AND version = ?`,
          )
          .run(
            nextVersion,
            payload,
            new Date(this.now()).toISOString(),
            this.clusterId,
            this.version,
          );
        if (result.changes !== 1) {
          throw new Error(
            "portable witness state version changed concurrently",
          );
        }
        this.version = nextVersion;
      }
      const insertAudit = this.database.prepare(
        `INSERT OR IGNORE INTO witness_audit
          (cluster_id, occurred_at, audit_id, payload)
         VALUES (?, ?, ?, ?)`,
      );
      for (const item of pendingAudit) {
        insertAudit.run(
          this.clusterId,
          item.occurredAt,
          item.auditId,
          JSON.stringify(item),
        );
      }
      this.database.exec("COMMIT");
      this.lastPersistedSnapshot = structuredClone(snapshot);
      this.audit.splice(0, this.audit.length);
    } catch (error) {
      try {
        this.database.exec("ROLLBACK");
      } catch {
        // Preserve the first storage error.
      }
      this.storageFailure =
        error instanceof Error ? error : new Error(String(error));
      this.version = previousVersion;
      this.restoreSnapshot(this.lastPersistedSnapshot);
      throw this.storageFailure;
    }
    try {
      this.writeRecoveryArtifacts();
    } catch (error) {
      this.storageFailure =
        error instanceof Error ? error : new Error(String(error));
      throw this.storageFailure;
    }
  }

  override async ready(): Promise<void> {
    this.assertStorageHealthy();
    this.refreshLease();
    await super.ready();
    quickCheck(this.database, "portable witness database");
    const row = this.database
      .prepare("SELECT version FROM witness_snapshot WHERE cluster_id = ?")
      .get(this.clusterId) as { version: number } | undefined;
    if (!row || Number(row.version) !== this.version) {
      throw new Error("portable witness state readback does not match memory");
    }
  }

  override async close(): Promise<void> {
    if (this.closed) return;
    clearInterval(this.leaseTimer);
    try {
      this.database
        .prepare(
          "DELETE FROM witness_process_lease WHERE cluster_id=? AND owner_token=?",
        )
        .run(this.clusterId, this.ownerToken);
    } finally {
      this.closed = true;
      this.database.close();
    }
  }

  override async listAudit(limit: number): Promise<AuditRecord[]> {
    this.assertStorageHealthy();
    const rows = this.database
      .prepare(
        `SELECT payload FROM witness_audit WHERE cluster_id = ?
         ORDER BY occurred_at DESC, audit_id DESC LIMIT ?`,
      )
      .all(this.clusterId, limit) as Array<{ payload: string }>;
    return rows.map((row) => JSON.parse(String(row.payload)) as AuditRecord);
  }

  override async getState(): Promise<LeadershipState> {
    this.assertStorageHealthy();
    return super.getState();
  }

  override async getPromotion(
    promotionId: string,
  ): Promise<PromotionReceipt | null> {
    this.assertStorageHealthy();
    return super.getPromotion(promotionId);
  }

  override async listCandidates(): Promise<CandidateRecord[]> {
    this.assertStorageHealthy();
    return super.listCandidates();
  }

  override async getConfigDigestRotation(
    rotationId: string,
  ): Promise<ConfigDigestRotationReceipt | null> {
    this.assertStorageHealthy();
    return super.getConfigDigestRotation(rotationId);
  }

  override async getConfigDigestRotationAbort(
    rotationId: string,
  ): Promise<ConfigDigestRotationAbortReceipt | null> {
    this.assertStorageHealthy();
    return super.getConfigDigestRotationAbort(rotationId);
  }

  override async getConfigDigestRotationPreparation(
    rotationId: string,
  ): Promise<ConfigDigestRotationPreparation | null> {
    this.assertStorageHealthy();
    return super.getConfigDigestRotationPreparation(rotationId);
  }

  override async listConfigDigestRotationPreparations(): Promise<
    ConfigDigestRotationPreparation[]
  > {
    this.assertStorageHealthy();
    return super.listConfigDigestRotationPreparations();
  }

  override async getFailbackPlan(
    tokenHash: string,
  ): Promise<FailbackPlan | null> {
    this.assertStorageHealthy();
    return super.getFailbackPlan(tokenHash);
  }
}
