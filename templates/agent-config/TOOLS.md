# Tools

List the visible capabilities intended for this layer.

## Skills

| Skill | Use When | Source |
| --- | --- | --- |
|  |  |  |

## Commands

| Command | Use When | Notes |
| --- | --- | --- |
|  |  |  |

## MCP Servers

| Config ID | Server | Use When | Install Status | Boundary |
| --- | --- | --- | --- | --- |
| `notion` | Notion | Genome's Notion control-plane reads and approved writes. | installed at every layer | Verify Genome's Notion before writing; do not use Michael Clark's personal workspace. |
| `genomes_brain` | Genome's Brain | Durable cross-session memory reads and non-secret writes. | installed at every layer | No secrets; use project rules and memory policy before writing. |
| `github` | GitHub | GitHub repository, issue, pull request, and code-hosting work. | installed at every layer | Use least-privilege `GITHUB_PAT_TOKEN`; never commit or print token values. |
| `context_mode` | Context Mode | Large-file, repo, and session-memory analysis without flooding prompt context. | installed at every layer | Use for analysis and retrieval; do not use context-mode subprocesses for file writes. |
| `sentry` | Sentry | LOS error, trace, release, and production incident investigation. | visible; LOS layers only | Production/customer-visible changes still require approval. |
| `datadog` | Datadog | LOS observability, logs, metrics, traces, and monitor investigation. | visible; LOS layers only | Do not expose customer data outside approved LOS observability workflows. |
| `supabase` | Supabase | Clark consulting Supabase project work. | visible; clarks_consulting layers only | Use only in approved Clark consulting layers unless a customer profile explicitly approves it. |
| `composio` | Composio | Federated SaaS tools, OAuth flows, triggers, and app actions. | visible; endpoint approval required | Install only after generating an approved Composio MCP server URL for the target layer. |
| `orgo` | Orgo.io | Isolated cloud desktop and computer-use execution targets. | visible; bridge approval required | Install only through an approved Orgo MCP bridge or runtime execution target. |
| `playwright` | Playwright | Browser automation and UI validation workflows. | visible; opt in for browser automation layers | Add to config only in layers that explicitly own browser automation. |

## Plugins And Libraries

| Name | Use When | Notes |
| --- | --- | --- |
|  |  |  |

## Local Wrappers

| Wrapper | Use When | Notes |
| --- | --- | --- |
|  |  |  |

## When To Use What

-

## Missing Or Disabled

-
