import { readFileSync } from "node:fs";
import { z } from "zod";

const digest = /^[a-f0-9]{64}$/;

const environmentSchema = z.object({
  WITNESS_TAILSCALE_IP: z.string().ip().optional(),
  WITNESS_BIND_IP: z.string().ip().optional(),
  WITNESS_PORT: z.coerce.number().int().min(1).max(65535).default(3195),
  WITNESS_HOST_ID: z.string().regex(/^[a-zA-Z0-9._-]{1,128}$/),
  WITNESS_CLUSTER_ID: z.string().regex(/^[a-zA-Z0-9._-]{1,128}$/),
  WITNESS_STATE_FILE: z
    .string()
    .min(1)
    .default("/var/lib/execution-fabric-witness/witness.sqlite3"),
  WITNESS_BOOTSTRAP_ONCE: z
    .enum(["true", "false"])
    .default("false")
    .transform((value) => value === "true"),
  WITNESS_PROCESS_LEASE_SECONDS: z.coerce
    .number()
    .int()
    .min(10)
    .max(300)
    .default(30),
  WITNESS_INITIAL_LEADER: z.string().regex(/^[a-zA-Z0-9._-]{1,128}$/),
  WITNESS_INITIAL_TIMELINE_ID: z.coerce.number().int().min(1),
  WITNESS_INITIAL_CONFIG_DIGEST: z.string().regex(digest),
  WITNESS_MAX_REPLICA_LAG_BYTES: z.coerce
    .number()
    .int()
    .min(0)
    .default(67108864),
  WITNESS_CANDIDATE_FRESHNESS_SECONDS: z.coerce
    .number()
    .int()
    .min(15)
    .max(3600)
    .default(90),
  WITNESS_LEADER_BASELINE_MAX_AGE_SECONDS: z.coerce
    .number()
    .int()
    .min(30)
    .max(86400)
    .default(300),
  WITNESS_PLAN_TTL_SECONDS: z.coerce
    .number()
    .int()
    .min(60)
    .max(86400)
    .default(900),
  WITNESS_MAX_REPORT_SKEW_SECONDS: z.coerce
    .number()
    .int()
    .min(1)
    .max(300)
    .default(30),
  WITNESS_STANDALONE_PRIMARY_HOST_ID: z
    .string()
    .regex(/^[a-zA-Z0-9._-]{1,128}$/)
    .optional(),
  WITNESS_ALLOW_DEGRADED_PRIMARY: z
    .enum(["true", "false"])
    .default("false")
    .transform((value) => value === "true"),
  WITNESS_MAX_DEGRADED_PRIMARY_SECONDS: z.coerce
    .number()
    .int()
    .min(60)
    .max(86400)
    .default(3600),
  WITNESS_READER_TOKEN_FILE: z.string().min(1),
  WITNESS_CANDIDATE_TOKENS_FILE: z.string().min(1),
  WITNESS_ADMIN_TOKEN_FILE: z.string().min(1),
  WITNESS_SIGNING_PRIVATE_KEY_FILE: z.string().min(1),
  WITNESS_LOG_LEVEL: z
    .enum(["fatal", "error", "warn", "info", "debug", "trace", "silent"])
    .default("info"),
});

function secret(path: string, variable: string): string {
  const value = readFileSync(path, "utf8").trim();
  if (!/^\S{32,}$/.test(value)) {
    throw new Error(
      `${variable} must reference a non-empty secret of at least 32 non-whitespace characters`,
    );
  }
  return value;
}

function privateKey(path: string): string {
  const value = readFileSync(path, "utf8");
  if (!value.includes("BEGIN PRIVATE KEY")) {
    throw new Error(
      "WITNESS_SIGNING_PRIVATE_KEY_FILE must reference a PEM PKCS8 private key",
    );
  }
  return value;
}

function candidateTokens(path: string): Record<string, string> {
  let decoded: unknown;
  try {
    decoded = JSON.parse(readFileSync(path, "utf8"));
  } catch {
    throw new Error(
      "WITNESS_CANDIDATE_TOKENS_FILE must reference a JSON object of host-scoped tokens",
    );
  }
  const parsed = z
    .record(
      z.string().regex(/^[a-zA-Z0-9._-]{1,128}$/),
      z.string().regex(/^\S{32,}$/),
    )
    .parse(decoded);
  if (Object.keys(parsed).length < 1) {
    throw new Error(
      "WITNESS_CANDIDATE_TOKENS_FILE must contain at least one host-scoped token",
    );
  }
  if (new Set(Object.values(parsed)).size !== Object.keys(parsed).length) {
    throw new Error("candidate tokens must be unique per host");
  }
  return parsed;
}

export type WitnessConfig = {
  host: string;
  port: number;
  witnessHostId: string;
  clusterId: string;
  stateFile: string;
  bootstrapOnce: boolean;
  processLeaseSeconds: number;
  initialLeader: string;
  initialTimelineId: number;
  initialConfigDigest: string;
  maxReplicaLagBytes: number;
  candidateFreshnessSeconds: number;
  leaderBaselineMaxAgeSeconds: number;
  planTtlSeconds: number;
  maxReportSkewSeconds: number;
  standalonePrimaryHostId?: string;
  allowDegradedPrimary?: boolean;
  maxDegradedPrimarySeconds?: number;
  readerToken: string;
  candidateTokens: Record<string, string>;
  adminToken: string;
  signingPrivateKey: string;
  logLevel: z.infer<typeof environmentSchema>["WITNESS_LOG_LEVEL"];
};

export function loadConfig(
  environment: NodeJS.ProcessEnv = process.env,
): WitnessConfig {
  const parsed = environmentSchema.parse(environment);
  if (
    Boolean(parsed.WITNESS_TAILSCALE_IP) === Boolean(parsed.WITNESS_BIND_IP)
  ) {
    throw new Error(
      "set exactly one of WITNESS_TAILSCALE_IP or WITNESS_BIND_IP",
    );
  }
  if (
    parsed.WITNESS_LEADER_BASELINE_MAX_AGE_SECONDS <=
    parsed.WITNESS_CANDIDATE_FRESHNESS_SECONDS
  ) {
    throw new Error(
      "WITNESS_LEADER_BASELINE_MAX_AGE_SECONDS must exceed WITNESS_CANDIDATE_FRESHNESS_SECONDS",
    );
  }
  const adminToken = secret(
    parsed.WITNESS_ADMIN_TOKEN_FILE,
    "WITNESS_ADMIN_TOKEN_FILE",
  );
  const readerToken = secret(
    parsed.WITNESS_READER_TOKEN_FILE,
    "WITNESS_READER_TOKEN_FILE",
  );
  const scopedCandidateTokens = candidateTokens(
    parsed.WITNESS_CANDIDATE_TOKENS_FILE,
  );
  const candidateHostIds = Object.keys(scopedCandidateTokens);
  if (parsed.WITNESS_STANDALONE_PRIMARY_HOST_ID) {
    if (
      parsed.WITNESS_STANDALONE_PRIMARY_HOST_ID !==
      parsed.WITNESS_INITIAL_LEADER
    ) {
      throw new Error(
        "WITNESS_STANDALONE_PRIMARY_HOST_ID must equal WITNESS_INITIAL_LEADER",
      );
    }
    if (
      candidateHostIds.length !== 1 ||
      candidateHostIds[0] !== parsed.WITNESS_STANDALONE_PRIMARY_HOST_ID
    ) {
      throw new Error(
        "standalone-primary witness must contain exactly one token for its configured host",
      );
    }
    if (parsed.WITNESS_ALLOW_DEGRADED_PRIMARY) {
      throw new Error(
        "standalone-primary and degraded-primary witness authority cannot be combined",
      );
    }
    if (parsed.WITNESS_CANDIDATE_FRESHNESS_SECONDS > 300) {
      throw new Error(
        "standalone-primary leadership proof lifetime must not exceed 300 seconds",
      );
    }
  } else if (candidateHostIds.length < 2) {
    throw new Error(
      "independent witness mode requires at least two host-scoped tokens",
    );
  }
  if (!(parsed.WITNESS_INITIAL_LEADER in scopedCandidateTokens)) {
    throw new Error(
      "WITNESS_CANDIDATE_TOKENS_FILE must include WITNESS_INITIAL_LEADER",
    );
  }
  if (parsed.WITNESS_HOST_ID in scopedCandidateTokens) {
    throw new Error(
      "WITNESS_HOST_ID must be independent from every leadership candidate",
    );
  }
  if (
    new Set([
      adminToken,
      readerToken,
      ...Object.values(scopedCandidateTokens),
    ]).size !==
    Object.keys(scopedCandidateTokens).length + 2
  ) {
    throw new Error("reader, admin, and candidate tokens must all differ");
  }
  const signingPrivateKey = privateKey(
    parsed.WITNESS_SIGNING_PRIVATE_KEY_FILE,
  );
  return {
    host: parsed.WITNESS_TAILSCALE_IP ?? parsed.WITNESS_BIND_IP!,
    port: parsed.WITNESS_PORT,
    witnessHostId: parsed.WITNESS_HOST_ID,
    clusterId: parsed.WITNESS_CLUSTER_ID,
    stateFile: parsed.WITNESS_STATE_FILE,
    bootstrapOnce: parsed.WITNESS_BOOTSTRAP_ONCE,
    processLeaseSeconds: parsed.WITNESS_PROCESS_LEASE_SECONDS,
    initialLeader: parsed.WITNESS_INITIAL_LEADER,
    initialTimelineId: parsed.WITNESS_INITIAL_TIMELINE_ID,
    initialConfigDigest: parsed.WITNESS_INITIAL_CONFIG_DIGEST,
    maxReplicaLagBytes: parsed.WITNESS_MAX_REPLICA_LAG_BYTES,
    candidateFreshnessSeconds: parsed.WITNESS_CANDIDATE_FRESHNESS_SECONDS,
    leaderBaselineMaxAgeSeconds:
      parsed.WITNESS_LEADER_BASELINE_MAX_AGE_SECONDS,
    planTtlSeconds: parsed.WITNESS_PLAN_TTL_SECONDS,
    maxReportSkewSeconds: parsed.WITNESS_MAX_REPORT_SKEW_SECONDS,
    ...(parsed.WITNESS_STANDALONE_PRIMARY_HOST_ID
      ? {
          standalonePrimaryHostId:
            parsed.WITNESS_STANDALONE_PRIMARY_HOST_ID,
        }
      : {}),
    allowDegradedPrimary: parsed.WITNESS_ALLOW_DEGRADED_PRIMARY,
    maxDegradedPrimarySeconds:
      parsed.WITNESS_MAX_DEGRADED_PRIMARY_SECONDS,
    readerToken,
    candidateTokens: scopedCandidateTokens,
    adminToken,
    signingPrivateKey,
    logLevel: parsed.WITNESS_LOG_LEVEL,
  };
}
