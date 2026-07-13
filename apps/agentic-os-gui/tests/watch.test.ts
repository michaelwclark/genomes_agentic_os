import { describe, expect, it } from "vitest";
import { isRelevantWatchPath, watchTargets } from "../src/main/watch";

describe("harness source watch coverage", () => {
  it("includes the authoritative Claude Desktop session registry", () => {
    expect(watchTargets("/aos", "/Users/test")).toContain(
      "/Users/test/Library/Application Support/Claude/claude-code-sessions",
    );
  });

  it("refreshes for Claude Desktop local registry records", () => {
    expect(isRelevantWatchPath("project/local_1234-abcd.json")).toBe(true);
    expect(isRelevantWatchPath("images/icon.png")).toBe(false);
  });
});
