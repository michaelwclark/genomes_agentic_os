# Plan 16 Orchestration Prompt

Use this prompt to start the Plan 16 orchestration run after Plan 15 has established the runtime scheduler and run queue contract.

## Source Spec

- Spec: `/Users/genome/projects/genomes_agentic_os/PLANS/16-connected-source-watch-registry.md`
- Companion prompt: `/Users/genome/projects/genomes_agentic_os/PLANS/16-connected-source-watch-registry.orchestration.md`

## Current Anchors

- Source watcher implementation: `/Users/genome/projects/genomes_agentic_os/src/genomes_agentic_os/source_watch.py`
- CLI surface: `/Users/genome/projects/genomes_agentic_os/src/genomes_agentic_os/cli.py`
- Runtime templates: `/Users/genome/projects/genomes_agentic_os/templates/runtime/connected-system.yml`, `/Users/genome/projects/genomes_agentic_os/templates/runtime/source-provider.yml`, `/Users/genome/projects/genomes_agentic_os/templates/runtime/watch-source.yml`, `/Users/genome/projects/genomes_agentic_os/templates/runtime/watch-cursor.yml`, `/Users/genome/projects/genomes_agentic_os/templates/runtime/source-event.yml`, `/Users/genome/projects/genomes_agentic_os/templates/runtime/trigger-rule.yml`
- Runtime command: `/Users/genome/projects/genomes_agentic_os/harness/commands/os-watch-source.md`
- Runtime skill: `/Users/genome/projects/genomes_agentic_os/harness/skills/source-watcher/SKILL.md`
- Feature guide: `/Users/genome/projects/genomes_agentic_os/docs/13-feature-guides/16-connected-source-watch-registry.md`
- Test coverage: `/Users/genome/projects/genomes_agentic_os/tests/test_cli_scaffold.py`

## Orchestration Prompt

```text
/orchestrate

Work in /Users/genome/projects/genomes_agentic_os.

Goal: finish Plan 16, "Connected Source Watch Registry", by hardening the existing connected-system, source-provider, watch-source, cursor, trigger-rule, and normalized source-event layer.

Primary spec:
/Users/genome/projects/genomes_agentic_os/PLANS/16-connected-source-watch-registry.md

Prerequisite:
Plan 15 should own the runtime loop and run queue semantics. If Plan 15 is still in progress, make Plan 16 compatible with its file-backed queue shape and do not invent a second queue contract.

Important repo context:
- This repo is the source package, not the live installed OS.
- The live install target is ~/agentic_os.
- Preserve the Plan 21 harness context contract at every installed layer.
- The worktree may be dirty. Do not revert user changes or unrelated edits. Work with concurrent changes.

Start with read-only investigations. Do not begin implementation workers until the investigation outputs identify the smallest safe first build slice.

Baseline first:
1. Capture `git status --short` and `git rev-parse HEAD`.
2. Run `uv run pytest -q` if the environment is ready. If blocked, record the exact blocker and continue with read-only investigation.
3. Inspect the Plan 16 spec, source_watch.py, cli.py, templates/runtime watch files, harness watch command/skill, docs guide, and tests.

Investigation requirements:
1. Contract audit: compare Plan 16 acceptance criteria to current implementation and tests.
2. Provider model: inspect connected systems, providers, provider priority, credential refs, workspace verification, permission scopes, and health checks.
3. Watch-source safety: inspect cursor handling, dedupe/idempotency, unsafe enabled states, dry-run/apply behavior, route requirements, and output locations.
4. Event bridge: define exactly how watch polling produces normalized source events and how those events flow into Plan 17 without chat history.

Expected implementation strategy:
- Keep provider adapters read-only by default.
- Treat direct APIs, MCPs, connectors, webhooks, polling, and filesystem watches as provider strategies behind one source-watch contract.
- Never store secret values in registries or logs; store refs only.
- Keep dry-run as the first supported execution path.
- Ensure validation catches missing cursor, provider, idempotency key, route, and unsafe enabled state.

Likely first build slice:
Make `watch-source` registries and dry-run polling production-grade:
- seed all Plan 16 registry files during runtime/init or install,
- validate connected-system/provider/watch-source/cursor/trigger-rule shape,
- normalize source events with stable idempotency keys,
- write source events only in apply mode,
- append run queue entries through the Plan 15 queue contract,
- add tests for provider fallback, cursor safety, duplicate events, and invalid routes.

Worker rules:
- You are not alone in this codebase. Other agents or the user may be editing files concurrently.
- Do not revert edits made by others.
- Adjust your implementation to accommodate concurrent changes.
- Edit files directly when assigned an implementation slice.
- List every changed file in your return.
- Include exact commands run and exact test results.

Verification target:
- `uv run pytest -q`
- `agentic-os watch-source list --root <temp root>`
- `agentic-os watch-source doctor --root <temp root>`
- `agentic-os watch-source poll <source_id> --root <temp root> --dry-run`
- `agentic-os watch-source run-due --root <temp root> --dry-run`
- `agentic-os validate --root <temp root>`

Return first:
1. Investigation summary.
2. Recommended build slices.
3. Files each slice should own.
4. Risks or user approvals needed.
5. The first implementation slice ready for worker dispatch.
```

## Investigation Prompts

### 1. Contract Audit

```text
Read-only investigation in /Users/genome/projects/genomes_agentic_os.

Compare Plan 16 acceptance criteria against current code, templates, docs, and tests.

Return:
- Done, partial, and missing matrix.
- Current command surface.
- Gaps not proven by tests.
- Smallest safe implementation slice.

Do not edit files.
```

### 2. Provider And Credential Model

```text
Read-only investigation in /Users/genome/projects/genomes_agentic_os.

Audit connected systems and source providers.

Focus on provider priority, fallback ordering, credential refs, workspace verification, permissions, health checks, and provider-specific examples for Notion, Slack, Jira, Linear, email, GitHub, Granola, AgentMail, Composio, MCP, direct APIs, webhooks, polling, and filesystem.

Return schema changes, validation gaps, tests, and any live-access approvals needed.

Do not edit files.
```

### 3. Cursor, Dedupe, And Trigger Safety

```text
Read-only investigation in /Users/genome/projects/genomes_agentic_os.

Design the durable cursor and dedupe semantics for watch sources.

Focus on cursor state refs, last edited timestamps, event ids, page tokens, file mtimes, idempotency keys, dry-run behavior, apply writes, trigger-rule routing, and invalid enabled states.

Return proposed schema additions, required code changes, tests, and edge cases.

Do not edit files.
```

### 4. Event Bridge

```text
Read-only investigation in /Users/genome/projects/genomes_agentic_os.

Define how Plan 16 source events should bridge into Plan 17 event graph processing.

Focus on source-event shape, route metadata, run queue writes, event ledger compatibility, correlation ids, and how a future agent can inspect pending source events without chat history.

Return minimal bridge contract and tests.

Do not edit files.
```

## Initial Findings

- The repo already has `source_watch.py`, watch-source CLI handlers, runtime watch templates, an `os-watch-source` command, and `source-watcher` skill.
- Tests already cover watch-source create, doctor, poll, and run-due paths.
- The likely gap is hardening semantics: provider fallback, cursor state, dedupe, unsafe enabled states, route validation, normalized source events, and handoff into the event graph.
