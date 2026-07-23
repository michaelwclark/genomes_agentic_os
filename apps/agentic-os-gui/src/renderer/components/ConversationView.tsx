import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ConversationSummary, ConversationTranscript, StreamEvent } from "../../shared/contracts";
import { formatMessageDate } from "../../shared/presentation";
import { layoutBounds } from "../layout/layoutState";
import { Sash } from "../layout/Sash";
import { MetadataPanel } from "./MetadataPanel";

interface Props {
  conversation?: ConversationSummary;
  transcript?: ConversationTranscript;
  loading: boolean;
  streamEvents: StreamEvent[];
  sending: boolean;
  operatorLabel: string;
  showMetadata: boolean;
  railWidth: number;
  onRailResize(next: number): void;
  sendMessage(prompt: string): Promise<void>;
  cancelMessage(): Promise<void>;
  openExternal(url: string): void;
}

const roleLabel = (role: string, operatorLabel: string) => role === "user" ? operatorLabel : role === "assistant" ? "Agent" : role;

function MarkdownMessage({ content, openExternal }: { content: string; openExternal(url: string): void }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        a: ({ href, children }) => (
          <a href={href} onClick={(event) => { if (href) { event.preventDefault(); openExternal(href); } }}>{children}</a>
        ),
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

export function ConversationView({ conversation, transcript, loading, streamEvents, sending, operatorLabel, showMetadata, railWidth, onRailResize, sendMessage, cancelMessage, openExternal }: Props) {
  const [prompt, setPrompt] = useState("");
  const liveText = useMemo(
    () => streamEvents.filter((event) => event.kind === "delta" && event.content).map((event) => event.content).join(""),
    [streamEvents],
  );
  if (!conversation) {
    return <main className="no-selection"><div className="no-selection-mark">AOS</div><h2>Select a conversation</h2><p>Choose a routed task to see its transcript, linked work, and model metadata.</p></main>;
  }
  const continuationNote = conversation.continuation_note || transcript?.continuation?.note;
  const submit = async () => {
    const value = prompt.trim();
    if (!value || sending) return;
    setPrompt("");
    await sendMessage(value);
  };
  return (
    <main className="conversation-view">
      <header className="conversation-header">
        <div>
          <span className="eyebrow">{conversation.harness} · {conversation.status}</span>
          <h2>{conversation.title}</h2>
          <p>{conversation.summary || [conversation.domain, conversation.project].filter(Boolean).join(" / ")}</p>
        </div>
        <span className="header-model">{conversation.model || conversation.provider}</span>
      </header>
      <div className="conversation-content" data-metadata-visible={showMetadata}>
        <section className="transcript-panel" aria-label="Transcript">
          {continuationNote && <div className="limitation-banner"><strong>Continuation boundary</strong><span>{continuationNote}</span></div>}
          <div className="messages" aria-live="polite">
            {loading ? <div className="loading-row">Loading local transcript…</div> : transcript?.messages.length ? transcript.messages.map((message) => (
              <article className="message" data-role={message.role} key={message.id} title={formatMessageDate(message.created_at)}>
                <header className="message-header">
                  <span className="message-role">{roleLabel(message.role, operatorLabel)}</span>
                  <time dateTime={message.created_at}>{formatMessageDate(message.created_at)}</time>
                  {message.role === "assistant" && (
                    <button className="copy-message" aria-label="Copy agent message" title="Copy agent message" onClick={() => void navigator.clipboard.writeText(message.content)}>Copy</button>
                  )}
                </header>
                <div className="message-body"><MarkdownMessage content={message.content} openExternal={openExternal} /></div>
              </article>
            )) : <div className="empty-state"><strong>No transcript was returned</strong><span>The metadata remains available, or continue in the native harness.</span></div>}
            {liveText && <article className="message" data-role="assistant"><header className="message-header"><span className="message-role">Agent · live</span></header><div className="message-body"><MarkdownMessage content={liveText} openExternal={openExternal} /></div></article>}
            {streamEvents.filter((event) => event.kind === "error").map((event, index) => (
              <div className="stream-error" key={`${event.conversationId}-${index}`}><strong>Continuation failed</strong><span>{event.content}</span>{event.fallbackCommand && <code>{event.fallbackCommand}</code>}</div>
            ))}
          </div>
          <div className="composer">
            <textarea
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void submit(); }
              }}
              placeholder={conversation.can_continue === false ? "This session is read-only in Command Center" : "Continue this conversation…"}
              disabled={conversation.can_continue === false || sending}
              rows={3}
            />
            <div className="composer-foot">
              <span>{conversation.harness === "claude" && conversation.imported ? "Single-writer resume · approvals may hand off to Claude" : "Enter to send · Shift+Enter for newline"}</span>
              {sending ? (
                <button className="cancel-button" onClick={() => void cancelMessage()}>Stop</button>
              ) : (
                <button disabled={!prompt.trim() || conversation.can_continue === false} onClick={() => void submit()}>Send</button>
              )}
            </div>
          </div>
        </section>
        {showMetadata && (
          <Sash
            label="Resize linked work panel"
            value={railWidth}
            min={layoutBounds.railWidth.min}
            max={layoutBounds.railWidth.max}
            invert
            onChange={onRailResize}
            onReset={() => onRailResize(layoutBounds.railWidth.default)}
          />
        )}
        {showMetadata && <MetadataPanel conversation={conversation} onOpen={openExternal} />}
      </div>
    </main>
  );
}
