---
name: quiet-workon-orchestrate
description: Use when LOS implementation needs multi-agent fan-out, several work units, risk-routed quality holdouts, full PR lifecycle management, pre-commit blocked CI fallback, or mandatory Copilot comment resolution with chat kept to receipt-backed milestones only. The orchestrator plans, decomposes, dispatches worker and explorer subagents, verifies returns, and routes gates; evidence lives in the Agentic OS work item and durable PR/Jira summaries. NOT for single-agent quiet edits; use los-quiet-workon. NOT for worktree or stack setup alone; use los-fast-workon. Triggers include "orchestrate this ticket quietly", "fan this out with subagents", resuming noisy orchestration, or long-running LOS work that burns context with status chatter.
---

# Quiet Workon Orchestrate

Orchestrate non-trivial LOS implementation through subagents while keeping chat to decision-grade milestones. The main thread is the manager: it plans, decomposes, dispatches agents, verifies returns, routes quality gates, and owns what merges or pushes. Subagents do scoped implementation, lookup, test, or review work.

This skill is self-contained. It does not require any global-only helper. Describe the behavior first; name a tool only as the mechanism; depend on nothing that may be absent.

## Sibling Routing

- This skill: fan-out across multiple work units, risk-routed holdouts, or PR lifecycle management. Use it when one agent is not enough.
- `los-quiet-workon`: single-agent quiet implementation or resume. No fan-out.
- `los-fast-workon`: fast worktree and per-worktree Docker stack setup.

Worktree handling: if the task needs a fast worktree or stack, set it up with `los-fast-workon` first, then run this skill inside it. Otherwise use the repo canonical worktree setup and Makefile router. `los-fast-workon` is repo-local and optional; never make it a precondition for a run that does not need a worktree.

## Output Model

Quiet is not unverified. Minimal chat means evidence moves to artifact tiers, not that it disappears.

| Tier | Holds | Audience | Lifetime |
| --- | --- | --- | --- |
| Chat | Receipt-backed one-line milestones | The user, now | The session |
| Agentic OS work item `artifacts/` | Full evidence: commands, results, agent returns, decisions | This checkout's agents | Local-only, lifecycle source of truth |
| PR body + Jira | Short durable continuity summary | The team and future chats | Permanent |

Receipt rule: no chat milestone may assert a test, quality gate, Copilot, or CI outcome until the command, result, and timestamp have been written to an artifact. The milestone then points to that artifact, for example `(receipt: quality-gates.md#targeted-tests)`. Dispatch lines and user-decision lines need no receipt.

## Chat Contract

Default to silence. Before emitting any line, ask: does this change what a future chat would do to finalize the PR? If not, write to the Agentic OS work item artifacts or stay quiet. Direct user questions are always allowed when behavior is ambiguous or blocked.

Allowed milestones:

1. Opening line with task id, branch or worktree, artifact folder, and planned agent count.
2. Plan locked and agents dispatched.
3. Subagent result accepted, rejected, blocked, or re-scoped, with receipt.
4. Test suite or quality gate passed, failed, or blocked, with receipt.
5. Review holdout changed the implementation.
6. PR pushed or updated; Copilot round fixed and resolved; CI green or red, with receipt.
7. User decision required.
8. Final handoff.

Forbidden in chat:

- per-tool narration
- test polling, status re-reads, progress percentages, ETAs
- command output, diffs, logs, stack traces, Docker tables, Jira or PR check dumps
- thinking aloud while waiting
- repeated milestones
- success of an individual file edit

Example ledger:

```text
FLYWL-1234 Something Cool | branch feature/FLYWL-1234-something-cool | 4 agents
Artifacts: /Users/genome/agentic_os/los/02-projects/los_app_los_django/work-items/02-active/001_flywl_1234_something_cool/artifacts/
- Plan locked; agents 1-4 dispatched
- Agent 1 accepted: API behavior (receipt: agent-returns/agent-1.md)
- Agent 3 rejected: tests asserted internals; re-dispatched (receipt: agent-returns/agent-3.md)
- Targeted tests passed (receipt: quality-gates.md#targeted-tests)
- Security holdout passed (receipt: quality-gates.md#security)
- PR #24979 pushed; Copilot round 1 fixed and resolved (receipt: pr-watch/pr-24979-copilot.md#round-1)
- CI green (receipt: pr-watch/pr-24979-watch-summary.md#2026-06-08-2258)
```

## Durable Artifacts

Write to the canonical Agentic OS work item, never to `.features/` inside a
worktree. Reuse an existing matching work item first; otherwise create one with
`agentic-os project work-item create los los_app_los_django --root
/Users/genome/agentic_os --status building --format packet --title "<JIRA-KEY
or task>: <short title>" --summary "<one-line task summary>"`. Use the work
item `WORKLOG.md` for human-readable progress and its `artifacts/` directory for
raw evidence. If a project-level human summary is useful outside the packet,
write it under
`/Users/genome/agentic_os/los/02-projects/los_app_los_django/worklogs/` using
the same ticket or task slug. Set `AGENTIC_OS_ACTIVE_WORK_ITEM=<absolute
work-item path>` before starting long-running commands or subagents.

Repo-local or distributed instructions that still point to `.features/<ticket>` are legacy mirrors. Use a `.features` folder only when existing repo tooling requires it, and mirror from the Agentic OS work item rather than making `.features` the source of truth. Do not stage or commit `.features/`, `.claude/`, `.cursor/`, or `.prs/` unless the user asks.

For reopened post-merge work, maintain `REOPEN.md` at the worktree root. It must
include the reopen date, reason, original PR, expected follow-up PR or ticket,
owner, current status, second-completion date when known, and whether the
worktree plus Docker/OrbStack runtime are safe to delete. Cleanup automation
must not silently remove a worktree while `REOPEN.md` is present.

```text
/Users/genome/agentic_os/los/02-projects/los_app_los_django/work-items/02-active/<id>/
  work.yml
  artifacts/
    orchestration.md
    decisions.md
    quality-gates.md
    agent-returns/agent-<n>.md
    async-runs/<run-id>/
    pr-watch/
```

Each artifact carries `Created:` or `Updated: YYYY-MM-DD HH:MM TZ`; append-only logs timestamp each entry. Copilot receipts append one entry per review round. CI receipts append one check snapshot per material status change. A stale receipt does not satisfy a new outcome claim.

Subagents write full evidence to `agent-returns`; they return only the structured summary. The orchestrator reads summaries, not raw transcripts or reported output files. Never write tokens, credentials, `.env` values, or secrets to any tier.

## Long-Running Command Discipline

Any local command expected to run longer than two minutes must use a quiet
artifact-backed runner, a project-specific watcher, or a scoped verification
subagent. This includes Docker setup, `make fast-up`, package installs, full or
integration test suites, pre-commit, browser waits, and PR/CI watchers.

Preferred artifact shape:

```text
$AGENTIC_OS_ACTIVE_WORK_ITEM/artifacts/async-runs/<run-id>/
  command.json
  state.json
  events.jsonl
  summary.md
  output.log
```

When available, use `quiet-async-runner` or
`/Users/genome/agentic_os/harness/bin/agentic-os-quiet-run`. If neither is
available, reproduce the same artifact shape with `nohup`, a background harness
process, or a verification subagent.

The main orchestrator may inspect `state.json` quietly. If status is still
`running`, write nothing to chat. Do not emit "still running", "almost done",
process-table, Docker-build, ETA, or repeated check updates. Use context-mode to
summarize large `output.log` files after a terminal result.

## Core Protocol

### 1. Load

Resolve the Jira key, PR, spec, or prose. Create or reuse the Agentic OS work item. Read root `AGENTS.md`, the nearest subtree `AGENTS.md`, and only the `RULES.md` sections the router points to. Set up a worktree only if needed. Emit milestone 1.

### 2. Plan And Decompose

Run this on the main thread and record it in `orchestration.md`:

- Scope each unit to one deliverable.
- Sequence dependencies; parallelize only truly independent units.
- Never run two agents that touch the same file, registry, migration, fixture, or shared config. Serialize or refactor the contention first.
- Allocate branch names, keys, and file ownership here; pass them into prompts.
- Fetch the project-configured base branch from the bindings or local router before spawning.

If any point is unanswered, do not spawn yet.

### 3. Baseline

Record in `quality-gates.md`: base commit and pre-work numbers for cheap signals that exist here, such as targeted test pass count, lint count, or typecheck count. Run only what is practical. Do not hold chat open for slow checks; if local checks are unreliable, plan to use CI as the post-push signal.

If the baseline signal is slow, start it as an `async-runs/<run-id>` receipt and
move on. A still-running baseline is not a chat milestone.

### 4. Dispatch Subagents

Each prompt is self-contained:

- why the unit exists
- scope and off-limits paths
- exact files and lines
- nearest `AGENTS.md` rules
- decisions already made
- allocated identifiers
- exact verification commands
- return contract

Tell every worker: you are not alone in the codebase; preserve unrelated edits; never revert another agent's work; never run `--no-verify`, force push, or destructive git. Match the nearest sibling pattern; reduce real duplication with existing helpers; keep public contracts strict; add comments or docstrings only where the contract, side effect, or non-obvious behavior needs it.

### 5. Return Contracts

Worker agents return under 400 words:

```text
Agent <n> [worker]: <unit>  status: done | blocked | rejected
Branch/commit: <branch> <sha or none>
Changed: <files>
Verification receipts: <commands -> results + baseline delta, path in agent-returns>
AC covered: <each acceptance criterion -> file:line>
Decisions/risks: <50/50 calls, follow-ups, or none>
```

Explorer agents stay strictly read-only and return:

```text
Explorer <n>: <question>
Answer: <conclusion>
Files inspected: <paths>
Evidence: <file:line citations>
Confidence: <high | medium | low>
Unresolved: <open questions or none>
```

If any field is missing or vague, the return is untrusted. Ask the agent for a corrected summary and do not merge.

### 6. Verify And Accept

- Inspect the actual branch or diff.
- Re-run targeted tests and changed-file lint or pre-commit against the branch when practical.
- Record commands, results, and timestamp to `quality-gates.md`.
- Run slow verification through `async-runs/<run-id>` or a verification subagent;
  do not use main-chat polling as the wait mechanism.
- Check baseline regression: error and failing-test counts did not increase.
- Check scope: no unexplained files, no off-limits paths, and acceptance criteria traceable to code in under a minute.
- Reject broad unrelated refactors, comments explaining obvious code, abstractions that remove no real complexity, copy-paste where a helper exists, ignored `AGENTS.md`, and tests that assert implementation details instead of behavior.

Re-dispatch for scope drift, architecture errors, or missing tests. The orchestrator may make a small integration fix within owned files when that is lower risk than another agent loop, but must record the receipt.

### 7. Quality Holdouts

Default governor:

- Always run practical mechanical gates: `lint`, `test`, `pre-commit`.
- If local `pre-commit` itself is blocked by environment, dependency, runner,
  or host tooling after focused tests and changed-file checks are otherwise
  ready, record the exact blocker in `quality-gates.md` and continue through
  the PR fallback in steps 8 and 9. This is not permission to skip hooks or hide
  a code failure.
- In LOS app worktrees, ignore unrelated dirty churn in
  `los/static-vue3/src/styles/peak-styles.css` unless the ticket intentionally
  changes peak styles. Do not stage, reformat, or block PR readiness on that
  file; record it as a known unrelated exception, run lane-scoped changed-file
  checks for task-owned files, and use PR checks as the final broad signal.
- Always do one lightweight anti-slop self-review with the step 6 checklist.
- Run specialist holdouts only when touched paths or behavior match the risk table.
- Default cap is two specialist holdouts. Mandatory high-risk holdouts consume the cap. If more than two high-risk categories are triggered, pause and record why the cap is being expanded, or ask the user if the added review cost is not obviously justified.

Risk routing:

| Risk | Repo-local mechanism | Optional Claude-only reviewer |
| --- | --- | --- |
| Permissions, tenant boundaries, IDOR, PII, user input | `security-scan`, `security-coach` | `pull-request-security-reviewer` |
| Layering, coupling, state machines, cross-module patterns | `architecture-scan`, `architecture-coach` | `pull-request-architecture-reviewer` |
| Serializers, list endpoints, querysets, N+1, repeated DB access | `perf-scan`, `perf-coach` | `pull-request-django-reviewer` |
| Celery, retries, idempotency, external side effects, recovery | `durable-execution-coach` | none |
| Jira acceptance, end-to-end, browser validation | `qa-analysis` | `pull-request-acceptance-reviewer` |

No repo-local coach exists for readability, maintainability, docs, database, or devops. Use `lint`, `test`, repo rules, human review, and confirmed Claude `pull-request-*` reviewers when present.

Run scan skills in local report mode by default. Do not post PR comments unless the user asked for PR review comments or the workflow explicitly entered PR-posting mode.

### 8. Commit, Push, PR

Use the repo commit convention `<JIRA-KEY>: <subject>`, body wrapped to 120, no `Co-Authored-By`, no AI footer, no `--no-verify`. If the primary checkout holds unrelated WIP, commit only owned files or work from the worktree.

Build the PR body from `.github/pull_request_template.md` with a linked Jira reference, a 1-3 bullet summary, and the verification evidence.

If local `pre-commit` is blocked by environment or tooling, do not stop at the
local blocker. Push the owned branch, open or update a PR, set it to ready for
review, and let GitHub checks run the validation that local pre-commit could
not complete. Monitor those checks through receipt-backed artifacts and fix
non-infrastructure failures until the PR is green or the remaining blocker is
specific and recorded.

### 9. PR Readiness

Prefer local checks when trustworthy; otherwise use CI as the final signal.

- Capture check status under the work item's `artifacts/pr-watch/`; never poll in chat.
- Use any available quiet PR watcher as an implementation detail if present.
- Otherwise write sparse `gh pr view` and `gh pr checks` snapshots to the artifact at intervals.
- Do not hardcode any global watcher script path in this skill.
- On a red check, dispatch a fix agent and emit one milestone with a receipt.

Copilot: use `copilot-fix` for a single triage/fix/reply/resolve round and `copilot-hell` for repeated rounds. Every Copilot comment or review thread that appears must be addressed by either making the requested fix or leaving a clear explanatory reply, then resolving the thread or comment. Emit a milestone only when a round is fixed and resolved or Copilot is clean, with an append-only receipt. Apply a ready label only after a clean Copilot pass, no actionable check failures, and passed holdouts.

### 10. Team Continuity

Before final handoff, write a short team-facing summary to the PR body and Jira when a PR or Jira exists and the agent has authorized write access. Include final decisions, verification status, known risks, and remaining blockers. Keep it short; do not mirror all local evidence.

If remote writes are blocked, record the intended summary in the work item artifacts and surface one blocker.

## Stop And Re-Scope

Stop and re-plan when:

- an agent drifts beyond owned files
- two agents need the same file or shared config
- verification fails twice with blind retries
- a high-risk holdout finds a blocker
- behavior needs a decision reasonable engineers could dispute
- local validation fails and CI cannot substitute
- context is burning without convergence, including host pressure or exit 137

On any stop, update `orchestration.md` and emit one milestone.

## Final Handoff

Shipped:

```text
FLYWL-1234 shipped via 4 subagents.
- Changed: API, UI state, tests
- Verification: targeted tests passed; CI green (receipts: quality-gates.md, PR #24979)
- Quality: security + perf holdouts passed; Copilot resolved
- PR: <url>   Jira: <url>
- Remaining: none
```

Blocked:

```text
FLYWL-1234 blocked.
- Blocker: <specific blocker>
- Last good state: <branch/sha/artifact>
- Resume from: <exact command or next action>
- Detail: /Users/genome/agentic_os/los/02-projects/los_app_los_django/work-items/02-active/<id>/artifacts/orchestration.md
```

## LOS Bindings

This section is LOS-specific; the protocol above is portable.

- Artifact root is always the Agentic OS work item `artifacts/` directory, even from a worktree.
- Base branch and PR target: `origin/develop`. Normalize `release/vX.Y` to `vX.Y.0`, same for hotfix.
- Branch format: `feature/<JIRA-KEY>-short-description`, or `hotfix/` and `release/` where appropriate.
- Jira prefixes: `DLOS`, `LOSIMP`, `FLYWL`. Confirm current ticket-creation policy before filing a new ticket. Atlassian root: `https://venturesgo.atlassian.net`.
- Tests and most operations run through `make`, for example `make t`; read the `Makefile` before inventing commands.
- Worktree and stack setup go through `los-fast-workon`, not raw `git worktree add`.
- Line length 120; run local pre-commit when possible, use the PR fallback when
  local pre-commit is blocked by environment or tooling, and never use
  `--no-verify`.
- Copy-paste prose, including PR body, commits, Copilot replies, and Jira comments, avoids em dashes.
- Do not read, edit, or commit `stgcore-app-ulp` unless explicitly asked.

## Availability

- Repo-local skills: `los-fast-workon`, `los-quiet-workon`, `lint`, `test`, `pre-commit`, `architecture-scan`, `security-scan`, `perf-scan`, `architecture-coach`, `security-coach`, `perf-coach`, `durable-execution-coach`, `qa-analysis`, `copilot-fix`, `copilot-hell`.
- Repo-local commands/workflows: `workon`.
- Global-only helpers, never required by this skill: `watch-pr-quiet`, global `orchestrate`, global `duel`.
- Claude-only agents, confirm present first: the `pull-request-*-reviewer` family and `pull-request-graybeard`.
- Do not make a global-only or unconfirmed helper a required dependency.
