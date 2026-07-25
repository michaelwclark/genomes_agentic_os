import { createHash, randomUUID } from "node:crypto";
import type pg from "pg";
import type { ExecutionFabric } from "./fabric.js";
import { ConflictError, FencedError, NotFoundError } from "./ledger.js";
import type { PolicySnapshot } from "./policy.js";
import type { ReliabilityObservation } from "./contracts.js";

export const FINDING_KINDS = [
  "expired_attempts",
  "missing_delivery",
  "dead_worker",
  "queue_without_capacity",
  "config_drift",
  "expired_effect_claims",
  "effect_projection_failure",
  "object_store_unavailable",
  "artifact_upload_failure",
  "external_observation",
] as const;

export type FindingKind = (typeof FINDING_KINDS)[number];
export type FindingSeverity = "info" | "warning" | "critical";

export type FindingObservation = {
  kind: FindingKind;
  scopeType: "fabric" | "queue" | "worker" | "effect" | "artifact" | "external";
  scopeId: string;
  severity: FindingSeverity;
  summary: string;
  details: Record<string, unknown>;
};

export type HealthFinding = FindingObservation & {
  id: string;
  fingerprint: string;
  revision: number;
  status: "open" | "acknowledged" | "resolved" | "cancelled";
  observedCount: number;
  fabricEpoch: number;
  firstObservedAt: string;
  lastObservedAt: string;
};

export type ReliabilitySnapshot = {
  schemaVersion: "execution-fabric-reliability-status/v1";
  findings: Record<string, number>;
  alarms: Record<string, number>;
  repairs: Record<string, number>;
  lastObservationAt: string | null;
  lastRepairAt: string | null;
  activeFindings?: HealthFinding[];
  unresolvedAlarms?: Array<Record<string, unknown>>;
  recentRepairReceipts?: RepairReceipt[];
};

export type AlarmAssignment = {
  alarmId: string;
  findingId: string;
  incidentKey: string;
  revision: number;
  severity: FindingSeverity;
  payload: Record<string, unknown>;
  fabricEpoch: number;
  claimToken: string;
  claimExpiresAt: string;
};

export type ExternalObservationReceipt = {
  schemaVersion: "execution-fabric-reliability-observation-receipt/v1";
  admitted: boolean;
  idempotent: boolean;
  source: string;
  incidentKey: string;
  revision: number;
  finding: HealthFinding;
  alarmDerived: boolean;
  recoveryRecorded: boolean;
  alarmStatus: "resolved_awaiting_ack" | null;
};

export type BoundedFailureState = {
  attemptCount: number;
  status: "pending" | "dead_lettered";
  delaySeconds: number;
};

export function nextBoundedFailure(input: {
  attemptCount: number;
  maxAttempts: number;
  baseBackoffSeconds: number;
}): BoundedFailureState {
  const attemptCount = input.attemptCount + 1;
  if (attemptCount >= input.maxAttempts) {
    return { attemptCount, status: "dead_lettered", delaySeconds: 0 };
  }
  return {
    attemptCount,
    status: "pending",
    delaySeconds: Math.min(
      86400,
      input.baseBackoffSeconds * 2 ** Math.min(attemptCount - 1, 10),
    ),
  };
}

export function replayedEffectState(currentEpoch: number) {
  return {
    status: "pending" as const,
    attemptCount: 0,
    fabricEpoch: currentEpoch,
    claimToken: null,
    claimExpiresAt: null,
    deadLetteredAt: null,
    cancelledAt: null,
    lastError: null,
  };
}

export function assertFreshEpoch(findingEpoch: number, currentEpoch: number): void {
  if (findingEpoch !== currentEpoch) {
    throw new FencedError(
      `finding epoch ${findingEpoch} is stale; current epoch is ${currentEpoch}`,
    );
  }
}

export type RepairPolicy = {
  allowActions: readonly RepairAction[];
  cooldownSeconds: number;
  maxRepairsPerHour: number;
};

export type RepairAction =
  | "reconcile_expired_attempts"
  | "reconstruct_delivery"
  | "recover_effect_claim";

export type RepairReceipt = {
  id: string;
  idempotencyKey: string;
  findingId: string;
  findingRevision: number;
  action: RepairAction;
  status: "running" | "succeeded" | "failed" | "skipped" | "cancelled";
  actor: string;
  fabricEpoch: number;
  beforeVerification: Record<string, unknown>;
  afterVerification: Record<string, unknown> | null;
  errorSummary: string | null;
  startedAt: string | null;
  completedAt: string | null;
};

type FindingRow = {
  id: string;
  fingerprint: string;
  revision: number;
  kind: FindingKind;
  scope_type: FindingObservation["scopeType"];
  scope_id: string;
  severity: FindingSeverity;
  status: HealthFinding["status"];
  summary: string;
  details: Record<string, unknown>;
  observed_count: number;
  fabric_epoch: string | number;
  first_observed_at: string | Date;
  last_observed_at: string | Date;
};

function iso(value: string | Date): string {
  return new Date(value).toISOString();
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, child]) => `${JSON.stringify(key)}:${canonicalJson(child)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

export function findingFingerprint(
  observation: Pick<FindingObservation, "kind" | "scopeType" | "scopeId">,
): string {
  return createHash("sha256")
    .update(
      canonicalJson({
        kind: observation.kind,
        scopeType: observation.scopeType,
        scopeId: observation.scopeId,
      }),
    )
    .digest("hex");
}

function findingFromRow(row: FindingRow): HealthFinding {
  return {
    id: row.id,
    fingerprint: row.fingerprint,
    revision: Number(row.revision),
    kind: row.kind,
    scopeType: row.scope_type,
    scopeId: row.scope_id,
    severity: row.severity,
    status: row.status,
    summary: row.summary,
    details: row.details ?? {},
    observedCount: Number(row.observed_count),
    fabricEpoch: Number(row.fabric_epoch),
    firstObservedAt: iso(row.first_observed_at),
    lastObservedAt: iso(row.last_observed_at),
  };
}

function receiptFromRow(row: Record<string, unknown>): RepairReceipt {
  return {
    id: String(row.id),
    idempotencyKey: String(row.idempotency_key),
    findingId: String(row.finding_id),
    findingRevision: Number(row.finding_revision),
    action: String(row.action) as RepairAction,
    status: String(row.status) as RepairReceipt["status"],
    actor: String(row.actor),
    fabricEpoch: Number(row.fabric_epoch),
    beforeVerification: (row.before_verification ?? {}) as Record<string, unknown>,
    afterVerification:
      (row.after_verification as Record<string, unknown> | null) ?? null,
    errorSummary: row.error_summary ? String(row.error_summary) : null,
    startedAt: row.started_at ? iso(row.started_at as string | Date) : null,
    completedAt: row.completed_at ? iso(row.completed_at as string | Date) : null,
  };
}

export class PostgresReliabilityStore {
  constructor(
    private readonly pool: pg.Pool,
    private readonly hostId: string,
  ) {}

  async observerState(): Promise<{
    fabricEpoch: number;
    databasePolicyFingerprint: string | null;
  }> {
    const result = await this.pool.query<{
      current_epoch: string;
      policy_fingerprint: string | null;
    }>(
      `SELECT current_epoch,policy_fingerprint
       FROM fabric_state WHERE singleton=true`,
    );
    return {
      fabricEpoch: Number(result.rows[0]?.current_epoch ?? 1),
      databasePolicyFingerprint:
        result.rows[0]?.policy_fingerprint ?? null,
    };
  }

  async collect(expectedPolicy: string | PolicySnapshot): Promise<FindingObservation[]> {
    const expectedPolicyFingerprint =
      typeof expectedPolicy === "string"
        ? expectedPolicy
        : expectedPolicy.appliedFingerprint;
    const result = await this.pool.query<{
      current_epoch: string;
      policy_fingerprint: string | null;
    }>(
      "SELECT current_epoch,policy_fingerprint FROM fabric_state WHERE singleton=true",
    );
    const observations: FindingObservation[] = [];
    const state = result.rows[0];
    const localConfigUnhealthy =
      typeof expectedPolicy !== "string" && expectedPolicy.state !== "applied";
    const databaseConfigUnhealthy =
      Boolean(state?.policy_fingerprint) &&
      state?.policy_fingerprint !== expectedPolicyFingerprint;
    if (localConfigUnhealthy || databaseConfigUnhealthy) {
      observations.push({
        kind: "config_drift",
        scopeType: "fabric",
        scopeId: "policy",
        severity: "critical",
        summary: localConfigUnhealthy
          ? "Canonical execution policy is invalid or unapplied"
          : "Database and local execution policy fingerprints differ",
        details: {
          databaseFingerprint: state?.policy_fingerprint ?? null,
          expectedFingerprint: expectedPolicyFingerprint,
          ...(typeof expectedPolicy === "string"
            ? {}
            : {
                localState: expectedPolicy.state,
                diskFingerprint: expectedPolicy.diskFingerprint,
                lastError: expectedPolicy.lastError,
              }),
        },
      });
    }

    const expiredAttempts = await this.pool.query<{
      queue_name: string;
      count: string;
      oldest: string | Date;
    }>(
      `SELECT t.queue_name,count(*)::text AS count,min(a.lease_expires_at) AS oldest
       FROM fabric_attempts a
       JOIN fabric_tasks t ON t.id=a.task_id
       WHERE a.status='running' AND a.lease_expires_at <= now()
       GROUP BY t.queue_name ORDER BY t.queue_name`,
    );
    for (const row of expiredAttempts.rows) {
      observations.push({
        kind: "expired_attempts",
        scopeType: "queue",
        scopeId: row.queue_name,
        severity: "critical",
        summary: `${row.count} expired running attempt(s) require reconciliation`,
        details: { count: Number(row.count), oldestLeaseExpiry: iso(row.oldest) },
      });
    }

    const missingDeliveries = await this.pool.query<{
      queue_name: string;
      count: string;
      oldest: string | Date;
    }>(
      `SELECT queue_name,count(*)::text AS count,min(created_at) AS oldest
       FROM fabric_tasks
       WHERE status='queued' AND available_at <= now()
         AND (
           delivery_published_at IS NULL OR
           delivery_published_at < now() - interval '1 minute'
         )
       GROUP BY queue_name ORDER BY queue_name`,
    );
    for (const row of missingDeliveries.rows) {
      observations.push({
        kind: "missing_delivery",
        scopeType: "queue",
        scopeId: row.queue_name,
        severity: "critical",
        summary: `${row.count} queued task(s) are missing a current BullMQ delivery`,
        details: { count: Number(row.count), oldestTaskAt: iso(row.oldest) },
      });
    }

    const deadWorkers = await this.pool.query<{
      worker_id: string;
      host_id: string;
      pool_id: string;
      lease_expires_at: string | Date;
    }>(
      `SELECT worker_id,host_id,pool_id,lease_expires_at
       FROM fabric_workers
       WHERE lease_expires_at <= now()
         AND last_heartbeat_at >= now() - interval '24 hours'
       ORDER BY worker_id`,
    );
    for (const row of deadWorkers.rows) {
      observations.push({
        kind: "dead_worker",
        scopeType: "worker",
        scopeId: row.worker_id,
        severity: "warning",
        summary: `Worker ${row.worker_id} on ${row.host_id} is offline`,
        details: {
          hostId: row.host_id,
          poolId: row.pool_id,
          leaseExpiredAt: iso(row.lease_expires_at),
        },
      });
    }

    const noCapacity = await this.pool.query<{
      queue_name: string;
      count: string;
    }>(
      `SELECT t.queue_name,count(*)::text AS count
       FROM fabric_tasks t
       WHERE t.status='queued'
         AND NOT EXISTS (
           SELECT 1 FROM fabric_workers w
           WHERE w.lease_expires_at > now()
             AND w.queues ? t.queue_name
         )
       GROUP BY t.queue_name ORDER BY t.queue_name`,
    );
    for (const row of noCapacity.rows) {
      observations.push({
        kind: "queue_without_capacity",
        scopeType: "queue",
        scopeId: row.queue_name,
        severity: "critical",
        summary: `Queue ${row.queue_name} has work but no live worker capacity`,
        details: { queued: Number(row.count) },
      });
    }

    const expiredEffectClaims = await this.pool.query<{ count: string }>(
      `SELECT count(*)::text AS count FROM fabric_effect_outbox
       WHERE status='processing' AND claim_expires_at <= now()`,
    );
    if (Number(expiredEffectClaims.rows[0]?.count ?? 0) > 0) {
      observations.push({
        kind: "expired_effect_claims",
        scopeType: "fabric",
        scopeId: "effect-outbox",
        severity: "critical",
        summary: `${expiredEffectClaims.rows[0]?.count} effect claim(s) expired before receipt`,
        details: { count: Number(expiredEffectClaims.rows[0]?.count) },
      });
    }

    const failedEffects = await this.pool.query<{
      id: string;
      effect_key: string;
      status: string;
      attempt_count: number;
      max_attempts: number;
      last_error: string | null;
    }>(
      `SELECT id,effect_key,status,attempt_count,max_attempts,last_error
       FROM fabric_effect_outbox
       WHERE status IN ('failed','dead_lettered')
          OR (status='pending' AND attempt_count > 0 AND last_error IS NOT NULL)
       ORDER BY updated_at DESC LIMIT 500`,
    );
    for (const row of failedEffects.rows) {
      observations.push({
        kind: "effect_projection_failure",
        scopeType: "effect",
        scopeId: row.id,
        severity: row.status === "dead_lettered" ? "critical" : "warning",
        summary: `Effect ${row.effect_key} is ${
          row.status === "pending" ? "retrying after projection failure" : row.status
        }`,
        details: {
          effectKey: row.effect_key,
          status: row.status,
          attemptCount: Number(row.attempt_count),
          maxAttempts: Number(row.max_attempts),
          lastError: row.last_error,
        },
      });
    }
    const failedArtifacts = await this.pool.query<{
      id: string;
      task_id: string;
      attempt_id: string;
      name: string;
      status: string;
      last_error: string | null;
    }>(
      `SELECT id,task_id,attempt_id,name,status,last_error
       FROM fabric_artifacts
       WHERE status IN ('failed','expired')
          OR (status='pending' AND upload_expires_at <= now())
       ORDER BY updated_at DESC LIMIT 500`,
    );
    for (const row of failedArtifacts.rows) {
      observations.push({
        kind: "artifact_upload_failure",
        scopeType: "artifact",
        scopeId: row.id,
        severity: row.status === "expired" ? "critical" : "warning",
        summary: `Artifact ${row.name} is ${row.status === "pending" ? "upload-expired" : row.status}`,
        details: {
          taskId: row.task_id,
          attemptId: row.attempt_id,
          status: row.status,
          lastError: row.last_error,
        },
      });
    }
    return observations;
  }

  async persistObservations(
    observations: FindingObservation[],
    fabricEpoch: number,
  ): Promise<HealthFinding[]> {
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      await client.query(
        "SELECT pg_advisory_xact_lock(hashtext('agentic-os-execution-fabric-observer'))",
      );
      await this.assertObserverLeadership(client, fabricEpoch);
      const observedFingerprints: string[] = [];
      const findings: HealthFinding[] = [];
      for (const observation of observations) {
        const fingerprint = findingFingerprint(observation);
        observedFingerprints.push(fingerprint);
        const result = await client.query<FindingRow>(
          `INSERT INTO fabric_health_findings(
             id,fingerprint,kind,scope_type,scope_id,severity,summary,details,
             fabric_epoch
           ) VALUES($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9)
           ON CONFLICT (fingerprint) DO UPDATE SET
             revision=CASE
               WHEN fabric_health_findings.severity IS DISTINCT FROM EXCLUDED.severity
                 OR fabric_health_findings.summary IS DISTINCT FROM EXCLUDED.summary
                 OR fabric_health_findings.details IS DISTINCT FROM EXCLUDED.details
                 OR fabric_health_findings.status IN ('resolved','cancelled')
               THEN fabric_health_findings.revision+1
               ELSE fabric_health_findings.revision
             END,
             severity=EXCLUDED.severity,
             status=CASE
               WHEN fabric_health_findings.status='acknowledged'
                 AND fabric_health_findings.severity IS NOT DISTINCT FROM EXCLUDED.severity
                 AND fabric_health_findings.summary IS NOT DISTINCT FROM EXCLUDED.summary
                 AND fabric_health_findings.details IS NOT DISTINCT FROM EXCLUDED.details
               THEN 'acknowledged'
               ELSE 'open'
             END,
             summary=EXCLUDED.summary,
             details=EXCLUDED.details,observed_count=fabric_health_findings.observed_count+1,
             last_observed_at=now(),resolved_at=NULL,cancelled_at=NULL,
             fabric_epoch=EXCLUDED.fabric_epoch,updated_at=now()
           RETURNING *`,
          [
            randomUUID(),
            fingerprint,
            observation.kind,
            observation.scopeType,
            observation.scopeId,
            observation.severity,
            observation.summary,
            JSON.stringify(observation.details),
            fabricEpoch,
          ],
        );
        const finding = findingFromRow(result.rows[0]!);
        findings.push(finding);
        if (finding.severity !== "info") {
          await client.query(
            `INSERT INTO fabric_alarm_outbox(
               id,finding_id,incident_key,revision,fabric_epoch,severity,payload
             ) VALUES($1,$2,$3,$4,$5,$6,$7::jsonb)
             ON CONFLICT (incident_key,revision) DO NOTHING`,
            [
              randomUUID(),
              finding.id,
              finding.fingerprint,
              finding.revision,
              fabricEpoch,
              finding.severity,
              JSON.stringify({
                schemaVersion: "execution-fabric-alarm/v1",
                findingId: finding.id,
                findingRevision: finding.revision,
                incidentKey: finding.fingerprint,
                kind: finding.kind,
                scopeType: finding.scopeType,
                scopeId: finding.scopeId,
                severity: finding.severity,
                summary: finding.summary,
                details: finding.details,
                fabricEpoch,
              }),
            ],
          );
        }
      }
      await client.query(
        `UPDATE fabric_health_findings
         SET status='resolved',resolved_at=now(),updated_at=now()
         WHERE status IN ('open','acknowledged')
           AND kind <> 'external_observation'
           AND NOT (fingerprint = ANY($1::text[]))`,
        [observedFingerprints],
      );
      await client.query(
        `UPDATE fabric_alarm_outbox a
         SET status='cancelled',updated_at=now()
         FROM fabric_health_findings f
         WHERE a.finding_id=f.id AND f.status='resolved'
           AND a.status IN ('pending','failed')`,
      );
      // Use the wall clock, not transaction-start time, so a lease that
      // expires during a slow observation pass rolls the entire transaction
      // back instead of letting a stale former leader resolve alarms.
      await this.assertObserverLeadership(client, fabricEpoch);
      await client.query("COMMIT");
      return findings;
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  }

  private async assertObserverLeadership(
    client: pg.PoolClient,
    expectedEpoch: number,
  ): Promise<void> {
    const state = await client.query<{
      current_epoch: string;
      leader_host_id: string | null;
      lease_valid: boolean;
    }>(
      `SELECT current_epoch,leader_host_id,
              leader_lease_expires_at > clock_timestamp() AS lease_valid
       FROM fabric_state
       WHERE singleton=true
       FOR UPDATE`,
    );
    const current = state.rows[0];
    if (
      !current ||
      Number(current.current_epoch) !== expectedEpoch ||
      current.leader_host_id !== this.hostId ||
      current.lease_valid !== true
    ) {
      throw new FencedError(
        "observer is not the current unexpired PostgreSQL leader",
      );
    }
  }

  async ingestExternalObservation(
    observation: ReliabilityObservation,
    fabricEpoch: number,
  ): Promise<ExternalObservationReceipt> {
    const canonical = canonicalJson(observation);
    const fingerprint = createHash("sha256")
      .update(
        canonicalJson({
          kind: "external_observation",
          source: observation.source,
          incidentKey: observation.incidentKey,
        }),
      )
      .digest("hex");
    const incidentKey = `external:${observation.source}:${observation.incidentKey}`;
    const details = {
      source: observation.source,
      incidentKey: observation.incidentKey,
      revision: observation.revision,
      code: observation.code,
      active: observation.active,
      evidence: observation.evidence,
      affected: observation.affected,
      runbook: observation.runbook,
      observedAt: observation.observedAt,
    };
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      await client.query("SELECT pg_advisory_xact_lock(hashtext($1))", [
        incidentKey,
      ]);
      const duplicate = await client.query<{
        observation: Record<string, unknown>;
        finding_id: string;
      }>(
        `SELECT observation,finding_id
         FROM fabric_external_observations
         WHERE source=$1 AND incident_key=$2 AND revision=$3`,
        [observation.source, observation.incidentKey, observation.revision],
      );
      if (duplicate.rows[0]) {
        if (canonicalJson(duplicate.rows[0].observation) !== canonical) {
          throw new ConflictError(
            "reliability observation revision was already used with different content",
          );
        }
        const existing = await client.query<FindingRow>(
          "SELECT * FROM fabric_health_findings WHERE id=$1",
          [duplicate.rows[0].finding_id],
        );
        await client.query("COMMIT");
        return {
          schemaVersion:
            "execution-fabric-reliability-observation-receipt/v1",
          admitted: false,
          idempotent: true,
          source: observation.source,
          incidentKey: observation.incidentKey,
          revision: observation.revision,
          finding: findingFromRow(existing.rows[0]!),
          alarmDerived: observation.active && observation.severity !== "info",
          recoveryRecorded: !observation.active,
          alarmStatus: observation.active ? null : "resolved_awaiting_ack",
        };
      }
      const latest = await client.query<{ revision: number | string | null }>(
        `SELECT max(revision) AS revision
         FROM fabric_external_observations
         WHERE source=$1 AND incident_key=$2`,
        [observation.source, observation.incidentKey],
      );
      if (
        latest.rows[0]?.revision != null &&
        observation.revision <= Number(latest.rows[0].revision)
      ) {
        throw new ConflictError(
          "reliability observation revision is stale",
        );
      }
      let findingResult: pg.QueryResult<FindingRow>;
      if (observation.active) {
        findingResult = await client.query<FindingRow>(
          `INSERT INTO fabric_health_findings(
             id,fingerprint,revision,kind,scope_type,scope_id,severity,summary,
             details,fabric_epoch
           ) VALUES($1,$2,$3,'external_observation','external',$4,$5,$6,$7::jsonb,$8)
           ON CONFLICT (fingerprint) DO UPDATE SET
             revision=EXCLUDED.revision,severity=EXCLUDED.severity,status='open',
             summary=EXCLUDED.summary,details=EXCLUDED.details,
             observed_count=fabric_health_findings.observed_count+1,
             last_observed_at=now(),resolved_at=NULL,cancelled_at=NULL,
             fabric_epoch=EXCLUDED.fabric_epoch,updated_at=now()
           WHERE fabric_health_findings.revision < EXCLUDED.revision
           RETURNING *`,
          [
            randomUUID(),
            fingerprint,
            observation.revision,
            incidentKey,
            observation.severity,
            observation.summary,
            JSON.stringify(details),
            fabricEpoch,
          ],
        );
      } else {
        findingResult = await client.query<FindingRow>(
          `UPDATE fabric_health_findings
           SET revision=$2,severity=$3,status='resolved',summary=$4,
             details=$5::jsonb,observed_count=observed_count+1,
             last_observed_at=now(),resolved_at=COALESCE(resolved_at,now()),
             cancelled_at=NULL,fabric_epoch=$6,updated_at=now()
           WHERE fingerprint=$1 AND kind='external_observation' AND revision < $2
           RETURNING *`,
          [
            fingerprint,
            observation.revision,
            observation.severity,
            observation.summary,
            JSON.stringify(details),
            fabricEpoch,
          ],
        );
        if (!findingResult.rows[0]) {
          throw new ConflictError(
            "recovery observation has no earlier active finding",
          );
        }
      }
      const finding = findingFromRow(findingResult.rows[0]!);
      if (observation.active && observation.severity !== "info") {
        await client.query(
          `INSERT INTO fabric_alarm_outbox(
             id,finding_id,incident_key,revision,fabric_epoch,severity,payload
           ) VALUES($1,$2,$3,$4,$5,$6,$7::jsonb)
           ON CONFLICT (incident_key,revision) DO NOTHING`,
          [
            randomUUID(),
            finding.id,
            incidentKey,
            observation.revision,
            fabricEpoch,
            observation.severity,
            JSON.stringify({
              schemaVersion: "execution-fabric-alarm/v1",
              findingId: finding.id,
              findingRevision: finding.revision,
              incidentKey,
              kind: finding.kind,
              scopeType: finding.scopeType,
              scopeId: finding.scopeId,
              severity: finding.severity,
              summary: finding.summary,
              details: finding.details,
              fabricEpoch,
            }),
          ],
        );
      } else if (!observation.active) {
        await client.query(
          `UPDATE fabric_repair_receipts
           SET status='cancelled',completed_at=now(),
             after_verification=$2::jsonb,
             error_summary='finding resolved by source recovery observation'
           WHERE finding_id=$1 AND status='running'`,
          [
            finding.id,
            JSON.stringify({
              recoveredByExternalObservation: true,
              source: observation.source,
              incidentKey: observation.incidentKey,
              revision: observation.revision,
            }),
          ],
        );
        await client.query(
          `UPDATE fabric_alarm_outbox
           SET status='resolved_awaiting_ack',claimed_by=NULL,claim_token=NULL,
             claim_expires_at=NULL,updated_at=now()
           WHERE finding_id=$1 AND status <> 'cancelled'`,
          [finding.id],
        );
        await client.query(
          `INSERT INTO fabric_external_recoveries(
             source,incident_key,revision,finding_id,fabric_epoch,observation
           ) VALUES($1,$2,$3,$4,$5,$6::jsonb)`,
          [
            observation.source,
            observation.incidentKey,
            observation.revision,
            finding.id,
            fabricEpoch,
            JSON.stringify(observation),
          ],
        );
      }
      await client.query(
        `INSERT INTO fabric_external_observations(
           source,incident_key,revision,active,observation,finding_id
         ) VALUES($1,$2,$3,$4,$5::jsonb,$6)`,
        [
          observation.source,
          observation.incidentKey,
          observation.revision,
          observation.active,
          JSON.stringify(observation),
          finding.id,
        ],
      );
      await client.query("COMMIT");
      return {
        schemaVersion: "execution-fabric-reliability-observation-receipt/v1",
        admitted: true,
        idempotent: false,
        source: observation.source,
        incidentKey: observation.incidentKey,
        revision: observation.revision,
        finding,
        alarmDerived: observation.active && observation.severity !== "info",
        recoveryRecorded: !observation.active,
        alarmStatus: observation.active ? null : "resolved_awaiting_ack",
      };
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  }

  async openFindings(): Promise<HealthFinding[]> {
    const result = await this.pool.query<FindingRow>(
      `SELECT * FROM fabric_health_findings
       WHERE status='open'
       ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
         last_observed_at,id`,
    );
    return result.rows.map(findingFromRow);
  }

  async finding(id: string): Promise<HealthFinding | null> {
    const result = await this.pool.query<FindingRow>(
      "SELECT * FROM fabric_health_findings WHERE id=$1",
      [id],
    );
    return result.rows[0] ? findingFromRow(result.rows[0]) : null;
  }

  async beginRepair(
    finding: HealthFinding,
    action: RepairAction,
    policy: RepairPolicy,
    actor: string,
    beforeVerification: Record<string, unknown>,
  ): Promise<RepairReceipt> {
    if (!policy.allowActions.includes(action)) {
      throw new Error(`repair action ${action} is not allow-listed`);
    }
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      const state = await client.query<{
        current_epoch: string;
        leader_host_id: string | null;
        leader_lease_expires_at: string | Date | null;
      }>(
        `SELECT current_epoch,leader_host_id,leader_lease_expires_at
         FROM fabric_state WHERE singleton=true FOR UPDATE`,
      );
      const current = state.rows[0];
      const epoch = Number(current?.current_epoch ?? 1);
      assertFreshEpoch(finding.fabricEpoch, epoch);
      if (
        current?.leader_host_id !== this.hostId ||
        !current.leader_lease_expires_at ||
        new Date(current.leader_lease_expires_at).getTime() <= Date.now()
      ) {
        throw new FencedError("healer is not the current unexpired leader");
      }
      const locked = await client.query<FindingRow>(
        `SELECT * FROM fabric_health_findings WHERE id=$1 FOR UPDATE`,
        [finding.id],
      );
      if (!locked.rowCount || locked.rows[0]?.status !== "open") {
        throw new NotFoundError("open finding not found");
      }
      const idempotencyKey = `${finding.id}:${finding.revision}:${action}`;
      const existing = await client.query<Record<string, unknown>>(
        "SELECT * FROM fabric_repair_receipts WHERE idempotency_key=$1",
        [idempotencyKey],
      );
      if (existing.rows[0]) {
        await client.query("COMMIT");
        return receiptFromRow(existing.rows[0]);
      }
      const budget = await client.query<{ count: string }>(
        `SELECT count(*)::text AS count FROM fabric_repair_receipts
         WHERE action=$1 AND started_at >= now() - interval '1 hour'
           AND status IN ('running','succeeded','failed')`,
        [action],
      );
      if (Number(budget.rows[0]?.count ?? 0) >= policy.maxRepairsPerHour) {
        throw new Error(`hourly repair budget exhausted for ${action}`);
      }
      const cooldown = await client.query(
        `SELECT 1 FROM fabric_repair_receipts r
         JOIN fabric_health_findings f ON f.id=r.finding_id
         WHERE f.fingerprint=$1 AND r.action=$2 AND r.status='succeeded'
           AND r.completed_at > now()-($3*interval '1 second')
         LIMIT 1`,
        [finding.fingerprint, action, policy.cooldownSeconds],
      );
      if (cooldown.rowCount) {
        throw new Error(`repair cooldown active for ${action}`);
      }
      const inserted = await client.query<Record<string, unknown>>(
        `INSERT INTO fabric_repair_receipts(
           id,idempotency_key,finding_id,finding_revision,action,status,actor,
           fabric_epoch,before_verification
         ) VALUES($1,$2,$3,$4,$5,'running',$6,$7,$8::jsonb)
         RETURNING *`,
        [
          randomUUID(),
          idempotencyKey,
          finding.id,
          finding.revision,
          action,
          actor,
          epoch,
          JSON.stringify(beforeVerification),
        ],
      );
      await client.query("COMMIT");
      return receiptFromRow(inserted.rows[0]!);
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  }

  async finishRepair(
    receiptId: string,
    status: "succeeded" | "failed" | "skipped",
    afterVerification: Record<string, unknown>,
    errorSummary?: string,
  ): Promise<RepairReceipt> {
    const result = await this.pool.query<Record<string, unknown>>(
      `UPDATE fabric_repair_receipts
       SET status=$2,after_verification=$3::jsonb,error_summary=$4,
         completed_at=now()
       WHERE id=$1 AND status='running' RETURNING *`,
      [receiptId, status, JSON.stringify(afterVerification), errorSummary ?? null],
    );
    if (!result.rows[0]) throw new FencedError("repair receipt is no longer running");
    return receiptFromRow(result.rows[0]);
  }

  async snapshot(): Promise<ReliabilitySnapshot> {
    const [
      findings,
      alarms,
      repairs,
      times,
      activeFindings,
      unresolvedAlarms,
      recentRepairs,
    ] = await Promise.all([
      this.pool.query<{ status: string; count: string }>(
        "SELECT status,count(*)::text AS count FROM fabric_health_findings GROUP BY status",
      ),
      this.pool.query<{ status: string; count: string }>(
        "SELECT status,count(*)::text AS count FROM fabric_alarm_outbox GROUP BY status",
      ),
      this.pool.query<{ status: string; count: string }>(
        "SELECT status,count(*)::text AS count FROM fabric_repair_receipts GROUP BY status",
      ),
      this.pool.query<{
        last_observation_at: string | Date | null;
        last_repair_at: string | Date | null;
      }>(
        `SELECT
           (SELECT max(last_observed_at) FROM fabric_health_findings) AS last_observation_at,
           (SELECT max(completed_at) FROM fabric_repair_receipts) AS last_repair_at`,
      ),
      this.pool.query<FindingRow>(
        `SELECT * FROM fabric_health_findings
         WHERE status IN ('open','acknowledged')
         ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
           last_observed_at DESC,id
         LIMIT 100`,
      ),
      this.pool.query<Record<string, unknown>>(
        `SELECT id,finding_id,incident_key,revision,fabric_epoch,severity,status,
           payload,attempt_count,last_error,created_at,updated_at
         FROM fabric_alarm_outbox
         WHERE status IN (
           'pending','processing','failed','dead_lettered','resolved_awaiting_ack'
         )
         ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
           updated_at DESC,id
         LIMIT 100`,
      ),
      this.pool.query<Record<string, unknown>>(
        `SELECT * FROM fabric_repair_receipts
         ORDER BY started_at DESC,id
         LIMIT 100`,
      ),
    ]);
    return {
      schemaVersion: "execution-fabric-reliability-status/v1",
      findings: Object.fromEntries(
        findings.rows.map((row) => [row.status, Number(row.count)]),
      ),
      alarms: Object.fromEntries(
        alarms.rows.map((row) => [row.status, Number(row.count)]),
      ),
      repairs: Object.fromEntries(
        repairs.rows.map((row) => [row.status, Number(row.count)]),
      ),
      lastObservationAt: times.rows[0]?.last_observation_at
        ? iso(times.rows[0].last_observation_at)
        : null,
      lastRepairAt: times.rows[0]?.last_repair_at
        ? iso(times.rows[0].last_repair_at)
        : null,
      activeFindings: activeFindings.rows.map(findingFromRow),
      unresolvedAlarms: unresolvedAlarms.rows.map((row) => ({
        id: String(row.id),
        findingId: String(row.finding_id),
        incidentKey: String(row.incident_key),
        revision: Number(row.revision),
        fabricEpoch: Number(row.fabric_epoch),
        severity: String(row.severity),
        status: String(row.status),
        payload: (row.payload ?? {}) as Record<string, unknown>,
        attemptCount: Number(row.attempt_count ?? 0),
        lastErrorSummary: row.last_error
          ? String(row.last_error)
          : null,
        createdAt: iso(row.created_at as string | Date),
        updatedAt: iso(row.updated_at as string | Date),
      })),
      recentRepairReceipts: recentRepairs.rows.map(receiptFromRow),
    };
  }

  async acknowledgeFinding(
    findingId: string,
    actor: string,
  ): Promise<HealthFinding> {
    const result = await this.pool.query<FindingRow>(
      `UPDATE fabric_health_findings
       SET status=CASE WHEN status='open' THEN 'acknowledged' ELSE status END,
         acknowledged_at=now(),acknowledged_by=$2,
         updated_at=now()
       WHERE id=$1 AND status IN ('open','resolved') RETURNING *`,
      [findingId, actor],
    );
    if (!result.rows[0]) {
      throw new NotFoundError("open or resolved finding not found");
    }
    await this.pool.query(
      `UPDATE fabric_alarm_outbox
       SET status='acknowledged',updated_at=now()
       WHERE finding_id=$1
         AND status IN (
           'pending','failed','dead_lettered','resolved_awaiting_ack'
         )`,
      [findingId],
    );
    return findingFromRow(result.rows[0]);
  }

  async claimAlarms(
    consumerId: string,
    limit: number,
    leaseSeconds: number,
  ): Promise<AlarmAssignment[]> {
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      await client.query(
        `UPDATE fabric_alarm_outbox
         SET attempt_count=attempt_count+1,
           status=CASE
             WHEN attempt_count+1 >= max_attempts THEN 'dead_lettered'
             ELSE 'pending'
           END,
           available_at=CASE
             WHEN attempt_count+1 >= max_attempts THEN now()
             ELSE now() + (
               LEAST(86400,60*power(2,LEAST(attempt_count,10))::integer)
               * interval '1 second'
             )
           END,
           claimed_by=NULL,claim_token=NULL,claim_expires_at=NULL,
           last_error='alarm dispatcher claim expired',updated_at=now()
         WHERE status='processing' AND claim_expires_at <= now()`,
      );
      const candidates = await client.query<{
        id: string;
        finding_id: string;
        incident_key: string;
        revision: number;
        fabric_epoch: string | number;
        severity: FindingSeverity;
        payload: Record<string, unknown>;
      }>(
        `SELECT a.id,a.finding_id,a.incident_key,a.revision,a.fabric_epoch,
           a.severity,a.payload
         FROM fabric_alarm_outbox a
         CROSS JOIN fabric_state s
         WHERE a.status='pending' AND a.available_at <= now()
           AND s.singleton=true AND a.fabric_epoch=s.current_epoch
         ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
           created_at,id
         FOR UPDATE SKIP LOCKED LIMIT $1`,
        [limit],
      );
      const assignments: AlarmAssignment[] = [];
      for (const row of candidates.rows) {
        const claimToken = randomUUID();
        const claimed = await client.query<{ claim_expires_at: string | Date }>(
          `UPDATE fabric_alarm_outbox
           SET status='processing',claimed_by=$2,claim_token=$3,
             claim_expires_at=now()+($4*interval '1 second'),updated_at=now()
           WHERE id=$1 RETURNING claim_expires_at`,
          [row.id, consumerId, claimToken, leaseSeconds],
        );
        assignments.push({
          alarmId: row.id,
          findingId: row.finding_id,
          incidentKey: row.incident_key,
          revision: Number(row.revision),
          fabricEpoch: Number(row.fabric_epoch),
          severity: row.severity,
          payload: row.payload ?? {},
          claimToken,
          claimExpiresAt: iso(claimed.rows[0]!.claim_expires_at),
        });
      }
      await client.query("COMMIT");
      return assignments;
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  }

  async deliverAlarm(
    alarmId: string,
    consumerId: string,
    claimToken: string,
    fabricEpoch: number,
    deliveryReceipt: Record<string, unknown>,
  ): Promise<void> {
    const result = await this.pool.query(
      `UPDATE fabric_alarm_outbox a
       SET status='delivered',delivered_at=now(),delivery_receipt=$5::jsonb,
         claimed_by=NULL,claim_token=NULL,claim_expires_at=NULL,updated_at=now()
       FROM fabric_state s
       WHERE a.id=$1 AND a.claimed_by=$2 AND a.claim_token=$3
         AND a.fabric_epoch=$4 AND s.singleton=true AND s.current_epoch=$4
         AND a.status='processing' AND a.claim_expires_at > now()
       RETURNING a.id`,
      [
        alarmId,
        consumerId,
        claimToken,
        fabricEpoch,
        JSON.stringify(deliveryReceipt),
      ],
    );
    if (!result.rowCount) throw new FencedError("alarm delivery claim is stale");
  }

  async failAlarm(
    alarmId: string,
    consumerId: string,
    claimToken: string,
    fabricEpoch: number,
    errorSummary: string,
  ): Promise<void> {
    const result = await this.pool.query(
      `UPDATE fabric_alarm_outbox a
       SET attempt_count=attempt_count+1,
         status=CASE
           WHEN attempt_count+1 >= max_attempts THEN 'dead_lettered'
           ELSE 'pending'
         END,
         available_at=CASE
           WHEN attempt_count+1 >= max_attempts THEN now()
           ELSE now() + (
             LEAST(86400,60*power(2,LEAST(attempt_count,10))::integer)
             * interval '1 second'
           )
         END,
         claimed_by=NULL,claim_token=NULL,claim_expires_at=NULL,
         last_error=$5,updated_at=now()
       FROM fabric_state s
       WHERE a.id=$1 AND a.claimed_by=$2 AND a.claim_token=$3
         AND a.fabric_epoch=$4 AND s.singleton=true AND s.current_epoch=$4
         AND a.status='processing' AND a.claim_expires_at > now()
       RETURNING a.id`,
      [alarmId, consumerId, claimToken, fabricEpoch, errorSummary],
    );
    if (!result.rowCount) throw new FencedError("alarm failure claim is stale");
  }

  async replayEffect(
    effectId: string,
    actor: string,
    idempotencyKey: string,
  ): Promise<Record<string, unknown>> {
    return this.operatorMutation(
      "effect.replay",
      "effect",
      effectId,
      actor,
      idempotencyKey,
      async (client, epoch) => {
        const before = await client.query(
          "SELECT * FROM fabric_effect_outbox WHERE id=$1 FOR UPDATE",
          [effectId],
        );
        if (!before.rows[0]) throw new NotFoundError("effect not found");
        if (!["failed", "dead_lettered", "cancelled"].includes(before.rows[0].status)) {
          throw new Error("only failed, dead-lettered, or cancelled effects can be replayed");
        }
        const after = await client.query(
          `UPDATE fabric_effect_outbox
           SET status='pending',attempt_count=0,fabric_epoch=$2,available_at=now(),
             claimed_by=NULL,claim_token=NULL,claimed_at=NULL,claim_expires_at=NULL,
             dead_lettered_at=NULL,cancelled_at=NULL,last_error=NULL,
             delivered_at=NULL,provider_receipt=NULL,updated_at=now()
           WHERE id=$1 RETURNING *`,
          [effectId, epoch],
        );
        return { before: before.rows[0], after: after.rows[0] };
      },
    );
  }

  async cancelTask(
    taskId: string,
    actor: string,
    idempotencyKey: string,
  ): Promise<Record<string, unknown>> {
    return this.operatorMutation(
      "task.cancel",
      "task",
      taskId,
      actor,
      idempotencyKey,
      async (client) => {
        const before = await client.query(
          "SELECT * FROM fabric_tasks WHERE id=$1 FOR UPDATE",
          [taskId],
        );
        if (!before.rows[0]) throw new NotFoundError("task not found");
        if (!["queued", "running"].includes(before.rows[0].status)) {
          throw new Error("only queued or running tasks can be cancelled");
        }
        await client.query(
          `UPDATE fabric_attempts SET status='fenced',finished_at=now(),
             error_code='operator_cancelled',error_summary='cancelled by operator'
           WHERE task_id=$1 AND status='running'`,
          [taskId],
        );
        await client.query(
          `UPDATE fabric_runs r SET status='expired',finished_at=now()
           FROM fabric_attempts a
           WHERE a.run_id=r.id AND a.task_id=$1 AND r.status='running'`,
          [taskId],
        );
        const after = await client.query(
          `UPDATE fabric_tasks SET status='cancelled',completed_at=now(),
             delivery_published_at=NULL,last_error_code='operator_cancelled',
             last_error_summary='cancelled by operator',updated_at=now()
           WHERE id=$1 RETURNING *`,
          [taskId],
        );
        return { before: before.rows[0], after: after.rows[0] };
      },
    );
  }

  async requeueTask(
    taskId: string,
    actor: string,
    idempotencyKey: string,
  ): Promise<Record<string, unknown>> {
    return this.operatorMutation(
      "task.requeue",
      "task",
      taskId,
      actor,
      idempotencyKey,
      async (client) => {
        const before = await client.query(
          "SELECT * FROM fabric_tasks WHERE id=$1 FOR UPDATE",
          [taskId],
        );
        if (!before.rows[0]) throw new NotFoundError("task not found");
        if (!["failed", "dead_lettered", "cancelled"].includes(before.rows[0].status)) {
          throw new Error("only failed, dead-lettered, or cancelled tasks can be requeued");
        }
        const after = await client.query(
          `UPDATE fabric_tasks SET status='queued',attempt_count=0,
             available_at=now(),delivery_published_at=NULL,completed_at=NULL,
             last_error_code=NULL,last_error_summary=NULL,updated_at=now()
           WHERE id=$1 RETURNING *`,
          [taskId],
        );
        return { before: before.rows[0], after: after.rows[0] };
      },
    );
  }

  async drainQueue(
    queue: string,
    actor: string,
    idempotencyKey: string,
  ): Promise<Record<string, unknown>> {
    return this.operatorMutation(
      "queue.drain",
      "queue",
      queue,
      actor,
      idempotencyKey,
      async (client) => {
        const before = await client.query<{ count: string }>(
          `SELECT count(*)::text AS count FROM fabric_tasks
           WHERE queue_name=$1 AND status='queued'`,
          [queue],
        );
        const after = await client.query(
          `UPDATE fabric_tasks SET status='cancelled',completed_at=now(),
             delivery_published_at=NULL,last_error_code='queue_drained',
             last_error_summary='queue drained by operator',updated_at=now()
           WHERE queue_name=$1 AND status='queued' RETURNING id`,
          [queue],
        );
        return {
          before: { queued: Number(before.rows[0]?.count ?? 0) },
          after: { cancelled: after.rowCount ?? 0 },
        };
      },
    );
  }

  private async operatorMutation(
    action: string,
    targetType: string,
    targetId: string,
    actor: string,
    idempotencyKey: string,
    mutation: (
      client: pg.PoolClient,
      epoch: number,
    ) => Promise<{ before: Record<string, unknown>; after: Record<string, unknown> }>,
  ): Promise<Record<string, unknown>> {
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      const existing = await client.query(
        "SELECT * FROM fabric_operator_receipts WHERE idempotency_key=$1",
        [idempotencyKey],
      );
      if (existing.rows[0]) {
        const row = existing.rows[0] as Record<string, unknown>;
        if (
          row.action !== action ||
          row.target_type !== targetType ||
          row.target_id !== targetId ||
          row.actor !== actor
        ) {
          throw new Error("operator idempotency key conflicts with another request");
        }
        await client.query("COMMIT");
        return row;
      }
      const state = await client.query<{
        current_epoch: string;
        leader_host_id: string | null;
        leader_lease_expires_at: string | Date | null;
      }>(
        `SELECT current_epoch,leader_host_id,leader_lease_expires_at
         FROM fabric_state WHERE singleton=true FOR UPDATE`,
      );
      const current = state.rows[0];
      if (
        current?.leader_host_id !== this.hostId ||
        !current.leader_lease_expires_at ||
        new Date(current.leader_lease_expires_at).getTime() <= Date.now()
      ) {
        throw new FencedError("operator mutation is fenced by leadership");
      }
      const epoch = Number(current.current_epoch);
      const result = await mutation(client, epoch);
      const receipt = await client.query(
        `INSERT INTO fabric_operator_receipts(
           id,idempotency_key,action,target_type,target_id,actor,fabric_epoch,
           status,before_state,after_state
         ) VALUES($1,$2,$3,$4,$5,$6,$7,'succeeded',$8::jsonb,$9::jsonb)
         RETURNING *`,
        [
          randomUUID(),
          idempotencyKey,
          action,
          targetType,
          targetId,
          actor,
          epoch,
          JSON.stringify(result.before),
          JSON.stringify(result.after),
        ],
      );
      await client.query("COMMIT");
      return receipt.rows[0] as Record<string, unknown>;
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  }
}

const ACTION_BY_FINDING: Partial<Record<FindingKind, RepairAction>> = {
  expired_attempts: "reconcile_expired_attempts",
  missing_delivery: "reconstruct_delivery",
  expired_effect_claims: "recover_effect_claim",
};

export class DeterministicHealer {
  constructor(
    private readonly store: PostgresReliabilityStore,
    private readonly fabric: ExecutionFabric,
    private readonly policy: RepairPolicy,
    private readonly actor: string,
  ) {}

  async runOnce(): Promise<RepairReceipt[]> {
    const receipts: RepairReceipt[] = [];
    for (const finding of await this.store.openFindings()) {
      const action = ACTION_BY_FINDING[finding.kind];
      if (!action || !this.policy.allowActions.includes(action)) continue;
      const before = await this.verify(finding);
      let receipt: RepairReceipt;
      try {
        receipt = await this.store.beginRepair(
          finding,
          action,
          this.policy,
          this.actor,
          before,
        );
      } catch (error) {
        if (
          error instanceof Error &&
          (error.message.includes("cooldown") ||
            error.message.includes("budget") ||
            error.message.includes("not found"))
        ) {
          continue;
        }
        throw error;
      }
      if (receipt.status !== "running") {
        receipts.push(receipt);
        continue;
      }
      try {
        if (action === "reconstruct_delivery") {
          await this.fabric.dispatchAvailable();
        } else {
          await this.fabric.reconcile();
        }
        const after = await this.verify(finding);
        receipt = await this.store.finishRepair(
          receipt.id,
          after.active ? "failed" : "succeeded",
          after,
          after.active ? "finding remained active after deterministic repair" : undefined,
        );
      } catch (error) {
        receipt = await this.store.finishRepair(
          receipt.id,
          "failed",
          await this.verify(finding).catch(() => ({ verificationUnavailable: true })),
          error instanceof Error ? error.message : "unknown healer failure",
        );
      }
      receipts.push(receipt);
    }
    return receipts;
  }

  private async verify(
    finding: HealthFinding,
  ): Promise<Record<string, unknown> & { active: boolean }> {
    const active = (await this.store.collect(
      this.fabric.policy.snapshot().appliedFingerprint,
    )).find(
      (observation) =>
        findingFingerprint(observation) === finding.fingerprint,
    );
    return {
      active: Boolean(active),
      checkedAt: new Date().toISOString(),
      ...(active ? { observation: active } : {}),
    };
  }
}
