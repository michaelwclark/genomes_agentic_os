---
name: auto-dev-health
description: Audit final Auto-Dev receipts and the complete durable packet, remove only the exact registered reconstructable worktree and runtime, and move the packet to finished after delivery is verified.
---

# Auto-Dev Health

Use this after Closeout. Closeout proves and reconciles delivery; Health keeps
the local operating system tidy without deleting the durable history needed to
understand or resume the work.

Health is safe to run when there is nothing left to remove. In that case it
records `absent` or `not_managed` dispositions after completing the same audit.
It is not a replacement for merge, deployment, or Closeout.

## Start from existing state only

Run Health against an existing work item:

```bash
agentic-os auto-dev health --state <work-item-or-autodev.json> --apply
```

Do not provide a new ticket as a substitute for `--state`. Health must never
create or provision a packet, worktree, branch, container, or runtime.
This command writes the packet-local receipt audit, resume manifest, and
`artifacts/auto-dev-health/preflight.json`. It deliberately stops before
runtime or worktree deletion. Treat that preflight as an immutable cleanup
gate; if its inputs change, generate and review a new one.

The physical cleanup gate re-proves the preflight instead of trusting its
`safe_to_cleanup` flag. It hashes and parses the linked Development Delivery
task, requires `delivery_complete`, and matches the exact work item,
repository/base, registered worktree id/path/branch/current HEAD, reviewed
revision, and merge revision. It compares the packet's Merge and Closeout
snapshots with the canonical typed task receipts as JSON, validates their
provider/PR/repository/base/authorship/revision fields, and requires the complete
ordered pre-cleanup audit for every Auto-Dev stage before Health.

Health also creates `auto-dev-packet-manifest/v1` before cleanup. It hashes
every required packet file, every file declared by `work.yml`, and every other
durable packet file outside Health's own output. It proves `artifacts/`, `logs/`,
and `logs/conversations/` exist. The destructive gate rechecks all of those
hashes. After the finished-lane move, every hash must still match except
`work.yml` and `autodev.json`; those two may change only for semantic
state/location relinking and are parsed and validated again.

Health always writes `dirty_disposition: clean_only`. A dirty checkout is
preserved and blocks physical removal. No receipt, filename, generated-file
classification, or merged pull request can waive this gate. Preserve or
reconcile dirty changes in a separate operator workflow, verify a clean
`git status --porcelain`, then rerun Health and review a fresh preflight.

The linked delivery task must already contain the exact runtime registration
resolved from the owning project's `config/development.yml`. Managed entries
name the provider, identity, teardown command, and readback command. Projects
without a per-worktree runtime must explicitly register
`ownership: not_managed`, `provider: none`, and `identity: not-managed`. Missing
runtime state is a blocker; never turn it into `not_managed` after the fact.

## 1. Prove cleanup is allowed

Read `autodev.json`, the linked Development Delivery task, the canonical work
registry row, project cleanup policy, and live pull-request merge proof. Before any
mutation, require all of the following:

- canonical delivery state is `delivery_complete`;
- a completed typed Merge receipt contains `merge_sha`, provider-read
  `source_head_sha` exactly equal to the reviewed `subject_revision`,
  `provider`, `pull_request`, configured `repository`, configured `base_branch`,
  provider-qualified `author_identity`, derived `author_kind`, and
  `readback_verified: true`;
- `pr_open`, readiness, and Merge receipts identify the same provider, pull
  request, repository, base branch, and author. The author classification comes
  from the frozen `task.authorship.ours` list, never from a caller assertion;
- every earlier required applicable stage is `completed` or policy-backed
  `not_required`, with readable receipt references;
- final QA, provider readback, Merge, Deploy or deployment-not-required, and
  Closeout evidence is present as applicable;
- the packet has no root `REOPEN.md` and no unresolved residual hold.

Build a receipt audit that names every required receipt and records its kind,
reference, and SHA-256 digest. Its `missing` list must be empty and
`resume_ready` must be true. Missing receipts, unverified merged-PR proof,
`REOPEN.md`, or an unresolved hold blocks Health before resource cleanup.

The ten exact required kinds are `terminal_authority`, `closeout`,
`receipt_audit`, `resume_manifest`, `packet_manifest`, `resource_cleanup`,
`runtime_cleanup`, `work_state`, `active_index`, and `validation`.

## 2. Write the resume manifest before cleanup

Write a durable resume manifest inside the work-item packet. Keep it compact
and plain English. It must identify:

- the work item, source ticket, domain, project, repository, and final revision;
- tracker, pull request, merge, release, deployment, QA, and Closeout receipts;
- the final decision, known follow-ups, residual risk, and why cleanup is safe;
- the exact worktree and target-local runtime identities;
- how a future agent can recreate a worktree or runtime without guessing; and
- the receipt-audit reference and cleanup plan.

Preserve `autodev.json`, Markdown packet files, `artifacts/`, and `logs/`. Move
useful receipts out of a worktree-local `.features/` folder and into the packet
before removing the checkout. That evidence copy does not make dirty work
disposable: the checkout must still be clean before physical cleanup. Never
place secrets in the manifest.

## 3. Delegate scoped cleanup to OS Cleaner

Use `$os-cleaner` and its canonical `os_cleanup` workflow. Always inspect the
dry run first. Cleanup is limited to resources proven to belong to this work
item:

1. Verify the worktree is under the owning project's managed `worktrees/`
   root; matches the registered id, path, and branch; is not a default or
   protected branch; has verified merged-PR proof; has a clean
   `git status --porcelain`; has current `HEAD` exactly equal to the
   provider-read reviewed `subject_revision`; and has no `REOPEN.md`.
2. Tear down only the runtime registered for that checkout, using the exact
   project-configured teardown command. A managed runtime identity template
   must include `{domain}`, `{project}`, and `{worktree}` so it is globally
   item-unique. Both registered commands must contain the rendered runtime
   identity. Run the exact registered readback command afterward. Do not invent
   or substitute a compose command.
3. Close the known worktree registry entry and remove the reconstructable
   checkout only when the reviewed cleanup decision permits physical removal.
4. Record resource identity, preflight facts, action, result, and receipt for
   the worktree and runtime independently.

Before physical removal, tear down or read back the exact target-local runtime
and write a packet-local `auto-dev-runtime-cleanup/v1` receipt. It must name the
same work item, canonical work id, runtime identity, ownership, and provider as
the preflight. A managed runtime records only `removed` or `absent`; an
explicitly unmanaged runtime records only `not_managed`. Set
`readback_verified: true`; include a verification time; and bind itself to the exact preflight bytes with
`preflight_sha256`. Even a no-runtime outcome needs this receipt.

The runtime receipt must be newer than the preflight and no more than 15
minutes old. Immediately before worktree removal, the physical gate executes
the same registered readback again from the canonical repository root. Exit 0
means the exact registered worktree runtime is absent; any other exit status,
timeout, or execution error blocks removal.

Never use `--force`, run a repository metadata sweep, invoke a host-wide
container/volume/image/network/VM/OrbStack cleanup, select all resources, guess
an identity, or touch a shared runtime. Never delete an external checkout or a runtime that cannot be
mapped uniquely to this work item. A dirty checkout always blocks physical removal.
Preserve or reconcile its changes in a separate operator workflow, make it
clean, and rerun Health. A merged pull request alone never waives this gate, and
`REOPEN.md` always blocks removal.

Use the exact worktree id or path from the linked delivery task for both the
dry run and apply. A Health run never uses an unscoped cleanup sweep:

```bash
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
```

Physical removal is invalid unless all five item-scoping inputs are present:
`--domain`, `--project`, `--worktree`, `--health-preflight`, and
`--runtime-receipt`. Persist the final readback as one packet-local
`auto-dev-resource-cleanup/v1` receipt that binds `preflight_ref` and both the
worktree and runtime identities, dispositions, and verified readbacks. The two
final Health resource entries must reference this same atomic receipt.

## 4. Finish the durable work item

After resource cleanup, move the filesystem packet into
`work-items/03-complete/`, rather than deleting or rebuilding it. Then update
canonical work state with the moved packet path, clear the reconstructable
worktree/branch pointers, and record the verified history receipt. Record both
the old and new packet paths.

Relocation is not permission to rewrite history. Recheck the pre-cleanup packet
manifest from the new location. Every durable file must retain its exact hash
except `work.yml` and `autodev.json`; only those two may receive the expected
finished-state/path updates, and both must parse and validate afterward.

```bash
agentic-os project work-item set <domain> <project> <packet-id> \
  --state finished --health-relocation \
  --note "Auto-Dev Health audit passed" --root <os-root>
agentic-os work set <canonical-work-id> --root <os-root> \
  --state finished --attention closed --packet-path <new-packet-path> \
  --clear-worktree --verified --receipt <history-receipt>
```

Refresh and read back both active-work projections:

```bash
agentic-os project work-item sync-active --root <os-root>
agentic-os work active-now --root <os-root>
agentic-os work show <work-item-id> --root <os-root>
agentic-os validate --root <os-root>
```

The item must be absent from active indexes, present as `finished`, and readable
from its completed packet. Preserve validation results and exact receipt
references; do not paste long cleanup logs into chat.

`--health-relocation` is mandatory for this move. It updates the packet's
state-bearing metadata and lane but deliberately does not append to packet-local
`WORKLOG.md` or `NEXT.md`, so the manifest made before cleanup remains valid.

The completed packet is immutable. A later QA or support change first reopens
the canonical work item through the explicit command below. It writes a durable
reopen receipt into one new active packet, then starts a new delivery run with a
fresh worktree and runtime registration:

```bash
agentic-os auto-dev reopen --state <finished-packet-or-autodev.json> \
  --run-id <new-run-id> --reason "<QA or support reason>" --stage qa \
  --root <os-root> --apply
```

Never edit the completed packet, run `agentic-os work set` as a substitute for
reopen, or silently reactivate its retired resources. Development Delivery
rejects a nonterminal canonical row that still points at `03-complete`.

## 5. Record strict Health evidence

The completed `auto-dev-health-evidence/v1` document must name the exact
`work_item_id`, keep `subject_revision` equal to the provider-read reviewed PR
head used by QA and Finalize, and store the typed provider-verified merge SHA
separately as `terminal_revision`. Its
structured evidence must include:

- `receipt_refs` for the durable audit, resume manifest, cleanup, lifecycle,
  index-readback, and validation receipts;
- `preflight_ref` for the packet-relative `auto-dev-health-preflight/v1` gate
  consumed by runtime teardown and physical worktree cleanup;
- `terminal_authority` with kind, provider, reference, revision, and verification
  time. Its kind is always `pull_request_merge`; its provider and reference
  exactly equal the typed Merge receipt's `evidence.provider` and
  `evidence.pull_request`, and its revision equals `evidence.merge_sha`. Health
  does not accept a tag, deployment, manual assertion, renamed reference, or
  other substitute for that provider-read merged pull request;
- `receipt_audit` with all ten canonical kinds (`terminal_authority`,
  `closeout`, `receipt_audit`, `resume_manifest`, `packet_manifest`,
  `resource_cleanup`, `runtime_cleanup`, `work_state`, `active_index`, and
  `validation`), present entries containing kind, work-item-relative reference,
  and SHA-256, plus `missing: []` and `resume_ready: true`;
- `resources.worktree` and `resources.runtime`, each with identity, preflight,
  action, result, and the same atomic `auto-dev-resource-cleanup/v1` receipt;
- `work_state` with canonical work id, before/after state, history receipt, and
  old/new packet paths;
- packet-local audited readback copies in `closed_worktree_registry_ref`,
  `active_index_refs`, and `validation_results`, plus `residual_holds: []`.
  `closed_worktree_registry_ref` uses
  `auto-dev-closed-worktree-readback/v1`, is audited under
  `resource_cleanup`, and contains the exact closed registry row or
  `result: not_managed`; a managed row is cross-checked with live
  `worktrees/closed.yml`.

Valid resource dispositions are `removed`, `absent`, and `not_managed`.
`not_required` is not a valid Health outcome: even a no-op cleanup must complete
the audit and readback.

Record from the moved packet so delivery pointers are safely relinked:

```bash
agentic-os auto-dev record <completed-packet>/autodev.json \
  --stage health \
  --evidence <completed-packet>/artifacts/auto-dev-health/evidence.json \
  --idempotency-key <run-id:ticket:health>
```

Read back Auto-Dev state after recording. Health is complete only when its
strict evidence is accepted, the whole packet remains readable, and the item
no longer appears active.

No schedule or host-wide/all-resource mode is enabled by this skill. Future monitoring
may invoke this exact item-scoped workflow repeatedly, but it must reuse the
same state and safety gates.
