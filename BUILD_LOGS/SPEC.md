# Build Runner Spec Log

## 00 Current State And Gap Map

- Source card: `366683b4-8dab-8175-bceb-c1e204696b64`
- Feature artifact: `features/00-current-state-and-gap-map/SPEC.md`
- Source plan: `PLANS/00-current-state-and-gap-map.md`
- Acceptance: readable source backlog, installed runtime plans, validation requirement, traceability to one plan file.

## 01 Project Create And Active Work

- Source card: `366683b4-8dab-81e2-9268-ea82e66315a2`
- Feature artifact: `features/01-project-create-and-active-work/SPEC.md`
- Source plan: `PLANS/01-project-create-and-active-work.md`
- Acceptance: `agentic-os project create` creates indexed, source-linked, idempotent project records.

## 02 Routing And Context Builder

- Source card: `366683b4-8dab-8154-bf58-f38c275a29ab`
- Feature artifact: `features/02-routing-and-context-builder/SPEC.md`
- Source plan: `PLANS/02-routing-and-context-builder.md`
- Acceptance: route/context/here commands build deterministic, read-only context packets.

## 18 Documentation And Help Guide For 00 Current State And Gap Map

- Source card: `368683b4-8dab-81e6-bdf1-e10a0fce5a68`
- Feature artifact: `features/18-documentation-and-help-guide-for-00-current-state-and-gap-map/SPEC.md`
- Related completed feature: `features/00-current-state-and-gap-map/`
- Acceptance: operator-facing guide for feature 00, source/runtime artifact map, validation commands, and Build Runner sequencing notes.

## 19 Holdout Command Validation For 00 Current State And Gap Map

- Source card: `368683b4-8dab-812f-a145-c9ae5900ff10`
- Feature artifact: `features/19-holdout-command-validation-for-00-current-state-and-gap-map/SPEC.md`
- Related completed feature: `features/00-current-state-and-gap-map/`
- Acceptance: local holdout validation for feature 00 artifacts, RUN_STATE done record, source plan sections, and disposable runtime plan installation without live Notion writes.

## 20 Documentation And Help Guide For 01 Project Create And Active Work

- Source card: `368683b4-8dab-81a4-925d-c2c18e7f5034`
- Feature artifact: `features/20-documentation-and-help-guide-for-01-project-create-and-active-work/SPEC.md`
- Related completed feature: `features/01-project-create-and-active-work/`
- Acceptance: operator-facing guide for `agentic-os project create`, active-work/project indexes, source-map refs, idempotency, validation, and domain alias behavior.

## 21 Holdout Command Validation For 01 Project Create And Active Work

- Source card: `368683b4-8dab-81d7-894c-d76bd3c484b4`
- Feature artifact: `features/21-holdout-command-validation-for-01-project-create-and-active-work/SPEC.md`
- Related completed feature: `features/01-project-create-and-active-work/`
- Acceptance: local holdout validator for project creation, indexes, source-map refs, idempotency, aliasing, and root validation.

## 22 Documentation And Help Guide For 02 Routing And Context Builder

- Source card: `368683b4-8dab-81ae-a8a2-e0fd6532e46a`
- Feature artifact: `features/22-documentation-and-help-guide-for-02-routing-and-context-builder/SPEC.md`
- Related completed feature: `features/02-routing-and-context-builder/`
- Acceptance: operator-facing guide for route/context/here commands, context packet shape, approval risks, source loading, and safe failures.

## 23 Holdout Command Validation For 02 Routing And Context Builder

- Source card: `368683b4-8dab-810a-97b5-e2cbd4b9bba5`
- Feature artifact: `features/23-holdout-command-validation-for-02-routing-and-context-builder/SPEC.md`
- Related completed feature: `features/02-routing-and-context-builder/`
- Acceptance: local holdout validator for route, context build, here context, approval risks, linked-repo detection, low-confidence failure, and root validation.

## 24 Documentation And Help Guide For 03 Workflow Readiness And Run Closeout

operator guide for workflow check and run-log closeout.

## 25 Holdout Command Validation For 03 Workflow Readiness And Run Closeout

local holdout validator for workflow readiness and closeout.

## 26 Documentation And Help Guide For 04 Automation Maturity And Reconfiguration

operator guide for automation maturity and reconfiguration.

## 27 Holdout Command Validation For 04 Automation Maturity And Reconfiguration

local holdout validation for automation maturity checks, unsafe promotion
guarding, safe `prepare` promotion, project attachment, and root validation.

## 28 Documentation And Help Guide For 05 Customer Os Factory

operator guide for customer profile inputs, customer init/update/validate,
additive updates, customer-safe generation, and validation output.

## 29 Holdout Command Validation For 05 Customer Os Factory

local holdout validation for customer init, additive update, validation output,
local edit preservation, and private source-owner filtering.

## 30 Documentation And Help Guide For 06 Notion Control Plane Sync

operator guide for Notion sync planning, dry run, guarded apply, workspace
verification, local mapping, and no-op behavior.

## 31 Holdout Command Validation For 06 Notion Control Plane Sync

local holdout validation for Notion sync planning, workspace refusal, guarded
apply, local mapping, and no-op dry run.

## 32 Documentation And Help Guide For 07 Doctor Validation And Migrations

operator guide for runtime doctor checks, additive managed repairs, migration
planning, apply, preview rollback notes, and changed-target refusal.

## 33 Holdout Command Validation For 07 Doctor Validation And Migrations

local holdout validation for doctor missing-file repair, stale run findings,
migration preview, drift refusal, and apply.

## 34 Documentation And Help Guide For 08 Losmon Replacement Validation

operator guide for generating and interpreting the LOSMon replacement
validation package.

## 35 Holdout Command Validation For 08 Losmon Replacement Validation

local holdout validation for LOSMon package generation, required runtime
objects, comparison artifact, run logs, and root validation.
