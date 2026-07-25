import { createHash, randomUUID } from "node:crypto";
import {
  GetObjectCommand,
  HeadBucketCommand,
  HeadObjectCommand,
  PutObjectCommand,
  S3Client,
} from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";
import type pg from "pg";
import type {
  ArtifactFinalize,
  ArtifactRecord,
  ArtifactRecoveryFinalize,
  ArtifactRecoveryUpload,
  ArtifactUpload,
} from "./contracts.js";
import { ConflictError, NotFoundError } from "./ledger.js";

export type ArtifactStoreConfig = {
  endpoint: string;
  region: string;
  bucket: string;
  accessKeyId: string;
  secretAccessKey: string;
  forcePathStyle: boolean;
  uploadTtlSeconds: number;
  downloadTtlSeconds: number;
  maxBytes: number;
};

export type ArtifactUploadReceipt = {
  artifact: ArtifactRecord;
  alreadyAvailable: boolean;
  upload?: {
    method: "PUT";
    url: string;
    expiresAt: string;
    headers: Record<string, string>;
  };
};

const artifactUploadSignedHeaders = new Set([
  "content-length",
  "content-type",
  "x-amz-meta-sha256",
]);

function iso(value: string | Date): string {
  return new Date(value).toISOString();
}

function record(row: Record<string, unknown>): ArtifactRecord {
  return {
    artifactId: String(row.id),
    taskId: String(row.task_id),
    attemptId: String(row.attempt_id),
    name: String(row.name),
    contentType: String(row.content_type),
    sha256: String(row.sha256),
    sizeBytes: Number(row.size_bytes),
    status: String(row.status) as ArtifactRecord["status"],
    uri: row.storage_uri ? String(row.storage_uri) : null,
    createdAt: iso(row.created_at as string),
    availableAt: row.available_at ? iso(row.available_at as string) : null,
  };
}

function safeName(name: string): string {
  return name.replace(/[^a-zA-Z0-9._-]/g, "_").slice(0, 128);
}

export class ArtifactStore {
  private readonly client: S3Client;

  constructor(
    private readonly pool: pg.Pool,
    private readonly config: ArtifactStoreConfig,
    private readonly clusterId: string,
    client?: S3Client,
  ) {
    this.client =
      client ??
      new S3Client({
        endpoint: config.endpoint,
        region: config.region,
        forcePathStyle: config.forcePathStyle,
        credentials: {
          accessKeyId: config.accessKeyId,
          secretAccessKey: config.secretAccessKey,
        },
      });
  }

  async ping(): Promise<void> {
    await this.client.send(new HeadBucketCommand({ Bucket: this.config.bucket }));
  }

  async health(): Promise<{
    status: "healthy" | "unavailable";
    bucket: string;
    checkedAt: string;
    error?: string;
  }> {
    const checkedAt = new Date().toISOString();
    try {
      await this.ping();
      return { status: "healthy", bucket: this.config.bucket, checkedAt };
    } catch (error) {
      return {
        status: "unavailable",
        bucket: this.config.bucket,
        checkedAt,
        error: error instanceof Error ? error.name : "object_store_error",
      };
    }
  }

  async initiate(input: ArtifactUpload): Promise<ArtifactUploadReceipt> {
    if (input.sizeBytes > this.config.maxBytes) {
      throw new ConflictError(
        `artifact exceeds configured maximum of ${this.config.maxBytes} bytes`,
      );
    }
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      const attempt = await client.query(
        `SELECT a.id
         FROM fabric_attempts a
         JOIN fabric_tasks t ON t.id=a.task_id
         CROSS JOIN fabric_state s
         WHERE a.id=$1 AND t.id=$2
           AND a.worker_id=$3 AND a.lease_token=$4
           AND a.fabric_epoch=$5 AND s.current_epoch=$5
           AND a.status='running' AND a.lease_expires_at > now()
           AND s.singleton=true
         FOR SHARE`,
        [
          input.attemptId,
          input.taskId,
          input.workerId,
          input.leaseToken,
          input.fabricEpoch,
        ],
      );
      if (!attempt.rowCount) {
        throw new NotFoundError("task attempt not found");
      }
      const existing = await client.query(
        `SELECT * FROM fabric_artifacts
         WHERE attempt_id=$1 AND name=$2 AND sha256=$3
         FOR UPDATE`,
        [input.attemptId, input.name, input.sha256],
      );
      let row: Record<string, unknown>;
      if (existing.rowCount) {
        row = existing.rows[0] as Record<string, unknown>;
        if (
          Number(row.size_bytes) !== input.sizeBytes ||
          String(row.content_type) !== input.contentType
        ) {
          throw new ConflictError(
            "artifact identity already exists with different metadata",
          );
        }
      } else {
        const artifactId = randomUUID();
        const objectKey = [
          "v1",
          this.clusterId,
          input.taskId,
          input.attemptId,
          `${artifactId}-${safeName(input.name)}`,
        ].join("/");
        const inserted = await client.query(
          `INSERT INTO fabric_artifacts(
             id,task_id,attempt_id,object_key,name,content_type,sha256,
             size_bytes,upload_expires_at
           ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,
             now()+($9*interval '1 second'))
           RETURNING *`,
          [
            artifactId,
            input.taskId,
            input.attemptId,
            objectKey,
            input.name,
            input.contentType,
            input.sha256,
            input.sizeBytes,
            this.config.uploadTtlSeconds,
          ],
        );
        row = inserted.rows[0] as Record<string, unknown>;
      }
      await client.query("COMMIT");
      const artifact = record(row);
      if (artifact.status === "available") {
        return { artifact, alreadyAvailable: true };
      }
      const expiresAt = new Date(
        Date.now() + this.config.uploadTtlSeconds * 1000,
      ).toISOString();
      const headers = {
        "content-type": input.contentType,
        "content-length": String(input.sizeBytes),
        "x-amz-meta-sha256": input.sha256,
      };
      const url = await getSignedUrl(
        this.client,
        new PutObjectCommand({
          Bucket: this.config.bucket,
          Key: String(row.object_key),
          ContentType: input.contentType,
          ContentLength: input.sizeBytes,
          Metadata: { sha256: input.sha256 },
        }),
        {
          expiresIn: this.config.uploadTtlSeconds,
          signableHeaders: artifactUploadSignedHeaders,
          unhoistableHeaders: new Set(["x-amz-meta-sha256"]),
        },
      );
      return {
        artifact,
        alreadyAvailable: false,
        upload: { method: "PUT", url, expiresAt, headers },
      };
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  async initiateRecovery(
    input: ArtifactRecoveryUpload,
  ): Promise<ArtifactUploadReceipt> {
    if (input.sizeBytes > this.config.maxBytes) {
      throw new ConflictError(
        `artifact exceeds configured maximum of ${this.config.maxBytes} bytes`,
      );
    }
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      const session = await client.query(
        `SELECT a.id
         FROM fabric_attempts a
         JOIN fabric_workers w ON w.worker_id=a.worker_id
         JOIN fabric_worker_sessions ws ON ws.id=w.current_session_id
         CROSS JOIN fabric_state s
         WHERE a.id=$1 AND a.task_id=$2 AND a.worker_id=$3
           AND a.recovery_token=$6
           AND w.registration_token=$4 AND w.registered_epoch=$5
           AND w.registered_epoch=s.current_epoch
           AND w.lease_expires_at > now()
           AND ws.registration_token=$4 AND ws.fabric_epoch=$5
           AND ws.status='active' AND ws.lease_expires_at > now()
           AND s.singleton=true
         FOR SHARE OF a,w,ws`,
        [
          input.attemptId,
          input.taskId,
          input.workerId,
          input.registrationToken,
          input.fabricEpoch,
          input.attemptRecoveryToken,
        ],
      );
      if (!session.rowCount) {
        throw new NotFoundError("current worker session cannot recover artifact");
      }
      const existing = await client.query(
        `SELECT * FROM fabric_artifacts
         WHERE attempt_id=$1 AND name=$2 AND sha256=$3
         FOR UPDATE`,
        [input.attemptId, input.name, input.sha256],
      );
      let row: Record<string, unknown>;
      if (existing.rowCount) {
        row = existing.rows[0] as Record<string, unknown>;
        if (
          Number(row.size_bytes) !== input.sizeBytes ||
          String(row.content_type) !== input.contentType
        ) {
          throw new ConflictError(
            "artifact identity already exists with different metadata",
          );
        }
        if (row.status !== "available") {
          const refreshed = await client.query(
            `UPDATE fabric_artifacts
             SET status='pending',last_error=NULL,
               upload_expires_at=now()+($2*interval '1 second'),updated_at=now()
             WHERE id=$1 RETURNING *`,
            [row.id, this.config.uploadTtlSeconds],
          );
          row = refreshed.rows[0] as Record<string, unknown>;
        }
      } else {
        const artifactId = randomUUID();
        const objectKey = [
          "v1",
          this.clusterId,
          input.taskId,
          input.attemptId,
          `${artifactId}-${safeName(input.name)}`,
        ].join("/");
        const inserted = await client.query(
          `INSERT INTO fabric_artifacts(
             id,task_id,attempt_id,object_key,name,content_type,sha256,
             size_bytes,upload_expires_at
           ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,
             now()+($9*interval '1 second'))
           RETURNING *`,
          [
            artifactId,
            input.taskId,
            input.attemptId,
            objectKey,
            input.name,
            input.contentType,
            input.sha256,
            input.sizeBytes,
            this.config.uploadTtlSeconds,
          ],
        );
        row = inserted.rows[0] as Record<string, unknown>;
      }
      await client.query("COMMIT");
      const artifact = record(row);
      if (artifact.status === "available") {
        return { artifact, alreadyAvailable: true };
      }
      const headers = {
        "content-type": input.contentType,
        "content-length": String(input.sizeBytes),
        "x-amz-meta-sha256": input.sha256,
      };
      const url = await getSignedUrl(
        this.client,
        new PutObjectCommand({
          Bucket: this.config.bucket,
          Key: String(row.object_key),
          ContentType: input.contentType,
          ContentLength: input.sizeBytes,
          Metadata: { sha256: input.sha256 },
        }),
        {
          expiresIn: this.config.uploadTtlSeconds,
          signableHeaders: artifactUploadSignedHeaders,
          unhoistableHeaders: new Set(["x-amz-meta-sha256"]),
        },
      );
      return {
        artifact,
        alreadyAvailable: false,
        upload: {
          method: "PUT",
          url,
          expiresAt: new Date(
            Date.now() + this.config.uploadTtlSeconds * 1000,
          ).toISOString(),
          headers,
        },
      };
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw error;
    } finally {
      client.release();
    }
  }

  async finalize(
    artifactId: string,
    input: ArtifactFinalize,
  ): Promise<ArtifactRecord> {
    const result = await this.pool.query(
      `SELECT fa.*
       FROM fabric_artifacts fa
       JOIN fabric_attempts a ON a.id=fa.attempt_id
       CROSS JOIN fabric_state s
       WHERE fa.id=$1 AND fa.task_id=$2 AND fa.attempt_id=$3
         AND a.worker_id=$4 AND a.lease_token=$5
         AND a.fabric_epoch=$6 AND s.current_epoch=$6
         AND a.status='running' AND a.lease_expires_at > now()
         AND s.singleton=true`,
      [
        artifactId,
        input.taskId,
        input.attemptId,
        input.workerId,
        input.leaseToken,
        input.fabricEpoch,
      ],
    );
    if (!result.rowCount) throw new NotFoundError("artifact upload not found");
    const row = result.rows[0] as Record<string, unknown>;
    if (row.status === "available") return record(row);
    let head;
    try {
      head = await this.client.send(
        new HeadObjectCommand({
          Bucket: this.config.bucket,
          Key: String(row.object_key),
        }),
      );
    } catch (error) {
      await this.pool.query(
        `UPDATE fabric_artifacts SET status='failed',last_error=$2,updated_at=now()
         WHERE id=$1`,
        [artifactId, error instanceof Error ? error.name : "head_failed"],
      );
      throw new ConflictError("artifact object is not available for verification");
    }
    let actualSha256 = "";
    try {
      const object = await this.client.send(
        new GetObjectCommand({
          Bucket: this.config.bucket,
          Key: String(row.object_key),
        }),
      );
      const bytes = await object.Body?.transformToByteArray();
      if (!bytes) throw new Error("object_body_unavailable");
      actualSha256 = createHash("sha256").update(bytes).digest("hex");
    } catch (error) {
      await this.pool.query(
        `UPDATE fabric_artifacts SET status='failed',last_error=$2,updated_at=now()
         WHERE id=$1`,
        [artifactId, error instanceof Error ? error.name : "digest_read_failed"],
      );
      throw new ConflictError("artifact object could not be read for verification");
    }
    if (
      Number(head.ContentLength) !== Number(row.size_bytes) ||
      actualSha256 !== String(row.sha256)
    ) {
      await this.pool.query(
        `UPDATE fabric_artifacts SET status='failed',
           last_error='metadata_verification_failed',updated_at=now()
         WHERE id=$1`,
        [artifactId],
      );
      throw new ConflictError("artifact size or stored-object sha256 did not verify");
    }
    const uri = `s3://${this.config.bucket}/${String(row.object_key)}`;
    const updated = await this.pool.query(
      `UPDATE fabric_artifacts SET status='available',storage_uri=$2,etag=$3,
         available_at=now(),last_error=NULL,updated_at=now()
       WHERE id=$1 RETURNING *`,
      [artifactId, uri, head.ETag ?? null],
    );
    return record(updated.rows[0] as Record<string, unknown>);
  }

  async finalizeRecovery(
    artifactId: string,
    input: ArtifactRecoveryFinalize,
  ): Promise<ArtifactRecord> {
    const authorized = await this.pool.query(
      `SELECT fa.*
       FROM fabric_artifacts fa
       JOIN fabric_attempts a ON a.id=fa.attempt_id
       JOIN fabric_workers w ON w.worker_id=a.worker_id
       JOIN fabric_worker_sessions ws ON ws.id=w.current_session_id
       CROSS JOIN fabric_state s
       WHERE fa.id=$1 AND fa.task_id=$2 AND fa.attempt_id=$3
         AND a.worker_id=$4
         AND a.recovery_token=$7
         AND w.registration_token=$5 AND w.registered_epoch=$6
         AND w.registered_epoch=s.current_epoch AND w.lease_expires_at > now()
         AND ws.registration_token=$5 AND ws.fabric_epoch=$6
         AND ws.status='active' AND ws.lease_expires_at > now()
         AND s.singleton=true`,
      [
        artifactId,
        input.taskId,
        input.attemptId,
        input.workerId,
        input.registrationToken,
        input.fabricEpoch,
        input.attemptRecoveryToken,
      ],
    );
    if (!authorized.rowCount) {
      throw new NotFoundError("artifact recovery upload not found");
    }
    return this.verifyStoredObject(
      artifactId,
      authorized.rows[0] as Record<string, unknown>,
    );
  }

  private async verifyStoredObject(
    artifactId: string,
    row: Record<string, unknown>,
  ): Promise<ArtifactRecord> {
    if (row.status === "available") return record(row);
    let head;
    try {
      head = await this.client.send(
        new HeadObjectCommand({
          Bucket: this.config.bucket,
          Key: String(row.object_key),
        }),
      );
    } catch (error) {
      await this.pool.query(
        `UPDATE fabric_artifacts SET status='failed',last_error=$2,updated_at=now()
         WHERE id=$1`,
        [artifactId, error instanceof Error ? error.name : "head_failed"],
      );
      throw new ConflictError("artifact object is not available for verification");
    }
    let actualSha256 = "";
    try {
      const object = await this.client.send(
        new GetObjectCommand({
          Bucket: this.config.bucket,
          Key: String(row.object_key),
        }),
      );
      const bytes = await object.Body?.transformToByteArray();
      if (!bytes) throw new Error("object_body_unavailable");
      actualSha256 = createHash("sha256").update(bytes).digest("hex");
    } catch (error) {
      await this.pool.query(
        `UPDATE fabric_artifacts SET status='failed',last_error=$2,updated_at=now()
         WHERE id=$1`,
        [artifactId, error instanceof Error ? error.name : "digest_read_failed"],
      );
      throw new ConflictError("artifact object could not be read for verification");
    }
    if (
      Number(head.ContentLength) !== Number(row.size_bytes) ||
      actualSha256 !== String(row.sha256)
    ) {
      await this.pool.query(
        `UPDATE fabric_artifacts SET status='failed',
           last_error='metadata_verification_failed',updated_at=now()
         WHERE id=$1`,
        [artifactId],
      );
      throw new ConflictError("artifact size or stored-object sha256 did not verify");
    }
    const uri = `s3://${this.config.bucket}/${String(row.object_key)}`;
    const updated = await this.pool.query(
      `UPDATE fabric_artifacts SET status='available',storage_uri=$2,etag=$3,
         available_at=now(),last_error=NULL,updated_at=now()
       WHERE id=$1 RETURNING *`,
      [artifactId, uri, head.ETag ?? null],
    );
    return record(updated.rows[0] as Record<string, unknown>);
  }

  async download(artifactId: string): Promise<{
    artifact: ArtifactRecord;
    downloadUrl: string;
    expiresAt: string;
  }> {
    const result = await this.pool.query(
      "SELECT * FROM fabric_artifacts WHERE id=$1 AND status='available'",
      [artifactId],
    );
    if (!result.rowCount) throw new NotFoundError("available artifact not found");
    const row = result.rows[0] as Record<string, unknown>;
    const downloadUrl = await getSignedUrl(
      this.client,
      new GetObjectCommand({
        Bucket: this.config.bucket,
        Key: String(row.object_key),
      }),
      { expiresIn: this.config.downloadTtlSeconds },
    );
    return {
      artifact: record(row),
      downloadUrl,
      expiresAt: new Date(
        Date.now() + this.config.downloadTtlSeconds * 1000,
      ).toISOString(),
    };
  }

  async snapshot(limit = 200): Promise<{
    counts: Record<string, number>;
    recent: ArtifactRecord[];
    objectStore: Awaited<ReturnType<ArtifactStore["health"]>>;
  }> {
    const [counts, recent, objectStore] = await Promise.all([
      this.pool.query<{ status: string; count: string }>(
        `SELECT status,count(*)::text AS count
         FROM fabric_artifacts GROUP BY status ORDER BY status`,
      ),
      this.pool.query(
        `SELECT * FROM fabric_artifacts ORDER BY created_at DESC,id LIMIT $1`,
        [limit],
      ),
      this.health(),
    ]);
    return {
      counts: Object.fromEntries(
        counts.rows.map((row) => [row.status, Number(row.count)]),
      ),
      recent: recent.rows.map((row) => record(row as Record<string, unknown>)),
      objectStore,
    };
  }

  async forTask(taskId: string): Promise<ArtifactRecord[]> {
    const result = await this.pool.query(
      `SELECT * FROM fabric_artifacts
       WHERE task_id=$1 ORDER BY created_at,id`,
      [taskId],
    );
    return result.rows.map((row) => record(row as Record<string, unknown>));
  }
}
