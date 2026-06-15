# 12 Factory Template Import Backlog

## Table Of Contents

- [Purpose](#purpose)
- [Commands](#commands)
- [Installed Template Areas](#installed-template-areas)
- [Import Policy](#import-policy)
- [Sanitation Rules](#sanitation-rules)
- [Additive Updates](#additive-updates)
- [Source Artifacts](#source-artifacts)

## Purpose

Factory template import turns reusable operating patterns into managed runtime
templates under the installed OS shared factory.

Use it when a template should be available to future customer, room, workflow,
reference, runtime, or planning work without copying private source material
into customer-facing output.

## Commands

Install runtime templates and docs into an OS root:

```bash
agentic-os docs install --root ~/agentic_os
```

Restore missing managed assets without overwriting local edits:

```bash
agentic-os docs update --root ~/agentic_os
```

Validate the installed root after an update:

```bash
agentic-os validate --root ~/agentic_os
```

## Installed Template Areas

Runtime templates install under:

```text
shared_factory/05-knowledge/templates/
```

Important template families include:

- `room/`
- `stage/`
- `reference/`
- `profile/`
- `customer/`
- `planning/`
- `runtime/`
- `notion/`
- `workflow/`
- `automation/`

The installed OS keeps these as reusable runtime assets. The source repository
remains canonical for changes.

## Import Policy

Factory-derived source material must be classified before it becomes a reusable
template:

| Classification | Meaning | Runtime treatment |
| --- | --- | --- |
| copied | Generic and safe as-is. | Install as a managed template. |
| adapted | Useful pattern with private or project-specific details. | Rewrite into a generic template before install. |
| referenced | Useful source of truth but not a reusable runtime file. | Link or describe in docs, do not install as a template. |
| rejected | Too private, stale, or unsafe for reuse. | Keep out of runtime templates. |

This keeps the shared factory useful without turning historical client work
into hidden product assumptions.

## Sanitation Rules

Customer-facing templates must be generic before they ship.

Do not include:

- client names
- private project names
- private repository names
- tenant-specific operating details
- credentials, tokens, or secret placeholders that look real

Use role-based examples such as `Customer`, `Operator`, `Source System`, and
`Workflow` unless a template explicitly requires a public product name.

## Additive Updates

`agentic-os docs update` is additive. It restores missing managed files but does
not overwrite local operator edits.

Expected recovery flow:

```bash
rm ~/agentic_os/shared_factory/05-knowledge/templates/room/context.md
agentic-os docs update --root ~/agentic_os
agentic-os validate --root ~/agentic_os
```

Validation should pass after the missing managed template is restored.

## Source Artifacts

- Installed spec: `SPECS/12-factory-template-import-backlog/SPEC.md`
- Installed worklog spec: `worklogs/source-features/12-factory-template-import-backlog/SPEC.md`
- Installed worklog QA: `worklogs/source-features/12-factory-template-import-backlog/HOLDOUT_QA.md`
- Factory policy docs: `docs/12-factory-patterns/README.md`
- Source templates: `templates/`
- Runtime install logic: `src/genomes_agentic_os/scaffold.py`
- Runtime validation: `src/genomes_agentic_os/validate.py`
- Test coverage: `tests/test_cli_scaffold.py`
