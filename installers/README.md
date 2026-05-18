# Installers

Installer work should start after the templates and schemas stabilize.

## Installer Responsibilities

- Create `~/agentic_os`.
- Copy base templates.
- Create initial domains.
- Install Claude and Codex skill surfaces.
- Scaffold or link Notion control-plane pages.
- Validate required config and IDs.

## Safety Requirements

- Idempotent by default.
- No destructive overwrite without explicit flag.
- Print every created or modified path.
- Keep generated and hand-authored sections clearly separated.
