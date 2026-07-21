---
name: auto-dev-closeout
description: Reconcile tracker and provider state, preserve follow-ups, and close canonical delivery after merge and deployment decisions have verified receipts.
---

# Auto-Dev Closeout

1. Read `autodev.json`, delivery state, live tracker/provider state, and the
   verified Merge and Deploy receipts. Delegate missing merge work to
   Auto-Dev Merge and missing deployment work to Auto-Dev Deploy.
2. Render tracker/comment/status/closeout output through Create Artifacts;
   verify provider readback.
3. Record the item-scoped cleanup decision, protected resources, residual risk,
   and follow-up. Do not remove worktrees, runtimes, or the work-item packet;
   Auto-Dev Health performs that receipt-first lifecycle maintenance afterward.
4. After the task is at `post_deploy_validation`, create a typed
   `development-stage-evidence/v1` completion receipt with
   `evidence.closeout_verified: true`, then record only the final reconciliation
   transition:

```bash
agentic-os develop stage <state.json> --stage closeout \
  --receipt delivery_complete=<closeout-receipt.json> \
  --idempotency-prefix <run:ticket:closeout>
```

The Development Delivery closeout recorder remains the atomic engine step that
verifies provider reconciliation and the cleanup decision. It accepts only a
task already at `post_deploy_validation`; it cannot backfill Merge or Deploy.
`delivery_complete` makes the item eligible for `/auto-dev-health`; it does not
claim local resource cleanup has already happened.
