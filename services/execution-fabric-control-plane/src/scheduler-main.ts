import "dotenv/config";
import { boundedIntegerEnvironment, runPeriodicRole } from "./roles.js";
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

await runtime.leadership.start();
await runtime.fabric.initialize();
await runPeriodicRole({
  role: "scheduler",
  intervalMs,
  signal: controller.signal,
  once: process.env.FABRIC_RUN_ONCE === "1",
  tick: async () => {
    await runtime.fabric.synchronizePolicy();
    const receipt = await scheduler.runOnce(batchSize);
    process.stdout.write(
      `${JSON.stringify({
        role: "scheduler",
        sampledAt: new Date().toISOString(),
        ...receipt,
      })}\n`,
    );
  },
  onError: (error) => {
    process.stderr.write(
      `${JSON.stringify({
        role: "scheduler",
        error: error instanceof Error ? error.message : "unknown scheduler failure",
      })}\n`,
    );
  },
});
await shutdown();
