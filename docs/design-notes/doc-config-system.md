# 23 · Doc Config System

Status: building
Priority: P0

## Problem

Agents need a reusable rule for where documents, Notion pages, specs,
plans, questions, and worklogs belong. Without a config-backed rule, every new
proposed feature requires re-explaining page structure and search order.

## Outcome

An agent can receive "Add this to Notion" or "save this as the plan" and produce a
deterministic route plan from Agentic OS config before writing.

## Scope

### In

- Global default doc config under `harness/shared_factory/00-control-plane/doc-config.yml`.
- Optional project-level overrides at `02-projects/<project>/config/doc-config.yml`.
- Configurable lifecycle buckets with `QUESTIONS` included when questions exist.
- Search/discovery method toggles for config, markdown, ripgrep, filesystem,
  Notion, context-mode, and memory.
- Notion style defaults for color variation and rich block usage.
- CLI doctor and dry-run route plan.
- Installed doc-config command/skill docs.
- Top-level `/add-spec` command and `spec-intake-router` skill that make
  doc-config the required first step for new spec and proposed-feature intake.
- Legacy `/new-feature`, `/add-feature`, `/new-idea`, and `feature-intake-router`
  aliases remain readable during migration.
- `/add-bug`, `bug-intake-router`, and managed `bug-intake` workflow for
  lightweight bug and missed-enforcement capture.
- `/auto-add-spec` and `auto-spec-intake` for long OS-shaping requests
  that should become local spec packets before implementation continues.
- Compact `os-authoring-rules.md` plus `os-authoring-guard` so reusable OS
  surfaces update worklogs, worktrees, paired command/skill access, and
  registries without loading the full manual.
- Strict schema coverage and focused tests.

### Out

- Live Notion page creation.
- Runtime analytics event writing.
- UI for editing the config.
- Replacing the existing work-item lifecycle.

## Implementation Files

- `src/genomes_agentic_os/doc_config.py`
- `src/genomes_agentic_os/cli.py`
- `templates/runtime/doc-config.yml`
- `schemas/doc-config.schema.json`
- `harness/commands/os-doc-config.md`
- `harness/commands/os-add-spec.md`
- `harness/commands/os-new-feature.md`
- `harness/commands/os-add-bug.md`
- `harness/commands/os-auto-add-spec.md`
- `harness/commands/os-auto-add-feature.md`
- `harness/skills/doc-config-router/SKILL.md`
- `harness/skills/spec-intake-router/SKILL.md`
- `harness/skills/feature-intake-router/SKILL.md`
- `harness/skills/bug-intake-router/SKILL.md`
- `harness/skills/auto-spec-intake/SKILL.md`
- `harness/skills/auto-feature-intake/SKILL.md`
- `harness/skills/os-authoring-guard/SKILL.md`
- `harness/rules/os-authoring-rules.md`
- `templates/runtime/spec-intake-workflow.md`
- `templates/runtime/feature-intake-workflow.md`
- `templates/runtime/bug-intake-workflow.md`
- `templates/planning/bug-report.md`
- `tests/test_doc_config.py`

## Validation

```bash
PYTHONPATH=src python -m pytest tests/test_doc_config.py tests/test_cli_scaffold.py tests/test_source_adapters.py -q
PYTHONPATH=src python -m pytest -q
agentic-os validate --root <fresh-root> --strict
```
