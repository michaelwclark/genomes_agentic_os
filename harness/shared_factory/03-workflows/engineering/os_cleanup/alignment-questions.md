# Alignment Questions: OS cleanup

## Metadata

| Field | Value |
| --- | --- |
| Domain | `shared_factory` |
| Lane | `engineering` |
| Owner | `Agentic OS` |
| Created | `2026-07-20` |
| Last Reviewed | `2026-07-20` |

## Purpose

These answers make the cleanup boundary explicit before an agent changes local
resources or lifecycle state.

## Required Questions

| Question | Answer | Blocks Dispatch |
| --- | --- | --- |
| What should exist when this is done? | A finished, readable packet with audited receipts and a resume manifest; each expected local resource is removed, absent, or not managed. | no |
| Who or what will use the result? | Operators, future agents, Auto-Dev Health, and bounded OS Cleaner runs. | no |
| What systems may be read? | Owning contracts, existing Auto-Dev/work state, provider terminal truth, Git worktree metadata, target-local runtime definitions, registries, packet artifacts, and active indexes. | no |
| What systems may be written? | Only the owning packet, its exact item-local runtime/worktree, canonical work state, project packet lane, and related indexes/registries. | no |
| What must not change? | Shared infrastructure, unrelated worktrees/runtimes, protected branches, external checkouts, delivered evidence, and provider delivery truth. | no |
| What proof will show the work is correct? | Typed provider-read Merge receipt and exactly matching Health authority, SHA-256 receipt audit, resume manifest, scoped cleanup receipts, typed closed-registry readback, work-state history, active-index readback, and validation results. | no |
| What should stop the run? | Missing proof, unresolved holds, ambiguous ownership, unsafe scope, failed teardown/removal, or unreadable post-move state. | no |

## Operator Answers

- Auto-Dev Closeout proves `delivery_complete`; Health performs the later
  receipt audit, lifecycle cleanup, finished-lane move, and final readback.
- No resource is removed merely because a tracker says Done or QA Ready.
- A no-resource run is still real work: it records `absent` or `not_managed`
  after the same audit and validation.
- Health is manually callable. No schedule is enabled by this workflow.
- Health has no host-wide/all-resource mode.

## Assumptions

| Assumption | Confidence | Validation Needed |
| --- | --- | --- |
| The work item already has `autodev.json` and canonical delivery state. | high | Read both before mutation. |
| A worktree is reconstructable after merge. | medium | Verify the merged pull request, exact merge revision, repository, base, branch, and recreation details in the resume manifest. |
| A local runtime is safe to remove only when uniquely mapped to the checkout. | high | Read target-local runtime configuration and record its identity. |

## Dispatch Decision

- Ready to run: `yes`, when every preflight gate passes.
- Remaining blockers: any missing merged-pull-request proof, receipt, ownership
  proof, or protected-hold resolution named by the current item.
