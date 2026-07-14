---
name: aos-product-orchestrator
description: Apply the Agentic OS self-improvement project profile while the canonical spec-engine skill owns Spec lifecycle and Linear projection. Use for AOS Product Orchestrator or Auto Groom compatibility requests.
---

# AOS Product Orchestrator

Agentic OS self-improvement adapter for the canonical `spec-engine` skill.
This skill contributes project-specific discovery, technical mapping, QA, and
rollout context. It does not own a separate packet, Notion intake row, status
taxonomy, or Linear synchronization path.

## Procedure

1. Load the routed Agentic OS project and
   `harness/skills/spec-engine/SKILL.md`.
2. Search existing Agentic OS Specs and Linear identities before creating work.
3. Add or update the canonical Spec through `agentic-os spec add`; default to
   the project policy's Linear adapter and Backlog placement.
4. For Auto Groom, transition the Spec to `grooming`, preserve original intent,
   and inspect the relevant source, installed runtime, config, tests, docs, and
   recent receipts.
5. Add Agentic OS-specific technical mapping: source-package versus installed
   OS impact, migration/install behavior, harness parity, validation, rollout,
   and backout.
6. Run `agentic-os spec sync ... --adapter linear --apply` only when external
   mutation is authorized. Read back the issue and retain the YAML receipt.
7. Move to `ready` only when the Spec Engine readiness contract passes.

## Compatibility

Historical Self Improvement Notion rows may remain source evidence. They are
not the intake queue. Do not call `agentic-os-intake-row` or
`agentic-os-intake-sync`; Spec Engine owns provider identity and idempotency.

## Guardrails

- Do not implement unless explicitly requested.
- Verify Linear workspace, team, and project before applying writes.
- Verify Genome's Notion before updating a historical source row.
- Keep local paths, private Notion links, secrets, token names, and internal
  harness details out of Linear.
- Completion requires one canonical Spec, its local/projection receipt, evidence
  summary, QA/rollout notes, and a clear next action or blocker.
