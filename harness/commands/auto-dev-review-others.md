# `/auto-dev-review-others`

Review another author's PR through the canonical PR Review owner. Use
`$auto-dev-review-others` in review-only/no-merge mode; this command does not
imply permission to repair or merge. Hand a clean hashed receipt to
`$auto-dev-merge`; it must preserve the provider-read PR/repository/base/head,
derived `author_kind: others`, `review_mode: review_no_merge`, and
`review_result: clean`.
