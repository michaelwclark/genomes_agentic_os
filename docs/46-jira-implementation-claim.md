# Jira implementation claim

Content readiness answers whether the ticket is specific enough to implement.
It does not replace the owner's required assignment, workflow, or release
updates. Perform those authorized updates before editing source or tests, or
delegating implementation. A creation acknowledgement or local plan is not
provider readback.

For LOS Jira, require the verified operator as both Assignee and Developer,
status `In Progress`, and the requested Fix Version. Developer and Assignee are
separate fields. Resolve their IDs through the domain identity registry and
the provider. If a write fails or access is unavailable, preserve the precise
blocker and stop source edits.

The shared read-only gate is `harness/bin/agentic-os-jira-claim-check`. It uses
the authenticated ACLI session, verifies its site before reading the exact
issue with `--fields '*all'`, and returns bounded JSON. It never assigns,
transitions, or changes versions, and does not echo provider error output.

```sh
python3 harness/bin/agentic-os-jira-claim-check \
  --ticket FLYWL-1234 --site venturesgo.atlassian.net \
  --account-id '<verified Michael Clark account ID>' \
  --developer-field '<verified Developer custom field ID>' \
  --fix-version '10.1'
```

Exit 0 means a fresh `jira-implementation-claim/v1` receipt passed. Exit 2
blocks implementation. Without `--fix-version`, the gate still requires a
nonempty Fix Version; supply the option whenever the user specifies a release.
Run again on resume and retain the receipt beside the implementation plan.

Configure `tracker.authority` and `tracker.implementation_gate` in the
project's `config/development.yml`; the development profile template contains
an argv example. The engine replaces `{ticket}` without invoking a shell and
runs the gate at both `worktree_ready -> planned` and `planned -> implementing`.
LOS Jira tasks cannot silently omit the command. A failed gate leaves task
state unchanged. A passing receipt is bound to the issue/site, must be fresh,
and is retained in `state.implementation_claim`.

This is an admission check in the shared delivery engine, not a sandbox on
arbitrary editor tools. Both Claude and Codex must use the readiness and
implementation entry points. The implementation skill also calls the live
gate before the first edit or worker dispatch, including resumed work. A
historical generic plan cannot prove the current Jira claim.

The operational claim gate is read from current project configuration so
adding a stricter gate also protects previously created tasks. This does not
replace or weaken their frozen engineering policies. Other trackers retain
their existing project lifecycle policy.

Owner: Auto-Dev Readiness / Development Delivery. Source definitions include
the shared skills, profile template, CLI engine, and gate. Install the matching
runtime and helper together; record a scoped local hotfix separately from a
published release. Changes to installed project policy are operator-owned.

Validation: `tests/test_jira_implementation_claim.py` checks the original
unassigned/Requirements failure, partial updates, site/ticket mismatches,
missing versions, malformed responses, and provider failures.
`tests/test_development_claim_gate.py` checks admission, immutable state on
failure, ticket-bound receipts, freshness, and unaffected non-Jira tasks.
