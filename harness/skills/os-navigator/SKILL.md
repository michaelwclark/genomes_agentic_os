# OS Navigator

Use when an agent needs to orient inside `~/agentic_os`, route a request, or decide which OS files to read next.

## Workflow

1. Read root `ROUTER.md`.
2. Pick the domain.
3. Read domain `ROUTER.md`, `CONTEXT.md`, and `REFERENCES.md`.
4. Check `00-control-plane/active-work.md`.
5. For project-known ideas or features, check the project `work-items/` lanes:
   `01-intake` for raw captured ideas, `02-active` for specified/building work,
   and `03-complete` for finished or documented work.
6. Return the target layer, path, approval risk, and next file to edit.

## Work-Item Rule

Use increasing indexed names. Default intake is a single markdown file such as
`work-items/01-intake/001_idea_slug.md`. If intake needs multiple files after a
duel/spec pass, expand it to `work-items/01-intake/001_idea_slug/` and keep the
same index. When an idea is solidified into work, the canonical object moves to a packet folder such as
`work-items/02-active/001_idea_slug/`. Subtasks use the parent index, for example
`001_01_update_database.md`.

## Output Contract

Always return `domain`, `lane`, `object_type`, `target_path`, `approval_required`, and `next_action`.
