# OS Status Report

Use when the operator asks `/status-report`, asks what has been worked on in
the last N hours or days, or needs a recent Agentic OS status report with gap
analysis.

Primary skill: `status-report`.

## CLI / Skill Surface

There is no dedicated `agentic-os status-report` CLI subcommand yet. Treat the
slash command as a harness command that runs the `status-report` skill and the
shared workflow at:

```text
harness/shared_factory/03-workflows/operations/status_report/
```

Codex-visible invocation is `$status-report` after skill registration.

## Parameters

| Parameter | Required | Notes |
| --- | --- | --- |
| `--hours N` | no | Look back N hours. |
| `--days N` | no | Look back N days. |
| `--since <ISO>` | no | Use an explicit start timestamp. |
| `--hosts local|genomesbox|all` | no | Default is `all` when remote access works. |
| `--project <name>` | no | Optional focus. |
| `--no-notion` | no | Skip Notion projection and record `skipped`. |

Default window is the prior day at 5:00 AM local time through now.

## Procedure

1. Route to `shared_factory/03-workflows/operations/status_report`.
2. Load `quick-reference.md`, `workflow.md`, `approval-rules.md`,
   `output-contract.md`, and `runbook.md`.
3. Call `memory_read` before local reconnaissance.
4. Use Context Mode or summarizing scripts for broad Claude/Codex log analysis.
5. Collect and summarize:
   - Claude logs and project transcripts;
   - Codex sessions and rollout summaries;
   - Agentic OS active work, work items, workflows, automations, commands,
     skills, registries, adapters, and `TOOLS.md`;
   - registered source roots and active worktree Git status;
   - Notion projection state.
6. Write the full markdown report to the filesystem first.
7. Verify Genome's Notion before writing the higher-level Notion summary.
8. Record projection status as `verified`, `skipped`, `warning`, or `blocked`.
9. Return the report path, projection status or URL, top next actions, and
   validation receipt.

## Required Report Sections

- Window and source coverage.
- Executive summary.
- Completed work.
- Work in progress.
- Risks and blockers.
- Gap analysis.
- What next.
- Receipts and artifacts.
- Notion projection.

## Gap Analysis Must Cover

- Workflow exists but missing command, skill, Codex adapter, registry row, or
  `TOOLS.md` visibility.
- Command or skill exists but is not registered or user-scope visible.
- Documentation or source package mirror is stale.
- Active work item has stale status, missing worklog, empty next action, or
  missing validation.
- Source checkout has dirty, untracked, uncommitted, unpushed, or conflicted
  files.
- Notion projection is missing, stale, or in an unverified workspace.
- A useful new feature would be stronger with a complementary workflow, skill,
  command, automation, Notion database, watcher, or run-log rule.

## Output

Default full report:

```text
/Users/genome/agentic_os/domains/clarks_consulting/02-projects/genomes_agentic_os/worklogs/status-reports/<YYYY-MM-DD-HHMM>-status-report.md
```

Default artifacts:

```text
<os-root>/<domain>/02-projects/genomes_agentic_os/work-items/<date>-011_status_report_workflow/artifacts/status-reports/<run-id>/
```

Resolve the existing `011_status_report_workflow` packet before writing. The
installed legacy packet may still live at
`/Users/genome/agentic_os/domains/clarks_consulting/02-projects/genomes_agentic_os/work-items/02-active/011_status_report_workflow/`;
it remains a read/resume surface. New packets live directly under `work-items/`,
and a returned packet may have moved to `work-items/99-archived/`. Do not create
a duplicate in a legacy numbered lane.

## Safety

- Filesystem markdown is source of truth.
- Notion is projection only and requires verified Genome's Notion.
- Do not expose raw transcripts, secrets, tokens, or connector payloads.
- Do not clean, commit, push, open PRs, update Jira, or send external messages
  unless the user explicitly asks.
