# 31 · First-Class Report Engine

The report engine makes a report a durable Agentic OS resource instead of only
a Markdown file or Notion page. Definitions, executions, and artifacts have
separate identities and can be queried independently.

## Ownership and source of truth

| Resource | Canonical registry | Durable content |
| --- | --- | --- |
| report prompt/catalog entry | `harness/registries/reports.yml` | governed draft/archive CRUD and source prompt document |
| `ReportDefinition` | `harness/registries/report-definitions.yml` | runnable generator links, catalog ref, sources, schedule, destinations, retention, permissions, health, sections |
| `ReportRun` | `harness/registries/report-runs.yml` | status, timing, source completeness, errors, projection evidence, artifact ids |
| `ReportArtifact` | `harness/registries/report-artifacts.yml` | artifact identity, checksum, JSON path, rendered Markdown path |

The filesystem is canonical. A Notion page is an optional projection and never
becomes report identity or lifecycle state.

The catalog and runtime definition are deliberately separate layers. A catalog
entry can exist as a draft before its sources, schedule, and destinations are
configured. A runnable definition may link it with `catalog_ref`. Validation
refuses stale explicit links, while consolidation shows catalog entries lacking
definitions and definitions lacking catalog links.

Schemas are versioned independently as `report-definition.schema.json`,
`report-run.schema.json`, and `report-artifact.schema.json`. `agentic-os init`
and `agentic-os docs update` add missing schemas and registries without replacing
operator data.

## Routing and execution

A definition may point to the workflow or program that owns its intent, and to
an existing runtime schedule. A schedule reference is checked during validation;
a removed schedule blocks create, update, and run-now as stale configuration.

The first engine deliberately supports only bounded built-in sources:

- `filesystem` reads one file below the installed root as text, JSON, or YAML,
  with a 1 MiB bound and no symlink traversal;
- `report_inventory` queries the existing bounded report discovery projection
  with typed domain, project, status, type, and limit filters.

It does not execute a command from a report definition. Programs, workflows,
and automations remain the owners of external or agentic generation; they can
write a bounded source and invoke this engine to construct the canonical run and
artifact.

## Progressive report content

Definitions can assemble `markdown`, `table`, `chart`, `list`, `timeline`,
`links`, and `evidence` sections. The JSON artifact preserves the typed section;
the Markdown artifact renders the same data in a portable operator view. A UI
can choose native components for tables and charts without parsing prose.

Every source records required/optional status, observation time, record count,
content checksum, and a compact detail. Missing required sources produce an
`error` run. Missing optional or empty sources produce a `partial` run. The
artifact and Markdown keep those findings visible.

## Governed actions

All lifecycle and run operations return the existing `resource-actions/v1`
envelope.

```bash
# Add the empty registries to an older installed OS.
agentic-os report init --root ~/agentic_os --json

# Validate and preview before mutation.
agentic-os report validate --definition-file report.yml --root ~/agentic_os --json
agentic-os report create --definition-file report.yml --root ~/agentic_os --dry-run --json

# Apply, query, and run.
agentic-os report create --definition-file report.yml --root ~/agentic_os --apply --json
agentic-os report query definition --root ~/agentic_os --json
agentic-os report run-now daily_operator_report --root ~/agentic_os --apply --json

# Definition lifecycle remains reversible.
agentic-os report archive daily_operator_report --root ~/agentic_os --dry-run --json
agentic-os report archive daily_operator_report --root ~/agentic_os --apply --json
agentic-os report rollback harness/shared_factory/06-runs-and-logs/report-engine/receipts/<receipt>.yml \
  --root ~/agentic_os --dry-run --json
```

Create, update, archive, restore, and rollback are dry-run by default. Applied
actions create a registry backup, atomic write, readback evidence, and receipt.
Rollback is optimistic: it refuses if another action changed the registry after
the source receipt. Completed runs are immutable evidence and are not rolled
back.

## Notion projection boundary

Notion is disabled by default. A projection requires all of the following:

1. an enabled `notion` destination with workspace exactly `Genome's Notion`;
2. definition permission `notion_projection: true`;
3. an explicit projection request with the exact verified workspace name;
4. an approved projector adapter supplied by the active harness/provider route.

A workspace mismatch refuses before the adapter is invoked. Adapter absence or
failure is recorded as projection evidence and makes an otherwise successful
run `partial`; it never gets flattened into success. The CLI does not store a
Notion token or silently select a workspace.

## Retention and consolidation

Retention is evidence-first. Each run returns candidates exceeding `max_runs`
or `max_age_days`, but the engine does not delete them. Likewise,
`report consolidate-plan` detects equivalent definitions, never-run/stale
definitions, and legacy report artifacts. It recommends review and canonical
mapping without automatic archive or deletion.

```bash
agentic-os report consolidate-plan --stale-days 30 --root ~/agentic_os --json
```

## Validation and projection updates

- Definition references and all generated run/artifact objects are validated
  against the installed versioned schemas.
- Tests cover lifecycle receipts, optimistic rollback, all rich section types,
  missing required/optional sources, retention planning, stale schedules,
  workspace guards, projection failure, path traversal, and consolidation.
- Operator UIs should consume the bounded
  `report query definition|run|artifact --limit 200 --json` contract. Every
  resource includes `id`, `status`, `scope`, and `source`; definitions also
  include `catalog_ref`, catalog metadata, schedule, current health, latest run,
  latest artifact, and related counts without scraping Markdown. The response
  declares `count`, `total_count`, `limit`, and `truncated`.
