# Auto-Dev: develop

Use `/auto-dev-develop`; it delegates to the canonical
`/auto-dev-implementation` owner without creating another state packet. This
stage implements the approved scope and proves the change locally.

## Required inputs

- an implementation-ready tracker item and acceptance behavior;
- a completed Readiness result with exact domain, project, repository, base
  branch, registered isolated worktree, and frozen policy fingerprint;
- repository instructions plus effective `dev_standards`, `qa_gates`,
  `gitflow_topology`, and environment policy;
- relevant investigation, design, compatibility, migration, and data evidence.

Do not begin in the main checkout, an unregistered worktree, the wrong
repository, or a base branch chosen from habit instead of ticket/release truth.

## Implementation behavior

1. Reproduce or characterize the current behavior when practical.
2. Trace the smallest responsible boundary before editing.
3. Make the smallest cohesive change that satisfies the acceptance behavior.
4. Follow existing architecture and naming; introduce a new abstraction only
   when it removes real duplication or enforces a needed boundary.
5. Preserve backward compatibility unless the tracker explicitly authorizes a
   breaking change and its rollout is defined.
6. Treat schema/data migrations, permissions, tenancy, concurrency, retries,
   idempotency, failure handling, observability, and dependency changes as
   explicit risk areas when applicable.
7. Add or update focused tests with the implementation. Prefer tests that
   observe behavior over tests coupled to private implementation details.
8. Update code-adjacent documentation and configuration examples when behavior
   or operator expectations changed.
9. Review the diff for accidental churn, generated files, secrets, debug code,
   unrelated edits, and user-owned changes.

Delegate only disjoint modules or bounded research/tests to subagents. Assign
file ownership, warn about concurrent edits, and integrate against the complete
diff. The coordinating agent owns architecture and acceptance behavior.

## Validation

Run the smallest complete risk-appropriate triangle:

- focused tests for the changed behavior;
- affected module/package checks such as lint, type, schema, or integration
  validation;
- the broader project gate required by policy when risk warrants it.

Record exact commands, revision, outcomes, skipped checks, and environment in
typed evidence. An unavailable service, broken local runtime, or missing access
is an infrastructure/environment blocker or an explicitly authorized CI
fallback. It is not a passing test. Diagnose a failure before rerunning; do not
blindly retry more than once without new evidence.

## Done criteria

Development ends at receipt-backed `local_validation`: the scoped change is
implemented in the registered worktree, focused evidence passes, known limits
are explicit, and the work log explains the change and next stage. This does
not imply a pull request, independent review, merge, release, deployment, or
production result.
