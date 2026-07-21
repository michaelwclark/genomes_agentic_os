# PRD: OS cleanup

## Metadata

| Field | Value |
| --- | --- |
| Domain | `shared_factory` |
| Lane | `engineering` |
| Owner | `Agentic OS` |
| Created | `2026-07-20` |
| Last Reviewed | `2026-07-20` |

## Problem

Auto-Dev creates useful but reconstructable local worktrees and runtimes. If
they live forever, active views and local resources accumulate stale entries.
If they are removed too aggressively, the evidence needed for QA, investigation,
or later resumption is lost. Cleanup therefore needs a receipt-first, item-
scoped lifecycle workflow after delivery is proven.

## Outcome

A delivered work item has a readable resume packet and verified finished state,
while only its reconstructable, uniquely owned local resources have been
removed or recorded as absent.

## Users And Use Cases

| User | Use Case | Success Signal |
| --- | --- | --- |
| Auto-Dev operator | Finish one delivered item. | `/auto-dev-health` completes with strict evidence. |
| OS operator | Reconcile a bounded known set. | `$os-cleaner` reports removed and skipped resources without hiding failures. |
| Future agent | Reopen or investigate old work. | The completed packet explains exact revision, decisions, receipts, and recreation steps. |

## Scope

### In Scope

- Existing-state-only Health and bounded OS Cleaner routing.
- Typed Merge authority, receipt, hold, path, branch, and ownership preflights.
- Resume-manifest preservation before item-local resource cleanup.
- Git-native worktree removal and target-local runtime teardown.
- Finished-packet, canonical work-state, registry, and active-index reconciliation.

### Out Of Scope

- Deciding or performing merges, releases, deployments, or tracker closeout.
- Unscoped host-wide/all-resource operations, shared infrastructure teardown, and evidence
  deletion.
- Scheduled physical cleanup.
- Treating any dirty file, tracker status, receipt, or caller assertion as
  deletion authority.

## Requirements

| Requirement | Priority | Acceptance Evidence |
| --- | --- | --- |
| Health requires existing delivered state and typed provider-read Merge proof. | must | Merge receipt binds reviewed source head, provider, PR reference, and exact merge SHA; Health authority matches it. |
| Required receipts are audited before cleanup. | must | Empty missing list, SHA-256 entries, and `resume_ready: true`. |
| Resume details survive resource removal. | must | Plain-English manifest stored in the durable packet before teardown. |
| Cleanup is limited to exact item-owned resources. | must | Worktree and runtime identities have separate preflight/action/result receipts. |
| Git worktree metadata stays correct. | must | Removal uses Git worktree operations and registry closure follows success. |
| Closed-registry readback is durable. | must | Packet-local `auto-dev-closed-worktree-readback/v1` is audited under `resource_cleanup` and matches live `closed.yml`, or says `not_managed`. |
| Dirty work is never inferred disposable. | must | Health preflight is always `clean_only`; physical removal requires clean `git status --porcelain`, otherwise the checkout remains in place until a separate operator workflow reconciles it and Health is rerun. |
| Durable lifecycle becomes finished and inactive. | must | Packet/state/index readbacks agree after the move. |
| No-op cleanup remains auditable. | must | `absent` or `not_managed` dispositions use the same audit and readback gates. |
| Unsafe or failed cleanup remains visible. | must | Resource is still registered with a precise hold/skip reason. |

## Data And Source Systems

| Source | Read | Write | Notes |
| --- | --- | --- | --- |
| Work-item packet and `autodev.json` | yes | yes | Durable record; never delete. |
| Development Delivery task and canonical work registry | yes | yes | Close only after resource and packet operations succeed. |
| Provider/tracker terminal truth | yes | no | Closeout owns provider reconciliation; cleanup consumes verified proof. |
| Git worktree metadata | yes | bounded | Only exact registered, non-protected checkout. |
| Target-local runtime definition | yes | bounded | Only uniquely mapped local resources. |
| Active projections | yes | refresh | Read back after finished transition. |

## Approval And Safety

- Dry-run, receipt audit, manifest creation, and readback come first.
- Physical resource removal requires all applicable gates in
  `approval-rules.md`; failed removal never becomes a hidden registry closure.
- Never print secrets into manifests, receipts, logs, or chat.
- Never run host-wide Docker or OrbStack cleanup from this workflow.

## Validation

| Check | Evidence | Required |
| --- | --- | --- |
| Contract and receipt completeness | Receipt-audit and Health-schema validation results | yes |
| Resource scope | Exact identity, managed-root, branch, hold, and ownership preflight | yes |
| Packet/state agreement | Completed packet plus canonical state/readback receipts | yes |
| Active-view agreement | Both active projections exclude the item | yes |
| Structural health | `agentic-os validate` summary | yes |

## Open Questions

- Future monitoring is a separate design decision. This workflow enables no
  schedule; any later monitor must invoke the same exact-item state and receipt
  gates rather than inventing a queue or host-wide cleanup path.
