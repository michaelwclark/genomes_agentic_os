# Holdout QA Results

## Guide Reference Check

```text
$ rg "plan-sync|--dry-run|--apply|verified-workspace|Genome's Notion|source of truth|mapping" docs/13-feature-guides/06-notion-control-plane-sync.md
filesystem remains the source of truth; Notion is the control plane
runtime files, `.notion-sync/mapping.yml`, and any local sync state
agentic-os notion plan-sync --root ~/agentic_os
agentic-os notion sync --root ~/agentic_os --dry-run
--apply
--verified-workspace "Genome's Notion"
`--dry-run` prints the planned create/update/no-op actions
`--apply` writes `.notion-sync/mapping.yml` after workspace verification.
Genome roots require the verified workspace name `Genome's Notion`.
Apply refuses to run without `--verified-workspace`
```

## Full Suite

```text
$ uv run --extra dev pytest -q
.......................................                                  [100%]
39 passed in 3.20s
```
