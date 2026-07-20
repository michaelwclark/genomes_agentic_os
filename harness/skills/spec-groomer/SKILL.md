---
name: spec-groomer
description: Compatibility adapter for spec-engine grooming mode. Use for legacy groom-spec requests; the canonical spec-engine skill owns lifecycle, policy, adapters, and receipts.
---

# Spec Groomer

Compatibility adapter for `spec-engine` grooming mode.

Load `harness/skills/spec-engine/SKILL.md`. Find or add the canonical Spec,
transition it to `grooming`, preserve original intent, run capability discovery,
complete the implementation-grade packet, and move it to `ready` only when the
configured gates pass. Do not create a parallel groomed-spec lifecycle.

Render every provider projection through `$auto-dev-create-artifacts`; grooming
owns evidence and judgment, not Jira/Linear/Notion formatting or readback.
