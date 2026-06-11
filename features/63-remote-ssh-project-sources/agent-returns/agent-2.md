# Agent 2 [worker]: P2 sync+doctor — status: done

## Branch/commit
`feat/63-remote-ssh-project-sources` `2f92ca3`

## Changed files
- `src/genomes_agentic_os/remote_ops.py` — new; sync engine with injectable runner
- `src/genomes_agentic_os/cli.py` — added `project sync-remote` subparser + handler; added `--check-remotes` to `config doctor`; imported `sync_project_remote` and `validate_project_remotes_connectivity`
- `src/genomes_agentic_os/validate.py` — imported `_remotes_from_config` + `load_hosts`; added `hosts.schema.json` to `SCHEMA_TARGETS`; added `validate_project_remotes` + `validate_project_remotes_connectivity`; wired `validate_project_remotes` into `validate_project_layer`
- `src/genomes_agentic_os/migrations.py` — added `HOSTS_MIGRATION_ID/TARGET/CONTENT` constants; `migrate_hosts_plan`, `migrate_hosts_apply`, `fix_missing_hosts_yml`; patched `migrate_apply` to dispatch to `migrate_hosts_apply` when `migration_id == HOSTS_MIGRATION_ID`
- `tests/test_remote_sources.py` — appended 24 new P2 tests across `TestSyncProjectRemote`, `TestDoctorRemoteValidation`, `TestMigrationHostsYml`

## Verification receipts
1. `.venv/bin/python -m pytest -q tests/test_remote_sources.py` → **67 passed** (43 P1 + 24 P2)
2. `.venv/bin/python -m pytest -q` → **382 passed, 0 failed** (baseline 358; delta +24)

## AC coverage

| AC | File:location |
|---|---|
| `sync_project_remote(root, domain, project, *, name, timeout, runner)` | remote_ops.py:sync_project_remote (line ~170) |
| git-kind: branch/head/dirty from ssh | remote_ops.py:_gather_git_info (~60) |
| folder-kind: no git block | remote_ops.py:sync_project_remote (~230) |
| listing capped at 200 + `listing_truncated` | remote_ops.py:_gather_listing (~105) |
| unreachable host → reachable: false, prior data kept, exit 0 | remote_ops.py:sync_project_remote (~250-270) |
| source-map row updated idempotently | remote_ops.py:_update_source_map_row (~130) |
| `agentic-os project sync-remote <domain> <project> [--name N] [--timeout S]` | cli.py parser (~241) + handle_project_sync_remote (~996) |
| `config doctor --check-remotes` flag + live probe | cli.py config_doctor parser (~503) + handle_config_doctor (~1233) + validate.py:validate_project_remotes_connectivity (~475) |
| `hosts.schema.json` registered in SCHEMA_TARGETS (malformed hosts.yml → error) | validate.py:SCHEMA_TARGETS ("hosts.schema.json" entry) |
| unknown host ref → error | validate.py:validate_project_remotes (~392) |
| missing REMOTE.md or manifest.yml → error | validate.py:validate_project_remotes (~398-410) |
| stale manifest (>14 days) → warning | validate.py:validate_project_remotes (~420-435) |
| null synced_at → warning | validate.py:validate_project_remotes (~415-418) |
| malformed remote entry (missing host/path) → error | validate.py:validate_project_remotes (~380-388) |
| `config doctor --fix-missing` / migrate flow creates hosts.yml | migrations.py:fix_missing_hosts_yml + migrate_hosts_apply (~100-130) |

## Decisions/risks

1. **`validate_project_layer` host-ref check gating**: When `config/hosts.yml` doesn't exist on disk, `validate_project_remotes` is called with `hosts=None` and skips the host-reference check — avoiding false errors on pre-migration installs. When the file exists but is empty (`hosts={}`), any reference is an error. This is the correct semantic but is a non-obvious distinction. The call site comment documents it.

2. **`--check-remotes` wired through `handle_config_doctor` with local imports**: The `validate_project_remotes_connectivity` call is a local import inside the handler to avoid a circular import risk at module level (validate already imports from scaffold; cli already imports from validate; validate does not import from cli). This is consistent with the existing codebase's pattern for optional feature toggles.

3. **migrations.py pattern**: The existing module hardcodes one migration via module-level constants. P2 follows the same pattern in parallel (separate `HOSTS_*` constants + separate plan/apply functions) rather than refactoring to a registry, to avoid touching P1 behavior. The `migrate_apply` dispatch is the only shared entry point changed. If a third migration is added, refactoring to a registry is advisable (flagged as follow-up, not done here per scope rules).

4. **`subprocess.run` `noqa: S603`**: SSH argv is constructed as a list (never `shell=True`), host alias and remote path are shlex-quoted when embedded in remote shell commands. The noqa annotation is accurate.

5. **No handoff items for P1 files**: The P1 functions (`append_project_remote_refs`, `remote_manifest_stub`, `ensure_project_remote_dirs`) were not modified. Their behavior is unchanged.
