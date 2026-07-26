# GitFlow Topology Drift Proposals

## Status

- Mode: `disabled_proposal_only`
- Schedule: none
- External writes: forbidden
- Promotion: explicit operator approval plus a separate automation change

## Purpose

Detect when branch-registry changes make an existing tracker-key PR family
incomplete. The automation runs the F2 resolver and emits proposals for M4; it
never creates branches, pull requests, comments, labels, or tracker changes.

## Inputs

- Routed project profiles.
- Fresh branch-registry snapshots.
- Open and recently merged PR families grouped by exact tracker key.

## Output

Proposal receipts under the active work item or configured program artifact
root. Each row contains project, tracker key, source SHA, missing target,
reason, idempotency key, and the exact `/gitflow-pr-create` plan command.

## Guardrails

- No timer or event trigger ships enabled.
- Missing/stale registry data produces a blocker, not a proposal.
- Duplicate idempotency keys collapse to one proposal.
- Applying a proposal is always a separate operator-authorized M4 run.
