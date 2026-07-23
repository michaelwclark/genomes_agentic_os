/**
 * Contract test: vitest
 * Validates the API surface used by this project.
 *
 * Usage across tests/: describe/it/expect/afterEach, vi.fn, vi.useFakeTimers,
 * vi.advanceTimersByTime, vi.useRealTimers; vitest/config defineConfig drives
 * vitest.contracts.config.ts.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { defineConfig } from "vitest/config";

describe("vitest contract", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("core test primitives are functions", () => {
    for (const primitive of [describe, it, expect, afterEach]) {
      expect(typeof primitive).toBe("function");
    }
  });

  it("vi.fn records calls and returns configured values", () => {
    const mocked = vi.fn(() => "value");
    expect(mocked()).toBe("value");
    expect(mocked).toHaveBeenCalledTimes(1);
  });

  it("fake timers advance as tests/watch.test.ts relies on", () => {
    vi.useFakeTimers();
    const tick = vi.fn();
    setTimeout(tick, 1_000);
    vi.advanceTimersByTime(1_000);
    expect(tick).toHaveBeenCalledTimes(1);
  });

  it("vitest/config defineConfig returns the config object", () => {
    const config = defineConfig({ test: { environment: "node" } });
    expect(config).toBeTypeOf("object");
    expect((config as { test?: { environment?: string } }).test?.environment).toBe("node");
  });
});
