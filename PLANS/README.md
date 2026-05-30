# Agentic OS Plans

This directory is the build backlog for turning Genome's Agentic OS from a scaffold into a running operating system for Codex, Claude, customer OS installs, and guarded automations.

These files are source-package plans. On install or `docs update`, they are copied into the installed runtime at:

```text
~/agentic_os/shared_factory/05-knowledge/plans/
```

That installed copy gives future agents a durable place to find what should be built next without searching chat history.

## Current Position

The repo has a working V1 scaffold:

- `agentic-os init`
- `agentic-os domain create`
- `agentic-os workflow create`
- `agentic-os automation create`
- `agentic-os run-log create`
- `agentic-os docs install`
- `agentic-os docs update`
- `agentic-os validate`

The missing work is the operating loop: projects, cwd-aware routing, automatic context packs, workflow readiness, run closeout, always-on heartbeats, schedule runners, connected source watchers, event chaining, doctor repairs, Notion sync, customer OS packaging, and LOS/losmon replacement validation.

## Plan Index

| File | Purpose | Priority |
| --- | --- | --- |
| `00-current-state-and-gap-map.md` | Snapshot of what exists and what does not. | P0 |
| `01-project-create-and-active-work.md` | Add real project scaffolding and active-work updates. | P0 |
| `02-routing-and-context-builder.md` | Make agents route and load context automatically. | P0 |
| `03-workflow-readiness-and-run-closeout.md` | Make workflows dispatchable and sessions close cleanly. | P0 |
| `04-automation-maturity-and-reconfiguration.md` | Turn proven workflows into safe, reconfigurable automations. | P1 |
| `05-customer-os-factory.md` | Create repeatable customer OS packages from the common source. | P1 |
| `06-notion-control-plane-sync.md` | Sync filesystem source of truth into Genome's Notion or approved customer Notion. | P1 |
| `07-doctor-validation-and-migrations.md` | Detect drift and handle explicit migrations safely. | P1 |
| `08-losmon-replacement-validation.md` | Validate Agentic OS against the current losmon operating surface. | P1 |
| `09-future-ideas-intake.md` | Give the installed OS a durable place for future plans and ideas. | P0 |
| `10-notion-control-plane-bootstrap.md` | Create the first usable top-level Agentic OS cockpit in Notion. | P0 |
| `11-room-first-installer-and-routing.md` | Make customer installs discover rooms, aliases, routing tables, and context contracts instead of inheriting Genome defaults. | P0 |
| `12-factory-template-import-backlog.md` | Decide which factory templates, constraints, and builder patterns to import into the product source. | P0 |
| `13-reference-and-skill-index-layer.md` | Add shared reference files for naming, tools, style/output rules, source priority, and contextual skill routing. | P1 |
| `14-client-automation-and-control-plane-playbooks.md` | Turn factory customer-discovery, control-plane, and automation-fit patterns into reusable OS playbooks. | P1 |
| `15-always-on-runtime-heartbeats-schedules-and-integrations.md` | Add heartbeats, schedule runners, execution targets, Orgo.io setup, Composio, AgentMail, Granola, and Notion tracking. | P0 |
| `16-connected-source-watch-registry.md` | Register connected systems and watch sources across Composio, MCPs, connectors, direct APIs, webhooks, and polling. | P0 |
| `17-event-graph-and-chained-automations.md` | Add file-backed event envelopes, event ledger, chain rules, and chained workflow dispatch. | P0 |
| `18-visible-capability-registry.md` | Make installed OS capabilities visible through top-level registries and inventory files. | P0 |
| `19-update-channel-and-customer-fleet.md` | Define future update channels, status reporting, phone-home policy, and customer fleet safety. | P1 |
| `20-operator-pushed-customer-updates-and-backups.md` | Build the simpler V1 customer update path with customer-generated SSH keys, Genome billing checks, GitHub update pulls, backup pushes, and operator-pushed releases. | P0 |
| `21-harness-context-contract-and-config-toml.md` | Normalize Codex/Claude context loading around `config.toml`, `AGENTS.md`, `CLAUDE.md`, `ROUTER.md`, `CONTEXT.md`, `RULES.md`, and `TOOLS.md`. | P0 |
| `22-project-work-lifecycle-and-conversation-auto-logging.md` | Promote feature-style markdown tracking into every project, configure idea-to-spec-to-validation workflows, and add redacted conversation/tool-call logging. | P0 |

## Status Vocabulary

- `draft`: direction is captured, but implementation details need review.
- `ready`: enough detail exists for an agent to implement.
- `building`: active implementation is underway.
- `validating`: implementation exists and needs real usage evidence.
- `done`: shipped, installed, validated, and documented.

## Writing Rule

Every plan should name concrete files, commands, state changes, and validation. If a plan cannot be tested from a fresh install and from `~/agentic_os`, it is not specific enough yet.
