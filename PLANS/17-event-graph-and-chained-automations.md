# Feature Spec: Event Graph And Chained Automations

## Status

- Status: ready
- Owner: Genome
- Created: 2026-05-20
- Target OS layer: source package, installed runtime, customer OS installs, automation runtime, and active state plane

## Problem

Genome's Agentic OS can describe workflows, automations, run logs, heartbeats, schedules, and connected watch sources, but it does not yet make event chaining a first-class operating primitive.

The real leverage comes when completion of one thing can reliably start the next thing:

- once a feature is merged, update docs and create release notes,
- once an email is sent, insert a row into CRM,
- once a meeting transcript arrives, analyze it and create follow-up tasks,
- once a Jira issue moves to QA, generate a test checklist,
- once a run closes with `needs_approval`, create an approval item,
- once an approval is granted, dispatch the next guarded action.

If this chaining lives only in agent memory or ad hoc scripts, the OS will become hard to inspect and hard to trust. The chain needs to be file-backed, self-documenting, replayable, and summarized from durable evidence.

## Outcome

The installed OS has a file-backed event graph:

- source changes, run closeouts, approvals, external actions, and agent outputs emit normalized events,
- event records are written as inspectable files,
- chain rules match events and enqueue follow-up workflows or automations,
- every chain transition has an idempotency key, evidence link, and route/context/dispatch contract,
- agents can analyze the event ledger at any point to summarize what happened and what should happen next,
- higher-volume installs can migrate the same event model into a database-backed active state plane without changing the markdown contracts.

## Core Principle

Watchers detect. Routers decide. Agents execute. Run closeout emits events. Chain rules enqueue the next unit of work.

Agents should not invisibly call the next agent. They should close the current run with evidence. The deterministic event processor then decides whether another workflow, automation, approval, or notification should be queued.

## Runtime Concepts

| Concept | Meaning |
| --- | --- |
| Event Envelope | Normalized record of something that happened. |
| Event Ledger | Append-only file-backed history of observed and emitted events. |
| Event Graph | Rules that map events to downstream actions. |
| Chain Rule | Deterministic rule that matches one or more events and enqueues follow-up work. |
| Correlation ID | Identifier connecting source event, run, approval, PR, email, CRM row, and follow-up events. |
| Idempotency Key | Key that prevents duplicate processing of the same event or chain step. |
| Dead Letter | Event that failed processing and needs manual review or replay. |
| Replay | Re-processing selected events from the ledger after rules or adapters are fixed. |

## Proposed Commands

```bash
agentic-os event append --type <event_type> --source <source_ref> --root ~/agentic_os
agentic-os event list --root ~/agentic_os
agentic-os event process-due --root ~/agentic_os --dry-run
agentic-os event process-due --root ~/agentic_os --apply
agentic-os event replay <event_id> --root ~/agentic_os --dry-run
agentic-os chain list --root ~/agentic_os
agentic-os chain test <chain_rule_id> --event <event_file> --root ~/agentic_os
agentic-os chain doctor --root ~/agentic_os
agentic-os run-log close <domain> <run-id> --status done --emit-events --root ~/agentic_os
```

## Files To Add

```text
templates/runtime/event-envelope.yml
templates/runtime/event-ledger-index.md
templates/runtime/chain-rule.yml
templates/runtime/event-processing-result.yml
templates/runtime/dead-letter-event.yml
harness/commands/os-event.md
harness/commands/os-chain.md
harness/skills/event-graph-operator/SKILL.md
```

Installed runtime targets:

```text
~/agentic_os/shared_factory/00-control-plane/event-graph.yml
~/agentic_os/shared_factory/00-control-plane/chain-rules.yml
~/agentic_os/shared_factory/00-control-plane/event-cursors.yml
~/agentic_os/shared_factory/06-runs-and-logs/events/
~/agentic_os/shared_factory/06-runs-and-logs/events/dead-letter/
~/agentic_os/shared_factory/06-runs-and-logs/runs/<run-id>/emitted-events/
```

## Event Envelope Shape

```yaml
id: evt_20260520_001
type: github.pull_request.merged
schema_version: 1
occurred_at: 2026-05-20T18:10:00-05:00
observed_at: 2026-05-20T18:10:30-05:00
source:
  system: github
  provider: github_mcp
  watch_source_id: genomes_agentic_os_prs
actor:
  type: user
  display_name: Genome
object:
  type: pull_request
  external_id: "123"
  title: Add runtime watcher registry
correlation:
  correlation_id: corr_agentic_os_runtime_123
  parent_event_id:
  run_id:
idempotency_key: "github:genomes_agentic_os:pr:123:merged"
summary: PR 123 merged into main.
payload_ref:
  type: link
  href: https://github.com/example/genomes_agentic_os/pull/123
privacy:
  contains_secret: false
  contains_customer_data: false
links:
  run_log:
  notion_record:
  source_url: https://github.com/example/genomes_agentic_os/pull/123
```

## Chain Rule Shape

```yaml
id: feature_merged_to_docs_update
display_name: Feature merged creates docs follow-up
enabled: false
when:
  event_type: github.pull_request.merged
  filters:
    repo: genomes_agentic_os
then:
  enqueue:
    work_type: documentation_update
    route_to: shared_factory
    workflow: docs_update_after_merge
    context_profile: merged_feature_docs
    execution_target: codex
    maturity: prepare
    idempotency_key: "{event.id}:docs_update"
approval:
  required: false
limits:
  max_chain_depth: 3
  cooldown: 10_minutes
outputs:
  run_queue: shared_factory/00-control-plane/run-queue.yml
  event_log: shared_factory/06-runs-and-logs/events/
```

## First Chain Examples

| Chain | Source Event | Follow-Up |
| --- | --- | --- |
| Feature merged to docs | `github.pull_request.merged` | Queue docs update, release note draft, and plan status review. |
| Email sent to CRM | `email.message.sent` | Queue CRM row insert or update with approval gates for customer-visible notes. |
| Meeting transcript to tasks | `granola.note.created` | Analyze transcript, extract decisions/actions, create Notion work items, optionally create Jira/Linear tasks. |
| Notion card to worktree | `os.work_item.started` | Create worktree, build context pack, dispatch Codex or Claude. |
| Run needs approval | `os.run.closed.needs_approval` | Create approval item and block downstream external write. |
| Approval granted | `os.approval.granted` | Dispatch the approved action with the original context and evidence links. |
| CI failed | `github.check_suite.failed` | Queue investigation workflow with PR, logs, and recent changes loaded. |

## Event Processing Loop

```text
source event or run closeout
  -> write event envelope
  -> append ledger index
  -> match chain rules
  -> validate idempotency and chain limits
  -> create run queue item or approval
  -> write processing result
  -> update control plane summary
  -> emit follow-up event if needed
```

## Markdown And File-Backed Growth

The OS should grow by leaving evidence behind:

- source event files show what changed,
- run logs show what was done,
- chain processing results show why the next thing started,
- context packs show what the agent loaded,
- progress files show current state,
- decision records show why rules changed,
- summaries can be generated from the ledger without rereading chat.

The markdown/filesystem layer is the source of truth for specs, rules, context, and evidence. Notion can display the cockpit. A database or queue can later own high-volume mutable state, but it should preserve the same event envelope and chain rule contracts.

## Risk Rules

- No infinite chains. Every chain has max depth and idempotency.
- No invisible agent-to-agent handoff. Each transition must create an event, run queue item, approval, or run log.
- External writes require approval unless the automation is promoted to `execute_guarded`.
- Full transcripts, secrets, and sensitive payloads should be referenced, not copied into event envelopes.
- Chain rules default to `enabled: false`.
- Replay must be dry-run first.
- Dead-letter events must include failure reason, attempted rule, and next action.
- Multiple processors require a database or queue-backed lock before concurrent processing is allowed.

## Relationship To Other Plans

- Plan 03 adds run closeout and final status. This plan extends closeout so runs can emit events.
- Plan 15 adds heartbeats, schedules, run queue, integrations, and execution targets.
- Plan 16 adds connected systems and watch sources that produce source events.
- Plan 04 governs automation maturity and prevents unsafe promotion.
- Plan 06 syncs human-facing state into Notion after events and chains are processed.
- Plan 09 can capture future chain ideas before they become enabled rules.

## Acceptance Criteria

- Event envelopes can be created from source watchers and run closeout.
- Event ledger files are append-only, inspectable, and linked to run logs where applicable.
- Chain rules can match a test event and produce a dry-run queue item.
- Chain processing records why a follow-up was or was not enqueued.
- Duplicate events do not create duplicate work.
- Dead-letter handling records failed events and next action.
- Initial chain examples cover feature merge docs, email to CRM, transcript to tasks, Notion card to worktree, approval grant, and CI failure.
- A fresh agent can summarize the last N events and identify pending follow-up work without chat history.

## Validation

- Unit tests for event envelope parsing and schema validation.
- Unit tests for chain matching, idempotency, max depth, dry-run queue output, and dead-letter records.
- Manual dry-run with one Notion work item event and one synthetic PR-merged event.
- `agentic-os validate --root ~/agentic_os`

## Rollout Notes

Install templates and command docs additively under `shared_factory/05-knowledge/`. Runtime event folders and rule files should be created only when missing. Existing event ledger files are append-only and must never be overwritten by `docs update`.
