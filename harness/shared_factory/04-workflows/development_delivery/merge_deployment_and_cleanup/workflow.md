# Merge, Deployment, and Cleanup

## What this does

Observes the authoritative merge, updates the tracker, watches configured
deployment and post-deploy signals, then compacts durable evidence and removes
ephemeral work without losing resumability.

## Inputs

- Ready/merged PRs, merge policy, tracker workflow mapping, deployment adapter,
  environment health checks, release target matrix, work-item/worktree registry,
  and retention configuration.

## Outputs

- Merge and tracker readbacks, deployment/health receipts, rollback or incident
  reference when needed, compact final summary, archived work item, and cleaned
  worktree/run artifacts.

## States

`ready_for_merge -> merged -> deployment_pending -> deploying ->
post_deploy_validation -> delivery_complete`. When no deployment is configured,
`merged -> post_deploy_validation` records `not_required` evidence.

## Steps

1. Re-read required checks/reviews and apply merge policy. Never auto-merge when
   policy is `never_auto`; observe a human merge instead.
2. Read back merge SHA/time and update tracker status/links idempotently.
3. Resolve configured deployment target(s), watch rollout/job status quietly,
   and run bounded post-deploy health/smoke validation.
4. On regression, stop propagation and execute or recommend the configured
   rollback; create/attach incident evidence without hiding the failed deploy.
5. Mark implementation work non-active after merge; keep a small deployment
   monitor receipt until delivery is terminal.
6. Produce one final summary linking decisions, test/PR/release/deploy evidence;
   promote durable learnings and archive the work item.
7. Remove merged clean worktrees and expire raw logs according to retention.

## Validations

- Merge SHA is authoritative and all required source/release PRs are accounted.
- Tracker writeback was read back and matches configured terminal state.
- Deployment target/version includes the merged artifact and health checks pass,
  or a verified `not_required` decision exists.
- Final summary contains acceptance-criteria outcome and exact durable receipts.
- Worktree cleanup is limited to registered, merged, task-owned paths; active,
  dirty, unmerged, or `REOPEN.md`-guarded worktrees are preserved.

## Success modes

- `delivery_complete`: merge, required propagation/deployment, health, tracker,
  summary, and cleanup decisions are receipt-backed.
- `merged_monitoring`: implementation leaves active status after merge while a
  separate bounded deployment monitor remains; this is not implementation work.

## Failure modes and recovery

- Merge blocked: remain `ready_for_merge` and report exact policy/check/review
  gate; re-read after the gate changes.
- Tracker writeback unavailable: keep merge truth, retry idempotently, and alert
  without reverting code.
- Deployment failed/unhealthy: stop, capture rollout evidence, rollback when
  configured and safe, open incident/repair task, then resume monitoring.
- Cleanup conflict/dirty worktree: preserve files, emit attention item, retry
  after ownership is resolved.
- Summary/projection unavailable: complete durable local closeout first and
  retry projection; projection failure does not erase delivery evidence.

## Events and receipts

Emit `pr.merged`, `tracker.updated`, `deployment.started|failed|healthy`,
`rollback.started|completed`, `work_item.archived`, `worktree.cleaned|preserved`,
and `delivery.completed`. Store merge snapshot, tracker readback, deploy version,
health commands/results, incident/rollback links, cleanup decision, and final
summary.

## Cleanup and handoff

Archive the work item after merge and move ongoing deployment observation into a
small monitoring queue. Retain compact state, final summary, decision/test/PR/
deploy receipts, and promoted learnings. Prune raw logs and remove clean merged
worktrees after the configured grace period.
