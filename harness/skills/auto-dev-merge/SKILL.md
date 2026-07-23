---
name: auto-dev-merge
description: Execute and record the final live merge only from an immutable Finalize or PR Review readiness receipt, preserving project approval policy and provider readback.
---

# Auto-Dev Merge

1. Read the provider-qualified author identity (for example,
   `github:michaelwclark`) and classify it against the frozen
   `task.authorship.ours` list. Never accept a caller-selected `author_kind`.
2. For our PR family, require the immutable `$auto-dev-finalize` readiness
   receipt. For another author's PR, require the canonical PR Review readiness
   receipt. If either is absent, return to that owner without merging.
3. Immediately before mutation, re-read head SHA, target branch, checks,
   required reviews, unresolved threads, mergeability, and explicit authority.
4. Merge through the configured provider mechanism, then read the pull request
   back from that provider. Capture both the resulting merge SHA and the
   provider-reported source head SHA; the latter must exactly equal the
   `subject_revision` accepted by the `ready_for_merge` receipt.
5. Write a `development-stage-evidence/v1` receipt for `merged` with
   `status: completed` and all of these fields under `evidence`:
   `merge_sha`, `source_head_sha`, `provider`, `pull_request`, `repository`,
   `base_branch`, `author_identity`, `author_kind`, and
   `readback_verified: true`. `pull_request` is the stable provider reference,
   `repository` is the non-empty identity frozen in the task, and neither value is locally
   inferred. Repository and base must match the original PR authority chain.
   Then record this stage independently:

```bash
agentic-os develop stage <state.json> --stage merge \
  --receipt merged=<merge-readback.json> \
  --idempotency-prefix <run:ticket:merge>
```

This router owns no duplicate review loop and never treats green CI as approval.
Use
`harness/shared_factory/00-programs/auto_dev/templates/auto-dev-merge-evidence.json`
as the field guide. Health later requires its `terminal_authority.provider` and
`terminal_authority.ref` to equal this receipt's `provider` and `pull_request`,
and its terminal revision to equal `merge_sha`.
