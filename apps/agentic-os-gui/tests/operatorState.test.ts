import { mkdtemp, readFile, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { OperatorStateStore } from "../src/main/operatorState";

describe("atomic operator state", () => {
  it("persists qualified pins and GUI-owned session mappings", async () => {
    const directory = await mkdtemp(join(tmpdir(), "aos-gui-state-"));
    const path = join(directory, "operator-state.json");
    const store = new OperatorStateStore(path);
    await store.setPinned("claude:local_source-id", true);
    await store.setLaunchedSession("claude:local_source-id", {
      harness: "claude",
      sessionId: "11111111-1111-4111-8111-111111111111",
      sourceConversationId: "local_source-id",
      sourceResumeId: "trusted-cli-session",
      createdAt: "2026-07-13T18:00:00Z",
      updatedAt: "2026-07-13T18:00:00Z",
    });

    const state = await store.read();
    expect(state.pinnedConversationIds).toEqual(["claude:local_source-id"]);
    expect(state.launchedSessions["claude:local_source-id"]?.sessionId).toBe("11111111-1111-4111-8111-111111111111");
    expect(JSON.parse(await readFile(path, "utf8"))).toEqual(state);
    expect((await stat(path)).mode & 0o777).toBe(0o600);
  });

  it("drops malformed legacy session mappings instead of resuming an untrusted id", async () => {
    const directory = await mkdtemp(join(tmpdir(), "aos-gui-state-"));
    const path = join(directory, "operator-state.json");
    const store = new OperatorStateStore(path);
    await store.write({
      schemaVersion: 1,
      pinnedConversationIds: [],
      routeOverrides: {},
      launchedSessions: { legacy: { harness: "claude" } as never },
    });
    expect((await store.read()).launchedSessions).toEqual({});
  });

  it("serializes concurrent read-modify-write operations", async () => {
    const directory = await mkdtemp(join(tmpdir(), "aos-gui-state-"));
    const store = new OperatorStateStore(join(directory, "operator-state.json"));
    await Promise.all([
      store.setPinned("codex:one", true),
      store.setPinned("claude:two", true),
      store.setLaunchedSession("claude:two", {
        harness: "claude",
        sessionId: "22222222-2222-4222-8222-222222222222",
        sourceConversationId: "two",
        sourceResumeId: "source-two",
        createdAt: "2026-07-13T18:00:00Z",
        updatedAt: "2026-07-13T18:00:00Z",
      }),
    ]);
    const state = await store.read();
    expect(state.pinnedConversationIds).toEqual(["claude:two", "codex:one"]);
    expect(state.launchedSessions["claude:two"]?.sourceResumeId).toBe("source-two");
  });
});
