import { z } from "zod";

export const hostIdSchema = z.string().regex(/^[a-zA-Z0-9._-]{1,128}$/);
export const digestSchema = z.string().regex(/^[a-f0-9]{64}$/);
export const lsnSchema = z.string().regex(/^[0-9A-F]+\/[0-9A-F]+$/);

export const candidateUpdateSchema = z.object({
  healthy: z.boolean(),
  inRecovery: z.boolean(),
  timelineId: z.number().int().min(1),
  receiveLsn: lsnSchema,
  replayLsn: lsnSchema,
  receiveWalPosition: z.number().int().min(0),
  replayWalPosition: z.number().int().min(0),
  replicaLagBytes: z.number().int().min(0),
  lagMeasuredAt: z.string().datetime(),
  upstreamSystemId: z.string().regex(/^[0-9]{1,32}$/),
  receiverState: z.enum([
    "not_applicable",
    "startup",
    "catchup",
    "streaming",
    "backup",
    "stopping",
    "disconnected",
  ]),
  lastMessageAt: z.string().datetime(),
  configDigest: digestSchema,
  policyCandidateDigest: digestSchema.optional(),
  policyCandidateObservedAt: z.string().datetime().optional(),
  observedAt: z.string().datetime().optional(),
}).strict().superRefine((candidate, context) => {
  if (
    candidate.policyCandidateObservedAt !== undefined &&
    candidate.policyCandidateDigest === undefined
  ) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["policyCandidateObservedAt"],
      message: "staged policy observation requires a staged policy digest",
    });
  }
  if (candidate.replayWalPosition > candidate.receiveWalPosition) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["replayWalPosition"],
      message: "replay WAL position cannot exceed receive WAL position",
    });
  }
  if (
    candidate.replicaLagBytes !==
    candidate.receiveWalPosition - candidate.replayWalPosition
  ) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["replicaLagBytes"],
      message: "replica lag must equal receive minus replay WAL position",
    });
  }
  if (candidate.inRecovery && candidate.receiverState === "not_applicable") {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["receiverState"],
      message: "standby must report its WAL receiver state",
    });
  }
  if (!candidate.inRecovery && candidate.receiverState !== "not_applicable") {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["receiverState"],
      message: "active primary cannot report a WAL receiver state",
    });
  }
});

export const promotionSchema = z.object({
  promotionId: z.string().uuid(),
  candidate: hostIdSchema,
  expectedLeader: hostIdSchema,
  expectedEpoch: z.number().int().min(1),
  incidentDigest: digestSchema,
  authorityMode: z.enum(["synchronous", "degraded_primary"]).optional(),
  degradedDurationSeconds: z.number().int().min(60).max(86400).optional(),
}).strict().superRefine((value, context) => {
  if (
    value.authorityMode === "degraded_primary" &&
    value.degradedDurationSeconds === undefined
  ) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["degradedDurationSeconds"],
      message: "degraded promotion requires a bounded duration",
    });
  }
  if (
    value.authorityMode === "synchronous" &&
    value.degradedDurationSeconds !== undefined
  ) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["degradedDurationSeconds"],
      message: "synchronous promotion cannot request degraded duration",
    });
  }
});

export const configDigestRotationSchema = z
  .object({
    rotationId: z.string().uuid(),
    expectedLeader: hostIdSchema,
    expectedEpoch: z.number().int().min(1),
    expectedCurrentDigest: digestSchema,
    candidateDigest: digestSchema,
  })
  .strict()
  .refine(
    (value) => value.expectedCurrentDigest !== value.candidateDigest,
    {
      path: ["candidateDigest"],
      message: "candidate digest must differ from the current digest",
    },
  );

export const configDigestRotationCommitSchema = z
  .object({
    rotationId: z.string().uuid(),
    preparationToken: z.string().regex(/^cpr1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/),
  })
  .strict();

export const configDigestRotationAbortSchema =
  configDigestRotationCommitSchema;

export const failbackPlanSchema = z
  .object({
    from: hostIdSchema,
    to: hostIdSchema,
    mode: z.literal("manual_failback"),
    preparationToken: z.string().min(32).max(256),
  })
  .refine((value) => value.from !== value.to, {
    message: "failback source and target must differ",
  });

export const failbackCommitSchema = z.object({
  planToken: z.string().min(32).max(256),
  approval: z.object({
    planTokenHash: digestSchema,
    approvalId: z.string().uuid(),
    approvedBy: z.string().min(1).max(128),
    approvedAt: z.string().datetime(),
  }).strict(),
});

export const failbackPrepareSchema = z
  .object({
    from: hostIdSchema,
    to: hostIdSchema,
    mode: z.literal("standby_reseed"),
  })
  .refine((value) => value.from !== value.to, {
    message: "failback source and target must differ",
  });

export type CandidateUpdate = z.infer<typeof candidateUpdateSchema>;
export type PromotionRequest = z.infer<typeof promotionSchema>;
export type ConfigDigestRotationRequest = z.infer<
  typeof configDigestRotationSchema
>;
export type ConfigDigestRotationCommitRequest = z.infer<
  typeof configDigestRotationCommitSchema
>;
export type ConfigDigestRotationAbortRequest = z.infer<
  typeof configDigestRotationAbortSchema
>;
export type FailbackPlanRequest = z.infer<typeof failbackPlanSchema>;
export type FailbackPrepareRequest = z.infer<typeof failbackPrepareSchema>;
export type FailbackCommitRequest = z.infer<typeof failbackCommitSchema>;

export type LeadershipState = {
  currentLeader: string;
  fabricEpoch: number;
  timelineId: number;
  configDigest: string;
  leaderWalPosition: number | null;
  leaderBaselineAt: string | null;
  upstreamSystemId: string | null;
  updatedAt: string;
  fenceDigest: string;
  authorityMode: "synchronous" | "degraded_primary" | "standalone_primary";
  degradedUntil: string | null;
  degradedIncidentDigest: string | null;
};

export type PromotionReceipt = {
  apiVersion: "execution-fabric-leadership/v1";
  decision: "promoted";
  promotionId: string;
  requestDigest: string;
  receiptId: string;
  previousLeader: string;
  currentLeader: string;
  fabricEpoch: number;
  clusterId: string;
  fenceToken: string;
  authorityMode: LeadershipState["authorityMode"];
  degradedUntil: string | null;
  committedAt: string;
};

export type CandidateRecord = CandidateUpdate & {
  candidate: string;
  observedAt: string;
  observedAtEpoch: number;
};

export type AuditRecord = {
  auditId: string;
  eventType:
    | "initialized"
    | "candidate_updated"
    | "config_digest_rotation_prepared"
    | "config_digest_rotation_aborted"
    | "config_digest_rotated"
    | "promotion_committed"
    | "failback_reseed_authorized"
    | "failback_planned"
    | "failback_rejected"
    | "failback_committed";
  actor: string;
  occurredAt: string;
  previousLeader?: string;
  newLeader?: string;
  previousEpoch?: number;
  newEpoch?: number;
  requestDigest?: string;
  detail: Record<string, unknown>;
};

export type ConfigDigestRotationPreparation = {
  apiVersion: "execution-fabric-leadership/v1";
  decision: "config_digest_rotation_prepared";
  rotationId: string;
  requestDigest: string;
  expectedLeader: string;
  expectedEpoch: number;
  expectedCurrentDigest: string;
  candidateDigest: string;
  candidateHosts: string[];
  expectedTimelineId: number;
  expectedLeaderWalPosition: number;
  expectedUpstreamSystemId: string;
  minimumStandbyReplayWalPosition: number;
  maxReplicaLagBytes: number;
  preparationToken: string;
  preparationTokenHash: string;
  issuedAt: string;
  expiresAt: string;
  expiresAtEpoch: number;
};

export type ConfigDigestRotationReceipt = {
  apiVersion: "execution-fabric-leadership/v1";
  decision: "config_digest_rotated";
  rotationId: string;
  requestDigest: string;
  currentLeader: string;
  fabricEpoch: number;
  previousConfigDigest: string;
  configDigest: string;
  candidateHosts: string[];
  preparationTokenHash: string;
  committedAt: string;
};

export type ConfigDigestRotationAbortReceipt = {
  apiVersion: "execution-fabric-leadership/v1";
  decision: "config_digest_rotation_aborted";
  rotationId: string;
  requestDigest: string;
  currentLeader: string;
  fabricEpoch: number;
  configDigest: string;
  candidateDigest: string;
  evidenceHost: string;
  preparationTokenHash: string;
  expiredAt: string;
  abortedAt: string;
};

export type ConfigDigestCandidateCondition = {
  candidate: string;
  inRecovery: boolean;
  receiverState: CandidateRecord["receiverState"];
  minimumReplayWalPosition: number;
};

export type ConfigDigestRotationPreparationMutation = {
  preparation: ConfigDigestRotationPreparation;
  expectedLeader: string;
  expectedEpoch: number;
  expectedCurrentDigest: string;
  candidateDigest: string;
  expectedTimelineId: number;
  expectedLeaderWalPosition: number;
  expectedUpstreamSystemId: string;
  leaderBaselineFreshAfterEpoch: number;
  candidateFreshAfterEpoch: number;
  policyCandidateFreshAfterEpoch: number;
  receiverFreshAfterEpoch: number;
  maxReplicaLagBytes: number;
  candidates: ConfigDigestCandidateCondition[];
  audit: AuditRecord;
};

export type ConfigDigestRotationCommitMutation = {
  preparation: ConfigDigestRotationPreparation;
  preparationTokenHash: string;
  candidateFreshAfterEpoch: number;
  receiverFreshAfterEpoch: number;
  commitCandidate: ConfigDigestCandidateCondition;
  nextState: LeadershipState;
  receipt: ConfigDigestRotationReceipt;
  audit: AuditRecord;
};

export type ConfigDigestRotationAbortMutation = {
  preparation: ConfigDigestRotationPreparation;
  preparationTokenHash: string;
  nowEpoch: number;
  evidenceAfterEpoch: number;
  evidenceCandidate: ConfigDigestCandidateCondition;
  candidateDigestGuardHosts: string[];
  receipt: ConfigDigestRotationAbortReceipt;
  audit: AuditRecord;
};

export type FailbackPlan = {
  phase: "reseed" | "transfer";
  tokenHash: string;
  from: string;
  to: string;
  expectedLeader: string;
  expectedEpoch: number;
  configDigest: string;
  createdAt: string;
  expiresAt: string;
  expiresAtEpoch: number;
  freshAfterEpoch: number;
  maxReplicaLagBytes: number;
  expectedTimelineId: number;
  expectedLeaderWalPosition: number;
  minimumReplayWalPosition: number;
  expectedUpstreamSystemId: string;
  leaderBaselineFreshAfterEpoch: number;
  receiverFreshAfterEpoch: number;
};

export type Eligibility = {
  eligible: boolean;
  reasons: string[];
};

export type LeadershipCasMutation = {
  expectedLeader: string;
  expectedEpoch: number;
  candidate: string;
  configDigest: string;
  freshAfterEpoch: number;
  maxReplicaLagBytes: number;
  expectedTimelineId: number;
  expectedLeaderWalPosition: number;
  minimumReplayWalPosition: number;
  expectedUpstreamSystemId: string;
  leaderBaselineFreshAfterEpoch: number;
  receiverFreshAfterEpoch: number;
  nextState: LeadershipState;
  audit: AuditRecord;
};

export type PromotionMutation = LeadershipCasMutation & {
  promotionId: string;
  requestDigest: string;
  receipt: PromotionReceipt;
};

export type FailbackCommitMutation = LeadershipCasMutation & {
  planTokenHash: string;
  nowEpoch: number;
};
