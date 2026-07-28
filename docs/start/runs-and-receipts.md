---
title: Runs and receipts
sidebar_label: Runs and receipts
slug: /start/runs-and-receipts
description: The record of what actually happened, kept so you can check it later rather than take somebody's word for it.
---

# Runs and receipts

**What they are for:** knowing what actually happened, weeks later, without
relying on anyone's memory or on a chat log you no longer have.

**Where they apply:** every time a workflow or automation does something. The
record lands in the domain's `06-runs-and-logs/` folder.

## Open a record before you start

The habit is: open the record first, do the work, close the record with
evidence.

```bash
agentic-os run-log create acme bug_to_merged_fix --root ~/agentic_os
```

That creates a folder named for the moment it started:

```
domains/acme/06-runs-and-logs/runs/2026-07-27T14-30-00Z-acme-bug_to_merged_fix/
  run-log.md
  artifacts/
```

`run-log.md` is the narrative — what you set out to do, what you found, what you
decided. `artifacts/` is where the proof goes: test output, screenshots,
command transcripts, links to the pull request.

Two words that get used almost interchangeably: the **run** is the folder and the
event it represents; the **run log** is the `run-log.md` file inside it.

## Closing it is where the discipline is

```bash
agentic-os run-log close ... --status done --validation "pytest: 1776 passed"
```

You cannot close a run as `done` without `--validation`. The command refuses and
exits with an error.

This is the rule the whole system is built around. "It works" is a claim.
"`pytest: 1776 passed`, and here is the output in `artifacts/`" is evidence. Only
the second one is allowed to close a run.

It sounds pedantic until the first time somebody — possibly an AI agent,
possibly you at midnight — reports that something is finished when it is not.

## Seeing what is happening now

```bash
agentic-os ps              # what is running right now
agentic-os ps --active     # the wider dashboard
```

`ps` is deliberately named after the Unix command that lists running processes.
It answers "what is in flight," which is a different question from "what has
happened," and the run logs answer the second.

## Why the evidence has to be on disk

Three reasons, and they compound:

1. **You will not remember.** Six weeks is enough to forget why you chose one
   approach over another.
2. **Agents forget instantly.** A new conversation has no memory of the last
   one. The receipt is how the next agent finds out what was already tried.
3. **Claims drift from reality.** An agent reporting "all tests pass" and the
   tests actually passing are two different facts. Writing the second one down
   is the only way to tell them apart later.

There is a general rule in this system, worth internalising: **any statement that
something passed must point at a receipt** — a specific check, a command output,
or a file path. A summary with no receipt is an opinion.

## Where evidence outranks what

When sources disagree about what is true, the order of authority is:

1. What the live system says right now
2. The most recent local receipt
3. GitHub — for anything about branches, checks and merges
4. A report surface such as Notion
5. Anyone's recollection

Memory is last on purpose.

## Go deeper

- [Runs and run logs](/docs/08-runs-and-run-logs) — the full handbook page
- [Source of truth](/docs/25-source-of-truth) — the authority order in detail
- [Health, doctor and validation](/docs/16-health-doctor-validation) — the
  checks available to you
