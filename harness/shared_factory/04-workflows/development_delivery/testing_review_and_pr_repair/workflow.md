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

- Test ledger, pre/post opposing-review decisions, provider-read PR-family
  snapshot, CI and review receipts, repair commits, and `ready_for_merge` or
  blocked decision.

## States

`local_validation -> pre_pr_review -> pr_open -> ci_repair -> review_repair ->
post_pr_review -> ready_for_merge`. Repair transitions return to the owning
failure state, not to discovery.

`pre_pr_review`, `pr_open`, and `post_pr_review` are stable lower-level receipt
names. In canonical Auto-Dev runs, `pre_pr_review` stores the initial opposing
review, `pr_open` stores the provider readback already created by PR Create,
and `post_pr_review` stores the final opposing review. These labels do not grant
this workflow pull-request creation or targeting authority.

## Steps

1. Run Arrange-Act-Assert tests selected by risk: micro requires unit; standard
   unit+integration; high unit+integration+repository end-to-end.
2. Classify each command as passed, code failed, environment unavailable, or
   not applicable. Never call infrastructure failure a pass.
3. Run the initial opposing-harness review against ticket, plan, evidence,
   diff, tests, security, data migration, observability, and recovery concerns.
   Store it under the stable `pre_pr_review` receipt name.
4. Repair actionable findings, push the task-owned branch, and re-read every PR
   from the canonical PR Create family receipt. Return missing, extra, or wrong
   targets to PR Create.
5. Watch required GitHub checks quietly. When local execution was impossible,
   CI becomes the final test signal only with explicit environment evidence.
6. Resolve actionable Copilot/human review threads, rerun affected tests, push,
   and watch again. Do not blindly rerun unchanged failures more than once.
7. Run final opposing review against the final diff and check/review state.
   Store it under the stable `post_pr_review` receipt name.

## Validations

- Required test layers exist and pass, or permitted CI fallback passes.
- Tests are deterministic, behavior-oriented, and use 3A structure where
  applicable; changed failure paths and integrations have coverage.
- Pre/post review decisions have model/harness and input/output receipts.
- The provider-read PR family exactly matches the canonical PR Create receipt.
- All required checks pass and no actionable review/Copilot threads remain.
- PR contains no secret, private link, or local filesystem leakage.

## Success modes

- `ready_for_merge`: tests, required checks, review threads, and final opposing
  review are clean; merge policy is recorded.
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
- Opposing harness unavailable: retry alternate configured harness/model; pause
  for human review if mandatory and all configured routes fail.

## Events and receipts

Emit `quality.layer.completed|failed`, the compatibility
`review.pre_pr.completed`,
`pr.family.verified`, `ci.failed|passed`, `review.finding.repaired`,
the compatibility `review.post_pr.completed`, and `task.ready_for_merge`. Store
commands/results, environment evidence, reviewer prompt/response/model,
canonical PR Create family receipt, provider snapshots, check runs, threads,
and repair commits.

## Cleanup and handoff

Quiet watchers retain compact state/summary receipts and prune raw logs by
policy. Handoff only after final remote readback proves checks and threads are
clean; keep the worktree until merge is observed.
