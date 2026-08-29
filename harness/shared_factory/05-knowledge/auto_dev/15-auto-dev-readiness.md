# Auto-Dev: readiness

Use `/auto-dev-readiness` after grooming, investigation, and required artifact
work to turn an implementation-ready item into one exact, safe execution plan.
Readiness prepares delivery state and isolation. It does not implement code.

## Content-based tracker readiness

Read the live Jira or Linear item before interpreting its workflow state.
`Requirements`, `Requirements Gathering`, and equivalent labels are advisory
only. If the problem, intended outcome, scope, acceptance behavior,
dependencies, and validation expectations are sufficient for safe delivery,
record the item as content-ready and proceed without waiting for a status
transition or a metadata-only approval.

If the content is incomplete, route through Grooming and continue when source
truth and project policy resolve the gaps. Block only on one concrete missing
decision or another real delivery gate. The provider status label itself is
never a blocker or attention request.

## Inputs

- live tracker item, acceptance behavior, dependencies, and fix/release version;
- completed investigation/artifact evidence required by the item;
- routed domain and project plus candidate repository identities;
- project repository catalog, development configuration, GitFlow topology,
  development standards, QA gates, and environment-access policy;
- existing work item, branch, worktree, pull request, runtime, and provider
  references when resuming.

## Resolve before work begins

1. Select the explicit repository id. A multi-repository project may never rely
   on a default guessed from the ticket type.
2. Determine the base branch and required pull-request targets from live ticket,
   fix-version, release, and project policy. Record any missing authority.
3. Confirm source checkout identity, remote, clean base revision, repository
   instructions, language/runtime, package manager, and required toolchain.
4. Compose root, domain, project, and invocation policy across Auto-Dev,
   development, QA, GitFlow, environment, investigation, and artifact planes.
5. Identify policy drift from an existing frozen task. Do not silently rewrite
   an active task's rules, runtime identity, repository, or base.
6. Create or verify the registered isolated worktree and exact branch through
   the canonical project worktree owner.
7. Resolve any item-owned runtime registration from project configuration
   without guessing names or teardown commands.
8. Produce a small implementation plan that maps acceptance behavior to files
   or boundaries, tests, documentation, migrations/data, observability,
   release/propagation, deployment, and rollback concerns.
9. Record risk level and the expected validation triangle.

Use bounded subagents for repository mapping or independent plan review when
the work spans separable systems. The coordinator owns the final repository,
base, worktree, policy, and plan decision.

## Evidence and done criteria

Readiness evidence names the tracker/work item, domain, project, repository,
remote, base branch and revision, feature branch, registered worktree,
item-runtime ownership/identity, policy sources/fingerprint, plan, risk, and
expected checks.

The stage completes when a developer can begin in the exact isolated checkout
without making another routing, branch, policy, or environment guess. Missing
repository authority, conflicting base rules, unsafe/dirty isolation, policy
drift, unavailable required toolchain, or a material product decision is an
explicit blocker and next action.

Readiness does not edit product code, create a pull request, merge, deploy, or
claim local validation.
