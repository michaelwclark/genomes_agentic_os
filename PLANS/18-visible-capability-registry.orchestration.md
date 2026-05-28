# Plan 18 Orchestration Prompt

Use this prompt to start the Plan 18 orchestration run after the runtime, source-watch, and event graph layers have clear registry contracts.

## Source Spec

- Spec: `/Users/genome/projects/genomes_agentic_os/PLANS/18-visible-capability-registry.md`
- Companion prompt: `/Users/genome/projects/genomes_agentic_os/PLANS/18-visible-capability-registry.orchestration.md`
- Supporting spec: `/Users/genome/projects/genomes_agentic_os/spec/capability-registry.md`

## Current Anchors

- Scaffolding: `/Users/genome/projects/genomes_agentic_os/src/genomes_agentic_os/scaffold.py`
- Config install and harness adapters: `/Users/genome/projects/genomes_agentic_os/src/genomes_agentic_os/config_ops.py`
- Validation: `/Users/genome/projects/genomes_agentic_os/src/genomes_agentic_os/validate.py`
- CLI surface: `/Users/genome/projects/genomes_agentic_os/src/genomes_agentic_os/cli.py`
- Skill registry: `/Users/genome/projects/genomes_agentic_os/harness/skills/skill-registry.yml`
- Harness commands: `/Users/genome/projects/genomes_agentic_os/harness/commands/`
- Agent config templates: `/Users/genome/projects/genomes_agentic_os/templates/agent-config/`
- System templates: `/Users/genome/projects/genomes_agentic_os/templates/system/`
- Test coverage: `/Users/genome/projects/genomes_agentic_os/tests/test_cli_scaffold.py`

## Orchestration Prompt

```text
/orchestrate

Work in /Users/genome/projects/genomes_agentic_os.

Goal: finish Plan 18, "Visible Capability Registry", by making installed OS capabilities inspectable through top-level directories, registries, generated inventory, and harness adapters.

Primary spec:
/Users/genome/projects/genomes_agentic_os/PLANS/18-visible-capability-registry.md

Supporting spec:
/Users/genome/projects/genomes_agentic_os/spec/capability-registry.md

Important repo context:
- This repo is the source package, not the live installed OS.
- The live install target is ~/agentic_os.
- Preserve the Plan 21 harness context contract at every installed layer.
- Visible registries should not replace shared_factory internals until a migration path is proven. Prefer mirror/adapter behavior first.
- The worktree may be dirty. Do not revert user changes or unrelated edits. Work with concurrent changes.

Start with read-only investigations. Do not begin implementation workers until the investigation outputs identify the smallest safe first build slice.

Baseline first:
1. Capture `git status --short` and `git rev-parse HEAD`.
2. Run `uv run pytest -q` if the environment is ready. If blocked, record the exact blocker and continue with read-only investigation.
3. Inspect Plan 18, spec/capability-registry.md, scaffold.py, config_ops.py, validate.py, cli.py, harness/commands, harness/skills/skill-registry.yml, templates/agent-config, templates/system, and tests.

Investigation requirements:
1. Registry contract audit: compare Plan 18 acceptance criteria to current install/scaffold/config/validate behavior.
2. Directory layout: design top-level installed directories for `bin/`, `commands/`, `skills/`, `mcp/`, `plugins/`, `libraries/`, `hooks/`, `rules/`, and `registries/`.
3. Inventory generation: define registry schema, `INVENTORY.md` generation, and how hidden shared capabilities become visible without duplicating source-of-truth semantics.
4. Harness adapter generation: define how Codex and Claude dot-folder config is generated from visible registry state.

Expected implementation strategy:
- Add visible top-level surfaces additively.
- Keep registries declarative and schema-backed.
- Generate `INVENTORY.md` from registries, not from ad hoc prose.
- Mirror existing shared commands/skills first; avoid moving paths in a way that breaks installed OS users.
- Validate declared capabilities against actual files.

Likely first build slice:
Add registry templates plus install/validate support for visible capability inventory:
- create top-level installed directories,
- seed registry files for commands, skills, MCP servers, libraries, hooks, plugins, and rules,
- generate `INVENTORY.md`,
- include Context Mode, Unified Memory, `/make-skill`, `/make-domain`, `/make-automation`, `/make-workflow`, and `/orchestrate`,
- add doctor/validate checks for declared-but-missing capabilities.

Worker rules:
- You are not alone in this codebase. Other agents or the user may be editing files concurrently.
- Do not revert edits made by others.
- Adjust your implementation to accommodate concurrent changes.
- Edit files directly when assigned an implementation slice.
- List every changed file in your return.
- Include exact commands run and exact test results.

Verification target:
- `uv run pytest -q`
- `agentic-os init --target <temp root> --projects-source <temp projects>`
- `agentic-os validate --root <temp root>`
- Inspect `<temp root>/INVENTORY.md`
- Confirm visible registries under `<temp root>/registries/`

Return first:
1. Investigation summary.
2. Recommended build slices.
3. Files each slice should own.
4. Risks or user approvals needed.
5. The first implementation slice ready for worker dispatch.
```

## Investigation Prompts

### 1. Registry Contract Audit

```text
Read-only investigation in /Users/genome/projects/genomes_agentic_os.

Compare Plan 18 and spec/capability-registry.md against current scaffold, config, validation, docs, and tests.

Return done, partial, and missing matrix, plus the smallest safe implementation slice.

Do not edit files.
```

### 2. Installed Directory Layout

```text
Read-only investigation in /Users/genome/projects/genomes_agentic_os.

Design the visible installed capability layout.

Focus on top-level `bin/`, `commands/`, `skills/`, `mcp/`, `plugins/`, `libraries/`, `hooks/`, `rules/`, `registries/`, their relationship to `shared_factory/05-knowledge/`, and additive migration constraints.

Return recommended layout, source templates, and install/validation changes.

Do not edit files.
```

### 3. Inventory Generation

```text
Read-only investigation in /Users/genome/projects/genomes_agentic_os.

Design registry schemas and `INVENTORY.md` generation.

Focus on capability types, required fields, file existence checks, stale declarations, generated content, and stable ordering for tests.

Return schema, generator, and test recommendations.

Do not edit files.
```

### 4. Harness Adapter Generation

```text
Read-only investigation in /Users/genome/projects/genomes_agentic_os.

Define how visible registry state should generate Codex and Claude adapter config.

Focus on config.toml profiles, AGENTS/CLAUDE adapters, command manifests, skill manifests, MCP/library registries, and Plan 21 context-loading rules.

Return minimal adapter contract and tests.

Do not edit files.
```

## Initial Findings

- Plan 18 is currently lighter than Plans 16/17, but it has clear build order and acceptance criteria.
- Supporting spec work exists at `spec/capability-registry.md`.
- The likely first implementation is additive visibility: directories, registry templates, inventory generation, and validation before any path migration.
