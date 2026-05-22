# Codex config.toml Inventory

Verified: 2026-05-22

Local runtime checked:

```text
codex-cli 0.131.0-alpha.9
```

Primary sources:

- [Config basics](https://developers.openai.com/codex/config-basic)
- [Configuration reference](https://developers.openai.com/codex/config-reference)
- [Sample configuration](https://developers.openai.com/codex/config-sample)
- [AGENTS.md guide](https://developers.openai.com/codex/guides/agents-md)
- [MCP guide](https://developers.openai.com/codex/mcp)
- [Hooks guide](https://developers.openai.com/codex/hooks)
- [Published config schema](https://developers.openai.com/codex/config-schema.json)

## Resolution Model

Codex configuration is layered. The effective value comes from the highest
matching layer:

1. CLI flags and `--config` overrides.
2. `--profile <name>` values from `[profiles.<name>]`.
3. Project `.codex/config.toml` files from project root down to the current
   directory, with closest winning. Project layers require a trusted project.
4. User config at `~/.codex/config.toml`.
5. System config at `/etc/codex/config.toml` on Unix.
6. Built-in defaults.

Agentic OS should use this resolution model rather than inventing a parallel
merge engine. OS templates should generate layer-appropriate files and leave
runtime precedence to Codex.

## Option Inventory

| Area | Supported keys or tables | Default or behavior | Agentic OS use |
| --- | --- | --- | --- |
| Model selection | `model`, `model_provider`, `model_reasoning_effort`, `model_reasoning_summary`, `model_verbosity`, `plan_mode_reasoning_effort`, `review_model`, `service_tier`, `personality` | Defaults are model/catalog dependent; local CLI supports `--model` and `--profile`. | Keep global defaults conservative; use profiles for layer-specific model and reasoning posture. |
| Providers | `[model_providers]`, `model_provider`, `oss_provider`, `model_catalog_json`, `chatgpt_base_url` | Built-ins include OpenAI and local/alternate providers in sample config. | Do not put customer provider secrets in project templates. Reference env vars. |
| Profiles | `profile`, `[profiles.<name>]`, `profiles.<name>.*` | A startup profile is equivalent to `--profile`. Profile keys can override supported config keys. | Define reusable Agentic OS profiles for global, OS root, customer root, domain, workflow, and automation layers. |
| Project trust | `[projects.<path>]`, `trust_level` | Trusted projects can load project `.codex/` layers. Untrusted projects skip project `.codex/` layers, hooks, and rules. | Mark installed OS roots and known project worktrees intentionally. Avoid broad trust globs. |
| Instructions | `project_doc_fallback_filenames`, `project_doc_max_bytes`, `project_root_markers`, `model_instructions_file`, `experimental_compact_prompt_file` | `AGENTS.md` is native. Fallback filenames are only checked after override/base names. Default project doc cap is 32 KiB. | Keep `AGENTS.md` as the Codex-native entrypoint. Treat `BRAIN.md`, `ROUTER.md`, and `CONTEXT.md` as Agentic OS files included by convention or fallback config. |
| Approval | `approval_policy`, `approvals_reviewer`, granular approval tables | CLI exposes `untrusted`, `on-request`, `never`; `on-failure` is deprecated in local help. | Global defaults should use `on-request` or stricter; automations can use `never` only inside external safeguards. |
| Sandbox | `sandbox_mode`, `[sandbox_workspace_write]`, `default_permissions`, `[permissions.<name>]`, `[windows]` | CLI supports `read-only`, `workspace-write`, and `danger-full-access`. Network in `workspace-write` is controlled separately. | Match OS layer risk: read-only for discovery, workspace-write for normal repo work, danger only for trusted automation surfaces. |
| Filesystem/network permissions | `permissions.<name>.filesystem`, `permissions.<name>.network`, `permissions.<name>.workspace_roots` | Permission profiles can define reusable filesystem and network policy. Deny rules win on conflicts. | Prefer named profiles for customer/domain/workflow scopes instead of repeating sandbox tables. |
| MCP | `[mcp_servers.<name>]`, `command`, `args`, `env`, `env_vars`, `cwd`, `url`, `bearer_token_env_var`, `http_headers`, `env_http_headers`, `startup_timeout_sec`, `tool_timeout_sec`, `enabled`, `required`, tool allow/deny and approval keys, OAuth callback keys | CLI and IDE share MCP config. STDIO and streamable HTTP transports are documented. | Put generic MCP definitions in OS/global layers; put customer-specific MCPs in customer roots; forward secrets through env vars only. |
| Apps/connectors/plugins | `[apps]`, `[plugins]`, plugin MCP overrides, bundled skills toggles | Supported by schema and desktop/app surfaces; availability is product-surface dependent. | Treat desktop connector policy as global or OS-root policy, not workflow-local boilerplate. |
| Hooks | `[features].hooks`, inline `[hooks]`, sibling `hooks.json` | Hooks are enabled by default; multiple matching hooks run; project hooks require trusted project layers. | Use hooks for deterministic validation/logging. Avoid hidden customer-specific hooks outside a customer root. |
| Shell environment | `[shell_environment_policy]`, `include_only`, `exclude`, `ignore_default_excludes`, `experimental_use_profile` | CLI supports `-c shell_environment_policy.inherit=all` style overrides. | Keep secret-heavy envs out of project profiles; prefer explicit env forwarding for MCP servers. |
| Tools/search | `[tools]`, `tools.view_image`, `web_search`, feature flags such as `features.web_search` variants | Local CLI exposes `--search`; sample config shows `[tools]`. | Enable search only where policy allows live web access. |
| Memory | `[memories]`, `[features].memories` | Sample config shows memory behavior gated by feature flags. | Agentic OS memory should stay file-backed/canonical; Codex memory features can be an adapter, not the source of truth. |
| Telemetry | `[otel]`, exporter tables, trace exporter tables, metrics exporter tables | Sample config states OTEL is disabled by default; user prompt logging defaults false. | Keep prompt logging off unless explicitly needed and approved for the workspace. |
| Analytics/feedback/history | `[analytics]`, `[feedback]`, `[history]` | Schema exposes product telemetry and history controls. | Use global policy; avoid customer-local overrides unless a customer operating requirement demands it. |
| Windows | `[windows].sandbox` | Native Windows sandbox supports `unelevated` or `elevated`. | Keep OS templates portable; use Windows-specific overlays only on Windows hosts. |
| Admin/managed config | `requirements.toml`, managed configuration, managed hooks | Requirements can enforce policy outside user `config.toml`. | Do not try to bypass admin policy from Agentic OS templates. Record blocked settings in the layer artifact. |

## Agentic OS Layer Map

| OS layer | Codex config surface | Intended contents |
| --- | --- | --- |
| Global user harness | `~/.codex/config.toml`, `~/.codex/AGENTS.md`, optional `~/.codex/hooks.json` | Personal defaults, default profile, trusted project list, global MCPs, global safety hooks, universal working agreements. |
| Agentic OS root | `~/agentic_os/.codex/config.toml`, `~/agentic_os/AGENTS.md` | OS operating defaults, shared skills/tooling, file-backed memory/control-plane rules, Notion workspace guardrails. |
| Customer OS root | `<customer_os>/.codex/config.toml`, customer `AGENTS.md` | Customer-specific MCPs, environment assumptions, data boundaries, approval posture, customer memory and source priorities. |
| Domain or lane | `<domain>/.codex/config.toml`, domain `AGENTS.md` or fallback files | Domain routes, context profile, model/reasoning posture, allowed tools, narrow prompts. |
| Workflow or task | `<workflow>/.codex/config.toml`, workflow context files | Temporary or workflow-specific model/profile/tool overrides and validation hooks. |

## Prompt File Stitching

Codex natively stitches `AGENTS.md` and configured fallback filenames. It reads
global guidance first, then project guidance from root to current directory. A
closer file appears later in the combined prompt and can override earlier
guidance.

Agentic OS should use these roles:

- `AGENTS.md`: Codex-native operating instructions.
- `CLAUDE.md`: Claude-native operating instructions with the same workflow
  contract as `AGENTS.md`.
- `BRAIN.md`: universal facts, defaults, and durable decisions.
- `ROUTER.md`: routing rules for domains, lanes, workflows, and tools.
- `CONTEXT.md`: current operating context assembled for a room/domain/workflow.
- `MEMORY.md`: durable memory handoff or local feature memory, not a substitute
  for the OS memory substrate.

For Codex, non-`AGENTS.md` names need either explicit references from
`AGENTS.md`, inclusion through `project_doc_fallback_filenames`, or a generated
`AGENTS.md` that summarizes and links them.

## Security-Sensitive Settings

Treat these as security-sensitive:

- `approval_policy`, `approvals_reviewer`, granular approval controls.
- `sandbox_mode`, `default_permissions`, and `[permissions.<name>]`.
- `sandbox_workspace_write.network_access`.
- MCP `env`, `env_vars`, `bearer_token_env_var`, `http_headers`, and
  `env_http_headers`.
- Hook command definitions.
- OTEL exporters and `otel.log_user_prompt`.
- Project `trust_level`.
- `model_instructions_file` and fallback instruction filenames.

Project-local configs are powerful because trusted projects can load them.
Agentic OS should generate them only for known roots and should keep secrets in
environment variables, not TOML literals.

## Desktop, CLI, And Unknown Areas

Verified local behavior:

- Local CLI version: `codex-cli 0.131.0-alpha.9`.
- `codex --help` exposes `--profile`, `--config`, `--sandbox`,
  `--ask-for-approval`, `--search`, `--cd`, and `--add-dir`.
- `codex debug --help` exposes `models`, `app-server`, and `prompt-input`.

Unsupported or not yet proven here:

- Exact desktop-only connector/app behavior for every `[apps]` key.
- Runtime behavior for every experimental feature flag.
- Organization-managed `requirements.toml` policy on machines without such
  policy installed.
- Whether all schema keys are accepted by every released CLI version. The
  official schema and installed alpha CLI should both be treated as inputs,
  not as a promise that older clients accept every key.

## Examples

Global default with a profile:

```toml
model = "gpt-5.5"
approval_policy = "on-request"
sandbox_mode = "workspace-write"
profile = "agentic_os"

[profiles.agentic_os]
model_reasoning_effort = "high"
plan_mode_reasoning_effort = "high"
personality = "pragmatic"

[projects."/Users/genome/agentic_os"]
trust_level = "trusted"
```

Project fallback prompt files:

```toml
project_doc_fallback_filenames = ["BRAIN.md", "ROUTER.md", "CONTEXT.md"]
project_doc_max_bytes = 65536
```

MCP with env forwarding:

```toml
[mcp_servers.context7]
command = "npx"
args = ["-y", "@upstash/context7-mcp"]
env_vars = ["CONTEXT7_API_KEY"]
startup_timeout_sec = 20
tool_timeout_sec = 60
```

OTEL disabled baseline:

```toml
[otel]
log_user_prompt = false
environment = "dev"
exporter = "none"
trace_exporter = "none"
```
