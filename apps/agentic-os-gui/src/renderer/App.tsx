import { useEffect, useMemo, useState } from "react";
import type { ConversationSummary, ConversationTranscript, GuiSnapshot, StreamEvent } from "../shared/contracts";
import { filterConversations } from "../shared/presentation";
import { ConversationList } from "./components/ConversationList";
import { ConversationView } from "./components/ConversationView";
import { ScopeTree, type ScopeSelection } from "./components/ScopeTree";

export function App() {
  const [snapshot, setSnapshot] = useState<GuiSnapshot>();
  const [scope, setScope] = useState<ScopeSelection>({});
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string>();
  const [transcript, setTranscript] = useState<ConversationTranscript>();
  const [transcriptLoading, setTranscriptLoading] = useState(false);
  const [streamEvents, setStreamEvents] = useState<StreamEvent[]>([]);
  const [leaseId, setLeaseId] = useState<string>();
  const [fatalError, setFatalError] = useState<string>();

  useEffect(() => {
    void window.agenticOS.getSnapshot().then(setSnapshot).catch((error) => setFatalError(String(error)));
    return window.agenticOS.onSnapshotChanged(setSnapshot);
  }, []);
  useEffect(() => window.agenticOS.onStreamEvent((event) => {
    setStreamEvents((current) => [...current.slice(-499), event]);
    if (event.kind === "completed" || event.kind === "error") {
      setLeaseId(undefined);
      if (event.kind === "completed" && event.conversationId === selectedId) {
        void window.agenticOS.getTranscript(event.conversationId).then(setTranscript).catch(() => undefined);
      }
    }
  }), [selectedId]);

  const conversations = useMemo(
    () => filterConversations(snapshot?.conversations ?? [], { ...scope, query }),
    [snapshot, scope, query],
  );
  const selected = snapshot?.conversations.find((item) => item.id === selectedId);
  const counts = useMemo(() => {
    const values = new Map<string, number>([["all", snapshot?.conversations.length ?? 0]]);
    for (const conversation of snapshot?.conversations ?? []) {
      if (conversation.domain) values.set(`domain:${conversation.domain}`, (values.get(`domain:${conversation.domain}`) ?? 0) + 1);
      if (conversation.domain && conversation.project) {
        const key = `project:${conversation.domain}:${conversation.project}`;
        values.set(key, (values.get(key) ?? 0) + 1);
      }
    }
    return values;
  }, [snapshot]);

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

  if (fatalError) return <div className="fatal"><strong>AgenticOSGui could not start</strong><span>{fatalError}</span><code>AOS_GUI_FIXTURE=1 pnpm dev</code></div>;
  if (!snapshot) return <div className="boot"><span className="boot-mark">AOS</span><strong>Loading the local operating system…</strong></div>;

  return (
    <div className="app-shell">
      <ScopeTree domains={snapshot.navigation.domains} selected={scope} counts={counts} onSelect={(next) => { setScope(next); setQuery(""); }} />
      <ConversationList
        conversations={conversations}
        selectedId={selectedId}
        query={query}
        generatedAt={snapshot.generated_at}
        onQuery={setQuery}
        onSelect={setSelectedId}
        onPin={(conversation, pinned) => void pin(conversation, pinned)}
      />
      <ConversationView
        conversation={selected}
        transcript={transcript}
        loading={transcriptLoading}
        streamEvents={streamEvents.filter((event) => event.conversationId === selectedId)}
        sending={Boolean(leaseId)}
        sendMessage={sendMessage}
        cancelMessage={cancelMessage}
        openExternal={(url) => void window.agenticOS.openExternal(url)}
      />
    </div>
  );
}
