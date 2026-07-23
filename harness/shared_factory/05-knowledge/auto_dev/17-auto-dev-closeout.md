# Auto-Dev: closeout

Use `/auto-dev-closeout` after the required merge, release, and deployment
outcomes are terminal. Closeout reconciles provider and tracker truth and proves
the delivery boundary. It does not remove worktrees or runtimes; Health owns
cleanup.

## Inputs

- completed typed receipts for every applicable predecessor;
- live pull-request/merge, release/package, deployment/environment, and tracker
  state;
- effective project rules for delivered status, resolution, version, release
  notes, QA handoff, ownership, and post-deploy follow-up;
- outstanding comments, child/sibling items, holds, incidents, or rollout work.

Do not close from local memory or from a green source branch. Read each system
that the project declares part of delivery truth.

## Reconciliation behavior

1. Verify the exact merge authority and `merge_sha` from the provider.
2. Verify every required release artifact and deployment target at its recorded
   version. A policy-backed `not_required` receipt must be present for any
   inapplicable stage.
3. Re-read the tracker item, linked children, fix/release version, ownership,
   status, and required QA/release fields.
4. Identify drift between packet receipts and live provider/tracker state.
   Resolve safe in-scope drift through the owning stage; otherwise record a
   blocker.
5. Render final tracker notes, release/QA handoff, or team-facing summaries
   through Create Artifacts. Obtain required approval, sanitize the audience,
   and verify provider readback.
6. Transition or resolve the tracker only through project-approved lifecycle
   rules and verify the resulting live status.
7. Record known follow-up work as separately owned items. Do not hide unfinished
   scope in a vague closeout note.
8. Update the work log, final summary, remaining risks, owners, links/identifiers,
   and plain-English resume context.

## Delivery-complete evidence

Closeout records the exact work item, provider references, source and merge
revisions, release/deployment dispositions, tracker before/after state,
external artifact receipts, outstanding follow-ups, and
`delivery_complete` judgment.

The stage is complete only when required provider and tracker readbacks agree
with the packet and no unresolved hold contradicts delivery. Be explicit about
the boundary: merged, released, deployed, and tracker-complete are distinct
facts.

Closeout leaves the durable packet and any reconstructable local resources in
place. It hands a receipt-backed `delivery_complete` item to Health for the
final audit, exact cleanup, active-index refresh, and finished-lane move.
