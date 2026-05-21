# Spec

## Scope

- Install runtime templates, runtime commands, runtime skills, and the feature plan into shared knowledge.
- Create local runtime state under `shared_factory/00-control-plane/`.
- Create heartbeat dry-run logs under `shared_factory/06-runs-and-logs/heartbeats/`.
- Queue schedules and heartbeats without executing external provider effects.
- Represent Orgo.io, Composio, AgentMail, Granola, and Notion setup readiness.
- Plan and apply local Notion runtime tracking records only after Genome's Notion workspace verification.

## Out Of Scope

- Live Orgo.io desktop execution.
- Live Composio tool execution.
- Live AgentMail sends.
- Direct Granola transcript extraction.
- Direct Notion API writes.

## Acceptance Criteria

- Runtime knowledge installs and validates.
- Runtime registries represent the required execution targets and integrations.
- Heartbeats can be listed and dry-run with a written log.
- Schedules can be created and dry-run into the run queue.
- Integration setup and doctor paths expose setup tasks, health checks, approval gates, and credential state.
- Notion runtime tracking has dry-run and apply flows with workspace verification.
