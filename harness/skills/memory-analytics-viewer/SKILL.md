---
name: memory-analytics-viewer
description: Inspect unified-memory retrieval analytics — summary, recent runs, method rollups, current-vs-grep-sidecar comparison, health, and markdown/JSON export from the live Atlas memory_ops store. Read-only and redacted.
---

# Memory Analytics Viewer

Use when the user asks `/memory-analytics`, wants to see how the unified memory
router is retrieving (grep vs typed vs vector), compare the current route to the
grep sidecar, check retrieval-analytics freshness, or export a tuning report.

## What It Reads

Live retrieval analytics are in Atlas, database `losmon`, collection
`memory_ops` — `op: "read"` rows with `provenance.retrieval`. genomesbox is the
host that can reach Atlas. The viewer is read-only and redacted: it never writes
the database and never emits the connection string.

## Load

1. Read `harness/commands/os-memory-analytics.md` for the command contract.
2. Confirm genomesbox reachability (`ssh genomesbox true`).

## Workflow

1. Pick the subcommand from the user's intent: `summary`, `recent`, `methods`,
   `compare`, `health`, or `export`.
2. Run the wrapper, which executes the report script on genomesbox:

   ```bash
   harness/bin/agentic-os-memory-analytics summary --project losmon --since 7d
   ```

   or directly:

   ```bash
   ssh genomesbox 'cd /home/genome/projects/losmon && \
     pnpm -s tsx scripts/memory/retrieval-analytics-report.ts <cmd> --since 7d'
   ```

3. For `export`, write artifacts to the active work item's
   `artifacts/retrieval-analytics/` folder (the wrapper copies them back from
   genomesbox).
4. Always surface the data-target class (Atlas vs local/dev) and newest-row
   freshness so live and dev data are never confused.
5. When summarizing the grep-vs-current comparison, distinguish hit COUNTS from
   answer QUALITY — more grep hits is not evidence to promote grep past
   `compare`. Defer promotion to a labelled benchmark
   (`scripts/memory/retrieval-bench.ts`).

## Related Surfaces

- losmon API: `GET /api/memory-view/retrieval/{summary,runs,methods,experiments,export}`.
- Benchmark/tuning: `scripts/memory/retrieval-bench.ts`.
- Health/clean/purge: `scripts/memory/memory-health.ts`.

## Guardrails

- Read-only. Never change retrieval config or grep mode from this skill.
- No raw snippets, no connection strings in any output or artifact.
- Notion is projection only; filesystem artifacts are the source of truth.
