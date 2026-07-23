# Quick Reference: OS cleanup

## Purpose

Safely finish one delivered Auto-Dev item: audit receipts, preserve its resume
path, reconcile only item-owned local resources, move the packet to finished,
and verify it is no longer active.

## Start Here

1. Load the owning root, domain, and project contracts.
2. Read `workflow.md`, `context-pack.md`, `approval-rules.md`, and `runbook.md`.
3. Confirm this is existing state with canonical `delivery_complete` proof.
4. Run Health with `--apply` to audit and hash receipts, write the resume and
   full packet manifests, and freeze `preflight.json` before cleanup.
5. Tear down or read back the exact target-local runtime and write a packet-local
   `auto-dev-runtime-cleanup/v1` receipt bound to the preflight SHA-256.
6. Inspect an exact item-scoped dry run with the preflight and runtime receipt.
7. Apply only when every worktree/runtime gate passes; preserve one atomic
   `auto-dev-resource-cleanup/v1` readback for both resources.
8. Snapshot the exact closed registry row, or `not_managed`, in
   `auto-dev-closed-worktree-readback/v1`; audit it under `resource_cleanup`
   and cross-check a managed row against live `worktrees/closed.yml`.
9. Move and reconcile the durable packet, then validate and read it back.

## Common Commands

```bash
agentic-os auto-dev health --state <work-item-or-autodev.json> --apply

agentic-os project worktree cleanup-closed \
  --domain <domain> --project <project> --worktree <exact-id-or-path> \
  --health-preflight <packet>/artifacts/auto-dev-health/preflight.json \
  --runtime-receipt <packet>/artifacts/auto-dev-health/receipts/runtime-cleanup.json \
  --root <os-root> --dry-run

agentic-os project worktree cleanup-closed \
  --domain <domain> --project <project> --worktree <exact-id-or-path> \
  --health-preflight <packet>/artifacts/auto-dev-health/preflight.json \
  --runtime-receipt <packet>/artifacts/auto-dev-health/receipts/runtime-cleanup.json \
  --root <os-root> --apply --remove-files

agentic-os project work-item set <domain> <project> <packet-id> \
  --state finished --health-relocation \
  --note "Auto-Dev Health audit passed" --root <os-root>

agentic-os work active-now --root <os-root>
agentic-os work show <canonical-work-id> --root <os-root>
agentic-os validate --root <os-root>
```

## Required Evidence

- Completed typed Merge receipt containing `merge_sha`, provider-read
  `source_head_sha` equal to the reviewed `subject_revision`, `provider`,
  `pull_request`, and `readback_verified: true`; Health authority reuses the
  same provider, PR reference, and merge revision.
- Empty receipt-audit missing list and readable resume manifest.
- Hashed canonical task parses as `delivery_complete` and exactly matches the
  work item, worktree, branch, reviewed revision, and merge revision.
- Packet Merge/Closeout snapshots are JSON-equivalent to canonical typed task
  receipts; the ordered non-Health stage audit is complete and every stage
  snapshot hash verifies.
- Packet-local `auto-dev-health-preflight/v1` plus its exact SHA-256.
- Full pre-cleanup packet manifest; after relocation all hashes match except
  validated semantic `work.yml` and `autodev.json` updates.
- `auto-dev-runtime-cleanup/v1` readback bound to that preflight hash, including
  an explicit no-runtime disposition when applicable. Managed identity and
  commands include domain/project/worktree; the receipt is at most 15 minutes
  old and the immediate registered readback exits 0 only when that runtime is
  absent.
- One `auto-dev-resource-cleanup/v1` readback binding the exact worktree and
  runtime identities and verified dispositions.
- One audited `auto-dev-closed-worktree-readback/v1` snapshot matching the live
  closed registry row, or recording `not_managed`.
- Packet move and canonical state-history receipt.
- Closed-registry and active-index readbacks.
- Passing validation results and no residual holds.

The final audit kinds are exactly `terminal_authority`, `closeout`,
`receipt_audit`, `resume_manifest`, `packet_manifest`, `resource_cleanup`,
`runtime_cleanup`, `work_state`, `active_index`, and `validation`.

## Safe Outcomes

| Resource result | Meaning |
| --- | --- |
| `removed` | Verified item-owned resource was safely retired. |
| `absent` | Expected resource no longer exists; audit still completed. |
| `not_managed` | This item never owned that resource; audit still completed. |

`not_required` is not a Health result. A no-op still receives a complete audit.

## Common Failure Modes

| Failure | Response |
| --- | --- |
| Missing merged-pull-request proof or exact merge revision | Stop before cleanup; route to Closeout or the pull-request authority owner. |
| Missing receipt or resume detail | Preserve resources and complete the packet first. |
| `REOPEN.md` or residual hold | Leave the resource registered and report the exact hold. |
| Dirty or untracked worktree | Preserve it. Reconcile the changes in a separate operator workflow, verify clean status, and rerun Health with a fresh preflight. |
| External/protected/primary/unregistered worktree | Do not remove it. |
| Ambiguous or shared runtime | Do not tear it down. |
| Runtime or Git removal failure | Keep the registry entry active and preserve the failure receipt. |
| Packet/state/index disagreement | Do not record Health complete; repair and read back again. |
| Request for host-wide/all-resource cleanup | Refuse and narrow the request to exact owned resources. |

Health is manual and item-scoped. This workflow enables no schedule or
host-wide/all-resource operation.
