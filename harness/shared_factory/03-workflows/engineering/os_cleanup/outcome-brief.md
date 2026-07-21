# Outcome Brief: OS cleanup

## Metadata

| Field | Value |
| --- | --- |
| Domain | `shared_factory` |
| Lane | `engineering` |
| Owner | `Agentic OS` |
| Created | `2026-07-20` |
| Last Reviewed | `2026-07-20` |

## Definition Of Done

In Health/physical mode, a delivered work item has a readable resume packet and
verified finished state while only its reconstructable, uniquely owned local
resources are removed or recorded as absent. In explicitly non-code
registry-only mode, eligible rows leave active registries with durable source
evidence and readback, but no resource is deleted and Health is not completed.

## Desired Outcome

Completed work does not leave permanent worktrees or item-local runtimes behind,
and a future agent can still understand, verify, or recreate the work without
chat history.

## Users / Beneficiaries

| User | Need | Success Signal |
| --- | --- | --- |
| Operator | Keep local development resources tidy. | Eligible item-owned resources are removed without a host-wide operation. |
| Future agent | Resume or investigate completed work quickly. | The finished packet contains a plain-English resume manifest and hashed receipts. |
| Auto-Dev Health | Complete the lifecycle after Closeout. | Strict Health evidence passes and the item disappears from active projections. |

## In Scope

- Reconcile explicitly non-code terminal rows in registry-only mode without
  physical deletion or a Health completion claim.
- Verify typed Merge proof: merge SHA, provider-read source head equal to the
  reviewed revision, provider, pull-request reference, and readback flag.
- Audit receipts and write the resume manifest before cleanup.
- Reconcile a registered worktree and its uniquely mapped local runtime.
- Move the durable packet to the finished lane and read back canonical state.
- Record every removal, no-op, skip, hold, and validation result.

## Out Of Scope

- Merge, deployment, release, QA, or tracker-close decisions.
- Host-wide/all-resource Docker, OrbStack, VM, container, volume, image, or
  network operations.
- Shared environment or LOS infrastructure teardown.
- Deleting durable work-item packets or their compact receipts.
- Removing external, primary, protected, reopened, unmerged, or ambiguously
  owned checkouts.

## Constraints

- Physical code-checkout removal requires explicit merged-PR proof.
- `REOPEN.md`, a residual hold, missing receipts, or failed teardown blocks
  completion and leaves the resource visible.
- Useful worktree-local evidence must be copied and hashed into the packet first.
- Physical worktree removal requires a clean `git status --porcelain`. Dirty
  work is always preserved; reconcile it through a separate operator workflow,
  then rerun Health after the checkout is clean.
- Filesystem changes must remain inside the owning project's managed paths.
- Health starts from existing state and never provisions replacement resources.
- Health is manual and exact-item scoped; scheduled or host-wide/all-resource
  Docker/OrbStack operations are out of scope.

## Acceptance Criteria

| Criterion | Evidence Required |
| --- | --- |
| Registry-only reconciliation is honest. | Routed terminal evidence, candidates, closed/skipped rows, and active-index readback; no `--remove-files` or Health completion. |
| Cleanup authority is trustworthy. | Completed typed Merge receipt; Health terminal authority exactly reuses its provider, PR reference, and merge SHA. |
| Work remains resumable. | Complete receipt audit and readable resume manifest written before cleanup. |
| Resource handling is bounded. | Separate worktree/runtime identities, preflight results, actions, and receipts. |
| Registry readback is durable. | Packet-local `auto-dev-closed-worktree-readback/v1`, audited under `resource_cleanup`, matches live `closed.yml` or records `not_managed`. |
| Durable state is finished. | Packet in `work-items/03-complete`, canonical state `finished`, cleared reconstructable pointers, and history receipt. |
| Active views are correct. | Readback shows the item absent from active indexes. |
| Nothing unsafe was hidden. | Validation passes and residual holds are empty; skipped resources retain an exact reason. |

## Health / physical stop conditions

- The merged pull request or its exact merge revision cannot be verified.
- The receipt audit is incomplete or the resume manifest cannot be preserved.
- Resource ownership is ambiguous, outside the managed root, or shared.
- `REOPEN.md` or another unresolved hold exists.
- Runtime teardown or Git worktree removal fails.
- A requested action would perform host-wide cleanup or delete durable evidence.

## Open Questions

- None for the manual workflow. A future automation may call the same contract,
  but must not weaken its gates or create a second lifecycle state machine.
