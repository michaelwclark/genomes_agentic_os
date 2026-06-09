<!--
  Spec produced by the Duel skill (~/.claude/skills/duel/)
  Duel ID:        2026-06-02-feature-62-codex-local
  Started:        2026-06-02T18:34:18.952Z
  Ended:          2026-06-02T18:41:50.579Z
  Termination:    PASS
  Final artifact: final-spec.md
  Total rounds:   5
  Total cost:     $0.0000 of $20.00 cap
  Writer:         codex-cli (default)
  Critic:         codex-cli (default)
-->

# Feature 62: Role Aware Codex Config Layers

## Status

- Status: planned
- Owner: Genome operators
- Created: 2026-06-02
- Target OS layer: source package, installed OS root, domains, projects, workflows, automations, customer OS factory
- Related completed features: `54-config-toml-options-inventory-and-analysis`, `55-codex-config-profiles-per-agentic-os-layer`, `56-universal-agent-brain-convention-and-prompt-stitching`, `57-config-toml-installer-and-directory-setup`, `58-otel-and-mcp-configuration-contracts`, `59-codex-config-documentation-and-holdout-validation`

## Vision

Codex config generation should make the active agent role explicit to both the Codex CLI and the model. Today the source package can discover the install tree and render per-layer `config.toml` files, but the generated posture is too flat: `config_ops.py` and `customer.py` hardcode `gpt-5.2`, role identity is not prompt-visible, and agents are expected to infer operating posture from directory position.

This feature makes Codex layers role-aware and model-tiered while preserving the decisions from Features 55 and 57: native Codex settings stay in TOML, richer Agentic OS metadata lives in YAML or prompt artifacts, and managed config conflicts block by default.

The intended result is deterministic: each generated layer has one policy entry that drives its profile name, default model, reasoning effort, prompt-visible role text, metadata sidecar, managed-file ownership, prompt stitching inventory, and test expectations. Navigation and routing layers default to lighter `gpt-5.2` posture. Heavy planning, implementation coordination, verification, review, and automation-guard surfaces default to `gpt-5.5` with high reasoning.

## Architecture

### Authoritative Policy Map

Add one source-of-truth policy map in `src/genomes_agentic_os/config_ops.py`, for example `LAYER_POLICIES: dict[str, CodexLayerPolicy]`. The implementation may use a dataclass, typed dict, or equivalent structured type, but it must be field-addressable in tests rather than assembled from unrelated string fragments.

Each policy entry must include:

- `layer_token`: one of the existing layer tokens.
- `profile`: the Codex profile key to generate.
- `legacy_profiles`: ordered list of compatibility aliases discovered from existing docs, tests, templates, or generated outputs; empty only after the P1 discovery task proves no legacy public name exists.
- `role`: short prompt-visible role identifier.
- `role_summary`: one or two sentences used in `PROFILE.md`.
- `model`: native Codex model string.
- `model_reasoning_effort`: native Codex reasoning key.
- `approval_policy`: inherited from current templates unless the existing layer already differs.
- `sandbox_mode`: inherited from current templates unless the existing layer already differs.
- `prompt_files`: ordered list of generated or expected prompt files, used by both sidecar metadata and the actual prompt-stitching manifest.
- `mcp_scope`: human-readable MCP availability statement for sidecar metadata and docs.
- `customer_safe`: boolean or separate customer policy selector for customer OS generation.

Required source-package policy:

| Layer token | Profile | Role | Model | Reasoning | Purpose |
| --- | --- | --- | --- | --- | --- |
| `global_harness` | `global_user_harness` | `navigator` | `gpt-5.2` | `medium` | Personal default routing and lightweight context gathering. |
| `agentic_os_root` | `agentic_os_root` | `os_navigator` | `gpt-5.2` | `medium` | Navigate the installed OS, read shared rules, and prepare context. |
| `customer_os_root` | `customer_os_root` | `customer_navigator` | `gpt-5.2` | `medium` | Stay inside a customer boundary and route to approved customer surfaces. |
| `domain_or_lane` | `domain_or_lane` | `domain_navigator` | `gpt-5.2` | `medium` | Classify work and route to the correct project, workflow, or automation. |
| `project` | `project_orchestrator` | `orchestrator` | `gpt-5.5` | `high` | Plan, decompose, coordinate implementation, and verify repo work. |
| `workflow_or_task` | `workflow_orchestrator` | `orchestrator` | `gpt-5.5` | `high` | Run workflow-scoped heavy work and verify delegated outputs. |
| `automation` | `automation_guard` | `automation_guard` | `gpt-5.5` | `high` | Execute only within an automation contract with evidence and approvals. |

Before changing any profile key, P1 must run a compatibility discovery pass over `src/`, `tests/`, `docs/`, `.agentic-atlas/`, and existing template fixtures using `rg "profiles\.|--profile|project_orchestrator|workflow_orchestrator|automation_guard|project\]"`. The result must be recorded in implementation notes or the feature worklog. If a current generated public profile key exists for a layer, add it to `legacy_profiles` and render a profile alias that contains the same native Codex posture as the canonical profile. Alias behavior is explicit and tested; aliases are not generated speculatively.

### TOML Contract

`config.toml` must contain only native Codex posture and MCP registration. For each generated canonical profile and each discovered legacy alias, render values directly from the policy entry. Do not store Agentic OS role metadata as custom TOML keys unless Codex already documents those keys as native and prompt-visible.

Example project profile output:

```toml
model = "gpt-5.5"
model_reasoning_effort = "high"
approval_policy = "on-request"
sandbox_mode = "workspace-write"

[profiles.project_orchestrator]
model = "gpt-5.5"
model_reasoning_effort = "high"
approval_policy = "on-request"
sandbox_mode = "workspace-write"
```

The template renderer must not have literal fallback model strings outside the policy definitions. Tests should fail if `gpt-5.2` or `gpt-5.5` appears in generation code outside the policy fixture or expected-output assertions.

### Prompt Stitching Contract

The policy `prompt_files` list is authoritative for both `config/codex-profile.yml` and the loader-visible prompt inventory. The implementation must either wire that list into the existing prompt generation path in `config_ops.py` that writes the layer prompt artifacts, or introduce one helper such as `render_prompt_files(policy, layer_root)` that both sidecar rendering and prompt artifact generation call. The same ordered list must appear in the sidecar and in the generated prompt-stitching manifest or generated prompt source used by Codex.

`PROFILE.md` is required for every generated main layer. If the current repo already has a named prompt manifest or prompt-file list used by Codex prompt input, this feature must update that named path. If no single path exists, this feature must create a single policy-driven path and update `config install`, `config install-tree`, and `doctor` to use it. Updating only YAML `prompt_files` is not sufficient.

Acceptance for this contract is code-enforced: a targeted test must load the generated policy, render a project layer, then assert that the prompt artifact inventory consumed by Codex contains `PROFILE.md` from the same `policy.prompt_files` value used by `config/codex-profile.yml`.

### Sidecar Metadata Contract

Generate `config/codex-profile.yml` next to the layer's generated config. This file contains Agentic OS metadata that is useful for tools and documentation but is not treated as the only prompt source.

Required YAML fields:

```yaml
layer: project
profile: project_orchestrator
role: orchestrator
role_summary: Plan, decompose, delegate, verify, and integrate project work.
model: gpt-5.5
model_reasoning_effort: high
prompt_files:
  - AGENTS.md
  - PROFILE.md
  - ROUTER.md
  - CONTEXT.md
  - RULES.md
  - TOOLS.md
  - MEMORY.md
mcp_availability: project-approved systems only
managed_by: genomes_agentic_os
managed_feature: "62-role-aware-codex-config-layers"
managed_policy_version: 1
```

The sidecar must be regenerated by `config install` and detected by `config install-tree --dry-run`. Existing sidecars with user edits must follow the same managed-file conflict behavior as `config.toml`: if managed content differs from local content, report a conflict and do not overwrite unless the existing explicit conflict-confirmation path is used.

For customer OS sidecars, `managed_by: genomes_agentic_os` remains required as non-user-visible ownership metadata. Customer safety scans must treat this exact key-value pair, plus `managed_feature` and `managed_policy_version`, as metadata-key exceptions, not as role text or customer-facing wording.

### Prompt Visibility Contract

Generate `PROFILE.md` for every main generated layer. It must be placed beside the layer's prompt artifacts, typically next to `AGENTS.md`, `ROUTER.md`, and `CONTEXT.md`. The file must be short and deterministic.

Required project example:

```markdown
# Codex Profile

Role: orchestrator
Layer: project
Profile: project_orchestrator
Default model: gpt-5.5
Reasoning effort: high

You plan, decompose, delegate, verify, and integrate project work. If the request is only navigation or routing, route to the narrowest layer and avoid broad implementation. If you spawn subagents, verify their results before declaring the work complete.
```

Prompt visibility is validated against a generated temporary root, not against the user's live Codex profile. The validation recipe must create a temporary root, run the local package CLI against that root, point Codex at the generated config using the repo-supported config path mechanism, and capture prompt input from the generated project profile.

Required recipe shape, with the exact config-path flag or environment variable adjusted only if local `codex debug --help` proves the CLI name has changed:

```bash
tmp_root="$(mktemp -d /tmp/aos-role-profile.XXXXXX)"
.venv/bin/agentic-os config install --root "$tmp_root" --layer project --yes
export CODEX_HOME="$tmp_root/.codex"
cd "$tmp_root"
codex debug prompt-input --profile project_orchestrator > "$tmp_root/prompt-input.txt"
grep -c '^Role: orchestrator$' "$tmp_root/prompt-input.txt" | grep '^1$'
grep -c '^Layer: project$' "$tmp_root/prompt-input.txt" | grep '^1$'
grep -c '^Profile: project_orchestrator$' "$tmp_root/prompt-input.txt" | grep '^1$'
grep -c '^Default model: gpt-5.5$' "$tmp_root/prompt-input.txt" | grep '^1$'
grep -c 'You plan, decompose, delegate, verify, and integrate project work\.' "$tmp_root/prompt-input.txt" | grep '^1$'
```

If Codex uses a different environment variable or CLI option than `CODEX_HOME` to select a generated config directory, the implementation must document the exact replacement in `docs/13-agent-surfaces.md` and in the validation test notes. The invariant does not change: all five required role fields must appear exactly once in captured prompt input from the generated temporary-root project profile.

If the current Codex prompt loader cannot include `PROFILE.md`, inject the same role block into the existing generated `CONTEXT.md` or `AGENTS.md` through the policy-driven prompt rendering path and document that fallback. The acceptance gate is captured prompt input, not file existence.

### Managed-File Ownership And Conflict Behavior

Feature 57 remains binding. Managed config conflicts block by default. This feature adds managed files (`PROFILE.md` and `config/codex-profile.yml`) and must include them in the same dry-run, conflict, and explicit-confirmation flow as existing generated config files.

Ownership rules:

- Generated `PROFILE.md` must include a short HTML comment marker: `<!-- managed-by: genomes_agentic_os; feature: 62-role-aware-codex-config-layers; policy-version: 1 -->`.
- Generated `config/codex-profile.yml` must include `managed_by`, `managed_feature`, and `managed_policy_version` fields.
- If a managed marker is present and rendered content differs, report a managed diff in dry-run mode and block writes unless the existing explicit conflict-confirmation path is used.
- If `PROFILE.md` or `config/codex-profile.yml` already exists without the managed marker, treat it as unmanaged user content: do not overwrite, report `pre_existing_unmanaged_file`, and instruct the operator to move, adopt, or explicitly confirm replacement through the existing conflict-confirmation path.
- If the file is missing, create or report it normally depending on dry-run mode.

Tests must cover missing file, managed changed file, and pre-existing unmanaged file cases for both `PROFILE.md` and `config/codex-profile.yml`.

Rules for `config.toml` remain unchanged:

- Existing user-local model selections in `config.toml` must not be overwritten silently.
- If local `config.toml` differs only because the generated policy changed from the old hardcoded model to the new policy model, report a managed diff in dry-run mode.
- If a user-edited value conflicts with the new policy, block and show the file path and conflicting key.
- Do not silently fall back to another model if Codex rejects `gpt-5.5` or a reasoning key. The failure must be visible in tests, validation docs, or the installation command output.

### Customer OS Safety

Update `src/genomes_agentic_os/customer.py::customer_layer_config` to use the same policy shape or an explicitly derived customer-safe policy map. Customer-generated configs must not include Genome-private user-visible wording, Genome-only MCP names, private paths, or internal operator role wording. Customer role names may stay generic, for example `customer_navigator`, `project_orchestrator`, and `automation_guard`, but customer sidecars and `PROFILE.md` files must describe customer-boundary behavior rather than Genome's internal operating system.

Customer defaults:

- `customer_os_root`, customer domain/lane navigation, and customer routing layers use `gpt-5.2` with `medium` reasoning.
- Customer project, workflow, and automation guard layers use `gpt-5.5` with `high` reasoning unless an existing customer factory option explicitly selects a lower model.
- MCP availability remains explicit and minimal. No new MCP servers are added by this feature.

Customer generated-artifact scanning is split into two explicit surfaces:

1. `whole_artifact_forbidden_terms`: scan the complete rendered `config.toml`, `PROFILE.md`, and `config/codex-profile.yml` for private paths, secrets, and forbidden MCP identifiers. The exact metadata-key exceptions allowed in this whole-file scan are `managed_by: genomes_agentic_os`, `managed_feature: "62-role-aware-codex-config-layers"`, `managed_policy_version: 1`, and the `PROFILE.md` HTML ownership marker. No other occurrence of `genomes_agentic_os`, `Genome`, `/Users/genome`, `~/agentic_os`, `GENOMES_NOTION_PAT`, or `GENOMES_NOTION_CONNECTOR` may appear in full customer artifacts.
2. `user_visible_role_text_forbidden_terms`: extract role-visible strings from `PROFILE.md`, sidecar `role`, sidecar `role_summary`, sidecar `mcp_availability`, and generated prompt inventory text, then scan them with zero exceptions for private terms and internal operator wording.

Whole-artifact forbidden terms with metadata exceptions:

- Forbidden paths and secrets: `/Users/genome`, `~/agentic_os`, `GENOMES_NOTION_PAT`, `GENOMES_NOTION_CONNECTOR`.
- Forbidden private wording except the exact ownership metadata exceptions above: `Genome operators`, `Genome's Agentic OS`, `Genome-only`, `internal operator`, and any non-exempt occurrence of `genomes_agentic_os` or `Genome`.
- Forbidden MCP identifiers unless an explicit customer option already allowed them before this feature: `losmon-memory`, `atlassian_rovo`, `gmail`, `notion`, `openbrain`, and any MCP server name containing `genome`.

User-visible role text forbidden terms have no metadata exceptions:

- `Genome operators`, `Genome's Agentic OS`, `Genome-only`, `internal operator`, `genomes_agentic_os`, `/Users/genome`, `~/agentic_os`, `GENOMES_NOTION_PAT`, `GENOMES_NOTION_CONNECTOR`, and any MCP server name containing `genome`.

Allowed customer role identifiers: `customer_navigator`, `domain_navigator`, `project_orchestrator`, `workflow_orchestrator`, `automation_guard`.

Allowed customer MCP wording: `customer-approved systems only`, `no MCP servers by default`, or an explicit customer-provided MCP name from existing customer factory input.

Customer safety tests must scan rendered customer artifacts, not only source strings. They must run both scan modes: full-file scan with only the enumerated metadata exceptions, and extracted user-visible role text scan with zero exceptions. If a customer name legitimately contains a denylisted substring, the test fixture must use a neutral customer name so the generated-policy invariant remains measurable.

## Phases

### P1: Policy, Compatibility Discovery, And Rendering, 1 week

- Run the compatibility discovery pass over source, tests, docs, atlas, and templates; record discovered existing generated profile keys and lock `legacy_profiles` for any required aliases.
- Add the structured layer policy in `config_ops.py`.
- Replace hardcoded model strings in `config_template` with policy-driven rendering.
- Generate `config/codex-profile.yml` and `PROFILE.md` for source-package layers.
- Wire `policy.prompt_files` into the actual prompt-stitching or prompt-artifact generation path, not only the sidecar.
- Update `install`, `install-tree`, and `doctor` paths so the new files are created, dry-run reported, and conflict checked.
- Add targeted unit tests for policy values, generated TOML, sidecar metadata, prompt inventory wiring, and prompt artifact content.

### P2: Customer Factory And Merge Safety, 1 week

- Replace hardcoded model strings in `customer.py` with customer-safe policy rendering.
- Add customer OS tests that assert customer-safe role text, expected model tiers, allowed role identifiers, explicit MCP allowlist behavior, full-artifact denylist behavior with exact ownership metadata exceptions, extracted role-text denylist behavior with zero exceptions, and absence of forbidden MCP identifiers.
- Extend merge/conflict tests to cover `PROFILE.md` and `config/codex-profile.yml` for missing, managed changed, and pre-existing unmanaged file cases.
- Verify install-tree discovery repairs missing config and role artifacts across root, domain, project, workflow, and automation test roots without mutating `~/agentic_os`.

### P3: Docs, Atlas, And Holdout Validation, 1 week

- Update `docs/13-agent-surfaces.md` to document role-aware model tiers, prompt-visible role artifacts, prompt stitching path, temporary-root prompt-input validation, customer scan surfaces, and the seven-layer table.
- Update `.agentic-atlas/architecture/command-reference.md` if command output or generated files changed.
- Update `.agentic-atlas/backlog.md` and `.agentic-atlas/gap-register.md` only if Feature 62 creates new tracked follow-up work.
- Run full repo tests and atlas validation.
- Run local Codex validation commands: `codex debug models` and the temporary-root `codex debug prompt-input --profile project_orchestrator` recipe. If the CLI command name or config-path selector has drifted, document the exact replacement command used.

## Acceptance Criteria

1. `src/genomes_agentic_os/config_ops.py` has one authoritative policy map for the seven existing layer tokens, and generated TOML values are rendered from that map.
2. P1 records current generated/public profile-key discovery. Any discovered legacy profile key is represented in `legacy_profiles`, rendered as an explicit alias, and covered by tests; otherwise `legacy_profiles` is intentionally empty with recorded evidence.
3. New generated `config.toml` files for `global_harness`, `agentic_os_root`, `customer_os_root`, and `domain_or_lane` contain `gpt-5.2` and `model_reasoning_effort = "medium"`.
4. New generated `config.toml` files for `project`, `workflow_or_task`, and `automation` contain `gpt-5.5` and `model_reasoning_effort = "high"`.
5. Existing local model overrides remain blocking conflicts and are not overwritten without the repo's explicit conflict-confirmation path.
6. Each generated main layer has `PROFILE.md` or a documented fallback prompt block containing role, layer, profile, default model, reasoning effort, and role summary.
7. The generated prompt-stitching inventory consumed by Codex is rendered from the same `policy.prompt_files` list as `config/codex-profile.yml`, and tests fail if `PROFILE.md` exists on disk but is absent from that loader-visible inventory.
8. `config/codex-profile.yml` is generated for each main layer and includes layer, profile, role, role summary, model, reasoning effort, prompt files, MCP availability, and managed ownership fields.
9. `config install-tree --dry-run` reports missing or changed `config.toml`, `PROFILE.md`, and `config/codex-profile.yml` across root, domain, project, workflow, and automation test fixtures.
10. Customer OS generation uses customer-safe role/model policy, only allowed role identifiers, explicit MCP allowlist behavior, full-artifact scanning with only enumerated ownership metadata exceptions, extracted user-visible role text scanning with zero exceptions, and generated customer artifacts do not contain forbidden MCP identifiers.
11. Docs explain the model-tiered role policy, prompt stitching mechanism, managed-file ownership, customer safety scan modes, and prompt visibility validation without relying on this originating conversation.
12. Local validation proves prompt visibility from a generated temporary root with the documented config selector. Captured prompt input for `project_orchestrator` contains exactly one occurrence each of `Role: orchestrator`, `Layer: project`, `Profile: project_orchestrator`, `Default model: gpt-5.5`, and the project role summary.

## Validations

Required commands:

```bash
.venv/bin/python -m pytest tests/test_cli_scaffold.py -q
.venv/bin/python -m pytest -q
bash .agentic-atlas/tools/validate-cli.sh
codex debug models
```

Required temporary-root prompt-input validation:

```bash
tmp_root="$(mktemp -d /tmp/aos-role-profile.XXXXXX)"
.venv/bin/agentic-os config install --root "$tmp_root" --layer project --yes
export CODEX_HOME="$tmp_root/.codex"
cd "$tmp_root"
codex debug prompt-input --profile project_orchestrator > "$tmp_root/prompt-input.txt"
grep -c '^Role: orchestrator$' "$tmp_root/prompt-input.txt" | grep '^1$'
grep -c '^Layer: project$' "$tmp_root/prompt-input.txt" | grep '^1$'
grep -c '^Profile: project_orchestrator$' "$tmp_root/prompt-input.txt" | grep '^1$'
grep -c '^Default model: gpt-5.5$' "$tmp_root/prompt-input.txt" | grep '^1$'
grep -c 'You plan, decompose, delegate, verify, and integrate project work\.' "$tmp_root/prompt-input.txt" | grep '^1$'
```

If `CODEX_HOME` is not the local CLI's config selector, replace it with the verified selector from `codex debug --help` or current Codex docs and update the docs and tests in the same PR. Do not run prompt visibility validation against `~/.codex` or `~/agentic_os`.

Required targeted tests:

- Assert every `LAYER_POLICIES` entry has non-empty `layer_token`, `profile`, `role`, `role_summary`, `model`, `model_reasoning_effort`, `prompt_files`, and `mcp_scope`.
- Assert compatibility discovery output is recorded and `legacy_profiles` matches discovered public/generated profile keys.
- Assert navigator layer TOML output uses `gpt-5.2` and `medium`.
- Assert heavy layer TOML output uses `gpt-5.5` and `high`.
- Assert no generation function outside the policy map hardcodes `gpt-5.2` or `gpt-5.5`.
- Assert generated `PROFILE.md` includes the exact role, layer, profile, model, reasoning effort, and managed marker.
- Assert generated `config/codex-profile.yml` parses as YAML and matches the policy entry, including managed ownership fields.
- Assert sidecar `prompt_files` and loader-visible prompt inventory are rendered from the same policy list.
- Assert dry-run install reports the new generated files without writing them.
- Assert conflict handling blocks local edits to `config.toml`, `PROFILE.md`, and `config/codex-profile.yml`.
- Assert pre-existing unmanaged `PROFILE.md` and `config/codex-profile.yml` are not overwritten and are reported as `pre_existing_unmanaged_file`.
- Assert customer rendered artifacts pass `whole_artifact_forbidden_terms` with only the exact ownership metadata exceptions allowed.
- Assert extracted customer user-visible role text passes `user_visible_role_text_forbidden_terms` with zero exceptions.
- Assert customer generated files use only allowed customer role identifiers and do not include forbidden MCP identifiers unless explicitly allowed by existing customer factory input.

Use temporary roots for install tests. Do not mutate `~/.codex/config.toml`, `~/.codex`, or `~/agentic_os` during implementation or validation.

## Risks

- Codex may not load arbitrary prompt files. Mitigation: require temporary-root prompt-input validation and inject the role block into an existing loaded prompt artifact through the policy-driven prompt rendering path if `PROFILE.md` is not loaded.
- `model_reasoning_effort` or model names may drift across Codex CLI versions. Mitigation: run `codex debug models`; fail visibly rather than silently substituting another model.
- Existing user-local config edits may conflict with new managed defaults. Mitigation: preserve Feature 57 blocking conflict behavior for all new managed files.
- Extra prompt text can increase context noise. Mitigation: keep `PROFILE.md` short, deterministic, and role-only.
- Customer OS generation could leak Genome-specific assumptions. Mitigation: add rendered-artifact tests with split scan modes so ownership metadata stays allowed while user-visible role text has zero private-term exceptions.
- Profile renames can break users who invoke old profile names manually. Mitigation: require compatibility discovery before renaming and render explicit tested aliases for discovered public/generated keys.

## What's NOT in v2

- No mutation of the user's live `~/.codex/config.toml`.
- No mutation of `~/.codex` or `~/agentic_os` during tests.
- No changes to Claude command or skill behavior beyond documentation alignment.
- No new MCP servers.
- No Notion control-plane changes.
- No silent model fallback when a selected model or reasoning key is rejected.
- No automation maturity bypasses or approval relaxations.
- No assumption that folder position alone proves role identity.
- No validation against live user profiles when a temporary generated config is required.
- No removal of required managed ownership metadata from customer sidecars just to pass denylist scans.

## Open Decisions Locked By This Spec

- `project` defaults to the canonical profile name `project_orchestrator`; compatibility aliases are generated only for existing public/generated profile names discovered in P1.
- `workflow_or_task` and `project` both default to heavy orchestration with `gpt-5.5` and high reasoning.
- `automation` defaults to `gpt-5.5` and high reasoning because the risk of incorrect automation execution is higher than the cost savings from a lighter model.
- `PROFILE.md` is the preferred prompt-visible artifact, but the validated requirement is prompt visibility from the generated temporary-root profile, so an implementation may inject the same block into an existing loaded prompt file if the CLI does not load `PROFILE.md`.
- Customer artifacts keep required managed ownership metadata; customer privacy validation is enforced by split scans with exact metadata exceptions for full artifacts and zero exceptions for user-visible role text.