# Agent 1 Return — P1: Schema + scaffold

## Evidence / Commands Run

### Baseline
- Branch: `feat/63-remote-ssh-project-sources` (already checked out)
- Pre-work test count: 315 passed (from task prompt)

### Context gathered
- Read SPEC.md fully
- Read scaffold.py: project_config (L1909), project_agents (L2012), project_context (L2059), ensure_project_operating_surface (L2444), create_project (L2961), set_project_repo (L2777), append_project_source_refs (L2417), onboard_project (L2939), link_project_source (L2794)
- Read cli.py: imports (L66-78), project create args (L169-178), project link-source (L179-189), handle_project_create (L906-919), handle_project_link_source (L922), main() error handler (L1571-1578)
- Read validate.py: SCHEMA_TARGETS dict (L626-651) — data-driven mapping
- Read schemas/domain.schema.json for style reference
- Read tests/test_cli_scaffold.py: fixture patterns, tmp_path usage, main() invocation

### Verification
```
.venv/bin/python -c "from genomes_agentic_os.hosts import ..."    → hosts OK
.venv/bin/python -c "from genomes_agentic_os.scaffold import ..." → scaffold OK
.venv/bin/python -c "from genomes_agentic_os.cli import main"     → cli OK
.venv/bin/python -m pytest -q tests/test_remote_sources.py        → 43 passed in 3.58s
.venv/bin/python -m pytest -q                                     → 358 passed in 33.86s
```

Zero regressions. Baseline was 315; post-work is 358 (+43 new tests).

---

## AC Coverage

| AC | File:location |
|---|---|
| Project can declare remote SSH sources in project.yml without breaking existing configs | scaffold.py: project_config() optional `remotes` param, backward compat defaults |
| Scaffold materialises remote/<name>/REMOTE.md | scaffold.py: ensure_project_remote_dirs(), remote_readme_content() |
| Scaffold materialises remote/<name>/manifest.yml stub | scaffold.py: remote_manifest_stub(), write_file_once() ensures no overwrite |
| AGENTS.md/CONTEXT.md include Remote Sources section only when remotes declared | scaffold.py: project_agents(), project_context() with remotes param |
| source-map.md gets one row per remote | scaffold.py: append_project_remote_refs() |
| project create --remote-host/--remote-path/--remote-name/--remote-kind/--authority | cli.py: L177-184, handle_project_create() L906 |
| project link-remote attaches remote to existing project | scaffold.py: link_project_remote(); cli.py: handle_project_link_remote() |
| link-remote conflict without --force → error | scaffold.py: _upsert_remote_in_config(), raises ValueError |
| link-remote --force replaces existing remote of same name | scaffold.py: _upsert_remote_in_config() |
| yaml round-trip through set_project_repo preserves remotes | scaffold.py: set_project_repo() unchanged (already uses safe_load/safe_dump which preserves dict structure) |
| onboard_project re-materialises remote dirs from project.yml | scaffold.py: onboard_project() calls _remotes_from_config() + passes to ensure_project_operating_surface() |
| project without remotes unchanged (no remote/ dir) | scaffold.py: ensure_project_operating_surface() only calls ensure_project_remote_dirs if remotes truthy |
| REMOTE.md pulled from hosts.yml ssh_options when host registered | scaffold.py: _remote_ssh_connect_cmd() calls load_hosts() |
| host add / host list CLI | cli.py: handle_host_add(), handle_host_list(); hosts.py: upsert_host(), list_hosts() |
| hosts.schema.json matches domain.schema.json style | schemas/hosts.schema.json |
| No secrets in any generated file | hosts.py: no credential fields; remote_readme_content() never writes keys/passwords |

---

## Decisions / 50-50 Calls

1. **project_agents/project_context marker phrases**: The original functions did NOT have the replace_markers phrases in their content, which meant `write_project_file` would never refresh them on re-run for existing projects. I added the marker phrase texts into the generated content so that `ensure_project_operating_surface`'s `replace_markers=` parameter works correctly on onboard/repair. This is required for the remote section to be injected on onboard. The marker phrases added: `"This file is the harness-neutral entrypoint for this Agentic OS layer"` (AGENTS.md) and `"Describe the local room, source systems, routing hints"` (CONTEXT.md).

2. **SCHEMA_TARGETS mapping for hosts.schema.json**: The mapping in validate.py (L626-651) is a data-driven dict in validate.py code, not in the schemas/ directory. The task says NOT to edit validate.py (agent 2 owns it). Therefore `hosts.schema.json` is created but NOT yet registered in SCHEMA_TARGETS. **Handoff item for agent 2**: Add `"hosts.schema.json": ["**/config/hosts.yml"]` to the `SCHEMA_TARGETS` dict in validate.py around line 651. Also add a doctor check for: unknown host references in sources.remotes, missing remote marker files, malformed hosts.yml.

3. **link_project_remote AGENTS.md/CONTEXT.md refresh**: Re-runs `write_project_file` with updated full remotes list (including newly added remote) so the section is always current after link-remote. Uses existing replace_markers mechanism.

4. **onboard_project remotes passthrough**: onboard_project now reads remotes from project.yml via `_remotes_from_config()` and passes them to `ensure_project_operating_surface()`. This means REMOTE.md can be re-created if deleted (idempotent repair). Manifest stub is still write_file_once — sync-remote (agent 2/P2) owns it after creation.

5. **_remotes_from_config exported**: Made public via `__init__` passthrough so tests can import it. It is also used by onboard_project and link_project_remote internally.

---

## Files Changed

- `src/genomes_agentic_os/hosts.py` (new)
- `schemas/hosts.schema.json` (new)
- `tests/test_remote_sources.py` (new, 43 tests)
- `src/genomes_agentic_os/scaffold.py` (modified — new helpers + extended existing functions)
- `src/genomes_agentic_os/cli.py` (modified — new args, parsers, handlers)

## Branch / Commit

Branch: `feat/63-remote-ssh-project-sources`
SHA: `91fd30c`
