# Genome's Agentic OS — CLI Command Reference

> Authoritative reference for `agentic-os`. Generated from
> `src/genomes_agentic_os/cli.py` (argparse) plus the receipts written by
> `docs/architecture/tools/validate-cli.sh` (statuses and real output).
> Do NOT edit manually — re-derive from those sources.

---

## 1. Conventions

| Convention | Rule |
|---|---|
| **Name format** | `snake_case` only: lowercase letters, digits, underscores. Hyphens are rejected. `weekly-report` fails; use `weekly_report`. |
| **`--root` default** | `~/agentic_os`. Always pass `--root` explicitly in scripts; never rely on the default. |
| **Exit 0** | Success |
| **Exit 1** | Health check "not ok" (doctor / validate) |
| **Exit 2** | argparse usage error OR deliberate handled refusal (e.g. `here route` when routing confidence is low; `config install` when blocked by conflicts) |
| **Dry-run default** | Several mutating commands default to `--dry-run`. Pass `--apply` to commit changes. Affected: `runtime run-next`, `run-queue prune`, `schedule run-due`, `event process-due`, `event replay`, `backup run`, `heartbeat run`, `update pull`, `integration setup`, `watch-source poll`, `watch-source run-due`, `notion sync`, `notion bootstrap`, `notion track-runtime`, `config install`, `config install-tree`. |
| **`backup run` prerequisite** | Requires `update register` first (generates an update grant). |
| **`run-log close --status done`** | Requires `--validation` evidence; missing evidence is a guardrail, not a crash. |
| **`config` subcommands** | `install`, `install-tree`, and `doctor`. No `config layers` subcommand exists. |
| **Automation maturity levels** | `observe`, `prepare`, `propose`, `execute_approved`, `execute_guarded` |
| **Config layers** | `agentic_os_root`, `automation`, `customer_os_root`, `domain_or_lane`, `global_harness`, `project`, `workflow_or_task` |

---

## 2. Core lifecycle: `init` / `validate` / `doctor` / `docs`

### `init`

Create the base installed OS tree (and optionally a profile-first layout).

| Arg / Flag | Required | Description |
|---|---|---|
| `--target` | No (default: `~/agentic_os`) | Destination path for the new OS root |
| `--profile` | No | Room-first OS profile YAML; activates profile install path |
| `--projects-source` | No | Deprecated compatibility flag; project repository links live under domain project folders |
| `--include-legacy-agent` | No | Also create `AGENT.md` compatibility shims for harnesses requiring that exact filename |

Writes: full OS directory tree at `--target`.

```bash
agentic-os init --target /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `validate`

Validate an installed OS root for structural correctness. Exits 1 on errors, 0 on success (warnings go to stderr).

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No (default: `~/agentic_os`) | Installed OS root path |

Reads: directory tree at `--root`. Writes: nothing.

```bash
agentic-os validate --root /tmp/aos-ref
```

Real output (success):
```text
valid: /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `doctor`

Run installed OS health checks. Optionally create missing managed files.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No (default: `~/agentic_os`) | Installed OS root path |
| `--fix-missing` | No | Create missing managed files without overwriting existing ones |

Reads: OS root. Writes: missing managed files (when `--fix-missing`).

```bash
agentic-os doctor --root /tmp/aos-ref
agentic-os doctor --root /tmp/aos-ref --fix-missing
```

Status: **OK** (rc 0)

---

### `docs install`

Install runtime templates, manual, commands, skills, and plan assets.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No (default: `~/agentic_os`) | Installed OS root path |

Writes: docs assets to the OS root.

```bash
agentic-os docs install --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `docs update`

Add missing runtime assets without overwriting local edits (additive only).

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No (default: `~/agentic_os`) | Installed OS root path |

```bash
agentic-os docs update --root /tmp/aos-ref
```

Status: not individually validated; same handler as `docs install`.

---

## 3. Domains, projects & routing: `domain` / `project` / `route` / `context` / `here`

### `domain create`

Create a domain scaffold (numbered sub-directories + context files).

| Arg / Flag | Required | Description |
|---|---|---|
| `name` | Yes | Domain slug (snake_case) |
| `--root` | No | Installed OS root path |
| `--include-legacy-agent` | No | Also create `AGENT.md` shims |

Writes: `<root>/<name>/` tree with `README.md`, `ROUTER.md`, `AGENTS.md`, `CLAUDE.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`, `REFERENCES.md`, `domain.yml`, numbered subdirs 00–08.

```bash
agentic-os domain create acme --root /tmp/aos-ref
```

Real output (excerpt):
```text
created: /tmp/aos-ref/acme
created: /tmp/aos-ref/acme/README.md
created: /tmp/aos-ref/acme/domain.yml
...
```

Status: **OK** (rc 0)

---

### `project create`

Create a project scaffold inside a domain.

| Arg / Flag | Required | Description |
|---|---|---|
| `domain` | Yes | Domain slug |
| `project` | Yes | Project slug (snake_case) |
| `--root` | No | Installed OS root path |
| `--repo` | No | Repository path or URL |
| `--notion` | No | Notion page, database, or URL |
| `--jira` | No | Jira project, issue, or URL |
| `--status` | No (default: `active`) | One of: `active`, `waiting`, `blocked`, `done` |
| `--lane` | No | Primary operating lane for this project |

Writes: `<root>/<domain>/02-projects/<project>/` with `project.yml`, `status.md`, `decisions.md`, `source-map.md`, `AGENTS.md`, `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`, `MEMORY.md`, `config/*.yml`, `ideas/`, `work-items/01-intake/`, `work-items/02-active/`, `work-items/03-complete/`, `worktrees/`, and `artifacts/`; creates `src` when `--repo` is a local path; updates domain `README.md` and `active-work.md`.

```bash
agentic-os project create acme launch --root /tmp/aos-ref \
  --repo https://github.com/example/launch --status active
```

Status: **OK** (rc 0)

---

### `project onboard`

Create or repair the project-local agent/config surface for an existing project.

| Arg / Flag | Required | Description |
|---|---|---|
| `domain` | Yes | Domain slug |
| `project` | Yes | Project slug (snake_case) |
| `--root` | No | Installed OS root path |

Writes missing project-local `AGENTS.md`, `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`, `MEMORY.md`, `config/*.yml`, `ideas/`, `work-items/01-intake/`, `work-items/02-active/`, `work-items/03-complete/`, `worktrees/`, and `config.toml`. Existing local edits are preserved unless the file is an older generic scaffold.

```bash
agentic-os project onboard acme launch --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `project work-item create`

Capture a project-known idea or create a lifecycle packet under the configured
project work-item lanes.

| Arg / Flag | Required | Description |
|---|---|---|
| `domain` | Yes | Domain slug |
| `project` | Yes | Project slug (snake_case) |
| `--title` | Yes | Work item title |
| `--summary` | Yes | Raw idea, scope, or next-step summary |
| `--work-id` | No | Optional slug; the command adds the next `NNN_` index when absent |
| `--status` | No (default: `captured`) | One of the lifecycle states |
| `--format` | No | `markdown` or `packet`; captured/triaged ideas default to markdown |
| `--root` | No | Installed OS root path |

Writes default intake to
`<project>/work-items/01-intake/NNN_slug.md`. With `--format packet`, writes
`<project>/work-items/01-intake/NNN_slug/`. Active states write packet folders
under `work-items/02-active/`; complete states write packet folders under
`work-items/03-complete/`.

```bash
agentic-os project work-item create acme launch --root /tmp/aos-ref \
  --title "Build logger" --summary "Auto-log agent conversations."
```

Status: **OK** (rc 0)

---

### `project worktree add`

Register an existing local git worktree as a visible project link and routing target.

| Arg / Flag | Required | Description |
|---|---|---|
| `domain` | Yes | Domain slug |
| `project` | Yes | Project slug (snake_case) |
| `name` | Yes | Visible worktree name (snake_case) |
| `--path` | Yes | Existing worktree directory to link |
| `--root` | No | Installed OS root path |
| `--force` | No | Replace an existing worktree symlink that points elsewhere |

Writes: `<project>/worktrees/<name>` as a symlink, updates `<project>/worktrees/index.yml`, and mirrors the registered list into `<project>/config/worktrees.yml`. Cwd-aware routing treats the real worktree path as part of the project.

```bash
agentic-os project worktree add acme launch source_worktree \
  --root /tmp/aos-ref --path /tmp/source-worktree
```

Status: **OK** (rc 0)

---

### `project worktree cleanup-closed`

Move registered worktrees with cached terminal Jira state, merged PR state, or
terminal worktree status out of active registries and into `worktrees/closed.yml`.
Dry-run by default; file removal is opt-in and only removes clean checkouts
inside the project `worktrees/` directory.

| Arg / Flag | Required | Description |
|---|---|---|
| `--domain` | No | Limit cleanup to one domain |
| `--project` | No | Limit cleanup to one project |
| `--root` | No | Installed OS root path |
| `--dry-run` | No (default) | Preview candidates without writing |
| `--apply` | No | Move matching registry entries to `worktrees/closed.yml` |
| `--remove-files` | No | Also remove clean in-project checkout directories |

Reads: `<project>/config/worktrees.yml` and `<project>/worktrees/index.yml`.
Writes: `<project>/worktrees/closed.yml`, the source worktree registry, and the
root active-work symlink container when `--apply` is used.

```bash
agentic-os project worktree cleanup-closed --root /tmp/aos-ref --dry-run
agentic-os project worktree cleanup-closed --root /tmp/aos-ref --apply --remove-files
```

Status: **OK** (unit-tested; rc 0)

---

### `project link-source` / `project src`

Create or repair a project-scoped `src` symlink to a local repository.

| Arg / Flag | Required | Description |
|---|---|---|
| `domain` | Yes | Domain slug |
| `project` | Yes | Project slug (snake_case) |
| `--root` | No | Installed OS root path |
| `--repo` | No | Local repository path; defaults to `project.yml` `sources.repo` |
| `--force` | No | Replace an existing `src` symlink that points elsewhere |

Writes: `<root>/<domain>/02-projects/<project>/src`, and updates `project.yml` plus `source-map.md` when `--repo` is supplied. Remote repository URLs are rejected because `src` must be a filesystem symlink.

```bash
agentic-os project link-source acme launch --root /tmp/aos-ref --repo /tmp/source-repo
agentic-os project src acme launch --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `route`

Route a request string to a domain, project, or workflow. Outputs a formatted routing packet.

| Arg / Flag | Required | Description |
|---|---|---|
| `request` | Yes | Free-text request to route |
| `--root` | No | Installed OS root path |

Reads: OS routing tables. Writes: nothing.

```bash
agentic-os route "draft blog post for launch" --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `context build`

Build a deterministic context packet for a domain (and optionally project/workflow/lane).

| Arg / Flag | Required | Description |
|---|---|---|
| `--domain` | Yes | Domain slug |
| `--project` | No | Project slug |
| `--workflow` | No | Workflow slug |
| `--lane` | No | Lane slug |
| `--root` | No | Installed OS root path |

Reads: domain/project/workflow context files. Writes: nothing.

```bash
agentic-os context build --domain acme --root /tmp/aos-ref
agentic-os context build --domain acme --project launch --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `context explain`

Resolve a workflow or automation `context-contract.yml` and print inherited
sources, local/deferred files, exclusions, skipped duplicates, capabilities,
provider routes, and provenance.

| Arg / Flag | Required | Description |
|---|---|---|
| `--path` | One target form | Workflow or automation folder |
| `--domain`, `--lane`, `--workflow` | One target form | Identify a workflow |
| `--domain`, `--lane`, `--automation` | One target form | Identify an automation |
| `--root` | No | Installed OS root path |

Writes: nothing.

### `context check`

Validate managed context manifests and report legacy fallbacks plus exact copied
contract hashes. High-volume evidence trees are not scanned.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |

Writes: nothing. Invalid manifests exit 1.

### `context compact`

Build or apply a guarded, reversible migration plan.

| Arg / Flag | Required | Description |
|---|---|---|
| `--dry-run` | One mode | Build a plan; context files are never changed |
| `--apply` | One mode | Apply a reviewed plan with automatic rollback |
| `--output-dir` | Dry-run only | Write plan and review rollback JSON |
| `--target` | Legacy promotion | Repeatable managed workflow/automation path; bounds the plan |
| `--migration` | Named dry-run | Enabled, approved batch from the installed context-migrations registry; mutually exclusive with ad hoc targets and policy flags |
| `--promote-legacy` | No | With explicit targets, create manifests and promote exact contracts to the lane |
| `--baseline-validation` | No | Hash full validation drift and reject new errors during apply |
| `--plan` | Apply only | Reviewed plan JSON produced by `--dry-run` |
| `--receipt-dir` | Apply only | Durable destination for the apply receipt |
| `--root` | No | Installed OS root path |

Without either mode, exits 2. Apply enforces hashes, inherited-source identity,
at least 40% local-context reduction, semantic parity, and root validation.
Named plans also pin the registry and selected-profile digests.

### `context restore`

Restore exact pre-compaction bytes from an applied receipt. Restore rejects a
root whose post-apply context hash changed, so it cannot overwrite newer work.

| Arg / Flag | Required | Description |
|---|---|---|
| `--receipt` | Yes | Applied context-compaction receipt JSON |
| `--root` | No | Installed OS root path |

---

### `here route`

Route a request from the current working directory (cwd-aware routing). Exits 2 when routing confidence is low — this is a deliberate guardrail, not a crash.

| Arg / Flag | Required | Description |
|---|---|---|
| `request` | Yes | Free-text request to route |
| `--root` | No | Installed OS root path |

Reads: cwd, OS routing tables. Writes: nothing.

```bash
agentic-os here route "what should I work on next" --root /tmp/aos-ref
```

Status: **GUARDED** (rc 2 — "routing confidence is low" when cwd does not map to a known domain/project)

---

### `here context build`

Build context packet from the current working directory.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |

```bash
agentic-os here context build --root /tmp/aos-ref
```

Status: not individually validated in RESULTS.md.

---

## 4. Workflows, automations & run logs: `workflow` / `automation` / `run-log`

### `workflow create`

Create a workflow scaffold inside a domain lane.

| Arg / Flag | Required | Description |
|---|---|---|
| `domain` | Yes | Domain slug |
| `lane` | Yes | Lane slug (e.g. `engineering`, `support`) |
| `name` | Yes | Workflow slug (snake_case) |
| `--root` | No | Installed OS root path |

Writes: `<root>/<domain>/03-workflows/<lane>/<name>/` with `workflow.md`, `alignment-questions.md`, `examples/`, `runs/`.

```bash
agentic-os workflow create acme engineering launch_blog --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `workflow check`

Check workflow readiness (validates required files and placeholder resolution).

| Arg / Flag | Required | Description |
|---|---|---|
| `domain` | Yes | Domain slug |
| `lane` | Yes | Lane slug |
| `workflow` | Yes | Workflow slug |
| `--root` | No | Installed OS root path |

Reads: workflow directory. Writes: nothing (emits YAML findings).

```bash
agentic-os workflow check acme engineering launch_blog --root /tmp/aos-ref
```

Real output (excerpt):
```text
findings:
- severity: blocker
  path: .../launch_blog/state-machine.md
  message: required workflow file is missing
- severity: fix-soon
  path: .../launch_blog/alignment-questions.md
  message: 'section has unresolved placeholders: Dispatch Decision'
```

Status: **OK** (rc 0, findings reported but exit is 0)

---

### `automation create`

Create an automation scaffold inside a domain lane.

| Arg / Flag | Required | Description |
|---|---|---|
| `domain` | Yes | Domain slug |
| `lane` | Yes | Lane slug |
| `name` | Yes | Automation slug (snake_case) |
| `--root` | No | Installed OS root path |

Writes: `<root>/<domain>/04-automations/<lane>/<name>/` scaffold.

```bash
agentic-os automation create acme support ticket_intake --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `automation check`

Check automation maturity readiness against its current maturity level.

| Arg / Flag | Required | Description |
|---|---|---|
| `domain` | Yes | Domain slug |
| `lane` | Yes | Lane slug |
| `automation` | Yes | Automation slug |
| `--root` | No | Installed OS root path |

```bash
agentic-os automation check acme support ticket_intake --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `automation attach`

Attach an automation to a project.

| Arg / Flag | Required | Description |
|---|---|---|
| `domain` | Yes | Domain slug |
| `lane` | Yes | Lane slug |
| `automation` | Yes | Automation slug |
| `--project` | Yes | Project slug to attach to |
| `--root` | No | Installed OS root path |

```bash
agentic-os automation attach acme support ticket_intake --project launch --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `automation set-maturity`

Set the maturity level for an automation.

| Arg / Flag | Required | Description |
|---|---|---|
| `domain` | Yes | Domain slug |
| `lane` | Yes | Lane slug |
| `automation` | Yes | Automation slug |
| `level` | Yes | One of: `observe`, `prepare`, `propose`, `execute_approved`, `execute_guarded` |
| `--root` | No | Installed OS root path |

```bash
agentic-os automation set-maturity acme support ticket_intake prepare --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `run-log create`

Create a timestamped run log for a domain workflow or automation.

| Arg / Flag | Required | Description |
|---|---|---|
| `domain` | Yes | Domain slug |
| `workflow_or_automation` | Yes | Workflow or automation slug |
| `--root` | No | Installed OS root path |

Writes: dated run log file under `<domain>/06-runs-and-logs/runs/`.

```bash
agentic-os run-log create acme launch_blog --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `run-log close`

Close a run log with audit evidence. `--status done` requires `--validation` evidence.

| Arg / Flag | Required | Description |
|---|---|---|
| `domain` | Yes | Domain slug |
| `run_id` | Yes | Run log ID (timestamped slug, e.g. `20260529T005116Z-acme-launch_blog`) |
| `--status` | Yes | One of: `done`, `waiting`, `failed`, `needs_approval` |
| `--summary` | No (default: `""`) | Free-text summary |
| `--validation` | No (repeatable) | Evidence of validation (required for `done`) |
| `--artifact` | No (repeatable) | Artifact path or URL |
| `--approval` | No (repeatable) | Approval reference |
| `--next-action` | No (default: `""`) | Next action description |
| `--owner` | No (default: `"OS Owner"`) | Owner label |
| `--learning` | No (default: `""`) | Learning to promote from this run |
| `--project` | No | Project slug whose `status.md` to update on close |
| `--emit-events` | No | Emit OS events on close |
| `--root` | No | Installed OS root path |

```bash
agentic-os run-log close acme 20260529T005116Z-acme-launch_blog \
  --status done \
  --validation "manual test passed" \
  --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

## 5. Profiles & rooms: `profile` / `room`

### `profile create`

Create an editable profile template YAML.

| Arg / Flag | Required | Description |
|---|---|---|
| `--target` | Yes | Path to write the profile template |

Writes: profile YAML template at `--target`.

```bash
agentic-os profile create --target /tmp/aos-ref/my-profile.yml
```

Status: **OK** (rc 0)

---

### `profile validate`

Validate a room-first profile YAML.

| Arg / Flag | Required | Description |
|---|---|---|
| `profile` | Yes (positional) | Path to the profile YAML file |

Reads: profile YAML. Writes: nothing.

```bash
agentic-os profile validate /tmp/aos-ref/my-profile.yml
```

Status: **OK** (rc 0)

---

### `room create`

Create a room scaffold (a domain-like directory without full domain context).

| Arg / Flag | Required | Description |
|---|---|---|
| `room_slug` | Yes | Room slug (snake_case) |
| `--root` | No | Installed OS root path |

```bash
agentic-os room create personal --root /tmp/aos-ref
```

Status: not individually validated in RESULTS.md.

---

### `room update`

Update a room from a profile (additive; applies profile layout to the room).

| Arg / Flag | Required | Description |
|---|---|---|
| `room_slug` | Yes | Room slug |
| `--root` | No | Installed OS root path |
| `--from-profile` | Yes | Path to the profile YAML to apply |

```bash
agentic-os room update personal --from-profile /tmp/aos-ref/my-profile.yml --root /tmp/aos-ref
```

Status: not individually validated in RESULTS.md.

---

## 6. Runtime / always-on: `runtime` / `run-queue` / `heartbeat` / `schedule` / `integration`

### `runtime init`

Initialize the runtime registry (creates queue, schedule, and tracking manifests).

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |

Writes: runtime registry files.

```bash
agentic-os runtime init --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `runtime doctor`

Check runtime registry health.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |

Exits 1 if not ok, 0 if ok.

```bash
agentic-os runtime doctor --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `runtime run-next`

Dispatch the next safe queued runtime item. Dry-run by default.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |
| `--item-id` | No | Specific queue item ID to inspect or dispatch |
| `--dry-run` | No (default) | Preview only, no dispatch |
| `--apply` | No | Actually dispatch the item |

Exits 1 on failed/blocked status when `--apply`. Reads/Writes: runtime queue.

```bash
agentic-os runtime run-next --root /tmp/aos-ref --dry-run
agentic-os runtime run-next --root /tmp/aos-ref --apply
```

Status: **OK** (rc 0, dry-run mode)

---

### `run-queue prune`

Prune stale runtime queue rows and old `run-queue.yml.backup*` files. Dry-run by default. `runtime prune` is an alias for the same handler.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |
| `--active-max-age-hours` | No | Prune queued/running/approval-needed rows older than this many hours; default 24 |
| `--terminal-max-age-days` | No | Prune done rows older than this many days; default 2 |
| `--failed-max-age-days` | No | Prune failed/blocked rows older than this many days; default 7 |
| `--skipped-max-age-days` | No | Prune skipped/dry-run rows older than this many days; default 1 |
| `--backup-max-age-days` | No | Remove run-queue backup files older than this many days; default 7 |
| `--archive` / `--no-archive` | No | Archive full pruned items under `shared_factory/06-runs-and-logs/run-queue-prune/`; default archive |
| `--dry-run` | No (default) | Preview only, no queue rewrite or backup removal |
| `--apply` | No | Rewrite the queue and remove stale backup files |

Reads/Writes: runtime queue, run-queue-prune archive logs, stale run-queue backup files.

```bash
agentic-os run-queue prune --root /tmp/aos-ref --dry-run
agentic-os run-queue prune --root /tmp/aos-ref --apply
agentic-os runtime prune --root /tmp/aos-ref --dry-run
```

Status: **OK** (rc 0, dry-run mode)

---

### `runtime supervise`

Run one supervisor tick across the whole runtime surface — heartbeats → schedules → watch-sources → events → run-queue — then a read-only health check. Dry-run by default. This is the single command an external scheduler calls (`installers/install-scheduler.sh`).

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |
| `--dry-run` | No (default) | Preview the tick; touches nothing |
| `--apply` | No | Commit each step's effects |

Steps are isolated — one failing subsystem does not abort the tick. Exits 1 if any mutating step raises. Reads/Writes: composes the runtime/event/source subsystems; health is read-only. Impl: `src/genomes_agentic_os/supervisor.py`.

```bash
agentic-os runtime supervise --root /tmp/aos-ref            # dry-run
agentic-os runtime supervise --root /tmp/aos-ref --apply    # real tick
```

Status: **OK** (rc 0; rc 1 only if a step raises)

---

### `heartbeat list`

List all configured heartbeats in the runtime registry.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |

```bash
agentic-os heartbeat list --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `heartbeat run`

Run (or dry-run) a specific heartbeat. Dry-run by default.

| Arg / Flag | Required | Description |
|---|---|---|
| `heartbeat_id` | Yes | Heartbeat ID |
| `--root` | No | Installed OS root path |
| `--dry-run` | No (default) | Preview only |
| `--apply` | No | Execute the heartbeat |

```bash
agentic-os heartbeat run daily_summary --root /tmp/aos-ref --dry-run
```

Status: **OK** (rc 0, heartbeat list validated)

---

### `heartbeat doctor`

Check runtime heartbeat health. Note: delegates to the same handler as `runtime doctor`.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |

Exits 1 if not ok.

```bash
agentic-os heartbeat doctor --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `schedule create`

Create a schedule entry in the runtime registry.

| Arg / Flag | Required | Description |
|---|---|---|
| `schedule_id` | Yes | Schedule ID (snake_case) |
| `--root` | No | Installed OS root path |
| `--cadence` | No (default: `manual`) | Cadence string (`manual`, `hourly`, `daily`, `weekly`, or a supported interval) |
| `--timezone` | No (default: `America/Chicago`) | IANA timezone name |
| `--command` | No | Command to invoke when due |

```bash
agentic-os schedule create weekly_review \
  --cadence weekly --timezone America/Chicago \
  --command "agentic-os runtime run-next --apply" \
  --root /tmp/aos-ref
```

For operator applications, pass `--dry-run --json` to preview or `--apply
--json` to write with a registry backup, mutation receipt, and readback. The
historical no-mode invocation remains an immediate create for compatibility.
Governed creates are disabled unless `--enabled` is explicit.

### Governed schedule CRUD

```bash
agentic-os schedule list --root ~/agentic_os --json
agentic-os schedule get weekly_review --root ~/agentic_os --json
agentic-os schedule update weekly_review --cadence daily --local-time 09:00 --dry-run --root ~/agentic_os --json
agentic-os schedule disable weekly_review --apply --root ~/agentic_os --json
agentic-os schedule delete weekly_review --apply --root ~/agentic_os --json
agentic-os schedule queue-now daily_agentic_os_doctor --apply --root ~/agentic_os --json
```

Updates are field-allowlisted. Delete requires a disabled schedule with no
active queue references. `queue-now` only appends a queue record and never
dispatches the command.

### Governed `resource` operations

Plan or scaffold filesystem-backed resources, or safely author registry-backed
rules, reports, skills, and commands:

```bash
agentic-os resource create workflow operator_review --domain work --lane engineering --dry-run --root ~/agentic_os --json
agentic-os resource validate workflow operator_review --domain work --lane engineering --root ~/agentic_os --json
agentic-os resource create program command_center --apply --root ~/agentic_os --json
agentic-os resource create report weekly_review --display-name "Weekly review" --description "Concise verified weekly delivery report." --prompt "Summarize verified delivery evidence." --dry-run --root ~/agentic_os --json
agentic-os resource update report weekly_review --description "Verified weekly delivery and risk report." --apply --root ~/agentic_os --json
agentic-os resource archive report weekly_review --apply --root ~/agentic_os --json
agentic-os resource rollback report weekly_review --backup-id 20260715T120000000000Z-0123abcd --dry-run --root ~/agentic_os --json
```

Supported resource kinds are `automation`, `workflow`, `program`, and
`instance-program` for scaffold create/validate, and `rule`, `report`, `skill`,
and `command` for governed list/get/create/update/archive/restore/rollback and
validation. Registry targets are fixed by scope. Mutations are dry-run first,
emit backup and receipt IDs, and verify readback. These operations never execute
the created resource or accept arbitrary paths, shell commands, or queries.

Status: **OK** (rc 0)

---

### `report`

Operate versioned `ReportDefinition`, `ReportRun`, and `ReportArtifact`
resources. `create`, `update`, `archive`, `restore`, `run-now`, and `rollback`
are dry-run by default and require `--apply` to persist.

| Subcommand | Required arguments | Important flags |
| --- | --- | --- |
| `init` | — | `--root`, `--json` |
| `query` | `definition\|run\|artifact` | `--definition-id`, `--status`, `--include-archived`, `--limit` (1-500) |
| `get` | `definition\|run\|artifact <id>` | `--root`, `--json` |
| `validate` | `--definition-file <path>` | `--root`, `--json` |
| `create` | `--definition-file <path>` | `--dry-run`, `--apply`, `--root`, `--json` |
| `update` | `<report_id> --definition-file <path>` | `--dry-run`, `--apply`, `--root`, `--json` |
| `archive` / `restore` | `<report_id>` | `--dry-run`, `--apply`, `--root`, `--json` |
| `run-now` | `<report_id>` | `--trigger`, `--project-notion`, `--notion-workspace`, `--dry-run`, `--apply` |
| `rollback` | `<receipt-relative-path>` | `--dry-run`, `--apply`, `--root`, `--json` |
| `consolidate-plan` | — | `--stale-days`, `--root`, `--json` |

```bash
agentic-os report create --definition-file report.yml --dry-run --root ~/agentic_os --json
agentic-os report run-now daily_operator_report --apply --root ~/agentic_os --json
agentic-os report query artifact --definition-id daily_operator_report --root ~/agentic_os --json
```

`run-now` executes only bounded built-in projections. It does not evaluate an
arbitrary generator command. Notion is optional and exact-workspace guarded;
projection failures remain explicit in the run and make the result partial.

Status: **OK** (covered by report engine contract tests)

---

### `schedule run-due`

Queue schedules that are currently due. Dry-run by default.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |
| `--dry-run` | No (default) | Preview which schedules are due |
| `--apply` | No | Actually enqueue due schedules |

```bash
agentic-os schedule run-due --root /tmp/aos-ref --dry-run
```

Status: **OK** (rc 0)

---

### `integration list`

List all configured integrations and their status.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |

```bash
agentic-os integration list --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `integration doctor`

Check integration health for all configured integrations.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |

```bash
agentic-os integration doctor --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `integration setup`

Dry-run or record setup for a specific integration. Dry-run by default.

| Arg / Flag | Required | Description |
|---|---|---|
| `integration_id` | Yes | Integration ID |
| `--root` | No | Installed OS root path |
| `--dry-run` | No (default) | Preview setup |
| `--apply` | No | Record the setup |

```bash
agentic-os integration setup notion --root /tmp/aos-ref --dry-run
```

Status: not individually validated in RESULTS.md.

---

## 7. Event graph & chains: `event` / `chain`

### `event append`

Append a normalized event to the file-backed event ledger.

| Arg / Flag | Required | Description |
|---|---|---|
| `--type` | Yes | Event type string (e.g. `github.pull_request.merged`) |
| `--source` | Yes | Source reference |
| `--summary` | No (default: `""`) | Event summary |
| `--correlation-id` | No | Correlation ID for tracing |
| `--root` | No | Installed OS root path |

Writes: event to ledger JSONL.

```bash
agentic-os event append \
  --type os.run.closed.done \
  --source "acme/launch" \
  --summary "run closed successfully" \
  --root /tmp/aos-ref
```

Status: not individually validated in RESULTS.md.

---

### `event list`

List recent events from the ledger.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |
| `--limit` | No (default: 20) | Max events to show |

```bash
agentic-os event list --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `event summary`

Summarize recent events and pending follow-up actions.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |
| `--limit` | No (default: 20) | Max events to consider |

```bash
agentic-os event summary --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `event process-due`

Process events matching chain rules. Dry-run or apply required (mutually exclusive, both required to choose one).

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |
| `--dry-run` | Yes (or `--apply`) | Preview matches only |
| `--apply` | Yes (or `--dry-run`) | Enqueue matched chain actions |

```bash
agentic-os event process-due --root /tmp/aos-ref --dry-run
```

Status: **OK** (rc 0)

---

### `event replay`

Replay a specific event against all chain rules.

| Arg / Flag | Required | Description |
|---|---|---|
| `event_id` | Yes | Event ID to replay |
| `--root` | No | Installed OS root path |
| `--dry-run` | Yes (or `--apply`) | Preview only |
| `--apply` | Yes (or `--dry-run`) | Apply matched chain actions |

```bash
agentic-os event replay evt_abc123 --root /tmp/aos-ref --dry-run
```

Status: not individually validated in RESULTS.md.

---

### `chain list`

List all configured chain rules.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |

```bash
agentic-os chain list --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `chain test`

Test a specific chain rule against an event file.

| Arg / Flag | Required | Description |
|---|---|---|
| `chain_rule_id` | Yes | Chain rule ID |
| `--event` | Yes | Path to event JSON/YAML file |
| `--root` | No | Installed OS root path |

```bash
agentic-os chain test feature_merged_to_docs_update \
  --event /tmp/test-event.json \
  --root /tmp/aos-ref
```

Status: not individually validated in RESULTS.md.

---

### `chain doctor`

Check chain rule safety (validates rule structure, depth limits, idempotency keys).

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |

```bash
agentic-os chain doctor --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

## 8. Connected sources: `connected-system` / `watch-source`

### `connected-system list`

List all connected systems and their selected providers.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |

```bash
agentic-os connected-system list --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `connected-system doctor`

Check health of a specific connected system.

| Arg / Flag | Required | Description |
|---|---|---|
| `system_id` | Yes | Connected system ID |
| `--root` | No | Installed OS root path |

```bash
agentic-os connected-system doctor notion_genome --root /tmp/aos-ref
```

Status: not individually validated in RESULTS.md.

---

### `watch-source list`

List all configured watch sources.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |

```bash
agentic-os watch-source list --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `watch-source create`

Create a file-backed watch source definition.

| Arg / Flag | Required | Description |
|---|---|---|
| `source_id` | Yes | Watch source ID (snake_case) |
| `--root` | No | Installed OS root path |
| `--connected-system` | No (default: `notion_genome`) | Connected system ID |
| `--source-type` | No (default: `notion_database`) | Source type |
| `--display-name` | No | Human-readable display name |
| `--cadence` | No (default: `manual`) | Poll cadence |
| `--external-ref` | No (repeatable) | External reference (database ID, URL, etc.) |
| `--route-to` | No (default: `shared_factory`) | Target domain to route work items |
| `--enabled` | No | Mark the watch source as enabled |

Writes: watch source YAML under OS runtime config.

```bash
agentic-os watch-source create my_tasks_db \
  --display-name "My Tasks Database" \
  --external-ref abc123 \
  --route-to acme \
  --enabled \
  --root /tmp/aos-ref
```

Status: not individually validated in RESULTS.md.

---

### `watch-source doctor`

Check health of a specific watch source.

| Arg / Flag | Required | Description |
|---|---|---|
| `source_id` | Yes | Watch source ID |
| `--root` | No | Installed OS root path |

```bash
agentic-os watch-source doctor my_tasks_db --root /tmp/aos-ref
```

Status: not individually validated in RESULTS.md.

---

### `watch-source poll`

Poll one watch source for new items. Dry-run or apply required (both mutually exclusive and one required).

| Arg / Flag | Required | Description |
|---|---|---|
| `source_id` | Yes | Watch source ID |
| `--root` | No | Installed OS root path |
| `--dry-run` | Yes (or `--apply`) | Preview what would be created |
| `--apply` | Yes (or `--dry-run`) | Create work items from new records |

```bash
agentic-os watch-source poll my_tasks_db --root /tmp/aos-ref --dry-run
```

Status: not individually validated in RESULTS.md.

---

### `watch-source run-due`

Poll all enabled watch sources that are due. Dry-run or apply required.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |
| `--dry-run` | Yes (or `--apply`) | Preview only |
| `--apply` | Yes (or `--dry-run`) | Execute polling |

```bash
agentic-os watch-source run-due --root /tmp/aos-ref --dry-run
```

Status: not individually validated in RESULTS.md.

---

## 9. Notion: `notion`

All `notion` subcommands operate on `--root` and default to dry-run or plan mode.

### `notion plan-sync`

Build a reviewable Notion sync plan (read-only; always shows plan, never applies).

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |

```bash
agentic-os notion plan-sync --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `notion sync`

Run a guarded Notion sync. Dry-run or apply required.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |
| `--dry-run` | Yes (or `--apply`) | Show plan only |
| `--apply` | Yes (or `--dry-run`) | Execute sync |
| `--verified-workspace` | No | Workspace name verified by the operator or connector (safety guard) |

```bash
agentic-os notion sync --root /tmp/aos-ref --dry-run
agentic-os notion sync --root /tmp/aos-ref \
  --apply --verified-workspace "Genome's Notion"
```

Status: not individually validated in RESULTS.md (plan-sync is #34; sync is separate).

---

### `notion bootstrap`

Plan or apply the Notion control-plane bootstrap. Dry-run or apply required.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |
| `--dry-run` | Yes (or `--apply`) | Show bootstrap plan |
| `--apply` | Yes (or `--dry-run`) | Execute bootstrap |
| `--verified-workspace` | No | Verified workspace name (safety guard) |
| `--parent-page-id` | No | Approved parent page ID in the verified workspace |

```bash
agentic-os notion bootstrap --root /tmp/aos-ref --dry-run
```

Status: not individually validated in RESULTS.md.

---

### `notion track-runtime`

Plan or apply runtime tracking setup in Notion. Dry-run or apply required.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |
| `--dry-run` | Yes (or `--apply`) | Show plan |
| `--apply` | Yes (or `--dry-run`) | Execute |
| `--verified-workspace` | No | Verified workspace name |

```bash
agentic-os notion track-runtime --root /tmp/aos-ref --dry-run
```

Status: not individually validated in RESULTS.md. Note: `--apply` exits 2 when workspace is not verified (tested in test suite).

---

## 10. Codex config: `config`

Subcommands: `install`, `install-tree`, and `doctor`. There is no `config layers` subcommand.

### `config install`

Install or merge `config.toml` for an OS directory. Dry-run by default.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Directory that should receive `config.toml` |
| `--layer` | Yes | Config layer — one of: `agentic_os_root`, `automation`, `customer_os_root`, `domain_or_lane`, `global_harness`, `project`, `workflow_or_task` |
| `--dry-run` | No (default) | Preview changes |
| `--apply` | No | Apply changes |
| `--backup` | No | Back up existing `config.toml` before applying |
| `--confirm-conflicts` | No | Apply non-conflicting additions while preserving conflicting keys |

Exits 2 when apply is blocked by unresolved conflicts. Dry-run reports conflicts without writing files. Reads/Writes: `config.toml` and `MEMORY.md` at `--root`.

```bash
agentic-os config install --root /tmp/aos-ref --layer agentic_os_root --dry-run
agentic-os config install --root /tmp/aos-ref --layer agentic_os_root --apply --backup
```

Real output (dry-run excerpt):
```text
root: /tmp/aos-ref
layer: agentic_os_root
dry_run: true
created:
- /tmp/aos-ref/config.toml
- /tmp/aos-ref/MEMORY.md
blocked: false
```

Status: **OK** (rc 0, dry-run)

---

### `config install-tree`

Install or merge `config.toml` across the routed OS tree. It targets the root,
domains with `domain.yml`, projects with `project.yml`, workflows with
`workflow.md`, and automations with `automation.md`. Dry-run by default.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |
| `--dry-run` | No (default) | Preview changes |
| `--apply` | No | Apply changes |
| `--backup` | No | Back up existing `config.toml` files before applying |
| `--confirm-conflicts` | No | Apply non-conflicting additions while preserving conflicting keys |

```bash
agentic-os config install-tree --root /tmp/aos-ref --dry-run
agentic-os config install-tree --root /tmp/aos-ref --apply
```

Status: **OK** (rc 0, dry-run)

---

### `config doctor`

Validate `config.toml` OTEL and MCP contracts.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Directory containing `config.toml` |
| `--layer` | Yes | Config layer (same choices as `config install`) |

Exits 1 when `ok: false` (e.g. `config.toml` is missing). Reads: `config.toml`.

```bash
agentic-os config doctor --root /tmp/aos-ref --layer agentic_os_root
```

Real output (scaffolded root):
```text
ok: true
root: /tmp/aos-ref
layer: agentic_os_root
findings: []
```

Status: **OK** on a fresh scaffolded root; **GUARDED** (rc 1) when `config.toml`
is absent or incomplete.

---

## 11. Update / backup / license: `update` / `backup` / `license`

### `update register`

Generate local update/backup SSH keys and write an update grant. Must run before `backup run --apply`.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |

Writes: SSH key pair, update grant file.

```bash
agentic-os update register --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `update check`

Check for available updates without mutating files.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |
| `--manifest` | No | Update manifest YAML or JSON file |

```bash
agentic-os update check --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `update plan`

Write an inspectable update plan.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |
| `--manifest` | No | Update manifest YAML or JSON file |

Writes: update plan YAML.

```bash
agentic-os update plan --root /tmp/aos-ref
```

Status: not individually validated in RESULTS.md.

---

### `update pull`

Plan or record an operator-pushed update pull. Dry-run by default.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |
| `--dry-run` | No (default) | Preview only |
| `--apply` | No | Record the pull |

```bash
agentic-os update pull --root /tmp/aos-ref --dry-run
```

Status: not individually validated in RESULTS.md.

---

### `update apply`

Apply safe additive update changes.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |
| `--plan` | No | Previously reviewed update plan YAML file |
| `--approve-risky` | No | Allow approved risky changes in the plan |

```bash
agentic-os update apply --root /tmp/aos-ref --plan /tmp/update-plan.yml
```

Status: not individually validated in RESULTS.md.

---

### `update rollback`

Record rollback against the latest update snapshot.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |
| `--snapshot` | No | Specific update snapshot to record against |

```bash
agentic-os update rollback --root /tmp/aos-ref
```

Status: not individually validated in RESULTS.md.

---

### `update status`

Show local update status.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |

```bash
agentic-os update status --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `update phone-home`

Emit a heartbeat-safe operational metadata payload (for operator telemetry).

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |

```bash
agentic-os update phone-home --root /tmp/aos-ref
```

Status: not individually validated in RESULTS.md.

---

### `backup run`

Plan or record a GitHub-backed OS state backup. Dry-run by default. Requires `update register` first.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |
| `--dry-run` | No (default) | Show backup plan only |
| `--apply` | No | Execute backup |

```bash
agentic-os backup run --root /tmp/aos-ref --dry-run
```

Status: **OK** (rc 0, dry-run)

---

### `license activate`

Activate a customer license. The raw key is never printed or stored.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |
| `--key` | Yes | Customer license key |

Writes: license metadata (not the raw key) to OS root.

```bash
agentic-os license activate --root /tmp/aos-ref --key "<LICENSE_KEY>"
```

Status: not individually validated in RESULTS.md.

---

## 12. Migration & validation: `migrate` / `plan`

### `migrate plan`

Create a reviewable migration plan for the installed OS root.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |

Writes: migration plan file.

```bash
agentic-os migrate plan --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `migrate apply`

Apply an approved migration by its ID.

| Arg / Flag | Required | Description |
|---|---|---|
| `migration_id` | Yes | Migration ID (from the plan) |
| `--root` | No | Installed OS root path |

```bash
agentic-os migrate apply migration_001 --root /tmp/aos-ref
```

Status: not individually validated in RESULTS.md.

---

### `plan capture`

Capture a future idea or plan in the right OS location.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |
| `--title` | Yes | Plan title |
| `--summary` | Yes | Plan summary |
| `--kind` | No (default: `os`) | One of: `os`, `domain`, `customer` |
| `--domain` | No | Domain slug (used when `--kind domain`) |
| `--project` | No | Project slug |

Writes: plan file to the appropriate OS location.

```bash
agentic-os plan capture \
  --title "Add Slack integration" \
  --summary "Surface OS events in Slack" \
  --kind os \
  --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

## 13. Host registry and operator projection: `host`

### `host add`

Create or update one SSH identity in the active installed host registry. The
resolver writes back to an existing `config/hosts.yml` or
`harness/config/hosts.yml` and does not create a parallel registry.

| Arg / Flag | Required | Description |
|---|---|---|
| `alias` | Yes | Stable host alias |
| `--ssh-alias` | No | Alias resolved by SSH config |
| `--user` | No | Informational remote username |
| `--home` | No | Absolute path-domain root on the host |
| `--description` | No | Human-readable host summary |
| `--root` | No | Installed OS root path |

### `host list`

List identities from the active registry. Pass `--json` for the stable
`host-list/v1` response.

```bash
agentic-os host list --root ~/agentic_os --json
```

### `host routing`

Join identity, routing policy, and recent harness receipts into the read-only,
failure-tolerant `host-query/v1` operator projection.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |
| `--recent-runs` | No (default: 8) | Maximum remote harness receipts to include |
| `--json` | No | Emit machine-readable JSON |

Health remains `unknown` without an observed receipt; this command never probes
SSH or dispatches work.

```bash
agentic-os host routing --root ~/agentic_os --recent-runs 20 --json
```

Status: **OK** (covered by remote-source contract tests)

---

## 14. Customer OS factory: `customer`

### `customer init`

Create a customer OS from a profile. Initializes a full OS tree for a named customer.

| Arg / Flag | Required | Description |
|---|---|---|
| `customer_slug` | Yes | Customer identifier (snake_case) |
| `--profile` | Yes | Profile YAML path |
| `--target` | Yes | Target directory for the customer OS root |

Writes: full OS directory tree at `--target` shaped by the profile.

```bash
agentic-os customer init example_corp \
  --profile /tmp/aos-ref/my-profile.yml \
  --target /tmp/example-corp-os
```

Status: **OK** (rc 0)

---

### `customer update`

Add missing customer OS assets (additive, does not overwrite).

| Arg / Flag | Required | Description |
|---|---|---|
| `customer_slug` | Yes | Customer identifier |
| `--root` | Yes | Customer OS root path |

Writes: missing assets to customer OS.

```bash
agentic-os customer update example_corp --root /tmp/example-corp-os
```

Status: not individually validated in RESULTS.md.

---

### `customer validate`

Validate a customer OS root.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | Yes | Customer OS root path |

Exits 1 on validation errors. Reads: customer OS tree.

```bash
agentic-os customer validate --root /tmp/example-corp-os
```

Status: **OK** (rc 0)

---

## Validation Summary

| Status | Count | Notes |
|---|---|---|
| **OK** | 52 | Exits 0 as expected |
| **GUARDED** | 1 | `here route` (rc 2, low confidence) |
| Total validated | 53 | Re-run `docs/architecture/tools/validate-cli.sh` for the current matrix |

Commands not in the 53-invocation matrix (`room`, `here context build`, `connected-system doctor`, `run-queue prune`, `watch-source create/doctor/poll/run-due`, `event append/replay`, `chain test`, `notion sync/bootstrap/track-runtime`, `update plan/pull/apply/rollback/phone-home`, `migrate apply`, `integration setup`, `customer update`) are structurally sound (argparse defined, handlers exist) but lack captured real-output evidence.
