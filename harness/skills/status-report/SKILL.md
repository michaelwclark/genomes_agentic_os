---
name: status-report
description: Generate a recent Agentic OS status report from Claude/Codex logs, OS state, source status, and Notion projection state.
---

# Status Report

Use when the user asks `/status-report`, asks what has been worked on in the
last N hours or days, asks for a recent Agentic OS work report, or asks for gap
analysis across recent agent work.

## Load

1. Route to `/Users/genome/agentic_os/harness/shared_factory/03-workflows/operations/status_report`.
2. Read `quick-reference.md`, `workflow.md`, `approval-rules.md`,
   `output-contract.md`, `runbook.md`, and `progress.md`.
3. Read the active work item when changing the workflow or reporting on this
   feature:
   `/Users/genome/agentic_os/clarks_consulting/02-projects/genomes_agentic_os/work-items/02-active/011_status_report_workflow`.

## Inputs

- Default window: prior day at 5:00 AM local time through now.
- Accept `--hours N`, `--days N`, or `--since <ISO timestamp>`.
- Accept optional host scope `local`, `genomesbox`, or `all`.
- Accept optional project or work-item focus.

## Workflow

1. Call `memory_read` first with a focused recent-work query.
2. Use Context Mode timeline search for recent prompts, decisions, blockers,
   errors, and compaction summaries.
3. Summarize Codex evidence from local and remote `~/.codex` sessions and
   rollout summaries. Reuse the existing Codex collector when available:

   ```bash
   python3 /Users/genome/.codex/skills/agentic-status-report/scripts/agentic_status.py --hours <N> --format json
   ```

4. Summarize Claude evidence from `~/.claude/projects`, `~/.claude/tasks`,
   `~/.claude/sessions`, `~/.claude/context-mode/sessions`, and installed OS
   conversation logs.
5. Inspect Agentic OS active work, work items, workflows, automations, commands,
   skills, registries, `.agents/skills`, and routed `TOOLS.md` files.
6. Inspect registered source roots and active worktrees with read-only Git status.
7. Write the full markdown report to the filesystem source-of-truth path.
8. Verify Genome's Notion before writing any Notion projection. If verification
   fails, record `warning` or `blocked` and do not write elsewhere.
9. Return the report path, Notion projection status or URL, top next actions,
   and validation receipt.

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

## Gap Analysis Checklist

Check for:

- workflows without `/command`, `$skill`, harness skill, Codex adapter,
  registry, or `TOOLS.md` visibility;
- command or skill docs missing registry or user-scope registration;
- source package mirror or documentation not updated after installed runtime
  changes;
- active work items with stale status, missing validation, empty `NEXT.md`, or
  no recent worklog;
- dirty, untracked, uncommitted, unpushed, or conflicted source checkouts;
- missing, stale, or unverified Notion projection;
- skipped or failed validation;
- complementary workflow, skill, command, automation, Notion database, watcher,
  or run-log rule that would make recent work usable.

## Output

Default full report:

```text
/Users/genome/agentic_os/clarks_consulting/02-projects/genomes_agentic_os/worklogs/status-reports/<YYYY-MM-DD-HHMM>-status-report.md
```

Default artifacts:

```text
/Users/genome/agentic_os/clarks_consulting/02-projects/genomes_agentic_os/work-items/02-active/011_status_report_workflow/artifacts/status-reports/<run-id>/
```

## Safety

- Keep raw logs and transcripts out of chat and Notion.
- Do not print or copy token values.
- Do not write to Notion unless Genome's Notion is verified.
- Do not create fallback Notion pages in any other workspace.
- Do not mutate source, commit, push, open PRs, update Jira, send external
  messages, or perform cleanup unless explicitly requested.
