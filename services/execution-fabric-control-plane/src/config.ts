import { readFileSync } from "node:fs";
import { z } from "zod";

const environmentSchema = z.object({
  FABRIC_HOST: z.string().default("0.0.0.0"),
  FABRIC_PORT: z.coerce.number().int().min(1).max(65535).default(3180),
  FABRIC_HOST_ID: z.string().min(1).max(128),
  FABRIC_DATABASE_URL: z.string().url(),
  FABRIC_VALKEY_URL: z.string().url(),
  FABRIC_QUEUE_PREFIX: z
    .string()
    .regex(/^[a-zA-Z0-9:_-]+$/)
    .default("agentic-os:fabric"),
  FABRIC_LEASE_SECONDS: z.coerce.number().int().min(10).max(3600).default(120),
  FABRIC_WORKER_TTL_SECONDS: z.coerce.number().int().min(10).max(600).default(45),
  FABRIC_LONG_POLL_MS: z.coerce.number().int().min(0).max(30000).default(15000),
  FABRIC_RECONCILE_INTERVAL_MS: z.coerce
    .number()
    .int()
    .min(1000)
    .max(300000)
    .default(10000),
  FABRIC_METRICS_PREFIX: z
    .string()
    .regex(/^[a-zA-Z_:][a-zA-Z0-9_:]*$/)
    .default("agentic_os_fabric_"),
  FABRIC_POLICY_CONFIG_FILE: z.string().min(1),
  FABRIC_POLICY_SCHEMA_FILE: z.string().min(1),
  FABRIC_SUBMIT_TOKEN_FILE: z.string().min(1),
  FABRIC_WORKER_BOOTSTRAP_CREDENTIALS_FILE: z.string().min(1),
  FABRIC_API_TOKEN_FILE: z.string().min(1),
  FABRIC_ADMIN_TOKEN_FILE: z.string().min(1),
  FABRIC_RELIABILITY_SOURCE_TOKENS_FILE: z.string().min(1),
  FABRIC_EFFECT_CONSUMER_CREDENTIALS_FILE: z.string().min(1),
  FABRIC_ALARM_DISPATCHER_CREDENTIALS_FILE: z.string().min(1),
  FABRIC_ARTIFACT_ENDPOINT: z.string().url().default("http://minio:9000"),
  FABRIC_ARTIFACT_REGION: z.string().min(1).max(64).default("us-east-1"),
  FABRIC_ARTIFACT_BUCKET: z
    .string()
    .min(3)
    .max(63)
    .regex(/^[a-z0-9][a-z0-9.-]+[a-z0-9]$/)
    .default("execution-fabric-artifacts"),
  FABRIC_ARTIFACT_ACCESS_KEY_FILE: z.string().min(1),
  FABRIC_ARTIFACT_SECRET_KEY_FILE: z.string().min(1),
  FABRIC_ARTIFACT_FORCE_PATH_STYLE: z
    .enum(["true", "false"])
    .default("true"),
  FABRIC_ARTIFACT_UPLOAD_TTL_SECONDS: z.coerce
    .number()
    .int()
    .min(60)
    .max(900)
    .default(300),
  FABRIC_ARTIFACT_DOWNLOAD_TTL_SECONDS: z.coerce
    .number()
    .int()
    .min(60)
    .max(3600)
    .default(300),
  FABRIC_ARTIFACT_MAX_BYTES: z.coerce
    .number()
    .int()
    .min(1024)
    .max(104857600)
    .default(10485760),
  FABRIC_CLUSTER_ID: z.string().regex(/^[a-zA-Z0-9._-]{1,128}$/),
  FABRIC_LEADERSHIP_API_BASE: z.string().url(),
  FABRIC_LEADERSHIP_TOKEN_FILE: z.string().min(1),
  FABRIC_LEADERSHIP_CANDIDATE_TOKEN_FILE: z.string().min(1),
  FABRIC_LEADERSHIP_PUBLIC_KEY_FILE: z.string().min(1),
  FABRIC_LEADERSHIP_RECEIPT_FILE: z.string().min(1).optional(),
  FABRIC_LEADERSHIP_REFRESH_MS: z.coerce
    .number()
    .int()
    .min(1000)
    .max(60000)
    .default(10000),
  FABRIC_LEADERSHIP_RECOVERY_HOLD_SECONDS: z.coerce
    .number()
    .int()
    .min(0)
    .max(3600)
    .default(30),
  FABRIC_LOG_LEVEL: z
    .enum(["fatal", "error", "warn", "info", "debug", "trace", "silent"])
    .default("info"),
});

const observerEnvironmentSchema = z.object({
  FABRIC_HOST_ID: z.string().min(1).max(128),
  FABRIC_DATABASE_URL: z.string().url(),
  FABRIC_POLICY_CONFIG_FILE: z.string().min(1),
  FABRIC_POLICY_SCHEMA_FILE: z.string().min(1),
  FABRIC_ARTIFACT_ENDPOINT: z.string().url().default("http://minio:9000"),
  FABRIC_ARTIFACT_REGION: z.string().min(1).max(64).default("us-east-1"),
  FABRIC_ARTIFACT_BUCKET: z
    .string()
    .min(3)
    .max(63)
    .regex(/^[a-z0-9][a-z0-9.-]+[a-z0-9]$/)
    .default("execution-fabric-artifacts"),
  FABRIC_ARTIFACT_ACCESS_KEY_FILE: z.string().min(1),
  FABRIC_ARTIFACT_SECRET_KEY_FILE: z.string().min(1),
  FABRIC_ARTIFACT_FORCE_PATH_STYLE: z.enum(["true", "false"]).default("true"),
  FABRIC_ARTIFACT_UPLOAD_TTL_SECONDS: z.coerce
    .number()
    .int()
    .min(60)
    .max(900)
    .default(300),
  FABRIC_ARTIFACT_DOWNLOAD_TTL_SECONDS: z.coerce
    .number()
    .int()
    .min(60)
    .max(3600)
    .default(300),
  FABRIC_ARTIFACT_MAX_BYTES: z.coerce
    .number()
    .int()
    .min(1024)
    .max(104857600)
    .default(10485760),
  FABRIC_CLUSTER_ID: z.string().regex(/^[a-zA-Z0-9._-]{1,128}$/),
});

export type Config = {
  host: string;
  port: number;
  hostId: string;
  databaseUrl: string;
  valkeyUrl: string;
  queuePrefix: string;
  leaseSeconds: number;
  workerTtlSeconds: number;
  longPollMs: number;
  reconcileIntervalMs: number;
  metricsPrefix: string;
  policyConfigPath: string;
  policySchemaPath: string;
  submitToken: string;
  workerBootstrapCredentials: Record<
    string,
    {
      token: string;
      workerId: string;
      hostId: string;
      poolId: string;
      queues: string[];
      capabilities: string[];
      maxConcurrency: number;
    }
  >;
  apiToken: string;
  adminToken: string;
  reliabilitySourceTokens: Record<string, string>;
  effectConsumerCredentials: Record<
    string,
    { token: string; source: string; effectTypes: string[] }
  >;
  alarmDispatcherCredentials: Record<
    string,
    { token: string; source: string }
  >;
  artifactStore: {
    endpoint: string;
    region: string;
    bucket: string;
    accessKeyId: string;
    secretAccessKey: string;
    forcePathStyle: boolean;
    uploadTtlSeconds: number;
    downloadTtlSeconds: number;
    maxBytes: number;
  };
  clusterId: string;
  leadershipApiBase: string;
  leadershipToken: string;
  leadershipCandidateToken: string;
  leadershipPublicKey: string;
  leadershipReceiptPath?: string;
  leadershipRefreshMs: number;
  leadershipRecoveryHoldSeconds: number;
  logLevel: z.infer<typeof environmentSchema>["FABRIC_LOG_LEVEL"];
};

export type ObserverConfig = Pick<
  Config,
  | "hostId"
  | "databaseUrl"
  | "policyConfigPath"
  | "policySchemaPath"
  | "artifactStore"
  | "clusterId"
>;

function readSecretFile(path: string, variable: string): string {
  const value = readFileSync(path, "utf8").trim();
  if (!/^\S{32,}$/.test(value)) {
    throw new Error(
      `${variable} must reference a non-empty token of at least 32 non-whitespace characters`,
    );
  }
  return value;
}

function readSourceTokens(path: string): Record<string, string> {
  const value = JSON.parse(readFileSync(path, "utf8")) as unknown;
  const parsed = z
    .record(
      z.string().regex(/^[a-zA-Z0-9._:-]{1,128}$/),
      z.string().regex(/^\S{32,}$/),
    )
    .parse(value);
  if (Object.keys(parsed).length === 0) {
    throw new Error(
      "FABRIC_RELIABILITY_SOURCE_TOKENS_FILE must define at least one source",
    );
  }
  if (new Set(Object.values(parsed)).size !== Object.keys(parsed).length) {
    throw new Error("reliability source tokens must be unique per source");
  }
  return parsed;
}

function readWorkerBootstrapCredentials(
  path: string,
): Config["workerBootstrapCredentials"] {
  const identifier = z.string().regex(/^[a-zA-Z0-9._:-]{1,128}$/);
  const parsed = z
    .record(
      identifier,
      z
        .object({
          token: z.string().regex(/^\S{32,}$/),
          workerId: identifier,
          hostId: identifier,
          poolId: identifier,
          queues: z.array(identifier).min(1).max(64),
          capabilities: z.array(identifier).max(128),
          maxConcurrency: z.number().int().min(1).max(256),
        })
        .strict(),
    )
    .parse(JSON.parse(readFileSync(path, "utf8")) as unknown);
  if (Object.keys(parsed).length === 0) {
    throw new Error(
      "FABRIC_WORKER_BOOTSTRAP_CREDENTIALS_FILE must define at least one worker identity",
    );
  }
  const tokens = Object.values(parsed).map((credential) => credential.token);
  const workerIds = Object.values(parsed).map((credential) => credential.workerId);
  if (new Set(tokens).size !== tokens.length) {
    throw new Error("worker bootstrap tokens must be unique per durable identity");
  }
  if (new Set(workerIds).size !== workerIds.length) {
    throw new Error("worker bootstrap workerId values must be unique");
  }
  for (const credential of Object.values(parsed)) {
    if (
      new Set(credential.queues).size !== credential.queues.length ||
      new Set(credential.capabilities).size !== credential.capabilities.length
    ) {
      throw new Error("worker bootstrap queues and capabilities must be unique");
    }
  }
  return parsed;
}

function readEffectConsumerCredentials(
  path: string,
): Config["effectConsumerCredentials"] {
  const parsed = z
    .record(
      z.string().regex(/^[a-zA-Z0-9._:-]{1,128}$/),
      z.object({
        token: z.string().regex(/^\S{32,}$/),
        source: z.string().regex(/^[a-zA-Z0-9._:-]{1,128}$/),
        effectTypes: z
          .array(z.string().regex(/^[a-zA-Z0-9._:-]{1,128}$/))
          .min(1)
          .max(128),
      }).strict(),
    )
    .parse(JSON.parse(readFileSync(path, "utf8")) as unknown);
  if (Object.keys(parsed).length === 0) {
    throw new Error(
      "FABRIC_EFFECT_CONSUMER_CREDENTIALS_FILE must define at least one consumer",
    );
  }
  for (const credential of Object.values(parsed)) {
    if (new Set(credential.effectTypes).size !== credential.effectTypes.length) {
      throw new Error("effect consumer effectTypes must be unique");
    }
  }
  return parsed;
}

function readAlarmDispatcherCredentials(
  path: string,
): Config["alarmDispatcherCredentials"] {
  const parsed = z
    .record(
      z.string().regex(/^[a-zA-Z0-9._:-]{1,128}$/),
      z.object({
        token: z.string().regex(/^\S{32,}$/),
        source: z.string().regex(/^[a-zA-Z0-9._:-]{1,128}$/),
      }).strict(),
    )
    .parse(JSON.parse(readFileSync(path, "utf8")) as unknown);
  if (Object.keys(parsed).length === 0) {
    throw new Error(
      "FABRIC_ALARM_DISPATCHER_CREDENTIALS_FILE must define at least one dispatcher",
    );
  }
  return parsed;
}

export function loadConfig(
  environment: NodeJS.ProcessEnv = process.env,
): Config {
  const parsed = environmentSchema.parse(environment);
  const apiToken = readSecretFile(
    parsed.FABRIC_API_TOKEN_FILE,
    "FABRIC_API_TOKEN_FILE",
  );
  const submitToken = readSecretFile(
    parsed.FABRIC_SUBMIT_TOKEN_FILE,
    "FABRIC_SUBMIT_TOKEN_FILE",
  );
  const workerBootstrapCredentials = readWorkerBootstrapCredentials(
    parsed.FABRIC_WORKER_BOOTSTRAP_CREDENTIALS_FILE,
  );
  const adminToken = readSecretFile(
    parsed.FABRIC_ADMIN_TOKEN_FILE,
    "FABRIC_ADMIN_TOKEN_FILE",
  );
  const reliabilitySourceTokens = readSourceTokens(
    parsed.FABRIC_RELIABILITY_SOURCE_TOKENS_FILE,
  );
  const effectConsumerCredentials = readEffectConsumerCredentials(
    parsed.FABRIC_EFFECT_CONSUMER_CREDENTIALS_FILE,
  );
  const alarmDispatcherCredentials = readAlarmDispatcherCredentials(
    parsed.FABRIC_ALARM_DISPATCHER_CREDENTIALS_FILE,
  );
  const workerTokens = Object.values(workerBootstrapCredentials).map(
    (credential) => credential.token,
  );
  const scopedTokens = [submitToken, apiToken, adminToken, ...workerTokens];
  if (new Set(scopedTokens).size !== scopedTokens.length) {
    throw new Error(
      "submit, worker bootstrap, observer API, and admin tokens must all differ",
    );
  }
  if (
    Object.values(reliabilitySourceTokens).some((token) =>
      scopedTokens.includes(token),
    )
  ) {
    throw new Error(
      "reliability source tokens must differ from submit, worker bootstrap, observer API, and admin tokens",
    );
  }
  const allStaticTokens = [
    ...scopedTokens,
    ...Object.values(reliabilitySourceTokens),
    ...Object.values(effectConsumerCredentials).map((item) => item.token),
    ...Object.values(alarmDispatcherCredentials).map((item) => item.token),
  ];
  if (new Set(allStaticTokens).size !== allStaticTokens.length) {
    throw new Error(
      "all static, source, consumer, and dispatcher tokens must differ",
    );
  }
  const leadershipToken = readSecretFile(
    parsed.FABRIC_LEADERSHIP_TOKEN_FILE,
    "FABRIC_LEADERSHIP_TOKEN_FILE",
  );
  const leadershipCandidateToken = readSecretFile(
    parsed.FABRIC_LEADERSHIP_CANDIDATE_TOKEN_FILE,
    "FABRIC_LEADERSHIP_CANDIDATE_TOKEN_FILE",
  );
  if (leadershipCandidateToken === leadershipToken) {
    throw new Error("witness reader and candidate tokens must differ");
  }
  const artifactAccessKey = readSecretFile(
    parsed.FABRIC_ARTIFACT_ACCESS_KEY_FILE,
    "FABRIC_ARTIFACT_ACCESS_KEY_FILE",
  );
  const artifactSecretKey = readSecretFile(
    parsed.FABRIC_ARTIFACT_SECRET_KEY_FILE,
    "FABRIC_ARTIFACT_SECRET_KEY_FILE",
  );
  const leadershipPublicKey = readFileSync(
    parsed.FABRIC_LEADERSHIP_PUBLIC_KEY_FILE,
    "utf8",
  );
  if (!leadershipPublicKey.includes("BEGIN PUBLIC KEY")) {
    throw new Error(
      "FABRIC_LEADERSHIP_PUBLIC_KEY_FILE must reference a PEM public key",
    );
  }
  return {
    host: parsed.FABRIC_HOST,
    port: parsed.FABRIC_PORT,
    hostId: parsed.FABRIC_HOST_ID,
    databaseUrl: parsed.FABRIC_DATABASE_URL,
    valkeyUrl: parsed.FABRIC_VALKEY_URL,
    queuePrefix: parsed.FABRIC_QUEUE_PREFIX,
    leaseSeconds: parsed.FABRIC_LEASE_SECONDS,
    workerTtlSeconds: parsed.FABRIC_WORKER_TTL_SECONDS,
    longPollMs: parsed.FABRIC_LONG_POLL_MS,
    reconcileIntervalMs: parsed.FABRIC_RECONCILE_INTERVAL_MS,
    metricsPrefix: parsed.FABRIC_METRICS_PREFIX,
    policyConfigPath: parsed.FABRIC_POLICY_CONFIG_FILE,
    policySchemaPath: parsed.FABRIC_POLICY_SCHEMA_FILE,
    submitToken,
    workerBootstrapCredentials,
    apiToken,
    adminToken,
    reliabilitySourceTokens,
    effectConsumerCredentials,
    alarmDispatcherCredentials,
    artifactStore: {
      endpoint: parsed.FABRIC_ARTIFACT_ENDPOINT,
      region: parsed.FABRIC_ARTIFACT_REGION,
      bucket: parsed.FABRIC_ARTIFACT_BUCKET,
      accessKeyId: artifactAccessKey,
      secretAccessKey: artifactSecretKey,
      forcePathStyle: parsed.FABRIC_ARTIFACT_FORCE_PATH_STYLE === "true",
      uploadTtlSeconds: parsed.FABRIC_ARTIFACT_UPLOAD_TTL_SECONDS,
      downloadTtlSeconds: parsed.FABRIC_ARTIFACT_DOWNLOAD_TTL_SECONDS,
      maxBytes: parsed.FABRIC_ARTIFACT_MAX_BYTES,
    },
    clusterId: parsed.FABRIC_CLUSTER_ID,
    leadershipApiBase: parsed.FABRIC_LEADERSHIP_API_BASE,
    leadershipToken,
    leadershipCandidateToken,
    leadershipPublicKey,
    ...(parsed.FABRIC_LEADERSHIP_RECEIPT_FILE
      ? { leadershipReceiptPath: parsed.FABRIC_LEADERSHIP_RECEIPT_FILE }
      : {}),
    leadershipRefreshMs: parsed.FABRIC_LEADERSHIP_REFRESH_MS,
    leadershipRecoveryHoldSeconds:
      parsed.FABRIC_LEADERSHIP_RECOVERY_HOLD_SECONDS,
    logLevel: parsed.FABRIC_LOG_LEVEL,
  };
}

/**
 * Load only the observer's read/health dependencies.
 *
 * The observer must never parse or receive submitter, worker-bootstrap,
 * administrator, effect-consumer, alarm-dispatcher, or witness credentials.
 */
export function loadObserverConfig(
  environment: NodeJS.ProcessEnv = process.env,
): ObserverConfig {
  const parsed = observerEnvironmentSchema.parse(environment);
  return {
    hostId: parsed.FABRIC_HOST_ID,
    databaseUrl: parsed.FABRIC_DATABASE_URL,
    policyConfigPath: parsed.FABRIC_POLICY_CONFIG_FILE,
    policySchemaPath: parsed.FABRIC_POLICY_SCHEMA_FILE,
    artifactStore: {
      endpoint: parsed.FABRIC_ARTIFACT_ENDPOINT,
      region: parsed.FABRIC_ARTIFACT_REGION,
      bucket: parsed.FABRIC_ARTIFACT_BUCKET,
      accessKeyId: readSecretFile(
        parsed.FABRIC_ARTIFACT_ACCESS_KEY_FILE,
        "FABRIC_ARTIFACT_ACCESS_KEY_FILE",
      ),
      secretAccessKey: readSecretFile(
        parsed.FABRIC_ARTIFACT_SECRET_KEY_FILE,
        "FABRIC_ARTIFACT_SECRET_KEY_FILE",
      ),
      forcePathStyle: parsed.FABRIC_ARTIFACT_FORCE_PATH_STYLE === "true",
      uploadTtlSeconds: parsed.FABRIC_ARTIFACT_UPLOAD_TTL_SECONDS,
      downloadTtlSeconds: parsed.FABRIC_ARTIFACT_DOWNLOAD_TTL_SECONDS,
      maxBytes: parsed.FABRIC_ARTIFACT_MAX_BYTES,
    },
    clusterId: parsed.FABRIC_CLUSTER_ID,
  };
}
