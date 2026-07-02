---
name: auto-feature-intake
description: Compatibility alias for auto-spec-intake. Use auto-spec-intake for new long OS-shaping requests; keep this skill callable for legacy /auto-add-feature requests.
---

# Auto Feature Intake

Compatibility alias for `auto-spec-intake`.

Use `harness/skills/auto-spec-intake/SKILL.md` as the primary workflow.
Existing `/auto-add-feature` requests route through the same doc-config and
project work-item intake as `/auto-add-spec`.

## Compatibility Notes

- New packets use `SPEC.md` as the raw-capture plus refined-spec file.
- Existing `IDEA.md` files remain readable legacy capture.
- All intake ultimately writes a row to the unified "🧭 OS Work Intake" Notion DB
  (id c442dd56a24340f0880acfd195f34225) via `agentic-os-intake-row`; see
  `auto-spec-intake` step 8.
