import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ConversationSummary, ConversationTranscript, GuiSnapshot, StreamEvent, UiConfig } from "../shared/contracts";
import { filterConversations, isActiveConversation, isArchivedConversation } from "../shared/presentation";
import { ConversationList } from "./components/ConversationList";
import { ConversationView } from "./components/ConversationView";
import { ScopeTree, type ScopeSelection } from "./components/ScopeTree";

interface WorkspaceTab {
  key: number;
  conversationId: string;
}

type PaletteMode = "commands" | "search";

export function snapshotFailureIsFatal(hasSnapshot: boolean): boolean {
  return !hasSnapshot;
}

export function App() {
  const [snapshot, setSnapshot] = useState<GuiSnapshot>();
  const [uiConfig, setUiConfig] = useState<UiConfig>({ displayName: "Command Center", operatorLabel: "Operator" });
  const [scope, setScope] = useState<ScopeSelection>({ view: "active" });
  const [query, setQuery] = useState("");
  const [tabs, setTabs] = useState<WorkspaceTab[]>([]);
  const [selectedTabKey, setSelectedTabKey] = useState<number>();
  const [transcript, setTranscript] = useState<ConversationTranscript>();
  const [transcriptLoading, setTranscriptLoading] = useState(false);
  const [streamEvents, setStreamEvents] = useState<StreamEvent[]>([]);
  const [leaseId, setLeaseId] = useState<string>();
  const [fatalError, setFatalError] = useState<string>();
  const [snapshotRefreshFailed, setSnapshotRefreshFailed] = useState(false);
  const [snapshotRefreshing, setSnapshotRefreshing] = useState(false);
  const [navVisible, setNavVisible] = useState(true);
  const [metadataVisible, setMetadataVisible] = useState(true);
  const [paletteMode, setPaletteMode] = useState<PaletteMode>();
  const [paletteQuery, setPaletteQuery] = useState("");
  const nextTabKey = useRef(1);
  const snapshotRequest = useRef(0);
  const snapshotRef = useRef<GuiSnapshot | undefined>(undefined);

  const selectedId = tabs.find((tab) => tab.key === selectedTabKey)?.conversationId;
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
      if (event.kind === "completed" && event.conversationId === selectedId) {
        void window.agenticOS.getTranscript(event.conversationId).then(setTranscript).catch(() => undefined);
      }
    }
  }), [selectedId]);

  const openTab = (conversationId: string, forceNew = false) => {
    const existing = forceNew ? undefined : tabs.find((tab) => tab.conversationId === conversationId);
    if (existing) {
      setSelectedTabKey(existing.key);
      return;
    }
    const tab = { key: nextTabKey.current++, conversationId };
    setTabs((current) => [...current, tab]);
    setSelectedTabKey(tab.key);
  };
  const closeTab = (key: number) => {
    setTabs((current) => {
      const index = current.findIndex((tab) => tab.key === key);
      const next = current.filter((tab) => tab.key !== key);
      if (key === selectedTabKey) setSelectedTabKey(next[Math.min(index, next.length - 1)]?.key);
      return next;
    });
  };
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
        setNavVisible((visible) => !visible);
      } else if (key === "u" && !event.shiftKey) {
        event.preventDefault();
        setMetadataVisible((visible) => !visible);
      } else if (key === "t" && event.shiftKey) {
        event.preventDefault();
        openPalette("search");
      } else if (/^[1-9]$/.test(event.key)) {
        const tab = tabs[Number(event.key) - 1];
        if (tab) {
          event.preventDefault();
          setSelectedTabKey(tab.key);
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [tabs]);

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
  const selected = snapshot?.conversations.find((item) => item.id === selectedId);
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

  useEffect(() => {
    if (!selectedId) { setTranscript(undefined); return; }
    setTranscriptLoading(true);
    setStreamEvents([]);
    void window.agenticOS.getTranscript(selectedId)
      .then(setTranscript)
      .catch((error) => setTranscript({ conversation_id: selectedId, messages: [], diagnostics: [{ severity: "error", message: String(error) }] }))
      .finally(() => setTranscriptLoading(false));
  }, [selectedId]);

  const pin = async (conversation: ConversationSummary, pinned: boolean) => {
    await window.agenticOS.setPinned(conversation.id, pinned);
  };
  const sendMessage = async (prompt: string) => {
    if (!selected) return;
    setStreamEvents([]);
    const result = await window.agenticOS.sendTurn({
      conversationId: selected.id,
      harness: selected.harness,
      prompt,
      imported: selected.imported,
    });
    if (result.accepted) setLeaseId(result.leaseId);
    else setStreamEvents([{ conversationId: selected.id, kind: "error", content: result.message, fallbackCommand: result.fallbackCommand }]);
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
    { label: navVisible ? "Hide navigation" : "Show navigation", shortcut: "⌘B", run: () => setNavVisible((visible) => !visible) },
    { label: metadataVisible ? "Hide linked work panel" : "Show linked work panel", shortcut: "⌘U", run: () => setMetadataVisible((visible) => !visible) },
    { label: "Open conversation in new tab", shortcut: "⇧⌘T", run: () => openPalette("search") },
    { label: "Focus Active work", shortcut: "", run: () => setScope({ view: "active" }) },
    { label: "Open Archive", shortcut: "", run: () => setScope({ view: "archive" }) },
  ].filter((command) => command.label.toLocaleLowerCase().includes(paletteQuery.toLocaleLowerCase()));

  if (fatalError && !snapshot) return <div className="fatal"><strong>Command Center could not start</strong><span>{fatalError}</span><code>AOS_GUI_FIXTURE=1 pnpm dev</code></div>;
  if (!snapshot) return <div className="boot"><span className="boot-mark">AOS</span><strong>Loading the local operating system…</strong></div>;

  return (
    <div className="app-shell" data-nav-visible={navVisible}>
      {snapshotRefreshFailed && <div className="snapshot-warning" role="status">Snapshot refresh failed. Showing the last known state.</div>}
      {navVisible && <ScopeTree displayName={uiConfig.displayName} domains={snapshot.navigation.domains} selected={scope} counts={counts} onSelect={(next) => { setScope(next); setQuery(""); }} />}
      <ConversationList
        conversations={conversations}
        selectedId={selectedId}
        query={query}
        generatedAt={snapshot.generated_at}
        runtime={snapshot.runtime}
        onQuery={setQuery}
        onSelect={(id) => openTab(id)}
        onPin={(conversation, pinned) => void pin(conversation, pinned)}
        onRefreshRuntime={refreshSnapshot}
        runtimeRefreshing={snapshotRefreshing}
      />
      <section className="workspace" aria-label="Conversation workspace">
        <div className="workspace-tabs" role="tablist" aria-label="Open conversations">
          {tabs.map((tab, index) => {
            const conversation = snapshot.conversations.find((item) => item.id === tab.conversationId);
            return (
              <div className="workspace-tab" data-active={tab.key === selectedTabKey} key={tab.key}>
                <button role="tab" aria-selected={tab.key === selectedTabKey} onClick={() => setSelectedTabKey(tab.key)}>
                  <span className="tab-number">{index + 1}</span>
                  <span>{conversation?.title ?? "Conversation"}</span>
                </button>
                <button className="tab-close" aria-label={`Close ${conversation?.title ?? "conversation"}`} onClick={() => closeTab(tab.key)}>×</button>
              </div>
            );
          })}
          <button className="new-tab" aria-label="Open conversation in new tab" title="Open conversation in new tab (Cmd+Shift+T)" onClick={() => openPalette("search")}>+</button>
        </div>
        <ConversationView
          conversation={selected}
          transcript={transcript}
          loading={transcriptLoading}
          streamEvents={streamEvents.filter((event) => event.conversationId === selectedId)}
          sending={Boolean(leaseId)}
          operatorLabel={uiConfig.operatorLabel}
          showMetadata={metadataVisible}
          sendMessage={sendMessage}
          cancelMessage={cancelMessage}
          openExternal={(url) => void window.agenticOS.openExternal(url)}
        />
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
                <button key={`${conversation.harness}:${conversation.id}`} onClick={() => { openTab(conversation.id, true); setPaletteMode(undefined); }}>
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
