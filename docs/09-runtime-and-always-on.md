# 09 · Runtime & Always-On

> **Purpose:** understand what the Agentic OS runtime surface *is* (file-backed
> registries, heartbeats, schedules, integrations, a run queue) and what it
> **is not yet** (an autonomous daemon that ticks without you). This page is the
> honest account of both halves.
>
> **You'll use:** `agentic-os runtime {init,doctor,run-next}`,
> `agentic-os heartbeat {list,run,doctor}`,
> `agentic-os schedule {create,run-due}`,
> `agentic-os integration {list,setup,doctor}`.
>
> **Prereqs:** an installed OS root
> ([01 · Install & Quickstart](01-install-and-quickstart.md)); runtime registries
> seeded by `runtime init` or included in the factory install.

---

## The idea

The Agentic OS runtime layer manages four file-backed registries that describe
*what should happen* on a cadence:

| Registry | File | What it holds |
| --- | --- | --- |
| Runtime registry | `shared_factory/00-control-plane/runtime-registry.yml` | Heartbeats, schedules, execution targets |
| Integration registry | `shared_factory/00-control-plane/integration-registry.yml` | Integration contracts, credentials, approval gates |
| Run queue | `shared_factory/00-control-plane/run-queue.yml` | Queued, approval-needed, and dispatched items |
| Heartbeat logs | `shared_factory/06-runs-and-logs/heartbeats/` | Per-run log files written by `heartbeat run` |

These files are the source of truth. Every CLI command reads and writes them
directly — there is no in-memory state, no database, no network call at the
registry layer. This is the MWP philosophy applied to operations: the filesystem
*is* the runtime state.

### Critical honesty: "always-on" is currently on-demand

**The OS has a full runtime surface but no runtime process.** Every command below
is invoked manually, or previewed via dry-run. Nothing ticks by itself.

- `heartbeat run` only fires when you type it.
- `schedule run-due` only enqueues due items when you type it.
- `watch-source poll` only polls when you type it.
- `event process-due` only processes chained events when you type it.
- `runtime run-next` only dispatches the next queue item when you type it (with
  `--apply`).

This is Gap A in the [gap register](../.agentic-atlas/gap-register.md), rated S1
(highest priority). The recommended fix — a thin supervisor (launchd plist on
macOS, systemd unit on Linux, or a cron entry) that runs the loop above on a
cadence — is backlogged as **F-001**. Until F-001 ships, treat the runtime surface
as a set of well-designed levers, not an engine that runs itself.

![Runtime registries (runtime-registry.yml, integration-registry.yml, run-queue.yml, heartbeat logs) fed by CLI commands; a dashed supervisor loop showing what F-001 would add (heartbeat run, schedule run-due, watch-source poll, event process-due, runtime run-next, doctor) is marked NOT YET SHIPPED](diagrams/runtime-registries.png)

---

## Registry templates

The `templates/runtime/` directory holds the canonical shapes for every registry
entry. Scaffold a new entry from the template, fill in the fields, then register
it via the appropriate command.

| Template file | Purpose |
| --- | --- |
| `heartbeat.yml` | A periodic health-check task with cadence, integration, approval policy, and escalation |
| `schedule.yml` | A command to run on a cadence, with timezone and next-due tracking |
| `integration.yml` | An external provider contract with setup tasks, health checks, and approval gates |
| `run-queue-item.yml` | A single item in the run queue (written by `heartbeat run` / `schedule run-due`) |
| `execution-target.yml` | A target environment (e.g. `script`, `computer_use_desktop`, `agentmail_api`) |

Key fields in a heartbeat entry:

| Field | Meaning |
| --- | --- |
| `id` | snake_case identifier, e.g. `granola_recent_notes_sync` |
| `cadence` | Cadence string, e.g. `hourly`, `every_2_hours`, `daily` |
| `execution_target` | Where the heartbeat runs: `script`, `agentmail_api`, etc. |
| `integration` | The integration ID this heartbeat is paired with |
| `enabled` | `false` until an active supervisor or manual trigger exists |
| `approval_policy` | Which action classes require approval before the run |
| `success_means` | Human-readable list of what a successful run proves |

Key fields in a schedule entry:

| Field | Meaning |
| --- | --- |
| `id` | snake_case identifier |
| `cadence` | `daily`, `weekly`, or a supported cron string |
| `timezone` | IANA timezone, defaults to `America/Chicago` |
| `command` | Shell command to invoke when due |
| `next_due_at` | Set by `schedule run-due`; blank until first tick |

---

## Commands & flags

### `agentic-os runtime init`

Seed the runtime registry files. Idempotent — skips files that already exist.

| Flag | Required | Description |
| --- | --- | --- |
| `--root` | — | Installed OS root. Defaults to `~/agentic_os`. |

Creates on first run:

- `shared_factory/00-control-plane/runtime-registry.yml`
- `shared_factory/00-control-plane/integration-registry.yml`
- `shared_factory/00-control-plane/run-queue.yml`
- `shared_factory/06-runs-and-logs/heartbeats/`

### `agentic-os runtime doctor`

Check the health of all runtime registries. Exits 1 if any blocker is found.
Reports missing files, malformed entries, unknown cadence strings, and missing
credential environment variables.

| Flag | Required | Description |
| --- | --- | --- |
| `--root` | — | Installed OS root. Defaults to `~/agentic_os`. |

### `agentic-os runtime run-next`

Inspect or dispatch the next safe queued item from `run-queue.yml`.
**Dry-run by default** — pass `--apply` to actually dispatch. Exits 1 if the
selected item is blocked or failed.

| Flag | Required | Description |
| --- | --- | --- |
| `--root` | — | Installed OS root. Defaults to `~/agentic_os`. |
| `--item-id` | — | Inspect or dispatch a specific queue item ID. |
| `--dry-run` | — | Preview only (default). |
| `--apply` | — | Actually dispatch the next item. |

### `agentic-os heartbeat list`

List all heartbeat entries from the runtime registry.

| Flag | Required | Description |
| --- | --- | --- |
| `--root` | — | Installed OS root. Defaults to `~/agentic_os`. |

### `agentic-os heartbeat run <heartbeat_id>`

Run a heartbeat (or dry-run it). Writes a log file under
`shared_factory/06-runs-and-logs/heartbeats/` and appends an item to the run
queue. **Dry-run by default.**

| Arg / Flag | Required | Description |
| --- | --- | --- |
| `heartbeat_id` | ✅ | snake_case ID of the heartbeat to run. |
| `--root` | — | Installed OS root. Defaults to `~/agentic_os`. |
| `--dry-run` | — | Preview only (default). |
| `--apply` | — | Attempt actual execution (blocked if target is not `active` or not in the safe-dispatch list). |

### `agentic-os heartbeat doctor`

Check heartbeat registry health — credential presence, cadence syntax, required
fields. Delegates to the same handler as `runtime doctor`.

| Flag | Required | Description |
| --- | --- | --- |
| `--root` | — | Installed OS root. Defaults to `~/agentic_os`. |

### `agentic-os schedule create <schedule_id>`

Register a new schedule entry in the runtime registry.

| Arg / Flag | Required | Description |
| --- | --- | --- |
| `schedule_id` | ✅ | snake_case schedule ID. |
| `--cadence` | — | `daily`, `weekly`, or supported cron string. Defaults to `manual`. |
| `--timezone` | — | IANA timezone. Defaults to `America/Chicago`. |
| `--command` | — | Shell command to invoke when due. |
| `--root` | — | Installed OS root. Defaults to `~/agentic_os`. |

### `agentic-os schedule run-due`

Find all schedules whose `next_due_at` has passed and enqueue them. Writes queue
items but does **not** execute them — dispatch happens via `runtime run-next
--apply`. **Dry-run by default.**

| Flag | Required | Description |
| --- | --- | --- |
| `--root` | — | Installed OS root. Defaults to `~/agentic_os`. |
| `--dry-run` | — | Preview which schedules are due (default). |
| `--apply` | — | Actually enqueue due schedules. |

### `agentic-os integration list`

List all integration entries from the integration registry, including status,
setup tasks, health checks, and approval gates.

| Flag | Required | Description |
| --- | --- | --- |
| `--root` | — | Installed OS root. Defaults to `~/agentic_os`. |

### `agentic-os integration setup <integration_id>`

Record or preview setup for a specific integration. **Dry-run by default.**
Note: `setup` records the intent; live adapter code is not yet implemented (Gap F).

| Arg / Flag | Required | Description |
| --- | --- | --- |
| `integration_id` | ✅ | Integration ID to set up. |
| `--root` | — | Installed OS root. Defaults to `~/agentic_os`. |
| `--dry-run` | — | Preview only (default). |
| `--apply` | — | Record the setup. |

### `agentic-os integration doctor`

Check all integrations for credential presence and health-check configuration.
Exits 1 on blockers.

| Flag | Required | Description |
| --- | --- | --- |
| `--root` | — | Installed OS root. Defaults to `~/agentic_os`. |

---

## Real output examples

### `runtime init`

```text
# CMD: agentic-os runtime init --root /tmp/aos-validate/root
root: /private/tmp/aos-validate/root
status: initialized
created:
- /private/tmp/aos-validate/root/shared_factory/06-runs-and-logs/heartbeats
- /private/tmp/aos-validate/root/shared_factory/00-control-plane/runtime-registry.yml
- /private/tmp/aos-validate/root/shared_factory/00-control-plane/integration-registry.yml
- /private/tmp/aos-validate/root/shared_factory/00-control-plane/run-queue.yml
skipped:
- /private/tmp/aos-validate/root/shared_factory/00-control-plane
- /private/tmp/aos-validate/root/shared_factory/06-runs-and-logs/runs
docs_created: 0
docs_skipped: 258
```

### `runtime run-next --dry-run`

```text
# CMD: agentic-os runtime run-next --root /tmp/aos-validate/root --dry-run
root: /private/tmp/aos-validate/root
status: idle
dry_run: true
message: no queued runtime work
```

The queue is empty because nothing has ticked to enqueue items yet — this is Gap A.

### `heartbeat list`

```text
# CMD: agentic-os heartbeat list --root /tmp/aos-validate/root
root: /private/tmp/aos-validate/root
heartbeats:
- id: granola_recent_notes_sync
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
- id: agentmail_inbound_check
  display_name: AgentMail inbound check
  domain: shared_factory
  enabled: false
  cadence: hourly
  execution_target: agentmail_api
  integration: agentmail
  context:
    read_first:
    - shared_factory/00-control-plane/integration-registry.yml
  approval_policy:
    external_write: false
    customer_visible_output: false
  success_means:
  - inbound queue checked
  - run log written
  failure_escalation:
    after_consecutive_failures: 2
    notify: Genome
```

Both heartbeats are `enabled: false` — they are contracts waiting for a live
adapter and a supervisor to call them.

### `heartbeat doctor`

```text
# CMD: agentic-os heartbeat doctor --root /tmp/aos-validate/root
root: /private/tmp/aos-validate/root
ok: true
findings:
- severity: fix-soon
  path: .../runtime-registry.yml
  message: 'credential environment variable is not set: AGENTMAIL_API_KEY'
- severity: fix-soon
  path: .../integration-registry.yml
  message: 'credential environment variable is not set: AGENTMAIL_API_KEY'
```

`ok: true` with `fix-soon` findings means the registry is structurally valid;
the credential is not set in the environment. Set `AGENTMAIL_API_KEY` and
re-run `heartbeat doctor` to clear the finding.

### `schedule create`

```text
# CMD: agentic-os schedule create demo --cadence daily --root /tmp/aos-validate/root
root: /private/tmp/aos-validate/root
status: created
schedule:
  id: demo
  display_name: Demo
  enabled: true
  cadence: daily
  timezone: America/Chicago
  execution_target: script
  command: agentic-os validate --root <root>
  outputs:
  - shared_factory/06-runs-and-logs/runs/
  next_due_at: null
  last_queued_at: null
registry: /private/tmp/aos-validate/root/shared_factory/00-control-plane/runtime-registry.yml
```

`next_due_at: null` — the schedule is registered but has never been ticked by
`schedule run-due`. Under Gap A, that tick must be initiated manually.

### `schedule run-due --dry-run`

```text
# CMD: agentic-os schedule run-due --root /tmp/aos-validate/root --dry-run
root: /private/tmp/aos-validate/root
status: dry-run
queued:
- id: queue_f780fc7fe05e
  kind: schedule
  ref: daily_agentic_os_doctor
  status: dry-run
  approval_state: not_required
  created_at: '2026-05-29T00:51:17.522130+00:00'
  dry_run: true
  due_at: '2026-05-28T05:00:00Z'
  idempotency_key: schedule:daily_agentic_os_doctor:2026-05-28T05:00:00Z
  execution_target: script
  command: agentic-os validate --root <root>
  log: shared_factory/06-runs-and-logs/runs/20260529T005117Z-f780fc7f-daily_agentic_os_doctor/run-log.yml
  evidence:
  - type: run_log
    path: shared_factory/06-runs-and-logs/runs/20260529T005117Z-f780fc7f-daily_agentic_os_doctor/run-log.yml
  blocked_reason: null
  updated_at: '2026-05-29T00:51:17.522130+00:00'
  created: true
- id: queue_8d1df5318143
  kind: schedule
  ref: demo
  status: dry-run
  approval_state: not_required
  created_at: '2026-05-29T00:51:17.523731+00:00'
  dry_run: true
  due_at: '2026-05-28T05:00:00Z'
  idempotency_key: schedule:demo:2026-05-28T05:00:00Z
  execution_target: script
  command: agentic-os validate --root <root>
  log: shared_factory/06-runs-and-logs/runs/20260529T005117Z-8d1df531-demo/run-log.yml
  evidence:
  - type: run_log
    path: shared_factory/06-runs-and-logs/runs/20260529T005117Z-8d1df531-demo/run-log.yml
  blocked_reason: null
  updated_at: '2026-05-29T00:51:17.523731+00:00'
  created: true
skipped: []
```

Two schedules are due. With `--apply` they would be written to `run-queue.yml`;
`runtime run-next --apply` would then dispatch the first safe one.

### `integration doctor`

```text
# CMD: agentic-os integration doctor --root /tmp/aos-validate/root
root: /private/tmp/aos-validate/root
ok: true
findings:
- severity: fix-soon
  path: .../integration-registry.yml
  message: 'credential environment variable is not set: AGENTMAIL_API_KEY'
```

---

## The F-001 supervisor loop (what would make this "always-on")

When F-001 ships, a thin supervisor — a launchd plist on macOS, a systemd unit
on Linux, or a crontab entry — would run the following sequence on each cadence
tick (suggested: every 5–15 minutes):

```bash
# F-001 supervisor sequence (not yet implemented)
agentic-os heartbeat run <each-enabled-heartbeat-id> --root ~/agentic_os --apply
agentic-os schedule run-due --root ~/agentic_os --apply
agentic-os watch-source run-due --root ~/agentic_os --apply
agentic-os event process-due --root ~/agentic_os --apply
agentic-os runtime run-next --root ~/agentic_os --apply
agentic-os doctor --root ~/agentic_os
```

The gap register also calls for:

- `installers/install-scheduler.sh` — a one-command installer that writes the
  platform-appropriate supervisor unit
- `agentic-os runtime supervise --dry-run` — a planner that shows what the
  supervisor would do without touching anything

Until then, operators can run these commands manually or wire them into an
external scheduler themselves. The registries, queue, and log contracts are
all stable; the supervisor is drop-in.

---

## Running this from Claude vs Codex

> Same registry files, same commands, same run-queue entries — only the trigger
> differs.

- **Claude:** use the `/os-runtime-init` command to seed registries, or invoke
  the **`runtime-operator`** skill (it wraps init, doctor, dry-run heartbeat and
  schedule inspection, and guarded Notion tracking).
- **Codex:** run `agentic-os runtime init --root ~/agentic_os`,
  `agentic-os heartbeat list`, and `agentic-os runtime doctor` directly from
  the terminal.

Full mechanics: [13 · Agent Surfaces](13-agent-surfaces.md).

---

## Guardrails & gotchas

- **Dry-run by default.** Every command that enqueues or dispatches work (`heartbeat
  run`, `schedule run-due`, `runtime run-next`, `integration setup`) is dry-run
  unless you pass `--apply`. Output printed to stdout; nothing written to the
  queue or logs until you confirm.
- **`--apply` exits 1 on blocked items.** If a queue item is blocked (approval
  needed, integration unhealthy), `runtime run-next --apply` exits 1 and reports
  the `blocked_reason`. Fix the blocker, then retry.
- **`enabled: false` heartbeats exit 1 with `blocked_reason`.** Dry-run always
  proceeds and writes a log. `--apply` on a disabled heartbeat resolves the gate
  with `status: blocked` and `blocked_reason: runtime item is disabled` — the
  command exits 1. Set `enabled: true` only when a live adapter is wired and
  you are ready for actual execution.
- **Integrations are contracts, not connections.** `integration list` shows what
  integrations are designed; none are live (Gap F). `integration doctor` checks
  that credential environment variables are set, but the credentials are not used
  for live API calls until adapters ship.
- **Names are snake\_case.** `granola_recent_notes_sync`, not
  `granola-recent-notes-sync`.
- **`--root` defaults to `~/agentic_os`.** Pass it explicitly in scripts and
  supervisors to avoid ambiguity.

---

## Related

- [08 · Runs & Run Logs](08-runs-and-run-logs.md) — the run-log format that
  heartbeats and schedules write.
- [10 · Events & Chains](10-events-and-chains.md) — `event process-due`, which
  runs alongside the supervisor loop.
- [11 · Connected Sources](11-connected-sources.md) — `watch-source run-due`,
  the other supervisor leg.
- [16 · Health, Doctor & Validation](16-health-doctor-validation.md) — the
  `doctor` commands this page's registries feed into.
- [17 · CLI Reference](17-cli-reference.md) — full flag listings for every command.
- Atlas: [gap-register.md §A](../.agentic-atlas/gap-register.md) ·
  [command-reference.md §6](../.agentic-atlas/architecture/command-reference.md)
