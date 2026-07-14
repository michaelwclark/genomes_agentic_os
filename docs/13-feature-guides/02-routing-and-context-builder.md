# 02 Routing And Context Builder

## Table Of Contents

- [Purpose](#purpose)
- [Source And Runtime Boundaries](#source-and-runtime-boundaries)
- [Commands](#commands)
- [Routing Inputs](#routing-inputs)
- [Context Packet Output](#context-packet-output)
- [Operator Flow](#operator-flow)
- [Disposable Validation](#disposable-validation)
- [Troubleshooting](#troubleshooting)
- [Source Artifacts](#source-artifacts)

## Purpose

Feature 02 adds deterministic routing and context-packet assembly. It lets an
agent ask where work belongs, then load the smallest useful set of source files
for that target.

Use this guide when a request needs to be mapped to a domain, project, workflow,
or linked repository before implementation starts.

## Source And Runtime Boundaries

This repository owns routing implementation and tests. The installed OS root
owns live routers, project records, workflow records, source maps, and linked
repository references. Run routing commands against an installed root such as
`~/agentic_os`.

## Commands

Route a request:

```bash
agentic-os route "Deploy launch to production" --root ~/agentic_os
```

Build a context packet from explicit target fields:

```bash
agentic-os context build --domain acme --project launch --root ~/agentic_os
```

Route from the current working directory:

```bash
agentic-os here route "Deploy this" --root ~/agentic_os
```

Build context from the current working directory:

```bash
agentic-os here context build --root ~/agentic_os
```

## Routing Inputs

Routing uses deterministic filesystem state:

- root and domain `ROUTER.md` files
- domain `00-control-plane/routing-rules.md`
- domain `00-control-plane/active-work.md`
- project `project.yml`, `status.md`, and `source-map.md`
- workflow records when a workflow is supplied
- the current working directory when using `here`

Low-confidence matches fail closed. A request that matches multiple domains or
no known target should return a routing confidence error instead of guessing.

## Context Packet Output

Context packet output includes:

- selected domain, project, workflow, and lane when known
- `target_path` for the chosen runtime object
- `sources_to_load`, the exact files an agent should read before acting
- source repository hints from project source maps when present

The packet is designed for agent handoff. It should be small enough to read
quickly and precise enough to avoid wandering across unrelated runtime state.

## Operator Flow

1. Create or confirm the project record.
2. Add source references with `agentic-os project create --repo ...` when a
   linked repository should participate in `here` routing.
3. Register branch checkouts with `agentic-os project worktree add ... --path ...`
   when a visible project worktree should also participate in `here` routing.
4. Run `agentic-os route` against the user request.
5. Read the returned `sources_to_load`.
6. If working inside a linked repository or registered worktree, run `agentic-os here context build`.
7. Stop on low-confidence routing and clarify the target instead of forcing a
   destination.

## Disposable Validation

```bash
TMP_PARENT="$(mktemp -d)"
TMP_ROOT="$TMP_PARENT/agentic_os"
REPO_PATH="$TMP_PARENT/launch_repo"
WORKTREE_PATH="$TMP_PARENT/launch_feature"
mkdir -p "$REPO_PATH"
mkdir -p "$WORKTREE_PATH/src"
uv run agentic-os init --target "$TMP_ROOT"
uv run agentic-os project create acme launch --root "$TMP_ROOT" --repo "$REPO_PATH"
uv run agentic-os project worktree add acme launch feature_branch --root "$TMP_ROOT" --path "$WORKTREE_PATH"
uv run agentic-os route "Deploy launch to production" --root "$TMP_ROOT"
uv run agentic-os context build --domain acme --project launch --root "$TMP_ROOT"
(cd "$REPO_PATH" && uv run --project /path/to/genomes_agentic_os agentic-os here context build --root "$TMP_ROOT")
(cd "$WORKTREE_PATH/src" && uv run --project /path/to/genomes_agentic_os agentic-os here context build --root "$TMP_ROOT")
```

## Troubleshooting

| Symptom | Likely Cause | Fix |
| --- | --- | --- |
| `routing confidence is low: no domain or project matched` | Request lacks a known domain/project token | Add the project name, use explicit context build flags, or create the missing project record. |
| `routing confidence is low: request matches multiple domains or projects` | Request is ambiguous | Clarify the domain or project before proceeding. |
| `here context build` cannot route | Current directory is outside the OS root, canonical source repo, and registered worktrees | Add a `--repo` source reference, register the worktree, or run the command from a known OS path. |
| Context packet omits expected files | Source map or project record is incomplete | Re-run `project create` with source refs or repair the project files. |

## Source Artifacts

- Historical Spec: migrated into the installed project's canonical `work-items/` lifecycle.
- Installed worklog folder: `worklogs/source-features/02-routing-and-context-builder/`
- Implementation: `src/genomes_agentic_os/routing.py`
- CLI parser: `src/genomes_agentic_os/cli.py`
- Tests: `tests/test_cli_scaffold.py`

No diagram is included. The command flow and troubleshooting table are more
useful for this guide than an extra image asset.
