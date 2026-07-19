# Program: development_delivery

## Purpose

Provide one project-configured entry point for any Agentic OS programming job,
from one tracker item to a bounded portfolio. Every task gets an active work
item, an isolated worktree, receipt-backed quality gates, repair loops, and a
post-delivery cleanup decision.

## Operator entry point

```bash
agentic-os develop start <domain> <project> <ticket> [<ticket> ...] --apply
```

Dry-run is the default. The project owns behavior through
`config/development.yml`; legacy `project.yml dev_factory` is read only as a
compatibility bridge. This is the canonical code settings contract for projects
in every domain. `worktrees.date_prefix: inherit` is the default; `true` or
`false` provides a project override while the physical checkout directory is
controlled by `worktrees.directory`.

## Workflow map

| Order | Workflow | Owns | Terminal handoff |
|---|---|---|---|
| 1 | `readiness_and_context` | claim, grooming check, evidence and plan inputs | `context_ready` |
| 2 | `isolated_implementation` | work item, worktree, implementation and local checks | `local_validation` |
| 3 | `testing_review_and_pr_repair` | test triangle, PR, CI, Copilot and opposing review loops | `ready_for_merge` |
| 4 | `release_propagation` | fix-version and cherry-pick/release-PR needs | `release_ready` or `not_required` |
| 5 | `merge_deployment_and_cleanup` | merge observation, deployment watch, closeout and retention | `delivery_complete` |

Each workflow is documented completely in one `workflow.md`; its adjacent
`workflow.yml` contains only the machine contract. Do not add routing/context
stubs inside workflow folders.

## Safety boundaries

- Never edit the shared checkout; fetch the configured base and create a task
  worktree under the configured directory. If that directory is external, keep
  the checkout registered on the project's visible `worktrees/` surface.
- Never treat a broken local environment as passing tests. Classify it as
  `environment_unavailable`, preserve evidence, and use PR CI only when policy
  permits.
- Never auto-merge unless the project profile explicitly permits it.
- A state change without a receipt is invalid.
- Retry only classified recoverable failures and block when the attempt budget
  is exhausted.
