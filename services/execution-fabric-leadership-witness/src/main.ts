import "dotenv/config";
import { loadConfig } from "./config.js";
import { DynamoWitnessStore } from "./dynamo-store.js";
import { buildServer } from "./server.js";
import { LeadershipWitness } from "./witness.js";

const config = loadConfig();
const store = new DynamoWitnessStore(config.tableName, config.clusterId, {
  region: config.region,
  ...(config.dynamoEndpoint ? { endpoint: config.dynamoEndpoint } : {}),
});
const witness = new LeadershipWitness(config, store);
await witness.initialize();
const server = buildServer(config, witness);

const shutdown = async (signal: string) => {
  server.log.info({ signal }, "leadership witness stopping");
  await server.close();
  process.exit(0);
};
process.once("SIGTERM", () => void shutdown("SIGTERM"));
process.once("SIGINT", () => void shutdown("SIGINT"));

await server.listen({ host: config.host, port: config.port });
