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
```

`context explain` prints inherited sources, local sources, deferred files,
exclusions, capability/provider provenance, missing files, and duplicates that
were skipped. `context check` validates manifests and inventories legacy
fallbacks plus duplicate contract hashes.

`context compact` is deliberately plan-only in this release. It never deletes a
file. The optional output directory receives:

- `context-compaction-plan.json` — deterministic candidate actions.
- `context-compaction-rollback.json` — exact base64 content and SHA-256 for every
  duplicate file proposed for later removal.

## Safe migration guide

1. Install the new source package additively; do not delete existing contracts.
2. Run `context check` and preserve the output as the baseline receipt.
3. Add `context-contract.yml` to one workflow or automation and keep its local
   Markdown content unchanged.
4. Run `context explain` and verify that approval rules, provider order, and the
   required operating sources remain present.
5. Run `context compact --dry-run --output-dir <receipt-dir>` twice. The plan
   must be byte-for-byte stable before it is trusted.
6. Review every proposed removal and its rollback entry. A future apply command
   may consume that evidence; this release does not perform the removal.
7. Keep legacy folders working throughout migration. Missing manifests use the
   exact legacy source list supplied by the caller and surface a warning.

This boundary keeps root, harness, domain, and project bootstrap contracts
intact. It compacts only workflow and automation object layers first.

## Running this from Claude vs Codex

- **Claude:** run the shared CLI commands from the routed OS root; the inherited
  `AGENTS.md` contract remains the harness-neutral entry point.
- **Codex:** use the same commands. Layered `config.toml` still selects model,
  effort, and tool permissions; it does not duplicate the context manifest.

Both harnesses receive the same resolved sources and provenance.
