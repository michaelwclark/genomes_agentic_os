import "dotenv/config";
import { createPool } from "./db.js";
import { loadObserverConfig } from "./config.js";
import {
  evaluateRoleHealth,
  roleHealthEvaluationOptions,
  roleHealthSnapshot,
  type PeriodicServiceRole,
} from "./roles.js";

const role = process.argv[2] as PeriodicServiceRole | undefined;
if (!role || !["observer", "healer", "scheduler"].includes(role)) {
  process.stderr.write("usage: role-healthcheck observer|healer|scheduler\n");
  process.exit(64);
}

const config = loadObserverConfig();
const pool = createPool(config.databaseUrl);
try {
  const result = await pool.query(
    `SELECT * FROM fabric_role_health WHERE host_id=$1 AND role=$2`,
    [config.hostId, role],
  );
  if (!result.rows[0]) {
    process.stderr.write(`no role health receipt for ${config.hostId}/${role}\n`);
    process.exitCode = 1;
  } else {
    const evaluation = evaluateRoleHealth(
      roleHealthSnapshot(result.rows[0] as Record<string, unknown>),
      roleHealthEvaluationOptions(),
    );
    process.stdout.write(`${JSON.stringify(evaluation)}\n`);
    process.exitCode = evaluation.status === "unhealthy" ? 1 : 0;
  }
} finally {
  await pool.end();
}
