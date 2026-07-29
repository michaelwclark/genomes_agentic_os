import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import {
  assertFreshEpoch,
  findingFingerprint,
  nextBoundedFailure,
  replayedEffectState,
} from "../src/reliability.js";
import {
  allowListEnvironment,
  evaluateRoleHealth,
  ROLE_ENTRYPOINTS,
  runPeriodicRole,
} from "../src/roles.js";

describe("bounded reliability semantics", () => {
  it("dead-letters repeated effect failures at the configured bound", () => {
    let state = {
      attemptCount: 0,
      status: "pending" as "pending" | "dead_lettered",
      delaySeconds: 0,
    };
    for (let index = 0; index < 3; index += 1) {
      state = nextBoundedFailure({
        attemptCount: state.attemptCount,
        maxAttempts: 3,
        baseBackoffSeconds: 10,
      });
    }
    expect(state).toEqual({
      attemptCount: 3,
      status: "dead_lettered",
      delaySeconds: 0,
    });
  });

  it("uses bounded exponential backoff before dead-lettering", () => {
    expect(
      nextBoundedFailure({
        attemptCount: 0,
        maxAttempts: 8,
        baseBackoffSeconds: 60,
      }),
    ).toMatchObject({ attemptCount: 1, status: "pending", delaySeconds: 60 });
    expect(
      nextBoundedFailure({
        attemptCount: 10,
        maxAttempts: 100,
        baseBackoffSeconds: 3600,
      }).delaySeconds,
    ).toBe(86400);
  });

  it("recovers an expired claim as one bounded failure attempt", () => {
    const recovered = nextBoundedFailure({
      attemptCount: 1,
      maxAttempts: 4,
      baseBackoffSeconds: 30,
    });
    expect(recovered).toEqual({
      attemptCount: 2,
      status: "pending",
      delaySeconds: 60,
    });
  });

  it("replay resets delivery state and re-fences it to the current epoch", () => {
    expect(replayedEffectState(9)).toEqual({
      status: "pending",
      attemptCount: 0,
      fabricEpoch: 9,
      claimToken: null,
      claimExpiresAt: null,
      deadLetteredAt: null,
      cancelledAt: null,
      lastError: null,
    });
  });

  it("rejects stale finding epochs before a healer mutation", () => {
    expect(() => assertFreshEpoch(8, 9)).toThrow(/stale/);
    expect(() => assertFreshEpoch(9, 9)).not.toThrow();
  });

  it("uses stable finding identity without coupling it to changing details", () => {
    const identity = {
      kind: "missing_delivery" as const,
      scopeType: "queue" as const,
      scopeId: "pr_reviews",
    };
    expect(findingFingerprint(identity)).toBe(findingFingerprint(identity));
    expect(findingFingerprint(identity)).not.toBe(
      findingFingerprint({ ...identity, scopeId: "codex" }),
    );
  });
});

describe("independently runnable roles", () => {
  it("declares distinct API, observer, healer, and scheduler entrypoints and scripts", () => {
    expect(new Set(Object.values(ROLE_ENTRYPOINTS)).size).toBe(4);
    const packageJson = JSON.parse(
      readFileSync(join(process.cwd(), "package.json"), "utf8"),
    ) as { scripts: Record<string, string> };
    expect(packageJson.scripts["start:api"]).toContain(ROLE_ENTRYPOINTS.api);
    expect(packageJson.scripts["start:observer"]).toContain(
      ROLE_ENTRYPOINTS.observer,
    );
    expect(packageJson.scripts["start:healer"]).toContain(ROLE_ENTRYPOINTS.healer);
    expect(packageJson.scripts["start:scheduler"]).toContain(
      ROLE_ENTRYPOINTS.scheduler,
    );
  });

  it("runs an observer or healer tick without starting the API server", async () => {
    const tick = vi.fn().mockResolvedValue(undefined);
    await runPeriodicRole({
      role: "observer",
      intervalMs: 1000,
      signal: new AbortController().signal,
      tick,
      once: true,
    });
    expect(tick).toHaveBeenCalledOnce();
  });

  it("exposes exact policy convergence and sustained tick health", () => {
    const now = new Date("2026-07-29T12:00:30.000Z");
    const snapshot = {
      hostId: "genomesbox",
      role: "healer" as const,
      instanceId: "00000000-0000-4000-8000-000000000001",
      startedAt: "2026-07-29T12:00:00.000Z",
      approvedPolicyFingerprint: "a".repeat(64),
      appliedPolicyFingerprint: "a".repeat(64),
      lastSuccessfulTickAt: "2026-07-29T12:00:20.000Z",
      lastTickAt: "2026-07-29T12:00:20.000Z",
      lastError: null,
      consecutiveFailures: 0,
      updatedAt: "2026-07-29T12:00:20.000Z",
    };
    expect(evaluateRoleHealth(snapshot, { now })).toMatchObject({
      status: "healthy",
      reason: null,
    });
    expect(
      evaluateRoleHealth({
        ...snapshot,
        approvedPolicyFingerprint: null,
        lastSuccessfulTickAt: null,
        lastTickAt: null,
      }, { now }),
    ).toMatchObject({ status: "degraded", reason: "awaiting_first_tick" });
    expect(
      evaluateRoleHealth(
        { ...snapshot, consecutiveFailures: 1, lastError: "temporary" },
        { now },
      ),
    ).toMatchObject({ status: "degraded", reason: "tick_failure" });
    expect(
      evaluateRoleHealth(
        { ...snapshot, consecutiveFailures: 3, lastError: "persistent" },
        { now },
      ),
    ).toMatchObject({ status: "unhealthy", reason: "sustained_tick_failures" });
    expect(
      evaluateRoleHealth(
        { ...snapshot, appliedPolicyFingerprint: "b".repeat(64) },
        { now },
      ),
    ).toMatchObject({ status: "unhealthy", reason: "policy_fingerprint_mismatch" });
    expect(
      evaluateRoleHealth(
        { ...snapshot, lastSuccessfulTickAt: "2026-07-29T11:58:00.000Z" },
        { now, maxTickAgeSeconds: 60 },
      ),
    ).toMatchObject({ status: "unhealthy", reason: "successful_tick_stale" });
  });

  it("awaits durable error reporting before the next role interval", async () => {
    const recorded: string[] = [];
    await runPeriodicRole({
      role: "healer",
      intervalMs: 1000,
      signal: new AbortController().signal,
      once: true,
      tick: async () => {
        throw new Error("policy mismatch");
      },
      onError: async () => {
        await Promise.resolve();
        recorded.push("durable");
      },
    });
    expect(recorded).toEqual(["durable"]);
  });

  it("rejects unknown automatic repair actions", () => {
    const original = process.env.FABRIC_TEST_REPAIR_ACTIONS;
    process.env.FABRIC_TEST_REPAIR_ACTIONS = "reconstruct_delivery,run_arbitrary_agent";
    try {
      expect(() =>
        allowListEnvironment(
          "FABRIC_TEST_REPAIR_ACTIONS",
          ["reconstruct_delivery", "recover_effect_claim"] as const,
          ["reconstruct_delivery"] as const,
        ),
      ).toThrow(/unsupported action/);
    } finally {
      if (original === undefined) delete process.env.FABRIC_TEST_REPAIR_ACTIONS;
      else process.env.FABRIC_TEST_REPAIR_ACTIONS = original;
    }
  });
});
