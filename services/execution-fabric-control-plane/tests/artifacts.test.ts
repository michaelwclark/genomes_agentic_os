import type pg from "pg";
import type { S3Client } from "@aws-sdk/client-s3";
import { describe, expect, it, vi } from "vitest";
import { ArtifactStore } from "../src/artifacts.js";

describe("cold recovery artifact custody",()=>{
  it.each(["initiate","initiateRecovery","finalize","finalizeRecovery"] as const)("holds %s before any object client or write",async(action)=>{
    const query=vi.fn(async()=>({rows:[{blocked:true}],rowCount:1}));
    const pool={query,connect:vi.fn()} as unknown as pg.Pool;
    const send=vi.fn();
    const store=new ArtifactStore(pool,{endpoint:"http://127.0.0.1:1",region:"test",bucket:"isolated",accessKeyId:"fixture",secretAccessKey:"fixture",forcePathStyle:true,uploadTtlSeconds:60,downloadTtlSeconds:60,maxBytes:1024},"isolated",{send} as unknown as S3Client);
    const input={attemptId:"9b4bf200-4ac8-4a64-9969-07812e617d81"};
    const call=action==="initiate" ? store.initiate(input as Parameters<ArtifactStore["initiate"]>[0])
      : action==="initiateRecovery" ? store.initiateRecovery(input as Parameters<ArtifactStore["initiateRecovery"]>[0])
      : action==="finalize" ? store.finalize("artifact",input as Parameters<ArtifactStore["finalize"]>[1])
      : store.finalizeRecovery("artifact",input as Parameters<ArtifactStore["finalizeRecovery"]>[1]);
    await expect(call).rejects.toThrow(/cold recovery holds artifact writes/);
    expect(pool.connect).not.toHaveBeenCalled();expect(send).not.toHaveBeenCalled();
  });
});

