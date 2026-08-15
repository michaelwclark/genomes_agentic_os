---
name: auto-dev-review-repair
description: Consume the canonical Auto-Dev review findings, repair the exact PR family, and use bounded delta verification to prove merge readiness without starting another full review.
---

# Auto-Dev Review and Repair

1. Verify the completed `$auto-dev-pr-create` family receipt, exact head SHA,
   clean intended diff, and required QA layers.
2. Consume the canonical full-review receipt and findings ledger owned by
   `$auto-dev-review-self`. If it is missing or its stable key does not match
   the exact review subject, return to Review Self. Never invoke another full
   review from Repair.
3. Re-read every provider PR from the PR Create receipt. Do not open or retarget
   a PR here; return a missing or wrong target to PR Create.
4. Use the quiet PR watcher for checks. Inspect a failure once, classify code
   versus infrastructure, fix from evidence, push, and re-watch.
5. Resolve actionable review threads; render outward comments/reviews through
   artifact contracts.
6. After a repair push, request delta verification only for the commits/files
   changed since the parent reviewed head. Chain each delta receipt to the
   canonical full-review key and prior reviewed head. Stop after three deltas;
   exhaustion blocks before another reviewer call. If no repair changed the
   head, reuse the canonical receipt with zero reviewer calls.
7. Verify required checks, current head, unresolved threads, target branch,
   release siblings, residual risk, and the complete findings ledger. Post at
   most one consolidated terminal provider comment using
   `<!-- agentic-os-review:<key> -->`; re-read the head before posting and reuse
   an existing marker instead of posting again.
8. Create typed `development-stage-evidence/v1` receipts with provider/check
   readback, then record the stage with one receipt per state:

```bash
agentic-os develop stage <state.json> --stage review \
  --receipt pre_pr_review=<canonical-full-review.json> --receipt pr_open=<pr-readback.json> \
  --receipt ci_repair=<ci-pass-or-repair-receipt.json> \
  --receipt review_repair=<thread-resolution-receipt.json> \
  --receipt post_pr_review=<canonical-or-delta-chain.json> --receipt ready_for_merge=<decision.json> \
  --idempotency-prefix <run:ticket:review>
```

`pre_pr_review` and `post_pr_review` remain compatibility receipt names, not two
full-review checkpoints. The former binds the one canonical full review; the
latter binds its reuse or final delta chain. The `ci_repair` and
`review_repair` receipts may explicitly say no repair was needed, but they must
prove the corresponding gate was checked.
