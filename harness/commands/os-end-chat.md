# OS End Chat

Use when a user or agent asks to finish a substantive Agentic OS thread with `/end-chat`, `/finalize`, `/cleanup-thread`, `/archive`, "close this out", or equivalent language.

Primary skill: `thread-finalizer`.

## CLI Surface

Use these command equivalents when a slash command needs a concrete local run:

| Slash Command | CLI |
| --- | --- |
| `/end-chat` | `agentic-os thread end --root <os-root>` |
| `/finalize` | `agentic-os thread finalize --root <os-root>` |
| `/cleanup-thread` | `agentic-os thread cleanup --root <os-root>` |
| `/archive` | `agentic-os thread archive --root <os-root>` |
| stale sweep | `agentic-os thread stale-finalize --root <os-root> --older-than-days 3 --dry-run` |

The direct aliases `agentic-os end-chat`, `agentic-os finalize`, `agentic-os cleanup-thread`, and `agentic-os archive` are also available.

## Command Modes

| Command | Mode | Result |
| --- | --- | --- |
| `/end-chat` | `finish` | Runs the FINISH contract and leaves the thread/work item active unless the closeout state says otherwise. |
| `/finalize` | `finish` | Alias for `/end-chat`. |
| `/cleanup-thread` | `cleanup` | Runs finalization, classifies generated dirt, and performs only allowlisted cleanup. |
| `/archive` | `archive` | Runs finalization, then archives only when no unresolved next action remains or the user explicitly accepts a parked/blocked archive. |

## Procedure

1. Re-read the newest user request and the routed Agentic OS layer.
2. Load the active work item, run log, PR/Jira/Notion reference, or conversation log when one is attached.
3. Classify work level: `trivial`, `contextual`, `artifact`, `implementation`, or `operational`.
4. Classify closeout mode: `noop`, `status-only`, `artifact-closeout`, `implementation-closeout`, `cleanup`, or `archive`.
5. Collect evidence without dumping raw logs into chat.
6. Update filesystem source of truth first: `WORKLOG.md`, `NEXT.md`, `DECISIONS.md`, `MEMORY.md`, project `status.md`, run log, and closeout artifacts as applicable.
7. Write thread closeout artifacts under the Agentic OS wrapper path, not the product source repository.
8. Attempt or record Genome's Notion projection for substantive closeouts only after verifying the target workspace.
9. Treat Notion connection, authorization, or permission failure as a non-blocking warning in `notion-sync.md`.
10. Return a short final response with the result, source-of-truth link, receipts, next action, and intentionally preserved dirty state.

## Required Artifacts

For `artifact`, `implementation`, and `operational` closeouts, create or update:

- `thread.yml` or `thread-closeout.yml`
- `closeout.md`
- `evidence.jsonl`
- `memory-write-receipts.jsonl`
- `notion-sync.md` when Notion projection was attempted, skipped, or failed
- `archive-manifest.yml` only for archive mode

Use `harness/shared_factory/05-knowledge/templates/thread/` as the artifact template set. The CLI writes these under `artifacts/thread-closeouts/<thread-id>/` when a work item is attached, otherwise under `harness/shared_factory/06-runs-and-logs/runs/<thread-id>/`.

## Notion Guardrail

Notion projection is default for substantive closeouts, but it is never the blocker. The finalizer must:

- verify `Genome's Notion` before writing;
- refuse Michael Clark personal Notion or any unverified workspace;
- record `verified`, `skipped`, `warning`, or `blocked` in `notion-sync.md`;
- continue local closeout when Notion is unavailable;
- avoid creating fallback pages in another workspace.

## Stale Thread Sweep

A stale-thread sweep may use this command contract for threads untouched for more than 3 days. The sweep is conservative:

- no action for trivial chats;
- prefer `status-only` or `artifact-closeout`;
- do not archive unresolved work silently;
- write `NEXT.md` when work remains;
- record the stale reason in `closeout.md` and `thread-closeout.yml`.

## Cleanup Boundary

`/cleanup-thread` classifies before mutating. Generated traces, receipts, and worklogs belong in Agentic OS wrapper paths. Repo-local generated traces require a `.gitignore` rule before use. Unrelated dirty files are preserved and reported.
