import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { generateKeyPairSync } from "node:crypto";
import { describe, expect, it } from "vitest";
import { loadConfig } from "../src/config.js";

describe("loadConfig", () => {
  function environment() {
    const directory = mkdtempSync(join(tmpdir(), "fabric-config-"));
    const apiTokenPath = join(directory, "api-token");
    const submitTokenPath = join(directory, "submit-token");
    const workerCredentialsPath = join(directory, "worker-credentials.json");
    const adminTokenPath = join(directory, "admin-token");
    const reliabilityTokensPath = join(directory, "reliability-tokens.json");
    const effectConsumersPath = join(directory, "effect-consumers.json");
    const alarmDispatchersPath = join(directory, "alarm-dispatchers.json");
    const witnessTokenPath = join(directory, "witness-token");
    const witnessCandidateTokenPath = join(directory, "witness-candidate-token");
    const witnessPublicKeyPath = join(directory, "witness-public.pem");
    const artifactAccessKeyPath = join(directory, "artifact-access-key");
    const artifactSecretKeyPath = join(directory, "artifact-secret-key");
    writeFileSync(apiTokenPath, "a".repeat(32), { mode: 0o600 });
    writeFileSync(submitTokenPath, "f".repeat(32), { mode: 0o600 });
    writeFileSync(
      workerCredentialsPath,
      JSON.stringify({
        "host-a.code.worker-a": {
          token: "g".repeat(32),
          workerId: "worker-a",
          hostId: "host-a",
          poolId: "code_workers",
          queues: ["code"],
          capabilities: ["test.run"],
          maxConcurrency: 1,
        },
      }),
      { mode: 0o600 },
    );
    writeFileSync(adminTokenPath, "b".repeat(32), { mode: 0o600 });
    writeFileSync(
      reliabilityTokensPath,
      JSON.stringify({
        "team-pr-runner": "i".repeat(32),
        "losmon-mongo-outbox": "j".repeat(32),
      }),
      { mode: 0o600 },
    );
    writeFileSync(
      effectConsumersPath,
      JSON.stringify({
        "jira-projector": {
          token: "k".repeat(32),
          source: "jira-projector",
          effectTypes: ["jira.transition"],
        },
      }),
      { mode: 0o600 },
    );
    writeFileSync(
      alarmDispatchersPath,
      JSON.stringify({
        "bigmac-agentic-os-notifier": {
          token: "l".repeat(32),
          source: "agentic-os-notify",
        },
      }),
      { mode: 0o600 },
    );
    writeFileSync(witnessTokenPath, "c".repeat(32), { mode: 0o600 });
    writeFileSync(witnessCandidateTokenPath, "h".repeat(32), { mode: 0o600 });
    writeFileSync(artifactAccessKeyPath, "d".repeat(32), { mode: 0o600 });
    writeFileSync(artifactSecretKeyPath, "e".repeat(40), { mode: 0o600 });
    const { publicKey } = generateKeyPairSync("ed25519");
    writeFileSync(
      witnessPublicKeyPath,
      publicKey.export({ type: "spki", format: "pem" }),
      { mode: 0o644 },
    );
    return {
      FABRIC_HOST_ID: "host-a",
      FABRIC_DATABASE_URL: "postgresql://localhost/fabric",
      FABRIC_VALKEY_URL: "redis://localhost:6379",
      FABRIC_POLICY_CONFIG_FILE: "/etc/agentic-os/execution-fabric.yml",
      FABRIC_POLICY_SCHEMA_FILE:
        "/etc/agentic-os/schemas/execution-fabric.schema.json",
      FABRIC_API_TOKEN_FILE: apiTokenPath,
      FABRIC_SUBMIT_TOKEN_FILE: submitTokenPath,
      FABRIC_WORKER_BOOTSTRAP_CREDENTIALS_FILE: workerCredentialsPath,
      FABRIC_ADMIN_TOKEN_FILE: adminTokenPath,
      FABRIC_RELIABILITY_SOURCE_TOKENS_FILE: reliabilityTokensPath,
      FABRIC_EFFECT_CONSUMER_CREDENTIALS_FILE: effectConsumersPath,
      FABRIC_ALARM_DISPATCHER_CREDENTIALS_FILE: alarmDispatchersPath,
      FABRIC_ARTIFACT_ACCESS_KEY_FILE: artifactAccessKeyPath,
      FABRIC_ARTIFACT_SECRET_KEY_FILE: artifactSecretKeyPath,
      FABRIC_CLUSTER_ID: "test-fabric",
      FABRIC_LEADERSHIP_API_BASE: "https://witness.example.test",
      FABRIC_LEADERSHIP_TOKEN_FILE: witnessTokenPath,
      FABRIC_LEADERSHIP_CANDIDATE_TOKEN_FILE: witnessCandidateTokenPath,
      FABRIC_LEADERSHIP_PUBLIC_KEY_FILE: witnessPublicKeyPath,
    };
  }

  it("loads required values with stable defaults", () => {
    const config = loadConfig(environment());
    expect(config.hostId).toBe("host-a");
    expect(config.port).toBe(3180);
    expect(config.queuePrefix).toBe("agentic-os:fabric");
    expect(config.longPollMs).toBe(15000);
    expect(config.artifactStore.bucket).toBe("execution-fabric-artifacts");
    expect(config.artifactStore.accessKeyId).toBe("d".repeat(32));
  });

  it("rejects an unsafe queue prefix", () => {
    expect(() =>
      loadConfig({
        ...environment(),
        FABRIC_QUEUE_PREFIX: "contains spaces",
      }),
    ).toThrow();
  });

  it("fails closed for missing, weak, or shared credentials", () => {
    const valid = environment();
    expect(() =>
      loadConfig({ ...valid, FABRIC_API_TOKEN_FILE: "/does/not/exist" }),
    ).toThrow();

    const directory = mkdtempSync(join(tmpdir(), "fabric-config-weak-"));
    const weak = join(directory, "weak");
    writeFileSync(weak, "too-short", { mode: 0o600 });
    expect(() => loadConfig({ ...valid, FABRIC_API_TOKEN_FILE: weak })).toThrow(
      /at least 32/,
    );
    expect(() =>
      loadConfig({
        ...valid,
        FABRIC_ADMIN_TOKEN_FILE: valid.FABRIC_API_TOKEN_FILE,
      }),
    ).toThrow(/must all differ/);

    writeFileSync(
      valid.FABRIC_EFFECT_CONSUMER_CREDENTIALS_FILE,
      JSON.stringify({
        "jira-projector": {
          token: "a".repeat(32),
          source: "jira-projector",
          effectTypes: ["jira.transition"],
        },
      }),
      { mode: 0o600 },
    );
    expect(() => loadConfig(valid)).toThrow(
      /all static, source, consumer, and dispatcher tokens must differ/,
    );
  });
});
