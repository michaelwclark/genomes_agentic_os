---
name: auto-dev-closeout
description: Merge, monitor deployment, validate the deployed result, reconcile tracker and provider state, clean worktrees, and close an Auto-Dev task with complete receipts. Use for merge, deployment follow-through, cleanup, finalization, or finish-all-the-way requests even if Auto-Dev is not named.
---

# Auto-Dev Closeout

1. Re-read PR head/target/checks/reviews, merge policy, release propagation, and
   explicit approval. `ready_for_merge` is not merge authorization.
2. Merge only through the configured provider policy and read back merge SHA.
3. Resolve deployed version, monitor deployment, and validate user-visible
   behavior plus required telemetry. If deployment is not required, use an
   explicit policy-backed not-required receipt for each deployment state.
4. Render tracker/comment/status/closeout output through Create Artifacts;
   verify provider readback.
5. Clean or retain worktrees according to policy, reconcile state, and preserve
   residual risk/follow-up.
6. Create typed `development-stage-evidence/v1` receipts. Merge requires
   merge-SHA/provider readback and completion requires closeout verification;
   then record the stage to `delivery_complete`:

```bash
agentic-os develop stage <state.json> --stage closeout \
  --receipt merged=<merge-readback.json> \
  --receipt deployment_pending=<deployment-policy.json> \
  --receipt deploying=<deployment-receipt.json> \
  --receipt post_deploy_validation=<validation-receipt.json> \
  --receipt delivery_complete=<closeout-receipt.json> \
  --idempotency-prefix <run:ticket:closeout>
```

Do not claim complete while checks, merge, deployment, readback, or required
cleanup is pending.
