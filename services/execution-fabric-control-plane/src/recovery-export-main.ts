/** Purpose-specific read-only recovery exporter. Never starts the Fabric API. */
import { createHash } from "node:crypto";
import { lstat, readFile, writeFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import { S3Client } from "@aws-sdk/client-s3";
import pg from "pg";
import { exportRecoveryVersions, listVersions, RecoveryExportError, type LedgerArtifact } from "./recovery-export.js";

type ExportPlan = {
  schemaVersion: "execution-fabric-recovery-export-plan/v1";
  sourceHost: string; endpoint: string; bucket: string; region: string;
  credentialFile: string; readOnlyDatabaseRole: string; ownerBinding: string;
  maxVersions: number; maxBytes: number;
  expectedPostgresSource: { systemId: string; database: string; databaseOid: string; majorVersion: number };
};
const SOURCE_SQL = `SELECT c.system_identifier::text AS "systemId", current_database() AS database,
  d.oid::text AS "databaseOid", current_setting('server_version_num')::integer AS "serverVersionNum"
  FROM pg_control_system() c JOIN pg_database d ON d.datname=current_database()`;
async function observedSource(connection: pg.PoolClient) {
  const result = await connection.query<{ systemId: string; database: string; databaseOid: string; serverVersionNum: number }>(SOURCE_SQL);
  const row = result.rows[0];
  if (result.rows.length !== 1 || !row || !/^[1-9][0-9]*$/.test(row.systemId) || !row.database ||
      !/^[1-9][0-9]*$/.test(row.databaseOid) || !Number.isSafeInteger(row.serverVersionNum) || row.serverVersionNum < 100000) {
    throw new RecoveryExportError("actual native PostgreSQL source identity is unavailable");
  }
  return { schemaVersion: "execution-fabric-postgres-source/v1", ...row,
    majorVersion: Math.floor(row.serverVersionNum / 10000) };
}
const digest = (value: unknown) => createHash("sha256").update(JSON.stringify(value)).digest("hex");
async function protectedJson(path: string): Promise<Record<string, unknown>> {
  const metadata = await lstat(path);
  if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.mode & 0o077) {
    throw new RecoveryExportError("protected private input reference required");
  }
  const value: unknown = JSON.parse(await readFile(path, "utf8"));
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new RecoveryExportError("input must be a closed object");
  return value as Record<string, unknown>;
}

export async function executeRecoveryExport(planFile: string, output: string, receiptFile: string,
                                            watermarkOnly = false): Promise<Record<string, unknown>> {
  const input = await protectedJson(planFile);
  const fields = ["schemaVersion", "sourceHost", "endpoint", "bucket", "region", "credentialFile",
    "readOnlyDatabaseRole", "ownerBinding", "maxVersions", "maxBytes", "expectedPostgresSource"].sort();
  if (JSON.stringify(Object.keys(input).sort()) !== JSON.stringify(fields) ||
      input.schemaVersion !== "execution-fabric-recovery-export-plan/v1" ||
      input.sourceHost !== process.env.FABRIC_HOST_ID) {
    throw new RecoveryExportError("closed export plan and exact current source host required");
  }
  const plan = input as unknown as ExportPlan;
  const expected = plan.expectedPostgresSource;
  if (!expected || Object.keys(expected).sort().join(",") !== "database,databaseOid,majorVersion,systemId" ||
      !/^[1-9][0-9]*$/.test(expected.systemId) || !expected.database || !/^[1-9][0-9]*$/.test(expected.databaseOid) ||
      !Number.isSafeInteger(expected.majorVersion) || expected.majorVersion < 10) {
    throw new RecoveryExportError("exact declared PostgreSQL system/database/version required");
  }
  const endpoint = new URL(plan.endpoint);
  if (!["http:", "https:"].includes(endpoint.protocol) || endpoint.username || endpoint.password ||
      endpoint.search || endpoint.hash || !plan.readOnlyDatabaseRole || !plan.ownerBinding) {
    throw new RecoveryExportError("declared private endpoint/read-only role required");
  }
  const credentials = await protectedJson(plan.credentialFile);
  if (Object.keys(credentials).sort().join(",") !== "accessKeyId,databaseUrl,secretAccessKey" ||
      typeof credentials.accessKeyId !== "string" || typeof credentials.secretAccessKey !== "string" ||
      typeof credentials.databaseUrl !== "string") throw new RecoveryExportError("closed read-only credential bundle required");
  const client = new S3Client({ endpoint: plan.endpoint, region: plan.region, forcePathStyle: true,
    maxAttempts: 1, credentials: { accessKeyId: credentials.accessKeyId, secretAccessKey: credentials.secretAccessKey } });
  const pool = new pg.Pool({ connectionString: credentials.databaseUrl, max: 1,
    connectionTimeoutMillis: 10000, query_timeout: 30000, statement_timeout: 30000 });
  let connection: pg.PoolClient | undefined;
  let nativeStage = "readonly_connection";
  try {
    connection = await pool.connect();
    nativeStage = "readonly_transaction";
    await connection.query("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY");
    nativeStage = "readonly_role_identity";
    const identity = await connection.query<{ role: string }>("SELECT current_user AS role");
    if (identity.rows[0]?.role !== plan.readOnlyDatabaseRole) throw new RecoveryExportError("database credential role differs from declared read-only identity");
    const privileges = await connection.query<{ elevated: boolean }>("SELECT (rolsuper OR rolcreatedb OR rolcreaterole) AS elevated FROM pg_roles WHERE rolname=current_user");
    if (privileges.rows[0]?.elevated !== false) throw new RecoveryExportError("recovery export refuses an elevated database role");
    // Missing function access fails under this same role; no elevated fallback.
    nativeStage = "native_source_identity";
    const source = await observedSource(connection);
    if (source.systemId !== expected.systemId || source.database !== expected.database ||
        source.databaseOid !== expected.databaseOid || source.majorVersion !== expected.majorVersion) {
      throw new RecoveryExportError("declared PostgreSQL source differs from native read-only connection");
    }
    nativeStage = "source_wal_and_ledger";
    const before = await connection.query<{ lsn: string }>("SELECT pg_current_wal_lsn()::text AS lsn");
    const rows = await connection.query<{
      id: string; task_id: string; attempt_id: string; object_key: string; storage_uri: string; sha256: string; size_bytes: string;
    }>("SELECT id,task_id,attempt_id,object_key,storage_uri,sha256,size_bytes FROM fabric_artifacts WHERE status='available' ORDER BY id LIMIT $1",
      [plan.maxVersions + 1]);
    if (rows.rows.length > plan.maxVersions) throw new RecoveryExportError("available ledger reference budget exceeded");
    const artifacts: LedgerArtifact[] = rows.rows.map(row => {
      if (!row.object_key || row.storage_uri !== "s3://" + plan.bucket + "/" + row.object_key) {
        throw new RecoveryExportError("available artifact source bucket binding differs");
      }
      return { artifactId: row.id, objectKey: row.object_key,
        sha256: row.sha256, sizeBytes: Number(row.size_bytes), ownerBinding: row.task_id + ":" + row.attempt_id };
    });
    let exported: Record<string, unknown>;
    nativeStage = "readonly_object_export";
    if (watermarkOnly) {
      const inventory = await listVersions(client, plan.bucket, plan.maxVersions);
      exported = { status: "watermark_verified", versionInventorySha256: digest(inventory) };
    } else {
      exported = await exportRecoveryVersions(client, {
        bucket: plan.bucket, output, ownerBinding: plan.ownerBinding, ledgerArtifacts: artifacts,
        maxVersions: plan.maxVersions, maxBytes: plan.maxBytes,
      });
    }
    nativeStage = "source_identity_readback";
    const after = await connection.query<{ lsn: string }>("SELECT pg_current_wal_lsn()::text AS lsn");
    if (JSON.stringify(await observedSource(connection)) !== JSON.stringify(source)) {
      throw new RecoveryExportError("native PostgreSQL source identity changed during export");
    }
    if (!before.rows[0]?.lsn || before.rows[0].lsn !== after.rows[0]?.lsn) {
      throw new RecoveryExportError("PostgreSQL changed under recovery writer barrier");
    }
    await connection.query("COMMIT");
    nativeStage = "private_receipt_publication";
    const receipt = { ...exported, sourceHost: plan.sourceHost,
      postgresWalLsn: before.rows[0].lsn, ledgerReferenceSha256: digest(artifacts),
      postgresSourceVerified: true, postgresSource: source,
      authorityTransferAuthorized: false };
    await writeFile(receiptFile, JSON.stringify(receipt, null, 2) + "\n", { mode: 0o600, flag: "wx" });
    return receipt;
  } catch (error: unknown) {
    if (error instanceof RecoveryExportError) throw error;
    const attributes = typeof error === "object" && error !== null ? error : {};
    const code = "code" in attributes ? attributes.code : "name" in attributes ? attributes.name : undefined;
    const category = typeof code === "string" && /^[A-Za-z0-9_]{1,32}$/.test(code) ? code : "native_actor_failed";
    throw new RecoveryExportError(nativeStage+": "+category);
  } finally {
    if (connection) {
      await connection.query("ROLLBACK").catch(() => undefined);
      connection.release();
    }
    await pool.end();
    client.destroy();
  }
}

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  const allowed = new Set(["--plan", "--output", "--receipt", "--watermark-only"]);
  const parsed = new Map<string, string>();
  let watermarkOnly = false;
  for (let index = 0; index < args.length; index++) {
    const key = args[index]!;
    if (!allowed.has(key) || parsed.has(key)) throw new RecoveryExportError("unsupported export argument");
    if (key === "--watermark-only") { watermarkOnly = true; continue; }
    const value = args[++index];
    if (!value || value.startsWith("--")) throw new RecoveryExportError("missing export reference");
    parsed.set(key, value);
  }
  if (!parsed.has("--plan") || !parsed.has("--receipt") || (!watermarkOnly && !parsed.has("--output"))) {
    throw new RecoveryExportError("plan, output and private receipt references required");
  }
  const receipt = await executeRecoveryExport(parsed.get("--plan")!, parsed.get("--output") ?? "",
    parsed.get("--receipt")!, watermarkOnly);
  console.log(JSON.stringify({ status: receipt.status, receiptSha256: createHash("sha256")
    .update(await readFile(parsed.get("--receipt")!)).digest("hex"), authorityTransferAuthorized: false }));
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error: unknown) => {
    // Our refusal messages contain no input values. Native errors expose only a
    // bounded code, never connection strings, object names or native payloads.
    const nativeCode = typeof error === "object" && error !== null && "code" in error ? error.code : undefined;
    const failureClass = error instanceof RecoveryExportError ? error.message :
      typeof nativeCode === "string" && /^[A-Za-z0-9_]{1,32}$/.test(nativeCode) ? nativeCode : "native_export_failed";
    console.error(JSON.stringify({ status: "held", reason: "read-only recovery export failed; private details withheld", failureClass }));
    process.exitCode = 1;
  });
}
