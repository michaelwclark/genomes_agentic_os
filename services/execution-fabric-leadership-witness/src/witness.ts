import {
  createHash,
  createPublicKey,
  randomBytes,
  randomUUID,
  sign,
  timingSafeEqual,
  verify,
} from "node:crypto";
import type { WitnessConfig } from "./config.js";
import type {
  AuditRecord,
  CandidateRecord,
  CandidateUpdate,
  ConfigDigestCandidateCondition,
  ConfigDigestRotationAbortReceipt,
  ConfigDigestRotationAbortRequest,
  ConfigDigestRotationCommitRequest,
  ConfigDigestRotationPreparation,
  ConfigDigestRotationReceipt,
  ConfigDigestRotationRequest,
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

  private standaloneEligibility(
    candidate: CandidateRecord | undefined,
    state: LeadershipState,
    nowEpoch: number,
  ): Eligibility {
    const reasons: string[] = [];
    if (!candidate) {
      return { eligible: false, reasons: ["candidate_not_reported"] };
    }
    if (!candidate.healthy) reasons.push("candidate_unhealthy");
    if (candidate.inRecovery) reasons.push("standalone_primary_in_recovery");
    if (candidate.receiverState !== "not_applicable") {
      reasons.push("standalone_primary_receiver_state_invalid");
    }
    if (
      candidate.observedAtEpoch <
      nowEpoch - this.config.candidateFreshnessSeconds
    ) {
      reasons.push("candidate_observation_stale");
    }
    for (const [field, value] of [
      ["replica_lag_measurement_stale", candidate.lagMeasuredAt],
      ["wal_receiver_message_stale", candidate.lastMessageAt],
    ] as const) {
      if (
        Math.floor(new Date(value).getTime() / 1000) <
        nowEpoch - this.config.candidateFreshnessSeconds
      ) {
        reasons.push(field);
      }
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
    configDigest: string,
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
        configDigest,
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

  private configRotationPreparationToken(
    request: ConfigDigestRotationRequest,
    issuedAt: string,
    expiresAt: string,
  ): string {
    const payload = Buffer.from(
      JSON.stringify({
        v: 1,
        type: "config_digest_rotation_preparation",
        clusterId: this.config.clusterId,
        rotationId: request.rotationId,
        expectedLeader: request.expectedLeader,
        expectedEpoch: request.expectedEpoch,
        expectedCurrentDigest: request.expectedCurrentDigest,
        candidateDigest: request.candidateDigest,
        issuedAt,
        expiresAt,
      }),
    ).toString("base64url");
    const signature = sign(
      null,
      Buffer.from(payload),
      this.config.signingPrivateKey,
    ).toString("base64url");
    return `cpr1.${payload}.${signature}`;
  }

  private validConfigRotationPreparationToken(
    token: string,
    preparation: ConfigDigestRotationPreparation,
  ): boolean {
    const [version, payload, signature, extra] = token.split(".");
    if (
      version !== "cpr1" ||
      !payload ||
      !signature ||
      extra !== undefined
    ) {
      return false;
    }
    try {
      if (
        !verify(
          null,
          Buffer.from(payload),
          createPublicKey(this.config.signingPrivateKey),
          Buffer.from(signature, "base64url"),
        )
      ) {
        return false;
      }
      const decoded = JSON.parse(
        Buffer.from(payload, "base64url").toString("utf8"),
      ) as Record<string, unknown>;
      return (
        decoded.v === 1 &&
        decoded.type === "config_digest_rotation_preparation" &&
        decoded.clusterId === this.config.clusterId &&
        decoded.rotationId === preparation.rotationId &&
        decoded.expectedLeader === preparation.expectedLeader &&
        decoded.expectedEpoch === preparation.expectedEpoch &&
        decoded.expectedCurrentDigest ===
          preparation.expectedCurrentDigest &&
        decoded.candidateDigest === preparation.candidateDigest &&
        decoded.issuedAt === preparation.issuedAt &&
        decoded.expiresAt === preparation.expiresAt
      );
    } catch {
      return false;
    }
  }

  private configRotationRequestDigest(
    request: ConfigDigestRotationRequest,
    candidateHosts: string[],
  ): string {
    return sha256(
      JSON.stringify({
        clusterId: this.config.clusterId,
        rotationId: request.rotationId,
        expectedLeader: request.expectedLeader,
        expectedEpoch: request.expectedEpoch,
        expectedCurrentDigest: request.expectedCurrentDigest,
        candidateDigest: request.candidateDigest,
        candidateHosts,
      }),
    );
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
      authorityMode: this.config.standalonePrimaryHostId
        ? "standalone_primary"
        : "synchronous",
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
    const [state, candidates, rotationPreparations] = await Promise.all([
      this.store.getState(),
      this.store.listCandidates(),
      this.store.listConfigDigestRotationPreparations(),
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
            policyCandidateDigest: candidate.policyCandidateDigest ?? null,
            policyCandidateObservedAt:
              candidate.policyCandidateObservedAt ?? null,
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
    const standalonePrimary =
      state.authorityMode === "standalone_primary" &&
      this.config.standalonePrimaryHostId === state.currentLeader;
    const standaloneEligibility = standalonePrimary
      ? this.standaloneEligibility(leaderCandidate, state, nowEpoch)
      : null;
    if (standaloneEligibility && !standaloneEligibility.eligible) {
      throw new WitnessConflictError(
        `standalone-primary proof renewal rejected: ${standaloneEligibility.reasons.join(",")}`,
      );
    }
    const promotionAllowed =
      !standalonePrimary &&
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
      state.configDigest,
    );
    return {
      apiVersion: "execution-fabric-leadership/v1",
      clusterId: this.config.clusterId,
      ...state,
      promotionAllowed,
      leaderEligibility,
      standaloneEligibility,
      candidates: candidateMap,
      pendingConfigDigestRotations: rotationPreparations
        .sort((left, right) => left.rotationId.localeCompare(right.rotationId))
        .map((preparation) => ({
          ...preparation,
          expired: preparation.expiresAtEpoch < nowEpoch,
        })),
      safety: {
        maxReplicaLagBytes: this.config.maxReplicaLagBytes,
        candidateFreshnessSeconds: this.config.candidateFreshnessSeconds,
        leaderBaselineMaxAgeSeconds:
          this.config.leaderBaselineMaxAgeSeconds,
        automaticFailback: false,
        automaticPromotion: !standalonePrimary,
        standalonePrimary,
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
    const [state, candidates] = await Promise.all([
      this.store.getState(),
      this.store.listCandidates(),
    ]);
    const previous = candidates.find((item) => item.candidate === candidate);
    let policyCandidate:
      | Pick<
          CandidateRecord,
          "policyCandidateDigest" | "policyCandidateObservedAt"
        >
      | undefined;
    if (update.policyCandidateDigest !== undefined) {
      const policyCandidateObservedAt =
        update.policyCandidateObservedAt ?? observedAt;
      const policyCandidateObservedAtEpoch = Math.floor(
        new Date(policyCandidateObservedAt).getTime() / 1000,
      );
      if (
        Math.abs(policyCandidateObservedAtEpoch - nowEpoch) >
        this.config.maxReportSkewSeconds
      ) {
        throw new WitnessConflictError(
          "staged policy observation exceeds the allowed clock-skew window",
        );
      }
      policyCandidate = {
        policyCandidateDigest: update.policyCandidateDigest,
        policyCandidateObservedAt: new Date(
          policyCandidateObservedAt,
        ).toISOString(),
      };
    } else if (
      previous?.policyCandidateDigest &&
      previous.policyCandidateObservedAt &&
      Math.floor(
        new Date(previous.policyCandidateObservedAt).getTime() / 1000,
      ) >=
        nowEpoch - this.config.candidateFreshnessSeconds
    ) {
      policyCandidate = {
        policyCandidateDigest: previous.policyCandidateDigest,
        policyCandidateObservedAt: previous.policyCandidateObservedAt,
      };
    }
    const record: CandidateRecord = {
      candidate,
      ...update,
      ...policyCandidate,
      observedAt,
      observedAtEpoch,
    };
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
        policyCandidateDigest: record.policyCandidateDigest ?? null,
        policyCandidateObservedAt:
          record.policyCandidateObservedAt ?? null,
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

  async configDigestRotation(rotationId: string) {
    const receipt = await this.store.getConfigDigestRotation(rotationId);
    if (!receipt) {
      throw new WitnessNotFoundError(
        "configuration digest rotation receipt was not found",
      );
    }
    return receipt;
  }

  async configDigestRotationAbort(rotationId: string) {
    const receipt =
      await this.store.getConfigDigestRotationAbort(rotationId);
    if (!receipt) {
      throw new WitnessNotFoundError(
        "configuration digest rotation abort receipt was not found",
      );
    }
    return receipt;
  }

  async configDigestRotationPreparation(rotationId: string) {
    const preparation =
      await this.store.getConfigDigestRotationPreparation(rotationId);
    if (!preparation) {
      throw new WitnessNotFoundError(
        "configuration digest rotation preparation was not found",
      );
    }
    return preparation;
  }

  async prepareConfigDigestRotation(
    request: ConfigDigestRotationRequest,
  ): Promise<ConfigDigestRotationPreparation> {
    const candidateHosts = Object.keys(this.config.candidateTokens).sort();
    const standaloneRotation =
      this.config.standalonePrimaryHostId !== undefined &&
      candidateHosts.length === 1 &&
      candidateHosts[0] === this.config.standalonePrimaryHostId;
    if (candidateHosts.length < 2 && !standaloneRotation) {
      throw new WitnessConflictError(
        "configuration digest rotation requires at least two configured failover hosts",
      );
    }
    const requestDigest = this.configRotationRequestDigest(
      request,
      candidateHosts,
    );
    const [
      existingReceipt,
      existingAbort,
      existingPreparation,
      activePreparations,
    ] = await Promise.all([
      this.store.getConfigDigestRotation(request.rotationId),
      this.store.getConfigDigestRotationAbort(request.rotationId),
      this.store.getConfigDigestRotationPreparation(request.rotationId),
      this.store.listConfigDigestRotationPreparations(),
    ]);
    if (existingReceipt) {
      throw new WitnessConflictError(
        "configuration rotation id was already committed",
      );
    }
    if (existingAbort) {
      throw new WitnessConflictError(
        "configuration rotation id was already aborted",
      );
    }
    const nowEpoch = Math.floor(this.now().getTime() / 1000);
    if (existingPreparation) {
      if (safeEqual(existingPreparation.requestDigest, requestDigest)) {
        return existingPreparation;
      }
      throw new WitnessConflictError(
        "configuration rotation id was already used by another request",
      );
    }
    if (activePreparations.length > 0) {
      throw new WitnessConflictError(
        `another unresolved configuration rotation is active: ${activePreparations[0]!.rotationId}`,
      );
    }

    const [state, candidates] = await Promise.all([
      this.store.getState(),
      this.store.listCandidates(),
    ]);
    if (
      state.currentLeader !== request.expectedLeader ||
      state.fabricEpoch !== request.expectedEpoch ||
      state.configDigest !== request.expectedCurrentDigest
    ) {
      throw new WitnessConflictError(
        "configuration rotation expected leader, epoch, or digest is stale",
      );
    }
    if (
      standaloneRotation &&
      (state.authorityMode !== "standalone_primary" ||
        state.currentLeader !== this.config.standalonePrimaryHostId)
    ) {
      throw new WitnessConflictError(
        "standalone-primary configuration rotation requires exact current-host authority",
      );
    }
    if (
      state.leaderWalPosition === null ||
      state.leaderBaselineAt === null ||
      state.upstreamSystemId === null
    ) {
      throw new WitnessConflictError(
        "configuration rotation requires a complete leader WAL baseline",
      );
    }

    const candidateFreshAfterEpoch =
      nowEpoch - this.config.candidateFreshnessSeconds;
    const leaderBaselineFreshAfterEpoch =
      nowEpoch - this.config.leaderBaselineMaxAgeSeconds;
    const baselineEpoch = Math.floor(
      new Date(state.leaderBaselineAt).getTime() / 1000,
    );
    if (
      !Number.isFinite(baselineEpoch) ||
      baselineEpoch < leaderBaselineFreshAfterEpoch
    ) {
      throw new WitnessConflictError(
        "configuration rotation leader WAL baseline is stale",
      );
    }

    const candidateMap = new Map(
      candidates.map((candidate) => [candidate.candidate, candidate]),
    );
    const conditions: ConfigDigestCandidateCondition[] = [];
    const reasons: string[] = [];
    for (const host of candidateHosts) {
      const candidate = candidateMap.get(host);
      const isLeader = host === state.currentLeader;
      const expectedInRecovery = !isLeader;
      const expectedReceiverState = isLeader
        ? "not_applicable"
        : "streaming";
      const minimumReplayWalPosition = isLeader
        ? state.leaderWalPosition
        : Math.max(
            0,
            state.leaderWalPosition - this.config.maxReplicaLagBytes,
          );
      conditions.push({
        candidate: host,
        inRecovery: expectedInRecovery,
        receiverState: expectedReceiverState,
        minimumReplayWalPosition,
      });
      if (!candidate) {
        reasons.push(`${host}:candidate_not_reported`);
        continue;
      }
      if (!candidate.healthy) reasons.push(`${host}:candidate_unhealthy`);
      if (candidate.inRecovery !== expectedInRecovery) {
        reasons.push(`${host}:recovery_role_mismatch`);
      }
      if (candidate.receiverState !== expectedReceiverState) {
        reasons.push(`${host}:receiver_state_mismatch`);
      }
      if (candidate.observedAtEpoch < candidateFreshAfterEpoch) {
        reasons.push(`${host}:candidate_observation_stale`);
      }
      if (
        Math.floor(new Date(candidate.lagMeasuredAt).getTime() / 1000) <
        candidateFreshAfterEpoch
      ) {
        reasons.push(`${host}:lag_measurement_stale`);
      }
      if (
        Math.floor(new Date(candidate.lastMessageAt).getTime() / 1000) <
        candidateFreshAfterEpoch
      ) {
        reasons.push(`${host}:receiver_message_stale`);
      }
      if (candidate.configDigest !== state.configDigest) {
        reasons.push(`${host}:applied_config_digest_mismatch`);
      }
      if (candidate.policyCandidateDigest !== request.candidateDigest) {
        reasons.push(`${host}:policy_candidate_digest_mismatch`);
      }
      if (
        Math.floor(
          new Date(candidate.policyCandidateObservedAt ?? "").getTime() /
            1000,
        ) < candidateFreshAfterEpoch
      ) {
        reasons.push(`${host}:policy_candidate_observation_stale`);
      }
      if (candidate.timelineId !== state.timelineId) {
        reasons.push(`${host}:timeline_mismatch`);
      }
      if (candidate.upstreamSystemId !== state.upstreamSystemId) {
        reasons.push(`${host}:upstream_system_id_mismatch`);
      }
      if (candidate.replayWalPosition < minimumReplayWalPosition) {
        reasons.push(`${host}:upstream_wal_gap_exceeds_limit`);
      }
      if (
        expectedInRecovery &&
        candidate.replicaLagBytes > this.config.maxReplicaLagBytes
      ) {
        reasons.push(`${host}:replica_lag_exceeds_limit`);
      }
    }
    if (reasons.length) {
      throw new WitnessConflictError(
        `configuration rotation candidates are not eligible: ${reasons.join(",")}`,
      );
    }

    const issuedAt = this.timestamp();
    const expiresAtEpoch = nowEpoch + this.config.planTtlSeconds;
    const expiresAt = new Date(expiresAtEpoch * 1000).toISOString();
    const preparationToken = this.configRotationPreparationToken(
      request,
      issuedAt,
      expiresAt,
    );
    const preparation: ConfigDigestRotationPreparation = {
      apiVersion: "execution-fabric-leadership/v1",
      decision: "config_digest_rotation_prepared",
      rotationId: request.rotationId,
      requestDigest,
      expectedLeader: state.currentLeader,
      expectedEpoch: state.fabricEpoch,
      expectedCurrentDigest: state.configDigest,
      candidateDigest: request.candidateDigest,
      candidateHosts,
      expectedTimelineId: state.timelineId,
      expectedLeaderWalPosition: state.leaderWalPosition,
      expectedUpstreamSystemId: state.upstreamSystemId,
      minimumStandbyReplayWalPosition: Math.max(
        0,
        state.leaderWalPosition - this.config.maxReplicaLagBytes,
      ),
      maxReplicaLagBytes: this.config.maxReplicaLagBytes,
      preparationToken,
      preparationTokenHash: sha256(preparationToken),
      issuedAt,
      expiresAt,
      expiresAtEpoch,
    };
    try {
      return await this.store.prepareConfigDigestRotation({
        preparation,
        expectedLeader: request.expectedLeader,
        expectedEpoch: request.expectedEpoch,
        expectedCurrentDigest: request.expectedCurrentDigest,
        candidateDigest: request.candidateDigest,
        expectedTimelineId: state.timelineId,
        expectedLeaderWalPosition: state.leaderWalPosition,
        expectedUpstreamSystemId: state.upstreamSystemId,
        leaderBaselineFreshAfterEpoch,
        candidateFreshAfterEpoch,
        policyCandidateFreshAfterEpoch: candidateFreshAfterEpoch,
        receiverFreshAfterEpoch: candidateFreshAfterEpoch,
        maxReplicaLagBytes: this.config.maxReplicaLagBytes,
        candidates: conditions,
        audit: {
          auditId: `${request.rotationId}:prepare`,
          eventType: "config_digest_rotation_prepared",
          actor: "authenticated_admin",
          occurredAt: issuedAt,
          requestDigest,
          detail: {
            expectedLeader: state.currentLeader,
            expectedEpoch: state.fabricEpoch,
            expectedCurrentDigest: state.configDigest,
            candidateDigest: request.candidateDigest,
            candidateHosts,
            preparationTokenHash: preparation.preparationTokenHash,
            expiresAt,
          },
        },
      });
    } catch (error) {
      if (!(error instanceof ConditionalWriteError)) throw error;
      const replay =
        await this.store.getConfigDigestRotationPreparation(
          request.rotationId,
        );
      if (
        replay &&
        safeEqual(replay.requestDigest, requestDigest)
      ) {
        return replay;
      }
      const active =
        await this.store.listConfigDigestRotationPreparations();
      throw new WitnessConflictError(
        replay
          ? "configuration rotation id was already used by another request"
          : active.length > 0
            ? `another unresolved configuration rotation is active: ${active[0]!.rotationId}`
            : "configuration digest rotation conditions changed before preparation",
      );
    }
  }

  async commitConfigDigestRotation(
    request: ConfigDigestRotationCommitRequest,
  ): Promise<ConfigDigestRotationReceipt> {
    const preparationTokenHash = sha256(request.preparationToken);
    const [existing, existingAbort] = await Promise.all([
      this.store.getConfigDigestRotation(request.rotationId),
      this.store.getConfigDigestRotationAbort(request.rotationId),
    ]);
    if (existing) {
      if (
        safeEqual(existing.preparationTokenHash, preparationTokenHash)
      ) {
        return existing;
      }
      throw new WitnessConflictError(
        "configuration rotation id was already committed with another preparation",
      );
    }
    if (existingAbort) {
      throw new WitnessConflictError(
        "configuration rotation was already aborted",
      );
    }
    const preparation =
      await this.store.getConfigDigestRotationPreparation(request.rotationId);
    if (!preparation) {
      throw new WitnessNotFoundError(
        "configuration digest rotation preparation is missing or already consumed",
      );
    }
    if (
      !safeEqual(preparation.preparationTokenHash, preparationTokenHash) ||
      !this.validConfigRotationPreparationToken(
        request.preparationToken,
        preparation,
      )
    ) {
      throw new WitnessConflictError(
        "configuration digest rotation preparation token is invalid or mismatched",
      );
    }
    const nowEpoch = Math.floor(this.now().getTime() / 1000);
    const [state, candidates] = await Promise.all([
      this.store.getState(),
      this.store.listCandidates(),
    ]);
    if (
      state.currentLeader !== preparation.expectedLeader ||
      state.fabricEpoch !== preparation.expectedEpoch ||
      state.configDigest !== preparation.expectedCurrentDigest
    ) {
      throw new WitnessConflictError(
        "configuration digest rotation preparation is stale for current leadership",
      );
    }
    const candidateFreshAfterEpoch =
      nowEpoch - this.config.candidateFreshnessSeconds;
    const standaloneRotation =
      state.authorityMode === "standalone_primary" &&
      this.config.standalonePrimaryHostId === state.currentLeader &&
      preparation.candidateHosts.length === 1 &&
      preparation.candidateHosts[0] === state.currentLeader;
    const commitCandidate = candidates
      .filter(
        (candidate) =>
          preparation.candidateHosts.includes(candidate.candidate) &&
          (standaloneRotation
            ? candidate.candidate === preparation.expectedLeader
            : candidate.candidate !== preparation.expectedLeader) &&
          candidate.healthy &&
          candidate.inRecovery === !standaloneRotation &&
          candidate.receiverState ===
            (standaloneRotation ? "not_applicable" : "streaming") &&
          candidate.observedAtEpoch >= candidateFreshAfterEpoch &&
          Math.floor(
            new Date(candidate.lagMeasuredAt).getTime() / 1000,
          ) >= candidateFreshAfterEpoch &&
          Math.floor(
            new Date(candidate.lastMessageAt).getTime() / 1000,
          ) >= candidateFreshAfterEpoch &&
          candidate.configDigest === preparation.candidateDigest &&
          candidate.timelineId === preparation.expectedTimelineId &&
          candidate.upstreamSystemId ===
            preparation.expectedUpstreamSystemId &&
          candidate.replayWalPosition >=
            preparation.minimumStandbyReplayWalPosition &&
          (standaloneRotation ||
            candidate.replicaLagBytes <= preparation.maxReplicaLagBytes),
      )
      .sort((left, right) =>
        left.candidate.localeCompare(right.candidate),
      )[0];
    if (!commitCandidate) {
      throw new WitnessConflictError(
        standaloneRotation
          ? "standalone-primary configuration rotation commit requires fresh healthy local evidence that the database applied the candidate digest"
          : "configuration digest rotation commit requires fresh healthy non-leader evidence that the database applied the candidate digest",
      );
    }
    const committedAt = this.timestamp();
    const receipt: ConfigDigestRotationReceipt = {
      apiVersion: "execution-fabric-leadership/v1",
      decision: "config_digest_rotated",
      rotationId: preparation.rotationId,
      requestDigest: preparation.requestDigest,
      currentLeader: state.currentLeader,
      fabricEpoch: state.fabricEpoch,
      previousConfigDigest: state.configDigest,
      configDigest: preparation.candidateDigest,
      candidateHosts: preparation.candidateHosts,
      preparationTokenHash,
      committedAt,
    };
    try {
      return await this.store.commitConfigDigestRotation({
        preparation,
        preparationTokenHash,
        candidateFreshAfterEpoch,
        receiverFreshAfterEpoch: candidateFreshAfterEpoch,
        commitCandidate: {
          candidate: commitCandidate.candidate,
          inRecovery: !standaloneRotation,
          receiverState: standaloneRotation ? "not_applicable" : "streaming",
          minimumReplayWalPosition:
            preparation.minimumStandbyReplayWalPosition,
        },
        nextState: {
          ...state,
          configDigest: preparation.candidateDigest,
          updatedAt: committedAt,
        },
        receipt,
        audit: {
          auditId: `${request.rotationId}:commit`,
          eventType: "config_digest_rotated",
          actor: "authenticated_admin",
          occurredAt: committedAt,
          requestDigest: preparation.requestDigest,
          detail: {
            currentLeader: state.currentLeader,
            fabricEpoch: state.fabricEpoch,
            previousConfigDigest: state.configDigest,
            configDigest: preparation.candidateDigest,
            candidateHosts: preparation.candidateHosts,
            preparationTokenHash,
            appliedEvidenceHost: commitCandidate.candidate,
            preparationExpiredAtCommit:
              preparation.expiresAtEpoch < nowEpoch,
          },
        },
      });
    } catch (error) {
      if (!(error instanceof ConditionalWriteError)) throw error;
      const replay = await this.store.getConfigDigestRotation(
        request.rotationId,
      );
      if (
        replay &&
        safeEqual(replay.preparationTokenHash, preparationTokenHash)
      ) {
        return replay;
      }
      throw new WitnessConflictError(
        replay
          ? "configuration rotation id was already committed with another preparation"
          : "configuration digest rotation preparation changed before commit",
      );
    }
  }

  async abortConfigDigestRotation(
    request: ConfigDigestRotationAbortRequest,
  ): Promise<ConfigDigestRotationAbortReceipt> {
    const preparationTokenHash = sha256(request.preparationToken);
    const [existingAbort, existingCommit] = await Promise.all([
      this.store.getConfigDigestRotationAbort(request.rotationId),
      this.store.getConfigDigestRotation(request.rotationId),
    ]);
    if (existingAbort) {
      if (
        safeEqual(
          existingAbort.preparationTokenHash,
          preparationTokenHash,
        )
      ) {
        return existingAbort;
      }
      throw new WitnessConflictError(
        "configuration rotation id was already aborted with another preparation",
      );
    }
    if (existingCommit) {
      throw new WitnessConflictError(
        "configuration rotation was already committed",
      );
    }
    const preparation =
      await this.store.getConfigDigestRotationPreparation(request.rotationId);
    if (!preparation) {
      throw new WitnessNotFoundError(
        "configuration digest rotation preparation is missing or already resolved",
      );
    }
    if (
      !safeEqual(preparation.preparationTokenHash, preparationTokenHash) ||
      !this.validConfigRotationPreparationToken(
        request.preparationToken,
        preparation,
      )
    ) {
      throw new WitnessConflictError(
        "configuration digest rotation preparation token is invalid or mismatched",
      );
    }
    const nowEpoch = Math.floor(this.now().getTime() / 1000);
    if (preparation.expiresAtEpoch >= nowEpoch) {
      throw new WitnessConflictError(
        "configuration digest rotation preparation cannot be aborted before expiry",
      );
    }
    const [state, candidates] = await Promise.all([
      this.store.getState(),
      this.store.listCandidates(),
    ]);
    if (
      state.currentLeader !== preparation.expectedLeader ||
      state.fabricEpoch !== preparation.expectedEpoch ||
      state.configDigest !== preparation.expectedCurrentDigest
    ) {
      throw new WitnessConflictError(
        "configuration digest rotation preparation is stale for current leadership",
      );
    }
    const evidenceAfterEpoch = Math.max(
      preparation.expiresAtEpoch,
      nowEpoch - this.config.candidateFreshnessSeconds,
    );
    const standaloneRotation =
      state.authorityMode === "standalone_primary" &&
      this.config.standalonePrimaryHostId === state.currentLeader &&
      preparation.candidateHosts.length === 1 &&
      preparation.candidateHosts[0] === state.currentLeader;
    const safeEvidenceCandidates = candidates
      .filter(
        (candidate) =>
          preparation.candidateHosts.includes(candidate.candidate) &&
          (standaloneRotation
            ? candidate.candidate === preparation.expectedLeader
            : candidate.candidate !== preparation.expectedLeader) &&
          candidate.healthy &&
          candidate.inRecovery === !standaloneRotation &&
          candidate.receiverState ===
            (standaloneRotation ? "not_applicable" : "streaming") &&
          candidate.observedAtEpoch > evidenceAfterEpoch &&
          Math.floor(
            new Date(candidate.lagMeasuredAt).getTime() / 1000,
          ) > evidenceAfterEpoch &&
          Math.floor(
            new Date(candidate.lastMessageAt).getTime() / 1000,
          ) > evidenceAfterEpoch &&
          candidate.timelineId === preparation.expectedTimelineId &&
          candidate.upstreamSystemId ===
            preparation.expectedUpstreamSystemId &&
          candidate.replayWalPosition >=
            preparation.minimumStandbyReplayWalPosition &&
          (standaloneRotation ||
            candidate.replicaLagBytes <= preparation.maxReplicaLagBytes),
      )
      .sort((left, right) =>
        left.candidate.localeCompare(right.candidate),
      );
    if (
      safeEvidenceCandidates.some(
        (candidate) =>
          candidate.configDigest === preparation.candidateDigest,
      )
    ) {
      throw new WitnessConflictError(
        standaloneRotation
          ? "configuration digest rotation cannot be aborted because the local database applied the candidate digest"
          : "configuration digest rotation cannot be aborted because a standby applied the candidate digest",
      );
    }
    const evidenceCandidate = safeEvidenceCandidates.find(
      (candidate) =>
        candidate.configDigest === preparation.expectedCurrentDigest,
    );
    if (!evidenceCandidate) {
      throw new WitnessConflictError(
        standaloneRotation
          ? "standalone-primary configuration rotation abort requires fresh healthy local evidence that the database remains on the current digest"
          : "configuration digest rotation abort requires fresh healthy non-leader evidence that the database remains on the current digest",
      );
    }
    const abortedAt = this.timestamp();
    const receipt: ConfigDigestRotationAbortReceipt = {
      apiVersion: "execution-fabric-leadership/v1",
      decision: "config_digest_rotation_aborted",
      rotationId: preparation.rotationId,
      requestDigest: preparation.requestDigest,
      currentLeader: state.currentLeader,
      fabricEpoch: state.fabricEpoch,
      configDigest: state.configDigest,
      candidateDigest: preparation.candidateDigest,
      evidenceHost: evidenceCandidate.candidate,
      preparationTokenHash,
      expiredAt: preparation.expiresAt,
      abortedAt,
    };
    try {
      return await this.store.abortConfigDigestRotation({
        preparation,
        preparationTokenHash,
        nowEpoch,
        evidenceAfterEpoch,
        evidenceCandidate: {
          candidate: evidenceCandidate.candidate,
          inRecovery: !standaloneRotation,
          receiverState: standaloneRotation ? "not_applicable" : "streaming",
          minimumReplayWalPosition:
            preparation.minimumStandbyReplayWalPosition,
        },
        candidateDigestGuardHosts: preparation.candidateHosts.filter(
          (host) =>
            host !== preparation.expectedLeader &&
            host !== evidenceCandidate.candidate,
        ),
        receipt,
        audit: {
          auditId: `${request.rotationId}:abort`,
          eventType: "config_digest_rotation_aborted",
          actor: "authenticated_admin",
          occurredAt: abortedAt,
          requestDigest: preparation.requestDigest,
          detail: {
            currentLeader: state.currentLeader,
            fabricEpoch: state.fabricEpoch,
            configDigest: state.configDigest,
            candidateDigest: preparation.candidateDigest,
            evidenceHost: evidenceCandidate.candidate,
            preparationTokenHash,
            expiredAt: preparation.expiresAt,
          },
        },
      });
    } catch (error) {
      if (!(error instanceof ConditionalWriteError)) throw error;
      const replay = await this.store.getConfigDigestRotationAbort(
        request.rotationId,
      );
      if (
        replay &&
        safeEqual(replay.preparationTokenHash, preparationTokenHash)
      ) {
        return replay;
      }
      throw new WitnessConflictError(
        replay
          ? "configuration rotation id was already aborted with another preparation"
          : "configuration digest rotation preparation changed before abort",
      );
    }
  }

  async promote(request: PromotionRequest) {
    const requestDigest = sha256(JSON.stringify(request));
    const replay = await this.store.getPromotion(request.promotionId);
    if (replay) {
      if (replay.requestDigest !== requestDigest) {
        throw new WitnessConflictError(
          "promotion id was already used by another request",
        );
      }
      return replay;
    }
    const authorityMode = request.authorityMode ?? "synchronous";
    const [state, candidates] = await Promise.all([
      this.store.getState(),
      this.store.listCandidates(),
    ]);
    if (
      this.config.standalonePrimaryHostId ||
      state.authorityMode === "standalone_primary"
    ) {
      throw new WitnessConflictError(
        "promotion is disabled for standalone-primary authority",
      );
    }
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
      state.configDigest,
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
    const receipt = {
      apiVersion: "execution-fabric-leadership/v1" as const,
      decision: "promoted" as const,
      promotionId: request.promotionId,
      requestDigest,
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
    try {
      return await this.store.promote({
        promotionId: request.promotionId,
        requestDigest,
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
        receipt,
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
  }

  async promotion(promotionId: string) {
    const receipt = await this.store.getPromotion(promotionId);
    if (!receipt) {
      throw new WitnessNotFoundError("promotion receipt was not found");
    }
    return receipt;
  }

  async planFailback(request: FailbackPlanRequest) {
    if (this.config.standalonePrimaryHostId) {
      throw new WitnessConflictError(
        "failback is disabled for standalone-primary authority",
      );
    }
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
    if (this.config.standalonePrimaryHostId) {
      throw new WitnessConflictError(
        "failback is disabled for standalone-primary authority",
      );
    }
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
    if (this.config.standalonePrimaryHostId) {
      throw new WitnessConflictError(
        "failback is disabled for standalone-primary authority",
      );
    }
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
      plan.configDigest,
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
