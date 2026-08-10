# Auto-Dev Validate Production Release

This is the blocking pre-merge release-candidate workflow in the Auto-Dev
family. It runs after Finalize and before Merge. It is read-only with respect
to Jira, GitHub, release systems, and production.

The workflow loads the effective root → domain → project → invocation policy
bundle. Every Markdown `Production Release Check` in that bundle is part of the
run. Shared checks are mandatory; domain and project files add or specialize
checks without weakening them.

## Procedure

1. Snapshot Jira release/Fix Version authority, GitHub repository and PR-family
   state, exact heads/bases/merge SHAs, build/version identity, and the frozen
   policy fingerprint.
2. Enumerate every Jira item in the candidate release and every required branch
   and PR from the configured GitFlow topology. Compare membership, Fix
   Version, ticket keys, branch bases, ancestry, and exact revisions.
3. For every Jira item, locate the configured QA Run or equivalent and verify
   terminal pass, exact ticket, exact build, exact tested revision, environment,
   tenant/fixture matrix, and acceptance evidence.
4. Review the complete exact-head diff against all effective Auto-Dev rules,
   including nested source rules and migrations/configuration/rules/generated
   files. Consume performance, configuration-composition, security/tenancy,
   dependency, and compatibility receipts.
5. For changed runtime payload boundaries, inspect every rule, template,
   integration, and tenant configuration consumer. Verify the consumer and
   tenant impact matrices, actual evaluator behavior for legacy and canonical
   shapes, compatibility/migration decision, and non-empty expected result.
   A request that returns success with zero formerly-valid results is a blocker.
6. Verify artifact provenance, rollback/recovery, observability/alerting,
   runbook ownership, and post-release verification. Require the stable shared
   check IDs, a non-empty per-Jira QA run matrix, and a passing independent
   review receipt. Unknown or unavailable evidence is a blocker under the
   configured policy.
7. Record one immutable `production_release_validation` receipt containing the
   check matrix, provider readbacks, exact revisions, policy fingerprint,
   evidence references, decision, and blocker owner when blocked.

Adding a future check means adding a Markdown `Production Release Check` at the
appropriate policy layer; the workflow engine does not need to change.
