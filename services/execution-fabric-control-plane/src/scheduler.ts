import { randomUUID } from "node:crypto";
import type pg from "pg";
import type { ExecutionFabric } from "./fabric.js";
import { FencedError } from "./ledger.js";

export type ScheduleDefinition = {
  id: string;
  namespace: string;
  queue: string;
  taskType: string;
  payload: Record<string, unknown>;
  requiredCapabilities: string[];
  priority: number;
  maxAttempts: number;
  intervalSeconds: number;
  enabled: boolean;
  nextOccurrenceAt: string;
};

export type ScheduleOccurrence = {
  occurrenceId: string;
  schedule: ScheduleDefinition;
  scheduledFor: string;
  idempotencyKey: string;
  fabricEpoch: number;
  claimToken: string;
};

function iso(value: string | Date): string {
  return new Date(value).toISOString();
}

function definition(row: Record<string, unknown>): ScheduleDefinition {
  return {
    id: String(row.id),
    namespace: String(row.namespace),
    queue: String(row.queue_name),
    taskType: String(row.task_type),
    payload: (row.payload ?? {}) as Record<string, unknown>,
    requiredCapabilities: (row.required_capabilities ?? []) as string[],
    priority: Number(row.priority),
    maxAttempts: Number(row.max_attempts),
    intervalSeconds: Number(row.interval_seconds),
    enabled: Boolean(row.enabled),
    nextOccurrenceAt: iso(row.next_occurrence_at as string),
  };
}

export function scheduleIdempotencyKey(
  scheduleId: string,
  scheduledFor: string,
): string {
  return `schedule:${scheduleId}:${new Date(scheduledFor).toISOString()}`;
}

export class PostgresScheduler {
  constructor(
    private readonly pool: pg.Pool,
    private readonly fabric: ExecutionFabric,
    private readonly hostId: string,
    private readonly claimSeconds = 60,
  ) {}

  async upsert(input: ScheduleDefinition): Promise<ScheduleDefinition> {
    this.fabric.assertSchedulerMutation();
    const normalized = this.fabric.policy.normalizeAdmission({
      namespace: input.namespace,
      queue: input.queue,
      taskType: input.taskType,
      idempotencyKey: `schedule-definition:${input.id}`,
      payload: input.payload,
      requiredCapabilities: input.requiredCapabilities,
      priority: input.priority,
      maxAttempts: input.maxAttempts,
    });
    const result = await this.pool.query(
      `INSERT INTO fabric_schedules(
         id,namespace,queue_name,task_type,payload,required_capabilities,
         priority,max_attempts,interval_seconds,enabled,next_occurrence_at
       )
       SELECT $1,$2,$3,$4,$5::jsonb,$6::jsonb,$7,$8,$9,$10,$11
       FROM fabric_state state
       WHERE state.singleton=true AND state.leader_host_id=$12
         AND state.leader_lease_expires_at>now()
       ON CONFLICT(id) DO UPDATE SET
         namespace=EXCLUDED.namespace,queue_name=EXCLUDED.queue_name,
         task_type=EXCLUDED.task_type,payload=EXCLUDED.payload,
         required_capabilities=EXCLUDED.required_capabilities,
         priority=EXCLUDED.priority,max_attempts=EXCLUDED.max_attempts,
         interval_seconds=EXCLUDED.interval_seconds,enabled=EXCLUDED.enabled,
         next_occurrence_at=EXCLUDED.next_occurrence_at,updated_at=now()
       RETURNING *`,
      [
        input.id,
        input.namespace,
        input.queue,
        input.taskType,
        JSON.stringify(normalized.payload),
        JSON.stringify(normalized.requiredCapabilities),
        normalized.priority,
        normalized.maxAttempts,
        input.intervalSeconds,
        input.enabled,
        input.nextOccurrenceAt,
        this.hostId,
      ],
    );
    if (!result.rowCount) {
      throw new FencedError("schedule mutation requires the current unexpired leader");
    }
    return definition(result.rows[0] as Record<string, unknown>);
  }

  async setEnabled(id: string, enabled: boolean): Promise<void> {
    this.fabric.assertSchedulerMutation();
    const result = await this.pool.query(
      `UPDATE fabric_schedules schedule SET enabled=$2,updated_at=now()
       FROM fabric_state state
       WHERE schedule.id=$1 AND state.singleton=true
         AND state.leader_host_id=$3 AND state.leader_lease_expires_at>now()
       RETURNING schedule.id`,
      [id, enabled, this.hostId],
    );
    if (!result.rowCount) {
      throw new FencedError("schedule not found or mutation is fenced");
    }
  }

  async snapshot(limit = 200): Promise<Array<Record<string, unknown>>> {
    const result = await this.pool.query(
      `SELECT schedule.*,
         count(occurrence.id) FILTER (
           WHERE occurrence.status='pending'
         )::int AS pending,
         count(occurrence.id) FILTER (
           WHERE occurrence.status='processing'
         )::int AS processing,
         count(occurrence.id) FILTER (
           WHERE occurrence.status='failed'
         )::int AS failed,
         count(occurrence.id) FILTER (
           WHERE occurrence.status='admitted'
         )::int AS admitted,
         max(occurrence.updated_at) AS last_occurrence_at
       FROM fabric_schedules schedule
       LEFT JOIN fabric_schedule_occurrences occurrence
         ON occurrence.schedule_id=schedule.id
       GROUP BY schedule.id
       ORDER BY schedule.enabled DESC,schedule.next_occurrence_at,schedule.id
       LIMIT $1`,
      [limit],
    );
    return result.rows.map((raw) => {
      const row = raw as Record<string, unknown>;
      return {
        ...definition(row),
        pending: Number(row.pending),
        processing: Number(row.processing),
        failed: Number(row.failed),
        admitted: Number(row.admitted),
        lastOccurrenceAt: row.last_occurrence_at
          ? iso(row.last_occurrence_at as string)
          : null,
      };
    });
  }

  async claimDue(limit = 20): Promise<ScheduleOccurrence[]> {
    this.fabric.assertSchedulerMutation();
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      await client.query(
        "SELECT pg_advisory_xact_lock(hashtext('agentic-os-execution-fabric-scheduler'))",
      );
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
        throw new FencedError("scheduler is not the current unexpired leader");
      }
      const epoch = Number(current.current_epoch);
      await client.query(
        `UPDATE fabric_schedule_occurrences
         SET status='fenced',claim_token=NULL,claim_expires_at=NULL,updated_at=now()
         WHERE fabric_epoch<>$1 AND status IN ('pending','processing')`,
        [epoch],
      );
      const due = await client.query(
        `SELECT * FROM fabric_schedules
         WHERE enabled=true AND next_occurrence_at<=now()
         ORDER BY next_occurrence_at,id
         FOR UPDATE SKIP LOCKED LIMIT $1`,
        [limit],
      );
      for (const row of due.rows as Array<Record<string, unknown>>) {
        const scheduledFor = iso(row.next_occurrence_at as string);
        await client.query(
          `INSERT INTO fabric_schedule_occurrences(
             id,schedule_id,scheduled_for,idempotency_key,fabric_epoch
           ) VALUES($1,$2,$3,$4,$5)
           ON CONFLICT(schedule_id,scheduled_for,fabric_epoch) DO NOTHING`,
          [
            randomUUID(),
            row.id,
            scheduledFor,
            scheduleIdempotencyKey(String(row.id), scheduledFor),
            epoch,
          ],
        );
        await client.query(
          `UPDATE fabric_schedules
           SET next_occurrence_at=GREATEST(
             next_occurrence_at+(interval_seconds*interval '1 second'),
             now()+(interval_seconds*interval '1 second')
           ),updated_at=now()
           WHERE id=$1`,
          [row.id],
        );
      }
      const pending = await client.query(
        `SELECT o.id AS occurrence_id,o.scheduled_for,o.idempotency_key,
           s.*
         FROM fabric_schedule_occurrences o
         JOIN fabric_schedules s ON s.id=o.schedule_id
         WHERE o.fabric_epoch=$1 AND o.available_at<=now()
           AND (
             o.status='pending' OR
             (o.status='processing' AND o.claim_expires_at<=now())
           )
         ORDER BY o.scheduled_for,o.id
         FOR UPDATE OF o SKIP LOCKED LIMIT $2`,
        [epoch, limit],
      );
      const occurrences: ScheduleOccurrence[] = [];
      for (const row of pending.rows as Array<Record<string, unknown>>) {
        const claimToken = randomUUID();
        await client.query(
          `UPDATE fabric_schedule_occurrences
           SET status='processing',claim_token=$2,
             claim_expires_at=now()+($3*interval '1 second'),updated_at=now()
           WHERE id=$1`,
          [row.occurrence_id, claimToken, this.claimSeconds],
        );
        occurrences.push({
          occurrenceId: String(row.occurrence_id),
          schedule: definition(row),
          scheduledFor: iso(row.scheduled_for as string),
          idempotencyKey: String(row.idempotency_key),
          fabricEpoch: epoch,
          claimToken,
        });
      }
      await client.query("COMMIT");
      return occurrences;
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  }

  async runOnce(limit = 20): Promise<{
    claimed: number;
    admitted: number;
    failed: number;
  }> {
    const occurrences = await this.claimDue(limit);
    let admitted = 0;
    let failed = 0;
    for (const occurrence of occurrences) {
      try {
        const result = await this.fabric.admit({
          namespace: occurrence.schedule.namespace,
          queue: occurrence.schedule.queue,
          taskType: occurrence.schedule.taskType,
          idempotencyKey: occurrence.idempotencyKey,
          payload: occurrence.schedule.payload,
          requiredCapabilities: occurrence.schedule.requiredCapabilities,
          priority: occurrence.schedule.priority,
          maxAttempts: occurrence.schedule.maxAttempts,
        });
        await this.finish(
          occurrence,
          "admitted",
          result.task.id,
        );
        admitted += 1;
      } catch (error) {
        await this.fail(occurrence, error);
        failed += 1;
      }
    }
    return { claimed: occurrences.length, admitted, failed };
  }

  private async finish(
    occurrence: ScheduleOccurrence,
    status: "admitted",
    taskId: string,
  ): Promise<void> {
    const result = await this.pool.query(
      `UPDATE fabric_schedule_occurrences o
       SET status=$4,task_id=$5,claim_token=NULL,claim_expires_at=NULL,
         last_error=NULL,updated_at=now()
       FROM fabric_state s
       WHERE o.id=$1 AND o.claim_token=$2 AND o.fabric_epoch=$3
         AND s.singleton=true AND s.current_epoch=$3
         AND s.leader_host_id=$6 AND s.leader_lease_expires_at>now()
       RETURNING o.id`,
      [
        occurrence.occurrenceId,
        occurrence.claimToken,
        occurrence.fabricEpoch,
        status,
        taskId,
        this.hostId,
      ],
    );
    if (!result.rowCount) throw new FencedError("schedule occurrence claim is stale");
  }

  private async fail(
    occurrence: ScheduleOccurrence,
    error: unknown,
  ): Promise<void> {
    const result = await this.pool.query(
      `UPDATE fabric_schedule_occurrences o
       SET attempt_count=attempt_count+1,
         status=CASE WHEN attempt_count+1>=8 THEN 'failed' ELSE 'pending' END,
         available_at=now()+(
           LEAST(3600,15*power(2,LEAST(attempt_count,8))::integer)
           * interval '1 second'
         ),
         claim_token=NULL,claim_expires_at=NULL,last_error=$4,updated_at=now()
       FROM fabric_state s
       WHERE o.id=$1 AND o.claim_token=$2 AND o.fabric_epoch=$3
         AND s.singleton=true AND s.current_epoch=$3
         AND s.leader_host_id=$5 AND s.leader_lease_expires_at>now()
       RETURNING o.id`,
      [
        occurrence.occurrenceId,
        occurrence.claimToken,
        occurrence.fabricEpoch,
        error instanceof Error ? error.message.slice(0, 2048) : "schedule admission failed",
        this.hostId,
      ],
    );
    if (!result.rowCount) throw new FencedError("schedule occurrence claim is stale");
  }
}
