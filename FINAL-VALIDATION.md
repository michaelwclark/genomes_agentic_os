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

## Plan 18: Visible Capability Registry

Source-package validation already completed:

- `uv run pytest -q` passed with 62 tests.
- Fresh `agentic-os init` generates `INVENTORY.md` plus `registries/` (capabilities,
  commands, skills, mcp-servers, libraries, hooks, plugins, rules), and
  `agentic-os validate` fails when a declared capability is missing from its registry.

Deferred by design (not required by the plan's acceptance criteria; tracked for a later slice):

1. `agentic-os init` does not auto-generate the `.codex/config.toml` harness adapter.
   The adapter is produced by the explicit, registry-backed `agentic-os config install`
   step. Wire `install_config` into `init` later if init-time generation is wanted.
2. Root `TOOLS.md` is written from a static template at init; the registry-driven
   `tools_prompt_template()` is only applied by `config install`. Consider consolidating
   so root `TOOLS.md` always reflects live registry entries.
3. Naming: the spec references `registries/mcp.yml`; the implementation uses
   `registries/mcp-servers.yml` (consistent across code, tests, and validation).
   Reconcile the spec name or the constant in a future cleanup.

Manual/live validation to run later (against `~/agentic_os`, after approval):

- Run `agentic-os docs update --root ~/agentic_os`, then confirm `INVENTORY.md` and
  `registries/` appear without overwriting local edits.
- `agentic-os validate --root ~/agentic_os` reports no declared-but-missing capabilities.

## Plan 19: Update Channel And Customer Fleet

Source-package validation already completed:

- `uv run pytest -q` passed with 62 tests.
- `update check/plan/apply/rollback/status/phone-home` are local and file-backed; risky
  change types (executable, hook, mcp, rule, permission) are blocked unless
  `--approve-risky`; phone-home emits metadata-only payloads (counts and booleans, never
  prompts, source code, logs, or secrets).

Deferred by design (spec/build-order granularity beyond the plan's acceptance criteria):

1. Post-update doctor checks appear in the update plan output, but `update apply` does not
   yet invoke `doctor()`. Run `agentic-os doctor --root <root>` manually after an apply
   until this is wired.
2. `doctor` does not yet surface update-channel health fields (installed version, last
   check, pending updates, rollback availability, telemetry status). `validate` already
   reports update/backup grant health.
3. `update rollback` records rollback intent plus a state snapshot (lock + status); it does
   not yet restore changed file contents. Destructive restore remains operator-driven in V1.
4. Update status is local only; mirroring update results into the Notion control plane is a
   later layer.

Manual/live validation to run later:

- `agentic-os update check --root ~/agentic_os` and `update plan` against a real manifest;
  confirm non-mutating, and that a subsequent `update apply` does not overwrite local edits.
- `agentic-os update phone-home --root ~/agentic_os`; confirm the payload contains no
  prompts, source code, logs, secrets, or customer data.

## Plan 20: Operator-Pushed Customer Updates And Backups

Source-package validation already completed:

- `uv run pytest -q` passed with 62 tests.
- License activation stores only a SHA-256 hash (never the raw key); `update register`
  generates separate update/backup ed25519 keypairs at mode `0600` and writes only public
  keys into the grant; `backup run` records a local run log under `logs/backups/`.

Finished in this pass (acceptance-criteria gaps closed; +2 tests):

1. `update register` now blocks with a clear error and exit code `2` when the customer
   license/billing status is not active, creating no keypair or grant in that case;
   activating a license unblocks it. (`src/genomes_agentic_os/update_ops.py`; test
   `test_update_register_blocks_when_billing_is_inactive`.)
2. The default backup policy now excludes `projects/` in addition to `logs/`,
   `security/ssh/*`, `**/.env`, and secret/token patterns.
   (`src/genomes_agentic_os/scaffold.py`; test
   `test_backup_policy_excludes_projects_keys_and_secrets`.)

Deferred by design (the plan's Notes defer these to a future layer; not in the
acceptance-criteria list):

1. `agentic-os fleet push <customer_slug>` (operator push over SSH/execution target) is not
   implemented.
2. Grant-expiry checking in `validate`/`doctor` (grant presence, separate remotes, and
   `0600` key permissions are already validated).
3. The provisioning client is a local fake (`fake_provisioning_response`); real MCP/GitHub
   provisioning is future work.

Manual/live validation to run later:

- On a real customer root: `license activate`, then `update register`; confirm only public
  keys are provisioned and private keys remain local at mode `0600`.
- Confirm `update register` is blocked before license activation.
- `agentic-os backup run --root ~/agentic_os --dry-run`; confirm `projects/`, private keys,
  env files, and secrets are excluded before any real `--apply` push.

## Plan 21: Harness Context Contract And Codex Config

Status: complete; no deferred items.

- Fresh installs create `.agentic_root`, `AGENTS.md`, `CLAUDE.md` (an `@AGENTS.md` adapter),
  `ROUTER.md`, `CONTEXT.md`, `RULES.md`, and `TOOLS.md`; `AGENT.md` is not created unless
  `--include-legacy-agent` is passed.
- Domain, customer, and profile scaffolds follow the same context-file contract, and
  `agentic-os validate` enforces the root file set.
