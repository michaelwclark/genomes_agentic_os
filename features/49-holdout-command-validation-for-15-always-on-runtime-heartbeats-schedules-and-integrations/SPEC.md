# 49 Holdout Command Validation For 15 Always On Runtime Heartbeats Schedules And Integrations

## Scope
- Re-run a holdout validation for feature 15 against the current command surface.
- Use a fresh temporary installed OS root instead of relying on feature 15's original QA notes.
- Validate the file-backed runtime, heartbeat, schedule, integration, and Notion runtime tracking commands.
- Confirm managed runtime knowledge can be restored by `agentic-os docs update` after selected managed files are removed.
- Record exact command results in this feature folder.

## Out Of Scope
- No changes to runtime command implementation.
- No writes to Notion, board state, `RUN_STATE.json`, or shared `BUILD_LOGS`.
- No external integration account setup.

## Acceptance Criteria
- The canonical Build Runner artifact set exists.
- `uv run agentic-os init --target <temp-root>` creates the installed OS root.
- Removing `os-runtime-init.md` and `templates/runtime/heartbeat.yml`, then running `uv run agentic-os docs update --root <temp-root>`, restores both managed files.
- `uv run agentic-os validate --root <temp-root>` passes.
- `runtime init`, `runtime doctor`, `heartbeat list`, `heartbeat run ... --dry-run`, `schedule create`, `schedule run-due --dry-run`, `integration list`, `integration setup ... --dry-run`, and `integration doctor` all pass.
- `notion track-runtime --dry-run` passes locally.
- `notion track-runtime --apply` without `--verified-workspace` fails closed with exit 2 and names the expected Genome's Notion workspace.
- `notion track-runtime --apply --verified-workspace "Genome's Notion"` writes only the local `.notion-runtime-tracking/manifest.yml`.
- Full pytest passes from the worktree.
