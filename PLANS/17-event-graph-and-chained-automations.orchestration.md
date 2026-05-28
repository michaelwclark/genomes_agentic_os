# Plan 17 Orchestration Prompt

Use this prompt to start the Plan 17 orchestration run after Plan 15 and Plan 16 have established runtime queueing and source-event generation.

## Source Spec

- Spec: `/Users/genome/projects/genomes_agentic_os/PLANS/17-event-graph-and-chained-automations.md`
- Companion prompt: `/Users/genome/projects/genomes_agentic_os/PLANS/17-event-graph-and-chained-automations.orchestration.md`

## Current Anchors

- Event graph implementation: `/Users/genome/projects/genomes_agentic_os/src/genomes_agentic_os/event_graph.py`
- Source watcher bridge: `/Users/genome/projects/genomes_agentic_os/src/genomes_agentic_os/source_watch.py`
- Runtime implementation: `/Users/genome/projects/genomes_agentic_os/src/genomes_agentic_os/runtime_ops.py`
- CLI surface: `/Users/genome/projects/genomes_agentic_os/src/genomes_agentic_os/cli.py`
- Runtime templates: `/Users/genome/projects/genomes_agentic_os/templates/runtime/event-envelope.yml`, `/Users/genome/projects/genomes_agentic_os/templates/runtime/event-ledger-index.md`, `/Users/genome/projects/genomes_agentic_os/templates/runtime/chain-rule.yml`, `/Users/genome/projects/genomes_agentic_os/templates/runtime/event-processing-result.yml`, `/Users/genome/projects/genomes_agentic_os/templates/runtime/dead-letter-event.yml`
- Runtime commands: `/Users/genome/projects/genomes_agentic_os/harness/commands/os-event.md`, `/Users/genome/projects/genomes_agentic_os/harness/commands/os-chain.md`
- Runtime skill: `/Users/genome/projects/genomes_agentic_os/harness/skills/event-graph-operator/SKILL.md`
- Feature guide: `/Users/genome/projects/genomes_agentic_os/docs/13-feature-guides/17-event-graph-and-chained-automations.md`
- Test coverage: `/Users/genome/projects/genomes_agentic_os/tests/test_cli_scaffold.py`

## Orchestration Prompt

```text
/orchestrate

Work in /Users/genome/projects/genomes_agentic_os.

Goal: finish Plan 17, "Event Graph And Chained Automations", by hardening the existing file-backed event envelope, event ledger, chain-rule, dead-letter, replay, and queued follow-up layer.

Primary spec:
/Users/genome/projects/genomes_agentic_os/PLANS/17-event-graph-and-chained-automations.md

Prerequisites:
- Plan 15 owns runtime queue semantics.
- Plan 16 owns connected source events.
- Plan 17 should consume those contracts instead of creating parallel state shapes.

Important repo context:
- This repo is the source package, not the live installed OS.
- The live install target is ~/agentic_os.
- Preserve the Plan 21 harness context contract at every installed layer.
- The worktree may be dirty. Do not revert user changes or unrelated edits. Work with concurrent changes.

Start with read-only investigations. Do not begin implementation workers until the investigation outputs identify the smallest safe first build slice.

Baseline first:
1. Capture `git status --short` and `git rev-parse HEAD`.
2. Run `uv run pytest -q` if the environment is ready. If blocked, record the exact blocker and continue with read-only investigation.
3. Inspect the Plan 17 spec, event_graph.py, source_watch.py, runtime_ops.py, cli.py, event/chain templates, harness commands/skill, docs guide, and tests.

Investigation requirements:
1. Contract audit: compare Plan 17 acceptance criteria to current implementation and tests.
2. Event ledger design: verify append-only ledger shape, event ids, correlation ids, event cursors, source-event bridge, and run closeout emitted events.
3. Chain processing model: verify chain matching, idempotency, max depth, dry-run queue output, approval gates, and skip reasons.
4. Failure and replay model: verify dead-letter records, replay behavior, processing results, summarization of last N events, and manual repair paths.

Expected implementation strategy:
- Keep the event ledger file-backed, append-only, and inspectable.
- Make chain processing deterministic and idempotent.
- Never execute external effects directly from event processing; enqueue guarded work.
- Record why each follow-up was queued, skipped, blocked, or dead-lettered.
- Keep chain examples concrete: feature merge docs, email to CRM, transcript to tasks, Notion card to worktree, approval grant, and CI failure.

Likely first build slice:
Make `event process-due` and chain-rule handling production-grade:
- normalize event envelopes from source watchers and run closeout,
- enforce idempotency keys and max depth,
- write processing-result records,
- write dead-letter files with next action,
- enqueue through the Plan 15 queue contract,
- add tests for duplicate events, chain max depth, approval-needed output, dead-letter replay, and event summaries.

Worker rules:
- You are not alone in this codebase. Other agents or the user may be editing files concurrently.
- Do not revert edits made by others.
- Adjust your implementation to accommodate concurrent changes.
- Edit files directly when assigned an implementation slice.
- List every changed file in your return.
- Include exact commands run and exact test results.

Verification target:
- `uv run pytest -q`
- `agentic-os event append --root <temp root> --type <type> --source <source>`
- `agentic-os event process-due --root <temp root> --dry-run`
- `agentic-os chain test <chain_id> --root <temp root>`
- `agentic-os chain doctor --root <temp root>`
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

Compare Plan 17 acceptance criteria against current code, templates, docs, and tests.

Return done, partial, and missing matrix, plus the smallest safe implementation slice.

Do not edit files.
```

### 2. Event Ledger And Envelope Design

```text
Read-only investigation in /Users/genome/projects/genomes_agentic_os.

Audit event envelope and ledger semantics.

Focus on event ids, source refs, correlation ids, payload refs, append-only ledger index, run log links, source watcher inputs, run closeout emitted events, and how agents summarize recent events without chat history.

Return required schema changes, validation rules, and tests.

Do not edit files.
```

### 3. Chain Matching And Queueing

```text
Read-only investigation in /Users/genome/projects/genomes_agentic_os.

Audit chain-rule processing.

Focus on match conditions, route-to fields, idempotency keys, max depth, dry-run queue output, approval-needed behavior, and queue item compatibility with Plan 15.

Return recommended state machine, minimal command changes, tests, and edge cases.

Do not edit files.
```

### 4. Dead Letter And Replay

```text
Read-only investigation in /Users/genome/projects/genomes_agentic_os.

Design failure handling for event graph processing.

Focus on dead-letter files, next-action fields, replay command behavior, duplicate replay prevention, repair notes, and doctor findings for stuck events.

Return schema, command, and test recommendations.

Do not edit files.
```

## Initial Findings

- The repo already has `event_graph.py`, event/chain CLI handlers, event runtime templates, `os-event` and `os-chain` commands, and an `event-graph-operator` skill.
- Tests already cover event append, chain process, idempotency, dead-letter handling, and run closeout emitted events.
- The likely gap is production semantics: deterministic chain state, deeper approval/skip reasons, replay ergonomics, dead-letter repair paths, and alignment with Plan 15/16 state shapes.
