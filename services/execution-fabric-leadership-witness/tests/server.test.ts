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
  witnessHostId: "witness-1",
  clusterId: "test-fabric",
  store: "sqlite",
  stateFile: "/tmp/test-witness.sqlite3",
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
  signingPrivateKey: signingKeys.privateKey
    .export({
      type: "pkcs8",
      format: "pem",
    })
    .toString(),
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

  it("publishes the config-digest prepare/commit contract", async () => {
    const server = await fixture();
    const response = await server.inject({
      method: "GET",
      url: "/openapi.json",
    });
    expect(response.statusCode).toBe(200);
    const document = response.json();
    expect(
      document.paths[
        "/api/v1/admin/leadership/config-digest-rotations/prepare"
      ].post,
    ).toMatchObject({
      operationId: "prepareLeadershipConfigDigestRotation",
      requestBody: {
        required: true,
        content: {
          "application/json": {
            schema: {
              $ref: "#/components/schemas/ConfigDigestRotationRequest",
            },
          },
        },
      },
    });
    expect(
      document.paths[
        "/api/v1/admin/leadership/config-digest-rotations/commit"
      ].post.requestBody.content["application/json"].schema.$ref,
    ).toBe("#/components/schemas/ConfigDigestRotationCommitRequest");
    expect(
      document.paths[
        "/api/v1/admin/leadership/config-digest-rotations/abort"
      ].post.requestBody.content["application/json"].schema.$ref,
    ).toBe("#/components/schemas/ConfigDigestRotationAbortRequest");
    expect(
      document.paths[
        "/api/v1/admin/leadership/config-digest-rotations/{rotationId}/abort"
      ].get.responses["200"].content["application/json"].schema.$ref,
    ).toBe("#/components/schemas/ConfigDigestRotationAbortReceipt");
    expect(
      document.paths[
        "/api/v1/admin/leadership/config-digest-rotations/{rotationId}"
      ].get.responses["200"].content["application/json"].schema.$ref,
    ).toBe("#/components/schemas/ConfigDigestRotationReceipt");
    expect(
      document.components.schemas.ConfigDigestRotationRequest.required,
    ).toEqual([
      "rotationId",
      "expectedLeader",
      "expectedEpoch",
      "expectedCurrentDigest",
      "candidateDigest",
    ]);
    expect(
      document.components.schemas.CandidateUpdate.properties,
    ).toHaveProperty("policyCandidateDigest");
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

  it("exposes admin-only prepare/commit with discovery and durable receipt readback", async () => {
    const server = await fixture();
    const observedAt = new Date().toISOString();
    const report = (
      candidate: "genomesbox" | "bigmac",
      configDigest: string,
      policyCandidateDigest?: string,
    ) => ({
      healthy: true,
      inRecovery: candidate !== "genomesbox",
      timelineId: 1,
      receiveLsn: "0/100",
      replayLsn: "0/100",
      receiveWalPosition: 1_000,
      replayWalPosition: 1_000,
      replicaLagBytes: 0,
      lagMeasuredAt: observedAt,
      upstreamSystemId: "7600000000000000000",
      receiverState:
        candidate === "genomesbox" ? "not_applicable" : "streaming",
      lastMessageAt: observedAt,
      configDigest,
      ...(policyCandidateDigest ? { policyCandidateDigest } : {}),
      observedAt,
    });
    const publish = async (
      candidate: "genomesbox" | "bigmac",
      configDigest: string,
      policyCandidateDigest?: string,
    ) =>
      server.inject({
        method: "PUT",
        url: `/api/v1/admin/leadership/candidates/${candidate}`,
        headers: {
          authorization: `Bearer ${config.candidateTokens[candidate]}`,
        },
        payload: report(candidate, configDigest, policyCandidateDigest),
      });

    expect(
      (await publish("genomesbox", config.initialConfigDigest)).statusCode,
    ).toBe(200);
    const candidateDigest = "b".repeat(64);
    expect(
      (
        await publish(
          "genomesbox",
          config.initialConfigDigest,
          candidateDigest,
        )
      ).statusCode,
    ).toBe(200);
    expect(
      (
        await publish("bigmac", config.initialConfigDigest, candidateDigest)
      ).statusCode,
    ).toBe(200);

    const rotationId = "00000000-0000-4000-8000-000000000201";
    const payload = {
      rotationId,
      expectedLeader: "genomesbox",
      expectedEpoch: 1,
      expectedCurrentDigest: config.initialConfigDigest,
      candidateDigest,
    };
    const unauthorized = await server.inject({
      method: "POST",
      url: "/api/v1/admin/leadership/config-digest-rotations/prepare",
      headers: { authorization: `Bearer ${config.readerToken}` },
      payload,
    });
    expect(unauthorized.statusCode).toBe(401);
    const invalid = await server.inject({
      method: "POST",
      url: "/api/v1/admin/leadership/config-digest-rotations/prepare",
      headers: { authorization: `Bearer ${config.adminToken}` },
      payload: {
        ...payload,
        candidateDigest: config.initialConfigDigest,
      },
    });
    expect(invalid.statusCode).toBe(400);

    const removedUnsafeEndpoint = await server.inject({
      method: "POST",
      url: "/api/v1/admin/leadership/config-digest-rotations",
      headers: { authorization: `Bearer ${config.adminToken}` },
      payload,
    });
    expect(removedUnsafeEndpoint.statusCode).toBe(404);

    const prepared = await server.inject({
      method: "POST",
      url: "/api/v1/admin/leadership/config-digest-rotations/prepare",
      headers: { authorization: `Bearer ${config.adminToken}` },
      payload,
    });
    expect(prepared.statusCode).toBe(200);
    expect(prepared.json()).toMatchObject({
      rotationId,
      decision: "config_digest_rotation_prepared",
      expectedLeader: "genomesbox",
      expectedEpoch: 1,
      candidateDigest,
    });
    const prepareReplay = await server.inject({
      method: "POST",
      url: "/api/v1/admin/leadership/config-digest-rotations/prepare",
      headers: { authorization: `Bearer ${config.adminToken}` },
      payload,
    });
    expect(prepareReplay.statusCode).toBe(200);
    expect(prepareReplay.json()).toEqual(prepared.json());

    const preparationReadback = await server.inject({
      method: "GET",
      url: `/api/v1/admin/leadership/config-digest-rotations/${rotationId}/preparation`,
      headers: { authorization: `Bearer ${config.adminToken}` },
    });
    expect(preparationReadback.statusCode).toBe(200);
    expect(preparationReadback.json()).toEqual(prepared.json());
    const discover = await server.inject({
      method: "GET",
      url: "/api/v1/admin/leadership/status",
      headers: { authorization: `Bearer ${config.readerToken}` },
    });
    expect(discover.json().pendingConfigDigestRotations).toEqual([
      { ...prepared.json(), expired: false },
    ]);

    const commitPayload = {
      rotationId,
      preparationToken: prepared.json().preparationToken,
    };
    const prematureCommit = await server.inject({
      method: "POST",
      url: "/api/v1/admin/leadership/config-digest-rotations/commit",
      headers: { authorization: `Bearer ${config.adminToken}` },
      payload: commitPayload,
    });
    expect(prematureCommit.statusCode).toBe(409);
    expect(
      (await publish("bigmac", candidateDigest)).statusCode,
    ).toBe(200);
    const rotated = await server.inject({
      method: "POST",
      url: "/api/v1/admin/leadership/config-digest-rotations/commit",
      headers: { authorization: `Bearer ${config.adminToken}` },
      payload: commitPayload,
    });
    expect(rotated.statusCode).toBe(200);
    expect(rotated.json()).toMatchObject({
      rotationId,
      currentLeader: "genomesbox",
      fabricEpoch: 1,
      configDigest: candidateDigest,
      preparationTokenHash: prepared.json().preparationTokenHash,
    });
    const commitReplay = await server.inject({
      method: "POST",
      url: "/api/v1/admin/leadership/config-digest-rotations/commit",
      headers: { authorization: `Bearer ${config.adminToken}` },
      payload: commitPayload,
    });
    expect(commitReplay.statusCode).toBe(200);
    expect(commitReplay.json()).toEqual(rotated.json());

    const readback = await server.inject({
      method: "GET",
      url: `/api/v1/admin/leadership/config-digest-rotations/${rotationId}`,
      headers: { authorization: `Bearer ${config.adminToken}` },
    });
    expect(readback.statusCode).toBe(200);
    expect(readback.json()).toEqual(rotated.json());
    const consumedPreparation = await server.inject({
      method: "GET",
      url: `/api/v1/admin/leadership/config-digest-rotations/${rotationId}/preparation`,
      headers: { authorization: `Bearer ${config.adminToken}` },
    });
    expect(consumedPreparation.statusCode).toBe(404);
    const missing = await server.inject({
      method: "GET",
      url: "/api/v1/admin/leadership/config-digest-rotations/00000000-0000-4000-8000-000000000999",
      headers: { authorization: `Bearer ${config.adminToken}` },
    });
    expect(missing.statusCode).toBe(404);
    await server.close();
  });
});
