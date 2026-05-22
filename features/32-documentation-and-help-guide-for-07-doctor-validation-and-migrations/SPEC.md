# 32 Documentation And Help Guide For 07 Doctor Validation And Migrations

Create an operator-facing guide for feature 07 explaining runtime doctor checks,
additive repairs, and reviewable migration planning/apply semantics.

## Acceptance

- Document `agentic-os doctor --root <root>`.
- Document `agentic-os doctor --root <root> --fix-missing`.
- Document `agentic-os migrate plan --root <root>`.
- Document `agentic-os migrate apply <migration_id> --root <root>`.
- Explain findings, severities, additive repair limits, migration previews,
  rollback notes, approval requirements, and changed-target refusal.
