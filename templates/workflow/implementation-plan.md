# Implementation Plan: <workflow_name>

## Metadata

| Field | Value |
| --- | --- |
| Domain | `<domain>` |
| Lane | `<lane>` |
| Owner | `<owner>` |
| Created | `<yyyy-mm-dd>` |
| Last Reviewed | `<yyyy-mm-dd>` |

## Outcome Link

- Outcome brief:

## Build Stages

| Stage | Scope | Acceptance Criteria | Risks |
| --- | --- | --- | --- |
| 1 |  |  |  |

## Files / Systems In Scope

| Path Or System | Change Type | Notes |
| --- | --- | --- |
|  |  |  |

## Dependencies And Assumptions

-

## Risk Register

| Risk | Impact | Mitigation | Stop Condition |
| --- | --- | --- | --- |
|  |  |  |  |

## Validation Plan

| Check | Command Or Evidence | Required |
| --- | --- | --- |
|  |  | yes |

## Orchestration Split

Use the cheapest reliable layer for each step.

| Step | Layer | Why |
| --- | --- | --- |
| Exact validation | Script / test | Deterministic and repeatable. |
| Routing or field checks | Rule logic | Stable conditions should not spend reasoning tokens. |
| Ambiguous synthesis | AI | Judgment or language interpretation is needed. |
| External commitment | Human approval | Accountability or risk requires a person. |

## Dispatch Plan

| Dispatch | Owner | Files Or Responsibility | Verification |
| --- | --- | --- | --- |
|  |  |  |  |
