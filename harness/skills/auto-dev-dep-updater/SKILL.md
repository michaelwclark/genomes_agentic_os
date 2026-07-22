---
name: auto-dev-dep-updater
description: Operate one repository's dependency-update lane, proven against the dependency contract suites, merged under written per-repo authority or repaired to green first.
---

# Auto-Dev Dep Updater

Operate one repository's automated dependency-update lane. Exactly one open
update PR per run, proven against the repository's dependency contract
suites, merged only under the project's written authority.

1. Resolve the project profile `dep_updater:` block. Require `enabled: true`,
   an explicit `merge.policy`, and contract-suite commands. Missing or
   disabled config ⇒ report-only run with a receipt.
2. Enumerate open update PRs (head-branch prefix from config, default
   `renovate/`). Select ONE — oldest first — skipping drafts, `no-auto`
   labels, and `blocked:` entries. Zero eligible PRs ⇒ clean exit receipt.
3. Ensure the selected PR is current with its base (provider rebase per
   `renovate.json` `rebaseWhen`, or a branch update). Wait for required
   checks; the dependency contract suites are the load-bearing signal.
4. Green ⇒ merge with the configured method, run `post_merge:` commands,
   record the disposition, stop. One PR per run, never more.
5. Red ⇒ repair on the PR head in an isolated worktree: update how the
   repository uses the dependency AND its contract tests together (the
   contract must keep asserting the surface actually used — never delete an
   assertion to get green). Push to the PR branch, re-verify locally and in
   CI, then merge as in step 4.
6. Incompatible updates (peer-dependency walls, upstream breakage) are never
   forced: record the blocker on the PR, apply the configured deferral
   (Renovate packageRule or `blocked:` entry), surface to the operator.
7. Record every disposition in the automation run ledger. Merge authority
   comes only from `dep_updater.merge` plus the invoking automation's
   maturity contract — never implicit.
