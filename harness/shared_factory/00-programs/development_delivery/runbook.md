# Operator runbook

1. Validate the project profile with a dry run.
2. Start one or more tickets with `--apply`; verify every ticket has a task
   state, active work item, and isolated worktree receipt.
3. Let the harness execute the five workflows in order. Use `status` for a
   compact readback; inspect a referenced receipt only when a gate fails.
4. For a recoverable failure, repair the cause and call `recover`. For a
   blocked task, preserve the blocker receipt and continue independent tasks.
5. After merge/deploy evidence is terminal, let the cleanup workflow archive
   the work item and remove the worktree according to project retention.

Do not restart a run by deleting state. Resume it using its run id and receipts.
