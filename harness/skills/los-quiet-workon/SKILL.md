---
name: los-quiet-workon
description: Use when working or resuming LOS Jira implementation in a fast worktree with minimal chat output, especially after noisy /workon loops, repeated stack setup, test polling, or context/token burn.
---

# LOS Quiet Workon

Use this workflow when the user wants LOS Jira/worktree implementation work with minimal chat output, especially after context/token burn, noisy `/workon` runs, repeated fast-stack setup, or test/debug loops.

## Output Contract

- Send at most one short opening line saying what will be done.
- Do not send periodic progress updates during normal command execution, polling, file reads, or test waits.
- Speak only for: a real blocker, a risky cleanup decision, a user-visible result, or final handoff.
- Never paste full command output, Docker tables, diffs, Jira descriptions, or test logs into chat unless the user asks. Summarize only the actionable result.
- Prefer low-output tool calls: small `max_output_tokens`, narrow `rg`, targeted `sed`, and focused test selectors.
- Put durable details in the canonical Agentic OS work item under `/Users/genome/agentic_os/los/02-projects/los_app_los_django/work-items/` instead of chat when the run needs notes, logs, PR bodies, watcher state, or handoff context. Use the packet's `artifacts/` directory. Repo `.features/<ticket-or-task>/` folders are legacy mirrors only; do not create `.features/` artifacts inside an isolated worktree.
- For reopened post-merge work, keep a root `REOPEN.md` in the worktree with reason, dates, original PR, follow-up PR/ticket, owner, status, and Docker/OrbStack cleanup note. This file blocks unattended cleanup.
- Commands expected to run longer than two minutes must use `quiet-async-runner`,
  `/Users/genome/agentic_os/harness/bin/agentic-os-quiet-run`, a project watcher,
  or a scoped verification subagent. Chat is not the polling loop.

## Workflow

1. Identify the Jira key and create or reuse the canonical Agentic OS work item first. Prefer an existing matching lane object; otherwise run `agentic-os project work-item create los los_app_los_django --root /Users/genome/agentic_os --status building --format packet --title "<JIRA-KEY or task>: <short title>" --summary "<one-line task summary>"`. Set `AGENTIC_OS_ACTIVE_WORK_ITEM=<absolute work-item path>` for long-running commands and subagents.
2. For implementation, use an isolated LOS worktree. Prefer `~/projects/los/misc/setup-worktree.sh -b feature/<JIRA-KEY>-<slug> --fast`; do not use raw `git worktree add` unless the setup script is unavailable.
3. Run `git status --short --branch` before edits. Preserve unrelated dirty work and do not stage or revert files outside the task.
4. Use the existing skill/router only as needed: `los-fast-workon` for stack/worktree setup, `workon` for Jira implementation flow, and nearest `AGENTS.md` before editing a subtree.
5. Keep investigation narrow. Use Jira comments and prior PRs to form the bug hypothesis, then inspect the exact service, callers, and focused tests.
6. Before file edits, make one concise note if needed. Then edit with `apply_patch`.
7. Verify with the smallest meaningful test target first. Expand only if the change touches shared behavior. Run slow verification through `artifacts/async-runs/<run-id>/` and report only terminal pass, fail, killed, blocked, or timeout with a receipt.

## Fast Stack And Resource Handling

- Start with `make fast-status`; use `make fast-up` or the worktree setup script outputs for URLs.
- If setup or tests fail from occupied ports, identify the owning containers first. Stop only clearly stale/unrelated LOS worktree containers, and name that cleanup in the final summary.
- If tests die with exit `137`, treat it as likely host/container pressure. Check `docker stats --no-stream`, stop stale unrelated stacks if safe, then rerun a narrower target.
- Do not keep chat alive with test polling. For any slow setup or test wait, inspect only `state.json`; if it still says `running`, stay silent unless the user explicitly asked for status.
- Use context-mode to summarize large `output.log` files from async run artifacts instead of reading full logs into chat.
- When local tests are slow or unavailable and a PR exists, rely on GitHub PR checks as the final readiness signal and capture status notes or check artifacts under the work item's `artifacts/pr-watch/` folder.

## Final Handoff

Final response should be short and include:

- ticket/key and branch/worktree when relevant
- Agentic OS work item path
- files changed
- verification run and result
- any cleanup performed
- remaining blocker or next command, only if one remains
- if the work was reopened, whether `REOPEN.md` was updated with second-completion and safe-delete notes
