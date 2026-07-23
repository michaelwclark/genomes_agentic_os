---
name: pull-request
description: Compatibility alias for canonical pr-review. Preserve the old name for callers, but delegate all review policy, receipts, posting, and merge behavior.
argument-hint: "[PR-number-or-URL] [--quick] [--severity critical|high|medium|low] [--jira-only] [--security] [--team-health on|off] [--post|--no-post] [--no-merge]"
---

# Pull Request Compatibility Alias

This legacy name remains so existing prompts and integrations do not break.
Immediately route to canonical `$pr-review`; do not execute a second review
policy from this directory.

- Default -> `pr-review --mode review --no-post`.
- `--jira-only` -> `--acceptance-only`.
- Other review, posting, severity, security, health, quick, and no-merge flags
  pass through unchanged.
- A request to merge another author's clean PR -> `review+merge` after authority
  checks.
- Operator/agent-authored merge work -> `$auto-dev-finalize` with independent
  model-family review.

The retained `references/` files and specialist reviewer agents remain shared
building blocks. This alias owns no policy.
