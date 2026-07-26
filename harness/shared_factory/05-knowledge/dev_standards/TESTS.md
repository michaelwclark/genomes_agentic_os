# Tests

Focus: unit floor for every behavior change; integration and end-to-end where the change warrants; regression tests reproduce the incident.

## Write
- Unit tests are the floor for every behavior change; integration tests when
  a service/module boundary or persistence is involved; an end-to-end or
  workflow test when a user-visible flow changed and the harness supports it.
- Regression tests reproduce the exact reported failure shape (data, config)
  before the fix, and are named/traceable to the ticket. Tests assert
  behavior, not implementation internals.

## Review
- Changed high-risk behavior without a failing-first regression test is
  blocking. Assertion-free tests, tests that mock the code under test, and
  happy-path-only coverage on guarded paths are blocking.
- Do not demand tests for unreachable trivia; demand them where the bug
  lived.

Blocking: always for changed high-risk behavior.
