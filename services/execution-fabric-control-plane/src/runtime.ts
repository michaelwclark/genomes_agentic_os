import { loadConfig } from "./config.js";
import { createPool, migrate } from "./db.js";
import { BullMqDelivery } from "./delivery.js";
import { ExecutionFabric } from "./fabric.js";
import { LeadershipGuard } from "./leadership.js";
import { PostgresLedger } from "./ledger.js";
import { PolicyManager } from "./policy.js";
import { ArtifactStore } from "./artifacts.js";
import {
  measurePostgresMutationDurability,
  measurePostgresReplication,
} from "./postgres-replication.js";
import { PostgresScheduler } from "./scheduler.js";

export async function buildFabricRuntime() {
  const config = loadConfig();
  const pool = createPool(config.databaseUrl);
  await migrate(pool);
  const ledger = new PostgresLedger(
    pool,
    config.workerTtlSeconds,
    config.hostId,
  );
  const delivery = new BullMqDelivery(config.valkeyUrl, config.queuePrefix);
  const policy = new PolicyManager(
    config.policyConfigPath,
    config.policySchemaPath,
  );
  const artifacts = new ArtifactStore(
    pool,
    config.artifactStore,
    config.clusterId,
  );
  const leadership = new LeadershipGuard(
    {
      clusterId: config.clusterId,
      hostId: config.hostId,
      witnessBaseUrl: config.leadershipApiBase,
      witnessToken: config.leadershipToken,
      witnessCandidateToken: config.leadershipCandidateToken,
      witnessPublicKey: config.leadershipPublicKey,
      ...(config.leadershipReceiptPath
        ? { receiptPath: config.leadershipReceiptPath }
        : {}),
      refreshMs: config.leadershipRefreshMs,
      recoveryHoldSeconds: config.leadershipRecoveryHoldSeconds,
      degradedPolicy: () =>
        policy.effective().execution_fabric.degraded_primary,
    },
    ledger,
    () => policy.snapshot().appliedFingerprint,
    {
      replicationProbe: () => measurePostgresReplication(pool),
      durabilityProbe: () => measurePostgresMutationDurability(pool),
    },
  );
  const fabric = new ExecutionFabric(
    ledger,
    delivery,
    config.leaseSeconds,
    config.longPollMs,
    policy,
    leadership,
  );
  const scheduler = new PostgresScheduler(pool, fabric, config.hostId);
  return {
    config,
    pool,
    ledger,
    delivery,
    policy,
    leadership,
    artifacts,
    fabric,
    scheduler,
  };
}
