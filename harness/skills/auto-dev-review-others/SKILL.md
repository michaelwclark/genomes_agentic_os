---
name: auto-dev-review-others
description: Friendly Auto-Dev name for blocker-focused review of another author's pull request through the canonical PR Review owner, without taking repair or merge authority.
---

# Auto-Dev Review Others

Delegate to `$pr-review` in `review --no-merge` mode; `$pull-request` remains
only a compatibility alias. Use the exact live diff and provider state and
report tight actionable findings. This Auto-Dev stage never repairs or merges,
even when the broader PR Review workflow has standing merge authority. Hand a
clean immutable review receipt to `$auto-dev-merge`, which alone revalidates
and executes an authorized merge. Record `review_others` evidence in
`autodev.json` when the step belongs to an Auto-Dev work item. Provider readback
must name provider, pull request, configured repository/base, reviewed head,
provider-qualified `author_identity`, derived `author_kind: others`,
`review_mode: review_no_merge`, `review_result: clean`, and
`readback_verified: true`. The frozen `task.authorship.ours` list, not the
caller, determines that classification. Merge receives this packet-local
receipt plus its SHA-256.
