---
name: gitflow-pr-create
description: Compatibility alias for Auto-Dev PR Create with GitFlow-family defaults.
argument-hint: "<ticket> [--apply] [--source-pr <number>]"
---

# GitFlow PR Create

Delegate the complete invocation to `$auto-dev-pr-create` in GitFlow-family
mode. Preserve legacy arguments and receipt discovery, but write canonical
receipts under `artifacts/auto-dev-pr-create/`. This alias owns no target
selection, provider behavior, or review policy.
