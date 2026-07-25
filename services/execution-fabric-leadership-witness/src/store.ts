import type {
  AuditRecord,
  CandidateRecord,
  FailbackCommitMutation,
  FailbackPlan,
  LeadershipState,
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
  promote(mutation: PromotionMutation): Promise<LeadershipState>;
  putFailbackPreparation(plan: FailbackPlan, audit: AuditRecord): Promise<void>;
  putFailbackPlan(plan: FailbackPlan, audit: AuditRecord): Promise<void>;
  getFailbackPlan(tokenHash: string): Promise<FailbackPlan | null>;
  commitFailback(mutation: FailbackCommitMutation): Promise<LeadershipState>;
  appendAudit(audit: AuditRecord): Promise<void>;
  listAudit(limit: number): Promise<AuditRecord[]>;
}

function eligible(
  candidate: CandidateRecord | undefined,
  mutation: PromotionMutation,
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
  private state?: LeadershipState;
  private readonly candidates = new Map<string, CandidateRecord>();
  private readonly plans = new Map<string, FailbackPlan>();
  private readonly audit: AuditRecord[] = [];

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
  }

  async promote(mutation: PromotionMutation): Promise<LeadershipState> {
    // Keep every conditional check and write in one synchronous section. This
    // mirrors the production DynamoDB transaction and makes dual-promotion
    // tests authoritative instead of allowing an await-point race.
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
    this.audit.push(structuredClone(mutation.audit));
    return structuredClone(this.state);
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
    return structuredClone(this.state);
  }

  async appendAudit(audit: AuditRecord): Promise<void> {
    this.audit.push(structuredClone(audit));
  }

  async listAudit(limit: number): Promise<AuditRecord[]> {
    return this.audit
      .slice(-limit)
      .reverse()
      .map((item) => structuredClone(item));
  }
}
