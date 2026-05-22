# Plan

1. Create a fresh temporary installed OS root.
2. Remove managed watch-source runtime knowledge and restore it with docs update.
3. Validate the root.
4. Exercise connected-system list and doctor.
5. Create an enabled `agentic_os_kanban` watch source.
6. Exercise watch-source list, doctor, dry-run poll, dry-run run-due, and apply poll.
7. Assert source event and cursor state were written.
8. Corrupt the watch source and confirm doctor fails closed.
9. Run full pytest.
10. Commit the feature 51 artifact set.
