# Worklog: Feature 63 Remote SSH Project Sources

Append-only receipts. Created: 2026-06-11 12:29 CDT

## Baseline (2026-06-11 12:29 CDT)

- Base commit: `f142db2` on `main` (includes pre-existing WIP committed separately: in-place worktree validation fix; decision recorded in PLAN.md).
- Branch: `feat/63-remote-ssh-project-sources`
- `.venv/bin/python -m pytest -q` → **315 passed in 31.43s**
- `bash .agentic-atlas/tools/validate-cli.sh` → **53 OK, 2 GUARDED, 0 FAIL** (scratch writes to `.agentic-atlas/validation/` reverted; full output preserved at `/tmp/f63-validate-cli-baseline.txt`)

## U1 accepted (2026-06-11 12:53 CDT)

- Agent 1 commit `91fd30c`: hosts.py + hosts.schema.json + scaffold remotes + create/link-remote/host CLI + tests/test_remote_sources.py (43 tests). Full return in `agent-returns/agent-1.md`.
- Orchestrator re-verification: `.venv/bin/python -m pytest -q` → **358 passed in 34.89s** (baseline 315 + 43, zero regressions); diff inspected — only owned files committed, REMOTE.md generator clean (alias-only ssh, BatchMode form, mirror warning), manifest stub via `write_file_once`, conflict handling in `link_project_remote` via `_upsert_remote_in_config(force=...)`.
- Note: agent 1 also delivered `host add`/`host list` CLI (planned for U2); accepted — removes U2's only hosts.py/cli-host contention. U2 scope reduced accordingly.
- Handoff to U2: register `hosts.schema.json` in validate.py `SCHEMA_TARGETS` (~line 651); doctor checks for unknown host refs, missing remote marker files, malformed hosts.yml, stale manifests.

## U2 accepted (2026-06-11 13:05 CDT)

- Agent 2 commit `2f92ca3`: remote_ops.py sync engine, `project sync-remote` + `config doctor --check-remotes` CLI, validate.py remote checks + hosts schema registration, `hosts-yml-init-v1` migration, 24 new tests. Full return in `agent-returns/agent-2.md`.
- Orchestrator re-verification: `.venv/bin/python -m pytest -q` → **382 passed in 35.80s** (358 + 24, zero regressions); only owned files in commit.
- Security holdout (orchestrator, ssh surface): argv-list invocations only, `BatchMode=yes` in `_build_base_cmd`, `shlex.quote` on remote paths, no `shell=True` anywhere, injectable runners in both remote_ops and the doctor probe, connectivity probe opt-in and never raises. PASS.
- Accepted decisions: `hosts=None` skips host-ref checks pre-migration (avoids false errors on old installs); migrations.py parallel-constants pattern kept, registry refactor deferred.

## Orchestrator integration fix (2026-06-11 13:18 CDT)

- Agent 2 wired `--check-remotes` onto `config doctor` (codex config-contract doctor, requires `--layer`) — wrong surface; root cause was ambiguous wording in the dispatch prompt. Moved flag + probe to the root `agentic-os doctor` command; probe warnings no longer flip doctor `ok` (offline is a warning state per spec). Commit `2146df0`; full suite re-run → **382 passed in 41.41s**.
- Post-P2 gate: `bash .agentic-atlas/tools/validate-cli.sh` → **53 OK, 2 GUARDED, 0 FAIL** (matches baseline; output at `/tmp/f63-validate-cli-post.txt`).

## U3 rollout (2026-06-11 13:30 CDT)

All commands run with the branch CLI (`.venv/bin/agentic-os`, editable install) against live root `~/agentic_os`:

- `host add genomesbox --ssh-alias genomesbox --user genome --description ...` → created `config/hosts.yml`; `ssh_options` (ClearAllForwardings) + `paths` added by hand (CLI does not expose them — follow-up below).
- `project create los losmon --remote-host genomesbox --remote-path /home/genome/projects/losmon --repo ~/projects/losmon --lane engineering` → full room at `los/02-projects/losmon/` with `src -> /Users/genome/projects/losmon` and `remote/losmon/{REMOTE.md,manifest.yml}`.
- `project sync-remote los losmon` → live ssh sync OK: `reachable: true`, `synced_at: 2026-06-11T17:56:03Z`, git branch `main`, head `cc37caa`, `dirty: true`; source-map row updated to `synced 2026-06-11`.
- `doctor --root ~/agentic_os` → **zero feature-63 findings**. Pre-existing, NOT caused by this work: 3 blockers on half-created `los_app_rulesengine_nodejs` room, 2 clarks_consulting active-work rows, 2 run-log closeouts, 1 cleanup, 1 observation. Self-caused fix-soon (losmon active-work placeholder) cured by setting a concrete next action; re-run shows 0 findings on `los/00-control-plane/active-work.md`.
- `doctor --check-remotes` → 0 unreachable hosts (live probe to genomesbox OK).

## Follow-ups (filed, not blocking)

- `host add` CLI does not expose `--ssh-option` / `--path`; hosts.yml hand-edit required for those fields. Candidate small follow-up feature.
- migrations.py parallel-constants pattern: refactor to a registry when a third migration lands (agent 2 note).
- Pre-existing doctor blockers on `los_app_rulesengine_nodejs` (half-created room) predate feature 63.
