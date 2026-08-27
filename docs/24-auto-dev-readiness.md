# 24 · Auto-Dev Readiness

> **Purpose:** prove that a tracker-backed code task has enough ownership,
> project configuration, evidence, policy, and recovery context to enter the
> canonical Development Delivery engine beneath Auto-Dev.

## Start with a dry run

```bash
agentic-os develop start <domain> <project> <ticket> [<ticket> ...]
# Add --repository <id> when repository.catalog requires explicit selection.
```

The dry run validates `config/development.yml`, resolves repository/base/worktree
behavior, and returns the intended portfolio plus effective policy source lists
and fingerprint. It does not create a work item, worktree, or external claim.

Use `--apply` only after the tracker item, target project, and scope are verified:

```bash
agentic-os develop start <domain> <project> <ticket> --apply
```

## Required project profile

`config/development.yml` is canonical. Legacy `project.yml dev_factory` remains
a compatibility bridge while projects migrate.

Required behavior includes tracker, repository/base branch, worktree directory
and branch template, validation commands/policy, opposing review, merge policy,
and recovery attempt/lease limits. Missing configuration blocks; Auto-Dev does
not silently default to LOS, Jira, Linear, `main`, `develop`, or a test command.
Multi-repository projects use `repository.catalog` plus
`selection_required: true`; each run receipts the chosen repository and refuses
to infer it from ticket wording.

## Tracker content decides readiness

Jira and Linear workflow status is advisory metadata. Read the live ticket and
evaluate its problem, intended outcome, scope, acceptance behavior,
dependencies, and validation expectations. When that content is sufficient for
safe implementation, record the item as content-ready and continue even if the
provider status remains `Requirements`, `Requirements Gathering`, or an
equivalent pre-development label. A status transition or grooming approval is
not required merely to start development.

If the content is incomplete, use Grooming to resolve the gaps from source
truth and project policy. Stop only for a concrete missing decision, unsafe
ambiguity, dependency, authority, access, or approval. Report the exact owner
action; never report the status label itself as the blocker or attention
request.

## Effective policy gate

Before implementation or review, inspect the dynamic 1-N Markdown bundles:

```bash
agentic-os develop policy <domain> <project> --plane dev_standards --json
agentic-os develop policy <domain> <project> --plane qa_gates --json
agentic-os develop policy <domain> <project> --plane gitflow_topology --json
agentic-os develop policy <domain> <project> --plane auto_dev --json
agentic-os develop policy <domain> <project> --plane environment_access --json
```

Default inheritance is root → domain → project. A project may configure an
ordered path list in `config/development.yml`. The applied run snapshots all
five nested Auto-Dev planes into
`state/development-runs/<run-id>/effective-policies.json`.

## Readiness checks

| Gate | Ready when | If not ready |
| --- | --- | --- |
| Tracker | live item, correct project/team, content-ready acceptance, no duplicate ownership; workflow status is advisory | groom missing content through Spec Engine; never block on the status label alone |
| Repository | configured source exists; exact remote base resolves | repair project config/access; never substitute a branch |
| Evidence | relevant project/domain context receipt exists, including an explicit `no_context` | investigate the missing questions |
| Environment | when behavior is environment-scoped, deployed version authority is known | run Detective; do not analyze a default branch as deployed truth |
| Policies | required folders parse and sources/fingerprint are visible | repair policy; do not bypass |
| Recovery | run id, retry classification, lease, receipt locations are valid | repair state/config before dispatch |

## Applied-run receipts

```text
<project>/state/development-runs/<run-id>/
  portfolio.json
  effective-policies.json
  tasks/<ticket>/
    state.json
    events.jsonl
```

The linked active work item carries its run reference, exact worktree/base SHA,
plan, test/review/PR/CI/release/deploy evidence, and compact final closeout.

## Failure and resume

- Provider/environment unavailable: classified retry with attempt budget.
- Missing evidence/config/product decision: block with exact owner action.
- Broken local environment: `environment_unavailable`, never a passing test.
- Stale worker: lease recovery; do not create duplicate ownership.
- Existing run: resume by run id and receipts; never delete state to restart.

See [42 · Auto-Dev Program](42-auto-dev-program.md) for the complete family and
[25 · Source Of Truth Rules](25-source-of-truth.md) for external ownership.
