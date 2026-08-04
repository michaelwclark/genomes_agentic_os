import { z } from "zod";

const identifier = z.string().min(1).max(128).regex(/^[a-zA-Z0-9._:-]+$/);

export const taskAdmissionSchema = z.object({
  namespace: identifier,
  queue: identifier,
  taskType: identifier,
  idempotencyKey: z.string().min(1).max(512),
  payload: z.record(z.unknown()).default({}),
  requiredCapabilities: z.array(identifier).max(128).default([]),
  priority: z.number().int().min(-1000).max(1000).optional(),
  availableAt: z.string().datetime({ offset: true }).optional(),
  maxAttempts: z.number().int().min(1).max(100).optional(),
});

export const workerRegistrationSchema = z.object({
  bootstrapId: identifier,
  workerId: identifier,
  hostId: identifier,
  queues: z.array(identifier).min(1).max(64),
  capabilities: z.array(identifier).max(128).default([]),
  maxConcurrency: z.number().int().min(1).max(256),
  metadata: z
    .record(z.union([z.string(), z.number(), z.boolean(), z.null()]))
    .default({}),
});

export const workerHeartbeatSchema = z.object({
  registrationToken: z.string().uuid(),
  activeAttemptIds: z.array(z.string().uuid()).max(256).default([]),
  artifactSpoolHealth: z
    .object({
      status: z.enum(["healthy", "degraded", "critical"]),
      pending: z.number().int().nonnegative(),
      due: z.number().int().nonnegative(),
      quarantined: z.number().int().nonnegative(),
      oldestPendingAt: z.string().datetime({ offset: true }).nullable(),
      lastDrainAt: z.string().datetime({ offset: true }),
      lastDrainAttempted: z.number().int().nonnegative(),
      lastDrainPublished: z.number().int().nonnegative(),
    })
    .strict()
    .optional(),
});

export const claimSchema = z.object({
  workerId: identifier,
  registrationToken: z.string().uuid(),
  queues: z.array(identifier).min(1).max(64),
  capabilities: z.array(identifier).max(128).default([]),
  waitMs: z.number().int().min(0).max(30000).optional(),
});

export const attemptCompletionSchema = z.object({
  workerId: identifier,
  leaseToken: z.string().uuid(),
  fabricEpoch: z.number().int().nonnegative(),
  result: z.record(z.unknown()).default({}),
  effects: z
    .array(
      z.object({
        effectKey: z.string().min(1).max(512),
        effectType: identifier,
        payload: z.record(z.unknown()).default({}),
        maxAttempts: z.number().int().min(1).max(100).default(8),
        baseBackoffSeconds: z.number().int().min(1).max(86400).default(60),
      }),
    )
    .max(256)
    .default([]),
});

export const attemptFailureSchema = z.object({
  workerId: identifier,
  leaseToken: z.string().uuid(),
  fabricEpoch: z.number().int().nonnegative(),
  errorCode: identifier,
  errorSummary: z.string().min(1).max(2048),
  retryable: z.boolean().default(true),
});

export const artifactUploadSchema = z.object({
  taskId: z.string().uuid(),
  attemptId: z.string().uuid(),
  workerId: identifier,
  leaseToken: z.string().uuid(),
  fabricEpoch: z.number().int().nonnegative(),
  name: z
    .string()
    .min(1)
    .max(128)
    .regex(/^[a-zA-Z0-9][a-zA-Z0-9._-]*$/),
  contentType: z.string().min(1).max(128).regex(/^[\w.+-]+\/[\w.+-]+$/),
  sha256: z.string().regex(/^[0-9a-f]{64}$/),
  sizeBytes: z.number().int().min(1).max(104857600),
});

export const artifactFinalizeSchema = z.object({
  taskId: z.string().uuid(),
  attemptId: z.string().uuid(),
  workerId: identifier,
  leaseToken: z.string().uuid(),
  fabricEpoch: z.number().int().nonnegative(),
});

export const artifactRecoveryUploadSchema = artifactUploadSchema
  .omit({ leaseToken: true })
  .extend({
    registrationToken: z.string().uuid(),
    attemptRecoveryToken: z.string().uuid(),
  });

export const artifactRecoveryFinalizeSchema = artifactFinalizeSchema
  .omit({ leaseToken: true })
  .extend({
    registrationToken: z.string().uuid(),
    attemptRecoveryToken: z.string().uuid(),
  });

export const effectClaimSchema = z.object({
  consumerId: identifier,
  source: identifier,
  effectTypes: z.array(identifier).min(1).max(128),
  limit: z.number().int().min(1).max(100).default(10),
});

export const effectDeliverySchema = z.object({
  consumerId: identifier,
  claimToken: z.string().uuid(),
  fabricEpoch: z.number().int().nonnegative(),
  providerReceipt: z.record(z.unknown()),
});

export const effectFailureSchema = z.object({
  consumerId: identifier,
  claimToken: z.string().uuid(),
  fabricEpoch: z.number().int().nonnegative(),
  errorSummary: z.string().min(1).max(2048),
  retryAfterSeconds: z.number().int().min(1).max(86400).default(60),
});

export const reliabilityObservationSchema = z
  .object({
    source: identifier,
    incidentKey: z.string().min(1).max(512).regex(/^[a-zA-Z0-9._:/-]+$/),
    revision: z.number().int().min(1),
    active: z.boolean(),
    severity: z.enum(["info", "warning", "critical"]),
    code: identifier,
    summary: z.string().min(1).max(2048),
    evidence: z.record(z.unknown()).default({}),
    affected: z
      .object({
        kind: identifier,
        id: z.string().min(1).max(512),
      })
      .strict(),
    runbook: z
      .object({
        ref: z.string().min(1).max(1024),
      })
      .strict(),
    observedAt: z.string().datetime({ offset: true }),
  })
  .strict()
  .superRefine((observation, context) => {
    if (!observation.active && observation.severity === "info") {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["severity"],
        message: "recovery observations retain warning or critical severity",
      });
    }
  });

export const configReloadSchema = z
  .object({
    rotationId: z.string().uuid(),
    preparationToken: z
      .string()
      .regex(/^cpr1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/),
    expectedCurrentFingerprint: z.string().regex(/^[a-f0-9]{64}$/),
    expectedCandidateFingerprint: z.string().regex(/^[a-f0-9]{64}$/),
  })
  .strict();

export const deliveryReconciliationSchema = z
  .object({
    // Projection repair is opt-in. The default reads PostgreSQL truth and
    // reports the bounded plan without publishing a BullMQ job or writing a
    // delivery timestamp.
    apply: z.boolean().default(false),
    limit: z.number().int().min(1).max(500).default(500),
  })
  .strict()
  .default({});

export const scheduleUpsertSchema = z.object({
  id: identifier,
  namespace: identifier,
  queue: identifier,
  taskType: identifier,
  payload: z.record(z.unknown()).default({}),
  requiredCapabilities: z.array(identifier).max(128).default([]),
  priority: z.number().int().min(-1000).max(1000).default(0),
  maxAttempts: z.number().int().min(1).max(100).default(8),
  intervalSeconds: z.number().int().min(1).max(31536000),
  nextOccurrenceAt: z.string().datetime({ offset: true }),
  enabled: z.boolean().default(true),
});

export type TaskAdmission = z.infer<typeof taskAdmissionSchema>;
export type WorkerRegistration = z.infer<typeof workerRegistrationSchema>;
export type WorkerHeartbeat = z.infer<typeof workerHeartbeatSchema>;
export type ClaimRequest = z.infer<typeof claimSchema>;
export type AttemptCompletion = z.infer<typeof attemptCompletionSchema>;
export type AttemptFailure = z.infer<typeof attemptFailureSchema>;
export type ArtifactUpload = z.infer<typeof artifactUploadSchema>;
export type ArtifactFinalize = z.infer<typeof artifactFinalizeSchema>;
export type ArtifactRecoveryUpload = z.infer<
  typeof artifactRecoveryUploadSchema
>;
export type ArtifactRecoveryFinalize = z.infer<
  typeof artifactRecoveryFinalizeSchema
>;
export type EffectClaim = z.infer<typeof effectClaimSchema>;
export type EffectDelivery = z.infer<typeof effectDeliverySchema>;
export type EffectFailure = z.infer<typeof effectFailureSchema>;
export type ReliabilityObservation = z.infer<
  typeof reliabilityObservationSchema
>;
export type ScheduleUpsert = z.infer<typeof scheduleUpsertSchema>;
export type DeliveryReconciliation = z.infer<typeof deliveryReconciliationSchema>;

export type TaskRecord = {
  id: string;
  namespace: string;
  queue: string;
  taskType: string;
  schedulingClass: "interactive" | "background";
  payload: Record<string, unknown>;
  requiredCapabilities: string[];
  priority: number;
  status: string;
  maxAttempts: number;
  attemptCount: number;
  availableAt: string;
  createdAt: string;
};

export type Assignment = {
  attemptId: string;
  attemptRecoveryToken: string;
  task: TaskRecord;
  leaseToken: string;
  leaseExpiresAt: string;
  fabricEpoch: number;
};

export type WorkerRegistrationReceipt = {
  workerId: string;
  registrationToken: string;
  leaseExpiresAt: string;
  fabricEpoch: number;
};

export type ReconcileReceipt = {
  expiredRequeued: number;
  expiredDeadLettered: number;
  effectsRequeued: number;
  effectsDeadLettered: number;
  deliveriesPublished: number;
  occurredAt: string;
};

export type DeliveryReconciliationReceipt = {
  dryRun: boolean;
  eligible: number;
  deliveriesPublished: number;
  taskIds: string[];
  occurredAt: string;
};

export type EffectAssignment = {
  effectId: string;
  effectKey: string;
  taskId: string;
  effectType: string;
  payload: Record<string, unknown>;
  claimToken: string;
  claimExpiresAt: string;
  fabricEpoch: number;
  attemptCount: number;
  maxAttempts: number;
};

export type ArtifactRecord = {
  artifactId: string;
  taskId: string;
  attemptId: string;
  name: string;
  contentType: string;
  sha256: string;
  sizeBytes: number;
  status: "pending" | "available" | "failed" | "expired";
  uri: string | null;
  createdAt: string;
  availableAt: string | null;
};
