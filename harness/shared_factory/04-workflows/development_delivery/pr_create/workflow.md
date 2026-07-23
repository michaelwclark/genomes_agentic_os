# PR Create

## Outcome

Every project-required pull-request target is accounted for before Review Self
as `pr_required`, `already_equivalent`, or `not_applicable`, with provider
readback and no duplicate PR.

## Flow

1. Require completed Readiness, Develop, and Document evidence.
2. Snapshot tracker authority, project configuration, registry freshness,
   source SHA, and live provider PRs.
3. Resolve the F2 topology and fail closed on ambiguous or mismatched targets.
4. Plan only missing targets; default to no writes.
5. On approved apply, create the exact branches/PRs through Create Artifacts.
6. Read back every target and write the canonical family receipt.
7. Record the stable lower-level `release_propagation` receipt; the Auto-Dev
   projection exposes it as `pr_create` and hands the family to Review Self.

`gitflow-pr-create` and Auto-Dev Release Propagation are compatibility adapters
to this workflow. They do not own policy or state.
