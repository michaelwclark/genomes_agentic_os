# Context Pack: Spec Engine

## Always Load

- `program.md`
- `components.yml`
- `RULES.md`
- `harness/skills/spec-engine/SKILL.md`
- `harness/commands/os-add-spec.md`

## Load For Template Changes

- `templates/ORIGINAL_INTENT_TEMPLATE.md`
- `templates/A_PLUS_SPEC_TEMPLATE.md`
- `examples/`

## Load For Registry Or Harness Visibility Changes

- `harness/registries/skills.yml`
- `harness/skills/skill-registry.yml`
- `src/genomes_agentic_os/capability_registry.py`
- `src/genomes_agentic_os/scaffold.py`

## Load For Projection Changes

- Root and project `TOOLS.md` contracts.
- The target project `project.yml`.
- The local Notion and tracker rules before any write.

## Compatibility Path

The directory remains `spec_grooming` during migration. Treat `spec_engine` as
the canonical program identity and `spec_grooming` as an alias.
