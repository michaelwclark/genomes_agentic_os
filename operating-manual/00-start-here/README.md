# Start Here

## The Five-Minute Rule

When you enter the OS, do this before creating anything:

1. Read root `ROUTER.md`.
2. Pick the domain.
3. Read `<domain>/ROUTER.md`.
4. Check `<domain>/00-control-plane/active-work.md`.
5. Reuse an existing project, workflow, or automation when one fits.

If the request is about improving Agentic OS itself, check `shared_factory/05-knowledge/plans/` before creating new planning notes.

## First Commands

```bash
agentic-os validate --root ~/agentic_os
agentic-os workflow create los engineering feature_dev --root ~/agentic_os
agentic-os automation create los support production_thread_intake --root ~/agentic_os
agentic-os run-log create los feature_dev --root ~/agentic_os
```

## What To Create First

Create in this order:

| Order | Object | Why |
| --- | --- | --- |
| 1 | Domain context | Agents need the room before the task. |
| 2 | Project | Active outcomes need a stable home. |
| 3 | Workflow | Repeatable judgment needs a written process. |
| 4 | Run log | Every execution needs evidence. |
| 5 | Automation | Only stable, low-risk workflows should become triggers. |

## Future Ideas

Reusable OS ideas belong under `shared_factory/05-knowledge/plans/`. Domain-specific ideas belong in `<domain>/01-inbox/raw-ideas.md` until triaged.
