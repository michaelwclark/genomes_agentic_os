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
into a traceable backlog inside the source package. It gives later Build Runner
work a concrete starting point instead of relying on scattered conversation
state.

The feature is intentionally documentation- and backlog-heavy. Its job is to
make the next work obvious:

- `PLANS/README.md` indexes the plan backlog.
- `PLANS/00-current-state-and-gap-map.md` records the initial gap map.
- `PLANS/09-future-ideas-intake.md` preserves a later-feature intake lane.
- `features/00-current-state-and-gap-map/` records the local audit trail.

## Source And Runtime Boundaries

This repository is product source. It owns reusable docs, schemas, templates,
skills, commands, installers, and plan backlog files.

The installed OS root, usually `~/agentic_os`, is the live runtime. Runtime plan
assets are installed under:

```text
~/agentic_os/shared_factory/05-knowledge/plans/
```

Do not treat the runtime copy as canonical source. Update the source package,
then run the docs install or update path so the installed OS receives missing
assets without overwriting local runtime edits.

## Plan Backlog Layout

The backlog is flat and prefix ordered:

```text
PLANS/
  README.md
  00-current-state-and-gap-map.md
  01-project-create-and-active-work.md
  ...
```

Each plan should be precise enough to become implementation work. If a later
feature discovers a prerequisite, create a new plan file with a stable prefix
and record the source card or artifact that justified it.

## How To Validate

Use the same checks the original feature used:

```bash
uv run pytest -q
uv run agentic-os validate --root ~/agentic_os
```

For a fresh runtime smoke test, install or update docs and confirm the plan
mirror exists:

```bash
uv run agentic-os init --target /tmp/agentic-os-guide-check
uv run agentic-os docs install --root /tmp/agentic-os-guide-check
test -f /tmp/agentic-os-guide-check/shared_factory/05-knowledge/plans/README.md
test -f /tmp/agentic-os-guide-check/shared_factory/05-knowledge/plans/00-current-state-and-gap-map.md
```

## Troubleshooting

| Symptom | Likely Cause | Fix |
| --- | --- | --- |
| Runtime plan file is missing | Docs were not installed or updated after source changes | Run `agentic-os docs install` for a new root or `agentic-os docs update` for an existing root. |
| Validation passes but a plan is stale | Validation checks required structure, not every backlog detail | Compare the runtime copy to `PLANS/` and update docs from source. |
| A new card has no source trail | The plan was created without a card, artifact, or decision reference | Add the source reference to the plan and feature `JUDGMENT.md`. |

## Source Artifacts

- Source plan: `PLANS/00-current-state-and-gap-map.md`
- Feature audit folder: `features/00-current-state-and-gap-map/`
- Build Runner state: `RUN_STATE.json`
- Shared logs: `BUILD_LOGS/*.md`

No new diagram is included here because the feature is a source/runtime
inventory and backlog mirror; the path table above carries the operational
model without adding image maintenance burden.

