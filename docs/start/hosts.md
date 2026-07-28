---
title: Hosts and the always-on loop
sidebar_label: Hosts
slug: /start/hosts
description: The individual computers the system runs on, and how scheduled work happens without a server.
---

# Hosts and the always-on loop

**What this is for:** running work on the right machine, and keeping scheduled
things happening when you are not at the keyboard.

**Where it applies:** any setup with more than one computer — typically a laptop
you use and a machine that stays on.

If you only ever run this on one laptop, you can skim this page. Nothing here is
required to get value from the system.

## A host is just a computer

The system keeps a list of the machines it knows about in `config/hosts.yml`.
Each entry is an SSH alias plus a description and some paths. There are no
passwords or keys in that file — connection details come from your normal
`~/.ssh/config`.

```bash
agentic-os host add ...
agentic-os host list
agentic-os host routing
```

A second file, `harness/registries/hosts-routing.yml`, holds the policy: which
harness runs where, which project paths live on which machine, how many things
may run at once.

Why more than one? Because a laptop closes. If you want something to run at
01:30, it needs to run somewhere that is awake at 01:30. The usual arrangement is
one always-on machine as the primary and a laptop as a secondary that can still
work on its own when the primary is unreachable.

## Checking a host is healthy

```bash
agentic-os host health-report --host bigmac
```

This runs a set of configured probes — disk space, system load, whether specific
services and containers are alive, whether an HTTP endpoint answers — and writes
a report you can read later.

It can also fix a narrow, pre-approved set of problems: restarting a service it
owns, or a named container. It will not do anything creative. Anything outside
that list is reported for a human.

By default it runs three times a day.

## The always-on loop

Here is the part that surprises people: **there is no background server.**

The system does not run a daemon. Instead, your operating system's own scheduler
— `launchd` on macOS, `cron` on Linux — calls one command every so often, by
default every fifteen minutes:

```bash
agentic-os runtime supervise --apply
```

One call is one **tick**. A tick walks through five things in order:

1. **Heartbeats** — recurring health checks and status syncs.
2. **Schedules** — commands whose time has come round.
3. **Watch sources** — external systems worth polling for new activity.
4. **Events** — records of things that happened, and the rules that react to
   them.
5. **The run queue** — work waiting to be picked up and dispatched.

Then it runs a read-only health check.

Each step is isolated. If watch sources fail, events and the queue still run.

Without `--apply` it is a dry run: it tells you what it would do and changes
nothing. That is the default, and it is a good way to see what your system is
actually up to.

The scheduler is **not** installed automatically. You opt in per machine, with
`installers/install-scheduler.sh`. Nothing starts running behind your back
because you installed the tool.

## Watching external systems

The system can poll outside services and turn what it finds into local event
files. The list of kinds it understands is broad — GitHub repositories, Slack
channels, Jira searches, Linear teams, Notion databases, email searches, folders
on disk.

Be aware of the gap between "understood" and "wired up." Today only **GitHub
repositories** and **Slack channels** have real working adapters, and they only
activate when the relevant token is set in your environment. The rest fall back
to a dry-run path. Treat the list as the design, not as the current capability.

Polling produces three things locally: a file recording what was seen, an
updated marker of how far it has read, and — if a rule matches — a job on the
queue.

## Doing more than one thing at once

There is a larger machinery called the **Execution Fabric** for when a single
queue file is not enough: several named queues, pools of workers, work that can
move between machines, and proper handover if the primary machine goes away.

It is **off by default**. A fresh install uses the simple file-based queue, which
is fine for one person on one machine. Turn the bigger thing on when you actually
have concurrency to manage, not before.

Its five queues are `codex`, `claude`, `pr_reviews`, `los_environment` and
`non_llm` — roughly, one per kind of worker.

## Go deeper

- [Runtime and always-on](/docs/09-runtime-and-always-on) — the full handbook page
- [Host auto-doctor](/docs/host-auto-doctor) — probes, repairs and receipts
- [Connected sources](/docs/11-connected-sources) — polling in detail
- [Execution Fabric](/docs/13-feature-guides/18-execution-fabric) — queues,
  workers and failover
