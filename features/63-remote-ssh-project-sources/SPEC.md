# Feature 63: Remote SSH Project Sources

## Status

- Phase: implemented and rolled out (P1 `91fd30c`, P2 `2f92ca3`, integration fix `2146df0`; losmon room live in `~/agentic_os` 2026-06-11). Duel skipped by user decision.
- Owner: OS Owner
- Created: 2026-06-11
- Driving case: `losmon` is authoritative on `genomesbox` (`/home/genome/projects/losmon`) but has no representation in the installed OS tree. The Mac checkout at `~/projects/losmon` is a reference copy only.

## Vision

Remote hosts, and the project working trees that live on them, become first-class declared sources in the installed Agentic OS. The project room in the OS tree is always local — artifacts, work-items, decisions, status, and logs live in the OS exactly as they do for local projects — while the code may be authoritative on a remote host reachable via ssh.

The OS tree represents a remote source with managed marker files and refreshed snapshots, never with mounts. An agent routed into the project room learns three things without leaving the tree: where the authoritative code lives, exactly how to reach it over ssh, and that any local mirror is reference-only.

This is an installer-level capability: it ships in `genomes_agentic_os`, is validated by doctor, and is then applied to the root instance (`~/agentic_os`) by running the new commands — not a hand-built one-off directory.

## Architecture

### Host registry — `<root>/config/hosts.yml`

A new managed-once file at the installed OS root, validated by a new `schemas/hosts.schema.json`:

```yaml
hosts:
  genomesbox:
    ssh_alias: genomesbox            # must resolve via ~/.ssh/config; no creds here
    user: genome
    description: Always-on Linux box. LOSMON and genomes_brain memory MCP are authoritative here.
    ssh_options:
      - "-o"
      - "ClearAllForwardings=yes"
    paths:                           # notable folders worth knowing about, project or not
      - path: /home/genome/projects/losmon
        purpose: LOSMON authoritative checkout
```

Rules:

- Alias-based only. No hostnames-with-credentials, no keys, no ports with secrets — `no-secret-registry-values` applies. Connectivity details live in `~/.ssh/config`, which the OS references but never owns.
- `host` values used anywhere else in the OS (project remotes) must be keys in this registry. Doctor enforces referential integrity.
- `paths` is informational registry data; onboarding a path as a project remote is a separate explicit step.

### project.yml sources extension

Backward compatible — `sources.repo`, `sources.notion`, `sources.jira` keep their current string shapes. New optional key:

```yaml
sources:
  repo: ~/projects/losmon            # optional LOCAL mirror; reference-only when a remote is authoritative
  remotes:
    - name: losmon                   # defaults to project name; unique within the project
      host: genomesbox               # key into <root>/config/hosts.yml
      path: /home/genome/projects/losmon
      kind: git                      # git | folder
      authority: remote              # remote | local — which checkout owns truth
```

- `kind: git` remotes get git facts in their manifest (branch, HEAD, dirty state); `kind: folder` remotes get listings only. This covers "other folders" that are not repos.
- `authority: remote` is the losmon case. `authority: local` covers the inverse (local repo, remote deploy copy worth tracking).

### Materialization — what lands in the project room

For each entry in `sources.remotes`, scaffold creates `<project>/remote/<name>/` containing:

1. `REMOTE.md` — managed file (uses the existing `write_project_file` + `replace_markers` mechanism so installer updates can refresh it). Contents: authority statement, the exact connect commands (`ssh -o ClearAllForwardings=yes genomesbox`, then `cd /home/genome/projects/losmon`), non-interactive command form for agents, and a warning naming the local mirror as reference-only when one exists.
2. `manifest.yml` — snapshot owned by `sync-remote`. Scaffold writes an initial stub with `reachable: unknown`. After a sync:

```yaml
name: losmon
host: genomesbox
path: /home/genome/projects/losmon
kind: git
authority: remote
reachable: true
synced_at: 2026-06-11T18:40:00Z
git:
  branch: main
  head: <sha>
  dirty: false
listing:                             # depth-1 names only, capped at 200 entries
  - src
  - package.json
```

Additionally:

- `source-map.md` gains one row per remote: `| Remote (genomesbox) | genomesbox:/home/genome/projects/losmon | Authoritative working tree | synced 2026-06-11 |`.
- Project `AGENTS.md` and `CONTEXT.md` templates gain a remote-sources section (managed via `replace_markers`): code is authoritative on `<host>`; reach it via the commands in `remote/<name>/REMOTE.md`; artifacts, work-items, and decisions stay local in this room.
- The `src/` symlink behavior is unchanged: it points at `sources.repo` when that is a local path ([scaffold.py](../../src/genomes_agentic_os/scaffold.py) `ensure_project_source_link`, ~line 2521). A remote-authoritative project with a local mirror gets both: `src/` → mirror (reference) and `remote/<name>/` (authority).

### CLI

- `agentic-os project create <domain> <project> ... --remote-host H --remote-path P [--remote-name N] [--remote-kind git|folder] [--authority remote|local]` — extends the existing create parser (cli.py ~line 167).
- `agentic-os project link-remote <domain> <project> --host H --path P [--name N] [--kind K] [--authority A] [--force]` — attach a remote to an existing project; mirrors `link-source` semantics including conflict behavior.
- `agentic-os project sync-remote <domain> <project> [--name N] [--timeout SECONDS]` — refreshes `manifest.yml` and the source-map row. Runs `ssh -o BatchMode=yes` with the host's `ssh_options`; never interactive. Unreachable host → `reachable: false` + warning, exit 0 (offline is a normal state, not an error).
- `agentic-os host add <alias> [--ssh-alias A] [--user U] [--description D]` and `agentic-os host list` — manage `config/hosts.yml`.
- Doctor (`validate.py`): hosts.yml conforms to schema; every `sources.remotes[].host` exists in hosts.yml; every declared remote has its `remote/<name>/REMOTE.md` and `manifest.yml`; manifests older than 14 days → warning. No network calls by default; `--check-remotes` flag performs a live `ssh -o BatchMode=yes <alias> true` probe.

### Test seam

`sync_remote` takes an injectable command-runner callable (same pattern as `source_providers.py` fetcher injection at line 28) so unit tests never open a real ssh connection. Tests cover: schema validation, scaffold output, manifest writing for git and folder kinds, unreachable-host handling, doctor findings, CLI argument wiring.

## Phases

### P1: Schema + scaffold

hosts.yml schema and loader; `sources.remotes` parsing; `remote/<name>/` materialization (REMOTE.md, manifest stub); source-map rows; AGENTS/CONTEXT managed sections; `project create` and `link-remote` CLI.

### P2: Sync + doctor

`sync-remote` with injectable runner; `host add` / `host list`; doctor checks including staleness and `--check-remotes`; migration entry so `config doctor --fix-missing` repairs existing installs.

### P3: Rollout to root instance

On the Mac, against `~/agentic_os`:

```bash
agentic-os host add genomesbox --ssh-alias genomesbox --user genome --description "Always-on box; losmon authoritative"
agentic-os project create los losmon --remote-host genomesbox --remote-path /home/genome/projects/losmon --repo ~/projects/losmon
agentic-os project sync-remote los losmon
agentic-os config doctor --root ~/agentic_os
```

Resulting tree: `los/02-projects/losmon/` with the full standard room (work-items, artifacts, logs, decisions) plus `remote/losmon/` and `src/` → `~/projects/losmon`.

## Acceptance Criteria

- A project can declare one or more remote ssh sources in `project.yml` without breaking any existing project config.
- Scaffold materializes `remote/<name>/REMOTE.md` and `manifest.yml` for every declared remote, and the project's AGENTS.md/CONTEXT.md state remote authority and the connect path.
- `sync-remote` records git facts and a capped listing for a reachable host, and records `reachable: false` without failing for an unreachable one.
- Doctor flags: unknown host references, missing remote marker files, malformed hosts.yml, stale manifests (warning).
- No secrets, hostnames-with-credentials, or ssh keys appear anywhere in the OS tree; connectivity is alias-only.
- Full pytest suite passes; `validate-cli.sh` passes; running P3 against `~/agentic_os` produces a doctor-clean losmon room.

## Risks

- ssh from scaffold/sync code is a new side-effect class for the installer; mitigated by BatchMode-only, timeouts, injectable runner, and keeping doctor offline by default.
- Manifest snapshots can mislead if stale; mitigated by `synced_at` being prominent in REMOTE.md guidance and the doctor staleness warning.
- Two checkouts (mirror + remote) invite agents to edit the wrong one; mitigated by authority language in REMOTE.md/AGENTS.md being explicit and repeated, mirroring the existing losmon AGENTS.md wording on genomesbox.

## What's NOT in v1

- sshfs or any mounted representation of remote trees (macFUSE dependency, hang risk for agents, accidental remote writes). Rejected, not deferred.
- Automatic rsync mirroring or two-way sync of code (changes authority semantics; the mirror remains a manually-managed reference copy).
- Scheduled/automated sync-remote runs (can later ride PLAN 15/16 runtime + watch registries; v1 is on-demand).
- Remote work execution helpers (running tests over ssh, remote worktrees). The room teaches the path; agents use their own ssh skills.
- Representing remote hosts' non-project folders beyond hosts.yml `paths` entries and `kind: folder` project remotes.

## Open Decisions Locked By This Spec

- Representation is marker-files-plus-manifest, not mounts and not clones. ("How is the remote folder represented in the file tree?" → a `remote/<name>/` directory with managed REMOTE.md + synced manifest.yml.)
- Host connectivity lives in `~/.ssh/config`; the OS stores aliases only.
- `sources.repo` keeps meaning "local path worth symlinking"; remote working trees are a new `sources.remotes` list, not an overload of `repo`.
- Offline hosts are a warning state, never a hard failure, everywhere except an explicit `--check-remotes` probe.
