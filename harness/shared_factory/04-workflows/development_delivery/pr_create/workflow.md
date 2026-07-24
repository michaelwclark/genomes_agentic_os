# PR Create

## What this does

Resolves, creates or reuses, and provider-verifies the complete pull-request
family required by the project before Review Self begins. This is the only
Auto-Dev workflow allowed to choose pull-request targets, create target
branches, or open and retarget pull requests.

## Manual run

Use `/auto-dev-pr-create`. `/gitflow-pr-create` and
`/auto-dev-release-propagation` are compatibility aliases that delegate here;
they do not own another target or provider policy.

## Inputs

- completed Readiness, Develop, and Document receipts for the exact work item
  and source revision;
- live tracker release/fix-version authority;
- effective project GitFlow topology and fresh version registry;
- current source branch/SHA and provider-read existing pull requests;
- Create Artifacts contract, apply authority, and stable idempotency key.

## Outputs

- complete target matrix with one disposition per required target;
- provider-read pull-request family receipt bound to the source revision;
- lower-level `release_propagation` compatibility receipt;
- synchronized Auto-Dev `pr_create` projection.

## States

`target_resolution -> planned -> applying -> provider_readback ->
family_complete|blocked`. A dry run ends at `planned`; provider mutation
requires the configured apply authority.

## Steps

1. Require terminal, receipt-backed Readiness, Develop, and Document evidence.
2. Snapshot tracker authority, project configuration, registry freshness,
   source SHA, and live provider pull requests.
3. Resolve the complete target matrix and fail closed on ambiguous,
   contradictory, or stale authority.
4. Classify every target as `pr_required`, `already_equivalent`, or
   `not_applicable`; plan only missing provider actions.
5. On authorized apply, create the exact branches and pull requests through
   Create Artifacts.
6. Read every target back from the provider and reject duplicates, wrong
   bases, or revision drift.
7. Store the packet-local canonical family receipt.
8. Invoke the lower-level `release_propagation` compatibility recorder with
   that exact receipt and synchronize `autodev.json` as completed
   `pr_create`.

## Validations

- Every active predecessor is terminal and bound to the same work item and
  source revision.
- Tracker authority, GitFlow topology, and registry agree on the exact target
  family.
- Every required target has exactly one policy-backed disposition and no
  duplicate pull request.
- Created or reused pull requests have provider-read repository, source,
  target, head revision, and linkage evidence.
- External text is scrubbed of secrets, private links, and local filesystem
  paths.
- Packet-local receipts are immutable, hash-bound, and idempotent.

## Success modes

- `planned`: dry-run target matrix and proposed provider actions are complete;
  no provider write occurred.
- `family_complete`: every required target has a provider-verified pull request
  or typed policy-backed disposition, and the compatibility recorder exposes
  the same evidence as Auto-Dev `pr_create`.

## Failure modes and recovery

- Missing predecessor: return to the owning earlier Auto-Dev stage.
- Missing or contradictory tracker/topology authority: block on the exact
  unanswered target question.
- Source or target drift: refresh provider state and re-plan before any write.
- Provider unavailable: preserve the plan and partial readbacks, then resume
  only the unverified targets with the same idempotency keys.
- Partial family or duplicate pull request: preserve completed targets, repair
  the exact mismatch, and re-read the whole family.

## Events and receipts

Emit `pr_create.planned`, `pr_create.target.created`,
`pr_create.target.reused`, `pr_create.target.failed`, and
`pr_create.family.completed`. Store predecessor descriptors, authority
snapshots, target matrix, provider actions/readbacks, source revision, family
receipt, and the lower-level compatibility receipt.

## Cleanup and handoff

Hand the exact provider-read family receipt to Review Self. Keep only
task-owned branches, worktrees, and watchers required by open family members;
Auto-Dev Health removes reconstructable resources after terminal delivery.
PR Create does not review, approve, merge, release, deploy, or close the item.
