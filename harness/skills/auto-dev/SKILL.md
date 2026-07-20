---
name: auto-dev
description: Run software work through the canonical polymorphic SDLC family: Detective investigation, governed artifact authoring, readiness/context, isolated implementation, testing/review/PR repair, release propagation, and merge/deployment/cleanup. Use for tracker-backed fixes, features, refactors, reviews, releases, deployments, or finish-all-the-way requests even when the user does not name Auto-Dev.
---

# Auto-Dev

Auto-Dev is the operator-facing family. `development_delivery` is its only code
delivery state/worktree/recovery engine. Never start a second state packet under
`artifacts/auto-dev/` for a new run.

## Route by intent

- Uncertain cause, reported bug, failed QA, log, alert, or RCA: start with
  `$auto-dev-detective`.
- Jira, Linear, Notion, Confluence, GitHub, Slack, RCA, report, PR body, review,
  status, or closeout output: use `$auto-dev-create-artifacts`.
- Code delivery: start/resume `agentic-os develop`, then use the matching stage
  skill below.

## Canonical delivery path

1. `$auto-dev-readiness` — tracker truth, repository/base, inherited policy,
   work item, isolated worktree, and plan; ends `planned`.
2. `$auto-dev-implementation` — bounded implementation and local validation;
   ends `local_validation`.
3. `$auto-dev-review-repair` — testing, opposing review, governed PR, quiet
   CI/review repair, and final readiness; ends `ready_for_merge`.
4. `$auto-dev-release-propagation` — required release/hotfix/backport/forward-
   port family; retains merge-readiness and records its own receipt.
5. `$auto-dev-closeout` — approved merge, deployment monitoring, deployed
   validation, provider reconciliation, cleanup, and `delivery_complete`.

Each stage is manually callable from chat and performs the work before
`agentic-os develop stage` records typed, preflighted receipts. The stage
recorder does not execute or invent provider actions.

## Policy composition

Before each stage, load the effective 1-N Markdown bundle:

```text
root → domain → project → invocation
```

- development: `dev_standards`, `qa_gates`, `gitflow_topology`;
- investigation: `investigation-config`;
- output: `artifact-config`.

Adding a matching Markdown file changes the next run without changing the
shared workflow. Active Development Delivery runs remain pinned to their policy
fingerprint and report later drift.

## Hard gates

- Multi-repository projects require an explicit repository id.
- Ticket/release authority selects the base branch; pass `--base-branch` rather
  than changing project defaults for one run.
- Environment-scoped causal code claims require a deployed-version receipt.
- Tests, review, checks, provider writes, merge, deployment, and closeout need
  exact evidence/readback; a transition string is not evidence.
- External writes, merge, deployment, production, destructive, billing, legal,
  and customer-visible operations retain their routed approval gates.
- Keep raw logs, secrets, customer data, local paths, private Notion links, and
  OS internals out of external output.

## Compatibility

`harness/skills/auto-dev/scripts/auto_dev_state.py`, its fixtures, and the old
`artifacts/auto-dev/state.json` model remain compatibility-only for runs already
created by that engine. Do not start new runs there. Migration/retirement is
tracked in the Auto-Dev `ARCHIVE_SOON.md` ledger.
