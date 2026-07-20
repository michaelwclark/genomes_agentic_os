# Program Builder

Use when creating, updating, investigating, retiring, or documenting an
OSProgram or InstanceOSProgram.

## Terms

- `OSProgram`: a reusable shared Agentic OS capability under
  `harness/shared_factory/00-programs/<program>/`.
- `InstanceOSProgram`: an installed-instance capability under
  `<domain>/00-programs/<program>/`.

Programs are context and ownership bundles. They can reference skills, commands,
workflows, automations, scripts, templates, docs, run logs, state files, Notion
surfaces, schedules, and external systems.

## Workflow

1. Route to the shared factory for `OSProgram` work or the owning domain for
   `InstanceOSProgram` work.
2. Load `AGENTS.md`, `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`, and
   `program.md` from the program folder.
3. Load `components.yml` and select the narrowest linked component paths needed
   for the requested create, read, update, delete, investigate, operate,
   validate, document, or promote action.
4. Apply the change across affected scripts, commands, skills, workflows,
   automations, schedules, docs, templates, registries, tests, and state
   contracts.
5. Update `documentation.md`, `worklog.md`, and any declared Notion projection
   notes before handoff.

## Creation Commands

```bash
agentic-os program create <program> --root ~/agentic_os
agentic-os instance-program create <domain> <program> --root ~/agentic_os
```

## Documentation Rule

Do not create undocumented OS-level behavior. Any new feature, program, skill,
command, workflow, automation, rule, hook, template, runtime convention, or
external projection must document ownership, routing, validation, and update
propagation.

## Completion Standard

A fresh agent should be able to update the named program without chat history by
loading the program folder and following `components.yml`.

Notion or other human-facing program documentation must be rendered through
`$auto-dev-create-artifacts` with type `program` or `control-plane`. This skill
owns program structure; the artifact contract owns presentation and readback.
