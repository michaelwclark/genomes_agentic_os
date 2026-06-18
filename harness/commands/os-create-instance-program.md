# OS Create Instance Program

Use when an installed OS instance has a named capability that should not ship as
shared Genomes Agentic OS functionality.

## Procedure

1. Route to the owning domain.
2. Run `agentic-os instance-program create <domain> <program> --root ~/agentic_os`.
3. Fill `program.md` with purpose, aliases, owner, scope, and status.
4. Fill `components.yml` with linked local workflows, automations, scripts, docs, schedules, state, Notion pages, and other external surfaces.
5. Fill `crud.md`, `context-pack.md`, `runbook.md`, `tests.md`, and `documentation.md`.
6. Update linked component docs and state so behavior changes are not stranded in one script or one prompt.
7. Record validation and next action in `worklog.md`.

## Completion Standard

When the user names the capability, agents can route directly to
`<domain>/00-programs/<program>/` and understand how CRUD work propagates across
the surrounding OS surfaces.
