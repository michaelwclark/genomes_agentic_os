# `agentic-os develop`

Canonical entry point for one or many Agentic OS programming tasks.

```bash
# Plan only (default)
agentic-os develop start <domain> <project> <ticket> [<ticket> ...]

# Multi-repository project (repository.catalog + selection_required)
agentic-os develop start <domain> <project> <ticket> --repository <repository-id>

# Ticket/release-derived base and invocation policy addenda
agentic-os develop start <domain> <project> <ticket> \
  --base-branch <branch> --policy-overlay dev_standards=<file.md>

# Frozen Rules Engine context candidate (does not imply a loaded kit)
agentic-os develop start <domain> <project> <ticket> \
  --touched-path <repo-relative-path> --subject rulebook \
  --rulebook-id <exact-rulebook-key>

# Provision portfolio, one active work item, and one isolated worktree per task
agentic-os develop start <domain> <project> <ticket> [<ticket> ...] --apply

# Compact portfolio/task readback
agentic-os develop status <run-dir>

# Inspect an already registered successor; no provisioning or task write
agentic-os develop inspect-successor <task-state.json> \
  --worktree-id <exact-project-registry-id> --pull-request <existing-family-pr> --json

# Plan a same-task binding from an exact packet-contained proof capsule
agentic-os develop bind-successor <task-state.json> --request <capsule.json> \
  --expect-state-sha256 <raw-predecessor-sha256> --idempotency-key <stable-key> --json

# Apply or replay the same exact binding; fresh ordinary validation still required
agentic-os develop bind-successor <task-state.json> --request <capsule.json> \
  --expect-state-sha256 <raw-predecessor-sha256> --idempotency-key <stable-key> --apply --json

# Abandon a pending, unconsumed binding if its live source/runtime has advanced.
# Inspect the raw pending task locally for its SHA256; plan first, then add --apply.
agentic-os develop abandon-successor <task-state.json> \
  --expect-state-sha256 <raw-pending-sha256> --idempotency-key <stable-key> \
  --reason "Published successor advanced during an interrupted projection" --json
```

Project behavior comes from `config/development.yml`, the canonical code
settings file for projects in every domain. Repository, base branch, worktree
directory, branch template, and date-prefix inheritance are configured there.
Multi-repository projects declare a catalog and require explicit `--repository`;
the engine never guesses from the ticket. The program contract and
five complete workflow specifications live in
`harness/shared_factory/00-programs/development_delivery/` and
`harness/shared_factory/04-workflows/development_delivery/`.

Every run snapshots its dynamic Markdown policy planes:

```bash
agentic-os develop policy <domain> <project> --plane dev_standards --json
agentic-os develop policy <domain> <project> --plane qa_gates --json
agentic-os develop policy <domain> <project> --plane gitflow_topology --json
agentic-os develop policy <domain> <project> --plane auto_dev --json
agentic-os develop policy <domain> <project> --plane environment_access --json
```

The conventional folder order is root → domain → project. Projects may provide
an ordered 1-N path list in `config/development.yml`; adding a Markdown file is
picked up automatically on the next run.

Same-task successor binding preserves the original task, packet, receipt and
review-budget history. It requires independent native Git/registry/runtime/PR
and policy-delta proofs; neither a new branch name nor a caller's `verified`
flag establishes ownership. The real local branch and provider publication
branch remain distinct. A partial projection blocks consumers until exact-key
replay finishes, and a completed binding still requires fresh frozen-command
validation and new-epoch delivery receipts. See the same-task successor section
of `docs/42-auto-dev-program.md` and the closed binding and abandonment schemas.

If a legitimate push, provider update or container restart makes exact pending
replay impossible, `abandon-successor` provides a separate receipt-backed outbox.
It restores the immutable predecessor's source and policy authority, without
changing either worktree or granting test/review acceptance. Only this ticket's
owned portfolio and canonical pointers can be restored; unrelated rows and
metadata remain intact. Original receipts, attempts, leases and shared review
budgets remain unchanged, and abandonment receipts/events remain in history.
An interrupted abandonment stays fenced and resumes with its original key and
pending-state digest. A consumed or completed binding cannot be abandoned.

`--touched-path` and `--subject` are normalized and frozen in the effective
policy receipt. `--rulebook-id` is required to resolve an exact Rules Engine
catalog entry; a selector match without a usable catalog, concrete five-file
kit with matching ready headers, usable local snapshot, and available compact
known-findings receipt is recorded as `kit-unavailable` or
`insufficient-evidence`, never as a loaded kit.

Direct state transitions fail closed. Named workflow stages are the only normal
advancement route; failures, recovery, and leases remain receipt-backed:

```bash
agentic-os develop fail <state.json> --kind <classification> --detail <text> --receipt <ref> --idempotency-key <key>
agentic-os develop recover <state.json> --receipt <ref> --idempotency-key <key>
agentic-os develop heartbeat <state.json> --owner <worker> --idempotency-key <key>
```

Each delivery workflow also has a manual chat skill and a stage recorder:

```bash
agentic-os develop stage <state.json> --stage <readiness|implementation|review|release_propagation|merge|deploy|closeout> \
  --receipt <state>=<development-stage-evidence.json> ... \
  --idempotency-prefix <stable-key>
```

`stage` records work already performed by the named skill; it is not a provider
executor. It preflights every receipt before mutation. Each JSON file must use
`development-stage-evidence/v1`, match the target state, contain terminal
status, summary, structured evidence, and `verified_at`; PR, merge, deploy,
readiness, and completion states require their specific readback fields.
In particular, a completed `merged` receipt requires `merge_sha`, provider-read
`source_head_sha` equal to the reviewed `subject_revision`, `provider`,
`pull_request`, and `readback_verified: true`. See the Auto-Dev Merge template;
Health later reuses that provider, PR reference, and merge revision exactly.

Manual named stage skills are `/auto-dev-readiness`, `/auto-dev-develop`,
`/auto-dev-pr-create`, `/auto-dev-review-self`, `/auto-dev-merge`,
`/auto-dev-deploy`, and `/auto-dev-closeout`. Develop delegates to
`/auto-dev-implementation`, and Review Self delegates to
`/auto-dev-review-repair`; both preserve the same canonical delivery state.
`/auto-dev-release-propagation` is a compatibility alias for PR Create and its
lower-level `release_propagation` recorder. These routes also activate
implicitly from equivalent chat requests.

The friendlier operator facade is `agentic-os auto-dev`. It creates or resumes
the same delivery task and `<work-item>/autodev.json`; it never owns another
delivery transition engine.
