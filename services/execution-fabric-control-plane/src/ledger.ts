import { createHash, randomUUID } from "node:crypto";
import type pg from "pg";
import type {
  Assignment,
  AttemptCompletion,
  AttemptFailure,
  ClaimRequest,
  EffectAssignment,
  EffectClaim,
  EffectDelivery,
  EffectFailure,
  ReconcileReceipt,
  TaskAdmission,
  TaskRecord,
  PolicyReloadOperatorOverride,
  WorkerHeartbeat,
  WorkerRegistration,
  WorkerRegistrationReceipt,
} from "./contracts.js";
import { roleHealthSnapshot, type RoleHealthSnapshot } from "./roles.js";
import type {
  NormalizedTaskAdmission,
  PolicySnapshot,
  QueuePolicy,
  WorkerPoolPolicy,
} from "./policy.js";

export class ConflictError extends Error {}
export class FencedError extends Error {}
export class NotFoundError extends Error {}

export type QueueSnapshot = {
  queue: string;
  queued: number;
  ready: number;
  delayed: number;
  retrying: number;
  running: number;
  succeeded: number;
  failed: number;
  deadLettered: number;
  cancelled: number;
  completedLastHour: number;
  failedLastHour: number;
  throughputPerHour: number;
  failureRateLastHour: number;
  oldestQueuedAt: string | null;
  oldestReadyAgeSeconds: number | null;
};

export type WorkerSessionSnapshot = {
  sessionId: string;
  status: "active" | "ended" | "expired" | "fenced";
  fabricEpoch: number;
  startedAt: string;
  lastHeartbeatAt: string;
  leaseExpiresAt: string;
  endedAt: string | null;
  endReason: string | null;
};

export type WorkerSnapshot = {
  workerId: string;
  hostId: string;
  poolId: string;
  provider: string;
  queues: string[];
  capabilities: string[];
  maxConcurrency: number;
  running: number;
  state: "online" | "offline";
  leaseExpiresAt: string;
  lastHeartbeatAt: string;
  configFingerprint: string;
  currentSessionId: string | null;
  currentSessionStartedAt: string | null;
  sessionHistory: WorkerSessionSnapshot[];
};

export type AttemptSnapshot = {
  attemptId: string;
  runId: string;
  attemptNumber: number;
  status: string;
  workerId: string;
  hostId: string | null;
  workerSessionId: string | null;
  fabricEpoch: number;
  leaseDurationSeconds: number;
  leaseExpiresAt: string;
  startedAt: string;
  finishedAt: string | null;
  result: Record<string, unknown> | null;
  errorCode: string | null;
  errorSummary: string | null;
};

export type RunSnapshot = {
  taskId: string;
  namespace: string;
  queue: string;
  taskType: string;
  status: string;
  schedulingClass: "interactive" | "background";
  priority: number;
  maxAttempts: number;
  attemptCount: number;
  workerId: string | null;
  leaseExpiresAt: string | null;
  availableAt: string;
  createdAt: string;
  completedAt: string | null;
  lastErrorCode: string | null;
  lastErrorSummary: string | null;
  attempts: AttemptSnapshot[];
  effects: Array<Record<string, unknown>>;
  artifacts: Array<Record<string, unknown>>;
  updatedAt: string;
};

export type AdmissionConstraints = {
  configFingerprint: string;
  queue: QueuePolicy;
  pool: WorkerPoolPolicy;
};

export type WorkerConstraints = {
  configFingerprint: string;
  pool: WorkerPoolPolicy;
};

export type ClaimConstraints = WorkerConstraints & {
  queue: QueuePolicy;
  globalMaxRunning: number;
  providerMaxRunning: number;
  reservedInteractiveSlots: number;
  maxInteractiveRunning: number;
  namespaceLimits: Record<string, number>;
  hostLimits: Record<string, number>;
  namespaceWeights: Record<string, number>;
  priorityAgingIntervalSeconds: number;
  priorityAgingBoost: number;
  priorityAgingMaxBoost: number;
};

export type SystemSnapshot = {
  fabricEpoch: number;
  leaderHostId: string | null;
  leaderLeaseExpiresAt: string | null;
  leadershipClusterId: string | null;
  leadershipReceiptId: string | null;
  leadershipFenceDigest: string | null;
  leaderRecoveryHoldUntil: string | null;
  databasePolicyFingerprint: string | null;
  effects: Record<string, number>;
  eventSequence: number;
  roleHealth?: RoleHealthSnapshot[];
};

export type LeadershipActivation = {
  clusterId: string;
  leaderHostId: string;
  fabricEpoch: number;
  receiptId: string;
  fenceDigest: string;
  leaseExpiresAt: string;
  recoveryHoldUntil: string | null;
};

export type ConfigReloadReceipt = {
  schemaVersion: "execution-fabric-config-reload-receipt/v1";
  receiptId: string;
  rotationId: string;
  preparationTokenHash: string;
  expectedCurrentFingerprint: string;
  expectedCandidateFingerprint: string;
  appliedFingerprint: string;
  fabricEpoch: number;
  hostId: string;
  authorizedAt?: string;
  appliedAt: string;
  decision: "standalone_policy_override_applied" | "policy_reload_applied";
  recoveryAction: string;
  operatorOverride?: PolicyReloadOperatorOverride;
};

export interface LedgerPort {
  admitTask(
    input: NormalizedTaskAdmission,
    constraints: AdmissionConstraints,
  ): Promise<{ task: TaskRecord; admitted: boolean }>;
  getTask(id: string): Promise<TaskRecord | null>;
  taskIdForAttempt(attemptId: string): Promise<string>;
  registerWorker(
    input: WorkerRegistration,
    constraints: WorkerConstraints,
  ): Promise<WorkerRegistrationReceipt>;
  heartbeat(workerId: string, input: WorkerHeartbeat): Promise<WorkerRegistrationReceipt>;
  claim(input: ClaimRequest, constraints: ClaimConstraints): Promise<Assignment | null>;
  complete(attemptId: string, input: AttemptCompletion): Promise<TaskRecord>;
  fail(attemptId: string, input: AttemptFailure): Promise<TaskRecord>;
  claimEffects(input: EffectClaim, leaseSeconds: number): Promise<EffectAssignment[]>;
  deliverEffect(effectId: string, input: EffectDelivery): Promise<void>;
  failEffect(effectId: string, input: EffectFailure): Promise<void>;
  reconcileExpired(): Promise<
    Omit<ReconcileReceipt, "deliveriesPublished" | "occurredAt">
  >;
  listPublishable(limit: number): Promise<TaskRecord[]>;
  markPublished(taskId: string): Promise<void>;
  queueSnapshot(): Promise<QueueSnapshot[]>;
  workerSnapshot(): Promise<WorkerSnapshot[]>;
  runSnapshot(limit: number): Promise<RunSnapshot[]>;
  systemSnapshot(): Promise<SystemSnapshot>;
  activatePolicy(fingerprint: string): Promise<void>;
  activatePolicyReload(input: {
    rotationId: string;
    preparationTokenHash: string;
    authorizationIssuedAt?: string;
    authorizationExpiresAt: string;
    expectedEpoch: number;
    expectedCurrentFingerprint: string;
    expectedCandidateFingerprint: string;
    operatorOverride?: PolicyReloadOperatorOverride;
  }): Promise<ConfigReloadReceipt>;
  activateLeadership(input: LeadershipActivation): Promise<void>;
  ping(): Promise<void>;
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(",")}]`;
  }
  if (value !== null && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, child]) => `${JSON.stringify(key)}:${canonicalJson(child)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function requestHash(input: TaskAdmission): string {
  return createHash("sha256").update(canonicalJson(input)).digest("hex");
}

function iso(value: Date | string): string {
  return new Date(value).toISOString();
}

function taskFromRow(row: Record<string, unknown>): TaskRecord {
  return {
    id: String(row.id),
    namespace: String(row.namespace),
    queue: String(row.queue_name),
    taskType: String(row.task_type),
    schedulingClass:
      row.scheduling_class === "interactive" ? "interactive" : "background",
    payload: (row.payload ?? {}) as Record<string, unknown>,
    requiredCapabilities: (row.required_capabilities ?? []) as string[],
    priority: Number(row.priority),
    status: String(row.status),
    maxAttempts: Number(row.max_attempts),
    attemptCount: Number(row.attempt_count),
    availableAt: iso(row.available_at as string),
    createdAt: iso(row.created_at as string),
  };
}

export class PostgresLedger implements LedgerPort {
  constructor(
    private readonly pool: pg.Pool,
    private readonly workerTtlSeconds: number,
    private readonly hostId?: string,
  ) {}

  private async transaction<T>(
    callback: (client: pg.PoolClient) => Promise<T>,
    requireLeadership = true,
  ): Promise<T> {
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      if (requireLeadership && this.hostId) {
        await this.assertDatabaseLeadership(client);
      }
      const result = await callback(client);
      await client.query("COMMIT");
      return result;
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  }

  async admitTask(
    input: NormalizedTaskAdmission,
    constraints: AdmissionConstraints,
  ): Promise<{ task: TaskRecord; admitted: boolean }> {
    const hash = requestHash(input);
    return this.transaction(async (client) => {
      await this.lockPolicyOperation(client, constraints.configFingerprint);
      const existing = await client.query(
        `SELECT * FROM fabric_tasks
         WHERE namespace = $1 AND idempotency_key = $2
         FOR UPDATE`,
        [input.namespace, input.idempotencyKey],
      );
      if (existing.rowCount) {
        const row = existing.rows[0] as Record<string, unknown>;
        if (row.request_hash !== hash) {
          throw new ConflictError(
            "idempotency key already exists with a different request",
          );
        }
        return { task: taskFromRow(row), admitted: false };
      }
      const queued = await client.query<{ count: string }>(
        `SELECT count(*)::text AS count FROM fabric_tasks
         WHERE queue_name = $1 AND status = 'queued'`,
        [input.queue],
      );
      if (Number(queued.rows[0]?.count ?? 0) >= constraints.queue.concurrency.max_queued) {
        throw new ConflictError(
          `queue ${input.queue} reached max_queued ${constraints.queue.concurrency.max_queued}`,
        );
      }
      const id = randomUUID();
      const inserted = await client.query(
        `INSERT INTO fabric_tasks (
           id, namespace, queue_name, task_type, idempotency_key, request_hash,
           payload, required_capabilities, priority, status, max_attempts,
           provider, retry_backoff_seconds, config_fingerprint, available_at,
           scheduling_class
         ) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,$9,'queued',$10,
           $11,$12,$13,COALESCE($14::timestamptz,now()),$15)
         RETURNING *`,
        [
          id,
          input.namespace,
          input.queue,
          input.taskType,
          input.idempotencyKey,
          hash,
          JSON.stringify(input.payload),
          JSON.stringify(input.requiredCapabilities),
          input.priority,
          input.maxAttempts,
          constraints.pool.provider,
          constraints.pool.retry.backoff_seconds,
          constraints.configFingerprint,
          input.availableAt ?? null,
          input.schedulingClass,
        ],
      );
      await this.event(client, "task", id, "task.admitted", {
        namespace: input.namespace,
        queue: input.queue,
      });
      return {
        task: taskFromRow(inserted.rows[0] as Record<string, unknown>),
        admitted: true,
      };
    });
  }

  async getTask(id: string): Promise<TaskRecord | null> {
    const result = await this.pool.query("SELECT * FROM fabric_tasks WHERE id = $1", [
      id,
    ]);
    return result.rowCount
      ? taskFromRow(result.rows[0] as Record<string, unknown>)
      : null;
  }

  async taskIdForAttempt(attemptId: string): Promise<string> {
    const result = await this.pool.query<{ task_id: string }>(
      "SELECT task_id::text FROM fabric_attempts WHERE id=$1",
      [attemptId],
    );
    if (!result.rowCount) throw new NotFoundError("attempt not found");
    return String(result.rows[0]!.task_id);
  }

  async registerWorker(
    input: WorkerRegistration,
    constraints: WorkerConstraints,
  ): Promise<WorkerRegistrationReceipt> {
    const token = randomUUID();
    const sessionId = randomUUID();
    return this.transaction(async (client) => {
      await this.lockPolicyOperation(client, constraints.configFingerprint);
      const online = await client.query<{ count: string }>(
        `SELECT count(*)::text AS count FROM fabric_workers
         WHERE pool_id = $1 AND worker_id <> $2 AND lease_expires_at > now()`,
        [constraints.pool.id, input.workerId],
      );
      if (
        Number(online.rows[0]?.count ?? 0) >=
        constraints.pool.capacity.max_workers
      ) {
        throw new ConflictError(
          `worker pool ${constraints.pool.id} reached max_workers ${constraints.pool.capacity.max_workers}`,
        );
      }
      const state = await client.query<{ current_epoch: string }>(
        "SELECT current_epoch FROM fabric_state WHERE singleton = true",
      );
      const epoch = Number(state.rows[0]?.current_epoch ?? 1);
      await client.query(
        `UPDATE fabric_attempts SET lease_expires_at=now()
         WHERE status='running' AND worker_session_id IN (
           SELECT id FROM fabric_worker_sessions
           WHERE worker_id=$1 AND status='active'
         )`,
        [input.workerId],
      );
      await client.query(
        `UPDATE fabric_worker_sessions SET status='fenced',ended_at=now(),
           end_reason='re_registered'
         WHERE worker_id=$1 AND status='active'`,
        [input.workerId],
      );
      const result = await client.query(
        `INSERT INTO fabric_workers (
           worker_id, bootstrap_id, host_id, pool_id, provider, queues, capabilities,
           max_concurrency, metadata, registration_token, registered_epoch,
           config_fingerprint, lease_expires_at
         ) VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8,$9::jsonb,$10,$11,$12,
           now() + ($13 * interval '1 second'))
         ON CONFLICT (worker_id) DO UPDATE SET
           bootstrap_id = EXCLUDED.bootstrap_id,
           host_id = EXCLUDED.host_id,
           pool_id = EXCLUDED.pool_id,
           provider = EXCLUDED.provider,
           queues = EXCLUDED.queues,
           capabilities = EXCLUDED.capabilities,
           max_concurrency = EXCLUDED.max_concurrency,
           metadata = EXCLUDED.metadata,
           registration_token = EXCLUDED.registration_token,
           registered_epoch = EXCLUDED.registered_epoch,
           config_fingerprint = EXCLUDED.config_fingerprint,
           lease_expires_at = EXCLUDED.lease_expires_at,
           last_heartbeat_at = now(),
           updated_at = now()
         RETURNING worker_id, registration_token, lease_expires_at`,
        [
          input.workerId,
          input.bootstrapId,
          input.hostId,
          constraints.pool.id,
          constraints.pool.provider,
          JSON.stringify(input.queues),
          JSON.stringify(input.capabilities),
          input.maxConcurrency,
          JSON.stringify(input.metadata),
          token,
          epoch,
          constraints.configFingerprint,
          this.workerTtlSeconds,
        ],
      );
      const row = result.rows[0] as Record<string, unknown>;
      await client.query(
        `INSERT INTO fabric_worker_sessions(
           id,worker_id,bootstrap_id,registration_token,host_id,pool_id,provider,
           fabric_epoch,config_fingerprint,metadata,lease_expires_at
         ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11)`,
        [
          sessionId,
          input.workerId,
          input.bootstrapId,
          token,
          input.hostId,
          constraints.pool.id,
          constraints.pool.provider,
          epoch,
          constraints.configFingerprint,
          JSON.stringify(input.metadata),
          row.lease_expires_at,
        ],
      );
      await client.query(
        "UPDATE fabric_workers SET current_session_id=$2 WHERE worker_id=$1",
        [input.workerId, sessionId],
      );
      await this.event(client, "worker", input.workerId, "worker.registered", {
        hostId: input.hostId,
        sessionId,
      });
      return {
        workerId: String(row.worker_id),
        registrationToken: String(row.registration_token),
        leaseExpiresAt: iso(row.lease_expires_at as string),
        fabricEpoch: epoch,
      };
    });
  }

  async heartbeat(
    workerId: string,
    input: WorkerHeartbeat,
  ): Promise<WorkerRegistrationReceipt> {
    return this.transaction(async (client) => {
      const state = await client.query<{ current_epoch: string }>(
        "SELECT current_epoch FROM fabric_state WHERE singleton = true",
      );
      const epoch = Number(state.rows[0]?.current_epoch ?? 1);
      const result = await client.query(
        `UPDATE fabric_workers SET
           lease_expires_at = now() + ($3 * interval '1 second'),
           metadata = CASE WHEN $5::jsonb IS NULL THEN metadata
             ELSE metadata || jsonb_build_object(
               'artifactSpoolHealth',$5::jsonb
             ) END,
           last_heartbeat_at = now(), updated_at = now()
         WHERE worker_id = $1 AND registration_token = $2
           AND registered_epoch = $4
         RETURNING worker_id, registration_token, lease_expires_at`,
        [
          workerId,
          input.registrationToken,
          this.workerTtlSeconds,
          epoch,
          input.artifactSpoolHealth
            ? JSON.stringify(input.artifactSpoolHealth)
            : null,
        ],
      );
      if (!result.rowCount) {
        throw new FencedError("worker registration is stale or fenced");
      }
      const session = await client.query(
        `UPDATE fabric_worker_sessions SET last_heartbeat_at=now(),
           lease_expires_at=$4,
           metadata = CASE WHEN $5::jsonb IS NULL THEN metadata
             ELSE metadata || jsonb_build_object(
               'artifactSpoolHealth',$5::jsonb
             ) END
         WHERE id=(
           SELECT current_session_id FROM fabric_workers WHERE worker_id=$1
         ) AND worker_id=$1 AND registration_token=$2
           AND fabric_epoch=$3 AND status='active'`,
        [
          workerId,
          input.registrationToken,
          epoch,
          (result.rows[0] as Record<string, unknown>).lease_expires_at,
          input.artifactSpoolHealth
            ? JSON.stringify(input.artifactSpoolHealth)
            : null,
        ],
      );
      if (!session.rowCount) {
        throw new FencedError("worker session is stale or fenced");
      }
      if (input.activeAttemptIds.length) {
        await client.query(
          `UPDATE fabric_attempts
           SET lease_expires_at =
             now() + (lease_duration_seconds * interval '1 second')
           WHERE worker_id = $1 AND id = ANY($2::uuid[]) AND status = 'running'
             AND fabric_epoch = $3
             AND worker_session_id=(
               SELECT current_session_id FROM fabric_workers WHERE worker_id=$1
             )`,
          [workerId, input.activeAttemptIds, epoch],
        );
      }
      const row = result.rows[0] as Record<string, unknown>;
      return {
        workerId,
        registrationToken: String(row.registration_token),
        leaseExpiresAt: iso(row.lease_expires_at as string),
        fabricEpoch: epoch,
      };
    });
  }

  async claim(
    input: ClaimRequest,
    constraints: ClaimConstraints,
  ): Promise<Assignment | null> {
    return this.transaction(async (client) => {
      await this.lockPolicyOperation(client, constraints.configFingerprint);
      const worker = await client.query(
        `SELECT w.*, s.current_epoch
         FROM fabric_workers w CROSS JOIN fabric_state s
         WHERE w.worker_id = $1 AND w.registration_token = $2
           AND w.lease_expires_at > now()
           AND w.registered_epoch = s.current_epoch
           AND w.pool_id = $3
           AND w.config_fingerprint = $4
           AND s.singleton = true
         FOR UPDATE OF w`,
        [
          input.workerId,
          input.registrationToken,
          constraints.pool.id,
          constraints.configFingerprint,
        ],
      );
      if (!worker.rowCount) {
        throw new FencedError("worker registration is stale or fenced");
      }
      const workerRow = worker.rows[0] as Record<string, unknown>;
      const registeredQueues = workerRow.queues as string[];
      const eligibleQueues = input.queues.filter((queue) =>
        registeredQueues.includes(queue),
      );
      if (!eligibleQueues.length) return null;
      const registeredCapabilities = workerRow.capabilities as string[];
      const active = await client.query<{ count: string }>(
        `SELECT count(*)::text AS count FROM fabric_attempts
         WHERE worker_id = $1 AND status = 'running'`,
        [input.workerId],
      );
      if (Number(active.rows[0]?.count ?? 0) >= Number(workerRow.max_concurrency)) {
        return null;
      }
      // Capacity checks and the claim transition must be one serialized decision.
      // Row locks alone only protect a single worker and can oversubscribe global,
      // host, provider, or tenant limits when different workers claim concurrently.
      await client.query(
        "SELECT pg_advisory_xact_lock(hashtext('agentic-os-execution-fabric-capacity'))",
      );
      const hostId = String(workerRow.host_id);
      const hostMaxRunning = constraints.hostLimits[hostId];
      if (hostMaxRunning !== undefined) {
        const hostRunning = await client.query<{ count: string }>(
          `SELECT count(*)::text AS count
           FROM fabric_attempts a
           JOIN fabric_workers w ON w.worker_id=a.worker_id
           WHERE a.status='running' AND w.host_id=$1`,
          [hostId],
        );
        if (Number(hostRunning.rows[0]?.count ?? 0) >= hostMaxRunning) {
          return null;
        }
      }
      const task = await client.query(
        `SELECT t.* FROM fabric_tasks t
         WHERE t.status = 'queued' AND t.available_at <= now()
           AND t.queue_name = ANY($1::text[])
           AND t.required_capabilities <@ $2::jsonb
           AND (
             NOT ($3::jsonb ? t.namespace)
             OR (
               SELECT count(*) FROM fabric_tasks running
               WHERE running.status='running'
                 AND running.namespace=t.namespace
             ) < (($3::jsonb ->> t.namespace)::integer)
           )
         ORDER BY
           t.priority + LEAST(
             $7::integer,
             GREATEST(
               0,
               floor(
                 extract(epoch FROM (now() - t.created_at)) /
                 GREATEST($5::integer,1)
               )::integer * $6::integer
             )
           ) DESC,
           (
             SELECT count(*) + 1 FROM fabric_tasks running
             WHERE running.status='running'
               AND running.namespace=t.namespace
           )::numeric /
             COALESCE(NULLIF(($4::jsonb ->> t.namespace)::numeric,0),1)
             ASC,
           t.available_at,t.created_at,t.id
         FOR UPDATE SKIP LOCKED LIMIT 1`,
        [
          eligibleQueues,
          JSON.stringify(registeredCapabilities),
          JSON.stringify(constraints.namespaceLimits),
          JSON.stringify(constraints.namespaceWeights),
          constraints.priorityAgingIntervalSeconds,
          constraints.priorityAgingBoost,
          constraints.priorityAgingMaxBoost,
        ],
      );
      if (!task.rowCount) return null;
      const taskRow = task.rows[0] as Record<string, unknown>;
      const schedulingClass =
        taskRow.scheduling_class === "interactive" ? "interactive" : "background";
      const running = await client.query<{
        global_running: string;
        queue_running: string;
        provider_running: string;
        interactive_running: string;
      }>(
        `SELECT
           count(*) FILTER (WHERE status='running')::text AS global_running,
           count(*) FILTER (
             WHERE status='running' AND queue_name=$1
           )::text AS queue_running,
           count(*) FILTER (
             WHERE status='running' AND provider=$2
           )::text AS provider_running,
           count(*) FILTER (
             WHERE status='running' AND scheduling_class='interactive'
           )::text AS interactive_running
         FROM fabric_tasks`,
        [constraints.pool.queues[0], constraints.pool.provider],
      );
      const counts = running.rows[0];
      if (
        Number(counts?.global_running ?? 0) >= constraints.globalMaxRunning ||
        Number(counts?.queue_running ?? 0) >=
          constraints.queue.concurrency.max_running
      ) {
        return null;
      }
      if (
        schedulingClass === "background" &&
        Number(counts?.global_running ?? 0) >=
          constraints.globalMaxRunning - constraints.reservedInteractiveSlots
      ) {
        return null;
      }
      if (
        schedulingClass === "interactive" &&
        Number(counts?.interactive_running ?? 0) >=
          constraints.maxInteractiveRunning
      ) {
        return null;
      }
      if (
        Number(counts?.provider_running ?? 0) >= constraints.providerMaxRunning
      ) {
        return null;
      }
      const taskId = String(taskRow.id);
      const attemptNumber = Number(taskRow.attempt_count) + 1;
      const runId = randomUUID();
      const attemptId = randomUUID();
      const attemptRecoveryToken = randomUUID();
      const leaseToken = randomUUID();
      const epoch = Number(workerRow.current_epoch);
      await client.query(
        `INSERT INTO fabric_runs(id,task_id,run_number,status)
         VALUES($1,$2,$3,'running')`,
        [runId, taskId, attemptNumber],
      );
      const attempt = await client.query(
         `INSERT INTO fabric_attempts(
           id,task_id,run_id,worker_id,attempt_number,status,lease_token,
           fabric_epoch,lease_duration_seconds,lease_expires_at,worker_session_id,
           recovery_token
         ) VALUES($1,$2,$3,$4,$5,'running',$6,$7,
           $8::integer,now() + ($8::integer * interval '1 second'),$9,$10)
         RETURNING lease_expires_at`,
        [
          attemptId,
          taskId,
          runId,
          input.workerId,
          attemptNumber,
          leaseToken,
          epoch,
          constraints.pool.lease.timeout_seconds,
          workerRow.current_session_id,
          attemptRecoveryToken,
        ],
      );
      await client.query(
        `UPDATE fabric_tasks SET status='running', attempt_count=$2,
           delivery_published_at=NULL, updated_at=now() WHERE id=$1`,
        [taskId, attemptNumber],
      );
      await this.event(client, "task", taskId, "task.claimed", {
        workerId: input.workerId,
        attemptId,
        attemptNumber,
      }, epoch);
      return {
        attemptId,
        attemptRecoveryToken,
        task: taskFromRow({ ...taskRow, status: "running", attempt_count: attemptNumber }),
        leaseToken,
        leaseExpiresAt: iso(
          (attempt.rows[0] as Record<string, unknown>).lease_expires_at as string,
        ),
        fabricEpoch: epoch,
      };
    });
  }

  async complete(
    attemptId: string,
    input: AttemptCompletion,
  ): Promise<TaskRecord> {
    return this.finishAttempt(attemptId, input, true);
  }

  async fail(attemptId: string, input: AttemptFailure): Promise<TaskRecord> {
    return this.finishAttempt(attemptId, input, false);
  }

  private async finishAttempt(
    attemptId: string,
    input: AttemptCompletion | AttemptFailure,
    succeeded: boolean,
  ): Promise<TaskRecord> {
    return this.transaction(async (client) => {
      const attempt = await client.query(
        `SELECT a.*, t.max_attempts, t.retry_backoff_seconds,
           t.status AS task_status, s.current_epoch
         FROM fabric_attempts a
         JOIN fabric_tasks t ON t.id = a.task_id
         CROSS JOIN fabric_state s
         WHERE a.id = $1 AND s.singleton = true
         FOR UPDATE OF a, t`,
        [attemptId],
      );
      if (!attempt.rowCount) throw new NotFoundError("attempt not found");
      const row = attempt.rows[0] as Record<string, unknown>;
      if (
        row.status !== "running" ||
        row.worker_id !== input.workerId ||
        row.lease_token !== input.leaseToken ||
        Number(row.fabric_epoch) !== input.fabricEpoch ||
        Number(row.current_epoch) !== input.fabricEpoch ||
        new Date(row.lease_expires_at as string).getTime() <= Date.now()
      ) {
        throw new FencedError("attempt completion is stale, expired, or fenced");
      }
      const taskId = String(row.task_id);
      const runId = String(row.run_id);
      if (succeeded) {
        const completion = input as AttemptCompletion;
        await client.query(
          `UPDATE fabric_attempts SET status='succeeded',finished_at=now(),
             result=$2::jsonb WHERE id=$1`,
          [attemptId, JSON.stringify(completion.result)],
        );
        await client.query(
          "UPDATE fabric_runs SET status='succeeded',finished_at=now() WHERE id=$1",
          [runId],
        );
        const task = await client.query(
          `UPDATE fabric_tasks SET status='succeeded',result=$2::jsonb,
             completed_at=now(),updated_at=now()
           WHERE id=$1 RETURNING *`,
          [taskId, JSON.stringify(completion.result)],
        );
        for (const effect of completion.effects) {
          await client.query(
            `INSERT INTO fabric_effect_outbox(
               id,effect_key,task_id,attempt_id,effect_type,payload,fabric_epoch,
               max_attempts,base_backoff_seconds
             ) VALUES($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9)
            `,
            [
              randomUUID(),
              effect.effectKey,
              taskId,
              attemptId,
              effect.effectType,
              JSON.stringify(effect.payload),
              input.fabricEpoch,
              effect.maxAttempts,
              effect.baseBackoffSeconds,
            ],
          );
        }
        await this.event(client, "task", taskId, "task.succeeded", { attemptId }, input.fabricEpoch);
        return taskFromRow(task.rows[0] as Record<string, unknown>);
      }
      const failure = input as AttemptFailure;
      await client.query(
        `UPDATE fabric_attempts SET status='failed',finished_at=now(),
           error_code=$2,error_summary=$3 WHERE id=$1`,
        [attemptId, failure.errorCode, failure.errorSummary],
      );
      await client.query(
        "UPDATE fabric_runs SET status='failed',finished_at=now() WHERE id=$1",
        [runId],
      );
      const retry =
        failure.retryable && Number(row.attempt_number) < Number(row.max_attempts);
      const nextStatus = retry ? "queued" : "dead_lettered";
      const task = await client.query(
        `UPDATE fabric_tasks SET status=$2,
           available_at=CASE WHEN $2='queued'
             THEN now()+($5*interval '1 second') ELSE available_at END,
           delivery_published_at=NULL,last_error_code=$3,last_error_summary=$4,
           completed_at=CASE WHEN $2='dead_lettered' THEN now() ELSE NULL END,
           updated_at=now()
         WHERE id=$1 RETURNING *`,
        [
          taskId,
          nextStatus,
          failure.errorCode,
          failure.errorSummary,
          Number(row.retry_backoff_seconds),
        ],
      );
      await this.event(
        client,
        "task",
        taskId,
        retry ? "task.retry_scheduled" : "task.dead_lettered",
        { attemptId, errorCode: failure.errorCode },
        input.fabricEpoch,
      );
      return taskFromRow(task.rows[0] as Record<string, unknown>);
    });
  }

  async claimEffects(
    input: EffectClaim,
    leaseSeconds: number,
  ): Promise<EffectAssignment[]> {
    return this.transaction(async (client) => {
      const state = await client.query<{ current_epoch: string }>(
        "SELECT current_epoch FROM fabric_state WHERE singleton=true",
      );
      const epoch = Number(state.rows[0]?.current_epoch ?? 1);
      const candidates = await client.query(
        `SELECT * FROM fabric_effect_outbox
         WHERE status='pending' AND available_at <= now()
           AND fabric_epoch=$1
           AND effect_type=ANY($2::text[])
         ORDER BY available_at,created_at,id
         FOR UPDATE SKIP LOCKED LIMIT $3`,
        [epoch, input.effectTypes, input.limit],
      );
      const assignments: EffectAssignment[] = [];
      for (const row of candidates.rows as Array<Record<string, unknown>>) {
        const claimToken = randomUUID();
        const claimed = await client.query(
          `UPDATE fabric_effect_outbox SET status='processing',claimed_by=$2,
             claim_token=$3,claimed_at=now(),
             claim_expires_at=now()+($4*interval '1 second'),updated_at=now()
           WHERE id=$1 RETURNING claim_expires_at`,
          [row.id, input.consumerId, claimToken, leaseSeconds],
        );
        assignments.push({
          effectId: String(row.id),
          effectKey: String(row.effect_key),
          taskId: String(row.task_id),
          effectType: String(row.effect_type),
          payload: (row.payload ?? {}) as Record<string, unknown>,
          claimToken,
          claimExpiresAt: iso(
            (claimed.rows[0] as Record<string, unknown>).claim_expires_at as string,
          ),
          fabricEpoch: epoch,
          attemptCount: Number(row.attempt_count ?? 0),
          maxAttempts: Number(row.max_attempts ?? 8),
        });
      }
      return assignments;
    });
  }

  async deliverEffect(effectId: string, input: EffectDelivery): Promise<void> {
    const result = await this.pool.query(
      `UPDATE fabric_effect_outbox e SET status='delivered',
         provider_receipt=$5::jsonb,delivered_at=now(),updated_at=now()
       FROM fabric_state s
       WHERE e.id=$1 AND e.claimed_by=$2 AND e.claim_token=$3
         AND e.fabric_epoch=$4 AND s.current_epoch=$4 AND s.singleton=true
         AND e.status='processing' AND e.claim_expires_at > now()
       RETURNING e.id`,
      [
        effectId,
        input.consumerId,
        input.claimToken,
        input.fabricEpoch,
        JSON.stringify(input.providerReceipt),
      ],
    );
    if (!result.rowCount) {
      throw new FencedError("effect delivery is stale, expired, or fenced");
    }
  }

  async failEffect(effectId: string, input: EffectFailure): Promise<void> {
    const result = await this.pool.query(
      `UPDATE fabric_effect_outbox e SET status='pending',
         available_at=now()+($5*interval '1 second'),last_error=$6,
         claimed_by=NULL,claim_token=NULL,claimed_at=NULL,claim_expires_at=NULL,
         updated_at=now()
       FROM fabric_state s
       WHERE e.id=$1 AND e.claimed_by=$2 AND e.claim_token=$3
         AND e.fabric_epoch=$4 AND s.current_epoch=$4 AND s.singleton=true
         AND e.status='processing' AND e.claim_expires_at > now()
       RETURNING e.id`,
      [
        effectId,
        input.consumerId,
        input.claimToken,
        input.fabricEpoch,
        input.retryAfterSeconds,
        input.errorSummary,
      ],
    );
    if (!result.rowCount) {
      throw new FencedError("effect failure is stale, expired, or fenced");
    }
  }

  async reconcileExpired(): Promise<{
    expiredRequeued: number;
    expiredDeadLettered: number;
    effectsRequeued: number;
    effectsDeadLettered: number;
  }> {
    return this.transaction(async (client) => {
      const expired = await client.query(
        `SELECT a.*, t.max_attempts, t.retry_backoff_seconds
         FROM fabric_attempts a JOIN fabric_tasks t ON t.id=a.task_id
         WHERE a.status='running' AND a.lease_expires_at <= now()
         ORDER BY a.task_id, a.attempt_number
         FOR UPDATE OF a, t SKIP LOCKED`,
      );
      let expiredRequeued = 0;
      let expiredDeadLettered = 0;
      for (const raw of expired.rows as Array<Record<string, unknown>>) {
        const retry = Number(raw.attempt_number) < Number(raw.max_attempts);
        await client.query(
          "UPDATE fabric_attempts SET status='expired',finished_at=now() WHERE id=$1",
          [raw.id],
        );
        await client.query(
          "UPDATE fabric_runs SET status='expired',finished_at=now() WHERE id=$1",
          [raw.run_id],
        );
        await client.query(
          `UPDATE fabric_tasks SET status=$2,delivery_published_at=NULL,
             available_at=CASE WHEN $2='queued'
               THEN now()+($3*interval '1 second') ELSE available_at END,
             completed_at=CASE WHEN $2='dead_lettered' THEN now() ELSE NULL END,
             last_error_code='lease_expired',last_error_summary='worker lease expired',
             updated_at=now() WHERE id=$1`,
          [
            raw.task_id,
            retry ? "queued" : "dead_lettered",
            Number(raw.retry_backoff_seconds),
          ],
        );
        await this.event(
          client,
          "task",
          String(raw.task_id),
          retry ? "task.lease_expired_requeued" : "task.lease_expired_dead_lettered",
          { attemptId: raw.id },
          Number(raw.fabric_epoch),
        );
        if (retry) expiredRequeued += 1;
        else expiredDeadLettered += 1;
      }
      await client.query(
        `UPDATE fabric_worker_sessions SET status='expired',ended_at=now(),
           end_reason='worker_lease_expired'
         WHERE status='active' AND lease_expires_at <= now()`,
      );
      const effects = await client.query<{ status: string }>(
        `UPDATE fabric_effect_outbox SET status='pending',claimed_by=NULL,
           claim_token=NULL,claimed_at=NULL,claim_expires_at=NULL,
           available_at=now(),updated_at=now(),last_error='effect claim expired'
         WHERE status='processing' AND claim_expires_at <= now()
         RETURNING status`,
      );
      return {
        expiredRequeued,
        expiredDeadLettered,
        effectsRequeued: effects.rows.filter((row) => row.status === "pending").length,
        effectsDeadLettered: effects.rows.filter(
          (row) => row.status === "dead_lettered",
        ).length,
      };
    });
  }

  async listPublishable(limit: number): Promise<TaskRecord[]> {
    const result = await this.pool.query(
      `SELECT * FROM fabric_tasks
       WHERE status='queued' AND available_at <= now()
         AND (delivery_published_at IS NULL OR delivery_published_at < now() - interval '1 minute')
       ORDER BY priority DESC,available_at,created_at,id LIMIT $1`,
      [limit],
    );
    return result.rows.map((row) => taskFromRow(row as Record<string, unknown>));
  }

  async markPublished(taskId: string): Promise<void> {
    await this.transaction(async (client) => {
      await client.query(
        `UPDATE fabric_tasks SET delivery_published_at=now(),updated_at=now()
         WHERE id=$1 AND status='queued'`,
        [taskId],
      );
    });
  }

  async queueSnapshot(): Promise<QueueSnapshot[]> {
    const result = await this.pool.query(
      `SELECT queue_name,
         count(*) FILTER (WHERE status='queued')::int AS queued,
         count(*) FILTER (
           WHERE status='queued' AND available_at <= now()
         )::int AS ready,
         count(*) FILTER (
           WHERE status='queued' AND available_at > now()
         )::int AS delayed,
         count(*) FILTER (
           WHERE status='queued' AND attempt_count > 0
         )::int AS retrying,
         count(*) FILTER (WHERE status='running')::int AS running,
         count(*) FILTER (WHERE status='succeeded')::int AS succeeded,
         count(*) FILTER (WHERE status='failed')::int AS failed,
         count(*) FILTER (WHERE status='dead_lettered')::int AS dead_lettered,
         count(*) FILTER (WHERE status='cancelled')::int AS cancelled,
         count(*) FILTER (
           WHERE status='succeeded'
             AND completed_at >= now() - interval '1 hour'
         )::int AS completed_last_hour,
         count(*) FILTER (
           WHERE status IN ('failed','dead_lettered')
             AND completed_at >= now() - interval '1 hour'
         )::int AS failed_last_hour,
         min(created_at) FILTER (WHERE status='queued') AS oldest_queued_at,
         extract(epoch FROM (
           now() - min(created_at) FILTER (
             WHERE status='queued' AND available_at <= now()
           )
         ))::int AS oldest_ready_age_seconds
       FROM fabric_tasks GROUP BY queue_name ORDER BY queue_name`,
    );
    return result.rows.map((row: Record<string, unknown>) => {
      const completedLastHour = Number(row.completed_last_hour);
      const failedLastHour = Number(row.failed_last_hour);
      const terminalLastHour = completedLastHour + failedLastHour;
      return {
        queue: String(row.queue_name),
        queued: Number(row.queued),
        ready: Number(row.ready),
        delayed: Number(row.delayed),
        retrying: Number(row.retrying),
        running: Number(row.running),
        succeeded: Number(row.succeeded),
        failed: Number(row.failed),
        deadLettered: Number(row.dead_lettered),
        cancelled: Number(row.cancelled),
        completedLastHour,
        failedLastHour,
        throughputPerHour: completedLastHour,
        failureRateLastHour:
          terminalLastHour === 0 ? 0 : failedLastHour / terminalLastHour,
        oldestQueuedAt: row.oldest_queued_at
          ? iso(row.oldest_queued_at as string)
          : null,
        oldestReadyAgeSeconds:
          row.oldest_ready_age_seconds === null
            ? null
            : Number(row.oldest_ready_age_seconds),
      };
    });
  }

  async workerSnapshot(): Promise<WorkerSnapshot[]> {
    const result = await this.pool.query(
      `SELECT w.*,
         count(a.id) FILTER (WHERE a.status='running')::int AS running,
         current_session.started_at AS current_session_started_at,
         COALESCE(history.sessions,'[]'::jsonb) AS session_history
       FROM fabric_workers w
       LEFT JOIN fabric_attempts a ON a.worker_id=w.worker_id
       LEFT JOIN fabric_worker_sessions current_session
         ON current_session.id=w.current_session_id
       LEFT JOIN LATERAL (
         SELECT jsonb_agg(
           jsonb_build_object(
             'sessionId',recent.id,
             'status',recent.status,
             'fabricEpoch',recent.fabric_epoch,
             'startedAt',recent.started_at,
             'lastHeartbeatAt',recent.last_heartbeat_at,
             'leaseExpiresAt',recent.lease_expires_at,
             'endedAt',recent.ended_at,
             'endReason',recent.end_reason
           ) ORDER BY recent.started_at DESC,recent.id
         ) AS sessions
         FROM (
           SELECT * FROM fabric_worker_sessions
           WHERE worker_id=w.worker_id
           ORDER BY started_at DESC,id
           LIMIT 10
         ) recent
       ) history ON true
       GROUP BY w.worker_id,current_session.started_at,history.sessions
       ORDER BY (w.lease_expires_at > now()) DESC,w.worker_id`,
    );
    return result.rows.map((row: Record<string, unknown>) => ({
      workerId: String(row.worker_id),
      hostId: String(row.host_id),
      poolId: String(row.pool_id),
      provider: String(row.provider),
      queues: row.queues as string[],
      capabilities: row.capabilities as string[],
      maxConcurrency: Number(row.max_concurrency),
      running: Number(row.running),
      state: new Date(row.lease_expires_at as string).getTime() > Date.now()
        ? "online"
        : "offline",
      leaseExpiresAt: iso(row.lease_expires_at as string),
      lastHeartbeatAt: iso(row.last_heartbeat_at as string),
      configFingerprint: String(row.config_fingerprint),
      currentSessionId: row.current_session_id
        ? String(row.current_session_id)
        : null,
      currentSessionStartedAt: row.current_session_started_at
        ? iso(row.current_session_started_at as string)
        : null,
      sessionHistory: (
        (row.session_history ?? []) as Array<Record<string, unknown>>
      ).map((session) => ({
        sessionId: String(session.sessionId),
        status: String(session.status) as WorkerSessionSnapshot["status"],
        fabricEpoch: Number(session.fabricEpoch),
        startedAt: iso(session.startedAt as string),
        lastHeartbeatAt: iso(session.lastHeartbeatAt as string),
        leaseExpiresAt: iso(session.leaseExpiresAt as string),
        endedAt: session.endedAt ? iso(session.endedAt as string) : null,
        endReason: session.endReason ? String(session.endReason) : null,
      })),
    }));
  }

  async runSnapshot(limit: number): Promise<RunSnapshot[]> {
    const result = await this.pool.query(
      `SELECT t.id AS task_id,t.namespace,t.queue_name,t.task_type,t.status,
         t.scheduling_class,t.priority,t.max_attempts,t.attempt_count,
         t.available_at,t.created_at,t.updated_at,t.completed_at,
         t.last_error_code,t.last_error_summary,
         attempt_history.worker_id,attempt_history.lease_expires_at,
         COALESCE(attempt_history.attempts,'[]'::jsonb) AS attempts,
         COALESCE(effect_history.effects,'[]'::jsonb) AS effects,
         COALESCE(artifact_history.artifacts,'[]'::jsonb) AS artifacts
       FROM fabric_tasks t
       LEFT JOIN LATERAL (
         SELECT
           (array_agg(a.worker_id ORDER BY a.attempt_number DESC))[1]
             AS worker_id,
           (array_agg(a.lease_expires_at ORDER BY a.attempt_number DESC))[1]
             AS lease_expires_at,
           jsonb_agg(
             jsonb_build_object(
               'attemptId',a.id,
               'runId',a.run_id,
               'attemptNumber',a.attempt_number,
               'status',a.status,
               'workerId',a.worker_id,
               'hostId',w.host_id,
               'workerSessionId',a.worker_session_id,
               'fabricEpoch',a.fabric_epoch,
               'leaseDurationSeconds',a.lease_duration_seconds,
               'leaseExpiresAt',a.lease_expires_at,
               'startedAt',a.started_at,
               'finishedAt',a.finished_at,
               'result',a.result,
               'errorCode',a.error_code,
               'errorSummary',a.error_summary
             ) ORDER BY a.attempt_number DESC,a.id
           ) AS attempts
         FROM fabric_attempts a
         LEFT JOIN fabric_workers w ON w.worker_id=a.worker_id
         WHERE a.task_id=t.id
       ) attempt_history ON true
       LEFT JOIN LATERAL (
         SELECT jsonb_agg(
           jsonb_build_object(
             'effectId',e.id,
             'effectKey',e.effect_key,
             'effectType',e.effect_type,
             'status',e.status,
             'attemptCount',e.attempt_count,
             'maxAttempts',e.max_attempts,
             'availableAt',e.available_at,
             'deliveredAt',e.delivered_at,
             'providerReceipt',e.provider_receipt,
             'lastError',e.last_error,
             'createdAt',e.created_at,
             'updatedAt',e.updated_at
           ) ORDER BY e.created_at,e.id
         ) AS effects
         FROM fabric_effect_outbox e WHERE e.task_id=t.id
       ) effect_history ON true
       LEFT JOIN LATERAL (
         SELECT jsonb_agg(
           jsonb_build_object(
             'artifactId',artifact.id,
             'attemptId',artifact.attempt_id,
             'name',artifact.name,
             'contentType',artifact.content_type,
             'sha256',artifact.sha256,
             'sizeBytes',artifact.size_bytes,
             'status',artifact.status,
             'uri',artifact.storage_uri,
             'createdAt',artifact.created_at,
             'availableAt',artifact.available_at,
             'lastError',artifact.last_error
           ) ORDER BY artifact.created_at,artifact.id
         ) AS artifacts
         FROM fabric_artifacts artifact WHERE artifact.task_id=t.id
       ) artifact_history ON true
       ORDER BY t.updated_at DESC,t.id LIMIT $1`,
      [limit],
    );
    return result.rows.map((row: Record<string, unknown>) => ({
      taskId: String(row.task_id),
      namespace: String(row.namespace),
      queue: String(row.queue_name),
      taskType: String(row.task_type),
      status: String(row.status),
      schedulingClass:
        row.scheduling_class === "interactive" ? "interactive" : "background",
      priority: Number(row.priority),
      maxAttempts: Number(row.max_attempts),
      attemptCount: Number(row.attempt_count),
      workerId: row.worker_id ? String(row.worker_id) : null,
      leaseExpiresAt: row.lease_expires_at
        ? iso(row.lease_expires_at as string)
        : null,
      availableAt: iso(row.available_at as string),
      createdAt: iso(row.created_at as string),
      completedAt: row.completed_at ? iso(row.completed_at as string) : null,
      lastErrorCode: row.last_error_code
        ? String(row.last_error_code)
        : null,
      lastErrorSummary: row.last_error_summary
        ? String(row.last_error_summary)
        : null,
      attempts: (
        (row.attempts ?? []) as Array<Record<string, unknown>>
      ).map((attempt) => ({
        attemptId: String(attempt.attemptId),
        runId: String(attempt.runId),
        attemptNumber: Number(attempt.attemptNumber),
        status: String(attempt.status),
        workerId: String(attempt.workerId),
        hostId: attempt.hostId ? String(attempt.hostId) : null,
        workerSessionId: attempt.workerSessionId
          ? String(attempt.workerSessionId)
          : null,
        fabricEpoch: Number(attempt.fabricEpoch),
        leaseDurationSeconds: Number(attempt.leaseDurationSeconds),
        leaseExpiresAt: iso(attempt.leaseExpiresAt as string),
        startedAt: iso(attempt.startedAt as string),
        finishedAt: attempt.finishedAt
          ? iso(attempt.finishedAt as string)
          : null,
        result: attempt.result
          ? (attempt.result as Record<string, unknown>)
          : null,
        errorCode: attempt.errorCode ? String(attempt.errorCode) : null,
        errorSummary: attempt.errorSummary
          ? String(attempt.errorSummary)
          : null,
      })),
      effects: (row.effects ?? []) as Array<Record<string, unknown>>,
      artifacts: (row.artifacts ?? []) as Array<Record<string, unknown>>,
      updatedAt: iso(row.updated_at as string),
    }));
  }

  async systemSnapshot(): Promise<SystemSnapshot> {
    const [state, effects, events, roleHealth] = await Promise.all([
      this.pool.query(
        `SELECT current_epoch,leader_host_id,leader_lease_expires_at,
           leadership_cluster_id,leadership_receipt_id,
           leadership_fence_digest,leader_recovery_hold_until,
           policy_fingerprint
         FROM fabric_state WHERE singleton=true`,
      ),
      this.pool.query<{ status: string; count: string }>(
        `SELECT status,count(*)::text AS count
         FROM fabric_effect_outbox GROUP BY status ORDER BY status`,
      ),
      this.pool.query<{ sequence: string }>(
        "SELECT COALESCE(max(sequence),0)::text AS sequence FROM fabric_events",
      ),
      this.pool.query("SELECT * FROM fabric_role_health ORDER BY host_id,role"),
    ]);
    const row = (state.rows[0] ?? {}) as Record<string, unknown>;
    return {
      fabricEpoch: Number(row.current_epoch ?? 1),
      leaderHostId: row.leader_host_id ? String(row.leader_host_id) : null,
      leaderLeaseExpiresAt: row.leader_lease_expires_at
        ? iso(row.leader_lease_expires_at as string)
        : null,
      leadershipClusterId: row.leadership_cluster_id
        ? String(row.leadership_cluster_id)
        : null,
      leadershipReceiptId: row.leadership_receipt_id
        ? String(row.leadership_receipt_id)
        : null,
      leadershipFenceDigest: row.leadership_fence_digest
        ? String(row.leadership_fence_digest)
        : null,
      leaderRecoveryHoldUntil: row.leader_recovery_hold_until
        ? iso(row.leader_recovery_hold_until as string)
        : null,
      databasePolicyFingerprint: row.policy_fingerprint
        ? String(row.policy_fingerprint)
        : null,
      effects: Object.fromEntries(
        effects.rows.map((effect) => [effect.status, Number(effect.count)]),
      ),
      eventSequence: Number(events.rows[0]?.sequence ?? 0),
      roleHealth: roleHealth.rows.map((row) =>
        roleHealthSnapshot(row as Record<string, unknown>),
      ),
    };
  }

  async activatePolicy(fingerprint: string): Promise<void> {
    await this.transaction(async (client) => {
      await client.query(
        "SELECT pg_advisory_xact_lock(hashtext('agentic-os-execution-fabric-policy'))",
      );
      const state = await client.query<{ policy_fingerprint: string | null }>(
        `SELECT policy_fingerprint FROM fabric_state
         WHERE singleton=true FOR UPDATE`,
      );
      const current = state.rows[0]?.policy_fingerprint ?? null;
      if (current === fingerprint) return;
      if (current !== null) {
        throw new ConflictError(
          "database policy fingerprint differs from this process; use the fenced admin reload protocol",
        );
      }
      await client.query(
        `UPDATE fabric_state SET policy_fingerprint=$1,updated_at=now()
         WHERE singleton=true AND policy_fingerprint IS NULL`,
        [fingerprint],
      );
    });
  }

  async activatePolicyReload(input: {
    rotationId: string;
    preparationTokenHash: string;
    authorizationIssuedAt?: string;
    authorizationExpiresAt: string;
    expectedEpoch: number;
    expectedCurrentFingerprint: string;
    expectedCandidateFingerprint: string;
    operatorOverride?: PolicyReloadOperatorOverride;
  }): Promise<ConfigReloadReceipt> {
    if (!this.hostId) {
      throw new FencedError("policy reload requires a stable control-plane host id");
    }
    if (input.operatorOverride) {
      const startsAt = new Date(
        input.operatorOverride.maintenanceWindow.startsAt,
      ).getTime();
      const endsAt = new Date(
        input.operatorOverride.maintenanceWindow.endsAt,
      ).getTime();
      const authorizationExpiresAt = new Date(
        input.authorizationExpiresAt,
      ).getTime();
      const now = Date.now();
      if (
        !Number.isFinite(startsAt) ||
        !Number.isFinite(endsAt) ||
        startsAt > now ||
        endsAt <= now ||
        authorizationExpiresAt > endsAt
      ) {
        throw new FencedError(
          "standalone policy reload is outside its signed maintenance window",
        );
      }
    }
    const hostId = this.hostId;
    return this.transaction(async (client) => {
      await client.query(
        "SELECT pg_advisory_xact_lock(hashtext('agentic-os-execution-fabric-policy'))",
      );
      const replay = await client.query<{
        id: string;
        rotation_id: string;
        preparation_token_hash: string;
        expected_current_fingerprint: string;
        expected_candidate_fingerprint: string;
        applied_fingerprint: string;
        fabric_epoch: string | number;
        host_id: string;
        applied_at: string;
        decision: ConfigReloadReceipt["decision"] | null;
        recovery_action: string | null;
        operator_id: string | null;
        override_reason: string | null;
        approval_reference: string | null;
        maintenance_window_start: string | null;
        maintenance_window_end: string | null;
        authorization_issued_at: string | null;
      }>(
        `SELECT id,rotation_id,preparation_token_hash,
                expected_current_fingerprint,expected_candidate_fingerprint,
                applied_fingerprint,fabric_epoch,host_id,applied_at,decision,
                recovery_action,operator_id,override_reason,approval_reference,
                maintenance_window_start,maintenance_window_end,
                authorization_issued_at
           FROM fabric_config_reload_receipts
          WHERE rotation_id=$1`,
        [input.rotationId],
      );
      const prior = replay.rows[0];
      if (prior) {
        if (
          prior.preparation_token_hash !== input.preparationTokenHash ||
          (input.authorizationIssuedAt !== undefined &&
            iso(prior.authorization_issued_at!) !== iso(input.authorizationIssuedAt)) ||
          Number(prior.fabric_epoch) !== input.expectedEpoch ||
          prior.expected_current_fingerprint !==
            input.expectedCurrentFingerprint ||
          prior.expected_candidate_fingerprint !==
            input.expectedCandidateFingerprint ||
          (prior.operator_id === null) !== (input.operatorOverride === undefined) ||
          (input.operatorOverride !== undefined &&
            (prior.operator_id !== input.operatorOverride.actor ||
              prior.override_reason !== input.operatorOverride.reason ||
              prior.approval_reference !== input.operatorOverride.approvalReference ||
              iso(prior.maintenance_window_start!) !==
                iso(input.operatorOverride.maintenanceWindow.startsAt) ||
              iso(prior.maintenance_window_end!) !==
                iso(input.operatorOverride.maintenanceWindow.endsAt)))
        ) {
          throw new ConflictError(
            "configuration rotation id was already used by another request",
          );
        }
        return {
          schemaVersion: "execution-fabric-config-reload-receipt/v1",
          receiptId: prior.id,
          rotationId: prior.rotation_id,
          preparationTokenHash: prior.preparation_token_hash,
          expectedCurrentFingerprint: prior.expected_current_fingerprint,
          expectedCandidateFingerprint:
            prior.expected_candidate_fingerprint,
          appliedFingerprint: prior.applied_fingerprint,
          fabricEpoch: Number(prior.fabric_epoch),
          hostId: prior.host_id,
          ...(prior.authorization_issued_at
            ? { authorizedAt: iso(prior.authorization_issued_at) }
            : {}),
          appliedAt: iso(prior.applied_at),
          decision:
            prior.decision ??
            (prior.operator_id
              ? "standalone_policy_override_applied"
              : "policy_reload_applied"),
          recoveryAction:
            prior.recovery_action ??
            "verify witness commit or run rotate-policy.sh --resume",
          ...(prior.operator_id &&
          prior.override_reason &&
          prior.approval_reference &&
          prior.maintenance_window_start &&
          prior.maintenance_window_end
            ? {
                operatorOverride: {
                  actor: prior.operator_id,
                  reason: prior.override_reason,
                  approvalReference: prior.approval_reference,
                  maintenanceWindow: {
                    startsAt: iso(prior.maintenance_window_start),
                    endsAt: iso(prior.maintenance_window_end),
                  },
                },
              }
            : {}),
        };
      }
      const state = await client.query<{
        policy_fingerprint: string | null;
        current_epoch: string | number;
        leader_host_id: string | null;
        leader_lease_expires_at: string | null;
      }>(
        `SELECT policy_fingerprint,current_epoch,leader_host_id,
                leader_lease_expires_at
           FROM fabric_state
         WHERE singleton=true FOR UPDATE`,
      );
      const current = state.rows[0]?.policy_fingerprint ?? null;
      if (current !== input.expectedCurrentFingerprint) {
        throw new ConflictError(
          "database policy fingerprint does not match expectedCurrentFingerprint",
        );
      }
      if (
        state.rows[0]?.leader_host_id !== hostId ||
        !state.rows[0]?.leader_lease_expires_at ||
        new Date(state.rows[0].leader_lease_expires_at).getTime() <= Date.now()
      ) {
        throw new FencedError(
          "policy reload requires this host to hold the current unexpired leadership lease",
        );
      }
      const active = await client.query<{ tasks: string; workers: string }>(
        `SELECT
           (SELECT count(*) FROM fabric_tasks
             WHERE status IN ('queued','running'))::text AS tasks,
           (SELECT count(*) FROM fabric_workers
             WHERE lease_expires_at > now())::text AS workers`,
      );
      if (
        Number(active.rows[0]?.tasks ?? 0) > 0 ||
        Number(active.rows[0]?.workers ?? 0) > 0
      ) {
        throw new ConflictError(
          "policy activation requires a drained queue and no live workers",
        );
      }
      const receiptId = randomUUID();
      const appliedAt = new Date().toISOString();
      const fabricEpoch = input.expectedEpoch;
      const decision: ConfigReloadReceipt["decision"] = input.operatorOverride
        ? "standalone_policy_override_applied"
        : "policy_reload_applied";
      const recoveryAction =
        "verify witness commit or run rotate-policy.sh --resume";
      const updated = await client.query(
        `UPDATE fabric_state SET policy_fingerprint=$1,updated_at=now()
         WHERE singleton=true
           AND policy_fingerprint=$2
           AND leader_host_id=$3
           AND leader_lease_expires_at > clock_timestamp()
           AND clock_timestamp() < $4::timestamptz
           AND current_epoch=$5
           AND (
             $6::timestamptz IS NULL OR
             (clock_timestamp() >= $6::timestamptz AND
              clock_timestamp() < $7::timestamptz)
           )
         RETURNING policy_fingerprint`,
        [
          input.expectedCandidateFingerprint,
          input.expectedCurrentFingerprint,
          hostId,
          input.authorizationExpiresAt,
          input.expectedEpoch,
          input.operatorOverride?.maintenanceWindow.startsAt ?? null,
          input.operatorOverride?.maintenanceWindow.endsAt ?? null,
        ],
      );
      if (updated.rowCount !== 1) {
        throw new FencedError(
          "policy reload lost leadership or signed durable policy authority before commit",
        );
      }
      await client.query(
        `INSERT INTO fabric_config_reload_receipts(
           id,rotation_id,preparation_token_hash,
           expected_current_fingerprint,expected_candidate_fingerprint,
           applied_fingerprint,fabric_epoch,host_id,applied_at,decision,
           recovery_action,operator_id,override_reason,approval_reference,
           maintenance_window_start,maintenance_window_end,authorization_issued_at
         ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)`,
        [
          receiptId,
          input.rotationId,
          input.preparationTokenHash,
          input.expectedCurrentFingerprint,
          input.expectedCandidateFingerprint,
          input.expectedCandidateFingerprint,
          fabricEpoch,
          hostId,
          appliedAt,
          decision,
          recoveryAction,
          input.operatorOverride?.actor ?? null,
          input.operatorOverride?.reason ?? null,
          input.operatorOverride?.approvalReference ?? null,
          input.operatorOverride?.maintenanceWindow.startsAt ?? null,
          input.operatorOverride?.maintenanceWindow.endsAt ?? null,
          input.authorizationIssuedAt ?? null,
        ],
      );
      return {
        schemaVersion: "execution-fabric-config-reload-receipt/v1",
        receiptId,
        rotationId: input.rotationId,
        preparationTokenHash: input.preparationTokenHash,
        expectedCurrentFingerprint: input.expectedCurrentFingerprint,
        expectedCandidateFingerprint: input.expectedCandidateFingerprint,
        appliedFingerprint: input.expectedCandidateFingerprint,
        fabricEpoch,
        hostId,
        ...(input.authorizationIssuedAt
          ? { authorizedAt: input.authorizationIssuedAt }
          : {}),
        appliedAt,
        decision,
        recoveryAction,
        ...(input.operatorOverride
          ? { operatorOverride: input.operatorOverride }
          : {}),
      };
    });
  }

  async activateLeadership(input: LeadershipActivation): Promise<void> {
    await this.transaction(async (client) => {
      await client.query(
        "SELECT pg_advisory_xact_lock(hashtext('agentic-os-execution-fabric-leadership'))",
      );
      const state = await client.query<{
        current_epoch: string;
        leader_host_id: string | null;
      }>(
        `SELECT current_epoch,leader_host_id FROM fabric_state
         WHERE singleton=true FOR UPDATE`,
      );
      const currentEpoch = Number(state.rows[0]?.current_epoch ?? 1);
      const currentLeader = state.rows[0]?.leader_host_id ?? null;
      const leadershipChanged =
        input.fabricEpoch > currentEpoch ||
        currentLeader !== input.leaderHostId;
      if (input.fabricEpoch < currentEpoch) {
        throw new FencedError("witness epoch is older than PostgreSQL fabric epoch");
      }
      if (
        input.fabricEpoch === currentEpoch &&
        currentLeader !== null &&
        currentLeader !== input.leaderHostId
      ) {
        throw new FencedError(
          "witness leader conflicts with PostgreSQL leader at the same epoch",
        );
      }
      if (input.fabricEpoch > currentEpoch + 1) {
        throw new FencedError(
          "witness epoch skipped the PostgreSQL epoch; operator reseed is required",
        );
      }
      if (input.fabricEpoch > currentEpoch) {
        await client.query(
          `UPDATE fabric_attempts SET status='fenced',finished_at=now(),
             error_code='leadership_epoch_advanced',
             error_summary='attempt fenced by leadership epoch advance'
           WHERE status='running' AND fabric_epoch < $1`,
          [input.fabricEpoch],
        );
        await client.query(
          `UPDATE fabric_runs r SET status='expired',finished_at=now()
           FROM fabric_attempts a
           WHERE r.id=a.run_id AND a.status='fenced'
             AND a.fabric_epoch < $1 AND r.status='running'`,
          [input.fabricEpoch],
        );
        await client.query(
          `UPDATE fabric_tasks t SET status='queued',delivery_published_at=NULL,
             available_at=now(),last_error_code='leadership_epoch_advanced',
             last_error_summary='work was safely requeued after leadership transfer',
             updated_at=now()
           WHERE t.status='running' AND EXISTS (
             SELECT 1 FROM fabric_attempts a
             WHERE a.task_id=t.id AND a.status='fenced' AND a.fabric_epoch < $1
           )`,
          [input.fabricEpoch],
        );
        await client.query(
          `UPDATE fabric_effect_outbox SET fabric_epoch=$1,status='pending',
             claimed_by=NULL,claim_token=NULL,claimed_at=NULL,
             claim_expires_at=NULL,available_at=now(),updated_at=now(),
             last_error='effect re-fenced by leadership epoch advance'
           WHERE status <> 'delivered' AND fabric_epoch < $1`,
          [input.fabricEpoch],
        );
        await client.query(
          `UPDATE fabric_workers SET lease_expires_at=now(),updated_at=now()
           WHERE registered_epoch < $1 OR registered_epoch=$1`,
          [input.fabricEpoch],
        );
      }
      await client.query(
        `UPDATE fabric_state SET current_epoch=$1,leader_host_id=$2,
           leader_lease_expires_at=$3::timestamptz,
           leadership_cluster_id=$4,leadership_receipt_id=$5,
           leadership_fence_digest=$6,
           leader_recovery_hold_until=$7::timestamptz,updated_at=now()
         WHERE singleton=true`,
        [
          input.fabricEpoch,
          input.leaderHostId,
          input.leaseExpiresAt,
          input.clusterId,
          input.receiptId,
          input.fenceDigest,
          input.recoveryHoldUntil,
        ],
      );
      if (leadershipChanged) {
        await this.event(
          client,
          "fabric",
          input.clusterId,
          "leadership.activated",
          {
            leaderHostId: input.leaderHostId,
            receiptId: input.receiptId,
            fenceDigest: input.fenceDigest,
            leaseExpiresAt: input.leaseExpiresAt,
          },
          input.fabricEpoch,
        );
      }
    }, false);
  }

  async ping(): Promise<void> {
    await this.pool.query("SELECT 1");
  }

  private async assertDatabaseLeadership(client: pg.PoolClient): Promise<void> {
    const result = await client.query(
      `SELECT 1 FROM fabric_state WHERE singleton=true
         AND leader_host_id=$1
         AND leader_lease_expires_at > clock_timestamp()`,
      [this.hostId],
    );
    if (!result.rowCount) {
      throw new FencedError(
        "control plane is not the current unexpired PostgreSQL leader",
      );
    }
  }

  private async lockPolicyOperation(
    client: pg.PoolClient,
    fingerprint: string,
  ): Promise<void> {
    await client.query(
      "SELECT pg_advisory_xact_lock(hashtext('agentic-os-execution-fabric-policy'))",
    );
    const state = await client.query<{ policy_fingerprint: string | null }>(
      `SELECT policy_fingerprint FROM fabric_state
       WHERE singleton=true FOR UPDATE`,
    );
    const current = state.rows[0]?.policy_fingerprint ?? null;
    if (current === null) {
      await client.query(
        `UPDATE fabric_state SET policy_fingerprint=$1,updated_at=now()
         WHERE singleton=true`,
        [fingerprint],
      );
      return;
    }
    if (current !== fingerprint) {
      throw new ConflictError(
        "replica policy fingerprint differs from the database policy fingerprint",
      );
    }
  }

  private async event(
    client: pg.PoolClient,
    aggregateType: string,
    aggregateId: string,
    eventType: string,
    data: Record<string, unknown>,
    epoch?: number,
  ): Promise<void> {
    let effectiveEpoch = epoch;
    if (effectiveEpoch === undefined) {
      const state = await client.query<{ current_epoch: string }>(
        "SELECT current_epoch FROM fabric_state WHERE singleton=true",
      );
      effectiveEpoch = Number(state.rows[0]?.current_epoch ?? 1);
    }
    await client.query(
      `INSERT INTO fabric_events(
         event_id,aggregate_type,aggregate_id,event_type,fabric_epoch,data
       ) VALUES($1,$2,$3,$4,$5,$6::jsonb)`,
      [
        randomUUID(),
        aggregateType,
        aggregateId,
        eventType,
        effectiveEpoch,
        JSON.stringify(data),
      ],
    );
  }
}
