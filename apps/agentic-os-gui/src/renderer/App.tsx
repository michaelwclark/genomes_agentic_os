import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import type { ConversationSummary, ConversationTranscript, GuiSnapshot, StreamEvent, UiConfig } from "../shared/contracts";
import { filterConversations, isActiveConversation, isArchivedConversation } from "../shared/presentation";
import { ConversationList } from "./components/ConversationList";
import { ConversationView } from "./components/ConversationView";
import { ScopeTree, type ScopeSelection } from "./components/ScopeTree";
import { layoutBounds, useLayoutState } from "./layout/layoutState";
import { Sash } from "./layout/Sash";
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
  type EditorGroup,
} from "./layout/workspaceModel";
import { pageRegistry, type PageId } from "./pages/registry";

type PaletteMode = "commands" | "search";

export function snapshotFailureIsFatal(hasSnapshot: boolean): boolean {
  return !hasSnapshot;
}

export function App() {
  const [snapshot, setSnapshot] = useState<GuiSnapshot>();
  const [uiConfig, setUiConfig] = useState<UiConfig>({ displayName: "Command Center", operatorLabel: "Operator" });
  const [scope, setScope] = useState<ScopeSelection>({ view: "active" });
  const [query, setQuery] = useState("");
  const [workspace, setWorkspace] = useState(createWorkspaceState);
  const [transcripts, setTranscripts] = useState<Record<string, ConversationTranscript | undefined>>({});
  const [transcriptLoading, setTranscriptLoading] = useState<Record<string, boolean | undefined>>({});
  const [streamEvents, setStreamEvents] = useState<StreamEvent[]>([]);
  const [leaseId, setLeaseId] = useState<string>();
  const [fatalError, setFatalError] = useState<string>();
  const [snapshotRefreshFailed, setSnapshotRefreshFailed] = useState(false);
  const [snapshotRefreshing, setSnapshotRefreshing] = useState(false);
  const [layout, updateLayout] = useLayoutState();
  const [paletteMode, setPaletteMode] = useState<PaletteMode>();
  const [paletteQuery, setPaletteQuery] = useState("");
  const snapshotRequest = useRef(0);
  const snapshotRef = useRef<GuiSnapshot | undefined>(undefined);
  const visibleIdsRef = useRef<string[]>([]);
  const groupsRef = useRef<HTMLDivElement | null>(null);

  const focusedTab = activeTab(focusedGroup(workspace));
  const selectedId = focusedTab?.kind === "conversation" ? focusedTab.conversationId : undefined;
  const refreshSnapshot = useCallback(async () => {
    const request = ++snapshotRequest.current;
    setSnapshotRefreshing(true);
    try {
      const next = await window.agenticOS.getSnapshot();
      if (request === snapshotRequest.current) {
        snapshotRef.current = next;
        setFatalError(undefined);
        setSnapshotRefreshFailed(false);
        setSnapshot(next);
      }
    } catch (error) {
      if (request === snapshotRequest.current) {
        if (snapshotFailureIsFatal(Boolean(snapshotRef.current))) setFatalError(String(error));
        else setSnapshotRefreshFailed(true);
      }
    } finally {
      if (request === snapshotRequest.current) setSnapshotRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void refreshSnapshot();
    void window.agenticOS.getUiConfig().then(setUiConfig).catch(() => undefined);
    return window.agenticOS.onSnapshotChanged((next) => {
      snapshotRequest.current += 1;
      snapshotRef.current = next;
      setFatalError(undefined);
      setSnapshotRefreshFailed(false);
      setSnapshotRefreshing(false);
      setSnapshot(next);
    });
  }, [refreshSnapshot]);
  useEffect(() => window.agenticOS.onStreamEvent((event) => {
    setStreamEvents((current) => [...current.slice(-499), event]);
    if (event.kind === "completed" || event.kind === "error") {
      setLeaseId(undefined);
      if (event.kind === "completed" && visibleIdsRef.current.includes(event.conversationId)) {
        void window.agenticOS.getTranscript(event.conversationId)
          .then((next) => setTranscripts((current) => ({ ...current, [event.conversationId]: next })))
          .catch(() => undefined);
      }
    }
  }), []);

  const openConversation = (conversationId: string, forceNew = false) =>
    setWorkspace((current) => openConversationTab(current, conversationId, { forceNew }));
  const openPage = (pageId: PageId) => setWorkspace((current) => openPageTab(current, pageId));
  const openPalette = (mode: PaletteMode) => {
    setPaletteMode(mode);
    setPaletteQuery("");
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!event.metaKey) return;
      const key = event.key.toLocaleLowerCase();
      if (key === "p") {
        event.preventDefault();
        openPalette(event.shiftKey ? "commands" : "search");
      } else if (key === "b" && !event.shiftKey) {
        event.preventDefault();
        updateLayout({ navVisible: !layout.navVisible });
      } else if (key === "u" && !event.shiftKey) {
        event.preventDefault();
        updateLayout({ railVisible: !layout.railVisible });
      } else if (key === "t" && event.shiftKey) {
        event.preventDefault();
        openPalette("search");
      } else if (key === "\\") {
        event.preventDefault();
        setWorkspace((current) => splitActiveTabRight(current));
      } else if (/^[1-9]$/.test(event.key)) {
        const tab = focusedGroup(workspace).tabs[Number(event.key) - 1];
        if (tab) {
          event.preventDefault();
          setWorkspace((current) => activateTab(current, tab.key));
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [workspace, layout, updateLayout]);

  const scopedConversations = useMemo(() => {
    const all = snapshot?.conversations ?? [];
    if (scope.view === "archive") return all.filter(isArchivedConversation);
    if (scope.view === "active") return all.filter((conversation) => isActiveConversation(conversation));
    return all.filter((conversation) => !isArchivedConversation(conversation));
  }, [snapshot, scope.view]);
  const conversations = useMemo(
    () => filterConversations(scopedConversations, { ...scope, query }),
    [scopedConversations, scope, query],
  );
  const counts = useMemo(() => {
    const all = (snapshot?.conversations ?? []).filter((conversation) => !isArchivedConversation(conversation));
    const values = new Map<string, number>([
      ["all", all.length],
      ["active", all.filter((conversation) => isActiveConversation(conversation)).length],
      ["archive", (snapshot?.conversations ?? []).filter(isArchivedConversation).length],
    ]);
    for (const conversation of scopedConversations) {
      if (conversation.domain) values.set(`domain:${conversation.domain}`, (values.get(`domain:${conversation.domain}`) ?? 0) + 1);
      if (conversation.domain && conversation.project) {
        const key = `project:${conversation.domain}:${conversation.project}`;
        values.set(key, (values.get(key) ?? 0) + 1);
      }
    }
    return values;
  }, [snapshot, scopedConversations]);

  const loadTranscript = useCallback((conversationId: string) => {
    setTranscriptLoading((current) => ({ ...current, [conversationId]: true }));
    void window.agenticOS.getTranscript(conversationId)
      .then((next) => {
        if (visibleIdsRef.current.includes(conversationId)) setTranscripts((current) => ({ ...current, [conversationId]: next }));
      })
      .catch((error) => {
        if (visibleIdsRef.current.includes(conversationId)) {
          setTranscripts((current) => ({
            ...current,
            [conversationId]: { conversation_id: conversationId, messages: [], diagnostics: [{ severity: "error", message: String(error) }] },
          }));
        }
      })
      .finally(() => {
        setTranscriptLoading((current) => conversationId in current ? { ...current, [conversationId]: false } : current);
      });
  }, []);

  const visibleIds = useMemo(() => visibleConversationIds(workspace), [workspace]);
  useEffect(() => {
    const previous = visibleIdsRef.current;
    visibleIdsRef.current = visibleIds;
    const added = visibleIds.filter((id) => !previous.includes(id));
    const removed = previous.filter((id) => !visibleIds.includes(id));
    if (removed.length > 0) {
      setTranscripts((current) => {
        const next = { ...current };
        for (const id of removed) delete next[id];
        return next;
      });
      setTranscriptLoading((current) => {
        const next = { ...current };
        for (const id of removed) delete next[id];
        return next;
      });
    }
    for (const id of added) loadTranscript(id);
  }, [visibleIds, loadTranscript]);
  useEffect(() => {
    setStreamEvents([]);
  }, [selectedId]);

  const pin = async (conversation: ConversationSummary, pinned: boolean) => {
    await window.agenticOS.setPinned(conversation.id, pinned);
  };
  const sendMessage = async (conversation: ConversationSummary, prompt: string) => {
    setStreamEvents([]);
    const result = await window.agenticOS.sendTurn({
      conversationId: conversation.id,
      harness: conversation.harness,
      prompt,
      imported: conversation.imported,
    });
    if (result.accepted) setLeaseId(result.leaseId);
    else setStreamEvents([{ conversationId: conversation.id, kind: "error", content: result.message, fallbackCommand: result.fallbackCommand }]);
  };
  const cancelMessage = async () => {
    if (!leaseId) return;
    await window.agenticOS.cancelTurn(leaseId);
  };

  const paletteConversations = useMemo(
    () => filterConversations(snapshot?.conversations ?? [], { query: paletteQuery }).slice(0, 12),
    [snapshot, paletteQuery],
  );
  const commands = [
    { label: layout.navVisible ? "Hide navigation" : "Show navigation", shortcut: "⌘B", run: () => updateLayout({ navVisible: !layout.navVisible }) },
    { label: layout.railVisible ? "Hide linked work panel" : "Show linked work panel", shortcut: "⌘U", run: () => updateLayout({ railVisible: !layout.railVisible }) },
    { label: "Open conversation in new tab", shortcut: "⇧⌘T", run: () => openPalette("search") },
    { label: "Split editor right", shortcut: "⌘\\", run: () => setWorkspace((current) => splitActiveTabRight(current)) },
    { label: "Open Execution Fabric", shortcut: "", run: () => openPage("execution-fabric") },
    { label: "Focus Active work", shortcut: "", run: () => setScope({ view: "active" }) },
    { label: "Open Archive", shortcut: "", run: () => setScope({ view: "archive" }) },
  ].filter((command) => command.label.toLocaleLowerCase().includes(paletteQuery.toLocaleLowerCase()));

  if (fatalError && !snapshot) return <div className="fatal"><strong>Command Center could not start</strong><span>{fatalError}</span><code>AOS_GUI_FIXTURE=1 pnpm dev</code></div>;
  if (!snapshot) return <div className="boot"><span className="boot-mark">AOS</span><strong>Loading the local operating system…</strong></div>;

  const shellStyle: CSSProperties = {
    "--nav-w": `${layout.navWidth}px`,
    "--list-w": `${layout.listWidth}px`,
    "--rail-w": `${layout.railWidth}px`,
  };
  const splitStyle: CSSProperties = {
    "--split-a": `${layout.centerSplitRatio}fr`,
    "--split-b": `${1 - layout.centerSplitRatio}fr`,
  };

  const renderGroup = (group: EditorGroup) => {
    const active = activeTab(group);
    const conversationTab = active?.kind === "conversation" ? active : undefined;
    const conversation = conversationTab ? snapshot.conversations.find((item) => item.id === conversationTab.conversationId) : undefined;
    return (
      <div
        className="editor-group"
        data-focused={workspace.focusedGroupId === group.id}
        onPointerDownCapture={() => setWorkspace((current) => focusGroup(current, group.id))}
      >
        <div className="workspace-tabs" role="tablist" aria-label={group.id === "primary" ? "Open tabs" : "Split tabs"}>
          {group.tabs.map((tab, index) => {
            const title = tab.kind === "conversation"
              ? snapshot.conversations.find((item) => item.id === tab.conversationId)?.title ?? "Conversation"
              : pageRegistry[tab.pageId].title;
            return (
              <div className="workspace-tab" data-active={tab.key === group.activeKey} key={tab.key}>
                <button role="tab" aria-selected={tab.key === group.activeKey} onClick={() => setWorkspace((current) => activateTab(current, tab.key))}>
                  <span className="tab-number">{index + 1}</span>
                  <span>{title}</span>
                </button>
                <button className="tab-close" aria-label={`Close ${title}`} onClick={() => setWorkspace((current) => closeTab(current, tab.key))}>×</button>
              </div>
            );
          })}
          <button className="new-tab" aria-label="Open conversation in new tab" title="Open conversation in new tab (Cmd+Shift+T)" onClick={() => { setWorkspace((current) => focusGroup(current, group.id)); openPalette("search"); }}>+</button>
        </div>
        {active?.kind === "page" ? (
          <div className="page-view">
            {pageRegistry[active.pageId].render({ runtime: snapshot.runtime, refreshRuntime: refreshSnapshot, runtimeRefreshing: snapshotRefreshing })}
          </div>
        ) : (
          <ConversationView
            conversation={conversation}
            transcript={conversationTab ? transcripts[conversationTab.conversationId] : undefined}
            loading={conversationTab ? transcriptLoading[conversationTab.conversationId] ?? transcripts[conversationTab.conversationId] === undefined : false}
            streamEvents={conversationTab ? streamEvents.filter((event) => event.conversationId === conversationTab.conversationId) : []}
            sending={Boolean(leaseId)}
            operatorLabel={uiConfig.operatorLabel}
            showMetadata={layout.railVisible}
            railWidth={layout.railWidth}
            onRailResize={(next) => updateLayout({ railWidth: next })}
            sendMessage={async (prompt) => { if (conversation) await sendMessage(conversation, prompt); }}
            cancelMessage={cancelMessage}
            openExternal={(url) => void window.agenticOS.openExternal(url)}
          />
        )}
      </div>
    );
  };

  return (
    <div className="app-shell" data-nav-visible={layout.navVisible} style={shellStyle}>
      {snapshotRefreshFailed && <div className="snapshot-warning" role="status">Snapshot refresh failed. Showing the last known state.</div>}
      {layout.navVisible && <ScopeTree displayName={uiConfig.displayName} domains={snapshot.navigation.domains} selected={scope} counts={counts} onSelect={(next) => { setScope(next); setQuery(""); }} />}
      {layout.navVisible && (
        <Sash
          label="Resize navigation"
          value={layout.navWidth}
          min={layoutBounds.navWidth.min}
          max={layoutBounds.navWidth.max}
          onChange={(next) => updateLayout({ navWidth: next })}
          onReset={() => updateLayout({ navWidth: layoutBounds.navWidth.default })}
        />
      )}
      <ConversationList
        conversations={conversations}
        selectedId={selectedId}
        query={query}
        generatedAt={snapshot.generated_at}
        runtime={snapshot.runtime}
        onQuery={setQuery}
        onSelect={(id) => openConversation(id)}
        onPin={(conversation, pinned) => void pin(conversation, pinned)}
        onOpenPage={openPage}
      />
      <Sash
        label="Resize conversation list"
        value={layout.listWidth}
        min={layoutBounds.listWidth.min}
        max={layoutBounds.listWidth.max}
        onChange={(next) => updateLayout({ listWidth: next })}
        onReset={() => updateLayout({ listWidth: layoutBounds.listWidth.default })}
      />
      <section className="workspace" aria-label="Conversation workspace">
        <div className="workspace-groups" data-split={workspace.groups.length > 1} style={splitStyle} ref={groupsRef}>
          {workspace.groups.map((group, index) => (
            <Fragment key={group.id}>
              {index > 0 && (
                <Sash
                  label="Resize editor split"
                  value={layout.centerSplitRatio}
                  min={layoutBounds.centerSplitRatio.min}
                  max={layoutBounds.centerSplitRatio.max}
                  onChange={(next) => updateLayout({ centerSplitRatio: next })}
                  onReset={() => updateLayout({ centerSplitRatio: layoutBounds.centerSplitRatio.default })}
                  getPixelsPerUnit={() => {
                    const width = groupsRef.current?.clientWidth ?? 0;
                    return width > 0 ? width : 1;
                  }}
                />
              )}
              {renderGroup(group)}
            </Fragment>
          ))}
        </div>
      </section>
      {paletteMode && (
        <div className="palette-backdrop" onMouseDown={() => setPaletteMode(undefined)}>
          <section className="command-palette" role="dialog" aria-modal="true" aria-label={paletteMode === "commands" ? "Command palette" : "Search conversations"} onMouseDown={(event) => event.stopPropagation()}>
            <label>
              <span aria-hidden="true">⌕</span>
              <input autoFocus value={paletteQuery} onChange={(event) => setPaletteQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Escape") setPaletteMode(undefined); }} placeholder={paletteMode === "commands" ? "Type a command…" : "Search every conversation…"} />
            </label>
            <div className="palette-results">
              {paletteMode === "commands" ? commands.map((command) => (
                <button key={command.label} onClick={() => { command.run(); if (command.label !== "Open conversation in new tab") setPaletteMode(undefined); }}>
                  <span>{command.label}</span><kbd>{command.shortcut}</kbd>
                </button>
              )) : paletteConversations.map((conversation) => (
                <button key={`${conversation.harness}:${conversation.id}`} onClick={() => { openConversation(conversation.id, true); setPaletteMode(undefined); }}>
                  <span><strong>{conversation.title}</strong><small>{[conversation.domain, conversation.project].filter(Boolean).join(" / ") || "Unclassified"}</small></span>
                  <kbd>New tab</kbd>
                </button>
              ))}
            </div>
            <footer>{paletteMode === "commands" ? "Command Center" : "Results always open in a new tab"}<kbd>esc</kbd></footer>
          </section>
        </div>
      )}
    </div>
  );
}
