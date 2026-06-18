# OS Create Program

Use when a reusable Agentic OS capability spans one or more skills, commands,
workflows, automations, docs, templates, runtime state, or external surfaces.

## Procedure

1. Confirm the capability should ship with Genomes Agentic OS, not only this installed instance.
2. Run `agentic-os program create <program> --root ~/agentic_os`.
3. Fill `program.md` with purpose, aliases, owner, scope, and status.
4. Fill `components.yml` with linked skills, commands, workflows, automations, docs, scripts, schedules, state, and external systems.
5. Fill `crud.md`, `context-pack.md`, `runbook.md`, `tests.md`, and `documentation.md`.
6. Add or update the linked command docs, skill adapters, workflow specs, automation specs, registries, templates, and tests.
7. Update filesystem docs and any declared Notion projection notes before handoff.

## Completion Standard

A fresh agent can update the named capability by loading the program folder first,
then following `components.yml` to the narrowest linked component.
