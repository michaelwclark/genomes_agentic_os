# Plan

1. Run the full CLI scaffold test suite.
2. Create a disposable runtime root.
3. Remove a managed customer template and confirm doctor reports a blocker.
4. Run `doctor --fix-missing` and confirm the file is restored.
5. Create an unclosed run log and confirm doctor reports a stale run finding.
6. Confirm migration apply fails before planning.
7. Create a migration plan, mutate the target, and confirm apply refuses drift.
8. Re-plan and apply successfully.
