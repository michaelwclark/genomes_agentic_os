# Plan

1. Run the repository test suite from the feature worktree.
2. Create a temporary OS root.
3. Run `agentic-os init`.
4. Run `agentic-os docs install`.
5. Validate the temporary root.
6. Check required plan files in the runtime mirror.
7. Run `agentic-os docs update` to prove idempotent update behavior.
8. Validate the temporary root again.
9. Record outputs and residual risk.

