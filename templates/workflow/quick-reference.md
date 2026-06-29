# Quick Reference: <workflow_name>

## Purpose

One-page companion for running this workflow without rereading every file.

## Start Here

1. Read `workflow.md`.
2. Confirm the invocation contract has a command or skill registry entry before
   treating the workflow as active.
3. Confirm `outcome-brief.md`, `alignment-questions.md`, `prd.md`, `implementation-plan.md`, and `dispatch-handoff.md` are ready.
4. Load `context-pack.md`.
5. Check `approval-rules.md`.
6. Execute from `runbook.md`.
7. Write the run log and update `progress.md`.

## Common Commands

```bash
agentic-os run-log create <domain> <workflow-or-automation> --root ~/agentic_os
agentic-os validate --root ~/agentic_os
```

## Required Evidence

- Source links loaded:
- Validation run:
- Approval required:
- Artifacts changed:
- Run log:

## Common Failure Modes

| Failure | Response |
| --- | --- |
| Outcome is vague | Stop and update `outcome-brief.md`. |
| Operator questions are unanswered | Stop and update `alignment-questions.md`. |
| Scope changed during execution | Pause and update `prd.md` plus `implementation-plan.md`. |
| Approval gate is crossed | Stop and request approval. |
| Session is ending mid-run | Update `progress.md` and the run log. |
