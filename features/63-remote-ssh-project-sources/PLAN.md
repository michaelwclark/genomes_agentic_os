# Plan: Feature 63 Remote SSH Project Sources

Created: 2026-06-11 12:29 CDT
Mode: quiet orchestration, duel skipped by user decision (design space small, spec locks the contentious calls).

## Decomposition

| Unit | Agent | Deliverable | Owned files | Depends on |
| --- | --- | --- | --- | --- |
| U1: P1 schema + scaffold + CLI | worker 1 (Sonnet) | `sources.remotes` parsing, hosts registry module + schema, `remote/<name>/` materialization, AGENTS/CONTEXT remote sections, `project create --remote-*`, `project link-remote`, tests | `src/genomes_agentic_os/hosts.py` (new), `src/genomes_agentic_os/scaffold.py`, `src/genomes_agentic_os/cli.py`, `schemas/hosts.schema.json` (new), `tests/test_remote_sources.py` (new) | — |
| U2: P2 sync + doctor + host CLI | worker 2 (Sonnet) | `project sync-remote` with injectable runner, `host add`/`host list`, doctor checks + staleness + `--check-remotes`, migration entry, tests | `src/genomes_agentic_os/remote_ops.py` (new), `src/genomes_agentic_os/cli.py`, `src/genomes_agentic_os/validate.py`, `src/genomes_agentic_os/migrations.py`, `tests/test_remote_sources.py` (append) | U1 |
| U3: P3 rollout + final gates | orchestrator | host add genomesbox; project create los/losmon; sync-remote; doctor clean against `~/agentic_os`; merge | `~/agentic_os` (live), merge to `main` | U2 |

## Sequencing and contention

U1 → U2 → U3 strictly serialized in the primary checkout on branch `feat/63-remote-ssh-project-sources` — U1 and U2 both touch `cli.py` and `tests/test_remote_sources.py`, so no parallel fan-out. `hosts.py` is fully built in U1 (load/save/upsert/list) so U2 never edits it.

## Allocated identifiers

- Branch: `feat/63-remote-ssh-project-sources` (created from `main` at `f142db2`)
- Commit style: imperative subject, no conventional prefix (repo convention), feature 63 named in body
- New modules: `hosts.py`, `remote_ops.py`; new schema `schemas/hosts.schema.json`; new test file `tests/test_remote_sources.py`

## Pre-work decisions (do not re-litigate)

- Representation = `remote/<name>/REMOTE.md` (managed) + `manifest.yml` (sync-owned). No mounts, no clones.
- Alias-only connectivity; `~/.ssh/config` owns transport; no secrets in tree.
- `sources.repo` keeps meaning local mirror path; remotes are a new `sources.remotes` list.
- Offline host → `reachable: false`, exit 0; staleness >14 days → doctor warning; live probe only behind `--check-remotes`.
- Pre-existing WIP (in-place worktree validation fix) committed separately as `f142db2` before feature work, full suite green.
