# Canonical Work State

Use SQLite work state instead of inferring activity from filesystem lanes,
Jira/Linear, branches, or worktrees.

```bash
agentic-os work active-now --root <os-root>
agentic-os work list --root <os-root> --attention active
agentic-os work show <work-item-id> --root <os-root>
agentic-os work upsert <work-item-id> --root <os-root> --title <title> [fields]
agentic-os work set <work-item-id> --root <os-root> [state/attention/context]
```

Read `active-now.json` first. Only rows with attention `active` belong in broad
resume context; queued and parked rows stay discoverable without consuming the
active context budget. Active rows require a resume summary, blocked rows
require a reason or receipt, and terminal lifecycle states force attention
`closed`.

Legacy folder migration never marks rows active:

```bash
agentic-os work import-legacy --root <os-root>
agentic-os work import-legacy --root <os-root> --apply
```
