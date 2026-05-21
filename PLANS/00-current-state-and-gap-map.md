# Current State And Gap Map

## Status

- Status: ready
- Owner: Genome
- Created: 2026-05-20
- Target OS layer: source package and installed runtime

## What Exists Now

Genome's Agentic OS currently has a useful V1 scaffold.

Built CLI surface:

- `agentic-os init`
- `agentic-os domain create`
- `agentic-os workflow create`
- `agentic-os automation create`
- `agentic-os run-log create`
- `agentic-os docs install`
- `agentic-os docs update`
- `agentic-os validate`

Built runtime surface:

- Domain-first installed root at `~/agentic_os`.
- Root and domain routers for Codex, Claude, and generic agents.
- Standard domain lanes for control plane, inbox, projects, workflows, automations, knowledge, runs, metrics, and archive.
- Workflow folder scaffold with PRD, implementation plan, dispatch handoff, context pack, approval rules, output contract, runbook, examples, and runs.
- Automation folder scaffold with trigger, inputs, outputs, permissions, failure modes, runbook, tests, and logs.
- Runtime operating manual, harness commands, harness skills, templates, and SVG diagrams under `shared_factory/05-knowledge/`.
- Additive `docs update` behavior that copies missing managed assets without overwriting existing runtime edits.
- Structural validation for required files, required folders, and parseable JSON/YAML.

## What Is Not Built Yet

The scaffold does not yet operate the full loop by itself.

Missing operational capabilities:

- `agentic-os project create`
- Project status, source map, artifacts, and active-work registration.
- Cwd-aware command routing from inside `~/projects/*` or any OS domain path.
- Automatic context pack creation from routers, source maps, projects, workflows, run logs, and memory policy.
- Workflow readiness checks.
- Run closeout with final status, validation evidence, next action, and learning promotion.
- Always-on heartbeat registry for monitors, recurring checks, scheduled prompts, and background jobs.
- Schedule runner that can dispatch scripts, Codex, Claude, Orgo.io desktops, Composio actions, AgentMail inbox handlers, Granola sync jobs, or future worker runtimes.
- Connected source registry for Slack, Jira, Linear, email, Notion, GitHub, Granola, AgentMail, filesystem, and customer-specific tools.
- Provider registry that lets each watch source choose Composio, MCP, connector, webhook, direct API, CLI, SDK, or polling without changing downstream routing.
- File-backed event envelopes, event ledger, and chain rules so one completed task can enqueue the next workflow or automation.
- Automation maturity model enforcement.
- Automation-to-project attachment.
- Routing-rule updates when projects, workflows, automations, or skills are added.
- Periodic doctor checks beyond structural validation.
- Explicit migration flow for installed files that must change.
- Notion control-plane sync.
- Customer OS factory profiles and packaging.
- LOS/losmon replacement validation using real workflows.
- Room-first/customer-first discovery for installs that should not inherit Genome's personal default domains.
- Task routing tables with `Task`, `Go To`, `Read First`, `Create Output In`, and `Optional Tools`.
- Room-level `CONTEXT.md` contracts with read/skip rules, output folders, tools/skills, and done criteria.
- Shared reference templates for naming conventions, tool indexes, style/output rules, and source priority.
- Factory template import policy covering what to copy, adapt, reference, or avoid from `/Users/genome/projects/factory`.
- First-class integration setup backlog for Orgo.io, Composio, AgentMail, Granola, and Notion-tracked connection state.

## Main Gap

The repo can create the rooms and documents. It does not yet keep those rooms alive as an operating system.

The repo also still reflects Genome's personal operating model too strongly. The factory and OS folder guide materials show that customer installs need a discovery flow that names rooms the way the operator thinks, then generates routing, context, references, skills, and output folders from those answers.

The next build sequence should make these actions work end to end:

```text
capture request
  -> route to domain/project/workflow
  -> build context
  -> dispatch Codex or Claude
  -> validate output
  -> close run
  -> promote durable learning
  -> update active state
```

The always-on loop should be:

```text
heartbeat due
  -> load runtime registry and approval policy
  -> load connected source and watch-source registry
  -> inspect due sources and normalize source events
  -> match trigger and chain rules
  -> enqueue work or approval with idempotency key
  -> choose execution target
  -> build minimal context pack
  -> run script/agent/tool
  -> record run evidence
  -> emit run closeout events
  -> update Notion control plane
  -> escalate if failed, stale, blocked, or approval-needed
```

The event-chaining loop should be:

```text
event observed or emitted
  -> write event envelope
  -> append ledger index
  -> match chain rules
  -> validate idempotency, approval, and max depth
  -> enqueue next workflow, automation, approval, or notification
  -> record processing result
  -> make the chain summarizable from files
```

For customer installs, the first loop should be:

```text
diagnose operator workflow
  -> define rooms and aliases
  -> generate map/router/context files
  -> attach skills and tools by room or stage
  -> test one workflow end to end
  -> remove rooms that do not match real work
```

## Acceptance Criteria

- A fresh agent can read this directory and know what to build next.
- The installed OS contains these plans under `shared_factory/05-knowledge/plans/`.
- Validation requires the plans index and future-ideas plan to exist in the installed runtime.
- Future feature work can be traced back to one plan file.

## Validation

- `pytest -q`
- `agentic-os docs update --root ~/agentic_os`
- `agentic-os validate --root ~/agentic_os`
