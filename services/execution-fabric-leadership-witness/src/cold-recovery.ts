import { createHash, createPrivateKey, createPublicKey, verify, randomUUID } from "node:crypto";
import { readFileSync, lstatSync, realpathSync } from "node:fs";
import { resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { z } from "zod";
import { SqliteWitnessStore } from "./sqlite-store.js";
import type { ColdRecoveryReceipt, LeadershipState } from "./contracts.js";

const hash = z.string().regex(/^[a-f0-9]{64}$/);
const host = z.string().regex(/^[a-zA-Z0-9._-]{1,128}$/);
const counter = z.number().int().positive().max(Number.MAX_SAFE_INTEGER);
const stamp = z.string().datetime({ offset: true });
const path = z.string().refine((s) => s.startsWith("/") && resolve(s) === s, "path must be absolute and normalized");
export const coldPolicySchema = z.object({
  schemaVersion: z.literal("execution-fabric-cold-recovery-policy/v1"),
  enabled: z.boolean(), clusterId: z.string().min(1), allowedHosts: z.array(host).min(2),
  recoveryPublicKeyPem: z.string().min(1), fencePublicKeyPem: z.string().min(1),
  maxApprovalSeconds: z.number().int().min(60).max(3600),
  witnessActorSha256: hash, controlPlaneActorSha256: hash,
}).strict();
export const coldPlanSchema = z.object({
  schemaVersion: z.literal("execution-fabric-cold-recovery-plan/v1"),
  recoveryId: z.string().uuid(), direction: z.enum(["recovery", "failback"]),
  clusterId: z.string().min(1), sourceHost: host, targetHost: host,
  expectedEpoch: counter, nextEpoch: counter, generation: counter,
  anchorSha256: hash, policySha256: hash, restoreInputSha256: hash,
  manifestSha256: hash, restoreReceiptSha256: hash, snapshotVersion: counter,
  originalDatabasePath: path, originalBackupPath: path, targetDatabasePath: path,
  databaseSha256: hash, sentinelSha256: hash, backupSha256: hash, hostMarkerSha256: hash,
  oldPublicKeySha256: hash, newPublicKeySha256: hash, candidateConfigDigest: hash,
  newPgSystemId: z.string().regex(/^[0-9]{1,32}$/), timelineId: counter,
  walPosition: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER),
  createdAt: stamp, expiresAt: stamp,
  canary: z.object({taskId: z.string().uuid(), workerId: host, taskType: z.literal("fabric.cold_canary"), queue: z.literal("fabric_cold_recovery"), namespace: z.literal("fabric_cold_recovery"), payload: z.object({schema_version:z.literal("execution-fabric-cold-canary/v1"),recovery_id:z.string().uuid(),cluster_id:z.string().min(1).max(128),epoch:counter,generation:counter}).strict(), payloadSha256: hash}).strict(),
}).strict().superRefine((plan, context) => {
  const p=plan.canary.payload;
  if(p.recovery_id!==plan.recoveryId || p.cluster_id!==plan.clusterId || p.epoch!==plan.nextEpoch || p.generation!==plan.generation)
    context.addIssue({code:z.ZodIssueCode.custom,message:"cold canary signed payload binding differs"});
});
const fenceSchema = z.object({
  schemaVersion: z.literal("execution-fabric-external-fence/v1"),
  recoveryId: z.string().uuid(), clusterId: z.string().min(1), sourceHost: host,
  sourceBootId: z.string().min(1), durable: z.literal(true),
  highestGeneration: counter, highestEpoch: counter,
  coveredWriterScopes: z.array(z.enum(["witness", "postgres", "producer", "provider"])).length(4),
  evidenceSha256: hash, issuedAt: stamp, expiresAt: stamp,
}).strict();
const approvalSchema = z.object({
  schemaVersion: z.literal("execution-fabric-cold-recovery-approval/v1"),
  planSha256: hash, policySha256: hash, fenceSha256: hash, approvedBy: z.string().min(1),
  issuedAt: stamp, expiresAt: stamp,
}).strict();
export const coldAnchorSchema = z.object({
  schemaVersion: z.literal("execution-fabric-recovery-anchor/v1"),
  clusterId: z.string().min(1), leader: host, generation: counter,
  highestEpoch: counter, publicKeySha256: hash, lastReceiptSha256: hash,
  pending: z.object({recoveryId: z.string().uuid(), planSha256: hash, generation: counter, nextEpoch: counter, targetHost: host, phase: z.enum(["RESERVED", "ANCHOR_COMMITTED"])}).strict().nullable(),
}).strict();
const signed = <T extends z.ZodTypeAny>(schema: T) => z.object({payload: schema, signature: z.string().min(1)}).strict();
export const coldRestoreInputSchema = z.object({
  schemaVersion:z.literal("execution-fabric-cold-restore-input/v1"), recoverySetId:z.string().uuid(),
  manifestSha256:hash, restoreReceiptSha256:hash, sourceRelease:z.string().min(1), imageLockSha256:hash,
  capturedAt:stamp, commonWatermark:z.string().min(1), custodyReceiptSha256:hash,
  witness:z.object({clusterId:z.string().min(1),version:counter,leader:host,epoch:counter,auditTailSha256:hash,databaseSha256:hash,sentinelSha256:hash,backupSha256:hash,hostMarkerSha256:hash,originalDatabasePath:path,originalBackupPath:path,signingPublicKeySha256:hash}).strict(),
  postgres:z.object({dumpSha256:hash,restoreReadbackSha256:hash,systemId:z.string().regex(/^[0-9]{1,32}$/),majorVersion:counter}).strict(),
  artifacts:z.object({inventorySha256:hash,verifiedReferences:z.literal(true)}).strict(),
  osAuthority:z.object({snapshotSha256:hash,immutableReceiptInventorySha256:hash}).strict(),
}).strict();
function assertRestoreInput(request:Record<string,unknown>,plan:ColdPlan):void {
  const allowed=["plan","restoreInput","approval","fence","signingPrivateKeyFile","hostMarkerFile","baseline","authorityProof","policySha256"];
  if(Object.keys(request).some((key)=>!allowed.includes(key))) throw new Error("cold request has unknown fields");
  const input=coldRestoreInputSchema.parse(request.restoreInput), w=input.witness;
  if(digest(input)!==plan.restoreInputSha256 || input.manifestSha256!==plan.manifestSha256 || input.restoreReceiptSha256!==plan.restoreReceiptSha256 || w.clusterId!==plan.clusterId || w.version!==plan.snapshotVersion || w.leader!==plan.sourceHost || w.epoch!==plan.expectedEpoch || w.signingPublicKeySha256!==plan.oldPublicKeySha256 || input.postgres.systemId!==plan.newPgSystemId) throw new Error("cold restore identity/closure differs");
  for(const key of ["databaseSha256","sentinelSha256","backupSha256","hostMarkerSha256","originalDatabasePath","originalBackupPath"] as const) if(w[key]!==plan[key]) throw new Error("cold restore witness hash/path differs");
}
export type ColdPlan = z.infer<typeof coldPlanSchema>;
export type ColdPolicy = z.infer<typeof coldPolicySchema>;
export type ColdAnchor = z.infer<typeof coldAnchorSchema>;
export type VerifiedColdRequest = { plan: ColdPlan; policy: ColdPolicy; anchor: ColdAnchor };
const verifiedRequests = new WeakSet<object>();
const verifiedExpiry = new WeakMap<object,number>();
function freezeJson<T>(value:T):T {
  if(value !== null && typeof value === "object") {
    for(const item of Object.values(value)) freezeJson(item);
    Object.freeze(value);
  }
  return value;
}
export function assertVerifiedColdRequest(value: VerifiedColdRequest): void {
  if (!verifiedRequests.has(value) || Date.now() >= (verifiedExpiry.get(value) ?? 0)) throw new Error("offline cold authorization was not verified or has expired");
}
export function canonical(value: unknown): string {
  if (typeof value === "number" && !Number.isSafeInteger(value)) throw new Error("cold protocol numbers must be safe integers");
  if (value === undefined || typeof value === "bigint" || typeof value === "function" || typeof value === "symbol") throw new Error("cold protocol value is not JSON");
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value !== null && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const order=(a:string,b:string)=>{const x=Array.from(a),y=Array.from(b);for(let i=0;i<Math.min(x.length,y.length);i++){const d=x[i]!.codePointAt(0)!-y[i]!.codePointAt(0)!;if(d)return d;}return x.length-y.length;};
    return "{" + Object.keys(obj).sort(order).map((k) => JSON.stringify(k)+":"+canonical(obj[k])).join(",") + "}";
  }
  return JSON.stringify(value);
}
export function digest(value: unknown): string { return createHash("sha256").update(canonical(value)).digest("hex"); }
export function fileHash(file: string): string { return createHash("sha256").update(readFileSync(safeFile(file))).digest("hex"); }
export function safeFile(file: string): string {
  const stat = lstatSync(file);
  if (resolve(file) !== file || realpathSync(file) !== file || stat.isSymbolicLink() || !stat.isFile() || stat.uid !== process.getuid?.() || stat.mode & 0o022) throw new Error("unsafe cold recovery file");
  return file;
}
function window(issuedAt: string, expiresAt: string, maximum: number, now: number): void {
  const a = Date.parse(issuedAt), b = Date.parse(expiresAt);
  if (!(a <= now && now < b && b-a > 0 && b-a <= maximum*1000)) throw new Error("cold authorization expired, future, or excessive");
}
function verifySigned<T>(envelope: {payload: T; signature: string}, publicKey: string): void {
  const key = createPublicKey(publicKey);
  const signature = Buffer.from(envelope.signature, "base64");
  if (key.asymmetricKeyType !== "ed25519" || signature.length !== 64 || !verify(null, Buffer.from(canonical(envelope.payload)), key, signature)) throw new Error("cold signature verification failed");
}
export function authorizeColdRequest(request: Record<string, unknown>, policyValue: unknown, anchorValue: unknown, now = Date.now()): VerifiedColdRequest {
  const policy = coldPolicySchema.parse(policyValue), plan = coldPlanSchema.parse(request.plan), anchor = coldAnchorSchema.parse(anchorValue);
  assertRestoreInput(request, plan);
  if(new Set(policy.allowedHosts).size!==policy.allowedHosts.length || (request.policySha256 !== undefined && request.policySha256 !== digest(policy))) throw new Error("cold policy/request binding differs");
  const fence = signed(fenceSchema).parse(request.fence), approval = signed(approvalSchema).parse(request.approval);
  if (!policy.enabled || plan.clusterId !== policy.clusterId || anchor.clusterId !== policy.clusterId || plan.sourceHost === plan.targetHost || !policy.allowedHosts.includes(plan.sourceHost) || !policy.allowedHosts.includes(plan.targetHost) || plan.nextEpoch <= plan.expectedEpoch || plan.oldPublicKeySha256 === plan.newPublicKeySha256 || plan.policySha256 !== digest(policy)) throw new Error("cold authority identity or policy differs");
  verifySigned(fence, policy.fencePublicKeyPem);
  verifySigned(approval, policy.recoveryPublicKeyPem);
  window(fence.payload.issuedAt, fence.payload.expiresAt, policy.maxApprovalSeconds, now);
  window(approval.payload.issuedAt, approval.payload.expiresAt, policy.maxApprovalSeconds, now);
  if (approval.payload.planSha256 !== digest(plan) || approval.payload.policySha256 !== digest(policy) || approval.payload.fenceSha256 !== digest(fence) || fence.payload.clusterId !== plan.clusterId || fence.payload.recoveryId !== plan.recoveryId || fence.payload.sourceHost !== plan.sourceHost || fence.payload.highestGeneration !== plan.generation-1 || fence.payload.highestEpoch !== plan.nextEpoch-1 || new Set(fence.payload.coveredWriterScopes).size !== 4 || plan.canary.payloadSha256 !== digest(plan.canary.payload)) throw new Error("cold fence, canary, approval or freshness differs");
  if (anchor.generation !== plan.generation || !anchor.pending || anchor.pending.generation !== plan.generation || anchor.pending.recoveryId !== plan.recoveryId || anchor.pending.planSha256 !== digest(plan) || anchor.pending.nextEpoch !== plan.nextEpoch || anchor.pending.targetHost !== plan.targetHost) throw new Error("external recovery anchor has no matching reserved operation");
  const original = anchor.leader === plan.sourceHost && anchor.publicKeySha256 === plan.oldPublicKeySha256 && anchor.highestEpoch === plan.nextEpoch - 1 && anchor.pending.phase === "RESERVED";
  const committed = anchor.leader === plan.targetHost && anchor.publicKeySha256 === plan.newPublicKeySha256 && anchor.highestEpoch === plan.nextEpoch && anchor.pending.phase === "ANCHOR_COMMITTED";
  if (!original && !committed) throw new Error("external recovery anchor high-watermark differs");
  const result = freezeJson({plan, policy, anchor});
  verifiedRequests.add(result);
  verifiedExpiry.set(result,Math.min(Date.parse(fence.payload.expiresAt),Date.parse(approval.payload.expiresAt)));
  return result;
}
export function inspectColdWitness(auth: VerifiedColdRequest, hostMarkerFile: string): {alreadyCommitted: boolean; version: number} {
  assertVerifiedColdRequest(auth);
  const p = auth.plan, database = safeFile(p.targetDatabasePath);
  const sentinelPath = safeFile(database + ".initialized"), backupPath = safeFile(database + ".backup");
  if (fileHash(hostMarkerFile) !== p.hostMarkerSha256) throw new Error("original host/bootstrap marker differs");
  const sentinel = JSON.parse(readFileSync(sentinelPath, "utf8")) as Record<string, unknown>;
  if (Object.keys(sentinel).sort().join(",") !== ["schemaVersion","clusterId","initializedAt","database","backup"].sort().join(",") || sentinel.schemaVersion !== "execution-fabric-witness-bootstrap/v1" || sentinel.clusterId !== p.clusterId) throw new Error("witness sentinel identity differs");
  const db = new DatabaseSync(database, {readOnly: true});
  try {
    const integrity = db.prepare("PRAGMA quick_check").get() as {quick_check: string};
    if (integrity.quick_check !== "ok") throw new Error("cold witness integrity failed");
    const row = db.prepare("SELECT version,payload FROM witness_snapshot WHERE cluster_id=?").get(p.clusterId) as {version: number; payload: string} | undefined;
    if (!row) throw new Error("cold witness cluster state is missing");
    const snapshot = JSON.parse(row.payload) as {state?: LeadershipState; coldRecoveries?: ColdRecoveryReceipt[]};
    const receipt = snapshot.coldRecoveries?.find((r) => r.recoveryId === p.recoveryId);
    const lease = db.prepare("SELECT lease_expires_at FROM witness_process_lease WHERE cluster_id=?").get(p.clusterId) as {lease_expires_at: number} | undefined;
    if (lease && Number(lease.lease_expires_at) > Date.now()) throw new Error("a witness process still owns the restored database");
    if (receipt) {
      if (receipt.planSha256 !== digest(p) || snapshot.state?.currentLeader !== p.targetHost || snapshot.state.fabricEpoch !== p.nextEpoch) throw new Error("committed cold witness receipt differs");
      if (!((sentinel.database === p.originalDatabasePath && sentinel.backup === p.originalBackupPath) || (sentinel.database === p.targetDatabasePath && sentinel.backup === p.targetDatabasePath + ".backup"))) throw new Error("committed cold path binding differs");
      return {alreadyCommitted: true, version: Number(row.version)};
    }
    if (Number(row.version) !== p.snapshotVersion || snapshot.state?.currentLeader !== p.sourceHost || snapshot.state.fabricEpoch !== p.expectedEpoch || snapshot.state.authorityMode !== "standalone_primary" || sentinel.database !== p.originalDatabasePath || sentinel.backup !== p.originalBackupPath || fileHash(database) !== p.databaseSha256 || fileHash(sentinelPath) !== p.sentinelSha256 || fileHash(backupPath) !== p.backupSha256) throw new Error("restored cold witness history/hash/path binding differs");
    return {alreadyCommitted: false, version: Number(row.version)};
  } finally { db.close(); }
}
export async function commitColdWitness(request: Record<string, unknown>, policy: unknown, anchor: unknown): Promise<ColdRecoveryReceipt> {
  const auth = authorizeColdRequest(request, policy, anchor), p = auth.plan;
  if (typeof request.hostMarkerFile !== "string" || typeof request.signingPrivateKeyFile !== "string") throw new Error("cold custody/key files are required");
  inspectColdWitness(auth, request.hostMarkerFile);
  const keyFile = safeFile(request.signingPrivateKeyFile);
  if (lstatSync(keyFile).mode & 0o077) throw new Error("cold signing key must be private to its owner");
  const key = createPrivateKey(readFileSync(keyFile, "utf8"));
  const publicKey = createPublicKey(key);
  if (key.asymmetricKeyType !== "ed25519" || createHash("sha256").update(publicKey.export({type:"spki",format:"der"})).digest("hex") !== p.newPublicKeySha256) throw new Error("rotated witness key identity differs");
  const store = new SqliteWitnessStore(p.targetDatabasePath, p.clusterId, {coldAuthorization: auth});
  try {
    const old = await store.getColdRecovery(p.recoveryId);
    if (old) { store.repairColdRecoveryArtifacts(auth); return old; }
    const state = await store.getState(), now = new Date().toISOString();
    const receipt: ColdRecoveryReceipt = {schemaVersion:"execution-fabric-cold-witness-receipt/v1", recoveryId:p.recoveryId, planSha256:digest(p), previousLeader:p.sourceHost,currentLeader:p.targetHost,fabricEpoch:p.nextEpoch,generation:p.generation,originalDatabasePath:p.originalDatabasePath,targetDatabasePath:p.targetDatabasePath,newPublicKeySha256:p.newPublicKeySha256,committedAt:now,held:true};
    return await store.commitColdRecovery({expectedLeader:p.sourceHost,expectedEpoch:p.expectedEpoch,nextState:{...state,currentLeader:p.targetHost,fabricEpoch:p.nextEpoch,configDigest:p.candidateConfigDigest,upstreamSystemId:p.newPgSystemId,timelineId:p.timelineId,leaderWalPosition:p.walPosition,leaderBaselineAt:now,updatedAt:now,fenceDigest:digest(receipt),authorityMode:"standalone_primary",degradedUntil:null,degradedIncidentDigest:null},receipt,audit:{auditId:randomUUID(),eventType:"cold_recovery_committed",actor:"offline-cold-recovery",occurredAt:now,previousLeader:p.sourceHost,newLeader:p.targetHost,previousEpoch:p.expectedEpoch,newEpoch:p.nextEpoch,requestDigest:digest(p),detail:{recoveryId:p.recoveryId,generation:p.generation,originalDatabasePath:p.originalDatabasePath,targetDatabasePath:p.targetDatabasePath}}});
  } finally { await store.close(); }
}
