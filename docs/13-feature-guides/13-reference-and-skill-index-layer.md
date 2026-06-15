# 13 Reference And Skill Index Layer

## Table Of Contents

- [Purpose](#purpose)
- [Commands](#commands)
- [Runtime Reference Paths](#runtime-reference-paths)
- [Reference Files](#reference-files)
- [Context Builder Behavior](#context-builder-behavior)
- [Skill Index](#skill-index)
- [Validation](#validation)
- [Source Artifacts](#source-artifacts)

## Purpose

The reference and skill index layer gives installed OS roots a shared place for
operating references that should be loaded across rooms, domains, workflows,
and context packets.

Use it for durable rules such as naming conventions, source priority, tool
selection, style/output expectations, and decision-log patterns. Do not bury
these rules inside one project or one workflow when they are meant to shape the
whole installed OS.

## Commands

Install or update runtime references:

```bash
agentic-os docs install --root ~/agentic_os
agentic-os docs update --root ~/agentic_os
```

Build a context packet that includes shared references:

```bash
agentic-os context build --root ~/agentic_os --domain shared_factory
```

Validate the installed reference layer:

```bash
agentic-os validate --root ~/agentic_os
```

## Runtime Reference Paths

Reference templates install under:

```text
shared_factory/05-knowledge/templates/reference/
```

Runtime reference files install under:

```text
shared_factory/05-knowledge/references/
```

Templates are reusable source shapes. Runtime references are the files agents
should read when building context or making operating decisions.

## Reference Files

The reference layer currently includes:

| File | Runtime use |
| --- | --- |
| `naming-conventions.md` | Stable names for domains, workflows, rooms, files, and generated artifacts. |
| `tool-index.md` | Which local tools, skills, or commands are expected for common jobs. |
| `source-priority.md` | Which source wins when repo, installed OS, Notion, and chat context disagree. |
| `style-and-output-rules.md` | How outputs should be structured, written, and handed off. |
| `decision-log.md` | How durable decisions should be recorded. |

Keep these files generic and operator-safe. Client-specific procedures belong
in customer or project surfaces, not the shared reference layer.

## Context Builder Behavior

`agentic-os context build` produces a deterministic packet for a domain,
project, workflow, or lane. Shared reference files are included so agents do
not have to rediscover global naming, tool, source-priority, or style rules.

Basic flow:

```text
requested work
  -> domain/project/workflow context
  -> shared_factory/05-knowledge/references/
  -> task-specific source files
  -> output or handoff
```

The reference layer should be broad enough to guide work, but not so large that
every context packet becomes noisy.

## Skill Index

Shared skills are tracked by the source registry:

```text
harness/skills/skill-registry.yml
```

Runtime copies install under:

```text
shared_factory/05-knowledge/skills/
```

The registry keeps Claude and Codex targets aligned even when each harness has
different install mechanics. Update the source skill registry before expecting
runtime docs or harness installs to expose a new shared skill.

## Validation

`agentic-os validate --root <root>` checks that required runtime references and
reference templates exist under the shared factory.

Validation should fail if required reference files are missing and should pass
after `agentic-os docs update --root <root>` restores missing managed files.

## Source Artifacts

- Installed spec: `SPECS/13-reference-and-skill-index-layer/SPEC.md`
- Installed worklog spec: `worklogs/source-features/13-reference-and-skill-index-layer/SPEC.md`
- Installed worklog QA: `worklogs/source-features/13-reference-and-skill-index-layer/HOLDOUT_QA.md`
- Reference templates: `templates/reference/`
- Skill registry: `harness/skills/skill-registry.yml`
- Context builder: `src/genomes_agentic_os/routing.py`
- Runtime docs install: `src/genomes_agentic_os/scaffold.py`
- Runtime validation: `src/genomes_agentic_os/validate.py`
- Test coverage: `tests/test_cli_scaffold.py`
