---
name: auto-dev-readiness
description: Prepare a tracker-backed programming task for safe implementation by resolving the routed project, explicit repository and base branch, root/domain/project/invocation development policies, tracker intent, acceptance evidence, work item, isolated worktree, and an implementation plan. Use for new coding work, ticket pickup, context/readiness checks, or when asked to start work even if Auto-Dev is not named.
---

# Auto-Dev Readiness

Create or resume the canonical Development Delivery run; do not create a second
state packet.

1. Route to the domain/project and read its `development.yml`.
2. Read the live Jira or Linear item and evaluate its problem, intended
   outcome, scope, acceptance behavior, dependencies, and validation
   expectations. Workflow status is advisory: when the content is sufficient,
   record the item as content-ready and continue even if the status is
   `Requirements`, `Requirements Gathering`, or an equivalent label. Do not
   require a provider status transition or approval merely to start delivery.
3. Resolve tracker truth, acceptance criteria, repository, and ticket-derived
   base branch. For environment defects, consume the Detective version receipt.
4. Explain dev, QA, and gitflow policy; add invocation overlays when needed.
   When a change touches an LOS Rules Engine caller or rulebook, also resolve
   its selector and local evidence status before planning; a match alone does
   not establish that a kit was loaded.
5. Start with `agentic-os develop start ... --apply`. Pass each changed
   repository-relative path as `--touched-path` and `--subject rules-engine`
   or `--subject rulebook` plus `--rulebook-id <exact-key>` when applicable;
   this freezes the context result in the effective-policy receipt.
   Multi-repository projects require
   `--repository`; release/hotfix work passes `--base-branch`.
6. Inspect the created work item, exact remote base SHA, and isolated worktree.
7. Write a plan that names behavior, risks, validation, and artifact outputs.
8. After the work is verified, create a typed
   `development-stage-evidence/v1` JSON receipt and record
   `worktree_ready -> planned`:

```bash
agentic-os develop stage <state.json> --stage readiness \
  --receipt planned=<plan-receipt.json> --idempotency-prefix <run:ticket:readiness>
```

If ticket content is incomplete, groom it and continue when source truth and
project policy resolve the gaps. Missing tracker intent, repository selection,
branch authority, policy, or a material product decision blocks readiness with
one exact owner action. The provider workflow label alone never blocks
readiness and must not be reported as the attention request.
