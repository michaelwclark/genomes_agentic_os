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
- `BRAIN.md`
- `ROUTER.md`
- `CONTEXT.md`
- `MEMORY.md`

Workflow and automation layers intentionally receive a narrower set because
their task-specific files carry the execution contract.

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
prompt_files = ["AGENTS.md", "CLAUDE.md", "BRAIN.md", "ROUTER.md", "CONTEXT.md", "MEMORY.md"]
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
```
