# OS Doc Config

Use when deciding where a document, note, spec, plan, question, or worklog belongs in Agentic OS and its Notion control-plane projection.

## Procedure

1. Read the routed `ROUTER.md`, `CONTEXT.md`, `RULES.md`, `TOOLS.md`, and any active work item.
2. Read `harness/rules/os-authoring-rules.md` when the request creates or changes conventions, workflows, automations, commands, skills, tools, project worktrees, or feature mirrors. Use `harness/shared_factory/05-knowledge/references/os-conventions.md` only when deeper background is needed.
3. Run `agentic-os doc-config plan --root <root> --request "<request>"` with `--domain`, `--project`, and `--work-item` when known.
4. If the request includes unanswered questions, pass `--questions-present` and include the `QUESTIONS` bucket.
5. Use enabled search methods in returned priority order.
6. Before Notion writes, verify the workspace is Genome's Notion or the explicitly selected client workspace.
7. Search for existing destinations before creating pages or folders.
8. Keep filesystem/work-item files authoritative; mirror or link Notion as the human control plane.

## Commands

```bash
agentic-os doc-config doctor --root ~/agentic_os
agentic-os doc-config plan --root ~/agentic_os --request "Add this to Notion" --domain clarks_consulting --project genomes_agentic_os --questions-present
agentic-os doc-config init --root ~/agentic_os --domain clarks_consulting --project genomes_agentic_os
```

## Output

A routing plan with destination, lifecycle buckets, enabled search methods, analytics config, and next actions.
