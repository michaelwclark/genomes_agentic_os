import { describe, expect, it, vi } from "vitest";
import { AosBridge, normalizeSnapshot, resolveAgenticOsCli } from "../src/main/aosBridge";
import { fixtureSnapshot } from "../src/shared/fixtures";
import type { GuiSnapshot, OperatorState } from "../src/shared/contracts";

describe("GUI-owned session snapshot overlay", () => {
  it("finds the local Agentic OS CLI without relying on a GUI PATH", () => {
    const runtime = "/Users/operator/Library/Application Support/AgenticOSGui/runtime/bin/agentic-os";
    expect(resolveAgenticOsCli(undefined, "/Users/operator", (path) => path === runtime)).toBe(runtime);
    expect(resolveAgenticOsCli("/custom/agentic-os", "/Users/operator", () => false)).toBe("/custom/agentic-os");
  });

  it("keeps the human Desktop conversation and overlays owned-session recency", () => {
    const source = fixtureSnapshot.conversations.find((item) => item.harness === "claude")!;
    const owned = {
      ...source,
      id: "11111111-1111-4111-8111-111111111111",
      title: "Opaque CLI fork",
      updated_at: "2026-07-13T19:00:00Z",
    };
    const state: OperatorState = {
      schemaVersion: 1,
      pinnedConversationIds: [],
      routeOverrides: {},
      launchedSessions: {
        [`claude:${source.id}`]: {
          harness: "claude",
          sessionId: owned.id,
          sourceConversationId: source.id,
          sourceResumeId: source.cli_session_id!,
          createdAt: "2026-07-13T18:30:00Z",
          updatedAt: "2026-07-13T19:00:00Z",
        },
      },
    };
    const snapshot = normalizeSnapshot(
      { ...fixtureSnapshot, conversations: [...fixtureSnapshot.conversations, owned] },
      fixtureSnapshot.root,
      state,
    );

    expect(snapshot.conversations.some((item) => item.id === owned.id)).toBe(false);
    const overlaid = snapshot.conversations.find((item) => item.id === source.id)!;
    expect(overlaid.title).toBe(source.title);
    expect(overlaid.updated_at).toBe("2026-07-13T19:00:00Z");
    expect(overlaid.metadata?.gui_owned_session_id).toBe(owned.id);
  });

  it("normalizes legacy aggregate-only runtime snapshots for the detailed view", () => {
    const { workers: _workers, tasks: _tasks, task_count: _taskCount, task_sample_count: _sampleCount, task_sample_limit: _sampleLimit, captured_at: _capturedAt, ...legacyRuntime } = fixtureSnapshot.runtime;
    const legacyQueues = legacyRuntime.queues.map(({ depth: _depth, running: _running, failed: _failed, dead_letter: _deadLetter, ...queue }) => queue);
    const state: OperatorState = { schemaVersion: 1, pinnedConversationIds: [], routeOverrides: {}, launchedSessions: {} };
    const snapshot = normalizeSnapshot(
      { ...fixtureSnapshot, runtime: { ...legacyRuntime, queues: legacyQueues } } as unknown as GuiSnapshot,
      fixtureSnapshot.root,
      state,
    );

    expect(snapshot.runtime.tasks).toEqual([]);
    expect(snapshot.runtime.workers).toEqual([]);
    expect(snapshot.runtime.task_count).toBe(0);
    expect(snapshot.runtime.task_sample_count).toBe(0);
    expect(snapshot.runtime.task_sample_limit).toBe(200);
    expect(snapshot.runtime.queues.find((queue) => queue.queue_name === "codex")?.depth).toBe(2);
  });

  it("single-flights overlapping forced snapshot refreshes", async () => {
    const state: OperatorState = { schemaVersion: 1, pinnedConversationIds: [], routeOverrides: {}, launchedSessions: {} };
    let release!: (value: OperatorState) => void;
    const readState = vi.fn(() => new Promise<OperatorState>((resolve) => { release = resolve; }));
    const bridge = new AosBridge(fixtureSnapshot.root, readState, true);

    const first = bridge.snapshot(true);
    const second = bridge.snapshot(true);
    expect(readState).toHaveBeenCalledTimes(1);
    release(state);

    await expect(first).resolves.toEqual(await second);
    expect(readState).toHaveBeenCalledTimes(1);
  });

  it("runs one trailing refresh when an unresolved snapshot is invalidated", async () => {
    const source = fixtureSnapshot.conversations[0];
    const freshState: OperatorState = {
      schemaVersion: 1,
      pinnedConversationIds: [`${source.harness}:${source.id}`],
      routeOverrides: {},
      launchedSessions: {},
    };
    const staleState: OperatorState = { schemaVersion: 1, pinnedConversationIds: [], routeOverrides: {}, launchedSessions: {} };
    let releaseFirst!: (value: OperatorState) => void;
    const readState = vi.fn()
      .mockImplementationOnce(() => new Promise<OperatorState>((resolve) => { releaseFirst = resolve; }))
      .mockResolvedValue(freshState);
    const bridge = new AosBridge(fixtureSnapshot.root, readState, true);

    const beforeInvalidation = bridge.snapshot(true);
    bridge.invalidate();
    const afterInvalidation = bridge.snapshot(true);
    releaseFirst(staleState);

    const [firstResult, secondResult] = await Promise.all([beforeInvalidation, afterInvalidation]);
    expect(readState).toHaveBeenCalledTimes(2);
    expect(firstResult.conversations.find((item) => item.id === source.id)?.pinned).toBe(true);
    expect(secondResult.conversations.find((item) => item.id === source.id)?.pinned).toBe(true);
  });
});
