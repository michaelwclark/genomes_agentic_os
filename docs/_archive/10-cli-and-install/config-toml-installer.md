# config.toml Installer

The Agentic OS CLI can install or update Codex `config.toml` conventions for a
new or existing directory:

```bash
agentic-os config install --root ~/agentic_os --layer agentic_os_root --dry-run
agentic-os config install --root ~/agentic_os --layer agentic_os_root --apply --backup
```

## Table Of Contents

- [Layers](#layers)
- [Write Contract](#write-contract)
- [Prompt Files](#prompt-files)
- [MCP Server Placement](#mcp-server-placement)
- [Validation](#validation)
- [Config Example](#config-example)

## Layers

| Layer | Use For |
| --- | --- |
| `global_harness` | User-level harness configuration directories. |
| `agentic_os_root` | The root of a reusable or installed Agentic OS. |
| `customer_os_root` | A customer-specific OS root. |
| `domain_or_lane` | Domain rooms and lane-level operating directories. |
| `workflow_or_task` | Workflow, project task, and run-specific directories. |
| `automation` | Automation directories with explicit runtime contracts. |

## Write Contract

- `--dry-run` reports the target files and a unified diff without writing.
- `--apply` creates the target directory, `config.toml`, and missing prompt
  files for the selected layer.
- `--backup` copies an existing `config.toml` before applying a merge.
- Existing prompt files are preserved.
- Existing `config.toml` values are not overwritten.
- If a managed key conflicts with an existing value, `--apply` exits blocked
  until the operator reruns with `--confirm-conflicts`.

The confirmation path applies non-conflicting additions, leaves conflicting
local values in place, and records the conflicts in command output.

## Prompt Files

The installer writes the Codex and Claude harness entry files plus the universal
prompt files required by the selected layer:

- `AGENTS.md`
- `CLAUDE.md`
- `ROUTER.md`
- `CONTEXT.md`
- `RULES.md`
- `TOOLS.md`
- `MEMORY.md`

Workflow and automation layers receive the same context-file contract, then add
task-specific files such as workflow specs, permissions, runbooks, and context
packs beside it.

## MCP Server Placement

`config install` writes only the MCP servers needed by the target layer. All
servers remain visible in `TOOLS.md` so agents can see what exists and why a
server is disabled in the current room.

| Config ID | Placement | Config |
| --- | --- | --- |
| `notion` | Every layer | `url = "https://mcp.notion.com/mcp"` |
| `genomes_brain` | Every layer | `url = "http://127.0.0.1:3155/mcp"` |
| `github` | Every layer | `url = "https://api.githubcopilot.com/mcp/"`, `bearer_token_env_var = "GITHUB_PAT_TOKEN"` |
| `context_mode` | Every layer | `command = "/Users/genome/.local/bin/context-mode"` |
| `sentry` | LOS layers only | `url = "https://mcp.sentry.dev/mcp"` |
| `datadog` | LOS layers only | `url = "https://mcp.datadoghq.com/api/unstable/mcp-server/mcp"` |
| `supabase` | `clarks_consulting` layers only | `url = "https://mcp.supabase.com/mcp"` |
| `composio` | Visible only until an approved generated MCP URL is available | Generate a layer-specific Composio MCP URL before installing. |
| `orgo` | Visible only until an approved Orgo MCP bridge is available | Orgo is a runtime execution target first; register MCP only after bridge approval. |
| `playwright` | Visible only until a browser automation layer opts in | `command = "npx"`, `args = ["@playwright/mcp@latest"]` |

Layer placement is inferred from the config target path. For example,
`~/agentic_os/los/config.toml` receives the LOS-only Sentry and Datadog entries,
while `~/agentic_os/clarks_consulting/config.toml` receives Supabase. Token
values are never written into generated config; use the named environment
variables or the provider's own auth flow.

## Validation

Run `config doctor` after applying:

```bash
agentic-os config doctor --root ~/agentic_os --layer agentic_os_root
```

The doctor checks required sandbox, approval, OTEL, MCP availability, and MCP
secret-policy keys.

## Config Example

```toml
model = "gpt-5.2"
approval_policy = "on-request"
sandbox_mode = "workspace-write"

[profiles.agentic_os_root]
model = "gpt-5.2"
approval_policy = "on-request"
sandbox_mode = "workspace-write"

[profiles.agentic_os_root.agentic_os]
layer = "agentic_os_root"
prompt_files = ["AGENTS.md", "CLAUDE.md", "ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md", "MEMORY.md"]
context_contract = "route-read-cd-repeat"
rules_file = "RULES.md"
tool_registry_file = "TOOLS.md"
mcp_availability = "source package and local filesystem tools"
environment = "local filesystem"

[otel]
log_user_prompt = false
exporter_otlp_endpoint_env_var = "AGENTIC_OS_OTEL_EXPORTER_OTLP_ENDPOINT"
headers_env_var = "AGENTIC_OS_OTEL_HEADERS"

[mcp_servers.filesystem_runtime]
command = "agentic-os"
args = ["config", "doctor"]
secret_policy = "no inline secrets"

[mcp_servers.notion]
url = "https://mcp.notion.com/mcp"
secret_policy = "no inline secrets; env var names only"

[mcp_servers.genomes_brain]
url = "http://127.0.0.1:3155/mcp"
secret_policy = "no inline secrets; env var names only"

[mcp_servers.github]
url = "https://api.githubcopilot.com/mcp/"
bearer_token_env_var = "GITHUB_PAT_TOKEN"
secret_policy = "no inline secrets; env var names only"

[mcp_servers.context_mode]
command = "/Users/genome/.local/bin/context-mode"
secret_policy = "no inline secrets; env var names only"
```
