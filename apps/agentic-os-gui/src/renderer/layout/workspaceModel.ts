import type { PageId } from "../pages/registry";

export type WorkspaceTab =
  | { key: number; kind: "conversation"; conversationId: string }
  | { key: number; kind: "page"; pageId: PageId };

export type EditorGroupId = "primary" | "secondary";

export interface EditorGroup {
  id: EditorGroupId;
  tabs: WorkspaceTab[];
  activeKey: number | null;
}

export interface WorkspaceState {
  groups: EditorGroup[];
  focusedGroupId: EditorGroupId;
  nextKey: number;
}

export function createWorkspaceState(): WorkspaceState {
  return { groups: [{ id: "primary", tabs: [], activeKey: null }], focusedGroupId: "primary", nextKey: 1 };
}

export function focusedGroup(state: WorkspaceState): EditorGroup {
  return state.groups.find((group) => group.id === state.focusedGroupId) ?? state.groups[0];
}

export function activeTab(group: EditorGroup): WorkspaceTab | undefined {
  return group.tabs.find((tab) => tab.key === group.activeKey);
}

/** Conversation ids currently visible as an active tab in some group, primary first, deduped. */
export function visibleConversationIds(state: WorkspaceState): string[] {
  const ids: string[] = [];
  for (const group of state.groups) {
    const tab = activeTab(group);
    if (tab?.kind === "conversation" && !ids.includes(tab.conversationId)) ids.push(tab.conversationId);
  }
  return ids;
}

const replaceGroup = (state: WorkspaceState, group: EditorGroup): WorkspaceState => ({
  ...state,
  groups: state.groups.map((current) => current.id === group.id ? group : current),
});

const appendTab = (state: WorkspaceState, tab: WorkspaceTab): WorkspaceState => {
  const group = focusedGroup(state);
  return {
    ...replaceGroup(state, { ...group, tabs: [...group.tabs, tab], activeKey: tab.key }),
    nextKey: state.nextKey + 1,
  };
};

export function openConversationTab(state: WorkspaceState, conversationId: string, options: { forceNew?: boolean } = {}): WorkspaceState {
  const group = focusedGroup(state);
  if (!options.forceNew) {
    const existing = group.tabs.find((tab) => tab.kind === "conversation" && tab.conversationId === conversationId);
    if (existing) return replaceGroup(state, { ...group, activeKey: existing.key });
  }
  return appendTab(state, { key: state.nextKey, kind: "conversation", conversationId });
}

export function openPageTab(state: WorkspaceState, pageId: PageId): WorkspaceState {
  const group = focusedGroup(state);
  const existing = group.tabs.find((tab) => tab.kind === "page" && tab.pageId === pageId);
  if (existing) return replaceGroup(state, { ...group, activeKey: existing.key });
  return appendTab(state, { key: state.nextKey, kind: "page", pageId });
}

export function closeTab(state: WorkspaceState, key: number): WorkspaceState {
  const group = state.groups.find((current) => current.tabs.some((tab) => tab.key === key));
  if (!group) return state;
  const index = group.tabs.findIndex((tab) => tab.key === key);
  const tabs = group.tabs.filter((tab) => tab.key !== key);
  const nextActive = tabs.length === 0 ? null : tabs[Math.min(index, tabs.length - 1)].key;
  const updated: EditorGroup = { ...group, tabs, activeKey: group.activeKey === key ? nextActive : group.activeKey };
  if (tabs.length > 0 || state.groups.length === 1) return replaceGroup(state, updated);
  // The emptied group collapses the split; the surviving group carries on as primary.
  const survivor = state.groups.find((current) => current.id !== group.id);
  if (!survivor) return replaceGroup(state, updated);
  return { ...state, groups: [{ ...survivor, id: "primary" }], focusedGroupId: "primary" };
}

export function splitActiveTabRight(state: WorkspaceState): WorkspaceState {
  if (state.groups.some((group) => group.id === "secondary")) return { ...state, focusedGroupId: "secondary" };
  const group = focusedGroup(state);
  const active = activeTab(group);
  if (!active) return state;
  const copy: WorkspaceTab = { ...active, key: state.nextKey };
  const secondary: EditorGroup = { id: "secondary", tabs: [copy], activeKey: copy.key };
  return { ...state, groups: [...state.groups, secondary], focusedGroupId: "secondary", nextKey: state.nextKey + 1 };
}

export function focusGroup(state: WorkspaceState, id: EditorGroupId): WorkspaceState {
  if (state.focusedGroupId === id || !state.groups.some((group) => group.id === id)) return state;
  return { ...state, focusedGroupId: id };
}

export function activateTab(state: WorkspaceState, key: number): WorkspaceState {
  const group = state.groups.find((current) => current.tabs.some((tab) => tab.key === key));
  if (!group) return state;
  return { ...replaceGroup(state, { ...group, activeKey: key }), focusedGroupId: group.id };
}
