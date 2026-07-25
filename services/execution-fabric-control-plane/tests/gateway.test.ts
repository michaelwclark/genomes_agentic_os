import { generateKeyPairSync, sign } from "node:crypto";
import { describe, expect, it, vi } from "vitest";
import { LeaderResolver, type GatewayConfig } from "../src/gateway.js";

const keys = generateKeyPairSync("ed25519");
const publicKey = keys.publicKey.export({ type: "spki", format: "pem" }).toString();
const privateKey = keys.privateKey.export({ type: "pkcs8", format: "pem" }).toString();

function token(leader: string, epoch: number, expiresAt: string): string {
  const payload = Buffer.from(
    JSON.stringify({
      v: 2,
      cluster: "test-fabric",
      leader,
      epoch,
      receiptId: "status:fence",
      issuedAt: "2026-07-24T20:00:00.000Z",
      expiresAt,
    }),
  ).toString("base64url");
  return `v2.${payload}.${sign(null, Buffer.from(payload), privateKey).toString(
    "base64url",
  )}`;
}

const config: GatewayConfig = {
  host: "127.0.0.1",
  port: 3181,
  clusterId: "test-fabric",
  witnessBaseUrl: "https://witness.example.test",
  witnessToken: "token",
  witnessPublicKey: publicKey,
  leaderEndpoints: {
    genomesbox: "http://100.64.0.10:3180",
    bigmac: "http://100.64.0.11:3180",
  },
};

describe("stable worker gateway", () => {
  it("routes only from an asymmetric witness proof and follows promotion", async () => {
    let leader = "genomesbox";
    let epoch = 1;
    const fetcher = vi.fn(async () =>
      new Response(
        JSON.stringify({
          clusterId: "test-fabric",
          currentLeader: leader,
          fabricEpoch: epoch,
          leadershipToken: token(
            leader,
            epoch,
            "2026-07-24T20:01:00.000Z",
          ),
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    const resolver = new LeaderResolver(
      config,
      fetcher as typeof globalThis.fetch,
      () => new Date("2026-07-24T20:00:10.000Z"),
    );
    expect((await resolver.resolve()).endpoint).toContain("100.64.0.10");
    leader = "bigmac";
    epoch = 2;
    expect((await resolver.resolve()).endpoint).toContain("100.64.0.11");
  });

  it("uses a still-valid signed cache during witness partition, then fences", async () => {
    let now = new Date("2026-07-24T20:00:10.000Z");
    let fail = false;
    const fetcher = vi.fn(async () => {
      if (fail) throw new Error("partitioned");
      return new Response(
        JSON.stringify({
          clusterId: "test-fabric",
          currentLeader: "genomesbox",
          fabricEpoch: 1,
          leadershipToken: token(
            "genomesbox",
            1,
            "2026-07-24T20:00:30.000Z",
          ),
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    });
    const resolver = new LeaderResolver(
      config,
      fetcher as typeof globalThis.fetch,
      () => now,
    );
    await resolver.resolve();
    fail = true;
    expect((await resolver.resolve()).leader).toBe("genomesbox");
    now = new Date("2026-07-24T20:00:31.000Z");
    await expect(resolver.resolve()).rejects.toThrow(/partitioned/);
  });

  it("rejects status whose signed leader differs from the JSON leader", async () => {
    const fetcher = vi.fn(async () =>
      new Response(
        JSON.stringify({
          clusterId: "test-fabric",
          currentLeader: "bigmac",
          fabricEpoch: 2,
          leadershipToken: token(
            "genomesbox",
            2,
            "2026-07-24T20:01:00.000Z",
          ),
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    const resolver = new LeaderResolver(
      config,
      fetcher as typeof globalThis.fetch,
      () => new Date("2026-07-24T20:00:10.000Z"),
    );
    await expect(resolver.resolve()).rejects.toThrow(/do not match/);
  });
});
