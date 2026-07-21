# Operator runbook

1. Validate the project profile with a dry run.
2. Start one or more tickets with `--apply`; verify every ticket has a task
   state, active work item, and isolated worktree receipt.
3. Let the harness execute the applicable named Auto-Dev workflows. Use
   `agentic-os auto-dev status <work-item>` for the plain-English resume view
   and `develop status` for canonical portfolio/task readback.
4. For a recoverable failure, repair the cause and call `recover`. For a
   blocked task, preserve the blocker receipt and continue independent tasks.
5. Record Merge to `merged` with provider-read `merge_sha`, `source_head_sha`
   equal to the reviewed `subject_revision`, `provider`, `pull_request`, and
   `readback_verified: true`. Record Deploy to `post_deploy_validation` and
   Closeout to `delivery_complete` as separate receipt-backed stages. Then invoke Auto-Dev
   Health to audit receipts, remove only reconstructable item-local resources,
   move the preserved packet to finished, refresh active projections, and
   record strict readback.

Do not restart a run by deleting state. Resume it using its run id and receipts.
