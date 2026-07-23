# Auto-Dev Dep Updater

`auto-dev-dep-updater` operates one repository's automated dependency-update
lane: Renovate (or Dependabot) opens update pull requests, and this skill
drives exactly one of them per run to a governed merge.

> This doc stands alone until `docs/dependency-contract-tests.md` lands
> (dependency contract test suites, `tests/contracts` and
> `apps/agentic-os-gui/e2e/contracts`). Once that doc exists, fold this
> section into it under an "Automation: auto-dev-dep-updater" heading.

## The loop

1. Read the project's `dep_updater:` profile block — see
   `harness/shared_factory/04-workflows/auto-dev-project-profile.md` for the
   full schema. A missing or disabled block produces a report-only run: PRs
   are enumerated and a receipt is recorded, but nothing merges.
2. Select the single oldest eligible open update PR, skipping drafts,
   `no-auto` labels, and configured `blocked:` entries. Zero eligible PRs is a
   clean exit, not a failure.
3. Bring the selected PR current with its base and wait for required checks.
   The project's dependency contract suites are the load-bearing signal —
   green CI alone is not sufficient proof that the update is safe.
4. Green ⇒ merge with the configured method, run any `post_merge:` commands,
   and stop. Exactly one PR merges per run.
5. Red ⇒ repair on the PR head in an isolated worktree: update how the
   repository uses the dependency **and** the contract tests that assert its
   surface, together. A contract test is never weakened or deleted just to
   turn a run green. Re-verify locally and in CI, then merge as in step 4.
6. A genuine incompatibility (peer-dependency wall, upstream breakage) is
   never forced through. It is recorded as a blocker on the PR, deferred via
   the configured mechanism, and surfaced to the operator.

## Configuration

Every behavior above is driven by the `dep_updater:` block in a project's
`project.yml`. See
`harness/shared_factory/04-workflows/auto-dev-project-profile.md` for the full
schema and an example.

## Merge authority

The skill only merges under `auto_when_green` when
`dep_updater.merge.authority` cites a dated operator directive. Without that
citation, the effective policy is `report_only` regardless of the configured
value — standing merge authority is never inferred, only granted explicitly
per project.
