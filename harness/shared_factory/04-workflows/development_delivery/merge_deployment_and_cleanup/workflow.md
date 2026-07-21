# Merge, Deployment, and Cleanup

## Flow

![Auto-Dev Development Delivery stages](../../../00-programs/auto_dev/assets/development-delivery-stages.svg)

## What this does

Observes the authoritative merge, updates the tracker, watches configured
deployment and post-deploy signals, then records the provider reconciliation
and cleanup decision. Auto-Dev Health performs the later resource cleanup and
finished-packet move without losing resumability.

## Manual run

Use `/auto-dev-merge`, `/auto-dev-deploy`, and `/auto-dev-closeout` separately,
recording each verified boundary with `agentic-os develop stage <state.json>
--stage <merge|deploy|closeout> ...`.

## Inputs

- Ready/merged PRs, merge policy, tracker workflow mapping, deployment adapter,
  environment health checks, release target matrix, work-item/worktree registry,
  and retention configuration.

## Outputs

- Merge and tracker readbacks, deployment/health receipts, rollback or incident
  reference when needed, compact final summary, and an item-scoped cleanup
  decision ready for Auto-Dev Health.

## States

`ready_for_merge -> merged -> deployment_pending -> deploying ->
post_deploy_validation -> delivery_complete`. When no deployment is configured,
the Deploy stage still records policy-backed `not_required` evidence for
`deployment_pending`, `deploying`, and `post_deploy_validation`; it never skips
state boundaries without receipts.

## Steps

1. Re-read required checks/reviews and apply merge policy. Never auto-merge when
   policy is `never_auto`; observe a human merge instead.
2. Read the merged pull request back from its provider. Record the merge SHA,
   provider-read source head SHA, provider, stable pull-request reference, and
   `readback_verified: true`; require the source head to equal the reviewed
   `subject_revision`. Update tracker status/links idempotently.
3. Resolve configured deployment target(s), watch rollout/job status quietly,
   and run bounded post-deploy health/smoke validation.
4. On regression, stop propagation and execute or recommend the configured
   rollback; create/attach incident evidence without hiding the failed deploy.
5. Mark implementation work non-active after merge; keep a small deployment
   monitor receipt until delivery is terminal.
6. Produce one final summary linking decisions, test/PR/release/deploy evidence;
   promote durable learnings and record the cleanup decision.
7. Hand the `delivery_complete` task to Auto-Dev Health. Do not remove the
   worktree, target-local runtime, active projection, or durable packet here.

## Validations

- The completed typed Merge receipt contains an authoritative `merge_sha`, a
  provider-read `source_head_sha` equal to the reviewed `subject_revision`, the
  provider and pull-request reference, and `readback_verified: true`; all
  required source/release PRs are accounted.
- Tracker writeback was read back and matches configured terminal state.
- Deployment target/version includes the merged artifact and health checks pass,
  or a verified `not_required` decision exists.
- Final summary contains acceptance-criteria outcome and exact durable receipts.
- The cleanup decision identifies registered task-owned resources and protected
  holds. Health independently audits receipts and performs any safe removal.

## Success modes

- `delivery_complete`: merge, required propagation/deployment, health, tracker,
  summary, and cleanup decisions are receipt-backed. Physical cleanup is still
  pending Auto-Dev Health.
- `merged_monitoring`: implementation leaves active status after merge while a
  separate bounded deployment monitor remains; this is not implementation work.

## Failure modes and recovery

- Merge blocked: remain `ready_for_merge` and report exact policy/check/review
  gate; re-read after the gate changes.
- Tracker writeback unavailable: keep merge truth, retry idempotently, and alert
  without reverting code.
- Deployment failed/unhealthy: stop, capture rollout evidence, rollback when
  configured and safe, open incident/repair task, then resume monitoring.
- Cleanup conflict/dirty worktree: record the hold for Auto-Dev Health; do not
  delete or hide the resource.
- Summary/projection unavailable: complete durable local closeout first and
  retry projection; projection failure does not erase delivery evidence.

## Events and receipts

Emit `pr.merged`, `tracker.updated`, `deployment.started|failed|healthy`,
`rollback.started|completed`, and `delivery.completed`. Store merge snapshot,
tracker readback, deploy version, health commands/results, incident/rollback
links, cleanup decision, and final summary. Health owns the later finished-
lifecycle and item-scoped cleanup receipts.

## Cleanup and handoff

Leave the packet in its current lane and hand its exact receipt manifest,
resource identities, protected holds, and cleanup decision to Auto-Dev Health.
Health carries the Merge receipt forward exactly: its terminal-authority
provider/reference match the Merge receipt provider/pull-request fields, and
its terminal revision matches `merge_sha`.
Health retains compact state, final summary, decision/test/PR/deploy receipts,
and promoted learnings before it moves the packet to finished and removes only
reconstructable task-local resources.
