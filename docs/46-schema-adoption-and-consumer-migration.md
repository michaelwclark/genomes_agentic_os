# Schema adoption and active consumer migration

A package can install successfully while the installed root keeps an older or
custom schema. Scaffold updates preserve unknown overrides and place the vendor
candidate beside them as `.new`. `schema-adoption` gives the operator an explicit
plan, exact-byte backup, acknowledged apply, recovery journal, and rollback for
one selected schema. It does not change that preservation default.

Package smoke acceptance, schema ownership, selected consumer compatibility, and
whole-root health are separate results. A successful schema transaction does not
prove that delivery, review, release, production validation, or Health ran.

## Plan and adopt one schema

Use the same selected interpreter/package for planning and applying. The plan
records its distribution version and module path, the bundled schema ID/hash,
installed schema hash and ownership classification, and the complete manifest
hash. It classifies an absent schema, current managed or unowned schema, managed
upgrade, and an unowned or custom override. It never treats unknown bytes as a
vendor revision merely because their JSON shape resembles one.

```bash
agentic-os schema-adoption plan --root /tmp/example-os \
  --schema auto-dev-work-item.schema.json \
  --consumer domains/acme/02-projects/app/work-items/task/autodev.json \
  --historical-consumer domains/acme/02-projects/app/work-items/closed/old/autodev.json \
  --output /tmp/adoption-plan.json
```

Consumer arguments select exact files; there is no implicit whole-root scan or
mass normalization. Canonical `state.db` is opened read-only. Each active or
historical selection must match its registered packet, domain, project and
lifecycle. Old-schema and bundled-schema diagnostics are frozen separately for
each consumer. Diagnostics include structural paths and validation keywords,
without copying consumer values into error messages. Historical selection is
diagnostic-only.

Inspect `plan_sha256`, `installed.sha256`, ownership, selected consumer identities,
and old/new validation before applying. An unowned/custom schema requires the
same explicit acknowledgement as every other adoption. For an absent schema,
acknowledge the literal `absent`. Replace the example hashes below with exact
values from the plan.

```bash
agentic-os schema-adoption apply --plan /tmp/adoption-plan.json \
  --plan-sha256 PLAN_SHA256 \
  --acknowledge-installed-sha256 INSTALLED_SCHEMA_SHA256 --apply
```

Apply recomputes the frozen plan under the mutation lock and refuses changed
schema, manifest, bundle, consumer, task or canonical identity. Manifest
readback divergence must be investigated before planning. The selected manifest
entry becomes package-managed; unrelated entries and unknown manifest metadata
are retained. Schema adoption writes the selected schema and manifest only.
Selected consumers, `.new` candidates, history, runtime settings and providers
are not changed by adoption.

## Migrate an exact active Auto-Dev consumer

First adopt the exact bundled Auto-Dev schema. Then create a separate consumer
plan. This migration supports `auto-dev-work-item/v1` with the known canonical
stage order preceding `validate_production_release`, the current order with only
that execution row absent, or a complete current contract as a no-op. Future
schemas, unknown or reordered stages, malformed existing rows, divergent
task/projection boundaries and running execution are refused. Older unrelated
contracts remain explicit compatibility gaps.

Task authority is versioned independently from the projection. Explicit
`development-task/v1` is supported; any other explicit task schema, including
a future version or null marker, is refused. An absent marker is reported as
`development-task/legacy-unversioned` and is supported only with the known
structural stage contract, matching explicit mode/window, and the exact
canonical active task/packet binding. Its marker stays absent; migration does
not manufacture a task version or ownership claim.

```bash
agentic-os schema-adoption consumer-plan --root /tmp/example-os \
  --consumer domains/acme/02-projects/app/work-items/task/autodev.json \
  --output /tmp/consumer-plan.json
agentic-os schema-adoption apply --plan /tmp/consumer-plan.json \
  --plan-sha256 CONSUMER_PLAN_SHA256 \
  --acknowledge-installed-sha256 INSTALLED_SCHEMA_SHA256 --apply
```

The plan binds both the canonical delivery task and its exact active projection.
Apply validates every selected member before its first write and takes the
existing portfolio, task and projection locks in that order. It updates only
selected task/projection stage contracts. It does not retarget a shared
portfolio's workflow boundary, change lifecycle state, or manufacture execution
evidence.

Exact backup inputs must still match the plan before the first target write.
Final migration readback rechecks the unchanged schema and complete manifest.
A concurrent prerequisite change refuses acceptance and restores only the known
consumer writes, preserving the changed prerequisite for investigation.

Existing stage rows, history, receipt references, frozen policies and unknown
consumer fields survive. A missing production-release stage inside the selected
workflow window receives `not_started`, empty receipt references and no verified
timestamp. The current stage/status point to real pending work; blocked and
paused admission remain blocked or paused. A stage outside the window is
`out_of_scope`. Previously completed later stages retain their historical
evidence; they do not supply the absent prerequisite receipt.

An existing production-release policy keeps its unknown/frozen metadata and
must declare required applicability. Disabled or conflicting applicability is
refused. A full stage-order list with an absent execution row is repaired
explicitly; it cannot be reported as a zero-write successful migration.

Unknown fields can remain incompatible with a strict vendor schema. Their
residual diagnostics stay visible in `migrated_validation`; preserving them does
not imply a clean root or authorize dropping them. Registry/lifecycle,
historical-output and unsupported consumer diagnostics need their own scoped
resolution. Normal Auto-Dev execution still requires its canonical receipt and
policy gates, including production validation when applicable.

## Exact rollback and interrupted transactions

Every transaction stores an immutable frozen plan, exact backups and a typed
journal under
`harness/shared_factory/00-control-plane/schema-adoption/<transaction>/`.
The journal records original and resulting hashes, prepared/applying/applied or
recovery status, and terminal readback. Backups and the journal are written and
synced before target mutation. Ordinary failures restore the original bytes.
An interrupted process leaves a journal for explicit recovery and blocks another
apply until recovery completes.

```bash
agentic-os schema-adoption rollback --root /tmp/example-os \
  --journal /tmp/example-os/harness/shared_factory/00-control-plane/schema-adoption/TRANSACTION/journal.json \
  --plan-sha256 PLAN_SHA256 --apply
```

Rollback checks every target and backup before restoring any member. It accepts
only exact original or exact planned result bytes. A concurrent or unknown edit
to the manifest, schema, task, projection or any selected diagnostic-only
consumer refuses the whole rollback; the
operator must investigate it without overwriting the divergence. Path traversal,
symlink targets and external schema references are unsupported. Limits are 50
selected consumers, 4 MiB per file/complete plan, and 100 diagnostics per consumer
validation; truncation is explicit and cannot count as valid.

Consumer rollback also verifies the unchanged installed schema and complete
manifest, although that transaction did not write them. A changed or removed
compatibility prerequisite refuses restoration before any consumer is changed.

## Claude and Codex

Both harnesses use the same CLI, frozen plans and receipts. Agents can prepare a
reviewable plan and fixture validation; applying to an operator root requires
that exact root, schema bytes and selected work to be authorized. A source PR or
runtime alias update alone does not adopt a schema or migrate its consumers.
