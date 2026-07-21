---
name: auto-dev-release
description: Create and verify a project release, version, tag, package, changelog, or provider release through the configured release owner; distinct from branch-family release propagation.
---

# Auto-Dev Release

1. Read project release policy, current version, target branch, changelog
   source, package/provider owner, and required approvals.
2. Decide whether branch-family work is required. Delegate hotfix, backport,
   forward-port, and target PRs to `$auto-dev-pr-create`; do not
   conflate those PRs with version/tag/package publication.
3. Run the project's canonical release program. Verify exact commit, version,
   tag, artifacts, checks, publication, and provider readback.
4. Record release notes through Auto-Dev Document/Create Artifacts and record
   `release` evidence in `autodev.json`.

Local packaging is local validation, not a published release.
