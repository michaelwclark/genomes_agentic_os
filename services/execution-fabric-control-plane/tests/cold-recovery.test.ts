import { generateKeyPairSync, sign } from "node:crypto";
import { chmodSync, copyFileSync, lstatSync, mkdtempSync, readFileSync, readdirSync, realpathSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { spawnSync } from "node:child_process";
import { DatabaseSync } from "node:sqlite";
import { randomUUID, createHash } from "node:crypto";
import { createPool, migrate } from "../src/db.js";
import { ArtifactStore } from "../src/artifacts.js";
import { artifactRecoveryFinalizeSchema, artifactRecoveryUploadSchema } from "../src/contracts.js";
import { PostgresReliabilityStore } from "../src/reliability.js";
import type pg from "pg";
import { afterEach, describe, expect, it, vi } from "vitest";
import { authorizeColdRequest, canonical, coldPlanSchema, digest, expectedCanaryResult, runColdLedgerOperation, type ColdPlan } from "../src/cold-recovery.js";
import { PostgresLedger, type AdmissionConstraints, type WorkerConstraints } from "../src/ledger.js";
import { LeaderResolver, type GatewayConfig } from "../src/gateway.js";
import { PolicyManager } from "../src/policy.js";
import { parse, stringify } from "yaml";
import { dispositionApprovalBinding, inspectColdDisposition, runColdDisposition, type DispositionPayload } from "../src/cold-disposition.js";

function fixture() {
  const signer=generateKeyPairSync("ed25519"), fenceKey=generateKeyPairSync("ed25519");
  const now=Date.now(), stamp=(seconds:number)=>new Date(now+seconds*1000).toISOString();
  const policy={schemaVersion:"execution-fabric-cold-recovery-policy/v1",enabled:true,clusterId:"isolated-fabric",allowedHosts:["genomesbox","bigmac"],recoveryPublicKeyPem:signer.publicKey.export({type:"spki",format:"pem"}).toString(),fencePublicKeyPem:fenceKey.publicKey.export({type:"spki",format:"pem"}).toString(),maxApprovalSeconds:600,witnessActorSha256:"a".repeat(64),controlPlaneActorSha256:"b".repeat(64)};
  const originalAnchor={schemaVersion:"execution-fabric-recovery-anchor/v1",clusterId:policy.clusterId,leader:"genomesbox",generation:2,highestEpoch:6,publicKeySha256:"1".repeat(64),lastReceiptSha256:"c".repeat(64),pending:null};
  const payload={schema_version:"execution-fabric-cold-canary/v1" as const,recovery_id:"9b4bf200-4ac8-4a64-9969-07812e617d81",cluster_id:policy.clusterId,epoch:7,generation:3};
  const plan:ColdPlan={schemaVersion:"execution-fabric-cold-recovery-plan/v1",recoveryId:"9b4bf200-4ac8-4a64-9969-07812e617d81",direction:"recovery",clusterId:policy.clusterId,sourceHost:"genomesbox",targetHost:"bigmac",expectedEpoch:4,nextEpoch:7,generation:3,anchorSha256:digest(originalAnchor),policySha256:digest(policy),restoreInputSha256:"d".repeat(64),manifestSha256:"e".repeat(64),restoreReceiptSha256:"f".repeat(64),snapshotVersion:3,originalDatabasePath:"/isolated/original.sqlite",originalBackupPath:"/isolated/original.sqlite.backup",targetDatabasePath:"/isolated/target.sqlite",databaseSha256:"2".repeat(64),sentinelSha256:"3".repeat(64),backupSha256:"4".repeat(64),hostMarkerSha256:"5".repeat(64),oldPublicKeySha256:originalAnchor.publicKeySha256,newPublicKeySha256:"6".repeat(64),candidateConfigDigest:"7".repeat(64),newPgSystemId:"12345",timelineId:1,walPosition:0,createdAt:stamp(-1),expiresAt:stamp(500),canary:{taskId:"c86c6c43-e638-4d37-a0f6-9e423ff7d764",workerId:"isolated-canary",taskType:"fabric.cold_canary",queue:"fabric_cold_recovery",namespace:"fabric_cold_recovery",payload,payloadSha256:digest(payload)}};
  const restoreInput={schemaVersion:"execution-fabric-cold-restore-input/v1",recoverySetId:"20261009T230000Z-012345abcdef",manifestSha256:plan.manifestSha256,restoreReceiptSha256:plan.restoreReceiptSha256,sourceRelease:"0.10.1",imageLockSha256:"f".repeat(64),capturedAt:stamp(-5),commonWatermark:"isolated-quiescent-watermark",custodyReceiptSha256:"b".repeat(64),witness:{clusterId:plan.clusterId,version:plan.snapshotVersion,leader:plan.sourceHost,epoch:plan.expectedEpoch,auditTailSha256:"a".repeat(64),databaseSha256:plan.databaseSha256,sentinelSha256:plan.sentinelSha256,backupSha256:plan.backupSha256,hostMarkerSha256:plan.hostMarkerSha256,originalDatabasePath:plan.originalDatabasePath,originalBackupPath:plan.originalBackupPath,signingPublicKeySha256:plan.oldPublicKeySha256},postgres:{dumpSha256:"d".repeat(64),restoreReadbackSha256:"e".repeat(64),systemId:plan.newPgSystemId,majorVersion:17},artifacts:{inventorySha256:"f".repeat(64),verifiedReferences:true},osAuthority:{snapshotSha256:"a".repeat(64),immutableReceiptInventorySha256:"b".repeat(64)}};
  plan.restoreInputSha256=digest(restoreInput);
  const signed=(payload:unknown,key=signer.privateKey)=>({payload,signature:sign(null,Buffer.from(canonical(payload)),key).toString("base64")});
  const fence=signed({schemaVersion:"execution-fabric-external-fence/v1",recoveryId:plan.recoveryId,clusterId:plan.clusterId,sourceHost:plan.sourceHost,sourceBootId:"original-boot",durable:true,highestGeneration:2,highestEpoch:6,coveredWriterScopes:["witness","postgres","producer","provider"],evidenceSha256:"8".repeat(64),issuedAt:stamp(-1),expiresAt:stamp(500)},fenceKey.privateKey);
  const request={plan,restoreInput,fence,approval:signed({schemaVersion:"execution-fabric-cold-recovery-approval/v1",planSha256:digest(plan),policySha256:digest(policy),fenceSha256:digest(fence),approvedBy:"isolated-operator",issuedAt:stamp(-1),expiresAt:stamp(500)})};
  const anchor={...originalAnchor,leader:"bigmac",generation:3,highestEpoch:7,publicKeySha256:plan.newPublicKeySha256,pending:{recoveryId:plan.recoveryId,planSha256:digest(plan),generation:3,nextEpoch:7,targetHost:"bigmac",phase:"ANCHOR_COMMITTED"}};
  return {policy,plan,request,anchor,signer,signed,fenceKey};
}
function poolFixture(f:ReturnType<typeof fixture>, overrides:Record<string,unknown>={}) {
  const canary={status:"succeeded",attempt_status:"succeeded",fabric_epoch:7,worker_id:f.plan.canary.workerId,host_id:f.plan.targetHost,provider:"local",metadata:{coldCanaryHandler:"fabric_cold_canary_v1"},result:expectedCanaryResult(f.plan),attempt_result:expectedCanaryResult(f.plan),task_type:f.plan.canary.taskType,queue_name:f.plan.canary.queue,namespace:f.plan.canary.namespace,payload:f.plan.canary.payload,...overrides};
  const state={current_epoch:7,leader_host_id:"bigmac",cold_recovery_id:f.plan.recoveryId,cold_recovery_generation:3,
    cold_recovery_phase:"CANARY_ADMITTED",cold_canary_task_id:f.plan.canary.taskId,cold_canary_worker_id:f.plan.canary.workerId,
    leadership_cluster_id:f.plan.clusterId,policy_fingerprint:f.plan.candidateConfigDigest,...overrides.state as Record<string,unknown>};
  const recovery={plan_sha256:digest(f.plan),phase:"CANARY_ADMITTED",receipts:{},canary_io_baseline_sha256:digest([]),
    generation:3,expected_epoch:4,next_epoch:7,source_host:"genomesbox",target_host:"bigmac",plan:f.plan,...overrides.recovery as Record<string,unknown>};
  const query=vi.fn(async(sql:string,_parameters?:unknown[])=>{
    let rows:unknown[]=[];
    if(sql.includes("FROM pg_control_system"))rows=[{system_id:"12345"}];
    else if(sql.includes("pg_is_in_recovery"))rows=[{in_recovery:false,fsync:"on",full_page_writes:"on",archive_mode:"on",synchronous_commit:"on",synchronous_standby_names:""}];
    else if(sql.startsWith("SELECT * FROM fabric_state"))rows=overrides.missingState?[]:[state];
    else if(sql.includes("SELECT plan_sha256,phase,receipts"))rows=overrides.missingRecovery?[]:[recovery];
    else if(sql.startsWith("SELECT t.status"))rows=[canary];
    else if(sql.startsWith("SELECT count(*)::int"))rows=[{count:sql.includes("fabric_artifacts") ? overrides.artifactCount??0 : overrides.effectCount??0}];
    else if(sql.startsWith("SELECT 'effect'") && overrides.ioMutation)rows=[{kind:"effect",id:"foreign",digest:"changed"}];
    return {rows,rowCount:rows.length};
  });
  const pool={connect:vi.fn(async()=>({query,release:vi.fn()}))} as unknown as pg.Pool;
  return {pool,query};
}
const committedWitnessUnitRoots:string[]=[];
afterEach(()=>{for(const root of committedWitnessUnitRoots.splice(0))rmSync(root,{recursive:true,force:true});});
function committedWitnessUnitFixture(f:ReturnType<typeof fixture>) {
  // Actual private SQLite bytes, with explicit storage-only provenance. This
  // does not qualify an original store producer, relocation or host recovery.
  const root=realpathSync(mkdtempSync(join(tmpdir(),"cold-witness-unit-")));committedWitnessUnitRoots.push(root);
  f.plan.targetDatabasePath=join(root,"witness.sqlite");
  f.request.approval=f.signed({...f.request.approval.payload as Record<string,unknown>,planSha256:digest(f.plan)});
  f.anchor.pending.planSha256=digest(f.plan);
  const snapshot={state:{currentLeader:f.plan.targetHost,fabricEpoch:f.plan.nextEpoch,authorityMode:"standalone_primary",
    configDigest:f.plan.candidateConfigDigest,upstreamSystemId:f.plan.newPgSystemId},coldRecoveries:[{
    schemaVersion:"execution-fabric-cold-witness-receipt/v1",recoveryId:f.plan.recoveryId,planSha256:digest(f.plan),
    fabricEpoch:f.plan.nextEpoch,generation:f.plan.generation,held:true,previousLeader:f.plan.sourceHost,currentLeader:f.plan.targetHost,
    originalDatabasePath:f.plan.originalDatabasePath,targetDatabasePath:f.plan.targetDatabasePath,newPublicKeySha256:f.plan.newPublicKeySha256}]};
  const sentinel={schemaVersion:"execution-fabric-witness-bootstrap/v1",clusterId:f.plan.clusterId,
    database:f.plan.targetDatabasePath,backup:f.plan.targetDatabasePath+".backup",initializedAt:new Date().toISOString()};
  let initialBackupCreated=false;
  const write=()=>{
    const db=new DatabaseSync(f.plan.targetDatabasePath);
    try {db.exec("CREATE TABLE IF NOT EXISTS witness_snapshot(cluster_id TEXT PRIMARY KEY,version INTEGER NOT NULL,payload TEXT NOT NULL)");
      db.prepare("INSERT OR REPLACE INTO witness_snapshot(cluster_id,version,payload) VALUES(?,1,?)").run(f.plan.clusterId,canonical(snapshot));}
    finally {db.close();}
    chmodSync(f.plan.targetDatabasePath,0o600);writeFileSync(f.plan.targetDatabasePath+".initialized",canonical(sentinel),{mode:0o600});
    if(!initialBackupCreated){
      // Preserve actual initial storage bytes. Later intentional state drift
      // tests do not replace this backup or claim native backup qualification.
      writeFileSync(f.plan.targetDatabasePath+".backup",readFileSync(f.plan.targetDatabasePath),{mode:0o600,flag:"wx"});
      expect(lstatSync(f.plan.targetDatabasePath+".backup").mode&0o077).toBe(0);
      initialBackupCreated=true;
    }
  };
  write();return {snapshot,sentinel,write};
}
function signedPolicyTransitionUnitFixture(f:ReturnType<typeof fixture>) {
  // Actual native policy parsing with a query/storage seam. Only the isolated
  // PG fixture below qualifies supported activation and durable mutation.
  const root=realpathSync(mkdtempSync(join(tmpdir(),"cold-policy-unit-")));committedWitnessUnitRoots.push(root);
  const sourceBytes=readFileSync(resolve(process.cwd(),"../../harness/config/execution-fabric.yml"));
  const sourceFile=join(root,"source.yml"),candidateFile=join(root,"candidate.yml");
  writeFileSync(sourceFile,sourceBytes,{mode:0o600});
  const value=parse(sourceBytes.toString());
  value.execution_fabric.queues.find((q:{id:string})=>q.id==="fabric_cold_recovery").enabled=true;
  value.execution_fabric.worker_pools.find((p:{id:string})=>p.id==="fabric_cold_recovery_workers").enabled=true;
  const candidateBytes=Buffer.from(stringify(value));writeFileSync(candidateFile,candidateBytes,{mode:0o600});
  const source=new PolicyManager(sourceFile,"canonical-source-schema"),candidate=new PolicyManager(candidateFile,"canonical-source-schema");
  f.plan.candidateConfigDigest=candidate.snapshot().appliedFingerprint;
  f.plan.policyTransition={expectedSourceFingerprint:source.snapshot().appliedFingerprint,candidateExecutionPolicyFile:candidateFile,
    candidateExecutionPolicySha256:createHash("sha256").update(candidateBytes).digest("hex")};
  const witness=committedWitnessUnitFixture(f);
  return {source,candidate,candidateFile,candidateBytes,sourceBytes,witness};
}
describe("cold recovery held control plane (isolated unit seams)",()=>{
  it.each(["expectedSourceFingerprint","candidateExecutionPolicySha256"] as const)("refuses final newline in optional transition %s at the closed structural boundary",(field)=>{
    const f=fixture(),legacyBytes=canonical(f.plan),legacyHash=digest(f.plan);
    const legacy=coldPlanSchema.parse(f.plan);
    expect(canonical(legacy)).toBe(legacyBytes);expect(digest(legacy)).toBe(legacyHash);
    expect(legacy).not.toHaveProperty("policyTransition");
    const plan={...f.plan,policyTransition:{expectedSourceFingerprint:"a".repeat(64),
      candidateExecutionPolicyFile:"/isolated/candidate-execution-policy.yml",candidateExecutionPolicySha256:"b".repeat(64)}};
    const bytes=canonical(plan),hash=digest(plan),valid=coldPlanSchema.parse(plan);
    expect(canonical(valid)).toBe(bytes);expect(digest(valid)).toBe(hash);
    const malformed={...plan,policyTransition:{...plan.policyTransition,[field]:plan.policyTransition[field]+"\n"}};
    const result=coldPlanSchema.safeParse(malformed);
    expect(result.success).toBe(false);
    if(result.success)throw new Error("optional transition hash accepted a final newline");
    expect(result.error.issues).toEqual([
      expect.objectContaining({code:"invalid_string",validation:"regex",path:["policyTransition",field]}),
      expect.objectContaining({code:"too_big",maximum:64,type:"string",inclusive:true,exact:true,path:["policyTransition",field]})]);
    // Only the production structural schema is exercised. No malformed
    // signature is sent to authority, PostgreSQL, a provider or a canary.
    expect(canonical(f.plan)).toBe(legacyBytes);expect(digest(f.plan)).toBe(legacyHash);
    expect(canonical(plan)).toBe(bytes);expect(digest(plan)).toBe(hash);
  });
  function rebindSetId(f:ReturnType<typeof fixture>,recoverySetId:string):void {
    f.request.restoreInput.recoverySetId=recoverySetId;f.plan.restoreInputSha256=digest(f.request.restoreInput);
    f.request.approval=f.signed({...f.request.approval.payload as Record<string,unknown>,planSha256:digest(f.plan)});
    f.anchor.pending.planSha256=digest(f.plan);
  }
  it.each(["20261009T230000Z-012345abcdef","3ebd266b-2f8d-4b85-9e6d-cd908a232eb0","A","a_B.c-d","A"+"x".repeat(127)])("authorizes original bounded manifest set ID without aliases: %s",(setId)=>{
    const f=fixture();rebindSetId(f,setId);
    expect(authorizeColdRequest(f.request,f.policy,f.anchor).plan.restoreInputSha256).toBe(digest(f.request.restoreInput));
    expect(f.request.restoreInput.recoverySetId).toBe(setId);
  });
  it.each(["","../escape","/absolute","a/b","a\\b",".hidden","_leading","-leading","white space","a\n","a\r","a\u2028","a\0","é","💥","A"+"x".repeat(128)])("unsafe or oversized set ID refuses before PostgreSQL: %j",async(setId)=>{
    const f=fixture(),p=poolFixture(f);rebindSetId(f,setId);
    await expect(runColdLedgerOperation(p.pool,"accept",f.request,f.policy,f.anchor)).rejects.toThrow();
    expect(p.pool.connect).not.toHaveBeenCalled();
  });
  it.each(["recoveryId","taskId"])("transition %s still requires UUID before PostgreSQL",async(field)=>{
    const f=fixture(),p=poolFixture(f);
    if(field==="recoveryId")f.plan.recoveryId="20261009T230000Z-012345abcdef";else f.plan.canary.taskId="20261009T230000Z-012345abcdef";
    await expect(runColdLedgerOperation(p.pool,"accept",f.request,f.policy,f.anchor)).rejects.toThrow(/uuid/);
    expect(p.pool.connect).not.toHaveBeenCalled();
  });
  it.each([
    {status:"queued"},
    {attempt_status:"failed"},
    {worker_id:"foreign-worker"},
    {host_id:"genomesbox"},
    {provider:"claude"},
    {metadata:{coldCanaryHandler:"claude_task"}},
    {result:{}},
    {attempt_result:{schemaVersion:"execution-fabric-cold-canary-result/v1",epoch:6}},
    {fabric_epoch:4},
    {payload:{probe:"changed"}},
    {effectCount:1},
    {artifactCount:1},
    {ioMutation:true},
  ])("acceptance refuses unfinished, foreign, stale or effectful canary: %j",async(overrides)=>{
    const f=fixture();committedWitnessUnitFixture(f);const p=poolFixture(f,overrides);
    await expect(runColdLedgerOperation(p.pool,"accept",f.request,f.policy,f.anchor)).rejects.toThrow(/effect-free runtime canary/);
    expect(p.query.mock.calls.filter(([sql])=>/^(INSERT|UPDATE|DELETE)/.test(sql))).toHaveLength(0);
    expect(p.query.mock.calls.some(([sql])=>sql==="ROLLBACK")).toBe(true);
  });
  it("successful canary receipt keeps residual restored-work quarantine",async()=>{
    const f=fixture();committedWitnessUnitFixture(f);const p=poolFixture(f);
    expect(await runColdLedgerOperation(p.pool,"accept",f.request,f.policy,f.anchor)).toMatchObject({operation:"accept",fabricEpoch:7,generation:3,held:false,residualQuarantine:true});
    expect(p.query.mock.calls.some(([sql])=>sql==="COMMIT")).toBe(true);
  });
  const acceptedCache=(f:ReturnType<typeof fixture>,changes:Record<string,unknown>={})=>{
    const receipt={schemaVersion:"execution-fabric-cold-ledger-receipt/v1",operation:"accept",recoveryId:f.plan.recoveryId,
      planSha256:digest(f.plan),fabricEpoch:7,generation:3,held:false,residualQuarantine:true};
    const anchor={...f.anchor,pending:null,lastReceiptSha256:digest(receipt)};
    const p=poolFixture(f,{state:{cold_recovery_phase:"ACCEPTED",...changes.state as Record<string,unknown>},
      recovery:{phase:"ACCEPTED",receipts:{accept:receipt},...changes.recovery as Record<string,unknown>},
      missingState:changes.missingState,missingRecovery:changes.missingRecovery});
    return {...p,receipt,anchor};
  };
  it("reuses exact accepted receipt only under unchanged current PG and selected witness authority",async()=>{
    const f=fixture();committedWitnessUnitFixture(f);const p=acceptedCache(f),before=canonical({receipt:p.receipt,anchor:p.anchor});
    expect(await runColdLedgerOperation(p.pool,"accept",f.request,f.policy,p.anchor)).toEqual(p.receipt);
    expect(canonical({receipt:p.receipt,anchor:p.anchor})).toBe(before);
    expect(p.query.mock.calls.filter(([sql])=>/^\s*(INSERT|UPDATE|DELETE)/.test(sql))).toEqual([]);
    expect(p.query.mock.calls.map(([sql])=>sql)).toContain("COMMIT");
  });
  it.each([
    {state:{cold_recovery_id:randomUUID()}},{state:{cold_recovery_generation:4}},{state:{current_epoch:8}},
    {state:{leader_host_id:"genomesbox"}},{state:{cold_recovery_phase:"LEDGER_HELD"}},
    {state:{leadership_cluster_id:"foreign"}},{state:{policy_fingerprint:"0".repeat(64)}},
    {state:{cold_canary_task_id:randomUUID()}},{state:{cold_canary_worker_id:"foreign"}},
    {recovery:{phase:"CANARY_ADMITTED"}},{recovery:{generation:4}},{recovery:{expected_epoch:3}},
    {recovery:{next_epoch:8}},{recovery:{source_host:"foreign"}},{recovery:{target_host:"genomesbox"}},
    {recovery:{plan:{foreign:true}}},
  ])("cached acceptance refuses conflicting current authority without replacing history: %j",async(changes)=>{
    const f=fixture();committedWitnessUnitFixture(f);const p=acceptedCache(f,changes),before=canonical({receipt:p.receipt,anchor:p.anchor});
    const stored=changes.recovery as Record<string,unknown>|undefined;
    await expect(runColdLedgerOperation(p.pool,"accept",f.request,f.policy,p.anchor)).rejects.toThrow(
      stored&&Object.keys(stored).some(key=>key!=="phase")?/stored cold predecessor identity differs/:/cached cold receipt current authority differs/);
    expect(canonical({receipt:p.receipt,anchor:p.anchor})).toBe(before);
    expect(p.query.mock.calls.filter(([sql])=>/^\s*(INSERT|UPDATE|DELETE)/.test(sql))).toEqual([]);
    expect(p.query.mock.calls.map(([sql])=>sql)).toContain("ROLLBACK");
  });
  it.each(["missingState","missingRecovery"])("cached acceptance refuses %s with old receipt/anchor intact",async(seam)=>{
    const f=fixture();committedWitnessUnitFixture(f);const p=acceptedCache(f,{[seam]:true}),before=canonical({receipt:p.receipt,anchor:p.anchor});
    await expect(runColdLedgerOperation(p.pool,"accept",f.request,f.policy,p.anchor)).rejects.toThrow();
    expect(canonical({receipt:p.receipt,anchor:p.anchor})).toBe(before);
    expect(p.query.mock.calls.filter(([sql])=>/^\s*(INSERT|UPDATE|DELETE)/.test(sql))).toEqual([]);
  });
  it.each([
    {state:{cold_recovery_id:randomUUID()}},{state:{cold_recovery_generation:4}},{state:{current_epoch:8}},
    {state:{leader_host_id:"genomesbox"}},{state:{cold_recovery_phase:"LEDGER_HELD"}},
    {state:{leadership_cluster_id:"foreign"}},{state:{policy_fingerprint:"0".repeat(64)}},
    {state:{cold_canary_task_id:randomUUID()}},{state:{cold_canary_worker_id:"foreign"}},
    {recovery:{phase:"LEDGER_COMMITTED_HELD"}},{recovery:{generation:4}},{recovery:{expected_epoch:3}},
    {recovery:{next_epoch:8}},{recovery:{source_host:"foreign"}},{recovery:{target_host:"genomesbox"}},
    {recovery:{plan:{foreign:true}}},
  ])("first acceptance refuses independently changed current predecessor authority: %j",async(changes)=>{
    const f=fixture();committedWitnessUnitFixture(f);const p=poolFixture(f,changes),before=canonical(f.anchor);
    const stored=changes.recovery as Record<string,unknown>|undefined;
    await expect(runColdLedgerOperation(p.pool,"accept",f.request,f.policy,f.anchor)).rejects.toThrow(
      stored&&Object.keys(stored).some(key=>key!=="phase")?/stored cold predecessor identity differs/:/authority|matching|predecessor/);
    expect(canonical(f.anchor)).toBe(before);
    expect(p.query.mock.calls.filter(([sql])=>/^\s*(INSERT|UPDATE|DELETE)/.test(sql))).toEqual([]);
    expect(p.query.mock.calls.map(([sql])=>sql)).toContain("ROLLBACK");
  });
  it.each([{cold_recovery_phase:"LEDGER_COMMITTED_HELD"},{current_epoch:5},{leader_host_id:"bigmac"}])(
    "fresh commit refuses changed source predecessor before writes: %j",async(delta)=>{
      const f=fixture();committedWitnessUnitFixture(f);
      const p=poolFixture(f,{state:{cold_recovery_phase:"LEDGER_HELD",current_epoch:4,leader_host_id:"genomesbox",...delta},recovery:{phase:"LEDGER_HELD"}});
      await expect(runColdLedgerOperation(p.pool,"commit",f.request,f.policy,f.anchor)).rejects.toThrow(/ledger cold commit current source authority differs/);
      expect(p.query.mock.calls.filter(([sql])=>/^\s*(INSERT|UPDATE|DELETE)/.test(sql))).toEqual([]);
      expect(p.query.mock.calls.map(([sql])=>sql)).toContain("ROLLBACK");
    });
  it.each(["commit","canary"] as const)("fresh %s refuses each inconsistent stored predecessor before writes",async(operation)=>{
    for(const field of ["plan_sha256","plan","generation","expected_epoch","next_epoch","source_host","target_host"]){
      const f=fixture();committedWitnessUnitFixture(f);
      const receipt={schemaVersion:"execution-fabric-cold-ledger-receipt/v1",operation:operation==="commit"?"hold":"commit",
        recoveryId:f.plan.recoveryId,planSha256:digest(f.plan),fabricEpoch:operation==="commit"?4:7,generation:3,held:true,residualQuarantine:true};
      const drift:Record<string,unknown>={plan_sha256:"0".repeat(64),plan:{...f.plan,timelineId:2},generation:4,
        expected_epoch:3,next_epoch:8,source_host:"foreign",target_host:"foreign"};
      const phase=operation==="commit"?"LEDGER_HELD":"LEDGER_COMMITTED_HELD";
      const predecessor={phase,receipts:{[receipt.operation]:receipt},[field]:drift[field]};
      const p=poolFixture(f,{state:{cold_recovery_phase:phase,current_epoch:operation==="commit"?4:7,
        leader_host_id:operation==="commit"?"genomesbox":"bigmac"},recovery:predecessor});
      const before=canonical({anchor:f.anchor,predecessor});
      await expect(runColdLedgerOperation(p.pool,operation,f.request,f.policy,f.anchor)).rejects.toThrow(
        field==="plan_sha256"?/cold recovery identity has another ledger plan/:/stored cold predecessor identity differs/);
      expect(canonical({anchor:f.anchor,predecessor})).toBe(before);
      expect(p.query.mock.calls.filter(([sql])=>/^\s*(INSERT|UPDATE|DELETE)/.test(sql))).toEqual([]);
      expect(p.query.mock.calls.map(([sql])=>sql)).toContain("ROLLBACK");
    }
  });
  it.each([{cold_canary_task_id:randomUUID()},{cold_canary_worker_id:"foreign-worker"}])(
    "fresh commit refuses changed declared held canary identity before authority update: %j",async(delta)=>{
      const f=fixture();committedWitnessUnitFixture(f);
      const receipt={schemaVersion:"execution-fabric-cold-ledger-receipt/v1",operation:"hold",recoveryId:f.plan.recoveryId,
        planSha256:digest(f.plan),fabricEpoch:4,generation:3,held:true,residualQuarantine:true};
      const p=poolFixture(f,{state:{cold_recovery_phase:"LEDGER_HELD",current_epoch:4,leader_host_id:"genomesbox",...delta},
        recovery:{phase:"LEDGER_HELD",receipts:{hold:receipt}}});
      const before=canonical({anchor:f.anchor,receipt});
      await expect(runColdLedgerOperation(p.pool,"commit",f.request,f.policy,f.anchor)).rejects.toThrow(/ledger cold commit current source authority differs/);
      expect(canonical({anchor:f.anchor,receipt})).toBe(before);
      expect(p.query.mock.calls.filter(([sql])=>/^\s*(INSERT|UPDATE|DELETE)/.test(sql))).toEqual([]);
      expect(p.query.mock.calls.map(([sql])=>sql)).toContain("ROLLBACK");
    });
  it("legacy commit refuses an A-to-B change without a signed policy transition",async()=>{
    const f=fixture();committedWitnessUnitFixture(f);
    const p=poolFixture(f,{state:{cold_recovery_phase:"LEDGER_HELD",current_epoch:4,leader_host_id:"genomesbox",policy_fingerprint:"0".repeat(64)},recovery:{phase:"LEDGER_HELD"}});
    await expect(runColdLedgerOperation(p.pool,"commit",f.request,f.policy,f.anchor)).rejects.toThrow(/signed transition is missing/);
    expect(p.query.mock.calls.filter(([sql])=>/^\s*(INSERT|UPDATE|DELETE)/.test(sql))).toEqual([]);
    expect(p.query.mock.calls.map(([sql])=>sql)).toContain("ROLLBACK");
  });
  it("legacy unchanged-policy commit preserves the private target storage seam",async()=>{
    const f=fixture();committedWitnessUnitFixture(f);
    const p=poolFixture(f,{state:{cold_recovery_phase:"LEDGER_HELD",current_epoch:4,leader_host_id:"genomesbox"},recovery:{phase:"LEDGER_HELD"}});
    expect(await runColdLedgerOperation(p.pool,"commit",f.request,f.policy,f.anchor)).toMatchObject({operation:"commit",fabricEpoch:7,generation:3,held:true});
    expect(p.query.mock.calls.map(([sql])=>sql)).toContain("COMMIT");
  });
  it("signed transition loads actual operational B and binds the atomic state update",async()=>{
    const f=fixture(),transition=signedPolicyTransitionUnitFixture(f);
    const source=transition.source.snapshot().appliedFingerprint,candidate=transition.candidate.snapshot().appliedFingerprint;
    expect(source).not.toBe(candidate);
    const p=poolFixture(f,{state:{cold_recovery_phase:"LEDGER_HELD",current_epoch:4,leader_host_id:"genomesbox",policy_fingerprint:source},recovery:{phase:"LEDGER_HELD"}});
    expect(await runColdLedgerOperation(p.pool,"commit",f.request,f.policy,f.anchor)).toMatchObject({operation:"commit",held:true});
    expect(p.query.mock.calls.find(([sql])=>sql.startsWith("UPDATE fabric_state SET current_epoch="))?.[1]?.[5]).toBe(candidate);
    expect(p.query.mock.calls.map(([sql])=>sql)).toContain("COMMIT");
    expect(createHash("sha256").update(readFileSync(transition.candidateFile)).digest("hex")).toBe(f.plan.policyTransition!.candidateExecutionPolicySha256);
  });
  it.each(["hold","commit"] as const)("signed %s refuses a current source fingerprint mismatch without writes",async(operation)=>{
    const f=fixture();signedPolicyTransitionUnitFixture(f);
    const p=poolFixture(f,{state:{cold_recovery_phase:operation==="hold"?null:"LEDGER_HELD",cold_recovery_generation:operation==="hold"?2:3,
      current_epoch:4,leader_host_id:"genomesbox",policy_fingerprint:"0".repeat(64)},recovery:{phase:"LEDGER_HELD"},missingRecovery:operation==="hold"});
    await expect(runColdLedgerOperation(p.pool,operation,f.request,f.policy,f.anchor)).rejects.toThrow(/source.*policy differs/);
    expect(p.query.mock.calls.filter(([sql])=>/^\s*(INSERT|UPDATE|DELETE)/.test(sql))).toEqual([]);
    expect(p.query.mock.calls.map(([sql])=>sql)).toContain("ROLLBACK");
  });
  it("legacy source policy mismatch refuses hold before quarantine or fencing writes",async()=>{
    const f=fixture(),before=canonical(f.anchor);
    const p=poolFixture(f,{state:{current_epoch:4,leader_host_id:"genomesbox",cold_recovery_id:null,cold_recovery_phase:null,
      cold_recovery_generation:2,policy_fingerprint:"0".repeat(64)},missingRecovery:true});
    await expect(runColdLedgerOperation(p.pool,"hold",f.request,f.policy,f.anchor)).rejects.toThrow(/restored source execution policy differs/);
    expect(canonical(f.anchor)).toBe(before);
    expect(p.query.mock.calls.filter(([sql])=>/^\s*(INSERT|UPDATE|DELETE)/.test(sql))).toEqual([]);
    expect(p.query.mock.calls.map(([sql])=>sql)).toContain("ROLLBACK");
  });
  it.each([false,true])("cached source-held receipt refuses policy drift, signed transition=%s",async(signedTransition)=>{
    const f=fixture();if(signedTransition)signedPolicyTransitionUnitFixture(f);
    const receipt={schemaVersion:"execution-fabric-cold-ledger-receipt/v1",operation:"hold",recoveryId:f.plan.recoveryId,
      planSha256:digest(f.plan),fabricEpoch:4,generation:3,held:true,residualQuarantine:true};
    const p=poolFixture(f,{state:{current_epoch:4,leader_host_id:"genomesbox",cold_recovery_phase:"LEDGER_HELD",policy_fingerprint:"0".repeat(64)},
      recovery:{phase:"LEDGER_HELD",receipts:{hold:receipt}}});
    const before=canonical({anchor:f.anchor,receipt});
    await expect(runColdLedgerOperation(p.pool,"hold",f.request,f.policy,f.anchor)).rejects.toThrow(/cached cold receipt current authority differs/);
    expect(canonical({anchor:f.anchor,receipt})).toBe(before);
    expect(p.query.mock.calls.filter(([sql])=>/^\s*(INSERT|UPDATE|DELETE)/.test(sql))).toEqual([]);
    expect(p.query.mock.calls.map(([sql])=>sql)).toContain("ROLLBACK");
  });
  it.each(["bytes","path","unsafe","fingerprint","invalid-policy","unknown-descriptor"])(
    "signed candidate %s refuses before opening the PG seam",async(kind)=>{
      const f=fixture(),transition=signedPolicyTransitionUnitFixture(f),p=poolFixture(f);
      if(kind==="bytes")writeFileSync(transition.candidateFile,Buffer.concat([transition.candidateBytes,Buffer.from("\n# changed\n")]));
      if(kind==="path")f.plan.policyTransition!.candidateExecutionPolicyFile=join(dirname(transition.candidateFile),"absent.yml");
      if(kind==="unsafe")chmodSync(transition.candidateFile,0o620);
      if(kind==="fingerprint")f.plan.candidateConfigDigest="0".repeat(64);
      if(kind==="invalid-policy"){
        const bytes=Buffer.from("execution_fabric: invalid\n");writeFileSync(transition.candidateFile,bytes);
        f.plan.policyTransition!.candidateExecutionPolicySha256=createHash("sha256").update(bytes).digest("hex");
      }
      if(kind==="unknown-descriptor")Object.assign(f.plan.policyTransition!,{allowUnsafe:true});
      f.request.approval=f.signed({...f.request.approval.payload as Record<string,unknown>,planSha256:digest(f.plan)});
      f.anchor.pending.planSha256=digest(f.plan);
      await expect(runColdLedgerOperation(p.pool,"commit",f.request,f.policy,f.anchor)).rejects.toThrow();
      expect(p.pool.connect).not.toHaveBeenCalled();
      expect(p.query).not.toHaveBeenCalled();
    });
  it.each(["bytes","inode","expiry"])("candidate %s drift before final COMMIT rolls back the unit query seam",async(kind)=>{
    const f=fixture(),transition=signedPolicyTransitionUnitFixture(f);
    const p=poolFixture(f,{state:{cold_recovery_phase:"LEDGER_HELD",current_epoch:4,leader_host_id:"genomesbox",policy_fingerprint:transition.source.snapshot().appliedFingerprint},recovery:{phase:"LEDGER_HELD"}});
    const query=p.query.getMockImplementation()!,anchorBefore=canonical(f.anchor);let changed=false;
    p.query.mockImplementation(async(sql,parameters)=>{
      const result=await query(sql,parameters);
      if(!changed&&sql.startsWith("INSERT INTO fabric_events")){
        changed=true;
        if(kind==="bytes")writeFileSync(transition.candidateFile,Buffer.concat([transition.candidateBytes,Buffer.from("\n# concurrent drift\n")]));
        if(kind==="inode"){
          const replacement=transition.candidateFile+".replacement";
          writeFileSync(replacement,transition.candidateBytes,{mode:0o600,flag:"wx"});renameSync(replacement,transition.candidateFile);
        }
        if(kind==="expiry")vi.spyOn(Date,"now").mockReturnValue(Date.parse(f.plan.expiresAt)+1);
      }
      return result;
    });
    try {
      await expect(runColdLedgerOperation(p.pool,"commit",f.request,f.policy,f.anchor)).rejects.toThrow(/identity or bytes differ|expired/);
      expect(changed).toBe(true);expect(canonical(f.anchor)).toBe(anchorBefore);
      expect(p.query.mock.calls.map(([sql])=>sql)).toContain("ROLLBACK");
      expect(p.query.mock.calls.map(([sql])=>sql)).not.toContain("COMMIT");
    } finally {vi.restoreAllMocks();}
  });
  it.each([{cold_recovery_phase:"CANARY_ADMITTED"},{leadership_cluster_id:"foreign"},{policy_fingerprint:"0".repeat(64)},
    {cold_canary_task_id:randomUUID()},{cold_canary_worker_id:"foreign"}])(
    "fresh canary refuses changed committed predecessor before ingress: %j",async(delta)=>{
      const f=fixture();committedWitnessUnitFixture(f);
      const p=poolFixture(f,{state:{cold_recovery_phase:"LEDGER_COMMITTED_HELD",...delta},recovery:{phase:"LEDGER_COMMITTED_HELD"}});
      await expect(runColdLedgerOperation(p.pool,"canary",f.request,f.policy,f.anchor)).rejects.toThrow(/canary current predecessor authority differs/);
      expect(p.query.mock.calls.filter(([sql])=>/^\s*(INSERT|UPDATE|DELETE)/.test(sql))).toEqual([]);
      expect(p.query.mock.calls.map(([sql])=>sql)).toContain("ROLLBACK");
    });
  it.each(["hold","commit","canary"] as const)("current unchanged %s cache remains a held factual receipt",async(operation)=>{
    const f=fixture();committedWitnessUnitFixture(f);
    const phase=operation==="hold"?"LEDGER_HELD":operation==="commit"?"LEDGER_COMMITTED_HELD":"CANARY_ADMITTED";
    const receipt={schemaVersion:"execution-fabric-cold-ledger-receipt/v1",operation,recoveryId:f.plan.recoveryId,
      planSha256:digest(f.plan),fabricEpoch:operation==="hold"?4:7,generation:3,held:true,residualQuarantine:true};
    const anchor=operation==="hold"?{...f.anchor,leader:f.plan.sourceHost,publicKeySha256:f.plan.oldPublicKeySha256,highestEpoch:6,
      pending:{...f.anchor.pending,phase:"RESERVED"}}:f.anchor;
    const p=poolFixture(f,{state:{cold_recovery_phase:phase,current_epoch:operation==="hold"?4:7,leader_host_id:operation==="hold"?"genomesbox":"bigmac"},recovery:{phase,receipts:{[operation]:receipt}}});
    expect(await runColdLedgerOperation(p.pool,operation,f.request,f.policy,anchor)).toEqual(receipt);
    expect(p.query.mock.calls.filter(([sql])=>/^\s*(INSERT|UPDATE|DELETE)/.test(sql))).toEqual([]);
  });
  it.each(["leader","epoch","mode","config","pgIdentity","missingReceipt","receiptSchema","receiptPlan","receiptEpoch","receiptGeneration",
    "receiptHeld","receiptSource","receiptTarget","receiptOriginalPath","receiptTargetPath","receiptKey",
    "sentinelSchema","sentinelCluster","sentinelDatabase","sentinelBackup"])(
    "accepted PG cache cannot hide changed selected witness %s",async(seam)=>{
      const f=fixture(),witness=committedWitnessUnitFixture(f),p=acceptedCache(f),before=canonical({receipt:p.receipt,anchor:p.anchor});
      const state=witness.snapshot.state as Record<string,unknown>,receipt=witness.snapshot.coldRecoveries[0] as Record<string,unknown>;
      const fields:Record<string,[Record<string,unknown>,string,unknown]>={
        leader:[state,"currentLeader","genomesbox"],epoch:[state,"fabricEpoch",8],mode:[state,"authorityMode","ha"],
        config:[state,"configDigest","0".repeat(64)],pgIdentity:[state,"upstreamSystemId","98765"],
        receiptSchema:[receipt,"schemaVersion","foreign"],receiptPlan:[receipt,"planSha256","0".repeat(64)],receiptEpoch:[receipt,"fabricEpoch",8],
        receiptGeneration:[receipt,"generation",4],receiptHeld:[receipt,"held",false],receiptSource:[receipt,"previousLeader","foreign"],
        receiptTarget:[receipt,"currentLeader","genomesbox"],receiptOriginalPath:[receipt,"originalDatabasePath","/foreign.sqlite"],
        receiptTargetPath:[receipt,"targetDatabasePath","/foreign.sqlite"],receiptKey:[receipt,"newPublicKeySha256","0".repeat(64)],
        sentinelSchema:[witness.sentinel,"schemaVersion","foreign"],sentinelCluster:[witness.sentinel,"clusterId","foreign"],
        sentinelDatabase:[witness.sentinel,"database","/foreign.sqlite"],sentinelBackup:[witness.sentinel,"backup","/foreign.backup"],
      };
      if(seam==="missingReceipt")witness.snapshot.coldRecoveries=[];
      else {const [object,key,value]=fields[seam]!;object[key]=value;}
      witness.write();
      if(seam==="sentinelSchema"){
        await expect(runColdLedgerOperation(p.pool,"accept",f.request,f.policy,p.anchor)).rejects.toMatchObject({name:"ZodError",
          issues:expect.arrayContaining([expect.objectContaining({code:"invalid_literal",path:["schemaVersion"],
            expected:"execution-fabric-witness-bootstrap/v1",received:"foreign"})])});
      } else await expect(runColdLedgerOperation(p.pool,"accept",f.request,f.policy,p.anchor)).rejects.toThrow(/current selected witness/);
      expect(canonical({receipt:p.receipt,anchor:p.anchor})).toBe(before);
      expect(p.query.mock.calls.filter(([sql])=>/^\s*(INSERT|UPDATE|DELETE)/.test(sql))).toEqual([]);
      expect(p.query.mock.calls.map(([sql])=>sql)).toContain("ROLLBACK");
    });
  it("cryptographic refusal precedes any PostgreSQL connection",async()=>{
    const f=fixture(), p=poolFixture(f);f.request.approval.signature=Buffer.alloc(64).toString("base64");
    await expect(runColdLedgerOperation(p.pool,"hold",f.request,f.policy,f.anchor)).rejects.toThrow(/signature/);
    expect(p.pool.connect).not.toHaveBeenCalled();
  });
  it("missing restore closure or unknown protocol field refuses before connection",async()=>{
    const f=fixture(), p=poolFixture(f);
    await expect(runColdLedgerOperation(p.pool,"accept",{...f.request,restoreInput:undefined},f.policy,f.anchor)).rejects.toThrow();
    await expect(runColdLedgerOperation(p.pool,"accept",{...f.request,command:"override"},f.policy,f.anchor)).rejects.toThrow(/unknown/);
    expect(p.pool.connect).not.toHaveBeenCalled();
  });
  it("a cleared anchor reservation cannot invent durable acceptance history",async()=>{
    const f=fixture(), p=poolFixture(f);
    await expect(runColdLedgerOperation(p.pool,"accept",f.request,f.policy,{...f.anchor,pending:null})).rejects.toThrow(/exact durable acceptance/);
    expect(p.query.mock.calls.filter(([sql])=>/^(INSERT|UPDATE|DELETE)/.test(sql))).toHaveLength(0);
  });
  it("all ordinary admissions and effect claims stop at the durable hold before writes",async()=>{
    const query=vi.fn(async(sql:string)=>({rows:sql.includes("cold_recovery_phase")?[{cold_recovery_phase:"LEDGER_HELD"}]:[],rowCount:0}));
    const pool={connect:async()=>({query,release:()=>{}})} as unknown as pg.Pool;
    const ledger=new PostgresLedger(pool,60);
    await expect(ledger.admitTask({namespace:"isolated",queue:"canary",taskType:"fixture.no-effect",idempotencyKey:"ordinary",payload:{},requiredCapabilities:[],maxAttempts:1,priority:0,schedulingClass:"background"},{} as AdmissionConstraints)).rejects.toThrow(/holds ordinary mutations/);
    await expect(ledger.claimEffects({consumerId:"isolated",source:"isolated-test",effectTypes:["webhook"],limit:1},60)).rejects.toThrow(/holds ordinary mutations/);
    expect(query.mock.calls.filter(([sql])=>/^(INSERT|UPDATE|DELETE)/.test(sql))).toHaveLength(0);
  });
  it("canary hold rejects unapproved worker and any effect-producing completion",async()=>{
    const f=fixture();
    const query=vi.fn(async(sql:string)=>({rows:sql.includes("cold_recovery_phase")?[{cold_recovery_phase:"CANARY_ADMITTED",cold_canary_task_id:f.plan.canary.taskId,cold_canary_worker_id:f.plan.canary.workerId}]:[],rowCount:0}));
    const pool={connect:async()=>({query,release:()=>{}})} as unknown as pg.Pool;
    const ledger=new PostgresLedger(pool,60);
    const registration={bootstrapId:"isolated",workerId:"foreign",hostId:"bigmac",queues:["canary"],capabilities:[],maxConcurrency:1,metadata:{}};
    await expect(ledger.registerWorker(registration,{pool:{provider:"local"}} as WorkerConstraints)).rejects.toThrow(/only the approved/);
    await expect(ledger.registerWorker({...registration,workerId:f.plan.canary.workerId},{pool:{provider:"claude"}} as WorkerConstraints)).rejects.toThrow(/provider-free/);
    await expect(ledger.complete("attempt", {workerId:f.plan.canary.workerId,leaseToken:"lease",fabricEpoch:7,result:{},effects:[{effectKey:"unexpected",effectType:"webhook",payload:{},maxAttempts:1,baseBackoffSeconds:0}]} as Parameters<PostgresLedger["complete"]>[1])).rejects.toThrow(/all effects/);
    expect(query.mock.calls.filter(([sql])=>/^(INSERT|UPDATE|DELETE)/.test(sql))).toHaveLength(0);
  });
  it("invalid authority response revokes a prior gateway cache",async()=>{
    const f=fixture(), now=new Date();
    const body=Buffer.from(JSON.stringify({v:2,cluster:"isolated-fabric",leader:"genomesbox",epoch:4,receiptId:"status:fence",configDigest:"a".repeat(64),issuedAt:new Date(now.getTime()-1000).toISOString(),expiresAt:new Date(now.getTime()+60_000).toISOString()})).toString("base64url");
    const token="v2."+body+"."+sign(null,Buffer.from(body),f.signer.privateKey).toString("base64url");
    let invalid=false;
    const fetcher=vi.fn(async()=>new Response(invalid?"invalid json":JSON.stringify({clusterId:"isolated-fabric",currentLeader:"genomesbox",fabricEpoch:4,leadershipToken:token}),{status:200}));
    const config:GatewayConfig={host:"127.0.0.1",port:3181,clusterId:"isolated-fabric",witnessBaseUrl:"https://isolated.invalid",witnessToken:"fixture",witnessPublicKey:f.policy.recoveryPublicKeyPem,leaderEndpoints:{genomesbox:"http://127.0.0.1:3180"}};
    const resolver=new LeaderResolver(config,fetcher as typeof fetch,()=>now);
    expect((await resolver.resolve()).leader).toBe("genomesbox");
    invalid=true;
    await expect(resolver.resolve()).rejects.toThrow(/invalid authority/);
    expect(resolver.snapshot().state).toBe("fenced");
  });
});

describe.skipIf(process.env.FABRIC_COLD_INTEGRATION_TESTS!=="1")("disposable PostgreSQL cold protocol",()=>{
  it("qualifies real coordinator/store commits, narrow canary, and residual quarantine without provider IO",async()=>{
    const secretFile=process.env.FABRIC_COLD_TEST_DATABASE_URL_FILE;
    if(!secretFile || realpathSync(secretFile)!==secretFile || lstatSync(secretFile).mode & 0o077) throw new Error("private explicit isolated database reference required");
    const databaseUrl=readFileSync(secretFile,"utf8").trim(), url=new URL(databaseUrl);
    if(url.hostname!=="127.0.0.1" || !/^\/fabric_cold_test_[a-z0-9_]+$/.test(url.pathname)) throw new Error("cold test refuses a shared or non-loopback database");
    const pool=createPool(databaseUrl), root=realpathSync(mkdtempSync(join(tmpdir(),"cold-pg-")));
    const worktree=resolve(process.cwd(),"../.."), serviceRoot=join(worktree,"services");
    const witnessScript=join(serviceRoot,"execution-fabric-leadership-witness/dist/src/cold-recovery-main.js");
    const ledgerScript=join(serviceRoot,"execution-fabric-control-plane/dist/src/cold-recovery-main.js");
    const hashFile=(p:string)=>createHash("sha256").update(readFileSync(p)).digest("hex");
    const privateFile=(p:string,value:unknown)=>{writeFileSync(p,typeof value==="string"?value:canonical(value),{mode:0o600});chmodSync(p,0o600);return p;};
    try {
      // Compatibility seam: execute exact shipped legacy installation SQL in
      // this owned empty database, then let the normal migrator perform 017.
      // The inserted legacy quarantine rows below are explicit storage seams.
      const migrationRoot=join(process.cwd(),"migrations");
      const legacyMigrations=readdirSync(migrationRoot).filter(name=>/^\d{3}_[a-z0-9_]+\.sql$/.test(name)&&name.slice(0,3)<="016").sort();
      expect(legacyMigrations).toEqual([
        "001_initial.sql","002_policy_enforcement.sql","003_leadership_fencing.sql",
        "004_reliability_plane.sql","005_artifact_registry.sql","006_task_route_policy.sql",
        "007_scheduler.sql","008_worker_sessions_observability.sql","009_external_reliability_observations.sql",
        "010_external_recovery_semantics.sql","011_config_reload_receipts.sql","012_worker_identity_and_retry_fencing.sql",
        "013_config_reload_rotation_authority.sql","014_role_policy_health.sql","014_standalone_policy_override_receipts.sql",
        "015_attempt_outcomes.sql","016_cold_recovery.sql"]);
      await pool.query("CREATE TABLE fabric_schema_migrations(version text PRIMARY KEY,applied_at timestamptz NOT NULL DEFAULT now())");
      for(const file of legacyMigrations){
        const client=await pool.connect();
        try {
          await client.query("BEGIN");
          await client.query(readFileSync(join(migrationRoot,file),"utf8"));
          await client.query("INSERT INTO fabric_schema_migrations(version) VALUES($1)",[file.slice(0,-4)]);
          await client.query("COMMIT");
        } catch(error){await client.query("ROLLBACK");throw error;}
        finally {client.release();}
      }
      const f=fixture(), nextKey=generateKeyPairSync("ed25519"), oldKey=generateKeyPairSync("ed25519");
      const sourceExecutionBytes=readFileSync(join(worktree,"harness/config/execution-fabric.yml"));
      const sourceExecutionPolicyFile=privateFile(join(root,"source-execution-policy.yml"),sourceExecutionBytes.toString());
      const sourceExecutionPolicy=new PolicyManager(sourceExecutionPolicyFile,join(worktree,"schemas/execution-fabric.schema.json"));
      const sourceFingerprint=sourceExecutionPolicy.snapshot().appliedFingerprint;
      const sourceCanaryQueue=sourceExecutionPolicy.effective().execution_fabric.queues.find(queue=>queue.id==="fabric_cold_recovery");
      const sourceCanaryPool=sourceExecutionPolicy.effective().execution_fabric.worker_pools.find(pool=>pool.id==="fabric_cold_recovery_workers");
      if(!sourceCanaryQueue || !sourceCanaryPool)throw new Error("source disabled canary descriptors missing");
      expect(sourceCanaryQueue.enabled).toBe(false);expect(sourceCanaryPool.enabled).toBe(false);
      expect(()=>sourceExecutionPolicy.queue("fabric_cold_recovery")).toThrow("queue is disabled: fabric_cold_recovery");
      expect(()=>sourceExecutionPolicy.pool("fabric_cold_recovery_workers")).toThrow("worker pool is disabled: fabric_cold_recovery_workers");
      const executionValue=parse(sourceExecutionBytes.toString());
      executionValue.execution_fabric.queues.find((q:{id:string})=>q.id==="fabric_cold_recovery").enabled=true;
      executionValue.execution_fabric.worker_pools.find((p:{id:string})=>p.id==="fabric_cold_recovery_workers").enabled=true;
      const executionPolicyFile=privateFile(join(root,"execution-policy.yml"),stringify(executionValue));
      const executionPolicy=new PolicyManager(executionPolicyFile,join(worktree,"schemas/execution-fabric.schema.json"));
      f.plan.candidateConfigDigest=executionPolicy.snapshot().appliedFingerprint;
      const candidateExecutionBytes=readFileSync(executionPolicyFile);
      f.plan.policyTransition={expectedSourceFingerprint:sourceFingerprint,candidateExecutionPolicyFile:executionPolicyFile,candidateExecutionPolicySha256:hashFile(executionPolicyFile)};
      expect(f.plan.candidateConfigDigest).not.toBe(sourceFingerprint);
      expect(executionPolicy.queue("fabric_cold_recovery").enabled).toBe(true);
      expect(executionPolicy.pool("fabric_cold_recovery_workers").enabled).toBe(true);
      expect(f.request.restoreInput.recoverySetId).toBe("20261009T230000Z-012345abcdef");
      // Dynamically import only the reviewed built sibling store; no alternate service actor.
      const storeModule=await import(pathToFileURL(join(serviceRoot,"execution-fabric-leadership-witness/dist/src/sqlite-store.js")).href);
      const original=join(root,"original.sqlite"), target=join(root,"target.sqlite");
      const originalStore=new storeModule.SqliteWitnessStore(original,f.plan.clusterId,{allowInitialBootstrap:true});
      const state={currentLeader:"genomesbox",fabricEpoch:4,timelineId:1,configDigest:sourceFingerprint,leaderWalPosition:null,leaderBaselineAt:null,upstreamSystemId:null,updatedAt:new Date().toISOString(),fenceDigest:"b".repeat(64),authorityMode:"standalone_primary",degradedUntil:null,degradedIncidentDigest:null};
      await originalStore.initialize(state,{auditId:randomUUID(),eventType:"initialized",actor:"isolated-fixture",occurredAt:state.updatedAt,detail:{}});
      const originalWitnessState=await originalStore.getState();
      expect(originalWitnessState.configDigest).toBe(sourceFingerprint);
      await originalStore.close();
      for(const suffix of ["",".initialized",".backup"]){copyFileSync(original+suffix,target+suffix);chmodSync(target+suffix,0o600);}
      const marker=privateFile(join(root,"host-marker.json"),{clusterId:f.plan.clusterId,host:"genomesbox",isolated:true});
      const rotatedKey=privateFile(join(root,"rotated-key.pem"),nextKey.privateKey.export({type:"pkcs8",format:"pem"}).toString());
      const anchor={schemaVersion:"execution-fabric-recovery-anchor/v1",clusterId:f.plan.clusterId,leader:"genomesbox",generation:2,highestEpoch:6,publicKeySha256:createHash("sha256").update(oldKey.publicKey.export({type:"spki",format:"der"})).digest("hex"),pending:null,lastReceiptSha256:"c".repeat(64)};
      const systemId=String((await pool.query("SELECT system_identifier::text AS id FROM pg_control_system()")).rows[0].id);
      f.policy.witnessActorSha256=hashFile(witnessScript);f.policy.controlPlaneActorSha256=hashFile(ledgerScript);
      const db=new DatabaseSync(target,{readOnly:true});
      const version=Number((db.prepare("SELECT version FROM witness_snapshot WHERE cluster_id=?").get(f.plan.clusterId) as {version:number}).version);db.close();
      const readWitness=(file:string)=>{
        const selected=new DatabaseSync(file,{readOnly:true});
        try {
          const row=selected.prepare("SELECT version,payload FROM witness_snapshot WHERE cluster_id=?").get(f.plan.clusterId) as {version:number;payload:string};
          const value=JSON.parse(row.payload);
          return {version:Number(row.version),state:{currentLeader:value.state.currentLeader,fabricEpoch:value.state.fabricEpoch,
            configDigest:value.state.configDigest,upstreamSystemId:value.state.upstreamSystemId},
            receipt:value.coldRecoveries?.find((receipt:{recoveryId:string})=>receipt.recoveryId===f.plan.recoveryId)??null};
        } finally {selected.close();}
      };
      const originalWitness=readWitness(original),witnessSource={version:originalWitness.version,state:originalWitness.state};
      expect(witnessSource.state.configDigest).toBe(originalWitnessState.configDigest);
      Object.assign(f.plan,{anchorSha256:digest(anchor),policySha256:digest(f.policy),originalDatabasePath:original,originalBackupPath:original+".backup",targetDatabasePath:target,snapshotVersion:version,databaseSha256:hashFile(target),sentinelSha256:hashFile(target+".initialized"),backupSha256:hashFile(target+".backup"),hostMarkerSha256:hashFile(marker),oldPublicKeySha256:anchor.publicKeySha256,newPublicKeySha256:createHash("sha256").update(nextKey.publicKey.export({type:"spki",format:"der"})).digest("hex"),newPgSystemId:systemId});
      Object.assign(f.request.restoreInput.witness,{version,originalDatabasePath:original,originalBackupPath:original+".backup",databaseSha256:f.plan.databaseSha256,sentinelSha256:f.plan.sentinelSha256,backupSha256:f.plan.backupSha256,hostMarkerSha256:f.plan.hostMarkerSha256,signingPublicKeySha256:f.plan.oldPublicKeySha256});
      f.request.restoreInput.postgres.systemId=systemId;f.plan.restoreInputSha256=digest(f.request.restoreInput);
      f.request.approval=f.signed({...f.request.approval.payload as Record<string,unknown>,planSha256:digest(f.plan),policySha256:digest(f.policy),fenceSha256:digest(f.request.fence)});
      const request={...f.request,hostMarkerFile:marker,signingPrivateKeyFile:rotatedKey};
      const policyFile=privateFile(join(root,"policy.json"),f.policy), requestFile=privateFile(join(root,"request.json"),request);
      const anchorFile=privateFile(join(root,"anchor.json"),anchor), journal=join(root,"journal");
      const python=join(worktree,".venv/bin/python");
      const invoke=(action:string,expectedSuccess=true)=>{
        const command="import json,sys; from genomes_agentic_os.cold_recovery import cold_recovery_operation; print(json.dumps(cold_recovery_operation(sys.argv[1],sys.argv[2],policy_file=sys.argv[3],anchor_file=sys.argv[4],journal_dir=sys.argv[5],witness_command=[sys.argv[6],sys.argv[7]],ledger_command=[sys.argv[6],sys.argv[8],'--database-url-file',sys.argv[9]])))";
        const result=spawnSync(python,["-c",command,action,requestFile,policyFile,anchorFile,journal,process.execPath,witnessScript,ledgerScript,secretFile],{env:{...process.env,PYTHONPATH:join(worktree,"src"),ANTHROPIC_API_KEY:"",ANTHROPIC_AUTH_TOKEN:""},encoding:"utf8",timeout:30_000,maxBuffer:1_048_576});
        if(expectedSuccess && result.status!==0)throw new Error("isolated cold coordinator refused "+action+": "+result.stderr.slice(-1800));
        if(!expectedSuccess){expect(result.status).not.toBe(0);return null;}
        return JSON.parse(result.stdout) as {phase:string;receipts:Array<{ref:string}>};
      };
      await pool.query("UPDATE fabric_state SET current_epoch=4,leader_host_id='genomesbox',leader_lease_expires_at=now()+interval '5 minutes' WHERE singleton=true");
      const originalLedger=new PostgresLedger(pool,60);
      expect((await pool.query("SELECT policy_fingerprint FROM fabric_state WHERE singleton=true")).rows[0].policy_fingerprint).toBeNull();
      await originalLedger.activatePolicy(sourceFingerprint);
      const policyState=async()=>{
        const row=(await pool.query("SELECT current_epoch,leader_host_id,policy_fingerprint,cold_recovery_id,cold_recovery_generation,cold_recovery_phase FROM fabric_state WHERE singleton=true")).rows[0];
        return {...row,current_epoch:Number(row.current_epoch),cold_recovery_generation:Number(row.cold_recovery_generation)};
      };
      const postgresBeforeHold=await policyState();expect(postgresBeforeHold.policy_fingerprint).toBe(sourceFingerprint);
      // The original task is produced by the real native admission API. The
      // restored attempt/effect/alarm/artifact rows below remain storage seams;
      // no provider handler, general production ingress or requeue is qualified.
      const originalOwner="isolated-original-owner", originalWork="cold-original-work";
      const ordinary=sourceExecutionPolicy.normalizeAdmission({namespace:"isolated",queue:"codex",taskType:"llm.codex",idempotencyKey:"original-before-hold",payload:{work_item_id:originalWork,instruction_ref:"work-items/cold-original-work/instruction.md"},requiredCapabilities:[],maxAttempts:1});
      const admitted=await originalLedger.admitTask(ordinary,{configFingerprint:sourceFingerprint,queue:sourceExecutionPolicy.queue(ordinary.queue),pool:sourceExecutionPolicy.pool(sourceExecutionPolicy.queue(ordinary.queue).worker_pool)});
      expect(admitted.admitted).toBe(true);
      const siblingAdmission=sourceExecutionPolicy.normalizeAdmission({namespace:"isolated",queue:"codex",taskType:"llm.codex",idempotencyKey:"foreign-sibling-before-hold",payload:{work_item_id:"foreign-sibling-work",instruction_ref:"work-items/foreign-sibling-work/instruction.md"},requiredCapabilities:[],maxAttempts:1});
      const sibling=await originalLedger.admitTask(siblingAdmission,{configFingerprint:sourceFingerprint,queue:sourceExecutionPolicy.queue(siblingAdmission.queue),pool:sourceExecutionPolicy.pool(sourceExecutionPolicy.queue(siblingAdmission.queue).worker_pool)});
      expect(sibling.admitted).toBe(true);
      const foreignSiblingConfigFingerprint=(await pool.query("SELECT config_fingerprint FROM fabric_tasks WHERE id=$1",[sibling.task.id])).rows[0].config_fingerprint;
      expect(foreignSiblingConfigFingerprint).toBe(sourceFingerprint);
      const priorTask=admitted.task.id, effectId=randomUUID(), attemptId=randomUUID(), runId=randomUUID(), leaseToken=randomUUID(), findingId=randomUUID(), alarmId=randomUUID(), artifactId=randomUUID();
      const originalTask=(await pool.query("SELECT row_to_json(t)::jsonb AS item FROM fabric_tasks t WHERE id=$1",[priorTask])).rows[0].item;
      expect(originalTask.config_fingerprint).toBe(sourceFingerprint);
      const authorityFile=join(root,"canonical-original.sqlite"), contextFile=join(root,"original-context.json");
      const authorityProgram=[
        "import hashlib,json,os,shutil,sys",
        "from pathlib import Path",
        "from genomes_agentic_os.state import db,work_items",
        "from genomes_agentic_os.state.control_plane_facts import record_artifact_reference,request_approval,decide_approval",
        "from genomes_agentic_os.development_delivery import resolve_development_policies",
        "v=json.load(sys.stdin); root=Path(v['root']); source=Path(v['source']); authority=Path(v['authority'])",
        "if v['action']=='original':",
        " fixture=root/'context-os'; project=fixture/'domains/isolated/02-projects/disposition_test'; project.mkdir(parents=True)",
        " (project/'project.yml').write_text('sources:\\n  repo: '+str(source)+'\\n')",
        " for rel in ['harness/shared_factory/05-knowledge/auto_dev','harness/investigation-config']:",
        "  if (source/rel).is_dir(): shutil.copytree(source/rel,fixture/rel)",
        " context_source=project/'investigation-config/sources/original-context.md'; context_source.parent.mkdir(parents=True)",
        " with context_source.open('x',encoding='utf-8') as f: f.write('---\\nschema_version: 1\\nid: native-original-context\\nkind: source\\ntitle: Récupération 🧬\\napplies_to:\\n  subjects:\\n    - rubicon-recovery\\n---\\n\\n# Récupération 🧬\\n\\nPreserve original ownership and every provider quarantine.\\n')",
        " context_source.chmod(0o600)",
        " receipt=resolve_development_policies(fixture,'isolated','disposition_test',touched_paths=['services/execution-fabric-control-plane/src/cold-disposition.ts'],subjects=['rubicon-recovery'])",
        " selected=receipt['context_selection']; source_ref=context_source.relative_to(fixture).as_posix()",
        " assert any(d['source_ref']==source_ref for d in selected['selection']['selected_documents'])",
        " assert any(d['id']=='native-original-context' and d['title']=='Récupération 🧬' and any('# Récupération 🧬' in text for text in d.get('instructions_markdown',[])) for d in selected['context_documents'])",
        " context=Path(v['context']); context.write_text(json.dumps(receipt,sort_keys=True,separators=(',',':'))); context.chmod(0o600)",
        " sha=hashlib.sha256(context.read_bytes()).hexdigest(); t=v['task']",
        " binding=dict(schemaVersion='execution-fabric-original-task-binding/v1',taskId=t['id'],contextSha256=receipt['context_selection']['content_sha256'],requestHash=t['request_hash'],developmentPolicyFingerprint=receipt['fingerprint'],contextReceiptUri=context.as_uri(),contextReceiptSha256=sha,configFingerprint=t['config_fingerprint'],namespace=t['namespace'],queue=t['queue_name'],taskType=t['task_type'],provider=t['provider'])",
        " conn=db.connect(authority); authority.chmod(0o600)",
        " work_items.upsert(conn,item_id=v['work'],title='Original isolated admitted task',state='building',attention='active',domain='isolated',project='disposition_test',owner=v['owner'],context_summary='Original isolated admitted task '+t['id']+' with context '+binding['contextSha256'],metadata={'executionFabricBinding':binding},actor=v['owner'],receipt_ref='fabric-task:'+t['id'])",
        " record_artifact_reference(conn,uri=context.as_uri(),content_sha256=sha,classification='internal',retention_days=7,source_ref=v['work'])",
        " print(json.dumps({'contextSha256':binding['contextSha256'],'originalHistory':True,'originalReference':True}))",
        "else:",
        " conn=db.connect(authority)",
        " if v['action']=='terminal':",
        "  row=work_items.get(conn,v['work']); work_items.upsert(conn,item_id=row['id'],title=row['title'],state='finished',attention='closed',domain=row['domain'],project=row['project'],owner=row['owner'],context_summary=row['context_summary'],metadata=row['metadata'],actor=row['owner'],receipt_ref='owner-terminal-cancellation')",
        " elif v['action']=='approval':",
        "  p=v['payload']; request_approval(conn,request_id=p['approvalId'],subject_type='execution_fabric_cold_disposition',subject_id=p['itemId'],requested_by=p['owner'],approver=p['operator'],expires_at=p['expiresAt'],metadata={'requestSha256':v['binding']}); decide_approval(conn,p['approvalId'],approver=p['operator'],decision='approved')",
        " print(json.dumps({'ok':True}))",
        "conn.close()",
      ].join("\n");
      const authorityAction=(action:string,extra:Record<string,unknown>={})=>{
        const result=spawnSync(python,["-c",authorityProgram],{input:JSON.stringify({action,root,source:worktree,authority:authorityFile,context:contextFile,task:originalTask,work:originalWork,owner:originalOwner,...extra}),env:{...process.env,PYTHONPATH:join(worktree,"src")},encoding:"utf8",timeout:30_000,maxBuffer:1_048_576});
        if(result.status!==0)throw new Error("isolated canonical API fixture refused: "+result.stderr.slice(-1800));
        return JSON.parse(result.stdout) as Record<string,unknown>;
      };
      const originalAssociation=authorityAction("original");
      const associationDb=new DatabaseSync(authorityFile,{readOnly:true});
      const originalAssociationProof={schemaVersion:"execution-fabric-isolated-original-association-proof/v1",task:originalTask,
        workItem:associationDb.prepare("SELECT * FROM work_items WHERE id=?").get(originalWork),
        ownerHistory:associationDb.prepare("SELECT * FROM work_item_history WHERE work_item_id=? ORDER BY id").all(originalWork),
        contextReference:associationDb.prepare("SELECT * FROM artifact_references WHERE uri=?").get(pathToFileURL(contextFile).href),
        contextReceiptSha256:hashFile(contextFile),contextSha256:originalAssociation.contextSha256,
        provenance:"actual native admission and Python canonical API producers before the first disposable hold"};
      associationDb.close();
      await pool.query("INSERT INTO fabric_workers(worker_id,bootstrap_id,host_id,pool_id,provider,queues,capabilities,max_concurrency,metadata,registration_token,registered_epoch,config_fingerprint,lease_expires_at) VALUES('old-worker','old-bootstrap','genomesbox','local','local','[]','[]',1,'{}',$1,4,$2,now()+interval '5 minutes')",[randomUUID(),sourceFingerprint]);
      await pool.query("INSERT INTO fabric_runs(id,task_id,run_number,status) VALUES($1,$2,1,'running')",[runId,priorTask]);
      await pool.query("INSERT INTO fabric_attempts(id,task_id,run_id,worker_id,attempt_number,status,lease_token,recovery_token,fabric_epoch,lease_duration_seconds,lease_expires_at) VALUES($1,$2,$3,'old-worker',1,'running',$4,$5,4,60,now()+interval '5 minutes')",[attemptId,priorTask,runId,leaseToken,randomUUID()]);
      await pool.query("INSERT INTO fabric_effect_outbox(id,effect_key,task_id,attempt_id,effect_type,payload,fabric_epoch,max_attempts,base_backoff_seconds) VALUES($1,'old-effect',$2,$3,'provider.never','{}',4,1,1)",[effectId,priorTask,attemptId]);
      await pool.query("INSERT INTO fabric_health_findings(id,fingerprint,kind,scope_type,scope_id,severity,summary,details,fabric_epoch) VALUES($1,$2,'external_observation','external',$3,'warning','isolated','{}',4)",[findingId,"a".repeat(64),priorTask]);
      await pool.query("INSERT INTO fabric_alarm_outbox(id,finding_id,incident_key,revision,fabric_epoch,severity,payload) VALUES($1,$2,'isolated',1,4,'warning','{}')",[alarmId,findingId]);
      await pool.query("INSERT INTO fabric_artifacts(id,task_id,attempt_id,object_key,name,content_type,sha256,size_bytes,upload_expires_at) VALUES($1,$2,$3,'isolated-never','old.json','application/json',$4,1,now()+interval '5 minutes')",[artifactId,priorTask,attemptId,"a".repeat(64)]);
      const legacyRecovery=randomUUID();
      await pool.query("INSERT INTO fabric_cold_recoveries(recovery_id,plan_sha256,generation,expected_epoch,next_epoch,source_host,target_host,phase,plan) VALUES($1,$2,1,1,2,'genomesbox','bigmac','ACCEPTED','{}')",[legacyRecovery,"a".repeat(64)]);
      const legacyRows: Record<string,unknown[]>={};
      for(const [kind,id,originalStatus] of [["task",priorTask,"queued"],["effect",effectId,"pending"],["alarm",alarmId,"pending"],["artifact",artifactId,"uploading"]] as const){
        await pool.query(`INSERT INTO fabric_cold_${kind}_quarantine(recovery_id,${kind}_id,original_status,reason) VALUES($1,$2,$3,'legacy016-held')`,[legacyRecovery,id,originalStatus]);
        legacyRows[kind]=(await pool.query(`SELECT row_to_json(q)::jsonb AS item FROM fabric_cold_${kind}_quarantine q`)).rows.map(row=>row.item);
      }
      await migrate(pool);
      const migrations=await pool.query("SELECT version FROM fabric_schema_migrations ORDER BY version");
      expect(migrations.rows.some((r)=>r.version==="016_cold_recovery")).toBe(true);
      expect(migrations.rows.some((r)=>r.version==="017_cold_quarantine_dispositions")).toBe(true);
      for(const kind of ["task","effect","alarm","artifact"]){
        expect((await pool.query(`SELECT row_to_json(q)::jsonb AS item FROM fabric_cold_${kind}_quarantine_history q`)).rows.map(row=>row.item)).toEqual(legacyRows[kind]);
        expect((await pool.query(`SELECT row_to_json(q)::jsonb AS item FROM fabric_cold_${kind}_quarantine q`)).rows.map(row=>row.item)).toEqual(legacyRows[kind]);
      }
      const firstHold=Date.parse(String((legacyRows.task![0] as Record<string,unknown>).created_at));
      expect(originalAssociationProof.ownerHistory.some(row=>row.actor===originalOwner&&row.receipt_ref==="fabric-task:"+priorTask&&Date.parse(String(row.changed_at))<firstHold)).toBe(true);
      expect(Date.parse(String(originalAssociationProof.contextReference!.created_at))).toBeLessThan(firstHold);
      expect(invoke("prepare")!.phase).toBe("PREPARED");
      expect(invoke("approve")!.phase).toBe("APPROVED");
      // A deliberate owned-file permission refusal leaves the actual native
      // coordinator at LEDGER_HELD. It provides an observable source-A hold
      // boundary without a wrapper or replacement for either fixed actor.
      const originalSentinelBytes=readFileSync(target+".initialized");
      chmodSync(target+".initialized",0o620);
      try {invoke("apply",false);} finally {chmodSync(target+".initialized",0o600);}
      expect(readFileSync(target+".initialized")).toEqual(originalSentinelBytes);
      expect(JSON.parse(readFileSync(join(journal,f.plan.recoveryId+".json"),"utf8")).phase).toBe("LEDGER_HELD");
      const postgresAfterHold=await policyState();
      expect(postgresAfterHold).toMatchObject({current_epoch:4,leader_host_id:"genomesbox",policy_fingerprint:sourceFingerprint,
        cold_recovery_id:f.plan.recoveryId,cold_recovery_generation:3,cold_recovery_phase:"LEDGER_HELD"});
      expect(readWitness(target).state).toEqual(witnessSource.state);
      const heldAnchor=JSON.parse(readFileSync(anchorFile,"utf8"));
      const heldRows=async()=>{
        const values:Record<string,unknown>={};
        for(const kind of ["task","effect","alarm","artifact"]){
          values[kind]=(await pool.query(`SELECT row_to_json(q)::jsonb AS item FROM fabric_cold_${kind}_quarantine_history q ORDER BY recovery_id,${kind}_id`)).rows;
        }
        values.recovery=(await pool.query("SELECT row_to_json(r)::jsonb AS item FROM fabric_cold_recoveries r WHERE recovery_id=$1",[f.plan.recoveryId])).rows;
        return values;
      };
      const heldBefore=await heldRows();
      await pool.query("UPDATE fabric_state SET policy_fingerprint=$1 WHERE singleton=true",["0".repeat(64)]);
      try {await expect(runColdLedgerOperation(pool,"commit",request,f.policy,heldAnchor)).rejects.toThrow(/source policy differs/);}
      finally {await pool.query("UPDATE fabric_state SET policy_fingerprint=$1 WHERE singleton=true",[sourceFingerprint]);}
      expect(await heldRows()).toEqual(heldBefore);expect(await policyState()).toEqual(postgresAfterHold);
      writeFileSync(executionPolicyFile,Buffer.concat([candidateExecutionBytes,Buffer.from("\n# disposable unsigned candidate drift\n")]));
      try {await expect(runColdLedgerOperation(pool,"commit",request,f.policy,heldAnchor)).rejects.toThrow(/signed candidate execution policy bytes differ/);}
      finally {writeFileSync(executionPolicyFile,candidateExecutionBytes);}
      expect(await heldRows()).toEqual(heldBefore);expect(await policyState()).toEqual(postgresAfterHold);
      const witnessBeforeRefusals=[target,target+".initialized",target+".backup"].map(file=>({file,bytes:readFileSync(file)}));
      for(const kind of ["wrong-source","legacy-absent-transition"]){
        const refused=structuredClone(request);
        if(kind==="wrong-source")refused.plan.policyTransition!.expectedSourceFingerprint="0".repeat(64);
        else delete refused.plan.policyTransition;
        refused.approval=f.signed({...refused.approval.payload as Record<string,unknown>,planSha256:digest(refused.plan)});
        const refusalAnchorFile=privateFile(join(root,"witness-refusal-"+kind+"-anchor.json"),{
          ...heldAnchor,pending:{...heldAnchor.pending,planSha256:digest(refused.plan)}});
        const refusal=spawnSync(process.execPath,[witnessScript,"commit",policyFile,refusalAnchorFile],{
          input:canonical(refused),encoding:"utf8",timeout:30_000,maxBuffer:1_048_576});
        expect(refusal.status).not.toBe(0);expect(refusal.stderr).toContain("cold_recovery_refused");
        for(const file of witnessBeforeRefusals)expect(readFileSync(file.file)).toEqual(file.bytes);
        expect(await heldRows()).toEqual(heldBefore);expect(await policyState()).toEqual(postgresAfterHold);
      }
      expect(invoke("resume")!.phase).toBe("ANCHOR_COMMITTED");
      const postgresAfterCommit=await policyState(),witnessTarget=readWitness(target);
      expect(postgresAfterCommit).toMatchObject({current_epoch:7,leader_host_id:"bigmac",policy_fingerprint:f.plan.candidateConfigDigest,
        cold_recovery_id:f.plan.recoveryId,cold_recovery_generation:3,cold_recovery_phase:"LEDGER_COMMITTED_HELD"});
      expect(witnessTarget.state).toEqual({currentLeader:"bigmac",fabricEpoch:7,configDigest:f.plan.candidateConfigDigest,upstreamSystemId:systemId});
      expect(witnessTarget.receipt).toMatchObject({schemaVersion:"execution-fabric-cold-witness-receipt/v1",planSha256:digest(f.plan),held:true,generation:3,fabricEpoch:7});
      expect(readWitness(original)).toEqual(originalWitness);
      expect((await pool.query("SELECT config_fingerprint FROM fabric_tasks WHERE id=$1",[priorTask])).rows[0].config_fingerprint).toBe(sourceFingerprint);
      expect((await pool.query("SELECT config_fingerprint FROM fabric_tasks WHERE id=$1",[sibling.task.id])).rows[0].config_fingerprint).toBe(sourceFingerprint);
      const counts=(await pool.query("SELECT (SELECT count(*)::int FROM fabric_cold_task_quarantine) AS tasks,(SELECT count(*)::int FROM fabric_cold_effect_quarantine) AS effects,(SELECT count(*)::int FROM fabric_cold_alarm_quarantine) AS alarms,(SELECT count(*)::int FROM fabric_cold_artifact_quarantine) AS artifacts")).rows[0];
      expect(counts).toEqual({tasks:2,effects:1,alarms:1,artifacts:1});
      for(const kind of ["task","effect","alarm","artifact"]){
        expect((await pool.query(`SELECT row_to_json(q)::jsonb AS item FROM fabric_cold_${kind}_quarantine_history q WHERE recovery_id=$1`,[legacyRecovery])).rows.map(row=>row.item)).toEqual(legacyRows[kind]);
        expect((await pool.query(`SELECT count(*)::int AS count FROM fabric_cold_${kind}_quarantine_history`)).rows[0].count).toBe(kind==="task"?3:2);
        expect((await pool.query(`SELECT recovery_id FROM fabric_cold_${kind}_quarantine`)).rows).toEqual(Array.from({length:kind==="task"?2:1},()=>({recovery_id:f.plan.recoveryId})));
      }
      const ledger=new PostgresLedger(pool,60), reliability=new PostgresReliabilityStore(pool,"bigmac");
      await expect(ledger.claimEffects({consumerId:"isolated",source:"isolated",effectTypes:["provider.never"],limit:1},60)).rejects.toThrow(/cold recovery/);
      await expect(reliability.claimAlarms("isolated",1,60)).rejects.toThrow(/cold recovery/);
      expect(invoke("canary")!.phase).toBe("CANARY_ADMITTED");
      invoke("accept",false);
      const constraints:WorkerConstraints={configFingerprint:f.plan.candidateConfigDigest,pool:{id:"fabric_cold_recovery_workers",enabled:true,provider:"local",queues:[f.plan.canary.queue],capabilities:["fabric.cold_canary"],capacity:{min_workers:0,max_workers:1,max_tasks_per_worker:1},lease:{timeout_seconds:60,heartbeat_seconds:10},retry:{max_attempts:1,backoff_seconds:0}}};
      const registration=await ledger.registerWorker({bootstrapId:"cold-bootstrap",workerId:f.plan.canary.workerId,hostId:"bigmac",queues:[f.plan.canary.queue],capabilities:["fabric.cold_canary"],maxConcurrency:1,metadata:{coldCanaryHandler:"fabric_cold_canary_v1"}},constraints);
      const assignment=await ledger.claim({workerId:f.plan.canary.workerId,registrationToken:registration.registrationToken,queues:[f.plan.canary.queue],capabilities:["fabric.cold_canary"],waitMs:0},{...constraints,queue:{id:f.plan.canary.queue,enabled:true,worker_pool:"fabric_cold_recovery_workers",accepted_task_types:[f.plan.canary.taskType],priority:0,concurrency:{max_running:1,max_queued:1}},globalMaxRunning:1,providerMaxRunning:1,reservedInteractiveSlots:0,maxInteractiveRunning:1,namespaceLimits:{},hostLimits:{},namespaceWeights:{},priorityAgingIntervalSeconds:60,priorityAgingBoost:1,priorityAgingMaxBoost:1});
      expect(assignment!.task.id).toBe(f.plan.canary.taskId);
      const blockedObject={send:vi.fn()} as unknown as import("@aws-sdk/client-s3").S3Client;
      const objects=new ArtifactStore(pool,{endpoint:"http://127.0.0.1:1",region:"test",bucket:"isolated",accessKeyId:"fixture",secretAccessKey:"fixture",forcePathStyle:true,uploadTtlSeconds:60,downloadTtlSeconds:60,maxBytes:1024},f.plan.clusterId,blockedObject);
      await expect(objects.initiate({taskId:f.plan.canary.taskId,attemptId:assignment!.attemptId,workerId:f.plan.canary.workerId,leaseToken:assignment!.leaseToken,fabricEpoch:7,name:"forbidden",contentType:"text/plain",sha256:"a".repeat(64),sizeBytes:1})).rejects.toThrow(/cold recovery/);
      await expect(ledger.complete(assignment!.attemptId,{workerId:f.plan.canary.workerId,leaseToken:assignment!.leaseToken,fabricEpoch:7,result:{},effects:[{effectKey:"forbidden",effectType:"provider.never",payload:{},maxAttempts:1,baseBackoffSeconds:1}]})).rejects.toThrow(/all effects/);
      const inertRoot=join(root,"inert-worker-root");
      const executed=spawnSync(python,["-c",[
        "import json, sys, yaml", "from pathlib import Path",
        "from genomes_agentic_os.runtime_ops import runtime_init",
        "from genomes_agentic_os.execution_fabric_remote import execute_assignment",
        "root=Path(sys.argv[1]); runtime_init(root)",
        "config=root/'harness/config/execution-fabric.yml'; value=yaml.safe_load(config.read_text())",
        "for queue in value['execution_fabric']['queues']:",
        " if queue['id']=='fabric_cold_recovery': queue['enabled']=True",
        "for pool in value['execution_fabric']['worker_pools']:",
        " if pool['id']=='fabric_cold_recovery_workers': pool['enabled']=True",
        "config.write_text(yaml.safe_dump(value,sort_keys=False))",
        "print(json.dumps(execute_assignment(root,json.loads(sys.stdin.read()))))",
      ].join("\n"),inertRoot],{input:JSON.stringify(assignment),encoding:"utf8",env:{...process.env,PYTHONPATH:join(worktree,"src")},timeout:15_000});
      if(executed.status!==0)throw new Error("fixed inert worker dispatch refused: "+executed.stderr.slice(-1200));
      const outcome=JSON.parse(executed.stdout) as {result:Record<string,unknown>;effects:unknown[];artifacts:unknown[]};
      expect(outcome).toEqual({result:expectedCanaryResult(f.plan),effects:[],artifacts:[]});
      await ledger.complete(assignment!.attemptId,{workerId:f.plan.canary.workerId,leaseToken:assignment!.leaseToken,fabricEpoch:7,result:outcome.result,effects:[]});
      expect(invoke("accept")!.phase).toBe("ACCEPTED");
      const acceptedAnchorBytes=readFileSync(anchorFile),acceptedAnchor=JSON.parse(acceptedAnchorBytes.toString("utf8"));
      const coldJournalFile=join(journal,f.plan.recoveryId+".json"),acceptedColdJournalBytes=readFileSync(coldJournalFile);
      const acceptedPolicyFingerprint=(await policyState()).policy_fingerprint;
      expect(acceptedPolicyFingerprint).toBe(f.plan.candidateConfigDigest);
      const acceptedLedgerReceipt=(await pool.query("SELECT receipts->'accept' AS receipt FROM fabric_cold_recoveries WHERE recovery_id=$1",[f.plan.recoveryId])).rows[0].receipt;
      expect(acceptedLedgerReceipt).toMatchObject({schemaVersion:"execution-fabric-cold-ledger-receipt/v1",operation:"accept",
        recoveryId:f.plan.recoveryId,planSha256:digest(f.plan),fabricEpoch:7,generation:3,held:false,residualQuarantine:true});
      const quarantineRows=async()=>{
        const values: Record<string,unknown>={};
        for(const kind of ["task","effect","alarm","artifact"]){
          values[kind]=(await pool.query(`SELECT row_to_json(q)::jsonb AS item FROM fabric_cold_${kind}_quarantine q ORDER BY recovery_id,${kind}_id`)).rows.map(row=>row.item);
          values[kind+"History"]=(await pool.query(`SELECT row_to_json(q)::jsonb AS item FROM fabric_cold_${kind}_quarantine_history q ORDER BY recovery_id,${kind}_id`)).rows.map(row=>row.item);
        }
        return values;
      };
      const acceptedQuarantineRows=await quarantineRows();
      const sameGenerationLedgerReplay=await runColdLedgerOperation(pool,"accept",request,f.policy,acceptedAnchor);
      expect(sameGenerationLedgerReplay).toEqual(acceptedLedgerReceipt);
      expect(invoke("resume")!.phase).toBe("ACCEPTED");
      expect(readFileSync(anchorFile)).toEqual(acceptedAnchorBytes);
      expect(readFileSync(coldJournalFile)).toEqual(acceptedColdJournalBytes);
      expect((await pool.query("SELECT receipts->'accept' AS receipt FROM fabric_cold_recoveries WHERE recovery_id=$1",[f.plan.recoveryId])).rows[0].receipt).toEqual(acceptedLedgerReceipt);
      expect(await quarantineRows()).toEqual(acceptedQuarantineRows);
      expect(await ledger.claimEffects({consumerId:"isolated",source:"isolated",effectTypes:["provider.never"],limit:1},60)).toEqual([]);
      expect(await reliability.claimAlarms("isolated",1,60)).toEqual([]);
      await expect(reliability.replayEffect(effectId,"isolated","held-replay")).rejects.toThrow(/restored delivery reconciliation/);
      expect((await pool.query("SELECT status FROM fabric_effect_outbox WHERE id=$1",[effectId])).rows[0].status).toBe("pending");
      expect((await pool.query("SELECT status FROM fabric_attempts WHERE id=$1",[attemptId])).rows[0].status).toBe("fenced");
      expect((await pool.query("SELECT count(*)::int AS count FROM fabric_artifacts WHERE task_id=$1",[f.plan.canary.taskId])).rows[0].count).toBe(0);
      const restoredUpload={taskId:priorTask,attemptId,workerId:"old-worker",leaseToken,fabricEpoch:7,name:"held",contentType:"text/plain",sha256:"a".repeat(64),sizeBytes:1};
      // Exact existing disposable restored-storage credentials. The old
      // session is fenced; these do not qualify positive recovery eligibility.
      const restoredTokens=(await pool.query("SELECT a.task_id,a.worker_id,a.recovery_token,w.registration_token FROM fabric_attempts a JOIN fabric_workers w ON w.worker_id=a.worker_id WHERE a.id=$1",[attemptId])).rows[0];
      expect(restoredTokens.task_id).toBe(priorTask);expect(restoredTokens.worker_id).toBe("old-worker");
      const restoredRecovery=artifactRecoveryFinalizeSchema.parse({taskId:priorTask,attemptId,workerId:restoredTokens.worker_id,fabricEpoch:7,
        registrationToken:restoredTokens.registration_token,attemptRecoveryToken:restoredTokens.recovery_token});
      const restoredRecoveryUpload=artifactRecoveryUploadSchema.parse({...restoredRecovery,name:"held",contentType:"text/plain",sha256:"a".repeat(64),sizeBytes:1});
      await expect(objects.initiate(restoredUpload)).rejects.toThrow(/restored artifact reconciliation/);
      await expect(objects.initiateRecovery(restoredRecoveryUpload)).rejects.toThrow(/restored artifact reconciliation/);
      await expect(objects.finalize(artifactId,restoredUpload)).rejects.toThrow(/restored artifact reconciliation/);
      await expect(objects.finalizeRecovery(artifactId,restoredRecovery)).rejects.toThrow(/restored artifact reconciliation/);
      const restoredAttempt=(await pool.query("SELECT status,fabric_epoch,lease_expires_at FROM fabric_attempts WHERE id=$1",[attemptId])).rows[0];
      // Disposable restored storage seam: a superficially current lease must
      // still be excluded by quarantine before ordinary completion/recovery.
      await pool.query("UPDATE fabric_attempts SET status='running',fabric_epoch=7,lease_expires_at=now()+interval '5 minutes' WHERE id=$1",[attemptId]);
      await expect(ledger.complete(attemptId,{workerId:"old-worker",leaseToken,fabricEpoch:7,result:{},effects:[]})).rejects.toThrow(/attempt not found/);
      await pool.query("UPDATE fabric_attempts SET lease_expires_at=now()-interval '1 minute' WHERE id=$1",[attemptId]);
      expect(await ledger.reconcileExpired()).toEqual({expiredRequeued:0,expiredDeadLettered:0,effectsRequeued:0,effectsDeadLettered:0});
      expect((await pool.query("SELECT status FROM fabric_attempts WHERE id=$1",[attemptId])).rows[0].status).toBe("running");
      await pool.query("UPDATE fabric_attempts SET status=$2,fabric_epoch=$3,lease_expires_at=$4 WHERE id=$1",[attemptId,restoredAttempt.status,restoredAttempt.fabric_epoch,restoredAttempt.lease_expires_at]);
      expect((await pool.query("SELECT status,fabric_epoch,lease_expires_at FROM fabric_attempts WHERE id=$1",[attemptId])).rows[0]).toEqual(restoredAttempt);
      expect(blockedObject.send).not.toHaveBeenCalled();
      authorityAction("terminal");
      const dispositionPolicy={...f.policy,selectiveDisposition:{enabled:true,acceptedPolicySha256:digest(f.policy),sourceRelease:"0.10.1",
        authority:{backend:"sqlite",databasePath:authorityFile,domain:"isolated",project:"disposition_test"},
        executionPolicyFile,allowedLocalTaskTypes:["fabric.cold_canary"],heldProviders:["claude","codex"]}};
      const inspectPayload={schemaVersion:"execution-fabric-cold-disposition-inspection/v1",recoveryId:f.plan.recoveryId,generation:3,fabricEpoch:7,
        clusterId:f.plan.clusterId,targetHost:"bigmac",itemKind:"task",itemId:priorTask,workItemId:originalWork,owner:originalOwner,
        operator:"isolated-named-operator",contextSha256:String(originalAssociation.contextSha256),policySha256:digest(dispositionPolicy),
        issuedAt:new Date(Date.now()-1000).toISOString(),expiresAt:new Date(Date.now()+180_000).toISOString()};
      const inspect=(selector=inspectPayload)=>inspectColdDisposition(pool,f.signed(selector),dispositionPolicy,acceptedAnchor);
      const snapshot=await inspect();
      expect(snapshot).toMatchObject({routeQualified:false,requeueAvailable:false,providerOutcomeVerifier:"unavailable",mutationCount:0,ownerBlocked:false,
        owner:originalOwner,decisionHistory:[],dependencyCounts:{attempts:1,runs:1,effects:1,artifacts:1,alarms:1}});
      const beforeDisposition=(await pool.query("SELECT count(*)::int AS count FROM fabric_cold_dispositions")).rows[0].count;
      const siblingRows=async()=>({
        task:(await pool.query("SELECT row_to_json(t)::jsonb AS item FROM fabric_tasks t WHERE id=$1",[sibling.task.id])).rows[0].item,
        history:(await pool.query("SELECT row_to_json(q)::jsonb AS item FROM fabric_cold_task_quarantine_history q WHERE task_id=$1 ORDER BY recovery_id",[sibling.task.id])).rows.map(row=>row.item),
        held:(await pool.query("SELECT row_to_json(q)::jsonb AS item FROM fabric_cold_task_quarantine q WHERE task_id=$1",[sibling.task.id])).rows.map(row=>row.item),
      });
      const siblingBefore=await siblingRows();
      expect(siblingBefore.history).toHaveLength(1);expect(siblingBefore.held).toHaveLength(1);
      const payloadKeys=["recoveryId","generation","fabricEpoch","clusterId","targetHost","pgSystemId","planSha256","acceptedReceiptSha256",
        "acceptedPolicySha256","policySha256","configFingerprint","executionPolicySha256","sourceRelease","itemKind","itemId","itemSha256",
        "historySha256","dependencySha256","workItemId","workItemSha256","owner","operator","contextSha256","priorDispositionSha256"];
      const prepareDecision=async(disposition:DispositionPayload["disposition"]="task_cancel",duration=30_000,selector=inspectPayload,overrides:Partial<DispositionPayload>={})=>{
        const current=await inspect(selector);
        const payload={schemaVersion:"execution-fabric-cold-disposition/v1",...Object.fromEntries(payloadKeys.map(k=>[k,current[k]])),
          approvalId:"approval-"+randomUUID(),approvalSha256:"0".repeat(64),disposition,
          reason:disposition==="hold"?"outcome_unknown":"owner_cancelled",idempotencyKey:"decision-"+randomUUID(),
          issuedAt:new Date(Date.now()-1000).toISOString(),expiresAt:new Date(Date.now()+duration).toISOString(),...overrides} as DispositionPayload;
        authorityAction("approval",{payload,binding:dispositionApprovalBinding(payload)});
        const actual=new DatabaseSync(authorityFile,{readOnly:true});
        payload.approvalSha256=digest(actual.prepare("SELECT * FROM approval_requests WHERE id=?").get(payload.approvalId));
        actual.close();
        return {payload,signature:sign(null,Buffer.from(canonical(payload)),f.signer.privateKey).toString("base64")};
      };
      const signedDecision=await prepareDecision("task_cancel",5000);
      const publicationBefore=(await pool.query("SELECT delivery_published_at,attempt_count FROM fabric_tasks WHERE id=$1",[priorTask])).rows[0];
      await ledger.markPublished(priorTask);
      expect((await pool.query("SELECT delivery_published_at,attempt_count FROM fabric_tasks WHERE id=$1",[priorTask])).rows[0]).toEqual(publicationBefore);
      const fenceChecks: boolean[]=[];
      const fencedPool={connect:async()=>{
        const client=await pool.connect();
        return {query:async(sql:string,params?:unknown[])=>{
          if(sql==="COMMIT"){
            const uri=pathToFileURL(authorityFile);uri.searchParams.set("mode","rw");
            const contender=new DatabaseSync(uri.href,{readOnly:false});
            try {contender.exec("PRAGMA busy_timeout=0");expect(()=>contender.exec("BEGIN IMMEDIATE")).toThrow(/locked/);fenceChecks.push(true);}
            finally {contender.close();}
          }
          return client.query(sql,params);
        },release:()=>client.release()};
      }} as unknown as pg.Pool;
      const cancelled=await runColdDisposition(fencedPool,signedDecision,dispositionPolicy,acceptedAnchor);
      expect(cancelled).toMatchObject({replayed:false,held:true,inspected:false,receipt:{disposition:"task_cancel",released:false,itemId:priorTask}});
      expect(cancelled.receipt.requestSha256).toBe(digest(signedDecision.payload));
      expect(fenceChecks).toEqual([true]);
      const cancellationEvent=(await pool.query("SELECT data FROM fabric_events WHERE event_id=$1",[cancelled.receipt.eventId])).rows[0].data;
      expect(cancellationEvent).toEqual(cancelled.receipt);
      const afterInspection=await inspect();
      expect(afterInspection.decisionHistory).toEqual([{sequence:1,recoveryId:f.plan.recoveryId,generation:3,fabricEpoch:7,
        disposition:"task_cancel",receiptSha256:digest(cancelled.receipt),predecessorSha256:null,eventId:cancelled.receipt.eventId}]);
      expect(afterInspection.dependencySha256).toBe(snapshot.dependencySha256);
      expect(afterInspection.historySha256).toBe(snapshot.historySha256);
      expect((await pool.query("SELECT status,attempt_count,delivery_published_at FROM fabric_tasks WHERE id=$1",[priorTask])).rows[0])
        .toEqual({status:"cancelled",attempt_count:publicationBefore.attempt_count,delivery_published_at:publicationBefore.delivery_published_at});
      const allHolds=()=>pool.query("SELECT (SELECT count(*)::int FROM fabric_cold_task_quarantine) AS tasks,(SELECT count(*)::int FROM fabric_cold_effect_quarantine) AS effects,(SELECT count(*)::int FROM fabric_cold_alarm_quarantine) AS alarms,(SELECT count(*)::int FROM fabric_cold_artifact_quarantine) AS artifacts");
      expect((await allHolds()).rows[0]).toEqual(counts);
      expect(await siblingRows()).toEqual(siblingBefore);
      // Exact committed replay is factual readback after authorization expiry,
      // rather than a fresh decision or an opportunity to release any hold.
      await new Promise(resolve=>setTimeout(resolve,Math.max(0,Date.parse(signedDecision.payload.expiresAt)-Date.now()+20)));
      const replayed=await runColdDisposition(pool,signedDecision,dispositionPolicy,acceptedAnchor);
      expect(replayed).toEqual({...cancelled,replayed:true});
      await expect(inspectColdDisposition(pool,f.signed({...inspectPayload,expiresAt:signedDecision.payload.expiresAt}),dispositionPolicy,acceptedAnchor))
        .rejects.toThrow(/window/);
      expect((await pool.query("SELECT count(*)::int AS count FROM fabric_cold_dispositions")).rows[0].count).toBe(beforeDisposition+1);
      const completedAt=(await pool.query("SELECT completed_at FROM fabric_tasks WHERE id=$1",[priorTask])).rows[0].completed_at;
      const reaffirmationRequest=await prepareDecision("task_cancel");
      const reaffirmed=await runColdDisposition(pool,reaffirmationRequest,dispositionPolicy,acceptedAnchor);
      expect(reaffirmed.receipt.predecessorSha256).toBe(digest(cancelled.receipt));
      expect(reaffirmed.receipt.requestSha256).toBe(digest(reaffirmationRequest.payload));
      expect((await pool.query("SELECT completed_at FROM fabric_tasks WHERE id=$1",[priorTask])).rows[0].completed_at).toEqual(completedAt);
      const reaffirmationEvent=(await pool.query("SELECT data FROM fabric_events WHERE event_id=$1",[reaffirmed.receipt.eventId])).rows[0].data;
      expect(reaffirmationEvent).toEqual(reaffirmed.receipt);
      const latestTaskInspection=await inspect();
      expect(latestTaskInspection.decisionHistory).toEqual([...(afterInspection.decisionHistory as unknown[]),
        {sequence:2,recoveryId:f.plan.recoveryId,generation:3,fabricEpoch:7,disposition:"task_cancel",
          receiptSha256:digest(reaffirmed.receipt),predecessorSha256:digest(cancelled.receipt),eventId:reaffirmed.receipt.eventId}]);
      await expect(runColdDisposition(pool,signedDecision,dispositionPolicy,acceptedAnchor)).rejects.toThrow(/current readback differs/);
      const fresh=await prepareDecision("hold");
      await expect(runColdDisposition(pool,f.signed({...fresh.payload,owner:"foreign-owner"}),dispositionPolicy,acceptedAnchor))
        .rejects.toThrow(/canonical owner or exact approval/);
      await expect(runColdDisposition(pool,f.signed({...fresh.payload,disposition:"task_requeue"}),dispositionPolicy,acceptedAnchor))
        .rejects.toThrow(/positive requeue/);
      for(const field of ["itemSha256","historySha256","dependencySha256"] as const){
        const stale=await prepareDecision("hold",30_000,inspectPayload,{[field]:"0".repeat(64)});
        await expect(runColdDisposition(pool,stale,dispositionPolicy,acceptedAnchor)).rejects.toThrow(/item or dependency bytes changed/);
      }
      const stalePredecessor=await prepareDecision("hold",30_000,inspectPayload,{priorDispositionSha256:null});
      await expect(runColdDisposition(pool,stalePredecessor,dispositionPolicy,acceptedAnchor)).rejects.toThrow(/predecessor conflicts/);
      const sameKey=await prepareDecision("hold",30_000,inspectPayload,{idempotencyKey:signedDecision.payload.idempotencyKey});
      await expect(runColdDisposition(pool,sameKey,dispositionPolicy,acceptedAnchor)).rejects.toThrow(/idempotency conflicts/);
      // Negative storage corruption seams touch only this private disposable
      // authority. Every original row is restored and independently compared.
      type SqliteRow=Record<string,string|number|null>;
      const readAuthority=(table:string,id:string|number):SqliteRow=>{
        const db=new DatabaseSync(authorityFile,{readOnly:true});
        try {return db.prepare(`SELECT * FROM ${table} WHERE id=?`).get(id) as SqliteRow;}
        finally {db.close();}
      };
      const withAuthorityChange=async(table:"work_items"|"approval_requests"|"work_item_history"|"artifact_references",id:string|number,delta:SqliteRow|null,check:()=>Promise<void>)=>{
        const before=readAuthority(table,id),keys=Object.keys(before);
        const uri=pathToFileURL(authorityFile);uri.searchParams.set("mode","rw");
        const change=(restore=false)=>{
          const db=new DatabaseSync(uri.href,{readOnly:false});
          try {
            if(restore){
              if(delta===null)db.prepare(`INSERT INTO ${table}(${keys.join(",")}) VALUES(${keys.map(()=>"?").join(",")})`).run(...keys.map(k=>before[k]!));
              else {const fields=Object.keys(delta);db.prepare(`UPDATE ${table} SET ${fields.map(k=>k+"=?").join(",")} WHERE id=?`).run(...fields.map(k=>before[k]!),id);}
            } else if(delta===null)db.prepare(`DELETE FROM ${table} WHERE id=?`).run(id);
            else {const fields=Object.keys(delta);db.prepare(`UPDATE ${table} SET ${fields.map(k=>k+"=?").join(",")} WHERE id=?`).run(...fields.map(k=>delta[k]!),id);}
          } finally {db.close();}
        };
        change();
        try {await check();}
        finally {change(true);expect(readAuthority(table,id)).toEqual(before);}
      };
      await withAuthorityChange("work_items",originalWork,{blocked_reason:"explicit fixture blocker"},async()=>{
        const blocked=await prepareDecision("hold");
        await expect(runColdDisposition(pool,blocked,dispositionPolicy,acceptedAnchor)).rejects.toThrow(/canonical owner or exact approval/);
      });
      const approvalDeltas:SqliteRow[]=[{approver:"foreign-operator"},{status:"waiting"},{expires_at:new Date(Date.now()-1000).toISOString()},
        {decided_at:new Date(Date.now()+60_000).toISOString()}];
      for(const delta of approvalDeltas){
        const request=await prepareDecision("hold");
        await withAuthorityChange("approval_requests",request.payload.approvalId,delta,async()=>{
          request.payload.approvalSha256=digest(readAuthority("approval_requests",request.payload.approvalId));
          await expect(runColdDisposition(pool,f.signed(request.payload),dispositionPolicy,acceptedAnchor)).rejects.toThrow(/approval/);
        });
      }
      const originalDb=new DatabaseSync(authorityFile,{readOnly:true});
      const originalHistory=originalDb.prepare("SELECT id FROM work_item_history WHERE work_item_id=? AND receipt_ref=?").get(originalWork,"fabric-task:"+priorTask) as {id:number};
      const originalReference=originalDb.prepare("SELECT id FROM artifact_references WHERE uri=?").get(pathToFileURL(contextFile).href) as {id:string};
      originalDb.close();
      const historyDeltas:(SqliteRow|null)[]=[null,{changed_at:new Date(Date.now()+60_000).toISOString()},{actor:"foreign-owner"}];
      for(const delta of historyDeltas){
        await withAuthorityChange("work_item_history",originalHistory.id,delta,async()=>{
          await expect(runColdDisposition(pool,fresh,dispositionPolicy,acceptedAnchor)).rejects.toThrow(/pre-recovery owner association history/);
        });
      }
      const referenceDeltas:(SqliteRow|null)[]=[null,{created_at:new Date(Date.now()+60_000).toISOString()},{source_ref:"foreign-work"},{classification:"public"}];
      for(const delta of referenceDeltas){
        await withAuthorityChange("artifact_references",originalReference.id,delta,async()=>{
          await expect(runColdDisposition(pool,fresh,dispositionPolicy,acceptedAnchor)).rejects.toThrow(/registered original context reference/);
        });
      }
      const missingContext=Buffer.from(readFileSync(contextFile));
      writeFileSync(contextFile,"{}",{mode:0o600});
      await expect(runColdDisposition(pool,fresh,dispositionPolicy,acceptedAnchor)).rejects.toThrow(/context receipt changed/);
      writeFileSync(contextFile,missingContext,{mode:0o600});
      const originalExecution=readFileSync(executionPolicyFile);
      writeFileSync(executionPolicyFile,Buffer.concat([originalExecution,Buffer.from("\n# disposable changed bytes\n")]),{mode:0o600});
      await expect(runColdDisposition(pool,fresh,dispositionPolicy,acceptedAnchor)).rejects.toThrow(/execution policy loaded bytes differ/);
      writeFileSync(executionPolicyFile,originalExecution,{mode:0o600});
      const privacyRequest=await prepareDecision("hold"),authorityIdentity=lstatSync(authorityFile),privacySql:string[]=[];
      const privacyRows=async()=>({
        item:(await pool.query("SELECT row_to_json(t)::jsonb AS item FROM fabric_tasks t WHERE id=$1",[priorTask])).rows[0].item,
        dispositions:(await pool.query("SELECT row_to_json(d)::jsonb AS item FROM fabric_cold_dispositions d ORDER BY sequence")).rows.map(row=>row.item),
        events:(await pool.query("SELECT row_to_json(e)::jsonb AS item FROM fabric_events e WHERE aggregate_type='cold_disposition' ORDER BY sequence")).rows.map(row=>row.item),
        quarantine:await quarantineRows(),workItem:readAuthority("work_items",originalWork),
        approval:readAuthority("approval_requests",privacyRequest.payload.approvalId),
      });
      const privacyBefore=await privacyRows();let permissionDrift=false;
      const permissionDriftPool={connect:async()=>{
        const client=await pool.connect();
        return {query:async(sql:string,params?:unknown[])=>{
          privacySql.push(sql);
          if(!permissionDrift&&sql.startsWith("SELECT * FROM fabric_state")){
            const waiting=client.query(sql,params);
            chmodSync(authorityFile,0o644);permissionDrift=true;
            expect(lstatSync(authorityFile).ino).toBe(authorityIdentity.ino);
            expect(lstatSync(authorityFile).dev).toBe(authorityIdentity.dev);
            expect(lstatSync(authorityFile).mode&0o777).toBe(0o644);
            return await waiting;
          }
          return client.query(sql,params);
        },release:()=>client.release()};
      }} as unknown as pg.Pool;
      try {
        await expect(runColdDisposition(permissionDriftPool,privacyRequest,dispositionPolicy,acceptedAnchor)).rejects.toThrow(/privacy changed/);
        expect(permissionDrift).toBe(true);
        expect(privacySql).toContain("ROLLBACK");expect(privacySql).not.toContain("COMMIT");
        expect(privacySql.filter(sql=>/^\s*(INSERT|UPDATE|DELETE)/.test(sql))).toEqual([]);
        expect(await privacyRows()).toEqual(privacyBefore);
        expect(readFileSync(anchorFile)).toEqual(acceptedAnchorBytes);
        expect(readFileSync(coldJournalFile)).toEqual(acceptedColdJournalBytes);
      } finally {chmodSync(authorityFile,0o600);}
      expect(lstatSync(authorityFile).mode&0o777).toBe(0o600);
      const effectSelector={...inspectPayload,itemKind:"effect",itemId:effectId};
      const effectBefore=await inspect(effectSelector),effectRequest=await prepareDecision("hold",30_000,effectSelector);
      const effectHeld=await runColdDisposition(pool,effectRequest,dispositionPolicy,acceptedAnchor);
      expect(effectHeld).toMatchObject({replayed:false,held:true,receipt:{disposition:"hold",released:false,itemKind:"effect",itemId:effectId}});
      expect(effectHeld.receipt.requestSha256).toBe(digest(effectRequest.payload));
      const effectAfter=await inspect(effectSelector);
      expect(effectAfter.itemSha256).toBe(effectBefore.itemSha256);
      expect(effectAfter.historySha256).toBe(effectBefore.historySha256);
      expect(effectAfter.dependencySha256).toBe(effectBefore.dependencySha256);
      expect(effectAfter.decisionHistory).toEqual([{sequence:3,recoveryId:f.plan.recoveryId,generation:3,fabricEpoch:7,
        disposition:"hold",receiptSha256:digest(effectHeld.receipt),predecessorSha256:null,eventId:effectHeld.receipt.eventId}]);
      const effectEvent=(await pool.query("SELECT data FROM fabric_events WHERE event_id=$1",[effectHeld.receipt.eventId])).rows[0].data;
      expect(effectEvent).toEqual(effectHeld.receipt);
      expect(await runColdDisposition(pool,effectRequest,dispositionPolicy,acceptedAnchor)).toEqual({...effectHeld,replayed:true});
      expect((await allHolds()).rows[0]).toEqual(counts);
      const originalEffect=(await pool.query("SELECT last_error FROM fabric_effect_outbox WHERE id=$1",[effectId])).rows[0].last_error;
      // Deliberate corruption of a disposable restored storage seam; this is
      // refusal evidence, never supported producer/provider qualification.
      await pool.query("UPDATE fabric_effect_outbox SET last_error='changed-after-decision' WHERE id=$1",[effectId]);
      await expect(runColdDisposition(pool,reaffirmationRequest,dispositionPolicy,acceptedAnchor)).rejects.toThrow(/current readback differs/);
      await pool.query("UPDATE fabric_effect_outbox SET last_error=$2 WHERE id=$1",[effectId,originalEffect]);
      await pool.query("UPDATE fabric_events SET data='{}'::jsonb WHERE event_id=$1",[effectHeld.receipt.eventId]);
      await expect(inspect(effectSelector)).rejects.toThrow(/immutable disposition history proof/);
      await expect(runColdDisposition(pool,effectRequest,dispositionPolicy,acceptedAnchor)).rejects.toThrow(/committed disposition event unavailable/);
      await pool.query("UPDATE fabric_events SET data=$2::jsonb WHERE event_id=$1",[effectHeld.receipt.eventId,JSON.stringify(effectEvent)]);
      expect((await pool.query("SELECT data FROM fabric_events WHERE event_id=$1",[effectHeld.receipt.eventId])).rows[0].data).toEqual(effectEvent);
      for(const table of ["fabric_cold_task_quarantine_history","fabric_cold_effect_quarantine_history","fabric_cold_alarm_quarantine_history","fabric_cold_artifact_quarantine_history","fabric_cold_dispositions"]){
        await expect(pool.query("DELETE FROM "+table)).rejects.toThrow(/immutable/);
      }
      await expect(reliability.requeueTask(priorTask,"isolated-operator","guarded-requeue")).rejects.toThrow(/restored delivery reconciliation/);
      await expect(reliability.cancelTask(priorTask,"isolated-operator","guarded-cancel")).rejects.toThrow(/restored delivery reconciliation/);
      await expect(reliability.drainQueue(ordinary.queue,"isolated-operator","guarded-drain")).rejects.toThrow(/quarantine/);
      await expect(reliability.replayEffect(effectId,"isolated-operator","guarded-replay")).rejects.toThrow(/restored delivery reconciliation/);
      await expect(ledger.deliverEffect(effectId,{consumerId:"isolated",claimToken:randomUUID(),fabricEpoch:7,providerReceipt:{}})).rejects.toThrow(/fenced/);
      await expect(ledger.failEffect(effectId,{consumerId:"isolated",claimToken:randomUUID(),fabricEpoch:7,retryAfterSeconds:1,errorSummary:"fixture"})).rejects.toThrow(/fenced/);
      await expect(reliability.deliverAlarm(alarmId,"isolated",randomUUID(),7,{})).rejects.toThrow(/stale/);
      await expect(reliability.failAlarm(alarmId,"isolated",randomUUID(),7,"fixture")).rejects.toThrow(/stale/);
      expect(await ledger.claimEffects({consumerId:"isolated",source:"isolated",effectTypes:["provider.never"],limit:1},60)).toEqual([]);
      expect(await reliability.claimAlarms("isolated",1,60)).toEqual([]);
      expect((await allHolds()).rows[0]).toEqual(counts);
      expect(await siblingRows()).toEqual(siblingBefore);
      const immutableHistory=(await pool.query("SELECT item_kind,item_id,receipt_sha256,receipt FROM fabric_cold_dispositions ORDER BY sequence")).rows;
      expect(immutableHistory).toHaveLength(3);
      await pool.query("UPDATE fabric_state SET current_epoch=8,cold_recovery_generation=4 WHERE singleton=true");
      await expect(runColdLedgerOperation(pool,"accept",request,f.policy,acceptedAnchor)).rejects.toThrow(/current|authority|generation/);
      expect((await pool.query("SELECT receipts->'accept' AS receipt FROM fabric_cold_recoveries WHERE recovery_id=$1",[f.plan.recoveryId])).rows[0].receipt).toEqual(acceptedLedgerReceipt);
      expect(readFileSync(anchorFile)).toEqual(acceptedAnchorBytes);
      expect(readFileSync(coldJournalFile)).toEqual(acceptedColdJournalBytes);
      expect(await quarantineRows()).toEqual(acceptedQuarantineRows);
      await expect(runColdDisposition(pool,signedDecision,dispositionPolicy,acceptedAnchor)).rejects.toThrow(/current authority differs/);
      await expect(runColdDisposition(pool,reaffirmationRequest,dispositionPolicy,acceptedAnchor)).rejects.toThrow(/current authority differs/);
      await expect(runColdDisposition(pool,effectRequest,dispositionPolicy,acceptedAnchor)).rejects.toThrow(/current authority differs/);
      expect((await allHolds()).rows[0]).toEqual(counts);
      expect(await siblingRows()).toEqual(siblingBefore);
      expect((await pool.query("SELECT item_kind,item_id,receipt_sha256,receipt FROM fabric_cold_dispositions ORDER BY sequence")).rows).toEqual(immutableHistory);
      const receiptFile=process.env.FABRIC_COLD_TEST_RECEIPT_FILE;
      if(receiptFile){
        sourceExecutionPolicy.assertOperational();executionPolicy.assertOperational();
        expect(readFileSync(sourceExecutionPolicyFile)).toEqual(sourceExecutionBytes);
        expect(readFileSync(executionPolicyFile)).toEqual(candidateExecutionBytes);
        const transitionProof={schemaVersion:"execution-fabric-isolated-policy-transition-proof/v1",plan:f.plan,
          source:{file:"SOURCE-EXECUTION-POLICY.yml",rawSha256:hashFile(sourceExecutionPolicyFile),appliedFingerprint:sourceFingerprint,
            effectivePolicy:sourceExecutionPolicy.effective(),state:sourceExecutionPolicy.snapshot().state,canaryEnabled:sourceCanaryQueue.enabled},
          candidate:{file:"CANDIDATE-EXECUTION-POLICY.yml",rawSha256:hashFile(executionPolicyFile),appliedFingerprint:f.plan.candidateConfigDigest,
            effectivePolicy:executionPolicy.effective(),state:executionPolicy.snapshot().state,canaryEnabled:executionPolicy.queue("fabric_cold_recovery").enabled},
          postgresBeforeHold,postgresAfterHold,postgresAfterCommit,witnessSource,witnessTarget,
          originalTaskConfigFingerprint:originalTask.config_fingerprint,foreignSiblingConfigFingerprint,acceptedPolicyFingerprint,
          scope:"native disposable supported A initial activation and signed A-to-B cold transition; not a live or installed host transition"};
        for(const [name,bytes] of [["ACCEPTED-COLD-JOURNAL.json",acceptedColdJournalBytes],["ACCEPTED-ANCHOR.json",acceptedAnchorBytes],
          ["SOURCE-EXECUTION-POLICY.yml",sourceExecutionBytes],["CANDIDATE-EXECUTION-POLICY.yml",candidateExecutionBytes],
          ["POLICY-TRANSITION-PROOF.json",Buffer.from(canonical(transitionProof))]] as const){
          const output=join(dirname(receiptFile),name);
          writeFileSync(output,bytes,{mode:0o600,flag:"wx"});
          const identity=lstatSync(output);expect(identity.isFile()).toBe(true);expect(identity.mode&0o077).toBe(0);
          expect(readFileSync(output)).toEqual(bytes);
        }
        const associationEvidence=privateFile(join(dirname(receiptFile),"ORIGINAL-ASSOCIATION.json"),originalAssociationProof);
        const contextEvidence=join(dirname(receiptFile),"ORIGINAL-CONTEXT.json");copyFileSync(contextFile,contextEvidence);chmodSync(contextEvidence,0o600);
        expect(hashFile(contextEvidence)).toBe(originalAssociationProof.contextReceiptSha256);
        privateFile(receiptFile,{schemaVersion:"execution-fabric-isolated-cold-qualification/v1",databaseName:url.pathname.slice(1),migrationVersions:migrations.rows.map((r)=>r.version),recoveryId:f.plan.recoveryId,recoverySetId:f.request.restoreInput.recoverySetId,epoch:7,generation:3,canaryTaskId:f.plan.canary.taskId,quarantine:counts,providerOrObjectCalls:0,canaryHandler:"fabric_cold_canary_v1",canaryExecutor:"execute_assignment",canaryResultVerified:true,accepted:true,
        metadataDisposition:{schemaVersion:"execution-fabric-isolated-metadata-disposition-qualification/v1",
          originalTaskId:priorTask,foreignSiblingTaskId:sibling.task.id,originalWorkItemId:originalWork,owner:originalOwner,operator:inspectPayload.operator,
          canonicalProducers:["PolicyManager.normalizeAdmission","PostgresLedger.admitTask","state.db.connect","state.work_items.upsert","state.control_plane_facts.record_artifact_reference","development_delivery.resolve_development_policies","state.control_plane_facts.request_approval","state.control_plane_facts.decide_approval"],
          originalAssociationProof:"ORIGINAL-ASSOCIATION.json",originalAssociationProofSha256:hashFile(associationEvidence),
          originalContextReceipt:"ORIGINAL-CONTEXT.json",originalContextReceiptSha256:hashFile(contextEvidence),
          sourceExecutionPolicy:"SOURCE-EXECUTION-POLICY.yml",sourceExecutionPolicySha256:hashFile(join(dirname(receiptFile),"SOURCE-EXECUTION-POLICY.yml")),
          candidateExecutionPolicy:"CANDIDATE-EXECUTION-POLICY.yml",candidateExecutionPolicySha256:hashFile(join(dirname(receiptFile),"CANDIDATE-EXECUTION-POLICY.yml")),
          policyTransitionProof:"POLICY-TRANSITION-PROOF.json",policyTransitionProofSha256:hashFile(join(dirname(receiptFile),"POLICY-TRANSITION-PROOF.json")),
          coldLedgerAcceptedReceipt:acceptedLedgerReceipt,coldLedgerAcceptedReceiptSha256:digest(acceptedLedgerReceipt),
          sameGenerationColdLedgerReplayVerified:digest(sameGenerationLedgerReplay)===digest(acceptedLedgerReceipt),laterGenerationColdLedgerReplayRefused:true,
          unchangedColdRecoveryJournalSha256:hashFile(coldJournalFile),unchangedAcceptedAnchorSha256:hashFile(anchorFile),coldLedgerReplayPreservesHolds:true,
          authorityPrivacyDriftRefused:permissionDrift,authorityPrivacyRollbackVerified:privacySql.includes("ROLLBACK")&&!privacySql.includes("COMMIT"),authorityPrivacyPreservesRows:true,
          contextSha256:inspectPayload.contextSha256,inspection:snapshot,inspectionSha256:digest(snapshot),
          cancellation:cancelled.receipt,cancellationSha256:digest(cancelled.receipt),cancellationEventSha256:digest(cancellationEvent),
          reaffirmedCancellation:reaffirmed.receipt,reaffirmedCancellationSha256:digest(reaffirmed.receipt),reaffirmationEventSha256:digest(reaffirmationEvent),completedAtPreserved:true,
          effectHold:effectHeld.receipt,effectHoldSha256:digest(effectHeld.receipt),effectHoldEventSha256:digest(effectEvent),
          taskDecisionHistory:latestTaskInspection.decisionHistory,effectDecisionHistory:effectAfter.decisionHistory,
          legacy016RowsSha256:digest(legacyRows),nonempty016UpgradePreserved:true,sqliteWriteFenceThroughPgCommit:fenceChecks.length===1,
          expiredExactReplayVerified:replayed.replayed,expiryRefusedFreshInspection:true,canonicalHistoryPredatesFirstHold:true,
          missingOrPostHoldHistoryRefused:true,missingOrPostHoldReferenceRefused:true,wrongOwnerOrApprovalRefused:true,
          changedContextOrPolicyRefused:true,changedDependencyOrEventRefused:true,sameKeyConflictRefused:true,stalePredecessorRefused:true,
          retainedQuarantine:counts,dependencyHashPreserved:afterInspection.dependencySha256===snapshot.dependencySha256,
          quarantineHistoryHashPreserved:afterInspection.historySha256===snapshot.historySha256,foreignSiblingUnchanged:true,
          claimDeliveryAdminReplayArtifactGuardsVerified:true,laterGenerationInvalidatesReplay:true,providerOrObjectCalls:0,
          genericRequeueQualified:false,providerOutcomeQualified:false,productionIngressQualified:false,
          scope:"native disposable producer/original-association and held metadata seams; restored dependencies and legacy016 rows are storage fixtures"},
        scope:"disposable local fixture only; no production fencing, backup/RPO, customer recovery or installed release qualification"});
      }
    } finally {await pool.end();rmSync(root,{recursive:true,force:true});}
  },180_000);
});
