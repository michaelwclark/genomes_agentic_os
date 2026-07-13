# System Shell Shape

The system layer tracks host-level shell, terminal, runtime, package-manager,
and cleanup conventions that should feel consistent across local and remote
hosts.

## Why This Exists

Agents doing shell or system work need an explicit inventory of the host before
they run commands. Humans need the same shape when moving between `bigmac`,
`genomesbox`, and other managed machines.

The system layer answers:

- Which shell startup files are authoritative?
- Which tools are installed and how should agents use them?
- Which tools are interactive-only versus automation-safe?
- Which cleanup and health-check commands are safe?
- Which setup belongs in user-local state instead of a public repo?

## Canonical Surfaces

| Surface | Purpose |
| --- | --- |
| `system/README.md` | Human and agent model for the system layer. |
| `templates/system/host-tool-registry.yml` | Machine-readable registry template for one host. |
| `templates/system/shell-shape.yml` | Desired shell/terminal shape template. |
| `harness/commands/system-tool-registry.md` | Agent-facing workflow for reading and maintaining host tools. |
| `~/agentic_os/harness/shared_factory/05-knowledge/host-tool-registry.<host>.yml` | Live host registry for a specific installed OS instance. |

## Agent Rule

Before doing non-trivial shell/system work, agents should read the host tool
registry when it exists. If it is missing or stale, inventory the host with
bounded commands, update the registry, and then proceed.

