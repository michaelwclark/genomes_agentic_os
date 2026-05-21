# Feature Spec: Always-On Runtime, Heartbeats, Schedules, And Integrations

## Status

- Status: ready
- Owner: Genome
- Created: 2026-05-20
- Target OS layer: source package, installed runtime, customer OS installs, Notion control plane, and external execution targets

## Problem

Genome's Agentic OS should not only scaffold folders and instructions. It needs an always-on operating loop that can wake up, inspect state, dispatch the right worker, log evidence, update Notion, and escalate when human approval or repair is needed.

The OS should own the runtime contract:

- what should run,
- when it should run,
- what context it needs,
- what tool or worker should execute it,
- what approval gates apply,
- where results are logged,
- how Notion reflects status.

Execution targets can be swappable. Orgo.io, Composio, AgentMail, Granola, Codex, Claude, scripts, MCP tools, and future agent runtimes should plug into the OS rather than becoming the OS.

## Outcome

The installed OS has a heartbeat and schedule layer that can run recurring work safely and visibly. The first external setup backlog includes:

- Orgo.io desktop/computer-use setup,
- Composio integration for authenticated SaaS tools and triggers,
- AgentMail for dedicated agent inboxes,
- Granola sync for meeting notes, transcripts, and summaries,
- Notion tracking for integration state, heartbeat status, scheduled jobs, approvals, and runs.

## Source Research

Current public docs checked on 2026-05-20:

| System | Role In Agentic OS |
| --- | --- |
| Orgo.io | Persistent cloud desktops for computer-use agents. Use for browser/desktop tasks that should not run on the user's local machine. |
| Composio | Unified tool/auth/MCP layer for SaaS actions, OAuth connections, triggers, and remote workbench state. |
| AgentMail | API-first email inboxes for agents, including threads, replies, attachments, realtime events, custom domains, SDKs, and MCP. |
| Granola | API access to meeting notes, transcripts, AI summaries, folders, and workspace notes depending on API key scope. |

## Runtime Concepts

| Concept | Meaning |
| --- | --- |
| Heartbeat | A recurring check that proves a workflow, integration, or automation is alive. |
| Schedule | A planned recurring or one-time dispatch. |
| Run Queue | Pending, running, blocked, failed, approval-needed, and done work. |
| Execution Target | The worker/runtime that performs the action. |
| Integration Registry | Configured external systems, credentials state, health, and owner. |
| Approval Gate | Rule that pauses risky work before external, customer-visible, production, billing, legal, destructive, or credential-sensitive actions. |
| Evidence | Logs, outputs, links, screenshots, API responses, Notion records, or file artifacts proving what happened. |

## Proposed Commands

```bash
agentic-os runtime init --root ~/agentic_os
agentic-os heartbeat list --root ~/agentic_os
agentic-os heartbeat run <heartbeat_id> --root ~/agentic_os
agentic-os heartbeat doctor --root ~/agentic_os
agentic-os schedule create <schedule_id> --root ~/agentic_os
agentic-os schedule run-due --root ~/agentic_os
agentic-os integration list --root ~/agentic_os
agentic-os integration setup <integration_id> --root ~/agentic_os
agentic-os integration doctor <integration_id> --root ~/agentic_os
agentic-os notion track-runtime --root ~/agentic_os --dry-run
agentic-os notion track-runtime --root ~/agentic_os --apply
```

## Files To Add

```text
templates/runtime/heartbeat.yml
templates/runtime/schedule.yml
templates/runtime/execution-target.yml
templates/runtime/integration.yml
templates/runtime/run-queue-item.yml
templates/notion/runtime-tracking-database-spec.md
harness/commands/os-runtime-init.md
harness/commands/os-heartbeat.md
harness/commands/os-integration-setup.md
harness/skills/runtime-operator/SKILL.md
harness/skills/integration-setup/SKILL.md
```

Installed runtime targets:

```text
~/agentic_os/shared_factory/05-knowledge/templates/runtime/
~/agentic_os/shared_factory/05-knowledge/plans/15-always-on-runtime-heartbeats-schedules-and-integrations.md
~/agentic_os/shared_factory/06-runs-and-logs/runs/<timestamp>-shared_factory-runtime-setup/
```

Future runtime state files:

```text
~/agentic_os/shared_factory/00-control-plane/runtime-registry.yml
~/agentic_os/shared_factory/00-control-plane/integration-registry.yml
~/agentic_os/shared_factory/00-control-plane/run-queue.yml
~/agentic_os/shared_factory/06-runs-and-logs/heartbeats/
```

## Execution Target Shape

```yaml
id: orgo_desktop
display_name: Orgo Desktop
type: computer_use_desktop
owner: Genome
status: planned
use_for:
  - browser workflows
  - desktop tasks requiring isolated environment
approval_required_for:
  - customer_visible_output
  - production_changes
  - credential_changes
credentials:
  env_vars:
    - ORGO_API_KEY
health_check:
  command: agentic-os integration doctor orgo_desktop
notion_tracking:
  database: Integrations
```

## Integration Setup Backlog

| Integration | Initial Setup Tasks | Health Check | Notion Tracking |
| --- | --- | --- | --- |
| Orgo.io | Create account/project, provision first desktop, decide per-domain or per-customer workspace model, store API key, define screenshot/log retention, test browser session. | Provision desktop, launch session, confirm file persistence, run one browser/computer-use smoke test. | Integration row, execution target row, heartbeat row, run records. |
| Composio | Create project, choose Connect/MCP vs SDK path, add MCP URL where needed, connect first apps, define user/session mapping, document OAuth approval flow. | Search tools, generate connect link, complete one OAuth, execute safe read-only tool, verify logs. | Integration row, connected account state, trigger candidates, approval gates. |
| AgentMail | Create account, choose domain strategy, create first agent inbox, define inbound webhook or polling, define outbound approval policy, test threading. | Send/receive test, webhook/event receipt, thread lookup, attachment handling, outbound draft gate. | Integration row, inbox inventory, inbound heartbeat, approval-needed outbound runs. |
| Granola | Create API key, choose personal vs enterprise scope, store key, define sync window, map notes to OS rooms/projects, handle transcript sensitivity. | List recent notes, fetch one note with transcript, create local run log, create or update Notion meeting item. | Integration row, meeting note sync heartbeat, source records, work items extracted from meetings. |
| Notion Runtime Tracking | Create or update `Agentic OS` control-plane databases for integrations, heartbeats, schedules, run queue, approvals, and runs. | Dry-run sync, apply test rows, verify IDs recorded locally. | This is the tracking layer for all runtime setup. |

## Notion Tracking Requirements

Add or extend these Notion control-plane objects under the verified `Agentic OS` page in Genome's Notion:

| Object | Purpose |
| --- | --- |
| Integrations | External systems, credentials state, owner, scope, health, docs, setup status. |
| Execution Targets | Workers/runtimes such as Codex, Claude, scripts, Orgo, Composio, AgentMail, Granola sync. |
| Heartbeats | Recurring checks, expected cadence, last success, last failure, next due, escalation rule. |
| Schedules | Recurring jobs and one-time future dispatches. |
| Run Queue | Pending/running/blocked/failed/approval-needed/done queue. |
| Approvals | Human review queue for risky actions. |
| Runs | Execution history and evidence links. |

Before any Notion write:

1. Use Notion MCP first.
2. If MCP is unavailable, use the Notion connector.
3. If both fail, use `GENOMES_NOTION_PAT` or `GENOMES_NOTION_CONNECTOR` from `.zshenv` for direct API access.
4. Verify the target is Genome's Notion.
5. Do not write to Michael Clark's personal Notion or any fallback workspace.

## Heartbeat Shape

```yaml
id: granola_recent_notes_sync
display_name: Granola recent notes sync
domain: shared_factory
enabled: false
cadence: every_2_hours
execution_target: script
integration: granola
context:
  read_first:
    - shared_factory/00-control-plane/integration-registry.yml
    - shared_factory/05-knowledge/source-map.md
approval_policy:
  external_write: false
  customer_visible_output: false
  sensitive_transcript_handling: true
success_means:
  - recent notes checked
  - run log written
  - Notion tracking updated or blocked with reason
failure_escalation:
  after_consecutive_failures: 2
  notify: Genome
```

## Schedule Shape

```yaml
id: daily_agentic_os_doctor
display_name: Daily Agentic OS doctor
enabled: true
cadence: daily
timezone: America/Chicago
execution_target: script
command: agentic-os validate --root ~/agentic_os
outputs:
  - shared_factory/06-runs-and-logs/runs/
notion_update:
  object: Heartbeats
  status_field: Last Status
```

## Implementation Steps

1. Add runtime templates and command prompts.
2. Add integration registry schema and validation.
3. Add heartbeat and schedule schema validation.
4. Add `run-due` execution loop with dry-run mode first.
5. Add run queue states and file-backed state transitions.
6. Add integration setup commands for Orgo.io, Composio, AgentMail, Granola, and Notion runtime tracking.
7. Add Notion runtime tracking dry-run and apply flows.
8. Add doctor checks for missing credentials, stale heartbeats, failed schedules, untracked integrations, and Notion drift.
9. Add a real pilot: Granola sync or AgentMail inbound heartbeat, because both are narrow and measurable.
10. Add a second pilot using Orgo.io or Composio only after the file-backed runtime loop is observable.

## Risk Rules

- Default all new integrations to `enabled: false`.
- First run for each integration must be read-only or dry-run.
- Outbound email starts as draft-only until approval policy is proven.
- Meeting transcripts are sensitive; do not sync full transcripts to Notion by default.
- Desktop/browser agents must run in isolated Orgo workspaces or other approved sandboxes, not on the user's primary machine.
- Composio sessions must be scoped per user/customer; never use `default` for production.
- Notion writes require verified Genome's Notion or explicitly approved customer workspace.

## Acceptance Criteria

- Plans and templates are installed under `shared_factory/05-knowledge/`.
- Runtime registry can represent at least Codex, Claude, script, Orgo.io, Composio, AgentMail, Granola, and Notion.
- A heartbeat can be defined, validated, run in dry-run mode, and logged.
- Notion tracking can create or update integration/heartbeat/schedule/run records after workspace verification.
- Orgo.io, Composio, AgentMail, and Granola each have setup tasks, health checks, approval gates, and Notion tracking fields.
- The first real heartbeat pilot runs without relying on chat history.

## Validation

- `pytest -q`
- `agentic-os docs update --root ~/agentic_os`
- `agentic-os validate --root ~/agentic_os`
- Dry-run Notion runtime tracking before any apply.
- Run one read-only integration health check and capture a run log.
