# OS Doc Config

Use when deciding where a document, note, idea, spec, plan, question, or worklog belongs in Agentic OS and its Notion control-plane projection.

## Procedure

1. Read the routed `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`, and any active work item.
2. Run `agentic-os doc-config plan --root <root> --request "<request>"` with `--domain`, `--project`, and `--work-item` when known.
3. If the request includes unanswered questions, pass `--questions-present` and include the `QUESTIONS` bucket.
4. Use enabled search methods in returned priority order.
5. Before Notion writes, verify the workspace is Genome's Notion or the explicitly selected client workspace.
6. Keep filesystem/work-item files authoritative; mirror or link Notion as the human control plane.

## Commands

```bash
agentic-os doc-config doctor --root ~/agentic_os
agentic-os doc-config plan --root ~/agentic_os --request "Add this to Notion" --domain clarks_consulting --project genomes_agentic_os --questions-present
agentic-os doc-config init --root ~/agentic_os --domain clarks_consulting --project genomes_agentic_os
```

## Output

A YAML routing plan with destination, lifecycle buckets, enabled search methods, Notion workspace guardrails, and next actions.
