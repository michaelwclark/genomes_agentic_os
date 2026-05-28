# Plan 15 Orchestration Prompt

Use this prompt to start the Plan 15 orchestration run.

## Source Spec

- Spec: `/Users/genome/projects/genomes_agentic_os/PLANS/15-always-on-runtime-heartbeats-schedules-and-integrations.md`
- Companion prompt: `/Users/genome/projects/genomes_agentic_os/PLANS/15-always-on-runtime-heartbeats-schedules-and-integrations.orchestration.md`

## Current Anchors

- Runtime implementation: `/Users/genome/projects/genomes_agentic_os/src/genomes_agentic_os/runtime_ops.py`
- CLI surface: `/Users/genome/projects/genomes_agentic_os/src/genomes_agentic_os/cli.py`
- Runtime templates: `/Users/genome/projects/genomes_agentic_os/templates/runtime/`
- Runtime commands: `/Users/genome/projects/genomes_agentic_os/harness/commands/os-runtime-init.md`, `/Users/genome/projects/genomes_agentic_os/harness/commands/os-heartbeat.md`, `/Users/genome/projects/genomes_agentic_os/harness/commands/os-integration-setup.md`
- Runtime skills: `/Users/genome/projects/genomes_agentic_os/harness/skills/runtime-operator/SKILL.md`, `/Users/genome/projects/genomes_agentic_os/harness/skills/integration-setup/SKILL.md`
- Test coverage: `/Users/genome/projects/genomes_agentic_os/tests/test_cli_scaffold.py`

## Orchestration Prompt

```text
/orchestrate

Work in /Users/genome/projects/genomes_agentic_os.

Goal: finish Plan 15, "Always-On Runtime, Heartbeats, Schedules, And Integrations", by turning the existing file-backed runtime surface into a dependable, observable always-on layer for Genome's Agentic OS.

Primary spec:
/Users/genome/projects/genomes_agentic_os/PLANS/15-always-on-runtime-heartbeats-schedules-and-integrations.md

Important repo context:
- This repo is the source package, not the live installed OS.
- The live install target is ~/agentic_os.
- Preserve the Plan 21 harness context contract: every installed layer should carry AGENTS.md, CLAUDE.md as @AGENTS.md, ROUTER.md, CONTEXT.md, RULES.md, TOOLS.md, MEMORY.md, and layer config where applicable.
- The current worktree is dirty. Do not revert user changes or unrelated edits. Work with concurrent changes.
- Current HEAD observed before orchestration: 0fe630e4fcc39e331c2fb7fbb9c970e7917eed59.

Start with read-only investigations. Do not begin implementation workers until the investigation outputs identify the smallest safe first build slice.

Baseline first:
1. Capture `git status --short` and `git rev-parse HEAD`.
2. Run `uv run pytest -q` if the environment is ready. If blocked, record the exact blocker and continue with read-only investigation.
3. Inspect the Plan 15 spec, runtime_ops.py, cli.py, templates/runtime, harness runtime commands/skills, and tests/test_cli_scaffold.py.

Investigation requirements:
1. Runtime contract audit: compare Plan 15 acceptance criteria to current implementation and tests. Produce a done/partial/missing matrix.
2. Scheduler design: determine the minimum durable due-calculation model for cadence, timezone, next_due_at, last_queued_at, idempotency, stale/disabled schedules, and queue writes.
3. Runner and approval model: define how schedule/heartbeat queue items become run records without unsafe external effects, how execution targets are selected, and how approval gates block risky work.
4. Integration and Notion tracking: define the guarded tracking contract for Orgo.io, Composio, AgentMail, Granola, and Genome's Notion without writing to Notion until workspace verification passes.

Expected implementation strategy after investigation:
- Prefer file-backed state first.
- Keep external integrations disabled by default.
- Preserve dry-run/apply semantics.
- Make the always-on loop callable by local shell, Codex automation, launchd/systemd, or a future remote runner.
- Add focused tests before broad docs expansion.
- Update templates, docs, and installed validation only where needed for Plan 15 acceptance.

Likely first build slice:
Implement a production-grade local scheduler loop that can:
- parse runtime-registry.yml schedules and heartbeats,
- compute due items using timezone-aware timestamps,
- append idempotent run_queue.yml entries,
- write structured run logs,
- respect enabled=false and approval gates,
- expose clear `runtime doctor`, `schedule run-due`, and `heartbeat run` results,
- remain safe in dry-run mode.

Worker rules:
- You are not alone in this codebase. Other agents or the user may be editing files concurrently.
- Do not revert edits made by others.
- Adjust your implementation to accommodate concurrent changes.
- Edit files directly when assigned an implementation slice.
- List every changed file in your return.
- Include exact commands run and exact test results.

Verification target:
- `uv run pytest -q`
- `agentic-os runtime init --root <temp root>`
- `agentic-os schedule run-due --root <temp root> --dry-run`
- `agentic-os heartbeat run granola_recent_notes_sync --root <temp root> --dry-run`
- `agentic-os runtime doctor --root <temp root>`
- `agentic-os docs update --root ~/agentic_os` only after source-package tests pass and the user approves touching the live install.

Return first:
1. Investigation summary.
2. Recommended build slices.
3. Files each slice should own.
4. Risks or user approvals needed.
5. The first implementation slice ready for worker dispatch.
```

## Investigation Prompts

### 1. Runtime Contract Audit

```text
Read-only investigation in /Users/genome/projects/genomes_agentic_os.

Compare Plan 15 acceptance criteria against the current source package.

Inspect:
- PLANS/15-always-on-runtime-heartbeats-schedules-and-integrations.md
- src/genomes_agentic_os/runtime_ops.py
- src/genomes_agentic_os/cli.py
- templates/runtime/
- harness/commands/os-runtime-init.md
- harness/commands/os-heartbeat.md
- harness/commands/os-integration-setup.md
- harness/skills/runtime-operator/SKILL.md
- harness/skills/integration-setup/SKILL.md
- tests/test_cli_scaffold.py

Return:
- Done, partial, and missing matrix.
- Current commands and schemas that already exist.
- Acceptance criteria that are not actually proven by tests.
- The smallest safe implementation slice.

Do not edit files.
```

### 2. Scheduler And Queue Semantics

```text
Read-only investigation in /Users/genome/projects/genomes_agentic_os.

Design the minimal durable scheduler semantics for Plan 15.

Focus on:
- cadence parsing and supported cadence vocabulary,
- timezone handling,
- next_due_at and last_queued_at fields,
- idempotency keys for schedule and heartbeat queue entries,
- disabled schedule behavior,
- dry-run versus apply behavior,
- run_queue.yml append/update rules,
- doctor findings for stale, invalid, or impossible schedules.

Return:
- Proposed schema additions.
- Required code changes.
- Required tests.
- Edge cases to cover.

Do not edit files.
```

### 3. Runner, Execution Targets, And Approval Gates

```text
Read-only investigation in /Users/genome/projects/genomes_agentic_os.

Define how Plan 15 should move from queued work to guarded execution without unsafe external side effects.

Focus on:
- execution target records for script, Codex, Claude, Orgo.io, Composio, AgentMail, Granola, and Notion,
- approval_state values,
- blocked versus approval-needed versus queued versus running versus done versus failed,
- run log fields,
- how heartbeat_run and schedule_run_due should write evidence,
- whether a separate `runtime run-next` or `runtime dispatch` command is needed,
- how to keep provider-backed integrations disabled and dry-run-first.

Return:
- Recommended state machine.
- Minimal command surface.
- Files to change.
- Tests that prove safety.

Do not edit files.
```

### 4. Integration And Notion Tracking Contract

```text
Read-only investigation in /Users/genome/projects/genomes_agentic_os.

Define the Plan 15 integration and Notion tracking layer.

Focus on:
- Orgo.io, Composio, AgentMail, Granola, and Genome's Notion setup tasks,
- credential reference shape without storing secrets,
- health check contract,
- Notion workspace verification requirements,
- local manifest files that record verified Notion database IDs,
- dry-run tracking plan versus apply,
- how runtime tracking relates to existing connected-system, watch-source, event, and chain templates.

Return:
- Proposed tracking schema.
- Required validation rules.
- Required docs/templates.
- Tests and smoke commands.
- Any user approvals needed before live Notion writes.

Do not edit files.
```

## Initial Findings

- The Plan 15 spec is ready and already names the runtime command surface, templates, integration backlog, risk rules, and acceptance criteria.
- The repo already contains a partial file-backed runtime in `runtime_ops.py` with `runtime_init`, `heartbeat_run`, `schedule_create`, `schedule_run_due`, integration setup/doctor, and Notion runtime tracking plan/apply helpers.
- The current tests cover runtime init, dry-run heartbeat logs, schedule queueing, integration setup/doctor, watch-source polling, event graph processing, dead-letter handling, and filesystem-backed Notion sync.
- The likely gap is not "create the first files"; it is production-grade runtime semantics: due calculation, idempotency, state transitions, approval gating, dispatch boundaries, and live-install validation.
