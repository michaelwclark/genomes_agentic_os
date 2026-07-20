---
name: auto-dev-release-propagation
description: Determine and execute the configured release, hotfix, backport, forward-port, or sibling-PR topology for a ready Auto-Dev task, with exact branch/tag/version evidence and a durable propagation receipt. Use for release-family and branch-propagation work even if Auto-Dev is not named.
---

# Auto-Dev Release Propagation

1. Load the effective `gitflow_topology` receipt and tracker Fix Version or
   equivalent release authority. Never infer targets from branch names alone.
2. Compare required targets with existing commits/PRs/tags and reuse existing
   work. Prevent duplicate or inverted PR families.
3. Create each required branch/PR through the project adapter; render PR bodies
   with Auto-Dev Create Artifacts.
4. Validate each target independently and store target/head/base/readback.
5. Create a typed `development-stage-evidence/v1` release-propagation receipt
   and record the stage without changing merge readiness:

```bash
agentic-os develop stage <state.json> --stage release_propagation \
  --receipt release_propagation=<family-receipt.json> \
  --idempotency-prefix <run:ticket:release>
```

No required propagation is a valid result only with an explicit policy-backed
receipt.
