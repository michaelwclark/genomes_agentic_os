# Harness Bin

Executable wrappers owned by the installed Agentic OS harness.

## Package entrypoints

- `agentic-os` — Python package console entrypoint for the full CLI.
- `aos` — Short alias for the same CLI.
- `context-mode` — Expected at `/Users/genome/.local/bin/context-mode`.
- `agentic-os-context-mode` — Local context-mode status and kill-switch wrapper.

## Scripts in this directory

| Script | Description |
|---|---|
| `agentic-os-automation-run-summary` | Replace an automation's Notion last-run summary page after each run. |
| `agentic-os-intake-sync` | Sync intake data from connected sources. |
| `agentic-os-jira` | Jira helper for an Atlassian Jira site; prefers OAuth, falls back to API token. |
| `agentic-os-memory-analytics` | Read-only memory-analytics viewer; runs the report on the configured analytics host via SSH. |
| `agentic-os-notify` | Deliver governed macOS notifications; records delivery/suppression history, enforces cooldowns, and prunes history after 48 hours by default. |
| `agentic-os-quiet-run` | Start and monitor long-running commands detached from the terminal. |
| `agentic-os-status-report` | Generate durable OS status report artifacts (markdown, Notion draft, gap analysis). |
| `register-codex-skills` | Sync Agentic OS skill adapters to Codex launcher metadata. |
| `register-harness-skills` | Register harness skills into the OS skill registry. |

Add scripts here only when the OS package owns the wrapper and the script is safe
to mirror into installed roots.

## Notification usage

Agents invoke `agentic-os-notify` through `/notify` or the
`notification-operator` skill. Those surfaces define eligibility, severity,
dedupe, source registration, and retained-history handling; do not treat this
wrapper index as the policy contract.
