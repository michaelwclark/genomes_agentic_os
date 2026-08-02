---
title: Where to go next
sidebar_label: Where to go next
slug: /start/where-to-go-next
description: A map from the plain-English introduction to the detailed handbook pages that answer each question.
---

# Where to go next

**What this is for:** working out which of the hundred-odd handbook pages
answers your question, now that you know the shape of the system.

## By what you are trying to do

| You want to… | Read |
| --- | --- |
| Set the whole thing up properly | [Install and quickstart](/docs/01-install-and-quickstart) |
| Understand how the pieces fit together | [Architecture](/docs/02-architecture) and [Information architecture](/docs/04-information-architecture) |
| Know what the daily loop looks like | [Operating model](/docs/03-operating-model) |
| Look up a command | [CLI reference](/docs/17-cli-reference) |
| Work out why something broke | [Troubleshooting and FAQ](/docs/18-troubleshooting-and-faq) |
| Check the system is healthy | [Health, doctor and validation](/docs/16-health-doctor-validation) |
| Write a workflow properly | [Workflows](/docs/06-workflows) |
| Promote an automation safely | [Automations](/docs/07-automations) |
| Make things run unattended | [Runtime and always-on](/docs/09-runtime-and-always-on) |
| Connect an external system | [Connected sources](/docs/11-connected-sources) |
| Understand what beats what when sources disagree | [Source of truth](/docs/25-source-of-truth) |
| Ship code with agents | [Auto-dev readiness](/docs/24-auto-dev-readiness) and [Auto-dev program](/docs/42-auto-dev-program) |
| Build one of these for a client | [Customer OS factory](/docs/15-customer-os-factory) |
| Change settings and understand the layers | [Configuration surfaces](/docs/23-configuration-surfaces) |
| Upgrade without losing local edits | [Config, update and backup](/docs/14-config-update-backup) |

## The three shelves

The documentation splits into three, and it helps to know which shelf you are
on.

**The [handbook](/docs/)** is the numbered pages. It is written for someone
operating the system, and it assumes you know the vocabulary. That is the main
body of knowledge.

**The [reference](/docs/17-cli-reference)** is look-it-up material — commands,
registries, the architecture atlas, feature guides, design notes, release notes.
Nobody reads it front to back.

**The [operating manual](/operating-manual/)** is different in kind. It gets
copied *into* an installed OS, so it is the manual an agent finds when it is
already inside a running system. It covers concepts, the layer map, file
formats, recipes and checklists.

## Two overlapping pairs

Some material is covered in both the handbook and the operating manual, from
different angles. If one does not land, try the other:

- Troubleshooting: [handbook page 18](/docs/18-troubleshooting-and-faq) and
  [manual section 09](/operating-manual/09-troubleshooting/)
- Commands: [handbook page 17](/docs/17-cli-reference) and
  [manual section 08](/operating-manual/08-harness-commands/)
- Core concepts: [handbook page 00](/docs/00-overview) and
  [manual section 01](/operating-manual/01-concepts/)

## Worked examples

If you learn better from a complete example than from reference material, the
[tutorials](/docs/tutorials/) walk through whole scenarios end to end, including
one written for a non-technical reader.

The [example OS trees](/docs/examples/) sketch how different kinds of business
would lay theirs out. They are illustrative sketches, not runnable templates.

## If a page contradicts what you see

Trust your own install. This documentation covers a system under active
development, and a few pages describe behaviour that has since changed —
several are flagged in these introductory pages where we found them.

The order of authority is: what your system does right now, then the most recent
receipt on disk, then the documentation.
