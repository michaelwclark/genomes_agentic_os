# `/auto-dev-merge`

Execute the final live merge from the correct immutable PR-owner readiness
receipt. Use `$auto-dev-merge`, then record a completed
`development-stage-evidence/v1`
receipt with the provider-read `merge_sha`, `source_head_sha`, `provider`,
`pull_request`, configured `repository` id, `base_branch`, provider-qualified
`author_identity`, derived `author_kind`, and
`readback_verified: true` through
`agentic-os develop stage --stage merge`. The source head must equal the exact
reviewed `subject_revision`; repository and base must equal the original PR
authority chain. Read the non-empty repository identity from the linked task;
never leave it empty. Green checks alone are never merge authority.
