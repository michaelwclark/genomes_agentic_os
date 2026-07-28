---
title: Command Center
sidebar_label: Command Center
slug: /start/command-center
description: The desktop app for browsing your agent conversations and watching what the system is doing.
---

# Command Center

**What it is for:** looking at what your agents have been doing, without reading
folders in a terminal.

**Where it applies:** your own machine, pointed at your OS folder. It is a
desktop application, not a website, and it does not need the internet.

## Names

The app is called **Command Center**. In the repository it lives at
`apps/agentic-os-gui/`, and older documentation calls it "AgenticOSGui" or "the
desktop conversation driver". Same thing. `Command Center` is the name on the
window.

## Launching it

```bash
agentic-os gui open --root ~/agentic_os
```

## What it does today

Two things, and it is worth being precise about the difference between what
ships and what is planned.

**Browsing agent conversations.** Your Claude and Codex sessions are stored on
disk. The app organises them by domain and project rather than as one long
undifferentiated list. You get a tree to pick a scope, a list of conversations
in that scope, the conversation itself, and a panel of details about it.

The value is being able to ask "what did we do on this client's project last
week" and get an answer, rather than scrolling a global history.

**Watching work in flight.** There is an operator view for the Execution Fabric
(the queue machinery described on the [hosts page](./hosts.md)). It shows work
that is waiting, running, finished, failed, retrying, delayed, or given up on;
how deep each queue is; how busy the workers are; and which machine is currently
in charge.

:::note What is planned but not built

The app's own architecture document describes a much larger application —
dashboards, a reporting engine, administrative screens. That is the target, not
the current state. If you read that document, treat it as a roadmap.

:::

## One design decision worth knowing

The app never reads the database or the files directly. Everything it displays
comes from running the command-line tool and reading its output:

```bash
agentic-os gui snapshot --json
agentic-os gui transcript --json
```

This is an explicit rule in the app's own guidelines — no database readers, no
YAML loaders, no log parsers inside the app.

The reason is that it keeps one implementation of "what is true." If the app
parsed files itself, it would slowly drift from what the command line reports,
and you would have two answers to the same question. Everything goes through the
same door.

It also means the app can never show you something the CLI cannot, which is a
useful constraint: if you can see it in Command Center, you can script it.

## What about Notion?

Some setups mirror the state of the system into Notion, so people who do not
live in a terminal can see what is going on.

Notion is a **mirror, never the truth**. Information flows one way: files to
Notion. Editing a Notion page does not change anything in the system. The sync
commands are dry-run by default and require you to confirm which workspace you
mean before they will write anything.

If Notion and your files disagree, the files are right.

## Go deeper

- [The GUI handbook page](/docs/29-agentic-os-gui) — pages, data flow and
  operations
- [Engineering cockpit](/docs/27-engineering-cockpit) — the local, read-only
  browser-based alternative
- [Notion control plane](/docs/12-control-plane-notion) — how the mirror works
