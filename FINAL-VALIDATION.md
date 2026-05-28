# Final Validation

Deferred manual and live-install validation items for Plan 15.

## Plan 15: Always-On Runtime, Heartbeats, Schedules, And Integrations

Source-package validation already completed:

- `uv run pytest -q` passed with 50 tests.
- Temp-root smoke validation passed for runtime init, schedule run-due, heartbeat dry-run, runtime doctor, runtime run-next dry-run/apply, runtime validate, and local Notion runtime tracking manifest apply.

Manual/live validation to run later:

1. Update the live installed OS documentation only after approval.

   ```bash
   agentic-os docs update --root ~/agentic_os
   ```

   Evidence to capture:

   - Command exit code.
   - List of created/skipped files.
   - Confirmation that local live-install edits were not overwritten.

2. Validate the live installed OS root after docs update.

   ```bash
   agentic-os validate --root ~/agentic_os
   ```

   Evidence to capture:

   - Command exit code.
   - Any validation warnings or errors.

3. Run runtime doctor on the live installed OS root.

   ```bash
   agentic-os runtime doctor --root ~/agentic_os
   ```

   Evidence to capture:

   - Command exit code.
   - Any blocker or fix-soon findings.
   - Expected credential findings, if credentials are intentionally absent.

4. Run live-root schedule and heartbeat dry-runs.

   ```bash
   agentic-os schedule run-due --root ~/agentic_os --dry-run
   agentic-os heartbeat run granola_recent_notes_sync --root ~/agentic_os --dry-run
   ```

   Evidence to capture:

   - Queue/log paths written or planned.
   - Confirmation that no provider-backed external effects occurred.

5. Verify Genome's Notion runtime tracking target before any live Notion write.

   ```bash
   agentic-os notion track-runtime --root ~/agentic_os --dry-run
   ```

   Evidence to capture:

   - Planned databases: Integrations, Execution Targets, Heartbeats, Schedules, Run Queue, Approvals, Runs.
   - Confirmation that the target workspace is Genome's Notion.
   - Confirmation that no token values are printed.

6. Apply runtime tracking only after Genome's Notion is verified.

   ```bash
   agentic-os notion track-runtime --root ~/agentic_os --apply --verified-workspace "Genome's Notion"
   ```

   Evidence to capture:

   - Command exit code.
   - `.notion-runtime-tracking/manifest.yml` exists.
   - Manifest includes `database_ids`.
   - No writes occurred to Michael Clark's personal Notion or any fallback workspace.

7. Run one read-only integration health check and capture a run log.

   Preferred first check:

   ```bash
   agentic-os integration doctor granola --root ~/agentic_os
   agentic-os integration setup granola --root ~/agentic_os --dry-run
   ```

   Evidence to capture:

   - Command exit codes.
   - Run log path or dry-run output.
   - Confirmation that full meeting transcripts were not synced to Notion by default.

8. Exercise guarded dispatch on the live root only after reviewing the queue item.

   ```bash
   agentic-os runtime run-next --root ~/agentic_os --dry-run
   ```

   Apply only if the item is local/script-safe and does not require approval:

   ```bash
   agentic-os runtime run-next --root ~/agentic_os --apply
   ```

   Evidence to capture:

   - Queue item id.
   - Dispatch log path.
   - Final queue status.
   - Confirmation that Orgo, Composio, AgentMail, Granola, and Notion provider-backed work stayed blocked or approval-needed unless explicitly approved.
