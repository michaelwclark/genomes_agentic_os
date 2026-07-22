import { describe, expect, it } from "vitest";
import {
  activateTab,
  activeTab,
  closeTab,
  createWorkspaceState,
  focusGroup,
  focusedGroup,
  openConversationTab,
  openPageTab,
  splitActiveTabRight,
  visibleConversationIds,
  type WorkspaceState,
} from "../src/renderer/layout/workspaceModel";

const openThree = (): WorkspaceState => {
  let state = createWorkspaceState();
  state = openConversationTab(state, "alpha");
  state = openConversationTab(state, "beta");
  state = openConversationTab(state, "gamma");
  return state;
};

describe("workspace model", () => {
  it("starts with one empty focused primary group", () => {
    const state = createWorkspaceState();
    expect(state.groups).toEqual([{ id: "primary", tabs: [], activeKey: null }]);
    expect(state.focusedGroupId).toBe("primary");
    expect(activeTab(focusedGroup(state))).toBeUndefined();
  });

  it("opens conversations with monotonic keys and activates the newest", () => {
    const state = openThree();
    expect(state.groups[0].tabs.map((tab) => tab.key)).toEqual([1, 2, 3]);
    expect(state.groups[0].activeKey).toBe(3);
    expect(state.nextKey).toBe(4);
    expect(visibleConversationIds(state)).toEqual(["gamma"]);
  });

  it("dedupes conversations within the target group unless forced new", () => {
    let state = openThree();
    state = openConversationTab(state, "alpha");
    expect(state.groups[0].tabs).toHaveLength(3);
    expect(state.groups[0].activeKey).toBe(1);
    state = openConversationTab(state, "alpha", { forceNew: true });
    expect(state.groups[0].tabs).toHaveLength(4);
    expect(state.groups[0].activeKey).toBe(4);
  });

  it("dedupes page tabs by page id", () => {
    let state = createWorkspaceState();
    state = openPageTab(state, "execution-fabric");
    state = openConversationTab(state, "alpha");
    state = openPageTab(state, "execution-fabric");
    expect(state.groups[0].tabs).toHaveLength(2);
    expect(state.groups[0].activeKey).toBe(1);
  });

  it("keeps a neighbouring tab active when the active tab closes", () => {
    let state = openThree();
    state = activateTab(state, 2);
    state = closeTab(state, 2);
    expect(state.groups[0].tabs.map((tab) => tab.key)).toEqual([1, 3]);
    expect(state.groups[0].activeKey).toBe(3);
    state = closeTab(state, 3);
    expect(state.groups[0].activeKey).toBe(1);
  });

  it("keeps the current active tab when closing an inactive one", () => {
    let state = openThree();
    state = closeTab(state, 1);
    expect(state.groups[0].activeKey).toBe(3);
  });

  it("leaves a single empty primary group when the last tab closes", () => {
    let state = createWorkspaceState();
    state = openConversationTab(state, "alpha");
    state = closeTab(state, 1);
    expect(state.groups).toEqual([{ id: "primary", tabs: [], activeKey: null }]);
  });

  it("splits the active tab into a focused secondary group", () => {
    const state = splitActiveTabRight(openThree());
    expect(state.groups).toHaveLength(2);
    expect(state.focusedGroupId).toBe("secondary");
    const secondary = state.groups[1];
    expect(secondary.tabs).toEqual([{ key: 4, kind: "conversation", conversationId: "gamma" }]);
    expect(secondary.activeKey).toBe(4);
    expect(visibleConversationIds(state)).toEqual(["gamma"]);
  });

  it("never creates a third group; a repeat split refocuses the secondary group", () => {
    let state = splitActiveTabRight(openThree());
    state = focusGroup(state, "primary");
    state = splitActiveTabRight(state);
    expect(state.groups).toHaveLength(2);
    expect(state.focusedGroupId).toBe("secondary");
  });

  it("is a no-op when splitting with no active tab", () => {
    const state = createWorkspaceState();
    expect(splitActiveTabRight(state)).toBe(state);
  });

  it("collapses the split when the last secondary tab closes", () => {
    let state = splitActiveTabRight(openThree());
    state = closeTab(state, 4);
    expect(state.groups).toHaveLength(1);
    expect(state.groups[0].id).toBe("primary");
    expect(state.groups[0].tabs).toHaveLength(3);
    expect(state.focusedGroupId).toBe("primary");
  });

  it("promotes the secondary group when the primary empties", () => {
    let state = createWorkspaceState();
    state = openConversationTab(state, "alpha");
    state = splitActiveTabRight(state);
    state = closeTab(state, 1);
    expect(state.groups).toHaveLength(1);
    expect(state.groups[0].id).toBe("primary");
    expect(state.groups[0].tabs.map((tab) => tab.key)).toEqual([2]);
    expect(state.focusedGroupId).toBe("primary");
  });

  it("routes new opens to the focused group", () => {
    let state = splitActiveTabRight(openThree());
    state = openConversationTab(state, "delta");
    expect(state.groups[1].tabs.map((tab) => tab.key)).toEqual([4, 5]);
    state = focusGroup(state, "primary");
    state = openConversationTab(state, "epsilon");
    expect(state.groups[0].tabs).toHaveLength(4);
    expect(visibleConversationIds(state)).toEqual(["epsilon", "delta"]);
  });

  it("activating a tab focuses its owning group", () => {
    let state = splitActiveTabRight(openThree());
    state = activateTab(state, 1);
    expect(state.focusedGroupId).toBe("primary");
    expect(state.groups[0].activeKey).toBe(1);
    expect(activateTab(state, 999)).toBe(state);
  });

  it("ignores focus requests for unknown groups", () => {
    const state = createWorkspaceState();
    expect(focusGroup(state, "secondary")).toBe(state);
  });
});
