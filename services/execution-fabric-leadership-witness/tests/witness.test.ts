import { describe, expect, it } from "vitest";
import { createHash, generateKeyPairSync, verify } from "node:crypto";
import type { WitnessConfig } from "../src/config.js";
import type { CandidateUpdate, PromotionRequest } from "../src/contracts.js";
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
  witnessHostId: "witness-1",
  clusterId: "test-fabric",
  stateFile: "/tmp/test-witness.sqlite3",
  bootstrapOnce: false,
  processLeaseSeconds: 30,
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
    override promote(
      request: Omit<PromotionRequest, "promotionId"> &
        Partial<Pick<PromotionRequest, "promotionId">>,
    ) {
      return super.promote({
        ...request,
        promotionId:
          request.promotionId ??
          `00000000-0000-4000-8000-${String(++id).padStart(12, "0")}`,
      });
    }
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

type RotationTestWitness = ReturnType<typeof fixture>["witness"];

describe("leadership witness", () => {
  const rotationRequest = {
    rotationId: "00000000-0000-4000-8000-000000000101",
    expectedLeader: "genomesbox",
    expectedEpoch: 1,
    expectedCurrentDigest: config.initialConfigDigest,
    candidateDigest: "b".repeat(64),
  };

  async function seedRotationCandidates(
    witness: RotationTestWitness,
    overrides: Partial<Record<string, Partial<CandidateUpdate>>> = {},
  ) {
    await witness.updateCandidate("genomesbox", {
      healthy: true,
      replicaLagBytes: 0,
      receiveWalPosition: 2_000,
      replayWalPosition: 2_000,
      configDigest: config.initialConfigDigest,
    });
    for (const candidate of Object.keys(config.candidateTokens)) {
      await witness.updateCandidate(candidate, {
        healthy: true,
        replicaLagBytes: 0,
        receiveWalPosition: 2_000,
        replayWalPosition: 2_000,
        configDigest: config.initialConfigDigest,
        policyCandidateDigest: rotationRequest.candidateDigest,
        ...(overrides[candidate] ?? {}),
      });
    }
  }

  it("prepares durably, survives stale host reports, and atomically commits one idempotent receipt", async () => {
    const { witness, advance } = fixture();
    await witness.initialize();
    await seedRotationCandidates(witness);

    const [preparation, prepareReplay] = await Promise.all([
      witness.prepareConfigDigestRotation(rotationRequest),
      witness.prepareConfigDigestRotation(rotationRequest),
    ]);
    expect(prepareReplay).toEqual(preparation);
    expect(preparation).toMatchObject({
      decision: "config_digest_rotation_prepared",
      rotationId: rotationRequest.rotationId,
      expectedLeader: "genomesbox",
      expectedEpoch: 1,
      expectedCurrentDigest: config.initialConfigDigest,
      candidateDigest: rotationRequest.candidateDigest,
      candidateHosts: ["bigmac", "genomesbox", "recovery-host"],
      expiresAt: "2026-07-24T20:15:00.000Z",
    });
    expect(preparation.preparationToken).toMatch(/^cpr1\./);
    const [, payload, signature] = preparation.preparationToken.split(".");
    expect(
      verify(
        null,
        Buffer.from(payload!),
        signingKeys.publicKey,
        Buffer.from(signature!, "base64url"),
      ),
    ).toBe(true);
    expect(
      JSON.parse(Buffer.from(payload!, "base64url").toString("utf8")),
    ).toEqual({
      v: 1,
      type: "config_digest_rotation_preparation",
      clusterId: config.clusterId,
      rotationId: rotationRequest.rotationId,
      expectedLeader: "genomesbox",
      expectedEpoch: 1,
      expectedCurrentDigest: config.initialConfigDigest,
      candidateDigest: rotationRequest.candidateDigest,
      issuedAt: "2026-07-24T20:00:00.000Z",
      expiresAt: "2026-07-24T20:15:00.000Z",
    });
    expect(
      await witness.configDigestRotationPreparation(rotationRequest.rotationId),
    ).toEqual(preparation);
    expect(
      await witness.prepareConfigDigestRotation(rotationRequest),
    ).toEqual(preparation);
    expect(await witness.status()).toMatchObject({
      currentLeader: "genomesbox",
      fabricEpoch: 1,
      configDigest: config.initialConfigDigest,
      pendingConfigDigestRotations: [
        { rotationId: rotationRequest.rotationId },
      ],
    });

    const commitRequest = {
      rotationId: rotationRequest.rotationId,
      preparationToken: preparation.preparationToken,
    };
    await expect(
      witness.commitConfigDigestRotation(commitRequest),
    ).rejects.toThrow(/database applied the candidate digest/);

    // The old leader may go stale or die, but one fresh standby must prove its
    // replicated database has applied the prepared fingerprint.
    advance(91);
    await witness.updateCandidate("bigmac", {
      healthy: true,
      replicaLagBytes: 0,
      receiveWalPosition: 2_000,
      replayWalPosition: 2_000,
      configDigest: rotationRequest.candidateDigest,
    });
    const [first, replay] = await Promise.all([
      witness.commitConfigDigestRotation(commitRequest),
      witness.commitConfigDigestRotation(commitRequest),
    ]);
    expect(replay).toEqual(first);
    expect(first).toMatchObject({
      decision: "config_digest_rotated",
      rotationId: rotationRequest.rotationId,
      currentLeader: "genomesbox",
      fabricEpoch: 1,
      previousConfigDigest: config.initialConfigDigest,
      configDigest: rotationRequest.candidateDigest,
      candidateHosts: ["bigmac", "genomesbox", "recovery-host"],
      preparationTokenHash: preparation.preparationTokenHash,
    });
    expect(await witness.configDigestRotation(rotationRequest.rotationId)).toEqual(
      first,
    );
    expect(await witness.status()).toMatchObject({
      currentLeader: "genomesbox",
      fabricEpoch: 1,
      configDigest: rotationRequest.candidateDigest,
      pendingConfigDigestRotations: [],
    });
    await expect(
      witness.configDigestRotationPreparation(rotationRequest.rotationId),
    ).rejects.toBeInstanceOf(WitnessNotFoundError);
    const audit = await witness.audit(50);
    expect(
      audit.filter(
        (record) =>
          record.eventType === "config_digest_rotation_prepared",
      ),
    ).toHaveLength(1);
    expect(
      audit.filter((record) => record.eventType === "config_digest_rotated"),
    ).toHaveLength(1);
  });

  it("fails closed for missing, mismatched, stale, timeline-drifted, and WAL-unsafe host reports", async () => {
    const cases: Array<{
      name: string;
      seed: (witness: RotationTestWitness) => Promise<void>;
      after?: (advance: (seconds: number) => void) => void;
      reason: RegExp;
    }> = [
      {
        name: "missing",
        seed: async (witness) => {
          await witness.updateCandidate("genomesbox", {
            healthy: true,
            replicaLagBytes: 0,
            configDigest: config.initialConfigDigest,
          });
          for (const candidate of ["genomesbox", "bigmac"]) {
            await witness.updateCandidate(candidate, {
              healthy: true,
              replicaLagBytes: 0,
              configDigest: config.initialConfigDigest,
              policyCandidateDigest: rotationRequest.candidateDigest,
            });
          }
        },
        reason: /recovery-host:candidate_not_reported/,
      },
      {
        name: "applied digest",
        seed: async (witness) =>
          seedRotationCandidates(witness, {
            bigmac: { configDigest: "c".repeat(64) },
          }),
        reason: /bigmac:applied_config_digest_mismatch/,
      },
      {
        name: "staged digest",
        seed: async (witness) =>
          seedRotationCandidates(witness, {
            bigmac: { policyCandidateDigest: "c".repeat(64) },
          }),
        reason: /bigmac:policy_candidate_digest_mismatch/,
      },
      {
        name: "stale",
        seed: async (witness) => seedRotationCandidates(witness),
        after: (advance) => advance(91),
        reason: /candidate_observation_stale/,
      },
      {
        name: "timeline",
        seed: async (witness) =>
          seedRotationCandidates(witness, {
            bigmac: { timelineId: 2 },
          }),
        reason: /bigmac:timeline_mismatch/,
      },
      {
        name: "wal",
        seed: async (witness) =>
          seedRotationCandidates(witness, {
            bigmac: {
              receiveWalPosition: 1_000,
              replayWalPosition: 1_000,
            },
          }),
        reason: /bigmac:upstream_wal_gap_exceeds_limit/,
      },
      {
        name: "upstream",
        seed: async (witness) =>
          seedRotationCandidates(witness, {
            bigmac: { upstreamSystemId: "7700000000000000000" },
          }),
        reason: /bigmac:upstream_system_id_mismatch/,
      },
    ];
    for (const testCase of cases) {
      const { witness, advance } = fixture();
      await witness.initialize();
      await testCase.seed(witness);
      testCase.after?.(advance);
      await expect(
        witness.prepareConfigDigestRotation({
          ...rotationRequest,
          rotationId: rotationRequest.rotationId.replace(/101$/, "102"),
        }),
        testCase.name,
      ).rejects.toThrow(testCase.reason);
    }
  });

  it("keeps expired preparations discoverable and commits them only after fresh applied standby evidence", async () => {
    const { witness, advance } = fixture();
    await witness.initialize();
    await seedRotationCandidates(witness);
    const preparation =
      await witness.prepareConfigDigestRotation(rotationRequest);
    await expect(
      witness.prepareConfigDigestRotation({
        ...rotationRequest,
        candidateDigest: "c".repeat(64),
      }),
    ).rejects.toThrow(/already used/);
    await expect(
      witness.commitConfigDigestRotation({
        rotationId: rotationRequest.rotationId,
        preparationToken: `${preparation.preparationToken.slice(0, -1)}${
          preparation.preparationToken.endsWith("A") ? "B" : "A"
        }`,
      }),
    ).rejects.toThrow(/invalid or mismatched/);
    advance(901);
    expect(await witness.status()).toMatchObject({
      pendingConfigDigestRotations: [
        {
          rotationId: rotationRequest.rotationId,
          expired: true,
        },
      ],
    });
    expect(
      await witness.configDigestRotationPreparation(rotationRequest.rotationId),
    ).toEqual(preparation);
    expect(
      await witness.prepareConfigDigestRotation(rotationRequest),
    ).toEqual(preparation);
    await expect(
      witness.commitConfigDigestRotation({
        rotationId: rotationRequest.rotationId,
        preparationToken: preparation.preparationToken,
      }),
    ).rejects.toThrow(/database applied the candidate digest/);
    await witness.updateCandidate("bigmac", {
      healthy: true,
      replicaLagBytes: 0,
      receiveWalPosition: 2_000,
      replayWalPosition: 2_000,
      configDigest: rotationRequest.candidateDigest,
    });
    await expect(
      witness.commitConfigDigestRotation({
        rotationId: rotationRequest.rotationId,
        preparationToken: preparation.preparationToken,
      }),
    ).resolves.toMatchObject({
      decision: "config_digest_rotated",
      configDigest: rotationRequest.candidateDigest,
    });
    await expect(
      witness.configDigestRotation(
        "00000000-0000-4000-8000-000000000999",
      ),
    ).rejects.toBeInstanceOf(WitnessNotFoundError);
  });

  it("preserves staged policy fields across applied-health updates only within their freshness lease", async () => {
    const { witness, advance } = fixture();
    await witness.initialize();
    await witness.updateCandidate("genomesbox", {
      healthy: true,
      replicaLagBytes: 0,
      configDigest: config.initialConfigDigest,
      policyCandidateDigest: rotationRequest.candidateDigest,
    });
    advance(30);
    await witness.updateCandidate("genomesbox", {
      healthy: true,
      replicaLagBytes: 0,
      configDigest: config.initialConfigDigest,
    });
    expect((await witness.status()).candidates.genomesbox).toMatchObject({
      configDigest: config.initialConfigDigest,
      policyCandidateDigest: rotationRequest.candidateDigest,
      policyCandidateObservedAt: "2026-07-24T20:00:00.000Z",
    });
    advance(61);
    await witness.updateCandidate("genomesbox", {
      healthy: true,
      replicaLagBytes: 0,
      configDigest: config.initialConfigDigest,
    });
    expect((await witness.status()).candidates.genomesbox).toMatchObject({
      configDigest: config.initialConfigDigest,
      policyCandidateDigest: null,
      policyCandidateObservedAt: null,
    });
  });

  it("enforces one unresolved preparation per cluster", async () => {
    const { witness } = fixture();
    await witness.initialize();
    await seedRotationCandidates(witness);
    const first = await witness.prepareConfigDigestRotation(rotationRequest);
    const secondRequest = {
      ...rotationRequest,
      rotationId: "00000000-0000-4000-8000-000000000104",
      candidateDigest: "c".repeat(64),
    };
    for (const candidate of Object.keys(config.candidateTokens)) {
      await witness.updateCandidate(candidate, {
        healthy: true,
        replicaLagBytes: 0,
        receiveWalPosition: 2_000,
        replayWalPosition: 2_000,
        configDigest: config.initialConfigDigest,
        policyCandidateDigest: secondRequest.candidateDigest,
      });
    }
    await expect(
      witness.prepareConfigDigestRotation(secondRequest),
    ).rejects.toThrow(/another unresolved configuration rotation is active/);
    expect(
      await witness.configDigestRotationPreparation(first.rotationId),
    ).toEqual(first);
  });

  it("aborts an expired abandoned preparation with fresh old-digest standby evidence and releases the singleton", async () => {
    const { witness, advance } = fixture();
    await witness.initialize();
    await seedRotationCandidates(witness);
    const preparation =
      await witness.prepareConfigDigestRotation(rotationRequest);
    const abortRequest = {
      rotationId: preparation.rotationId,
      preparationToken: preparation.preparationToken,
    };
    await expect(
      witness.abortConfigDigestRotation(abortRequest),
    ).rejects.toThrow(/cannot be aborted before expiry/);

    advance(901);
    await witness.updateCandidate("bigmac", {
      healthy: true,
      replicaLagBytes: 0,
      receiveWalPosition: 2_000,
      replayWalPosition: 2_000,
      configDigest: config.initialConfigDigest,
    });
    const receipt = await witness.abortConfigDigestRotation(abortRequest);
    expect(receipt).toMatchObject({
      decision: "config_digest_rotation_aborted",
      rotationId: preparation.rotationId,
      currentLeader: "genomesbox",
      fabricEpoch: 1,
      configDigest: config.initialConfigDigest,
      candidateDigest: rotationRequest.candidateDigest,
      evidenceHost: "bigmac",
    });
    expect(await witness.abortConfigDigestRotation(abortRequest)).toEqual(
      receipt,
    );
    expect(
      await witness.configDigestRotationAbort(preparation.rotationId),
    ).toEqual(receipt);
    expect(await witness.status()).toMatchObject({
      currentLeader: "genomesbox",
      fabricEpoch: 1,
      configDigest: config.initialConfigDigest,
      pendingConfigDigestRotations: [],
    });
    expect(
      (await witness.audit(50)).filter(
        (record) =>
          record.eventType === "config_digest_rotation_aborted",
      ),
    ).toHaveLength(1);

    const nextRequest = {
      ...rotationRequest,
      rotationId: "00000000-0000-4000-8000-000000000104",
      candidateDigest: "c".repeat(64),
    };
    for (const candidate of Object.keys(config.candidateTokens)) {
      await witness.updateCandidate(candidate, {
        healthy: true,
        replicaLagBytes: 0,
        receiveWalPosition: 2_000,
        replayWalPosition: 2_000,
        configDigest: config.initialConfigDigest,
        policyCandidateDigest: nextRequest.candidateDigest,
      });
    }
    await expect(
      witness.prepareConfigDigestRotation(nextRequest),
    ).resolves.toMatchObject({ rotationId: nextRequest.rotationId });
  });

  it("never aborts when any configured standby reports the candidate digest applied", async () => {
    const { witness, advance } = fixture();
    await witness.initialize();
    await seedRotationCandidates(witness);
    const preparation =
      await witness.prepareConfigDigestRotation(rotationRequest);
    advance(901);
    await witness.updateCandidate("bigmac", {
      healthy: true,
      replicaLagBytes: 0,
      receiveWalPosition: 2_000,
      replayWalPosition: 2_000,
      configDigest: rotationRequest.candidateDigest,
    });
    await witness.updateCandidate("recovery-host", {
      healthy: true,
      replicaLagBytes: 0,
      receiveWalPosition: 2_000,
      replayWalPosition: 2_000,
      configDigest: config.initialConfigDigest,
    });
    await expect(
      witness.abortConfigDigestRotation({
        rotationId: preparation.rotationId,
        preparationToken: preparation.preparationToken,
      }),
    ).rejects.toThrow(/a standby applied the candidate digest/);
  });

  it("does not abort from an old-digest report observed just before expiry", async () => {
    const { witness, advance } = fixture();
    await witness.initialize();
    await seedRotationCandidates(witness);
    const preparation =
      await witness.prepareConfigDigestRotation(rotationRequest);

    advance(899);
    await witness.updateCandidate("bigmac", {
      healthy: true,
      replicaLagBytes: 0,
      receiveWalPosition: 2_000,
      replayWalPosition: 2_000,
      configDigest: config.initialConfigDigest,
    });
    // The database can commit between this old report and expiry. The report
    // remains generically fresh, but it is not causally post-expiry evidence.
    advance(2);
    await expect(
      witness.abortConfigDigestRotation({
        rotationId: preparation.rotationId,
        preparationToken: preparation.preparationToken,
      }),
    ).rejects.toThrow(/database remains on the current digest/);

    await witness.updateCandidate("bigmac", {
      healthy: true,
      replicaLagBytes: 0,
      receiveWalPosition: 2_000,
      replayWalPosition: 2_000,
      configDigest: rotationRequest.candidateDigest,
    });
    await expect(
      witness.commitConfigDigestRotation({
        rotationId: preparation.rotationId,
        preparationToken: preparation.preparationToken,
      }),
    ).resolves.toMatchObject({
      decision: "config_digest_rotated",
      configDigest: rotationRequest.candidateDigest,
    });
  });

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
      policyCandidateDigest: "c".repeat(64),
    });

    const status = await witness.status();
    expect(status.promotionAllowed).toBe(true);
    expect(status.currentLeader).toBe("genomesbox");
    const [, statusPayload] = status.leadershipToken.split(".");
    expect(
      JSON.parse(
        Buffer.from(statusPayload!, "base64url").toString("utf8"),
      ),
    ).toMatchObject({
      v: 2,
      leader: "genomesbox",
      epoch: 1,
      configDigest: config.initialConfigDigest,
    });

    const promotionRequest = {
      promotionId: "00000000-0000-4000-8000-000000000201",
      candidate: "bigmac",
      expectedLeader: "genomesbox",
      expectedEpoch: 1,
      incidentDigest: "b".repeat(64),
    };
    const receipt = await witness.promote(promotionRequest);
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
    expect(
      JSON.parse(Buffer.from(payload!, "base64url").toString("utf8")),
    ).toMatchObject({
      v: 2,
      cluster: config.clusterId,
      leader: "bigmac",
      epoch: 2,
      configDigest: config.initialConfigDigest,
    });
    await expect(witness.promote(promotionRequest)).resolves.toEqual(receipt);
    await expect(witness.promotion(promotionRequest.promotionId)).resolves.toEqual(
      receipt,
    );
    await expect(
      witness.promote({
        ...promotionRequest,
        incidentDigest: "c".repeat(64),
      }),
    ).rejects.toThrow(/already used/);

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
    const [, failbackPayload] = receipt.fenceToken.split(".");
    expect(
      JSON.parse(
        Buffer.from(failbackPayload!, "base64url").toString("utf8"),
      ),
    ).toMatchObject({
      v: 2,
      leader: "genomesbox",
      epoch: 3,
      configDigest: config.initialConfigDigest,
    });

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
