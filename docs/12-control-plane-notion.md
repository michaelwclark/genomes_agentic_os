# 12 · Control Plane (Notion)

> **Purpose:** give the human operator a single, readable cockpit — Notion pages
> and databases that *mirror* the OS filesystem so you can review work items,
> approve risky actions, and track runs without opening files.  The filesystem
> remains the authoritative source of truth; Notion is always a projection.
>
> **You'll use:** `agentic-os notion plan-sync`, `notion sync`, `notion bootstrap`,
> `notion track-runtime`.
> **Prereqs:** an installed OS root ([01 · Install & Quickstart](01-install-and-quickstart.md))
> with at least one domain.  `notion bootstrap` additionally requires a verified
> Notion workspace and an approved parent page ID.

---

## The idea

Every domain's state — projects, workflows, automations, runs, approvals,
decisions, metrics — lives in Markdown and YAML files under `~/agentic_os`.
Agents read those files; humans find them inconvenient to browse.  The control
plane solves this by projecting the filesystem into Notion databases:

| Layer | Source of truth | Notion role |
| --- | --- | --- |
| Domains | `<domain>/domain.yml` | Domains database row |
| Active work | `00-control-plane/active-work.md` | Work Items view |
| Workflows & automations | `03-workflows/` · `04-automations/` | Catalog rows |
| Runs | `06-runs-and-logs/runs/*/run-log.md` | Runs database row |
| Approvals | `00-control-plane/approval-rules.md` | Approvals queue |
| Decisions | `00-control-plane/decisions.md` | Decisions log |
| Metrics | `07-metrics/scorecards.md` | Metrics view |

The sync is **one-directional**: files → Notion.  Humans act in Notion (approve,
comment, reorder) and then record the decision back in the appropriate file.
Notion never writes to the filesystem automatically.

![Filesystem objects are fingerprinted and planned by notion plan-sync; the plan passes through an apply guard requiring a verified workspace and parent page; notion sync/bootstrap/track-runtime apply the plan and update the local mapping; Notion becomes a read-only cockpit; human approvals are written back to filesystem files](diagrams/notion-control-plane-flow.png)

---

## Commands & flags

### `agentic-os notion plan-sync`

Build a reviewable sync plan — always safe, never applies.

| Arg / Flag | Required | Description |
| --- | --- | --- |
| `--root` | — | OS root path. Defaults to `~/agentic_os`. |

```bash
agentic-os notion plan-sync --root ~/agentic_os
```

Exits 0.  Prints a YAML plan listing every object that would be created or
updated.  Run this first, every time, before `sync`.

---

### `agentic-os notion sync`

Apply a guarded sync — updates the local mapping (`mapping.yml`) and (in a
future live-API release) pushes to Notion.  Requires `--dry-run` **or**
`--apply`.

| Arg / Flag | Required | Description |
| --- | --- | --- |
| `--root` | — | OS root path (default `~/agentic_os`). |
| `--dry-run` | ✅ or `--apply` | Print plan, make no changes. |
| `--apply` | ✅ or `--dry-run` | Execute the sync. |
| `--verified-workspace` | Required with `--apply` | Workspace name; must match the target exactly (e.g. `"Genome's Notion"`). |

```bash
# safe preview
agentic-os notion sync --root ~/agentic_os --dry-run

# apply (operator must supply the verified workspace name)
agentic-os notion sync --root ~/agentic_os \
  --apply --verified-workspace "Genome's Notion"
```

---

### `agentic-os notion bootstrap`

Plan or apply the Notion control-plane page tree: an OS Home page, the five
core databases (OS Inbox, Work Items, Runs, Approvals, Domains), and eight
dashboard views.  Requires `--dry-run` **or** `--apply`.

| Arg / Flag | Required | Description |
| --- | --- | --- |
| `--root` | — | OS root path (default `~/agentic_os`). |
| `--dry-run` | ✅ or `--apply` | Show the bootstrap plan. |
| `--apply` | ✅ or `--dry-run` | Create pages and write manifest. |
| `--verified-workspace` | Required with `--apply` | Verified workspace name. |
| `--parent-page-id` | Required with `--apply` | Notion page ID under which the OS Home page is created. |

```bash
agentic-os notion bootstrap --root ~/agentic_os --dry-run

agentic-os notion bootstrap --root ~/agentic_os \
  --apply \
  --verified-workspace "Genome's Notion" \
  --parent-page-id "<approved-page-id>"
```

`--apply` without `--parent-page-id` raises an error and exits 2.

---

### `agentic-os notion track-runtime`

Plan or apply runtime-registry mirroring — heartbeats, schedules, and active
run entries projected into the Runs and Work Items databases.

| Arg / Flag | Required | Description |
| --- | --- | --- |
| `--root` | — | OS root path (default `~/agentic_os`). |
| `--dry-run` | ✅ or `--apply` | Show plan. |
| `--apply` | ✅ or `--dry-run` | Execute. |
| `--verified-workspace` | Required with `--apply` | Verified workspace name. |

```bash
agentic-os notion track-runtime --root ~/agentic_os --dry-run
```

`--apply` without `--verified-workspace` exits 2 (unverified workspace
refusal, confirmed in test suite).

---

## Notion databases provisioned by `bootstrap`

| Database | Purpose |
| --- | --- |
| OS Inbox | Capture requests, rough ideas, and kickoff records. |
| Work Items | Active queue across domains, projects, workflows, and automations. |
| Runs | Execution history, validation evidence, artifacts, and final state. |
| Approvals | Human review queue for risky actions. |
| Domains | Domain catalog with root paths, owners, and source systems. |

Dashboard views seeded automatically: **Needs Approval**, **Active Work**,
**Waiting On Me**, **Running Or Failed Runs**, **Recent Outputs**, **Automation
Health**, **Inbox To Triage**, **Decisions This Week**.

---

## Real output — `notion plan-sync`

The following is captured output from the validation suite
(`.agentic-atlas/validation/command-output-examples.md`, example 33):

```bash
agentic-os notion plan-sync --root /tmp/aos-validate/root
```

```text
root: /private/tmp/aos-validate/root
workspace: Genome's Notion
mapping_path: /private/tmp/aos-validate/root/.notion-sync/mapping.yml
actions:
- action: create
  kind: domain
  key: acme
  title: acme
  path: /private/tmp/aos-validate/root/acme/domain.yml
  record_key: domain:acme
  notion_id: null
  fingerprint: f8019fd16a730137fcefa2c3ee1fc810b2cd1f31af54c5ed497eab81eddadced
- action: create
  kind: project
  key: acme/launch
  title: launch
  path: /private/tmp/aos-validate/root/acme/02-projects/launch/project.yml
  record_key: project:acme/launch
  notion_id: null
  fingerprint: 15c87fe3d7ab4f340abe9287df8e82dedca7c70c6a50ad76c1ad6fbb0a26ed87
- action: create
  kind: workflow
  key: acme/engineering/launch_blog
  title: launch_blog
  path: /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog/workflow.md
  record_key: workflow:acme/engineering/launch_blog
  notion_id: null
  fingerprint: 96f225ed14369075296e777079849ca6608259df8870ef92a87413d07c47c649
- action: create
  kind: automation
  key: acme/marketing/weekly_report
  title: weekly_report
  path: /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/automation.md
  record_key: automation:acme/marketing/weekly_report
  notion_id: null
  fingerprint: 2467a03437db66b972d87026ae73645a3b653003aea3a2c2dfbc7ca0ce8850a3
- action: create
  kind: run
  key: acme/20260529T005116Z-acme-launch_blog
  title: 20260529T005116Z-acme-launch_blog
  path: /private/tmp/aos-validate/root/acme/06-runs-and-logs/runs/20260529T005116Z-acme-launch_blog/run-log.md
  record_key: run:acme/20260529T005116Z-acme-launch_blog
  notion_id: null
  fingerprint: 63543aa239e5103bbef0e33a4bb46751d1792a11e5e07a3e842c84b...
```

*(Output trimmed — five additional `active_work`, `approvals`, `decisions`, and
`metrics` action entries omitted for brevity; all have `notion_id: null`.)*

Two things the output reveals:

- `notion_id: null` on every action — no live Notion page exists yet; the plan
  is the product.
- `fingerprint` hashes let subsequent runs detect changes and emit `update`
  instead of `create`.

---

## Running this from Claude vs Codex

> Same guard rails, same plan YAML, same local mapping file — only the trigger
> differs.

- **Claude:** run the `/os-sync-notion` command, or invoke the
  **`control-plane-bootstrap`** skill.  Both wrap `notion plan-sync` / `notion
  bootstrap` with the correct `--root` and workspace flags.
- **Codex:** run `agentic-os notion plan-sync --root ~/agentic_os` directly, or
  call `agentic-os notion sync --dry-run` to preview an apply.  The
  `agentic_os_root` profile governs tool allow-list and validation hooks for
  apply-mode commands.

Full mechanics: [13 · Agent Surfaces](13-agent-surfaces.md).

---

## Guardrails & gotchas

- **`plan-sync` is always safe (exit 0).** It reads files, fingerprints them,
  and prints YAML.  Run it freely.
- **`sync`, `bootstrap`, and `track-runtime` are guarded.** They require
  `--dry-run` or `--apply` explicitly; omitting both is a usage error (exit 2).
- **`--apply` requires `--verified-workspace`.** The workspace name must match
  the expected value exactly (case-sensitive).  Mismatches are refused with
  exit 2.  Passing a name containing `michael clark`, `michaelwclark`, or
  `personal notion` is additionally blocked — the code refuses to write to the
  wrong Notion account.
- **`bootstrap --apply` additionally requires `--parent-page-id`.** Without an
  approved parent page, the bootstrap aborts before touching anything.
- **`track-runtime --apply` exits 2 if the workspace is unverified.**
  Confirmed in the test suite; runtime tracking cannot proceed without the
  workspace guard.
- **V1 does not call the live Notion API (Gap B).** `--apply` today writes a
  local `mapping.yml` under `.notion-sync/` and (for bootstrap) a manifest
  under `.notion-control-plane/manifest.yml`.  Notion IDs in the mapping are
  deterministic local placeholders (`local-notion-<sha256[:16]>`).  Wiring a
  real Notion adapter behind the existing guard rails is the planned V2 step;
  the guards are already in place.
- **Names are snake\_case.** Domains, lanes, workflows, and automations use
  lowercase letters, digits, and underscores only.
- **`--root` defaults to `~/agentic_os`.** Always pass `--root` in scripts or
  CI to avoid touching the real install.

## Related

- [00 · Overview](00-overview.md) — how the control plane fits the five-layer
  model.
- [03 · Operating Model](03-operating-model.md) — the approval-first operating
  loop the cockpit supports.
- [04 · Information Architecture](04-information-architecture.md) — the domain
  folder structure that `plan-sync` traverses.
- [09 · Runtime & Always-On](09-runtime-and-always-on.md) — what
  `track-runtime` mirrors into Notion.
- [13 · Agent Surfaces](13-agent-surfaces.md) — harness commands and skills
  that invoke Notion sync.
- [17 · CLI Reference](17-cli-reference.md) — full flag listing for all
  `notion` sub-commands.
- [18 · Troubleshooting & FAQ](18-troubleshooting-and-faq.md) — exit-code
  meanings and workspace-verification errors.
- Atlas: [`gap-register.md` §B](../.agentic-atlas/gap-register.md) ·
  [`command-reference.md` §9](../.agentic-atlas/architecture/command-reference.md)

---

## Live runtime-tracking path (F-010)

The `agentic-os notion track-runtime --apply` command can write the 7 runtime
tracking databases directly to Genome's Notion. The live path is opt-in and
controlled by a config file installed into every root.

### Config file

Location inside each installed root:

```
harness/shared_factory/00-control-plane/notion-tracking.yml
```

Fresh installs receive this file via `agentic-os init`. It arrives in
**local mode** (`parent_page_id` is empty) so no credentials are required.

| Field | Default | Purpose |
|---|---|---|
| `workspace` | `Genome's Notion` | Expected workspace name — must match the bot's |
| `parent_page_id` | *(empty)* | Parent page ID; leave empty for local mode |
| `token_env` | `GENOMES_NOTION_PAT` | Name of the env var holding the token (never the value) |
| `cockpit_page_title` | `Runtime Control Plane` | Title of the cockpit page under `parent_page_id` |

### Activating the live path

1. Set the Notion integration token: `export GENOMES_NOTION_PAT=secret_...`
2. Set `parent_page_id` in `notion-tracking.yml` to a real Notion page ID.
3. Run `agentic-os notion track-runtime --root ~/agentic_os --apply --verified-workspace "Genome's Notion"`.

The command verifies the workspace two ways: the string-match guard in
`verify_workspace` and a live `/users/me` API call confirming the bot's
`workspace_name`. If either check fails, the command exits with an error and
writes nothing to Notion.

### Idempotency

Re-applying is safe. Existing pages and databases are reused (matched by the
IDs in the manifest, or by title search). Records are upserted by their `Key`
field — no duplicates are created. The manifest records `live: true` and all
real Notion IDs.

### Token safety

The token value never appears in the manifest, result dict, log output, or
exception messages. Only the env-var *name* is stored in config.

### Supervisor constraint

The launchd supervisor, heartbeat runner, and all scheduled paths are
network-silent — they never call the Notion API. Only the explicit
`notion track-runtime --apply` command goes live.
