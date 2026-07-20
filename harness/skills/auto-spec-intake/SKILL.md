---
name: auto-spec-intake
description: Compatibility adapter for automatic Spec Engine capture. Use for legacy /auto-add-spec requests; the canonical spec-engine skill owns add, update, grooming, adapters, and receipts.
---

# Auto Spec Intake

Compatibility adapter for `spec-engine`.

For a long OS-shaping request, search scoped Specs, update the match or execute
`agentic-os spec add`, and return the YAML receipt before implementation. Use
status `grooming` only when spec development has started; otherwise retain
`idea`. Do not create a Notion intake row or parallel feature packet.
Any requested provider projection is rendered, approved, applied, and read back
through `$auto-dev-create-artifacts`; this adapter owns only idempotent capture.
