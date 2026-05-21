# Feature Spec: Workflow Readiness And Run Closeout

## Status

- Status: ready
- Owner: Genome
- Created: 2026-05-20
- Target OS layer: source package, installed runtime, Codex, and Claude

## Problem

Workflow folders can be created, but the OS does not tell an agent whether the workflow is complete enough to run. Run logs can be created, but there is no close command that records final state, validation, artifacts, next action, or durable learning.

## Outcome

Every non-trivial agent session can start from a ready workflow and end with a useful audit record.

## Commands

```bash
agentic-os workflow check <domain> <lane> <workflow> --root ~/agentic_os
agentic-os run-log close <domain> <run-id> --status done|waiting|failed|needs_approval --root ~/agentic_os
```

## Workflow Readiness Checks

- Required workflow files exist.
- Required sections are not empty.
- Outcome brief has definition of done and acceptance criteria.
- Alignment questions are answered or explicitly deferred.
- Context pack names source files and source systems.
- Approval rules are present.
- Output contract names required artifacts.
- Runbook has start, operate, and closeout instructions.

## Run Closeout Fields

- Final status.
- Summary of actions taken.
- Validation performed.
- Artifacts created or changed.
- Approval gates encountered.
- Next action and owner.
- Learning promoted or intentionally not promoted.

## Required Side Effects

- Append a summary row to `<domain>/06-runs-and-logs/activity-log.md`.
- Update workflow `progress.md` when the run belongs to a workflow.
- Update project `status.md` when a project is linked.
- Never close a run as `done` without validation evidence.

## Out Of Scope

- Automated test execution beyond recording commands.
- External ticket updates.
- Notion sync.

## Acceptance Criteria

- `workflow check` produces blocker/fix-soon/cleanup/observation findings.
- `run-log close` refuses invalid status values.
- A closed run can be understood by a fresh agent without reading chat.
- Tests cover happy path, missing sections, invalid status, and activity-log updates.

## Validation

- `pytest -q`
- Create a temp workflow, create a run log, close it, then validate the root.
