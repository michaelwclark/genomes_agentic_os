# 01 Project Create And Active Work

## Table Of Contents

- [Purpose](#purpose)
- [Source And Runtime Boundaries](#source-and-runtime-boundaries)
- [Command](#command)
- [Files Created](#files-created)
- [Idempotency Rule](#idempotency-rule)
- [Operator Flow](#operator-flow)
- [Disposable Validation](#disposable-validation)
- [Done Signal](#done-signal)

## Purpose

Feature 01 adds first-class project creation to an installed Agentic OS root. It lets an operator create durable project state under a domain instead of relying on whatever repository or terminal directory an agent happens to be in.

Use this guide when adding a new project, checking active work, or validating that Codex and Claude can discover the same project record.

## Source And Runtime Boundaries

This repository owns the command implementation, tests, and reusable docs. The
installed OS root owns live project state. Run `agentic-os project create`
against an installed root such as `~/agentic_os`; do not create live project
records inside this source repository.

## Command

```bash
agentic-os project create <domain> <project> --root ~/agentic_os
```

Common flags:

- `--repo <path-or-url>` records the source repository.
- `--notion <url-or-id>` records the Notion control-plane reference.
- `--jira <project-or-url>` records the Jira reference.
- `--status active|waiting|blocked|done` sets the project status. The default is `active`.
- `--lane <lane>` records the operating lane for routing.

The project name must use lowercase letters, numbers, and underscores. The domain alias `lenders` normalizes to `los`.

Repair an existing project layer:

```bash
agentic-os project onboard <domain> <project> --root ~/agentic_os
```

Register a visible branch worktree:

```bash
agentic-os project worktree add <domain> <project> <name> --root ~/agentic_os --path <existing-worktree>
```

## Files Created

A project is written under `<root>/<domain>/02-projects/<project>/`:

```text
README.md
project.yml
status.md
decisions.md
source-map.md
AGENTS.md
ROUTER.md
CONTEXT.md
RULES.md
TOOLS.md
MEMORY.md
config.toml
artifacts/
config/
ideas/
work-items/
  01-intake/
  02-active/
  03-complete/
worktrees/
```

`config/` holds parsed project defaults such as workflow profiles, output
artifact locations, validation commands, MCP boundaries, tools, memory policy,
and registered worktrees. `work-items/01-intake/` is the project-known idea
intake lane, defaulting to indexed files such as `001_build_logger.md`.
Expanded intake can use an indexed packet folder when a duel/spec pass needs
multiple files.
`ideas/` remains only as a compatibility index.
`worktrees/` contains visible symlinks and `worktrees/index.yml`, which routing
uses to recognize commands run from real worktree paths.

The command also updates these domain indexes:

- `<domain>/00-control-plane/active-work.md`
- `<domain>/02-projects/README.md`

When `--repo`, `--notion`, or `--jira` is supplied, those references are recorded in the project `source-map.md`.

## Idempotency Rule

Project creation is additive. Running the same command again should not
overwrite local edits in existing project files. Operators can safely rerun the
command to confirm the project exists, but should still review generated paths
before making manual edits.

## Operator Flow

1. Initialize or choose an Agentic OS root.
2. Run `agentic-os project create` with the domain and project slug.
3. Open the project folder and confirm the source references are correct.
4. Check `active-work.md` to ensure the project appears in the active queue.
5. Run validation before dispatching agents against the project.

## Disposable Validation

```bash
TMP_ROOT="$(mktemp -d)/agentic_os"
uv run agentic-os init --target "$TMP_ROOT"
uv run agentic-os project create los losmon_replacement --root "$TMP_ROOT" --repo /tmp/losmon --notion https://notion.example/project --jira FLYWL
mkdir -p /tmp/losmon-feature
uv run agentic-os project worktree add los losmon_replacement feature_branch --root "$TMP_ROOT" --path /tmp/losmon-feature
uv run agentic-os validate --root "$TMP_ROOT"
test -f "$TMP_ROOT/los/02-projects/losmon_replacement/project.yml"
test -f "$TMP_ROOT/los/02-projects/losmon_replacement/config/output-artifacts.yml"
test -L "$TMP_ROOT/los/02-projects/losmon_replacement/worktrees/feature_branch"
grep -q "losmon_replacement" "$TMP_ROOT/los/00-control-plane/active-work.md"
grep -q "/tmp/losmon" "$TMP_ROOT/los/02-projects/losmon_replacement/source-map.md"
```

Alias check:

```bash
TMP_ROOT="$(mktemp -d)/agentic_os"
uv run agentic-os init --target "$TMP_ROOT"
uv run agentic-os project create lenders loan_ops --root "$TMP_ROOT"
test -d "$TMP_ROOT/los/02-projects/loan_ops"
test ! -d "$TMP_ROOT/lenders"
```

## Done Signal

Feature 01 is healthy when project creation creates the project folder, project-local agent/config/work-item/worktree surfaces, updates active-work and project indexes, preserves existing files on rerun, records supplied source references, normalizes `lenders` to `los`, routes from registered worktree paths, and leaves `agentic-os validate` passing.
