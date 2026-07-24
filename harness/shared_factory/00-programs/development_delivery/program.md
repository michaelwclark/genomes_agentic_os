# Program: development_delivery

## Purpose

Provide one project-configured entry point for any Agentic OS programming job,
from one tracker item to a bounded portfolio. Every task gets an active work
item, an isolated worktree, receipt-backed quality gates, repair loops, and a
post-delivery cleanup decision.

This is the durable execution engine beneath the operator-facing Auto-Dev
program. It owns coordination, state, worktrees, recovery, and delivery
receipts; Auto-Dev owns the coherent SDLC family, investigation/artifact
workflows, implicit routing, and documentation.

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
| 1 | `readiness_and_context` | claim, grooming check, evidence, worktree and plan inputs | `planned` |
| 2 | `isolated_implementation` | work item, worktree, implementation and local checks | `local_validation` |
| 3 | `pr_create` | resolve, create or reuse, and provider-read the complete PR family | canonical family receipt projected as Auto-Dev `pr_create` |
| 4 | `testing_review_and_pr_repair` | verify the canonical PR Create family, then run test, CI, Copilot, and opposing-review loops | `ready_for_merge` |
| 5 | `merge_deployment_and_cleanup` | independently record Merge, Deploy, provider Closeout, and the cleanup decision | `delivery_complete`; Auto-Dev Health performs later resource pruning |

Auto-Dev PR Create exclusively owns target resolution plus branch and
pull-request creation. The historical `release_propagation` workflow name is a
lower-level recorder/adapter invoked inside the PR Create handoff, not another
ordered workflow, Auto-Dev stage, or provider writer.

Each workflow is documented completely in one `workflow.md`; its adjacent
`workflow.yml` contains only the machine contract. Do not add routing/context
stubs inside workflow folders.

The workflow's historical name is compatibility. Development Delivery owns the
closeout decision and `delivery_complete`; it does not claim the worktree,
target-local runtime, active indexes, or durable packet have been cleaned.
Operators use `develop stage --stage merge`, then `--stage deploy`, then
`--stage closeout`; the broad Closeout range remains only as a compatibility
catch-up path for older callers with every missing receipt.

The Merge recorder accepts only completed typed evidence with an authoritative
`merge_sha`, provider-read `source_head_sha` equal to the reviewed
`subject_revision`, `provider`, `pull_request`, and
`readback_verified: true`. Auto-Dev Health uses those same provider/PR fields
and merge revision as its terminal authority.

Every run also snapshots `auto_dev`, `environment_access`, `dev_standards`,
`qa_gates`, and `gitflow_topology`
from the configured 1-N root/domain/project Markdown folders into
`effective-policies.json`.

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
