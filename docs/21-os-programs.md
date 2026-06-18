# 21 · OS Programs

> **Purpose:** make named OS capabilities easy to create, explain, update,
> investigate, retire, and promote without rediscovering which skills, commands,
> workflows, automations, docs, scripts, schedules, Notion pages, and state files
> belong together.
>
> **You'll use:** `agentic-os program create`, `agentic-os instance-program create`,
> the `program-builder` skill, and the program folder's `components.yml`.
> **Prereqs:** an installed OS root and a routed domain.

---

## Terms

An **OSProgram** is a shared Genomes Agentic OS capability:

```text
harness/shared_factory/00-programs/<program>/
```

Use it when the capability should ship with the OS installer or be reusable
across installed OS instances.

An **InstanceOSProgram** is a capability owned by one installed OS instance or
domain:

```text
<domain>/00-programs/<program>/
```

Use it for local subsystems such as a Team PR Sync board, client-specific
automation suite, or private workflow set.

Programs do not replace workflows or automations. They are ownership and context
bundles around named capabilities that may include workflows, automations, skills,
commands, templates, documentation, run logs, scripts, schedules, state files, and
external systems.

---

## Folder contract

Both program types use the same file set:

```text
<program>/
  AGENTS.md
  ROUTER.md
  CONTEXT.md
  RULES.md
  TOOLS.md
  config.toml
  program.md
  components.yml
  context-pack.md
  crud.md
  documentation.md
  runbook.md
  tests.md
  worklog.md
  artifacts/
```

The important files:

| File | Role |
| --- | --- |
| `program.md` | Purpose, aliases, owner, scope, status, and linked surfaces. |
| `components.yml` | Machine-readable map of linked skills, commands, workflows, automations, scripts, docs, Notion surfaces, schedules, and state. |
| `context-pack.md` | What agents load for read, update, investigate, operate, and promote work. |
| `crud.md` | How create/read/update/delete changes propagate across linked components. |
| `documentation.md` | Filesystem and Notion projection contract. |
| `runbook.md` | How to operate and recover the program. |
| `tests.md` | Validation commands and evidence expectations. |
| `worklog.md` | Program-local change history and validation receipts. |

---

## Commands

Create a shared OSProgram:

```bash
agentic-os program create os_program_lifecycle --root ~/agentic_os
```

Create an instance/domain program:

```bash
agentic-os instance-program create los team_pr_sync --root ~/agentic_os
```

Both commands are additive. They create the program folder, program context files,
`components.yml`, documentation stubs, `artifacts/`, and a `config.toml` layer.

---

## CRUD routing

When a prompt names a program or one of its aliases, agents should load the
program folder before editing component internals.

| Intent | Load First | Then Load |
| --- | --- | --- |
| Create | `program.md`, `components.yml`, `documentation.md` | command docs, skill adapters, workflow or automation specs |
| Read/explain | `context-pack.md`, `components.yml` | linked source docs, scripts, state, latest logs |
| Update/tweak | `crud.md`, `components.yml`, `tests.md` | affected scripts, templates, schedules, docs, tests |
| Delete/retire | `RULES.md`, `components.yml`, `runbook.md` | schedules, external systems, archive plan; destructive action needs approval |
| Investigate | `runbook.md`, `tests.md`, `worklog.md` | latest logs, state files, source receipts |
| Promote | `documentation.md`, `components.yml` | source package docs, templates, registry rows, tests |

The update standard is broader than a code patch: behavior changes must update
the linked docs, routing, validation, and external projection notes.

---

## Documentation rule

Do not ship undocumented OS-level behavior. Any new OS-level feature, program,
skill, command, workflow, automation, rule, hook, template, runtime convention,
or external projection must document:

- Ownership.
- Context routing.
- Validation.
- Filesystem and Notion projection updates when applicable.
- A worklog or run-log receipt.

This rule exists in root `RULES.md`, `harness/rules/os-authoring-rules.md`, and
the `program-builder` skill.

---

## Promotion path

Start instance-specific work as an `InstanceOSProgram` under the owning domain.
Promote it to an `OSProgram` only when:

- More than one domain or install needs the capability.
- The behavior is stable enough to template.
- The source package docs, CLI, templates, registries, tests, and migration notes
  are updated together.

Promotion is an OS feature change, so it must carry tests and documentation.

---

## Running this from Claude vs Codex

**Claude:** use `/create-program` or `/create-instance-program` when those command
docs are installed, or invoke the `program-builder` skill directly.

**Codex:** use `agentic-os program create <name>` or
`agentic-os instance-program create <domain> <name>`, then fill the generated
files and update linked components. Re-run `agentic-os validate` before handoff.
