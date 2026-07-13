# 04 Automation Maturity And Reconfiguration

## Table Of Contents

- [Purpose](#purpose)
- [Source And Runtime Boundaries](#source-and-runtime-boundaries)
- [Commands](#commands)
- [Maturity Levels](#maturity-levels)
- [Project Attachment](#project-attachment)
- [Disposable Validation](#disposable-validation)
- [Troubleshooting](#troubleshooting)
- [Source Artifacts](#source-artifacts)

## Purpose

Feature 04 makes automations safer to introduce and reconfigure. New
automations start at `observe`, can move to `prepare`, and require file-first
evidence before higher maturity levels.

## Source And Runtime Boundaries

This repository owns the CLI behavior and templates. The installed OS root owns
live automation specs, maturity decisions, project attachments, and validation
evidence.

## Commands

```bash
agentic-os automation create acme support production_thread_intake --root ~/agentic_os
agentic-os automation check acme support production_thread_intake --root ~/agentic_os
agentic-os automation set-maturity acme support production_thread_intake prepare --root ~/agentic_os
agentic-os automation attach acme support production_thread_intake --project launch --root ~/agentic_os
```

## Maturity Levels

| Level | Meaning |
| --- | --- |
| `observe` | Watch and report only. This is the default for new automations. |
| `prepare` | Prepare artifacts or draft actions for review. |
| `propose` | Suggest actions based on file-first evidence. |
| `execute_approved` | Execute only after approval evidence exists. |
| `execute_guarded` | Execute with explicit guardrails and rollback evidence. |

Higher levels require the automation spec to contain the contract, permissions,
outputs, and audit evidence needed for safe operation.

## Project Attachment

`automation attach` links a runtime automation to a project. The project status
and source map should then expose which automation participates in that project
and where to inspect it.

## Disposable Validation

```bash
TMP_ROOT="$(mktemp -d)/agentic_os"
uv run agentic-os init --target "$TMP_ROOT"
uv run agentic-os project create acme launch --root "$TMP_ROOT"
uv run agentic-os automation create acme support production_thread_intake --root "$TMP_ROOT"
uv run agentic-os automation check acme support production_thread_intake --root "$TMP_ROOT"
uv run agentic-os automation set-maturity acme support production_thread_intake prepare --root "$TMP_ROOT"
uv run agentic-os automation attach acme support production_thread_intake --project launch --root "$TMP_ROOT"
uv run agentic-os validate --root "$TMP_ROOT"
```

## Troubleshooting

| Symptom | Likely Cause | Fix |
| --- | --- | --- |
| Higher maturity level is refused | Required file-first evidence is missing | Fill contract, permissions, outputs, and audit sections before promoting. |
| New automation is too powerful | Maturity was manually edited past `observe` | Reset to `observe` or use `set-maturity` with evidence. |
| Project does not show automation attachment | Attachment command was not run or project slug was wrong | Run `automation attach` with the correct project slug. |

## Source Artifacts

- Installed spec: `SPECS/04-automation-maturity-and-reconfiguration/SPEC.md`
- Installed worklog folder: `worklogs/source-features/04-automation-maturity-and-reconfiguration/`
- Implementation: `src/genomes_agentic_os/automation_ops.py`
- CLI parser: `src/genomes_agentic_os/cli.py`

No diagram is included. The maturity table and command sequence are the more
useful operating surface.

