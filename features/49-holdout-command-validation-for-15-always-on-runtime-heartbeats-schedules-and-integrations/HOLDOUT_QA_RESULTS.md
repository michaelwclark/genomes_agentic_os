# Holdout QA Results

Temp root: `/tmp/agentic-os-feature49-pass-XcQGVt/agentic_os`

| Step | Command | Result |
| --- | --- | --- |
| 1 | `uv run agentic-os init --target /tmp/agentic-os-feature49-pass-XcQGVt/agentic_os` | PASS, exit 0 |
| 2 | `rm .../shared_factory/05-knowledge/commands/os-runtime-init.md` and `rm .../shared_factory/05-knowledge/templates/runtime/heartbeat.yml` | PASS, files removed for repair check |
| 3 | `uv run agentic-os docs update --root /tmp/agentic-os-feature49-pass-XcQGVt/agentic_os` | PASS, exit 0; restored `templates/runtime/heartbeat.yml` and `commands/os-runtime-init.md` |
| 4 | `uv run agentic-os validate --root /tmp/agentic-os-feature49-pass-XcQGVt/agentic_os` | PASS, exit 0; root reported valid |
| 5 | `uv run agentic-os runtime init --root /tmp/agentic-os-feature49-pass-XcQGVt/agentic_os` | PASS, exit 0; runtime registry state initialized |
| 6 | `uv run agentic-os runtime doctor --root /tmp/agentic-os-feature49-pass-XcQGVt/agentic_os` | PASS, exit 0; `ok: true` |
| 7 | `uv run agentic-os heartbeat list --root /tmp/agentic-os-feature49-pass-XcQGVt/agentic_os` | PASS, exit 0; heartbeats listed |
| 8 | `uv run agentic-os heartbeat run granola_recent_notes_sync --root /tmp/agentic-os-feature49-pass-XcQGVt/agentic_os --dry-run` | PASS, exit 0; dry-run heartbeat log written |
| 9 | `uv run agentic-os schedule create smoke_runtime_doctor --root /tmp/agentic-os-feature49-pass-XcQGVt/agentic_os --cadence weekly` | PASS, exit 0; schedule created |
| 10 | `uv run agentic-os schedule run-due --root /tmp/agentic-os-feature49-pass-XcQGVt/agentic_os --dry-run` | PASS, exit 0; due schedule entries reported as dry-run queue items |
| 11 | `uv run agentic-os integration list --root /tmp/agentic-os-feature49-pass-XcQGVt/agentic_os` | PASS, exit 0; integrations listed |
| 12 | `uv run agentic-os integration setup granola --root /tmp/agentic-os-feature49-pass-XcQGVt/agentic_os --dry-run` | PASS, exit 0; Granola setup status `planned` |
| 13 | `uv run agentic-os integration doctor granola --root /tmp/agentic-os-feature49-pass-XcQGVt/agentic_os` | PASS, exit 0; integration setup contract complete |
| 14 | `uv run agentic-os notion track-runtime --root /tmp/agentic-os-feature49-pass-XcQGVt/agentic_os --dry-run` | PASS, exit 0; planned Integrations, Heartbeats, Schedules, and Runs databases |
| 15 | `uv run agentic-os notion track-runtime --root /tmp/agentic-os-feature49-pass-XcQGVt/agentic_os --apply` | PASS, expected fail-closed behavior; exit 2 with `expected "Genome's Notion"` |
| 16 | `uv run agentic-os notion track-runtime --root /tmp/agentic-os-feature49-pass-XcQGVt/agentic_os --apply --verified-workspace "Genome's Notion"` | PASS, exit 0; local manifest written |
| 17 | `uv run --extra dev pytest -q` | PASS, `39 passed in 3.25s` |

Assertions after the corrected run:

- Restored command: yes.
- Restored runtime template: yes.
- Runtime registry exists: yes.
- Integration registry exists: yes.
- Heartbeat dry-run logs found: 1.
- Runtime run queue file exists after dry-run: no, expected because `schedule run-due --dry-run` reports queue items without persisting the queue file.
- Notion runtime tracking manifest exists: yes.
- Orchestrator rerun: `uv run --extra dev pytest -q` passed with 39 tests,
  and a fresh temp-root runtime holdout smoke passed before branch commit.

Notes:

- An initial exploratory attempt with `uv run agentic-os init --root <temp-root>` failed with exit 2 because `init` uses `--target`, not `--root`. The passing holdout above records the corrected command matrix.
