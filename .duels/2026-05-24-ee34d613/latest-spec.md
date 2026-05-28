<!--
  Spec produced by the Duel skill (~/.claude/skills/duel/)
  Duel ID:        2026-05-24-ee34d613
  Started:        2026-05-24T19:24:58.955Z
  Ended:          2026-05-24T19:37:18.229Z
  Termination:    NON_PASS_MAX_ROUNDS
  Final artifact: latest-spec.md
  Total rounds:   7
  Total cost:     $0.0000 of $20.00 cap
  Writer:         codex-cli (default)
  Critic:         codex-cli (default)
-->

# Capability Registry Spec v2

## Vision

Genome's Agentic OS should make installed capabilities discoverable from the visible OS root. Commands, skills, MCP servers, hooks, plugins, libraries, and shared rules are not considered usable because files exist in hidden harness folders. A capability becomes active only through a deterministic install state machine: declared package intent is validated, visible artifacts are linked or copied, staged disabled adapters are rendered and extracted, doctor checks are recomputed against staged intent and artifacts, final enabled adapters are rendered only for capabilities that passed doctor, final adapters are extracted again, and the lockfile records the final recomputed evidence.

The registry model gives Codex, Claude, and future harnesses one shared source of truth. Harness-specific folders such as `.codex/` and `.claude/` are generated adapters. They may cache or render configuration, but they do not define what the OS contains. `agentic-os.lock.json` is also generated evidence, not authority: install and doctor always recompute current registry, artifact, adapter, and check state before comparing that recomputed state to the previous lockfile for drift.

## Architecture

The installed OS root contains `.agentic_root`, package metadata, generated lock metadata, visible capability folders, and registry files under `registries/`. The source package provides templates, schemas, installers, adapter generators, and validation fixtures. The installed runtime state is represented by visible root-level folders plus canonical registry files. Hidden harness folders and the lockfile are generated outputs.

### Registry Authority

Per-type registry files are the canonical authoring surface. `registries/capabilities.yml` is generated from the per-type registries and must never be hand-authored during normal install. The installer computes a normalized capability graph from `registries/commands.yml`, `registries/skills.yml`, `registries/mcp.yml`, `registries/plugins.yml`, `registries/libraries.yml`, `registries/hooks.yml`, and `registries/rules.yml`; writes `registries/capabilities.yml`; then re-reads it and verifies that each generated record carries a `source_registry`, `source_id`, and `source_digest` matching exactly one per-type record. If `capabilities.yml` is edited independently, install and doctor fail with `capability_digest_drift` unless the command is an explicit migration repair mode that rewrites it from per-type registries.

The canonical registries are:

| Registry | Path | Responsibility |
| --- | --- | --- |
| Capability registry | `registries/capabilities.yml` | Generated normalized installed capability index, status, source registry pointer, and source digest. |
| Command registry | `registries/commands.yml` | Slash commands, executable shims, aliases, input/output contracts, and harness targets. |
| Skill registry | `registries/skills.yml` | Skills, source paths, installed paths, dependencies, update policies, and harness targets. |
| MCP registry | `registries/mcp.yml` | MCP server launch definitions, env var names, exposed tools, approval mode, and doctor checks. |
| Plugin registry | `registries/plugins.yml` | Plugin and connector bundle metadata plus emitted harness adapters. |
| Library registry | `registries/libraries.yml` | Embedded, linked, global, or externally managed libraries used by capabilities. |
| Hook registry | `registries/hooks.yml` | Lifecycle hooks, trigger events, allowed side effects, network behavior, timeout, and rollback behavior. |
| Rule registry | `registries/rules.yml` | Shared rule documents consumed by generated `AGENTS.md`, `CLAUDE.md`, and future harness adapters. |

### Schema Ownership

Schemas live in `schemas/registries/` in this source package. The registry schema language is JSON Schema 2020-12, with YAML registries parsed to JSON before validation. Required schema files are `capability.schema.json`, `commands.schema.json`, `skills.schema.json`, `mcp.schema.json`, `plugins.schema.json`, `libraries.schema.json`, `hooks.schema.json`, and `rules.schema.json`. Contributors validate package records with `agentic-os validate --package agentic-os.package.json --registries registries/ --schemas schemas/registries/`. CI must run the same command plus fixture tests for invalid records.

Every registry item must normalize to a capability record with `id`, `type`, `display_name`, `status`, `visibility`, `customer_safe`, `source`, `install`, `harness_targets`, `provides`, `requires`, `doctor`, `update`, and `source_digest`. Literal secrets are forbidden in registry files; records may reference env var names only. Secret detection is deterministic: schema validation rejects field names or scalar values matching configured secret patterns such as private key blocks, token-like values longer than 32 characters in secret-bearing fields, and literal values under `env` where only variable names are allowed.

### Capability Lifecycle

The only allowed lifecycle statuses are:

| Status | Meaning | May appear in inventory | May emit enabled adapter behavior | May appear in lock summary |
| --- | --- | --- | --- | --- |
| `declared` | Package intent exists and schema validation passed, but visible artifact work has not completed. | yes | no | yes |
| `linked` | Visible artifact was copied or linked at `install.target`. | yes | no | yes |
| `staged` | Disabled staged adapters and inventory were rendered and extracted for validation. | yes | no | yes |
| `active` | Registry, artifact, staged extraction, doctor checks, final enabled adapter render, and final extraction all passed in the current run. | yes | yes | yes |
| `broken` | A declared capability failed artifact, staged adapter, doctor, final adapter, or extraction validation. | yes | no | yes |
| `disabled` | Operator or package policy intentionally disables the capability before adapter generation. | yes | no | yes |
| `removed` | A previously locked capability is no longer declared and was removed by managed upgrade. | yes for one lock cycle | no | yes |

Status transitions are installer-owned. Fresh install begins at `declared`, moves to `linked` after visible artifact creation, moves to `staged` after disabled adapter and inventory generation plus staged extraction, and moves to `active` only after doctor passes, final enabled adapters are rendered, and final extraction proves that enabled adapter entries exactly match the active capability set. Any failed required step transitions the capability to `broken`; `broken` and `disabled` records are visible in inventory but cannot emit enabled adapter entries. A capability cannot move directly from `declared` to `active` or from `staged` to `active` without final adapter re-extraction.

### Install Modes

| Mode | Input condition | Failure policy | Migration behavior |
| --- | --- | --- | --- |
| `fresh-install` | Empty or absent OS root. | Fail on any invalid registry, artifact, adapter, doctor, final extraction, or customer-safety check. | None. |
| `managed-upgrade` | Existing root with valid prior lockfile and registries. | Fail on registry drift, unregistered adapter behavior, unsafe local overrides, final extraction mismatch, or doctor failures unless capability is explicitly disabled. | Removed capabilities are marked `removed` for one lock cycle. |
| `legacy-migration-report` | Existing hidden harness state without valid registry authority. | Never writes adapters or lockfile; reports proposed registry records and blockers. | Read-only proposal only. |
| `legacy-migration-apply` | Operator accepts a report file. | Writes registries first, then runs the same gates as managed upgrade. | Hidden harness state is imported only if represented as registry records. |

### Local Override Policy

`agentic-os.local.json` may only set machine-local paths, explicit disabled capability IDs, non-secret env var name mappings, and adapter output locations. It may not change `visibility`, `customer_safe`, `type`, `provides`, `harness_targets`, launch commands, hook side effects, network behavior, doctor checks, or update policy. Install and doctor validate overrides before registry normalization. A forbidden override fails with `unsafe_local_override` and cannot be downgraded to a warning.

### Two-Pass Adapter Activation

Adapter generation uses a two-pass contract to avoid circular activation gates.

Pass A renders staged disabled adapters. A staged adapter contains every declared, linked, or intentionally disabled adapter entry, but each executable or harness-active item is emitted with an explicit disabled marker native to that adapter format. For structural adapters this is `enabled = false`, `disabled: true`, or the equivalent schema field. For Markdown adapters, staged generated blocks include `state="staged"` in the block marker and may describe intent, but they must not contain reserved active syntax. The staged extractor produces `staged_intent` records with capability id, type, harness target, source digest, and intended enabled state. Doctor runs against registry records, visible artifacts, declared commands, env var availability, MCP startup checks, hook safety checks, staged extractor results, and customer-safety policy. It does not rely on enabled harness behavior.

Pass B runs only after doctor passes for the current recomputed graph. The installer renders final adapters atomically into temporary files with enabled entries only for capabilities whose final lifecycle status is `active`; disabled, broken, declared, linked, staged, and removed capabilities are emitted only as inactive inventory text or disabled adapter comments. The final extractor parses those temporary final adapters and produces `enabled_adapter_items`. The installer then asserts `enabled_adapter_items == active_capability_adapter_projection`, where the projection is the deterministic set of active capability records expanded by harness target and adapter item type. If the set differs by id, type, harness target, digest, or enabled state, install and doctor fail with `final_adapter_projection_mismatch`. Only after this assertion passes are final adapter files moved into place and `agentic-os.lock.json` written.

### Adapter Extraction Gate

Adapter extraction is deterministic in both passes. It reads generated adapter outputs and produces typed items: `command`, `skill`, `mcp_server`, `plugin`, `hook`, `library`, and `rule`. TOML, JSON, and YAML adapters are parsed structurally. Markdown adapters such as `AGENTS.md` and `CLAUDE.md` are parsed using reserved generated blocks bounded by `<!-- agentic-os:begin <type> <id> state="staged|active|disabled" digest="..." -->` and `<!-- agentic-os:end <type> <id> -->`.

Markdown adapters have a small reserved active grammar. The extractor treats only the following patterns as active syntax, and only inside `state="active"` generated blocks:

| Item type | Reserved active syntax | Example |
| --- | --- | --- |
| `command` | A line beginning with `- /<command-id>` or `command: /<command-id>` | `- /os-doctor` |
| `skill` | `skill: <skill-id>` or `SKILL.md: skills/<skill-id>/SKILL.md` | `skill: make-skill` |
| `mcp_server` | `mcp_server: <server-id>` | `mcp_server: context-mode` |
| `plugin` | `plugin: <plugin-id>` | `plugin: github` |
| `hook` | `hook: <hook-id>` plus `trigger: <event>` in the same block | `hook: pre-doctor` |
| `library` | `library: <library-id>` | `library: mempalace` |
| `rule` | `rule: <rule-id>` or `include_rule: rules/<rule-id>.md` | `include_rule: rules/notion-workspace.md` |

The reserved grammar is case-sensitive and line-oriented. Markdown links, code fences, examples, and prose outside generated blocks are ignored as active adapter items, but they are scanned for reserved active syntax. If any reserved active syntax appears outside a generated block, or appears inside a `state="staged"` or `state="disabled"` block, extraction fails with `reserved_active_syntax_outside_active_block`. Arbitrary imperative prose outside generated blocks is allowed only as explanatory text and is not treated as generated harness behavior; generated harness adapters must not depend on such prose for activation. Future active syntax requires a schema and extractor update before any adapter may emit it.

Each extracted active item must map to exactly one normalized capability record with matching `id`, `type`, `harness_target`, and source digest. Install and doctor fail if an adapter contains an enabled command, rule, MCP, hook, plugin, library, or skill reference that cannot be traced to exactly one canonical registry record. Zero unregistered active adapter items are permitted.

### Inventory And Lockfile

`INVENTORY.md` is generated from the recomputed capability graph and is optimized for scanning. It must include every capability ID, type, status, visibility, customer-safe flag, primary path, source registry, and doctor summary. Active capabilities are shown separately from declared, linked, staged, disabled, broken, and removed capabilities. The generator fails if the inventory omits any normalized record or marks a non-active capability as usable.

`agentic-os.lock.json` is generated-only evidence. It records the recomputed capability graph digest, per-type registry digests, installed artifact fingerprints, staged extractor results, doctor result summaries, final adapter output digests, final extractor results, lifecycle statuses, and final active adapter projection from the current run. It is never used as proof that the current install is valid. Doctor always recomputes current state first, then compares recomputed digests against the lockfile and reports `lockfile_drift` for stale or hand-edited lockfiles.

## Phases

### P1 - Registry Schema And Installer Gate (2 weeks)

Define JSON Schema 2020-12 schemas for all registry files and the normalized capability record. Add installer logic for `fresh-install` and `managed-upgrade` that reads `agentic-os.package.json`, validates per-type registries, writes generated `capabilities.yml`, verifies source digests, applies allowed local overrides, installs or links visible folders, and refuses to continue if any capability cannot enter a valid lifecycle status.

Deliverables: schema files in `schemas/registries/`, sample registry files, lifecycle transition code, per-type-to-capability normalization, digest drift checks, local override validation, contributor command `agentic-os validate`, and failing fixtures for missing fields, secret-like values, unresolved paths, unsafe overrides, edited `capabilities.yml`, and unsupported capability types.

### P2 - Inventory And Harness Adapter Generation (2 weeks)

Generate `INVENTORY.md`, `.codex/config.toml`, `AGENTS.md`, `CLAUDE.md`, and other adapter outputs from registry state using the two-pass adapter activation contract. Pass A renders staged disabled adapters, extracts staged intent, and feeds doctor without enabling harness behavior. Pass B renders final enabled adapters only for active capabilities, re-extracts enabled items, and atomically installs adapter files only if final extractor output exactly equals the active capability adapter projection.

Deliverables: inventory generator, Codex adapter, Claude adapter, generated-block Markdown format, Markdown reserved grammar implementation, staged adapter renderer, final adapter renderer, adapter extractors, adapter provenance comments, tests proving hidden harness state cannot introduce an unregistered active capability, a fixture where a Markdown adapter template emits an extra slash command and install plus doctor both fail, and a fixture proving final enabled adapter entries exactly match active lifecycle records.

### P3 - Doctor, Lockfile, And Migration Path (2 weeks)

Implement `agentic-os doctor`, lockfile writing, and separated legacy migration modes. Doctor recomputes registry, artifact, staged adapter extraction, inventory, check state, final adapter projection, and final extraction before reading the lockfile for drift comparison. Migration report mode proposes registry records from existing scattered capability locations without writing adapters or lockfile; migration apply mode writes registries and then runs managed-upgrade gates.

Deliverables: doctor command, generated `agentic-os.lock.json` writer, lockfile drift detection, `legacy-migration-report`, `legacy-migration-apply`, compatibility decision notes for `shared_factory/05-knowledge/skills/`, and regression tests for customer-safe filtering, broken lifecycle status, removed lifecycle status, stale lockfile handling, staged-to-active adapter transitions, and Markdown reserved grammar enforcement.

## Acceptance Criteria

1. A fresh install creates the expected root shape under `~/agentic_os/`, including `.agentic_root`, package metadata, visible capability folders, `registries/`, generated `capabilities.yml`, generated `INVENTORY.md`, final generated adapters, and generated `agentic-os.lock.json`.
2. Per-type registries are the only canonical authoring surface; `capabilities.yml` is generated and install fails on source digest drift.
3. The installer fails before final adapter generation when any declared capability lacks a valid normalized capability record or attempts an unsafe local override.
4. A capability emits enabled adapter behavior only in `active` status, and `active` is reachable only after schema validation, visible artifact creation, staged adapter extraction, inventory generation, current doctor checks, final adapter render, and final adapter extraction pass.
5. Staged adapters never contain reserved active Markdown syntax or enabled structural adapter entries; final adapters contain enabled entries only for active capabilities.
6. Final adapter extraction must exactly match the active capability adapter projection by id, type, harness target, source digest, and enabled state before adapter files are moved into place.
7. `INVENTORY.md` includes every normalized capability, separates active from declared, linked, staged, disabled, broken, and removed records, and never advertises a non-active capability as usable.
8. Generated `.codex/` and `.claude/` adapter entries are derived only from registry records and include provenance that points to the source registry record and digest.
9. Adapter extractors fail install and doctor when any active command, rule, MCP, hook, plugin, library, or skill reference cannot be traced to exactly one registry record.
10. Markdown adapters define active behavior only through the reserved grammar inside `state="active"` generated blocks; reserved syntax outside active blocks fails extraction.
11. MCP records name required env vars but never contain literal secret values.
12. Customer OS installs fail doctor checks when operator-only capabilities are active or when local overrides attempt to change safety-relevant fields.
13. Hook records must declare trigger event, command, allowed filesystem roots, external network behavior, timeout, rollback or failure behavior, and customer-install eligibility.
14. The lockfile is generated-only evidence. Doctor recomputes current state before comparing it to the lockfile and reports stale or hand-edited lockfiles as drift.
15. Legacy migration report mode is read-only; strict enforcement begins only in fresh install, managed upgrade, and migration apply modes.

## Validations

- Schema tests validate every registry type and the normalized capability record using JSON Schema 2020-12 through `agentic-os validate --package agentic-os.package.json --registries registries/ --schemas schemas/registries/`.
- Lifecycle tests prove capabilities cannot skip from `declared` to `active`, cannot emit final adapters while `broken` or `disabled`, and are marked `broken` on failed required checks.
- Two-pass adapter tests render a valid command fixture through staged and final passes, assert staged adapters are disabled, assert doctor does not depend on enabled harness behavior, and assert final enabled adapter entries exactly match active lifecycle records.
- Installer tests cover missing registry files, invalid capability types, unresolved install targets, command resolution failures, literal secret rejection, unsafe local overrides, edited generated `capabilities.yml`, and final adapter projection mismatch.
- Inventory tests compare the full normalized capability graph against generated `INVENTORY.md` entries and assert non-active statuses are not presented as usable.
- Adapter tests parse generated Codex and Claude outputs and assert every enabled entry maps to exactly one registry record; Markdown tests include reserved active syntax outside generated blocks, reserved active syntax inside staged blocks, and an extra slash command inside an active block with no registry record, all of which must fail.
- Doctor tests simulate failed MCP startup, missing skills, unsafe hooks, operator-only capabilities in customer installs, stale lockfiles, hand-edited lockfiles, staged extraction mismatch, and final extraction mismatch.
- Migration tests run in report-only mode first, confirm existing harness files are not treated as source of truth, and verify apply mode runs managed-upgrade gates before writing lockfile evidence.

## Risks

- Existing users may rely on hidden harness folders as de facto source of truth. Mitigation: ship read-only migration report mode before apply mode and preserve generated adapter backups during P3.
- Registry records can become verbose. Mitigation: keep per-type registries concise and generate normalized capability records programmatically.
- Adapter drift may reappear if humans edit generated files. Mitigation: include provenance comments, generated-file headers, staged and final extractor gates, and doctor checks that compare adapter content to registry state.
- Two-pass adapter rendering can introduce temporary file complexity. Mitigation: render final adapters into temporary paths, extract them before move, and atomically replace adapter outputs only after projection equality passes.
- Markdown prose can be mistaken for enforceable harness behavior. Mitigation: define a reserved active grammar, ignore arbitrary prose as activation source, and fail when reserved syntax appears outside active generated blocks.
- Customer-safe filtering could be bypassed if capabilities omit visibility fields. Mitigation: make `visibility` and `customer_safe` required fields with no permissive defaults and block local overrides from changing them.
- Lockfile drift could be mistaken for validity. Mitigation: lockfile is explicitly generated evidence and doctor recomputes current state before reading it.

## What's NOT in v2

- No runtime Notion database dependency. Notion may be a registered MCP/control-plane integration, but registries live in the OS root.
- No full implementation of every command candidate beyond registry representation, schema validation, adapter extraction, and doctor gates.
- No final decision on whether commands are Markdown prompts, executable shims, or both.
- No final decision on whether `shared_factory/05-knowledge/skills/` remains a compatibility mirror or becomes generated from top-level `skills/`.
- No plugin marketplace implementation beyond registry representation and adapter generation contracts.
- No support for local overrides that change safety-relevant capability semantics.
- No attempt to infer active generated adapter behavior from arbitrary natural-language prose outside reserved generated blocks.