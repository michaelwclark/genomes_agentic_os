# Bug Intake

Use this workflow whenever a bug, missed enforcement, logging gap, routing drift,
or broken product behavior needs to enter Agentic OS.

## Trigger Phrases

- `/add-bug`
- "bug in"
- "not working"
- "missed enforcement"
- "not logging"
- "routing drift"

## Workflow

1. Route the request through the current Agentic OS layer.
2. Run `agentic-os doc-config plan` with the original bug report.
3. Resolve affected domain/project.
4. Search existing work-items for duplicates.
5. Create or repair a bug packet.
6. Fill `BUG`, `SPEC`, `PLAN`, `WORKLOG`, `NEXT`, and `QUESTIONS` when needed.
7. Register any active source worktree that will be used for investigation.
8. Mirror to Notion only after workspace verification.

## Required Artifacts

- bug summary
- current vs expected behavior
- evidence or reproduction
- severity
- affected area
- next action

## Source Of Truth

The filesystem work item is authoritative. Notion is the human control-plane
projection unless local config explicitly changes the source of truth.
