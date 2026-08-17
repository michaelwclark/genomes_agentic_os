---
name: auto-dev-validate-production-release
description: Validate exact release-family, revision, QA, and policy evidence after Finalize and before Auto-Dev Merge without mutating providers.
---

# Auto-Dev Validate Production Release

Use this stage only after the governed Finalize receipt is current. Re-read the
selected project policy, exact PR family, revisions, QA receipts, review gates,
and release-operation evidence. Record the read-only validation outcome against
the existing work item; stop on missing or stale evidence.

This stage never merges, publishes, deploys, posts, or repairs provider state.
Merge is separately authorized and is the sole merge executor.
