# 10 · Events & Chains

> **Purpose:** record every notable occurrence as a file-backed event, then let
> declarative chain rules react to those events automatically — queuing follow-up
> runs with **no implicit side effects**. This is the OS's event-emission and
> reaction model, realized entirely as files (not an in-memory pub/sub bus).
>
> **You'll use:** `agentic-os event append|list|summary|process-due|replay`,
> `agentic-os chain list|test|doctor`.
> **Prereqs:** an installed OS root ([01 · Install & Quickstart](01-install-and-quickstart.md));
> familiarity with the run-queue ([09 · Runtime & Always-On](09-runtime-and-always-on.md)).

---

## The idea

The MWP principle — *filesystem is the architecture* — applies equally to events.
Instead of an in-process event bus that lives and dies with a process, the OS
maintains a **file-backed event ledger**: each event is a YAML file, each chain
rule is a YAML record, and every decision about what to react to is written to
disk before execution touches anything.

Three properties are guaranteed by `event_graph.py` (the authoritative module):

- **Idempotency.** `rule_idempotency_key(rule, event)` derives a deterministic
  key for each (rule, event) pair; keys already recorded in `event-cursors.yml`
  are skipped. The same source event can never enqueue the same chain action twice.
- **Loop protection.** `event_chain_depth(event)` reads `correlation.chain_depth`
  from the event envelope. If a rule's `limits.max_chain_depth` is reached or
  exceeded, the match is recorded as `skipped` — not dispatched, not dead-lettered.
- **Deferred execution.** Chain reactions only *queue* items in `run-queue.yml`.
  `runtime run-next` (page 09) executes them, gated by automation maturity and any
  approval requirement the rule declares. Nothing fires an external side effect
  implicitly when an event is appended.

**Rule of thumb:** emit events for cross-concern reactions. If you need the result
immediately, call the function directly. If a source change should trigger a
review workflow, append an event and add a chain rule.

---

## Control-plane files

All event state lives under two directories:

```
shared_factory/
  00-control-plane/
    event-graph.yml         # graph metadata + file-path registry
    chain-rules.yml         # list of chain_rules (loaded by chain list / process-due)
    event-cursors.yml       # processed_idempotency_keys — the dedupe ledger
    run-queue.yml           # items queued by chain reactions
  06-runs-and-logs/events/
    evt_<hash>.yml          # one file per appended event
    event-ledger-index.md   # human-readable index (append-only, never deleted)
    dead-letter/            # *.yml — events matched by malformed rules
    processing-results/     # *.yml — per-(event, rule) outcome records
```

These files are the source of truth. There is no in-memory state to get out of
sync with disk.

---

## Event envelope

`append_event` normalizes every occurrence into a consistent envelope and writes
it as `evt_<hash>.yml`. The fields written by the current implementation are:

| Field | Set by |
| --- | --- |
| `id` | `evt_` + SHA-256 of `event_type:source_ref:observed_at` (12 hex chars) |
| `type` | `--type` flag (e.g. `github.pull_request.merged`) |
| `schema_version` | `1` |
| `occurred_at` / `observed_at` | UTC ISO-8601 timestamp at append time |
| `source.ref` | `--source` flag |
| `correlation.correlation_id` | `--correlation-id` flag, or SHA-256 of source ref |
| `idempotency_key` | `{event_type}:{sha256(source_ref)[:16]}` |
| `summary` | `--summary` flag, or auto-generated from type + source |
| `payload_ref` | reference link to full payload (never copies secrets) |
| `privacy` | `contains_secret: false`, `contains_customer_data: false` by default |
| `links.run_log` | populated automatically by `emit_run_close_event` |

The full template schema (including `actor`, `object`, `parent_event_id`, and
`chain_depth`) lives at
[`templates/runtime/event-envelope.yml`](../templates/runtime/event-envelope.yml);
the implementation writes a subset. Payload privacy is caller-controlled — link to
payloads rather than embedding transcripts or secrets.

---

## Chain rule anatomy

A chain rule in `chain-rules.yml` has five sections:

| Section | Purpose |
| --- | --- |
| `when.event_type` | Must equal the event's `type` exactly. |
| `when.filters` | Key-value pairs AND-matched against event fields (source, payload, object). |
| `then.enqueue` | What to queue: `workflow`, `route_to`, `context_profile`, `maturity`. |
| `approval` | `required: true` puts the queue item in `approval-needed` status. |
| `limits` | `max_chain_depth` (integer) and optional `cooldown`. |
| `idempotency.key` | Template string; `{event_idempotency_key}:{rule_id}` is the default. |

New rules ship with `enabled: false`. Enable only after `chain doctor` passes.

---

## Flow diagram

![Event flow: a source appends a normalized event to the ledger; chain rules match by event_type and filters; malformed rules route to dead-letter; depth limit or seen idempotency key skips the item; otherwise a queue item is written to run-queue.yml and dispatched by runtime run-next](diagrams/events-flow.png)

---

## Commands & flags

### `agentic-os event append`

Normalize an occurrence and write it to the ledger.

| Arg / Flag | Required | Description |
| --- | --- | --- |
| `--type` | Yes | Event type string, e.g. `github.pull_request.merged` |
| `--source` | Yes | Source reference (path, URL, or identifier) |
| `--summary` | — | Human-readable summary (auto-generated if omitted) |
| `--correlation-id` | — | Correlation ID for cross-event tracing |
| `--root` | — | OS root; defaults to `~/agentic_os` |

Writes: `evt_*.yml` to the event ledger; appends a row to `event-ledger-index.md`.
Status: not individually validated in published output examples.

```bash
agentic-os event append \
  --type os.run.closed.done \
  --source "acme/launch" \
  --summary "run closed successfully" \
  --root ~/agentic_os
```

### `agentic-os event list`

List recent events from the ledger (most recent `--limit`, default 20).

| Arg / Flag | Required | Description |
| --- | --- | --- |
| `--limit` | — | Max events to show (default 20) |
| `--root` | — | OS root; defaults to `~/agentic_os` |

Real output (fresh install, no events appended yet):

```text
# CMD: agentic-os event list --root /tmp/aos-validate/root
# ---
events: []
ledger: /private/tmp/aos-validate/root/shared_factory/06-runs-and-logs/events/event-ledger-index.md
```

### `agentic-os event summary`

Snapshot view across the ledger, run-queue, dead-letter, and processing-results.
Use this to hand orientation context to a fresh agent session.

| Arg / Flag | Required | Description |
| --- | --- | --- |
| `--limit` | — | Max items per category (default 20) |
| `--root` | — | OS root; defaults to `~/agentic_os` |

Real output (fresh install):

```text
# CMD: agentic-os event summary --root /tmp/aos-validate/root
# ---
last_events: []
pending_follow_up: []
dead_letters: []
processing_results: []
ledger: /private/tmp/aos-validate/root/shared_factory/06-runs-and-logs/events/event-ledger-index.md
run_queue: /private/tmp/aos-validate/root/shared_factory/00-control-plane/run-queue.yml
```

### `agentic-os event process-due`

Match all ledger events against enabled chain rules and (optionally) enqueue
results. **Exactly one of `--dry-run` or `--apply` is required — there is no
default.**

| Arg / Flag | Required | Description |
| --- | --- | --- |
| `--dry-run` | Yes (or `--apply`) | Preview matches; write nothing |
| `--apply` | Yes (or `--dry-run`) | Write queue items and record idempotency keys |
| `--root` | — | OS root; defaults to `~/agentic_os` |

Always run `--dry-run` first. Real output (fresh install, no enabled rules):

```text
# CMD: agentic-os event process-due --root /tmp/aos-validate/root --dry-run
# ---
dry_run: true
actions: []
```

### `agentic-os event replay`

Re-run one event through all chain rules (useful after fixing a rule or
un-dead-lettering an event). **Exactly one of `--dry-run` or `--apply` is
required.**

| Arg / Flag | Required | Description |
| --- | --- | --- |
| `event_id` | Yes (positional) | ID of the event to replay (e.g. `evt_a3f9c2e1b8d4`) |
| `--dry-run` | Yes (or `--apply`) | Preview only |
| `--apply` | Yes (or `--dry-run`) | Enqueue matched chain actions |
| `--root` | — | OS root; defaults to `~/agentic_os` |

Not individually validated in published output examples; returns the same
per-rule `processing_result` records as `event process-due`.

---

## Processing outcomes

Each (event, rule) pair produces a processing result written to
`processing-results/*.yml`:

| `status` | Meaning |
| --- | --- |
| `dry-run` | Matched in preview mode; nothing written |
| `queued` | Queue item written to `run-queue.yml`; idempotency key recorded |
| `approval-needed` | Queued but requires human approval before dispatch |
| `skipped` | Idempotency key already seen, OR `event_chain_depth >= max_chain_depth` |
| `dead-letter` | Rule matched but is malformed (missing `id` or `enqueue` action) |

Dead-letter records land in `dead-letter/*.yml` with a `failure_reason` and a
`next_action` field. Fix the rule, then replay the event with `--apply`.

---

## Chain commands

### `agentic-os chain list`

List all configured chain rules from `chain-rules.yml`.

| Arg / Flag | Required | Description |
| --- | --- | --- |
| `--root` | — | OS root; defaults to `~/agentic_os` |

Real output (two of the built-in rules shown):

```text
# CMD: agentic-os chain list --root /tmp/aos-validate/root
# ---
chain_rules:
- id: feature_merged_to_docs_update
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
      maturity: prepare
  approval:
    required: false
  limits:
    max_chain_depth: 3
    cooldown: 10_minutes
  idempotency:
    key: '{event_idempotency_key}:feature_merged_to_docs_update'
- id: email_sent_to_crm_update
  display_name: Email sent updates CRM follow-up
  enabled: false
  when:
    event_type: email.message.sent
    filters: {}
  then:
    enqueue:
      work_type: crm_update
      route_to: shared_factory
      workflow: email_to_crm_update
      context_profile: customer_communication
      maturity: prepare
  approval:
    required: true
  limits:
    max_chain_depth: 2
  idempotency:
    key: '{event_idempotency_key}:email_sent_to_crm_update'
```

### `agentic-os chain test`

Test a specific chain rule against an event file without writing anything.

| Arg / Flag | Required | Description |
| --- | --- | --- |
| `chain_rule_id` | Yes (positional) | ID of the rule to test |
| `--event` | Yes | Path to an event YAML or JSON file |
| `--root` | — | OS root; defaults to `~/agentic_os` |

Returns `matched: true/false` and the queue item that *would* be created.
Not individually validated in published output examples.

```bash
agentic-os chain test feature_merged_to_docs_update \
  --event /tmp/test-event.yml \
  --root ~/agentic_os
```

### `agentic-os chain doctor`

Validate all chain rules: checks `id` presence, `enqueue` action, depth limits,
and idempotency key templates.

| Arg / Flag | Required | Description |
| --- | --- | --- |
| `--root` | — | OS root; defaults to `~/agentic_os` |

Real output (clean install):

```text
# CMD: agentic-os chain doctor --root /tmp/aos-validate/root
# ---
ok: true
findings: []
```

Exit codes: `0` ok · `1` findings present · `2` usage error or deliberate refusal.

---

## Running this from Claude vs Codex

> Same ledger files, same chain rules, same run-queue — only the trigger differs.

- **Claude:** run `/os-event` (normalize and append an event) or `/os-chain`
  (inspect/test rules). The **`event-graph-operator`** skill wraps the full
  workflow: normalize → append → dry-run process-due → confirm before apply.
- **Codex:** run `agentic-os event <subcommand>` and `agentic-os chain <subcommand>`
  directly from the terminal. Always pass `--root ~/agentic_os` in scripts to
  avoid touching the default root unintentionally.

Full mechanics and surface setup: [13 · Agent Surfaces](13-agent-surfaces.md).

---

## Guardrails & gotchas

- **`--dry-run` or `--apply` is required** for `event process-due` and
  `event replay`. There is no default. Omitting both is a usage error (exit 2).
- **New rules ship disabled.** `enabled: false` is the safe default. Run
  `chain doctor` and `chain test` with a representative event file before flipping
  to `enabled: true`.
- **Reactions queue, they do not execute.** A chain match writes to `run-queue.yml`;
  it does not launch a process. `runtime run-next` (page 09) dispatches the queue,
  gated by automation maturity and approval rules.
- **Names are snake_case.** Rule IDs, event types, and source refs that feed into
  idempotency keys must use lowercase letters, digits, and underscores only.
- **Dead-letter means a malformed rule**, not a depth/dedupe hit. Depth and
  idempotency skips produce `status: skipped`. Only a rule that is enabled but
  missing its `id` or `enqueue` block produces `status: dead-letter`.
- **Connected sources emit events automatically** (page 11) when their pollers
  detect changes. You rarely need to call `event append` manually for watched
  sources; it is there for OS-internal events (`os.run.closed.*`) and for one-off
  integrations.
- **Payload privacy.** `append_event` defaults `contains_secret: false` and
  `contains_customer_data: false`. Set these explicitly if the source ref points
  to sensitive material, and link to payloads rather than embedding them.

---

## Related

- [09 · Runtime & Always-On](09-runtime-and-always-on.md) — `runtime run-next` dispatches what chain reactions queue.
- [11 · Connected Sources](11-connected-sources.md) — watch-sources emit events that chain rules can react to.
- [07 · Automations](07-automations.md) — automation maturity gates whether a queued chain reaction actually executes.
- [17 · CLI Reference](17-cli-reference.md) — full flag listing for all `event` and `chain` subcommands.
- Atlas: [`architecture/system-architecture.md` §6](architecture/system-architecture.md) · [`command-reference.md` §7](architecture/command-reference.md) · [`harness/commands/os-event.md`](../harness/commands/os-event.md) · [`harness/commands/os-chain.md`](../harness/commands/os-chain.md)
