# Auto-Dev: validate production release

Use `/auto-dev-validate-production-release` after Finalize and before Merge to
perform the read-only release-family validation required by project policy.

Validate the exact PR family, source and target revisions, QA receipts,
required policy reviews, release gates, and any project-specific release
operations. Record missing, stale, or conflicting evidence as a blocker. This
stage never merges, releases, deploys, posts, or repairs provider state.

The stage requires the immutable Finalize `ready_for_merge` decision and records
a receipt bound to the same work item and policy fingerprint. Merge remains the
only stage allowed to perform a merge after a successful validation.
