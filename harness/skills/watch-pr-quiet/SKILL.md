---
name: watch-pr-quiet
description: Use when an agent needs to monitor GitHub pull request checks without repeatedly printing polling output into the conversation. Starts or uses a file-based PR watcher that writes status artifacts under a specified output folder, usually the task's durable artifact folder, and then the orchestrator inspects those files on a schedule.
---

# /watch-pr-quiet

Use this skill whenever you need to watch GitHub PR checks, CI, or branch protection state over time.

Do not repeatedly run `gh pr checks`, `gh run watch`, or long polling loops in the main conversation. Start the quiet watcher and inspect its files later.

## Canonical Command

```bash
python3 "${AGENTIC_OS_ROOT:-$HOME/agentic_os}/harness/skills/watch-pr-quiet/scripts/watch_pr_quiet.py" \
  --pr <PR_NUMBER> \
  --output-dir <OUTPUT_FOLDER> \
  --timeout-minutes <MINUTES> \
  --interval-minutes <MINUTES> \
  [--repo owner/name]
```

For LOS work, prefer the Agentic OS work item artifact folder:

```bash
python3 "${AGENTIC_OS_ROOT:-$HOME/agentic_os}/harness/skills/watch-pr-quiet/scripts/watch_pr_quiet.py" \
  --pr 12345 \
  --repo thesummitgrp/los-app-los-django \
  --output-dir <os-root>/domains/los/02-projects/los_app_los_django/work-items/<date>-<id>/artifacts/pr-watch \
  --timeout-minutes 90 \
  --interval-minutes 5
```

The script prints nothing. It writes:

- `pr-<PR>-watch-state.json`: latest machine-readable status
- `pr-<PR>-watch-events.jsonl`: append-only polling history
- `pr-<PR>-watch-summary.md`: compact human-readable status

## Status Meanings

- `success`: all observed checks/status contexts passed
- `failure`: at least one observed check/status context failed, timed out, was cancelled, or requires action
- `pending`: checks are queued, in progress, expected, or not yet observed
- `timeout`: timeframe expired before a terminal pass/fail state
- `error`: the watcher could not query GitHub or write artifacts

## Orchestrator Pattern

1. Put the watcher output in the task's durable artifact folder, not in `/tmp`.
2. Start the watcher in the background when it will run longer than the current interaction should block.
3. Schedule a heartbeat or reminder every 10 minutes to inspect `pr-<PR>-watch-state.json`.
4. If `status` is `failure`, dispatch the applicable subagent with the state file path and PR number.
5. If `status` is `success`, update the task tracker and stop watching.
6. If `status` is `timeout` or `error`, inspect the summary file and decide whether to restart with a new timeframe.

## Background Start

Use shell redirection so the conversation does not receive polling output:

```bash
nohup python3 "${AGENTIC_OS_ROOT:-$HOME/agentic_os}/harness/skills/watch-pr-quiet/scripts/watch_pr_quiet.py" \
  --pr <PR_NUMBER> \
  --output-dir <OUTPUT_FOLDER> \
  --timeout-minutes 120 \
  --interval-minutes 5 \
  --repo <owner/name> \
  >/dev/null 2>&1 &
```

Record the PR number and output folder in the Agentic OS work item so future agents can resume by reading the watcher files.

## Rules

- Prefer GitHub-hosted checks when local worktree tests are unavailable, broken, or too slow for the current loop.
- Local targeted tests are still useful when they run cleanly; GitHub is the source of truth for final PR readiness.
- Never paste full polling logs into chat. Reference the summary/state files instead.
- Do not use this watcher for unrelated production monitoring. It is for PR check status only.
