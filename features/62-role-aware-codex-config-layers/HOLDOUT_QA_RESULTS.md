# Holdout QA Results

## 2026-06-02

Result: pass.

Evidence:

- `.venv/bin/python -m pytest tests/test_cli_scaffold.py -q`: `86 passed in 11.20s`.
- `.venv/bin/python -m pytest -q`: `89 passed in 13.21s`.
- `bash .agentic-atlas/tools/validate-cli.sh`: `53 OK`, `2 GUARDED`, `55 commands`.
- `codex debug models`: current catalog includes `gpt-5.4-mini`, `gpt-5.4`, and `gpt-5.5`; `gpt-5.2` is not listed.
- `codex debug prompt-input 'feature 62 validation'` from `/tmp/aos-feature62-GfvcG9`: rendered the managed project role block from `AGENTS.md`, including `Role: orchestrator`, `Layer: project`, `Profile: project_orchestrator`, `Default model: gpt-5.5`, and `Reasoning effort: high`.

Notes:

- Current Codex `debug prompt-input` does not expose the older `--profile` flag. Validation used the current command from the generated project-layer directory.
- `PROFILE.md` remains generated as the tool-visible role artifact. The same short role block is mirrored into generated `AGENTS.md` because that is what current prompt-input includes.

## 2026-06-09

Result: pass.

Evidence:

- `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_cli_scaffold.py -k 'config_install or customer_init_generates_public_customer_os_from_profile or update_apply_migrates_legacy_root_layout_to_harness'`: `12 passed, 82 deselected`.
- `PYTHONPATH=src .venv/bin/python -m pytest -q`: `97 passed`.
- Detached staged-tree verification:
  - `PYTHONPATH=<staged-worktree>/src .venv/bin/python -m pytest -q tests/test_cli_scaffold.py -k 'config_install or customer_init_generates_public_customer_os_from_profile or update_apply_migrates_legacy_root_layout_to_harness'`: `12 passed, 82 deselected`.
  - `PYTHONPATH=<staged-worktree>/src .venv/bin/python -m pytest -q`: `97 passed`.
  - `AOS=<repo>/.venv/bin/agentic-os PYTHONPATH=<staged-worktree>/src bash .agentic-atlas/tools/validate-cli.sh`: `53 OK`, `2 GUARDED`, `55 commands`.
