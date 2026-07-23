# Readiness and Context

## Flow

![Auto-Dev Development Delivery stages](../../../00-programs/auto_dev/assets/development-delivery-stages.svg)

## What this does

Turns a tracker item into verified implementation context. It prevents coding
from starting when ownership, acceptance criteria, project configuration, or
required data evidence is missing.

## Manual run

Use `/auto-dev-readiness`, then record verified work with
`agentic-os develop stage <state.json> --stage readiness ...`.

## Inputs

- Tracker identifier and live tracker snapshot.
- Project `config/development.yml` and tracker/repository credentials.
- Existing project-domain articles, relevant code, prior work-item receipts,
  and optional read-only pre-production/production evidence.

## Outputs

- Verified claim, groom-check decision, bounded context pack, explicit
  project-domain context receipt (including `no_context`), risk level,
  implementation/test plan, and explicit blocker or `context_ready` receipt.

## States

`discovered -> claimed -> groom_check -> context_ready`. Any non-terminal state
may move to `blocked`, `abandoned`, or `cancelled` with a receipt.

## Steps

1. Re-read the tracker and verify project, ownership, dependencies, acceptance
   criteria, fix version, and duplicate/overlap risk.
2. Claim with a provider-side token, then re-read to prove exclusive ownership.
3. Load the project profile and validate every adapter needed by this ticket.
4. Invoke `project-domain-investigate` for the focus topic, preserve its
   `project-domain-context/v1` receipt, and inspect only the relevant code. A
   `no_context` receipt is valid but must name the uncovered questions.
5. If correctness depends on real data, gather minimum read-only evidence and
   redact secrets/customer data from prompts and external writebacks.
6. Produce a change map, risk classification, required test layers, and the
   smallest execution plan that satisfies acceptance criteria.

## Validations

- Claim token, assignee, tracker project/team, and current state match.
- Acceptance criteria are observable and internally consistent.
- Repository/base branch and validation commands resolve.
- Context sources and the consumed domain receipt are recorded; stale or
  contradictory evidence is called out.
- High-risk/data-dependent work has explicit rollback and test evidence needs.

## Success modes

- `context_ready`: sufficient evidence and an executable plan exist.
- `cancelled`: live evidence proves the request is already satisfied or invalid.

## Failure modes and recovery

- Missing criteria/config: block with exact missing fields; recover after tracker
  or profile repair.
- Duplicate claim: release local lease and block; do not steal ownership.
- Provider unavailable: retry with backoff up to project attempt limit.
- Data access unavailable: continue only when data is not decision-critical;
  otherwise block with the failed read-only preflight receipt.
- Contradictory scope: return to grooming rather than guessing.

## Events and receipts

Emit `task.claimed`, `groom_check.passed|failed`, `context.loaded`, and
`task.blocked|cancelled`. Store tracker snapshot, claim readback, source list,
  data-query summary, domain context receipt, risk decision, and
  implementation/test plan in the work item artifacts.

## Cleanup and handoff

Release the claim on cancellation/abandonment. Handoff `context_ready` with the
profile snapshot, plan, risk, and evidence references; do not hand off raw data
dumps or unrelated repository context.
