# Tools

List the visible capabilities intended for this layer.

## Skills

| Skill | Use When | Source |
| --- | --- | --- |
|  |  |  |

## Commands

| Command | Use When | Notes |
| --- | --- | --- |
|  |  |  |

## MCP Servers

| Config ID | Server | Use When | Install Status | Boundary |
| --- | --- | --- | --- | --- |
| `notion` | Notion | Notion control-plane reads and approved writes. | installed at every layer | Verify the intended control-plane workspace before writing. |
| `genomes_brain` | Genome's Brain | Durable cross-session memory reads and non-secret writes. | installed at every layer | No secrets; use project rules and memory policy before writing. |
| `github` | GitHub | GitHub repository, issue, pull request, and code-hosting work. | installed at every layer | Use least-privilege `GITHUB_PAT_TOKEN`; never commit or print token values. |
| `context_mode` | Context Mode | Large-file, repo, and session-memory analysis without flooding prompt context. | installed at every layer | Use for analysis and retrieval; do not use context-mode subprocesses for file writes. |
| `sentry` | Sentry | Error, trace, release, and production incident investigation. | visible; domain-gated via mcp-domain-gating registry | Production/customer-visible changes still require approval. |
| `datadog` | Datadog | Observability, logs, metrics, traces, and monitor investigation. | visible; domain-gated via mcp-domain-gating registry | Do not expose customer data outside approved observability workflows. |
| `supabase` | Supabase | Supabase project work in domains that opt in. | visible; domain-gated via mcp-domain-gating registry | Install only in layers the gating registry approves. |
| `composio` | Composio | Federated SaaS tools, OAuth flows, triggers, and app actions. | visible; endpoint approval required | Install only after generating an approved Composio MCP server URL for the target layer. |
| `orgo` | Orgo.io | Isolated cloud desktop and computer-use execution targets. | visible; bridge approval required | Install only through an approved Orgo MCP bridge or runtime execution target. |
| `playwright` | Playwright | Browser automation and UI validation workflows. | visible; opt in for browser automation layers | Add to config only in layers that explicitly own browser automation. |

## Composio Tool Routes

| Route ID | Toolkit | Use When | Layers | Provider Order | Known Tools | Boundary |
| --- | --- | --- | --- | --- | --- | --- |
| `agentmail_genome` | `agent_mail` | Inbox reads, message lookup, and approved agent email sends. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `composio` -> `agentmail_api` -> `direct_api` | read: `AGENT_MAIL_LIST_INBOXES`, `AGENT_MAIL_LIST_MESSAGES`, `AGENT_MAIL_GET_MESSAGE`; write: `AGENT_MAIL_SEND_EMAIL` | Use for Genome AgentMail only; sending email requires explicit approval. |
| `slack_genome` | `slack` | Slack context lookup, DM/channel routing, and approved Slack notifications. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `composio` -> `slack_mcp` -> `slack_connector` -> `direct_api` | write: `SLACK_OPEN_DM`, `SLACK_SEND_MESSAGE` | Verify Genome Slack workspace and channel/user target before sending. |
| `notion_blocks` | `notion` | Fallback block-content reads when the Notion MCP/connector cannot fetch the needed page blocks. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `notion_mcp` -> `notion_connector` -> `composio` -> `direct_api` | read: `NOTION_FETCH_ALL_BLOCK_CONTENTS` | Prefer Notion MCP; verify Genome's Notion before any Notion write path. |
| `jira_genome` | `jira` | Jira issue/project reads and approved issue creation or updates. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `composio` -> `jira_mcp` -> `jira_connector` -> `direct_api` | discover with `composio tools list <toolkit>` | Use the configured Genome Jira workspace; writes require ticket-scope approval. |
| `linear_genome` | `linear` | Linear issue/team reads and approved issue creation or updates. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `composio` -> `linear_mcp` -> `linear_connector` -> `direct_api` | discover with `composio tools list <toolkit>` | Use only for Genome Linear routes; external writes require approval. |
| `email_genome` | `gmail` | Email search/read and approved outbound mail. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `composio` -> `gmail_mcp` -> `email_connector` -> `direct_api` | discover with `composio tools list <toolkit>` | Read only by default; sending mail requires explicit approval and recipient verification. |
| `github_genome` | `github` | GitHub issue, pull request, repo, and code-hosting actions when MCP/gh are unavailable or Composio is the approved route. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `github_mcp` -> `github_cli` -> `composio` -> `direct_api` | discover with `composio tools list <toolkit>` | Prefer GitHub MCP or gh for repo work; writes require repo/PR/issue scope verification. |
| `granola_local` | `granola` | Meeting-note lookup and approved notes ingestion when a Granola integration is configured. | agentic_os_root, domain_or_lane, project, workflow_or_task | `composio` -> `granola_local` -> `direct_api` | discover with `composio tools list <toolkit>` | Read-only by default; do not expose private notes into customer-visible output without approval. |
| `composio_discovery` | `composio` | Unknown slug discovery, schema inspection, dry-run validation, proxy fallback, and multi-tool scripting. | agentic_os_root, domain_or_lane, project, workflow_or_task, automation | `composio_cli` | read: `composio search`, `composio tools list`, `composio tools info`, `composio execute --get-schema`, `composio execute --dry-run`, `composio proxy`, `composio run --dry-run` | Use execute before search when a slug is known; link accounts only after confirming the target toolkit/workspace. |

## Plugins And Libraries

| Name | Use When | Notes |
| --- | --- | --- |
|  |  |  |

## Local Wrappers

| Wrapper | Use When | Notes |
| --- | --- | --- |
| `harness/bin/agentic-os-notify` | A watcher, automation, or agent-side helper has a bounded attention signal for the operator. | Native macOS Notification Center delivery with severity, quiet hours, source policy, durable local history, 48-hour retention, and anti-flood controls. Do not use it for routine progress narration. |

## When To Use What

-

## Missing Or Disabled

-
