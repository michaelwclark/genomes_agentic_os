---
name: auto-dev-readiness
description: Prepare a tracker-backed programming task for safe implementation by resolving the routed project, explicit repository and base branch, root/domain/project/invocation development policies, tracker intent, acceptance evidence, work item, isolated worktree, and an implementation plan. Use for new coding work, ticket pickup, context/readiness checks, or when asked to start work even if Auto-Dev is not named.
---

# Auto-Dev Readiness

Create or resume the canonical Development Delivery run; do not create a second
state packet.

1. Route to the domain/project and read its `development.yml`.
2. Resolve tracker truth, acceptance criteria, repository, and ticket-derived
   base branch. For environment defects, consume the Detective version receipt.
3. Explain dev, QA, and gitflow policy; add invocation overlays when needed.
4. Start with `agentic-os develop start ... --apply`. Multi-repository projects
   require `--repository`; release/hotfix work passes `--base-branch`.
5. Inspect the created work item, exact remote base SHA, and isolated worktree.
6. Write a plan that names behavior, risks, validation, and artifact outputs.
7. After the work is verified, create a typed
   `development-stage-evidence/v1` JSON receipt and record
   `worktree_ready -> planned`:

```bash
agentic-os develop stage <state.json> --stage readiness \
  --receipt planned=<plan-receipt.json> --idempotency-prefix <run:ticket:readiness>
```

Missing tracker intent, repository selection, branch authority, or policy blocks
readiness with one exact owner action. Do not guess.
