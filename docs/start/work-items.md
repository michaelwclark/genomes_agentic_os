---
title: Work items
sidebar_label: Work items
slug: /start/work-items
description: One folder per piece of work, holding everything about it from first idea to finished result.
---

# Work items

**What they are for:** giving every individual piece of work one folder that
holds its plan, its progress, and its evidence — so nothing about it is scattered
across chat logs, ticket comments, and your memory.

**Where they apply:** inside a project. If a project is "rebuild the reporting
pipeline," a work item is "add the weekly summary endpoint."

## The shape of it

A work item is a folder:

```
~/agentic_os/domains/acme/02-projects/reporting-pipeline/
  work-items/
    072126-001_weekly_summary_endpoint/
```

The name encodes the date it was created, a sequence number, and a short slug.
That is deliberate: sorted alphabetically, they come out in the order you
started them.

Inside goes everything about that work — the specification, the plan, the
worklog, the handoff notes for whoever picks it up next, and the receipts
proving what was tested. The exact files depend on how the work was created and
which procedures ran against it.

:::note Older layouts

You may see work items in numbered subfolders like `02-active/` or `01-intake/`.
That was the previous layout. The code still reads it, but new work items go
directly under `work-items/`. Some handbook pages still show the old form.

:::

Finished work eventually moves to `work-items/99-archived/` after a retention
period. It is not deleted.

## The lifecycle

A work item has a state, and the states run in order:

```
captured → triaged → specified → ready → building → validating → finished → documented
```

In plain terms:

| State | What it means |
| --- | --- |
| `captured` | Somebody wrote the idea down. Nothing has been decided. |
| `triaged` | You have decided it is real and which project it belongs to. |
| `specified` | What "done" means has been written down. |
| `ready` | It is specified well enough for someone to start. |
| `building` | Work is happening. |
| `validating` | The work is done and is being checked. |
| `finished` | It passed. |
| `documented` | The knowledge from it has been written down somewhere durable. |

Two states sit outside the sequence: `blocked` (waiting on something you do not
control) and `archived` (put away). `finished`, `documented` and `archived` are
the ones that end the line.

The states are not decoration. Things like "can this be automatically archived"
and "what should I be working on" are answered by reading them.

## Two ways to look at work items

This is the one genuinely confusing part, so it is worth being explicit.

**The folders** are the record. They are created and repaired with:

```bash
agentic-os project work-item create ...
agentic-os project work-item repair ...
agentic-os project work-item sync-active ...
```

**A database** at `harness/shared_factory/00-control-plane/state.db` holds a fast
index of the same work, so questions like "what is active across every project"
can be answered without walking hundreds of folders. You query it with a
separate command group:

```bash
agentic-os work list
agentic-os work show <id>
agentic-os work active-now
```

The database also tracks a second, independent axis called **attention** —
`active`, `queued`, `parked`, `closed`. That is about whether *you* are currently
paying attention to something, which is a different question from how far along
it is. A work item can be `building` and `parked` at the same time: started, then
set aside.

`agentic-os work active-now` writes a small summary file,
`active-now.json`, that agents read to find out what is going on right now
without loading everything.

:::note Command reference

The [`agentic-os work` command group](/docs/17-cli-reference#canonical-work-state--cliworkpy)
is the canonical interface for querying and reconciling work state. Use
`agentic-os work <command> --help` for every flag.

:::

## The rule that makes this worth doing

You cannot close a work item as done without evidence. The tooling refuses. This
is the single most important habit the system enforces: a claim that something
works is not the same as proof that it works, and only one of them gets written
to disk.

## Go deeper

- [Source of truth](/docs/25-source-of-truth) — which system is authoritative
  when the filesystem, GitHub and your tracker disagree
- [Runs and run logs](/docs/08-runs-and-run-logs) — where the evidence goes
- [Filesystem resource lifecycle](/docs/33-filesystem-resource-lifecycle) — how
  things get archived and cleaned up
