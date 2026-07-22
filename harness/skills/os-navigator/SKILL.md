# OS Navigator

Use when an agent needs to orient inside `~/agentic_os`, route a request, or decide which OS files to read next.

## Workflow

1. Read root `ROUTER.md`.
2. Pick the domain.
3. Read domain `ROUTER.md`, `CONTEXT.md`, and `REFERENCES.md`.
4. Check `00-control-plane/active-work.md`.
5. For project-known ideas or features, check date-prefixed packets directly
   under `work-items/`, then `work-items/99-archived/` for returned tickets.
6. Return the target layer, path, approval risk, and next file to edit.

## Work-Item Rule

Use increasing indexed, date-prefixed packet names such as
`work-items/072126-001_idea_slug/`. The packet stays at that path as lifecycle
state changes. Subtasks remain inside the packet and use the parent index.
`01-intake`, `02-active`, and `03-complete` are read-only legacy import paths.

## Output Contract

Always return `domain`, `lane`, `object_type`, `target_path`, `approval_required`, and `next_action`.
