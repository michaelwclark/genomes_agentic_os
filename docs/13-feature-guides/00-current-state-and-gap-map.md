# 00 Current State And Gap Map

## Table Of Contents

- [What This Feature Established](#what-this-feature-established)
- [Source And Runtime Boundaries](#source-and-runtime-boundaries)
- [Plan Backlog Layout](#plan-backlog-layout)
- [How To Validate](#how-to-validate)
- [Troubleshooting](#troubleshooting)
- [Source Artifacts](#source-artifacts)

## What This Feature Established

Feature `00-current-state-and-gap-map` turned the initial Agentic OS gap map
into a traceable installed OS project backlog. It gives later Build Runner work
a concrete starting point instead of relying on scattered conversation state.

The feature is intentionally documentation- and backlog-heavy. Its job is to
make the next work obvious:

- The installed project's `work-items/` lanes index the migrated backlog and
  preserve the initial gap map and later-feature intake.
- `worklogs/source-features/00-current-state-and-gap-map/` records the migrated audit trail.

## Source And Runtime Boundaries

This repository is product source. It owns reusable docs, schemas, templates,
skills, commands, and installers.

The installed OS root, usually `~/agentic_os`, is the live runtime and the
canonical lifecycle surface for this source package. Project lifecycle assets
live under:

```text
~/agentic_os/work/02-projects/genomes_agentic_os/
```

Do not recreate source-root lifecycle folders for this package. Record new
specs, work items, worklogs, run logs, and generated evidence in the installed
OS project buckets.

## Plan Backlog Layout

The migrated backlog is prefix ordered inside the installed OS project:

```text
work-items/
  01-intake/
  02-active/
  03-complete/
```

Each plan should be precise enough to become implementation work. If a later
feature discovers a prerequisite, create a new spec or work item with a stable
prefix and record the source card or artifact that justified it.

## How To Validate

Use the same checks the original feature used:

```bash
uv run pytest -q
uv run agentic-os validate --root ~/agentic_os
```

For a fresh runtime smoke test, initialize a disposable OS root and validate it:

```bash
uv run agentic-os init --target /tmp/agentic-os-guide-check
uv run agentic-os validate --root /tmp/agentic-os-guide-check
```

## Troubleshooting

| Symptom | Likely Cause | Fix |
| --- | --- | --- |
| Installed spec is missing | Lifecycle migration or project sync did not run | Check the migration manifest in `artifacts/source-lifecycle-consolidation-2026-06-15/` and restore the missing installed bucket. |
| Validation passes but a spec is stale | Validation checks required structure, not every backlog detail | Compare the installed OS project spec to the originating card, artifact, or decision reference. |
| A new card has no source trail | The spec was created without a card, artifact, or decision reference | Add the source reference to the installed spec and worklog `JUDGMENT.md`. |

## Source Artifacts

- Historical Spec: migrated into the installed project's canonical `work-items/` lifecycle.
- Installed worklog folder: `worklogs/source-features/00-current-state-and-gap-map/`
- Build Runner state: `RUN_STATE.json`
- Shared logs: `worklogs/source-build-logs/*.md`

No new diagram is included here because the feature is a source/runtime
inventory and backlog mirror; the path table above carries the operational
model without adding image maintenance burden.
