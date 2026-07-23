# Auto-Dev: finalize

Use `/auto-dev-finalize` to converge an agent-authored pull-request family and
record a governed merge-readiness decision. Finalize is a decision and evidence
stage. It never executes the merge.

## Entry gates

- the frozen task authorship list classifies the provider-read author identity
  as `ours`;
- Review Self is terminal for the exact current revisions;
- required QA and Release Propagation dispositions are present;
- repository, base branch, tracker key, pull requests, and sibling relationships
  are unambiguous;
- the effective policy fingerprint matches the active task or drift has been
  explicitly reconciled.

If the provider says the author is not ours, route to Review Others and do not
manufacture Finalize authority.

## Convergence audit

1. Discover every related pull request using tracker and configured repository
   identity, not title similarity alone.
2. Re-read each live head, target, mergeability result, required check, review,
   automated finding, human thread, and branch-protection gate.
3. Re-read the live tracker and verify the intended fix, acceptance behavior,
   dev-standard evidence, and required tests are present on every sibling.
4. Check propagation order, migration numbering/order, dependency compatibility,
   generated artifacts, and target-branch-specific behavior.
5. Confirm every actionable finding is fixed and read back as resolved on the
   exact reviewed revision. Do not treat a dismissed or stale thread as proof.
6. Obtain the independent review required by project policy and preserve its
   result. When the project selects Claude CLI Fable, preserve its model and
   session receipt. Actual findings always block readiness.
7. Re-read provider state after the last push or thread resolution so the final
   decision is based on current truth.

Use quiet provider watchers while checks are pending. Do not repeatedly poll in
chat or finalize against an earlier green revision.

## Finalize evidence

For each pull request, record provider, pull-request reference, configured
repository and base, provider-qualified `author_identity`, derived
`author_kind: ours`, immutable reviewed `subject_revision`, checks/reviews,
family relationships, and `readiness_decision`.

The frozen task authorship list—not caller identity or local Git configuration—
determines author classification. Store the completed packet-local receipt and
its SHA-256 so Merge can verify the exact authority without translation.

## Done criteria

Finalize completes as `ready_for_merge` only when the entire required family is
converged at the recorded revisions. Otherwise it records `changes_required` or
an exact provider/policy/approval blocker with the next action.

Merge then applies the project's configured strategy, authority, and target
order. A project-authorized admin bypass can supply provider merge authority;
it cannot bypass checks, acceptance proof, review findings, unresolved threads,
or family parity.

Finalize does not merge, deploy, release, update the tracker to delivered, or
perform lifecycle cleanup. Those authorities belong to later stages.
