import { readFileSync, lstatSync } from "node:fs";
import { fileURLToPath } from "node:url";
import pg from "pg";
import { runColdLedgerOperation, fileHash, safeFile } from "./cold-recovery.js";

async function main():Promise<void> {
  const [flag,secretFile,operation,policyFile,anchorFile,...extra]=process.argv.slice(2);
  if(flag!=="--database-url-file" || !secretFile || !operation || !policyFile || !anchorFile || extra.length) throw new Error("explicit target database secret file is required");
  const privateSecret=safeFile(secretFile);
  if(lstatSync(privateSecret).mode & 0o077) throw new Error("target database secret must be private to its owner");
  const policy=JSON.parse(readFileSync(safeFile(policyFile),"utf8"));
  if(fileHash(fileURLToPath(import.meta.url))!==policy.controlPlaneActorSha256) throw new Error("unreviewed control-plane actor image");
  const databaseUrl=readFileSync(privateSecret,"utf8").trim();
  const url=new URL(databaseUrl);
  if (!["postgres:","postgresql:"].includes(url.protocol) || !url.hostname || !url.pathname || url.pathname==="/") throw new Error("target PostgreSQL URL is invalid");
  const chunks:Buffer[]=[];let bytes=0;
  for await(const chunk of process.stdin){const data=Buffer.from(chunk);bytes+=data.length;if(bytes>4_194_304)throw new Error("cold request too large");chunks.push(data);}
  const pool=new pg.Pool({connectionString:databaseUrl,max:1,connectionTimeoutMillis:5000,application_name:"agentic-os-offline-cold-recovery"});
  try {
    const request=JSON.parse(Buffer.concat(chunks).toString("utf8")) as Record<string,unknown>;
    const result=await runColdLedgerOperation(pool,operation,request,policy,JSON.parse(readFileSync(safeFile(anchorFile),"utf8")));
    process.stdout.write(JSON.stringify(result)+"\n");
  } finally {await pool.end();}
}
main().catch((error:unknown)=>{
  const value=error as {code?:unknown;name?:unknown};
  const classification=typeof value?.code==="string" && /^[0-9A-Z]{5}$/.test(value.code) ? "postgres_"+value.code : value?.name==="ZodError" ? "schema" : "actor_or_authorization";
  // Never expose a database URL, query values, key bytes or arbitrary message.
  process.stderr.write("cold_recovery_refused:"+classification+"\n");process.exitCode=1;
});
