---
name: auto-dev-document
description: Document code, architecture, APIs, operations, issues, decisions, investigations, QA, releases, and handoffs for the right audience and destination with source-backed claims and verified output.
---

# Auto-Dev Document

This workflow can run at any point.

1. State the audience, question, source of truth, destination, owner, and
   freshness expectation.
2. Read code/project context and existing documentation. Reuse the routed docs
   upkeep or project-domain context tools; do not invent another renderer.
3. Choose the right form: code/API docs, architecture note, runbook, issue or
   decision record, RCA, QA plan/result, release notes, or handoff.
4. Draft in plain English. Mark facts, inferences, decisions, and unknowns.
5. Use Auto-Dev Create Artifacts for governed external writes and read back the
   rendered result. Never expose local paths, secrets, or private links.
6. Record `document` evidence in `autodev.json`, including freshness owner and
   the verified output reference.
