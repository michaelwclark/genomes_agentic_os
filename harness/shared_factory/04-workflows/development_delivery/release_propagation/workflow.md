# Release Propagation

## Flow

![Auto-Dev Development Delivery stages](../../../00-programs/auto_dev/assets/development-delivery-stages.svg)

## What this does

Translates tracker fix-version/release policy into the required target branches
and cherry-pick PRs without silently inventing release scope.

## Manual run

Use `/auto-dev-release-propagation`, then record verified work with
`agentic-os develop stage <state.json> --stage release_propagation ...`.

## Inputs

- Ready PR, tracker fix version, project release configuration, branch/version
  registry, merge commit when available, and target release eligibility rules.

## Outputs

- `not_required` decision or verified release target matrix, cherry-pick
  branches/PRs, conflict receipts, and `release_ready` decision.

## States

This workflow is a gated companion to `ready_for_merge`/`merged`:
`release_evaluation -> not_required|release_preparing -> release_ready|blocked`.

## Steps

1. Re-read fix version and project release policy; map them to canonical target
   branches through the version registry.
2. Decide whether the primary PR is sufficient or propagation is required.
3. After the source commit exists, create isolated release worktrees/branches
   and cherry-pick in dependency-safe order.
4. Resolve mechanical conflicts only when intent is unambiguous; otherwise
   block with the conflict set and original acceptance criteria.
5. Run target-branch validation, open linked release PRs, and watch their checks
   and review findings using the same quality policy.

## Validations

- Fix version, branch mapping, and release eligibility agree.
- Every required target has exactly one linked PR/receipt; no duplicate cherry
  pick exists.
- Cherry-picked diff preserves intent and target-specific tests pass.
- External tracker/PR links are verified after write.

## Success modes

- `not_required`: policy proves the primary branch delivers the fix.
- `release_ready`: every required release PR is open, green, review-clean, and
  linked to the source task.

## Failure modes and recovery

- Missing/ambiguous fix version: block for tracker grooming.
- Target mapping absent: block for release configuration repair.
- Cherry-pick conflict: keep isolated worktree, record conflict files, and retry
  after an intent-backed resolution.
- Target checks fail: repair on that target branch and rewatch.
- Partial propagation: keep completed targets and resume only missing/failed
  targets through idempotent target keys.

## Events and receipts

Emit `release.evaluated`, `release.not_required`, `release.target.started`,
`release.pr.opened`, `release.target.failed`, and `release.ready`. Store fix-
version snapshot, target matrix, source SHA, cherry-pick result, target tests,
PR/check snapshots, and conflict details.

## Cleanup and handoff

Remove release worktrees only after their PRs merge or are abandoned. Handoff
the target matrix and terminal evidence to deployment/cleanup; do not hold the
primary task active solely for raw release logs.
