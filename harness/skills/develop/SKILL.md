---
name: develop
description: Canonical Agentic OS implementation program for one or many tracker-backed programming tasks, including project configuration, isolated worktrees, testing, PR repair, PR-family compatibility recording, deployment monitoring, recovery, and cleanup.
---

# Develop

Use this skill for every Agentic OS programming implementation job, whether the
input is one ticket or a bounded list.

## Start

1. Read the routed project contract and `config/development.yml`, the canonical
   code settings file for projects in every domain. Worktree names inherit the
   OS date-prefix policy unless `worktrees.date_prefix` overrides it.
2. Read `harness/shared_factory/00-programs/development_delivery/program.md` and
   `components.yml`.
3. Start or resume with:

```bash
agentic-os develop start <domain> <project> <ticket> [<ticket> ...] --apply
```

4. Execute the five workflows in `components.yml` order. Each workflow's single
   `workflow.md` is the complete human specification; `workflow.yml` is the
   machine contract. Do not require additional workflow context stubs.

## Non-negotiable gates

- One active work item and one task-owned worktree under the directory configured
  by `worktrees.directory` per ticket; every worktree must remain visible through
  the project `worktrees/` registry. Never implement in the shared checkout.
- Verify the tracker claim and grooming/context decision before coding.
- Document non-obvious invariants, failure behavior, and recovery decisions in
  code and the work item.
- Use risk-based unit, integration, and repository end-to-end tests with 3A
  structure where applicable.
- A broken local environment is `environment_unavailable`, not passing. When
  policy permits, finish the branch/PR and require GitHub CI as the final signal.
- Watch and repair CI and actionable Copilot/review findings until clean.
- Run pre-PR and post-PR opposing-harness review when configured; preserve
  prompt, response, model, and decision receipts.
- Respect fix-version PR-family policy, preserve the lower-level
  `release_propagation` compatibility receipt, and enforce post-merge
  deployment/cleanup.
- Record every state transition and failure with an idempotency key and receipt.

## Failure and resumption

Classify failures using the owning workflow. Retry only recoverable failures up
to the project attempt limit. Preserve successful independent tasks in a 1-N
portfolio. Never delete state to restart: repair the cause and use
`agentic-os develop recover`.
