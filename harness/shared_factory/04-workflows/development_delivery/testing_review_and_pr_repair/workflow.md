# Testing, Review, and PR Repair

## Flow

![Auto-Dev Development Delivery stages](../../../00-programs/auto_dev/assets/development-delivery-stages.svg)

## What this does

Proves the implementation with a risk-based test triangle, opens the PR only
after a pre-PR review, and repairs CI and review findings until the PR is truly
ready or a classified blocker is exhausted.

## Manual run

Use `/auto-dev-review-repair`, then record verified work with
`agentic-os develop stage <state.json> --stage review ...`.

## Inputs

- Implementation diff/commits, acceptance criteria, risk/test plan, project
  validation commands, PR/Copilot policies, and optional local-environment
  failure evidence.

## Outputs

- Test ledger, pre/post opposing-review decisions, PR URL/number, CI and review
  receipts, repair commits, and `ready_for_merge` or blocked decision.

## States

`local_validation -> pre_pr_review -> pr_open -> ci_repair -> review_repair ->
post_pr_review -> ready_for_merge`. Repair transitions return to the owning
failure state, not to discovery.

## Steps

1. Run Arrange-Act-Assert tests selected by risk: micro requires unit; standard
   unit+integration; high unit+integration+repository end-to-end.
2. Classify each command as passed, code failed, environment unavailable, or
   not applicable. Never call infrastructure failure a pass.
3. Run a pre-PR opposing-harness review against ticket, plan, evidence, diff,
   tests, security, data migration, observability, and recovery concerns.
4. Repair actionable findings, push a task-owned branch, open the PR, and
   verify tracker linkage and safe external text.
5. Watch required GitHub checks quietly. When local execution was impossible,
   CI becomes the final test signal only with explicit environment evidence.
6. Resolve actionable Copilot/human review threads, rerun affected tests, push,
   and watch again. Do not blindly rerun unchanged failures more than once.
7. Run post-PR opposing review against the final diff and check/review state.

## Validations

- Required test layers exist and pass, or permitted CI fallback passes.
- Tests are deterministic, behavior-oriented, and use 3A structure where
  applicable; changed failure paths and integrations have coverage.
- Pre/post review decisions have model/harness and input/output receipts.
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
  open PR, and require remote CI when profile permits; otherwise block.
- Flaky/infrastructure CI: one evidence-based rerun; persistent failures block
  or route to infrastructure ownership.
- Review findings: repair actionable issues; record reason for non-actionable
  findings. Never dismiss silently.
- Opposing harness unavailable: retry alternate configured harness/model; pause
  for human review if mandatory and all configured routes fail.

## Events and receipts

Emit `quality.layer.completed|failed`, `review.pre_pr.completed`, `pr.opened`,
`ci.failed|passed`, `review.finding.repaired`, `review.post_pr.completed`, and
`task.ready_for_merge`. Store commands/results, environment evidence, reviewer
prompt/response/model, PR snapshot, check runs, threads, and repair commits.

## Cleanup and handoff

Quiet watchers retain compact state/summary receipts and prune raw logs by
policy. Handoff only after final remote readback proves checks and threads are
clean; keep the worktree until merge is observed.
