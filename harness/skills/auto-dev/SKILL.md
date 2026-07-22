---
name: auto-dev
description: Route software work through the canonical plain-English Auto-Dev family, either end to end with Auto-Dev Everything or as one named workflow, using one work item and autodev.json projection over the Development Delivery engine.
---

# Auto-Dev

Auto-Dev is the operator-facing family. `development_delivery` is its only code
delivery state/worktree/recovery engine. `<work-item>/autodev.json` is the
cross-workflow resume projection and points to that engine. Never start a second
state packet under `artifacts/auto-dev/` for a new run.

## Canonical work-item lookup

Resolve a matching packet directly under the owning project's `work-items/`
root before creating anything. If the ticket has returned, also search
`work-items/99-archived/` and preserve the prior packet as history. Legacy
`01-intake`, `02-active`, and `03-complete` lanes are import/read surfaces,
not destinations for new Auto-Dev packets.

## Genomes Agentic OS maintainer profile

When the routed project is `genomes_agentic_os`, load its generated
`config/development.yml`, `config/workflows.yml`, and `config/validation.yml`.
The configured `auto_dev_everything` workflow owns the complete sequence:
Groom, Detective, Create Artifacts, Readiness, Develop, Document, PR Create,
Review Self, Review Others, QA, Finalize, Merge, Release, Deploy, Closeout, and
Health. Generated configurations that still say `release_propagation` use that
name as a compatibility alias for the PR Create boundary; it is not a separate
or later stage.

This profile requires Linear grooming, a fresh install plus two additive
installs at `~/agentic_os_qa`, exact-head CI, gated squash merge, a version/tag
and GitHub release after merge, then repository, verified Genome's Notion, and
Clark's Consulting documentation projections. Claude Review Self is preferred
but non-blocking when its receipt records that the reviewer was unavailable.

> Compatibility alias: all new generic Agentic OS programming jobs start with
> `agentic-os develop start <domain> <project> <ticket> [<ticket> ...] --apply`
> and follow the `development_delivery` program. The contracts below remain
> available for existing Auto-Dev runs and provider adapters during migration.

## Route by intent

- Uncertain cause, reported bug, failed QA, log, alert, or RCA: start with
  `$auto-dev-detective`.
- Jira, Linear, Notion, Confluence, GitHub, Slack, RCA, report, PR body, review,
  status, or closeout output: use `$auto-dev-create-artifacts`.
- Code delivery: start/resume `agentic-os develop`, then use the matching stage
  skill below.
- Full delivery: use `$auto-dev-everything`.
- One friendly stage: `agentic-os auto-dev groom|investigate|create|readiness|
  develop|document|pr-create|review-self|review-others|qa|finalize|merge|release|
  deploy|closeout|health ...` and the same-named skill. `release-propagation` is
  a compatibility alias for `pr-create`.

## Canonical delivery path

1. `$auto-dev-grooming`
2. `$auto-dev-detective`
3. `$auto-dev-create-artifacts`
4. `$auto-dev-readiness`
5. `$auto-dev-implementation` / `$auto-dev-develop`
6. `$auto-dev-document`
7. `$auto-dev-pr-create`
8. `$auto-dev-review-repair` / `$auto-dev-review-self`
9. `$auto-dev-review-others`
10. `$auto-dev-qa`
11. `$auto-dev-finalize`
12. `$auto-dev-merge`
13. `$auto-dev-release`
14. `$auto-dev-deploy`
15. `$auto-dev-closeout`
16. `$auto-dev-health`

That order is exact. Every stage is independently callable, but a later
external stage on an Auto-Dev item requires all predecessors to be terminal and
receipt-backed. Everything records all sixteen rows; policy-backed
inapplicability is a typed terminal decision, not an omitted step.

Each stage is manually callable from chat and performs the work before
`agentic-os develop stage` records typed, preflighted receipts. The stage
recorder does not execute or invent provider actions.

## Policy composition

Before each stage, load the effective 1-N Markdown bundle:

```text
root → domain → project → invocation
```

- program and access: `auto_dev`, `environment_access`;
- development: `dev_standards`, `qa_gates`, `gitflow_topology`;
- investigation: `investigation-config`;
- output: `artifact-config`.

Adding a matching Markdown file changes the next run without changing the
shared workflow. Active Development Delivery runs remain pinned to their policy
fingerprint and report later drift.

## Hard gates

- Multi-repository projects require an explicit repository id.
- Ticket/release authority selects the base branch; pass `--base-branch` rather
  than changing project defaults for one run.
- Environment-scoped causal code claims require a deployed-version receipt.
- Tests, review, checks, provider writes, merge, deployment, and closeout need
  exact evidence/readback; a transition string is not evidence.
- `not_required` needs `auto-dev-stage-policy-decision/v1` bound to the work
  item identity, exact frozen policy fingerprint/source/hash, reason, decision
  maker, and time. The policy and decision are copied into immutable
  packet-local proof. A plain `policy_ref` assertion is rejected.
- Provider-read `author_identity` is classified against the frozen
  `task.authorship.ours` list. Finalize is readiness-only for `ours`; Review
  Others is clean review-only for `others`; Merge accepts only the correct
  hashed owner receipt and the same provider/PR/repository/base/revision/author
  chain.
- Health starts cleanup only after the final receipt audit passes. It respects
  reopen/hold markers, requires the ten canonical Health receipt kinds and full
  packet manifest, and never deletes the durable work-item packet. Runtime
  identity/commands are exact and domain/project/worktree-bound; the fresh
  immediate readback exits 0 only when that runtime is absent. Worktree removal
  uses the exact id/path/branch/HEAD with no force, metadata sweep, host-wide/all
  selector, shared runtime, or guessed identity.
- External writes, merge, deployment, production, destructive, billing, legal,
  and customer-visible operations retain their routed approval gates.
- Keep raw logs, secrets, customer data, local paths, private Notion links, and
  OS internals out of external output.

## Compatibility

`harness/skills/auto-dev/scripts/auto_dev_state.py`, its fixtures, and the old
`artifacts/auto-dev/state.json` model remain compatibility-only for runs already
created by that engine. Do not start new runs there. Migration/retirement is
tracked in the Auto-Dev `ARCHIVE_SOON.md` ledger.

Health is manually runnable. Auto-Dev does not enable a cleanup schedule or
automation; a future adapter must invoke the same state and receipt contract.

For several tickets, Everything creates one packet and `autodev.json` per
ticket. Resume only the selected packet with `--state`. A finished packet is
immutable history; use `agentic-os auto-dev reopen --state <finished-packet>
--run-id <new-id> --reason "<why>" --stage qa --apply` to create the receipt,
fresh active packet, delivery run, worktree, and runtime registration. Never
edit the old packet, reopen it with a plain work-state change, or reuse its
retired resources.
