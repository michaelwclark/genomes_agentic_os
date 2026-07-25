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
  observedAt: z.string().datetime().optional(),
}).strict().superRefine((candidate, context) => {
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
  authorityMode: "synchronous" | "degraded_primary";
  degradedUntil: string | null;
  degradedIncidentDigest: string | null;
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

export type PromotionMutation = {
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

export type FailbackCommitMutation = PromotionMutation & {
  planTokenHash: string;
  nowEpoch: number;
};
