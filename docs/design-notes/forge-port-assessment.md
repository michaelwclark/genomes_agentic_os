# FORGE → Agentic OS: Port Assessment And Roadmap

Status: assessment complete (2026-07-13 night run). Source evidence: comparative audit of
`losmon` FORGE (file plane + `src/data/forge*` modules) versus this repository's runtime,
events, automations, and run-log subsystems, plus the installed-instance state inventory.

## Why This Document Exists

FORGE is losmon's event-driven, multi-agent SDLC engine. It solves the same problem family
this product solves — coordinating agents through workflows with auditable state — and the
two systems have been converging independently. This document records which side owns the
better implementation per capability, what gets ported, and in what order, so the two
systems stop drifting apart and duplicated engineering stops accruing.

## Verdict Summary

The OS product is the surviving home for the generic engine. FORGE remains losmon's
project-local engine until ports land, then losmon adopts the OS implementations where the
OS wins. Neither system is wholesale better:

| Capability | FORGE | Agentic OS product | Verdict |
| --- | --- | --- | --- |
| Event ledger | `events.jsonl` append-only ground truth; markdown derived | One YAML file per event; chain rules present but disabled | Port FORGE pattern (append-only ledger; SQLite implementation, see state plane) |
| Trace honesty | `reconcileTraces` detects phantom/fabricated completion claims | Nothing equivalent | Port |
| Notifications | Lease-based outbox: `claimNextPending` / `markSent` / `markFailed` + backoff | Absent | Port |
| Review queues | Three adjudication modules (review-queue, enhanced-review, behavior-validation) | Absent | Port (as one generalized queue, not three) |
| Self-verification gate | Spawns real build/test before `DEV_COMPLETE` can be claimed | Validation evidence required at `run-log close` (exit 2 without `--validation`) | Merge: keep OS's CLI-enforced evidence gate, add FORGE's "actually run the build" verifier as an evidence provider |
| Preconditions | Declarative, composable (`feature-card-exists`, `build-succeeds`, …) gate phase dispatch | Approval rules are prose + maturity levels | Port the declarative precondition registry; keep OS approval semantics |
| Gates / maturity | Phase gates, project-local | 5-level maturity ladder (observe → execute_guarded), blocker-gated advancement, auto-logged decisions | Keep OS (product-grade, externally legible) |
| Run audit trail | Agent traces + logs, reconciliation after the fact | Run-log lifecycle enforced at CLI layer before any write | Keep OS |
| Context building | Universal chokepoint enforcing holdout-exclusion by agent role | Context packs are convention, not enforced | Port the chokepoint pattern into context-pack loading |
| Workflow engine | YAML DAG + HMAC-verified webhook triggers | Workflow folders + runbooks; no DAG executor | Converge later — biggest piece, do last |

FORGE-internal debt found during the audit (dual event logs, dual project registries) is
losmon's to fix and is tracked in losmon's own backlog, not here.

## Port Order (each lands as its own work item)

1. **Append-only event ledger in the state plane** — replaces one-file-per-event YAML.
   Ships with the SQLite state plane (AGE-39); the FORGE lesson applied is "ledger is
   ground truth, human-readable views are projections."
2. **Trace/claim reconciliation** — a `doctor`-class command that cross-checks recorded
   run/agent completion claims against ledger evidence and flags phantom completions.
   Directly attacks the trust gap in multi-agent work.
3. **Lease-based outbox** — generic notification/side-effect outbox table + worker loop
   (claim, send, mark, backoff). Unblocks reliable external effects (tracker sync per the
   external-tracker policy spec; notifications).
4. **Declarative preconditions** — registry of named, composable checks consumable by
   automations and workflows before dispatch; maturity ladder stays the authority for
   what runs unattended.
5. **Generalized review queue** — one adjudication queue for agent-produced work
   (findings, PRs, proposals), replacing FORGE's three specialized variants at port time.
6. **Context-builder chokepoint** — enforce context-pack contracts (including holdout
   exclusion) in code at load time instead of by convention.
7. **Workflow DAG executor** — last and largest; only after 1–6 prove out, and only if
   folder-plus-runbook workflows demonstrably hit their ceiling.

## Non-Goals

- No wholesale FORGE import: its Mongo-backed persistence, losmon-specific project
  registries, and SCREAMING_SNAKE event taxonomy stay behind.
- No losmon behavior change tonight; losmon adopts ported OS implementations on its own
  schedule.

## Evidence Trail

- Comparative audit detail (component map, overlap matrix, persistence map, instance
  state inventory, SQL sketches): night-run scratchpad `audit-forge-sqlite.md`.
- Instance pain quantified: `run-queue.yml` 13.01MB / 261,184 lines / 10,850 items,
  whole-file rewrite per tick; one-YAML-per-event ledger; cursor files rewritten per
  update. These numbers justify port items 1 and the AGE-39 milestone order.
