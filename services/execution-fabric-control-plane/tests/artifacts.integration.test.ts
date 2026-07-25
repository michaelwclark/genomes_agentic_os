import { randomUUID } from "node:crypto";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { ArtifactStore } from "../src/artifacts.js";
import { createPool, migrate } from "../src/db.js";

const enabled = process.env.FABRIC_INTEGRATION_TESTS === "1";
const describeIntegration = enabled ? describe : describe.skip;
const databaseUrl =
  process.env.FABRIC_TEST_DATABASE_URL ??
  "postgresql://fabric:fabric@127.0.0.1:5432/execution_fabric";
const objectEndpoint =
  process.env.FABRIC_TEST_ARTIFACT_ENDPOINT ?? "http://127.0.0.1:9000";
const objectBucket =
  process.env.FABRIC_TEST_ARTIFACT_BUCKET ?? "execution-fabric-artifacts";
const objectAccessKey = process.env.FABRIC_TEST_ARTIFACT_ACCESS_KEY ?? "fabricminio";
const objectSecretKey =
  process.env.FABRIC_TEST_ARTIFACT_SECRET_KEY ?? "fabricminiosecret";

describeIntegration("portable run artifact integration", () => {
  const pool = createPool(databaseUrl);
  const taskId = randomUUID();
  const runId = randomUUID();
  const attemptId = randomUUID();
  const leaseToken = randomUUID();
  const registrationToken = randomUUID();
  const recoveryToken = randomUUID();
  const workerSessionId = randomUUID();
  const workerId = `artifact-worker-${randomUUID()}`;

  beforeAll(async () => {
    await migrate(pool);
    await pool.query(
      "UPDATE fabric_state SET current_epoch=1 WHERE singleton=true",
    );
    await pool.query(
      `INSERT INTO fabric_workers(
         worker_id,bootstrap_id,host_id,pool_id,provider,queues,capabilities,max_concurrency,
         metadata,registration_token,registered_epoch,config_fingerprint,
         lease_expires_at
       ) VALUES($1,$1,'integration-host','integration','process','[]','[]',1,'{}',
         $2,1,$3,now()+interval '5 minutes')`,
      [workerId, registrationToken, "a".repeat(64)],
    );
    await pool.query(
      `INSERT INTO fabric_worker_sessions(
         id,worker_id,bootstrap_id,registration_token,host_id,pool_id,provider,
         fabric_epoch,config_fingerprint,metadata,lease_expires_at
       ) VALUES($1,$2,$2,$3,'integration-host','integration','process',
         1,$4,'{}',now()+interval '5 minutes')`,
      [workerSessionId, workerId, registrationToken, "a".repeat(64)],
    );
    await pool.query(
      "UPDATE fabric_workers SET current_session_id=$2 WHERE worker_id=$1",
      [workerId, workerSessionId],
    );
    await pool.query(
      `INSERT INTO fabric_tasks(
         id,namespace,queue_name,task_type,idempotency_key,request_hash,payload,
         required_capabilities,priority,status,max_attempts,provider,
         retry_backoff_seconds,config_fingerprint,attempt_count
       ) VALUES($1,'integration','artifacts','integration.run',$2,$3,'{}','[]',
         0,'running',3,'process',10,$4,1)`,
      [taskId, randomUUID(), "b".repeat(64), "a".repeat(64)],
    );
    await pool.query(
      `INSERT INTO fabric_runs(id,task_id,run_number,status)
       VALUES($1,$2,1,'running')`,
      [runId, taskId],
    );
    await pool.query(
      `INSERT INTO fabric_attempts(
         id,task_id,run_id,worker_id,attempt_number,status,lease_token,
         fabric_epoch,lease_duration_seconds,lease_expires_at,worker_session_id,
         recovery_token
       ) VALUES($1,$2,$3,$4,1,'running',$5,1,120,now()+interval '2 minutes',
         $6,$7)`,
      [
        attemptId,
        taskId,
        runId,
        workerId,
        leaseToken,
        workerSessionId,
        recoveryToken,
      ],
    );
  });

  afterAll(async () => {
    await pool.query("DELETE FROM fabric_artifacts WHERE task_id=$1", [taskId]);
    await pool.query("DELETE FROM fabric_attempts WHERE task_id=$1", [taskId]);
    await pool.query("DELETE FROM fabric_runs WHERE task_id=$1", [taskId]);
    await pool.query("DELETE FROM fabric_tasks WHERE id=$1", [taskId]);
    await pool.query(
      "UPDATE fabric_workers SET current_session_id=NULL WHERE worker_id=$1",
      [workerId],
    );
    await pool.query("DELETE FROM fabric_worker_sessions WHERE worker_id=$1", [
      workerId,
    ]);
    await pool.query("DELETE FROM fabric_workers WHERE worker_id=$1", [workerId]);
    await pool.end();
  });

  it("uploads, verifies, and lists a task-attempt artifact", async () => {
    const store = new ArtifactStore(
      pool,
      {
        endpoint: objectEndpoint,
        region: "us-east-1",
        bucket: objectBucket,
        accessKeyId: objectAccessKey,
        secretAccessKey: objectSecretKey,
        forcePathStyle: true,
        uploadTtlSeconds: 300,
        downloadTtlSeconds: 300,
        maxBytes: 1024 * 1024,
      },
      "integration",
    );
    await store.ping();
    const body = Buffer.from('{"status":"succeeded"}\n');
    const digest =
      "822305d9edc89df2b273f03fc308155652235dad79ed8399e02d1c89fc699619";
    const initiated = await store.initiate({
      taskId,
      attemptId,
      workerId,
      leaseToken,
      fabricEpoch: 1,
      name: "run-report.json",
      contentType: "application/json",
      sha256: digest,
      sizeBytes: body.length,
    });
    expect(initiated.upload?.url).toMatch(/^http/);
    const uploaded = await fetch(initiated.upload!.url, {
      method: "PUT",
      headers: initiated.upload!.headers,
      body,
    });
    expect(
      uploaded.ok,
      `MinIO PUT ${uploaded.status}: ${await uploaded.text()}`,
    ).toBe(true);
    const artifact = await store.finalize(initiated.artifact.artifactId, {
      taskId,
      attemptId,
      workerId,
      leaseToken,
      fabricEpoch: 1,
    });
    expect(artifact.status).toBe("available");
    expect(artifact.uri).toMatch(/^s3:/);
    expect(await store.forTask(taskId)).toHaveLength(1);
    const download = await store.download(artifact.artifactId);
    expect((await fetch(download.downloadUrl)).status).toBe(200);

    const recoveredBody = Buffer.from('{"status":"recovered"}\n');
    const recoveredDigest =
      "49b99a8934ed9f4ea1dc2e37e2b60166f3fbf05d22c09fc1a8db7f0a563390a2";
    const recovered = await store.initiateRecovery({
      taskId,
      attemptId,
      workerId,
      registrationToken,
      attemptRecoveryToken: recoveryToken,
      fabricEpoch: 1,
      name: "recovered-report.json",
      contentType: "application/json",
      sha256: recoveredDigest,
      sizeBytes: recoveredBody.length,
    });
    const recoveredUpload = await fetch(recovered.upload!.url, {
      method: "PUT",
      headers: recovered.upload!.headers,
      body: recoveredBody,
    });
    expect(
      recoveredUpload.ok,
      `MinIO recovery PUT ${recoveredUpload.status}: ${await recoveredUpload.text()}`,
    ).toBe(true);
    const recoveredArtifact = await store.finalizeRecovery(
      recovered.artifact.artifactId,
      {
        taskId,
        attemptId,
        workerId,
        registrationToken,
        attemptRecoveryToken: recoveryToken,
        fabricEpoch: 1,
      },
    );
    expect(recoveredArtifact.status).toBe("available");
    expect(await store.forTask(taskId)).toHaveLength(2);
  });
});
