# Spec Intake

Use this workflow whenever future work, a proposed feature, a spec, a plan, or
a Notion spec page needs to enter Agentic OS.

## Trigger Phrases

- `/add-spec`
- `/auto-add-spec`
- `/new-feature`
- `/add-feature`
- `/new-idea`
- "add a new feature"
- "capture this idea"
- "turn this into a spec"
- "add this to Notion as a spec"

## Workflow

1. Route the request through the current Agentic OS layer.
2. Read `harness/rules/os-authoring-rules.md` when the request changes
   convention policy, command/skill surfaces, workflow/automation setup,
   project worktrees, or filesystem mirror rules.
3. Run `agentic-os doc-config plan` with the original user request.
4. Confirm or infer the domain/project destination.
5. Ensure the project surface exists.
6. Create or repair a project work item.
7. Register external source checkouts with `agentic-os project worktree add`.
8. Populate configured buckets, including `QUESTIONS` when needed.
9. Mirror to Notion only after workspace verification.
10. Record the next action in the work item and append progress to `WORKLOG.md`.

## Required Artifacts

- `SPEC.md`
- `PLAN.md`
- `WORKLOG.md`
- `NEXT.md`
- `QUESTIONS.md` when unresolved questions exist
- registered `worktrees/<name>` link when source work uses an external checkout

## Source Of Truth

The filesystem work item is authoritative. Notion is the human control plane
projection unless local config explicitly changes the source of truth.

## Filesystem Mirror

- Keep lifecycle state in Agentic OS `work-items/`.
- Use `SPECS/` for scannable future-work/spec indexes.
- Use `worklogs/` or `WORKLOGS/` for human-readable work history, matching the
  project's local casing.
- Treat lowercase `logs/` as raw system output, transcripts, and runtime logs.
- Treat source repository `features/` and `.features/` folders as mirrors or
  implementation artifacts unless project config explicitly assigns lifecycle
  ownership there.
- If a source repository already has a product-code `/features` folder, do not
  create a competing OS lifecycle tree inside it.
- Do not generate `IDEA.md` for new packets. Existing `IDEA.md` files remain
  readable legacy capture.
