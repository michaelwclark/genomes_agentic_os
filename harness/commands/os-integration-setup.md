# os-integration-setup

Prepare approval-gated integrations for runtime use.

## Commands

```bash
agentic-os integration list --root ~/agentic_os
agentic-os integration setup granola --root ~/agentic_os --dry-run
agentic-os integration doctor granola --root ~/agentic_os
agentic-os notion track-runtime --root ~/agentic_os --dry-run
agentic-os notion track-runtime --root ~/agentic_os --apply --verified-workspace "Genome's Notion"
```

## Supported Runtime Integrations

- Orgo.io
- Composio
- AgentMail
- Granola
- Genome's Notion

## Guardrails

- Never print credential values.
- Track only credential state and required environment variable names.
- Stop if the verified Notion workspace is Michael Clark's personal Notion or any non-Genome workspace.
- Keep setup in `planned` or `dry-run` until health checks and approval gates are satisfied.
