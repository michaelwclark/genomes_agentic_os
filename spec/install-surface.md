# Install Surface

The OS needs to install into human and agent surfaces without forking the operating model.

## Filesystem Target

Default target:

```text
~/agentic_os
```

The target contains live operating state and client/domain overlays. This repo remains the source package.

Default installed roots:

```text
~/agentic_os/
  .agentic_root
  ROUTER.md
  AGENTS.md
  CLAUDE.md
  CONTEXT.md
  RULES.md
  TOOLS.md
  personal/
  clarks_consulting/
  los/
  shared_factory/
    05-knowledge/
      operating-manual/
      commands/
      skills/
      templates/
  archive/
```

Each root contains the standard domain router and numbered folders from `00-control-plane` through `08-archive`.

## Codex Target

Codex install should provide:

- Project or global `AGENTS.md` route bootstrap instructions.
- Installed root and domain `ROUTER.md`, `CONTEXT.md`, `RULES.md`, and `TOOLS.md` files for the route-read-cd-repeat loop.
- Runtime skill specs under `shared_factory/05-knowledge/skills/`.
- Runtime command prompts under `shared_factory/05-knowledge/commands/`.
- Optional validation scripts for context packs and specs.
- Rules for preserving local work and writing run logs.

## Claude Target

Claude install should provide:

- `CLAUDE.md` adapters that include `AGENTS.md` instead of duplicating instructions.
- Matching skill and command specs under `shared_factory/05-knowledge/skills/` and `commands/`.
- Same domain routing, workflow names, and output contracts as Codex.
- Memory policy references.

## Notion Target

Notion install should provide:

- OS Home page.
- Standard databases.
- Dashboard views.
- Relation properties between work items, runs, approvals, decisions, meeting notes, and artifacts.
- Stored IDs in filesystem config.

## Future Runtime Target

When database-backed state is added, install should also create:

- Database migrations.
- Event table.
- Work item table.
- Run table.
- Integration mapping table.
- Idempotency keys.
- Optional embedding table.
