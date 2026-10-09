import { generateKeyPairSync, sign } from "node:crypto";
import { chmodSync, copyFileSync, lstatSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { spawnSync } from "node:child_process";
import { DatabaseSync } from "node:sqlite";
import { randomUUID, createHash } from "node:crypto";
import { createPool, migrate } from "../src/db.js";
import { ArtifactStore } from "../src/artifacts.js";
import { PostgresReliabilityStore } from "../src/reliability.js";
import type pg from "pg";
import { describe, expect, it, vi } from "vitest";
import { authorizeColdRequest, canonical, digest, expectedCanaryResult, runColdLedgerOperation, type ColdPlan } from "../src/cold-recovery.js";
import { PostgresLedger, type AdmissionConstraints, type WorkerConstraints } from "../src/ledger.js";
import { LeaderResolver, type GatewayConfig } from "../src/gateway.js";

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
  const state={current_epoch:7,leader_host_id:"bigmac",cold_recovery_id:f.plan.recoveryId,cold_recovery_generation:3};
  const query=vi.fn(async(sql:string)=>{
    let rows:unknown[]=[];
    if(sql.includes("FROM pg_control_system"))rows=[{system_id:"12345"}];
    else if(sql.includes("pg_is_in_recovery"))rows=[{in_recovery:false,fsync:"on",full_page_writes:"on",archive_mode:"on",synchronous_commit:"on",synchronous_standby_names:""}];
    else if(sql.startsWith("SELECT * FROM fabric_state"))rows=[state];
    else if(sql.includes("SELECT plan_sha256,phase,receipts"))rows=[{plan_sha256:digest(f.plan),phase:"CANARY_ADMITTED",receipts:{},canary_io_baseline_sha256:digest([])}];
    else if(sql.startsWith("SELECT t.status"))rows=[canary];
    else if(sql.startsWith("SELECT count(*)::int"))rows=[{count:sql.includes("fabric_artifacts") ? overrides.artifactCount??0 : overrides.effectCount??0}];
    else if(sql.startsWith("SELECT 'effect'") && overrides.ioMutation)rows=[{kind:"effect",id:"foreign",digest:"changed"}];
    return {rows,rowCount:rows.length};
  });
  const pool={connect:vi.fn(async()=>({query,release:vi.fn()}))} as unknown as pg.Pool;
  return {pool,query};
}
describe("cold recovery held control plane (isolated unit seams)",()=>{
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
    const f=fixture(), p=poolFixture(f,overrides);
    await expect(runColdLedgerOperation(p.pool,"accept",f.request,f.policy,f.anchor)).rejects.toThrow(/effect-free runtime canary/);
    expect(p.query.mock.calls.filter(([sql])=>/^(INSERT|UPDATE|DELETE)/.test(sql))).toHaveLength(0);
    expect(p.query.mock.calls.some(([sql])=>sql==="ROLLBACK")).toBe(true);
  });
  it("successful canary receipt keeps residual restored-work quarantine",async()=>{
    const f=fixture(), p=poolFixture(f);
    expect(await runColdLedgerOperation(p.pool,"accept",f.request,f.policy,f.anchor)).toMatchObject({operation:"accept",fabricEpoch:7,generation:3,held:false,residualQuarantine:true});
    expect(p.query.mock.calls.some(([sql])=>sql==="COMMIT")).toBe(true);
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
      await migrate(pool);
      const migrations=await pool.query("SELECT version FROM fabric_schema_migrations ORDER BY version");
      expect(migrations.rows.some((r)=>r.version==="016_cold_recovery")).toBe(true);
      const f=fixture(), nextKey=generateKeyPairSync("ed25519"), oldKey=generateKeyPairSync("ed25519");
      expect(f.request.restoreInput.recoverySetId).toBe("20261009T230000Z-012345abcdef");
      // Dynamically import only the reviewed built sibling store; no alternate service actor.
      const storeModule=await import(pathToFileURL(join(serviceRoot,"execution-fabric-leadership-witness/dist/src/sqlite-store.js")).href);
      const original=join(root,"original.sqlite"), target=join(root,"target.sqlite");
      const originalStore=new storeModule.SqliteWitnessStore(original,f.plan.clusterId,{allowInitialBootstrap:true});
      const state={currentLeader:"genomesbox",fabricEpoch:4,timelineId:1,configDigest:"a".repeat(64),leaderWalPosition:null,leaderBaselineAt:null,upstreamSystemId:null,updatedAt:new Date().toISOString(),fenceDigest:"b".repeat(64),authorityMode:"standalone_primary",degradedUntil:null,degradedIncidentDigest:null};
      await originalStore.initialize(state,{auditId:randomUUID(),eventType:"initialized",actor:"isolated-fixture",occurredAt:state.updatedAt,detail:{}});
      await originalStore.close();
      for(const suffix of ["",".initialized",".backup"]){copyFileSync(original+suffix,target+suffix);chmodSync(target+suffix,0o600);}
      const marker=privateFile(join(root,"host-marker.json"),{clusterId:f.plan.clusterId,host:"genomesbox",isolated:true});
      const rotatedKey=privateFile(join(root,"rotated-key.pem"),nextKey.privateKey.export({type:"pkcs8",format:"pem"}).toString());
      const anchor={schemaVersion:"execution-fabric-recovery-anchor/v1",clusterId:f.plan.clusterId,leader:"genomesbox",generation:2,highestEpoch:6,publicKeySha256:createHash("sha256").update(oldKey.publicKey.export({type:"spki",format:"der"})).digest("hex"),pending:null,lastReceiptSha256:"c".repeat(64)};
      const systemId=String((await pool.query("SELECT system_identifier::text AS id FROM pg_control_system()")).rows[0].id);
      f.policy.witnessActorSha256=hashFile(witnessScript);f.policy.controlPlaneActorSha256=hashFile(ledgerScript);
      const db=new DatabaseSync(target,{readOnly:true});
      const version=Number((db.prepare("SELECT version FROM witness_snapshot WHERE cluster_id=?").get(f.plan.clusterId) as {version:number}).version);db.close();
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
      await pool.query("UPDATE fabric_state SET current_epoch=4,leader_host_id='genomesbox',leader_lease_expires_at=now()+interval '5 minutes',policy_fingerprint=$1 WHERE singleton=true",[f.plan.candidateConfigDigest]);
      const priorTask=randomUUID(), effectId=randomUUID(), attemptId=randomUUID(), runId=randomUUID(), leaseToken=randomUUID(), findingId=randomUUID(), alarmId=randomUUID(), artifactId=randomUUID();
      await pool.query("INSERT INTO fabric_tasks(id,namespace,queue_name,task_type,idempotency_key,request_hash,payload,required_capabilities,priority,status,max_attempts,provider,retry_backoff_seconds,config_fingerprint) VALUES($1,'isolated','old','old.task','old',$2,'{}','[]',0,'running',1,'local',0,$2)",[priorTask,f.plan.candidateConfigDigest]);
      await pool.query("INSERT INTO fabric_workers(worker_id,bootstrap_id,host_id,pool_id,provider,queues,capabilities,max_concurrency,metadata,registration_token,registered_epoch,config_fingerprint,lease_expires_at) VALUES('old-worker','old-bootstrap','genomesbox','local','local','[]','[]',1,'{}',$1,4,$2,now()+interval '5 minutes')",[randomUUID(),f.plan.candidateConfigDigest]);
      await pool.query("INSERT INTO fabric_runs(id,task_id,run_number,status) VALUES($1,$2,1,'running')",[runId,priorTask]);
      await pool.query("INSERT INTO fabric_attempts(id,task_id,run_id,worker_id,attempt_number,status,lease_token,recovery_token,fabric_epoch,lease_duration_seconds,lease_expires_at) VALUES($1,$2,$3,'old-worker',1,'running',$4,$5,4,60,now()+interval '5 minutes')",[attemptId,priorTask,runId,leaseToken,randomUUID()]);
      await pool.query("INSERT INTO fabric_effect_outbox(id,effect_key,task_id,attempt_id,effect_type,payload,fabric_epoch,max_attempts,base_backoff_seconds) VALUES($1,'old-effect',$2,$3,'provider.never','{}',4,1,1)",[effectId,priorTask,attemptId]);
      await pool.query("INSERT INTO fabric_health_findings(id,fingerprint,kind,scope_type,scope_id,severity,summary,details,fabric_epoch) VALUES($1,$2,'external_observation','external','isolated','warning','isolated','{}',4)",[findingId,"a".repeat(64)]);
      await pool.query("INSERT INTO fabric_alarm_outbox(id,finding_id,incident_key,revision,fabric_epoch,severity,payload) VALUES($1,$2,'isolated',1,4,'warning','{}')",[alarmId,findingId]);
      await pool.query("INSERT INTO fabric_artifacts(id,task_id,attempt_id,object_key,name,content_type,sha256,size_bytes,upload_expires_at) VALUES($1,$2,$3,'isolated-never','old.json','application/json',$4,1,now()+interval '5 minutes')",[artifactId,priorTask,attemptId,"a".repeat(64)]);
      expect(invoke("prepare")!.phase).toBe("PREPARED");
      expect(invoke("approve")!.phase).toBe("APPROVED");
      expect(invoke("apply")!.phase).toBe("ANCHOR_COMMITTED");
      const counts=(await pool.query("SELECT (SELECT count(*)::int FROM fabric_cold_task_quarantine) AS tasks,(SELECT count(*)::int FROM fabric_cold_effect_quarantine) AS effects,(SELECT count(*)::int FROM fabric_cold_alarm_quarantine) AS alarms,(SELECT count(*)::int FROM fabric_cold_artifact_quarantine) AS artifacts")).rows[0];
      expect(counts).toEqual({tasks:1,effects:1,alarms:1,artifacts:1});
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
      expect(invoke("resume")!.phase).toBe("ACCEPTED");
      expect(await ledger.claimEffects({consumerId:"isolated",source:"isolated",effectTypes:["provider.never"],limit:1},60)).toEqual([]);
      expect(await reliability.claimAlarms("isolated",1,60)).toEqual([]);
      await expect(reliability.replayEffect(effectId,"isolated","held-replay")).rejects.toThrow(/restored delivery reconciliation/);
      expect((await pool.query("SELECT status FROM fabric_effect_outbox WHERE id=$1",[effectId])).rows[0].status).toBe("pending");
      expect((await pool.query("SELECT status FROM fabric_attempts WHERE id=$1",[attemptId])).rows[0].status).toBe("fenced");
      expect((await pool.query("SELECT count(*)::int AS count FROM fabric_artifacts WHERE task_id=$1",[f.plan.canary.taskId])).rows[0].count).toBe(0);
      expect(blockedObject.send).not.toHaveBeenCalled();
      const receiptFile=process.env.FABRIC_COLD_TEST_RECEIPT_FILE;
      if(receiptFile)privateFile(receiptFile,{schemaVersion:"execution-fabric-isolated-cold-qualification/v1",databaseName:url.pathname.slice(1),migrationVersions:migrations.rows.map((r)=>r.version),recoveryId:f.plan.recoveryId,recoverySetId:f.request.restoreInput.recoverySetId,epoch:7,generation:3,canaryTaskId:f.plan.canary.taskId,quarantine:counts,providerOrObjectCalls:0,canaryHandler:"fabric_cold_canary_v1",canaryExecutor:"execute_assignment",canaryResultVerified:true,accepted:true,scope:"disposable local fixture only; no production fencing, backup/RPO or installed release qualification"});
    } finally {await pool.end();rmSync(root,{recursive:true,force:true});}
  },90_000);
});
