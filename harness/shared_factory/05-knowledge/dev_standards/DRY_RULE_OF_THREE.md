# DRY Without Premature Abstraction

Focus: extract on the third occurrence; never speculate an abstraction on the first.

## Write
- Rule of three: first and second occurrence stay inline; third extracts a
  named helper co-located with its domain.
- Never extract a helper on first use; never flatten two cases into a generic
  before a third proves the shape.

## Review
- Flag both failure modes: scattered near-identical logic in 3+ sites
  (extract), and speculative abstraction serving one caller (inline it).

Blocking: no (fix when trivial, otherwise log with rationale).
