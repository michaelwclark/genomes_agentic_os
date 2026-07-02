---
name: bug-intake-router
description: Capture lightweight Agentic OS or project bug reports through doc-config, project work-items, and optional Notion projection. Use when the user says /add-bug or reports broken behavior, missing logs, routing drift, or missed OS enforcement.
---

# Bug Intake Router

Use this skill to turn a bug report into local markdown that a later agent can
triage without reading the original chat.

## Intake Loop

1. Load the routed OS layer and `harness/rules/os-authoring-rules.md`.
2. Run `agentic-os doc-config plan` with the original bug report.
3. Resolve the affected domain/project. Route Agentic OS bugs to
   `clarks_consulting/genomes_agentic_os`.
4. Search existing work-items for duplicate bugs.
5. Create or repair a captured packet work item named `Bug: <short failure>`.
6. Add `BUG.md` when the generic packet files are not enough.
7. Record evidence in `WORKLOG.md` and next action in `NEXT.md`.
8. Verify Notion workspace before any projection.
9. Create the unified intake row (non-blocking):

```bash
agentic-os-intake-row \
  --title "Bug: <short failure>" \
  --type bug \
  --route-text '<user's original bug report words>' \
  --body-file <packet BUG.md or SPEC.md path>
```

   If the row create fails, record the error in `WORKLOG.md` and continue.

## Required Bug Shape

- affected area
- severity
- current behavior
- expected behavior
- reproduction/evidence
- suspected cause when known
- owner/status
- next action

## Guardrails

- Keep raw logs and transcripts out of chat and Notion unless explicitly needed.
- Link large evidence from artifacts instead of pasting it.
- Treat missed OS enforcement, stale worktree registration, missing registry
  rows, and missing conversation logs as bugs.
