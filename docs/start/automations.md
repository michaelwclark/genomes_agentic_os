---
title: Automations
sidebar_label: Automations
slug: /start/automations
description: A workflow that has earned the right to run without you starting it, promoted one careful step at a time.
---

# Automations

**What they are for:** letting a procedure run without you starting it — but only
after it has proved it does the right thing.

**Where they apply:** inside a domain, in the `04-automations/` folder, grouped
by the same lanes as workflows.

## The core idea: trust is earned in stages

Most automation goes wrong the same way. Somebody writes a script, it works
twice, they schedule it, and three weeks later it quietly does something
expensive at 2am.

This system refuses to let you skip to the end. An automation has a **maturity
level**, and it climbs the ladder one rung at a time as evidence accumulates:

```
observe → prepare → propose → execute_approved → execute_guarded
```

| Level | What it is allowed to do |
| --- | --- |
| `observe` | Look and report. It writes nothing outside itself. |
| `prepare` | Draft the output — the email, the ticket, the pull request — but not send it. |
| `propose` | Recommend a specific action and wait for you to approve it. |
| `execute_approved` | Actually do it, but only after a human approves **that particular run**. |
| `execute_guarded` | Do it on its own, within narrow pre-agreed limits, recording evidence of every action. |

The distinction people miss is the last two. `execute_approved` asks every single
time. `execute_guarded` has standing permission, but only inside a boundary you
defined in advance, and it must leave a receipt for each thing it did.

The first two levels — `observe` and `prepare` — are considered safe starting
points and can be set immediately. To go beyond `propose`, the automation's
`check` must come back with zero blockers.

```bash
agentic-os automation create acme operations weekly_report --root ~/agentic_os
agentic-os automation check acme operations weekly_report --root ~/agentic_os
```

## What is in an automation folder

Eight files, and they are mostly about safety:

| File | What it holds |
| --- | --- |
| `automation.md` | What it does, and what triggers it |
| `inputs.md` / `outputs.md` | What it consumes and what it produces |
| `permissions.md` | What it is allowed to touch |
| `failure-modes.md` | What happens when it goes wrong |
| `runbook.md` | How to operate it, including how to turn it off |
| `tests.md` | How you know it works |
| `context-contract.yml` | What an agent should read before running it |

`failure-modes.md` is required, not optional. You have to have thought about the
failure before you get to run the thing unattended.

## What sets one off

Two kinds of trigger:

- **A schedule** — "every night at 01:30." Handled by the
  [always-on runtime](./hosts.md#the-always-on-loop).
- **An event** — "a pull request was merged in this repository." Handled by
  event rules.

An event here is just a small file recording that something happened. A **chain
rule** watches for events of a particular kind and, when one matches, adds a job
to a queue. Note that word: it *queues* the follow-up work. It does not run it
directly. Something else picks it up, which keeps one automation from
recursively setting off a hundred others.

There are guards against that too — every queued item carries a key so the same
thing is never queued twice, and there is a maximum chain depth.

## A real one

`harness/shared_factory/04-automations/operations/work_item_archive/` ships with
the repository. It runs nightly at 01:30 and moves finished work-item folders
into the archive. If you drop a file called `REOPEN.md` into one, it is skipped —
a deliberately crude, obvious override.

:::note Not every folder on disk was scaffolded

A couple of the automations in the repository do not match the eight-file layout
above, and one is named with hyphens, which `automation create` would reject.
They were placed on disk by hand. If you copy one as a template, run
`automation check` against your copy.

:::

## The habit this is really teaching

Start at `observe`. Let it run for a while. Read what it reported. Only then move
it up a rung.

It feels slow. It is much faster than debugging an automation that has been
quietly doing the wrong thing since March.

## Go deeper

- [Automations](/docs/07-automations) — the full handbook page, including how
  maturity is recorded
- [Events and chains](/docs/10-events-and-chains) — event files and chain rules
- [Runtime and always-on](/docs/09-runtime-and-always-on) — what actually runs
  the schedules
