---
title: Workflows
sidebar_label: Workflows
slug: /start/workflows
description: A written-down procedure you follow more than once, stored as a folder of documents rather than code.
---

# Workflows

**What they are for:** writing down a procedure you do more than once, so the
tenth time goes the same way as the first — whoever or whatever is doing it.

**Where they apply:** inside a domain, grouped by category. "How we onboard a
new client." "How we take a bug from report to merged fix." "How we publish the
monthly report."

## A workflow is documents, not code

This surprises people. A workflow is not a script and it does not execute. It is
a folder of Markdown files describing what the procedure needs, where it has to
stop for a human decision, and what it must produce.

The reason is that the audience is a mix of humans and AI agents, and both read
prose. A script would only be runnable by one of them.

```bash
agentic-os workflow create acme engineering bug_to_merged_fix --root ~/agentic_os
```

That creates
`~/agentic_os/domains/acme/03-workflows/engineering/bug_to_merged_fix/`, holding
around fourteen files. The ones that carry the most weight:

| File | What it holds |
| --- | --- |
| `outcome-brief.md` | What this procedure is for and what success looks like |
| `prd.md` | The requirements in detail |
| `implementation-plan.md` | The steps |
| `approval-rules.md` | Where a human must say yes before continuing |
| `output-contract.md` | What must exist at the end for this to count as done |
| `context-pack.md` | Which files and links you need to have read |
| `runbook.md` | The operational detail for actually running it |
| `state-machine.md` | The stages the work moves through |
| `context-contract.yml` | A machine-readable list of what an agent should read first |

`acme` is the domain. `engineering` is the **lane** — a category. The standard
lanes are `engineering`, `marketing`, `sales`, `support`, `operations`,
`finance`, `personal_admin` and `learning`.

Names use underscores, not hyphens. The tool rejects hyphens.

## Checking a workflow is fit to use

```bash
agentic-os workflow check acme engineering bug_to_merged_fix --root ~/agentic_os
```

This reports findings at four severities: **blocker**, **fix-soon**, **cleanup**
and **observation**. Blockers are things like "the trigger section is still a
placeholder."

Important: `workflow check` always exits successfully, even with blockers. It
advises, it does not enforce. The gate is you reading the output. Where it does
bite is in [automations](./automations.md) — you cannot promote an automation
past a certain point while it has blockers.

:::note Fresh scaffold result

The scaffold writes all 14 required files and both support READMEs. Before you
fill the contract, `workflow check` reports one intentional `fix-soon` finding:
the unresolved `Dispatch Decision` placeholders in `alignment-questions.md`.
See the [captured output](/docs/06-workflows#real-output--freshly-scaffolded-workflow).

:::

## Routing: how an agent finds the right one

You do not tell the agent which workflow to use. You describe what you want and
the system works it out:

```bash
agentic-os route "the weekly summary endpoint is returning stale data"
```

This is deterministic — plain matching rules, not a model call. It returns an
ordered list of files to read, the folder to work in, anything on the request
that looks like it needs approval, and a ready-made prompt to hand an agent.

If it is not confident, it refuses and exits with an error rather than guessing.
That refusal is a feature. A confident wrong route is worse than no route.

## The five instruction files

Every level of the tree — the OS root, each domain, each project, each workflow —
carries the same five files. They are how an agent orients itself:

| File | Answers |
| --- | --- |
| `AGENTS.md` | "You have just arrived. Read these things, in this order." |
| `ROUTER.md` | "Work about X belongs over there." |
| `CONTEXT.md` | "Here is what this place is for and what is currently going on." |
| `RULES.md` | "Here is what you must ask about, and what you must never do." |
| `TOOLS.md` | "Here are the commands and integrations available here." |

`CLAUDE.md` exists too, and is a one-line pointer at `AGENTS.md`. It is there so
Claude finds the same content Codex does.

## A real one to look at

`harness/shared_factory/03-workflows/engineering/os_cleanup/` ships with the
repository. It is the procedure for tidying up finished worktrees and stale
runtimes without deleting evidence somebody might still need.

## Go deeper

- [Workflows](/docs/06-workflows) — the full handbook page
- [Routing and context](/docs/05-routing-and-context) — how routing decides
- [Governed workflow engine](/docs/37-governed-workflow-engine) — the
  machine-readable workflow definition, for when documents are not enough
