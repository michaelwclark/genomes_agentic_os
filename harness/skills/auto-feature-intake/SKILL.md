---
name: auto-feature-intake
description: Compatibility adapter for automatic Spec Engine capture with type feature. Use for legacy /auto-add-feature requests.
---

# Auto Feature Intake

Load `harness/skills/spec-engine/SKILL.md` through `auto-spec-intake` and use
`--type feature`. Do not create a separate feature packet, lifecycle, Notion
queue row, or tracker sync.
Delegate any requested provider projection to `$auto-dev-create-artifacts`
through the canonical Spec Engine record.
