import { describe, expect, it } from "vitest";
import { scheduleIdempotencyKey } from "../src/scheduler.js";

describe("scheduler occurrence identity", () => {
  it("is deterministic across scheduler retries and normalizes timestamps", () => {
    expect(
      scheduleIdempotencyKey("nightly-health", "2026-07-24T12:00:00+00:00"),
    ).toBe("schedule:nightly-health:2026-07-24T12:00:00.000Z");
    expect(
      scheduleIdempotencyKey("nightly-health", "2026-07-24T12:00:00Z"),
    ).toBe("schedule:nightly-health:2026-07-24T12:00:00.000Z");
  });
});
