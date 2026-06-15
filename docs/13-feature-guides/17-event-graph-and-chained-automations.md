# 17 Event Graph And Chained Automations

## Table Of Contents

- [Purpose](#purpose)
- [Installed Surface](#installed-surface)
- [Operating Flow](#operating-flow)
- [Commands](#commands)
- [Runtime Files](#runtime-files)
- [Appending Events](#appending-events)
- [Testing Chain Rules](#testing-chain-rules)
- [Processing And Replay](#processing-and-replay)
- [Dead Letters](#dead-letters)
- [Run Closeout Events](#run-closeout-events)
- [Validation](#validation)
- [Troubleshooting](#troubleshooting)
- [Source Artifacts](#source-artifacts)

## Purpose

The event graph layer turns important OS occurrences into durable local event
files and lets configured chain rules create follow-up work.

Use it when a source watcher, run closeout, merge event, approval request, or
manual operation needs inspectable evidence and replayable downstream behavior.
The runtime ledger stays file-backed. Chain processing has a dry-run mode, an
apply mode, idempotency state, processing result records, and dead-letter files
for failed rules.

## Installed Surface

Feature 17 installs these runtime knowledge files:

```text
shared_factory/05-knowledge/templates/runtime/event-envelope.yml
shared_factory/05-knowledge/templates/runtime/event-ledger-index.md
shared_factory/05-knowledge/templates/runtime/chain-rule.yml
shared_factory/05-knowledge/templates/runtime/event-processing-result.yml
shared_factory/05-knowledge/templates/runtime/dead-letter-event.yml
shared_factory/05-knowledge/commands/os-event.md
shared_factory/05-knowledge/commands/os-chain.md
shared_factory/05-knowledge/skills/event-graph-operator/SKILL.md
```

The runtime state files live under:

```text
shared_factory/00-control-plane/event-graph.yml
shared_factory/00-control-plane/chain-rules.yml
shared_factory/00-control-plane/event-cursors.yml
shared_factory/00-control-plane/run-queue.yml
shared_factory/06-runs-and-logs/events/
shared_factory/06-runs-and-logs/events/processing-results/
shared_factory/06-runs-and-logs/events/dead-letter/
shared_factory/06-runs-and-logs/events/event-ledger-index.md
```

## Operating Flow

```text
source or operator action
  -> normalized event envelope
  -> event ledger file
  -> chain rule match
  -> dry-run processing result
  -> apply processing result
  -> run queue item or dead-letter record
  -> replay if needed
```

The graph is deliberately local. Events are durable evidence. Chain rules are
reviewable registry entries. Queue writes happen only in apply mode.

## Commands

Append an event:

```bash
agentic-os event append \
  --root ~/agentic_os \
  --type github.pull_request.merged \
  --source github:genomes_agentic_os:pull/123 \
  --summary "PR 123 merged into main."
```

List recent events:

```bash
agentic-os event list --root ~/agentic_os --limit 20
```

Summarize recent events and pending follow-up:

```bash
agentic-os event summary --root ~/agentic_os --limit 20
```

List chain rules:

```bash
agentic-os chain list --root ~/agentic_os
```

Test one chain rule against an event file:

```bash
agentic-os chain test feature_merged_to_docs_update \
  --event ~/agentic_os/shared_factory/06-runs-and-logs/events/<event_id>.yml \
  --root ~/agentic_os
```

Check chain rule safety:

```bash
agentic-os chain doctor --root ~/agentic_os
```

Preview queue writes for matching enabled rules:

```bash
agentic-os event process-due --root ~/agentic_os --dry-run
```

Apply matching enabled rules:

```bash
agentic-os event process-due --root ~/agentic_os --apply
```

Replay one event:

```bash
agentic-os event replay <event_id> --root ~/agentic_os --dry-run
```

## Runtime Files

`event-graph.yml` records the local graph contract: event log path, chain rule
registry, and run queue path.

`chain-rules.yml` stores disabled-by-default chain rules. A rule includes:

- `id`
- `display_name`
- `enabled`
- `when`
- `then`
- `approval`
- `limits`
- `idempotency`

`event-cursors.yml` stores processed idempotency keys. It prevents repeated
apply runs and duplicate event envelopes from adding duplicate queue items.

`run-queue.yml` receives queue items created by apply-mode chain processing.

`events/` stores event envelopes. `processing-results/` stores rule processing
outcomes. `dead-letter/` stores failures that require operator review.

## Appending Events

`event append` writes a normalized event envelope to
`shared_factory/06-runs-and-logs/events/` and updates
`event-ledger-index.md`.

Use `--correlation-id` when the event belongs to a larger run, issue, PR, or
source watcher operation. Keep payloads referenced by path or source ID instead
of copying large private records into the event envelope.

## Testing Chain Rules

There is no `chain create` command. Create or modify chain rules in
`shared_factory/00-control-plane/chain-rules.yml`, keep them disabled while
editing, and use:

```bash
agentic-os chain doctor --root ~/agentic_os
agentic-os chain test <chain_rule_id> --event <event_file> --root ~/agentic_os
```

`chain doctor` should pass before enabling a rule. Enabled rules need an
enqueue action, idempotency key, and max chain depth.

## Processing And Replay

`event process-due --dry-run` evaluates enabled matching rules and returns what
would be queued. It must not write the run queue.

`event process-due --apply` writes queue items, processing results, and
processed idempotency keys. Re-running apply against the same event should
return skipped results instead of duplicating queue work.

`event replay <event_id> --dry-run` reruns matching logic for one event. Use it
after editing a rule, recovering from a dead letter, or checking whether a
previous event should now produce a different queue item.

`event summary --limit <N>` reads only durable event files, processing results,
dead letters, and the run queue. Use it when a fresh agent needs the last N
events and pending follow-up without relying on chat history.

## Dead Letters

If an enabled rule matches but cannot produce a valid queue item, processing
writes a dead-letter record under:

```text
shared_factory/06-runs-and-logs/events/dead-letter/
```

Dead-letter records include the event ID, chain rule ID, failure reason, next
action, and timestamp. Fix the event or rule, then replay the event before
re-enabling broader processing.

## Run Closeout Events

Run closeout can emit event evidence:

```bash
agentic-os run-log close <domain> <run_id> \
  --status done \
  --validation "validation passed" \
  --emit-events \
  --root ~/agentic_os
```

The emitted event uses the run closeout state as source evidence and writes to
the same file-backed event ledger. This keeps run evidence available to later
chain rules without relying on chat history.

## Validation

Validate the installed OS after event graph changes:

```bash
agentic-os validate --root ~/agentic_os
```

For source-package development, run:

```bash
uv run --extra dev pytest -q
```

The test suite covers event append, ledger index creation, chain rule testing,
dry-run processing, apply-mode queue writes, duplicate-event idempotency,
max-depth skips, approval-needed queue output, event summaries, dead-letter
records, replay after repair, and run closeout event emission.

## Troubleshooting

If `event process-due --dry-run` returns no actions, confirm the event type
matches an enabled rule in:

```text
shared_factory/00-control-plane/chain-rules.yml
```

If apply queues duplicate work, inspect:

```text
shared_factory/00-control-plane/event-cursors.yml
```

If `chain doctor` fails, keep the rule disabled until the blocker findings are
fixed. The common blockers are a missing enqueue action or missing
`max_chain_depth` on an enabled rule.

If a rule dead-letters, inspect the dead-letter file first, then replay the
event with:

```bash
agentic-os event replay <event_id> --root ~/agentic_os --dry-run
```

## Source Artifacts

- Installed spec: `SPECS/17-event-graph-and-chained-automations/SPEC.md`
- Installed worklog spec: `worklogs/source-features/17-event-graph-and-chained-automations/SPEC.md`
- Installed worklog QA: `worklogs/source-features/17-event-graph-and-chained-automations/HOLDOUT_QA.md`
- Installed worklog QA results: `worklogs/source-features/17-event-graph-and-chained-automations/HOLDOUT_QA_RESULTS.md`
- Command prompts: `harness/commands/os-event.md`, `harness/commands/os-chain.md`
- Skill: `harness/skills/event-graph-operator/SKILL.md`
- Runtime templates: `templates/runtime/event-envelope.yml`, `templates/runtime/event-ledger-index.md`, `templates/runtime/chain-rule.yml`, `templates/runtime/event-processing-result.yml`, `templates/runtime/dead-letter-event.yml`
- Runtime implementation: `src/genomes_agentic_os/event_graph.py`
- CLI registration: `src/genomes_agentic_os/cli.py`
- Runtime validation: `src/genomes_agentic_os/validate.py`
- Test coverage: `tests/test_cli_scaffold.py`
