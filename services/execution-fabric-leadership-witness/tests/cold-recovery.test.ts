import { generateKeyPairSync, createHash, sign } from "node:crypto";
import { chmodSync, copyFileSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { afterEach, describe, expect, it } from "vitest";
import { authorizeColdRequest, canonical, commitColdWitness, digest, fileHash, inspectColdWitness, safeFile, type ColdPlan, type VerifiedColdRequest } from "../src/cold-recovery.js";
import { SqliteWitnessStore } from "../src/sqlite-store.js";
import type { LeadershipState } from "../src/contracts.js";

const dirs: string[] = [];
afterEach(() => { for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true }); });
function privateFile(path: string, text: string): string { writeFileSync(path, text, { mode: 0o600 }); chmodSync(path, 0o600); return path; }
function keyHash(key: ReturnType<typeof generateKeyPairSync>["publicKey"]): string {
  return createHash("sha256").update(key.export({type:"spki", format:"der"})).digest("hex");
}
async function fixture() {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "cold-witness-"))); dirs.push(root);
  const original = join(root, "original.sqlite"), target = join(root, "target.sqlite");
  const oldKey = generateKeyPairSync("ed25519"), nextKey = generateKeyPairSync("ed25519");
  const operator = generateKeyPairSync("ed25519"), fencer = generateKeyPairSync("ed25519");
  const state: LeadershipState = {currentLeader:"genomesbox", fabricEpoch:4, timelineId:1, configDigest:"a".repeat(64), leaderWalPosition:null, leaderBaselineAt:null, upstreamSystemId:null, updatedAt:new Date().toISOString(), fenceDigest:"b".repeat(64), authorityMode:"standalone_primary", degradedUntil:null, degradedIncidentDigest:null};
  const store = new SqliteWitnessStore(original, "isolated-fabric", {allowInitialBootstrap:true});
  await store.initialize(state, {auditId:"initial-audit",eventType:"initialized",actor:"isolated-test",occurredAt:state.updatedAt,detail:{}});
  await store.close();
  for (const suffix of ["",".initialized",".backup"]) { copyFileSync(original+suffix, target+suffix); chmodSync(target+suffix, 0o600); }
  const marker = privateFile(join(root,"original-host-marker.json"), '{"clusterId":"isolated-fabric","host":"genomesbox"}');
  const signingPrivateKeyFile = privateFile(join(root,"rotated-private.pem"), nextKey.privateKey.export({type:"pkcs8",format:"pem"}).toString());
  const db = new DatabaseSync(target, {readOnly:true});
  const version = Number((db.prepare("SELECT version FROM witness_snapshot WHERE cluster_id=?").get("isolated-fabric") as {version:number}).version); db.close();
  const policy = {schemaVersion:"execution-fabric-cold-recovery-policy/v1" as const,enabled:true,clusterId:"isolated-fabric",allowedHosts:["genomesbox","bigmac"],recoveryPublicKeyPem:operator.publicKey.export({type:"spki",format:"pem"}).toString(),fencePublicKeyPem:fencer.publicKey.export({type:"spki",format:"pem"}).toString(),maxApprovalSeconds:600,witnessActorSha256:"a".repeat(64),controlPlaneActorSha256:"b".repeat(64)};
  const initialAnchor = {schemaVersion:"execution-fabric-recovery-anchor/v1" as const,clusterId:policy.clusterId,leader:"genomesbox",generation:2,highestEpoch:6,publicKeySha256:keyHash(oldKey.publicKey),lastReceiptSha256:"c".repeat(64),pending:null};
  const now=Date.now(), stamp=(offset:number)=>new Date(now+offset*1000).toISOString();
  const payload={schema_version:"execution-fabric-cold-canary/v1" as const,recovery_id:"9b4bf200-4ac8-4a64-9969-07812e617d81",cluster_id:policy.clusterId,epoch:7,generation:3};
  const plan:ColdPlan={schemaVersion:"execution-fabric-cold-recovery-plan/v1",recoveryId:"9b4bf200-4ac8-4a64-9969-07812e617d81",direction:"recovery",clusterId:policy.clusterId,sourceHost:"genomesbox",targetHost:"bigmac",expectedEpoch:4,nextEpoch:7,generation:3,anchorSha256:digest(initialAnchor),policySha256:digest(policy),restoreInputSha256:"d".repeat(64),manifestSha256:"e".repeat(64),restoreReceiptSha256:"f".repeat(64),snapshotVersion:version,originalDatabasePath:original,originalBackupPath:original+".backup",targetDatabasePath:target,databaseSha256:fileHash(target),sentinelSha256:fileHash(target+".initialized"),backupSha256:fileHash(target+".backup"),hostMarkerSha256:fileHash(marker),oldPublicKeySha256:initialAnchor.publicKeySha256,newPublicKeySha256:keyHash(nextKey.publicKey),candidateConfigDigest:"1".repeat(64),newPgSystemId:"12345",timelineId:1,walPosition:0,createdAt:stamp(-1),expiresAt:stamp(500),canary:{taskId:"c86c6c43-e638-4d37-a0f6-9e423ff7d764",workerId:"isolated-canary",taskType:"fabric.cold_canary",queue:"fabric_cold_recovery",namespace:"fabric_cold_recovery",payload,payloadSha256:digest(payload)}};
  const restoreInput={schemaVersion:"execution-fabric-cold-restore-input/v1",recoverySetId:"20261009T230000Z-012345abcdef",manifestSha256:plan.manifestSha256,restoreReceiptSha256:plan.restoreReceiptSha256,sourceRelease:"0.10.1",imageLockSha256:"f".repeat(64),capturedAt:stamp(-5),commonWatermark:"isolated-quiescent-watermark",custodyReceiptSha256:"b".repeat(64),witness:{clusterId:plan.clusterId,version:plan.snapshotVersion,leader:plan.sourceHost,epoch:plan.expectedEpoch,auditTailSha256:"a".repeat(64),databaseSha256:plan.databaseSha256,sentinelSha256:plan.sentinelSha256,backupSha256:plan.backupSha256,hostMarkerSha256:plan.hostMarkerSha256,originalDatabasePath:plan.originalDatabasePath,originalBackupPath:plan.originalBackupPath,signingPublicKeySha256:plan.oldPublicKeySha256},postgres:{dumpSha256:"d".repeat(64),restoreReadbackSha256:"e".repeat(64),systemId:plan.newPgSystemId,majorVersion:17},artifacts:{inventorySha256:"f".repeat(64),verifiedReferences:true},osAuthority:{snapshotSha256:"a".repeat(64),immutableReceiptInventorySha256:"b".repeat(64)}};
  plan.restoreInputSha256=digest(restoreInput);
  const signed = (payload: unknown, key=operator.privateKey) => ({payload,signature:sign(null,Buffer.from(canonical(payload)),key).toString("base64")});
  const fence=signed({schemaVersion:"execution-fabric-external-fence/v1",recoveryId:plan.recoveryId,clusterId:policy.clusterId,sourceHost:"genomesbox",sourceBootId:"original-boot",durable:true,highestGeneration:2,highestEpoch:6,coveredWriterScopes:["witness","postgres","producer","provider"],evidenceSha256:"2".repeat(64),issuedAt:stamp(-1),expiresAt:stamp(500)},fencer.privateKey);
  const anchor={...initialAnchor,generation:3,pending:{recoveryId:plan.recoveryId,planSha256:digest(plan),generation:3,nextEpoch:7,targetHost:"bigmac",phase:"RESERVED" as const}};
  const request:Record<string,unknown>={plan,restoreInput,fence,approval:signed({schemaVersion:"execution-fabric-cold-recovery-approval/v1",planSha256:digest(plan),policySha256:digest(policy),fenceSha256:digest(fence),approvedBy:"isolated-operator",issuedAt:stamp(-1),expiresAt:stamp(500)}),hostMarkerFile:marker,signingPrivateKeyFile};
  return {root,original,target,policy,anchor,request,plan,marker,signingPrivateKeyFile,signed,fence,stamp,fencer};
}
describe("offline standalone cold authority",()=>{
  function rebindSetId(f:Awaited<ReturnType<typeof fixture>>,recoverySetId:string):void {
    const input=f.request.restoreInput as {recoverySetId:string};input.recoverySetId=recoverySetId;
    f.plan.restoreInputSha256=digest(input);
    f.request.approval=f.signed({...((f.request.approval as {payload:Record<string,unknown>}).payload),planSha256:digest(f.plan)});
    f.anchor.pending.planSha256=digest(f.plan);
  }
  it.each(["20261009T230000Z-012345abcdef","3ebd266b-2f8d-4b85-9e6d-cd908a232eb0","A","a_B.c-d","A"+"x".repeat(127)])("authorizes original bounded manifest set ID without aliases: %s",async(setId)=>{
    const f=await fixture();rebindSetId(f,setId);
    expect(authorizeColdRequest(f.request,f.policy,f.anchor).plan.restoreInputSha256).toBe(digest(f.request.restoreInput));
    expect((f.request.restoreInput as {recoverySetId:string}).recoverySetId).toBe(setId);
  });
  it.each(["","../escape","/absolute","a/b","a\\b",".hidden","_leading","-leading","white space","a\n","a\r","a\u2028","a\0","é","💥","A"+"x".repeat(128)])("unsafe or oversized set ID refuses before authority write: %j",async(setId)=>{
    const f=await fixture(),before=["",".initialized",".backup"].map((suffix)=>fileHash(f.target+suffix));
    rebindSetId(f,setId);
    await expect(commitColdWitness(f.request,f.policy,f.anchor)).rejects.toThrow();
    expect(["",".initialized",".backup"].map((suffix)=>fileHash(f.target+suffix))).toEqual(before);
  });
  it.each(["recoveryId","taskId"])("transition %s still requires UUID before authority write",async(field)=>{
    const f=await fixture(),before=fileHash(f.target);
    if(field==="recoveryId")f.plan.recoveryId="20261009T230000Z-012345abcdef";else f.plan.canary.taskId="20261009T230000Z-012345abcdef";
    await expect(commitColdWitness(f.request,f.policy,f.anchor)).rejects.toThrow(/uuid/);
    expect(fileHash(f.target)).toBe(before);
  });
  it("ordinary startup refuses relocated sentinel; verified commit rotates epoch and preserves history",async()=>{
    const f=await fixture();
    expect(()=>new SqliteWitnessStore(f.target,"isolated-fabric")).toThrow(/bootstrap marker|storage identity|does not match|sentinel/);
    const receipt=await commitColdWitness(f.request,f.policy,f.anchor);
    expect(receipt).toMatchObject({fabricEpoch:7,previousLeader:"genomesbox",currentLeader:"bigmac",generation:3,held:true});
    const restarted=new SqliteWitnessStore(f.target,"isolated-fabric");
    expect(await restarted.getState()).toMatchObject({currentLeader:"bigmac",fabricEpoch:7,authorityMode:"standalone_primary",degradedUntil:null});
    expect(await restarted.listAudit(10)).toEqual(expect.arrayContaining([expect.objectContaining({auditId:"initial-audit"}),expect.objectContaining({eventType:"cold_recovery_committed",previousEpoch:4,newEpoch:7})]));
    await restarted.close();
    expect(JSON.parse(readFileSync(f.target+".initialized","utf8"))).toMatchObject({database:f.target,backup:f.target+".backup"});
    expect(await commitColdWitness(f.request,f.policy,f.anchor)).toEqual(receipt);
  });
  it("forged authorization capability never opens the database",async()=>{
    const f=await fixture(), before=fileHash(f.target);
    expect(()=>new SqliteWitnessStore(f.target,"isolated-fabric",{coldAuthorization:{plan:f.plan,policy:f.policy,anchor:f.anchor} as VerifiedColdRequest})).toThrow(/not verified/);
    expect(fileHash(f.target)).toBe(before);
  });
  it("verified capability is immutable and ordinary store has no cold mutation grant",async()=>{
    const f=await fixture(), auth=authorizeColdRequest(f.request,f.policy,f.anchor);
    expect(()=>{auth.plan.nextEpoch=99;}).toThrow();
    const normal=new SqliteWitnessStore(f.original,"isolated-fabric");
    await expect(normal.commitColdRecovery({} as Parameters<SqliteWitnessStore["commitColdRecovery"]>[0])).rejects.toThrow(/ordinary witness store/);
    await normal.close();
  });
  it("bad signature refuses before any authority write",async()=>{
    const f=await fixture(), before=fileHash(f.target);
    (f.request.approval as {signature:string}).signature=Buffer.alloc(64).toString("base64");
    await expect(commitColdWitness(f.request,f.policy,f.anchor)).rejects.toThrow(/signature/);
    expect(fileHash(f.target)).toBe(before);
  });
  it("foreign anchor watermark refuses even with valid signatures",async()=>{
    const f=await fixture(), before=fileHash(f.target);
    f.anchor.highestEpoch=5;
    await expect(commitColdWitness(f.request,f.policy,f.anchor)).rejects.toThrow(/high-watermark/);
    expect(fileHash(f.target)).toBe(before);
  });
  it("missing backup and tampered original sentinel refuse without commit",async()=>{
    const f=await fixture(), auth=authorizeColdRequest(f.request,f.policy,f.anchor);
    const original=readFileSync(f.target+".initialized","utf8");
    privateFile(f.target+".initialized",JSON.stringify({...JSON.parse(original),backup:join(f.root,"unbound.backup")}));
    expect(()=>inspectColdWitness(auth,f.marker)).toThrow(/history\/hash\/path/);
    privateFile(f.target+".initialized",original);
    rmSync(f.target+".backup");
    expect(()=>inspectColdWitness(auth,f.marker)).toThrow();
  });
  it("live database lease and group-readable private key refuse",async()=>{
    const f=await fixture(), auth=authorizeColdRequest(f.request,f.policy,f.anchor);
    const db=new DatabaseSync(f.target);
    db.prepare("INSERT OR REPLACE INTO witness_process_lease(cluster_id,owner_token,lease_expires_at,acquired_at) VALUES(?,?,?,?)").run("isolated-fabric","live-owner",Date.now()+60_000,new Date().toISOString());
    db.close();
    expect(()=>inspectColdWitness(auth,f.marker)).toThrow(/still owns/);
    const g=await fixture();chmodSync(g.signingPrivateKeyFile,0o640);
    await expect(commitColdWitness(g.request,g.policy,g.anchor)).rejects.toThrow(/private/);
  });
  it("canonical numbers and symlink ancestry fail closed",async()=>{
    const f=await fixture();
    expect(()=>canonical({value:0.1})).toThrow(/safe integers/);
    const link=join(f.root,"linked");symlinkSync(f.root,link);
    expect(()=>safeFile(join(link,"original-host-marker.json"))).toThrow(/unsafe/);
  });
  it("committed replay refuses tampered backup path and different plan",async()=>{
    const f=await fixture();await commitColdWitness(f.request,f.policy,f.anchor);
    privateFile(f.target+".initialized",JSON.stringify({...JSON.parse(readFileSync(f.target+".initialized","utf8")),backup:"/foreign.backup"}));
    await expect(commitColdWitness(f.request,f.policy,f.anchor)).rejects.toThrow(/path binding/);
  });
  it("failback requires a fresh current-host snapshot, new key and another monotonic epoch",async()=>{
    const f=await fixture();await commitColdWitness(f.request,f.policy,f.anchor);
    const target=join(f.root,"returned-genomesbox.sqlite");
    for(const suffix of ["",".initialized",".backup"]){copyFileSync(f.target+suffix,target+suffix);chmodSync(target+suffix,0o600);}
    const db=new DatabaseSync(target,{readOnly:true});
    const version=Number((db.prepare("SELECT version FROM witness_snapshot WHERE cluster_id=?").get(f.plan.clusterId) as {version:number}).version);db.close();
    const key=generateKeyPairSync("ed25519");
    const marker=privateFile(join(f.root,"bigmac-marker.json"),'{"host":"bigmac","clusterId":"isolated-fabric"}');
    const signingPrivateKeyFile=privateFile(join(f.root,"failback-key.pem"),key.privateKey.export({type:"pkcs8",format:"pem"}).toString());
    const prior={...f.anchor,leader:"bigmac",highestEpoch:7,publicKeySha256:f.plan.newPublicKeySha256,pending:null};
    const plan:ColdPlan={...f.plan,recoveryId:"9b4bf200-4ac8-4a64-9969-07812e617d82",direction:"failback",sourceHost:"bigmac",targetHost:"genomesbox",expectedEpoch:7,nextEpoch:8,generation:4,anchorSha256:digest(prior),snapshotVersion:version,originalDatabasePath:f.target,originalBackupPath:f.target+".backup",targetDatabasePath:target,databaseSha256:fileHash(target),sentinelSha256:fileHash(target+".initialized"),backupSha256:fileHash(target+".backup"),hostMarkerSha256:fileHash(marker),oldPublicKeySha256:f.plan.newPublicKeySha256,newPublicKeySha256:keyHash(key.publicKey)};
    plan.canary={...plan.canary,payload:{...plan.canary.payload,recovery_id:plan.recoveryId,epoch:plan.nextEpoch,generation:plan.generation}};
    plan.canary.payloadSha256=digest(plan.canary.payload);
    const restoreInput=structuredClone(f.request.restoreInput) as {witness:Record<string,unknown>};
    Object.assign(restoreInput.witness,{version,leader:"bigmac",epoch:7,originalDatabasePath:f.target,originalBackupPath:f.target+".backup",databaseSha256:plan.databaseSha256,sentinelSha256:plan.sentinelSha256,backupSha256:plan.backupSha256,hostMarkerSha256:plan.hostMarkerSha256,signingPublicKeySha256:plan.oldPublicKeySha256});
    plan.restoreInputSha256=digest(restoreInput);
    const fence=f.signed({...f.fence.payload as Record<string,unknown>,recoveryId:plan.recoveryId,sourceHost:"bigmac",highestGeneration:3,highestEpoch:7},f.fencer.privateKey);
    const approval=f.signed({schemaVersion:"execution-fabric-cold-recovery-approval/v1",planSha256:digest(plan),policySha256:digest(f.policy),fenceSha256:digest(fence),approvedBy:"isolated-operator",issuedAt:f.stamp(-1),expiresAt:f.stamp(500)});
    const anchor={...prior,generation:4,pending:{recoveryId:plan.recoveryId,planSha256:digest(plan),generation:4,nextEpoch:8,targetHost:"genomesbox",phase:"RESERVED"}};
    const receipt=await commitColdWitness({plan,restoreInput,fence,approval,hostMarkerFile:marker,signingPrivateKeyFile},f.policy,anchor);
    expect(receipt).toMatchObject({currentLeader:"genomesbox",previousLeader:"bigmac",fabricEpoch:8,generation:4,held:true});
    const restarted=new SqliteWitnessStore(target,f.plan.clusterId);
    expect(await restarted.listAudit(10)).toEqual(expect.arrayContaining([expect.objectContaining({eventType:"cold_recovery_committed",newEpoch:7}),expect.objectContaining({eventType:"cold_recovery_committed",newEpoch:8})]));
    await restarted.close();
  });
});
