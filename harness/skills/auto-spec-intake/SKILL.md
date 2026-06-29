---
name: auto-spec-intake
description: Automatically create or update a local Agentic OS spec packet for long OS-shaping requests before implementation work continues. Use when the user gives a multi-part Agentic OS feature/rules/conventions request or says /auto-add-spec.
---

# Auto Spec Intake

Use this skill when a request is large enough that losing the chat would lose
the work definition.

## Intake Loop

1. Load the routed OS layer and `harness/rules/os-authoring-rules.md`.
2. Run `agentic-os doc-config plan` with the original request.
3. Search active and intake work-items for a matching spec.
4. Create or update a packet with `SPEC`, `PLAN`, `WORKLOG`, `NEXT`, and
   `QUESTIONS` when unresolved questions exist.
5. Add `CONVENTIONS` when the request creates reusable OS behavior.
6. Record any required source worktree registration.
7. Hand the packet path back to the orchestrator before implementation.

## Context Budget

Do not load all prior work. Search by title/request terms, active work indexes,
and doc-config search methods. Load only the matching packet and the compact
authoring rules.

## Guardrails

- Do not generate `IDEA.md` for new packets. Existing `IDEA.md` files remain
  readable legacy capture.
