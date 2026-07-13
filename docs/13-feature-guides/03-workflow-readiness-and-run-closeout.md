# 03 Workflow Readiness And Run Closeout

## Table Of Contents

- [Purpose](#purpose)
- [Source And Runtime Boundaries](#source-and-runtime-boundaries)
- [Commands](#commands)
- [Readiness Checks](#readiness-checks)
- [Run Closeout Evidence](#run-closeout-evidence)
- [Disposable Validation](#disposable-validation)
- [Troubleshooting](#troubleshooting)
- [Source Artifacts](#source-artifacts)

## Purpose

Feature 03 makes workflows reviewable before execution and makes run closeout
evidence-based. Agents should be able to check whether a workflow has the
required sections, create a run log, and close it only when validation evidence
exists.

## Source And Runtime Boundaries

This repository owns the CLI, templates, and tests. The installed OS root owns
live workflow specs and run logs under domain runtime folders. Run these
commands against a runtime root such as `~/agentic_os`.

## Commands

Create and check a workflow:

```bash
agentic-os workflow create acme engineering feature_dev --root ~/agentic_os
agentic-os workflow check acme engineering feature_dev --root ~/agentic_os
```

Create and close a run log:

```bash
agentic-os run-log create acme feature_dev --root ~/agentic_os
agentic-os run-log close acme <run-id> --status done --summary "Completed work" --validation "tests passed" --artifact run-log.md --approval "No approval gate" --next-action "Promote" --project launch --root ~/agentic_os
```

## Readiness Checks

`workflow check` returns findings with severities such as blocker, fix-soon,
cleanup, and observation. A blocker means the workflow should not be automated
or delegated until the missing contract is fixed.

## Run Closeout Evidence

Closing a run as `done` requires at least one validation item. This prevents a
run from appearing finished without proof. Closeout records summary,
validation, artifacts, approval notes, next action, owner, optional project
linkage, and durable learning.

## Disposable Validation

```bash
TMP_ROOT="$(mktemp -d)/agentic_os"
uv run agentic-os init --target "$TMP_ROOT"
uv run agentic-os project create acme launch --root "$TMP_ROOT"
uv run agentic-os workflow create acme engineering feature_dev --root "$TMP_ROOT"
uv run agentic-os workflow check acme engineering feature_dev --root "$TMP_ROOT"
uv run agentic-os run-log create acme feature_dev --root "$TMP_ROOT"
RUN_ID="$(basename "$(find "$TMP_ROOT/acme/06-runs-and-logs/runs" -maxdepth 1 -type d -name '*-acme-feature_dev' | head -1)")"
uv run agentic-os run-log close acme "$RUN_ID" --status done --summary "Verified" --validation "tests passed" --root "$TMP_ROOT"
uv run agentic-os validate --root "$TMP_ROOT"
```

## Troubleshooting

| Symptom | Likely Cause | Fix |
| --- | --- | --- |
| Done closeout is refused | No validation evidence was supplied | Add one or more `--validation` entries. |
| Workflow check reports blocker | Required workflow sections are missing | Fill the workflow contract before delegating or automating. |
| Project status does not reflect closeout | Closeout was run without `--project` | Re-close or update the linked project status with the project slug. |

## Source Artifacts

- Installed spec: `SPECS/03-workflow-readiness-and-run-closeout/SPEC.md`
- Installed worklog folder: `worklogs/source-features/03-workflow-readiness-and-run-closeout/`
- Implementation: `src/genomes_agentic_os/workflow_ops.py`
- CLI parser: `src/genomes_agentic_os/cli.py`

No diagram is included; the evidence flow is clearer as command examples and a
troubleshooting table.

