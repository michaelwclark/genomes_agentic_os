import type { CSSProperties } from "react";
import type { ConversationSummary } from "../../shared/contracts";
import { compactAge, modelColor } from "../../shared/presentation";

interface Props {
  conversations: ConversationSummary[];
  selectedId?: string;
  query: string;
  generatedAt?: string;
  onQuery(value: string): void;
  onSelect(id: string): void;
  onPin(conversation: ConversationSummary, pinned: boolean): void;
}

export function ConversationList({ conversations, selectedId, query, generatedAt, onQuery, onSelect, onPin }: Props) {
  return (
    <section className="conversation-list-panel" aria-label="Active conversations">
      <header className="list-header">
        <div>
          <span className="eyebrow">Active conversations</span>
          <h1>{conversations.length} in focus</h1>
        </div>
        <span className="refresh-time" title={generatedAt}>Live</span>
      </header>
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
    </section>
  );
}
