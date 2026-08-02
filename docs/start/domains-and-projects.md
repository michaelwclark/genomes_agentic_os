---
title: Domains and projects
sidebar_label: Domains and projects
slug: /start/domains-and-projects
description: The top-level folders that separate your different areas of work, and the outcome-sized folders inside them.
---

# Domains and projects

**What they are for:** keeping unrelated work apart, so that an agent working on
one client's code cannot wander into another client's notes, and so that rules
you set for one area do not silently apply everywhere.

**Where they apply:** the two outermost levels of the folder structure.
Everything else lives inside a project, which lives inside a domain.

## A domain is an area of your work

Think of a domain as a filing cabinet. One for each part of your life that has
its own rules, its own people, and its own history.

Typical domains: `personal`, `work`, one per consulting client.

A fresh install gives you two — `personal` and `work`. Add another with:

```bash
agentic-os domain create acme --root ~/agentic_os
```

That creates `~/agentic_os/domains/acme/` containing a numbered set of folders.
The numbers are there to force a consistent order, so every domain looks the
same:

| Folder | What goes in it |
| --- | --- |
| `00-control-plane/` | What is active right now, decisions, routing and approval rules |
| `00-programs/` | Reusable bundles of capability shared across this domain |
| `01-inbox/` | Unsorted incoming things you have not triaged yet |
| `02-projects/` | The actual work, one folder per project |
| `03-workflows/` | Written-down procedures |
| `04-automations/` | Procedures that run on a trigger |
| `05-knowledge/` | What you have learned that outlives any one project |
| `06-runs-and-logs/` | The record of what has run, and what failed |
| `07-metrics/` | Measurements |
| `08-archive/` | Finished things kept for reference |

Alongside those, the domain gets its own instruction files — `AGENTS.md`,
`ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md` — plus a `domain.yml` holding
its settings.

The point of the identical skeleton is stated plainly in the handbook: an agent
that learns one domain can navigate any domain. There is nothing to look up.

:::note "Room" means the same thing

You will see the word **room** in some commands and profile files. `room create`
runs the same code as `domain create`. Treat them as the same concept unless a
page explicitly distinguishes them.

:::

## A project is one outcome

A project is work aimed at a specific result, tracked across many sessions.
"Rebuild the client's reporting pipeline" is a project. "Fix this typo" is not —
that is a [work item](./work-items.md), which lives inside a project.

Every project belongs to exactly one domain.

```bash
agentic-os project create acme reporting-pipeline --root ~/agentic_os \
  --repo git@github.com:acme/reporting.git \
  --status active
```

That lands at `~/agentic_os/domains/acme/02-projects/reporting-pipeline/` and
contains:

- `project.yml` — settings: which repository, which tracker, current status
- `README.md`, `status.md`, `decisions.md` — the human-readable record
- `source-map.md` — where this project's real assets live (repos, docs, boards)
- the usual `AGENTS.md` / `ROUTER.md` / `CONTEXT.md` / `RULES.md` / `TOOLS.md`
  instruction files, scoped to this project
- `MEMORY.md` — durable notes agents write for their future selves
- `work-items/` — the individual pieces of work
- `worklogs/`, `artifacts/`, `worktrees/`, `ideas/`, `config/`

You can point a project at an existing code repository with `--repo` and at a
tracker with `--jira` or `--linear`. The project folder does not contain your
code. It contains everything *about* the work on your code.

## Why the separation matters

`RULES.md` at the domain level applies to everything in that domain. `RULES.md`
inside one project applies only there. So "never touch production without asking"
can be a client-wide rule while "this repo uses trunk-based development" stays
local to the one project it is true for.

An agent reads them from the outside in and combines them, most specific winning.

## A wrinkle worth knowing

The path prefix is not perfectly consistent across the codebase. Newer OS folders
put domains under `domains/`, so a project is at
`<root>/domains/<domain>/02-projects/<project>/`. Older folders created before
that change resolve to `<root>/<domain>/02-projects/<project>/` instead, and the
code still supports both. Some handbook pages show one form and some show the
other.

If you are unsure which yours is, look:

```bash
ls ~/agentic_os
```

If you see a `domains/` folder, you are on the current layout.

## Go deeper

- [Information architecture](/docs/04-information-architecture) — every folder,
  in detail
- [Operating model](/docs/03-operating-model) — how domains and projects fit the
  daily loop
- [Project create and active work](/docs/13-feature-guides/01-project-create-and-active-work)
  — the feature guide, with worked examples
