import { randomUUID } from "node:crypto";
import type { Pool } from "pg";

export const ROLE_ENTRYPOINTS = {
  api: "dist/src/main.js",
  observer: "dist/src/observer-main.js",
  healer: "dist/src/healer-main.js",
  scheduler: "dist/src/scheduler-main.js",
} as const;

export type ServiceRole = keyof typeof ROLE_ENTRYPOINTS;
export type PeriodicServiceRole = Exclude<ServiceRole, "api">;

export type RoleHealthSnapshot = {
  hostId: string;
  role: PeriodicServiceRole;
  instanceId: string;
  startedAt: string;
  approvedPolicyFingerprint: string | null;
  appliedPolicyFingerprint: string | null;
  lastSuccessfulTickAt: string | null;
  lastTickAt: string | null;
  lastError: string | null;
  consecutiveFailures: number;
  updatedAt: string;
};

export type RoleHealthEvaluation = RoleHealthSnapshot & {
  status: "healthy" | "degraded" | "unhealthy";
  reason: string | null;
};

export class RoleHealthInstanceReplacedError extends Error {}

export function roleHealthEvaluationOptions(): {
  failureThreshold: number;
  maxTickAgeSeconds: number;
  startupGraceSeconds: number;
} {
  return {
    failureThreshold: boundedIntegerEnvironment(
      "FABRIC_ROLE_HEALTH_FAILURE_THRESHOLD",
      3,
      1,
      100,
    ),
    maxTickAgeSeconds: boundedIntegerEnvironment(
      "FABRIC_ROLE_HEALTH_MAX_AGE_SECONDS",
      60,
      1,
      86400,
    ),
    startupGraceSeconds: boundedIntegerEnvironment(
      "FABRIC_ROLE_HEALTH_STARTUP_GRACE_SECONDS",
      90,
      1,
      86400,
    ),
  };
}

function iso(value: Date | string | null): string | null {
  if (value === null) return null;
  return new Date(value).toISOString();
}

export function evaluateRoleHealth(
  snapshot: RoleHealthSnapshot,
  options: {
    now?: Date;
    failureThreshold?: number;
    maxTickAgeSeconds?: number;
    startupGraceSeconds?: number;
  } = {},
): RoleHealthEvaluation {
  const failureThreshold = options.failureThreshold ?? 3;
  const maxTickAgeSeconds = options.maxTickAgeSeconds ?? 60;
  const startupGraceSeconds = options.startupGraceSeconds ?? 90;
  const now = options.now ?? new Date();
  const startupAgeSeconds = Math.max(
    0,
    (now.getTime() - new Date(snapshot.startedAt).getTime()) / 1000,
  );
  if (snapshot.lastSuccessfulTickAt === null) {
    if (snapshot.consecutiveFailures >= failureThreshold) {
      return { ...snapshot, status: "unhealthy", reason: "sustained_tick_failures" };
    }
    if (!Number.isFinite(startupAgeSeconds) || startupAgeSeconds > startupGraceSeconds) {
      return { ...snapshot, status: "unhealthy", reason: "first_tick_overdue" };
    }
    if (
      snapshot.approvedPolicyFingerprint === null &&
      snapshot.appliedPolicyFingerprint !== null
    ) {
      return { ...snapshot, status: "degraded", reason: "awaiting_first_tick" };
    }
  }
  if (
    snapshot.approvedPolicyFingerprint === null ||
    snapshot.appliedPolicyFingerprint === null ||
    snapshot.approvedPolicyFingerprint !== snapshot.appliedPolicyFingerprint
  ) {
    return { ...snapshot, status: "unhealthy", reason: "policy_fingerprint_mismatch" };
  }
  if (snapshot.consecutiveFailures >= failureThreshold) {
    return { ...snapshot, status: "unhealthy", reason: "sustained_tick_failures" };
  }
  if (snapshot.lastSuccessfulTickAt === null) {
    return { ...snapshot, status: "degraded", reason: "no_successful_tick" };
  }
  const ageSeconds = Math.max(
    0,
    (now.getTime() - new Date(snapshot.lastSuccessfulTickAt).getTime()) / 1000,
  );
  if (!Number.isFinite(ageSeconds) || ageSeconds > maxTickAgeSeconds) {
    return { ...snapshot, status: "unhealthy", reason: "successful_tick_stale" };
  }
  if (snapshot.consecutiveFailures > 0) {
    return { ...snapshot, status: "degraded", reason: "tick_failure" };
  }
  return { ...snapshot, status: "healthy", reason: null };
}

export class PostgresRoleHealthStore {
  readonly instanceId: string;

  constructor(
    private readonly pool: Pool,
    private readonly hostId: string,
    private readonly role: PeriodicServiceRole,
    instanceId = randomUUID(),
  ) {
    this.instanceId = instanceId;
  }

  async start(appliedPolicyFingerprint: string | null): Promise<RoleHealthSnapshot> {
    const result = await this.pool.query(
      `INSERT INTO fabric_role_health(
         host_id,role,instance_id,started_at,approved_policy_fingerprint,
         applied_policy_fingerprint,last_successful_tick_at,last_tick_at,
         last_error,consecutive_failures,updated_at
       ) VALUES($1,$2,$3,now(),NULL,$4,NULL,NULL,NULL,0,now())
       ON CONFLICT(host_id,role) DO UPDATE SET
         instance_id=EXCLUDED.instance_id,
         started_at=EXCLUDED.started_at,
         approved_policy_fingerprint=NULL,
         applied_policy_fingerprint=EXCLUDED.applied_policy_fingerprint,
         last_successful_tick_at=NULL,
         last_tick_at=fabric_role_health.last_tick_at,
         last_error=fabric_role_health.last_error,
         consecutive_failures=fabric_role_health.consecutive_failures,
         updated_at=now()
       RETURNING *`,
      [this.hostId, this.role, this.instanceId, appliedPolicyFingerprint],
    );
    return roleHealthSnapshot(result.rows[0] as Record<string, unknown>);
  }

  async success(
    approvedPolicyFingerprint: string | null,
    appliedPolicyFingerprint: string | null,
  ): Promise<RoleHealthSnapshot> {
    const result = await this.pool.query(
      `UPDATE fabric_role_health SET
         approved_policy_fingerprint=$4,
         applied_policy_fingerprint=$5,
         last_successful_tick_at=now(),
         last_tick_at=now(),
         last_error=NULL,
         consecutive_failures=0,
         updated_at=now()
       WHERE host_id=$1 AND role=$2 AND instance_id=$3
       RETURNING *`,
      [
        this.hostId,
        this.role,
        this.instanceId,
        approvedPolicyFingerprint,
        appliedPolicyFingerprint,
      ],
    );
    if (!result.rows[0]) {
      throw new RoleHealthInstanceReplacedError("role health instance was replaced");
    }
    return roleHealthSnapshot(result.rows[0] as Record<string, unknown>);
  }

  async failure(
    error: unknown,
    approvedPolicyFingerprint: string | null,
    appliedPolicyFingerprint: string | null,
  ): Promise<RoleHealthSnapshot> {
    const message = error instanceof Error ? error.message : "unknown role failure";
    const result = await this.pool.query(
      `UPDATE fabric_role_health SET
         approved_policy_fingerprint=$4,
         applied_policy_fingerprint=$5,
         last_tick_at=now(),
         last_error=$6,
         consecutive_failures=consecutive_failures+1,
         updated_at=now()
       WHERE host_id=$1 AND role=$2 AND instance_id=$3
       RETURNING *`,
      [
        this.hostId,
        this.role,
        this.instanceId,
        approvedPolicyFingerprint,
        appliedPolicyFingerprint,
        message.slice(0, 2048),
      ],
    );
    if (!result.rows[0]) {
      throw new RoleHealthInstanceReplacedError("role health instance was replaced");
    }
    return roleHealthSnapshot(result.rows[0] as Record<string, unknown>);
  }
}

export async function recordRoleFailure(options: {
  store: Pick<PostgresRoleHealthStore, "failure">;
  error: unknown;
  approvedPolicyFingerprint: string | null;
  appliedPolicyFingerprint: string | null;
  onReportingError: (error: unknown) => void;
}): Promise<void> {
  try {
    await options.store.failure(
      options.error,
      options.approvedPolicyFingerprint,
      options.appliedPolicyFingerprint,
    );
  } catch (error) {
    if (error instanceof RoleHealthInstanceReplacedError) throw error;
    options.onReportingError(error);
  }
}

export function roleHealthSnapshot(row: Record<string, unknown>): RoleHealthSnapshot {
  return {
    hostId: String(row.host_id),
    role: String(row.role) as PeriodicServiceRole,
    instanceId: String(row.instance_id),
    startedAt: iso(row.started_at as Date | string)!,
    approvedPolicyFingerprint: row.approved_policy_fingerprint
      ? String(row.approved_policy_fingerprint)
      : null,
    appliedPolicyFingerprint: row.applied_policy_fingerprint
      ? String(row.applied_policy_fingerprint)
      : null,
    lastSuccessfulTickAt: iso(
      (row.last_successful_tick_at as Date | string | null) ?? null,
    ),
    lastTickAt: iso((row.last_tick_at as Date | string | null) ?? null),
    lastError: row.last_error ? String(row.last_error) : null,
    consecutiveFailures: Number(row.consecutive_failures ?? 0),
    updatedAt: iso(row.updated_at as Date | string)!,
  };
}

export async function runPeriodicRole(options: {
  role: PeriodicServiceRole;
  intervalMs: number;
  signal: AbortSignal;
  tick: () => Promise<void>;
  once?: boolean;
  onError?: (error: unknown) => Promise<void> | void;
}): Promise<void> {
  do {
    try {
      await options.tick();
    } catch (error) {
      await options.onError?.(error);
    }
    if (options.once || options.signal.aborted) return;
    await new Promise<void>((resolve) => {
      const timer = setTimeout(resolve, options.intervalMs);
      options.signal.addEventListener(
        "abort",
        () => {
          clearTimeout(timer);
          resolve();
        },
        { once: true },
      );
    });
  } while (!options.signal.aborted);
}

export function boundedIntegerEnvironment(
  name: string,
  fallback: number,
  minimum: number,
  maximum: number,
): number {
  const value = process.env[name];
  if (value === undefined) return fallback;
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw new Error(`${name} must be an integer between ${minimum} and ${maximum}`);
  }
  return parsed;
}

export function allowListEnvironment<T extends string>(
  name: string,
  allowed: readonly T[],
  fallback: readonly T[],
): T[] {
  const raw = process.env[name];
  const values = raw === undefined
    ? [...fallback]
    : raw.split(",").map((value) => value.trim()).filter(Boolean);
  if (values.length === 0) {
    throw new Error(`${name} must contain at least one allow-listed action`);
  }
  const invalid = values.filter((value) => !allowed.includes(value as T));
  if (invalid.length > 0) {
    throw new Error(`${name} contains unsupported action(s): ${invalid.join(",")}`);
  }
  return [...new Set(values)] as T[];
}
