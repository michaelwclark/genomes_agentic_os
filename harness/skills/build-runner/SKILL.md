---
name: build-runner
description: Drive a Kanban-backed implementation queue through orchestrate, producing local worklog artifacts, verified worktree merges, holdout QA, worklog rollups, and board writeback. Use when READY cards should be built in prefix order with tracking notes left on the source board.
---

# Build Runner

Build Runner is a higher-level queue runner layered on top of `/orchestrate`.
It treats a Kanban board as the control plane, local markdown artifacts as the
durable audit trail, and git worktrees as isolated execution lanes.

Canonical source path:

```text
harness/skills/build-runner/SKILL.md
```

Use this skill when the user asks to build multiple Kanban items in order,
update the source cards with tracking notes, and keep development moving until
the queue is complete.

Do not use this skill for a single small task. Use `/orchestrate` directly for
one feature, bug, or spec.

## Core Contract

Given a board, column, and ordering rule, Build Runner must:

1. Verify the board is accessible and safe to write.
2. Load project `CONFIG.md` when present and use it before skill defaults.
3. Load the requested cards from the requested queue.
4. Normalize card specs into local worklog folders.
5. Run each card through investigation, planning, implementation, review, QA,
   merge, and board sync.
6. Append completed card artifacts into `WORKLOGS/*.md` or `worklogs/*.md`.
7. Persist enough state to resume after interruption without duplicating work.

The board is the control plane. The repo is the execution surface. The worklog
folder is the audit trail. Git is the merge record.

## Recommended Changes From The Initial Prompt

- Make this a wrapper around `/orchestrate`, not a replacement for it.
- Add a board adapter contract so Notion, Jira, Linear, GitHub Projects, and
  local markdown boards can normalize into the same card schema.
- Add a preflight gate for board identity, git state, default branch, test
  commands, and existing artifacts.
- Add `RUN_STATE.json` so a long queue can resume safely.
- Add `work.yml` to every worklog folder as the machine-readable anchor.
- Standardize artifact names: `INVESTIGATION.md`, `JUDGMENT.md`, and
  `HOLDOUT_QA_RESULTS.md`.
- Keep shared writes orchestrator-owned. Subagents return structured results;
  they do not append to `WORKLOGS/*.md`, `worklogs/*.md`, or write board
  comments directly.
- Make automation finite and checkpointed. "Do not stop" means resumable loop,
  retry limits, timeouts, and kill criteria.
- Make generated `SPECS/*.md` subtasks idempotent and linked back to the source
  card ID.
- Treat Notion as the control plane, not the runtime database.

## Required Inputs

The user should provide:

- Board source: Notion URL, Jira board, Linear view, GitHub Project, or local
  markdown index.
- Source queue: for example `READY`.
- Ordering rule: for example title prefix ascending from `ex00` through `ex99`.
- Target branch: default to the repo default branch.
- Worklog root: default to `worklogs/`, or `WORKLOGS/` when the project uses
  uppercase bucket folders.
- Spec root: default to `SPECS/`.
- Legacy artifact roots: read existing `features/`, `.features/`, `PLANS/`,
  and `BUILD_LOGS/` only as compatibility inputs unless project config says
  otherwise.

If root `CONFIG.md` exists, read it before applying these defaults. It may
define board properties, queue names, workflow direction, spec/worklog artifact
paths, worktree policy, merge strategy, holdout QA requirements, and writeback
mode.

Infer missing low-risk inputs from the repo and log the choice in
`JUDGMENT.md`. Stop and ask only when the missing input could write to the wrong
external system, destroy existing work, or materially change scope.

## Board Safety

Before writing to any board:

- Verify the board workspace/account is the intended destination.
- For Notion documentation or tracking, verify the target is Genome's Notion
  unless the user explicitly names another workspace.
- If the active Notion connector is Michael Clark's personal Notion, stop.
- If Genome's Notion is not visible, ask for a Genome's Notion parent page URL
  or access before creating, updating, moving, or duplicating content.
- Do not create temporary fallback pages in another workspace.

Board writes must be idempotent. Include stable references such as source card
ID, feature slug, branch name, merge commit, and timestamped status entries.

## Card Schema

Normalize every board item to this internal shape:

```yaml
id: stable external card id
url: source card URL
title: original title
prefix: sortable title prefix, such as "00" or "ex00"
slug: filesystem-safe slug
status: source queue status
acceptance_criteria: list of concrete outcomes
notes: source-card notes or body
dependencies: list of card ids, prefixes, or slugs
blocked_by: list of external blockers
```

Stop and ask if a card lacks enough acceptance criteria to determine done.

## Ordering

Default order:

1. Parse a leading prefix matching `exNN`, `NN`, or `NN-...`.
2. Sort ascending by numeric value.
3. For equal prefixes, preserve board order.
4. Ignore cards outside the requested source queue.

If board order conflicts with title-prefix order, title-prefix order wins when
the user explicitly asks for lowest prefix to highest prefix.

## Local Artifact Layout

For every card, create one canonical worklog directory:

```text
worklogs/<prefix-slug>/
  work.yml
  SPEC.md
  INVESTIGATION.md
  PLAN.md
  MEMORY.md
  WORKLOG.md
  SUMMARY.md
  NEXT.md
  HOLDOUT_QA.md
  HOLDOUT_QA_RESULTS.md
  JUDGMENT.md
```

Use `WORKLOGS/<prefix-slug>/` instead of `worklogs/<prefix-slug>/` when the
project's visible bucket folders are uppercase. Lowercase `logs/` remains raw
system output only.

Use the spellings above as canonical. Do not create `JUIDGMENT.md`,
`JUDGEMENT.md`, `INVESTIGATE.md`, or `HOLDOUT_QA_RESUTLS.md`.

`work.yml` must record source card ID, title, prefix, slug, source URL,
status, branch, base SHA, merge SHA, started/completed timestamps, baseline
verification, and final verification.

## Run State

Create or update root-level `RUN_STATE.json`.

It must track:

- Run ID.
- Board source and workspace/account verification.
- Queue name and ordering rule.
- Target branch and base SHA.
- Work list with card IDs, slugs, status, branch, and merge commit.
- Current active work item.
- Last successful phase per work item.
- Generated subtasks.
- Board sync writes already performed.

Before processing a card, check whether the worklog folder, branch, merge
commit, generated subtask, or board note already exists.

## State Machine

Each card moves through:

```text
queued -> claimed -> investigating -> planned -> implementing -> reviewing
-> qa_planning -> qa_running -> ready_to_merge -> merged -> synced -> done
```

Use `blocked` for cards that cannot proceed.

Only the orchestrator may change state. Subagents can recommend state changes,
but the orchestrator verifies and writes them.

## Git And Worktree Rules

Before starting the queue:

- Capture `git status --short`.
- Detect the default branch.
- Fetch the default branch.
- Record the base SHA.
- Detect existing worktrees.
- Identify uncommitted user changes.

Do not overwrite existing user work. If dirty files overlap the feature, stop
and ask. If dirty files are unrelated, create a separate worktree from the
target branch and leave the user's changes alone.

For each feature:

1. Create a dedicated worktree and branch.
2. Run investigation and planning in that worktree.
3. Dispatch implementation subagents only for isolated plan items.
4. Require one scoped commit per subagent-owned plan item when code changes.
5. Re-review the spec and plan after subagent returns.
6. Loop implementation until all acceptance criteria are satisfied.
7. Run holdout QA from the orchestrator-owned testing plan.
8. Merge the feature branch back to the target branch after verification.

Use `--no-ff` merges unless the host project specifies a stronger convention.
Never use `--no-verify`.

## Orchestration Rules

The main thread is the driver. It owns card loading, ordering, worklog folders,
shared logs, worktree creation, merges, scope decisions, acceptance-criteria
mapping, board updates, and final verification.

Subagents may own read-only investigation, one isolated implementation plan
item, focused review, or holdout QA execution.

Subagents must not write shared files such as `WORKLOGS/*.md`, `worklogs/*.md`,
legacy `BUILD_LOGS/*.md`, `RUN_STATE.json`, or source-board tracking notes.
They return structured results to the orchestrator, and the orchestrator writes
shared state.

Each implementation subagent prompt must include:

- Work slug and source card title.
- Exact plan item it owns.
- Files it may edit.
- Files it must not edit.
- Required branch/worktree.
- Required verification commands.
- Required commit format.
- Return contract.

Each subagent must return branch/commit SHA, changed files, verification
results, judgment calls, deferrals, and blockers. If the return is incomplete,
treat it as untrusted and request a correction before merging or logging.

## Per-Feature Phases

Run every card through these phases in order.

### 1. Start

Claim the card in `RUN_STATE.json`, add a source-board progress note, create the
worklog directory, copy the source spec into `SPEC.md`, create `work.yml`,
and initialize the artifact files.

### 2. Investigate

Write `INVESTIGATION.md` with current code paths, existing tests, relevant docs,
configuration, risks, unknowns, and missing acceptance criteria.

If investigation reveals a missing prerequisite feature, create:

```text
SPECS/<parent-prefix>-<subtask-number>-<parent-slug>-<sub-name>.md
```

Add the prerequisite to the board only after board write access is verified.

### 3. Plan

Write `PLAN.md` with acceptance-criteria mapping, work units, dependencies,
likely files, subagent allocation, verification commands, and rollback path.

Do not dispatch subagents until file ownership is clear and parallel edits to
the same files are avoided.

### 4. Implement

Run `/orchestrate` against the feature plan. Append orchestrator-owned progress
entries to `WORKLOG.md`, update `JUDGMENT.md` for 50/50 decisions, and update
`MEMORY.md` for notable findings worth carrying forward.

After every implementation return, re-read `SPEC.md` and `PLAN.md`. Map every
acceptance criterion to completed work, a blocker, or a follow-up. Continue
until no acceptance criteria remain unhandled.

### 5. Review

Review the feature branch before QA. Confirm the diff matches scope, no
unexpected files changed, shared files changed intentionally, acceptance
criteria are covered, tests are added or intentionally omitted, and docs/control
plane updates are included when required.

### 6. Holdout QA

Write `HOLDOUT_QA.md` as an executable test plan for a fresh agent that did not
implement the feature. Include setup, commands, manual/browser checks if
needed, expected results, and failure triage.

Dispatch QA subagents only when tests are isolated. Write
`HOLDOUT_QA_RESULTS.md` with commands, pass/fail results, summarized logs, bugs
found, fix verification, and residual risk.

If holdout QA fails, return to implementation and continue the loop.

### 7. Merge And Sync

Before merging, re-run orchestrator-side verification, compare final results
against baseline, confirm test failures do not exceed baseline failures, and
ensure no acceptance criteria remain open unless explicitly deferred.

After merge, record the merge commit in `work.yml`, update `SUMMARY.md`,
update `NEXT.md`, update the source card, and move the card only if the board
convention is known.

### 8. Append Worklog Rollups

After each work item is complete, append every work artifact to shared worklogs
when the project uses aggregate rollup files:

```text
worklogs/SPEC.md or WORKLOGS/SPEC.md
worklogs/INVESTIGATION.md or WORKLOGS/INVESTIGATION.md
worklogs/PLAN.md or WORKLOGS/PLAN.md
worklogs/MEMORY.md or WORKLOGS/MEMORY.md
worklogs/WORKLOG.md or WORKLOGS/WORKLOG.md
worklogs/SUMMARY.md or WORKLOGS/SUMMARY.md
worklogs/NEXT.md or WORKLOGS/NEXT.md
worklogs/HOLDOUT_QA.md or WORKLOGS/HOLDOUT_QA.md
worklogs/HOLDOUT_QA_RESULTS.md or WORKLOGS/HOLDOUT_QA_RESULTS.md
worklogs/JUDGMENT.md or WORKLOGS/JUDGMENT.md
```

Each append must start with:

```markdown
# WORK-<work-slug>
```

## Board Writeback Template

Use a concise tracking note:

```markdown
## Build Runner Update

Status: <state>
Work: <work-slug>
Branch: <branch>
Commits: <commit list>
Merge: <merge sha or pending>
Verification:
- Typecheck: <result>
- Tests: <result>
- Build: <result>
Blockers: <none or list>
Follow-ups: <none or list>
Artifacts:
- worklogs/<work-slug>/ or WORKLOGS/<work-slug>/
- shared worklog rollups when configured
```

Never paste secrets or raw token values into board notes.

## Stop And Ask

Stop and ask when board write access cannot be verified, Notion is not Genome's
Notion when expected, a card lacks acceptance criteria, a change appears
destructive, secrets or tenant data are required, dirty changes overlap needed
files, the merge target is ambiguous, baseline verification blocks regression
judgment, or a generated prerequisite materially changes the queue.

## Use Best Judgment And Log

Continue without asking, but log the decision in `JUDGMENT.md`, for naming
within the accepted slug convention, local artifact placement, minor docs
organization, obvious test command selection, serializing work for file
isolation, or deferring non-acceptance-criteria cleanup to `NEXT.md`.

Every judgment entry should include decision, rationale, alternatives
considered, risk, and follow-up.

## Automation Loop

Build Runner should be resumable, not unbounded.

Use a finite loop:

1. Load `RUN_STATE.json`.
2. Find the next eligible card.
3. Run the next incomplete phase.
4. Persist state.
5. Sync the board.
6. Continue until all requested cards are `done` or `blocked`.

Each loop iteration needs a timeout, retry limit, kill criterion, and persisted
checkpoint. If the host supports recurring automations or heartbeats, use them
only to resume the same run with the same `RUN_STATE.json`.

## Kill Criteria

Stop the current feature and mark it blocked when subagents drift outside
scope, two implementation attempts fail the same verification without new
evidence, the base branch changes in a way that invalidates the worktree, merge
conflicts affect unrelated user work, QA finds an unresolved product decision,
or the board/card disappears or changes ownership mid-run.

## Recommended Skill Packaging

Keep this `SKILL.md` as the concise operating contract.

Recommended bundled files for a production version:

```text
harness/skills/build-runner/
  SKILL.md
  templates/
    work.yml
    SPEC.md
    INVESTIGATION.md
    PLAN.md
    MEMORY.md
    WORKLOG.md
    SUMMARY.md
    NEXT.md
    HOLDOUT_QA.md
    HOLDOUT_QA_RESULTS.md
    JUDGMENT.md
    RUN_STATE.json
    board-update.md
  references/
    board-adapters.md
    worktree-safety.md
    qa-gates.md
  scripts/
    init_feature.py
    append_build_logs.py
    validate_run_state.py
```

Use scripts for deterministic filesystem work once this workflow is repeated
often enough. Until then, the orchestrator may create markdown artifacts
directly.

## Open Questions

1. Should completed source cards move to `DONE`, move to `QA`, or stay in place
   with tracking notes only?
2. Should generated prerequisite `SPECS/*.md` items enter the active queue
   immediately or wait in backlog for review?
3. What is the canonical Genome's Notion board schema: status, title, prefix,
   acceptance criteria, notes, and done/review properties?
4. Should each work item merge immediately after passing QA, or should the runner
   batch merges at the end of a queue run?
5. What is the maximum number of concurrent subagents or worktrees for one run?
6. Should the runner create a real automation/heartbeat for long runs, or only
   persist `RUN_STATE.json` and resume when invoked again?
7. Should board writeback append comments, update the card body, update
   structured properties, or do both property updates and a short comment?
8. Should failed cards block the whole queue, or should the runner mark the
    card blocked and continue to the next independent card?
