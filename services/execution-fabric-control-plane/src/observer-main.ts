import "dotenv/config";
import { loadObserverConfig } from "./config.js";
import { createPool, migrate } from "./db.js";
import { PolicyError, PolicyManager } from "./policy.js";
import { PostgresReliabilityStore } from "./reliability.js";
import {
  boundedIntegerEnvironment,
  PostgresRoleHealthStore,
  recordRoleFailure,
  runPeriodicRole,
  validateRoleHealthInterval,
} from "./roles.js";
import { ArtifactStore } from "./artifacts.js";

const config = loadObserverConfig();
const pool = createPool(config.databaseUrl);
await migrate(pool);
const policy = new PolicyManager(config.policyConfigPath, config.policySchemaPath);
const store = new PostgresReliabilityStore(pool, config.hostId);
const artifacts = new ArtifactStore(
  pool,
  config.artifactStore,
  config.clusterId,
);
const controller = new AbortController();
const intervalMs = boundedIntegerEnvironment(
  "FABRIC_OBSERVER_INTERVAL_MS",
  15000,
  1000,
  300000,
);
validateRoleHealthInterval(intervalMs);
const roleHealth = new PostgresRoleHealthStore(pool, config.hostId, "observer");
let stopping = false;

async function shutdown(): Promise<void> {
  if (stopping) return;
  stopping = true;
  controller.abort();
  await pool.end();
}

process.once("SIGINT", () => void shutdown());
process.once("SIGTERM", () => void shutdown());

await roleHealth.start(policy.snapshot().appliedFingerprint);
await runPeriodicRole({
  role: "observer",
  intervalMs,
  signal: controller.signal,
  once: process.env.FABRIC_RUN_ONCE === "1",
  tick: async () => {
    const state = await store.observerState();
    try {
      policy.synchronizeApprovedFingerprint(
        state.databasePolicyFingerprint,
      );
    } catch (error) {
      // The observer remains useful during invalid/unapproved drift: collect()
      // turns the PolicyError state into a durable config_drift finding. Any
      // unrelated error still fails the tick.
      if (!(error instanceof PolicyError)) throw error;
    }
    const observations = await store.collect(policy.check());
    const objectStore = await artifacts.health();
    if (objectStore.status !== "healthy") {
      observations.push({
        kind: "object_store_unavailable",
        scopeType: "fabric",
        scopeId: "run-artifacts",
        severity: "critical",
        summary: "Execution Fabric object store is unavailable",
        details: objectStore,
      });
    }
    const findings = await store.persistObservations(
      observations,
      state.fabricEpoch,
    );
    await roleHealth.success(
      state.databasePolicyFingerprint,
      policy.snapshot().appliedFingerprint,
    );
    process.stdout.write(
      `${JSON.stringify({
        role: "observer",
        sampledAt: new Date().toISOString(),
        observations: observations.length,
        openFindings: findings.length,
        fabricEpoch: state.fabricEpoch,
      })}\n`,
    );
  },
  onError: async (error) => {
    let approved: string | null = null;
    try {
      approved = (await store.observerState()).databasePolicyFingerprint;
    } catch {
      // The tick error remains the durable role error.
    }
    await recordRoleFailure({
      store: roleHealth,
      error,
      approvedPolicyFingerprint: approved,
      appliedPolicyFingerprint: policy.snapshot().appliedFingerprint,
      onReportingError: (healthError) => {
        process.stderr.write(`${JSON.stringify({
          role: "observer",
          event: "role_health_write_failed",
          error: healthError instanceof Error ? healthError.message : "unknown role health failure",
        })}\n`);
      },
    });
    process.stderr.write(
      `${JSON.stringify({
        role: "observer",
        error: error instanceof Error ? error.message : "unknown observer failure",
      })}\n`,
    );
  },
});
await shutdown();
