---
name: auto-dev-pr-create
description: Canonical Auto-Dev owner for resolving a project-specific 1-N pull-request target matrix, creating only missing branches and PRs, and recording provider-read family completeness before review.
argument-hint: "<ticket-or-state> [--apply]"
---

# Auto-Dev PR Create

Create or prove the complete pull-request family without duplicating GitFlow
policy or review behavior.

## Contract

1. Reuse the canonical work item and require completed Readiness, Develop, and
   Document receipts when this is part of Auto-Dev.
2. Snapshot tracker release authority, effective project profile, fresh branch
   or version registry state, source branch/SHA, and existing open or merged
   PRs. A caller-supplied base branch is a candidate, never authority.
3. Resolve the target matrix through the effective `gitflow_topology` policy.
   For Jira-backed LOS work, require explicit `fixVersions` plus the current LOS
   version registry before selecting hotfix/release/develop targets.
4. Classify every configured target as `pr_required`, `already_equivalent`, or
   `not_applicable`. Fail closed on a missing required target, stale registry,
   unresolved alias, ambiguous source, or an unreceipted manual mismatch.
5. Render and apply GitHub artifacts through `$auto-dev-create-artifacts`.
   The effective pull-request contract must include `Linked Work` with a visible
   Markdown hyperlink to its Jira, Linear, or GitHub work item; a bare ticket
   key never satisfies the contract. Re-read the provider immediately before
   every write and after every result. Existing open or merged equivalents are
   idempotent success.
6. When `qa.assessment.always_create` is enabled, create or reuse one Jira QA
   Automation Assessment subtask under the root Jira after the application PR
   opens. Read it back and bind an `auto-dev-qa-assessment/v1` receipt—with Jira
   issue key, root parent key, and `readback_verified: true`—inside the PR-family
   evidence. PR Create cannot finish without that receipt. This creates the
   assessment, not an automatic claim that Playwright is required.
7. Default to plan-only. `--apply` authorizes only the computed branch pushes,
   PR creations, and the configured QA assessment subtask; it never authorizes
   review approval, merge, release, or deployment.
8. Store the canonical receipt family under
   `artifacts/auto-dev-pr-create/`, then record the compatibility delivery
   receipt with:

```bash
agentic-os develop stage <task-state.json> --stage release_propagation \
  --receipt release_propagation=<family-complete.json> \
  --idempotency-prefix <run:ticket:pr-create>
```

The Auto-Dev projection maps that stable lower-level receipt to the canonical
`pr_create` stage. Hand the exact provider-read family to Review Self.

## Receipts

```text
artifacts/auto-dev-pr-create/
  source-snapshot.json
  topology.json
  plan.json
  write-ledger.jsonl
  family-complete.json
  summary.md
```

Each target is bound to ticket, repository, base branch, source SHA, authority
snapshot, effective-policy fingerprint, action classification, and provider
readback. Compatibility aliases may point to these files but cannot fork them.

## Compatibility

`gitflow-pr-create` delegates here with GitFlow-family defaults.
`auto-dev-release-propagation`, `auto-dev propagate`, and
`auto-dev release-propagation` delegate here in family mode. Neither alias owns
target policy. Review Self consumes the family receipt and does not open PRs.
