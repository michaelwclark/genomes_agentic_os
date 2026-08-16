# Production Release Validation Gate

Block Merge and Release when any required production-release check is missing,
stale, unavailable, or bound to a different PR head, build, Jira Fix Version,
environment, tenant matrix, or QA run.

The gate must prove release-family completeness, exact source identity, matching
passing QA for every Jira item, full effective-policy diff review, applicable
performance/configuration/security/compatibility gates, artifact provenance,
rollback/recovery, observability, and post-release verification.

For a runtime consumer contract change, the gate also requires the exact-head
consumer inventory, tenant impact matrix, real evaluator evidence for legacy
and canonical shapes, and a compatibility or coordinated-migration decision.
Missing or unclassified consumers block Merge and Release.

Future checks are additive: add another Markdown `Production Release Check` at
the shared, domain, project, or invocation layer. Do not edit the workflow
engine merely to add a check.
