---
name: auto-dev-review-self
description: Independently review and repair the exact pull-request family created by Auto-Dev PR Create, then converge it to merge readiness without creating another PR.
---

# Auto-Dev Review Self

Review Self is the sole owner of the canonical full review. Require the
completed `$auto-dev-pr-create` family receipt, claim the stable review key for
the exact repository, PR, base/head revisions, policy fingerprint, scope, and
purpose, then run or reuse exactly one full opposing-model review through
`$auto-dev-review-self-opposing-model <TICKET>`. Concurrent callers join that
claim; a completed exact-key receipt is reused without another model call.

Pass the canonical findings ledger to `$auto-dev-review-repair`. Repair may
change code and request bounded delta verification, but it must never restart
the full review. Re-read live checks, threads, and the provider head after every
push. Record `review_self` only after one canonical receipt plus its delta chain
proves the exact current head is `ready_for_merge`.

The normal budget is one full review, at most three delta verifications, and one
consolidated terminal provider post. The absolute circuit breaker permits no
more than two full reviews for a PR family, including explicitly justified
recovery. Enforce every limit before a reviewer or provider call. This stage
must not create or retarget a PR; a missing or wrong target returns to PR Create.
It does not grant merge authority.
