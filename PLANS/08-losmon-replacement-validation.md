# Feature Spec: LOS/losmon Replacement Validation

## Status

- Status: draft
- Owner: Genome
- Created: 2026-05-20
- Target OS layer: installed runtime and LOS operations

## Problem

The genomesbox losmon setup runs automations for a complex LOS webapp, but it is hard to reconfigure and feels too code-heavy. Agentic OS should be validated against that real operating surface before it is treated as a replacement.

## Outcome

Agentic OS can run a small set of LOS workflows and automations with clearer routing, context, logs, approval gates, and reconfiguration than the existing losmon path.

## Candidate Validation Workflows

- LOS PR review intake.
- LOS failing CI triage.
- LOS deploy planning.
- LOS release readiness check.
- LOS support thread or production issue triage.
- LOS Jira technical mapping.

## Required OS Objects

```text
los/02-projects/losmon_replacement/
los/03-workflows/engineering/pr_review/
los/03-workflows/engineering/failing_ci_triage/
los/03-workflows/operations/deploy_planning/
los/04-automations/support/thread_intake/
los/06-runs-and-logs/runs/
```

## Comparison Criteria

- Time to route a request.
- Context quality.
- Approval safety.
- Reconfiguration effort.
- Evidence quality in run logs.
- Recovery from failed runs.
- Ease of handoff between Codex and Claude.

## Out Of Scope

- Removing losmon.
- Rewriting genomesbox services.
- Unattended production writes.

## Acceptance Criteria

- At least three real LOS tasks run through Agentic OS with run logs.
- Each task has explicit routing, context sources, validation, and next action.
- Agentic OS identifies where losmon remains better or still required.
- The comparison produces implementation gaps for the next plan cycle.

## Validation

- Create the LOS project in `~/agentic_os`.
- Run three live read-only LOS workflows through OS logging.
- Compare outcomes to existing losmon behavior before migrating any automation.
