import "dotenv/config";
import {
  boundedIntegerEnvironment,
  PostgresRoleHealthStore,
  recordRoleFailure,
  runPeriodicRole,
} from "./roles.js";
import { buildFabricRuntime } from "./runtime.js";

const runtime = await buildFabricRuntime();
const scheduler = runtime.scheduler;
const controller = new AbortController();
const intervalMs = boundedIntegerEnvironment(
  "FABRIC_SCHEDULER_INTERVAL_MS",
  15000,
  1000,
  300000,
);
const batchSize = boundedIntegerEnvironment(
  "FABRIC_SCHEDULER_BATCH_SIZE",
  20,
  1,
  500,
);
const roleHealth = new PostgresRoleHealthStore(
  runtime.pool,
  runtime.config.hostId,
  "scheduler",
);
let stopping = false;

async function shutdown(): Promise<void> {
  if (stopping) return;
  stopping = true;
  controller.abort();
  runtime.leadership.stop();
  await runtime.delivery.close();
  await runtime.pool.end();
}

process.once("SIGINT", () => void shutdown());
process.once("SIGTERM", () => void shutdown());

await roleHealth.start(runtime.policy.snapshot().appliedFingerprint);
try {
  await runtime.leadership.start();
  await runtime.fabric.initialize();
} catch (error) {
  let approved: string | null = null;
  try {
    approved = (await runtime.ledger.systemSnapshot()).databasePolicyFingerprint;
  } catch {
    // The primary startup error is retained below.
  }
  try {
    await recordRoleFailure({
      store: roleHealth,
      error,
      approvedPolicyFingerprint: approved,
      appliedPolicyFingerprint: runtime.policy.snapshot().appliedFingerprint,
      onReportingError: (healthError) => {
        process.stderr.write(`${JSON.stringify({
          role: "scheduler",
          event: "startup_role_health_write_failed",
          error: healthError instanceof Error ? healthError.message : "unknown role health failure",
        })}\n`);
      },
    });
  } catch (healthError) {
    process.stderr.write(`${JSON.stringify({
      role: "scheduler",
      event: "startup_role_health_fenced",
      error: healthError instanceof Error ? healthError.message : "role health instance replaced",
    })}\n`);
  }
  throw error;
}
await runPeriodicRole({
  role: "scheduler",
  intervalMs,
  signal: controller.signal,
  once: process.env.FABRIC_RUN_ONCE === "1",
  tick: async () => {
    await runtime.fabric.synchronizePolicy();
    const state = await runtime.ledger.systemSnapshot();
    const receipt = await scheduler.runOnce(batchSize);
    await roleHealth.success(
      state.databasePolicyFingerprint,
      runtime.policy.snapshot().appliedFingerprint,
    );
    process.stdout.write(
      `${JSON.stringify({
        role: "scheduler",
        sampledAt: new Date().toISOString(),
        ...receipt,
      })}\n`,
    );
  },
  onError: async (error) => {
    let approved: string | null = null;
    try {
      approved = (await runtime.ledger.systemSnapshot()).databasePolicyFingerprint;
    } catch {
      // The tick error remains the durable role error.
    }
    await recordRoleFailure({
      store: roleHealth,
      error,
      approvedPolicyFingerprint: approved,
      appliedPolicyFingerprint: runtime.policy.snapshot().appliedFingerprint,
      onReportingError: (healthError) => {
        process.stderr.write(`${JSON.stringify({
          role: "scheduler",
          event: "role_health_write_failed",
          error: healthError instanceof Error ? healthError.message : "unknown role health failure",
        })}\n`);
      },
    });
    process.stderr.write(
      `${JSON.stringify({
        role: "scheduler",
        error: error instanceof Error ? error.message : "unknown scheduler failure",
      })}\n`,
    );
  },
});
await shutdown();
