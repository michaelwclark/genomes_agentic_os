# Holdout QA Results

- `uv run --extra dev pytest -q`: 35 passed in 2.34s.
- Temp-root smoke: initialized `/tmp/agentic-os-runtime-hD4r21/agentic_os`, restored removed `os-runtime-init.md` and `templates/runtime/heartbeat.yml` via `agentic-os docs update`, validated the root, initialized runtime state, ran runtime doctor, dry-ran `granola_recent_notes_sync`, created and dry-ran `smoke_runtime_doctor`, dry-ran Granola setup, dry-ran runtime Notion tracking, and applied guarded local tracking with verified workspace `Genome's Notion`.
