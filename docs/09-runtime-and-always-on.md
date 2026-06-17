# 09 · Runtime & Always-On

> **Purpose:** understand the Agentic OS runtime surface (file-backed registries,
> heartbeats, schedules, integrations, a run queue) and how to make it **tick on a
> cadence**. There is no bespoke daemon — an external scheduler calls one
> auditable tick command (`runtime supervise`), installed by a small script.
>
> **You'll use:** `agentic-os runtime {init,doctor,run-next,supervise}`,
> `agentic-os heartbeat {list,run,doctor}`,
> `agentic-os schedule {create,run-due}`,
> `agentic-os integration {list,setup,doctor}`, `installers/install-scheduler.sh`.
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

### How it ticks: on-demand by default, schedulable via the supervisor

By itself, every command below is **invoked manually or previewed via dry-run** —
the registry layer has no daemon. What turns the surface into an always-on engine
is the **supervisor** plus an **external scheduler**:

- **`agentic-os runtime supervise`** runs *one tick* across the whole surface, in
  order — heartbeats → schedules → watch-sources → events → run-queue — then a
  read-only health check. Dry-run by default; `--apply` commits. Steps are
  **isolated**: one failing subsystem never aborts the tick.
- **`installers/install-scheduler.sh`** installs a **launchd agent** (macOS) or a
  **crontab line** (other platforms) that calls `runtime supervise --apply` on a
  cadence (default 15 min). It is dry-run by default and **not auto-installed** —
  enabling a background agent is an explicit, per-host choice.

So "always-on" is opt-in per machine: install the scheduler and the OS ticks
itself; skip it and the same commands stay on-demand levers. This closes the old
Gap A (F-001 + F-002) in the
[gap register](../.agentic-atlas/gap-register.md) — see
[the supervisor section](#the-supervisor-what-makes-it-always-on) below for setup.

![Runtime registries (runtime-registry.yml, integration-registry.yml, run-queue.yml, heartbeat logs) fed by manual CLI commands; the shipped supervisor loop — runtime supervise, installed via install-scheduler.sh — composes one tick of heartbeat run, schedule run-due, watch-source run-due, event process-due, runtime run-next, and a read-only health check on a cadence](diagrams/runtime-registries.png)

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
| `local_time` | Optional `HH:MM` local wall-clock time for `daily` schedules |
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

## The supervisor: what makes it always-on

A single command runs the whole loop, and a small installer schedules it.

### One tick — `runtime supervise`

```bash
# Preview a tick (dry-run is the default — touches nothing):
agentic-os runtime supervise --root ~/agentic_os

# Run a real tick (commit effects):
agentic-os runtime supervise --root ~/agentic_os --apply
```

`runtime supervise` composes the surface in order — heartbeats → schedules →
watch-sources → events → run-queue — then a read-only health check, printing an
auditable per-step report (`ok`, `health_ok`, and a summary per step). Each step
is **isolated**: if one subsystem raises, the tick records it, continues the rest,
and the command exits 1 so a scheduler can alert.

### Schedule it — `install-scheduler.sh`

```bash
# Preview what would be installed (dry-run; changes nothing):
bash installers/install-scheduler.sh --root ~/agentic_os --interval-minutes 15

# Install the background driver:
bash installers/install-scheduler.sh --root ~/agentic_os --interval-minutes 15 --apply

# Remove it later:
bash installers/install-scheduler.sh --uninstall --apply
```

On macOS this writes a **launchd agent** to `~/Library/LaunchAgents/` (rendered from
`templates/runtime/supervisor.launchd.plist.template`); on other platforms it adds a
**crontab line**. Either way it calls `runtime supervise --apply` on the cadence,
logging to `shared_factory/06-runs-and-logs/supervisor.{out,err}.log`. It is
**dry-run by default and never auto-installed** — turning on a background agent is a
deliberate, per-host choice.

> **Manual fallback:** run `runtime supervise --apply` by hand, or wire it into any
> scheduler you prefer. The registry, queue, and log contracts are stable.

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
