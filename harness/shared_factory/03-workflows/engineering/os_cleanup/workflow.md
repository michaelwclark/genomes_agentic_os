# Workflow: OS cleanup

## Purpose

Keep closed worktrees, target-local runtimes, work registries, and finished
packets aligned without deleting the durable evidence needed to understand or
resume a change. Auto-Dev Health uses this policy for one delivered item;
bounded general reconciliation may audit registry rows but cannot perform a
host-wide/all-resource physical operation or claim Health completion.

## Safe order

1. Refresh terminal tracker and pull-request truth. For physical code checkout
   removal, require a completed typed Merge receipt with `merge_sha`, provider-
   read `source_head_sha` equal to the reviewed `subject_revision`, `provider`,
   `pull_request`, and `readback_verified: true`; tracker status alone is not
   enough.
2. Copy and hash useful worktree-local evidence, audit required receipts, write
   a resume manifest and full packet manifest, and freeze a packet-local
   `auto-dev-health-preflight/v1` before removing anything.
3. Tear down or read back the exact item-local runtime and write
   `auto-dev-runtime-cleanup/v1` bound to the preflight SHA-256. Its identity
   and commands contain domain/project/worktree. The receipt is newer than the
   preflight and at most 15 minutes old; the gate immediately runs readback
   again and accepts exit 0 only as proof that exact runtime is absent.
4. Run completion and worktree cleanup dry-runs with exact domain, project,
   worktree, preflight, and runtime-receipt inputs. The gate parses the hashed
   canonical task, compares packet Merge/Closeout snapshots with its typed
   receipts, and verifies the complete ordered non-Health stage audit and every
   stage snapshot hash. A root `REOPEN.md`, missing
   verified merged-pull-request proof or exact merge revision, external path,
   primary/protected branch, or residual hold blocks physical removal and
   leaves the registry entry active.
5. Match the exact registered worktree id/path/branch and require a clean
   `git status --porcelain`. A dirty checkout remains in place
   until a separate operator workflow reconciles it and Health is rerun with a
   fresh preflight. Also require current checkout `HEAD` to equal the provider-
   read reviewed `subject_revision`; a clean later commit blocks removal.
6. Apply guarded cleanup to remove only the eligible linked checkout with
   `git worktree remove`. Do not run a repository-wide metadata sweep. Close
   the registry entry only after exact removal succeeds.
7. Persist one `auto-dev-resource-cleanup/v1` receipt that atomically binds
   both resource identities, dispositions, verified readbacks, and the
   preflight reference.
8. Write `auto-dev-closed-worktree-readback/v1` with the exact closed registry
   row or `result: not_managed`. Audit it under `resource_cleanup`; a managed
   entry must match live `worktrees/closed.yml`.
9. Move the filesystem packet into `work-items/03-complete`, then mark
   canonical work `finished`, update its packet path, clear its reconstructable
   worktree/branch pointers, and refresh active indexes. Recheck every
   pre-cleanup packet hash; only semantic `work.yml` and `autodev.json`
   state/path updates may differ, and both must parse again.
10. Validate and read back work state, packet state, closed registry state, and
   active projections. Preserve compact receipts and any skip reason.

## Never do

- No host-wide/all-resource Docker, OrbStack, container, volume, image,
  network, or VM operation.
- No shared LOS infrastructure teardown.
- No deletion outside the owning project's managed worktree root.
- No physical removal on `QA Ready`, `Done`, or another tracker status without
  independent merge proof for code work.
- No physical removal of a dirty or untracked checkout, even when useful
  changes were copied elsewhere.
- No archive-before-removal behavior that hides a failed or reopened checkout.
- No scheduled Health cleanup or host-wide/all-resource physical operation.

## Completion

Cleanup is complete only when every expected resource is `removed`, `absent`,
or `not_managed`; the preserved packet is finished and readable; active indexes
exclude it; the packet-local closed-worktree readback matches live registry
state; required receipts are present and hashed; validation passes; and no
residual hold remains.

The final audit has ten exact kinds: `terminal_authority`, `closeout`,
`receipt_audit`, `resume_manifest`, `packet_manifest`, `resource_cleanup`,
`runtime_cleanup`, `work_state`, `active_index`, and `validation`. Finished
packets are immutable; follow-up work uses a receipt-backed canonical reopen
and a new delivery run.
