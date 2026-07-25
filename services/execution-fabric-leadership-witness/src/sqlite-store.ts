import { chmodSync, mkdirSync } from "node:fs";
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
} from "./contracts.js";
import {
  InMemoryWitnessStore,
  type WitnessStoreSnapshot,
} from "./store.js";

type SnapshotRow = {
  version: number;
  payload: string;
};

function snapshotFromJson(payload: string): WitnessStoreSnapshot {
  const decoded: unknown = JSON.parse(payload);
  if (
    typeof decoded !== "object" ||
    decoded === null ||
    !("schemaVersion" in decoded) ||
    decoded.schemaVersion !== "execution-fabric-witness-store/v1"
  ) {
    throw new Error("portable witness state has an unsupported schema");
  }
  const record = decoded as Record<string, unknown>;
  for (const field of [
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

/**
 * Durable, provider-neutral witness storage for a singleton independent host.
 *
 * Every conditional decision is still made by InMemoryWitnessStore in one
 * synchronous section. Before the request can return, the complete state and
 * immutable audit stream are committed under SQLite BEGIN IMMEDIATE with WAL
 * and synchronous=FULL. The deployment contract permits exactly one witness
 * container for this database; a second container is a configuration error,
 * not a quorum.
 */
export class SqliteWitnessStore extends InMemoryWitnessStore {
  private readonly database: DatabaseSync;
  private version = 0;
  private storageFailure?: Error;
  private lastPersistedSnapshot: WitnessStoreSnapshot = {
    schemaVersion: "execution-fabric-witness-store/v1",
    candidates: [],
    plans: [],
    configRotations: [],
    configRotationAborts: [],
    configRotationPreparations: [],
    audit: [],
  };

  constructor(
    databasePath: string,
    private readonly clusterId: string,
  ) {
    super();
    mkdirSync(dirname(databasePath), { recursive: true, mode: 0o700 });
    this.database = new DatabaseSync(databasePath);
    chmodSync(databasePath, 0o600);
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
    `);
    const row = this.database
      .prepare(
        "SELECT version, payload FROM witness_snapshot WHERE cluster_id = ?",
      )
      .get(clusterId) as SnapshotRow | undefined;
    if (row) {
      this.version = Number(row.version);
      this.lastPersistedSnapshot = snapshotFromJson(String(row.payload));
      this.restoreSnapshot(this.lastPersistedSnapshot);
    }
  }

  private assertStorageHealthy(): void {
    if (this.storageFailure) throw this.storageFailure;
  }

  protected override didMutate(): void {
    if (this.storageFailure) throw this.storageFailure;
    const snapshot = this.exportSnapshot();
    const pendingAudit = structuredClone(snapshot.audit);
    snapshot.audit = [];
    const payload = JSON.stringify(snapshot);
    const previousVersion = this.version;
    try {
      this.database.exec("BEGIN IMMEDIATE");
      const current = this.database
        .prepare(
          "SELECT version FROM witness_snapshot WHERE cluster_id = ?",
        )
        .get(this.clusterId) as { version: number } | undefined;
      if (!current) {
        this.database
          .prepare(
            `INSERT INTO witness_snapshot
              (cluster_id, version, payload, updated_at)
             VALUES (?, 1, ?, ?)`,
          )
          .run(this.clusterId, payload, new Date().toISOString());
        this.version = 1;
      } else {
        const nextVersion = Number(current.version) + 1;
        const result = this.database
          .prepare(
            `UPDATE witness_snapshot
                SET version = ?, payload = ?, updated_at = ?
              WHERE cluster_id = ? AND version = ?`,
          )
          .run(
            nextVersion,
            payload,
            new Date().toISOString(),
            this.clusterId,
            Number(current.version),
          );
        if (result.changes !== 1) {
          throw new Error("portable witness state version changed concurrently");
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
        // Preserve the first storage error. Readiness will remain failed.
      }
      this.storageFailure =
        error instanceof Error ? error : new Error(String(error));
      this.version = previousVersion;
      this.restoreSnapshot(this.lastPersistedSnapshot);
      throw this.storageFailure;
    }
  }

  override async ready(): Promise<void> {
    this.assertStorageHealthy();
    await super.ready();
    const row = this.database
      .prepare(
        "SELECT version FROM witness_snapshot WHERE cluster_id = ?",
      )
      .get(this.clusterId) as { version: number } | undefined;
    if (!row || Number(row.version) !== this.version) {
      throw new Error("portable witness state readback does not match memory");
    }
  }

  override async listAudit(limit: number): Promise<AuditRecord[]> {
    this.assertStorageHealthy();
    const rows = this.database
      .prepare(
        `SELECT payload
           FROM witness_audit
          WHERE cluster_id = ?
          ORDER BY occurred_at DESC, audit_id DESC
          LIMIT ?`,
      )
      .all(this.clusterId, limit) as Array<{ payload: string }>;
    return rows.map((row) => JSON.parse(String(row.payload)) as AuditRecord);
  }

  override async getState(): Promise<LeadershipState> {
    this.assertStorageHealthy();
    return super.getState();
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

  override async getFailbackPlan(tokenHash: string): Promise<FailbackPlan | null> {
    this.assertStorageHealthy();
    return super.getFailbackPlan(tokenHash);
  }
}
