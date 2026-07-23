---
name: auto-dev-review-repair
description: Run Auto-Dev opposing review, CI and review repair, and final merge-readiness checks for the exact PR family emitted by Auto-Dev PR Create.
---

# Auto-Dev Review and Repair

1. Verify the completed `$auto-dev-pr-create` family receipt, exact head SHA,
   clean intended diff, and required QA layers.
2. Run the configured pre-PR opposing review. Store findings and decision.
   The review must validate live Jira acceptance criteria, implementation
   effectiveness, reuse, security, readability, causal bug-fix comments, and
   acceptance-path tests.
3. Re-read every provider PR from the PR Create receipt. Do not open or retarget
   a PR here; return a missing or wrong target to PR Create.
4. Use the quiet PR watcher for checks. Inspect a failure once, classify code
   versus infrastructure, fix from evidence, push, and re-watch.
5. Treat Copilot and blocking reviewer findings as family-wide by default.
   Apply the repair to every required target, or record target-specific
   non-applicability evidence. Resolve bot threads only after the repair or a
   factual false-positive reply; never auto-resolve a human thread. Render
   outward comments/reviews through artifact contracts.
6. Run post-PR review and verify required checks, current head, unresolved
   threads, target branch, release siblings, family repair parity, Jira/AC
   effectiveness, all effective dev standards, and residual risk.
7. Create typed `development-stage-evidence/v1` receipts with provider/check
   readback, then record the stage with one receipt per state:

```bash
agentic-os develop stage <state.json> --stage review \
  --receipt pre_pr_review=<receipt.json> --receipt pr_open=<pr-readback.json> \
  --receipt ci_repair=<ci-pass-or-repair-receipt.json> \
  --receipt review_repair=<thread-resolution-receipt.json> \
  --receipt post_pr_review=<receipt.json> --receipt ready_for_merge=<decision.json> \
  --idempotency-prefix <run:ticket:review>
```

The `ci_repair` and `review_repair` receipts may explicitly say no repair was
needed, but they must prove the corresponding gate was checked.
