# Isolated Implementation

## What this does

Creates durable task ownership and a clean, project-configured worktree, then
implements the scoped change with maintainable code and proportionate local
validation.

## Inputs

- `context_ready` receipt, implementation/test plan, tracker id, risk level,
  project profile, repository, and exact configured base branch.

## Outputs

- Active work-item packet, registered isolated worktree, exact base SHA,
  implementation commits/diff, updated tests, and local-validation receipt.

## States

`context_ready -> work_item_ready -> worktree_ready -> planned -> implementing
-> local_validation`.

## Steps

1. Create or resume exactly one active work item for the task.
2. Fetch the configured remote base and resolve its exact SHA.
3. Create one task branch/worktree beneath the project `worktrees/` directory;
   never edit the shared checkout.
4. Confirm the worktree is clean and ownership metadata matches the task.
5. Write the file-level plan and tests before or with behavior changes.
6. Implement the smallest coherent change, documenting non-obvious invariants,
   error handling, and recovery behavior inline.
7. Run fast static/unit checks as feedback and record the diff/commit receipt.

## Validations

- Work item is active and uniquely linked to tracker/run/task.
- Worktree path is under configured project storage, branch is task-owned, base
  SHA is the fetched remote base, and shared checkout is untouched.
- Code follows existing good project patterns; intentional deviations are
  documented as decisions.
- Changed behavior has tests; comments explain why, not obvious syntax.
- No secrets, generated junk, or unrelated user changes enter the diff.

## Success modes

- `local_validation`: implementation is complete enough for the full quality
  workflow and has traceable work-item/worktree receipts.

## Failure modes and recovery

- Destination/branch ownership conflict: block, never reuse or overwrite.
- Fetch/base missing: retry provider failures, then block with command receipt.
- Shared checkout dirty: ignore its unrelated state and use a new worktree; do
  not clean/reset user changes.
- Implementation regression: remain in `implementing`, repair, and rerun the
  smallest failing check.
- Local environment unavailable: classify distinctly and hand evidence to the
  next workflow only when CI fallback is enabled.

## Events and receipts

Emit `work_item.created|resumed`, `worktree.created`, `implementation.started`,
`implementation.updated`, and `local_validation.completed|failed`. Store work
item path, worktree registry entry, branch/base SHA, plan, changed-files list,
test changes, commands, and classified results.

## Cleanup and handoff

Do not delete implementation work on failure. Release an expired worker lease
for safe resumption. Handoff the active work item, clean task ownership, diff,
and validation evidence to testing/review.
