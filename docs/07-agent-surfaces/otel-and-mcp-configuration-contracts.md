# OTEL And MCP Configuration Contracts

Agentic OS config must describe telemetry and MCP availability without leaking
secrets or coupling customer roots to one local machine.

## OTEL Contract

Use `[otel]` for telemetry posture:

```toml
[otel]
log_user_prompt = false
exporter_otlp_endpoint_env_var = "AGENTIC_OS_OTEL_EXPORTER_OTLP_ENDPOINT"
headers_env_var = "AGENTIC_OS_OTEL_HEADERS"
```

Rules:

- `log_user_prompt` defaults to `false` for every Agentic OS layer.
- Exporter endpoints and headers are referenced by environment variable name.
- Token, password, and header values must not be printed in command output,
  docs, templates, logs, or comments.
- Narrower layers may only make telemetry more restrictive unless the user
  explicitly approves a broader setting.

## Per-Layer Defaults

| Layer | Prompt Logging | OTEL Env Vars | Notes |
| --- | --- | --- | --- |
| `global_harness` | disabled | `AGENTIC_OS_OTEL_EXPORTER_OTLP_ENDPOINT`, `AGENTIC_OS_OTEL_HEADERS` | Global harness logs must not capture secrets or full prompts. |
| `agentic_os_root` | disabled | same | Source package and installed OS runs can record local validation summaries. |
| `customer_os_root` | disabled | same | Customer roots must keep customer-safe summaries only. |
| `domain_or_lane` | disabled | same | Domain logs record run evidence, not raw secrets. |
| `workflow_or_task` | disabled | same | Workflow run logs capture validation and artifacts. |
| `automation` | disabled | same | Runtime records should be structured and redacted. |

## MCP Registration Points

| MCP Surface | Registration Point | Secret Rule |
| --- | --- | --- |
| Notion | Verified Genome's Notion connector or direct API env vars | Reference `GENOMES_NOTION_PAT` or `GENOMES_NOTION_CONNECTOR` by name only. |
| Browser | Local browser or in-app browser capability | No credentials in config; rely on the user's authenticated browser session. |
| Filesystem/runtime | `mcp_servers.filesystem_runtime` or local CLI command | No inline secrets; path access is scoped by the active environment. |
| Memory | configured memory MCP or local memory files | No secrets or sensitive customer data unless explicitly approved and sanitized. |
| Customer integrations | customer-specific integration setup | Use customer-approved env var names and approval gates. |

## Validation

Run:

```bash
agentic-os config doctor --root ~/agentic_os --layer agentic_os_root
```

The doctor reports actionable remediation when required OTEL keys, MCP secret
policy, sandbox, approval, or layer MCP availability are missing.
