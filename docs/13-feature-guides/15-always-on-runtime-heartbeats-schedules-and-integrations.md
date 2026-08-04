# 15 Always On Runtime Heartbeats Schedules And Integrations

## Table Of Contents

- [Purpose](#purpose)
- [Runtime Registries](#runtime-registries)
- [Commands](#commands)
- [Heartbeats](#heartbeats)
- [Schedules](#schedules)
- [Integrations](#integrations)
- [Notion Runtime Tracking](#notion-runtime-tracking)
- [Validation](#validation)
- [Source Artifacts](#source-artifacts)

## Purpose

The always-on runtime layer gives an installed Agentic OS file-backed state for
heartbeats, schedules, execution targets, run queues, integrations, and guarded
runtime tracking.

This layer records observable local runtime intent before any external provider
execution. Provider actions should remain dry-run or explicit setup records
until credentials, approval gates, and workspace identity are verified.

## Runtime Registries

Runtime state is stored inside the installed OS root. The key surfaces are:

- execution targets
- integrations
- heartbeats
- schedules
- run queue items
- heartbeat logs
- integration setup records
- guarded Notion runtime tracking manifest

Templates install under:

```text
shared_factory/05-knowledge/templates/runtime/
```

Runtime command prompts and skills install under:

```text
shared_factory/05-knowledge/commands/
shared_factory/05-knowledge/skills/
```

## Commands

Initialize and inspect runtime state:

```bash
agentic-os runtime init --root ~/agentic_os
agentic-os runtime doctor --root ~/agentic_os
```

List and dry-run heartbeats:

```bash
agentic-os heartbeat list --root ~/agentic_os
agentic-os heartbeat run granola_recent_notes_sync --root ~/agentic_os --dry-run
agentic-os heartbeat doctor --root ~/agentic_os
```

Create and queue schedules:

```bash
agentic-os schedule create smoke_runtime_doctor --root ~/agentic_os --target runtime_doctor
agentic-os schedule run-due --root ~/agentic_os --dry-run
```

The daily self-improvement schedule should target the morning report command
when the operator wants autonomous filesystem repair plus a Notion reading
surface:

```bash
agentic-os self-improvement morning-report --root ~/agentic_os --apply
```

Runtime dispatch supports this command through the local script target. The
command writes dated filesystem reports and logs under
`harness/shared_factory/06-runs-and-logs/self-improvement/morning-reports/` and
projects to `Genome's Agentic OS / Self Improvement Reports` only after Notion
workspace verification.

Inspect and prepare integrations:

```bash
agentic-os integration list --root ~/agentic_os
agentic-os integration setup granola --root ~/agentic_os --dry-run
agentic-os integration doctor --root ~/agentic_os
```

## Heartbeats

Heartbeats are named recurring checks or syncs. They should write local evidence
before any external effect is trusted.

Dry-run heartbeat execution is the default verification path for new runtime
work. It should leave a local heartbeat log that can be inspected before the
heartbeat is promoted into a real recurring automation.

## Schedules

Schedules represent due work without executing external effects directly.

`schedule run-due` should add local run queue items. The queue is the handoff
surface for later execution, review, or automation qualification.

For high-frequency schedules where older queued work is safely superseded by
the newest item, add:

```yaml
supervisor:
  priority_dispatch: true
  dispatch_policy: latest_queued
  supersede_older_queued: true
```

The supervisor uses that block to bypass stale generic backlog for the schedule:
it dispatches the newest queued item and marks older queued duplicates skipped.
This is appropriate for control-plane watchers such as automation control ticks
and status projections; it is not appropriate for schedules where every missed
interval must execute.

The queue writer batches `schedule run-due` changes into one load and one write
per tick. Keep runtime queue files out of source control; committed
`RUN_STATE.json` or generated run queues are stale local state, not repo
artifacts.

## Integrations

Integration setup records expected credentials, approval gates, health checks,
and setup tasks.

Supported registry concepts include providers such as Orgo.io, Composio,
AgentMail, Granola, and Notion, plus local targets for Codex, Claude, and
script execution.

Do not treat a listed integration as active until `integration doctor` and the
relevant approval gates pass.

## Validation

`agentic-os validate --root <root>` checks that runtime templates, commands,
skills, and plans are installed.

`agentic-os docs update --root <root>` restores missing managed runtime files
additively.

## Source Artifacts

- Historical Spec: migrated into the installed project's canonical `work-items/` lifecycle.
- Installed worklog spec: `worklogs/source-features/15-always-on-runtime-heartbeats-schedules-and-integrations/SPEC.md`
- Installed worklog QA: `worklogs/source-features/15-always-on-runtime-heartbeats-schedules-and-integrations/HOLDOUT_QA.md`
- Runtime implementation: `src/genomes_agentic_os/runtime_ops.py`
- Notion tracking: `src/genomes_agentic_os/notion_sync.py`
- Runtime templates: `templates/runtime/`
- Runtime commands: `harness/commands/os-runtime-init.md`, `harness/commands/os-heartbeat.md`, `harness/commands/os-integration-setup.md`
- Runtime skills: `harness/skills/runtime-operator/SKILL.md`, `harness/skills/integration-setup/SKILL.md`
- Test coverage: `tests/test_cli_scaffold.py`
