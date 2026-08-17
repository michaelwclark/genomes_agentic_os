# `/auto-dev-validate-production-release`

Run the required, read-only production-release validation after Finalize and
before Merge. It verifies the exact release family, revision, QA and policy
evidence required by the selected project. It records a blocker for missing or
stale evidence and never merges, releases, deploys, posts, or repairs state.
