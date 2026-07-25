import {
  createHash,
  randomBytes,
  randomUUID,
  sign,
  timingSafeEqual,
} from "node:crypto";
import type { WitnessConfig } from "./config.js";
import type {
  AuditRecord,
  CandidateRecord,
  CandidateUpdate,
  Eligibility,
  FailbackCommitRequest,
  FailbackPrepareRequest,
  FailbackPlanRequest,
  LeadershipState,
  PromotionRequest,
} from "./contracts.js";
import {
  ConditionalWriteError,
  type WitnessStore,
} from "./store.js";

export class WitnessConflictError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "WitnessConflictError";
  }
}

export class WitnessNotFoundError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "WitnessNotFoundError";
  }
}

type Dependencies = {
  now?: () => Date;
  randomToken?: () => string;
  randomId?: () => string;
};

function sha256(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

function safeEqual(left: string, right: string): boolean {
  const leftBuffer = Buffer.from(left);
  const rightBuffer = Buffer.from(right);
  return (
    leftBuffer.length === rightBuffer.length &&
    timingSafeEqual(leftBuffer, rightBuffer)
  );
}

export class LeadershipWitness {
  private readonly now: () => Date;
  private readonly randomToken: () => string;
  private readonly randomId: () => string;

  constructor(
    readonly config: WitnessConfig,
    readonly store: WitnessStore,
    dependencies: Dependencies = {},
  ) {
    this.now = dependencies.now ?? (() => new Date());
    this.randomToken =
      dependencies.randomToken ??
      (() => randomBytes(32).toString("base64url"));
    this.randomId = dependencies.randomId ?? randomUUID;
  }

  private timestamp(): string {
    return this.now().toISOString();
  }

  private auditRecord(
    eventType: AuditRecord["eventType"],
    detail: Record<string, unknown>,
    additional: Partial<Omit<AuditRecord, "auditId" | "eventType" | "actor" | "occurredAt" | "detail">> = {},
  ): AuditRecord {
    return {
      auditId: this.randomId(),
      eventType,
      actor: "authenticated_admin",
      occurredAt: this.timestamp(),
      ...additional,
      detail,
    };
  }

  private eligibility(
    candidate: CandidateRecord | undefined,
    state: LeadershipState,
    nowEpoch: number,
  ): Eligibility {
    const reasons: string[] = [];
    if (!candidate) {
      reasons.push("candidate_not_reported");
      return { eligible: false, reasons };
    }
    if (!candidate.healthy) reasons.push("candidate_unhealthy");
    if (!candidate.inRecovery) reasons.push("candidate_not_in_recovery");
    if (candidate.receiverState !== "streaming") {
      reasons.push("wal_receiver_not_streaming");
    }
    if (
      candidate.observedAtEpoch <
      nowEpoch - this.config.candidateFreshnessSeconds
    ) {
      reasons.push("candidate_observation_stale");
    }
    if (candidate.replicaLagBytes > this.config.maxReplicaLagBytes) {
      reasons.push("replica_lag_exceeds_limit");
    }
    const baselineEpoch = Math.floor(
      new Date(state.leaderBaselineAt ?? "").getTime() / 1000,
    );
    if (
      state.leaderWalPosition === null ||
      state.upstreamSystemId === null ||
      !Number.isFinite(baselineEpoch)
    ) {
      reasons.push("leader_wal_baseline_missing");
    } else {
      if (
        baselineEpoch <
        nowEpoch - this.config.leaderBaselineMaxAgeSeconds
      ) {
        reasons.push("leader_wal_baseline_stale");
      }
      if (candidate.upstreamSystemId !== state.upstreamSystemId) {
        reasons.push("upstream_system_id_mismatch");
      }
      if (
        Math.max(0, state.leaderWalPosition - candidate.replayWalPosition) >
        this.config.maxReplicaLagBytes
      ) {
        reasons.push("upstream_wal_gap_exceeds_limit");
      }
    }
    const lastMessageAtEpoch = Math.floor(
      new Date(candidate.lastMessageAt).getTime() / 1000,
    );
    if (
      lastMessageAtEpoch <
      nowEpoch - this.config.candidateFreshnessSeconds
    ) {
      reasons.push("wal_receiver_message_stale");
    }
    const lagMeasuredAtEpoch = Math.floor(
      new Date(candidate.lagMeasuredAt).getTime() / 1000,
    );
    if (
      lagMeasuredAtEpoch <
      nowEpoch - this.config.candidateFreshnessSeconds
    ) {
      reasons.push("replica_lag_measurement_stale");
    }
    if (candidate.timelineId !== state.timelineId) {
      reasons.push("timeline_mismatch");
    }
    if (candidate.configDigest !== state.configDigest) {
      reasons.push("config_digest_mismatch");
    }
    return { eligible: reasons.length === 0, reasons };
  }

  private leadershipToken(
    leader: string,
    epoch: number,
    receiptId: string,
    occurredAt: string,
    authorityMode: LeadershipState["authorityMode"],
    degradedUntil: string | null,
  ): string {
    const expiresAt = new Date(
      new Date(occurredAt).getTime() +
        this.config.candidateFreshnessSeconds * 1000,
    ).toISOString();
    const payload = Buffer.from(
      JSON.stringify({
        v: 2,
        cluster: this.config.clusterId,
        leader,
        epoch,
        receiptId,
        authorityMode,
        degradedUntil,
        issuedAt: occurredAt,
        expiresAt,
      }),
    ).toString("base64url");
    const signature = sign(
      null,
      Buffer.from(payload),
      this.config.signingPrivateKey,
    ).toString("base64url");
    return `v2.${payload}.${signature}`;
  }

  async initialize(): Promise<LeadershipState> {
    const occurredAt = this.timestamp();
    const state: LeadershipState = {
      currentLeader: this.config.initialLeader,
      fabricEpoch: 1,
      timelineId: this.config.initialTimelineId,
      configDigest: this.config.initialConfigDigest,
      leaderWalPosition: null,
      leaderBaselineAt: null,
      upstreamSystemId: null,
      updatedAt: occurredAt,
      fenceDigest: sha256(
        `bootstrap:${this.config.clusterId}:${this.config.initialLeader}:1`,
      ),
      authorityMode: "synchronous",
      degradedUntil: null,
      degradedIncidentDigest: null,
    };
    return this.store.initialize(
      state,
      this.auditRecord("initialized", {
        clusterId: this.config.clusterId,
        leader: state.currentLeader,
        fabricEpoch: state.fabricEpoch,
        timelineId: state.timelineId,
        configDigest: state.configDigest,
      }),
    );
  }

  async ready(): Promise<void> {
    await this.store.ready();
  }

  async status() {
    const [state, candidates] = await Promise.all([
      this.store.getState(),
      this.store.listCandidates(),
    ]);
    const nowEpoch = Math.floor(this.now().getTime() / 1000);
    const candidateMap = Object.fromEntries(
      candidates
        .sort((a, b) => a.candidate.localeCompare(b.candidate))
        .map((candidate) => [
          candidate.candidate,
          {
            healthy: candidate.healthy,
            inRecovery: candidate.inRecovery,
            timelineId: candidate.timelineId,
            receiveLsn: candidate.receiveLsn,
            replayLsn: candidate.replayLsn,
            receiveWalPosition: candidate.receiveWalPosition,
            replayWalPosition: candidate.replayWalPosition,
            replicaLagBytes: candidate.replicaLagBytes,
            lagMeasuredAt: candidate.lagMeasuredAt,
            upstreamSystemId: candidate.upstreamSystemId,
            receiverState: candidate.receiverState,
            lastMessageAt: candidate.lastMessageAt,
            upstreamWalGapBytes:
              state.leaderWalPosition === null
                ? null
                : Math.max(
                    0,
                    state.leaderWalPosition - candidate.replayWalPosition,
                  ),
            configDigest: candidate.configDigest,
            observedAt: candidate.observedAt,
            ...this.eligibility(candidate, state, nowEpoch),
          },
        ]),
    );
    const leaderCandidate = candidates.find(
      (item) => item.candidate === state.currentLeader,
    );
    const leaderEligibility = this.eligibility(
      leaderCandidate,
      state,
      nowEpoch,
    );
    const leaderHasBaseline =
      state.leaderWalPosition !== null &&
      state.leaderBaselineAt !== null &&
      state.upstreamSystemId !== null;
    // A negative health report is an alarm, not a revocation primitive. The
    // witness waits for the entire signed-leadership lease window to expire,
    // so an old primary cannot retain a still-valid proof after promotion.
    const leaderLeaseExpired = Boolean(
      leaderCandidate &&
        leaderCandidate.observedAtEpoch <
          nowEpoch - this.config.candidateFreshnessSeconds,
    );
    const promotionAllowed =
      leaderHasBaseline &&
      leaderLeaseExpired &&
      candidates.some(
        (candidate) =>
          candidate.candidate !== state.currentLeader &&
          this.eligibility(candidate, state, nowEpoch).eligible,
      );
    const sampledAt = this.timestamp();
    const leadershipToken = this.leadershipToken(
      state.currentLeader,
      state.fabricEpoch,
      `status:${state.fenceDigest}`,
      sampledAt,
      state.authorityMode,
      state.degradedUntil,
    );
    return {
      apiVersion: "execution-fabric-leadership/v1",
      clusterId: this.config.clusterId,
      ...state,
      promotionAllowed,
      leaderEligibility,
      candidates: candidateMap,
      safety: {
        maxReplicaLagBytes: this.config.maxReplicaLagBytes,
        candidateFreshnessSeconds: this.config.candidateFreshnessSeconds,
        leaderBaselineMaxAgeSeconds:
          this.config.leaderBaselineMaxAgeSeconds,
        automaticFailback: false,
      },
      sampledAt,
      leadershipToken,
    };
  }

  async updateCandidate(
    candidate: string,
    update: CandidateUpdate,
  ): Promise<CandidateRecord> {
    const nowEpoch = Math.floor(this.now().getTime() / 1000);
    const observedAt = update.observedAt ?? this.timestamp();
    const observedAtEpoch = Math.floor(new Date(observedAt).getTime() / 1000);
    if (
      Math.abs(observedAtEpoch - nowEpoch) >
      this.config.maxReportSkewSeconds
    ) {
      throw new WitnessConflictError(
        "candidate observation exceeds the allowed clock-skew window",
      );
    }
    const lagMeasuredAtEpoch = Math.floor(
      new Date(update.lagMeasuredAt).getTime() / 1000,
    );
    if (
      Math.abs(lagMeasuredAtEpoch - nowEpoch) >
      this.config.maxReportSkewSeconds
    ) {
      throw new WitnessConflictError(
        "replica lag measurement exceeds the allowed clock-skew window",
      );
    }
    const lastMessageAtEpoch = Math.floor(
      new Date(update.lastMessageAt).getTime() / 1000,
    );
    if (lastMessageAtEpoch > nowEpoch + this.config.maxReportSkewSeconds) {
      throw new WitnessConflictError(
        "WAL receiver last-message time exceeds the allowed clock-skew window",
      );
    }
    const record: CandidateRecord = {
      candidate,
      ...update,
      observedAt,
      observedAtEpoch,
    };
    const state = await this.store.getState();
    const isCurrentLeaderBaseline =
      candidate === state.currentLeader &&
      !record.inRecovery &&
      record.timelineId === state.timelineId &&
      record.configDigest === state.configDigest;
    try {
      await this.store.putCandidate(
        record,
        this.auditRecord("candidate_updated", {
        candidate,
        healthy: record.healthy,
        inRecovery: record.inRecovery,
        timelineId: record.timelineId,
        receiveLsn: record.receiveLsn,
        replayLsn: record.replayLsn,
        receiveWalPosition: record.receiveWalPosition,
        replayWalPosition: record.replayWalPosition,
        replicaLagBytes: record.replicaLagBytes,
        lagMeasuredAt: record.lagMeasuredAt,
        upstreamSystemId: record.upstreamSystemId,
        receiverState: record.receiverState,
        lastMessageAt: record.lastMessageAt,
        configDigest: record.configDigest,
        observedAt,
      }),
        isCurrentLeaderBaseline
          ? {
              expectedLeader: state.currentLeader,
              expectedTimelineId: state.timelineId,
              expectedConfigDigest: state.configDigest,
            }
          : undefined,
      );
    } catch (error) {
      if (error instanceof ConditionalWriteError) {
        throw new WitnessConflictError(error.message);
      }
      throw error;
    }
    return record;
  }

  async promote(request: PromotionRequest) {
    const authorityMode = request.authorityMode ?? "synchronous";
    const [state, candidates] = await Promise.all([
      this.store.getState(),
      this.store.listCandidates(),
    ]);
    if (request.candidate === request.expectedLeader) {
      throw new WitnessConflictError("candidate is already the expected leader");
    }
    if (
      authorityMode === "degraded_primary" &&
      !(this.config.allowDegradedPrimary ?? false)
    ) {
      throw new WitnessConflictError(
        "degraded-primary authority is disabled by witness policy",
      );
    }
    if (
      authorityMode === "degraded_primary" &&
      (request.degradedDurationSeconds ?? 0) >
        (this.config.maxDegradedPrimarySeconds ?? 3600)
    ) {
      throw new WitnessConflictError(
        "requested degraded-primary duration exceeds witness policy",
      );
    }
    const nowEpoch = Math.floor(this.now().getTime() / 1000);
    const candidate = candidates.find(
      (item) => item.candidate === request.candidate,
    );
    const candidateEligibility = this.eligibility(candidate, state, nowEpoch);
    if (!candidateEligibility.eligible) {
      throw new WitnessConflictError(
        `promotion candidate is not eligible: ${candidateEligibility.reasons.join(",")}`,
      );
    }
    if (
      state.leaderWalPosition === null ||
      state.leaderBaselineAt === null ||
      state.upstreamSystemId === null ||
      !candidate
    ) {
      throw new WitnessConflictError(
        "leader WAL baseline is missing; promotion is unsafe",
      );
    }
    const occurredAt = this.timestamp();
    const receiptId = this.randomId();
    const nextEpoch = request.expectedEpoch + 1;
    const degradedUntil =
      authorityMode === "degraded_primary"
        ? new Date(
            this.now().getTime() +
              (request.degradedDurationSeconds ?? 0) * 1000,
          ).toISOString()
        : null;
    const fenceToken = this.leadershipToken(
      request.candidate,
      nextEpoch,
      receiptId,
      occurredAt,
      authorityMode,
      degradedUntil,
    );
    const nextState: LeadershipState = {
      currentLeader: request.candidate,
      fabricEpoch: nextEpoch,
      timelineId: state.timelineId + 1,
      configDigest: state.configDigest,
      leaderWalPosition: candidate.replayWalPosition,
      leaderBaselineAt: candidate.lagMeasuredAt,
      upstreamSystemId: state.upstreamSystemId,
      updatedAt: occurredAt,
      fenceDigest: sha256(fenceToken),
      authorityMode,
      degradedUntil,
      degradedIncidentDigest:
        authorityMode === "degraded_primary"
          ? request.incidentDigest
          : null,
    };
    try {
      await this.store.promote({
        expectedLeader: request.expectedLeader,
        expectedEpoch: request.expectedEpoch,
        candidate: request.candidate,
        configDigest: state.configDigest,
        freshAfterEpoch:
          Math.floor(this.now().getTime() / 1000) -
          this.config.candidateFreshnessSeconds,
        maxReplicaLagBytes: this.config.maxReplicaLagBytes,
        expectedTimelineId: state.timelineId,
        expectedLeaderWalPosition: state.leaderWalPosition,
        minimumReplayWalPosition: Math.max(
          0,
          state.leaderWalPosition - this.config.maxReplicaLagBytes,
        ),
        expectedUpstreamSystemId: state.upstreamSystemId,
        leaderBaselineFreshAfterEpoch:
          nowEpoch - this.config.leaderBaselineMaxAgeSeconds,
        receiverFreshAfterEpoch:
          nowEpoch - this.config.candidateFreshnessSeconds,
        nextState,
        audit: {
          auditId: receiptId,
          eventType: "promotion_committed",
          actor: "authenticated_admin",
          occurredAt,
          previousLeader: request.expectedLeader,
          newLeader: request.candidate,
          previousEpoch: request.expectedEpoch,
          newEpoch: nextEpoch,
          requestDigest: request.incidentDigest,
          detail: {
            fenceDigest: nextState.fenceDigest,
            authorityMode: nextState.authorityMode,
            degradedUntil,
          },
        },
      });
    } catch (error) {
      if (error instanceof ConditionalWriteError) {
        throw new WitnessConflictError(error.message);
      }
      throw error;
    }
    return {
      apiVersion: "execution-fabric-leadership/v1",
      decision: "promoted",
      receiptId,
      previousLeader: request.expectedLeader,
      currentLeader: request.candidate,
      fabricEpoch: nextEpoch,
      clusterId: this.config.clusterId,
      fenceToken,
      authorityMode: nextState.authorityMode,
      degradedUntil,
      committedAt: occurredAt,
    };
  }

  async planFailback(request: FailbackPlanRequest) {
    const [state, candidates] = await Promise.all([
      this.store.getState(),
      this.store.listCandidates(),
    ]);
    const nowEpoch = Math.floor(this.now().getTime() / 1000);
    const preparation = await this.store.getFailbackPlan(
      sha256(request.preparationToken),
    );
    if (
      !preparation ||
      preparation.phase !== "reseed" ||
      preparation.from !== request.from ||
      preparation.to !== request.to ||
      preparation.expectedLeader !== state.currentLeader ||
      preparation.expectedEpoch !== state.fabricEpoch ||
      preparation.expiresAtEpoch < nowEpoch
    ) {
      throw new WitnessConflictError(
        "failback reseed preparation is missing, expired, or bound to another leadership epoch",
      );
    }
    const targetEligibility = this.eligibility(
      candidates.find((item) => item.candidate === request.to),
      state,
      nowEpoch,
    );
    const reasons = [...targetEligibility.reasons];
    const target = candidates.find((item) => item.candidate === request.to);
    if (state.currentLeader !== request.from) {
      reasons.push("source_is_not_current_leader");
    }
    if (request.from === request.to) reasons.push("source_and_target_match");
    if (reasons.length > 0) {
      await this.store.appendAudit(
        this.auditRecord("failback_rejected", {
          from: request.from,
          to: request.to,
          reasons,
        }),
      );
      return {
        apiVersion: "execution-fabric-leadership/v1",
        safe: false,
        reasons,
        currentLeader: state.currentLeader,
        fabricEpoch: state.fabricEpoch,
      };
    }
    if (
      state.leaderWalPosition === null ||
      state.leaderBaselineAt === null ||
      state.upstreamSystemId === null ||
      !target
    ) {
      throw new WitnessConflictError(
        "leader WAL baseline or failback target is missing",
      );
    }

    const planToken = this.randomToken();
    const tokenHash = sha256(planToken);
    const createdAt = this.timestamp();
    const expiresAtEpoch = nowEpoch + this.config.planTtlSeconds;
    const expiresAt = new Date(expiresAtEpoch * 1000).toISOString();
    try {
      await this.store.putFailbackPlan(
        {
          phase: "transfer",
          tokenHash,
          from: request.from,
          to: request.to,
          expectedLeader: state.currentLeader,
          expectedEpoch: state.fabricEpoch,
          configDigest: state.configDigest,
          createdAt,
          expiresAt,
          expiresAtEpoch,
          freshAfterEpoch: nowEpoch - this.config.candidateFreshnessSeconds,
          maxReplicaLagBytes: this.config.maxReplicaLagBytes,
          expectedTimelineId: state.timelineId,
          expectedLeaderWalPosition: state.leaderWalPosition,
          minimumReplayWalPosition: Math.max(
            0,
            state.leaderWalPosition - this.config.maxReplicaLagBytes,
          ),
          expectedUpstreamSystemId: state.upstreamSystemId,
          leaderBaselineFreshAfterEpoch:
            nowEpoch - this.config.leaderBaselineMaxAgeSeconds,
          receiverFreshAfterEpoch:
            nowEpoch - this.config.candidateFreshnessSeconds,
        },
        this.auditRecord("failback_planned", {
          from: request.from,
          to: request.to,
          tokenHash,
          expiresAt,
        }),
      );
    } catch (error) {
      if (error instanceof ConditionalWriteError) {
        throw new WitnessConflictError(error.message);
      }
      throw error;
    }
    return {
      apiVersion: "execution-fabric-leadership/v1",
      safe: true,
      planToken,
      from: request.from,
      to: request.to,
      expectedEpoch: state.fabricEpoch,
      expiresAt,
      approvalRequired: true,
    };
  }

  async prepareFailback(request: FailbackPrepareRequest) {
    const state = await this.store.getState();
    const nowEpoch = Math.floor(this.now().getTime() / 1000);
    if (state.currentLeader !== request.from) {
      throw new WitnessConflictError(
        "failback reseed source is not the current witnessed leader",
      );
    }
    if (
      state.leaderWalPosition === null ||
      state.leaderBaselineAt === null ||
      state.upstreamSystemId === null
    ) {
      throw new WitnessConflictError(
        "leader WAL baseline is required before authorizing standby reseed",
      );
    }
    const preparationToken = this.randomToken();
    const tokenHash = sha256(preparationToken);
    const createdAt = this.timestamp();
    const expiresAtEpoch = nowEpoch + this.config.planTtlSeconds;
    const expiresAt = new Date(expiresAtEpoch * 1000).toISOString();
    try {
      await this.store.putFailbackPreparation(
        {
          phase: "reseed",
          tokenHash,
          from: request.from,
          to: request.to,
          expectedLeader: state.currentLeader,
          expectedEpoch: state.fabricEpoch,
          configDigest: state.configDigest,
          createdAt,
          expiresAt,
          expiresAtEpoch,
          freshAfterEpoch: nowEpoch - this.config.candidateFreshnessSeconds,
          maxReplicaLagBytes: this.config.maxReplicaLagBytes,
          expectedTimelineId: state.timelineId,
          expectedLeaderWalPosition: state.leaderWalPosition,
          minimumReplayWalPosition: Math.max(
            0,
            state.leaderWalPosition - this.config.maxReplicaLagBytes,
          ),
          expectedUpstreamSystemId: state.upstreamSystemId,
          leaderBaselineFreshAfterEpoch:
            nowEpoch - this.config.leaderBaselineMaxAgeSeconds,
          receiverFreshAfterEpoch:
            nowEpoch - this.config.candidateFreshnessSeconds,
        },
        this.auditRecord("failback_reseed_authorized", {
          from: request.from,
          to: request.to,
          tokenHash,
          expiresAt,
        }),
      );
    } catch (error) {
      if (error instanceof ConditionalWriteError) {
        throw new WitnessConflictError(error.message);
      }
      throw error;
    }
    return {
      apiVersion: "execution-fabric-leadership/v1",
      authorized: true,
      preparationToken,
      from: request.from,
      to: request.to,
      expectedEpoch: state.fabricEpoch,
      expiresAt,
      nextRequiredAction: "reseed_target_and_publish_candidate_measurement",
    };
  }

  async commitFailback(request: FailbackCommitRequest) {
    const tokenHash = sha256(request.planToken);
    if (!safeEqual(tokenHash, request.approval.planTokenHash)) {
      throw new WitnessConflictError(
        "operator approval is not bound to this failback plan",
      );
    }
    const nowEpoch = Math.floor(this.now().getTime() / 1000);
    const approvedAtEpoch = Math.floor(
      new Date(request.approval.approvedAt).getTime() / 1000,
    );
    if (
      Math.abs(approvedAtEpoch - nowEpoch) >
      this.config.maxReportSkewSeconds
    ) {
      throw new WitnessConflictError(
        "operator approval exceeds the allowed clock-skew window",
      );
    }
    const [plan, state, candidates] = await Promise.all([
      this.store.getFailbackPlan(tokenHash),
      this.store.getState(),
      this.store.listCandidates(),
    ]);
    if (!plan) {
      throw new WitnessNotFoundError(
        "failback plan is missing, expired, or already consumed",
      );
    }
    if (plan.phase !== "transfer") {
      throw new WitnessConflictError(
        "standby reseed authorization cannot be used as a transfer plan",
      );
    }
    if (plan.expiresAtEpoch < nowEpoch) {
      throw new WitnessConflictError("failback plan has expired");
    }
    const target = candidates.find((item) => item.candidate === plan.to);
    const targetEligibility = this.eligibility(target, state, nowEpoch);
    if (!targetEligibility.eligible || !target) {
      throw new WitnessConflictError(
        `failback target is not eligible: ${targetEligibility.reasons.join(",")}`,
      );
    }
    const occurredAt = this.timestamp();
    const receiptId = this.randomId();
    const nextEpoch = plan.expectedEpoch + 1;
    const fenceToken = this.leadershipToken(
      plan.to,
      nextEpoch,
      receiptId,
      occurredAt,
      "synchronous",
      null,
    );
    const nextState: LeadershipState = {
      currentLeader: plan.to,
      fabricEpoch: nextEpoch,
      timelineId: plan.expectedTimelineId + 1,
      configDigest: plan.configDigest,
      leaderWalPosition: target.replayWalPosition,
      leaderBaselineAt: target.lagMeasuredAt,
      upstreamSystemId: plan.expectedUpstreamSystemId,
      updatedAt: occurredAt,
      fenceDigest: sha256(fenceToken),
      authorityMode: "synchronous",
      degradedUntil: null,
      degradedIncidentDigest: null,
    };
    try {
      await this.store.commitFailback({
        expectedLeader: plan.expectedLeader,
        expectedEpoch: plan.expectedEpoch,
        candidate: plan.to,
        configDigest: plan.configDigest,
        freshAfterEpoch: nowEpoch - this.config.candidateFreshnessSeconds,
        maxReplicaLagBytes: this.config.maxReplicaLagBytes,
        expectedTimelineId: plan.expectedTimelineId,
        expectedLeaderWalPosition: plan.expectedLeaderWalPosition,
        minimumReplayWalPosition: plan.minimumReplayWalPosition,
        expectedUpstreamSystemId: plan.expectedUpstreamSystemId,
        leaderBaselineFreshAfterEpoch:
          plan.leaderBaselineFreshAfterEpoch,
        receiverFreshAfterEpoch:
          nowEpoch - this.config.candidateFreshnessSeconds,
        nextState,
        planTokenHash: tokenHash,
        nowEpoch,
        audit: {
          auditId: receiptId,
          eventType: "failback_committed",
          actor: "authenticated_admin",
          occurredAt,
          previousLeader: plan.from,
          newLeader: plan.to,
          previousEpoch: plan.expectedEpoch,
          newEpoch: nextEpoch,
          requestDigest: tokenHash,
          detail: {
            fenceDigest: nextState.fenceDigest,
            approvalId: request.approval.approvalId,
            approvedBy: request.approval.approvedBy,
            approvedAt: request.approval.approvedAt,
          },
        },
      });
    } catch (error) {
      if (error instanceof ConditionalWriteError) {
        throw new WitnessConflictError(error.message);
      }
      throw error;
    }
    return {
      apiVersion: "execution-fabric-leadership/v1",
      decision: "committed",
      receiptId,
      previousLeader: plan.from,
      currentLeader: plan.to,
      fabricEpoch: nextEpoch,
      clusterId: this.config.clusterId,
      fenceToken,
      committedAt: occurredAt,
    };
  }

  async audit(limit: number): Promise<AuditRecord[]> {
    return this.store.listAudit(limit);
  }
}
