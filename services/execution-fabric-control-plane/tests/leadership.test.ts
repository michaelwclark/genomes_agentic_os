import { generateKeyPairSync, sign } from "node:crypto";
import { describe, expect, it, vi } from "vitest";
import type { LedgerPort } from "../src/ledger.js";
import {
  LeadershipFencedError,
  LeadershipGuard,
  verifyConfigRotationPreparationToken,
  verifyLeadershipToken,
} from "../src/leadership.js";

const keys = generateKeyPairSync("ed25519");
const privateKey = keys.privateKey.export({ type: "pkcs8", format: "pem" }).toString();
const publicKey = keys.publicKey.export({ type: "spki", format: "pem" }).toString();
const digest = "a".repeat(64);

function token(
  leader: string,
  epoch: number,
  receiptId: string,
  issuedAt: string,
  expiresAt: string,
  authorityMode:
    | "synchronous"
    | "degraded_primary"
    | "standalone_primary" = "synchronous",
  degradedUntil: string | null = null,
  configDigest = digest,
): string {
  const payload = Buffer.from(
    JSON.stringify({
      v: 2,
      cluster: "test-fabric",
      leader,
      epoch,
      receiptId,
      configDigest,
      issuedAt,
      expiresAt,
      authorityMode,
      degradedUntil,
    }),
  ).toString("base64url");
  return `v2.${payload}.${sign(null, Buffer.from(payload), privateKey).toString(
    "base64url",
  )}`;
}

function preparationToken(
  expiresAt = "2026-07-24T20:01:00.000Z",
): string {
  const payload = Buffer.from(
    JSON.stringify({
      v: 1,
      type: "config_digest_rotation_preparation",
      clusterId: "test-fabric",
      rotationId: "00000000-0000-4000-8000-000000000001",
      expectedLeader: "bigmac",
      expectedEpoch: 2,
      expectedCurrentDigest: digest,
      candidateDigest: "b".repeat(64),
      issuedAt: "2026-07-24T20:00:00.000Z",
      expiresAt,
    }),
  ).toString("base64url");
  return `cpr1.${payload}.${sign(
    null,
    Buffer.from(payload),
    privateKey,
  ).toString("base64url")}`;
}

function fixture(
  options: {
    leader?: string;
    epoch?: number;
    receipt?: boolean;
    persistedHold?: boolean;
    durabilityReady?: boolean;
    degraded?: boolean;
    standalone?: boolean;
    standalonePolicyHost?: string;
  } = {},
) {
  let now = new Date("2026-07-24T20:00:00.000Z");
  const leader = options.leader ?? "bigmac";
  const epoch = options.epoch ?? 2;
  const statusToken = () =>
    token(
      leader,
      epoch,
      "status:fence",
      now.toISOString(),
      new Date(now.getTime() + 60_000).toISOString(),
      options.standalone
        ? "standalone_primary"
        : options.degraded
          ? "degraded_primary"
          : "synchronous",
      options.degraded
        ? new Date(now.getTime() + 3_600_000).toISOString()
        : null,
    );
  const receiptToken = token(
    "bigmac",
    epoch,
    "receipt-2",
    now.toISOString(),
    new Date(now.getTime() + 60_000).toISOString(),
  );
  const fetcher = vi.fn(
    async (input: string | URL | Request, _init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/candidates/")) {
      return new Response("{}", {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    return new Response(
      JSON.stringify({
        apiVersion: "execution-fabric-leadership/v1",
        clusterId: "test-fabric",
        currentLeader: leader,
        fabricEpoch: epoch,
        configDigest: digest,
        leadershipToken: statusToken(),
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
    },
  );
  const ledger = {
    activateLeadership: vi.fn().mockResolvedValue(undefined),
    ping: vi.fn().mockResolvedValue(undefined),
    systemSnapshot: vi.fn().mockResolvedValue({
      fabricEpoch: options.receipt ? epoch - 1 : epoch,
      leaderHostId: options.receipt ? "genomesbox" : leader,
      leaderLeaseExpiresAt: null,
      databasePolicyFingerprint: digest,
      effects: {},
      eventSequence: 0,
      leaderRecoveryHoldUntil: options.persistedHold
        ? "2026-07-24T20:00:30.000Z"
        : null,
    }),
  } as unknown as LedgerPort;
  const guard = new LeadershipGuard(
    {
      clusterId: "test-fabric",
      hostId: "bigmac",
      witnessBaseUrl: "https://witness.example.test",
      witnessToken: "witness-token",
      witnessCandidateToken: "candidate-token",
      witnessPublicKey: publicKey,
      ...(options.receipt ? { receiptPath: "/receipt.json" } : {}),
      refreshMs: 1000,
      recoveryHoldSeconds: 30,
      degradedPolicy: () => ({
        allow_degraded_primary: options.degraded === true,
        max_duration_seconds: 3600,
        allowed_task_types: ["llm.codex"],
        allowed_effect_types: ["agentic_os.alert.publish"],
        allow_scheduler: false,
      }),
      standalonePolicy: () => ({
        enabled: options.standalone === true,
        host_id: options.standalonePolicyHost ?? "bigmac",
      }),
    },
    ledger,
    () => digest,
    {
      now: () => now,
      fetch: fetcher as typeof globalThis.fetch,
      readReceipt: () =>
        JSON.stringify({
          receiptId: "receipt-2",
          currentLeader: "bigmac",
          fabricEpoch: epoch,
          clusterId: "test-fabric",
          fenceToken: receiptToken,
        }),
      replicationProbe: async () => ({
        inRecovery: false,
        timelineId: 1,
        receiveLsn: "0/100",
        replayLsn: "0/100",
        receiveWalPosition: 256,
        replayWalPosition: 256,
        replicaLagBytes: 0,
        upstreamSystemId: "7600000000000000000",
        receiverState: "not_applicable",
        lastMessageAt: now.toISOString(),
        lagMeasuredAt: now.toISOString(),
      }),
      durabilityProbe: async () => ({
        inRecovery: false,
        synchronousCommit:
          options.durabilityReady === false ? "local" : "remote_apply",
        synchronousStandbyNames:
          options.durabilityReady === false ? "" : "FIRST 1 (fabric_standby)",
        synchronousStandbyCount: options.durabilityReady === false ? 0 : 1,
        mutationDurabilityReady: options.durabilityReady !== false,
        fsync: true,
        fullPageWrites: true,
        archiveMode: "on",
        degradedPrimaryDurabilityReady:
          options.degraded === true &&
          options.durabilityReady === false,
        standalonePrimaryDurabilityReady:
          options.standalone === true &&
          options.durabilityReady === false,
        measuredAt: now.toISOString(),
      }),
    },
  );
  return {
    guard,
    ledger,
    fetcher,
    advance(seconds: number) {
      now = new Date(now.getTime() + seconds * 1000);
    },
  };
}

describe("leadership fencing", () => {
  it("verifies asymmetric tokens and rejects tampering", () => {
    const proof = token(
      "bigmac",
      2,
      "receipt-2",
      "2026-07-24T20:00:00.000Z",
      "2026-07-24T20:01:00.000Z",
    );
    expect(verifyLeadershipToken(proof, publicKey).epoch).toBe(2);
    const [version, payload, signature] = proof.split(".");
    const tamperedPayload = `${payload!.slice(0, -2)}aa`;
    expect(() =>
      verifyLeadershipToken(
        `${version}.${tamperedPayload}.${signature}`,
        publicKey,
      ),
    ).toThrow(/signature/);
  });

  it("activates the witnessed epoch and self-fences after proof expiry", async () => {
    const { guard, ledger, advance } = fixture();
    await guard.start();
    expect(ledger.activateLeadership).toHaveBeenCalledWith(
      expect.objectContaining({
        leaderHostId: "bigmac",
        fabricEpoch: 2,
        fenceDigest: expect.stringMatching(/^[a-f0-9]{64}$/),
      }),
    );
    expect(() => guard.assertMutation()).not.toThrow();
    advance(61);
    expect(() => guard.assertMutation()).toThrow(/expired/);
    guard.stop();
  });

  it("uses the candidate credential only for measured PostgreSQL reports", async () => {
    const { guard, fetcher } = fixture();
    await guard.start();
    expect(fetcher).toHaveBeenNthCalledWith(
      1,
      expect.stringContaining("/candidates/bigmac"),
      expect.objectContaining({
        method: "PUT",
        headers: expect.objectContaining({
          authorization: "Bearer candidate-token",
        }),
      }),
    );
    const candidateRequest = fetcher.mock.calls[0]![1] as RequestInit;
    expect(JSON.parse(String(candidateRequest.body))).toMatchObject({
      healthy: true,
      inRecovery: false,
      timelineId: 1,
      receiveLsn: "0/100",
      replayLsn: "0/100",
      replicaLagBytes: 0,
    });
    expect(fetcher).toHaveBeenNthCalledWith(
      2,
      expect.stringContaining("/leadership/status"),
      expect.objectContaining({
        headers: expect.objectContaining({
          authorization: "Bearer witness-token",
        }),
      }),
    );
    guard.stop();
  });

  it("fails closed when witness leadership moved to the other host", async () => {
    const { guard } = fixture({ leader: "genomesbox" });
    await expect(guard.start()).rejects.toBeInstanceOf(LeadershipFencedError);
    expect(() => guard.assertMutation()).toThrow(/witness does not name/);
  });

  it("fences every mutation immediately when local policy outgrows its signed proof", async () => {
    const { guard } = fixture();
    await guard.start();
    expect(() => guard.assertMutation()).not.toThrow();
    (guard as unknown as { configDigest: () => string }).configDigest = () =>
      "b".repeat(64);
    expect(() => guard.assertMutation()).toThrow(
      /local policy digest differs from the signed witness proof/,
    );
    guard.stop();
  });

  it("authorizes only the exact signed and unexpired witness policy preparation", async () => {
    const { guard } = fixture();
    await guard.start();
    const preparation = preparationToken();
    expect(
      verifyConfigRotationPreparationToken(preparation, publicKey),
    ).toMatchObject({
      rotationId: "00000000-0000-4000-8000-000000000001",
      expectedLeader: "bigmac",
      expectedEpoch: 2,
    });
    expect(
      guard.authorizePolicyRotation({
        rotationId: "00000000-0000-4000-8000-000000000001",
        preparationToken: preparation,
        expectedCurrentDigest: digest,
        candidateDigest: "b".repeat(64),
      }),
    ).toMatchObject({ candidateDigest: "b".repeat(64) });
    expect(() =>
      guard.authorizePolicyRotation({
        rotationId: "00000000-0000-4000-8000-000000000002",
        preparationToken: preparation,
        expectedCurrentDigest: digest,
        candidateDigest: "b".repeat(64),
      }),
    ).toThrow(/not bound/);
    expect(() =>
      guard.authorizePolicyRotation({
        rotationId: "00000000-0000-4000-8000-000000000001",
        preparationToken: preparationToken(
          "2026-07-24T19:59:59.000Z",
        ),
        expectedCurrentDigest: digest,
        candidateDigest: "b".repeat(64),
      }),
    ).toThrow(/expired/);
    guard.stop();
  });

  it("allows a prepared policy reload through intentional drift only on an opted-in standalone primary", async () => {
    const { guard } = fixture({ standalone: true, durabilityReady: false });
    await guard.start();
    (guard as unknown as { configDigest: () => string }).configDigest = () =>
      "b".repeat(64);

    expect(() => guard.assertMutation()).toThrow(
      /local policy digest differs from the signed witness proof/,
    );
    expect(
      guard.authorizePolicyRotation({
        rotationId: "00000000-0000-4000-8000-000000000001",
        preparationToken: preparationToken(),
        expectedCurrentDigest: digest,
        candidateDigest: "b".repeat(64),
      }),
    ).toMatchObject({ candidateDigest: "b".repeat(64) });
    guard.stop();
  });

  it("keeps intentional policy drift fenced outside an opted-in standalone primary", async () => {
    const { guard } = fixture();
    await guard.start();
    (guard as unknown as { configDigest: () => string }).configDigest = () =>
      "b".repeat(64);

    expect(() =>
      guard.authorizePolicyRotation({
        rotationId: "00000000-0000-4000-8000-000000000001",
        preparationToken: preparationToken(),
        expectedCurrentDigest: digest,
        candidateDigest: "b".repeat(64),
      }),
    ).toThrow(/only by an opted-in standalone primary/);
    guard.stop();
  });

  it("validates transfer receipt and enforces recovery hold", async () => {
    const { guard, advance } = fixture({ receipt: true });
    await guard.start();
    expect(() => guard.assertMutation()).toThrow(/recovery hold/);
    advance(31);
    expect(() => guard.assertMutation()).not.toThrow();
    guard.stop();
  });

  it("rejects a promotion receipt bound to another epoch", async () => {
    const { guard } = fixture({ receipt: true, epoch: 3 });
    // The receipt helper is signed for the same epoch. Corrupt its digest to
    // prove the signed envelope, not JSON fields, is authoritative.
    (guard as unknown as { readReceipt: () => string }).readReceipt = () =>
      JSON.stringify({
        receiptId: "receipt-2",
        currentLeader: "bigmac",
        fabricEpoch: 3,
        clusterId: "test-fabric",
        fenceToken: token(
          "bigmac",
          2,
          "receipt-2",
          "2026-07-24T20:00:00.000Z",
          "2026-07-24T20:01:00.000Z",
        ),
      });
    await expect(guard.start()).rejects.toThrow(/does not match/);
  });

  it("preserves a PostgreSQL recovery hold across process restart", async () => {
    const { guard, advance } = fixture({ persistedHold: true });
    await guard.start();
    expect(() => guard.assertMutation()).toThrow(/recovery hold/);
    advance(31);
    expect(() => guard.assertMutation()).not.toThrow();
    guard.stop();
  });

  it("keeps the mutation plane fenced without remote-apply durability", async () => {
    const { guard } = fixture({ durabilityReady: false });
    await guard.start();
    expect(() => guard.assertMutation()).toThrow(
      /PostgreSQL mutation durability is not ready/,
    );
    expect(guard.snapshot()).toMatchObject({
      state: "fenced",
      durability: {
        mutationDurabilityReady: false,
      },
    });
    guard.stop();
  });

  it("allows only bounded policy-approved mutations on a signed degraded primary", async () => {
    const { guard } = fixture({ durabilityReady: false, degraded: true });
    await guard.start();
    expect(() => guard.assertTaskMutation("llm.codex")).not.toThrow();
    expect(() => guard.assertTaskMutation("production.deploy")).toThrow(
      /fenced during degraded-primary/,
    );
    expect(() =>
      guard.assertEffectMutation(["agentic_os.alert.publish"]),
    ).not.toThrow();
    expect(() => guard.assertSchedulerMutation()).toThrow(
      /scheduler is fenced/,
    );
    expect(guard.snapshot()).toMatchObject({
      state: "active",
      authorityMode: "degraded_primary",
    });
    guard.stop();
  });

  it("allows normal task, effect, and scheduler mutations on an opted-in standalone primary", async () => {
    const { guard } = fixture({
      durabilityReady: false,
      standalone: true,
    });
    await guard.start();
    expect(() => guard.assertTaskMutation("production.deploy")).not.toThrow();
    expect(() =>
      guard.assertEffectMutation(["provider.effect"]),
    ).not.toThrow();
    expect(() => guard.assertSchedulerMutation()).not.toThrow();
    expect(guard.snapshot()).toMatchObject({
      state: "active",
      authorityMode: "standalone_primary",
      durability: { standalonePrimaryDurabilityReady: true },
    });
    guard.stop();
  });

  it("fences standalone authority when canonical opt-in names another host", async () => {
    const { guard } = fixture({
      durabilityReady: false,
      standalone: true,
      standalonePolicyHost: "genomesbox",
    });
    await guard.start();
    expect(() => guard.assertMutation()).toThrow(/exact canonical policy opt-in/);
    guard.stop();
  });
});
