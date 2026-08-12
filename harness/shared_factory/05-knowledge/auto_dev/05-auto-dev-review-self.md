# Auto-Dev: review and repair our work

Use `/auto-dev-review-self`; it delegates to the canonical
`/auto-dev-review-repair` owner. This stage challenges, tests, and repairs an
agent-authored change until the exact pull-request revision is ready for
Finalize or an explicit blocker remains. It consumes the family created by PR
Create and never creates or retargets a pull request.

## Inputs

- completed Development and PR Create family evidence for the registered
  worktree and revision;
- tracker acceptance behavior and risk assessment;
- effective development, QA, review, artifact, and GitFlow policy;
- exact provider-read repository/base/branch and sibling pull-request family.

## Review and repair loop

1. Review the complete diff as if it came from another author. Check behavior,
   edge cases, security, data/migrations, compatibility, failure handling,
   observability, tests, docs, and accidental changes.
2. Run the configured local tests and quality gates and record exact outcomes.
3. Obtain the required independent or opposing-model review only through
   `/auto-dev-review-self-opposing-model <TICKET>`. A reviewer that is
   unavailable is recorded according to project policy; actual findings remain
   blocking.
4. Verify every pull request from the canonical PR Create family receipt. A
   missing, extra, or wrong target returns to PR Create.
5. Read live CI checks, required reviews, automated-review threads, and human
   discussion from the provider.
6. Classify each failure or finding before editing. Repair the smallest
   responsible code and add regression evidence.
7. Rerun affected local checks, push the new revision, and re-read provider
   state. Do not dismiss or mark a thread resolved until the code and evidence
   actually address it.
8. Bound repeated loops. If the same failure returns without new evidence,
   capture one blocker with the root cause and next discriminating action.
9. For any serializer, request payload, canonicalization, persisted
   configuration, rule, or template input change, run the runtime-consumer
   contract gate. Review the complete consumer inventory and tenant impact
   matrix; inspect legacy and canonical-shape tests through the real evaluator;
   and reject a producer-only change that can yield a silent empty result.

Use quiet watchers for CI and long tests. Keep raw output in durable logs and
surface only terminal check results or blocker-grade summaries in chat.

## Pull-request family expectations

When project GitFlow requires more than one pull request, verify every sibling
has the correct source and target, equivalent intended fix, compatible
migration/dependency order, and its own live checks. Do not assume one green
pull request proves its siblings.

## Done criteria

The stage records the provider, pull request family, exact head revisions,
commands, checks, independent review, addressed findings, unresolved blockers,
and live readback. Contract-risk changes additionally record the consumer
matrix, tenant impact matrix, compatibility strategy, and exact evaluator
evidence.

It ends at `ready_for_merge` only when the exact current revisions satisfy the
effective policy. That status is evidence for Finalize; it is not approval or
authority to merge, release, or deploy.
