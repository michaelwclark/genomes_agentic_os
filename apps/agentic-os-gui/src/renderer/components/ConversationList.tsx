import { useEffect, useRef, useState, type CSSProperties } from "react";
import type { ConversationSummary, RuntimeHealth } from "../../shared/contracts";
import { compactAge, modelColor } from "../../shared/presentation";
import { ExecutionFabricView } from "./ExecutionFabricView";

interface Props {
  conversations: ConversationSummary[];
  selectedId?: string;
  query: string;
  generatedAt?: string;
  runtime: RuntimeHealth;
  onQuery(value: string): void;
  onSelect(id: string): void;
  onPin(conversation: ConversationSummary, pinned: boolean): void;
  onRefreshRuntime(): Promise<void>;
  runtimeRefreshing: boolean;
}

export function wrappedDialogFocusIndex(activeIndex: number, count: number, shift: boolean): number | undefined {
  if (count < 1) return undefined;
  if (activeIndex < 0) return shift ? count - 1 : 0;
  if (shift && activeIndex === 0) return count - 1;
  if (!shift && activeIndex === count - 1) return 0;
  return undefined;
}

export function ConversationList({ conversations, selectedId, query, generatedAt, runtime, onQuery, onSelect, onPin, onRefreshRuntime, runtimeRefreshing }: Props) {
  const [runtimeOpen, setRuntimeOpen] = useState(false);
  const detailsButton = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!runtimeOpen) return undefined;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : undefined;
    const focusable = () => Array.from(dialog.current?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ) ?? []);
    focusable()[0]?.focus();
    const containFocus = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setRuntimeOpen(false);
        return;
      }
      if (event.key !== "Tab") return;
      const targets = focusable();
      if (!targets.length) return;
      const activeIndex = targets.findIndex((target) => target === document.activeElement);
      const nextIndex = wrappedDialogFocusIndex(activeIndex, targets.length, event.shiftKey);
      if (nextIndex !== undefined) {
        event.preventDefault();
        targets[nextIndex].focus();
      }
    };
    window.addEventListener("keydown", containFocus);
    return () => {
      window.removeEventListener("keydown", containFocus);
      (previousFocus ?? detailsButton.current)?.focus();
    };
  }, [runtimeOpen]);
  return (
    <section className="conversation-list-panel" aria-label="Active conversations">
      <header className="list-header">
        <div>
          <span className="eyebrow">Active conversations</span>
          <h1>{conversations.length} in focus</h1>
        </div>
        <span className="refresh-time" title={generatedAt}>Live</span>
      </header>
      <section className="runtime-health-strip" data-status={runtime.status} aria-label={`Runtime health ${runtime.status}`}>
        <div><span className="runtime-health-dot" /><strong>{runtime.status}</strong><small>{runtime.queue_mode.replaceAll("_", " ")}</small></div>
        <dl>
          <div><dt>Queued</dt><dd>{runtime.queue_depth}</dd></div>
          <div><dt>Running</dt><dd>{runtime.running}</dd></div>
          <div><dt>Long runs</dt><dd>{runtime.long_running_active ?? 0}</dd></div>
          <div><dt>Safety attention</dt><dd>{runtime.long_running_attention ?? 0}</dd></div>
          <div><dt>Workers</dt><dd>{runtime.active_workers}</dd></div>
          <div><dt>Interactive max</dt><dd>{runtime.queue_mode === "execution_fabric" ? runtime.max_interactive_running : "legacy"}</dd></div>
          <div><dt>Failed</dt><dd>{runtime.failed + runtime.dead_letter}</dd></div>
        </dl>
        <button ref={detailsButton} type="button" className="runtime-detail-button" onClick={() => setRuntimeOpen(true)}>Details</button>
      </section>
      <label className="search-box">
        <span aria-hidden="true">⌕</span>
        <input value={query} onChange={(event) => onQuery(event.target.value)} placeholder="Search tasks, Jira, model…" />
      </label>
      <div className="conversation-scroll">
        {conversations.length === 0 ? (
          <div className="empty-state"><strong>No conversations here</strong><span>Switch scope or clear the search.</span></div>
        ) : conversations.map((conversation) => {
          const accent = modelColor(
            conversation.provider,
            conversation.model_tier ?? "unknown",
            conversation.reasoning_effort ?? "unknown",
          );
          return (
            <article
              className="conversation-card"
              data-selected={selectedId === conversation.id}
              key={`${conversation.harness}:${conversation.id}`}
              style={{ "--model-accent": accent } as CSSProperties}
            >
              <button className="conversation-main" onClick={() => onSelect(conversation.id)}>
                <span className="model-rail" />
                <span className="conversation-copy">
                  <span className="title-line">
                    <strong>{conversation.title}</strong>
                    <time dateTime={conversation.updated_at}>{compactAge(conversation.updated_at)}</time>
                  </span>
                  <span className="badge-line">
                    <span className="route-badge">{conversation.domain || "Unclassified"}</span>
                    {conversation.project && <span className="route-badge">{conversation.project}</span>}
                    <span className="model-badge">{conversation.model || conversation.provider}</span>
                    {conversation.reasoning_effort && conversation.reasoning_effort !== "unknown" && (
                      <span>{conversation.reasoning_effort}</span>
                    )}
                    <span className="runtime-status" data-status={conversation.status}>{conversation.status}</span>
                  </span>
                </span>
              </button>
              <button
                className="pin-button"
                aria-label={conversation.pinned ? `Unpin ${conversation.title}` : `Pin ${conversation.title}`}
                aria-pressed={Boolean(conversation.pinned)}
                onClick={() => onPin(conversation, !conversation.pinned)}
              >
                <span aria-hidden="true">{conversation.pinned ? "●" : "+"}</span>
                <span className="pin-label">{conversation.pinned ? "Pinned" : "Pin"}</span>
              </button>
            </article>
          );
        })}
      </div>
      {runtimeOpen && <div ref={dialog} className="fabric-overlay" role="dialog" aria-modal="true" aria-label="Execution Fabric operations">
        <button type="button" className="fabric-close" onClick={() => setRuntimeOpen(false)} aria-label="Close Execution Fabric view">×</button>
        <ExecutionFabricView runtime={runtime} onRefresh={onRefreshRuntime} refreshing={runtimeRefreshing} />
      </div>}
    </section>
  );
}
