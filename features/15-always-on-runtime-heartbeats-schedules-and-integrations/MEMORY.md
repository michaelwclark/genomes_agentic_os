# Memory

- Runtime state is intentionally file-backed under `shared_factory/00-control-plane/` before any provider execution is attempted.
- `agentic-os heartbeat run <id> --dry-run` writes a heartbeat log and run-queue item because the pilot requires observable evidence even without external effects.
- Notion runtime tracking apply writes a local manifest and uses the existing Genome's Notion workspace guard. It does not call the live Notion API.
