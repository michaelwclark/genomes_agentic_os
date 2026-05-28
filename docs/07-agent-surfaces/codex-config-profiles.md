# Codex Config Profiles Per Agentic OS Layer

Codex profiles should match the Agentic OS layer that is doing the work. The
profile selects runtime posture: model behavior, sandbox and approval defaults,
available MCP surfaces, prompt files to load, environment assumptions, and
telemetry posture.

Use this guide with:

- `docs/07-agent-surfaces/codex-config-toml-inventory.md`
- `templates/agent-config/codex-config-layer-map.yml`
- `templates/agent-config/codex-profiles.toml`
- `templates/agent-config/codex-profile-manifest.yml`

## Profile Layers

| Profile | Directory Layer | Model Behavior | Skills | Prompt Files | MCP Availability | Environment | Logging / Telemetry |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `global_user_harness` | user harness runtime | Conservative defaults; do not assume repo context. | Skill discovery, memory refresh, shell hygiene. | `AGENTS.md`, `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`, `MEMORY.md` | User-approved global MCPs only. | User home and configured project roots. | Minimal; do not log secrets or full prompts. |
| `agentic_os_root` | reusable OS source or installed OS root | Product/source-aware; prefer templates, schemas, and commands. | build-runner, os-doctor, workflow-builder, run-logger. | `AGENTS.md`, `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`, `MEMORY.md` | Filesystem, Git, Notion control-plane access after workspace verification. | Repository or installed `~/agentic_os`. | Normal run logs; OTEL prompt logging disabled unless explicitly approved. |
| `customer_os_root` | customer-specific OS root | Customer-boundary aware; preserve approved domains. | customer validation, source-map review, handoff checks. | `AGENTS.md`, `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`, `MEMORY.md`, `customer.yml` | Customer-approved systems only. | Customer OS root and approved repos. | Customer-safe summaries only; no private source leakage. |
| `domain_or_lane` | domain, room, or lane directory | Narrow routing and source-map behavior. | routing, context-pack, workflow readiness, automation qualifier. | `AGENTS.md`, `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`, `MEMORY.md`, `domain.yml` | Domain-approved systems only. | Domain folder plus linked project/workflow folders. | Domain run logs and activity logs. |
| `workflow_or_task` | workflow, project task, or run directory | Task-specific execution with explicit acceptance criteria. | context-pack builder, QA planning, run closeout. | `AGENTS.md`, `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`, `MEMORY.md`, workflow files | Workflow-approved systems only. | Workflow folder, run artifacts, linked sources. | Run log evidence and validation results. |
| `automation` | automation directory | Guarded, repeatable, idempotent operation. | automation qualifier, runtime operator, integration setup. | `AGENTS.md`, `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`, `MEMORY.md`, automation files | Explicit automation contract only. | Runtime registry, logs, and approved connected systems. | Structured runtime records; keep prompt logging disabled by default. |

## Prompt Duplication Rule

Profiles should not duplicate long behavior text. Keep durable behavior in the
shared context-file convention:

- `AGENTS.md` for the route-read-cd-repeat bootstrap.
- `ROUTER.md` for routing.
- `CONTEXT.md` for local operating context.
- `RULES.md` for approval, safety, and local constraints.
- `TOOLS.md` for visible capabilities.
- `MEMORY.md` for memory policy.
- `CLAUDE.md` as a short adapter that includes `AGENTS.md`.

Profiles may point to these files and select runtime posture; they should not
copy the same instructions into every directory.

## Precedence And Merge Behavior

Codex and Agentic OS context can come from several places. Use this precedence:

1. Active user instruction in the current thread.
2. Directory-local `config.toml` profile.
3. Directory-local prompt files.
4. Parent Agentic OS profile and prompt files.
5. Global harness defaults.

When nested directories each provide configuration:

- The narrower directory selects the active profile for model, sandbox,
  approval, and task posture.
- The strictest approval, secrets, production, destructive-action, billing, and
  customer-visible-output rule wins.
- MCP availability is the intersection of runtime availability and the
  narrowest applicable layer contract.
- Telemetry defaults should only become more restrictive in narrower layers.
- Prompt files stitch broad to narrow; local files add context but do not
  silently weaken parent safety rules.

## Installer Contract

An installer should treat `templates/agent-config/codex-profiles.toml` as the
Codex-facing profile template and `codex-profile-manifest.yml` as Agentic OS
metadata. It should preserve local edits, show diffs, and require explicit
confirmation before changing existing security-sensitive keys.
