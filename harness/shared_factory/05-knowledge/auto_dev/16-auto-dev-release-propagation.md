# Auto-Dev: release propagation

This is a compatibility policy note. `/auto-dev-release-propagation` delegates
to `/auto-dev-pr-create` family mode. The canonical PR Create policy selects
targets, creates or reuses PRs, and records family completeness; this file must
not introduce a second targeting or provider contract.

## Inputs

- canonical provider-read PR Create family receipt;
- exact work item, task, repository, provider, and source revision;
- packet-local evidence snapshot and SHA-256;
- stable idempotency key and `autodev.json` linkage.

Legacy release, hotfix, backport, forward-port, and sibling-PR arguments are
passed through to PR Create family mode. This policy does not interpret them.

## Compatibility behavior

1. Delegate the invocation to `/auto-dev-pr-create` before resolving any target
   or performing a provider action.
2. Require the canonical PR Create family receipt and exact provider readback.
3. Verify work-item, task, repository, provider, family, and revision identity.
4. Snapshot the evidence inside the canonical work-item packet.
5. Record the stable Development Delivery `release_propagation` receipt
   idempotently.
6. Synchronize `autodev.json` so the same receipt appears as completed
   `pr_create`.
7. Read back the stored receipt and projection.

This compatibility policy never resolves target branches, creates or
cherry-picks branches, opens or retargets pull requests, watches checks, or owns
GitFlow decisions.

## Done criteria

The recorder completes only when the packet-local compatibility receipt and
Auto-Dev `pr_create` projection reference the same canonical PR Create family
evidence. Missing family evidence returns to PR Create; identity, hash, or
idempotency mismatch blocks without overwriting prior proof.

This compatibility flow does not review, approve, or merge pull requests.
Review Self, Finalize, and Merge retain those authorities.
