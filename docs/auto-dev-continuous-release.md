# Auto-Dev Continuous Release

`auto-dev-continuous-release` operates one project's own-PR continuous-delivery
loop: it drives exactly one operator-authored pull request per run through
review, finalize, and merge, then runs the project's release program and
post-release documentation.

## The loop

1. Read the project's `continuous_release:` profile block — see
   `harness/shared_factory/04-workflows/auto-dev-project-profile.md` for the
   full schema. It requires `enabled: true`, a dated `authority`, a
   `release:` block, and `dev_factory.merge.policy: auto_when_green`. Missing
   or incomplete config produces a report-only run: PRs and any pending
   release are still enumerated and recorded in a receipt, but nothing
   merges or releases.
2. Select the single oldest eligible open PR authored by the configured
   `author_allowlist`, skipping drafts, excluded head prefixes, the
   `no-auto` opt-out label, and `blocked:` entries. Zero eligible PRs still
   runs the catch-up release check in step 4.
3. Drive the selected PR through the canonical chain by delegation, never by
   reimplementing it: `auto-dev-review-self` reviews and repairs, then
   `auto-dev-finalize` records merge-readiness intent from
   `dev_factory.merge`, then `auto-dev-merge` executes the merge. Every
   profile gate — CI green, Copilot clean, finishing review — binds; an
   unsatisfiable gate stops the run without forcing a merge.
4. Release per the project's `release:` block: compute the SemVer bump from
   Conventional Commits since the last version tag (a breaking-change commit
   is major, `feat` is minor, `fix`/`perf` including `fix(deps)` is patch,
   a chore/docs/test/ci-only run is no release). When a release is due,
   bump the version file, update the changelog, commit the release commit,
   cut the immutable tag, and publish the provider release with generated
   notes. A tagged commit is never re-tagged, and a release never tags over
   a red mainline workflow. This step runs as a catch-up even when no PR was
   processed this run, whenever the mainline carries release-worthy commits
   with no tag yet.
5. Notify through the governed notifier (`agentic-os notify`) with the
   project's configured source and dedupe key, then run the project's
   post-release documentation entries through `auto-dev-document`.
6. Record every disposition — merged, released, deferred, or report-only —
   in the automation run ledger.

## Configuration

Every behavior above is driven by the `continuous_release:` and `release:`
blocks in a project's `project.yml`, plus the shared
`automation.repo_ops_lock`. See
`harness/shared_factory/04-workflows/auto-dev-project-profile.md` for the
full schema and examples. Release policy — Conventional Commits → SemVer,
protected immutable mainline tags — follows this project's release
conventions (work-item packet 071826-064).

## Authority

The skill only drives a PR to merge, or cuts a release, when
`continuous_release.authority` cites a dated operator directive. Without
that citation, the whole loop is treated as `report_only` regardless of
`enabled: true` — standing authority to merge or release is never inferred,
only granted explicitly per project.

## Composing with auto-dev-dep-updater

`auto-dev-continuous-release` and `auto-dev-dep-updater` are two independent
PR-driving loops over the same repository, kept from colliding by:

- **Branch ownership.** `continuous_release.exclude_head_prefixes` (default
  `renovate/`) keeps this skill from ever touching a PR that belongs to
  `auto-dev-dep-updater`, and the dep-updater skill only ever looks at that
  same prefix — the two authors' PRs never overlap.
- **A shared lock.** Both loops acquire `automation.repo_ops_lock` (a
  project-relative lock path, for example `state/repo-ops.lock`) before a
  merge or a release tag, so a scheduled run of one skill can never race a
  concurrent run of the other against the same mainline.
- **One release owner.** Either loop's merge can be release-worthy, but the
  `release:` block, its guards, and the immutable-tag rule are shared,
  project-level state — not something either skill owns privately.
