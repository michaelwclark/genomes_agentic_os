# Feature Spec: Room-First Installer And Routing

## Status

- Status: ready
- Owner: Genome
- Created: 2026-05-20
- Target OS layer: source package, installed runtime, customer OS, Claude, and Codex

## Problem

The current scaffold can create default Genome domains, but customer installs need domains that match how the operator thinks. A consultant, creator, software team, or client should be able to describe their rooms, workflows, references, and tool triggers without inheriting hard-coded Genome defaults.

## Outcome

`agentic-os` can create a room-first OS profile where the root map, domain rooms, `CONTEXT.md` files, routing tables, naming rules, templates, and validation are generated from a profile or wizard. Claude and Codex should read the same map and room files.

## Concepts

| Concept | Source Package Name | Installed Runtime Shape |
| --- | --- | --- |
| Map | root router template | `~/agentic_os/ROUTER.md` plus pointers |
| Room | domain profile | `<domain>/CONTEXT.md`, `<domain>/ROUTER.md`, `<domain>/domain.yml` |
| Work | object templates | projects, workflows, automations, runs, and artifacts |
| Routing table | profile routing rows | root and domain `ROUTER.md` tables |
| Load rules | room context rows | `CONTEXT.md` `What To Load` table |
| Tool triggers | profile skill/tool rows | `CONTEXT.md` `Tools And Skills` table |

## Commands

```bash
agentic-os init --target ~/agentic_os --profile profiles/genome.yml
agentic-os profile create --target profiles/customer.yml
agentic-os profile validate profiles/customer.yml
agentic-os room create <room_slug> --root ~/agentic_os
agentic-os room update <room_slug> --root ~/agentic_os --from-profile profiles/customer.yml
agentic-os route "<request>" --root ~/agentic_os
```

Backward compatibility:

- `agentic-os domain create` remains as an alias for `agentic-os room create`.
- Existing default domains still install when no profile is supplied.
- `lenders` continues to normalize to `los`.

## Wizard Questions

Ask the smallest useful set first:

1. What is this OS for?
2. What rooms or domains do you naturally think in?
3. For each room, what kind of work happens there?
4. What inputs arrive in that room?
5. What outputs should that room create?
6. Which references should agents read first?
7. Which references should agents skip unless needed?
8. Which tools or skills should activate for specific task types?
9. What does done mean for the room?
10. What approvals are required before external, production, destructive, billing, legal, secrets, or customer-visible actions?

## Profile Shape

```yaml
os:
  display_name: Example Agentic OS
  default_root: ~/agentic_os
  owner: Genome

map:
  naming_conventions:
    filesystem: lowercase_snake_case
    dated_artifacts: YYYY-MM-DD-topic.md
  global_skip_by_default:
    - unrelated rooms
    - archived work
    - private source dumps unless explicitly routed

rooms:
  - slug: writing_room
    display_name: Writing Room
    purpose: Ideas become polished drafts.
    inputs:
      - rough ideas
      - research notes
    output_folders:
      drafts: drafts
      finals: final
    routing:
      - task: write blog post
        read_first:
          - docs/voice.md
          - docs/style-guide.md
        read_when_needed:
          - docs/audience.md
        skip_by_default:
          - production docs
        output_path: drafts/
    tools:
      - name: humanizer
        trigger: before a draft moves to final
        notes: remove generic AI writing patterns
    done_means:
      - output exists in the expected folder
      - naming convention is followed
      - source files are preserved
```

## Templates To Add

- `templates/profile/os-profile.yml`
- `schemas/os-profile.schema.json`
- `templates/profile/customer-os-profile.yml` as the initial editable profile template.
- `templates/room/context.md` as the room context source template.
- `templates/room/router.md` as the room-local routing source template.
- `templates/room/routing-table.md` as the reusable task routing table fragment.
- `templates/stage/stage-context.md` for rooms that use a stage pipeline.
- `templates/reference/naming-conventions.md`
- `templates/reference/tool-index.md`
- `templates/reference/source-priority.md`
- `templates/reference/style-and-output-rules.md`
- `templates/root/router.md` if generated root routing moves out of Python string literals.
- `templates/profile/README.md` with profile authoring rules.

## Implementation Steps

1. Add profile schema and example profile.
2. Add profile parser with deterministic validation before filesystem writes.
3. Refactor default domains into a built-in profile object instead of scattered constants.
4. Generate root router rows from profile rooms.
5. Generate room `CONTEXT.md` from profile inputs, load rules, output folders, tools, and done criteria.
6. Generate room `domain.yml` with `context_loading`.
7. Keep pointer files for Claude and Codex aligned with `ROUTER.md`.
8. Add `profile validate` and unit tests for invalid room slugs, missing load rules, duplicate rooms, and unsafe approval defaults.
9. Add `route` read-only output that reports room, likely object, files to load, files to skip, approval risks, and output destination.
10. Update docs install so profile, room, stage, and reference templates are copied into `shared_factory/05-knowledge/templates/`.

## Acceptance Criteria

- A profile can create an OS root with custom rooms and no Genome-specific required rooms.
- Re-running install or room create preserves hand-authored runtime files.
- Generated room `CONTEXT.md` includes inputs, process, output folders, what-to-load rows, tools, and done criteria.
- Root `ROUTER.md` picks the right room without loading every room.
- Domain `ROUTER.md`, `AGENTS.md`, `CLAUDE.md`, and `AGENT.md` keep the same source-of-truth pointer model.
- `agentic-os route` stays read-only by default.
- Validation checks profile parseability and installed room shape.

## Migration Notes

- Existing installed roots should not be rewritten by `docs update`.
- Add a future explicit migration to convert default-domain constants into a generated profile manifest.
- Keep current files valid: `personal`, `clarks_consulting`, `los`, `shared_factory`, and `archive` remain supported.
- Customer installs must verify the Notion workspace before any Notion write; profile creation can record intended Notion destinations without writing.

## Validation

- `uv run --extra dev pytest -q`
- `agentic-os profile validate profiles/example.yml`
- `agentic-os init --target <tmp-root> --profile profiles/example.yml`
- `agentic-os validate --root <tmp-root>`
- Manual route checks against at least one custom room and one default Genome room.
