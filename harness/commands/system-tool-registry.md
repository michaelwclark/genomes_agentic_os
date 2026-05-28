# system-tool-registry

Use the host tool registry before doing shell, terminal, package-manager, or
host cleanup work.

## Read Order

1. `~/agentic_os/shared_factory/05-knowledge/host-tool-registry.$(hostname -s).yml`
2. `~/agentic_os/shared_factory/05-knowledge/host-tool-registry.yml`
3. `templates/system/host-tool-registry.yml`

## Agent Workflow

1. Read the registry if present.
2. Use listed tools and respect `interactive_only`.
3. If the needed tool is not listed, verify with `command -v <tool>` before use.
4. If a durable setup change is made, update the registry and the shell-shape docs.
5. Never infer secrets from registry entries; registry values are capability hints.

## Minimum Registry Fields

- host
- last_verified
- shell startup files
- terminal constraints
- package managers
- tools with command, path, version, category, and agent_use
- health checks
- cleanup commands and confirmation boundaries
