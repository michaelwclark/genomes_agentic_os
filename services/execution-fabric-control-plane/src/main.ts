import "dotenv/config";
import { PostgresReliabilityStore } from "./reliability.js";
import { buildFabricRuntime } from "./runtime.js";
import { buildServer } from "./server.js";

const runtime = await buildFabricRuntime();
const reliability = new PostgresReliabilityStore(
  runtime.pool,
  runtime.config.hostId,
);
const server = buildServer(runtime.config, runtime.fabric, {
  reliability,
  artifacts: runtime.artifacts,
  scheduler: runtime.scheduler,
});
let stopping = false;

async function shutdown(signal: string): Promise<void> {
  if (stopping) return;
  stopping = true;
  server.log.info({ signal }, "shutting down");
  runtime.leadership.stop();
  await server.close();
  await runtime.delivery.close();
  await runtime.pool.end();
}

process.once("SIGINT", () => void shutdown("SIGINT"));
process.once("SIGTERM", () => void shutdown("SIGTERM"));

await runtime.leadership.start();
await runtime.fabric.initialize();
await server.listen({
  host: runtime.config.host,
  port: runtime.config.port,
});
