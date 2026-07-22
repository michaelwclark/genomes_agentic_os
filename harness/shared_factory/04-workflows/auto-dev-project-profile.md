# Auto-Dev Project Profile — Dependency Updater

This reference documents the `dep_updater:` block of a project's `project.yml`.
It is consumed by the `auto-dev-dep-updater` skill (see
`harness/skills/auto-dev-dep-updater/SKILL.md`) and by the automation that
invokes that skill on a schedule.

## Schema

```yaml
dep_updater:
  enabled: true
  provider: renovate            # renovate | dependabot
  head_branch_prefix: renovate/
  merge:
    policy: auto_when_green     # auto_when_green | report_only
    method: squash
    authority: "<dated operator directive reference — REQUIRED for auto_when_green>"
  required_checks: [pytest, gui]
  contract_suites:
    - python -m pytest tests/contracts -q
    - pnpm --dir apps/agentic-os-gui test:contracts
  post_merge: []                # commands run after each merge (e.g. reinstall)
  blocked: []                   # dependency names deferred with a written reason
  max_prs_per_run: 1            # hard cap; the skill enforces 1 regardless
```

## Field notes

- `provider` selects which bot's open PRs the skill enumerates.
- `head_branch_prefix` filters candidate PRs by branch name; `renovate/` is the
  default for a Renovate-managed repository.
- `required_checks` names the checks that must be green before merge; the
  project's `contract_suites` commands are the load-bearing signal among them,
  not merely CI going green.
- `post_merge` runs after a successful merge (for example, a lockfile
  reinstall) and is never used to skip verification before merge.
- `blocked` defers specific dependencies with a written reason instead of
  forcing an incompatible update through.
- `max_prs_per_run` exists for documentation and defense in depth; the skill
  itself enforces exactly one PR per run regardless of this value.

## Merge authority rule

`merge.authority` must cite a dated operator directive — a dated instruction or
decision record authorizing standing auto-merge for this repository's
dependency updates. Without that citation, the skill treats the configured
`merge.policy` as `report_only` regardless of its literal value; standing merge
authority is never inferred from the presence of the block alone.

## Missing or disabled configuration

A project with no `dep_updater:` block, or with `enabled: false`, still gets a
report-only run: the skill enumerates eligible update PRs and records a
receipt, but never merges or pushes a repair commit.
