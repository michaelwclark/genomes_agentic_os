import { describe, expect, it } from "vitest";
import {
  compactAge,
  filterConversations,
  formatMessageDate,
  isActiveConversation,
  modelColor,
} from "../src/shared/presentation";
import { fixtureSnapshot } from "../src/shared/fixtures";

describe("conversation presentation", () => {
  const now = Date.parse("2026-07-13T18:00:00Z");

  it.each([
    ["2026-07-13T17:59:45Z", "now"],
    ["2026-07-13T17:15:00Z", "45m"],
    ["2026-07-13T13:00:00Z", "5h"],
    ["2026-07-12T18:00:00Z", "1d"],
    ["2026-07-06T18:00:00Z", "1w"],
  ])("formats %s as %s", (timestamp, expected) => {
    expect(compactAge(timestamp, now)).toBe(expected);
  });

  it("filters by first-class domain/project and searches linked Jira keys", () => {
    expect(filterConversations(fixtureSnapshot.conversations, { domain: "engineering" })).toHaveLength(1);
    expect(filterConversations(fixtureSnapshot.conversations, { project: "client_portal" })[0]?.title).toContain("Client portal");
    expect(filterConversations(fixtureSnapshot.conversations, { query: "ACME-2044" })[0]?.harness).toBe("claude");
  });

  it("sorts pinned conversations first and makes higher complexity brighter", () => {
    expect(filterConversations(fixtureSnapshot.conversations, {})[0]?.pinned).toBe(true);
    expect(modelColor("openai", "economy", "low")).not.toBe(modelColor("openai", "frontier_max", "ultra"));
    expect(modelColor("openai", "frontier", "high")).not.toBe(modelColor("anthropic", "frontier", "high"));
  });

  it("treats pinned or recently updated conversations as active", () => {
    const recent = { ...fixtureSnapshot.conversations[0], pinned: false, updated_at: "2026-07-13T17:00:00Z" };
    const stale = { ...recent, updated_at: "2026-07-12T16:00:00Z" };
    const pinned = { ...stale, pinned: true };
    const archived = { ...recent, status: "archived", pinned: true };

    expect(isActiveConversation(recent, now)).toBe(true);
    expect(isActiveConversation(stale, now)).toBe(false);
    expect(isActiveConversation(pinned, now)).toBe(true);
    expect(isActiveConversation(archived, now)).toBe(false);
  });

  it("formats transcript timestamps for hover labels", () => {
    expect(formatMessageDate("2026-07-13T18:05:00Z")).toMatch(/^13\/07 \d{2}:\d{2} (am|pm)$/);
    expect(formatMessageDate()).toBe("Time unavailable");
  });
});
