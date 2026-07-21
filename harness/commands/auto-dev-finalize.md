# `/auto-dev-finalize`

Manually converge every agent-authored PR for one ticket through independent
review and a governed merge-readiness decision. Finalize never executes the
merge; use `$auto-dev-finalize`, then hand its immutable receipt to
`$auto-dev-merge` when authorized. The receipt binds the provider-read PR,
configured repository/base, reviewed head, provider-qualified author identity,
derived `author_kind: ours`, and `readiness_decision: ready_for_merge`.
