---
name: auto-dev-deploy
description: Deploy or monitor an exact merged artifact through the project's canonical deployment owner, verify the target environment and deployed behavior, and record receipt-backed results.
---

# Auto-Dev Deploy

1. Resolve `environment_access` plus project deployment policy. Verify the
   environment, tenant/account, region, VPN/auth, exact commit/version/artifact,
   provider owner, and required approval.
2. Reuse the project's canonical deploy program or pipeline. Do not reproduce
   cloud commands or credentials in this shared skill.
3. Monitor the normal provider signal quietly. Distinguish code, provider, and
   access/infrastructure failures.
4. Validate deployed version and required user-visible behavior/telemetry. A
   completed job is not deployment proof.
5. Write one `development-stage-evidence/v1` receipt per delivery transition,
   then record Deploy independently:

```bash
agentic-os develop stage <state.json> --stage deploy \
  --receipt deployment_pending=<deployment-policy.json> \
  --receipt deploying=<deployment-run.json> \
  --receipt post_deploy_validation=<deployment-readback.json> \
  --idempotency-prefix <run:ticket:deploy>
```

Completed post-deploy evidence must name the exact merged
`deployed_revision`, immutable `artifact_ref`, target `environment`, and set
`readback_verified: true`. If deployment does not apply, every skipped
transition uses typed `not_required` evidence with `policy_ref`; the final
receipt also sets `deployment_applicable: false`.

Tracker/provider reconciliation remains Auto-Dev Closeout work. Receipt-first
local resource removal and the finished-packet move remain Auto-Dev Health work.
