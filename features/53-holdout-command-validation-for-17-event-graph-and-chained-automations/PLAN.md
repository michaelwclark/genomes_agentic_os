# Plan

1. Create a fresh temporary installed OS root.
2. Remove managed event runtime knowledge and restore it with docs update.
3. Validate the root.
4. Append a pull-request merged event and assert the event file and ledger index exist.
5. Enable the default docs-update chain rule and clear its repo filter for the holdout event.
6. Run chain doctor and chain test.
7. Run process-due in dry-run and apply modes.
8. Confirm idempotency skips repeated apply.
9. Replay the event.
10. Add a broken enabled rule and confirm dead-letter behavior.
11. Close a run log with event emission enabled.
12. Run full pytest.
13. Commit the feature 53 artifact set.
