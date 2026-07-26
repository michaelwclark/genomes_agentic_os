import { createHash, verify } from "node:crypto";
import { readFileSync } from "node:fs";
import { z } from "zod";
import type { LedgerPort } from "./ledger.js";
import type { PostgresReplicationSnapshot } from "./postgres-replication.js";
import type { PostgresMutationDurabilitySnapshot } from "./postgres-replication.js";

const signedLeadershipSchema = z.object({
  v: z.literal(2),
  cluster: z.string().min(1),
  leader: z.string().min(1),
  epoch: z.number().int().min(1),
  receiptId: z.string().min(1),
  configDigest: z.string().regex(/^[a-f0-9]{64}$/),
  issuedAt: z.string().datetime(),
  expiresAt: z.string().datetime(),
  authorityMode: z
    .enum(["synchronous", "degraded_primary", "standalone_primary"])
    .default("synchronous"),
  degradedUntil: z.string().datetime().nullable().default(null),
});

const witnessStatusSchema = z.object({
  apiVersion: z.literal("execution-fabric-leadership/v1"),
  clusterId: z.string().min(1),
  currentLeader: z.string().min(1),
  fabricEpoch: z.number().int().min(1),
  configDigest: z.string().regex(/^[a-f0-9]{64}$/),
  leadershipToken: z.string().min(1),
});

const transferReceiptSchema = z.object({
  receiptId: z.string().min(1),
  currentLeader: z.string().min(1),
  fabricEpoch: z.number().int().min(1),
  clusterId: z.string().min(1),
  fenceToken: z.string().min(1),
});

const configRotationPreparationProofSchema = z
  .object({
    v: z.literal(1),
    type: z.literal("config_digest_rotation_preparation"),
    clusterId: z.string().min(1),
    rotationId: z.string().uuid(),
    expectedLeader: z.string().min(1),
    expectedEpoch: z.number().int().min(1),
    expectedCurrentDigest: z.string().regex(/^[a-f0-9]{64}$/),
    candidateDigest: z.string().regex(/^[a-f0-9]{64}$/),
    issuedAt: z.string().datetime(),
    expiresAt: z.string().datetime(),
  })
  .strict();

export type LeadershipProof = z.infer<typeof signedLeadershipSchema>;
export type ConfigRotationPreparationProof = z.infer<
  typeof configRotationPreparationProofSchema
>;

export class LeadershipFencedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "LeadershipFencedError";
  }
}

export type LeadershipGuardConfig = {
  clusterId: string;
  hostId: string;
  witnessBaseUrl: string;
  witnessToken: string;
  witnessCandidateToken: string;
  witnessPublicKey: string;
  receiptPath?: string;
  refreshMs: number;
  recoveryHoldSeconds: number;
  degradedPolicy?: () => {
    allow_degraded_primary: boolean;
    max_duration_seconds: number;
    allowed_task_types: string[];
    allowed_effect_types: string[];
    allow_scheduler: boolean;
  };
  standalonePolicy?: () => {
    enabled: boolean;
    host_id: string;
  };
};

type Dependencies = {
  now?: () => Date;
  fetch?: typeof globalThis.fetch;
  readReceipt?: (path: string) => string;
  replicationProbe?: () => Promise<PostgresReplicationSnapshot>;
  durabilityProbe?: () => Promise<PostgresMutationDurabilitySnapshot>;
};

function digest(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

export function verifyLeadershipToken(
  token: string,
  publicKey: string,
): LeadershipProof {
  const [version, payload, signature, ...extra] = token.split(".");
  if (version !== "v2" || !payload || !signature || extra.length) {
    throw new LeadershipFencedError("leadership token has an invalid envelope");
  }
  if (
    !verify(
      null,
      Buffer.from(payload),
      publicKey,
      Buffer.from(signature, "base64url"),
    )
  ) {
    throw new LeadershipFencedError("leadership token signature is invalid");
  }
  let decoded: unknown;
  try {
    decoded = JSON.parse(Buffer.from(payload, "base64url").toString("utf8"));
  } catch {
    throw new LeadershipFencedError("leadership token payload is invalid");
  }
  return signedLeadershipSchema.parse(decoded);
}

export function verifyConfigRotationPreparationToken(
  token: string,
  publicKey: string,
): ConfigRotationPreparationProof {
  const [version, payload, signature, ...extra] = token.split(".");
  if (version !== "cpr1" || !payload || !signature || extra.length) {
    throw new LeadershipFencedError(
      "configuration rotation preparation token has an invalid envelope",
    );
  }
  if (
    !verify(
      null,
      Buffer.from(payload),
      publicKey,
      Buffer.from(signature, "base64url"),
    )
  ) {
    throw new LeadershipFencedError(
      "configuration rotation preparation signature is invalid",
    );
  }
  try {
    return configRotationPreparationProofSchema.parse(
      JSON.parse(Buffer.from(payload, "base64url").toString("utf8")),
    );
  } catch {
    throw new LeadershipFencedError(
      "configuration rotation preparation payload is invalid",
    );
  }
}

export class LeadershipGuard {
  private readonly now: () => Date;
  private readonly fetcher: typeof globalThis.fetch;
  private readonly readReceipt: (path: string) => string;
  private readonly replicationProbe: () => Promise<PostgresReplicationSnapshot>;
  private readonly durabilityProbe: () => Promise<PostgresMutationDurabilitySnapshot>;
  private proof: LeadershipProof | null = null;
  private lastVerifiedAt: string | null = null;
  private lastError: string | null = "leadership has not been verified";
  private recoveryHoldUntil: Date | null = null;
  private durability: PostgresMutationDurabilitySnapshot | null = null;
  private timer: NodeJS.Timeout | null = null;
  private refreshing = false;

  private degradedPolicy() {
    return (
      this.config.degradedPolicy?.() ?? {
        allow_degraded_primary: false,
        max_duration_seconds: 60,
        allowed_task_types: [],
        allowed_effect_types: [],
        allow_scheduler: false,
      }
    );
  }

  private standalonePolicy() {
    return (
      this.config.standalonePolicy?.() ?? {
        enabled: false,
        host_id: "",
      }
    );
  }

  private isStandaloneAuthority(): boolean {
    return this.proof?.authorityMode === "standalone_primary";
  }

  constructor(
    readonly config: LeadershipGuardConfig,
    private readonly ledger: LedgerPort,
    private readonly configDigest: () => string,
    dependencies: Dependencies = {},
  ) {
    this.now = dependencies.now ?? (() => new Date());
    this.fetcher = dependencies.fetch ?? globalThis.fetch;
    this.readReceipt = dependencies.readReceipt ?? ((path) => readFileSync(path, "utf8"));
    this.replicationProbe =
      dependencies.replicationProbe ??
      (async () => {
        throw new LeadershipFencedError(
          "PostgreSQL replication probe is not configured",
        );
      });
    this.durabilityProbe =
      dependencies.durabilityProbe ??
      (async () => {
        throw new LeadershipFencedError(
          "PostgreSQL mutation durability probe is not configured",
        );
      });
  }

  private async request(
    path: string,
    token: string,
    init?: RequestInit,
  ): Promise<unknown> {
    const response = await this.fetcher(
      `${this.config.witnessBaseUrl.replace(/\/$/, "")}${path}`,
      {
        ...init,
        signal: AbortSignal.timeout(Math.min(this.config.refreshMs, 10000)),
        headers: {
          authorization: `Bearer ${token}`,
          "content-type": "application/json",
          ...(init?.headers ?? {}),
        },
      },
    );
    if (!response.ok) {
      throw new LeadershipFencedError(
        `witness ${path} returned HTTP ${response.status}`,
      );
    }
    return response.json();
  }

  private loadTransferReceipt(): z.infer<typeof transferReceiptSchema> | null {
    if (!this.config.receiptPath) return null;
    try {
      return transferReceiptSchema.parse(
        JSON.parse(this.readReceipt(this.config.receiptPath)),
      );
    } catch (error) {
      if (
        error instanceof Error &&
        "code" in error &&
        (error as NodeJS.ErrnoException).code === "ENOENT"
      ) {
        return null;
      }
      throw new LeadershipFencedError(
        `leadership transfer receipt is invalid: ${
          error instanceof Error ? error.message : "unknown error"
        }`,
      );
    }
  }

  private validateProof(
    token: string,
    expected: {
      leader: string;
      epoch: number;
      configDigest: string;
      receiptId?: string;
    },
  ): LeadershipProof {
    const proof = verifyLeadershipToken(token, this.config.witnessPublicKey);
    if (
      proof.cluster !== this.config.clusterId ||
      proof.leader !== expected.leader ||
      proof.epoch !== expected.epoch ||
      proof.configDigest !== expected.configDigest ||
      (expected.receiptId !== undefined &&
        proof.receiptId !== expected.receiptId)
    ) {
      throw new LeadershipFencedError(
        "leadership token identity, cluster, epoch, or receipt does not match",
      );
    }
    if (new Date(proof.expiresAt).getTime() <= this.now().getTime()) {
      throw new LeadershipFencedError("leadership token has expired");
    }
    return proof;
  }

  async refresh(): Promise<void> {
    if (this.refreshing) return;
    this.refreshing = true;
    try {
      const policyDigest = this.configDigest();
      // Never publish a healthy candidate observation from a remote ping
      // alone. Local PostgreSQL reachability and policy validity are required.
      await this.ledger.ping();
      const replication = await this.replicationProbe();
      const durability = await this.durabilityProbe();
      await this.request(
        `/api/v1/admin/leadership/candidates/${encodeURIComponent(
          this.config.hostId,
        )}`,
        this.config.witnessCandidateToken,
        {
          method: "PUT",
          body: JSON.stringify({
            healthy: true,
            ...replication,
            configDigest: policyDigest,
            observedAt: this.now().toISOString(),
          }),
        },
      );
      const status = witnessStatusSchema.parse(
        await this.request(
          "/api/v1/admin/leadership/status",
          this.config.witnessToken,
        ),
      );
      if (
        status.clusterId !== this.config.clusterId ||
        status.currentLeader !== this.config.hostId ||
        status.configDigest !== policyDigest
      ) {
        throw new LeadershipFencedError(
          "witness does not name this host and configuration as current leader",
        );
      }
      const proof = this.validateProof(status.leadershipToken, {
        leader: status.currentLeader,
        epoch: status.fabricEpoch,
        configDigest: status.configDigest,
      });
      const databaseState = await this.ledger.systemSnapshot();
      const receipt = this.loadTransferReceipt();
      const transferBootstrap =
        status.fabricEpoch > databaseState.fabricEpoch;
      if (!this.recoveryHoldUntil && databaseState.leaderRecoveryHoldUntil) {
        this.recoveryHoldUntil = new Date(
          databaseState.leaderRecoveryHoldUntil,
        );
      }
      if (transferBootstrap && !receipt) {
        throw new LeadershipFencedError(
          "a signed transfer receipt is required to advance the PostgreSQL epoch",
        );
      }
      if (transferBootstrap && receipt) {
        if (
          receipt.clusterId !== this.config.clusterId ||
          receipt.currentLeader !== this.config.hostId ||
          receipt.fabricEpoch !== status.fabricEpoch
        ) {
          throw new LeadershipFencedError(
            "transfer receipt does not match current witness state",
          );
        }
        this.validateProof(receipt.fenceToken, {
          leader: receipt.currentLeader,
          epoch: receipt.fabricEpoch,
          configDigest: status.configDigest,
          receiptId: receipt.receiptId,
        });
        if (!this.recoveryHoldUntil) {
          this.recoveryHoldUntil = new Date(
            this.now().getTime() +
              this.config.recoveryHoldSeconds * 1000,
          );
        }
      }
      await this.ledger.activateLeadership({
        clusterId: this.config.clusterId,
        leaderHostId: this.config.hostId,
        fabricEpoch: proof.epoch,
        receiptId: proof.receiptId,
        fenceDigest: digest(status.leadershipToken),
        leaseExpiresAt: proof.expiresAt,
        recoveryHoldUntil:
          this.recoveryHoldUntil?.toISOString() ?? null,
      });
      this.durability = durability;
      this.proof = proof;
      this.lastVerifiedAt = this.now().toISOString();
      this.lastError = null;
    } catch (error) {
      this.lastError =
        error instanceof Error ? error.message : "unknown leadership failure";
      throw error;
    } finally {
      this.refreshing = false;
    }
  }

  async start(): Promise<void> {
    await this.refresh();
    this.timer = setInterval(() => {
      void this.refresh().catch(() => undefined);
    }, this.config.refreshMs);
    this.timer.unref();
  }

  stop(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.proof = null;
    this.durability = null;
    this.lastError = "leadership guard stopped";
  }

  assertMutation(): void {
    if (!this.proof) {
      throw new LeadershipFencedError(this.lastError ?? "leadership is unverified");
    }
    if (this.proof.leader !== this.config.hostId) {
      throw new LeadershipFencedError("this host is not the witnessed leader");
    }
    if (this.proof.configDigest !== this.configDigest()) {
      throw new LeadershipFencedError(
        "local policy digest differs from the signed witness proof",
      );
    }
    if (new Date(this.proof.expiresAt).getTime() <= this.now().getTime()) {
      this.lastError = "leadership proof expired before witness renewal";
      throw new LeadershipFencedError(this.lastError);
    }
    if (
      this.recoveryHoldUntil &&
      this.recoveryHoldUntil.getTime() > this.now().getTime()
    ) {
      throw new LeadershipFencedError(
        `leadership recovery hold remains active until ${this.recoveryHoldUntil.toISOString()}`,
      );
    }
    if (this.durability?.mutationDurabilityReady) return;
    if (this.proof.authorityMode === "standalone_primary") {
      const standalone = this.standalonePolicy();
      if (
        !standalone.enabled ||
        standalone.host_id !== this.config.hostId ||
        this.proof.degradedUntil !== null
      ) {
        throw new LeadershipFencedError(
          "standalone-primary authority requires exact canonical policy opt-in for this host",
        );
      }
      if (!this.durability?.standalonePrimaryDurabilityReady) {
        throw new LeadershipFencedError(
          "standalone-primary PostgreSQL durability requires a local primary, synchronous_commit=on or local, no synchronous standbys, fsync=on, full_page_writes=on, and archive_mode=on",
        );
      }
      return;
    }
    const degradedPolicy = this.degradedPolicy();
    if (
      this.proof.authorityMode !== "degraded_primary" ||
      !this.proof.degradedUntil ||
      !degradedPolicy.allow_degraded_primary
    ) {
      throw new LeadershipFencedError(
        "PostgreSQL mutation durability is not ready and degraded-primary authority is not enabled",
      );
    }
    if (
      new Date(this.proof.degradedUntil).getTime() <= this.now().getTime() ||
      new Date(this.proof.degradedUntil).getTime() -
        new Date(this.proof.issuedAt).getTime() >
        degradedPolicy.max_duration_seconds * 1000
    ) {
      throw new LeadershipFencedError(
        "degraded-primary authority expired or exceeds canonical policy",
      );
    }
    if (!this.durability?.degradedPrimaryDurabilityReady) {
      throw new LeadershipFencedError(
        "degraded-primary PostgreSQL durability requires synchronous_commit=on, fsync=on, full_page_writes=on, and archive_mode=on",
      );
    }
  }

  authorizePolicyRotation(input: {
    rotationId: string;
    preparationToken: string;
    expectedCurrentDigest: string;
    candidateDigest: string;
  }): ConfigRotationPreparationProof {
    this.assertMutation();
    if (!this.proof) {
      throw new LeadershipFencedError("leadership is unverified");
    }
    const preparation = verifyConfigRotationPreparationToken(
      input.preparationToken,
      this.config.witnessPublicKey,
    );
    if (
      preparation.clusterId !== this.config.clusterId ||
      preparation.rotationId !== input.rotationId ||
      preparation.expectedLeader !== this.config.hostId ||
      preparation.expectedEpoch !== this.proof.epoch ||
      preparation.expectedCurrentDigest !== input.expectedCurrentDigest ||
      preparation.candidateDigest !== input.candidateDigest
    ) {
      throw new LeadershipFencedError(
        "configuration rotation preparation is not bound to this leader, epoch, or digest transition",
      );
    }
    if (new Date(preparation.expiresAt).getTime() <= this.now().getTime()) {
      throw new LeadershipFencedError(
        "configuration rotation preparation has expired",
      );
    }
    return preparation;
  }

  assertTaskMutation(taskType: string): void {
    this.assertMutation();
    if (this.isStandaloneAuthority()) return;
    if (
      !this.durability?.mutationDurabilityReady &&
      !this.degradedPolicy().allowed_task_types.includes(taskType)
    ) {
      throw new LeadershipFencedError(
        `task type ${taskType} is fenced during degraded-primary authority`,
      );
    }
  }

  assertEffectMutation(effectTypes: string[]): void {
    this.assertMutation();
    if (this.isStandaloneAuthority()) return;
    if (!this.durability?.mutationDurabilityReady) {
      const allowed = new Set(
        this.degradedPolicy().allowed_effect_types,
      );
      const rejected = effectTypes.find((effectType) => !allowed.has(effectType));
      if (rejected) {
        throw new LeadershipFencedError(
          `effect type ${rejected} is fenced during degraded-primary authority`,
        );
      }
    }
  }

  assertSchedulerMutation(): void {
    this.assertMutation();
    if (this.isStandaloneAuthority()) return;
    if (
      !this.durability?.mutationDurabilityReady &&
      !this.degradedPolicy().allow_scheduler
    ) {
      throw new LeadershipFencedError(
        "scheduler is fenced during degraded-primary authority",
      );
    }
  }

  snapshot(): Record<string, unknown> {
    let state = "fenced";
    try {
      this.assertMutation();
      state = "active";
    } catch {
      if (
        this.recoveryHoldUntil &&
        this.recoveryHoldUntil.getTime() > this.now().getTime()
      ) {
        state = "recovery_hold";
      }
    }
    return {
      state,
      clusterId: this.config.clusterId,
      hostId: this.config.hostId,
      fabricEpoch: this.proof?.epoch ?? null,
      receiptId: this.proof?.receiptId ?? null,
      proofExpiresAt: this.proof?.expiresAt ?? null,
      authorityMode: this.proof?.authorityMode ?? null,
      degradedUntil: this.proof?.degradedUntil ?? null,
      lastVerifiedAt: this.lastVerifiedAt,
      recoveryHoldUntil: this.recoveryHoldUntil?.toISOString() ?? null,
      durability: this.durability,
      lastError: this.lastError,
    };
  }
}
