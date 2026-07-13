import type { ReactNode } from "react";
import type { ConversationSummary } from "../../shared/contracts";

interface Props {
  conversation: ConversationSummary;
  onOpen(url: string): void;
}

function MetadataSection({ title, children }: { title: string; children: ReactNode }) {
  return <section className="metadata-section"><h3>{title}</h3>{children}</section>;
}

export function MetadataPanel({ conversation, onOpen }: Props) {
  const hasLinks = Boolean(
    conversation.jira_keys?.length || conversation.jira_issues?.length || conversation.linear_issues?.length ||
      conversation.pull_requests?.length || conversation.slack_threads?.length,
  );
  const linkedJiraKeys = new Set(conversation.jira_issues?.map((issue) => issue.key) ?? []);
  const openWorkItem = (action: "vscode" | "finder") => {
    void window.agenticOS.openLocalTarget(conversation.id, "work-item", action);
  };
  return (
    <aside className="metadata-panel" aria-label="Conversation metadata">
      <MetadataSection title="Route">
        <dl>
          <div><dt>Domain</dt><dd>{conversation.domain || "Unclassified"}</dd></div>
          <div><dt>Project</dt><dd>{conversation.project || "Unclassified"}</dd></div>
          <div><dt>Work item</dt><dd>{conversation.work_item || "—"}</dd></div>
          <div><dt>Branch</dt><dd>{conversation.git?.branch || "—"}</dd></div>
        </dl>
      </MetadataSection>
      <MetadataSection title="Model route">
        <dl>
          <div><dt>Provider</dt><dd>{conversation.provider}</dd></div>
          <div><dt>Model</dt><dd>{conversation.model || "Unknown"}</dd></div>
          <div><dt>Tier</dt><dd>{conversation.model_tier || "Unknown"}</dd></div>
          <div><dt>Effort</dt><dd>{conversation.reasoning_effort || "Unknown"}</dd></div>
        </dl>
      </MetadataSection>
      {conversation.work_item && <MetadataSection title="Work item actions">
        <div className="link-stack">
          <button type="button" onClick={() => openWorkItem("vscode")}>Open in VS Code<span>↗</span></button>
          <button type="button" onClick={() => openWorkItem("finder")}>Reveal in Finder<span>↗</span></button>
        </div>
      </MetadataSection>}
      {hasLinks && <MetadataSection title="Linked work">
        <div className="link-stack">
          {conversation.pull_requests?.map((pr) => (
            <button type="button" key={pr.url} onClick={() => onOpen(pr.url)}>PR {pr.number ? `#${pr.number}` : pr.repo || "link"}<span>↗</span></button>
          ))}
          {conversation.jira_issues?.map((issue) => (
            <button type="button" key={issue.url} title={issue.title} onClick={() => onOpen(issue.url)}>{issue.key}<span>↗</span></button>
          ))}
          {conversation.jira_keys?.filter((key) => !linkedJiraKeys.has(key)).map((key) => (
            <span className="metadata-chip" key={key} title="No Jira URL was captured for this reference">{key}</span>
          ))}
          {conversation.linear_issues?.map((issue) => (
            <button type="button" key={issue.url} title={issue.title} onClick={() => onOpen(issue.url)}>{issue.key}<span>↗</span></button>
          ))}
          {conversation.slack_threads?.map((url) => (
            <button type="button" key={url} onClick={() => onOpen(url)}>Slack thread<span>↗</span></button>
          ))}
        </div>
      </MetadataSection>}
      {conversation.assets?.length ? <MetadataSection title="Filesystem assets">
        <div className="asset-stack">
          {conversation.assets.map((asset) => <div key={asset.path}><strong>{asset.label}</strong><span>{asset.path}</span></div>)}
        </div>
      </MetadataSection> : null}
      <MetadataSection title="Harness">
        <dl>
          <div><dt>Surface</dt><dd>{conversation.harness}</dd></div>
          <div><dt>Conversation ID</dt><dd className="mono truncate" title={conversation.id}>{conversation.id}</dd></div>
          <div><dt>Working folder</dt><dd className="mono truncate" title={conversation.cwd}>{conversation.cwd || "—"}</dd></div>
        </dl>
      </MetadataSection>
    </aside>
  );
}
