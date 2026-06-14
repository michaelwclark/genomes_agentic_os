# Thread Finalizer

Use when the user says `/end-chat`, `/finalize`, `/cleanup-thread`, `/archive`, "end chat", "finalize", "close this out", "clean up this thread", or when a stale-thread sweep is finalizing work untouched for more than 3 days.

## Purpose

Finish substantive Agentic OS work so the filesystem source of truth, durable memory, Notion projection receipt, evidence, and next-action state are complete enough for a future agent to continue without reading the chat.

## Load

Read only what is needed:

1. The newest user request and current route files.
2. The active work item, run log, or attached project status.
3. Relevant receipts: command summaries, PR/check identifiers, artifact paths, agent returns, or external refs.
4. Existing `WORKLOG.md`, `NEXT.md`, `DECISIONS.md`, `MEMORY.md`, and `notion-sync.md` when present.

## Classify

Work levels:

- `trivial`: final answer only.
- `contextual`: memory/writeback only if a durable non-obvious fact was learned.
- `artifact`: update worklog, next action, closeout receipt, and optional memory.
- `implementation`: update worklog, receipts, dirty-state summary, next action, and memory when useful.
- `operational`: update run log, approvals, receipts, owner, next check, and rollback/status notes.

Closeout modes:

- `noop`
- `status-only`
- `artifact-closeout`
- `implementation-closeout`
- `cleanup`
- `archive`

## Workflow

1. Re-read newest user intent and avoid finalizing an older task by mistake.
2. Route to the narrowest Agentic OS layer and attach to the current work item or run log when available.
3. Collect evidence privately; summarize receipts instead of pasting raw logs.
4. Write or update source-of-truth files first.
5. Create closeout artifacts from `harness/shared_factory/05-knowledge/templates/thread/`.
6. Write durable memory only for non-obvious learnings, state transitions, reusable conventions, user preferences, feedback, or references.
7. Attempt Notion projection for substantive closeouts after verifying `Genome's Notion`; record warning or skip status without blocking local finalization.
8. Classify dirty state as unrelated, generated, or intentional. Preserve unrelated dirt.
9. For archive mode, archive only after finalization and only when no unresolved `NEXT.md` remains unless the user explicitly accepts a blocked/parked archive.
10. Return a concise closeout response with links and risks.

## CLI

Prefer the structured command family for filesystem closeout:

- `agentic-os thread end --root <os-root>`
- `agentic-os thread finalize --root <os-root>`
- `agentic-os thread cleanup --root <os-root>`
- `agentic-os thread archive --root <os-root>`
- `agentic-os thread stale-finalize --root <os-root> --older-than-days 3 --dry-run`

Direct aliases also exist: `agentic-os end-chat`, `agentic-os finalize`, `agentic-os cleanup-thread`, and `agentic-os archive`.

## Memory Phrasing

Durable memory writes must start with one of:

- `user:`
- `feedback:`
- `project:`
- `reference:`

Skip memory for trivial or obvious work.

## Notion Receipt

`notion-sync.md` must say whether projection was `verified`, `skipped`, `warning`, or `blocked`. Connection failure, authorization failure, and missing Genome workspace access are warnings or blockers for projection only; they do not undo filesystem closeout.

## Stale Thread Rule

For stale-thread sweeps, only finalize threads untouched for more than 3 days. Prefer `status-only` or `artifact-closeout`, never delete evidence, and never silently archive unresolved work.

## Final Response

Keep the user response short:

- result;
- source-of-truth path;
- receipt paths or identifiers;
- next action or `None`;
- known risks or dirty state intentionally left alone.
