---
name: auto-dev-validate-production-release
description: Run the blocking pre-merge Auto-Dev release-candidate validation across Jira, GitHub, exact revisions, QA evidence, effective policy, risk gates, and release operations.
---

# Auto-Dev Validate Production Release

Run this family workflow after Auto-Dev Finalize and before Auto-Dev Merge.
It is a read-only provider-validation stage; it does not merge, release,
deploy, or update Jira/GitHub.

## Procedure

1. Load the effective `auto_dev`, `dev_standards`, `qa_gates`,
   `gitflow_topology`, artifact, and investigation policy bundle. Freeze its
   fingerprint for the receipt.
2. Read Jira release/Fix Version authority and enumerate every item in scope.
   Read GitHub and enumerate every required branch/PR target from topology.
   Block missing, extra, mismatched, or conflicting membership and Fix Version.
3. Compare each PR base/head/merge SHA, branch ancestry, build/version
   registry, and candidate artifact. Any stale or unbound identity blocks.
4. For every Jira item, verify a matching terminal passing QA Run or configured
   equivalent for the exact ticket, build, tested SHA, environment,
   tenant/fixture matrix, and acceptance path.
5. Review the complete exact-head diff against the frozen effective rules,
   including nested source rules and migrations/configuration/rules/generated
   files. Consume all applicable performance, configuration-composition,
   security/tenancy, dependency, and compatibility receipts.
6. When the diff changes a serializer, request/payload canonicalization,
   persisted configuration, rule, template, or consumer input, require
   `runtime_consumer_contracts`: complete consumer and tenant matrices, real
   evaluator tests for both legacy and canonical shapes, a compatibility or
   coordinated-migration strategy, and runtime readback. Block a silent empty
   result, even when the request succeeds.
7. Verify artifact provenance, rollback/recovery, observability/alerting,
   runbook ownership, and post-release verification.
8. Record `production_release_validation` with the required stable check IDs,
   per-Jira `qa_runs`, a passing independent-review receipt, provider
   readbacks, exact revisions, policy fingerprint, evidence refs, and either
   `ready_for_merge` or one exact blocker and owner.

Every Markdown `Production Release Check` in the effective policy bundle is
required. Future checks are added through shared, domain, project, or
invocation Markdown; do not modify this workflow to add a check.
