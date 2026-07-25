import { describe, expect, it, vi } from "vitest";
import type {
  ConfigDigestRotationAbortMutation,
  ConfigDigestRotationAbortReceipt,
  ConfigDigestRotationCommitMutation,
  ConfigDigestRotationPreparation,
  ConfigDigestRotationPreparationMutation,
  ConfigDigestRotationReceipt,
} from "../src/contracts.js";
import { DynamoWitnessStore } from "../src/dynamo-store.js";
import { ConditionalWriteError } from "../src/store.js";

const previousDigest = "a".repeat(64);
const candidateDigest = "b".repeat(64);
const preparation: ConfigDigestRotationPreparation = {
  apiVersion: "execution-fabric-leadership/v1",
  decision: "config_digest_rotation_prepared",
  rotationId: "00000000-0000-4000-8000-000000000301",
  requestDigest: "c".repeat(64),
  expectedLeader: "genomesbox",
  expectedEpoch: 7,
  expectedCurrentDigest: previousDigest,
  candidateDigest,
  candidateHosts: ["bigmac", "genomesbox"],
  expectedTimelineId: 4,
  expectedLeaderWalPosition: 2_000,
  expectedUpstreamSystemId: "7600000000000000000",
  minimumStandbyReplayWalPosition: 1_900,
  maxReplicaLagBytes: 100,
  preparationToken: "cpr1.payload.signature",
  preparationTokenHash: "e".repeat(64),
  issuedAt: "2026-07-24T20:00:00.000Z",
  expiresAt: "2026-07-24T20:15:00.000Z",
  expiresAtEpoch: 1_753_388_100,
};
const receipt: ConfigDigestRotationReceipt = {
  apiVersion: "execution-fabric-leadership/v1",
  decision: "config_digest_rotated",
  rotationId: preparation.rotationId,
  requestDigest: preparation.requestDigest,
  currentLeader: "genomesbox",
  fabricEpoch: 7,
  previousConfigDigest: previousDigest,
  configDigest: candidateDigest,
  candidateHosts: preparation.candidateHosts,
  preparationTokenHash: preparation.preparationTokenHash,
  committedAt: "2026-07-24T20:02:00.000Z",
};
const abortReceipt: ConfigDigestRotationAbortReceipt = {
  apiVersion: "execution-fabric-leadership/v1",
  decision: "config_digest_rotation_aborted",
  rotationId: preparation.rotationId,
  requestDigest: preparation.requestDigest,
  currentLeader: preparation.expectedLeader,
  fabricEpoch: preparation.expectedEpoch,
  configDigest: preparation.expectedCurrentDigest,
  candidateDigest: preparation.candidateDigest,
  evidenceHost: "bigmac",
  preparationTokenHash: preparation.preparationTokenHash,
  expiredAt: preparation.expiresAt,
  abortedAt: "2026-07-24T20:16:00.000Z",
};

const prepareMutation: ConfigDigestRotationPreparationMutation = {
  preparation,
  expectedLeader: "genomesbox",
  expectedEpoch: 7,
  expectedCurrentDigest: previousDigest,
  candidateDigest,
  expectedTimelineId: 4,
  expectedLeaderWalPosition: 2_000,
  expectedUpstreamSystemId: "7600000000000000000",
  leaderBaselineFreshAfterEpoch: 1_753_387_000,
  candidateFreshAfterEpoch: 1_753_387_100,
  policyCandidateFreshAfterEpoch: 1_753_387_100,
  receiverFreshAfterEpoch: 1_753_387_100,
  maxReplicaLagBytes: 100,
  candidates: [
    {
      candidate: "bigmac",
      inRecovery: true,
      receiverState: "streaming",
      minimumReplayWalPosition: 1_900,
    },
    {
      candidate: "genomesbox",
      inRecovery: false,
      receiverState: "not_applicable",
      minimumReplayWalPosition: 2_000,
    },
  ],
  audit: {
    auditId: `${preparation.rotationId}:prepare`,
    eventType: "config_digest_rotation_prepared",
    actor: "authenticated_admin",
    occurredAt: preparation.issuedAt,
    requestDigest: preparation.requestDigest,
    detail: { candidateDigest },
  },
};

const nextState = {
  currentLeader: "genomesbox",
  fabricEpoch: 7,
  timelineId: 4,
  configDigest: candidateDigest,
  leaderWalPosition: 2_000,
  leaderBaselineAt: "2026-07-24T20:00:00.000Z",
  upstreamSystemId: "7600000000000000000",
  updatedAt: receipt.committedAt,
  fenceDigest: "d".repeat(64),
  authorityMode: "synchronous" as const,
  degradedUntil: null,
  degradedIncidentDigest: null,
};

const commitMutation: ConfigDigestRotationCommitMutation = {
  preparation,
  preparationTokenHash: preparation.preparationTokenHash,
  candidateFreshAfterEpoch: 1_753_387_100,
  receiverFreshAfterEpoch: 1_753_387_100,
  commitCandidate: {
    candidate: "bigmac",
    inRecovery: true,
    receiverState: "streaming",
    minimumReplayWalPosition: 1_900,
  },
  nextState,
  receipt,
  audit: {
    auditId: `${preparation.rotationId}:commit`,
    eventType: "config_digest_rotated",
    actor: "authenticated_admin",
    occurredAt: receipt.committedAt,
    requestDigest: preparation.requestDigest,
    detail: { candidateDigest },
  },
};
const abortMutation: ConfigDigestRotationAbortMutation = {
  preparation,
  preparationTokenHash: preparation.preparationTokenHash,
  nowEpoch: preparation.expiresAtEpoch + 60,
  evidenceAfterEpoch: preparation.expiresAtEpoch,
  evidenceCandidate: {
    candidate: "bigmac",
    inRecovery: true,
    receiverState: "streaming",
    minimumReplayWalPosition: preparation.minimumStandbyReplayWalPosition,
  },
  candidateDigestGuardHosts: [],
  receipt: abortReceipt,
  audit: {
    auditId: `${preparation.rotationId}:abort`,
    eventType: "config_digest_rotation_aborted",
    actor: "authenticated_admin",
    occurredAt: abortReceipt.abortedAt,
    requestDigest: preparation.requestDigest,
    detail: { evidenceHost: "bigmac" },
  },
};

function fixture() {
  const store = new DynamoWitnessStore("witness-table", "test-fabric", {
    region: "us-east-1",
  });
  const send = vi.fn();
  (
    store as unknown as {
      client: { send: typeof send };
    }
  ).client.send = send;
  return { store, send };
}

describe("Dynamo configuration digest rotation", () => {
  it("durably prepares in one conditional transaction without mutating state", async () => {
    const { store, send } = fixture();
    send.mockResolvedValueOnce({});
    await expect(
      store.prepareConfigDigestRotation(prepareMutation),
    ).resolves.toEqual(preparation);

    const command = send.mock.calls[0]![0] as {
      input: { TransactItems: Array<Record<string, unknown>> };
    };
    const items = command.input.TransactItems;
    expect(items).toHaveLength(6);
    expect(items[0]).toHaveProperty("ConditionCheck");
    expect(items[0]).not.toHaveProperty("Update");
    const stateCondition = items[0]!.ConditionCheck as {
      ConditionExpression: string;
    };
    expect(stateCondition.ConditionExpression).toContain(
      "currentLeader = :expectedLeader AND fabricEpoch = :expectedEpoch",
    );
    expect(stateCondition.ConditionExpression).toContain(
      "configDigest = :expectedCurrentDigest",
    );
    for (const item of items.slice(1, 3)) {
      const condition = item.ConditionCheck as {
        ConditionExpression: string;
        ExpressionAttributeValues: Record<string, unknown>;
      };
      expect(condition.ConditionExpression).toContain(
        "configDigest = :expectedCurrentDigest",
      );
      expect(condition.ConditionExpression).toContain(
        "policyCandidateDigest = :candidateDigest",
      );
      expect(condition.ConditionExpression).toContain(
        "policyCandidateObservedAt >= :policyFreshAfterIso",
      );
      expect(condition.ExpressionAttributeValues[":candidateDigest"]).toBe(
        candidateDigest,
      );
    }
    expect(items[3]!.Put).toMatchObject({
      ConditionExpression: "attribute_not_exists(pk)",
      Item: {
        entity: "config_digest_rotation_active",
        rotationId: preparation.rotationId,
        requestDigest: preparation.requestDigest,
      },
    });
    expect(items[4]!.Put).toMatchObject({
      ConditionExpression: "attribute_not_exists(pk)",
      Item: {
        entity: "config_digest_rotation_preparation",
        rotationId: preparation.rotationId,
        preparationTokenHash: preparation.preparationTokenHash,
      },
    });
    expect(
      (items[4]!.Put as { Item: Record<string, unknown> }).Item,
    ).not.toHaveProperty("ttl");
    expect(items[5]!.Put).toMatchObject({
      ConditionExpression: "attribute_not_exists(pk)",
      Item: {
        entity: "audit",
        eventType: "config_digest_rotation_prepared",
      },
    });
  });

  it("atomically consumes the preparation only with fresh applied standby evidence", async () => {
    const { store, send } = fixture();
    send.mockResolvedValueOnce({});
    await expect(
      store.commitConfigDigestRotation(commitMutation),
    ).resolves.toEqual(receipt);

    const command = send.mock.calls[0]![0] as {
      input: { TransactItems: Array<Record<string, unknown>> };
    };
    const items = command.input.TransactItems;
    expect(items).toHaveLength(6);
    const stateUpdate = items[0]!.Update as {
      UpdateExpression: string;
      ConditionExpression: string;
    };
    expect(stateUpdate.UpdateExpression).toBe(
      "SET configDigest = :candidateDigest, updatedAt = :updatedAt",
    );
    expect(stateUpdate.UpdateExpression).not.toMatch(
      /currentLeader|fabricEpoch|timelineId/,
    );
    expect(stateUpdate.ConditionExpression).toBe(
      "currentLeader = :expectedLeader AND fabricEpoch = :expectedEpoch AND configDigest = :expectedCurrentDigest",
    );
    expect(items[1]!.ConditionCheck).toMatchObject({
      ConditionExpression: expect.stringContaining(
        "configDigest = :candidateDigest",
      ),
      ExpressionAttributeValues: expect.objectContaining({
        ":candidateDigest": candidateDigest,
        ":expectedTimelineId": preparation.expectedTimelineId,
        ":expectedSystemId": preparation.expectedUpstreamSystemId,
        ":minimumReplayWal": preparation.minimumStandbyReplayWalPosition,
      }),
    });
    expect(items[2]!.Delete).toMatchObject({
      ConditionExpression:
        "requestDigest = :requestDigest AND preparationTokenHash = :tokenHash",
    });
    expect(
      (items[2]!.Delete as { ConditionExpression: string })
        .ConditionExpression,
    ).not.toContain("expiresAt");
    expect(items[3]!.Delete).toMatchObject({
      ConditionExpression:
        "rotationId = :rotationId AND requestDigest = :requestDigest",
    });
    expect(items[4]!.Put).toMatchObject({
      ConditionExpression: "attribute_not_exists(pk)",
      Item: {
        entity: "config_digest_rotation",
        preparationTokenHash: preparation.preparationTokenHash,
      },
    });
    expect(items[5]!.Put).toMatchObject({
      ConditionExpression: "attribute_not_exists(pk)",
      Item: { entity: "audit", eventType: "config_digest_rotated" },
    });
  });

  it("atomically aborts only an expired preparation with old-digest standby evidence", async () => {
    const { store, send } = fixture();
    send.mockResolvedValueOnce({});
    await expect(
      store.abortConfigDigestRotation(abortMutation),
    ).resolves.toEqual(abortReceipt);

    const command = send.mock.calls[0]![0] as {
      input: { TransactItems: Array<Record<string, unknown>> };
    };
    const items = command.input.TransactItems;
    expect(items).toHaveLength(6);
    expect(items[0]!.ConditionCheck).toMatchObject({
      ConditionExpression:
        "currentLeader = :expectedLeader AND fabricEpoch = :expectedEpoch AND configDigest = :expectedCurrentDigest",
    });
    expect(items[1]!.ConditionCheck).toMatchObject({
      ConditionExpression: expect.stringContaining(
        "configDigest = :expectedCurrentDigest",
      ),
      ExpressionAttributeValues: expect.objectContaining({
        ":evidenceAfter": preparation.expiresAtEpoch,
        ":expectedCurrentDigest": previousDigest,
        ":expectedTimelineId": preparation.expectedTimelineId,
        ":expectedSystemId": preparation.expectedUpstreamSystemId,
      }),
    });
    expect(
      (
        items[1]!.ConditionCheck as { ConditionExpression: string }
      ).ConditionExpression,
    ).toContain("observedAtEpoch > :evidenceAfter");
    expect(items[2]!.Delete).toMatchObject({
      ConditionExpression:
        "requestDigest = :requestDigest AND preparationTokenHash = :tokenHash AND expiresAtEpoch < :nowEpoch",
    });
    expect(items[3]!.Delete).toMatchObject({
      ConditionExpression:
        "rotationId = :rotationId AND requestDigest = :requestDigest",
    });
    expect(items[4]!.Put).toMatchObject({
      ConditionExpression: "attribute_not_exists(pk)",
      Item: {
        entity: "config_digest_rotation_abort",
        decision: "config_digest_rotation_aborted",
        evidenceHost: "bigmac",
      },
    });
    expect(items[5]!.Put).toMatchObject({
      Item: {
        entity: "audit",
        eventType: "config_digest_rotation_aborted",
      },
    });
  });

  it("reads durable preparation and receipts consistently and maps conditional failures", async () => {
    const { store, send } = fixture();
    send.mockResolvedValueOnce({ Item: preparation });
    await expect(
      store.getConfigDigestRotationPreparation(preparation.rotationId),
    ).resolves.toEqual(preparation);
    send.mockResolvedValueOnce({ Item: receipt });
    await expect(
      store.getConfigDigestRotation(receipt.rotationId),
    ).resolves.toEqual(receipt);
    send.mockResolvedValueOnce({ Item: abortReceipt });
    await expect(
      store.getConfigDigestRotationAbort(abortReceipt.rotationId),
    ).resolves.toEqual(abortReceipt);

    const cancelled = new Error("conditional");
    cancelled.name = "TransactionCanceledException";
    send.mockRejectedValueOnce(cancelled);
    await expect(
      store.commitConfigDigestRotation(commitMutation),
    ).rejects.toBeInstanceOf(ConditionalWriteError);
  });
});
