# 30 · Compact Context Contracts

> **Purpose:** let workflow and automation folders declare only what is local,
> inherit safety and provider routing from their parents, and explain the
> effective context without copying four more Markdown catalogs into every folder.

## The contract

New workflow and automation scaffolds include `context-contract.yml`:

```yaml
schema_version: 1
kind: workflow
inherits: [parent]
read:
  first: [workflow.md, quick-reference.md, context-pack.md, approval-rules.md, runbook.md]
  deferred: [prd.md, implementation-plan.md, progress.md]
  exclude: [runs/**, artifacts/**, snapshots/**]
capabilities: []
providers: {}
overrides:
  rules: []
```

`read.first` is the small operating packet. `read.deferred` stays discoverable
but is loaded only when the task needs it. `read.exclude` keeps evidence-heavy
trees out of broad discovery. Parent `AGENTS.md`, `ROUTER.md`, `CONTEXT.md`,
`RULES.md`, and `TOOLS.md` remain authoritative and are inherited with source
provenance. Exact duplicate content is skipped and reported.

Capability IDs are stable identities, not copied tool documentation. Provider
routes resolve first from `harness/registries/composio-tools.yml`; a manifest
override is explicit and visible in `context explain`.

## Operator commands

```bash
agentic-os context explain \
  --domain los --lane engineering --workflow release_review \
  --root ~/agentic_os

agentic-os context check --root ~/agentic_os

agentic-os context compact --dry-run --root ~/agentic_os \
  --output-dir ./context-compaction-receipts

# Only after reviewing the plan and merging the source change:
agentic-os context compact --apply --root ~/agentic_os \
  --plan ./context-compaction-receipts/context-compaction-plan.json \
  --receipt-dir ./context-compaction-receipts

# Exact recovery remains an explicit one-command operation:
agentic-os context restore --root ~/agentic_os \
  --receipt ./context-compaction-receipts/context-compaction-<hash>.json
```

`context explain` prints inherited sources, local sources, deferred files,
exclusions, capability/provider provenance, missing files, and duplicates that
were skipped. `context check` validates manifests and inventories legacy
fallbacks plus duplicate contract hashes.

`context compact --dry-run` never deletes a file. The optional output directory
receives:

- `context-compaction-plan.json` — deterministic candidate actions.
- `context-compaction-rollback.json` — exact base64 content and SHA-256 for every
  duplicate file proposed for later removal. This is review evidence; apply
  builds a fresh durable receipt from the verified live bytes.

`context compact --apply` accepts only that reviewed, untampered plan. It checks
the plan hash, root identity, complete context-tree hash, every candidate hash,
the inherited source hash, and the object's inheritance declaration before it
changes a byte. Only `ROUTER.md`, `CONTEXT.md`, `RULES.md`, and `TOOLS.md` are
eligible, and only when an ancestor contains the byte-identical file. A plan
must remove at least 40% of the managed objects' local context bytes.

Apply writes a `prepared` receipt before removing files. It then compares a
semantic signature of resolved source content, exclusions, capabilities,
providers, and diagnostics; runs the context check plus full installed-root
validation; and records exact before/after hashes. Any failed gate restores the
base64-preserved bytes automatically and marks the receipt `rolled_back`.
Manual restore refuses to overwrite newer work if the post-apply tree hash has
changed.

## Safe migration guide

1. Install the new source package additively; do not delete existing contracts.
2. Run `context check` and preserve the output as the baseline receipt.
3. Add `context-contract.yml` to one workflow or automation and keep its local
   Markdown content unchanged.
4. Run `context explain` and verify that approval rules, provider order, and the
   required operating sources remain present.
5. Run `context compact --dry-run --output-dir <receipt-dir>` twice. The plan
   and `plan_sha256` must be stable before they are trusted.
6. Review every proposed removal, `inherited_from` source, before hash, semantic
   signature, and the reported reduction ratio.
7. Apply only after the source package containing these safeguards is merged.
   Keep the resulting receipt outside the mutable object folders.
8. Keep legacy folders working throughout migration. Missing manifests use the
   exact legacy source list supplied by the caller and surface a warning.

This boundary keeps root, harness, domain, and project bootstrap contracts
intact. It compacts only workflow and automation object layers first.

## Running this from Claude vs Codex

- **Claude:** run the shared CLI commands from the routed OS root; the inherited
  `AGENTS.md` contract remains the harness-neutral entry point.
- **Codex:** use the same commands. Layered `config.toml` still selects model,
  effort, and tool permissions; it does not duplicate the context manifest.

Both harnesses receive the same resolved sources and provenance.

## First source-owned migration receipt

CC-303 migrated the bounded fixture group
`tests/fixtures/context_migration/os/acme/03-workflows/engineering/{first,second}`.
The before-state copied four contracts into each workflow (eight files total).
The apply removed 1,868 of 2,324 local context bytes, an 80.3787% reduction,
while the before and after semantic signatures remained identical. The fixture
now commits the compact after-state; tests reconstruct the exact legacy input
in temporary space to continuously prove apply, automatic rollback, and manual
restore.
