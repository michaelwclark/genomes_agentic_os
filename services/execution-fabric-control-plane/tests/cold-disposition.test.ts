import { generateKeyPairSync, randomUUID, sign } from "node:crypto";
import { existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type pg from "pg";
import { describe, expect, it, vi } from "vitest";
import { canonical, digest } from "../src/cold-recovery.js";
import {
  dispositionApprovalBinding,
  dispositionInspectionSchema,
  dispositionRequestSchema,
  inspectColdDisposition,
  runColdDisposition,
  type DispositionPayload,
} from "../src/cold-disposition.js";

// These are pre-connection refusal fixtures, never canonical store qualification.
function refusalFixture() {
  const key = generateKeyPairSync("ed25519");
  const authority = join(tmpdir(), "absent-disposition-" + randomUUID(), "state.db");
  const policy = {
    schemaVersion: "execution-fabric-cold-recovery-policy/v1", enabled: true,
    clusterId: "disposition-refusal", allowedHosts: ["genomesbox", "bigmac"],
    recoveryPublicKeyPem: key.publicKey.export({ type: "spki", format: "pem" }).toString(),
    fencePublicKeyPem: key.publicKey.export({ type: "spki", format: "pem" }).toString(),
    maxApprovalSeconds: 600, witnessActorSha256: "a".repeat(64), controlPlaneActorSha256: "b".repeat(64),
    selectiveDisposition: {
      enabled: true, acceptedPolicySha256: "c".repeat(64), sourceRelease: "0.10.1",
      authority: { backend: "sqlite", databasePath: authority, domain: "isolated", project: "disposition-test" },
      executionPolicyFile: join(tmpdir(), "absent-policy-" + randomUUID() + ".yml"),
      allowedLocalTaskTypes: ["fabric.cold_canary"], heldProviders: ["claude", "codex"],
    },
  };
  const anchor = {
    schemaVersion: "execution-fabric-recovery-anchor/v1", clusterId: policy.clusterId,
    leader: "bigmac", generation: 3, highestEpoch: 7, publicKeySha256: "d".repeat(64),
    lastReceiptSha256: "e".repeat(64), pending: null,
  };
  const stamp = (seconds: number) => new Date(Date.now() + seconds * 1000).toISOString();
  const payload: DispositionPayload = {
    schemaVersion: "execution-fabric-cold-disposition/v1", recoveryId: randomUUID(),
    generation: 3, fabricEpoch: 7, clusterId: policy.clusterId, targetHost: "bigmac", pgSystemId: "12345",
    planSha256: "f".repeat(64), acceptedReceiptSha256: anchor.lastReceiptSha256,
    acceptedPolicySha256: policy.selectiveDisposition.acceptedPolicySha256,
    policySha256: digest(policy), configFingerprint: "1".repeat(64), executionPolicySha256: "2".repeat(64),
    sourceRelease: "0.10.1", itemKind: "task", itemId: randomUUID(), itemSha256: "3".repeat(64),
    historySha256: "4".repeat(64), dependencySha256: "5".repeat(64),
    workItemId: "original-work", workItemSha256: "6".repeat(64), owner: "original-owner",
    operator: "named-operator", contextSha256: "7".repeat(64), approvalId: "named-approval",
    approvalSha256: "8".repeat(64), disposition: "task_cancel", priorDispositionSha256: null,
    idempotencyKey: "one-cancellation", reason: "owner_cancelled", issuedAt: stamp(-1), expiresAt: stamp(300),
  };
  const signed = <T>(value: T) => ({
    payload: value,
    signature: sign(null, Buffer.from(canonical(value)), key.privateKey).toString("base64"),
  });
  const inspection = (): Record<string, unknown> => {
    const keys = ["recoveryId", "generation", "fabricEpoch", "clusterId", "targetHost", "itemKind", "itemId",
      "workItemId", "owner", "operator", "contextSha256", "policySha256", "issuedAt", "expiresAt"];
    return { schemaVersion: "execution-fabric-cold-disposition-inspection/v1",
      ...Object.fromEntries(keys.map((name) => [name, (payload as unknown as Record<string, unknown>)[name]])) };
  };
  const pool = { connect: vi.fn(), query: vi.fn() } as unknown as pg.Pool;
  return { policy, anchor, payload, signed, inspection, pool, authority };
}

describe("cold disposition closed pre-connection boundaries", () => {
  it.each([
    ["generation", true], ["generation", 0],
    ["recoveryId", "not-a-uuid"], ["itemId", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"],
    ["owner", ""], ["operator", "💥".repeat(129)], ["pgSystemId", "123\n"],
    ["targetHost", "bigmac\n"], ["contextSha256", "a".repeat(64) + "\n"],
    ["idempotencyKey", "../escape"], ["issuedAt", "2026-10-12"],
    ["expiresAt", "2026-99-99T00:00:00Z"], ["disposition", "delete"], ["reason", true],
  ])("rejects malformed %s before any database", async (name, value) => {
    const f = refusalFixture();
    const payload = { ...f.payload, [String(name)]: value };
    await expect(runColdDisposition(f.pool, f.signed(payload), f.policy, f.anchor)).rejects.toThrow();
    expect(f.pool.connect).not.toHaveBeenCalled();
    expect(existsSync(f.authority)).toBe(false);
  });
  it("unsafe numeric counter is refused by the canonical signer and closed schema without IO",()=>{
    const f=refusalFixture(),payload={...f.payload,fabricEpoch:Number.MAX_SAFE_INTEGER+1};
    expect(()=>f.signed(payload)).toThrow("cold protocol numbers must be safe integers");
    // Schema-only observation: this envelope is never sent as signed authority.
    const parsed=dispositionRequestSchema.safeParse({...f.signed(f.payload),payload});
    expect(parsed.success).toBe(false);
    if(!parsed.success)expect(parsed.error.issues).toEqual(expect.arrayContaining([
      expect.objectContaining({path:["payload","fabricEpoch"],code:"too_big",maximum:Number.MAX_SAFE_INTEGER}),
    ]));
    expect(f.pool.connect).not.toHaveBeenCalled();expect(f.pool.query).not.toHaveBeenCalled();
    expect(existsSync(f.authority)).toBe(false);
  });

  it("binds approval to every decision field while excluding only the circular approval-row hash", () => {
    const f = refusalFixture(), original = dispositionApprovalBinding(f.payload);
    expect(dispositionApprovalBinding({ ...f.payload, approvalSha256: "0".repeat(64) })).toBe(original);
    for (const delta of [{ owner: "foreign" }, { operator: "foreign" }, { itemId: randomUUID() },
      { dependencySha256: "0".repeat(64) }, { priorDispositionSha256: "0".repeat(64) }]) {
      expect(dispositionApprovalBinding({ ...f.payload, ...delta })).not.toBe(original);
    }
  });

  it("refuses caller-supplied ownership and eligibility booleans in both closed protocols", async () => {
    const f = refusalFixture();
    expect(dispositionRequestSchema.safeParse({ ...f.signed(f.payload), approved: true }).success).toBe(false);
    await expect(runColdDisposition(f.pool, f.signed({ ...f.payload, released: true }), f.policy, f.anchor)).rejects.toThrow();
    expect(dispositionInspectionSchema.safeParse(f.signed({ ...f.inspection(), ownerVerified: true })).success).toBe(false);
    expect(f.pool.connect).not.toHaveBeenCalled();
  });

  it.each(["signature", "policy", "generation", "pending", "disabled", "release", "acceptedPolicy"])(
    "refuses changed %s authority before canonical SQLite or PG", async (seam) => {
      const f = refusalFixture(), request = f.signed(f.payload);
      if (seam === "signature") request.signature = "A".repeat(86) + "==";
      if (seam === "policy") f.policy.clusterId = "foreign";
      if (seam === "generation") f.anchor.generation += 1;
      if (seam === "pending") (f.anchor as unknown as Record<string, unknown>).pending = {};
      if (seam === "disabled") f.policy.selectiveDisposition.enabled = false;
      if (seam === "release") request.payload.sourceRelease = "foreign-release";
      if (seam === "acceptedPolicy") request.payload.acceptedPolicySha256 = "0".repeat(64);
      await expect(runColdDisposition(f.pool, request, f.policy, f.anchor)).rejects.toThrow();
      expect(f.pool.connect).not.toHaveBeenCalled();
      expect(existsSync(f.authority)).toBe(false);
    });

  it.each([
    ["task", "task_requeue"], ["effect", "effect_retry"], ["effect", "effect_delivered"], ["task", "effect_delivered"],
  ] as const)("retains unqualified %s/%s without creating an authority store", async (kind, verb) => {
    const f = refusalFixture();
    const request = f.signed({ ...f.payload, itemKind: kind, disposition: verb });
    await expect(runColdDisposition(f.pool, request, f.policy, f.anchor)).rejects.toThrow(/unavailable/);
    expect(f.pool.connect).not.toHaveBeenCalled();
    expect(existsSync(f.authority)).toBe(false);
  });

  it.each(["signature", "expired", "future", "tooLong", "policy", "laterGeneration"])(
    "refuses inspection %s without PG or authority bootstrap", async (seam) => {
      const f = refusalFixture(), payload = f.inspection();
      if (seam === "expired") payload.expiresAt = new Date(Date.now() - 1000).toISOString();
      if (seam === "future") payload.issuedAt = new Date(Date.now() + 1000).toISOString();
      if (seam === "tooLong") payload.expiresAt = new Date(Date.now() + 700_000).toISOString();
      if (seam === "policy") payload.policySha256 = "0".repeat(64);
      if (seam === "laterGeneration") f.anchor.generation += 1;
      const request = f.signed(payload);
      if (seam === "signature") request.signature = "A".repeat(86) + "==";
      await expect(inspectColdDisposition(f.pool, request, f.policy, f.anchor)).rejects.toThrow();
      expect(f.pool.connect).not.toHaveBeenCalled();
      expect(existsSync(f.authority)).toBe(false);
    });

  it("missing original store remains missing when a correctly signed hold reaches native authority", async () => {
    const f = refusalFixture();
    await expect(runColdDisposition(f.pool, f.signed({ ...f.payload, disposition: "hold", reason: "outcome_unknown" }),
      f.policy, f.anchor)).rejects.toThrow();
    expect(f.pool.connect).not.toHaveBeenCalled();
    expect(existsSync(f.authority)).toBe(false);
  });
});
