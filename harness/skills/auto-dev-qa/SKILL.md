---
name: auto-dev-qa
description: Run the project-configured risk-based QA gates as a standalone Auto-Dev step and record exact typed evidence without weakening unavailable-environment failures into passes.
---

# Auto-Dev QA

1. Read the ticket acceptance criteria, effective `qa_gates`, changed surface,
   and current `autodev.json`.
2. Select the smallest complete static, unit, integration, end-to-end, manual,
   CI, and deployed checks justified by risk.
3. Run the checks through the project's canonical tooling. Keep raw logs out of
   chat; retain compact commands, identifiers, results, and artifact paths.
4. Classify failures as code, test, data, provider, or environment failures.
   Use CI fallback only when project policy permits it and record why.
5. Map every acceptance criterion to evidence or a gap. Record `qa` as
   completed only after evidence is current for the exact revision.

## Project-owned campaign behavior

Resolve the effective `auto_dev`, `qa_gates`, `environment_access`, and
`gitflow_topology` planes before selecting a campaign path. A project may define
ticket-family classification, child delivery, fixture/configuration ownership,
merge authority, or tracker transitions. Those rules belong in that project's
configuration and policy addenda, never in this shared skill.

Preserve one work item per ticket. When a project defines a child QA delivery,
bind the child ticket, contract, repository, revision, evidence, and disposition
back to its parent. The parent QA gate is terminal only at the completion
boundary declared by the effective project policy.
