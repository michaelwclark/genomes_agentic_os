import { describe, expect, it, vi } from "vitest";
import type { TaskRecord } from "../src/contracts.js";
import type { DeliveryPort } from "../src/delivery.js";
import { ExecutionFabric } from "../src/fabric.js";
import type { LedgerPort } from "../src/ledger.js";
import { createTestPolicy } from "./policy-fixture.js";

const task: TaskRecord = {
  id: "2ec5aa60-5ee8-4bc0-b629-d8f1eff7fc77",
  namespace: "test",
  queue: "code",
  taskType: "example.run",
  schedulingClass: "background",
  payload: {},
  requiredCapabilities: [],
  priority: 0,
  status: "queued",
  maxAttempts: 3,
  attemptCount: 0,
  availableAt: "2026-01-01T00:00:00.000Z",
  createdAt: "2026-01-01T00:00:00.000Z",
};

function fixture() {
  const ledger = {
    admitTask: vi.fn().mockResolvedValue({ task, admitted: true }),
    markPublished: vi.fn().mockResolvedValue(undefined),
    claim: vi.fn().mockResolvedValue(null),
    listPublishable: vi.fn().mockResolvedValue([]),
    reconcileExpired: vi
      .fn()
      .mockResolvedValue({
        expiredRequeued: 0,
        expiredDeadLettered: 0,
        effectsRequeued: 0,
        effectsDeadLettered: 0,
      }),
    claimEffects: vi.fn().mockResolvedValue([]),
    deliverEffect: vi.fn().mockResolvedValue(undefined),
    failEffect: vi.fn().mockResolvedValue(undefined),
  } as unknown as LedgerPort;
  const delivery = {
    publish: vi.fn().mockResolvedValue(undefined),
    acknowledge: vi.fn().mockResolvedValue(undefined),
    waitForWork: vi.fn().mockResolvedValue(undefined),
    ping: vi.fn().mockResolvedValue(undefined),
    close: vi.fn().mockResolvedValue(undefined),
  } satisfies DeliveryPort;
  return {
    ledger,
    delivery,
    fabric: new ExecutionFabric(
      ledger,
      delivery,
      120,
      100,
      createTestPolicy().policy,
    ),
  };
}

describe("ExecutionFabric", () => {
  it("publishes and receipts admitted work", async () => {
    const { fabric, delivery, ledger } = fixture();
    const result = await fabric.admit({
      namespace: "test",
      queue: "code",
      taskType: "example.run",
      idempotencyKey: "one",
      payload: {},
      requiredCapabilities: ["test.run"],
      priority: 0,
      maxAttempts: 3,
    });
    expect(result.admitted).toBe(true);
    expect(delivery.publish).toHaveBeenCalledWith(task);
    expect(ledger.markPublished).toHaveBeenCalledWith(task.id);
  });

  it("long-polls once and returns no work without inventing an assignment", async () => {
    const { fabric, delivery, ledger } = fixture();
    const result = await fabric.claim({
      workerId: "worker-a",
      registrationToken: "test-registration-token",
      queues: ["code"],
      capabilities: ["test.run"],
      waitMs: 10,
    });
    expect(result).toBeNull();
    expect(delivery.waitForWork).toHaveBeenCalledWith(["code"], 10);
    expect(ledger.claim).toHaveBeenCalledTimes(2);
  });
});
