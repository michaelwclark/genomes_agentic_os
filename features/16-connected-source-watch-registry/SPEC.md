# Spec

Add a provider-agnostic connected source watch registry for Agentic OS installs.

## Scope

- Connected systems define provider priority, credentials references, workspace verification, permissions, approval gates, and health checks.
- Watch sources define source type, external reference, cadence, cursor, dedupe key, route, and output paths.
- Dry-run polling emits normalized source events without reading external systems.
- Apply mode writes local source event files and cursor state.

## Out Of Scope

- Live Slack, Jira, Notion, GitHub, Granola, AgentMail, or Composio reads.
- Webhook servers or provider triggers.
- Database-backed concurrent processing.
