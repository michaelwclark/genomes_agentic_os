import "dotenv/config";
import {
  PostgresReliabilityStore,
  DeterministicHealer,
  type RepairAction,
} from "./reliability.js";
import {
  allowListEnvironment,
  boundedIntegerEnvironment,
  PostgresRoleHealthStore,
  recordRoleFailure,
  runPeriodicRole,
  validateRoleHealthInterval,
} from "./roles.js";
import { buildFabricRuntime } from "./runtime.js";

const runtime = await buildFabricRuntime();
const store = new PostgresReliabilityStore(runtime.pool, runtime.config.hostId);
const controller = new AbortController();
const intervalMs = boundedIntegerEnvironment(
  "FABRIC_HEALER_INTERVAL_MS",
  15000,
  1000,
  300000,
);
validateRoleHealthInterval(intervalMs);
const supportedRepairActions = [
  "reconcile_expired_attempts",
  "reconstruct_delivery",
  "recover_effect_claim",
] as const satisfies readonly RepairAction[];
const healer = new DeterministicHealer(
  store,
  runtime.fabric,
  {
    allowActions: allowListEnvironment(
      "FABRIC_HEALER_ALLOW_ACTIONS",
      supportedRepairActions,
      supportedRepairActions,
    ),
    cooldownSeconds: boundedIntegerEnvironment(
      "FABRIC_HEALER_COOLDOWN_SECONDS",
      60,
      0,
      86400,
    ),
    maxRepairsPerHour: boundedIntegerEnvironment(
      "FABRIC_HEALER_MAX_REPAIRS_PER_HOUR",
      30,
      1,
      1000,
    ),
  },
  `healer:${runtime.config.hostId}`,
);
const roleHealth = new PostgresRoleHealthStore(
  runtime.pool,
  runtime.config.hostId,
  "healer",
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
          role: "healer",
          event: "startup_role_health_write_failed",
          error: healthError instanceof Error ? healthError.message : "unknown role health failure",
        })}\n`);
      },
    });
  } catch (healthError) {
    process.stderr.write(`${JSON.stringify({
      role: "healer",
      event: "startup_role_health_fenced",
      error: healthError instanceof Error ? healthError.message : "role health instance replaced",
    })}\n`);
  }
  throw error;
}
await runPeriodicRole({
  role: "healer",
  intervalMs,
  signal: controller.signal,
  once: process.env.FABRIC_RUN_ONCE === "1",
  tick: async () => {
    await runtime.fabric.synchronizePolicy();
    const state = await runtime.ledger.systemSnapshot();
    const receipts = await healer.runOnce();
    await roleHealth.success(
      state.databasePolicyFingerprint,
      runtime.policy.snapshot().appliedFingerprint,
    );
    process.stdout.write(
      `${JSON.stringify({
        role: "healer",
        sampledAt: new Date().toISOString(),
        repairs: receipts,
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
          role: "healer",
          event: "role_health_write_failed",
          error: healthError instanceof Error ? healthError.message : "unknown role health failure",
        })}\n`);
      },
    });
    process.stderr.write(
      `${JSON.stringify({
        role: "healer",
        error: error instanceof Error ? error.message : "unknown healer failure",
      })}\n`,
    );
  },
});
await shutdown();
