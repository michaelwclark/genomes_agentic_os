# 37 · Governed Workflow Engine

> **Purpose:** give operator applications a versioned, round-trip-safe API for
> workflow definitions, immutable published versions, installed instances, and
> queue-only run requests.

The original workflow folder remains the human-readable procedure contract.
The Workflow Engine adds a machine-readable definition and governed mutation
boundary without turning the OS into a generic visual-programming runtime.

## Resource identities

The four resource kinds are intentionally distinct:

| Kind | Example identity | Meaning |
| --- | --- | --- |
| `workflow_definition` | `workflow_definition:work:engineering:release_review` | Editable authoring source in `.agentic-workflow.yml`. |
| `workflow_version` | `workflow_version:work:engineering:release_review:1.0.0:<hash>` | Immutable definition snapshot created by publish. |
| `workflow_instance` | `workflow_instance:work:engineering:release_review` | Installed pointer to the active published version. |
| `workflow_run` | `workflow_run:<hash>` | A run request. `run-now` initially records `queued` or `approval-needed`; it does not mean execution occurred. |

The API version is `workflow-engine/v1`. Canonical targets are derived only
from `domain`, `lane`, and workflow `id`. Mutation commands do not accept a
target path, shell command, provider query, or execution destination.

## Definition contract

A managed definition lives beside `workflow.md` as
`.agentic-workflow.yml`. The installed JSON Schema is
`harness/schemas/workflow-definition.schema.json`.

```yaml
schema_version: 1
resource_kind: workflow_definition
id: release_review
domain: work
lane: engineering
name: Release Review
summary: Review a release with explicit evidence and approval gates.
owner: OS Owner
availability: active
health: healthy
version: 1.0.0
inputs: {}
outputs: {}
approvals: []
retry:
  max_attempts: 1
  backoff_seconds: 0
failure_policy: stop
prompts: []
agents: []
models: []
linked_capabilities:
  - kind: skill
    id: pull_request
publish:
  allowed: true
execution:
  harness: agentic_os
steps:
  - id: collect_evidence
    name: Collect evidence
    summary: Collect bounded release evidence.
    order: 1
    kind: skill
    depends_on: []
    inputs: {}
    outputs: {}
    approvals: []
    retry:
      max_attempts: 1
      backoff_seconds: 0
    failure_policy: stop
```

Unknown top-level and step fields are allowed so newer producers can round-trip
through an older compatible editor. Update deep-merges mappings and merges
steps by ID. It refuses an update that silently omits an existing step; a future
schema migration must make destructive step removal explicit.

`execution.harness` is optional and allowlisted to `agentic_os`, `codex`, or
`claude`. It selects a governed queue destination; it never accepts a command,
path, URL, or arbitrary worker target.

## Query and read contract

```bash
agentic-os workflow query definition --domain work --lane engineering --json --root ~/agentic_os
agentic-os workflow query version --workflow release_review --json --root ~/agentic_os
agentic-os workflow query instance --health healthy --json --root ~/agentic_os
agentic-os workflow query run --workflow release_review --json --root ~/agentic_os

agentic-os workflow get definition release_review --domain work --lane engineering --json --root ~/agentic_os
agentic-os workflow get instance release_review --domain work --lane engineering --json --root ~/agentic_os
agentic-os workflow get version '<version-id>' --json --root ~/agentic_os
agentic-os workflow get run '<run-id>' --json --root ~/agentic_os
```

Definition queries include legacy workflow folders. A legacy folder without a
managed definition is returned as `source_state: partial`, `managed: false`,
and `editable: false`; the engine does not invent steps. An unreadable managed
definition is isolated as `source_state: invalid` instead of failing the whole
inventory.

Filters cover domain, lane, workflow, availability, health, owner, linked
capability, free text, archived state, and a bounded `--limit` of 1–500.

## Validation and field errors

```bash
agentic-os workflow validate --definition-file workflow.yml --json --root ~/agentic_os
```

Findings include `code`, `severity`, JSON-style `path`, `message`, and a
`step_id` when the finding belongs to a step. Validation checks schema fields,
duplicate IDs/orders, displayed order, missing or forward dependencies, and
cycles. Error findings return exit 1 and block create, update, publish, and run
queue requests.

## Governed create and update

Managed mutations are dry-run first. The plan returns
`drift.before`; apply requires that exact value through
`--expected-drift-hash`.

```bash
agentic-os workflow create --definition-file workflow.yml --dry-run --json --root ~/agentic_os
agentic-os workflow create --definition-file workflow.yml \
  --expected-drift-hash '<dry-run hash>' --apply --json --root ~/agentic_os

agentic-os workflow update release_review \
  --domain work --lane engineering --definition-file changes.yml \
  --dry-run --json --root ~/agentic_os
agentic-os workflow update release_review \
  --domain work --lane engineering --definition-file changes.yml \
  --expected-drift-hash '<dry-run hash>' --apply --json --root ~/agentic_os
```

Create can safely adopt an existing legacy workflow folder: it preserves all
human-authored files and adds only the managed definition. The historical
`agentic-os workflow create <domain> <lane> <name>` scaffold command remains
an immediate compatibility action.

Applied mutations create a fixed-location backup and receipt, perform canonical
readback, and restore exact prior bytes automatically if validation or readback
fails.

## Publish

```bash
agentic-os workflow publish release_review \
  --domain work --lane engineering --dry-run --json --root ~/agentic_os
agentic-os workflow publish release_review \
  --domain work --lane engineering \
  --expected-drift-hash '<dry-run hash>' --apply --json --root ~/agentic_os
```

Publish requires an error-free definition with `availability: active` and
`publish.allowed: true`. It writes an immutable version and atomically updates
the instance pointer. Re-publishing identical bytes is idempotent. Reusing a
semantic version for different content is refused.

## Run Now means queue now

```bash
agentic-os workflow run-now release_review \
  --domain work --lane engineering \
  --idempotency-key operator:release_review:2026_07_15 \
  --dry-run --json --root ~/agentic_os
agentic-os workflow run-now release_review \
  --domain work --lane engineering \
  --idempotency-key operator:release_review:2026_07_15 \
  --expected-drift-hash '<dry-run hash>' --apply --json --root ~/agentic_os
```

`run-now` appends an idempotent runtime queue record and a typed
`workflow_run` request. Its response always includes:

```yaml
dispatch_performed: false
execution_status: not_started
execution_contract: harness_worker_required
external_effects: local queue request only; no dispatch performed
```

The existing harness/runtime worker owns later execution and must write its own
terminal run evidence. The Workflow Engine never converts queue acceptance into
a false success claim.

## Rollback

Create, update, and publish receipts are reversible. Run requests are immutable
and not rollback receipts.

```bash
agentic-os workflow rollback '<receipt-id>' --dry-run --json --root ~/agentic_os
agentic-os workflow rollback '<receipt-id>' \
  --expected-drift-hash '<rollback dry-run hash>' --apply --json --root ~/agentic_os
```

Rollback accepts only a fixed workflow receipt ID, not a path. It refuses when
the current workflow state differs from the source receipt's after-hash, then
restores the exact definition/pointer/version bytes and verifies the prior
state hash.

## Operator application contract

An application should use this sequence:

1. `query definition` for the searchable list.
2. `get definition` for the full editor payload and current drift hash.
3. `validate --definition-file` for field/step findings.
4. `create` or `update` dry-run and display the returned plan.
5. Apply with the exact `drift.before` token.
6. Require `readback.ok: true` before showing the mutation as saved.
7. Publish separately; never conflate draft save with the live instance.
8. Treat `run-now` as queued/approval-needed until a worker supplies execution evidence.

This keeps the desktop editor thin: the source package owns schema validation,
identity, version immutability, drift checks, receipts, readback, and rollback.
