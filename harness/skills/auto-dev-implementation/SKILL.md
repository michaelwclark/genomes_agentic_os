---
name: auto-dev-implementation
description: Implement a planned Auto-Dev task inside its isolated worktree using the effective root/domain/project/invocation engineering standards, bounded changes, risk-based tests, and receipt-backed local validation. Use when asked to code, fix, build, or continue implementation after readiness even if Auto-Dev is not named.
---

# Auto-Dev Implementation

Operate only the selected task worktree and pinned policy receipt.

1. Read `develop status`, task state, plan, effective policies, and repo-local
   instructions. Confirm state is `planned` or resume `implementing`.
2. Transition to `implementing` with the plan/worktree receipt.
3. Make the smallest cohesive change. Preserve framework, tenancy, security,
   migration, API, UI, and compatibility requirements from policy.
4. Run the required static/unit/integration/end-to-end layers. Classify code
   failures separately from unavailable environments; never turn a failing test
   into an infrastructure skip.
5. Store compact `development-stage-evidence/v1` command/result receipts and
   record the completed stage to `local_validation`:

```bash
agentic-os develop stage <state.json> --stage implementation \
  --receipt implementing=<implementation-receipt.json> \
  --receipt local_validation=<validation-receipt.json> \
  --idempotency-prefix <run:ticket:implementation>
```

Do not create provider artifacts directly. PRs, tracker comments, and reports
must use Auto-Dev Create Artifacts.
