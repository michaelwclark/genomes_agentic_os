import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { parse as parseYaml } from "yaml";
import { z } from "zod";
import type {
  ClaimRequest,
  TaskAdmission,
  WorkerRegistration,
} from "./contracts.js";

const id = z.string().regex(/^[a-z][a-z0-9_]*$/);
const taskType = z.string().regex(/^[a-z][a-z0-9_.-]*$/);
const scopeId = z.string().min(1).max(128).regex(/^[a-zA-Z0-9._:-]+$/);

const payloadPropertySchema = z
  .object({
    type: z.enum(["string", "integer", "boolean"]),
    pattern: z.string().max(512).optional(),
    enum: z.array(z.union([z.string(), z.number().int(), z.boolean()])).min(1).optional(),
  })
  .strict();

const taskRouteSchema = z
  .object({
    task_type: taskType,
    queue: id,
    scheduling_class: z.enum(["interactive", "background"]),
    execution: z
      .object({
        remote_allowed: z.boolean(),
        target: z.enum(["script", "codex_harness", "claude_harness", "domain_worker"]),
        required_capability: z.string().min(1).max(128).nullable(),
        command_template: z.array(z.string().min(1).max(512)).min(1).nullable(),
        domain_worker: id.nullable(),
      })
      .strict(),
    mutation_class: z.enum([
      "read_only",
      "internal_write",
      "external_write",
      "production_write",
    ]),
    approval_class: z.enum(["not_required", "policy_gated", "explicit"]),
    payload: z
      .object({
        additional_properties: z.literal(false),
        required: z.array(id),
        properties: z.record(id, payloadPropertySchema),
      })
      .strict(),
    allowed_effect_types: z.array(taskType),
  })
  .strict();

const queueSchema = z
  .object({
    id,
    enabled: z.boolean(),
    worker_pool: id,
    accepted_task_types: z.array(z.string().min(1)).min(1),
    priority: z.number().int().min(0).max(100),
    concurrency: z
      .object({
        max_running: z.number().int().min(1),
        max_queued: z.number().int().min(1),
      })
      .strict(),
  })
  .strict();

const poolSchema = z
  .object({
    id,
    enabled: z.boolean(),
    provider: id,
    queues: z.array(id).min(1).max(1),
    capabilities: z.array(z.string().min(1)).default([]),
    capacity: z
      .object({
        min_workers: z.number().int().min(0),
        max_workers: z.number().int().min(1),
        max_tasks_per_worker: z.number().int().min(1),
      })
      .strict(),
    lease: z
      .object({
        timeout_seconds: z.number().int().min(30),
        heartbeat_seconds: z.number().int().min(1),
      })
      .strict(),
    retry: z
      .object({
        max_attempts: z.number().int().min(1).max(100),
        backoff_seconds: z.number().int().min(0),
      })
      .strict(),
  })
  .strict();

const canonicalPolicySchema = z
  .object({
    schema_version: z.literal(1),
    execution_fabric: z
      .object({
        standalone_primary: z
          .object({
            enabled: z.boolean(),
            host_id: scopeId,
          })
          .strict(),
        degraded_primary: z
          .object({
            allow_degraded_primary: z.boolean(),
            max_duration_seconds: z.number().int().min(60).max(86400),
            allowed_task_types: z.array(taskType),
            allowed_effect_types: z.array(taskType),
            allow_scheduler: z.boolean(),
          })
          .strict(),
        transport: z
          .object({
            mode: z.enum(["local", "remote", "remote_with_local_fallback"]),
            control_plane_url: z.string().nullable(),
            request_timeout_seconds: z.number().int().min(1).max(300),
            long_poll_seconds: z.number().int().min(0).max(30),
            submit_token_env: z.string().regex(/^[A-Z][A-Z0-9_]*$/),
            worker_token_env: z.string().regex(/^[A-Z][A-Z0-9_]*$/),
            observer_token_env: z.string().regex(/^[A-Z][A-Z0-9_]*$/),
            admin_token_env: z.string().regex(/^[A-Z][A-Z0-9_]*$/),
            fallback: z
              .object({
                failure_threshold: z.number().int().min(2).max(60),
                state_path: z.string().min(1),
              })
              .strict()
              .optional(),
          })
          .strict()
          .optional(),
        admission: z
          .object({
            global_max_running: z.number().int().min(1),
            reserved_interactive_slots: z.number().int().min(0),
            max_interactive_running: z.number().int().min(1),
            provider_limits: z.record(id, z.number().int().min(1)),
            namespace_limits: z
              .record(scopeId, z.number().int().min(1))
              .default({}),
            host_limits: z.record(scopeId, z.number().int().min(1)).default({}),
          })
          .strict(),
        scheduling: z
          .object({
            priority_aging: z
              .object({
                interval_seconds: z.number().int().min(1).max(86400),
                boost_per_interval: z.number().int().min(0).max(1000),
                max_boost: z.number().int().min(0).max(1000),
              })
              .strict(),
            namespace_weights: z
              .record(scopeId, z.number().int().min(1).max(100))
              .default({}),
          })
          .strict()
          .default({
            priority_aging: {
              interval_seconds: 300,
              boost_per_interval: 1,
              max_boost: 100,
            },
            namespace_weights: {},
          }),
        task_routes: z.array(taskRouteSchema).min(1),
        queues: z.array(queueSchema).min(1),
        worker_pools: z.array(poolSchema).min(1),
      })
      .strict(),
  })
  .strict();

export type QueuePolicy = z.infer<typeof queueSchema>;
export type WorkerPoolPolicy = z.infer<typeof poolSchema>;
export type TaskRoutePolicy = z.infer<typeof taskRouteSchema>;
export type CanonicalPolicy = z.infer<typeof canonicalPolicySchema>;
export type NormalizedTaskAdmission = Omit<
  TaskAdmission,
  "maxAttempts" | "priority"
> & {
  maxAttempts: number;
  priority: number;
  schedulingClass: TaskRoutePolicy["scheduling_class"];
};

export type PolicySnapshot = {
  schemaVersion: "execution-fabric-policy-status/v1";
  source: string;
  schemaSource: string;
  appliedFingerprint: string;
  diskFingerprint: string | null;
  state: "applied" | "drifted" | "invalid";
  appliedAt: string;
  lastCheckedAt: string;
  lastReloadAt: string | null;
  lastReloadStatus: "never" | "succeeded" | "failed";
  lastError: string | null;
};

export type PreparedPolicyReload = {
  previousFingerprint: string;
  candidateFingerprint: string;
  candidate: CanonicalPolicy;
};

export class PolicyError extends Error {
  constructor(
    readonly code:
      | "config_invalid"
      | "config_drift"
      | "queue_unknown"
      | "queue_disabled"
      | "task_type_rejected"
      | "task_route_rejected"
      | "payload_rejected"
      | "capability_rejected"
      | "effect_type_rejected"
      | "max_attempts_rejected"
      | "worker_pool_rejected",
    message: string,
  ) {
    super(message);
  }
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value !== null && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, child]) => `${JSON.stringify(key)}:${canonicalJson(child)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function fingerprint(value: unknown): string {
  return createHash("sha256").update(canonicalJson(value)).digest("hex");
}

function mergeConfig(base: unknown, override: unknown): unknown {
  if (
    base !== null &&
    override !== null &&
    typeof base === "object" &&
    typeof override === "object" &&
    !Array.isArray(base) &&
    !Array.isArray(override)
  ) {
    const merged = { ...(base as Record<string, unknown>) };
    for (const [key, value] of Object.entries(
      override as Record<string, unknown>,
    )) {
      merged[key] =
        key in merged ? mergeConfig(merged[key], value) : structuredClone(value);
    }
    return merged;
  }
  if (Array.isArray(base) && Array.isArray(override)) {
    const rows = [...base, ...override];
    if (
      rows.every(
        (row) =>
          row !== null &&
          typeof row === "object" &&
          !Array.isArray(row) &&
          typeof (row as Record<string, unknown>).id === "string",
      )
    ) {
      const ordered: string[] = [];
      const byId = new Map<string, unknown>();
      for (const row of base) {
        const rowId = String((row as Record<string, unknown>).id);
        ordered.push(rowId);
        byId.set(rowId, structuredClone(row));
      }
      for (const row of override) {
        const rowId = String((row as Record<string, unknown>).id);
        if (!byId.has(rowId)) ordered.push(rowId);
        byId.set(rowId, mergeConfig(byId.get(rowId) ?? {}, row));
      }
      return ordered.map((rowId) => byId.get(rowId));
    }
    return structuredClone(override);
  }
  return structuredClone(override);
}

function capacityCaps(policy: CanonicalPolicy): Map<string, number> {
  const fabric = policy.execution_fabric;
  const caps = new Map<string, number>([
    ["admission.global_max_running", fabric.admission.global_max_running],
    [
      "admission.max_interactive_running",
      fabric.admission.max_interactive_running,
    ],
  ]);
  for (const [provider, limit] of Object.entries(
    fabric.admission.provider_limits,
  )) {
    caps.set(`admission.provider_limits.${provider}`, limit);
  }
  for (const [namespace, limit] of Object.entries(
    fabric.admission.namespace_limits,
  )) {
    caps.set(`admission.namespace_limits.${namespace}`, limit);
  }
  for (const [host, limit] of Object.entries(fabric.admission.host_limits)) {
    caps.set(`admission.host_limits.${host}`, limit);
  }
  for (const queue of fabric.queues) {
    caps.set(`queues.${queue.id}.max_running`, queue.concurrency.max_running);
    caps.set(`queues.${queue.id}.max_queued`, queue.concurrency.max_queued);
  }
  for (const pool of fabric.worker_pools) {
    caps.set(`worker_pools.${pool.id}.max_workers`, pool.capacity.max_workers);
    caps.set(
      `worker_pools.${pool.id}.max_tasks_per_worker`,
      pool.capacity.max_tasks_per_worker,
    );
    caps.set(`worker_pools.${pool.id}.max_attempts`, pool.retry.max_attempts);
  }
  return caps;
}

function assertNarrowerHostOverride(
  base: CanonicalPolicy,
  candidate: CanonicalPolicy,
  hostAlias: string,
): void {
  const baseCaps = capacityCaps(base);
  const increased = [...capacityCaps(candidate)].flatMap(([key, value]) => {
    const baseline = baseCaps.get(key);
    return baseline !== undefined && value > baseline ? [key] : [];
  });
  if (increased.length) {
    throw new Error(
      `host override ${hostAlias} may tighten but not increase capacity: ${increased.sort().join(", ")}`,
    );
  }
}

function parsePolicy(source: string): CanonicalPolicy {
  const parsedYaml = parseYaml(source);
  if (
    parsedYaml === null ||
    typeof parsedYaml !== "object" ||
    Array.isArray(parsedYaml)
  ) {
    throw new Error("canonical policy must be a YAML mapping");
  }
  const raw = parsedYaml as Record<string, unknown>;
  const rawFabric = raw.execution_fabric as
    | Record<string, unknown>
    | undefined;
  const rawOverrides = rawFabric?.host_overrides;
  if (
    rawOverrides !== undefined &&
    (rawOverrides === null ||
      typeof rawOverrides !== "object" ||
      Array.isArray(rawOverrides))
  ) {
    throw new Error("execution_fabric.host_overrides must be a mapping");
  }
  const withoutOverrides = structuredClone(raw);
  const effectiveFabric = withoutOverrides.execution_fabric as Record<
    string,
    unknown
  >;
  if (!effectiveFabric || typeof effectiveFabric !== "object") {
    throw new Error("canonical policy execution_fabric must be a mapping");
  }
  delete effectiveFabric.host_overrides;
  const base = canonicalPolicySchema.parse(withoutOverrides);
  const candidates = new Map<string, CanonicalPolicy>();
  for (const [hostAlias, override] of Object.entries(
    (rawOverrides ?? {}) as Record<string, unknown>,
  )) {
    scopeId.parse(hostAlias);
    if (override === null || typeof override !== "object" || Array.isArray(override)) {
      throw new Error(`host override ${hostAlias} must be a mapping`);
    }
    const candidate = canonicalPolicySchema.parse(
      mergeConfig(base, { execution_fabric: override }),
    );
    assertNarrowerHostOverride(base, candidate, hostAlias);
    candidates.set(hostAlias, candidate);
  }
  const parsed = candidates.get(process.env.FABRIC_HOST_ID ?? "") ?? base;
  const queues = new Map<string, QueuePolicy>();
  for (const queue of parsed.execution_fabric.queues) {
    if (queues.has(queue.id)) throw new Error(`duplicate queue id: ${queue.id}`);
    queues.set(queue.id, queue);
  }
  const pools = new Map<string, WorkerPoolPolicy>();
  for (const pool of parsed.execution_fabric.worker_pools) {
    if (pools.has(pool.id)) throw new Error(`duplicate worker pool id: ${pool.id}`);
    pools.set(pool.id, pool);
    if (pool.capacity.min_workers > pool.capacity.max_workers) {
      throw new Error(`worker pool ${pool.id} min_workers exceeds max_workers`);
    }
    if (pool.lease.heartbeat_seconds >= pool.lease.timeout_seconds) {
      throw new Error(
        `worker pool ${pool.id} heartbeat_seconds must be below timeout_seconds`,
      );
    }
  }
  for (const queue of queues.values()) {
    const pool = pools.get(queue.worker_pool);
    if (!pool || pool.queues.length !== 1 || pool.queues[0] !== queue.id) {
      throw new Error(
        `queue ${queue.id} and worker pool ${queue.worker_pool} must reference each other`,
      );
    }
  }
  for (const pool of pools.values()) {
    if (!queues.has(pool.queues[0]!)) {
      throw new Error(`worker pool ${pool.id} references unknown queue`);
    }
    if (
      parsed.execution_fabric.admission.provider_limits[pool.provider] === undefined
    ) {
      throw new Error(`provider ${pool.provider} has no admission limit`);
    }
  }
  const routes = new Map<string, TaskRoutePolicy>();
  for (const route of parsed.execution_fabric.task_routes) {
    if (routes.has(route.task_type)) {
      throw new Error(`duplicate task route: ${route.task_type}`);
    }
    routes.set(route.task_type, route);
    const queue = queues.get(route.queue);
    if (!queue || !queue.accepted_task_types.includes(route.task_type)) {
      throw new Error(
        `task route ${route.task_type} must reference a queue that accepts it`,
      );
    }
    const propertyNames = new Set(Object.keys(route.payload.properties));
    if (route.payload.required.some((name) => !propertyNames.has(name))) {
      throw new Error(`task route ${route.task_type} requires an undefined payload field`);
    }
    const execution = route.execution;
    const hasTemplate = execution.command_template !== null;
    const hasDomainWorker = execution.domain_worker !== null;
    if (hasTemplate === hasDomainWorker) {
      throw new Error(
        `task route ${route.task_type} must define exactly one command_template or domain_worker`,
      );
    }
    if (hasDomainWorker && execution.target !== "domain_worker") {
      throw new Error(
        `task route ${route.task_type} domain_worker requires target domain_worker`,
      );
    }
    if (!execution.remote_allowed && route.allowed_effect_types.length > 0) {
      throw new Error(
        `local-only task route ${route.task_type} cannot declare remote effects`,
      );
    }
  }
  for (const queue of queues.values()) {
    for (const accepted of queue.accepted_task_types) {
      if (!routes.has(accepted)) {
        throw new Error(`queue ${queue.id} accepts task type ${accepted} without a task route`);
      }
    }
  }
  const admission = parsed.execution_fabric.admission;
  if (admission.reserved_interactive_slots >= admission.global_max_running) {
    throw new Error("reserved_interactive_slots must be below global_max_running");
  }
  if (admission.max_interactive_running > admission.global_max_running) {
    throw new Error("max_interactive_running exceeds global_max_running");
  }
  const aging = parsed.execution_fabric.scheduling.priority_aging;
  if (aging.max_boost < aging.boost_per_interval) {
    throw new Error("priority_aging max_boost must cover one boost interval");
  }
  return parsed;
}

function safeError(error: unknown): string {
  if (error instanceof z.ZodError) {
    const issue = error.issues[0];
    return `invalid policy at ${issue?.path.join(".") || "/"}: ${issue?.message}`;
  }
  return error instanceof Error ? error.message : "unknown policy error";
}

export class PolicyManager {
  private policy: CanonicalPolicy;
  private appliedFingerprint: string;
  private appliedAt: string;
  private lastCheckedAt: string;
  private lastReloadAt: string | null = null;
  private lastReloadStatus: PolicySnapshot["lastReloadStatus"] = "never";
  private lastError: string | null = null;
  private diskFingerprint: string | null;
  private diskState: PolicySnapshot["state"] = "applied";

  constructor(
    readonly source: string,
    readonly schemaSource: string,
  ) {
    const raw = readFileSync(source, "utf8");
    this.policy = parsePolicy(raw);
    this.appliedFingerprint = fingerprint(this.policy);
    this.diskFingerprint = this.appliedFingerprint;
    this.appliedAt = new Date().toISOString();
    this.lastCheckedAt = this.appliedAt;
  }

  effective(): CanonicalPolicy {
    return this.policy;
  }

  check(): PolicySnapshot {
    this.lastCheckedAt = new Date().toISOString();
    try {
      const candidate = parsePolicy(readFileSync(this.source, "utf8"));
      this.diskFingerprint = fingerprint(candidate);
      this.diskState =
        this.diskFingerprint === this.appliedFingerprint ? "applied" : "drifted";
      this.lastError =
        this.diskState === "drifted"
          ? "canonical policy differs from the applied policy; explicit reload required"
          : null;
    } catch (error) {
      this.diskFingerprint = null;
      this.diskState = "invalid";
      this.lastError = safeError(error);
    }
    return this.snapshot();
  }

  assertOperational(): void {
    const snapshot = this.check();
    if (snapshot.state !== "applied") {
      throw new PolicyError(
        snapshot.state === "drifted" ? "config_drift" : "config_invalid",
        snapshot.lastError ?? "canonical policy is not applied",
      );
    }
  }

  reload(): PolicySnapshot {
    this.lastReloadAt = new Date().toISOString();
    try {
      const candidate = parsePolicy(readFileSync(this.source, "utf8"));
      this.policy = candidate;
      this.appliedFingerprint = fingerprint(candidate);
      this.diskFingerprint = this.appliedFingerprint;
      this.appliedAt = this.lastReloadAt;
      this.lastCheckedAt = this.lastReloadAt;
      this.diskState = "applied";
      this.lastReloadStatus = "succeeded";
      this.lastError = null;
    } catch (error) {
      this.diskFingerprint = null;
      this.diskState = "invalid";
      this.lastReloadStatus = "failed";
      this.lastError = safeError(error);
      throw new PolicyError("config_invalid", this.lastError);
    }
    return this.snapshot();
  }

  prepareReload(): PreparedPolicyReload {
    try {
      const candidate = parsePolicy(readFileSync(this.source, "utf8"));
      return {
        previousFingerprint: this.appliedFingerprint,
        candidateFingerprint: fingerprint(candidate),
        candidate,
      };
    } catch (error) {
      this.diskFingerprint = null;
      this.diskState = "invalid";
      this.lastReloadStatus = "failed";
      this.lastError = safeError(error);
      throw new PolicyError("config_invalid", this.lastError);
    }
  }

  activatePrepared(prepared: PreparedPolicyReload): PolicySnapshot {
    if (this.appliedFingerprint !== prepared.previousFingerprint) {
      throw new PolicyError(
        "config_drift",
        "applied policy changed after reload preparation",
      );
    }
    this.lastReloadAt = new Date().toISOString();
    this.policy = prepared.candidate;
    this.appliedFingerprint = prepared.candidateFingerprint;
    this.diskFingerprint = prepared.candidateFingerprint;
    this.appliedAt = this.lastReloadAt;
    this.lastCheckedAt = this.lastReloadAt;
    this.diskState = "applied";
    this.lastReloadStatus = "succeeded";
    this.lastError = null;
    return this.snapshot();
  }

  /**
   * Converge a long-running role only to the fingerprint already authorized
   * in PostgreSQL by the admin reload transaction.
   *
   * This never treats an arbitrary disk edit as authority. A scheduler,
   * healer, or observer may adopt the disk candidate only when its exact
   * fingerprint matches the durable database fingerprint.
   */
  synchronizeApprovedFingerprint(
    approvedFingerprint: string | null,
  ): PolicySnapshot {
    const observed = this.check();
    if (!approvedFingerprint) {
      throw new PolicyError(
        "config_drift",
        "database has no approved policy fingerprint",
      );
    }
    if (observed.appliedFingerprint === approvedFingerprint) {
      if (observed.state !== "applied") {
        throw new PolicyError(
          observed.state === "invalid" ? "config_invalid" : "config_drift",
          observed.lastError ??
            "canonical policy differs from the database-approved policy",
        );
      }
      return observed;
    }
    if (observed.diskFingerprint !== approvedFingerprint) {
      throw new PolicyError(
        observed.state === "invalid" ? "config_invalid" : "config_drift",
        "disk policy does not match the database-approved fingerprint",
      );
    }
    const prepared = this.prepareReload();
    if (prepared.candidateFingerprint !== approvedFingerprint) {
      throw new PolicyError(
        "config_drift",
        "disk policy changed while synchronizing the approved fingerprint",
      );
    }
    return this.activatePrepared(prepared);
  }

  snapshot(): PolicySnapshot {
    return {
      schemaVersion: "execution-fabric-policy-status/v1",
      source: this.source,
      schemaSource: this.schemaSource,
      appliedFingerprint: this.appliedFingerprint,
      diskFingerprint: this.diskFingerprint,
      state: this.diskState,
      appliedAt: this.appliedAt,
      lastCheckedAt: this.lastCheckedAt,
      lastReloadAt: this.lastReloadAt,
      lastReloadStatus: this.lastReloadStatus,
      lastError: this.lastError,
    };
  }

  normalizeAdmission(input: TaskAdmission): NormalizedTaskAdmission {
    this.assertOperational();
    const queue = this.queue(input.queue);
    if (!queue.accepted_task_types.includes(input.taskType)) {
      throw new PolicyError(
        "task_type_rejected",
        `task type ${input.taskType} is not accepted by queue ${input.queue}`,
      );
    }
    const route = this.route(input.taskType);
    if (route.queue !== input.queue || !route.execution.remote_allowed) {
      throw new PolicyError(
        "task_route_rejected",
        `task type ${input.taskType} is not remotely admissible on queue ${input.queue}`,
      );
    }
    this.validatePayload(route, input.payload ?? {});
    const pool = this.pool(queue.worker_pool);
    const required = route.execution.required_capability;
    const requiredCapabilities = [
      ...new Set([
        ...input.requiredCapabilities,
        ...(required ? [required] : []),
      ]),
    ];
    if (
      requiredCapabilities.some(
        (capability) => !pool.capabilities.includes(capability),
      )
    ) {
      throw new PolicyError(
        "capability_rejected",
        `task type ${input.taskType} requests a capability outside worker pool ${pool.id}`,
      );
    }
    const maxAttempts = input.maxAttempts ?? pool.retry.max_attempts;
    if (maxAttempts > pool.retry.max_attempts) {
      throw new PolicyError(
        "max_attempts_rejected",
        `maxAttempts ${maxAttempts} exceeds queue policy ${pool.retry.max_attempts}`,
      );
    }
    return {
      ...input,
      payload: input.payload ?? {},
      requiredCapabilities,
      priority: input.priority ?? queue.priority,
      maxAttempts,
      schedulingClass: route.scheduling_class,
    };
  }

  route(taskTypeValue: string): TaskRoutePolicy {
    const route = this.policy.execution_fabric.task_routes.find(
      (candidate) => candidate.task_type === taskTypeValue,
    );
    if (!route) {
      throw new PolicyError(
        "task_route_rejected",
        `no canonical task route exists for ${taskTypeValue}`,
      );
    }
    return route;
  }

  validateCompletionEffects(
    taskTypeValue: string,
    effects: Array<{ effectType: string }>,
  ): void {
    const allowed = new Set(this.route(taskTypeValue).allowed_effect_types);
    for (const effect of effects) {
      if (!allowed.has(effect.effectType)) {
        throw new PolicyError(
          "effect_type_rejected",
          `effect type ${effect.effectType} is not allowed for task type ${taskTypeValue}`,
        );
      }
    }
  }

  validateEffectClaim(effectTypes: string[]): void {
    const allowed = new Set(
      this.policy.execution_fabric.task_routes.flatMap(
        (route) => route.allowed_effect_types,
      ),
    );
    for (const effectType of effectTypes) {
      if (!allowed.has(effectType)) {
        throw new PolicyError(
          "effect_type_rejected",
          `effect type ${effectType} is not declared by any canonical task route`,
        );
      }
    }
  }

  private validatePayload(
    route: TaskRoutePolicy,
    payload: Record<string, unknown>,
  ): void {
    const fields = new Set(Object.keys(payload));
    for (const required of route.payload.required) {
      if (!fields.has(required)) {
        throw new PolicyError(
          "payload_rejected",
          `task type ${route.task_type} requires payload field ${required}`,
        );
      }
    }
    for (const [name, value] of Object.entries(payload)) {
      const rule = route.payload.properties[name];
      if (!rule) {
        throw new PolicyError(
          "payload_rejected",
          `task type ${route.task_type} does not allow payload field ${name}`,
        );
      }
      const validType =
        (rule.type === "string" && typeof value === "string") ||
        (rule.type === "integer" && typeof value === "number" && Number.isInteger(value)) ||
        (rule.type === "boolean" && typeof value === "boolean");
      if (!validType) {
        throw new PolicyError(
          "payload_rejected",
          `task type ${route.task_type} payload field ${name} must be ${rule.type}`,
        );
      }
      if (
        rule.pattern &&
        (typeof value !== "string" || !new RegExp(rule.pattern).test(value))
      ) {
        throw new PolicyError(
          "payload_rejected",
          `task type ${route.task_type} payload field ${name} does not match policy`,
        );
      }
      if (rule.enum && !rule.enum.includes(value as never)) {
        throw new PolicyError(
          "payload_rejected",
          `task type ${route.task_type} payload field ${name} is not an allowed value`,
        );
      }
    }
  }

  validateWorker(input: WorkerRegistration): WorkerPoolPolicy {
    this.assertOperational();
    const queueIds = [...new Set(input.queues)];
    if (queueIds.length !== input.queues.length) {
      throw new PolicyError("worker_pool_rejected", "worker queues must be unique");
    }
    for (const queueId of queueIds) this.queue(queueId);
    const candidates = this.policy.execution_fabric.worker_pools.filter(
      (pool) =>
        pool.enabled &&
        queueIds.length === pool.queues.length &&
        queueIds.every((queue) => pool.queues.includes(queue)),
    );
    if (candidates.length !== 1) {
      throw new PolicyError(
        "worker_pool_rejected",
        `worker queues do not map to exactly one enabled worker pool`,
      );
    }
    const pool = candidates[0]!;
    if (input.maxConcurrency > pool.capacity.max_tasks_per_worker) {
      throw new PolicyError(
        "worker_pool_rejected",
        `worker concurrency exceeds ${pool.id} max_tasks_per_worker`,
      );
    }
    if (!pool.capabilities.every((capability) => input.capabilities.includes(capability))) {
      throw new PolicyError(
        "worker_pool_rejected",
        `worker is missing required capabilities for pool ${pool.id}`,
      );
    }
    return pool;
  }

  validateClaim(input: ClaimRequest): WorkerPoolPolicy {
    this.assertOperational();
    return this.validateWorker({
      bootstrapId: "claim",
      workerId: input.workerId,
      hostId: "claim",
      queues: input.queues,
      capabilities: input.capabilities,
      maxConcurrency: 1,
      metadata: {},
    });
  }

  queue(idValue: string): QueuePolicy {
    const queue = this.policy.execution_fabric.queues.find(
      (candidate) => candidate.id === idValue,
    );
    if (!queue) throw new PolicyError("queue_unknown", `unknown queue: ${idValue}`);
    if (!queue.enabled) {
      throw new PolicyError("queue_disabled", `queue is disabled: ${idValue}`);
    }
    return queue;
  }

  pool(idValue: string): WorkerPoolPolicy {
    const pool = this.policy.execution_fabric.worker_pools.find(
      (candidate) => candidate.id === idValue,
    );
    if (!pool || !pool.enabled) {
      throw new PolicyError("worker_pool_rejected", `worker pool is disabled: ${idValue}`);
    }
    return pool;
  }

  poolForQueue(queueId: string): WorkerPoolPolicy {
    return this.pool(this.queue(queueId).worker_pool);
  }

  providerQueues(provider: string): string[] {
    return this.policy.execution_fabric.worker_pools
      .filter((pool) => pool.enabled && pool.provider === provider)
      .flatMap((pool) => pool.queues);
  }
}
