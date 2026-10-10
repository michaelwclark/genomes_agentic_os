import { createHash } from "node:crypto";
import { mkdir, open, readFile, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import {
  GetObjectCommand, GetObjectTaggingCommand, GetBucketVersioningCommand, ListObjectVersionsCommand, S3Client,
} from "@aws-sdk/client-s3";
import type { ObjectVersion, DeleteMarkerEntry } from "@aws-sdk/client-s3";

type Client = Pick<S3Client, "send">;
type Version = { key: string; versionId: string; deleted: boolean; latest: boolean; size: number; etag: string | null; modified: string | null };
type Reference = { relativePath: string; sha256: string; bytes: number; ownerBinding: string; artifactId: string; objectKey: string; versionId: string };
export type LedgerArtifact = { artifactId: string; objectKey: string; sha256: string; sizeBytes: number; ownerBinding: string };
export type ExportOptions = { bucket: string; output: string; ownerBinding: string; ledgerArtifacts: LedgerArtifact[]; maxVersions: number; maxBytes: number };
export class RecoveryExportError extends Error {
  constructor(message: string) { super(message); this.name = "RecoveryExportError"; }
}
const digest = (data: string | Uint8Array) => createHash("sha256").update(data).digest("hex");
const canonical = (value: unknown): string => JSON.stringify(value);
const id = (value: string) => digest(value).slice(0, 32);

async function privateJson(path: string, value: unknown): Promise<void> {
  await writeFile(path, canonical(value) + "\n", { mode: 0o600, flag: "wx" });
}
function version(record: ObjectVersion | DeleteMarkerEntry, deleted: boolean): Version {
  if (!record.Key || !record.VersionId || record.VersionId === "null") {
    throw new RecoveryExportError("all-version export requires actual versioned object identities");
  }
  const size = "Size" in record ? Number(record.Size ?? 0) : 0;
  if (!Number.isSafeInteger(size) || size < 0) throw new RecoveryExportError("invalid object version size");
  return { key: record.Key, versionId: record.VersionId, deleted,
    latest: record.IsLatest === true, size,
    etag: "ETag" in record ? record.ETag ?? null : null,
    modified: record.LastModified?.toISOString() ?? null };
}

export async function listVersions(client: Client, bucket: string, limit: number): Promise<Version[]> {
  const versions: Version[] = [];
  let key: string | undefined;
  let marker: string | undefined;
  const pages = new Set<string>();
  do {
    const cursor = canonical([key, marker]);
    if (pages.has(cursor)) throw new RecoveryExportError("object-version pagination repeated");
    pages.add(cursor);
    const page = await client.send(new ListObjectVersionsCommand({
      Bucket: bucket, KeyMarker: key, VersionIdMarker: marker, MaxKeys: 1000,
    }));
    versions.push(...(page.Versions ?? []).map((v: ObjectVersion) => version(v, false)),
                  ...(page.DeleteMarkers ?? []).map((v: DeleteMarkerEntry) => version(v, true)));
    if (versions.length > limit) throw new RecoveryExportError("declared version export budget exceeded");
    if (!page.IsTruncated) break;
    key = page.NextKeyMarker;
    marker = page.NextVersionIdMarker;
    if (!key || !marker) throw new RecoveryExportError("truncated version listing omitted exact cursor");
  } while (true);
  versions.sort((a, b) => a.key.localeCompare(b.key) || a.versionId.localeCompare(b.versionId));
  const unique = new Set(versions.map(v => canonical([v.key, v.versionId])));
  if (unique.size !== versions.length) throw new RecoveryExportError("duplicate object-version identity");
  return versions;
}

/** Read-only configured-bucket export. Caller retains a qualified writer barrier. */
export async function exportRecoveryVersions(client: Client, options: ExportOptions): Promise<Record<string, unknown>> {
  if (!/^[a-z0-9][a-z0-9.-]{1,62}$/.test(options.bucket) || !options.ownerBinding ||
      !Number.isSafeInteger(options.maxVersions) || options.maxVersions < 1 ||
      !Number.isSafeInteger(options.maxBytes) || options.maxBytes < 1) {
    throw new RecoveryExportError("closed bucket/owner/budget binding required");
  }
  const enabled = await client.send(new GetBucketVersioningCommand({ Bucket: options.bucket }));
  if (enabled.Status !== "Enabled") throw new RecoveryExportError("bucket versioning must already be enabled");
  const before = await listVersions(client, options.bucket, options.maxVersions);
  if (before.reduce((total, item) => total + item.size, 0) > options.maxBytes) {
    throw new RecoveryExportError("declared payload export budget exceeded");
  }
  const output = resolve(options.output);
  // Existing roots are never overwritten, including another incomplete attempt.
  await mkdir(output, { mode: 0o700 });
  await mkdir(join(output, "versions"), { mode: 0o700 });
  const references: Reference[] = [];
  const payloads = new Map<string, { sha256: string; bytes: number; versionId: string }>();
  for (const item of before) {
    const identity = id(canonical([item.key, item.versionId]));
    const metadataRelative = "artifactStore/versions/" + identity + ".metadata.json";
    const metadataPath = join(output, "versions", identity + ".metadata.json");
    const metadata: Record<string, unknown> = { schemaVersion: "execution-fabric-recovery-object-version/v1", bucket: options.bucket,
      ...item, ownerBinding: options.ownerBinding };
    const captureMetadata = async () => {
      await privateJson(metadataPath, metadata);
      const metadataBytes = await readFile(metadataPath);
      references.push({ relativePath: metadataRelative, sha256: digest(metadataBytes), bytes: metadataBytes.length,
        ownerBinding: options.ownerBinding, artifactId: "version-metadata:" + identity,
        objectKey: item.key, versionId: item.versionId });
    };
    if (item.deleted) { await captureMetadata(); continue; }
    const response = await client.send(new GetObjectCommand({
      Bucket: options.bucket, Key: item.key, VersionId: item.versionId,
    }));
    if (!response.Body || response.VersionId !== item.versionId) {
      throw new RecoveryExportError("version payload response lacks exact requested identity");
    }
    metadata.objectMetadata = response.Metadata ?? {};
    for (const field of ["ContentType", "ContentEncoding", "ContentDisposition", "ContentLanguage",
      "CacheControl", "Expires", "StorageClass", "ObjectLockMode", "ObjectLockRetainUntilDate",
      "ObjectLockLegalHoldStatus", "ChecksumSHA256", "ChecksumCRC32", "ChecksumCRC32C", "ChecksumSHA1"] as const) {
      if (response[field] !== undefined) metadata[field] = response[field];
    }
    const tags = await client.send(new GetObjectTaggingCommand({ Bucket: options.bucket,
      Key: item.key, VersionId: item.versionId }));
    metadata.tags = [...(tags.TagSet ?? [])].sort((a, b) => (a.Key ?? "").localeCompare(b.Key ?? ""));
    const body = response.Body as AsyncIterable<Uint8Array>;
    const path = join(output, "versions", identity + ".payload");
    const handle = await open(path, "wx", 0o600);
    const hash = createHash("sha256");
    let bytes = 0;
    try {
      for await (const chunk of body) {
        bytes += chunk.length;
        if (bytes > item.size) throw new RecoveryExportError("object payload exceeds declared version bytes");
        hash.update(chunk);
        await handle.writeFile(chunk);
      }
      await handle.sync();
    } finally { await handle.close(); }
    const sha256 = hash.digest("hex");
    if (bytes !== item.size || (response.ContentLength !== undefined && response.ContentLength !== bytes)) {
      throw new RecoveryExportError("object payload size differs from version listing");
    }
    const payload = { sha256, bytes, versionId: item.versionId };
    if (item.latest) payloads.set(item.key, payload);
    references.push({ relativePath: "artifactStore/versions/" + identity + ".payload",
      ...payload, ownerBinding: options.ownerBinding, artifactId: "object-version:" + identity, objectKey: item.key });
    await captureMetadata();
  }
  // Actual ledger references must resolve to the currently available source version.
  for (const artifact of options.ledgerArtifacts) {
    const payload = payloads.get(artifact.objectKey);
    if (!payload || payload.sha256 !== artifact.sha256 || payload.bytes !== artifact.sizeBytes ||
        !artifact.artifactId || !artifact.ownerBinding) {
      throw new RecoveryExportError("available ledger artifact cannot resolve to exact exported source bytes");
    }
  }
  const after = await listVersions(client, options.bucket, options.maxVersions);
  if (canonical(before) !== canonical(after)) throw new RecoveryExportError("version inventory changed under writer barrier");
  const ledgerPath = join(output, "ledger-artifacts.json");
  await privateJson(ledgerPath, { schemaVersion: "execution-fabric-recovery-ledger-artifacts/v1",
    artifacts: options.ledgerArtifacts, versionInventorySha256: digest(canonical(before)) });
  const ledgerBytes = await readFile(ledgerPath);
  references.push({ relativePath: "artifactStore/ledger-artifacts.json", sha256: digest(ledgerBytes),
    bytes: ledgerBytes.length, ownerBinding: options.ownerBinding,
    artifactId: "ledger-reference-inventory", objectKey: "__recovery_metadata__/ledger",
    versionId: digest(canonical(before)) });
  await privateJson(join(output, "inventory.json"), {
    schemaVersion: "execution-fabric-recovery-artifacts/v1", references,
  });
  return { schemaVersion: "execution-fabric-recovery-export/v1", status: "exported_bytes_verified",
    versionInventorySha256: digest(canonical(before)), dataVersions: before.filter(v => !v.deleted).length,
    deleteMarkers: before.filter(v => v.deleted).length, verifiedLedgerReferences: options.ledgerArtifacts.length,
    bytes: references.reduce((total, reference) => total + reference.bytes, 0),
    inventorySha256: digest(await readFile(join(output, "inventory.json"))) };
}
