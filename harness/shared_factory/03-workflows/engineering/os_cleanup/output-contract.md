# Output contract: OS cleanup

Every mode records:

- scope and dry-run/apply mode;
- candidates, closed registries, removed resources, and skipped resources with
  reasons;
- validation/readback outcomes, residual holds, and the exact next action.

An explicitly non-code registry-only run also records its routed terminal
source evidence and active-index readback. It never emits Health completion or
a physical-removal receipt.

Health or physical code cleanup additionally records:

- typed `terminal_authority` derived from a completed Merge receipt containing
  `merge_sha`, provider-read `source_head_sha` equal to the reviewed
  `subject_revision`, `provider`, `pull_request`, and
  `readback_verified: true`; Health provider/ref/revision match it exactly;
- packet-relative `auto-dev-health-preflight/v1` reference and exact hash;
- packet-local `auto-dev-runtime-cleanup/v1` receipt whose
  `preflight_sha256` binds the runtime readback to that gate; for managed
  runtime it is domain/project/worktree identity-bound, at most 15 minutes old,
  and immediately re-executed with exit 0 meaning the exact runtime is absent;
- required/present/missing receipt inventory and resume-manifest reference;
- complete packet-manifest reference and hash; after relocation every file hash
  matches except validated semantic `work.yml` and `autodev.json` updates;
- a task-state SHA-256 whose parsed task is `delivery_complete` and exactly
  matches the item, worktree, branch, reviewed revision, and merge revision;
- packet Merge and Closeout snapshots that are JSON-equivalent to the canonical
  typed task receipts, plus a complete ordered non-Health stage audit with a
  verified hash for every stage snapshot;
- one `auto-dev-resource-cleanup/v1` receipt that atomically binds the exact
  worktree and runtime identities, results, and verified readbacks;
- one packet-local `auto-dev-closed-worktree-readback/v1` snapshot of the exact
  closed row or `result: not_managed`, audited under `resource_cleanup` and
  cross-checked with live `worktrees/closed.yml` for a managed entry;
- canonical work history receipt and packet old/new locations;
- active-index readback references;
- validation commands, outcomes, and durable receipts.

The final receipt inventory uses exactly these kinds: `terminal_authority`,
`closeout`, `receipt_audit`, `resume_manifest`, `packet_manifest`,
`resource_cleanup`, `runtime_cleanup`, `work_state`, `active_index`, and
`validation`.

Long logs stay in the work packet or run artifact, not in chat.
