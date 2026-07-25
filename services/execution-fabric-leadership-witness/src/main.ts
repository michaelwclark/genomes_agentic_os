import "dotenv/config";
import { loadConfig } from "./config.js";
import { buildServer } from "./server.js";
import { SqliteWitnessStore } from "./sqlite-store.js";
import { LeadershipWitness } from "./witness.js";

const config = loadConfig();
const store = new SqliteWitnessStore(config.stateFile, config.clusterId, {
  allowInitialBootstrap: config.bootstrapOnce,
  leaseDurationMs: config.processLeaseSeconds * 1000,
});
const witness = new LeadershipWitness(config, store);
await witness.initialize();
const server = buildServer(config, witness);

const shutdown = async (signal: string) => {
  server.log.info({ signal }, "leadership witness stopping");
  await server.close();
  await store.close();
  process.exit(0);
};
process.once("SIGTERM", () => void shutdown("SIGTERM"));
process.once("SIGINT", () => void shutdown("SIGINT"));

await server.listen({ host: config.host, port: config.port });
