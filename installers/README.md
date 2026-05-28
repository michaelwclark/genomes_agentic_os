# Installers

Installer work should start after the templates and schemas stabilize.

## Installer Responsibilities

- Create `~/agentic_os`.
- Copy base templates.
- Create initial domains.
- Install Claude and Codex skill surfaces.
- Scaffold or link Notion control-plane pages.
- Validate required config and IDs.
- Provide per-user integration helpers such as Composio debug-bundle env setup.

## Safety Requirements

- Idempotent by default.
- No destructive overwrite without explicit flag.
- Print every created or modified path.
- Keep generated and hand-authored sections clearly separated.
- Print environment variable names only; do not print credential or account values.
