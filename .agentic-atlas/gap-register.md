# Gap Register — Designed-but-not-running, missing services, health

> **What this is:** the honest delta between what the OS *describes* and what it
> *does* today, established by running the CLI (see
> [`validation/RESULTS.md`](validation/RESULTS.md)) and reading the source. Each
> gap has evidence, impact, and a recommendation. Items here feed
> [`backlog.md`](backlog.md). Last validated: 2026-05-28 (60/60 tests pass; 45/45
> commands functional).

Severity: **S1** blocks the "running OS" promise · **S2** materially limits value ·
**S3** polish / friction.

---

## A. Always-on runtime — the headline gap (S1)

**The OS has a full runtime *surface* but no runtime *process*.** `runtime`,
`heartbeat`, `schedule`, `watch-source`, `event process-due`, and `runtime
run-next` all exist and work, but every one is **manual / dry-run-by-default**.
Nothing executes them on a cadence.

- **Evidence:** `grep -rniE 'cron|launchd|systemd|daemon|apscheduler'` over `src/`
  and `installers/` returns nothing. `spec/product-spec.md` non-goals: *"does not
  execute automations, schedule jobs, or manage long-running state."* The runtime
  commands default to `--dry-run`; effects need explicit `--apply`.
- **Impact:** heartbeats don't beat, schedules don't fire, sources aren't polled,
  queued runs aren't dispatched, chain reactions don't process — unless a human
  types the command. "Always-on" is currently "on-demand."
- **Recommendation:** ship a thin **supervisor** (launchd plist on macOS / systemd
  unit / cron) that periodically runs, in order: `heartbeat run … --apply`,
  `schedule run-due --apply`, `watch-source run-due --apply`, `event process-due --apply`,
  `runtime run-next --apply`, then `doctor`. Provide an installer
  (`installers/install-scheduler.sh`) and a `agentic-os runtime supervise` dry-run
  planner. This is the single highest-leverage item to make the OS "live."

---

## B. Control plane (Notion) is plan-only (S2)

- **Evidence:** `notion plan-sync` builds a reviewable plan (OK). `notion sync /
  bootstrap / track-runtime` are guarded and require a verified workspace + parent
  page; `spec` V1 explicitly *"does not call the Notion API."*
- **Impact:** the human cockpit (dashboards, approvals, status) is designed but not
  live; approvals still happen in files, not Notion.
- **Recommendation:** wire a real Notion adapter behind the existing guard rails
  (verified-workspace + parent-page checks already exist). Keep files
  authoritative; Notion remains a projection. Honor the Genome's-Notion
  destination rule. Gate live writes behind `--apply` + workspace verification.

---

## C. No monitored health — only point-in-time doctors (S2)

- **Evidence:** excellent *breadth* of health checks — `doctor`, `runtime doctor`,
  `chain doctor`, `integration doctor`, `connected-system doctor`, `heartbeat
  doctor`, `config doctor` — but each is a one-shot CLI call. No aggregation, no
  scheduled run, no alerting.
- **Impact:** drift and failures are invisible until someone runs a doctor.
- **Recommendation:** add `agentic-os doctor --all` that fans across every
  subsystem doctor and returns one health report (ok/findings per subsystem);
  have the supervisor (Gap A) run it each tick and write a health scorecard +
  emit an event on regression.

---

## D. Schemas authored but not enforced by `validate` (S2)

- **Evidence:** `schemas/` contains 18 JSON/YAML schemas (workflow, automation,
  domain, run, registries, update-grant…), but `validate.py` references neither
  `jsonschema` nor `schemas/`. `spec/cli-spec.md`: *"Full schema enforcement … is
  future work."* Workflow/automation readiness *is* checked by their own ops, but
  generic structured-file validation is not wired in.
- **Impact:** malformed runtime YAML (heartbeats, schedules, chain rules, events)
  can pass `validate` and fail later at use.
- **Recommendation:** add `jsonschema` enforcement to `validate` (and/or a
  `validate --strict` mode) that loads `schemas/` and checks every structured file
  it can map. Cheap, high-confidence safety win.

---

## E. Metrics layer is templates only (S2)

- **Evidence:** the roadmap (`spec/running-os-roadmap.md`, phase 10) lists
  `agentic-os metrics refresh`, and every domain scaffolds `07-metrics/baselines.md`
  + `scorecards.md` — but `grep metrics src/.../cli.py` is empty. No `metrics`
  command exists.
- **Impact:** workflow quality, automation safety, cycle time, and cleanup health
  are not measured; the OS can't show it's improving.
- **Recommendation:** build `agentic-os metrics refresh` to compute scorecards from
  run logs, doctor findings, and automation maturity, writing `07-metrics/`.

---

## F. Integrations & connected sources are contracts, not connections (S2)

- **Evidence:** `integration {list,setup,doctor}` and `connected-system` /
  `watch-source` manage registries and check *contracts*; `setup` is dry-run /
  record-only. There is no live API client or polling loop, and secrets are
  out of scope (`spec`: *"does not store secrets"*; only a
  `composio-debug-bundle.env.example` exists).
- **Impact:** "connected" sources aren't actually polled; integrations aren't live.
- **Recommendation:** define a secrets contract (env/keychain, never in-repo), then
  implement real adapters for the first one or two sources (GitHub, Slack) behind
  the existing registry + doctor scaffolding, driven by the supervisor (Gap A).

---

## G. Runtime state plane (database) is future (S2, by design)

- **Evidence:** all state is files; layer ⑤ (DB/queue) is explicitly future
  (`spec/data-model.md` defines the eventual tables: domains, inbound_items,
  work_items, runs, state_transitions, approvals, artifacts, external_refs).
- **Impact:** acceptable for V1; file-based event ledger + run-queue will strain at
  high message volume / concurrent writers (no locking/replay/dedupe beyond
  idempotency keys).
- **Recommendation:** keep files for V1. Document the trigger conditions (from
  `data-model.md`) for introducing the DB so the migration isn't premature.

---

## H. Install & onboarding friction (S3)

- **Evidence:** `agentic-os` is not on `PATH` after `pip install -e .` unless the
  venv is active; no `pipx` path documented. First-time users hit "command not
  found" (this reviewer did).
- **Impact:** avoidable onboarding stumble.
- **Recommendation:** document `pipx install` (or a wrapper on PATH); add a
  one-line "activate or use `.venv/bin/agentic-os`" note to the README quick start.

---

## I. Routing low-confidence threshold may be aggressive (S3)

- **Evidence:** `here route "update the launch project"` from inside a domain that
  *has* a `launch` project still exited 2 ("routing confidence is low: no domain or
  project matched"). The refusal guardrail is correct; the threshold/matching may
  be stricter than ideal.
- **Impact:** valid requests can be refused, pushing users to specify explicitly.
- **Recommendation:** review `routing.detect_from_request` matching (token overlap
  vs. exact); consider returning the best low-confidence candidate *as a
  suggestion* rather than a hard refusal.

---

## J. Services that SHOULD run for a "running OS" (summary)

| Service | Purpose | Today | Target |
| --- | --- | --- | --- |
| **Scheduler/supervisor** | tick heartbeats, schedules, polling, queue dispatch, chain processing | ❌ none | launchd/systemd/cron (Gap A) |
| **Notion sync job** | project files → cockpit | ⚠️ plan-only | `notion sync --apply` on cadence (Gap B) |
| **Health monitor** | aggregate doctors, alert on regression | ⚠️ manual one-shots | `doctor --all` each tick (Gap C) |
| **Backup job** | snapshot installed OS | ⚠️ `backup run` manual + needs grant | scheduled `backup run --apply` |
| **Metrics refresh** | scorecards from runs | ❌ none | `metrics refresh` (Gap E) |
| **Source pollers** | pull GitHub/Slack/etc. events | ⚠️ registry + doctor only | live adapters (Gap F) |

---

See [`backlog.md`](backlog.md) for the prioritized, actionable version of these.
