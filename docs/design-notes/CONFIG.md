# Genome's Agentic OS Configuration

This file documents the default operating configuration that ships with
Genome's Agentic OS. It is intentionally human-readable first and
machine-parsable second.

Each setting includes:

- Default value.
- What it controls.
- Valid options or expected shape.
- Notes about how agents should use it.

Projects may override these defaults, but agents should prefer this file before
inventing local conventions.

## Config Resolution

Default resolution order:

1. User instruction in the active thread.
2. Project-local `CONFIG.md`.
3. Project `AGENTS.md`, `CLAUDE.md`, or equivalent harness instructions.
4. Installed OS config under `~/agentic_os`.
5. Skill defaults.

When values conflict, prefer the more specific active instruction and record
the choice in the relevant work artifact, usually `JUDGMENT.md`.

## Shared Skills

```env
OS_SHARED_SKILLS_SOURCE_DIR=./harness/skills/
OS_SHARED_SKILLS_REGISTRY=./harness/skills/skill-registry.yml
OS_SHARED_SKILLS_INSTALLED_DIR=~/agentic_os/harness/shared_factory/05-knowledge/skills/
OS_SHARED_SKILLS_INSTALLED_REGISTRY=~/agentic_os/harness/shared_factory/05-knowledge/skill-registry.yml
OS_SKILL_INSTALL_MODE=copy
OS_SKILL_UPDATE_POLICY=additive_non_destructive
OS_SKILL_HARNESS_TARGETS=codex,claude
OS_BUILTIN_SKILLS=build-runner,automation-qualifier,context-pack-builder,domain-setup,learning-promoter,os-doctor,os-navigator,room-builder,run-logger,workflow-builder
```

### `OS_SHARED_SKILLS_SOURCE_DIR`

Default: `./harness/skills/`

Controls where canonical shared skills live in this source package.

Valid options:

- Relative path inside the source repository.
- Absolute path only when explicitly requested.

Notes:

- This is product source, not the live installed OS.
- `build-runner` lives at `harness/skills/build-runner/`.
- Skills in this directory can be shipped into installed OS roots and synced to
  harness runtime skill folders.

### `OS_SHARED_SKILLS_REGISTRY`

Default: `./harness/skills/skill-registry.yml`

Controls the source registry that lists built-in shared skills, target harnesses,
install paths, and update policy.

Valid options:

- YAML file path.

Notes:

- The registry should validate against `schemas/skill-registry.schema.json`.
- Add new built-in skills to the registry before expecting installers or sync
  commands to ship them.

### `OS_SHARED_SKILLS_INSTALLED_DIR`

Default: `~/agentic_os/harness/shared_factory/05-knowledge/skills/`

Controls where shared skills are installed inside a live Agentic OS root.

Valid options:

- Path under the installed OS root.
- Alternate OS root path when explicitly selected by the user.

Notes:

- Installed skills are runtime copies.
- The source repo remains canonical.

### `OS_SHARED_SKILLS_INSTALLED_REGISTRY`

Default: `~/agentic_os/harness/shared_factory/05-knowledge/skill-registry.yml`

Controls where the installed OS keeps its runtime copy of the shared skill
registry.

Valid options:

- YAML file path under the installed OS root.

Notes:

- Agents should read this registry when operating from `~/agentic_os`.

### `OS_SKILL_INSTALL_MODE`

Default: `copy`

Controls how source skills are placed into installed OS and harness runtime
directories.

Valid options:

- `copy`
- `symlink`
- `manual`

Notes:

- Use `copy` by default so installed OS versions are stable snapshots.
- Use `symlink` only for active local development.
- Use `manual` when a harness needs special packaging.

### `OS_SKILL_UPDATE_POLICY`

Default: `additive_non_destructive`

Controls how shared skill updates are applied to an installed OS.

Valid options:

- `additive_non_destructive`
- `overwrite_managed`
- `manual_review`

Notes:

- Default to additive, non-destructive updates.
- Do not overwrite user-modified runtime skills without an explicit migration
  plan.

### `OS_SKILL_HARNESS_TARGETS`

Default: `codex,claude`

Controls which local harnesses receive runtime skill copies.

Valid options:

- Comma-separated harness IDs.

Notes:

- Default shared skills target Codex and Claude.
- Do not mutate Cursor surfaces unless the user explicitly confirms Cursor.

### `OS_BUILTIN_SKILLS`

Default:

```text
build-runner,automation-qualifier,context-pack-builder,domain-setup,learning-promoter,os-doctor,os-navigator,room-builder,run-logger,workflow-builder
```

Controls which skills are treated as built-in OS skills.

Valid options:

- Comma-separated skill IDs present in `OS_SHARED_SKILLS_REGISTRY`.

Notes:

- `build-runner` is both a bootstrap skill for finishing this source package and
  a built-in skill for future installed OS versions.
- Built-in skills should remain generic enough to ship across OS instances.

## Core Paths

```env
BUILD_RUNNER_FEATURE_DIR=<os-root>/<work-domain>/02-projects/genomes_agentic_os/worklogs/source-features/
BUILD_RUNNER_PLAN_DIR=<os-root>/<work-domain>/02-projects/genomes_agentic_os/work-items/01-intake/
BUILD_RUNNER_LOG_DIR=<os-root>/<work-domain>/02-projects/genomes_agentic_os/worklogs/source-build-logs/
BUILD_RUNNER_RUN_STATE=./RUN_STATE.json
BUILD_RUNNER_WORKTREE_ROOT=../.worktrees/
BUILD_RUNNER_TARGET_BRANCH=auto
BUILD_RUNNER_BRANCH_PREFIX=codex/
```

### `BUILD_RUNNER_FEATURE_DIR`

Default for this source package: installed OS `worklogs/source-features/`

Controls where build-runner stores human-readable work history for source
package cards.

Valid options:

- Installed OS project path, such as
  `<os-root>/<work-domain>/02-projects/genomes_agentic_os/worklogs/source-features/`.
- Relative path inside the repository only for legacy compatibility.
- Relative hidden path, such as `./.features/`.
- Absolute path, only when the user explicitly wants artifacts outside the
  repository.

Notes:

- Do not create source-root `features/` for this repository. Use the installed
  OS project `worklogs/source-features/<prefix-slug>/` bucket.
- If a host project already uses `features/` for tests, prefer `.features/`.
- Each feature folder contains `SPEC.md`, `INVESTIGATION.md`, `PLAN.md`,
  `MEMORY.md`, `WORKLOG.md`, `SUMMARY.md`, `NEXT.md`, `HOLDOUT_QA.md`,
  `HOLDOUT_QA_RESULTS.md`, `JUDGMENT.md`, and `feature.yml`.
- `BUILDER_RUNNER_FEATURE_DIR` may be treated as an alias if present in older
  prompts or environment files.

### `BUILD_RUNNER_PLAN_DIR`

Default for this source package: installed OS project `work-items/01-intake/`

Controls where specs and generated prerequisite task files live.

Valid options:

- Installed OS project path, such as
  `<os-root>/<work-domain>/02-projects/genomes_agentic_os/work-items/01-intake/`.
- Relative repository path only for legacy compatibility.
- Absolute path only when explicitly requested.

Notes:

- Existing source plan files were consolidated into the installed OS project
  lifecycle on 2026-06-15 and later normalized into `work-items/`.
- Generated subtasks should use:

```text
<parent-prefix>-<subtask-number>-<parent-slug>-<sub-name>.md
```

Example:

```text
00-00-current-state-and-gap-map-add-run-state.md
```

### `BUILD_RUNNER_LOG_DIR`

Default for this source package: installed OS `worklogs/source-build-logs/`

Controls where completed source-package work summaries are appended.

Valid options:

- Installed OS project path, such as
  `<os-root>/<work-domain>/02-projects/genomes_agentic_os/worklogs/source-build-logs/`.
- Relative repository path only for legacy compatibility.
- Absolute path only when explicitly requested.

Notes:

- Shared log appends are orchestrator-owned.
- Subagents should not write directly to files in this directory.
- Each append starts with:

```markdown
# FEATURE-<feature-slug>
```

### `BUILD_RUNNER_RUN_STATE`

Default: `./RUN_STATE.json`

Controls the resumable queue ledger for a build-runner execution.

Valid options:

- JSON file path.

Notes:

- Tracks board source, queue, ordering rule, feature statuses, active feature,
  generated subtasks, board writebacks, branch names, and merge commits.
- Must be checked before processing a card to avoid duplicated work.

### `BUILD_RUNNER_WORKTREE_ROOT`

Default: `../.worktrees/`

Controls where git worktrees are created.

Valid options:

- Relative path outside the active repository.
- Absolute path.

Notes:

- Prefer a path outside the repository so generated worktrees do not appear as
  nested project content.
- Worktree names should include the feature prefix and slug.

### `BUILD_RUNNER_TARGET_BRANCH`

Default: `auto`

Controls the branch that completed work is merged into.

Valid options:

- `auto`, meaning detect the repository default branch.
- Explicit branch name such as `main`, `master`, `develop`, or `trunk`.

Notes:

- Fetch the target branch before creating feature worktrees.
- Do not merge over unrelated dirty work.

### `BUILD_RUNNER_BRANCH_PREFIX`

Default: `codex/`

Controls the branch name prefix for generated feature branches.

Valid options:

- Any git-safe branch prefix ending in `/`.
- Empty string only when the user explicitly requests no prefix.

Notes:

- This repository should default to `codex/<feature-slug>`.

## Build Runner Behavior

```env
BUILD_RUNNER_QUEUE=Ready
BUILD_RUNNER_ORDER=title-prefix-ascending
BUILD_RUNNER_REQUIRE_ACCEPTANCE_CRITERIA=true
BUILD_RUNNER_MAX_CONCURRENT_SUBAGENTS=2
BUILD_RUNNER_MERGE_STRATEGY=no-ff
BUILD_RUNNER_HOLDOUT_QA_REQUIRED=true
BUILD_RUNNER_FAILED_CARD_POLICY=block-and-continue
```

### `BUILD_RUNNER_QUEUE`

Default: `Ready`

Controls which Kanban lane is eligible for execution.

Valid options:

- Any configured board status.

Notes:

- For the current Agentic OS Kanban, all 18 plan cards are currently in
  `Ready`.

### `BUILD_RUNNER_ORDER`

Default: `title-prefix-ascending`

Controls the card execution order.

Valid options:

- `title-prefix-ascending`
- `board-order`
- `priority-then-prefix`
- `manual`

Notes:

- `title-prefix-ascending` parses leading prefixes such as `00`, `01`, `ex00`,
  and `ex01`.
- If board order conflicts with the title prefix and the user requested prefix
  order, prefix order wins.

### `BUILD_RUNNER_REQUIRE_ACCEPTANCE_CRITERIA`

Default: `true`

Controls whether the runner may start a card without clear acceptance criteria.

Valid options:

- `true`
- `false`

Notes:

- Default behavior is to stop and ask when done cannot be determined.

### `BUILD_RUNNER_MAX_CONCURRENT_SUBAGENTS`

Default: `2`

Controls how many implementation or QA subagents may run in parallel for one
feature.

Valid options:

- Positive integer.

Notes:

- Raise only when file ownership is clear and verification is independent.
- The orchestrator must still review every return before merge.

### `BUILD_RUNNER_MERGE_STRATEGY`

Default: `no-ff`

Controls how feature branches merge back to the target branch.

Valid options:

- `no-ff`
- `squash`
- `ff-only`

Notes:

- Use `no-ff` by default so a feature merge can be reverted cleanly.
- Never use `--no-verify`.

### `BUILD_RUNNER_HOLDOUT_QA_REQUIRED`

Default: `true`

Controls whether a fresh holdout QA phase is required before merge.

Valid options:

- `true`
- `false`

Notes:

- Default behavior is to write `HOLDOUT_QA.md`, run the plan, and record
  results in `HOLDOUT_QA_RESULTS.md`.

### `BUILD_RUNNER_FAILED_CARD_POLICY`

Default: `block-and-continue`

Controls what happens when a card cannot be completed.

Valid options:

- `block-and-continue`
- `block-and-stop`
- `ask`

Notes:

- Use `block-and-continue` only when the next card is independent.
- Use `block-and-stop` when cards are sequential dependencies.

## Notion Kanban

```env
NOTION_KANBAN_WORKSPACE=Genome's Notion
NOTION_KANBAN_DATABASE_TITLE=Agentic OS Kanban
NOTION_KANBAN_DATABASE_ID=366683b4-8dab-81a1-ab5f-c73e7e1f5c60
NOTION_KANBAN_VIEW_ID=366683b4-8dab-818f-b4e5-000cdb1f8478
NOTION_KANBAN_TITLE_PROPERTY=Name
NOTION_KANBAN_STATUS_PROPERTY=Status
NOTION_KANBAN_GROUP_BY=Status
NOTION_KANBAN_READY_STATUS=Ready
NOTION_KANBAN_DONE_STATUS=Done
NOTION_KANBAN_BLOCKED_STATUS=Blocked
NOTION_KANBAN_WRITEBACK_MODE=properties-and-comment
```

### Workspace

Default: `Genome's Notion`

Controls where Notion reads and writes are allowed.

Valid options:

- `Genome's Notion`
- A specifically named alternate workspace from the active user instruction.

Notes:

- The Notion connector is preferred when authenticated.
- If the connector is unavailable or unauthorized, direct API access may be used
  with `GENOMES_NOTION_PAT` or `GENOMES_NOTION_CONNECTOR`.
- Never print token values.
- Do not write to Michael Clark's personal Notion.
- Do not create fallback pages in another workspace.

### Database

Default title: `Agentic OS Kanban`

Default database ID: `366683b4-8dab-81a1-ab5f-c73e7e1f5c60`

Default view ID: `366683b4-8dab-818f-b4e5-000cdb1f8478`

Controls which Notion database is the human control plane for build-runner work.

Valid options:

- A Notion database ID or URL.
- A Notion board view ID or URL when a specific view matters.

Notes:

- The current database has 18 cards, all currently in `Ready`.
- Existing local `PLANS/` content was migrated into the installed OS project
  lifecycle on 2026-06-15 and later normalized into `work-items/`.

### Lanes And Statuses

Configured status property: `Status`

Current status options:

- `Inbox`
- `Ready`
- `Building`
- `Validating`
- `Blocked`
- `Done`
- `In Progress`

Recommended workflow direction:

```text
Inbox -> Ready -> Building -> Validating -> Done
                \-> Blocked -> Ready
```

Notes:

- `Inbox` is for raw ideas or unshaped work.
- `Ready` is eligible for build-runner execution.
- `Building` means implementation is active.
- `Validating` means holdout QA or review is active.
- `Blocked` means the runner cannot proceed without new information or access.
- `Done` means merged, verified, logged, and synced.
- `In Progress` exists on the board but should be treated as legacy or
  compatibility status unless the user explicitly chooses it.

### Properties

Current derived properties:

| Property | Type | Controls |
| --- | --- | --- |
| `Name` | title | Card title and sortable prefix. |
| `Status` | select | Kanban lane and workflow state. |
| `Priority` | select | Optional ordering or triage. Valid values: `P0`, `P1`, `P2`. |
| `Related Integration` | multi_select | Integration tags. |
| `Next Action` | rich_text | Human-readable next step. |
| `Notion Tracker URL` | url | Link to detailed tracker page when one exists. |
| `Blocker` | rich_text | Reason a card cannot proceed. |
| `Owner` | rich_text | Person or agent responsible. |
| `Plan File` | rich_text | Installed OS `work-items/*/*/SPEC.md` path. |
| `Canonical Source` | checkbox | Marks whether this card maps to canonical local source. |
| `Installed Runtime Path` | rich_text | Installed OS path affected by the card. |
| `Source Path` | rich_text | Source repo path affected by the card. |
| `Last Touched` | date | Last meaningful update date. |

Valid `Related Integration` values:

- `Notion`
- `Orgo.io`
- `Composio`
- `AgentMail`
- `Granola`
- `Heartbeats`
- `Customer OS`
- `LOS/losmon`
- `Slack`
- `Jira`
- `Linear`
- `Email`
- `GitHub`

### Ready Queue

Current derived Ready queue in execution order:

1. `00 Current State And Gap Map`
2. `01 Project Create And Active Work`
3. `02 Routing And Context Builder`
4. `03 Workflow Readiness And Run Closeout`
5. `04 Automation Maturity And Reconfiguration`
6. `05 Customer Os Factory`
7. `06 Notion Control Plane Sync`
8. `07 Doctor Validation And Migrations`
9. `08 Losmon Replacement Validation`
10. `09 Future Ideas Intake`
11. `10 Notion Control Plane Bootstrap`
12. `11 Room First Installer And Routing`
13. `12 Factory Template Import Backlog`
14. `13 Reference And Skill Index Layer`
15. `14 Client Automation And Control Plane Playbooks`
16. `15 Always On Runtime Heartbeats Schedules And Integrations`
17. `16 Connected Source Watch Registry`
18. `17 Event Graph And Chained Automations`

### Board Writeback

Default: `properties-and-comment`

Controls how agents update Notion after work starts or completes.

Valid options:

- `properties-only`
- `comment-only`
- `properties-and-comment`
- `none`

Notes:

- Use properties for current machine-readable state.
- Use comments or card body notes for human-readable progress, branch, commit,
  verification, blockers, and follow-ups.
- Board writes must be idempotent and include stable card IDs or feature slugs.

## Notion Writeback Template

```markdown
## Build Runner Update

Status: <state>
Feature: <feature-slug>
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
- worklogs/source-features/<feature-slug>/
- worklogs/source-build-logs/*.md
```

## Stop Conditions

Agents should stop and ask when:

- Notion access cannot be verified.
- The visible Notion workspace is not Genome's Notion.
- A card lacks acceptance criteria.
- A card would require destructive or irreversible changes.
- Existing dirty changes overlap files needed by the current card.
- The target branch is ambiguous.
- Baseline verification is too broken to judge regressions.
- A generated prerequisite changes the requested queue materially.

## Defaults For Shipped OS

The installed OS should ship this config shape with sane defaults even when no
Notion board has been connected yet.

For fresh installs:

```env
BUILD_RUNNER_FEATURE_DIR=./worklogs/source-features/
BUILD_RUNNER_PLAN_DIR=./work-items/01-intake/
BUILD_RUNNER_LOG_DIR=./worklogs/source-build-logs/
BUILD_RUNNER_RUN_STATE=./RUN_STATE.json
BUILD_RUNNER_WORKTREE_ROOT=../.worktrees/
BUILD_RUNNER_TARGET_BRANCH=auto
BUILD_RUNNER_BRANCH_PREFIX=codex/
BUILD_RUNNER_QUEUE=Ready
BUILD_RUNNER_ORDER=title-prefix-ascending
BUILD_RUNNER_REQUIRE_ACCEPTANCE_CRITERIA=true
BUILD_RUNNER_MAX_CONCURRENT_SUBAGENTS=2
BUILD_RUNNER_MERGE_STRATEGY=no-ff
BUILD_RUNNER_HOLDOUT_QA_REQUIRED=true
BUILD_RUNNER_FAILED_CARD_POLICY=block-and-continue
OS_SHARED_SKILLS_SOURCE_DIR=./harness/skills/
OS_SHARED_SKILLS_REGISTRY=./harness/skills/skill-registry.yml
OS_SHARED_SKILLS_INSTALLED_DIR=~/agentic_os/harness/shared_factory/05-knowledge/skills/
OS_SHARED_SKILLS_INSTALLED_REGISTRY=~/agentic_os/harness/shared_factory/05-knowledge/skill-registry.yml
OS_SKILL_INSTALL_MODE=copy
OS_SKILL_UPDATE_POLICY=additive_non_destructive
OS_SKILL_HARNESS_TARGETS=codex,claude
OS_BUILTIN_SKILLS=build-runner,automation-qualifier,context-pack-builder,domain-setup,learning-promoter,os-doctor,os-navigator,room-builder,run-logger,workflow-builder
NOTION_KANBAN_WORKSPACE=Genome's Notion
NOTION_KANBAN_TITLE_PROPERTY=Name
NOTION_KANBAN_STATUS_PROPERTY=Status
NOTION_KANBAN_GROUP_BY=Status
NOTION_KANBAN_READY_STATUS=Ready
NOTION_KANBAN_DONE_STATUS=Done
NOTION_KANBAN_BLOCKED_STATUS=Blocked
NOTION_KANBAN_WRITEBACK_MODE=properties-and-comment
```
