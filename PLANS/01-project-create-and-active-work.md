# Feature Spec: Project Create And Active Work

## Status

- Status: ready
- Owner: Genome
- Created: 2026-05-20
- Target OS layer: source package and installed runtime

## Problem

The installed OS has `02-projects/` folders, but there is no command that creates a real project, records status, links sources, or updates active work. This keeps Codex and Claude operating from ad hoc `~/projects/*` context instead of OS-owned project state.

## Outcome

A user can add a project once and both agents can route future work through the same project record.

## Command

```bash
agentic-os project create <domain> <project> --root ~/agentic_os
```

Optional flags:

- `--repo <path-or-url>`
- `--notion <url-or-id>`
- `--jira <project-or-url>`
- `--status active|waiting|blocked|done`
- `--lane <lane>`

## Files To Create

```text
<domain>/02-projects/<project>/
  README.md
  project.yml
  status.md
  decisions.md
  source-map.md
  artifacts/
```

## Required Side Effects

- Add a row to `<domain>/00-control-plane/active-work.md`.
- Add or update a project index in `<domain>/02-projects/README.md`.
- Add source references to project `source-map.md` when flags are supplied.
- Keep writes additive; never overwrite an existing project file.
- Normalize `lenders` to `los` using the existing domain alias behavior.

## Out Of Scope

- Notion writes.
- GitHub issue creation.
- Automatic workflow creation.

## Acceptance Criteria

- Running the command twice preserves local edits.
- Validation passes after project creation.
- A fresh agent can find the project from active work and from the project folder.
- Tests cover default project creation, idempotency, invalid names, and domain aliasing.

## Validation

- `pytest -q`
- `agentic-os project create los losmon_replacement --root <tmp-root>`
- `agentic-os validate --root <tmp-root>`
