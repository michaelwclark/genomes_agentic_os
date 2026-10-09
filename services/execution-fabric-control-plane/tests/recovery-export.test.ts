import { createHash } from "node:crypto";
import { chmod, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { exportRecoveryVersions, listVersions, type ExportOptions } from "../src/recovery-export.js";
import { executeRecoveryExport } from "../src/recovery-export-main.js";
const native = vi.hoisted(() => ({ client: undefined as any, queries: [] as string[], role: "readonly-recovery",
  elevated: false, lsn: "0/ABCD", connectFailure: false, released: false, poolEnded: false, destroyed: false,
  systemId: "7432345656789123456", database: "execution_fabric", databaseOid: "16384", majorVersion: 17 }));
vi.mock("@aws-sdk/client-s3", async importOriginal => ({
  ...await importOriginal<typeof import("@aws-sdk/client-s3")>(),
  S3Client: class {
    send(command: any): Promise<any> { return native.client.send(command); }
    destroy(): void { native.destroyed = true; }
  },
}));
vi.mock("pg", () => ({ default: { Pool: class {
  async connect(): Promise<any> {
    if (native.connectFailure) throw new Error("fixture connection failure");
    return {
      query: async (text: string): Promise<any> => {
        native.queries.push(text);
        if (text.includes("current_user AS role")) return { rows: [{ role: native.role }] };
        if (text.includes("rolsuper")) return { rows: [{ elevated: native.elevated }] };
        if (text.includes("FROM pg_control_system()")) return { rows: [{ systemId: native.systemId,
          database: native.database, databaseOid: native.databaseOid, serverVersionNum: native.majorVersion * 10000 + 6 }] };
        if (text.includes("pg_current_wal_lsn")) return { rows: [{ lsn: native.lsn }] };
        if (text.includes("FROM fabric_artifacts")) return { rows: [{ id: "original-artifact", task_id: "original-task",
          attempt_id: "attempt", object_key: "objects/key", storage_uri: "s3://rubicon-artifacts/objects/key",
          sha256: createHash("sha256").update("latest").digest("hex"), size_bytes: "6" }] };
        return { rows: [] };
      },
      release: () => { native.released = true; },
    };
  }
  async end(): Promise<void> { native.poolEnded = true; }
} } }));
const hash = (value: string) => createHash("sha256").update(value).digest("hex");
const roots: string[] = [];
afterEach(async () => {
  vi.unstubAllEnvs();
  for (const root of roots.splice(0)) await rm(root, { recursive: true, force: true });
});
async function options(): Promise<ExportOptions> {
  const root = await mkdtemp(join(tmpdir(), "rubicon-readonly-export-"));
  roots.push(root);
  return { bucket: "rubicon-artifacts", output: join(root, "new-export"), ownerBinding: "original-bucket-owner",
    ledgerArtifacts: [{ artifactId: "original-artifact", objectKey: "objects/key", sha256: hash("latest"),
      sizeBytes: 6, ownerBinding: "original-task:attempt" }], maxVersions: 100, maxBytes: 10000 };
}
function fixture({ changed = false, wrongPayload = false, repeated = false } = {}) {
  let listing = 0;
  const calls: string[] = [];
  return { calls, send: async (command: any): Promise<any> => {
    calls.push(command.constructor.name);
    if (command.constructor.name === "GetBucketVersioningCommand") return { Status: "Enabled" };
    if (command.constructor.name === "GetObjectTaggingCommand") return { TagSet: [{ Key: "owner", Value: "original-owner" }] };
    if (command.constructor.name === "ListObjectVersionsCommand") {
      listing++;
      if (repeated) return { IsTruncated: true, NextKeyMarker: "same", NextVersionIdMarker: "same" };
      if (!command.input.KeyMarker) return {
        Versions: [{ Key: "objects/key", VersionId: "v-latest", IsLatest: true, Size: 6 }],
        IsTruncated: true, NextKeyMarker: "objects/key", NextVersionIdMarker: "v-latest",
      };
      return { Versions: [{ Key: "objects/key", VersionId: "v-old", Size: changed && listing > 2 ? 4 : 3 }],
        DeleteMarkers: [{ Key: "deleted/key", VersionId: "v-delete", IsLatest: true }], IsTruncated: false };
    }
    if (command.constructor.name === "GetObjectCommand") {
      const content = command.input.VersionId === "v-latest" ? (wrongPayload ? "broken" : "latest") : "old";
      return { VersionId: command.input.VersionId, ContentLength: content.length,
        Metadata: { original: "preserved" }, ContentType: "application/octet-stream",
        Body: (async function* () { yield Buffer.from(content); })() };
    }
    throw new Error("fixture refuses object mutation");
  } };
}
describe("read-only all-version recovery export", () => {
  it("captures old/latest payload versions and delete-marker metadata with original ledger bindings", async () => {
    const config = await options();
    const client = fixture();
    const result = await exportRecoveryVersions(client as any, config);
    expect(result.status).toBe("exported_bytes_verified");
    expect(result.dataVersions).toBe(2);
    expect(result.deleteMarkers).toBe(1);
    expect(result.verifiedLedgerReferences).toBe(1);
    const inventory = JSON.parse(await readFile(join(config.output, "inventory.json"), "utf8"));
    expect(inventory.references).toHaveLength(6);
    for (const reference of inventory.references) {
      const file = join(config.output, reference.relativePath.slice("artifactStore/".length));
      const bytes = await readFile(file);
      expect(createHash("sha256").update(bytes).digest("hex")).toBe(reference.sha256);
      expect(bytes.length).toBe(reference.bytes);
    }
    expect(client.calls.some(name => /Put|Delete/.test(name))).toBe(false);
    const metadataFiles = (await readdir(join(config.output, "versions"))).filter(name => name.endsWith(".metadata.json"));
    const metadata = await Promise.all(metadataFiles.map(name => readFile(join(config.output, "versions", name), "utf8")));
    expect(metadata.some(text => text.includes('"deleted":true'))).toBe(true);
    expect(metadata.some(text => text.includes('"original":"preserved"'))).toBe(true);
    expect(await readFile(join(config.output, "ledger-artifacts.json"), "utf8")).toContain("original-task:attempt");
  });
  it("refuses an available artifact whose actual payload bytes differ", async () => {
    await expect(exportRecoveryVersions(fixture({ wrongPayload: true }) as any, await options()))
      .rejects.toThrow("available ledger artifact");
  });
  it("refuses changed before/after version inventory and never publishes inventory success", async () => {
    const config = await options();
    await expect(exportRecoveryVersions(fixture({ changed: true }) as any, config)).rejects.toThrow("changed");
    await expect(readFile(join(config.output, "inventory.json"))).rejects.toThrow();
  });
  it("refuses broken repeated pagination instead of pretending export closure", async () => {
    await expect(listVersions(fixture({ repeated: true }) as any, "rubicon-artifacts", 100)).rejects.toThrow("repeated");
  });
  it("refuses duplicate/unversioned identities and budget overrun", async () => {
    const nullVersion = { send: async () => ({ Versions: [{ Key: "key", VersionId: "null", Size: 1 }] }) };
    await expect(listVersions(nullVersion as any, "rubicon-artifacts", 10)).rejects.toThrow("versioned");
    await expect(listVersions(fixture() as any, "rubicon-artifacts", 1)).rejects.toThrow("budget");
  });
});

describe("purpose-specific released recovery export entry", () => {
  async function inputs() {
    const root = await mkdtemp(join(tmpdir(), "rubicon-entry-fixture-"));
    roots.push(root);
    const credential = join(root, "private-credential-reference.json");
    await writeFile(credential, JSON.stringify({ accessKeyId: "fixture-only", secretAccessKey: "fixture-secret",
      databaseUrl: "postgres://fixture-only/isolated" }), { mode: 0o600 });
    const plan = join(root, "private-plan.json");
    await writeFile(plan, JSON.stringify({ schemaVersion: "execution-fabric-recovery-export-plan/v1",
      sourceHost: "genomesbox", endpoint: "http://fixture-minio.invalid:9000", bucket: "rubicon-artifacts",
      region: "us-east-1", credentialFile: credential, readOnlyDatabaseRole: "readonly-recovery",
      expectedPostgresSource: { systemId: "7432345656789123456", database: "execution_fabric", databaseOid: "16384", majorVersion: 17 },
      ownerBinding: "original-bucket-owner", maxVersions: 100, maxBytes: 10000 }), { mode: 0o600 });
    Object.assign(native, { client: fixture(), queries: [], role: "readonly-recovery", elevated: false,
      lsn: "0/ABCD", connectFailure: false, released: false, poolEnded: false, destroyed: false });
    Object.assign(native, { systemId: "7432345656789123456", database: "execution_fabric", databaseOid: "16384", majorVersion: 17 });
    vi.stubEnv("FABRIC_HOST_ID", "genomesbox");
    return { root, plan, credential, output: join(root, "new-output"), receipt: join(root, "new-receipt.json") };
  }
  it("executes an actual read-only transaction and fresh all-version private receipt without starting an API", async () => {
    const input = await inputs();
    const result = await executeRecoveryExport(input.plan, input.output, input.receipt);
    expect(result.status).toBe("exported_bytes_verified");
    expect(result.authorityTransferAuthorized).toBe(false);
    expect(result.postgresSourceVerified).toBe(true);
    expect(native.queries[0]).toBe("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY");
    expect(native.queries.some(query => /INSERT|UPDATE|DELETE|CREATE/.test(query))).toBe(false);
    expect(native.released && native.poolEnded && native.destroyed).toBe(true);
    expect(await readFile(input.receipt, "utf8")).not.toContain("fixture-secret");
    await expect(executeRecoveryExport(input.plan, join(input.root, "another-output"), input.receipt)).rejects.toThrow();
  });
  it("checks current watermarks without exporting object payloads or creating an output tree", async () => {
    const input = await inputs();
    expect((await executeRecoveryExport(input.plan, input.output, input.receipt, true)).status).toBe("watermark_verified");
    expect(native.client.calls).not.toContain("GetObjectCommand");
    await expect(readdir(input.output)).rejects.toThrow();
  });
  it("refuses an elevated or mismatched database identity before object reads", async () => {
    const input = await inputs();
    native.elevated = true;
    await expect(executeRecoveryExport(input.plan, input.output, input.receipt)).rejects.toThrow("elevated");
    expect(native.client.calls).toHaveLength(0);
    native.elevated = false;
    native.role = "foreign-role";
    await expect(executeRecoveryExport(input.plan, input.output, input.receipt)).rejects.toThrow("role differs");
    await expect(readFile(input.receipt)).rejects.toThrow();
  });
  it.each(["systemId", "database", "databaseOid", "majorVersion"] as const)("refuses changed actual PostgreSQL %s before object reads", async field => {
    const input = await inputs();
    if (field === "majorVersion") native.majorVersion = 16;
    else native[field] = "99999";
    await expect(executeRecoveryExport(input.plan, input.output, input.receipt)).rejects.toThrow("differs from native");
    expect(native.client.calls).toHaveLength(0);
    await expect(readFile(input.receipt)).rejects.toThrow();
  });
  it("refuses exposed credential input and cleans native clients even when connection setup fails", async () => {
    const input = await inputs();
    await chmod(input.credential, 0o644);
    await expect(executeRecoveryExport(input.plan, input.output, input.receipt)).rejects.toThrow("private input");
    expect(native.queries).toHaveLength(0);
    await chmod(input.credential, 0o600);
    native.connectFailure = true;
    await expect(executeRecoveryExport(input.plan, input.output, input.receipt)).rejects.toThrow("readonly_connection: Error");
    expect(native.poolEnded && native.destroyed).toBe(true);
    expect(native.released).toBe(false);
  });
});
