# Auto-Dev Validate Production Release

Run the read-only pre-merge production-release validation gate after Finalize
and before Merge. Load the effective root, domain, project, and invocation
Markdown policies; enumerate the complete Jira/GitHub release family; bind every
item to the exact branch, PR, source head, and build; verify a matching passing
QA run; inspect the entire exact-head diff; and verify performance,
configuration/migration, security, compatibility, artifact, rollback,
observability, and post-release evidence. Any mismatch, stale receipt, unknown
provider result, or missing policy evidence blocks Merge.

When the diff changes a request, serializer, canonical payload, persisted
configuration, rule, or template input, `runtime_consumer_contracts` is
mandatory. The receipt must contain the complete consumer and tenant matrices,
legacy and canonical-shape evaluator evidence, compatibility strategy, and
runtime readback; a serializer-only test cannot satisfy the gate.

The canonical command and receipt contract are defined by
`/auto-dev-validate-production-release` and
`lib/workflows/root/validate_production_release/`. Project and domain overlays
may add checks or stricter evidence in Markdown, but may not weaken shared
checks.
