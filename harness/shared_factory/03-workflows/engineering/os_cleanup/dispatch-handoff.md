# Dispatch Handoff: OS cleanup

## Metadata

| Field | Value |
| --- | --- |
| Domain | `shared_factory` |
| Lane | `engineering` |
| Owner | `Agentic OS` |
| Created | `2026-07-20` |
| Target Agent / Harness | `codex_or_claude_or_human` |

## Outcome

Finish one delivered work item without losing its durable evidence, and remove
only reconstructable local resources after ownership, merged-pull-request proof,
and the exact merge revision are verified.

## Required Sources To Load

| Source | Location | Why Required |
| --- | --- | --- |
| Root/domain/project contracts | routed owning object | Establish the strictest applicable safety rules. |
| Workflow contract | `workflow.md`, `approval-rules.md`, `runbook.md` | Defines order, gates, and completion. |
| Existing Auto-Dev state | item `autodev.json` | Confirms item identity and stage history. |
| Delivery truth | linked Development Delivery task and provider readback | Proves `delivery_complete`, the merged pull request, and exact merge revision. |
| Cleanup context | `context-pack.md` and project policies | Resolves managed root, runtime, retention, and protected holds. |
| Resume state | `progress.md` and packet artifacts | Prevents lost or duplicated work. |

## Ownership

| File / System / Responsibility | Owner | Notes |
| --- | --- | --- |
| Provider/tracker delivery reconciliation | Auto-Dev Closeout | Health reads this proof; it does not recreate it. |
| Receipt audit, resume manifest, finished lifecycle | Auto-Dev Health | Required even when resources are absent. |
| Bounded resource operations | OS Cleaner | Exact item scope only. |
| Durable packet | Owning project | Preserve and move; never delete. |

## Instructions

1. Confirm this is an existing delivered item; do not create a new packet.
2. Read the merged pull request live and require a completed typed Merge receipt:
   `merge_sha`, provider-read `source_head_sha` equal to the reviewed revision,
   `provider`, `pull_request`, and `readback_verified: true`. Health authority
   must match its provider, PR reference, and merge SHA exactly.
3. Complete the receipt audit and resume manifest, then freeze the packet-local
   Health preflight before resource mutation.
4. Tear down or read back the exact local runtime, then record
   `auto-dev-runtime-cleanup/v1` bound to the preflight SHA-256, even when the
   runtime is absent or not managed.
5. Inspect the item-scoped dry run with domain, project, worktree, preflight,
   and runtime receipt; stop for any external, protected, shared,
   reopened, dirty, or ambiguously owned resource.
6. Remove the exact Git worktree only through the guarded apply, then preserve
   one atomic `auto-dev-resource-cleanup/v1` readback for both resources.
7. Preserve `auto-dev-closed-worktree-readback/v1` with the exact closed row or
   `not_managed`; audit it under `resource_cleanup` and cross-check live
   `worktrees/closed.yml` for a managed row.
8. Leave failed or skipped resources visible in the active registry.
9. Move the durable packet, reconcile work state and indexes, validate, and
   record strict Health evidence from the completed packet.

## Constraints

- Allowed reads: routed policy, provider/tracker truth, Git metadata, local
  runtime configuration, packet evidence, registries, and projections.
- Allowed writes: exact item-local resources, its packet/state/registry rows,
  and their derived indexes and receipts.
- Approval gates: every physical cleanup gate in `approval-rules.md`.
- Out of scope: provider delivery actions, host-wide/all-resource operations, shared infrastructure,
  scheduled physical cleanup, external checkouts, and durable packet deletion.

## Verification

| Check | Command Or Evidence | Required |
| --- | --- | --- |
| Merged pull request identity and revisions | Typed Merge receipt plus exactly matching Health terminal authority | yes |
| Receipt audit and recovery path | SHA-256 inventory plus resume manifest | yes |
| Item-scoped cleanup | Dry-run/apply receipts for exact worktree/runtime | yes |
| Closed registry | Packet-local typed readback cross-checked with live `closed.yml` | yes |
| Finished/inactive lifecycle | Packet, canonical state, and active-index readbacks | yes |
| Structural validation | `agentic-os validate` summary | yes |

## Stop Conditions

- The outcome conflicts with project retention or reopening policy.
- Required state, merged-pull-request proof, receipts, or resource identity is
  missing.
- A target is external, protected, shared, primary, unmerged, reopened, or
  dirty.
- Teardown/removal fails or post-move readback disagrees.
- The requested action would widen cleanup beyond the named item.

## Handoff Back

- Run log: exact durable run or packet receipt reference.
- Artifacts: audit, resume manifest, resource, work-state, index, and validation receipts.
- State update: final packet path and canonical finished-state readback.
- Next action: none on success; otherwise one exact owner and unblock action.
