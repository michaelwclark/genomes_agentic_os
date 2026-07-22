---
name: auto-dev-continuous-release
description: Operate one project's own-PR continuous-delivery loop: one operator PR per run through review, finalize, and merge, then the project release program and documentation run.
---

# Auto-Dev Continuous Release

Operate one project's own-PR continuous-delivery loop. Exactly one
operator-authored PR per run through the canonical chain, then the project
release program, then documentation.

1. Resolve the project profile: require `continuous_release.enabled: true`
   with a dated `authority`, a `release:` block, and
   `dev_factory.merge.policy: auto_when_green`. Missing config ⇒ report-only
   run with a receipt.
2. Enumerate open PRs authored by the configured allowlist, excluding
   drafts, configured head prefixes (e.g. `renovate/` — owned by
   `$auto-dev-dep-updater`), the opt-out label, and `blocked:` entries.
   Select ONE, oldest first. Zero eligible ⇒ run step 5's catch-up check,
   then exit with a receipt.
3. Drive the selected PR through the canonical stages — delegate, never
   reimplement: `$auto-dev-review-self` (repair via its owner) →
   `$auto-dev-finalize` (merge intent from `dev_factory.merge`) →
   `$auto-dev-merge`. Every profile gate (CI green, Copilot clean, finishing
   review) binds; an unsatisfiable gate stops the run.
4. Release per the project `release:` block: compute the SemVer bump from
   Conventional Commits since the last version tag (breaking ⇒ major,
   `feat` ⇒ minor, `fix`/`perf` ⇒ patch including `fix(deps)`;
   chore/docs/test/ci-only ⇒ none). When due: bump the version file, update
   the changelog, commit the release commit, create the immutable tag,
   publish the provider release with generated notes. Never re-tag a tagged
   SHA; never tag over a red mainline workflow.
5. Catch-up: if the mainline carries release-worthy commits with no tag,
   run step 4 even when no PR was processed this run.
6. Notify through the governed notifier (`agentic-os notify`) with the
   configured source and dedupe key, then run the project's post-release
   documentation entries (`$auto-dev-document`) and record the receipt.
7. Record every disposition in the automation run ledger. One PR per run.
   Merge and release authority come only from the project profile plus the
   invoking automation's maturity contract — never implicit.
