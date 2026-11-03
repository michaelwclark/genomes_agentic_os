# Forward validation reconciliation

An older delivery task can retain valid historical identity while lacking the
metadata needed by the modern validation refresh operation. Reconciliation adds
current evidence to that same task. It preserves the original task, worktree,
frozen policy, receipts, timestamps, failures and review charges.

The owner is `development_validation_reconciliation.py`. The CLI is a thin
adapter. Ordinary `TaskState.read()` continues returning historical task fields;
PR creation and review explicitly resolve current action authority.

## Boundaries

| Operation | Behavior |
| --- | --- |
| `inspect` | Read original custody, canonical review history and current policy. Adopt nothing. |
| `plan` | Check the exact predecessor, current owner, registered source, current action policy and genuine project proof. Write an optional new plan artifact. |
| `apply` | Preview by default. With `--execute`, lock, recheck the exact plan, append current authority and refresh the owning projections. |

This operation accepts an active task at `local_validation` or `pr_open`, its
existing canonical packet/run linkage and an unexpired
owner lease. It retains that milestone and does not rewind it,
insert an old implementation stage, replace a run or mark historical deferred
validation as passed. Repository/base correction and implementation-context
continuation remain separate capabilities.

## Required project adapter

The current selected project validation policy must opt in explicitly:

```yaml
validation:
  reconciliation:
    adapter: configured-command-proof/v1
    actions: [pr_create, review]
    max_age_seconds: 3600
    claims: [configured_commands_only]
```

The built-in adapter proves only the complete ordered configured commands under
the existing native command, interpreter/dependency, source and timestamp
checks. A caller-set `passed`, `readback_verified` or percentage cannot replace
those checks. The adapter does not qualify native full95, source-scope
completeness, migration child processes, browser behavior or customer acceptance.
Unsupported launchers and unqualified Python closures retain their existing
refusal behavior. There is no fallback to trusting JSON or relaxing execution
provenance. A project needing additional native qualification requires a
separately implemented and reviewed proof adapter; absence or an unsupported
adapter refuses adoption.

The project proof uses `development-reconciliation-project-proof/v1`. It binds
the task path, ticket, run and work identity, repository, current worktree/branch,
head/tree, current policy fingerprint/hash, actual verification time, exact
allowed claims and the native `validation_runs` bindings. The native artifacts
must be contained in the existing packet. Original selection or native coverage
requirements cannot be inferred from this command-only adapter.
Its `profile_sha256` binds the complete current selected profile and source
configuration bytes. The action policy extends the standard selected-profile
authority with that digest and uses the existing canonical fingerprint and
validation primitives. Thus a review-setting change also changes exact review
identity when the five planes and source HEAD are unchanged. Historical policy
snapshots stay untouched; changed configuration requires fresh evidence.

## Operator flow

Use the same command from Claude, Codex or a normal terminal. Never edit the
produced historical receipts to make a request eligible.

```bash
agentic-os develop reconcile-validation inspect /path/to/task/state.json --json
agentic-os develop reconcile-validation plan /path/to/task/state.json \
  --request /path/to/packet/request.json --idempotency-key current-validation-1 \
  --output /path/to/packet/plan.json --json
agentic-os develop reconcile-validation apply /path/to/task/state.json \
  --plan /path/to/packet/plan.json --plan-sha256 <exact-plan-sha256> --json
```

The final example is read-only. Add `--execute` only for an authorized adoption
of that exact reviewed plan. Runtime installation, activation and adoption on a
live task are distinct governed actions.

The request schema is `development-validation-reconciliation-request/v1`. It
contains the exact `predecessor_sha256`, current lease `owner`, registered
`worktree` record, expected `current_policy_fingerprint`, hash-bound
`project_proof`, and SHA-256 hashes of the inspected `historical_files` and
`review_history` mappings. Mapping hashes use sorted, two-space-indented JSON
with a final newline. A changed receipt, source, policy, owner, lease, review
reservation or predecessor makes the plan stale.

## History, concurrency and recovery

Apply appends a `development-validation-reconciliation/v1` record and a receipt
with kind/state `validation_reconciliation`. The new validation artifact names
its actual stage `validation_reconciliation`; it never pretends to be an old
implementation receipt. Original task fields and receipt rows remain unchanged.
Content-addressed snapshots retain the original task bytes, accepted plan and
current policy, including raw configuration bytes. The task event binds the
actual acceptance time.
For an original receipt row without a recorded hash, the plan binds its present
file bytes without inserting a hash or timestamp into that historical row.
Missing original files or task-event history refuse reconciliation.
Canonical tracker identity markers and the existing packet/worktree directory
references are metadata-only rows, as they are in ordinary Development Delivery.
The plan names their body-proof gaps explicitly and preserves their exact rows;
it does not traverse directories or claim fresh provider validation from them.

The task lock and relevant original review-family locks guard apply. A busy family or
changed plan refuses without adopting authority. Exact replay adds no second
reconciliation event or review charge and repairs a failed owning projection.
Unmerged source and failed attempts remain intact. An output symlink, escaped
path or conflicting immutable snapshot refuses before the task commit.

The canonical review root and original receipt/index/attempt/tombstone bytes are
preserved. The command does not grant a new review allowance. An exhausted task
family or chain requires its separate audited recovery; a changed source head,
policy or reconciliation key cannot reset its counters.

Complete repository ledger bytes remain bound, while capacity uses trusted
canonical task/PR-family lineage. Hash-bound task PR receipts and native review
requests belonging to a verified canonical packet establish ownership. Valid
unrelated tasks retain their charges without spending this task's capacity.
Unattributed or unsupported lineage refuses explicitly. Provider repository
identity comes from the actual Git remote; a catalog alias cannot hide charges.
The current adapter supports GitHub provider identity and refuses unsupported
providers. The bounded inspection also refuses unidentified, redirected or
oversized history. It never creates a fresh budget namespace.
Catalog selection and provider identity remain separate. Review compares the
actual provider against the proven Git remote, while retaining the original
native review subject, family key, lock and counters. Potential alias-named
history is preserved and must have proven ownership. Conflicting native
namespaces for one provider PR refuse rather than open a new allowance.
The canonical work projection consumes source identity without requiring an
additional execution action; a review-only proof never grants PR Create.

## Ordinary source repairs

After review or CI repairs, execute fresh required validation and create a new
request and plan artifact for the same task. The plan binds the exact current
task bytes and latest accepted reconciliation. Apply appends the successor;
every prior record, configuration/policy snapshot, receipt row and event prefix
remains immutable. The new source must descend from the previously accepted
source. Legitimate later canonical receipt appends are retained.

Only the latest accepted record supplies current action authority. Replaying an
older exact plan returns `replayed: true` and `superseded: true`, together with
the qualified latest authority. It adds no event or charge and cannot reactivate
an older head. If current evidence is stale, replay refuses rather than revive
it. Two successor plans built from one predecessor admit only one.

Later `ready_for_merge` head replacement and policy-only same-head PR refresh
remain unsupported and refuse explicitly. The original milestone stays intact;
the current-action projection marks stale or missing source/review as pending.
A completed historical Review stage cannot return no-op current readiness.

`autodev.json` keeps the original delivery policy/worktree and adds
`delivery.current_action_authority`. Its Develop projection references the new
accepted validation artifact. The owning work registry projects the explicitly
selected current worktree. PR creation must name that exact current source and
policy; review must retain the same canonical receipt root. Stale current
evidence is rejected even though its historical acceptance remains auditable.
The executable opposing-review consumer selects the accepted current worktree
and canonical current PR Create readback, names the reconciliation explicitly,
and binds the current policy while preserving prior review-request bytes. It
continues using the original canonical review coordinator and budget ledger.

## Validation and release

The regression suite uses actual governed commands and canonical writer/CLI
consumers in temporary OS/project roots. It covers historical conservation,
substitution/refusal, stale and concurrent apply, duplicate idempotency and
projection repair. Run focused tests first, then the normal Python 3.14
branch-coverage gate and isolated package/CLI checks described in
[the coverage contract](43-python-coverage-gate.md). A source or package pass
does not activate a runtime or qualify a live application.
