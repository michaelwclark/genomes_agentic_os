import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { generateKeyPairSync } from "node:crypto";
import { describe, expect, it } from "vitest";
import { loadConfig } from "../src/config.js";

function environment() {
  const directory = mkdtempSync(join(tmpdir(), "witness-config-"));
  const admin = join(directory, "admin");
  const reader = join(directory, "reader");
  const candidates = join(directory, "candidates.json");
  const signingKey = join(directory, "signing-key.pem");
  writeFileSync(admin, "a".repeat(32), { mode: 0o600 });
  writeFileSync(reader, "b".repeat(32), { mode: 0o600 });
  writeFileSync(
    candidates,
    JSON.stringify({
      genomesbox: "c".repeat(32),
      bigmac: "d".repeat(32),
    }),
    { mode: 0o600 },
  );
  const { privateKey } = generateKeyPairSync("ed25519");
  writeFileSync(
    signingKey,
    privateKey.export({ type: "pkcs8", format: "pem" }),
    { mode: 0o600 },
  );
  return {
    WITNESS_TAILSCALE_IP: "100.100.100.100",
    WITNESS_HOST_ID: "witness-1",
    WITNESS_CLUSTER_ID: "test-fabric",
    WITNESS_INITIAL_LEADER: "genomesbox",
    WITNESS_INITIAL_TIMELINE_ID: "1",
    WITNESS_INITIAL_CONFIG_DIGEST: "c".repeat(64),
    WITNESS_ADMIN_TOKEN_FILE: admin,
    WITNESS_READER_TOKEN_FILE: reader,
    WITNESS_CANDIDATE_TOKENS_FILE: candidates,
    WITNESS_SIGNING_PRIVATE_KEY_FILE: signingKey,
  };
}

describe("witness config", () => {
  it("requires file-backed, distinct secrets and a pinned config digest", () => {
    const config = loadConfig(environment());
    expect(config.port).toBe(3195);
    expect(config.host).toBe("100.100.100.100");
    expect(config.bootstrapOnce).toBe(false);
    expect(config.initialConfigDigest).toHaveLength(64);

    const valid = environment();
    expect(() =>
      loadConfig({
        ...valid,
        WITNESS_SIGNING_PRIVATE_KEY_FILE: valid.WITNESS_ADMIN_TOKEN_FILE,
      }),
    ).toThrow(/PEM PKCS8/);
    expect(() =>
      loadConfig({
        ...valid,
        WITNESS_INITIAL_CONFIG_DIGEST: "not-a-digest",
      }),
    ).toThrow();

    expect(() =>
      loadConfig({
        ...environment(),
        WITNESS_HOST_ID: "genomesbox",
      }),
    ).toThrow(/independent/);

    expect(
      loadConfig({
        ...environment(),
        WITNESS_BOOTSTRAP_ONCE: "true",
        WITNESS_PROCESS_LEASE_SECONDS: "45",
      }),
    ).toMatchObject({ bootstrapOnce: true, processLeaseSeconds: 45 });
  });
});
