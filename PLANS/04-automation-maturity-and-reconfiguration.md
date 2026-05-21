# Feature Spec: Automation Maturity And Reconfiguration

## Status

- Status: draft
- Owner: Genome
- Created: 2026-05-20
- Target OS layer: source package, installed runtime, and automation operations

## Problem

The current automation scaffold documents permissions and tests, but the OS does not enforce a maturity model or make automations easy to reconfigure. This is part of why losmon-style automations feel heavy: behavior lives in code instead of a visible operating contract.

## Outcome

Automations can start in safe observe/prepare modes, gather evidence, and move toward guarded execution only when the workflow is proven and permissions are explicit.

## Maturity Levels

- `observe`: read inputs and log what would happen.
- `prepare`: draft artifacts or actions without external writes.
- `propose`: prepare an action and request approval.
- `execute_approved`: execute only after explicit approval for each run.
- `execute_guarded`: execute within a narrow pre-approved guardrail.

## Commands

```bash
agentic-os automation check <domain> <lane> <automation> --root ~/agentic_os
agentic-os automation attach <domain> <lane> <automation> --project <project> --root ~/agentic_os
agentic-os automation set-maturity <domain> <lane> <automation> <level> --root ~/agentic_os
```

## Required Automation Fields

- Trigger.
- Inputs and validation.
- Outputs and destinations.
- Idempotency key.
- Permissions.
- Approval gates.
- Failure modes.
- Tests.
- Run evidence.

## Required Side Effects

- Attachments update project `status.md` and `source-map.md`.
- Maturity changes append a row to domain `decisions.md`.
- Routing rules update only when explicitly requested or confirmed.
- Default execution remains conservative.

## Out Of Scope

- Building the scheduler.
- Replacing losmon in one step.
- Unattended production writes.

## Acceptance Criteria

- A new automation starts at `observe` or `prepare`.
- Maturity cannot advance without required evidence.
- Reconfiguration is file-first and reviewable.
- Tests cover maturity transitions, unsafe promotions, and project attachment.

## Validation

- `pytest -q`
- Manual dry run using a LOS support automation in a temp OS root.
