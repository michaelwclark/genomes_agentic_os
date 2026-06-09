# Holdout QA

## Checks

- Fresh OS install creates role-aware `config.toml` at the OS root with the verified lightweight model.
- Domain creation creates or repairs a navigator profile for that domain.
- Project onboarding creates a heavy-work orchestrator profile.
- Workflow creation creates a heavy-work workflow orchestrator profile.
- Automation creation creates an automation guard profile with explicit approval posture.
- `config install-tree --dry-run` reports missing configs, sidecars, and role artifacts without writing.
- `config install-tree --apply` writes missing artifacts into a temporary root.
- Existing `config.toml` with a local model override is not silently overwritten.
- Pre-existing unmanaged `PROFILE.md` and `config/codex-profile.yml` are not overwritten.
- Managed changed `PROFILE.md` and `config/codex-profile.yml` are conflict-reported before write.
- Customer OS generation emits customer-safe role/model policy and passes full-artifact forbidden-term scans with only exact ownership metadata exceptions.
- Extracted customer user-visible role text passes forbidden-term scans with zero exceptions.
- Generated MCP entries keep env var names only and no inline secrets.
- `codex debug prompt-input` from a generated temporary layer shows the managed role block mirrored into `AGENTS.md`.

## Commands

```bash
.venv/bin/python -m pytest tests/test_cli_scaffold.py -q
.venv/bin/python -m pytest -q
bash .agentic-atlas/tools/validate-cli.sh
codex debug models
codex debug prompt-input 'feature 62 validation'
```

Use temporary roots only. Do not mutate the user's live `~/agentic_os` during
holdout QA.
