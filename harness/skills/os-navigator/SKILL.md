# OS Navigator

Use when an agent needs to orient inside `~/agentic_os`, route a request, or decide which OS files to read next.

## Workflow

1. Read root `ROUTER.md`.
2. Pick the domain.
3. Read domain `ROUTER.md`, `CONTEXT.md`, and `REFERENCES.md`.
4. Check `00-control-plane/active-work.md`.
5. Return the target layer, path, approval risk, and next file to edit.

## Output Contract

Always return `domain`, `lane`, `object_type`, `target_path`, `approval_required`, and `next_action`.
