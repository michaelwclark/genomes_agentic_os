# Memory Integration

The skill is memory-first.

## Startup

The Graybeard Orchestrator must:

1. Read local memory routing when present, especially `MEMORY.md`.
2. Query Unified Memory MCP/CoCoIndex before broad file search.
3. Search with focused terms: repo, PR number, Jira key, changed symbols, touched domain, tenant/client, prior bug name, and workflow names.
4. Pass relevant memory hits to specialist agents.
5. Verify memory-derived claims against current code before treating them as findings.

## Specialist Rule

Every specialist starts with a focused memory lookup for its lane. Memory can prioritize where to inspect, but it is not proof.

Each finding must state whether it is:

- `code-verified`
- `jira-verified`
- `ci-verified`
- `memory-informed`

## Writeback

Write durable follow-up direction to both available memory layers:

- Unified Memory MCP with concise taxonomy-friendly phrasing.
- Local memory update mechanism, such as an ad hoc note under the Codex memory extension path when direct `MEMORY.md` edits are not allowed.

Write back:

- User review preferences.
- Severity calibration.
- Preferred comment style examples.
- Durable workflow decisions.
- External pointers such as Notion specs or team-health dashboards.

Do not write secrets, ephemeral command output, obvious code facts, or personal judgments about authors.
