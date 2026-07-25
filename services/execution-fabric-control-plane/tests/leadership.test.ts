import { generateKeyPairSync, sign } from "node:crypto";
import { describe, expect, it, vi } from "vitest";
import type { LedgerPort } from "../src/ledger.js";
import {
  LeadershipFencedError,
  LeadershipGuard,
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
  authorityMode: "synchronous" | "degraded_primary" = "synchronous",
  degradedUntil: string | null = null,
): string {
  const payload = Buffer.from(
    JSON.stringify({
      v: 2,
      cluster: "test-fabric",
      leader,
      epoch,
      receiptId,
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

function fixture(
  options: {
    leader?: string;
    epoch?: number;
    receipt?: boolean;
    persistedHold?: boolean;
    durabilityReady?: boolean;
    degraded?: boolean;
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
      options.degraded ? "degraded_primary" : "synchronous",
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
});
