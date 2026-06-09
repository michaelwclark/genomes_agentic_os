# Implementation Plan

## Phase 1: Policy, Compatibility Discovery, And Rendering

- Run the compatibility discovery pass from `SPEC.md` and record the results in `WORKLOG.md`.
- Add `LAYER_POLICIES` or an equivalent field-addressable policy map in `src/genomes_agentic_os/config_ops.py`.
- Replace hardcoded model strings in `config_template` with policy-driven rendering.
- Generate native Codex TOML only from policy values.
- Generate `PROFILE.md` and `config/codex-profile.yml`.
- Wire `policy.prompt_files` into the actual prompt-stitching or generated prompt artifact path.
- Update `config install`, `config install-tree`, and `doctor` to report/create/conflict-check all managed files.

## Phase 2: Customer Factory And Merge Safety

- Replace hardcoded model strings in `src/genomes_agentic_os/customer.py`.
- Use a customer-safe policy map or derived customer policy.
- Add rendered-artifact tests for customer role text, allowed role identifiers, explicit MCP allowlist behavior, and split privacy scans.
- Extend conflict tests for `PROFILE.md` and `config/codex-profile.yml` across missing, managed changed, and pre-existing unmanaged file cases.

## Phase 3: Docs, Atlas, And Holdout Validation

- Update `docs/13-agent-surfaces.md` for role-aware model tiers, prompt-visible role artifacts, managed ownership, customer scan modes, and temporary-root prompt-input validation.
- Update atlas command docs only if generated output changes.
- Run targeted tests, full tests, atlas validation, `codex debug models`, and temporary-root prompt-input validation.

## Suggested Work Breakdown

- Worker 1: policy map, TOML renderer, sidecar renderer, prompt artifact renderer.
- Worker 2: source-package tests for policy values, generated files, install-tree, and conflicts.
- Worker 3: customer factory policy and customer privacy tests.
- Worker 4: docs, atlas updates, and prompt-input validation recipe.
- Orchestrator: compatibility discovery, integration, verification, and acceptance mapping.
