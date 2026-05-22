# Holdout QA

## Command Matrix
- `uv run agentic-os init --target <temp-root>`
- `rm <temp-root>/shared_factory/05-knowledge/commands/os-runtime-init.md`
- `rm <temp-root>/shared_factory/05-knowledge/templates/runtime/heartbeat.yml`
- `uv run agentic-os docs update --root <temp-root>`
- `uv run agentic-os validate --root <temp-root>`
- `uv run agentic-os runtime init --root <temp-root>`
- `uv run agentic-os runtime doctor --root <temp-root>`
- `uv run agentic-os heartbeat list --root <temp-root>`
- `uv run agentic-os heartbeat run granola_recent_notes_sync --root <temp-root> --dry-run`
- `uv run agentic-os schedule create smoke_runtime_doctor --root <temp-root> --cadence weekly`
- `uv run agentic-os schedule run-due --root <temp-root> --dry-run`
- `uv run agentic-os integration list --root <temp-root>`
- `uv run agentic-os integration setup granola --root <temp-root> --dry-run`
- `uv run agentic-os integration doctor granola --root <temp-root>`
- `uv run agentic-os notion track-runtime --root <temp-root> --dry-run`
- `uv run agentic-os notion track-runtime --root <temp-root> --apply`
- `uv run agentic-os notion track-runtime --root <temp-root> --apply --verified-workspace "Genome's Notion"`
- `uv run --extra dev pytest -q`

## Expected Result
- All positive commands exit 0.
- Unverified Notion runtime tracking apply exits 2 and names the expected Genome's Notion workspace.
- Removed managed knowledge files are restored.
- Runtime registry, integration registry, heartbeat log, and Notion runtime manifest exist after the corrected run.
