# Plan

1. Add workflow readiness operations for required file, section, placeholder, and supporting README checks.
2. Add run log closeout operations with final metadata, validation enforcement, and state writebacks.
3. Wire `workflow check` and `run-log close` into the CLI.
4. Add tests for readiness findings, invalid closeout status, validation enforcement, and activity updates.
5. Run full pytest and temp-root smoke validation.
