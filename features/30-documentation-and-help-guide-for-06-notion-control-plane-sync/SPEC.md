# 30 Documentation And Help Guide For 06 Notion Control Plane Sync

Create an operator-facing guide for feature 06 explaining guarded
filesystem-to-Notion sync planning, dry runs, workspace verification, apply, and
local mappings.

## Acceptance

- Document `agentic-os notion plan-sync --root <root>`.
- Document `agentic-os notion sync --root <root> --dry-run`.
- Document `agentic-os notion sync --root <root> --apply --verified-workspace <workspace>`.
- Explain filesystem source of truth and Notion control plane boundaries.
- Explain `Genome's Notion` and customer workspace requirements.
- Explain `.notion-sync/mapping.yml` and no-op behavior after unchanged apply.
