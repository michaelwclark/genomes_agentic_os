# Agent Handoff

## Objective

Implement Feature 62: role-aware, model-tiered Codex config layers. As of the
2026-06-02 local model catalog check, use `gpt-5.4-mini` for lightweight
navigation/routing layers and `gpt-5.5` for heavy project/workflow/automation
layers.

Start with `SPEC.md`. Treat it as the source of truth. The implementation is not
complete until every acceptance criterion in `SPEC.md` is mapped to code, tests,
docs, or an explicit recorded deferral.

## Context To Read First

1. `.agentic-atlas/START-HERE.md`
2. `features/62-role-aware-codex-config-layers/SPEC.md`
3. `features/62-role-aware-codex-config-layers/PLAN.md`
4. `features/62-role-aware-codex-config-layers/JUDGMENT.md`
5. Prior feature judgments:
   - `features/55-codex-config-profiles-per-agentic-os-layer/JUDGMENT.md`
   - `features/57-config-toml-installer-and-directory-setup/JUDGMENT.md`

## Files Likely To Change

- `src/genomes_agentic_os/config_ops.py`
- `src/genomes_agentic_os/customer.py`
- `tests/test_cli_scaffold.py`
- `docs/13-agent-surfaces.md`
- `.agentic-atlas/architecture/command-reference.md`, only if generated command output changes
- `.agentic-atlas/backlog.md` and `.agentic-atlas/gap-register.md`, only if new tracked follow-up work is created

## Required First Step

Run compatibility discovery before changing profile names:

```bash
rg -n "profiles\\.|--profile|project_orchestrator|workflow_orchestrator|automation_guard|project\\]" src tests docs .agentic-atlas templates
```

Record the result in `WORKLOG.md`. If existing public/generated profile keys are
found, represent them in `legacy_profiles`, render tested aliases, and document
the compatibility decision.

## Implementation Constraints

- Do not mutate `~/.codex`, `~/.codex/config.toml`, or `~/agentic_os` during tests.
- Use temporary roots.
- Do not overwrite existing local config values silently.
- Preserve no-inline-secret MCP policy.
- Keep native Codex keys in TOML.
- Keep richer Agentic OS role metadata in `config/codex-profile.yml` and
  prompt-visible markdown.
- If `PROFILE.md` is not actually model-visible, inject the role block into the
  existing loaded prompt artifact and document that fallback.

## Verification

Run:

```bash
.venv/bin/python -m pytest tests/test_cli_scaffold.py -q
.venv/bin/python -m pytest -q
bash .agentic-atlas/tools/validate-cli.sh
codex debug models
```

Then run the temporary-root prompt-input validation from `SPEC.md` and capture
evidence that `project_orchestrator` prompt input contains exactly one role block.

## Return Contract

Return:

- changed files;
- compatibility discovery result;
- acceptance criteria mapping;
- verification commands and results;
- any unresolved risks or deferrals.
