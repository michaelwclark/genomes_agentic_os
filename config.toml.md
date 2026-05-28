# Codex `config.toml` Reference

Source: official Codex config schema at `https://developers.openai.com/codex/config-schema.json`.

Snapshot date: 2026-05-22.

This file is a human reference for Codex `config.toml`. It is not an active
configuration file. Use it to decide what belongs in:

- `~/.codex/config.toml` for user-wide settings.
- `<repo>/.codex/config.toml` for trusted project settings.
- `codex -c key=value` for one-off overrides.

When this document says "no schema max", the schema does not declare a hard
maximum. The running Codex product, session, account, or tool surface may still
apply runtime limits.

## Load Order

Highest priority wins:

1. CLI flags and `-c key=value` overrides.
2. Selected `[profiles.<name>]` values.
3. Trusted project `.codex/config.toml` files from project root to cwd.
4. `~/.codex/config.toml`.
5. `/etc/codex/config.toml`.
6. Built-in defaults.

Project-local config is intentionally restricted. Keep provider, auth,
telemetry, notification, and profile selection settings in user-level config
unless the Codex docs explicitly say otherwise.

## Common Value Sets

| Type | Available values |
| --- | --- |
| `AskForApproval` | `untrusted`, `on-failure`, `on-request`, `never`, or `{ granular = { ... } }` |
| `AppToolApproval` | `auto`, `prompt`, `approve` |
| `ApprovalsReviewer` | `user`, `auto_review`, `guardian_subagent` |
| `AuthCredentialsStoreMode` | `file`, `keyring`, `auto`, `ephemeral` |
| `OAuthCredentialsStoreMode` | `auto`, `file`, `keyring` |
| `ForcedLoginMethod` | `chatgpt`, `api` |
| `HistoryPersistence` | `save-all`, `none` |
| `MarketplaceSourceType` | `git`, `local` |
| `NotificationCondition` | `unfocused`, `always` |
| `NotificationMethod` | `auto`, `osc9`, `bel` |
| `OtelExporterKind` | `none`, `statsig` |
| `Personality` | `none`, `friendly`, `pragmatic` |
| `ReasoningEffort` | `none`, `minimal`, `low`, `medium`, `high`, `xhigh` |
| `ReasoningSummary` | `auto`, `concise`, `detailed`, `none` |
| `SandboxMode` | `read-only`, `workspace-write`, `danger-full-access` |
| `ShellEnvironmentPolicyInherit` | `core`, `all`, `none` |
| `SessionPickerViewMode` | `comfortable`, `dense` |
| `ToolSuggestDiscoverableType` | `connector`, `plugin` |
| `UriBasedFileOpener` | `vscode`, `vscode-insiders`, `windsurf`, `cursor`, `none` |
| `Verbosity` | `low`, `medium`, `high` |
| `WebSearchContextSize` | `low`, `medium`, `high` |
| `WebSearchMode` | `disabled`, `cached`, `live` |
| `WindowsSandboxModeToml` | `elevated`, `unelevated` |
| `WireApi` | `responses` |

## Recommended Personal Baseline

```toml
model = "gpt-5.5"
model_reasoning_effort = "high"
sandbox_mode = "workspace-write"
approval_policy = "on-request"

project_doc_fallback_filenames = ["router.md", "CLAUDE.md"]
project_doc_max_bytes = 65536

[agents]
max_threads = 4
max_depth = 1
job_max_runtime_seconds = 1800
interrupt_message = true

[skills]
include_instructions = true
config = []

[skills.bundled]
enabled = true

[shell_environment_policy]
inherit = "core"
experimental_use_profile = false
```

## Top-Level Keys

| Key | Type / values | Default / limits | Purpose |
| --- | --- | --- | --- |
| `agents` | `AgentsToml` table | no schema default | Subagent thread limits and custom agent roles. |
| `allow_login_shell` | boolean | default `true` | Allows shell tools to request login-shell semantics. |
| `analytics` | `AnalyticsConfigToml` table | no schema default | Enables or disables analytics across Codex surfaces. |
| `approval_policy` | `AskForApproval` | values above | Controls when command execution asks for user approval. |
| `approvals_reviewer` | `ApprovalsReviewer` | values above | Chooses who reviews approval requests. |
| `apps` | apps map | no schema default | App/connector visibility and tool approval settings. |
| `apps_mcp_product_sku` | string | no schema enum | Product SKU used by app MCP behavior. Usually managed. |
| `audio` | object | experimental | Audio/realtime-related settings. |
| `auto_review` | `AutoReviewToml` table | no schema default | Extra policy for the automatic approval reviewer. |
| `background_terminal_max_timeout` | integer | no schema min/max | Maximum timeout for background terminal work. |
| `chatgpt_base_url` | string | user-level | Overrides ChatGPT backend base URL. |
| `check_for_update_on_startup` | boolean | no schema default | Checks for Codex updates on startup. |
| `cli_auth_credentials_store` | `AuthCredentialsStoreMode` | values above | Storage backend for CLI auth credentials. |
| `compact_prompt` | string | no schema max | Prompt used for history compaction. |
| `debug` | `DebugToml` table | no schema default | Debugging and reproducibility options. |
| `default_permissions` | string | built-ins start with `:` | Selects a named permissions profile. |
| `desktop` | object | opaque | Desktop-app settings stored in config. |
| `developer_instructions` | string | no schema max | Adds a developer message to sessions. Use carefully. |
| `disable_paste_burst` | boolean | no schema default | Disables burst-paste detection for typed input. |
| `experimental_compact_prompt_file` | absolute path | experimental | Reads compact prompt from a file. |
| `experimental_realtime_start_instructions` | string | experimental | Realtime startup instructions. |
| `experimental_realtime_ws_backend_prompt` | string | experimental | Realtime websocket backend prompt. |
| `experimental_realtime_ws_base_url` | string | user-level, experimental | Realtime websocket base URL override. |
| `experimental_realtime_ws_model` | string | experimental | Realtime websocket model. |
| `experimental_realtime_ws_startup_context` | string | experimental | Realtime startup context override. |
| `experimental_thread_config_endpoint` | string | experimental | Remote thread-scoped config endpoint. |
| `experimental_thread_store` | `ThreadStoreToml` | experimental | Selects thread store implementation. |
| `experimental_use_unified_exec_tool` | boolean | experimental | Enables unified exec tool path. |
| `features` | object of feature flags | no schema default | Centralized feature flags. Most are experimental. |
| `feedback` | `FeedbackConfigToml` table | default enabled | Enables/disables feedback collection. |
| `file_opener` | `UriBasedFileOpener` | values above | Controls file citation link target. |
| `forced_chatgpt_workspace_id` | string or array | no schema enum | Restricts ChatGPT login to workspace id(s). |
| `forced_login_method` | `ForcedLoginMethod` | `chatgpt`, `api` | Restricts login mechanism. |
| `ghost_snapshot` | `GhostSnapshotToml` | legacy | Compatibility-only no-op settings. |
| `hide_agent_reasoning` | boolean | default `false` | Hides agent reasoning events from UI/output. |
| `history` | `History` table | default `save-all` | Controls `~/.codex/history.jsonl`. |
| `hooks` | `HooksToml` table | no schema default | Lifecycle hook configuration. |
| `include_apps_instructions` | boolean | no schema default | Injects apps instruction block. |
| `include_collaboration_mode_instructions` | boolean | no schema default | Injects collaboration-mode instruction block. |
| `include_environment_context` | boolean | no schema default | Injects environment context block. |
| `include_permissions_instructions` | boolean | no schema default | Injects permissions instruction block. |
| `instructions` | string | no schema max | Top-level system instruction override. Use carefully. |
| `log_dir` | absolute path | defaults to `$CODEX_HOME/log` | Where Codex writes logs. |
| `marketplaces` | map | usually managed | Marketplace source metadata. |
| `mcp_oauth_callback_port` | integer | no schema max | Fixed local callback port for MCP OAuth. |
| `mcp_oauth_callback_url` | string | no schema enum | Fixed callback URL for MCP OAuth. |
| `mcp_oauth_credentials_store` | `OAuthCredentialsStoreMode` | values above | Storage backend for MCP OAuth credentials. |
| `mcp_servers` | map of MCP server configs | default `{}` | Registers MCP servers and per-tool policies. |
| `memories` | `MemoriesToml` table | no schema default | Codex memory subsystem settings. |
| `model` | string | no schema enum | Model slug to use. Must be served by provider. |
| `model_auto_compact_token_limit` | integer | no schema min/max | Token threshold for auto-compaction. |
| `model_auto_compact_token_limit_scope` | string | no schema enum | How token threshold is counted. |
| `model_catalog_json` | absolute path | startup-only | Custom model catalog JSON path. |
| `model_context_window` | integer | no schema min/max | Optional context window override. |
| `model_instructions_file` | absolute path | discouraged | Replaces built-in model instructions. |
| `model_provider` | string | map key | Selects provider from `model_providers`. |
| `model_providers` | provider map | default `{}` | Adds OpenAI-compatible provider definitions. |
| `model_reasoning_effort` | `ReasoningEffort` | values above | Default model reasoning effort. |
| `model_reasoning_summary` | `ReasoningSummary` | values above | Reasoning summary behavior. |
| `model_supports_reasoning_summaries` | boolean | no schema default | Force-enables reasoning summary support. |
| `model_verbosity` | `Verbosity` | `low`, `medium`, `high` | GPT verbosity setting. |
| `notice` | `Notice` table | usually managed | Tracks acknowledged product notices. |
| `notify` | array | user-level | External notification command. |
| `openai_base_url` | string | user-level | Overrides built-in OpenAI provider base URL. |
| `oss_provider` | string | e.g. `lmstudio`, `ollama` | Default local provider for `codex --oss`. |
| `otel` | `OtelConfigToml` table | user-level | OpenTelemetry export settings. |
| `permissions` | `PermissionsToml` table | no schema default | Named permission profiles. |
| `personality` | `Personality` | values above | Optional personality preset. |
| `plan_mode_reasoning_effort` | `ReasoningEffort` | values above | Reasoning effort while planning. |
| `plugins` | plugin map | default `{}` | User-level plugin settings. |
| `profile` | string | map key | Selects an entry from `[profiles]`. |
| `profiles` | profile map | no schema default | Named reusable config overlays. |
| `project_doc_fallback_filenames` | array of strings | default `null` | Fallback instruction filenames after `AGENTS.md`. |
| `project_doc_max_bytes` | integer | default `32768`, min `0` | Max bytes included from project instruction docs. |
| `project_root_markers` | array of strings | default `.git` when unset | Markers used to find project root. |
| `projects` | project map | no schema default | Per-project trust settings. |
| `realtime` | `RealtimeToml` table | experimental | Realtime websocket session selection. |
| `review_model` | string | no schema enum | Model override for `/review`. |
| `sandbox_mode` | `SandboxMode` | values above | Command sandbox mode. |
| `sandbox_workspace_write` | `SandboxWorkspaceWrite` | default values below | Workspace-write sandbox controls. |
| `service_tier` | string | e.g. `default`, `priority`, `flex` | Requested service tier for new turns. |
| `shell_environment_policy` | `ShellEnvironmentPolicyToml` | default object | Shell env inheritance/filtering. |
| `show_raw_agent_reasoning` | boolean | default `false` | Shows raw agent reasoning events. |
| `skills` | `SkillsConfig` table | no schema default | Skill loader behavior and enable/disable selectors. |
| `sqlite_home` | absolute path | `$CODEX_SQLITE_HOME` or `$CODEX_HOME` | SQLite state DB directory. |
| `suppress_unstable_features_warning` | boolean | no schema default | Suppresses unstable feature warnings. |
| `tool_output_token_limit` | integer | no schema min/max | Context budget for tool output. |
| `tool_suggest` | `ToolSuggestConfig` | no schema default | Connector/plugin suggestion controls. |
| `tools` | `ToolsToml` table | no schema default | Built-in tool settings, currently web search. |
| `tui` | `Tui` table | no schema default | Terminal UI settings. |
| `web_search` | `WebSearchMode` | values above | Web search mode. |
| `windows` | `WindowsToml` table | Windows only | Windows sandbox settings. |
| `zsh_path` | absolute path | no schema default | Patched zsh path for shell execution. |

## Project Instruction Discovery

These keys control local rule discovery for Codex.

| Key | Values / limits | Description |
| --- | --- | --- |
| `project_doc_fallback_filenames` | array of strings; no schema min/max length | Fallback files tried after `AGENTS.override.md` and `AGENTS.md`. This is fallback, not include. Codex includes at most one instruction file per directory. |
| `project_doc_max_bytes` | integer; default `32768`; min `0`; no schema max | Maximum bytes of project instruction text included. Raise for large rule stacks. |
| `project_root_markers` | array of strings; default is `.git` when unset | Controls where Codex stops walking parent directories for project config and project docs. |

Example:

```toml
project_doc_fallback_filenames = ["router.md", "CLAUDE.md"]
project_doc_max_bytes = 65536
project_root_markers = [".git", "package.json", "pyproject.toml"]
```

## Agents

`[agents]` controls spawned Codex subagents.

| Key | Values / limits | Description |
| --- | --- | --- |
| `max_threads` | integer; min `1`; no schema max | Maximum open agent threads. Runtime/session caps may still be lower. |
| `max_depth` | integer; min `1`; no schema max | Maximum nesting depth. Root session is depth `0`; direct subagents are depth `1`. |
| `job_max_runtime_seconds` | integer; min `1`; no schema max | Default max runtime for agent job workers. |
| `interrupt_message` | boolean; default behavior is `true` | Records a model-visible message when an agent turn is interrupted. |

Recommended:

```toml
[agents]
max_threads = 4
max_depth = 1
job_max_runtime_seconds = 1800
interrupt_message = true
```

Custom roles are allowed under `[agents.<role>]`.

| Role key | Values / limits | Description |
| --- | --- | --- |
| `description` | string | Human-facing role documentation used in spawn tool guidance. Required unless supplied by the referenced role file. |
| `config_file` | absolute path; relative paths resolve relative to the defining config file | Role-specific config layer. Can set model, sandbox, reasoning, tools, and other profile-like settings. |
| `nickname_candidates` | array of strings | Candidate nicknames for agents spawned with this role. |

Example:

```toml
[agents.reviewer]
description = "Read-only code reviewer focused on regressions and missing tests."
config_file = "roles/reviewer.config.toml"
nickname_candidates = ["reviewer", "critic"]
```

## Skills

`[skills]` config controls skill discovery presentation and explicit enable/disable selectors.
It does not define skill metadata, env vars, MCP dependencies, or approval modes.

| Key | Values / limits | Description |
| --- | --- | --- |
| `include_instructions` | boolean | Whether turns receive the automatic skills instruction block. Leave `true` for normal use. |
| `config` | array of `SkillConfig` selectors | Per-skill enable/disable list. |
| `[skills.bundled].enabled` | boolean; default `true` | Enables or disables bundled/system skills. |

`SkillConfig` entries:

| Key | Values / limits | Description |
| --- | --- | --- |
| `name` | string | Selects skill by name. Useful when names are unique. |
| `path` | absolute path | Selects an exact `SKILL.md` path. Use when duplicate names exist. |
| `enabled` | boolean | Enables or disables the selected skill. |

Example:

```toml
[skills]
include_instructions = true
config = [
  { name = "imagegen", enabled = false },
  { path = "/Users/genome/.codex/skills/composio-cli/SKILL.md", enabled = true },
]

[skills.bundled]
enabled = true
```

## Models And Providers

| Key | Values / limits | Description |
| --- | --- | --- |
| `model` | string | Slug Codex asks the provider for. The provider must actually serve it. |
| `model_provider` | string | Key in `[model_providers]` or a built-in provider id. |
| `model_providers` | map | Adds provider definitions. Built-in ids cannot be overridden. |
| `model_catalog_json` | absolute path | Startup-only custom model catalog. Affects model metadata/picker, not provider capability. |
| `oss_provider` | string, commonly `ollama` or `lmstudio` | Preferred local provider when launching `codex --oss`. |
| `openai_base_url` | string | User-level override for built-in OpenAI provider. |
| `chatgpt_base_url` | string | User-level override for ChatGPT backend. |

Provider entries live under `[model_providers.<id>]`.

| Provider key | Values / limits | Description |
| --- | --- | --- |
| `name` | string; default `""` | Friendly display name. |
| `base_url` | string | Base URL for the OpenAI-compatible API. |
| `wire_api` | `responses`; default `responses` | Protocol the provider speaks. |
| `env_key` | string | Environment variable containing the provider API key. |
| `env_key_instructions` | string | Help text for setting the env var. |
| `requires_openai_auth` | boolean; default `false` | Whether provider requires OpenAI API key or ChatGPT login token. |
| `request_max_retries` | integer; min `0`; no schema max | HTTP request retry count. |
| `stream_max_retries` | integer; min `0`; no schema max | Stream reconnection retry count. |
| `stream_idle_timeout_ms` | integer; min `0`; no schema max | Streaming idle timeout in milliseconds. |
| `websocket_connect_timeout_ms` | integer; min `0`; no schema max | Websocket connection timeout in milliseconds. |
| `supports_websockets` | boolean; default `false` | Whether provider supports Responses API WebSocket transport. |
| `http_headers` | object | Literal HTTP headers. Avoid secrets here. |
| `env_http_headers` | object | Header names mapped to env var names. Safer for secrets. |
| `query_params` | object | Query params appended to base URL. |
| `experimental_bearer_token` | string | Direct bearer token. Discouraged; prefer `env_key`. |
| `auth` | `ModelProviderAuthInfo` | Command-backed bearer-token configuration. |
| `aws` | `ModelProviderAwsAuthInfo` | AWS SigV4 provider auth configuration. |

Example local provider:

```toml
model_provider = "local_ollama"
model = "llama3.1"
oss_provider = "ollama"

[model_providers.local_ollama]
name = "Local Ollama"
base_url = "http://127.0.0.1:11434/v1"
wire_api = "responses"
env_key = "OLLAMA_API_KEY"
request_max_retries = 0
stream_idle_timeout_ms = 300000
```

## Approval, Permissions, And Sandbox

| Key | Values / limits | Description |
| --- | --- | --- |
| `approval_policy` | `untrusted`, `on-failure`, `on-request`, `never`, or granular object | Main approval policy for commands. |
| `approvals_reviewer` | `user`, `auto_review`, `guardian_subagent` | Reviewer for approval prompts. |
| `default_permissions` | string | Named permissions profile; built-ins begin with `:`. |
| `permissions` | table | Named permissions profiles. Shape is policy-specific. |
| `sandbox_mode` | `read-only`, `workspace-write`, `danger-full-access` | Shell sandbox mode. |
| `sandbox_workspace_write` | table | Extra controls for `workspace-write`. |

Granular approval form:

```toml
[approval_policy.granular]
mcp_elicitations = true
request_permissions = false
rules = true
sandbox_approval = true
skill_approval = false
```

`[sandbox_workspace_write]`:

| Key | Values / limits | Description |
| --- | --- | --- |
| `network_access` | boolean; default `false` | Allows network from workspace-write sandbox. |
| `writable_roots` | array; default `[]` | Extra writable filesystem roots. |
| `exclude_slash_tmp` | boolean; default `false` | Excludes `/tmp` from default writable paths. |
| `exclude_tmpdir_env_var` | boolean; default `false` | Excludes `$TMPDIR` from default writable paths. |

## Shell Environment

`[shell_environment_policy]` controls what environment reaches shell tools.

| Key | Values / limits | Description |
| --- | --- | --- |
| `inherit` | `core`, `all`, `none` | Base inheritance policy. |
| `include_only` | array of regex strings | Only include env vars matching these regexes. |
| `exclude` | array of regex strings | Exclude env vars matching these regexes. |
| `ignore_default_excludes` | boolean | Disables Codex default exclude list. Use carefully. |
| `set` | object | Explicit env vars to set. Never hardcode secrets in shared files. |
| `experimental_use_profile` | boolean | Uses more shell profile behavior for subprocesses. Usually leave `false`. |

Example:

```toml
[shell_environment_policy]
inherit = "core"
include_only = ["^PATH$", "^HOME$", "^USER$", "^SHELL$"]
exclude = ["^OPENAI_API_KEY$", "^AWS_"]
set = { PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin" }
experimental_use_profile = false
```

## MCP Servers

MCP servers live under `[mcp_servers.<name>]`.

| MCP key | Values / limits | Description |
| --- | --- | --- |
| `command` | string | Local command to start stdio MCP server. |
| `args` | array; default `null` | Command arguments. |
| `cwd` | string; default `null` | Working directory for server command. |
| `env` | object; default `null` | Literal env values for server. Avoid secrets in shared files. |
| `env_vars` | array; default `null` | Env var names forwarded from environment. |
| `url` | string | Remote/server URL. |
| `bearer_token_env_var` | string | Env var that contains bearer token. |
| `http_headers` | object | Literal HTTP headers. |
| `env_http_headers` | object; default `null` | Header names mapped to env var names. |
| `enabled` | boolean; default `null` | Enables/disables server entry. |
| `required` | boolean; default `null` | Marks server required. |
| `enabled_tools` | array; default `null` | Allow-list of tools. |
| `disabled_tools` | array; default `null` | Deny-list of tools. |
| `default_tools_approval_mode` | `auto`, `prompt`, `approve`; default `null` | Default approval mode for tools. |
| `tools` | object; default `null` | Per-tool settings. |
| `startup_timeout_ms` | integer; min `0`; default `null` | Startup timeout in ms. |
| `startup_timeout_sec` | number; default `null` | Startup timeout in seconds. |
| `tool_timeout_sec` | number; default `null` | Per-tool timeout in seconds. |
| `supports_parallel_tool_calls` | boolean; default `null` | Whether tools can run in parallel. |
| `oauth` | `McpServerOAuthConfig`; default `null` | OAuth details. |
| `oauth_resource` | string; default `null` | OAuth resource identifier. |
| `scopes` | array; default `null` | OAuth scopes. |
| `experimental_environment` | string; default `null` | Experimental environment selector. |
| `name` | string; default `null` | Legacy display name. |

Per-tool MCP config:

```toml
[mcp_servers.github.tools.create_issue]
approval_mode = "prompt"
```

## Apps, Connectors, Plugins, And Tool Suggestions

`[apps]` controls app/connector availability and per-tool behavior.

| App key | Values / limits | Description |
| --- | --- | --- |
| `enabled` | boolean; default `true` | Whether Codex surfaces this app. |
| `default_tools_enabled` | boolean | Whether app tools are enabled by default. |
| `default_tools_approval_mode` | `auto`, `prompt`, `approve` | Default app tool approval mode. |
| `open_world_enabled` | boolean | Allows tools marked `open_world_hint = true`. |
| `destructive_enabled` | boolean | Allows tools marked `destructive_hint = true`. |
| `tools` | map | Per-tool app settings. |

Per-tool app settings:

| Key | Values / limits | Description |
| --- | --- | --- |
| `enabled` | boolean | Enables/disables a tool. |
| `approval_mode` | `auto`, `prompt`, `approve` | Approval mode for that tool. |

`[plugins.<name>]`:

| Plugin key | Values / limits | Description |
| --- | --- | --- |
| `enabled` | boolean | Enables/disables the plugin. |
| `mcp_servers` | map | Policy overlays for MCP servers contributed by the plugin. |

`[tool_suggest]` controls suggestions to install or enable discoverable plugins/connectors.
It does not disable already installed tools.

| Key | Values / limits | Description |
| --- | --- | --- |
| `disabled_tools` | array of `{ type, id }` | Prevents suggestions for specific discoverables. `type` is `connector` or `plugin`. |
| `discoverables` | array of `{ type, id }` | Adds discoverables eligible for suggestion. `type` is `connector` or `plugin`. |

Example:

```toml
[tool_suggest]
disabled_tools = [
  { type = "plugin", id = "canva@openai-curated" },
]
discoverables = [
  { type = "plugin", id = "linear@openai-curated" },
]
```

## Built-In Tools And Web Search

| Key | Values / limits | Description |
| --- | --- | --- |
| `web_search` | `disabled`, `cached`, `live` | Top-level web search mode. |
| `[tools.web_search].allowed_domains` | array | Restricts web search to domains. |
| `[tools.web_search].context_size` | `low`, `medium`, `high` | Search context size. |
| `[tools.web_search].location` | object/string shape | Search location hint. |
| `tool_output_token_limit` | integer; no schema min/max | Token budget for tool output. |

## Profiles

`[profiles.<name>]` is a reusable config overlay. Select it with:

```toml
profile = "work"
```

Profile-supported keys include:

| Profile key | Values / limits |
| --- | --- |
| `model` | string |
| `model_provider` | string |
| `model_reasoning_effort` | `ReasoningEffort` |
| `model_reasoning_summary` | `ReasoningSummary` |
| `model_verbosity` | `low`, `medium`, `high` |
| `model_catalog_json` | absolute path |
| `model_instructions_file` | absolute path |
| `oss_provider` | string |
| `sandbox_mode` | `SandboxMode` |
| `approval_policy` | `AskForApproval` |
| `approvals_reviewer` | `ApprovalsReviewer` |
| `service_tier` | string |
| `web_search` | `WebSearchMode` |
| `tools` | `ToolsToml` |
| `tui` | `ProfileTui` |
| `features` | object |
| `personality` | `Personality` |
| `plan_mode_reasoning_effort` | `ReasoningEffort` |
| `include_apps_instructions` | boolean |
| `include_collaboration_mode_instructions` | boolean |
| `include_environment_context` | boolean |
| `include_permissions_instructions` | boolean |
| `experimental_compact_prompt_file` | absolute path |
| `experimental_use_unified_exec_tool` | boolean |
| `chatgpt_base_url` | string |
| `zsh_path` | absolute path |
| `windows` | `WindowsToml` |

Example:

```toml
profile = "local"

[profiles.local]
model_provider = "local_ollama"
model = "llama3.1"
model_reasoning_effort = "medium"
sandbox_mode = "workspace-write"
approval_policy = "on-request"
web_search = "disabled"
```

## TUI And Notifications

`[tui]` controls terminal UI behavior.

| Key | Values / limits | Description |
| --- | --- | --- |
| `alternate_screen` | `auto`, `always`, `never` | Terminal alternate screen behavior. |
| `animations` | boolean; default `true` | Enables welcome/spinner/shimmer animations. |
| `notification_condition` | `unfocused`, `always` | When TUI notifications are delivered. |
| `notification_method` | `auto`, `osc9`, `bel` | Notification transport. |
| `notifications` | boolean; default `true` | Enables desktop/terminal notifications. |
| `raw_output_mode` | boolean; default `false` | Starts TUI in copy-friendly raw scrollback mode. |
| `session_picker_view` | `comfortable`, `dense` | Resume/fork picker layout. |
| `show_tooltips` | boolean; default `true` | Startup tooltip visibility. |
| `status_line` | array | Ordered status line item ids. |
| `status_line_use_colors` | boolean; default `true` | Colors status line items. |
| `terminal_resize_reflow_max_rows` | integer; min `0`; no schema max | Max rows replayed during terminal resize reflow. |
| `terminal_title` | array | Ordered terminal title item ids. |
| `theme` | string | Syntax highlighting theme name. |
| `vim_mode_default` | boolean; default `false` | Starts composer in Vim normal mode. |
| `pet` | string | Terminal pet id. |
| `pet_anchor` | enum-like value | Where terminal pet anchors. |
| `keymap` | table | Keybinding overrides by group. |
| `model_availability_nux` | table | Startup model availability tooltip state. Usually managed. |

## History And Memories

`[history]`:

| Key | Values / limits | Description |
| --- | --- | --- |
| `persistence` | `save-all`, `none`; default `save-all` | Whether history is written to disk. |
| `max_bytes` | integer; no schema min/max | Maximum history file size before old entries are dropped. |

`[memories]`:

| Key | Values / limits | Description |
| --- | --- | --- |
| `use_memories` | boolean | Whether memory instructions are injected. |
| `generate_memories` | boolean | Whether new threads produce memory candidates. |
| `extract_model` | string | Model for thread summarization. |
| `consolidation_model` | string | Model for memory consolidation. |
| `max_rollout_age_days` | integer | Oldest rollout age considered for memory. |
| `max_rollouts_per_startup` | integer | Startup processing cap. |
| `min_rollout_idle_hours` | integer | Idle time before a thread is eligible. |
| `max_raw_memories_for_consolidation` | integer | Recent raw memory retention cap. |
| `max_unused_days` | integer | Max unused age before memory is ineligible. |
| `min_rate_limit_remaining_percent` | integer | Rate limit reserve needed before memory startup work. |
| `disable_on_external_context` | boolean | Marks threads polluted when external context is present. |

## Hooks

`[hooks]` supports lifecycle hook arrays/tables. Hook payload shapes evolve quickly,
so treat this section as version-sensitive.

Known hook groups:

- `PermissionRequest`
- `PreToolUse`
- `PostToolUse`
- `UserPromptSubmit`
- `SessionStart`
- `Stop`
- `PreCompact`
- `PostCompact`
- `SubagentStart`
- `SubagentStop`
- `state`

## Telemetry, Auth, And Notices

| Key | Values / limits | Description |
| --- | --- | --- |
| `cli_auth_credentials_store` | `file`, `keyring`, `auto`, `ephemeral` | CLI auth credential storage. |
| `mcp_oauth_credentials_store` | `auto`, `file`, `keyring` | MCP OAuth credential storage. |
| `forced_login_method` | `chatgpt`, `api` | Restricts login method. |
| `forced_chatgpt_workspace_id` | string or array | Restricts ChatGPT login to specific workspace ids. |
| `analytics.enabled` | boolean | Enables analytics. |
| `feedback.enabled` | boolean | Enables feedback flow. |
| `auto_review.policy` | string | Additional approval reviewer policy. |

`[otel]`:

| Key | Values / limits | Description |
| --- | --- | --- |
| `environment` | string; default `dev` | Environment tag for traces. |
| `exporter` | `none`, `statsig` | Default exporter. |
| `trace_exporter` | `none`, `statsig` | Trace exporter. |
| `metrics_exporter` | `none`, `statsig` | Metrics exporter. |
| `log_user_prompt` | boolean | Whether user prompts are logged in traces. |
| `span_attributes` | object | Attributes added to exported spans. |
| `tracestate` | object | W3C tracestate members. |

`[notice]` is normally managed by Codex and tracks acknowledged prompts such as
full-access warnings, model migrations, external config migration prompts, and
rate-limit nudges.

## Marketplaces

Marketplace entries are usually managed by Codex:

| Key | Values / limits | Description |
| --- | --- | --- |
| `source` | string | Source location. |
| `source_type` | `git`, `local` | Source kind. |
| `ref` | string | Git ref when source is git. |
| `sparse_paths` | array | Sparse checkout paths. |
| `last_revision` | string | Last successfully activated revision. |
| `last_updated` | string | Last refresh time. |

## Realtime, Audio, Windows, Debug, And Compatibility

These sections are either experimental, platform-specific, or usually managed.

| Section / key | Values / limits | Description |
| --- | --- | --- |
| `[realtime].version` | `v1`, `v2` | Realtime conversation version. |
| `[realtime].type` | `conversational`, `transcription` | Realtime mode. |
| `[realtime].transport` | `webrtc`, `websocket` | Realtime transport. |
| `[realtime].voice` | `alloy`, `arbor`, `ash`, `ballad`, `breeze`, `cedar`, `coral`, `cove`, `echo`, `ember`, `juniper`, `maple`, `marin`, `sage`, `shimmer`, `sol`, `spruce`, `vale`, `verse` | Voice. |
| `[windows].sandbox` | `elevated`, `unelevated` | Windows sandbox type. |
| `[windows].sandbox_private_desktop` | boolean; default `true` | Uses private desktop for sandboxed child process. |
| `[ghost_snapshot].disable_warnings` | boolean | Legacy no-op compatibility setting. |
| `[ghost_snapshot].ignore_large_untracked_dirs` | legacy | Legacy no-op compatibility setting. |
| `[ghost_snapshot].ignore_large_untracked_files` | legacy | Legacy no-op compatibility setting. |
| `[debug.config_lockfile].export_dir` | absolute path | Writes resolved config lock data. |
| `[debug.config_lockfile].load_path` | absolute path | Loads config lock data. |
| `[debug.config_lockfile].allow_codex_version_mismatch` | boolean | Allows lockfile reuse across versions. |
| `[debug.config_lockfile].save_fields_resolved_from_model_catalog` | boolean | Persists model-catalog-resolved fields. |

## Feature Flags

`[features]` is a map of booleans unless a named feature uses a richer table
shape. Most flags are experimental or rollout controls. Do not turn on unknown
flags just because they exist.

Known schema feature keys:

| Feature flag | Typical value | Notes |
| --- | --- | --- |
| `apply_patch_freeform` | boolean | Freeform patch tool path. |
| `apply_patch_streaming_events` | boolean | Streaming patch events. |
| `apps` | boolean | Apps/connectors feature. |
| `apps_mcp_path_override` | boolean or table | App MCP path override. |
| `auth_elicitation` | boolean | Auth elicitation feature. |
| `browser_use` | boolean | Browser-use feature. |
| `browser_use_external` | boolean | External browser-use path. |
| `child_agents_md` | boolean | Child agent instruction docs. |
| `chronicle` | boolean | Chronicle feature. |
| `code_mode` | boolean | Code mode. |
| `code_mode_only` | boolean | Code-mode-only surface. |
| `codex_git_commit` | boolean | Codex git commit feature. |
| `codex_hooks` | boolean | Codex hooks. |
| `collab` | boolean | Collaboration feature. |
| `collaboration_modes` | boolean | Collaboration modes. |
| `computer_use` | boolean | Computer-use tools. |
| `connectors` | boolean | Connectors feature. |
| `default_mode_request_user_input` | boolean | Request-user-input in default mode. |
| `elevated_windows_sandbox` | boolean | Elevated Windows sandbox. |
| `enable_experimental_windows_sandbox` | boolean | Experimental Windows sandbox. |
| `enable_fanout` | boolean | Fanout/concurrent work features. |
| `enable_mcp_apps` | boolean | MCP-backed apps. |
| `enable_request_compression` | boolean | Request compression. |
| `exec_permission_approvals` | boolean | Exec permission approvals. |
| `experimental_use_unified_exec_tool` | boolean | Unified exec experiment. |
| `experimental_windows_sandbox` | boolean | Windows sandbox experiment. |
| `external_migration` | boolean | External migration prompts. |
| `fast_mode` | boolean | Fast mode. |
| `goals` | boolean | Goals feature. |
| `guardian_approval` | boolean | Guardian approval reviewer. |
| `hooks` | boolean | Hook system. |
| `image_detail_original` | boolean | Original-detail image handling. |
| `image_generation` | boolean | Image generation tool. |
| `in_app_browser` | boolean | In-app browser. |
| `js_repl` | boolean | JS REPL. |
| `js_repl_tools_only` | boolean | JS REPL tools-only mode. |
| `memories` | boolean | Memory subsystem. |
| `memory_tool` | boolean | Memory tool. |
| `mentions_v2` | boolean | Mentions v2. |
| `multi_agent` | boolean | Multi-agent support. |
| `multi_agent_v2` | boolean or table | V2 multi-agent config. |
| `network_proxy` | boolean or table | Network proxy controls. |
| `personality` | boolean | Personality setting support. |
| `plugin_hooks` | boolean | Plugin hook support. |
| `plugin_sharing` | boolean | Plugin sharing. |
| `plugins` | boolean | Plugin system. |
| `prevent_idle_sleep` | boolean | Prevents idle sleep. |
| `realtime_conversation` | boolean | Realtime conversation. |
| `remote_compaction_v2` | boolean | Remote compaction v2. |
| `remote_control` | boolean | Remote control. |
| `remote_models` | boolean | Remote model features. |
| `remote_plugin` | boolean | Remote plugin. |
| `request_permissions` | boolean | Request permissions system. |
| `request_permissions_tool` | boolean | Request permissions tool. |
| `request_rule` | boolean | Request rule feature. |
| `responses_websocket_response_processed` | boolean | Responses websocket processed event. |
| `responses_websockets` | boolean | Responses websocket transport. |
| `responses_websockets_v2` | boolean | Responses websocket v2. |
| `runtime_metrics` | boolean | Runtime metrics. |
| `search_tool` | boolean | Search tool. |
| `shell_snapshot` | boolean | Shell snapshot. |
| `shell_tool` | boolean | Shell tool. |
| `shell_zsh_fork` | boolean | zsh fork shell execution. |
| `skill_env_var_dependency_prompt` | boolean | Skill env var dependency prompts. |
| `skill_mcp_dependency_install` | boolean | Skill MCP dependency install. |
| `sqlite` | boolean | SQLite state features. |
| `steer` | boolean | Steering feature. |
| `telepathy` | boolean | Telepathy feature. |
| `terminal_resize_reflow` | boolean | Terminal resize reflow. |
| `tool_call_mcp_elicitation` | boolean | MCP elicitation during tool calls. |
| `tool_search` | boolean | Deferred tool search. |
| `tool_search_always_defer_mcp_tools` | boolean | Always defer MCP tools to search. |
| `tool_suggest` | boolean | Tool suggestion system. |
| `tui_app_server` | boolean | TUI app server. |
| `unavailable_dummy_tools` | boolean | Dummy tools for unavailable tools. |
| `undo` | boolean | Undo feature. |
| `unified_exec` | boolean | Unified exec. |
| `use_legacy_landlock` | boolean | Legacy Linux landlock path. |
| `use_linux_sandbox_bwrap` | boolean | Linux bubblewrap sandbox. |
| `web_search` | boolean | Web search feature. |
| `web_search_cached` | boolean | Cached web search. |
| `web_search_request` | boolean | Web search request path. |
| `workspace_dependencies` | boolean | Workspace dependency helper. |
| `workspace_owner_usage_nudge` | boolean | Workspace owner usage nudge. |

`features.network_proxy` table keys when table-shaped:

| Key | Values / limits | Description |
| --- | --- | --- |
| `enabled` | boolean | Enables proxy feature. |
| `mode` | mode-specific | Proxy mode. |
| `proxy_url` | string | HTTP proxy URL. |
| `socks_url` | string | SOCKS proxy URL. |
| `enable_socks5` | boolean | Enables SOCKS5. |
| `enable_socks5_udp` | boolean | Enables SOCKS5 UDP. |
| `allow_local_binding` | boolean | Allows local binding. |
| `allow_upstream_proxy` | boolean | Allows upstream proxy use. |
| `dangerously_allow_non_loopback_proxy` | boolean | Allows non-loopback proxy. Security-sensitive. |
| `dangerously_allow_all_unix_sockets` | boolean | Allows all Unix sockets. Security-sensitive. |
| `domains` | object | Domain policy map. |
| `unix_sockets` | object | Unix socket policy map. |

## Practical Rules

- Put behavioral rules in `AGENTS.md`, not in `config.toml`.
- Put project-local Codex config in `<repo>/.codex/config.toml` only when the project is trusted.
- Keep secrets out of shared repo config. Use env vars and `env_key` / `env_http_headers`.
- Treat `features.*`, `experimental_*`, `realtime`, `audio`, and `debug` as unstable unless you are testing a known Codex feature.
- For subagents, prefer `max_depth = 1`; raise `max_threads` before raising depth.
- For local models, `model_catalog_json` changes Codex model metadata, while `model_provider` and `base_url` decide where requests actually go.
