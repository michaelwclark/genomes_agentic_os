import "dotenv/config";
import { loadConfig } from "./config.js";
import { createPool, migrate } from "./db.js";
import { PolicyManager } from "./policy.js";
import { PostgresReliabilityStore } from "./reliability.js";
import { boundedIntegerEnvironment, runPeriodicRole } from "./roles.js";
import { ArtifactStore } from "./artifacts.js";

const config = loadConfig();
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
let stopping = false;

async function shutdown(): Promise<void> {
  if (stopping) return;
  stopping = true;
  controller.abort();
  await pool.end();
}

process.once("SIGINT", () => void shutdown());
process.once("SIGTERM", () => void shutdown());

await runPeriodicRole({
  role: "observer",
  intervalMs,
  signal: controller.signal,
  once: process.env.FABRIC_RUN_ONCE === "1",
  tick: async () => {
    const epoch = await store.currentEpoch();
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
    const findings = await store.persistObservations(observations, epoch);
    process.stdout.write(
      `${JSON.stringify({
        role: "observer",
        sampledAt: new Date().toISOString(),
        observations: observations.length,
        openFindings: findings.length,
        fabricEpoch: epoch,
      })}\n`,
    );
  },
  onError: (error) => {
    process.stderr.write(
      `${JSON.stringify({
        role: "observer",
        error: error instanceof Error ? error.message : "unknown observer failure",
      })}\n`,
    );
  },
});
await shutdown();
