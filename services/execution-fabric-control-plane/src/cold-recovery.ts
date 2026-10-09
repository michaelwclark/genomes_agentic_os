import { createHash, createPrivateKey, createPublicKey, verify, randomUUID } from "node:crypto";
import { readFileSync, lstatSync, realpathSync } from "node:fs";
import { resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { z } from "zod";
import type pg from "pg";

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
export function expectedCanaryResult(plan:ColdPlan):Record<string,unknown> {
  return {...plan.canary.payload,schema_version:"execution-fabric-cold-canary-result/v1",handler:"fabric_cold_canary_v1",task_id:plan.canary.taskId};
}
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
export function authorizeColdRequest(request: Record<string, unknown>, policyValue: unknown, anchorValue: unknown, now = Date.now(), allowAccepted = false): VerifiedColdRequest {
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
  const accepted = allowAccepted && anchor.pending === null && anchor.leader === plan.targetHost && anchor.publicKeySha256 === plan.newPublicKeySha256 && anchor.highestEpoch === plan.nextEpoch;
  if (anchor.generation !== plan.generation || (!accepted && (!anchor.pending || anchor.pending.generation !== plan.generation || anchor.pending.recoveryId !== plan.recoveryId || anchor.pending.planSha256 !== digest(plan) || anchor.pending.nextEpoch !== plan.nextEpoch || anchor.pending.targetHost !== plan.targetHost))) throw new Error("external recovery anchor has no matching reserved operation");
  const original = anchor.leader === plan.sourceHost && anchor.publicKeySha256 === plan.oldPublicKeySha256 && anchor.highestEpoch === plan.nextEpoch - 1 && anchor.pending?.phase === "RESERVED";
  const committed = anchor.leader === plan.targetHost && anchor.publicKeySha256 === plan.newPublicKeySha256 && anchor.highestEpoch === plan.nextEpoch && (anchor.pending?.phase === "ANCHOR_COMMITTED" || accepted);
  if (!original && !committed) throw new Error("external recovery anchor high-watermark differs");
  const result = freezeJson({plan, policy, anchor});
  verifiedRequests.add(result);
  verifiedExpiry.set(result,Math.min(Date.parse(fence.payload.expiresAt),Date.parse(approval.payload.expiresAt)));
  return result;
}

export type ColdLedgerReceipt = {schemaVersion:"execution-fabric-cold-ledger-receipt/v1"; operation:string; recoveryId:string; planSha256:string; fabricEpoch:number; generation:number; held:boolean; residualQuarantine:boolean};
async function ioFootprint(client:pg.PoolClient):Promise<string> {
  const rows=await client.query(`SELECT 'effect' AS kind,id::text,encode(sha256(convert_to(row_to_json(e)::text,'UTF8')),'hex') AS digest FROM fabric_effect_outbox e
    UNION ALL SELECT 'alarm',id::text,encode(sha256(convert_to(row_to_json(a)::text,'UTF8')),'hex') FROM fabric_alarm_outbox a
    UNION ALL SELECT 'artifact',id::text,encode(sha256(convert_to(row_to_json(f)::text,'UTF8')),'hex') FROM fabric_artifacts f ORDER BY kind,id`);
  return digest(rows.rows);
}
export async function runColdLedgerOperation(pool: pg.Pool, operation: string, request: Record<string, unknown>, policyValue: unknown, anchorValue: unknown): Promise<ColdLedgerReceipt> {
  if (!["hold","commit","canary","accept"].includes(operation)) throw new Error("unsupported offline ledger operation");
  const auth = authorizeColdRequest(request, policyValue, anchorValue, Date.now(), operation === "accept"), p=auth.plan, planHash=digest(p);
  const client=await pool.connect();
  try {
    await client.query("BEGIN");
    await client.query("SELECT pg_advisory_xact_lock(hashtext('agentic-os-execution-fabric-cold-recovery'))");
    const identity=await client.query("SELECT system_identifier::text AS system_id FROM pg_control_system()");
    const durability=await client.query("SELECT pg_is_in_recovery() AS in_recovery,current_setting('fsync') AS fsync,current_setting('full_page_writes') AS full_page_writes,current_setting('archive_mode') AS archive_mode,current_setting('synchronous_commit') AS synchronous_commit,current_setting('synchronous_standby_names') AS synchronous_standby_names");
    const d=durability.rows[0] as Record<string,unknown> | undefined;
    if (identity.rows[0]?.system_id !== p.newPgSystemId || !d || d.in_recovery !== false || d.fsync !== "on" || d.full_page_writes !== "on" || d.archive_mode !== "on" || !["on","local"].includes(String(d.synchronous_commit)) || d.synchronous_standby_names !== "") throw new Error("target PostgreSQL identity/standalone durability is unqualified");
    const stateResult=await client.query("SELECT * FROM fabric_state WHERE singleton=true FOR UPDATE");
    const state=stateResult.rows[0] as Record<string,unknown> | undefined;
    if (!state) throw new Error("restored PostgreSQL authority row is missing");
    const old=await client.query("SELECT plan_sha256,phase,receipts,canary_io_baseline_sha256 FROM fabric_cold_recoveries WHERE recovery_id=$1 FOR UPDATE",[p.recoveryId]);
    const previous=old.rows[0] as {plan_sha256:string;phase:string;receipts:Record<string,ColdLedgerReceipt>;canary_io_baseline_sha256:string|null} | undefined;
    if (previous && previous.plan_sha256 !== planHash) throw new Error("cold recovery identity has another ledger plan");
    if (auth.anchor.pending === null && (!previous?.receipts.accept || auth.anchor.lastReceiptSha256 !== digest(previous.receipts.accept))) throw new Error("accepted anchor requires the exact durable acceptance receipt");
    if (previous?.receipts[operation]) { await client.query("COMMIT"); return previous.receipts[operation]!; }
    if (operation === "hold") {
      if (previous || Number(state.current_epoch) !== p.expectedEpoch || state.leader_host_id !== p.sourceHost || (state.cold_recovery_phase && state.cold_recovery_phase !== "ACCEPTED") || Number(state.cold_recovery_generation ?? 0) >= p.generation) throw new Error("restored ledger authority differs or another recovery owns it");
      await client.query("INSERT INTO fabric_cold_recoveries(recovery_id,plan_sha256,generation,expected_epoch,next_epoch,source_host,target_host,phase,plan) VALUES($1,$2,$3,$4,$5,$6,$7,'LEDGER_HELD',$8::jsonb)",[p.recoveryId,planHash,p.generation,p.expectedEpoch,p.nextEpoch,p.sourceHost,p.targetHost,JSON.stringify(p)]);
      await client.query("INSERT INTO fabric_cold_task_quarantine(recovery_id,task_id,original_status,reason) SELECT $1,id,status,'post_snapshot_delivery_unknown' FROM fabric_tasks WHERE status IN ('queued','running') ON CONFLICT DO NOTHING",[p.recoveryId]);
      await client.query("INSERT INTO fabric_cold_effect_quarantine(recovery_id,effect_id,original_status,reason) SELECT $1,id,status,'post_snapshot_provider_delivery_unknown' FROM fabric_effect_outbox WHERE status <> 'delivered' ON CONFLICT DO NOTHING",[p.recoveryId]);
      await client.query("INSERT INTO fabric_cold_alarm_quarantine(recovery_id,alarm_id,original_status,reason) SELECT $1,id,status,'post_snapshot_alarm_delivery_unknown' FROM fabric_alarm_outbox WHERE status <> 'delivered' ON CONFLICT DO NOTHING",[p.recoveryId]);
      await client.query("INSERT INTO fabric_cold_artifact_quarantine(recovery_id,artifact_id,original_status,reason) SELECT $1,id,status,'post_snapshot_object_write_unknown' FROM fabric_artifacts WHERE status <> 'available' ON CONFLICT DO NOTHING",[p.recoveryId]);
      await client.query("UPDATE fabric_attempts SET status='fenced',finished_at=now(),error_code='cold_recovery_held',error_summary='restored attempt quarantined by offline cold recovery' WHERE status='running'");
      await client.query("UPDATE fabric_runs SET status='expired',finished_at=now() WHERE status='running'");
      await client.query("UPDATE fabric_worker_sessions SET status='fenced',ended_at=now(),end_reason='cold_recovery_held' WHERE status='active'");
      await client.query("UPDATE fabric_workers SET lease_expires_at=now(),updated_at=now()");
      await client.query("UPDATE fabric_state SET cold_recovery_id=$1,cold_recovery_phase='LEDGER_HELD',cold_recovery_generation=$2,cold_canary_task_id=$3,cold_canary_worker_id=$4,leader_lease_expires_at=NULL,updated_at=now() WHERE singleton=true",[p.recoveryId,p.generation,p.canary.taskId,p.canary.workerId]);
    } else {
      if (!previous || state.cold_recovery_id !== p.recoveryId || Number(state.cold_recovery_generation) !== p.generation) throw new Error("ledger has no matching held cold operation");
      if (operation === "commit") {
        if (previous.phase !== "LEDGER_HELD") throw new Error("ledger cold commit predecessor differs");
        // The separate store commit must actually exist; a coordinator claim alone is insufficient.
        const witness=new DatabaseSync(safeFile(p.targetDatabasePath),{readOnly:true});
        try {
          const row=witness.prepare("SELECT payload FROM witness_snapshot WHERE cluster_id=?").get(p.clusterId) as {payload:string} | undefined;
          const snapshot=row ? JSON.parse(row.payload) as {state?:{currentLeader:string;fabricEpoch:number};coldRecoveries?:Array<{recoveryId:string;planSha256:string}>} : undefined;
          if (snapshot?.state?.currentLeader !== p.targetHost || snapshot.state.fabricEpoch !== p.nextEpoch || !snapshot.coldRecoveries?.some((r)=>r.recoveryId===p.recoveryId && r.planSha256===planHash)) throw new Error("witness cold commit has not been read back");
        } finally { witness.close(); }
        await client.query("UPDATE fabric_state SET current_epoch=$1,leader_host_id=$2,leadership_cluster_id=$3,leadership_receipt_id=$4,leadership_fence_digest=$5,leader_lease_expires_at=NULL,leader_recovery_hold_until=NULL,cold_recovery_phase='LEDGER_COMMITTED_HELD',updated_at=now() WHERE singleton=true",[p.nextEpoch,p.targetHost,p.clusterId,p.recoveryId,planHash]);
      } else {
        if (Number(state.current_epoch)!==p.nextEpoch || state.leader_host_id!==p.targetHost || auth.anchor.highestEpoch!==p.nextEpoch || auth.anchor.leader!==p.targetHost || auth.anchor.publicKeySha256!==p.newPublicKeySha256 || auth.anchor.pending?.phase!=="ANCHOR_COMMITTED") throw new Error("committed anchor/ledger authority differs");
        if (operation === "canary") {
          if (previous.phase!=="LEDGER_COMMITTED_HELD") throw new Error("canary predecessor differs");
          if ((await client.query("SELECT id FROM fabric_tasks WHERE id=$1",[p.canary.taskId])).rowCount) throw new Error("canary task identity already exists");
          await client.query("UPDATE fabric_cold_recoveries SET canary_io_baseline_sha256=$2 WHERE recovery_id=$1",[p.recoveryId,await ioFootprint(client)]);
          await client.query("INSERT INTO fabric_tasks(id,namespace,queue_name,task_type,idempotency_key,request_hash,payload,required_capabilities,priority,status,max_attempts,provider,retry_backoff_seconds,config_fingerprint,available_at) VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,'[\"fabric.cold_canary\"]'::jsonb,0,'queued',1,'local',0,$8,now())",[p.canary.taskId,p.canary.namespace,p.canary.queue,p.canary.taskType,p.recoveryId,p.canary.payloadSha256,JSON.stringify(p.canary.payload),p.candidateConfigDigest]);
          await client.query("UPDATE fabric_state SET cold_recovery_phase='CANARY_ADMITTED',updated_at=now() WHERE singleton=true");
        } else {
          if (previous.phase!=="CANARY_ADMITTED") throw new Error("acceptance predecessor differs");
          const canary=await client.query("SELECT t.status,t.payload,t.task_type,t.queue_name,t.namespace,t.result,a.fabric_epoch,a.worker_id,a.status AS attempt_status,a.result AS attempt_result,w.host_id,w.provider,w.metadata FROM fabric_tasks t JOIN LATERAL (SELECT * FROM fabric_attempts WHERE task_id=t.id ORDER BY attempt_number DESC LIMIT 1) a ON true JOIN fabric_workers w ON w.worker_id=a.worker_id WHERE t.id=$1",[p.canary.taskId]);
          const c=canary.rows[0] as Record<string,unknown> | undefined;
          const effects=await client.query("SELECT count(*)::int AS count FROM fabric_effect_outbox WHERE task_id=$1",[p.canary.taskId]);
          const artifacts=await client.query("SELECT count(*)::int AS count FROM fabric_artifacts WHERE task_id=$1",[p.canary.taskId]);
          if (!c || c.status!=="succeeded" || c.attempt_status!=="succeeded" || Number(c.fabric_epoch)!==p.nextEpoch || c.worker_id!==p.canary.workerId || c.host_id!==p.targetHost || c.provider!=="local" || (c.metadata as Record<string,unknown>|null)?.coldCanaryHandler!=="fabric_cold_canary_v1" || digest(c.result)!==digest(expectedCanaryResult(p)) || digest(c.attempt_result)!==digest(expectedCanaryResult(p)) || c.task_type!==p.canary.taskType || c.queue_name!==p.canary.queue || c.namespace!==p.canary.namespace || digest(c.payload)!==p.canary.payloadSha256 || Number(effects.rows[0]?.count)!==0 || Number(artifacts.rows[0]?.count)!==0 || !previous.canary_io_baseline_sha256 || previous.canary_io_baseline_sha256!==await ioFootprint(client)) throw new Error("declared effect-free runtime canary has not completed without artifact or provider writes");
          await client.query("UPDATE fabric_state SET cold_recovery_phase='ACCEPTED',updated_at=now() WHERE singleton=true");
        }
      }
    }
    const receipt:ColdLedgerReceipt={schemaVersion:"execution-fabric-cold-ledger-receipt/v1",operation,recoveryId:p.recoveryId,planSha256:planHash,fabricEpoch:operation==="hold"?p.expectedEpoch:p.nextEpoch,generation:p.generation,held:operation!=="accept",residualQuarantine:true};
    const phase=operation==="hold"?"LEDGER_HELD":operation==="commit"?"LEDGER_COMMITTED_HELD":operation==="canary"?"CANARY_ADMITTED":"ACCEPTED";
    await client.query("UPDATE fabric_cold_recoveries SET phase=$2,receipts=receipts || jsonb_build_object($3::text,$4::jsonb),updated_at=now() WHERE recovery_id=$1",[p.recoveryId,phase,operation,JSON.stringify(receipt)]);
    await client.query("INSERT INTO fabric_events(event_id,aggregate_type,aggregate_id,event_type,fabric_epoch,data) VALUES($1,'cold_recovery',$2,$3,$4,$5::jsonb)",[randomUUID(),p.recoveryId,"cold_recovery."+operation,receipt.fabricEpoch,JSON.stringify(receipt)]);
    await client.query("COMMIT");
    return receipt;
  } catch (error) { await client.query("ROLLBACK"); throw error; }
  finally { client.release(); }
}
