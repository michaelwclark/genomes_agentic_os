# 14 · Config, Update & Backup

> **Purpose:** keep an installed OS current, recoverable, and correctly configured —
> with an operator-approved, additive, reversible posture that requires no
> destructive action by default.
>
> **You'll use:** `agentic-os config install-tree`,
> `agentic-os update {check,register,pull,plan,apply,rollback,status,phone-home,watch-release,verify-reinstall,rollback-drill}`,
> `agentic-os backup {run,push,restore-plan}`, `agentic-os license activate`, `agentic-os migrate {plan,apply}`.
>
> **Prereqs:** a working OS root ([01 · Install & Quickstart](01-install-and-quickstart.md)).
> Config (Codex `config.toml` layers, `config install`, `config install-tree`, `config doctor`) is documented
> fully in [13 · Agent Surfaces](13-agent-surfaces.md) — this page keeps config brief.

---

## The `.agentic_root` marker

Every installed OS root contains a `.agentic_root` TOML file. It is the
source of truth for install-scoped identity and update behavior:

| Key | Meaning |
| --- | --- |
| `update_channel` | Which channel to track (`stable` is the default). |
| `update_policy` | Release-install policy (`auto_patch_minor` is the default; major releases remain operator-approved). |
| `project_link_scope` | Project repository symlinks are scoped to `domain/02-projects/<project>/src`. |

The marker is read on every CLI call — it is never cached in a singleton. The lock
file `agentic-os.lock.json` in the root carries `installed_version` and echoes the
channel and policy for status queries.

---

## The update lifecycle

Updates follow a deliberate, multi-step flow designed so that nothing applies
without the operator reviewing a plan first.

![Update lifecycle: license activate enables update register (grant + keys); register gates update check, plan, apply, rollback, status, phone-home, and backup run; apply is additive and snapshots before acting; rollback records intent against the latest snapshot](diagrams/update-lifecycle.png)

### `update register`

Generates an ed25519 SSH key pair (separate update and backup keys, stored at
`security/ssh/` with mode `0600`) and writes an update grant to
`registries/update-grant.json`. This command must run before `backup run --apply`.

**Prerequisite:** `license activate` must have been called first; the grant
generation raises an error if the license status is not `active`.

| Arg / Flag | Default | Description |
| --- | --- | --- |
| `--root` | `~/agentic_os` | Installed OS root. |

### `update check`

Read-only. Reads the lock file and local manifest and compares `installed_version`
to `available_version`. No filesystem writes; exit 0 always.

| Arg / Flag | Default | Description |
| --- | --- | --- |
| `--manifest` | (local) | Path to an explicit manifest YAML/JSON. |
| `--root` | `~/agentic_os` | Installed OS root. |

### `update pull`

Plans or records an operator-pushed update pull. **Dry-run by default** — pass
`--apply` to record the pull intent. In V1 no network operation is performed even
with `--apply`; the command writes a structured log to `logs/updates/`.

| Arg / Flag | Default | Description |
| --- | --- | --- |
| `--dry-run` | ✅ (default) | Preview only; no filesystem mutation. |
| `--apply` | — | Record the pull intent. |
| `--root` | `~/agentic_os` | Installed OS root. |

### `update plan`

Writes a reviewable plan to `registries/update-plan.yml`. The plan lists
`safe_additive_paths` (templates, registries, commands, skills, operating-manual)
and flags `risky_changes` requiring explicit approval.

**Risky change types** (require `--approve-risky` on apply): `executable`, `hook`,
`mcp`, `rule`, `permission`.

| Arg / Flag | Default | Description |
| --- | --- | --- |
| `--manifest` | (local) | Path to an explicit manifest. |
| `--root` | `~/agentic_os` | Installed OS root. |

### `update apply`

Applies the plan. Takes a snapshot of the current state first, then runs additive
operations (missing templates, registry entries, command and skill definitions,
docs); existing local edits are preserved. Blocked if risky changes are present and
`--approve-risky` is not passed.

| Arg / Flag | Default | Description |
| --- | --- | --- |
| `--plan` | `registries/update-plan.yml` | Explicit plan path. |
| `--approve-risky` | `false` | Unlock application of risky changes. |
| `--root` | `~/agentic_os` | Installed OS root. |

### `update rollback`

Records rollback intent against the latest snapshot in `logs/updates/snapshots/`.
In V1 this is a recorded intent; destructive restore of files remains
operator-driven from the snapshot YAML.

| Arg / Flag | Default | Description |
| --- | --- | --- |
| `--snapshot` | (latest) | Explicit snapshot path. |
| `--root` | `~/agentic_os` | Installed OS root. |

### `update status`

Reads `agentic-os.lock.json`, `registries/update-status.yml`, and the plan path
and prints current state. Read-only, exit 0 always.

| Arg / Flag | Default | Description |
| --- | --- | --- |
| `--root` | `~/agentic_os` | Installed OS root. |

### `update phone-home`

Assembles a heartbeat-safe operational metadata payload: install identity, channel,
policy, `.agentic_root` presence, `INVENTORY.md` presence, and registry counts. No
network request is made — the payload is printed for the operator to review and
forward.

| Arg / Flag | Default | Description |
| --- | --- | --- |
| `--root` | `~/agentic_os` | Installed OS root. |

### Receipt-backed post-release reinstall

`update watch-release` runs locally on each target host. It consumes an
upstream-produced published-release JSON/YAML receipt rather than creating or
guessing a release itself. A receipt must declare `published: true`, `draft:
false`, stable `version`, matching `tag`, and (when available) the exact
`source_revision`.

Patch and minor releases are eligible under `auto_patch_minor`; major releases
always require `--approve-major`. Older roots that deliberately retain
`operator_approved` need `--approve-release` for patch/minor releases. The
command is a plan by default. `--apply`
authorizes only that local target's transactional library reinstall; it never
opens SSH connections or executes a release remotely. A successful apply records
the release state and verifies object count, current content/projection hashes,
source revision, and any retained predecessor generation. A failed post-install
verification invokes the already-authorized transactional rollback and reports
the result.

```bash
agentic-os update watch-release \
  --root /srv/agentic_os \
  --release-receipt /srv/receipts/v1.2.4.json \
  --repository https://example.invalid/agentic-library.git

agentic-os update watch-release \
  --root /srv/agentic_os \
  --release-receipt /srv/receipts/v1.2.4.json \
  --repository https://example.invalid/agentic-library.git \
  --apply
```

Use `update verify-reinstall --release-receipt <receipt>` for a read-only
recheck. It fails if the receipt, object count, hashes, expected source revision,
or retained rollback generation disagree.

`update rollback-drill` proves the one-command library revert only on a test
target bearing an operator-created `.agentic-os-rollback-drill` marker. It plans
by default and needs both `--apply` and `--approve-rollback-drill` to mutate the
marked test root. It is never a production rollback command.

---

## Backup

### `backup run`

Plans or records a GitHub-backed OS state backup. **Dry-run by default.** Requires
`update register` first (reads the grant from `registries/update-grant.json`; raises
if absent). Reads `registries/backup-policy.yml` for include/exclude lists and the
remote URL.

| Arg / Flag | Default | Description |
| --- | --- | --- |
| `--dry-run` | ✅ (default) | Show backup plan; write a plan log; no git push. |
| `--apply` | — | Execute backup to the registered remote. |
| `--root` | `~/agentic_os` | Installed OS root. |

**Default backup scope (from `templates/runtime/backup-policy.yml`):**

Include: `.agentic_root`, `lib/`, `harness/AGENTS.md`,
`harness/artifact-config/`, `harness/ROUTER.md`, `harness/CONTEXT.md`,
`harness/RULES.md`, `harness/TOOLS.md`, `harness/bin/`, `harness/commands/`,
`harness/investigation-config/`, `harness/registries/`, `harness/rules/`,
`harness/skills/`, `harness/shared_factory/00-control-plane/`. The `lib/`
entry preserves canonical program objects; the two policy entries preserve
root artifact and investigation contracts.

Exclude: `projects/`, `harness/logs/`, `harness/security/ssh/*`, `**/.env`,
`**/*secret*`, `**/*token*`

The backup policy schema (`schemas/backup-policy.schema.json`) requires `enabled`,
`include`, `exclude`, and `remote` (name + url).

### `backup push`

Records a local backup-push run log. If the update grant is missing, the command
does not fail the operator loop; it writes `status: skipped_no_grant` with the
reason so the missing registration is visible. It does not print private keys or
secret-bearing file contents.

| Arg / Flag | Default | Description |
| --- | --- | --- |
| `--root` | `~/agentic_os` | Installed OS root. |

### `backup restore-plan`

Builds a read-only restore readiness plan from the latest backup log and
`registries/backup-policy.yml`. This command does **not** clone, copy, overwrite,
delete, or restore files. It reports:

- the latest backup log,
- registered backup remote metadata,
- include/exclude scope,
- coverage for critical installed harness paths,
- blockers such as missing update grant or missing backup log,
- the operator-reviewed steps required to restore safely.

| Arg / Flag | Default | Description |
| --- | --- | --- |
| `--backup-log` | latest `logs/backups/backup*.yml` | Plan from a specific backup log. |
| `--root` | `~/agentic_os` | Installed OS root. |

Use it before any restore-sensitive overhaul:

```bash
agentic-os backup run --root ~/agentic_os --dry-run
agentic-os backup restore-plan --root ~/agentic_os
```

The restore path remains operator-driven because the protected state includes
memories, active work, logs, and secret-adjacent configuration. The plan tells you
what is restorable and what must not be overwritten without explicit approval.

If the policy omits critical installed harness paths such as `harness/bin/`,
`harness/commands/`, `harness/skills/`, or `harness/rules/`, restore planning
returns `blocked`. Fix the backup policy and run a fresh backup dry-run before a
larger installed-root overhaul.

For tracker-claiming implementation work, pair this restore gate with
[24 · Auto-Dev Readiness](24-auto-dev-readiness.md) before starting `$auto-dev`.

---

## License

### `license activate`

Activates a customer license. The raw key is SHA-256 hashed and only the hash is
stored; the key is never printed or persisted. Writes license metadata to
`registries/customer-identity.json`.

| Arg / Flag | Required | Description |
| --- | --- | --- |
| `--key` | ✅ | Customer license key. |
| `--root` | — | Installed OS root (default `~/agentic_os`). |

`license activate` is the only `license` subcommand. It must succeed before
`update register` will run.

---

## Migrations

### `migrate plan`

Creates a reviewable migration plan for the installed root. Each migration has a
unique `migration_id`, a unified diff, an `approval_required` flag, and a
`rollback` description. The plan YAML is written to `.migrations/<id>.yml` for
review before apply. SHA-256 of the target file is recorded at plan time.

| Arg / Flag | Default | Description |
| --- | --- | --- |
| `--root` | `~/agentic_os` | Installed OS root. |

### `migrate apply`

Applies an approved migration by ID. Verifies the target file SHA-256 has not
changed since `migrate plan` was run; raises if it has, so no apply ever runs
against a modified target.

| Arg / Flag | Required | Description |
| --- | --- | --- |
| `migration_id` | ✅ (positional) | Migration ID from the plan. |
| `--root` | — | Installed OS root. |

The filesystem remains the source of truth. Apply only after the target workspace is
verified.

---

## Real output examples

### `update register`

```text
# CMD: agentic-os update register --root /tmp/aos-validate/root
# ---
root: /private/tmp/aos-validate/root
grant_path: /private/tmp/aos-validate/root/registries/update-grant.json
ssh_config: /private/tmp/aos-validate/root/security/ssh/config
remotes:
  update:
    name: agentic-os-update
    url: git@github.com:genome/local-agentic-os-updates.git
    access: read-only
  backup:
    name: agentic-os-backup
    url: git@github.com:genome/local-agentic-os-backups.git
    access: write
public_keys:
  update: ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPlHhLMpo1elQzVvOXwiKc+pB3Vvu+VPCEht+Js0NVYW
    agentic-os-update_ed25519
  backup: ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDfJ43rE+ucSnsDqpH3RU+UxCcx9po2CIsxrVGbEsa4m
    agentic-os-backup_ed25519
private_keys: stored locally under security/ssh with mode 0600
```

### `update check`

```text
# CMD: agentic-os update check --root /tmp/aos-validate/root
# ---
root: /private/tmp/aos-validate/root
installed_version: 0.1.0
available_version: 0.1.0
update_available: false
channel: stable
policy: operator_approved
mutated: false
risky_changes: []
```

### `update status`

```text
# CMD: agentic-os update status --root /tmp/aos-validate/root
# ---
root: /private/tmp/aos-validate/root
lock:
  installed_version: 0.1.0
  update_channel: stable
  update_policy: operator_approved
  status: installed
status:
  status: unknown
plan_path: ''
```

### `backup run --dry-run`

```text
# CMD: agentic-os backup run --root /tmp/aos-validate/root --dry-run
# ---
root: /private/tmp/aos-validate/root
log_path: /private/tmp/aos-validate/root/logs/backups/backup-20260529005118.yml
status: planned
dry_run: true
created_at: '2026-05-29T00:51:18Z'
remote:
  name: agentic-os-backup
  url: git@github.com:genome/local-agentic-os-backups.git
  access: write
include:
- .agentic_root
- AGENTS.md
- ROUTER.md
- CONTEXT.md
- RULES.md
- TOOLS.md
- registries/
- shared_factory/00-control-plane/
exclude:
- logs/
- security/ssh/*
- '**/.env'
- '**/*secret*'
- '**/*token*'
manifest: []
```

### `migrate plan`

```text
# CMD: agentic-os migrate plan --root /tmp/aos-validate/root
# ---
root: /private/tmp/aos-validate/root
migrations:
- migration_id: notion-sync-readme-v1
  purpose: Add the local Notion sync mapping contract README.
  target: /private/tmp/aos-validate/root/.notion-sync/README.md
  expected_sha256: null
  approval_required: true
  rollback: Remove the README or restore the previous file content from version control.
  diff: '--- /private/tmp/aos-validate/root/.notion-sync/README.md
    +++ /private/tmp/aos-validate/root/.notion-sync/README.md (proposed)
    @@ -0,0 +1,9 @@
    +# Notion Sync Mapping
    ...'
plan_path: /private/tmp/aos-validate/root/.migrations/notion-sync-readme-v1.yml
```

---

### Running this from Claude vs Codex

> Same update/backup logic, same grant file, same run logs — only the trigger differs.

- **Claude:** use the `/os-update` command or the **`update`** skill flows to step
  through `register → check → plan → apply`.
- **Codex:** run `agentic-os update register --root ~/agentic_os` then each
  subsequent subcommand in sequence. The `agentic_os_root` profile in
  `~/agentic_os/config.toml` governs approval policy and sandbox posture.

Full mechanics and harness config: [13 · Agent Surfaces](13-agent-surfaces.md).

---

## Guardrails & gotchas

- **`backup run` requires `update register` first.** The command raises immediately
  if `registries/update-grant.json` is absent. Run `update register` (and
  `license activate` before that) to create the grant.
- **Both `update pull` and `backup run` are dry-run by default.** Pass `--apply`
  to commit the action; omitting it is always safe.
- **`backup restore-plan` is always read-only.** It reports restore readiness and
  guarded steps; it does not restore files.
- **`update apply` blocks on risky changes.** Change types `executable`, `hook`,
  `mcp`, `rule`, and `permission` require explicit `--approve-risky`; safe additive
  paths (templates, registries, commands, skills, operating-manual) never require it.
- **`migrate apply` verifies SHA-256.** If the target file changes between
  `migrate plan` and `migrate apply`, the apply is refused. Rerun `migrate plan` to
  refresh.
- **`update rollback` records intent, not a live restore.** V1 writes rollback
  evidence to the status file; the actual file restore is operator-driven from the
  snapshot YAML.
- **Names are `snake_case`.** The OS rejects hyphens in domain/project names used
  as migration targets or registry keys.
- **Exit codes:** `0` = success; `1` = health check not ok; `2` = usage error or
  deliberate refusal (e.g. missing grant, risky changes blocked).
- **Always pass `--root` in scripts.** The default `~/agentic_os` will silently
  target a live install if omitted.

---

## Related

- [01 · Install & Quickstart](01-install-and-quickstart.md) — initial install that creates the root.
- [13 · Agent Surfaces](13-agent-surfaces.md) — Codex `config.toml` layer model and `config install`/`install-tree`/`config doctor` in full.
- [15 · Customer OS Factory](15-customer-os-factory.md) — `customer update` and per-customer backup posture.
- [16 · Health, Doctor & Validation](16-health-doctor-validation.md) — post-apply doctor checks.
- [17 · CLI Reference](17-cli-reference.md) — full flag index.
- [18 · Troubleshooting & FAQ](18-troubleshooting-and-faq.md) — common error messages.
- Atlas: [`architecture/command-reference.md` §11–12](architecture/command-reference.md) · real command output: re-run `docs/architecture/tools/validate-cli.sh` (receipts in gitignored `.validation/`)
