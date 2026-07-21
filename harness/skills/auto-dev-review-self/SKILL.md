---
name: auto-dev-review-self
description: Independently review and repair the exact pull-request family created by Auto-Dev PR Create, then converge it to merge readiness without creating another PR.
---

# Auto-Dev Review Self

Require the completed `$auto-dev-pr-create` family receipt, then delegate review
and repair to `$auto-dev-review-repair`. Require an opposing model/family where
policy calls for independence, then use live PR checks and review threads. This
stage must not create or retarget a PR; a missing or wrong target returns to PR
Create.
Record `review_self` only after the exact head is `ready_for_merge`. This alias
does not grant merge authority.
