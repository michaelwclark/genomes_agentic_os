# Testing, Review, and PR Repair

## Flow

![Auto-Dev Development Delivery stages](../../../00-programs/auto_dev/assets/development-delivery-stages.svg)

## What this does

Proves the implementation with a risk-based test triangle, verifies the exact
pull-request family created by PR Create, and repairs CI and review findings
until the family is truly ready or a classified blocker is exhausted.

This workflow does not open, retarget, or add pull requests. A missing or wrong
target returns to PR Create.

## Manual run

Use `/auto-dev-review-repair`, then record verified work with
`agentic-os develop stage <state.json> --stage review ...`.

## Inputs

- Canonical PR Create family receipt, implementation diff/commits, acceptance
  criteria, risk/test plan, project validation commands, PR/Copilot policies,
  and optional local-environment failure evidence.

## Outputs

- Test ledger, one canonical full-review decision, provider-read PR-family
  snapshot, CI and review receipts, repair commits, bounded delta decisions,
  and `ready_for_merge` or blocked decision.

## States

`local_validation -> canonical_full_review -> pr_open -> ci_repair ->
review_repair -> delta_verification -> ready_for_merge`. Repair transitions
return to the owning failure state, not to discovery or full review.

`pre_pr_review`, `pr_open`, and `post_pr_review` remain stable lower-level
compatibility receipt names. `pre_pr_review` binds the one canonical full
review owned by Review Self, `pr_open` stores the PR Create provider readback,
and `post_pr_review` binds reuse of that receipt or its final delta chain. The
labels do not represent two full-review checkpoints and grant no PR mutation.

## Steps

1. Run Arrange-Act-Assert tests selected by risk: micro requires unit; standard
   unit+integration; high unit+integration+repository end-to-end.
2. Classify each command as passed, code failed, environment unavailable, or
   not applicable. Never call infrastructure failure a pass.
3. Claim or reuse the stable exact-subject review key, then run the sole full
   opposing-harness review against ticket, plan, evidence, diff, tests,
   security, data migration, observability, and recovery concerns. Concurrent
   callers join the claim and exact-key reruns reuse its terminal receipt.
4. Repair actionable findings, push the task-owned branch, and re-read every PR
   from the canonical PR Create family receipt. Return missing, extra, or wrong
   targets to PR Create.
5. Watch required GitHub checks quietly. When local execution was impossible,
   CI becomes the final test signal only with explicit environment evidence.
6. Resolve actionable Copilot/human review threads, rerun affected tests, push,
   and watch again. Do not blindly rerun unchanged failures more than once.
7. Delta-verify only the repair commits/files against the canonical parent
   receipt. Chain no more than three delta receipts. If the head did not change,
   reuse the canonical receipt with no reviewer call.
8. Re-read the provider head after review and post at most one consolidated
   terminal comment containing `<!-- agentic-os-review:<key> -->`. Reuse the
   existing marked comment and store provider readback instead of reposting.

## Validations

- Required test layers exist and pass, or permitted CI fallback passes.
- Tests are deterministic, behavior-oriented, and use 3A structure where
  applicable; changed failure paths and integrations have coverage.
- The canonical review and delta decisions have exact subject, parent chain,
  model/harness, and input/output receipts.
- The provider-read PR family exactly matches the canonical PR Create receipt.
- All required checks pass and no actionable review/Copilot threads remain.
- PR contains no secret, private link, or local filesystem leakage.

## Success modes

- `ready_for_merge`: tests, required checks, review threads, and the canonical
  review/delta chain are clean; merge policy is recorded.
- `awaiting_human_review` may be represented as a non-error paused receipt when
  the project requires approval, while the task remains non-terminal.

## Failure modes and recovery

- Code/test/CI failure: inspect root cause, repair code/test, rerun the affected
  layer, then required checks; retry to configured limit.
- Environment unavailable: preserve command/error evidence, finish the change,
  return to PR Create if the family is missing, and require remote CI when the
  profile permits; otherwise block.
- Flaky/infrastructure CI: one evidence-based rerun; persistent failures block
  or route to infrastructure ownership.
- Review findings: repair actionable issues; record reason for non-actionable
  findings. Never dismiss silently.
- Opposing harness unavailable: record the terminal unavailable receipt; never
  switch reviewers to bypass the stable key or duplicate the full review.
- Review budget exhausted: block before a reviewer/provider call. Limits are
  one normal full review, three deltas, two absolute full reviews per family,
  and one provider post.

## Events and receipts

Emit `quality.layer.completed|failed`, `review.full.completed` or
`review.receipt.reused`, `pr.family.verified`, `ci.failed|passed`,
`review.finding.repaired`, `review.delta.completed`, the compatibility pre/post
events, one `review.provider_post.completed`, and `task.ready_for_merge`.
Store commands/results, environment evidence, reviewer prompt/response/model,
stable review keys, canonical PR Create family receipt, provider snapshots/post
readback, checks, threads, and repair commits.

## Cleanup and handoff

Quiet watchers retain compact state/summary receipts and prune raw logs by
policy. Handoff only after final remote readback proves checks and threads are
clean; keep the worktree until merge is observed.
