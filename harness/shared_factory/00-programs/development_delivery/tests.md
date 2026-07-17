# Test contract

- Unit: profile loading, compatibility translation, state transitions,
  idempotency, retries, lease recovery, and risk-to-test mapping.
- Integration: real temporary Git repository creates a worktree from the exact
  fetched base and registers it under the project.
- End to end: CLI dry-run/apply produces readable portfolio/task receipts.
- Documentation: every workflow has exactly `workflow.md` and `workflow.yml`,
  all required sections, inputs, outputs, states, validation, failure recovery,
  events, receipts, and cleanup.

Feature work must select tests using the same risk-based triangle. A failing
local environment is a distinct result, never a passing result.
