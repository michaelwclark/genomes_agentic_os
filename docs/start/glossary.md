---
title: Plain-English glossary
sidebar_label: Glossary
slug: /start/glossary
description: Every piece of internal vocabulary in Genome's Agentic OS, translated into ordinary language.
---

# Plain-English glossary

**What this is for:** translating the vocabulary you will hit in the handbook.
Keep it open in a second tab while you read.

Words are grouped by what they are about rather than alphabetically, because the
confusing ones tend to be confusing together.

## The structure

**Domain** — a top-level area of your work, such as one client or "personal".
Each one is a folder with an identical set of numbered subfolders, so learning
one teaches you all of them.

**Room** — another word for a domain. `room create` runs the same code as
`domain create`. If a page uses one and you expected the other, they are the
same.

**Project** — work aimed at one outcome, inside a domain, tracked across many
sessions.

**Work item** — one discrete piece of work inside a project, with its own folder
holding everything about it.

**Lane** — an overloaded word. It means one of three things depending on where
you see it:
1. A numbered folder inside a domain (`00-control-plane`, `02-projects`, and so on).
2. A category for workflows and automations: `engineering`, `marketing`,
   `sales`, `support`, `operations`, `finance`, `personal_admin`, `learning`.
3. In older layouts only, a work-item status folder such as `02-active`.

**Harness** — the AI agent runtime you are using, meaning Claude or Codex. Also
the name of the `harness/` folder at the OS root, which holds the shared
instruction files and templates. Context tells you which is meant.

**shared_factory** — the folder inside `harness/` holding things shared across
every domain: templates, patterns, shared programs, the control-plane database.
Not a domain of your work.

**Control plane** — two meanings. Inside a domain, the `00-control-plane/` folder
holding what is active and what the rules are. At the whole-system level,
sometimes used for Notion as the human-facing dashboard.

## Doing the work

**Workflow** — a written-down procedure, stored as a folder of Markdown
documents. It does not execute; it describes.

**Automation** — a workflow that runs on a trigger instead of being started by
you.

**Maturity level** — how much an automation is trusted, on a five-rung ladder:
`observe`, `prepare`, `propose`, `execute_approved`, `execute_guarded`. See
[Automations](./automations.md).

**Run** — one execution, and the folder recording it.

**Run log** — the `run-log.md` narrative file inside that folder.

**Receipt** — evidence that something actually happened: command output, a
check identifier, a file path. The system's central rule is that claims of
success must point at one.

**Routing** — working out, from a plain-English request, which domain, project
and files are relevant. It uses fixed matching rules, not a language model, and
refuses rather than guessing when it is unsure.

**Context pack** — three different things, unfortunately:
1. The result of routing: an ordered list of files to read plus a prompt.
2. `context-pack.md`, a file inside a workflow listing the sources you need.
3. `context-contract.yml`, the machine-readable version of the same idea.

**Blocker / fix-soon / cleanup / observation** — the four severities a `check`
command reports, most serious first.

## Running unattended

**Tick** — one pass of `agentic-os runtime supervise`, which walks heartbeats,
schedules, watch sources, events and the run queue in that order.

**Heartbeat** — a recurring health check or status sync.

**Schedule** — a registered command that runs when its time comes round.

**Watch source** — an external system worth polling for new activity, such as a
GitHub repository.

**Watch cursor** — a bookmark recording how far through a source you have
already read, so you do not process the same thing twice.

**Event** — a small file recording that something happened.

**Chain rule** — a rule that watches for a kind of event and, when one matches,
adds a job to the queue. It queues; it does not execute directly.

**Run queue** — the list of jobs waiting to be picked up.

**Execution Fabric** — the optional heavier machinery for running many things at
once across several machines. Off by default.

**Degraded mode** — another overloaded term. For the Execution Fabric it means
running locally with no remote coordinator. For a host it means the last health
check failed or is more than a day old.

## Words that sound like jargon and are

These come up constantly in the handbook. Here is what they actually mean.

**Projection** — a copy of information, derived from the real source, kept
somewhere more convenient to look at. It is never the truth. Notion pages are
projections. `active-now.json` is a projection. If a projection disagrees with
the files, the files win.

**Source of truth** — the one place that is authoritative for a given fact. For
how work was done, that is the filesystem. For whether a branch merged, that is
GitHub. For ticket status, that is your tracker.

**File-first** — the design choice that the filesystem, not a database, is the
system's structure. There is a database, but it holds a fast index of what the
files already say.

**Idempotency key** — a label attached to a job so that if the same job is
submitted twice, the second one is recognised as a duplicate and ignored. It is
how the system avoids doing the same thing twice when something is retried.

**Outbox** — a holding area for actions that need to reach an external system
(posting a comment, updating a ticket) but have not been delivered yet. It exists
so that a failure to reach Jira does not lose the fact that you meant to.

**Port and adapter** — a way of separating "what capability we need" from "which
specific service provides it." The *port* is the description of the capability;
the *adapter* is the working connection to one particular service. It lets the
rest of the system carry on when a service is not configured.

**Attention** — a work item's second status axis, separate from how far along it
is: `active`, `queued`, `parked`, `closed`. It records whether you are currently
looking at something.

**Fenced failover** — when one machine takes over from another, the handover is
tagged with a number that only increases, so an old machine that comes back to
life cannot resume acting as though it were still in charge.

**Model Workspace Protocol (MWP)** — the name the handbook gives to the guiding
idea that folder structure, rather than a database, is the architecture.

## Terms this documentation is not confident about

Named here rather than guessed at:

- **Witness commit** — described in the Execution Fabric material as a way of
  proving a standby machine has caught up before it is promoted. The precise
  mechanism is not spelled out.
- The exact enforcement mechanism separating `execute_approved` from
  `execute_guarded` beyond the policy described in each automation's own
  `permissions.md`.

If you know these well, they are good candidates for a documentation
contribution.
