import { describe, expect, it } from "vitest";
import { generateKeyPairSync } from "node:crypto";
import type { WitnessConfig } from "../src/config.js";
import { buildServer } from "../src/server.js";
import { InMemoryWitnessStore } from "../src/store.js";
import { LeadershipWitness } from "../src/witness.js";

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
  },
  adminToken: "admin-token-0000000000000000000000",
  signingPrivateKey: signingKeys.privateKey.export({
    type: "pkcs8",
    format: "pem",
  }).toString(),
  logLevel: "silent",
  region: "us-east-1",
};

async function fixture() {
  const witness = new LeadershipWitness(config, new InMemoryWitnessStore());
  await witness.initialize();
  return buildServer(config, witness);
}

describe("leadership HTTP contract", () => {
  it("keeps liveness and readiness unauthenticated", async () => {
    const server = await fixture();
    expect(
      (await server.inject({ method: "GET", url: "/healthz" })).statusCode,
    ).toBe(200);
    expect(
      (await server.inject({ method: "GET", url: "/readyz" })).statusCode,
    ).toBe(200);
    await server.close();
  });

  it("fails closed for every leadership API route", async () => {
    const server = await fixture();
    const response = await server.inject({
      method: "GET",
      url: "/api/v1/admin/leadership/status",
    });
    expect(response.statusCode).toBe(401);
    expect(response.headers["www-authenticate"]).toContain('scope="reader"');
    await server.close();
  });

  it("accepts the exact admin bearer and validates candidate reports", async () => {
    const server = await fixture();
    const status = await server.inject({
      method: "GET",
      url: "/api/v1/admin/leadership/status",
      headers: { authorization: `Bearer ${config.readerToken}` },
    });
    expect(status.statusCode).toBe(200);
    expect(status.json().fabricEpoch).toBe(1);

    const invalid = await server.inject({
      method: "PUT",
      url: "/api/v1/admin/leadership/candidates/bigmac",
      headers: {
        authorization: `Bearer ${config.candidateTokens.bigmac}`,
      },
      payload: {
        healthy: true,
        replicaLagBytes: -1,
        configDigest: config.initialConfigDigest,
      },
    });
    expect(invalid.statusCode).toBe(400);
    await server.close();
  });

  it("does not let readers, admins, or another host impersonate a candidate", async () => {
    const server = await fixture();
    for (const token of [
      config.readerToken,
      config.adminToken,
      config.candidateTokens.genomesbox,
    ]) {
      const response = await server.inject({
        method: "PUT",
        url: "/api/v1/admin/leadership/candidates/bigmac",
        headers: { authorization: `Bearer ${token}` },
        payload: {},
      });
      expect(response.statusCode).toBe(401);
      expect(response.headers["www-authenticate"]).toContain(
        'scope="candidate:bigmac"',
      );
    }
    const promotedWithReader = await server.inject({
      method: "POST",
      url: "/api/v1/admin/leadership/promote",
      headers: { authorization: `Bearer ${config.readerToken}` },
      payload: {},
    });
    expect(promotedWithReader.statusCode).toBe(401);
    await server.close();
  });
});
