# OS Docs Upkeep

Run the observe-mode documentation upkeep planner.

## Dry Run

```bash
agentic-os docs upkeep --root ~/agentic_os
```

The planner reads `harness/shared_factory/00-control-plane/documentation-upkeep.yml`,
hashes each registered source set, and reports `unchanged`, `stale`, or
`missing_sources`. It does not write to Notion.

## Receipt

```bash
agentic-os docs upkeep --root ~/agentic_os --write-receipt
```

Receipt mode writes a YAML and Markdown report under
`harness/shared_factory/06-runs-and-logs/documentation-upkeep/runs/`.
