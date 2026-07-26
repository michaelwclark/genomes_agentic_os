# Implementation Plan

Created: 2026-06-25 14:34 CDT

1. Create isolated worktree from `origin/develop`.
2. Inspect `.github/workflows/pytest-fast.yml` for Node 20 action-runtime sources.
3. Verify internal action mirror tags that declare `node24`.
4. Update checkout/setup-python action majors in the pytest workflow.
5. Validate YAML parse, action references, and diff whitespace.
6. Commit, push, and open PR to `develop`.
