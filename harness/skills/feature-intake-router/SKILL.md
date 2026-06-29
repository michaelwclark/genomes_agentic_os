---
name: feature-intake-router
description: Compatibility alias for spec-intake-router. Use spec-intake-router for new future-work, proposed-feature, and spec intake; keep this skill callable for legacy /new-feature and /add-feature requests.
---

# Feature Intake Router

Compatibility alias for `spec-intake-router`.

Use `harness/skills/spec-intake-router/SKILL.md` as the primary workflow.
Existing `/new-feature`, `/add-feature`, and `/new-idea` requests route through
the same doc-config and project work-item intake as `/add-spec`.

## Compatibility Notes

- New packets use `SPEC.md` as the raw-capture plus refined-spec file.
- Existing `IDEA.md` files remain readable legacy capture.
- Source repository `features/` or `.features/` folders remain mirrors/artifacts
  by default, not lifecycle owners.
