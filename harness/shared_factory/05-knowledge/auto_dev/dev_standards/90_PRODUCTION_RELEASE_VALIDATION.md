# Auto-Dev Production Release Validation

This is a blocking pre-merge release-candidate review. It validates the
complete Jira/GitHub release family and the exact revision that will be merged,
not merely the PR that happens to be open.

## Check bundle contract

Each effective policy layer may add a Markdown file containing a `Production
Release Check` section. A check is identified by a stable `check_id`, declares
its required inputs, procedure, pass criteria, and receipt fields, and is
blocking by default. Project/domain files may narrow scope or add required
variants; they may not weaken a shared blocking check without a typed policy
decision and independent review.

## Required shared checks

1. **Release membership and Fix Version** — enumerate every Jira item and every
   GitHub branch/PR in the configured build family. Every item must have the
   authoritative Fix Version, every required target branch must be represented,
   and no unrelated or missing item may be silently included.
2. **Exact source identity** — compare Jira, GitHub PR base/head/merge SHA,
   branch ancestry, build/version registry, and the candidate artifact. Any
   unknown, stale, dirty, or mismatched identity blocks release.
3. **Matching QA Run** — every Jira item has a terminal passing QA Run (or the
   configured equivalent) for the exact ticket, candidate build, tested commit,
   environment, tenant/fixture matrix, and acceptance path. A Jira status,
   comment, or stale test run is not QA evidence.
4. **Whole-diff policy review** — inspect the complete exact-head diff against
   every effective Auto-Dev policy layer, including nested source rules,
   migrations, configuration/rules, generated files, tests, and operational
   changes. Record the frozen policy fingerprint and reviewer receipt.
5. **Risk gates** — consume all applicable performance, configuration
   composition, migration, security/tenancy, dependency, and compatibility
   gates. Unknown or unavailable evidence is blocking for a production release.
6. **Release operations** — verify artifact provenance, dependency ordering,
   rollback/recovery, observability/alerting, runbook ownership, and a
   post-release verification plan. A green CI run alone is never release proof.
7. **Runtime consumer contracts** — for every changed request, serializer,
   canonical payload, persistence, rule, template, or configuration boundary,
   verify the complete consumer inventory, tenant impact matrix, legacy and
   canonical-shape evaluator tests, compatibility strategy, and runtime
   readback. A valid request must not become a silent empty result because a
   consumer receives a different shape.

The receipt must include a non-empty `check_matrix` containing stable checks
`jira_github_alignment`, `exact_release_identity`, `qa_per_jira`,
`whole_diff_policy`, `risk_gates`, and `artifact_rollback_observability`. It
must also include `runtime_consumer_contracts`, a non-empty `qa_runs` list,
non-empty `consumer_contract_matrix` and `tenant_impact_matrix` when that
check applies, and a passing independent review receipt. Domain and project
Markdown may add check IDs and evidence, but may not remove these shared
checks.

## Completion rule

The workflow returns `ready_for_merge` only when every required check has a
provider-qualified, exact-revision receipt. Otherwise it returns one exact
blocker and the owning action. It performs no Jira, GitHub, merge, deploy, or
customer-visible write.
