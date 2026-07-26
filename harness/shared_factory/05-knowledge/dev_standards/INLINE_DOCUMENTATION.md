# Inline Documentation

Focus: anything slightly complex carries a what/why/how comment at the seam.

## Write
- Guards, fallbacks, data-repair paths, non-obvious invariants, and
  production-history workarounds get a short what/why/how comment at the
  decision point, anchored to the ticket key.
- Public functions/classes get a 1-2 line purpose docstring. No comments
  restating obvious code.

## Review
- Complex logic with zero explanation is a finding; comment noise on obvious
  assignments is a finding in the other direction.
- New config/settings surfaces carry operator-facing help text.

Blocking: no (fix when trivial, otherwise log with rationale).
