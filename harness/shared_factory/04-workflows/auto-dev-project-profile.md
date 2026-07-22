# Auto-Dev Project Profile

This reference documents the automation-related blocks of a project's
`project.yml`: `dep_updater:` (dependency-update PRs), the shared
`automation.repo_ops_lock`, `release:` (the release program), and
`continuous_release:` (the own-PR continuous-delivery loop). Each block is
consumed by the matching skill and by the automation that invokes it on a
schedule.

## Dependency Updater (`dep_updater:`)

Consumed by the `auto-dev-dep-updater` skill (see
`harness/skills/auto-dev-dep-updater/SKILL.md`).

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

### Field notes

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

### Merge authority rule

`merge.authority` must cite a dated operator directive — a dated instruction or
decision record authorizing standing auto-merge for this repository's
dependency updates. Without that citation, the skill treats the configured
`merge.policy` as `report_only` regardless of its literal value; standing merge
authority is never inferred from the presence of the block alone.

### Missing or disabled configuration

A project with no `dep_updater:` block, or with `enabled: false`, still gets a
report-only run: the skill enumerates eligible update PRs and records a
receipt, but never merges or pushes a repair commit.

## Repo Ops Lock (`automation.repo_ops_lock`)

```yaml
automation:
  repo_ops_lock: state/repo-ops.lock
```

A project-relative lock path that both PR-driving automations —
`auto-dev-dep-updater` and `auto-dev-continuous-release` — acquire before a
merge or a release tag. Without it, the two loops could race: for example,
both attempting a merge or a tag against the same repository at the same
time. Any automation that merges PRs or cuts release tags for this project
must hold this lock for the duration of that step.

## Release Program (`release:`)

Consumed by `auto-dev-release` and by `auto-dev-continuous-release`'s
post-merge release step. Policy source: Conventional Commits → SemVer with
protected, immutable mainline tags, per this project's release conventions
(work-item packet 071826-064).

```yaml
release:
  policy: continuous
  version_file: pyproject.toml
  tag_format: "v{version}"
  bump_rules:
    major: breaking_change
    minor: [feat]
    patch: [fix, perf, "fix(deps)"]
    none: [chore, docs, test, ci, refactor, style]
  changelog: CHANGELOG.md
  provider_release:
    system: github
    command: gh release create v{version} --generate-notes
  release_commit_format: "release: v{version}"
  guards:
    require_green_main_workflow: true
    never_retag: true
  notify:
    source: agentic_os_release
    dedupe_key: "release-v{version}"
  post_release:
    - documentation_run
```

### Field notes

- `bump_rules` computes the SemVer bump from Conventional Commits since the
  last version tag: any breaking-change commit ⇒ major; any `feat` (with no
  breaking change) ⇒ minor; only `fix`/`perf` commits (including
  `fix(deps)`) ⇒ patch; a run made up only of
  `chore`/`docs`/`test`/`ci`/`refactor`/`style` commits ⇒ no release.
- `guards.require_green_main_workflow` refuses to tag over a red mainline
  workflow run.
- `guards.never_retag` makes an existing version tag immutable; a release is
  never re-tagged onto a different commit.
- `notify` drives exactly one governed notification per release, through the
  configured source and dedupe key — never an ad hoc message.
- `post_release` lists steps that run after a successful release;
  `documentation_run` delegates to `auto-dev-document`.

## Continuous Release (`continuous_release:`)

Consumed by the `auto-dev-continuous-release` skill. Merge gates live in
`dev_factory.merge` (for example `auto_when_green` plus required receipts)
and are not duplicated here; this block only scopes which PRs are eligible
and whether the loop (including the release step) runs at all.

```yaml
continuous_release:
  enabled: true
  authority: "<dated operator directive — REQUIRED>"
  author_allowlist: ["<github-username>"]
  exclude_head_prefixes: [renovate/]
  opt_out_label: no-auto
  blocked: []
  max_prs_per_run: 1
```

### Field notes

- `author_allowlist` lists the GitHub handles whose own PRs this loop may
  drive to merge; a PR from anyone else is out of scope for this skill.
- `exclude_head_prefixes` keeps this loop from ever touching branches owned
  by another automation; `renovate/` belongs to `auto-dev-dep-updater`.
- `opt_out_label` lets an operator pull one specific PR out of the loop for
  a single run without disabling the whole block.
- `blocked` defers specific PRs or branches with a written reason.
- `max_prs_per_run` exists for documentation and defense in depth; the
  skill itself enforces exactly one PR per run regardless of this value.

### Authority rule

`authority` must cite a dated operator directive authorizing this project's
own PRs to be driven through review, finalize, and merge, and its mainline
to be released automatically. Without that citation, the skill treats the
whole loop as report_only regardless of `enabled: true` — standing authority
to merge and release is never inferred from the presence of this block
alone.

### Missing or disabled configuration

A project with no `continuous_release:` block, `enabled: false`, or no
`authority`, gets a report-only run: open PRs and any pending release are
still enumerated and recorded in a receipt, but the skill never merges a PR
or cuts a release.
