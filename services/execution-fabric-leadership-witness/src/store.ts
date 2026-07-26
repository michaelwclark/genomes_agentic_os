import type {
  AuditRecord,
  CandidateRecord,
  ConfigDigestRotationAbortMutation,
  ConfigDigestRotationAbortReceipt,
  ConfigDigestRotationCommitMutation,
  ConfigDigestRotationPreparation,
  ConfigDigestRotationPreparationMutation,
  ConfigDigestRotationReceipt,
  FailbackCommitMutation,
  FailbackPlan,
  LeadershipState,
  LeadershipCasMutation,
  PromotionReceipt,
  PromotionMutation,
} from "./contracts.js";

export class ConditionalWriteError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConditionalWriteError";
  }
}

export type LeaderBaselineUpdate = {
  expectedLeader: string;
  expectedTimelineId: number;
  expectedConfigDigest: string;
};

export interface WitnessStore {
  initialize(state: LeadershipState, audit: AuditRecord): Promise<LeadershipState>;
  ready(): Promise<void>;
  getState(): Promise<LeadershipState>;
  listCandidates(): Promise<CandidateRecord[]>;
  putCandidate(
    candidate: CandidateRecord,
    audit: AuditRecord,
    leaderBaseline?: LeaderBaselineUpdate,
  ): Promise<void>;
  getConfigDigestRotation(
    rotationId: string,
  ): Promise<ConfigDigestRotationReceipt | null>;
  getConfigDigestRotationAbort(
    rotationId: string,
  ): Promise<ConfigDigestRotationAbortReceipt | null>;
  getConfigDigestRotationPreparation(
    rotationId: string,
  ): Promise<ConfigDigestRotationPreparation | null>;
  listConfigDigestRotationPreparations(): Promise<
    ConfigDigestRotationPreparation[]
  >;
  prepareConfigDigestRotation(
    mutation: ConfigDigestRotationPreparationMutation,
  ): Promise<ConfigDigestRotationPreparation>;
  commitConfigDigestRotation(
    mutation: ConfigDigestRotationCommitMutation,
  ): Promise<ConfigDigestRotationReceipt>;
  abortConfigDigestRotation(
    mutation: ConfigDigestRotationAbortMutation,
  ): Promise<ConfigDigestRotationAbortReceipt>;
  getPromotion(promotionId: string): Promise<PromotionReceipt | null>;
  promote(mutation: PromotionMutation): Promise<PromotionReceipt>;
  putFailbackPreparation(plan: FailbackPlan, audit: AuditRecord): Promise<void>;
  putFailbackPlan(plan: FailbackPlan, audit: AuditRecord): Promise<void>;
  getFailbackPlan(tokenHash: string): Promise<FailbackPlan | null>;
  commitFailback(mutation: FailbackCommitMutation): Promise<LeadershipState>;
  appendAudit(audit: AuditRecord): Promise<void>;
  listAudit(limit: number): Promise<AuditRecord[]>;
  close(): Promise<void>;
}

export type WitnessStoreSnapshot = {
  schemaVersion: "execution-fabric-witness-store/v2";
  state?: LeadershipState;
  promotions: PromotionReceipt[];
  candidates: CandidateRecord[];
  plans: FailbackPlan[];
  configRotations: ConfigDigestRotationReceipt[];
  configRotationAborts: ConfigDigestRotationAbortReceipt[];
  configRotationPreparations: ConfigDigestRotationPreparation[];
  audit: AuditRecord[];
};

function rotationCandidateEligible(
  candidate: CandidateRecord | undefined,
  expected: ConfigDigestRotationPreparationMutation["candidates"][number],
  mutation: ConfigDigestRotationPreparationMutation,
): boolean {
  return Boolean(
    candidate?.candidate === expected.candidate &&
      candidate.healthy &&
      candidate.inRecovery === expected.inRecovery &&
      candidate.receiverState === expected.receiverState &&
      candidate.observedAtEpoch >= mutation.candidateFreshAfterEpoch &&
      Math.floor(new Date(candidate.lagMeasuredAt).getTime() / 1000) >=
        mutation.candidateFreshAfterEpoch &&
      Math.floor(new Date(candidate.lastMessageAt).getTime() / 1000) >=
        mutation.receiverFreshAfterEpoch &&
      candidate.configDigest === mutation.expectedCurrentDigest &&
      candidate.policyCandidateDigest === mutation.candidateDigest &&
      Math.floor(
        new Date(candidate.policyCandidateObservedAt ?? "").getTime() / 1000,
      ) >= mutation.policyCandidateFreshAfterEpoch &&
      candidate.timelineId === mutation.expectedTimelineId &&
      candidate.upstreamSystemId === mutation.expectedUpstreamSystemId &&
      candidate.replayWalPosition >= expected.minimumReplayWalPosition &&
      (!expected.inRecovery ||
        candidate.replicaLagBytes <= mutation.maxReplicaLagBytes),
  );
}

function rotationCommitCandidateEligible(
  candidate: CandidateRecord | undefined,
  mutation: ConfigDigestRotationCommitMutation,
  state: LeadershipState,
): boolean {
  const expected = mutation.commitCandidate;
  const preparation = mutation.preparation;
  const standalonePrimary =
    state.authorityMode === "standalone_primary" &&
    preparation.candidateHosts.length === 1 &&
    preparation.candidateHosts[0] === preparation.expectedLeader;
  return Boolean(
    (standalonePrimary
      ? expected.candidate === preparation.expectedLeader &&
        expected.inRecovery === false &&
        expected.receiverState === "not_applicable"
      : expected.candidate !== preparation.expectedLeader &&
        expected.inRecovery === true &&
        expected.receiverState === "streaming") &&
      preparation.candidateHosts.includes(expected.candidate) &&
      candidate?.candidate === expected.candidate &&
      candidate.healthy &&
      candidate.inRecovery === expected.inRecovery &&
      candidate.receiverState === expected.receiverState &&
      candidate.observedAtEpoch >= mutation.candidateFreshAfterEpoch &&
      Math.floor(new Date(candidate.lagMeasuredAt).getTime() / 1000) >=
        mutation.candidateFreshAfterEpoch &&
      Math.floor(new Date(candidate.lastMessageAt).getTime() / 1000) >=
        mutation.receiverFreshAfterEpoch &&
      candidate.configDigest === preparation.candidateDigest &&
      candidate.timelineId === preparation.expectedTimelineId &&
      candidate.upstreamSystemId === preparation.expectedUpstreamSystemId &&
      candidate.replayWalPosition >= expected.minimumReplayWalPosition &&
      (!expected.inRecovery ||
        candidate.replicaLagBytes <= preparation.maxReplicaLagBytes),
  );
}

function rotationAbortCandidateEligible(
  candidate: CandidateRecord | undefined,
  mutation: ConfigDigestRotationAbortMutation,
  state: LeadershipState,
): boolean {
  const expected = mutation.evidenceCandidate;
  const preparation = mutation.preparation;
  const standalonePrimary =
    state.authorityMode === "standalone_primary" &&
    preparation.candidateHosts.length === 1 &&
    preparation.candidateHosts[0] === preparation.expectedLeader;
  return Boolean(
    (standalonePrimary
      ? expected.candidate === preparation.expectedLeader &&
        expected.inRecovery === false &&
        expected.receiverState === "not_applicable"
      : expected.candidate !== preparation.expectedLeader &&
        expected.inRecovery === true &&
        expected.receiverState === "streaming") &&
      preparation.candidateHosts.includes(expected.candidate) &&
      candidate?.candidate === expected.candidate &&
      candidate.healthy &&
      candidate.inRecovery === expected.inRecovery &&
      candidate.receiverState === expected.receiverState &&
      candidate.observedAtEpoch > mutation.evidenceAfterEpoch &&
      Math.floor(new Date(candidate.lagMeasuredAt).getTime() / 1000) >
        mutation.evidenceAfterEpoch &&
      Math.floor(new Date(candidate.lastMessageAt).getTime() / 1000) >
        mutation.evidenceAfterEpoch &&
      candidate.configDigest === preparation.expectedCurrentDigest &&
      candidate.timelineId === preparation.expectedTimelineId &&
      candidate.upstreamSystemId === preparation.expectedUpstreamSystemId &&
      candidate.replayWalPosition >= expected.minimumReplayWalPosition &&
      (!expected.inRecovery ||
        candidate.replicaLagBytes <= preparation.maxReplicaLagBytes),
  );
}

function eligible(
  candidate: CandidateRecord | undefined,
  mutation: LeadershipCasMutation,
): boolean {
  return Boolean(
    candidate?.healthy &&
      candidate.inRecovery &&
      candidate.observedAtEpoch >= mutation.freshAfterEpoch &&
      candidate.replicaLagBytes <= mutation.maxReplicaLagBytes &&
      candidate.receiverState === "streaming" &&
      Math.floor(new Date(candidate.lastMessageAt).getTime() / 1000) >=
        mutation.receiverFreshAfterEpoch &&
      candidate.upstreamSystemId === mutation.expectedUpstreamSystemId &&
      candidate.replayWalPosition >= mutation.minimumReplayWalPosition &&
      candidate.configDigest === mutation.configDigest &&
      candidate.timelineId === mutation.expectedTimelineId &&
      Math.floor(new Date(candidate.lagMeasuredAt).getTime() / 1000) >=
        mutation.freshAfterEpoch,
  );
}

export class InMemoryWitnessStore implements WitnessStore {
  protected state: LeadershipState | undefined;
  protected readonly candidates = new Map<string, CandidateRecord>();
  protected readonly promotions = new Map<string, PromotionReceipt>();
  protected readonly plans = new Map<string, FailbackPlan>();
  protected readonly configRotations = new Map<
    string,
    ConfigDigestRotationReceipt
  >();
  protected readonly configRotationAborts = new Map<
    string,
    ConfigDigestRotationAbortReceipt
  >();
  protected readonly configRotationPreparations = new Map<
    string,
    ConfigDigestRotationPreparation
  >();
  protected readonly audit: AuditRecord[] = [];

  protected didMutate(): void {}

  async close(): Promise<void> {}

  protected exportSnapshot(): WitnessStoreSnapshot {
    return structuredClone({
      schemaVersion: "execution-fabric-witness-store/v2",
      ...(this.state ? { state: this.state } : {}),
      promotions: [...this.promotions.values()],
      candidates: [...this.candidates.values()],
      plans: [...this.plans.values()],
      configRotations: [...this.configRotations.values()],
      configRotationAborts: [...this.configRotationAborts.values()],
      configRotationPreparations: [
        ...this.configRotationPreparations.values(),
      ],
      audit: this.audit,
    });
  }

  protected restoreSnapshot(snapshot: WitnessStoreSnapshot): void {
    if (snapshot.schemaVersion !== "execution-fabric-witness-store/v2") {
      throw new Error("unsupported portable witness store schema");
    }
    this.state = snapshot.state ? structuredClone(snapshot.state) : undefined;
    this.promotions.clear();
    for (const item of snapshot.promotions) {
      this.promotions.set(item.promotionId, structuredClone(item));
    }
    this.candidates.clear();
    for (const item of snapshot.candidates) {
      this.candidates.set(item.candidate, structuredClone(item));
    }
    this.plans.clear();
    for (const item of snapshot.plans) {
      this.plans.set(item.tokenHash, structuredClone(item));
    }
    this.configRotations.clear();
    for (const item of snapshot.configRotations) {
      this.configRotations.set(item.rotationId, structuredClone(item));
    }
    this.configRotationAborts.clear();
    for (const item of snapshot.configRotationAborts) {
      this.configRotationAborts.set(item.rotationId, structuredClone(item));
    }
    this.configRotationPreparations.clear();
    for (const item of snapshot.configRotationPreparations) {
      this.configRotationPreparations.set(
        item.rotationId,
        structuredClone(item),
      );
    }
    this.audit.splice(0, this.audit.length, ...structuredClone(snapshot.audit));
  }

  private requireState(): LeadershipState {
    if (!this.state) throw new Error("leadership state is not initialized");
    return this.state;
  }

  async initialize(
    state: LeadershipState,
    audit: AuditRecord,
  ): Promise<LeadershipState> {
    if (!this.state) {
      this.state = structuredClone(state);
      this.audit.push(structuredClone(audit));
      this.didMutate();
    }
    return structuredClone(this.state);
  }

  async ready(): Promise<void> {
    if (!this.state) throw new Error("leadership state is not initialized");
  }

  async getState(): Promise<LeadershipState> {
    if (!this.state) throw new Error("leadership state is not initialized");
    return structuredClone(this.state);
  }

  async listCandidates(): Promise<CandidateRecord[]> {
    return [...this.candidates.values()].map((item) => structuredClone(item));
  }

  async putCandidate(
    candidate: CandidateRecord,
    audit: AuditRecord,
    leaderBaseline?: LeaderBaselineUpdate,
  ): Promise<void> {
    if (leaderBaseline) {
      const state = this.requireState();
      if (
        state.currentLeader !== leaderBaseline.expectedLeader ||
        state.timelineId !== leaderBaseline.expectedTimelineId ||
        state.configDigest !== leaderBaseline.expectedConfigDigest ||
        candidate.candidate !== state.currentLeader ||
        candidate.inRecovery ||
        candidate.timelineId !== state.timelineId ||
        candidate.configDigest !== state.configDigest ||
        (state.upstreamSystemId !== null &&
          state.upstreamSystemId !== candidate.upstreamSystemId) ||
        (state.leaderWalPosition !== null &&
          candidate.replayWalPosition < state.leaderWalPosition)
      ) {
        throw new ConditionalWriteError(
          "leader WAL baseline conditions were not satisfied",
        );
      }
      this.state = {
        ...state,
        leaderWalPosition: candidate.replayWalPosition,
        leaderBaselineAt: candidate.lagMeasuredAt,
        upstreamSystemId: candidate.upstreamSystemId,
      };
    }
    this.candidates.set(candidate.candidate, structuredClone(candidate));
    this.audit.push(structuredClone(audit));
    this.didMutate();
  }

  async getConfigDigestRotation(
    rotationId: string,
  ): Promise<ConfigDigestRotationReceipt | null> {
    const receipt = this.configRotations.get(rotationId);
    return receipt ? structuredClone(receipt) : null;
  }

  async getConfigDigestRotationAbort(
    rotationId: string,
  ): Promise<ConfigDigestRotationAbortReceipt | null> {
    const receipt = this.configRotationAborts.get(rotationId);
    return receipt ? structuredClone(receipt) : null;
  }

  async getConfigDigestRotationPreparation(
    rotationId: string,
  ): Promise<ConfigDigestRotationPreparation | null> {
    const preparation = this.configRotationPreparations.get(rotationId);
    return preparation ? structuredClone(preparation) : null;
  }

  async listConfigDigestRotationPreparations(): Promise<
    ConfigDigestRotationPreparation[]
  > {
    return [...this.configRotationPreparations.values()].map((preparation) =>
      structuredClone(preparation),
    );
  }

  async prepareConfigDigestRotation(
    mutation: ConfigDigestRotationPreparationMutation,
  ): Promise<ConfigDigestRotationPreparation> {
    if (
      this.configRotations.has(mutation.preparation.rotationId) ||
      this.configRotationAborts.has(mutation.preparation.rotationId) ||
      this.configRotationPreparations.size > 0
    ) {
      throw new ConditionalWriteError("configuration rotation id already exists");
    }
    const state = this.requireState();
    const baselineEpoch = Math.floor(
      new Date(state.leaderBaselineAt ?? "").getTime() / 1000,
    );
    if (
      state.currentLeader !== mutation.expectedLeader ||
      state.fabricEpoch !== mutation.expectedEpoch ||
      state.configDigest !== mutation.expectedCurrentDigest ||
      state.timelineId !== mutation.expectedTimelineId ||
      state.leaderWalPosition !== mutation.expectedLeaderWalPosition ||
      state.upstreamSystemId !== mutation.expectedUpstreamSystemId ||
      !Number.isFinite(baselineEpoch) ||
      baselineEpoch < mutation.leaderBaselineFreshAfterEpoch
    ) {
      throw new ConditionalWriteError(
        "configuration rotation leadership baseline changed",
      );
    }
    if (
      (mutation.candidates.length < 2 &&
        !(
          state.authorityMode === "standalone_primary" &&
          mutation.candidates.length === 1 &&
          mutation.candidates[0]?.candidate === state.currentLeader &&
          mutation.candidates[0]?.inRecovery === false &&
          mutation.candidates[0]?.receiverState === "not_applicable"
        )) ||
      !mutation.candidates.every((condition) =>
        rotationCandidateEligible(
          this.candidates.get(condition.candidate),
          condition,
          mutation,
        ),
      )
    ) {
      throw new ConditionalWriteError(
        "configuration rotation candidates are not eligible",
      );
    }
    this.configRotationPreparations.set(
      mutation.preparation.rotationId,
      structuredClone(mutation.preparation),
    );
    this.audit.push(structuredClone(mutation.audit));
    this.didMutate();
    return structuredClone(mutation.preparation);
  }

  async commitConfigDigestRotation(
    mutation: ConfigDigestRotationCommitMutation,
  ): Promise<ConfigDigestRotationReceipt> {
    if (this.configRotations.has(mutation.preparation.rotationId)) {
      throw new ConditionalWriteError("configuration rotation id already exists");
    }
    const preparation = this.configRotationPreparations.get(
      mutation.preparation.rotationId,
    );
    const state = this.requireState();
    if (
      !preparation ||
      preparation.requestDigest !== mutation.preparation.requestDigest ||
      preparation.preparationTokenHash !== mutation.preparationTokenHash ||
      state.currentLeader !== preparation.expectedLeader ||
      state.fabricEpoch !== preparation.expectedEpoch ||
      state.configDigest !== preparation.expectedCurrentDigest ||
      !rotationCommitCandidateEligible(
        this.candidates.get(mutation.commitCandidate.candidate),
        mutation,
        state,
      )
    ) {
      throw new ConditionalWriteError(
        "configuration rotation preparation is missing, consumed, stale, or lacks applied standby evidence",
      );
    }
    this.state = structuredClone(mutation.nextState);
    this.configRotationPreparations.delete(preparation.rotationId);
    this.configRotations.set(
      preparation.rotationId,
      structuredClone(mutation.receipt),
    );
    this.audit.push(structuredClone(mutation.audit));
    this.didMutate();
    return structuredClone(mutation.receipt);
  }

  async abortConfigDigestRotation(
    mutation: ConfigDigestRotationAbortMutation,
  ): Promise<ConfigDigestRotationAbortReceipt> {
    if (
      this.configRotations.has(mutation.preparation.rotationId) ||
      this.configRotationAborts.has(mutation.preparation.rotationId)
    ) {
      throw new ConditionalWriteError(
        "configuration rotation id is already resolved",
      );
    }
    const preparation = this.configRotationPreparations.get(
      mutation.preparation.rotationId,
    );
    const state = this.requireState();
    if (
      !preparation ||
      preparation.requestDigest !== mutation.preparation.requestDigest ||
      preparation.preparationTokenHash !== mutation.preparationTokenHash ||
      preparation.expiresAtEpoch >= mutation.nowEpoch ||
      state.currentLeader !== preparation.expectedLeader ||
      state.fabricEpoch !== preparation.expectedEpoch ||
      state.configDigest !== preparation.expectedCurrentDigest ||
      mutation.candidateDigestGuardHosts.some(
        (host) =>
          this.candidates.get(host)?.configDigest ===
          preparation.candidateDigest,
      ) ||
      !rotationAbortCandidateEligible(
        this.candidates.get(mutation.evidenceCandidate.candidate),
        mutation,
        state,
      )
    ) {
      throw new ConditionalWriteError(
        "configuration rotation abort is premature, stale, or lacks old-digest standby evidence",
      );
    }
    this.configRotationPreparations.delete(preparation.rotationId);
    this.configRotationAborts.set(
      preparation.rotationId,
      structuredClone(mutation.receipt),
    );
    this.audit.push(structuredClone(mutation.audit));
    this.didMutate();
    return structuredClone(mutation.receipt);
  }

  async getPromotion(promotionId: string): Promise<PromotionReceipt | null> {
    const receipt = this.promotions.get(promotionId);
    return receipt ? structuredClone(receipt) : null;
  }

  async promote(mutation: PromotionMutation): Promise<PromotionReceipt> {
    const replay = this.promotions.get(mutation.promotionId);
    if (replay) {
      if (replay.requestDigest !== mutation.requestDigest) {
        throw new ConditionalWriteError(
          "promotion id was already used by another request",
        );
      }
      return structuredClone(replay);
    }
    // Keep every conditional check and write in one synchronous section. This
    // makes the SQLite CAS, durable receipt, and audit one crash-safe commit.
    const state = this.requireState();
    if (
      state.currentLeader !== mutation.expectedLeader ||
      state.fabricEpoch !== mutation.expectedEpoch
    ) {
      throw new ConditionalWriteError("expected leader or epoch is stale");
    }
    const currentLeader = this.candidates.get(state.currentLeader);
    if (!currentLeader) {
      throw new ConditionalWriteError(
        "current leader has no candidate-health baseline",
      );
    }
    if (currentLeader.observedAtEpoch >= mutation.freshAfterEpoch) {
      throw new ConditionalWriteError(
        "current leader proof lease has not expired",
      );
    }
    const baselineEpoch = Math.floor(
      new Date(state.leaderBaselineAt ?? "").getTime() / 1000,
    );
    if (
      state.leaderWalPosition !== mutation.expectedLeaderWalPosition ||
      state.upstreamSystemId !== mutation.expectedUpstreamSystemId ||
      !Number.isFinite(baselineEpoch) ||
      baselineEpoch < mutation.leaderBaselineFreshAfterEpoch
    ) {
      throw new ConditionalWriteError(
        "leader WAL baseline is missing, stale, or changed",
      );
    }
    if (!eligible(this.candidates.get(mutation.candidate), mutation)) {
      throw new ConditionalWriteError("promotion candidate is not eligible");
    }
    this.state = structuredClone(mutation.nextState);
    this.promotions.set(
      mutation.promotionId,
      structuredClone(mutation.receipt),
    );
    this.audit.push(structuredClone(mutation.audit));
    this.didMutate();
    return structuredClone(mutation.receipt);
  }

  async putFailbackPlan(
    plan: FailbackPlan,
    audit: AuditRecord,
  ): Promise<void> {
    const state = this.requireState();
    if (
      plan.phase !== "transfer" ||
      state.currentLeader !== plan.expectedLeader ||
      state.fabricEpoch !== plan.expectedEpoch ||
      state.leaderWalPosition !== plan.expectedLeaderWalPosition ||
      state.upstreamSystemId !== plan.expectedUpstreamSystemId ||
      Math.floor(new Date(state.leaderBaselineAt ?? "").getTime() / 1000) <
        plan.leaderBaselineFreshAfterEpoch
    ) {
      throw new ConditionalWriteError("leadership changed while planning failback");
    }
    if (this.plans.has(plan.tokenHash)) {
      throw new ConditionalWriteError("failback plan token collision");
    }
    this.plans.set(plan.tokenHash, structuredClone(plan));
    this.audit.push(structuredClone(audit));
    this.didMutate();
  }

  async putFailbackPreparation(
    plan: FailbackPlan,
    audit: AuditRecord,
  ): Promise<void> {
    const state = this.requireState();
    if (
      plan.phase !== "reseed" ||
      state.currentLeader !== plan.expectedLeader ||
      state.fabricEpoch !== plan.expectedEpoch ||
      state.leaderWalPosition !== plan.expectedLeaderWalPosition ||
      state.upstreamSystemId !== plan.expectedUpstreamSystemId
    ) {
      throw new ConditionalWriteError(
        "leadership changed while authorizing standby reseed",
      );
    }
    if (this.plans.has(plan.tokenHash)) {
      throw new ConditionalWriteError("failback preparation token collision");
    }
    this.plans.set(plan.tokenHash, structuredClone(plan));
    this.audit.push(structuredClone(audit));
    this.didMutate();
  }

  async getFailbackPlan(tokenHash: string): Promise<FailbackPlan | null> {
    const plan = this.plans.get(tokenHash);
    return plan ? structuredClone(plan) : null;
  }

  async commitFailback(
    mutation: FailbackCommitMutation,
  ): Promise<LeadershipState> {
    const plan = this.plans.get(mutation.planTokenHash);
    if (
      !plan ||
      plan.phase !== "transfer" ||
      plan.expiresAtEpoch < mutation.nowEpoch
    ) {
      throw new ConditionalWriteError("failback plan is missing, expired, or consumed");
    }
    const state = this.requireState();
    if (
      state.currentLeader !== mutation.expectedLeader ||
      state.fabricEpoch !== mutation.expectedEpoch
    ) {
      throw new ConditionalWriteError("leadership changed after failback planning");
    }
    const baselineEpoch = Math.floor(
      new Date(state.leaderBaselineAt ?? "").getTime() / 1000,
    );
    if (
      state.leaderWalPosition !== mutation.expectedLeaderWalPosition ||
      state.upstreamSystemId !== mutation.expectedUpstreamSystemId ||
      !Number.isFinite(baselineEpoch) ||
      baselineEpoch < mutation.leaderBaselineFreshAfterEpoch
    ) {
      throw new ConditionalWriteError(
        "leader WAL baseline is missing, stale, or changed",
      );
    }
    if (!eligible(this.candidates.get(mutation.candidate), mutation)) {
      throw new ConditionalWriteError("failback target is not eligible");
    }
    this.state = structuredClone(mutation.nextState);
    this.plans.delete(mutation.planTokenHash);
    this.audit.push(structuredClone(mutation.audit));
    this.didMutate();
    return structuredClone(this.state);
  }

  async appendAudit(audit: AuditRecord): Promise<void> {
    this.audit.push(structuredClone(audit));
    this.didMutate();
  }

  async listAudit(limit: number): Promise<AuditRecord[]> {
    return this.audit
      .slice(-limit)
      .reverse()
      .map((item) => structuredClone(item));
  }
}
