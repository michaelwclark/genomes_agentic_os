---
name: auto-dev-grooming
description: Groom rough product or engineering work into a source-backed, implementation-ready spec and provider backlog through the existing Spec Engine and Auto-Dev artifact flow.
---

# Auto-Dev Grooming

1. Read live tracker/source truth and preserve the user's original intent.
   Treat Jira and Linear status as advisory metadata. If the existing problem,
   outcome, scope, acceptance behavior, dependencies, and validation
   expectations already make the item buildable, record it as content-ready
   and hand it forward without waiting for a `Requirements` status change.
2. Reuse the canonical Spec/work item. Discover existing capabilities before
   classifying the request as extend, create-under-existing, or create-new.
3. Use Detective for uncertain causes. Write problem, outcomes, scenarios,
   risks, dependencies, decisions, holdout QA, and a dependency-ordered plan.
4. Use the project's product orchestrator for provider hierarchy and
   `/auto-dev-create-artifacts` for every external projection and readback.
5. Record `groom` evidence in `autodev.json` and hand implementation-ready
   children to Auto-Dev Readiness.

Grooming ends with a buildable source of truth or one exact blocking question.
The tracker workflow label is never that question.
It does not create a worktree or write code.
