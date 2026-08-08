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
| **Dry-run default** | Several mutating commands default to `--dry-run`. Pass `--apply` to commit changes. Affected: `runtime run-next`, `run-queue prune`, `schedule run-due`, `event process-due`, `event replay`, `backup run`, `heartbeat run`, `update pull`, `integration setup`, `watch-source poll`, `watch-source run-due`, `notion sync`, `notion bootstrap`, `config install`, `config install-tree`. |
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

Writes: `<root>/domains/<name>/` tree with `README.md`, `ROUTER.md`, `AGENTS.md`, `CLAUDE.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`, `REFERENCES.md`, `domain.yml`, numbered subdirs 00–08. Root-level domain directories and compatibility aliases are not created.

```bash
agentic-os domain create acme --root /tmp/aos-ref
```

Real output (excerpt):
```text
created: /tmp/aos-ref/domains/acme
created: /tmp/aos-ref/domains/acme/README.md
created: /tmp/aos-ref/domains/acme/domain.yml
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

Writes: `<root>/domains/<domain>/02-projects/<project>/` with `project.yml`, `status.md`, `decisions.md`, `source-map.md`, `AGENTS.md`, `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`, `MEMORY.md`, `config/*.yml`, `ideas/`, canonical `work-items/` and `work-items/99-archived/`, `worktrees/`, and `artifacts/`; creates `src` when `--repo` is a local path; updates domain `README.md` and `active-work.md`.

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

Writes missing project-local `AGENTS.md`, `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`, `MEMORY.md`, `config/*.yml`, `ideas/`, canonical `work-items/` and `work-items/99-archived/`, `worktrees/`, and `config.toml`. Existing local edits are preserved unless the file is an older generic scaffold.

```bash
agentic-os project onboard acme launch --root /tmp/aos-ref
```

Status: **OK** (rc 0)

---

### `project work-item create`

Capture a project-known idea as one stable, date-prefixed lifecycle packet.

| Arg / Flag | Required | Description |
|---|---|---|
| `domain` | Yes | Domain slug |
| `project` | Yes | Project slug (snake_case) |
| `--title` | Yes | Work item title |
| `--summary` | Yes | Raw idea, scope, or next-step summary |
| `--work-id` | No | Optional slug; the command adds the next `NNN_` index when absent |
| `--status` | No (default: `captured`) | One of the lifecycle states |
| `--format` | No | Compatibility option; canonical installs always create a packet |
| `--root` | No | Installed OS root path |

Writes `<project>/work-items/MMDDYY-NNN_slug/`. State changes never move the
packet. Terminal packets are moved to `work-items/99-archived/` only after the
configured retention period.

```bash
agentic-os project work-item create acme launch --root /tmp/aos-ref \
  --title "Build logger" --summary "Auto-log agent conversations."
```

Status: **OK** (rc 0)

---

### `project worktree create`

Create and register an isolated git worktree for a code project in any domain.
The command reads the repository and worktree policy from
`<project>/config/development.yml`; `--repo` is only needed as an explicit
override. Worktree names inherit the root artifact naming policy by default.

| Arg / Flag | Required | Description |
|---|---|---|
| `domain` | Yes | Domain slug |
| `project` | Yes | Project slug |
| `name` | No | Directory name; defaults to a normalized branch name |
| `--branch` | Yes | Existing or new branch to check out |
| `--repo` | No | Override the configured local repository |
| `--root` | No | Installed OS root path |

```bash
agentic-os project worktree create acme launch \
  --root /tmp/aos-ref --branch feature/launch-dashboard
```

`worktrees.directory` controls the physical location and
`worktrees.date_prefix` accepts `inherit` (default), `true`, or `false`.
External locations are linked back into the project's visible `worktrees/`
registry.

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
Dry-run by default. Physical removal is opt-in and requires an explicitly
merged PR, a non-primary registered Git worktree inside the project
`worktrees/` directory, no `REOPEN.md`, a packet-local Health preflight, and a
runtime-cleanup readback bound to that preflight hash. Registry closure happens
only after exact Git worktree removal succeeds; no separate metadata-sweep
operation runs.

| Arg / Flag | Required | Description |
|---|---|---|
| `--domain` | With `--remove-files` | Limit cleanup to one domain |
| `--project` | With `--remove-files` | Limit cleanup to one project |
| `--worktree` | With `--remove-files` | Limit cleanup to one exact registered worktree id, name, or path |
| `--health-preflight` | With `--remove-files` | Packet-local `auto-dev-health-preflight/v1` file that freezes authority, receipts, and exact resource identity |
| `--runtime-receipt` | With `--remove-files` | Packet-local `auto-dev-runtime-cleanup/v1` readback whose `preflight_sha256` matches the preflight |
| `--root` | No | Installed OS root path |
| `--dry-run` | No (default) | Preview candidates without writing |
| `--apply` | No | Move matching registry entries to `worktrees/closed.yml` |
| `--remove-files` | No | Remove the selected merged Git worktree through the exact guarded Git operation when all five scoped Health inputs validate |

Reads: `<project>/config/worktrees.yml` and `<project>/worktrees/index.yml`.
Writes: `<project>/worktrees/closed.yml`, the source worktree registry, and the
root active-work symlink container when `--apply` is used.

```bash
agentic-os project worktree cleanup-closed --root /tmp/aos-ref \
  --domain acme --project launch --worktree feature-123 \
  --health-preflight <packet>/artifacts/auto-dev-health/preflight.json \
  --runtime-receipt <packet>/artifacts/auto-dev-health/receipts/runtime-cleanup.json \
  --dry-run
agentic-os project worktree cleanup-closed --root /tmp/aos-ref \
  --domain acme --project launch --worktree feature-123 \
  --health-preflight <packet>/artifacts/auto-dev-health/preflight.json \
  --runtime-receipt <packet>/artifacts/auto-dev-health/receipts/runtime-cleanup.json \
  --apply --remove-files
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

Writes: `<root>/domains/<domain>/02-projects/<project>/src`, and updates `project.yml` plus `source-map.md` when `--repo` is supplied. Remote repository URLs are rejected because `src` must be a filesystem symlink.

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

### `agentic-os-policy-context`

Resolve the complete, hashed policy context before making a source change or
reviewing one. This harness executable composes the five Agentic OS policy
planes with the selected checkout's `AGENTS.md`, nested `AGENTS.md`, and
declared Claude rule surfaces. It emits a paste-ready
`effective-policy-context/v1` block and can persist the structured result as a
work-item receipt.

```bash
harness/bin/agentic-os-policy-context \
  --path /path/to/registered/worktree \
  --strict-source-rules \
  --receipt artifacts/policy-context.json
```

It recognizes only canonical project profiles:

- `domains/<domain>/02-projects/<project>/config/development.yml`
- `harness/shared_factory/02-projects/<project>/config/development.yml`

When `--path` targets a registered worktree, source-rule hashing uses that
worktree rather than silently substituting the configured primary checkout.
Project-visible external worktree links are matched before symlink resolution
and must share the selected repository's Git common directory. In a
multi-repository project, `--repository` and `--path` must identify the same
checkout; a mismatch is a blocker rather than a misleading policy receipt.
The executable fails closed (exit 2) for missing profiles, missing required
source rules, alias profiles, or an inventory that exceeds the reviewed safety
limit; it never emits a partial effective-policy fingerprint.

---

## 3A. Canonical work state: `work`

The `work` group reads and updates the SQLite work-item registry without
scanning trackers or repository paths. Every subcommand accepts `--root` and an
optional `--db` override.

| Command | Required inputs | Important optional inputs | Behavior |
|---|---|---|---|
| `work list` | — | `--attention`, `--state`, `--domain`, `--project`, `--limit` | List canonical work items using registry filters. |
| `work show` | `item_id` | — | Show one canonical work item; exits 1 when it is absent. |
| `work upsert` | `item_id`, `--title` | State, attention, source, ownership, packet/worktree/branch, summary, blocker, actor, receipt, verification | Create or fully reconcile one item and refresh `active-now.json`. |
| `work set` | `item_id` | State, attention, summary, blocker, packet/worktree/branch, `--clear-worktree`, actor, receipt, verification | Change lifecycle or resume context and refresh `active-now.json`. |
| `work active-now` | — | `--stale-hours` | Refresh and print the compact active-context projection; exits 2 when stale active entries remain. |
| `work import-legacy` | — | `--apply` | Preview legacy numbered-lane imports by default; apply them only when requested. |
| `work migrate-path-prefix` | `--from-prefix`, `--to-prefix` | `--domain`, `--actor`, `--receipt`, `--apply` | Preview or atomically migrate stored packet path prefixes. |

```bash
agentic-os work list --attention active --root /tmp/aos-ref
agentic-os work show AGE-113 --root /tmp/aos-ref
agentic-os work active-now --root /tmp/aos-ref
```

Writes: `work upsert`, `work set`, applied imports, and applied path migrations
update `harness/shared_factory/00-control-plane/state.db`; registry mutations
also refresh `harness/shared_factory/00-control-plane/active-now.json`.

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

Writes: `<root>/domains/<domain>/03-workflows/<lane>/<name>/` with `workflow.md`, `alignment-questions.md`, `examples/`, `runs/`.

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

Writes: `<root>/domains/<domain>/04-automations/<lane>/<name>/` scaffold.

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

---

### `runtime snapshot`

Capture one read-only queue, worker-pool, worker, and safe task snapshot from
the selected filesystem or Execution Fabric backend.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |
| `--queue NAME` | No | Restrict task rows to one named queue |
| `--status STATUS` | No | Restrict task rows by status; repeatable |
| `--limit N` | No | Maximum task rows (default 50) |
| `--all` | No | Include every matching task row instead of a bounded sample |
| `--json` | No | Print the versioned JSON contract |
| `--output PATH` | No | Atomically write the JSON receipt |

```bash
agentic-os runtime snapshot --root /tmp/aos-ref
agentic-os runtime snapshot --queue codex --status queued --limit 100 --json --root /tmp/aos-ref
```

Status: covered by runtime snapshot contract tests.

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

## 13A. Program and Automation operator projection: `operator-resource`

### `operator-resource query`

Read all source-backed Program or Automation resources through the stable
`operator-resource-query/v1` envelope.

| Arg / Flag | Required | Description |
|---|---|---|
| `kind` | Yes | `program` or `automation` |
| `--root` | No | Installed OS root path |

```bash
agentic-os operator-resource query program --root ~/agentic_os
agentic-os operator-resource query automation --root ~/agentic_os
```

### `operator-resource get`

Return one exact resource identity from the same projection. The command does
not resolve display names or aliases.

| Arg / Flag | Required | Description |
|---|---|---|
| `kind` | Yes | `program` or `automation` |
| `resource_id` | Yes | Exact ID returned by `query` |
| `--root` | No | Installed OS root path |

```bash
agentic-os operator-resource get program program_definition:thread_management --root ~/agentic_os
agentic-os operator-resource get automation automation_definition:los:engineering:active_prs_board --root ~/agentic_os
```

These commands are read-only, always emit JSON, never probe remote hosts, and
preserve malformed, unmatched, missing, stale, and error evidence through
structured diagnostics.

Status: **OK** (covered by operator resource contract and installed-root smoke tests)

---

## 13B. First-class resource snapshot and tags: `resource-registry`

`resource-registry query` reads the atomic local snapshot and supports `--kind`,
`--domain`, `--project`, `--query`, and `--ensure`. `resource-registry refresh`
explicitly reconciles the installed tree.

Custom tags use the exact resource ID returned by `query`:

```bash
agentic-os resource-registry tags list --resource-id <id> --root ~/agentic_os
agentic-os resource-registry tags add --resource-id <id> --tag needs-review --root ~/agentic_os
agentic-os resource-registry tags remove --resource-id <id> --tag needs-review --root ~/agentic_os
```

The add/remove forms validate and normalize input, serialize concurrent writes,
atomically update the dedicated tag overlay, refresh the snapshot, and emit a
JSON mutation receipt. They never edit the generated snapshot in place.

Status: **OK** (covered by registry, mutation, concurrency, and CLI tests)

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

## 14. AgenticOSGui desktop: `gui`

### `gui snapshot`

Emit the versioned desktop composition snapshot with domain/project navigation,
provider-backed active Claude/Codex conversations, native titles and recency,
model presentation, resume capabilities, and locally derived work metadata.

| Arg / Flag | Required | Description |
|---|---|---|
| `--root` | No | Installed OS root path |
| `--json` | No | Emit machine-readable JSON |

Reads provider registries and transcripts in read-only mode. Writes nothing.

```bash
agentic-os gui snapshot --root ~/agentic_os --json
```

### `gui transcript`

Read visible user and assistant messages for one selected native conversation.
Reasoning, developer instructions, tool payloads, and subagent traces are not
returned.

| Arg / Flag | Required | Description |
|---|---|---|
| `--provider` | Yes | `codex` or `claude` |
| `--conversation-id` | Yes | Provider-native conversation identifier |
| `--root` | No | Installed OS root path |
| `--json` | No | Emit machine-readable JSON |

```bash
agentic-os gui transcript --provider codex --conversation-id <uuid> --json
```

### `gui open`

Open the packaged local AgenticOSGui application. If no packaged application is
installed, report the exact source development/build path instead of silently
starting a web server.

```bash
agentic-os gui open --root ~/agentic_os
```

Provider stores remain read-only. Pins, focus, leases, and GUI-owned session
mappings live in AgenticOSGui application support state.

---

## 15. Universal long-running execution: `long-run`

`long-run start` governs any process expected to exceed two minutes. It
creates a central registry row and per-run receipts, bounds logs and resources,
enforces wall-clock/no-progress watchdogs, and returns immediately.

```bash
agentic-os long-run start --kind test --label "full suite" -- pytest -q
agentic-os long-run list --root ~/agentic_os --active
agentic-os long-run pause --run-dir <run-dir>
agentic-os long-run resume --run-dir <run-dir>
agentic-os long-run cancel --run-dir <run-dir>
agentic-os long-run recover --root ~/agentic_os --mark-stale
```

Mutating kinds require `--checkpoint-strategy` plus `--mutation-lock` or a
`--post-run-check`. Import, export, backfill, cleanup, and migration also
require a `--preflight-check` that records complexity and performance evidence.
Use `--progress-file` for semantic phase/item/file/byte progress.
`agentic-os-quiet-run` is a compatibility launcher for this same command.

---

## 16. Plain-English SDLC orchestration: `auto-dev`

`auto-dev` starts or resumes one canonical Development Delivery run and keeps a
plain-English `autodev.json` projection in its work-item packet. It does not
replace tracker, Git provider, canonical work state, or Development Delivery
truth.

Run the whole applicable lifecycle:

```bash
agentic-os auto-dev everything <domain> <project> <ticket> [<ticket> ...] --apply
```

Adopt one exact active packet created before `autodev.json` existed:

```bash
agentic-os auto-dev adopt <domain> <project> <ticket> \
  --state <existing-work-item> --run-id <stable-id> --apply
```

Adoption requires one canonical work row whose packet path and source key
match. It preserves that identity and reuses an existing worktree only after
the project registry, Git worktree metadata, and branch all match. It never
creates a replacement packet or checkout.

Reconcile a legacy task that is already at `worktree_ready` only when the
complete missing delivery ledger is backed by exact provider-read merge,
release, and install evidence:

```bash
agentic-os auto-dev reconcile-historical \
  --state <development-task-state.json> \
  --evidence <historical-delivery-evidence.json> \
  --idempotency-key <stable-key> --apply
```

The evidence uses `auto-dev-historical-delivery-reconciliation/v1`. It must
bind one reviewed head to the merged revision, a provider-read release tag and
installed artifact to that revision, and typed receipts for every missing
delivery state. The command rejects any mismatch before mutation, snapshots
the evidence inside the existing packet, and preserves the packet/worktree. It
does not invent missing Auto-Dev stage evidence; Closeout and Health remain
blocked until their ordinary receipt gates are satisfied.

Reopen immutable post-Health history for a fresh QA or development run:

```bash
agentic-os auto-dev reopen --state <finished-packet-or-autodev.json> \
  --run-id <new-run-id> --reason "<QA or support reason>" \
  --stage qa --root <os-root> --apply
```

`--stage` is `qa` by default and also accepts `develop`. Without `--apply`, the
command is a read-only safety plan. Apply requires completed Health evidence, a
closed terminal canonical row pointing to the selected `03-complete` packet,
and cleared prior worktree pointers. It creates one new active packet and reopen
receipt, then provisions a fresh worktree/runtime registration. Repeating the
same run id returns the existing reopen; it does not create a second packet.

The prior frozen context is carried unchanged by default. Passing a new
`--touched-path`, `--subject`, or `--rulebook-id` without `--reselect-context`
fails closed. An explicit reselect uses:

```bash
agentic-os auto-dev reopen --state <finished-packet-or-autodev.json> \
  --run-id <new-run-id> --reason "<reason>" --stage qa \
  --reselect-context --touched-path <repo-relative-path> \
  --subject rulebook --rulebook-id <exact-rulebook-key> --apply
```

The reopen receipt binds both prior and selected context hashes, preserving
path/subject provenance rather than recomputing or silently dropping it.

Run one named workflow with the same state model:

```bash
agentic-os auto-dev groom <domain> <project> <ticket> --apply
agentic-os auto-dev investigate --state <work-item>/autodev.json --apply
agentic-os auto-dev create --state <work-item>/autodev.json --apply
agentic-os auto-dev readiness --state <work-item>/autodev.json --apply
agentic-os auto-dev develop --state <work-item>/autodev.json --apply
agentic-os auto-dev document --state <work-item>/autodev.json --apply
agentic-os auto-dev review-self --state <work-item>/autodev.json --apply
agentic-os auto-dev review-others --state <work-item>/autodev.json --apply
agentic-os auto-dev qa --state <work-item>/autodev.json --apply
agentic-os auto-dev propagate --state <work-item>/autodev.json --apply
agentic-os auto-dev finalize --state <work-item>/autodev.json --apply
agentic-os auto-dev merge --state <work-item>/autodev.json --apply
agentic-os auto-dev release --state <work-item>/autodev.json --apply
agentic-os auto-dev deploy --state <work-item>/autodev.json --apply
agentic-os auto-dev closeout --state <work-item>/autodev.json --apply
agentic-os auto-dev health --state <existing-packet>/autodev.json --apply
```

Merge, Deploy, Closeout, and Health are existing-state-only so a downstream
command cannot create a duplicate packet or checkout. Health never provisions
a worktree. The completed Merge receipt must contain provider-read `merge_sha`,
`source_head_sha` equal to the reviewed `subject_revision`, `provider`,
`pull_request`, configured `repository`, configured `base_branch`,
provider-qualified `author_identity`, derived `author_kind`, and
`readback_verified: true`. After verified
`delivery_complete`, `auto-dev health --apply`
audits and hashes the durable receipt inventory, preserves a resume manifest
and full packet manifest, and writes `auto-dev-health-preflight/v1`; it stops
before resource deletion.
That preflight is always `clean_only`. A dirty checkout is preserved and blocks
physical cleanup; no receipt or merge state can make dirty files disposable.
Preserve or reconcile the changes through a separate operator workflow, verify
the checkout is clean, then rerun Health with a fresh preflight.
The exact runtime readback must use `auto-dev-runtime-cleanup/v1`, bind
`preflight_sha256`, be newer than the preflight and at most 15 minutes old, and
use the identity-bound command for the domain/project/worktree runtime. The gate
immediately executes that command again; exit 0 means the exact runtime is
absent. Physical worktree removal then requires domain, project, worktree,
preflight, and runtime-receipt inputs. Preserve both final resource
  results atomically in `auto-dev-resource-cleanup/v1`, move the packet with
  `project work-item set ... --state finished --health-relocation` to
canonical `finished` / `03-complete`, and preserve an
`auto-dev-closed-worktree-readback/v1` snapshot of the exact closed registry
row or `not_managed`. Audit that snapshot under `resource_cleanup` and
cross-check a managed entry against live `worktrees/closed.yml`; then refresh
active projections and record strict `auto-dev-health-evidence/v1`. A root
`REOPEN.md`, missing receipt, unverified
terminal merge revision, missing canonical finished state, teardown failure, or
residual hold leaves Health incomplete. Health has no schedule or host-wide/
all-resource mode and has no force, Git-metadata-sweep, guessed-identity, or shared-
runtime path.

The five-input physical cleanup gate does not trust the preflight flag alone.
It hashes and parses the canonical task, requires `delivery_complete` and exact
item/repository/base/worktree-id/path/branch/HEAD/revision matches, compares packet Merge and Closeout
snapshots with canonical typed task receipts as JSON, validates their fields,
and verifies the complete ordered non-Health stage audit, every stage snapshot,
and the full packet manifest. After relocation, every packet hash must match
except semantic `work.yml` and `autodev.json` state/path updates; those two are
parsed and validated again.

The exact stage order is Groom, Detective, Create Artifacts, Readiness,
Develop, Document, PR Create, Review Self, Review Others, QA,
Finalize, Merge, Release, Deploy, Closeout, Health. A multi-ticket command
creates one task/packet/`autodev.json` per ticket; resume one with its own
`--state`.

`not_required` uses strict `auto-dev-stage-policy-decision/v1`, bound to the
work item, canonical work id, domain/project/stage, decision maker/reason/time,
frozen policy fingerprint, and exact policy source/hash. The policy and
decision are materialized into packet-local immutable proof.

Finalize authorizes only provider-read identities classified as `ours` and
records readiness without merging. Review Others authorizes only identities
classified as `others` and records a clean `review_no_merge` result. Merge's
hashed readiness descriptor and open/ready/merged provider readbacks must keep
the provider/PR/repository/base/revision/author chain identical.

The final Health audit contains exactly `terminal_authority`, `closeout`,
`receipt_audit`, `resume_manifest`, `packet_manifest`, `resource_cleanup`,
`runtime_cleanup`, `work_state`, `active_index`, and `validation`.

Finished packets are immutable. Follow-up QA or development uses `auto-dev
reopen`; direct canonical state edits never authorize writes to a completed
packet. The explicit command preserves the old packet and starts a new delivery
run with fresh resources.

Health does not rename or reinterpret Merge authority. Its
`terminal_authority.provider` and `terminal_authority.ref` must exactly equal
the typed Merge receipt's `provider` and `pull_request`, and its terminal
revision must equal that receipt's `merge_sha`.

Inspect, resynchronize, or record a standalone workflow:

```bash
agentic-os auto-dev status <work-item-or-autodev.json>
agentic-os auto-dev sync <development-task-state.json>
agentic-os auto-dev record <autodev.json> --stage <stage> \
  --evidence <typed-evidence.json> --idempotency-key <stable-key>
```

`auto-dev record` accepts `auto-dev-stage-evidence/v1` for standalone stages
and strict `auto-dev-health-evidence/v1` for Health. Record delivery-managed
Readiness, Develop, PR Create, Review Self, Merge, Deploy, and
Closeout transitions with `agentic-os develop stage`, not this command.

Common launch flags are `--state`, `--run-id`, `--repository`, `--base-branch`,
repeatable `--policy-overlay PLANE=PATH`, `--root`, `--apply`, and `--json`.
Without `--apply`, launch commands are plans only. Matching `/auto-dev-*`
commands and skills provide the operator workflow for every named stage.

---

## Validation Summary

| Status | Count | Notes |
|---|---|---|
| **OK** | 52 | Exits 0 as expected |
| **GUARDED** | 1 | `here route` (rc 2, low confidence) |
| Total validated | 53 | Re-run `docs/architecture/tools/validate-cli.sh` for the current matrix |

Commands not in the 53-invocation matrix (`room`, `here context build`, `connected-system doctor`, `run-queue prune`, `watch-source create/doctor/poll/run-due`, `event append/replay`, `chain test`, `notion sync/bootstrap`, `update plan/pull/apply/rollback/phone-home`, `migrate apply`, `integration setup`, `customer update`) are structurally sound (argparse defined, handlers exist) but lack captured real-output evidence.
