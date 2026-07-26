---
name: auto-dev-finalize
description: Drive every open gitflow PR for one tracker ticket to merged or explicitly blocked. Per-PR subagent assessment, Copilot fix-and-resolve rounds, CI green, branch-correct migrations, tracker acceptance fit, deep quality review, bounded convergence loops, a family merge gate, and tracker closeout. Manual kickoff only. Use when the user asks for Agentic OS `auto-dev-finalize` work, says "finalize <TICKET>", "review and finalize the PRs", "drive the PR family to merge", "babysit these PRs to done", or when auto-dev hands off a multi-target PR set at pr_open.
---

# Auto Dev Finalize

Auto Dev Finalize is the Review + Finalize stage of the SDLC. It takes one
tracker ticket, discovers the ticket's ENTIRE open PR family across gitflow
targets (develop, active release, hotfix), and drives every PR in the family to
`merged` or an explicit receipt-backed `blocked` state. It is the canonical
endgame owner for "N PRs, one ticket": Copilot threads fixed AND resolved,
checks green, migrations correct for each target branch, tracker acceptance
criteria demonstrably met, and a deep quality review passed, looped
continuously because every push re-triggers Copilot and CI.

Manual kickoff only. This workflow must not be scheduled, cron-launched, or
chained from an automation until the operator explicitly promotes it.

This skill is self-contained. Describe the behavior first; name a tool only as
the mechanism; depend on nothing that may be absent. Project-specific behavior
comes from the routed project layer (`project.yml` `dev_factory`), never from
hardcoded defaults.

## Canonical Spec Boundary

This skill is the canonical policy source for ticket-level PR-family
finalization. Sibling capabilities are building blocks, not competitors:

| Capability | Role here |
| --- | --- |
| `auto-dev` | Upstream SDLC runner (ticket -> implementation -> PR). Its post-PR loop handles a single PR; when a ticket has multiple gitflow targets, it hands the family endgame to this skill at `pr_open`. |
| `quiet-workon-orchestrate` | Implementation engine. Fix waves dispatched by this skill follow its subagent, receipt, and chat contracts. |
| `watch-pr-quiet` | Per-PR CI watch primitive (file-based, quiet). |
| `finishing-touches-review` | Deep-review engine reusable for the quality gate when configured. |
| `pull-request` skill + `pull-request-*` reviewer agents | Review battery consumed by the quality gate. Review-only; they do not own fixing, resolving, or merging. |
| Repo-local `copilot-fix` / `copilot-hell` | Preferred per-PR Copilot triage/fix/reply/resolve mechanism when the repo ships them. |
| `os-cleaner` / `os_cleanup` workflow | Post-merge worktree and work-item reconciliation. |

Any change to family discovery, gate definitions, loop bounds, merge policy
handling, or closeout lands here first and is then reflected into adapters.

## Hard Rules

- Manual kickoff only. No cron, no queue trigger, no automation chaining.
- Load the routed project layer before acting. `project.yml` `dev_factory`
  (tracker, repo, validation, copilot, merge, pull_request.target_policy) is
  the data authority. Resolve `pull_request.target_policy` only through
  `harness/shared_factory/05-knowledge/gitflow-topology/CONTRACT.md` and its
  deterministic resolver. Missing required config or unresolved branch aliases
  block the run.
- Merge intent is resolved explicitly at kickoff, never left implicit. The
  resolution order is: operator flag (`--merge-authorized` / `--no-merge`),
  then the project's finalize merge policy
  (`dev_factory.merge.finalize.policy`, falling back to
  `dev_factory.merge.policy`), then one direct operator question at
  family-ready. A standing `auto_when_green` policy set by the operator IS
  merge authorization; `never_auto` means hold at `ready_for_merge` and
  watch for external merges. Record the resolved intent in
  `finalize-state.json` at Phase 0.
- Never resolve a human reviewer's thread. Reply with team-visible context and
  leave resolution to the human. Copilot/bot threads may be resolved by the
  run, but only after a fix was pushed or a clear false-positive reply was
  posted.
- Every tracker/GitHub writeback is scrubbed first: no local filesystem paths,
  no Agentic OS skill/workflow/automation names, no Notion links, no em dashes
  in copy-paste prose. Use the auto-dev scrubber when available.
- Git safety: no `--no-verify`, no force-push, no destructive git, no
  `git config user.*` mutations (linked worktrees share `.git/config`). Push
  with `git push origin HEAD:<branch>` after a fresh fetch. Verify outgoing
  author/committer identity before every push.
- Bounded loops. Per-PR convergence rounds are capped (default 5, or the
  project `copilot.max_rounds_without_progress` for no-progress detection).
  Hitting a cap produces a `blocked_loop_limit` receipt, never silent retry.
- Concurrent-driver guard: before each wave, snapshot per-PR head SHAs. If a
  head advances from outside this run, pause that PR lane, re-assess, and
  record who/what is driving before continuing. Never fight another driver.
- Quiet chat contract: inherit the `quiet-workon-orchestrate` output model.
  Receipts live under the work item `artifacts/finalize/`; chat gets
  decision-grade milestones only. No polling, no dumps, no heartbeats.
- Read-only inspection is pre-authorized. Mutations follow the routed approval
  gates: pushes to existing ticket branches and thread replies/resolutions are
  in-scope for the run; merges, tracker transitions, and anything
  customer-visible follow the merge gate and tracker contract below.

## Kickoff Contract

Inputs, resolved on the main thread before any subagent spawns:

- `ticket` (required): tracker key, e.g. `FLYWL-2496`.
- `--prs <n,n,n>` (optional): explicit PR list override for family discovery.
- `--merge-authorized` / `--no-merge` (optional): per-run override of the
  project's finalize merge policy. When neither is passed, the project
  policy decides; when no policy resolves either, ask the operator one
  direct question at family-ready instead of silently holding.
- `--max-rounds <n>` (optional, default 5): per-PR convergence cap.
- `--rounds-only <n>` (optional): run n assessment/fix waves then report,
  without entering the long watch loop.

Kickoff resolves: routed domain/project, `project.yml` `dev_factory`, the
tracker item (status, acceptance criteria), the branch registry (active
release, next hotfix), and the canonical work item (create or reuse; exactly
one canonical packet per ticket).

## State And Receipts

All run state lives under the canonical work item:

```text
<work-item>/artifacts/finalize/
  finalize-state.json          # family manifest + per-PR gate matrix + rounds
  family-manifest.md           # PR list, bases, heads, discovered how
  round-<n>/
    assessment-pr-<num>.md     # per-PR assessment agent return
    fixes-pr-<num>.md          # fix wave receipts (commands, commits, pushes)
  copilot/
    threads-pr-<num>.json      # raw thread snapshot per round
    receipt-pr-<num>-round-<n>.json   # copilot_loop.py classification output
  pr-watch/                    # watch-pr-quiet artifacts per PR
  migration-audit-pr-<num>.md
  ac-map.md                    # tracker AC -> file:line + test evidence
  quality-review/              # battery outputs per reviewer lane
  merge/merge-decision.json    # gate matrix at decision time + authorization
  closeout.md
```

`finalize-state.json` tracks, per PR: `head_sha`, `rounds`, and the gate
matrix: `ci_green`, `copilot_clean`, `human_threads_addressed`,
`migrations_ok`, `ac_satisfied`, `quality_review_pass`, `approvals_met`,
`mergeable`. The family is ready only when EVERY family PR passes
(`pull_request.target_policy.ready_for_merge_requires_all_targets`).

Every receipt carries a timestamp. Append-only files are never rewritten. A
stale receipt does not satisfy a new outcome claim (a new push invalidates
`ci_green`, `copilot_clean`, and `mergeable` until re-proven).

## Phase 0: Discover And Baseline

1. Resolve the PR family. Search open PRs by ticket key in title and head
   branch (`gh pr list --search "<KEY>" --state open --json
   number,title,baseRefName,headRefName,url`). Keep only PRs whose title or
   head branch carries the exact ticket key. Pass the tracker snapshot,
   project profile, branch registry, and exact open-PR base branches to the F2
   resolver. Store its JSON verdict in `artifacts/finalize/topology.json`.
   Record each `missing_required_target` blocker as `fix_required`: open the
   missing propagation PR through GitFlow PR Create or record the operator
   decision not to.
2. Create or reuse the canonical work item (`agentic-os project work-item
   create <domain> <project> --root <os-root> --status building --format
   packet --title "<KEY>: <title>" --summary "<one line>"`). If stray or
   duplicate packets exist for the ticket, consolidate into the canonical one
   and record the merge in `WORKLOG.md`.
3. Snapshot the tracker item (status, AC, labels) and the per-PR baseline:
   head SHA, check rollup, unresolved thread count, review decision.
4. Concurrent-driver check: compare current heads against the last known
   receipts; look for recent pushes not made by this operator. If another
   automation is driving the PRs, stop and surface it.

## Phase 1: Per-PR Assessment Fan-Out

Spawn one read-only assessment subagent per family PR, all in parallel. Each
prompt is self-contained (why, scope, exact PR number/branch, off-limits
paths, return contract). Each agent returns a structured assessment:

- Checks: failing/pending check names with root-cause class (code vs
  infrastructure) from the failed job logs.
- Threads: every unresolved review thread with id, author, path:line, and a
  classification per the copilot-loop taxonomy (`fix_required`,
  `reply_and_resolve`, `blocked_product_decision`, `needs_triage`), human vs
  bot flagged.
- Migration audit (see recipe below): pass/fail per added migration with the
  exact remedy when failing.
- AC map: every tracker acceptance criterion -> file:line + test evidence in
  THIS PR's diff, or `MISSING`.
- Quality findings: severity-tagged findings against DEV_STANDARDS
  (see DEV_STANDARDS phase) scoped to the PR diff.
- Cherry-pick parity (non-develop PRs): file list and hunk-level comparison
  against the develop PR; expected divergences (migration renumbering,
  conflict adaptations) vs unexpected drift.

Thread snapshot mechanism:

```bash
gh api graphql -f query='query($o:String!,$r:String!,$n:Int!){repository(owner:$o,name:$r){pullRequest(number:$n){reviewThreads(first:100){nodes{id isResolved isOutdated path line comments(first:10){nodes{author{login} body createdAt}}}}}}}' \
  -f o=<owner> -f r=<repo> -F n=<pr> > threads-pr-<num>.json
```

Classify with the existing engine (do not reimplement):

```bash
python3 harness/skills/auto-dev/scripts/copilot_loop.py --input <threads.json> --output <receipt.json>
```

## Phase 2: Consolidate And Plan (Main Thread)

The orchestrator, never a subagent, owns this step:

- Dedupe findings across the family. The same finding on N branches is ONE
  decision with N applications.
- Decide the fix topology from the saved F2 verdict: fix on the primary PR
  first, then follow its `propagation` method for the remaining targets.
  Branch-specific findings (migrations, conflict adaptations) are fixed
  per-branch.
- Contention check: two agents never touch the same file in parallel. Same
  fix across branches is sequential propagation, not parallel invention.
- Classify every finding: `fix_required` -> fix wave; `reply_and_resolve` ->
  reply wave; `blocked_product_decision` -> surface to operator with the
  exact question; style-level nits -> fix when trivial, otherwise log with
  rationale.
- Record the plan in `round-<n>/` before dispatching.

## Phase 3: Fix Wave (Per-PR Worktrees)

- One worktree per PR head branch via the project worktree tooling, fetched
  fresh (`git fetch origin` first; base the worktree on `origin/<head>`).
- Apply the planned fixes. Follow write-side DEV_STANDARDS: resolve the
  ordered folder list from `dev_factory.dev_standards.paths`, falling back to
  `dev_factory.quality_gates.paths` during migration (default:
  `harness/shared_factory/05-knowledge/dev_standards`, the routed domain's
  `05-knowledge/dev_standards`, then the project's `config/dev_standards`),
  enumerate every `*.md` except `README.md` in
  each, later folders sharpening earlier ones (composable contract; new
  markdowns apply automatically) so fixes do not create the next round's
  findings.
- Validate: targeted tests for touched paths (project `validation.commands`),
  changed-file pre-commit. When local validation is blocked by environment,
  record the exact blocker and rely on PR CI per project policy
  (`allow_ci_fallback_when_local_blocked`).
- Commit `<KEY>: <subject>` (repo convention, no AI attribution, no
  `Co-Authored-By`), verify identity, push `HEAD:<branch>`.
- Thread hygiene, per thread: after the fix is pushed, reply with short
  team-visible context (what changed, where; vary phrasing, no stock openers)
  and resolve bot threads. False positives get a factual reply then resolve.
  Human threads get the reply only.

```bash
# reply
gh api graphql -f query='mutation($t:ID!,$b:String!){addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$t,body:$b}){comment{id}}}' -f t=<thread-id> -f b="<scrubbed reply>"
# resolve (bot threads only)
gh api graphql -f query='mutation($t:ID!){resolveReviewThread(input:{threadId:$t}){thread{isResolved}}}' -f t=<thread-id>
```

Prefer the repo-local `copilot-fix` (single round) / `copilot-hell` (repeated
rounds) skills when the repo ships them; the commands above are the fallback
mechanism.

## Phase 4: Watch And Re-Assess (The Continual Loop)

Every push re-arms the loop. This is by design: each push re-triggers CI and
Copilot, which can find new issues, on every branch.

- Start `watch-pr-quiet` per pushed PR into `artifacts/finalize/pr-watch/`,
  in the background. Never poll in chat.
- If Copilot does not auto-re-review on push, re-request it:

```bash
gh api -X POST repos/<owner>/<repo>/pulls/<n>/requested_reviewers -f 'reviewers[]=<copilot reviewer login>'
```

- On watcher terminal state per PR:
  - `success`: mark `ci_green`, take a fresh thread snapshot. New actionable
    threads -> increment the PR round counter and go to Phase 2. No new
    threads inside the project `copilot.clean_window_minutes` after the
    Copilot re-review completes -> mark `copilot_clean`.
  - `failure`: classify from the failed job logs. Infrastructure (no test
    failure, no code traceback) -> rerun once with a receipt; a repeat of the
    same infrastructure class blocks with the log receipt. Code failure ->
    Phase 2 with the narrowest fix.
  - `timeout`/`error`: inspect the summary artifact, restart the watcher with
    an adjusted window, and record it.
- Round accounting is per PR. `rounds >= max` with open actionable findings
  -> `blocked_loop_limit` receipt and operator surface. Two consecutive
  rounds with no progress -> same.

The run stays alive until every family PR is merged, explicitly blocked, or
the operator ends the run. Waiting states are quiet: watchers in the
background, scheduled check-ins, zero chat noise between milestones.

## Phase 5: Quality Gate (Deep Review)

Entered per PR once `ci_green` AND `copilot_clean` hold. This is a real
review, not a checkbox:

- Battery: run the deep review against the develop PR diff as primary, with a
  parity audit on each cherry-pick PR. Use, in order of availability: the
  confirmed `pull-request-*` reviewer agents (security, django, database,
  testing, acceptance, architecture at minimum), the
  `finishing-touches-review` engine when the project configures it, or a
  structured self-review against the composable DEV_STANDARDS folders
  (`harness/shared_factory/05-knowledge/dev_standards/*.md`, the routed
  domain folder, and the routed project's `config/dev_standards/*.md`, all
  excluding `README.md`), citing the standard filename in each finding.
- Score findings by DEV_STANDARDS. Blocking classes: correctness, security,
  tenant isolation, data/migration risk, ORM/performance (N+1, missing
  select_related, leaks), missing/false tests, unmet AC. Non-blocking style
  findings are fixed when trivial or logged with rationale.
- Blocking findings feed Phase 2 as `fix_required` (they count against the
  same round caps).
- `ac_satisfied` is verified against the QA-gates plane: resolve
  `dev_factory.qa_gates.paths` (default:
  `harness/shared_factory/05-knowledge/qa-gates` then the project's
  `config/qa-gates`) and apply every gate (acceptance evidence, regression
  focus, environment/tenant matrix, evidence capture); human-QA items land
  in the packet's HOLDOUT_QA.md for handoff.
- Gate outputs: `quality_review_pass`, `ac_satisfied` (every AC maps to
  code + test evidence in under a minute of tracing), `migrations_ok`.

### Migration Audit Recipe (Django projects)

Per PR, in a fetched worktree:

```bash
git fetch origin <base>
git diff --name-status --diff-filter=AR origin/<base>...HEAD -- '*/migrations/*.py'
```

For each added migration: parse its `dependencies`; every referenced
`(app, migration)` must exist on `origin/<base>` (`git ls-tree
origin/<base> -- <app>/migrations/`) or earlier in this PR. The dependency
must point at the target branch's CURRENT leaf for that app, not the source
branch's. Numbering must not collide with any migration already on the
target branch. Cherry-picked migrations keep their filename; only the
dependency line is repointed to the target leaf. Never renumber an already
pushed migration; never leave a develop-only parent in a release/hotfix PR
(that is the `NodeNotFoundError`-in-every-shard failure). When the project
runtime is available, `makemigrations --check` and a `showmigrations`
smoke on the worktree stack are the dynamic confirmation; the static graph
check is mandatory either way.

## Phase 6: Family Merge Gate

- A PR is merge-eligible when its full gate row is green AND
  `approvals_met` (project `merge.required_approvals`; a Copilot review is
  not an approval) AND GitHub reports it mergeable.
- The FAMILY is ready only when every PR is merge-eligible
  (`ready_for_merge_requires_all_targets: true`).
- At family-ready: transition the tracker to its `ready_for_merge` state and
  post one scrubbed tracker comment summarizing the family (PR links in
  team-visible form, gate status, verification receipts summary).
- Merge execution follows the resolved merge intent:
  - `auto_when_green`: once EVERY family PR passes its full gate row, the
    run merges the family itself with the project method, in the configured
    merge order (default: develop, then active release, then hotfix). When
    the project declares `approvals_satisfied_by: operator_bypass`, the
    approvals gate is satisfied by the operator's standing authority and
    the merge uses the provider's admin/bypass path (GitHub:
    `gh pr merge <n> --admin --squash`). Read back each merge state and
    SHA before proceeding to the next PR. Copilot is never an approval.
  - `never_auto`: hold at `ready_for_merge`, keep a light watch for
    external merge events, and run closeout per PR as merges land.
  - Unresolved intent: ask the operator one direct question at
    family-ready, then act on the answer.
  Record `merge/merge-decision.json` (resolved intent, gate matrix, and
  which path satisfied approvals) in every case.
- When holding with only human review missing, say so once (the tracker
  comment covers it), keep watching quietly, and do not ping repeatedly.

## Phase 7: Closeout

On each merged PR, and at family completion:

- Tracker: when ALL family PRs are merged, run the project's post-merge
  tracker routing workflow when one exists (it owns the terminal status
  decision and its guards) and post the final scrubbed comment (what
  shipped, family PR links, verification summary). Only fall back to the
  plain `project.yml` `merged` state transition when no post-merge routing
  workflow is configured. Partial merges get a WORKLOG note, not a premature
  transition. When the tracker is hybrid (Jira + Linear mirror), update the
  configured mirror without cross-referencing it in company surfaces.
- Work item: append the closeout to `WORKLOG.md`, write
  `artifacts/finalize/closeout.md`, set the lifecycle state per project
  policy (`validating` when QA remains, `finished` when terminal), and let
  `os-cleaner` / the `os_cleanup` workflow own worktree teardown (respect
  `REOPEN.md`).
- Registries: append the run to the domain run log, refresh or note the
  release-membership registry when release/hotfix branches changed (merged
  cherry-picks change release membership), and update any configured
  operator dashboards or projections. If a configured projection cannot be
  written, record the blocker locally; never leave it silently stale.
- Memory: write durable learnings (surprises, environment quirks, decisions)
  to the unified memory plane.
- Final chat handoff: one milestone with per-PR outcomes and receipt paths.

## Orchestration Model

- The main thread is the orchestrator: family discovery, consolidation,
  decisions, gates, merges, tracker writes. It never delegates judgment.
- Per-PR lanes run in parallel through subagents: assessment (read-only),
  fixes (worktree-scoped), watches (file-based). All N PRs are worked at
  once; the orchestrator serializes only where files or fixes overlap.
- Subagent prompts follow the `quiet-workon-orchestrate` contract: why,
  scope, exact paths/PR numbers, decisions already made, verification
  commands, return contract, no-delegation clause. Returns are drafts;
  the orchestrator verifies against the live PR before accepting.
- Kill criteria: scope drift, two blind retry failures, base invalidated by
  another lane, or budget exceeded. Kill, re-plan on the main thread,
  re-dispatch narrower.

## Failure And Stop States

- `blocked_product_decision`: a finding needs an operator/product call.
  Surface the exact question with options; pause that PR lane only.
- `blocked_loop_limit`: round cap or no-progress cap hit. Surface with the
  last receipt and the narrowest next action.
- `blocked_external_driver`: another automation or person is pushing to the
  branch. Surface and stand down that lane until resolved.
- `blocked_infrastructure`: same infra failure class twice. Surface with log
  receipt and owner action.
- Every stop state writes its receipt before the chat milestone.

## LOS Bindings

The protocol above is portable; these bindings are LOS-specific:

- Repo `thesummitgrp/los-app-los-django` at
  `/Users/genome/projects/los/app/los-app-los-django`. Branch registry:
  `domains/los/02-projects/los_app_los_django/config/git_remote_branch_registry.json`
  (active release, next hotfix, environment heads).
- Family rule (from `los/RULES.md`): 10.x release items target `develop` +
  active `release/v10.x.y`; hotfix items during an active release target
  hotfix + active release + develop.
- Worktrees via `los-fast-workon` / `~/projects/los/misc/setup-worktree.sh`
  (never raw `git worktree add`); runtime via `make fast-up` when dynamic
  validation is needed; targeted tests `make t`; changed-file
  `pre-commit run --files ...`; peak-styles dirty churn is a known unrelated
  exception; never touch `stgcore-app-ulp`.
- Jira: `venturesgo.atlassian.net`, pre-merge statuses per `project.yml`
  (`pr_open: Code Review`, `ready_for_merge: Ready for Merge`,
  `blocked: Blocked`); Developer field = Michael Clark. Post-merge status is
  owned by the `post_merge_jira_routing` workflow
  (`domains/los/03-workflows/engineering/post_merge_jira_routing/`): `Ready for QA`
  for manually testable work, `Ready for Release` otherwise, only after all
  sibling gitflow targets are merged, the version registry is fresh, and
  hotfix SHA/fixVersion membership checks pass. Writes via `acli` with
  native ADF first, MCP/API fallback with a recorded reason; comments carry
  no local paths, no Notion links, no em dashes.
- GitHub text: team-visible only, PR links as
  `[thesummitgrp/los-app-los-django#N](https://github.com/thesummitgrp/los-app-los-django/pull/N)`,
  no OS internals, no em dashes, vary Copilot reply phrasing.
- Merge: squash. Finalize policy is `auto_when_green` with
  `approvals_satisfied_by: operator_bypass` (operator directive 2026-07-18,
  FLYWL-2496 run 1 retro): once every family gate is green the run merges
  develop, then active release, then hotfix via
  `gh pr merge <n> --admin --squash` with per-merge read-backs. Generic
  auto-dev runs keep `never_auto`. Copilot approval never counts. Identity
  guard before every push (no `*.invalid` emails, no synthetic names; the
  repo's commit-message check hard-blocks).
- DEV_STANDARDS: enumerate
  `harness/shared_factory/05-knowledge/dev_standards/*.md` (excluding
  `README.md`) + the LOS domain and project folders
  `domains/los/05-knowledge/dev_standards/*.md` and
  `domains/los/02-projects/los_app_los_django/config/dev_standards/*.md`
  on every run (composable contract; drop-in markdowns extend behavior
  automatically).

## Verification

Before declaring any phase done: the phase receipt exists under
`artifacts/finalize/`, the gate matrix in `finalize-state.json` matches the
receipts, and no claim in chat lacks a receipt path. Before declaring the RUN
done: every family PR is `merged` (with closeout receipts) or holds an
explicit blocked/ready_for_merge receipt, the tracker reflects the terminal
state, and the work item WORKLOG carries the closeout entry.
