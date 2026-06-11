# Pre-Duel Brief: Feature 63 Remote SSH Project Sources

## Why this exists

`losmon` is the flagship always-on system and it is authoritative on `genomesbox` (`/home/genome/projects/losmon`), yet the installed OS at `~/agentic_os` has no representation of it — agents routed through the OS cannot discover it, its artifacts, or how to reach it. The Mac checkout at `~/projects/losmon` is a reference copy only and must never be treated as the running system. The fix must be an installer capability, not a hand-built directory, so every future remote project (and customer installs) gets the same treatment.

## Codebase facts the critic should hold the spec against

- Projects are scaffolded by `create_project()` in `src/genomes_agentic_os/scaffold.py` (~line 2746); project rooms live at `<domain>/02-projects/<project>/` with project.yml, source-map.md, status.md, decisions.md, work-items lanes, artifacts/, worktrees/, and managed AGENTS/ROUTER/CONTEXT/RULES/TOOLS/MEMORY files written via `write_project_file` with `replace_markers`.
- `sources.repo` is a plain string; `ensure_project_source_link` (~line 2521) symlinks `src/` only for local paths, and `link_project_source` (~line 2579) raises on non-local paths. `is_remote_repo_reference` (~line 2508) already exists but only recognizes git URLs, not ssh working trees.
- Doctor is `agentic-os config doctor --root ~/agentic_os [--fix-missing]` backed by `validate.py` (validate_root ~line 869, strict schema validation ~line 690); migrations exist (PLAN 07).
- `source_providers.py` (line 28) establishes the injectable-fetcher test seam pattern; sync-remote must follow it.
- PLAN 16 (connected-source-watch-registry) covers polling GitHub/Slack/Jira/Notion — it does not cover ssh working trees; this feature must not fork a competing watch mechanism, just leave a clean later integration point.
- Strictest rules: no secrets in registries (`no-secret-registry-values`), managed-file merge policies in `schemas/managed-templates.schema.json`.

## Constraints already decided (do not re-litigate, attack their consequences)

- No mounts (sshfs rejected outright). Representation = `remote/<name>/` marker dir + synced manifest.
- Alias-only connectivity; `~/.ssh/config` owns the transport.
- Offline host = warning, never failure (except explicit `--check-remotes`).
- Local mirror stays `sources.repo` + `src/` symlink; remote trees are a new `sources.remotes` list.

## Where the critic should press

- Schema evolution: does `sources.remotes` survive contact with `set_project_repo`/`project_repo_from_config` round-tripping project.yml through yaml.safe_dump?
- Managed-section updates to existing AGENTS.md/CONTEXT.md in already-installed rooms: will `replace_markers` actually fire on the in-the-wild file contents, or does this need a migration?
- Staleness semantics: is 14 days right, and should sync-remote stamp source-map.md at all (churn vs signal)?
- Multi-remote projects: naming collisions, manifest cap (200 entries) adequacy, `kind: folder` listing depth.
- Doctor `--check-remotes`: BatchMode probe failure modes when ControlMaster sockets or local forwards exist (the ClearAllForwardings precedent on genomesbox).
- Rollout idempotency: running P3 twice must be a no-op; does `write_file_once` + append-once cover all new artifacts?
