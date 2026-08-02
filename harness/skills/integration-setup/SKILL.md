---
name: integration-setup
description: Prepare runtime integrations such as Orgo.io, Composio, AgentMail, Granola, and Genome's Notion with setup tasks, health checks, approval gates, and tracking fields.
---

# Integration Setup

Use this skill when a runtime integration must be discovered, prepared, dry-run, or diagnosed before automation uses it.

## Workflow

1. Confirm the installed OS root, defaulting to `~/agentic_os`.
2. Run `agentic-os runtime init --root <root>` if `integration-registry.yml` is missing.
3. Run `agentic-os integration list --root <root>` and identify the integration id.
4. Run `agentic-os integration setup <integration_id> --root <root> --dry-run`.
5. Run `agentic-os integration doctor <integration_id> --root <root>`.

## Required Integration Contract

Each integration record must include:

- `setup_tasks`
- `health_checks`
- `approval_gates`
- `credentials.env_vars`
- `notion_tracking`

## Guardrails

- Never print or store secret values.
- Treat missing environment variables as a setup finding, not permission to use another credential source.
- Stop before Notion writes if the active workspace is not Genome's Notion.
