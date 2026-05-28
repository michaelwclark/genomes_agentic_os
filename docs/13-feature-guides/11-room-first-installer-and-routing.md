# 11 Room First Installer And Routing

## Table Of Contents

- [Purpose](#purpose)
- [Commands](#commands)
- [Profile Shape](#profile-shape)
- [Install Behavior](#install-behavior)
- [Routing Contract](#routing-contract)
- [Validation](#validation)
- [Source Artifacts](#source-artifacts)

## Purpose

Room-first installation lets an Agentic OS root be created from a declared room
profile instead of the Genome default domain set.

Use it when an installed OS should start from a customer, project, or operator
profile with only the rooms that profile names. The source repository remains
canonical for templates and commands; the installed root is runtime output.

## Commands

Create an editable profile template:

```bash
agentic-os profile create --target profiles/customer.yml
```

Validate the profile before installation:

```bash
agentic-os profile validate profiles/customer.yml
```

Install a room-first OS root:

```bash
agentic-os init --target ~/agentic_os --profile profiles/customer.yml
```

Create or update one room in an existing root:

```bash
agentic-os room create writing_room --root ~/agentic_os
agentic-os room update writing_room --root ~/agentic_os --from-profile profiles/customer.yml
```

Validate the installed root:

```bash
agentic-os validate --root ~/agentic_os
```

## Profile Shape

Profiles are YAML files with top-level OS metadata, an approval policy, and a
non-empty `rooms` list.

```yaml
os:
  display_name: Customer Agentic OS
  owner: Operator
approval_policy:
  external_writes_require_approval: true
rooms:
  - slug: writing_room
    display_name: Writing Room
    purpose: Ideas become polished drafts.
    inputs:
      - rough ideas
      - source notes
    output_folders:
      drafts: drafts
    routing:
      - task: write blog post
        read_first:
          - docs/voice.md
        read_when_needed: []
        skip_by_default: []
        output_path: drafts/
    tools:
      - name: codex
        trigger: implementation and verification
        notes: keep shared writes orchestrator-owned
    done_means:
      - output exists in the expected folder
```

Required room fields are:

- `slug`
- `purpose`
- `done_means`
- approval defaults, either per room or from top-level `approval_policy`

Room slugs use the same validation rules as domain names.

## Install Behavior

`agentic-os init --profile` writes the root files, stores a copy of the profile
as `profile.yml`, installs shared runtime documentation, and creates one room
root for each declared room.

For each room, the installer creates the standard domain structure and then
generates room-specific:

- `CONTEXT.md`
- `ROUTER.md`

Generated room files include the `room-profile-managed` marker. A later
`agentic-os room update ... --from-profile` skips files that already contain
that marker, so operators can avoid accidental replacement of managed room
instructions without an explicit migration step.

The default Genome operational domains are not created by a profile install.
`shared_factory` can still be present because it carries shared runtime docs and
skills, not operator work domains.

## Routing Contract

The root `ROUTER.md` maps each room slug to that room's `ROUTER.md`.

Claude and Codex use the same route-read-cd-repeat contract:

```text
AGENTS.md -> ROUTER.md + CONTEXT.md + RULES.md + TOOLS.md
CLAUDE.md -> @AGENTS.md
```

Inside a room, `CONTEXT.md` records purpose, inputs, output folders, tools,
approval rules, and done criteria. The room `ROUTER.md` keeps routing rows for
tasks and output paths.

Operational flow:

```text
request
  -> root ROUTER.md
  -> selected room ROUTER.md
  -> selected room CONTEXT.md
  -> task-specific references
  -> room output folder
```

Agents should route to one room first and skip unrelated rooms by default.

## Validation

`agentic-os profile validate <profile>` checks that the profile is a YAML
mapping with at least one valid room and approval defaults.

`agentic-os validate --root <root>` reads `profile.yml` when it exists and
validates profile-defined room roots instead of falling back to the Genome
default domain list.

Run both checks before treating a profile install as usable:

```bash
agentic-os profile validate profiles/customer.yml
agentic-os init --target /tmp/customer-os --profile profiles/customer.yml
agentic-os validate --root /tmp/customer-os
```

## Source Artifacts

- Source plan: `PLANS/11-room-first-installer-and-routing.md`
- Feature spec: `features/11-room-first-installer-and-routing/SPEC.md`
- Feature QA: `features/11-room-first-installer-and-routing/HOLDOUT_QA.md`
- Implementation: `src/genomes_agentic_os/room_profile.py`
- CLI wiring: `src/genomes_agentic_os/cli.py`
- Default scaffold support: `src/genomes_agentic_os/scaffold.py`
- Runtime validation: `src/genomes_agentic_os/validate.py`
- Test coverage: `tests/test_cli_scaffold.py`
