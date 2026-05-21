# Feature Spec: Connected Source Watch Registry

## Status

- Status: ready
- Owner: Genome
- Created: 2026-05-20
- Target OS layer: source package, installed runtime, customer OS installs, integration providers, and automation runtime

## Problem

The first watch source is likely the Agentic OS Notion Kanban, but the OS cannot be Notion-specific. Customer and personal operating systems need to watch any connected source: Slack channels, Jira boards, Linear teams, email inboxes, GitHub events, Notion databases, Granola notes, AgentMail inboxes, Composio triggers, MCP resources, direct APIs, webhooks, and file folders.

Without a provider-agnostic source registry, every watcher becomes one-off code. That makes customer OSes hard to configure, hard to audit, and hard to move between Composio, native MCPs, connectors, direct APIs, and webhooks.

## Outcome

The installed OS can declare:

- which systems are connected,
- which provider should be used to access each system,
- which exact sources should be watched,
- how each source should be polled, listened to, or queried,
- how cursors and idempotency keys are tracked,
- which trigger rules convert source changes into OS events or work items,
- which route/context/dispatch contract receives the resulting work.

Composio becomes a first-class provider, but not the only provider. The OS can prefer Composio SDK/MCP/CLI for a source while still falling back to native MCP, installed connector, direct API, webhook, or polling where appropriate.

## Runtime Concepts

| Concept | Meaning |
| --- | --- |
| Connected System | A system the OS can access, such as Slack, Jira, Linear, Gmail, Notion, GitHub, Granola, AgentMail, or HubSpot. |
| Provider | The access path for a system: Composio, MCP, connector, direct API, webhook, CLI, SDK, or script. |
| Watch Source | One specific source to inspect, such as a Slack channel, Jira JQL query, Linear team, email search, Notion database, GitHub repo, or Granola folder. |
| Watch Method | Poll, webhook, provider trigger, stream, file watch, or manual replay. |
| Cursor | Last seen timestamp, event ID, page token, issue update time, message timestamp, or other resume marker. |
| Source Event | Normalized record that says something changed in a watched source. |
| Trigger Rule | Deterministic filter that decides whether a source event becomes a queued OS task, approval, chain event, or ignored observation. |

## Proposed Commands

```bash
agentic-os connected-system list --root ~/agentic_os
agentic-os connected-system doctor <system_id> --root ~/agentic_os
agentic-os watch-source list --root ~/agentic_os
agentic-os watch-source create <source_id> --root ~/agentic_os
agentic-os watch-source doctor <source_id> --root ~/agentic_os
agentic-os watch-source poll <source_id> --root ~/agentic_os --dry-run
agentic-os watch-source run-due --root ~/agentic_os --dry-run
agentic-os watch-source run-due --root ~/agentic_os --apply
```

## Files To Add

```text
templates/runtime/connected-system.yml
templates/runtime/source-provider.yml
templates/runtime/watch-source.yml
templates/runtime/watch-cursor.yml
templates/runtime/source-event.yml
templates/runtime/trigger-rule.yml
harness/commands/os-watch-source.md
harness/skills/source-watcher/SKILL.md
```

Installed runtime targets:

```text
~/agentic_os/shared_factory/00-control-plane/connected-systems.yml
~/agentic_os/shared_factory/00-control-plane/source-providers.yml
~/agentic_os/shared_factory/00-control-plane/watch-sources.yml
~/agentic_os/shared_factory/00-control-plane/watch-cursors.yml
~/agentic_os/shared_factory/05-knowledge/templates/runtime/
~/agentic_os/shared_factory/06-runs-and-logs/source-events/
```

## Connected System Shape

```yaml
id: slack_genome
display_name: Genome Slack
system: slack
status: planned
owner: Genome
provider_priority:
  - composio
  - slack_mcp
  - slack_connector
  - direct_api
credential_refs:
  env_vars:
    - COMPOSIO_API_KEY
  account_aliases:
    - genome_slack
workspace_verification:
  required: true
  expected_workspace: Genome
permissions:
  read:
    - channels:history
  write:
    - chat:write
approval_required_for:
  - external_message_send
  - customer_visible_output
health_check:
  command: agentic-os connected-system doctor slack_genome
```

## Watch Source Shape

```yaml
id: agentic_os_kanban_in_progress
display_name: Agentic OS Kanban In Progress
connected_system: notion_genome
source_type: notion_database
external_ref:
  database_id: 366683b4-8dab-81a1-ab5f-c73e7e1f5c60
watch_method: poll
cadence: every_1_minute
enabled: false
cursor:
  type: last_edited_time
  state_ref: shared_factory/00-control-plane/watch-cursors.yml
dedupe:
  idempotency_key: "{source_type}:{database_id}:{page_id}:{last_edited_time}"
filters:
  status_field: Status
  status_values:
    - In Progress
trigger_rules:
  - agentic_os_work_item_started
route:
  command: agentic-os route
  context_command: agentic-os context build
  fallback_domain: shared_factory
outputs:
  source_events_dir: shared_factory/06-runs-and-logs/source-events/
  run_queue_ref: shared_factory/00-control-plane/run-queue.yml
```

## Provider Priority

Provider selection should be explicit and reviewable:

1. Use the configured provider for the source when it is healthy.
2. Prefer Composio when the source needs authenticated SaaS tool access, OAuth account mapping, provider triggers, or portable customer setup.
3. Prefer native MCP or installed connector when it is already reliable and workspace identity is verified.
4. Use direct API only when credentials and workspace boundaries are explicit.
5. Use polling before webhooks for the first version unless a provider trigger is already proven.

Provider adapters must normalize output into source events. Downstream routing should not care whether a Slack message came from Composio, Slack MCP, connector, webhook, or direct API.

## Trigger Rule Shape

```yaml
id: agentic_os_work_item_started
display_name: Agentic OS work item moved to In Progress
source_ids:
  - agentic_os_kanban_in_progress
when:
  event_type: notion.database_page.updated
  fields:
    Status: In Progress
only_if:
  fields_empty:
    - Active Run
    - Claimed By
then:
  emit_event:
    type: os.work_item.started
  enqueue:
    work_type: plan_implementation
    route_to: shared_factory
    context_profile: plan_file_and_runtime_state
    maturity: prepare
approval:
  required: false
```

## Source Examples

| Source | Watch Source | Trigger Candidate |
| --- | --- | --- |
| Slack | Channel or thread search | Mention, keyword, reaction, new customer escalation. |
| Jira | Board, project, filter, or JQL | Issue moved to ready, blocked, merged, failed QA. |
| Linear | Team inbox, project, label, or workflow state | Issue moved to In Progress or Done. |
| Email | Inbox, label, search query, or sender rule | Client reply, attachment received, outbound sent. |
| Notion | Database, page, or view | Status change, approval checkbox, new work item. |
| GitHub | Repo, PR, issue, check suite | PR merged, CI failed, review requested. |
| Granola | Recent notes or folder | New meeting transcript or summary available. |
| AgentMail | Agent inbox or thread | Inbound message or reply needed. |
| Filesystem | Folder or glob | New export, artifact, transcript, or handoff file. |

## Relationship To Other Plans

- Plan 15 owns the heartbeat, schedule, execution-target, integration, and run queue runtime.
- This plan adds provider-agnostic connected systems and watch sources.
- Plan 17 should consume normalized source events and support chained automations.
- Plan 06 reflects selected state into Notion, but Notion is not the authoritative event store.
- Plan 04 controls automation maturity and promotion rules.

## Risk Rules

- Do not store secrets in registries, run logs, source events, or Notion.
- New watch sources default to `enabled: false`.
- First execution mode is `observe` or `prepare`.
- Every source needs a cursor and idempotency key before it can run on a timer.
- Workspace/account identity must be verified before reads from customer systems.
- External writes require approval gates unless the automation is explicitly promoted to `execute_guarded`.
- High-volume sources should move to a database-backed active state plane before multiple agents process them concurrently.

## Acceptance Criteria

- A connected system can declare provider priority, credentials references, workspace verification, permissions, and health checks.
- A watch source can declare source type, external reference, cadence, cursor, dedupe key, filters, trigger rules, route, and output locations.
- `watch-source poll --dry-run` can inspect one configured source without mutating external systems.
- Provider adapters return normalized source events.
- Trigger rules can emit source events or enqueue work without chat history.
- Validation catches missing cursor, missing idempotency key, missing provider, unsafe enabled state, and missing route.
- Notion, Slack, Jira, Linear, email, GitHub, Granola, AgentMail, and filesystem examples are documented.

## Validation

- Unit tests for parsing connected systems, watch sources, cursors, and trigger rules.
- Unit tests for provider selection and fallback ordering.
- Dry-run against a test Notion database and one read-only Composio-backed source.
- `agentic-os validate --root ~/agentic_os`

## Rollout Notes

Install templates and command docs additively under `shared_factory/05-knowledge/`. Runtime registries must be created only if missing. Existing customer or Genome watch-source files must not be overwritten by `docs update`.
