# Runbook: OS cleanup

## Choose the mode

- Auto-Dev Health or any physical code-worktree removal uses the full numbered
  runbook below: merged-PR proof, packet audit and preflight, runtime readback,
  all five cleanup inputs, atomic resource receipt, and finished-state readback.
- An explicitly non-code general OS Cleaner run may perform registry-only
  reconciliation from routed terminal evidence. It must omit `--remove-files`,
  never claim Health completion, and record candidates, closed/skipped rows,
  source evidence, and active-index readback in its general cleanup receipt.

Do not run registry-only apply before a planned physical apply; closing the row
would remove the exact target that the guarded physical command must select.

## Before Running

- Confirm the request names one existing item or an explicitly bounded candidate
  set. For Auto-Dev Health, require the existing `autodev.json` path.
- Load the owning root, domain, project, development, environment-access, and
  cleanup policies. Apply the strictest rule.
- For Health/physical mode, read canonical work state, the linked delivery task, the live merged pull
  request and exact merge revision, worktree registries, `REOPEN.md`, runtime definition, packet
  artifacts, and active-index projections.
- Confirm Closeout already proved `delivery_complete`. Cleanup does not decide
  merge or deployment truth.

## 1. Audit Before Mutation

1. Match work-item and repository to a completed typed Merge receipt. Require
   `merge_sha`, provider-read `source_head_sha` equal to the reviewed
   `subject_revision`, `provider`, `pull_request`, and
   `readback_verified: true`; Health terminal authority uses the same provider,
   pull-request reference, and merge revision.
2. Inventory every required receipt and build the full packet manifest. Store
   packet-relative references and SHA-256 digests; the missing list must be
   empty. The manifest covers every durable packet file outside Health output.
3. Copy any useful worktree-local evidence into the packet and verify its hash.
4. Write a plain-English resume manifest naming the final revision, key
   decisions, verification receipts, residual risk, resource identities, and
   recreation steps.
5. Run `agentic-os auto-dev health --state <state> --apply` and preserve the
   returned packet-local `auto-dev-health-preflight/v1` reference. It always
   records `clean_only`. Do not edit the preflight after reviewing it.
6. Stop if any receipt is unreadable, the merged pull request or exact merge
   revision is unverified, or a hold exists.

## 2. Preflight Exact Resources

Require all applicable facts before physical worktree removal:

- explicit merged-PR proof and exact revision;
- registered checkout inside the owning managed worktree root;
- not the primary checkout and not a default or protected branch;
- clean `git status --porcelain` with no tracked or untracked changes;
- no root `REOPEN.md` and no residual hold; and
- exact runtime identity uniquely mapped to this checkout.

If the checkout is dirty, stop. Preserve or reconcile the changes through a
separate operator workflow, make the checkout clean, then rerun Health to
create and review a fresh preflight. Copying evidence into the packet does not
waive the clean-status gate.

If a worktree or runtime never existed or is already gone, plan to record
`not_managed` or `absent`; do not invent a resource or use `not_required`.
Do not call a three-input dry-run an exact Health gate: the runtime receipt must
exist before the five-input cleanup dry-run can validate the full boundary.

## 3. Reconcile Item-Local Resources

1. Tear down only the runtime registered in the delivery task from the owning
   project's `config/development.yml`. Run its exact `teardown_command`, then
   its exact `readback_command`; do not invent a compose fallback.
2. Stop if teardown fails. Keep the worktree and registry entry visible.
3. After teardown/readback, write packet-local
   `auto-dev-runtime-cleanup/v1`. It must match the preflight's work item,
   canonical work id, runtime identity, ownership, and provider. A managed
   runtime uses `removed` or `absent`; an explicitly unmanaged runtime uses
   only `not_managed`. Set `readback_verified: true`; record `verified_at`; and set
   `preflight_sha256` to the SHA-256 of the exact preflight file. For a managed
   runtime, identity and commands contain domain/project/worktree. The receipt
   is newer than preflight and at most 15 minutes old; the physical gate runs
   readback again and accepts exit 0 only as proof that runtime is absent.
4. Exercise the full gate with the same five inputs intended for apply:

   The gate must first re-hash and parse `task_state_ref`, require
   `delivery_complete`, and match the exact item, worktree, branch,
   `subject_revision`, and `terminal_revision`. It then compares the packet
   Merge and Closeout snapshots with the canonical typed task receipts as JSON,
   validates their provider/PR/source-head/merge/Closeout fields, and verifies
   every row and packet-local hash in the complete ordered non-Health stage
   audit.

   ```bash
   agentic-os project worktree cleanup-closed \
     --domain <domain> --project <project> --worktree <exact-id-or-path> \
     --health-preflight <packet>/artifacts/auto-dev-health/preflight.json \
     --runtime-receipt <packet>/artifacts/auto-dev-health/receipts/runtime-cleanup.json \
     --root <os-root> --dry-run
   ```

5. Apply exact worktree cleanup only after that gated dry run is unchanged and safe:

   ```bash
   agentic-os project worktree cleanup-closed \
     --domain <domain> --project <project> --worktree <exact-id-or-path> \
     --health-preflight <packet>/artifacts/auto-dev-health/preflight.json \
     --runtime-receipt <packet>/artifacts/auto-dev-health/receipts/runtime-cleanup.json \
     --root <os-root> --apply --remove-files
   ```

6. Removal must use the exact Git worktree operation. Do not use force or run a
   separate Git metadata-sweep command. Close the registry entry only after
   physical removal succeeds.
7. Physical removal always requires all five selectors: domain, project, exact
   worktree, Health preflight, and runtime receipt.
8. Persist the final cleanup readback as one packet-local
   `auto-dev-resource-cleanup/v1` receipt. It must bind `preflight_ref` and the
   exact identity, result, and verified readback for both worktree and runtime.
9. Write a packet-local `auto-dev-closed-worktree-readback/v1` receipt with the
   exact closed registry row, or `result: not_managed`. Audit this file under
   `resource_cleanup`; for a managed entry, verify that its identity, path,
   terminal revision, and Health preflight reference match live
   `worktrees/closed.yml`.

Never run a host-wide/all-resource Docker, OrbStack, VM, container, image,
volume, or network operation. Never tear down shared LOS or other shared infrastructure. Health
is manual and exact-item scoped; do not schedule physical cleanup or widen it
beyond the selected item.

## 4. Finish the Durable Item

Move the filesystem packet before updating its canonical pointer:

```bash
agentic-os project work-item set <domain> <project> <packet-id> \
  --state finished --health-relocation \
  --note "Auto-Dev Health audit passed" --root <os-root>

agentic-os work set <canonical-work-id> --root <os-root> \
  --state finished --attention closed --packet-path <new-packet-path> \
  --clear-worktree --verified --receipt <history-receipt>
```

Refresh and read back the derived views:

```bash
agentic-os project work-item sync-active --root <os-root>
agentic-os work active-now --root <os-root>
agentic-os work show <canonical-work-id> --root <os-root>
agentic-os validate --root <os-root>
```

The packet must be readable in `work-items/03-complete`, canonical state must be
`finished` with closed attention, and the item must not appear in active views.
Every pre-cleanup packet hash must still match except semantic `work.yml` and
`autodev.json` state/path updates; parse and validate those two again.

## 5. Record Completion

For Auto-Dev Health, write strict `auto-dev-health-evidence/v1` from the moved
packet and record it against the existing state. Include packet-relative
`preflight_ref`; both `resources.*.receipt` values must point to the same atomic
`auto-dev-resource-cleanup/v1` receipt. `closed_worktree_registry_ref` must
point to the separately audited `auto-dev-closed-worktree-readback/v1` file:

```bash
agentic-os auto-dev record <completed-packet>/autodev.json \
  --stage health \
  --evidence <completed-packet>/artifacts/auto-dev-health/evidence.json \
  --idempotency-key <run-id:work-item:health>
```

Read back `autodev.json`. Completion requires accepted strict evidence, a
readable finished packet, no residual holds, and consistent state/index views.
The audit contains exactly `terminal_authority`, `closeout`, `receipt_audit`,
`resume_manifest`, `packet_manifest`, `resource_cleanup`, `runtime_cleanup`,
`work_state`, `active_index`, and `validation`. The packet is immutable after
completion; follow-up work uses a receipt-backed canonical reopen and new run.

## Failure Handoff

Keep the resource registered and the packet readable. Record the safe state,
failed gate, evidence reference, exact owner, and one next action. Do not retry a
destructive step without new evidence that addresses the failure.
