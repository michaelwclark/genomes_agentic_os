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

## Plan 16: Connected Source Watch Registry

Source-package validation already completed:

- `uv run pytest -q` passed with 54 tests.
- Temp-root smoke validation passed for watch-source list, doctor, poll dry-run, run-due dry-run, and root validation.

Manual/live validation to run later:

1. Verify the active Notion target is Genome's Notion before any live Notion read.

   Evidence to capture:

   - Connected workspace name.
   - Parent/test database identity.
   - Confirmation that no token values are printed.
   - Confirmation that Michael Clark's personal Notion and Flywheel Notion are not targeted.

2. Run a dry-run poll against a real test Notion database watch source.

   ```bash
   agentic-os connected-system doctor notion_genome --root ~/agentic_os
   agentic-os watch-source poll <notion_source_id> --root ~/agentic_os --dry-run
   ```

   Evidence to capture:

   - Selected provider.
   - Dry-run source event preview.
   - Dedupe idempotency key.
   - Confirmation that no external writes occurred.

3. Run a dry-run against one read-only Composio-backed source.

   ```bash
   agentic-os connected-system doctor <composio_system_id> --root ~/agentic_os
   agentic-os watch-source poll <composio_source_id> --root ~/agentic_os --dry-run
   ```

   Evidence to capture:

   - Connected account alias or workspace identity, without secrets.
   - Selected provider and fallback order.
   - Dry-run source event preview.
   - Confirmation that no provider-backed write occurred.

4. Confirm live provider output normalizes into source events without storing secrets.

   Evidence to capture:

   - Local source-event file path if apply is approved.
   - Redacted payload reference only, not copied secret/customer payload.
   - Stable idempotency key across duplicate reads of the same provider item.

5. Confirm apply mode writes local source-event and run-queue evidence only after dry-run review.

   ```bash
   agentic-os watch-source run-due --root ~/agentic_os --dry-run
   agentic-os watch-source run-due --root ~/agentic_os --apply
   agentic-os validate --root ~/agentic_os
   ```

   Evidence to capture:

   - Source-event path.
   - Run-queue item id.
   - Trigger action status.
   - Confirmation that duplicate apply does not create duplicate source-event or run-queue work.

## Plan 17: Event Graph And Chained Automations

Source-package validation already completed:

- `uv run pytest tests/test_cli_scaffold.py -q -k 'event_graph'` passed with 4 tests.
- `uv run pytest -q` passed with 57 tests.
- Temp-root smoke validation passed for event append, process-due dry-run, chain test, chain doctor, and root validation.

Manual/live validation to run later:

1. Run a real Genome Notion work-item/source-watch event through dry-run first.

   ```bash
   agentic-os watch-source poll <source_id> --root ~/agentic_os --dry-run
   ```

   Apply only after the emitted event and queue preview are correct.

2. Run a synthetic PR-merged event against the live install.

   ```bash
   agentic-os event append --root ~/agentic_os --type github.pull_request.merged --source github:genomes_agentic_os:pull/<pr>
   agentic-os event process-due --root ~/agentic_os --dry-run
   agentic-os event summary --root ~/agentic_os --limit 20
   ```

   Evidence to capture:

   - Event file path.
   - Matched chain rule.
   - Exactly one pending follow-up queue item.
   - Confirmation that duplicate processing does not create duplicate queue work.

3. Exercise an approval-required chain on the live install.

   Evidence to capture:

   - Queue item status stays `approval-needed`.
   - Approval state is `required`.
   - No external execution occurs.

4. Inspect a dead-letter and replay flow manually.

   Evidence to capture:

   - Dead-letter file includes event ID, chain rule ID, failure reason, and next action.
   - After rule repair, `agentic-os event replay <event_id> --root ~/agentic_os --dry-run` returns the expected queue preview.

5. Validate the live installed OS root after live event graph checks.

   ```bash
   agentic-os validate --root ~/agentic_os
   ```
