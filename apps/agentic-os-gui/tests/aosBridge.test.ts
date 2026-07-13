import { describe, expect, it } from "vitest";
import { normalizeSnapshot, resolveAgenticOsCli } from "../src/main/aosBridge";
import { fixtureSnapshot } from "../src/shared/fixtures";
import type { OperatorState } from "../src/shared/contracts";

describe("GUI-owned session snapshot overlay", () => {
  it("finds the local Agentic OS CLI without relying on a GUI PATH", () => {
    expect(resolveAgenticOsCli(undefined, "/Users/operator", (path) => path === "/Users/operator/.local/bin/agentic-os"))
      .toBe("/Users/operator/.local/bin/agentic-os");
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
});
