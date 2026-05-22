# 14 Client Automation And Control Plane Playbooks

## Table Of Contents

- [Purpose](#purpose)
- [Runtime Playbooks](#runtime-playbooks)
- [Commands](#commands)
- [Client Automation Brief](#client-automation-brief)
- [Control-Plane Bootstrap](#control-plane-bootstrap)
- [Context Audit](#context-audit)
- [Validation](#validation)
- [Source Artifacts](#source-artifacts)

## Purpose

Client automation and control-plane playbooks make repeatable client OS work
available as runtime command prompts and skills.

Use these playbooks when a customer OS needs automation discovery, control
plane bootstrap guidance, or a context audit without inventing the workflow
from scratch in the live project.

## Runtime Playbooks

Runtime command prompts install under:

```text
shared_factory/05-knowledge/commands/
```

Runtime skills install under:

```text
shared_factory/05-knowledge/skills/
```

Feature 14 requires these playbook surfaces:

| Playbook | Command prompt | Skill |
| --- | --- | --- |
| Client automation brief | `os-client-automation-brief.md` | `client-automation-brief/SKILL.md` |
| Control-plane bootstrap | `os-control-plane-bootstrap.md` | `control-plane-bootstrap/SKILL.md` |
| Context audit | `os-context-audit.md` | `context-audit/SKILL.md` |

## Commands

Install or restore runtime playbooks:

```bash
agentic-os docs install --root ~/agentic_os
agentic-os docs update --root ~/agentic_os
```

Validate playbook availability:

```bash
agentic-os validate --root ~/agentic_os
```

Related runtime commands:

```bash
agentic-os customer init --help
agentic-os automation check --help
agentic-os notion track-runtime --root ~/agentic_os --dry-run
```

## Client Automation Brief

The client automation brief separates work into automation-fit categories:

- deterministic and rule-based
- LLM-needed
- human-judgment
- not ready for automation

Use it before creating automation work so the OS captures what should be
scripted, what should stay review-gated, and what needs better source data.

Supporting templates live under:

```text
shared_factory/05-knowledge/templates/customer/
```

## Control-Plane Bootstrap

The control-plane bootstrap playbook keeps the filesystem as source of truth
and treats Notion as the control plane.

Use it with the Notion bootstrap and sync guides when creating or refreshing
Genome's Notion control-plane surfaces. Verify workspace identity before any
write and do not create fallback pages in another workspace.

## Context Audit

The context audit playbook checks whether a client OS has enough source
material, references, routing rules, and active-work state for reliable agent
execution.

Use it before pushing a client OS into heavier automation or recurring
heartbeats.

## Validation

`agentic-os validate --root <root>` requires the runtime command prompts and
skills for these playbooks. `agentic-os docs update --root <root>` should
restore missing managed playbook files without overwriting local edits.

## Source Artifacts

- Source plan: `PLANS/14-client-automation-and-control-plane-playbooks.md`
- Feature spec: `features/14-client-automation-and-control-plane-playbooks/SPEC.md`
- Feature QA: `features/14-client-automation-and-control-plane-playbooks/HOLDOUT_QA.md`
- Command prompts: `harness/commands/os-client-automation-brief.md`, `harness/commands/os-control-plane-bootstrap.md`, `harness/commands/os-context-audit.md`
- Skills: `harness/skills/client-automation-brief/SKILL.md`, `harness/skills/control-plane-bootstrap/SKILL.md`, `harness/skills/context-audit/SKILL.md`
- Customer templates: `templates/customer/`
- Notion templates: `templates/notion/`
- Runtime install logic: `src/genomes_agentic_os/scaffold.py`
- Runtime validation: `src/genomes_agentic_os/validate.py`
- Test coverage: `tests/test_cli_scaffold.py`
