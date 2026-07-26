# Correctness And Acceptance Fit

Focus: the change does what the tracker item's acceptance criteria say, including the negative paths.

## Write
- Implement to the acceptance criteria, not the ticket title. Each AC maps to
  code and a test before the PR opens.
- Negative paths and idempotency ACs get explicit coverage.

## Review
- Trace every AC to file:line plus test evidence in under a minute. `MISSING`
  mappings are blocking.
- Verify the negative/ambiguous paths the AC names (ownership not stolen,
  duplicates not created, retries idempotent).

Blocking: always.
