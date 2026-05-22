# Memory

- The current-state/gap-map feature is validated through docs install/update
  and runtime plan mirror checks, not through a feature-specific command.
- `agentic-os docs update --root <root>` should report `no changes` on a fresh
  install after `docs install`, and the root should remain valid.

