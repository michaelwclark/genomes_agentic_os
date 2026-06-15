# 06 Notion Control Plane Sync

## Table Of Contents

- [Purpose](#purpose)
- [Source And Runtime Boundaries](#source-and-runtime-boundaries)
- [Commands](#commands)
- [What Sync Planning Discovers](#what-sync-planning-discovers)
- [Dry Run And Apply](#dry-run-and-apply)
- [Workspace Guardrails](#workspace-guardrails)
- [Local Mapping](#local-mapping)
- [Troubleshooting](#troubleshooting)
- [Source Artifacts](#source-artifacts)

## Purpose

Feature 06 adds a guarded filesystem-to-Notion planning surface. The runtime
filesystem remains the source of truth; Notion is the control plane where
reviewable records can be planned and tracked after workspace verification.

The sync commands produce deterministic local actions and mappings before any
live Notion write path is trusted.

## Source And Runtime Boundaries

This repository owns sync planning logic and CLI guardrails. The installed OS
root owns runtime files, `.notion-sync/mapping.yml`, and any local sync state.

Do not treat Notion as the runtime database. Notion records should reflect the
filesystem state, not replace it.

## Commands

Build a reviewable sync plan:

```bash
agentic-os notion plan-sync --root ~/agentic_os
```

Run a dry run:

```bash
agentic-os notion sync --root ~/agentic_os --dry-run
```

Apply after the workspace has been verified:

```bash
agentic-os notion sync --root ~/agentic_os \
  --apply \
  --verified-workspace "Genome's Notion"
```

The command prints YAML. Plans and dry runs report `create`, `update`, and
`no-op` actions.

## What Sync Planning Discovers

`plan-sync` discovers runtime objects from domain folders and managed runtime
files:

- domains
- active work
- approvals
- decisions
- metrics
- projects
- workflows
- automations
- run logs

Each planned action includes the object kind, key, title, source path, record
key, fingerprint, and local Notion ID when already mapped.

## Dry Run And Apply

`--dry-run` prints the planned create/update/no-op actions without writing the
mapping file.

`--apply` writes `.notion-sync/mapping.yml` after workspace verification. The
mapping stores deterministic local Notion IDs and file fingerprints. When source
files are unchanged, a later dry run reports no-op actions.

## Workspace Guardrails

Genome roots require the verified workspace name `Genome's Notion`.

Customer roots require the customer workspace configured in `customer.yml`.

Apply refuses to run without `--verified-workspace`, with the wrong workspace,
or with a workspace name that looks like Michael Clark's personal Notion. This
prevents accidental writes to the wrong control plane.

## Local Mapping

The mapping file is local runtime state:

```text
.notion-sync/mapping.yml
```

It is deterministic and reviewable. Mapping IDs remain local until a verified
live Notion write replaces them with real page or database IDs.

## Troubleshooting

If apply refuses workspace verification, confirm the active connector or direct
API identity is in Genome's Notion before retrying.

If dry run keeps showing updates after apply, inspect the source file paths in
the action list. A fingerprint changed, so the filesystem source has changed.

If a customer root expects a different workspace, inspect `customer.yml` and use
the customer workspace from that profile.

## Source Artifacts

- Installed spec: `SPECS/06-notion-control-plane-sync/SPEC.md`
- Installed worklog spec: `worklogs/source-features/06-notion-control-plane-sync/SPEC.md`
- Installed worklog QA: `worklogs/source-features/06-notion-control-plane-sync/HOLDOUT_QA.md`
- Sync implementation: `src/genomes_agentic_os/notion_sync.py`
- CLI wiring: `src/genomes_agentic_os/cli.py`
- Test coverage: `tests/test_cli_scaffold.py`
