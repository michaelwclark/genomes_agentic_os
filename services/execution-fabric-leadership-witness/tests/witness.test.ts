import { describe, expect, it } from "vitest";
import { createHash, generateKeyPairSync, verify } from "node:crypto";
import type { WitnessConfig } from "../src/config.js";
import type { CandidateUpdate } from "../src/contracts.js";
import { InMemoryWitnessStore } from "../src/store.js";
import {
  LeadershipWitness,
  WitnessConflictError,
  WitnessNotFoundError,
} from "../src/witness.js";

const signingKeys = generateKeyPairSync("ed25519");
const config: WitnessConfig = {
  host: "127.0.0.1",
  port: 3195,
  clusterId: "test-fabric",
  tableName: "test-witness",
  initialLeader: "genomesbox",
  initialTimelineId: 1,
  initialConfigDigest: "a".repeat(64),
  maxReplicaLagBytes: 100,
  candidateFreshnessSeconds: 90,
  leaderBaselineMaxAgeSeconds: 300,
  planTtlSeconds: 900,
  maxReportSkewSeconds: 30,
  readerToken: "reader-token-000000000000000000000",
  candidateTokens: {
    genomesbox: "genomesbox-token-000000000000000000",
    bigmac: "bigmac-token-0000000000000000000000",
    "recovery-host": "recovery-token-00000000000000000000",
  },
  adminToken: "admin-token-0000000000000000000000",
  signingPrivateKey: signingKeys.privateKey.export({
    type: "pkcs8",
    format: "pem",
  }).toString(),
  logLevel: "silent",
  region: "us-east-1",
  allowDegradedPrimary: true,
  maxDegradedPrimarySeconds: 3600,
};

function fixture() {
  let now = new Date("2026-07-24T20:00:00.000Z");
  let id = 0;
  let tokenId = 0;
  const store = new InMemoryWitnessStore();
  type TestUpdate = Pick<
    CandidateUpdate,
    "healthy" | "replicaLagBytes" | "configDigest"
  > &
    Partial<CandidateUpdate>;
  class TestWitness extends LeadershipWitness {
    override updateCandidate(candidate: string, update: TestUpdate) {
      const inRecovery = candidate !== "genomesbox";
      const receiveWalPosition = update.receiveWalPosition ?? 1_000;
      const replayWalPosition =
        update.replayWalPosition ??
        receiveWalPosition - (update.replicaLagBytes ?? 0);
      return super.updateCandidate(candidate, {
        inRecovery,
        timelineId: 1,
        receiveLsn: "0/100",
        replayLsn: "0/100",
        receiveWalPosition,
        replayWalPosition,
        upstreamSystemId: "7600000000000000000",
        receiverState: inRecovery ? "streaming" : "not_applicable",
        lastMessageAt: now.toISOString(),
        lagMeasuredAt: now.toISOString(),
        ...update,
      });
    }
  }
  const witness = new TestWitness(config, store, {
    now: () => now,
    randomToken: () =>
      `plan-token-${String(++tokenId).padStart(28, "0")}`,
    randomId: () => `receipt-${++id}`,
  });
  return {
    witness,
    store,
    advance(seconds: number) {
      now = new Date(now.getTime() + seconds * 1000);
    },
  };
}

describe("leadership witness", () => {
  it("fails closed until the current leader has a candidate-health baseline", async () => {
    const { witness } = fixture();
    await witness.initialize();
    await witness.updateCandidate("bigmac", {
      healthy: true,
      replicaLagBytes: 0,
      configDigest: config.initialConfigDigest,
    });
    expect((await witness.status()).promotionAllowed).toBe(false);
    await expect(
      witness.promote({
        candidate: "bigmac",
        expectedLeader: "genomesbox",
        expectedEpoch: 1,
        incidentDigest: "b".repeat(64),
      }),
    ).rejects.toBeInstanceOf(WitnessConflictError);
  });

  it("promotes only a fresh, healthy, config-matched standby when the leader is unavailable", async () => {
    const { witness, advance } = fixture();
    await witness.initialize();
    await witness.updateCandidate("genomesbox", {
      healthy: false,
      replicaLagBytes: 0,
      configDigest: config.initialConfigDigest,
    });
    advance(91);
    await witness.updateCandidate("bigmac", {
      healthy: true,
      replicaLagBytes: 12,
      configDigest: config.initialConfigDigest,
    });

    const status = await witness.status();
    expect(status.promotionAllowed).toBe(true);
    expect(status.currentLeader).toBe("genomesbox");

    const receipt = await witness.promote({
      candidate: "bigmac",
      expectedLeader: "genomesbox",
      expectedEpoch: 1,
      incidentDigest: "b".repeat(64),
    });
    expect(receipt.decision).toBe("promoted");
    expect(receipt.fabricEpoch).toBe(2);
    expect(receipt.fenceToken).toMatch(/^v2\./);
    const [, payload, signature] = receipt.fenceToken.split(".");
    expect(
      verify(
        null,
        Buffer.from(payload!),
        signingKeys.publicKey,
        Buffer.from(signature!, "base64url"),
      ),
    ).toBe(true);

    await expect(
      witness.promote({
        candidate: "bigmac",
        expectedLeader: "genomesbox",
        expectedEpoch: 1,
        incidentDigest: "b".repeat(64),
      }),
    ).rejects.toBeInstanceOf(WitnessConflictError);
  });

  it("persists signed time-bounded degraded-primary authority", async () => {
    const { witness, advance } = fixture();
    await witness.initialize();
    await witness.updateCandidate("genomesbox", {
      healthy: false,
      replicaLagBytes: 0,
      configDigest: config.initialConfigDigest,
    });
    advance(91);
    await witness.updateCandidate("bigmac", {
      healthy: true,
      replicaLagBytes: 0,
      configDigest: config.initialConfigDigest,
    });
    const receipt = await witness.promote({
      candidate: "bigmac",
      expectedLeader: "genomesbox",
      expectedEpoch: 1,
      incidentDigest: "d".repeat(64),
      authorityMode: "degraded_primary",
      degradedDurationSeconds: 600,
    });
    expect(receipt).toMatchObject({
      authorityMode: "degraded_primary",
      degradedUntil: "2026-07-24T20:11:31.000Z",
    });
    expect(await witness.status()).toMatchObject({
      currentLeader: "bigmac",
      fabricEpoch: 2,
      authorityMode: "degraded_primary",
      degradedIncidentDigest: "d".repeat(64),
    });
  });

  it("rejects unhealthy, stale, lagging, and config-drifted candidates", async () => {
    const { witness, advance } = fixture();
    await witness.initialize();
    await witness.updateCandidate("genomesbox", {
      healthy: false,
      replicaLagBytes: 0,
      configDigest: config.initialConfigDigest,
    });
    advance(91);
    await witness.updateCandidate("bigmac", {
      healthy: true,
      replicaLagBytes: 101,
      configDigest: config.initialConfigDigest,
    });
    await expect(
      witness.promote({
        candidate: "bigmac",
        expectedLeader: "genomesbox",
        expectedEpoch: 1,
        incidentDigest: "b".repeat(64),
      }),
    ).rejects.toBeInstanceOf(WitnessConflictError);

    await witness.updateCandidate("bigmac", {
      healthy: true,
      replicaLagBytes: 0,
      configDigest: "c".repeat(64),
    });
    await expect(
      witness.promote({
        candidate: "bigmac",
        expectedLeader: "genomesbox",
        expectedEpoch: 1,
        incidentDigest: "b".repeat(64),
      }),
    ).rejects.toBeInstanceOf(WitnessConflictError);

    await witness.updateCandidate("bigmac", {
      healthy: true,
      replicaLagBytes: 0,
      configDigest: config.initialConfigDigest,
    });
    advance(91);
    await expect(
      witness.promote({
        candidate: "bigmac",
        expectedLeader: "genomesbox",
        expectedEpoch: 1,
        incidentDigest: "b".repeat(64),
      }),
    ).rejects.toBeInstanceOf(WitnessConflictError);
  });

  it("rejects a disconnected standby even when its local receive/replay gap is zero", async () => {
    const { witness, advance } = fixture();
    await witness.initialize();
    await witness.updateCandidate("genomesbox", {
      healthy: false,
      replicaLagBytes: 0,
      receiveWalPosition: 1_000,
      replayWalPosition: 1_000,
      configDigest: config.initialConfigDigest,
    });
    advance(91);
    await witness.updateCandidate("bigmac", {
      healthy: true,
      replicaLagBytes: 0,
      receiveWalPosition: 1_000,
      replayWalPosition: 1_000,
      receiverState: "disconnected",
      lastMessageAt: "2026-07-24T20:00:00.000Z",
      configDigest: config.initialConfigDigest,
    });
    const status = await witness.status();
    expect(status.candidates.bigmac!.reasons).toContain(
      "wal_receiver_not_streaming",
    );
    expect(status.candidates.bigmac!.reasons).toContain(
      "wal_receiver_message_stale",
    );
    await expect(
      witness.promote({
        candidate: "bigmac",
        expectedLeader: "genomesbox",
        expectedEpoch: 1,
        incidentDigest: "b".repeat(64),
      }),
    ).rejects.toBeInstanceOf(WitnessConflictError);
  });

  it("uses the upstream leader WAL baseline instead of trusting a zero local gap", async () => {
    const { witness, advance } = fixture();
    await witness.initialize();
    await witness.updateCandidate("genomesbox", {
      healthy: false,
      replicaLagBytes: 0,
      receiveWalPosition: 2_000,
      replayWalPosition: 2_000,
      configDigest: config.initialConfigDigest,
    });
    advance(91);
    await witness.updateCandidate("bigmac", {
      healthy: true,
      replicaLagBytes: 0,
      receiveWalPosition: 1_000,
      replayWalPosition: 1_000,
      configDigest: config.initialConfigDigest,
    });
    const status = await witness.status();
    expect(status.candidates.bigmac!.upstreamWalGapBytes).toBe(1_000);
    expect(status.candidates.bigmac!.reasons).toContain(
      "upstream_wal_gap_exceeds_limit",
    );
    await expect(
      witness.promote({
        candidate: "bigmac",
        expectedLeader: "genomesbox",
        expectedEpoch: 1,
        incidentDigest: "b".repeat(64),
      }),
    ).rejects.toBeInstanceOf(WitnessConflictError);
  });

  it("rejects promotion when the last accepted leader WAL baseline is stale", async () => {
    const { witness, advance } = fixture();
    await witness.initialize();
    await witness.updateCandidate("genomesbox", {
      healthy: false,
      replicaLagBytes: 0,
      configDigest: config.initialConfigDigest,
    });
    advance(301);
    await witness.updateCandidate("bigmac", {
      healthy: true,
      replicaLagBytes: 0,
      configDigest: config.initialConfigDigest,
    });
    const status = await witness.status();
    expect(status.candidates.bigmac!.reasons).toContain(
      "leader_wal_baseline_stale",
    );
    await expect(
      witness.promote({
        candidate: "bigmac",
        expectedLeader: "genomesbox",
        expectedEpoch: 1,
        incidentDigest: "b".repeat(64),
      }),
    ).rejects.toBeInstanceOf(WitnessConflictError);
  });

  it("rejects promoted primaries, timeline drift, and backdated lag samples", async () => {
    const { witness, advance } = fixture();
    await witness.initialize();
    await witness.updateCandidate("genomesbox", {
      healthy: false,
      replicaLagBytes: 0,
      configDigest: config.initialConfigDigest,
    });
    advance(91);
    for (const update of [
      { inRecovery: false },
      { inRecovery: true, timelineId: 2 },
    ]) {
      await witness.updateCandidate("bigmac", {
        healthy: true,
        replicaLagBytes: 0,
        configDigest: config.initialConfigDigest,
        ...update,
      });
      await expect(
        witness.promote({
          candidate: "bigmac",
          expectedLeader: "genomesbox",
          expectedEpoch: 1,
          incidentDigest: "b".repeat(64),
        }),
      ).rejects.toBeInstanceOf(WitnessConflictError);
    }
    await expect(
      witness.updateCandidate("bigmac", {
        healthy: true,
        replicaLagBytes: 0,
        configDigest: config.initialConfigDigest,
        lagMeasuredAt: "2026-07-24T20:00:00.000Z",
      }),
    ).rejects.toThrow(/clock-skew/);
  });

  it("commits exactly one winner under concurrent dual promotion", async () => {
    const { witness, advance } = fixture();
    await witness.initialize();
    await witness.updateCandidate("genomesbox", {
      healthy: false,
      replicaLagBytes: 0,
      configDigest: config.initialConfigDigest,
    });
    advance(91);
    for (const candidate of ["bigmac", "recovery-host"]) {
      await witness.updateCandidate(candidate, {
        healthy: true,
        replicaLagBytes: 0,
        configDigest: config.initialConfigDigest,
      });
    }
    const results = await Promise.allSettled(
      ["bigmac", "recovery-host"].map((candidate, index) =>
        witness.promote({
          candidate,
          expectedLeader: "genomesbox",
          expectedEpoch: 1,
          incidentDigest: String(index + 1).repeat(64),
        }),
      ),
    );
    expect(results.filter((result) => result.status === "fulfilled")).toHaveLength(1);
    expect(results.filter((result) => result.status === "rejected")).toHaveLength(1);
    const status = await witness.status();
    expect(status.fabricEpoch).toBe(2);
    expect(["bigmac", "recovery-host"]).toContain(status.currentLeader);
  });

  it("plans manual failback, requires the exact token, and consumes it once", async () => {
    const { witness, advance } = fixture();
    await witness.initialize();
    await witness.updateCandidate("genomesbox", {
      healthy: false,
      replicaLagBytes: 0,
      configDigest: config.initialConfigDigest,
    });
    advance(91);
    await witness.updateCandidate("bigmac", {
      healthy: true,
      replicaLagBytes: 0,
      configDigest: config.initialConfigDigest,
    });
    await witness.promote({
      candidate: "bigmac",
      expectedLeader: "genomesbox",
      expectedEpoch: 1,
      incidentDigest: "b".repeat(64),
    });
    const preparation = await witness.prepareFailback({
      from: "bigmac",
      to: "genomesbox",
      mode: "standby_reseed",
    });
    expect(preparation.authorized).toBe(true);
    expect(preparation.preparationToken).toBe(
      "plan-token-0000000000000000000000000001",
    );
    const unsafeBeforeReseed = await witness.planFailback({
      from: "bigmac",
      to: "genomesbox",
      mode: "manual_failback",
      preparationToken: preparation.preparationToken,
    });
    expect(unsafeBeforeReseed).toMatchObject({
      safe: false,
      reasons: expect.arrayContaining(["candidate_not_in_recovery"]),
    });
    await witness.updateCandidate("genomesbox", {
      healthy: true,
      inRecovery: true,
      timelineId: 2,
      replicaLagBytes: 0,
      receiverState: "streaming",
      configDigest: config.initialConfigDigest,
    });

    const plan = await witness.planFailback({
      from: "bigmac",
      to: "genomesbox",
      mode: "manual_failback",
      preparationToken: preparation.preparationToken,
    });
    expect(plan.safe).toBe(true);
    expect(plan.planToken).toBe(
      "plan-token-0000000000000000000000000002",
    );

    await expect(
      witness.commitFailback({
        planToken: plan.planToken!,
        approval: {
          planTokenHash: "f".repeat(64),
          approvalId: "00000000-0000-4000-8000-000000000001",
          approvedBy: "operator-a",
          approvedAt: "2026-07-24T20:01:31.000Z",
        },
      }),
    ).rejects.toBeInstanceOf(WitnessConflictError);

    const receipt = await witness.commitFailback({
      planToken: plan.planToken!,
      approval: {
        planTokenHash: createHash("sha256")
          .update(plan.planToken!)
          .digest("hex"),
        approvalId: "00000000-0000-4000-8000-000000000001",
        approvedBy: "operator-a",
        approvedAt: "2026-07-24T20:01:31.000Z",
      },
    });
    expect(receipt.decision).toBe("committed");
    expect(receipt.currentLeader).toBe("genomesbox");
    expect(receipt.fabricEpoch).toBe(3);

    await expect(
      witness.commitFailback({
        planToken: plan.planToken!,
        approval: {
          planTokenHash: createHash("sha256")
            .update(plan.planToken!)
            .digest("hex"),
          approvalId: "00000000-0000-4000-8000-000000000001",
          approvedBy: "operator-a",
          approvedAt: "2026-07-24T20:01:31.000Z",
        },
      }),
    ).rejects.toBeInstanceOf(WitnessNotFoundError);

    const audit = await witness.audit(20);
    expect(audit.some((event) => event.eventType === "promotion_committed")).toBe(
      true,
    );
    expect(audit.some((event) => event.eventType === "failback_committed")).toBe(
      true,
    );
  });
});
