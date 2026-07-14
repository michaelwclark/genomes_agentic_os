---
name: spec-intake-router
description: Compatibility adapter for the canonical spec-engine skill. Use for legacy spec intake or /add-spec requests; new work should execute agentic-os spec add through spec-engine.
---

# Spec Intake Router

Compatibility adapter for `spec-engine` add mode.

Load `harness/skills/spec-engine/SKILL.md`, then execute `agentic-os spec add`.
Do not run a separate doc-config lifecycle, `project work-item create`, or
`agentic-os-intake-row`. Domain/project `spec_engine` policy now owns routing,
adapter selection, lifecycle authority, and optional documentation projection.
