# 08 Losmon Replacement Validation

## Table Of Contents

- [Purpose](#purpose)
- [Source And Runtime Boundaries](#source-and-runtime-boundaries)
- [Command](#command)
- [Generated Validation Package](#generated-validation-package)
- [Run Logs And Closeout](#run-logs-and-closeout)
- [Comparison Artifact](#comparison-artifact)
- [Troubleshooting](#troubleshooting)
- [Source Artifacts](#source-artifacts)

## Purpose

Feature 08 creates a read-only validation package for evaluating whether
Genome's Agentic OS can replace LOSMon automation safely. It scaffolds the LOS
project state, required workflows, support automation, validation run logs, and
a comparison artifact before any live migration is attempted.

## Source And Runtime Boundaries

This repository owns the scaffolding command and comparison template. The
installed OS root owns the generated `los` project state, workflow files,
automation contracts, run logs, and validation evidence.

The command does not replace LOSMon by itself. It prepares a package for
read-only validation against real LOS inputs.

## Command

Generate or refresh the validation package:

```bash
agentic-os losmon validate --root ~/agentic_os --repo <los_or_losmon_repo>
```

`--repo` is optional, but providing it records the candidate source repository
in project source references and the comparison artifact.

## Generated Validation Package

The command creates or verifies:

- project: `los/02-projects/losmon_replacement/`
- workflows:
  - `los/03-workflows/engineering/pr_review/`
  - `los/03-workflows/engineering/failing_ci_triage/`
  - `los/03-workflows/operations/deploy_planning/`
- automation: `los/04-automations/support/thread_intake/`
- comparison artifact:
  `los/02-projects/losmon_replacement/artifacts/losmon-comparison.md`

The project is marked active in the engineering lane and records a validation
section in `status.md`.

## Run Logs And Closeout

The command creates three read-only validation run logs and closes them with
status `waiting`. Each closeout names the prepared workflow, the comparison
artifact, the approval note that no external write was performed, and a next
action to run the workflow against a real read-only LOS task.

These run logs are not evidence of parity. They are placeholders that make the
next validation step explicit.

## Comparison Artifact

`losmon-comparison.md` keeps migration gaps visible. It compares Agentic OS
evidence against areas where LOSMon may still be better or required:

- live input watching
- service-specific runtime context
- tenant and environment approval matrices
- migration mapping from code paths to OS contracts
- telemetry-to-run-log adapters
- guarded retry policy
- Codex/Claude handoff trials

Do not remove these gaps until real validation evidence exists.

## Troubleshooting

If validation output does not include three run logs, inspect
`los/06-runs-and-logs/runs/` and rerun the command in a disposable root.

If the root fails `agentic-os validate`, inspect missing workflow, automation,
or project files before attempting any live migration.

If the comparison artifact says the candidate repo is not linked, rerun with
`--repo <los_or_losmon_repo>` or update the project source map manually with the
reviewed repository path.

## Source Artifacts

- Source plan: `PLANS/08-losmon-replacement-validation.md`
- Feature spec: `features/08-losmon-replacement-validation/SPEC.md`
- Feature QA: `features/08-losmon-replacement-validation/HOLDOUT_QA.md`
- Implementation: `src/genomes_agentic_os/losmon.py`
- CLI wiring: `src/genomes_agentic_os/cli.py`
- Test coverage: `tests/test_cli_scaffold.py`
