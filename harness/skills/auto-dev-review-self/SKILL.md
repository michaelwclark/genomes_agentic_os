---
name: auto-dev-review-self
description: Independently review and repair the exact pull-request family created by Auto-Dev PR Create, then converge it to merge readiness without creating another PR.
---

# Auto-Dev Review Self

Require the completed `$auto-dev-pr-create` family receipt, then delegate review
and repair to `$auto-dev-review-repair`. Require an opposing model/family where
policy calls for independence, then use live Jira, PR checks, and review
threads.

Treat every PR in the family receipt as one delivery unit:

1. Validate the current Jira description and acceptance criteria, then prove
   the implementation actually solves them.
2. Check the effective project dev standards, including existing-utility
   reuse, security, readability, bug-fix what/why comments, and
   acceptance-path tests.
3. Propagate every actionable Copilot finding and every blocking reviewer
   finding to all required family targets unless target-specific evidence
   proves it does not apply.
4. Fix or factually answer bot threads before resolving them. Never
   automatically resolve a human thread.
5. Withhold family readiness when any required sibling is stale, failing,
   missing the repair, or lacks the required evidence.

This stage must not create or retarget a PR; a missing or wrong target returns
to PR Create. Record `review_self` only after every exact family head is
`ready_for_merge`. This alias does not grant merge authority.
