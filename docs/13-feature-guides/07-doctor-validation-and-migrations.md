# 07 Doctor Validation And Migrations

## Table Of Contents

- [Purpose](#purpose)
- [Source And Runtime Boundaries](#source-and-runtime-boundaries)
- [Doctor Commands](#doctor-commands)
- [Doctor Findings](#doctor-findings)
- [Managed Repairs](#managed-repairs)
- [Migration Commands](#migration-commands)
- [Migration Safety](#migration-safety)
- [Troubleshooting](#troubleshooting)
- [Source Artifacts](#source-artifacts)

## Purpose

Feature 07 adds deeper runtime health checks and explicit local migration
planning. It gives operators a reviewable way to inspect installed OS roots,
repair missing managed files additively, and apply small filesystem migrations
only after a stable preview has been reviewed.

## Source And Runtime Boundaries

This repository owns the doctor checks, managed repair rules, and migration
definitions. The installed OS root owns the runtime files, run logs, project
state, and migration preview records.

Doctor and migration commands operate on a runtime root. They should not be used
to silently rewrite source package files.

## Doctor Commands

Run health checks:

```bash
agentic-os doctor --root ~/agentic_os
```

Run additive managed-file repairs and then health checks:

```bash
agentic-os doctor --root ~/agentic_os --fix-missing
```

The command prints YAML with `root`, `ok`, `repairs`, and `findings`.

## Doctor Findings

Doctor findings include severity, path, and message. Current checks cover:

- root validation errors and warnings
- workflow readiness findings
- automation maturity findings
- active work rows that lack concrete next actions
- project folders missing `project.yml`, `status.md`, or `source-map.md`
- run logs without final status or closeout

Blocking findings make `ok: false` and cause the CLI to exit non-zero. Non-
blocking findings such as `fix-soon`, `cleanup`, and `observation` still matter
because they identify stale or incomplete runtime state.

## Managed Repairs

`--fix-missing` only runs additive managed-file repairs. It is designed for
missing standard files, not for overwriting local edits or making product
decisions.

Use it when a runtime root is missing generated docs or customer-safe managed
templates. Review the diff after repair and run doctor again before continuing
work.

## Migration Commands

Create a reviewable migration plan:

```bash
agentic-os migrate plan --root ~/agentic_os
```

Apply an approved migration by ID:

```bash
agentic-os migrate apply notion-sync-readme-v1 --root ~/agentic_os
```

The current migration ID is `notion-sync-readme-v1`. It writes
`.notion-sync/README.md`, documenting that filesystem state remains the source
of truth, workspace verification is required before apply, and local mapping IDs
remain local until a verified live Notion write replaces them.

## Migration Safety

`migrate plan` writes `.migrations/notion-sync-readme-v1.yml` with the migration
purpose, target, expected target hash, approval requirement, rollback note, and
unified diff.

`migrate apply` reads that saved preview before writing. If the target changed
after the preview was created, apply fails with a changed-target error. Re-run
`migrate plan` to create a fresh preview, review the new diff, and then apply.

Unknown migration IDs are rejected.

## Troubleshooting

If doctor reports blockers after `--fix-missing`, inspect the referenced paths.
The repair path only creates missing managed files; it will not invent project
state, close run logs, or fill incomplete workflow and automation contracts.

If a run log is reported as stale, close it through the run-log command with a
valid status and validation evidence.

If migration apply says the target changed after preview, do not force apply.
Review the current target, re-run `migrate plan`, and apply only after the new
preview matches the intended change.

## Source Artifacts

- Source plan: `PLANS/07-doctor-validation-and-migrations.md`
- Feature spec: `features/07-doctor-validation-and-migrations/SPEC.md`
- Feature QA: `features/07-doctor-validation-and-migrations/HOLDOUT_QA.md`
- Doctor implementation: `src/genomes_agentic_os/doctor.py`
- Migration implementation: `src/genomes_agentic_os/migrations.py`
- CLI wiring: `src/genomes_agentic_os/cli.py`
- Test coverage: `tests/test_cli_scaffold.py`
