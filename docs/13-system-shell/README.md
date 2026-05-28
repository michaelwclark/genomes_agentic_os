# System Shell And Host Tools

The Agentic OS includes a system layer for shell shape, terminal behavior,
host tools, setup automation, and cleanup routines.

## System Shell Shape

System shell shape is the repeatable contract that makes each managed host feel
familiar:

- zsh startup files are split by purpose.
- oh-my-zsh custom helpers live in a known location.
- interactive-only tools are separated from automation-safe tools.
- package-manager state is reproducible.
- iTerm2 and SSH behavior are documented without assuming every host is a Mac.
- agents can read a host registry before running shell commands.

## File Boundaries

| File Or Folder | Role |
| --- | --- |
| `~/.zshenv` | Environment needed by non-interactive shells and agents. Keep secrets local. |
| `~/.zshrc` | Interactive shell behavior, aliases, zoxide/fzf, iTerm2 integration. |
| `~/.oh-my-zsh/custom/*.zsh` | Small reusable helper functions. |
| `~/projects/zsh-custom/current/` | Non-secret reproducible snapshot for this operator. |
| `~/agentic_os/shared_factory/05-knowledge/host-tool-registry.<host>.yml` | Host-specific agent-readable registry. |
| `templates/system/` | Portable registry and shell-shape templates. |

## Agent Behavior

Before shell/system work, agents should:

1. Check the host registry.
2. Prefer listed tools over rediscovering available commands.
3. Respect each tool's `agent_use` guidance.
4. Avoid interactive-only utilities in non-interactive automation.
5. Update the registry after durable host setup changes.

## Remote Host Parity

Remote hosts should not blindly mirror macOS-only pieces like iTerm2 app
profiles, but they should preserve the same operator feel where possible:

- zsh conventions.
- shared helpers such as `killport` and `portpids`.
- common CLI tools such as `rg`, `fd`, `fzf`, `bat`, `eza`, `zoxide`, `delta`,
  `yq`, `tmux`, `direnv`, and `gh`.
- host-specific notes for terminal capabilities, package manager, and SSH.

