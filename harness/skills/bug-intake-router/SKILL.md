---
name: bug-intake-router
description: Compatibility adapter for spec-engine add with type bug. Use for legacy /add-bug requests or reports of broken behavior and missed enforcement.
---

# Bug Intake Router

Load `harness/skills/spec-engine/SKILL.md` and execute its add flow with
`--type bug`. Preserve severity, current behavior, expected behavior,
reproduction/evidence, and the next validation step in the canonical Spec. Do
not create a separate bug packet or intake lifecycle.
