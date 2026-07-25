import { readFile, readdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import pg from "pg";

const { Pool } = pg;

export function createPool(databaseUrl: string): pg.Pool {
  return new Pool({
    connectionString: databaseUrl,
    max: 20,
    connectionTimeoutMillis: 5000,
    idleTimeoutMillis: 30000,
    application_name: "agentic-os-execution-fabric",
  });
}

export async function migrate(pool: pg.Pool): Promise<void> {
  const client = await pool.connect();
  try {
    await client.query("SELECT pg_advisory_lock(hashtext($1))", [
      "agentic-os-execution-fabric-migrations",
    ]);
    await client.query(`
      CREATE TABLE IF NOT EXISTS fabric_schema_migrations (
        version text PRIMARY KEY,
        applied_at timestamptz NOT NULL DEFAULT now()
      )
    `);
    const migrationDirectory = join(
      dirname(fileURLToPath(import.meta.url)),
      "../migrations",
    );
    const files = (await readdir(migrationDirectory))
      .filter((name) => /^\d{3}_[a-z0-9_]+\.sql$/.test(name))
      .sort();
    for (const file of files) {
      const version = file.slice(0, -4);
      const exists = await client.query<{ version: string }>(
        "SELECT version FROM fabric_schema_migrations WHERE version = $1",
        [version],
      );
      if (exists.rowCount !== 0) continue;
      await client.query("BEGIN");
      try {
        await client.query(
          await readFile(join(migrationDirectory, file), "utf8"),
        );
        await client.query(
          `INSERT INTO fabric_schema_migrations(version) VALUES ($1)
           ON CONFLICT DO NOTHING`,
          [version],
        );
        await client.query("COMMIT");
      } catch (error) {
        await client.query("ROLLBACK");
        throw error;
      }
    }
  } finally {
    await client
      .query("SELECT pg_advisory_unlock(hashtext($1))", [
        "agentic-os-execution-fabric-migrations",
      ])
      .catch(() => undefined);
    client.release();
  }
}
