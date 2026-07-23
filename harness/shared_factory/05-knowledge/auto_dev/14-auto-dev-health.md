# Auto-Dev: health

Use `/auto-dev-health` after Closeout to keep completed Auto-Dev work from
leaving permanent worktrees or target-local runtimes behind. Health is the final
Auto-Dev stage. Closeout proves delivery and reconciles providers; Health audits
the durable record, preserves a resume path, and performs lifecycle hygiene.

Health always starts from an existing `autodev.json`. It never creates or
provisions anything. Before cleanup it verifies `delivery_complete` and a
completed typed Merge receipt containing `merge_sha`, provider-read
`source_head_sha` equal to the reviewed `subject_revision`, `provider`,
`pull_request`, configured `repository`, configured `base_branch`,
provider-qualified `author_identity`, derived `author_kind`, and
`readback_verified: true`, plus
applicable stage receipts, and the absence of
`REOPEN.md` or residual holds. It writes a receipt audit and a plain-English
resume manifest into the packet before removing reconstructable resources.
The command also writes `auto-dev-health-preflight/v1` and stops before
resource deletion. Treat that file as immutable.

In plain English, Health has three responsibilities: prove the packet can be
trusted and resumed, remove only the exact clean item-owned resources that are
safe to reconstruct, and preserve the finished packet as immutable history. A
missing receipt, dirty checkout, ambiguous runtime, reopen/hold marker, failed
readback, or mismatched identity stops cleanup. Health never broadens a cleanup
selector to make the run pass.

Guarded cleanup re-opens and hashes the task state. It requires
`delivery_complete` plus exact item, worktree, branch, reviewed-revision, and
merge-revision matches. Packet Merge and Closeout snapshots must be JSON-
equivalent to the canonical typed task receipts and pass their field checks.
The immutable packet-local task snapshot remains the replay receipt after the
live task pointer is relinked from the active lane to the finished lane.
The pre-cleanup audit must list every non-Health Auto-Dev stage in canonical
order, use only `completed` or policy-backed `not_required`, and retain a valid
packet-local hash for each stage snapshot.

Health also writes a complete `auto-dev-packet-manifest/v1`. It hashes every
required and `work.yml`-declared file plus every other durable packet file
outside Health's own output, and proves the artifact/log directories exist.
The destructive gate rechecks every pre-cleanup hash. After relocation, only
`work.yml` and `autodev.json` may change for the semantic finished-state/path
update; both are parsed again, and every other file must still match exactly.

Health always records `dirty_disposition: clean_only`, so a dirty checkout is
preserved and blocks physical cleanup. There is no dirty-checkout exception.
Copy useful evidence into the durable packet, reconcile the changes through a
separate operator workflow, verify a clean `git status --porcelain`, then rerun
Health with a fresh preflight. Merge state alone never authorizes deleting
dirty changes.

Runtime ownership comes from the project's `config/development.yml`; Health
never guesses it from container names or from the existence of a worktree. A
project with no per-worktree runtime declares:

```yaml
runtime:
  ownership: not_managed
  provider: none
  identity: not-managed
```

A project-owned runtime declares `ownership: managed`, its provider, an
`identity_template` that includes `{domain}`, `{project}`, and `{worktree}`, and
exact identity-bound `teardown_command` and `readback_command` values. The
three-part identity prevents one item's Health run from tearing down a shared
runtime. Development Delivery resolves
that declaration when it creates the
worktree and stores the exact registration in the task. A missing or malformed
registration blocks Health. `not_managed` means the project explicitly owns no
runtime for the item; it never means "the agent did not look."

Cleanup delegates to `$os-cleaner`. It may remove only a verified closed
worktree under the owning project's managed worktree root and that worktree's
explicitly registered target-local runtime. Run only the registered teardown
and readback commands; do not invent a compose fallback. Unknown, external,
reopened, unmerged, or ambiguously owned resources
remain untouched and block completion when they are expected to be cleaned.
The checkout id, path, branch, and current HEAD must match the registered task;
it must be clean, and HEAD must equal the provider-read reviewed
`subject_revision`. A later clean local commit blocks removal.
Before physical worktree removal, write a packet-local
`auto-dev-runtime-cleanup/v1` readback for the exact runtime and bind
`preflight_sha256` to the Health preflight. Then call guarded cleanup with the
exact domain, project, worktree, preflight, and runtime receipt. Preserve one
`auto-dev-resource-cleanup/v1` receipt that atomically records verified final
dispositions for both the worktree and runtime.

The runtime receipt must be newer than the preflight and no more than 15
minutes old. The cleanup gate immediately executes the registered readback
again from the canonical repository root. Exit 0 means the exact registered
worktree runtime is absent; any other exit, timeout, or execution failure blocks
worktree removal. Do not use `--force`, run a Git metadata sweep or host-wide
container/volume/image/network cleanup, select all resources, guess an
identity, or touch a shared runtime.

### LOS fast-worktree readback

The LOS Django fast-worktree provider has additional durable data on shared
infrastructure: `los_<slug>` in Postgres and the `los-<slug>:*` namespace in
both Redis and Valkey. Its project config must call the source-owned
`harness/bin/agentic-os-los-fast-worktree-health.py` wrapper for both teardown
and readback, using the full `{domain}-{project}-{worktree}` runtime identity,
exact worktree path, and the same frozen identity in `AUTO_DEV_RUNTIME_ID`.

The wrapper validates that identity against `los/los_app_los_django`, the Git
worktree, registry row, and `.env.worktree`; delegates only the existing
target-local `down.sh`; then independently proves the exact compose project,
including its containers and exact project-labeled or project-prefixed networks
and volumes, plus the database, both cache namespaces across every configured
logical cache database, registry row, and env file are absent. Shared
Postgres, Redis, and Valkey must all be running and queryable. If any is down,
teardown/readback fails because absence is unknowable. Never use a negated
`status.sh | grep <slug>` as Health proof: when shared infra is down, status
cannot enumerate databases and that grep can falsely report success while DB
or cache residue remains.

The current fast-worktree compose file uses bind mounts and the external
`los-infra_network`; it declares no item-owned named volumes. The wrapper never
selects that shared external network. Any network or volume carrying the exact
Compose project label or `los-<slug>_` prefix is unexpected target-local residue
and blocks Health. Docker network/volume enumeration failure also blocks. The
wrapper observes these resources but does not broaden teardown into a volume,
network, or host-wide prune.

The copyable runtime mapping lives at
`harness/shared_factory/00-programs/auto_dev/config/examples/los/los_app_los_django/development-runtime.yml`.
Replace its Agentic OS root sentinel before merging it into the installed
project config. A config update affects newly registered tasks; do not silently
rewrite an already frozen task runtime during Health.

The durable packet is never deleted. Preserve its Markdown, `artifacts/`,
`logs/`, and `autodev.json`; transition it to `finished` in
`work-items/03-complete/`; refresh the active indexes; validate; and read back
the completed packet. Record strict Health evidence from the moved packet with
the exact terminal revision, receipt inventory, resource actions, work-state
history, active-index receipts, validation results, and no residual holds.

The inventory has ten exact kinds: `terminal_authority`, `closeout`,
`receipt_audit`, `resume_manifest`, `packet_manifest`, `resource_cleanup`,
`runtime_cleanup`, `work_state`, `active_index`, and `validation`.

When no worktree or runtime exists, Health still audits and records an `absent`
or `not_managed` disposition. Missing receipts or merged-PR proof are blockers,
never successful cleanup.

The Health evidence field is named `terminal_authority`, but version 1 accepts
only `kind: pull_request_merge`. Tags, deployments, manual assertions, and
other terminal-looking events do not authorize Health cleanup. Its provider
and reference must exactly equal the Merge receipt's `provider` and
`pull_request`; its revision and top-level `terminal_revision` must equal the
Merge receipt's `merge_sha`. Top-level `subject_revision` remains the reviewed
pull-request head and must not be overwritten with the merge SHA.

Health is manually callable and carries no schedule or host-wide/all-resource mode. A
later automation may reuse this exact item-scoped workflow, state projection,
and strict evidence contract.

Once recorded, the finished packet is immutable history. A QA follow-up uses a
receipt-backed canonical work-item reopen and a new delivery run/worktree/
runtime:

```bash
agentic-os auto-dev reopen --state <finished-packet-or-autodev.json> \
  --run-id <new-run-id> --reason "<QA or support reason>" --stage qa \
  --root <os-root> --apply
```

The command never rewrites the old packet or silently reuses retired resources.

Use the schema-valid field guides in `examples/` in lifecycle order:

1. `auto-dev-health-preflight.json` freezes the pre-cleanup gate.
2. `auto-dev-runtime-cleanup.json` records target-local runtime readback and the
   exact preflight digest.
3. `auto-dev-resource-cleanup.json` records both resource dispositions in one
   atomic receipt.
4. `auto-dev-closed-worktree-readback.json` snapshots the exact live
   `worktrees/closed.yml` row, or records that the item had no managed worktree.
5. `auto-dev-health-evidence.json` assembles the final audited Health result.

The closed-worktree readback is audited under `resource_cleanup`; when it
contains an entry, final Health compares its identity, path, terminal revision,
and preflight reference with the live closed registry. Replace every sample
identity, revision, timestamp, digest, command, path, and reference with durable
evidence from the actual work item.
