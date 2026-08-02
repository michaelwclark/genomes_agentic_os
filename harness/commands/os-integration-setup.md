# os-integration-setup

Prepare approval-gated integrations for runtime use.

## Commands

```bash
agentic-os integration list --root ~/agentic_os
agentic-os integration setup granola --root ~/agentic_os --dry-run
agentic-os integration doctor granola --root ~/agentic_os
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
- Keep provider-backed setup in `planned`, `dry-run`, `blocked`, or `approval-needed` until health checks and approval gates are satisfied.
- Runtime tracking should plan `Integrations`, `Execution Targets`, `Heartbeats`, `Schedules`, `Run Queue`, `Approvals`, and `Runs`; apply only after Genome's Notion is verified.
