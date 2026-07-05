---
name: los-fast-workon
description: Use when the user wants to work a LOS Jira ticket or non-trivial LOS task in a dedicated fast worktree, especially when they mention /workon, /orchestrate, fast worktree, use a worktree, or parallel agents.
---

# LOS Fast Workon

Use this skill to start LOS implementation work in the project-approved fast-worktree path, then optionally orchestrate subagents after the worktree is ready.

Agentic OS lifecycle state is the source of truth for LOS work. Repo-local or distributed skill/rule copies that still point agents at `.features/<ticket>` are legacy; use them only as optional mirrors after the OS work item exists.

## Entry Conditions

Use this when the user asks to work a Jira ticket, start implementation, use a worktree, combine `/workon` with `/orchestrate`, or run parallel agents for LOS work.

This skill is for agent-created worktrees. Codex Desktop UI worktrees are still created under `$CODEX_HOME/worktrees`; their local environment setup should run `.codex/environments/los-app-los-django.toml`, which delegates to `scripts/codex/setup-environment.sh`.

## Canonical Workflow

1. Start in the primary LOS checkout unless the user already provided a specific worktree.
2. Run `git status --short --branch` and preserve unrelated dirty work.
3. Call `memory_read` with the ticket key or task keywords before deep reconnaissance.
4. Resolve the Jira ticket if a key is provided. Extract summary, acceptance criteria, fix version, and linked context.
5. Create or reuse the canonical Agentic OS work item under `/Users/genome/agentic_os/los/02-projects/los_app_los_django/work-items/`. Prefer an existing matching lane object; otherwise create one:

```bash
agentic-os project work-item create los los_app_los_django \
  --root /Users/genome/agentic_os \
  --status building \
  --format packet \
  --title "<JIRA-KEY or task>: <short title>" \
  --summary "<one-line task summary>"
```

Use the work item's `WORKLOG.md` for human-readable progress and its
`artifacts/` directory for plans, PR bodies, watcher state, raw logs, and
handoff evidence. If a project-level human summary is useful outside the packet,
write it under `/Users/genome/agentic_os/los/02-projects/los_app_los_django/worklogs/`
using the same ticket or task slug. Set
`AGENTIC_OS_ACTIVE_WORK_ITEM=<absolute work-item path>` for long-running commands
or subagents so hooks route transcripts to the packet. Treat primary-checkout
`.features/<ticket-or-task>/` as a legacy mirror only when existing tooling still
requires it; do not create `.features` inside an isolated worktree.
If QA or production follow-up reopens work after a PR has already merged, create
`REOPEN.md` at the worktree root. Include the reopen date, reason, original PR,
expected follow-up PR or ticket, owner, current status, and Docker/OrbStack
cleanup note. `REOPEN.md` blocks unattended cleanup until the follow-up is
resolved and a human confirms deletion.
6. Create the implementation worktree with the stable LOS helper:

```bash
~/projects/los/misc/setup-worktree.sh -b feature/<JIRA-KEY>-<slug> --fast
```

Use `--fast-with-legacy-ui` only when the task needs the legacy Webpack dev server. If fast startup fails because `los_gold` is missing, report the bootstrap command instead of silently falling back.

7. `cd` into the new worktree. Run `make fast-status`; if the stack is not up and the user needs runtime validation, run `make fast-up` through `quiet-async-runner`, `/Users/genome/agentic_os/harness/bin/agentic-os-quiet-run`, or an equivalent artifact-backed runner when it may take longer than two minutes. Do not keep chat alive with Docker build or container-start polling.
8. Run the `/workon` workflow inside the worktree: plan file, likely files, implementation approach, and test plan. Store durable output in the Agentic OS work item artifacts unless a legacy mirror is explicitly needed.
9. Use `/orchestrate` only after the worktree and plan are ready. The orchestrator stays in control, allocates branches/units, and only spawns agents for independent file scopes. Tell workers they are not alone in the codebase and must not revert others changes.
10. Verify locally with repo Makefile targets where practical. Run slow local tests through `artifacts/async-runs/<run-id>/` and summarize large logs with context-mode. If local tests are blocked or too slow, lean on GitHub PR checks after pushing. Use a quiet PR watcher only when that helper is available; otherwise run `gh pr checks` and record the result in the Agentic OS work item artifact folder.
11. On pause, run `make fast-down` unless the user asks to keep the stack running.

## Guardrails

- Do not run raw `git worktree add` for LOS implementation work.
- Do not use stale repo-local setup scripts; the stable helper is `~/projects/los/misc/setup-worktree.sh`.
- Do not touch `stgcore-app-ulp` unless the user explicitly asks.
- Do not mutate the main checkout when it is dirty; isolate implementation in the worktree.
- When completing reopened work, update `REOPEN.md` with the second completion date, follow-up PR, and whether the worktree plus Docker/OrbStack runtime are safe to delete.
- For placeholder keys ending in `-0000`, such as `DLOS-0000`, `LOSIMP-0000`, or `FLYWL-0000`, require a clear slug so branch and work-item names are not ambiguous.
- Chat is not the wait loop for worktree setup, Docker, tests, pre-commit, or PR checks. If status is only `running`, stay silent unless the user explicitly asked for status.
- Commit format is `<JIRA-KEY>: <concise message>` with no AI attribution.

## Final Report

Report the ticket, worktree path, branch, fast-worktree ports or `.env.worktree` location, commands run, validation result, and any blockers.
