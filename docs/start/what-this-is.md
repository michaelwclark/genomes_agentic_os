---
title: What this actually is
sidebar_label: What this actually is
slug: /start/what-this-is
description: The problem Genome's Agentic OS solves, who it is for, and what it is not — in ordinary English.
---

# What this actually is

**What it is for:** keeping the state of your work in ordinary files on your own
computer, in a fixed structure, so that both you and the AI agents you work with
can pick up any thread without being re-briefed.

**Where it applies:** any work you do repeatedly and hand off — to an agent, to a
colleague, or to yourself in three weeks. It was built for software delivery and
consulting work, but nothing in it is specific to code.

## The problem

If you work with AI coding agents, you have probably noticed this pattern:

- You start a conversation. You spend the first ten minutes explaining the
  project, the constraints, and where you left off.
- The agent does good work.
- The conversation ends. Everything it learned goes with it.
- Tomorrow you start again from zero.

The knowledge is real, but it only ever lives in chat transcripts. Nothing
accumulates. Every agent, and every session, rebuilds the same context from
scratch.

## The idea

Write the state of the work down, in files, in a structure that never changes.

That is the whole idea. When the structure is predictable, an agent does not
have to be told where things are — it can go and look. And because the files are
just Markdown and YAML in a folder, you can read them, edit them, search them,
and commit them to git like anything else.

The system is a command-line tool, `agentic-os`, that creates and maintains that
folder. Once the folder exists, agents and humans both read and write it.

## What you actually get

A folder — by default `~/agentic_os` — containing:

- **A place for each area of your work.** Consulting for one client is separate
  from your side project, which is separate from personal admin.
- **A folder per piece of work**, holding its plan, its notes, and its evidence
  from the first idea to the finished result.
- **Written-down procedures** for things you do more than once, so the tenth
  time is the same as the first.
- **A record of every run**, so when something goes wrong in a month you can
  find out what actually happened rather than guessing.
- **Instruction files** at every level that tell an agent what it is allowed to
  do here and what it must ask about first.

Those last ones matter more than they sound. Every folder has a small set of
files with fixed names — `AGENTS.md`, `ROUTER.md`, `CONTEXT.md`, `RULES.md`,
`TOOLS.md` — that an agent reads on the way in. `RULES.md` is where you write
things like "never push to main" or "always ask before touching production." The
agent reads that file because it is always in the same place.

## A concrete example

Say you are fixing a bug for a client.

1. You describe the task. The tool works out which area of your work it belongs
   to and which files an agent should read first. If it cannot work that out
   confidently, it stops and says so rather than guessing.
2. A folder is created for that bug. The plan goes in it. So do the notes, the
   test output, and the link to the pull request.
3. An agent does the work, writing its progress into that same folder.
4. When it finishes, a record is closed out with evidence that it actually
   passed — the system refuses to mark work "done" without it.
5. Six weeks later somebody asks why you made a particular decision. The answer
   is in the folder, not in a chat log you no longer have.

## What it is not

- **Not a hosted service.** There is no account, no login, no server. It runs on
  your machine and the files are yours.
- **Not an agent.** It does not think or write code. It is the filing system the
  thinking happens inside. You still bring your own agent — Claude, Codex, or a
  human.
- **Not a project-management tool.** It does not replace Jira or Linear. It
  connects to them, and treats them as the authority on ticket status while the
  files stay the authority on how the work was actually done.
- **Not finished.** Parts of it are mature and used daily. Other parts are
  designed and only partly built. The handbook is honest about which is which,
  and so are these pages.

## Who it is for

Someone who runs a lot of work through AI agents and is tired of re-explaining
things. You need to be comfortable in a terminal and comfortable editing text
files. You do not need to be a Python developer, even though the tool is written
in Python.

If you have never opened a terminal, this is not the right tool for you yet.

## Next

[Install it](./install.md), then read [the seven ideas](./index.md#the-seven-ideas)
in order.
