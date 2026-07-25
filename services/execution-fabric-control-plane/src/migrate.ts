import "dotenv/config";
import { loadConfig } from "./config.js";
import { createPool, migrate } from "./db.js";

const config = loadConfig();
const pool = createPool(config.databaseUrl);

try {
  await migrate(pool);
  process.stdout.write("execution-fabric migrations applied\n");
} finally {
  await pool.end();
}
