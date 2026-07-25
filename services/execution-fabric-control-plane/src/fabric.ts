import type {
  Assignment,
  AttemptCompletion,
  ClaimRequest,
  ReconcileReceipt,
  TaskAdmission,
  TaskRecord,
  WorkerRegistration,
  WorkerRegistrationReceipt,
  EffectAssignment,
  EffectClaim,
} from "./contracts.js";
import type { DeliveryPort } from "./delivery.js";
import { ConflictError, type LedgerPort } from "./ledger.js";
import type { LeadershipGuard } from "./leadership.js";
import { PolicyManager } from "./policy.js";

export class ExecutionFabric {
  private lastReconcile: ReconcileReceipt | null = null;
  private lastReconcileError: string | null = null;

  constructor(
    readonly ledger: LedgerPort,
    readonly delivery: DeliveryPort,
    private readonly leaseSeconds: number,
    private readonly defaultLongPollMs: number,
    readonly policy: PolicyManager,
    readonly leadership?: LeadershipGuard,
  ) {}

  async admit(
    input: TaskAdmission,
  ): Promise<{ task: TaskRecord; admitted: boolean }> {
    const normalized = this.policy.normalizeAdmission(input);
    this.leadership?.assertTaskMutation(normalized.taskType);
    const queue = this.policy.queue(normalized.queue);
    const pool = this.policy.pool(queue.worker_pool);
    const result = await this.ledger.admitTask(normalized, {
      configFingerprint: this.policy.snapshot().appliedFingerprint,
      queue,
      pool,
    });
    if (result.task.status === "queued") {
      await this.delivery.publish(result.task);
      await this.ledger.markPublished(result.task.id);
    }
    return result;
  }

  async claim(input: ClaimRequest): Promise<Assignment | null> {
    this.assertMutation();
    const pool = this.policy.validateClaim(input);
    const effective = this.policy.effective().execution_fabric;
    const queue = this.policy.queue(pool.queues[0]!);
    for (const acceptedTaskType of queue.accepted_task_types) {
      this.leadership?.assertTaskMutation(acceptedTaskType);
    }
    const constraints = {
      configFingerprint: this.policy.snapshot().appliedFingerprint,
      pool,
      queue,
      globalMaxRunning: effective.admission.global_max_running,
      providerMaxRunning: effective.admission.provider_limits[pool.provider]!,
      reservedInteractiveSlots:
        effective.admission.reserved_interactive_slots,
      maxInteractiveRunning:
        effective.admission.max_interactive_running,
      namespaceLimits: effective.admission.namespace_limits,
      hostLimits: effective.admission.host_limits,
      namespaceWeights: effective.scheduling.namespace_weights,
      priorityAgingIntervalSeconds:
        effective.scheduling.priority_aging.interval_seconds,
      priorityAgingBoost:
        effective.scheduling.priority_aging.boost_per_interval,
      priorityAgingMaxBoost:
        effective.scheduling.priority_aging.max_boost,
    };
    const initial = await this.ledger.claim(input, constraints);
    if (initial) {
      await this.delivery.acknowledge(initial.task);
      return initial;
    }
    const waitMs = input.waitMs ?? this.defaultLongPollMs;
    if (waitMs <= 0) return null;
    await this.delivery.waitForWork(input.queues, waitMs);
    const assignment = await this.ledger.claim(input, constraints);
    if (assignment) await this.delivery.acknowledge(assignment.task);
    return assignment;
  }

  async registerWorker(
    input: WorkerRegistration,
  ): Promise<WorkerRegistrationReceipt> {
    this.assertMutation();
    const pool = this.policy.validateWorker(input);
    for (const queueId of pool.queues) {
      for (const acceptedTaskType of this.policy.queue(queueId)
        .accepted_task_types) {
        this.leadership?.assertTaskMutation(acceptedTaskType);
      }
    }
    return this.ledger.registerWorker(input, {
      configFingerprint: this.policy.snapshot().appliedFingerprint,
      pool,
    });
  }

  async complete(
    attemptId: string,
    input: AttemptCompletion,
  ): Promise<TaskRecord> {
    const task = await this.ledger.getTask(
      await this.ledger.taskIdForAttempt(attemptId),
    );
    if (!task) throw new Error("attempt task not found");
    this.leadership?.assertTaskMutation(task.taskType);
    this.policy.validateCompletionEffects(task.taskType, input.effects);
    this.leadership?.assertEffectMutation(
      input.effects.map((effect) => effect.effectType),
    );
    return this.ledger.complete(attemptId, input);
  }

  async claimEffects(input: EffectClaim): Promise<EffectAssignment[]> {
    this.policy.validateEffectClaim(input.effectTypes);
    this.leadership?.assertEffectMutation(input.effectTypes);
    return this.ledger.claimEffects(input, this.leaseSeconds);
  }

  async dispatchAvailable(limit = 500): Promise<number> {
    this.assertMutation();
    const tasks = await this.ledger.listPublishable(limit);
    let published = 0;
    for (const task of tasks) {
      await this.delivery.publish(task);
      await this.ledger.markPublished(task.id);
      published += 1;
    }
    return published;
  }

  async reconcile(): Promise<ReconcileReceipt> {
    this.assertMutation();
    try {
      const expired = await this.ledger.reconcileExpired();
      const deliveriesPublished = await this.dispatchAvailable();
      this.lastReconcile = {
        ...expired,
        deliveriesPublished,
        occurredAt: new Date().toISOString(),
      };
      this.lastReconcileError = null;
      return this.lastReconcile;
    } catch (error) {
      this.lastReconcileError =
        error instanceof Error ? error.message : "unknown reconcile failure";
      throw error;
    }
  }

  async ready(): Promise<void> {
    this.policy.assertOperational();
    await Promise.all([this.ledger.ping(), this.delivery.ping()]);
    await this.ledger.activatePolicy(this.policy.snapshot().appliedFingerprint);
    this.assertMutation();
  }

  async initialize(): Promise<void> {
    this.policy.assertOperational();
    await Promise.all([this.ledger.ping(), this.delivery.ping()]);
    await this.ledger.activatePolicy(this.policy.snapshot().appliedFingerprint);
  }

  async reloadPolicy(input: {
    expectedCurrentFingerprint: string;
    expectedCandidateFingerprint: string;
  }): Promise<Record<string, unknown>> {
    this.assertMutation();
    const prepared = this.policy.prepareReload();
    if (prepared.previousFingerprint !== input.expectedCurrentFingerprint) {
      throw new ConflictError(
        "applied policy does not match expectedCurrentFingerprint",
      );
    }
    if (
      prepared.candidateFingerprint !== input.expectedCandidateFingerprint
    ) {
      throw new ConflictError(
        "disk policy does not match expectedCandidateFingerprint",
      );
    }
    const receipt = await this.ledger.activatePolicyReload(input);
    const snapshot = this.policy.activatePrepared(prepared);
    return { ...snapshot, receipt, appliedFingerprint: snapshot.appliedFingerprint };
  }

  async status(activeHost: string, limit = 200): Promise<Record<string, unknown>> {
    const config = this.policy.check();
    const [queues, workers, rawRuns, system] = await Promise.all([
      this.ledger.queueSnapshot(),
      this.ledger.workerSnapshot(),
      this.ledger.runSnapshot(limit),
      this.ledger.systemSnapshot(),
    ]);
    const runs = rawRuns.map((run) => {
      const route = this.policy.route(run.taskType);
      return {
        ...run,
        mutationClass: route.mutation_class,
        approvalClass: route.approval_class,
        executionTarget: route.execution.target,
      };
    });
    const queuedById = new Map(queues.map((row) => [row.queue, row]));
    const configuredQueues = this.policy.effective().execution_fabric.queues;
    const observableQueues = configuredQueues.map((queue) => {
      const row = queuedById.get(queue.id) ?? {
        queue: queue.id,
        queued: 0,
        ready: 0,
        delayed: 0,
        retrying: 0,
        running: 0,
        succeeded: 0,
        failed: 0,
        deadLettered: 0,
        cancelled: 0,
        completedLastHour: 0,
        failedLastHour: 0,
        throughputPerHour: 0,
        failureRateLastHour: 0,
        oldestQueuedAt: null,
        oldestReadyAgeSeconds: null,
      };
      const pool = queue
        ? this.policy.effective().execution_fabric.worker_pools.find(
            (candidate) => candidate.id === queue.worker_pool,
          )
        : undefined;
      return {
        ...row,
        enabled: queue?.enabled ?? false,
        workerPool: queue?.worker_pool ?? null,
        provider: pool?.provider ?? null,
        acceptedTaskTypes: queue?.accepted_task_types ?? [],
        maxRunning: queue?.concurrency.max_running ?? null,
        maxQueued: queue?.concurrency.max_queued ?? null,
        saturation:
          queue?.concurrency.max_running
            ? row.running / queue.concurrency.max_running
            : null,
        capacityRemaining:
          queue?.concurrency.max_running !== undefined
            ? Math.max(0, queue.concurrency.max_running - row.running)
            : null,
      };
    });
    const alarms: Array<Record<string, unknown>> = [];
    if (config.state !== "applied") {
      alarms.push({
        code: config.state === "drifted" ? "config_drift" : "config_invalid",
        severity: "critical",
        summary: config.lastError,
      });
    }
    if (
      system.databasePolicyFingerprint !== null &&
      system.databasePolicyFingerprint !== config.appliedFingerprint
    ) {
      alarms.push({
        code: "replica_config_mismatch",
        severity: "critical",
        summary: "database and replica policy fingerprints differ",
      });
    }
    for (const queue of observableQueues) {
      if (queue.deadLettered > 0) {
        alarms.push({
          code: "dead_lettered_tasks",
          severity: "warning",
          queue: queue.queue,
          count: queue.deadLettered,
        });
      }
      if (
        queue.queued > 0 &&
        !workers.some(
          (worker) =>
            worker.state === "online" && worker.queues.includes(queue.queue),
        )
      ) {
        alarms.push({
          code: "queue_without_live_worker",
          severity: "critical",
          queue: queue.queue,
          count: queue.queued,
        });
      }
    }
    if (this.lastReconcileError) {
      alarms.push({
        code: "healer_failed",
        severity: "critical",
        summary: this.lastReconcileError,
      });
    }
    return {
      schemaVersion: "agentic-os-execution-fabric-status/v1",
      sampledAt: new Date().toISOString(),
      config,
      controlPlane: {
        activeHost,
        fabricEpoch: system.fabricEpoch,
        leaderHostId: system.leaderHostId,
        leaderLeaseExpiresAt: system.leaderLeaseExpiresAt,
        leadershipClusterId: system.leadershipClusterId,
        leadershipReceiptId: system.leadershipReceiptId,
        leadershipFenceDigest: system.leadershipFenceDigest,
        leaderRecoveryHoldUntil: system.leaderRecoveryHoldUntil,
        databasePolicyFingerprint: system.databasePolicyFingerprint,
        eventSequence: system.eventSequence,
        leadership: this.leadership?.snapshot() ?? {
          state: "not_configured",
        },
      },
      queues: observableQueues,
      workers,
      runs,
      effects: system.effects,
      healing: {
        status: this.lastReconcileError ? "failed" : "healthy",
        lastReconcileAt: this.lastReconcile?.occurredAt ?? null,
        lastReceipt: this.lastReconcile,
        lastError: this.lastReconcileError,
      },
      alarms,
    };
  }

  assertMutation(): void {
    this.leadership?.assertMutation();
  }

  assertSchedulerMutation(): void {
    this.leadership?.assertSchedulerMutation();
  }
}
