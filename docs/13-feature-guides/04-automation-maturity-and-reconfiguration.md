# 04 Automation Maturity And Reconfiguration

## Table Of Contents

- [Purpose](#purpose)
- [Commands](#commands)
- [Maturity Levels](#maturity-levels)
- [Promotion Evidence](#promotion-evidence)
- [Project Attachment](#project-attachment)
- [Disposable Validation](#disposable-validation)
- [Done Signal](#done-signal)

## Purpose

Feature 04 keeps automations conservative until their local contract has enough evidence. Operators can check automation readiness, promote maturity through explicit levels, and attach an automation to a project with reviewable file writebacks.

## Commands

```bash
agentic-os automation check los support production_thread_intake --root ~/agentic_os
agentic-os automation set-maturity los support production_thread_intake prepare --root ~/agentic_os
agentic-os automation attach los support production_thread_intake --project losmon_replacement --root ~/agentic_os
```

## Maturity Levels

Automations start at `observe`. Supported levels are `observe`, `prepare`, `propose`, `execute_approved`, and `execute_guarded`. Promotions beyond the safe start levels require contract evidence.

## Promotion Evidence

Before higher-risk promotion, the automation contract should include trigger source/frequency, idempotency key and duplicate handling, read/write permissions, approval gates, default action before approval, outputs, tests, and runbook coverage. `automation check` reports blockers when those are missing.

## Project Attachment

`automation attach` writes local evidence instead of external side effects. It updates the automation record, the project `status.md`, and the project `source-map.md` so future agents can see the relationship.

## Disposable Validation

```bash
TMP_ROOT="$(mktemp -d)/agentic_os"
uv run agentic-os init --target "$TMP_ROOT"
uv run agentic-os project create los losmon_replacement --root "$TMP_ROOT"
uv run agentic-os automation create los support production_thread_intake --root "$TMP_ROOT"
uv run agentic-os automation check los support production_thread_intake --root "$TMP_ROOT"
uv run agentic-os automation set-maturity los support production_thread_intake prepare --root "$TMP_ROOT"
uv run agentic-os automation attach los support production_thread_intake --project losmon_replacement --root "$TMP_ROOT"
uv run agentic-os validate --root "$TMP_ROOT"
```

## Done Signal

Feature 04 is healthy when new automations begin at `observe`, readiness checks surface blockers, safe promotion to `prepare` records a decision, unsafe promotion is blocked without evidence, project attachment updates project/automation files, and validation remains green.
