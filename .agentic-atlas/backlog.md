# Backlog — Features / Fixes / Upgrades

> **What this is:** the prioritized, actionable inventory of work, built while
> taking stock of the system (running the CLI, reading the source, mapping gaps).
> Each item links to its evidence in [`gap-register.md`](gap-register.md). This is
> a living file — append as new findings land. IDs are stable; don't renumber.
>
> **Type:** 🟩 feature · 🟦 fix · 🟪 upgrade/refactor · 📄 docs
> **Priority:** P0 ship-blocker for "running OS" · P1 high value · P2 polish
> **Status:** `todo` · `in-progress` · `done` · `deferred`

---

## P0 — Make the OS actually run

| ID | Type | Item | Why | Gap | Status |
| --- | --- | --- | --- | --- | --- |
| F-001 | 🟩 | **Scheduler/supervisor** (launchd/cron) that ticks the runtime surface | Without it, "always-on" is on-demand; nothing fires by itself | [A](gap-register.md#a-always-on-runtime--the-headline-gap-s1) | **done** — `installers/install-scheduler.sh` renders a launchd agent (macOS) / crontab line that runs `runtime supervise --apply` on a cadence; dry-run by default, `--uninstall` supported. *Not auto-installed — operator runs it per host.* |
| F-002 | 🟩 | **`agentic-os runtime supervise`** — a dry-run planner + single-tick executor the supervisor calls | Gives one auditable entrypoint for the loop; testable without a daemon | **done** — `src/genomes_agentic_os/supervisor.py` composes heartbeats → schedules → watch-sources → events → run-queue + read-only health; dry-run default; isolated steps; 3 tests in `tests/test_runtime_supervise.py`. |
| F-003 | 🟩 | **`agentic-os doctor --all`** — aggregate every subsystem doctor into one health report; emit event on regression | Turns point-in-time checks into monitorable health | [C](gap-register.md#c-no-monitored-health--only-point-in-time-doctors-s2) | todo |
| F-004 | 🟩 | **Project work lifecycle + conversation auto logging** — promote feature-style markdown tracking into every project and write redacted transcript/tool-call sidecars to the routed work item | Agents need a durable path from idea to spec to build to validation to documented closeout; otherwise the OS still depends on chat memory | [K](gap-register.md#k-project-work-lifecycle-and-conversation-evidence-are-not-first-class-s1) | todo |

## P1 — Close the value gaps

| ID | Type | Item | Why | Gap | Status |
| --- | --- | --- | --- | --- | --- |
| F-010 | 🟩 | **Live Notion adapter** behind existing workspace/parent-page guards (`notion sync --apply`) | The human control plane is designed but not live | [B](gap-register.md#b-control-plane-notion-is-plan-only-s2) | todo |
| F-011 | 🟦 | **Schema enforcement in `validate`** — load `schemas/` (jsonschema) and check structured files; add `validate --strict` | 22 schemas exist but nothing enforces them; malformed YAML passes today | [D](gap-register.md#d-schemas-authored-but-not-enforced-by-validate-s2) | todo |
| F-012 | 🟩 | **`agentic-os metrics refresh`** — compute scorecards/baselines from run logs, doctor findings, automation maturity | 07-metrics is templates only; OS can't show it's improving | [E](gap-register.md#e-metrics-layer-is-templates-only-s2) | todo |
| F-013 | 🟩 | **First live source adapters** (GitHub, Slack) + a **secrets contract** (env/keychain, never in-repo) | "Connected" sources aren't actually polled | [F](gap-register.md#f-integrations--connected-sources-are-contracts-not-connections-s2) | todo |
| F-014 | 🟦 | **Tune routing low-confidence threshold** — return best candidate as a suggestion instead of hard refusal; revisit `detect_from_request` matching | Valid requests get refused (e.g. a request naming an existing project) | [I](gap-register.md#i-routing-low-confidence-threshold-may-be-aggressive-s3) | todo |

## P2 — Polish & onboarding

| ID | Type | Item | Why | Gap | Status |
| --- | --- | --- | --- | --- | --- |
| F-020 | 📄 | **Install ergonomics** — document `pipx install` / PATH wrapper; quick-start note that bare `agentic-os` needs the venv | First-run "command not found" friction | [H](gap-register.md#h-install--onboarding-friction-s3) | todo |
| F-021 | 🟪 | **Friendlier name errors** — when a hyphenated name is rejected, suggest the snake_case form (`weekly-report` → `weekly_report`) | Small UX win; the rule is currently a flat rejection | — | todo |
| F-022 | 🟩 | **`run-log create` discoverability** — surface it in routing/here output and docs (it's required before `run-log close` but easy to miss) | Closeout depends on a create step users don't see | — | todo |
| F-023 | 🟪 | **DB plane trigger doc** — record the explicit conditions (from `spec/data-model.md`) for introducing the runtime database | Prevent premature/over-late migration off files | [G](gap-register.md#g-runtime-state-plane-database-is-future-s2-by-design) | todo |

---

## Notes for whoever picks these up

- **Validate first, always.** Re-run `bash .agentic-atlas/tools/validate-cli.sh`
  and `.venv/bin/python -m pytest -q` before and after. Baseline: 53 commands
  OK (2 intentional guardrail exits), 97/97 tests pass.
- **Match the architecture.** New commands follow the §9 recipe in
  [`architecture/system-architecture.md`](architecture/system-architecture.md):
  parser + thin handler in `cli.py`, logic in a `*_ops.py`, template in
  `templates/`, schema in `schemas/`, registry entry in `capability_registry.py`,
  test in `tests/`.
- **Keep effects dry-run-by-default.** Anything touching an external system or the
  real `~/agentic_os` must require `--apply`.
- **Files stay authoritative.** Notion and any future DB are projections.
