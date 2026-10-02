---
name: watch-pr-quiet
description: Monitor GitHub pull request checks with a bounded background watcher and terminal-event receipts, without periodic model wakeups or parent-chat status polling.
---

# /watch-pr-quiet

Use this skill whenever you need to watch GitHub PR checks, CI, or branch protection state over time.

Do not repeatedly run `gh pr checks`, `gh run watch`, `gh pr view`, or any long
polling loop in the main conversation. The deterministic bounded watcher or an
isolated subagent owns waiting; the main task resumes only for a
terminal/actionable event or an explicit user status request.

Periodic model wakeups solely to read status are forbidden. Silent heartbeats,
reminders, and empty final responses still consume model tokens and parent-chat
context. If terminal-event delivery is unavailable, record an artifact-only
handoff; never use a heartbeat/reminder fallback. Approved substantive scheduled
jobs remain allowed; a status-only poll is not one.

## Canonical Command

```bash
python3 "${AGENTIC_OS_ROOT:-$HOME/agentic_os}/harness/skills/watch-pr-quiet/scripts/watch_pr_quiet.py" \
  --pr <PR_NUMBER> \
  --output-dir <OUTPUT_FOLDER> \
  --timeout-minutes <MINUTES> \
  --interval-minutes <MINUTES> \
  --expected-head-sha <FULL_SHA> \
  --required-check <EXACT_CHECK_NAME> \
  [--required-check <EXACT_CHECK_NAME>] \
  [--repo owner/name]
```

For LOS work, prefer the Agentic OS work item artifact folder:

```bash
python3 "${AGENTIC_OS_ROOT:-$HOME/agentic_os}/harness/skills/watch-pr-quiet/scripts/watch_pr_quiet.py" \
  --pr 12345 \
  --repo Lenders-Cooperative/los-app-los-django \
  --output-dir /Users/genome/agentic_os/domains/los/02-projects/los_app_los_django/work-items/02-active/<id>/artifacts/pr-watch \
  --timeout-minutes 90 \
  --interval-minutes 5 \
  --expected-head-sha <FULL_SHA> \
  --required-check "pytest / Coverage"
```

The script prints nothing. It writes:

- `pr-<PR>-watch-state.json`: latest machine-readable status
- `pr-<PR>-watch-events.jsonl`: append-only polling history
- `pr-<PR>-watch-summary.md`: compact human-readable status

## Status Meanings

- `success`: the expected head matches and every named required check and
  observed check/status context passed, with no missing required checks
- `failure`: at least one observed check/status context failed, timed out, was cancelled, or requires action
- `pending`: checks are queued, in progress, expected, or not yet observed
- `timeout`: timeframe expired before a terminal pass/fail state
- `error`: the watcher could not query GitHub or write artifacts

## Orchestrator Pattern

1. Resolve and record the exact PR head SHA before starting a delivery-grade watch.
2. Name every required check with repeatable `--required-check` arguments.
3. Put the watcher output in the task's durable artifact folder, not in `/tmp`.
4. Start it through `agentic-os long-run`; raw `nohup` and direct background
   processes are not permitted.
5. Let the deterministic watcher or isolated subagent handle its bounded wait
   and terminal-event delivery. Record the run id, expected head, required checks,
   artifact path, owner, and event route. If that route is unavailable, record
   an artifact-only handoff and stop the main turn; do not schedule a model
   wakeup to inspect `pr-<PR>-watch-state.json`.
6. On `failure`, inspect the exact failed job log before changing code.
7. On `success`, verify `sha`, `expected_head_sha`, `head_matches_expected`, and
   `missing_required_checks`, then perform one GitHub mergeability/review readback.
8. On `timeout` or `error`, inspect the watcher summary before restarting.
   Preserve existing pause/cancel controls and bounded wall-clock/resource
   limits; user cancellation or a safety pause ends the wait.

## Consumer Gate

Starting the watcher creates active work; it does not create a completion
receipt. A workflow may record CI success or `ready_for_merge` only after it
consumes `pr-<PR>-watch-state.json` and proves all of the following:

- `status` is exactly `success`;
- `sha` equals `expected_head_sha` and `head_matches_expected` is true;
- every required check was named before the watch began and has an explicit
  success conclusion; and
- `missing_required_checks` is empty.

Treat `pending`, `running`, `timeout`, and `error` as nonterminal. Treat
`failure` as a repair transition: inspect the failed job, classify it, repair
or perform the single permitted infrastructure rerun, push when code changes,
and start a new exact-head watch. Any push invalidates the earlier watcher
receipt, including an earlier success.

## Governed Long-Run Start

Use the Agentic OS long-run control plane so the watcher is registered,
bounded, recoverable, and quiet:

```bash
agentic-os long-run start \
  --root "${AGENTIC_OS_ROOT:-$HOME/agentic_os}" \
  --kind watcher \
  --label "PR <PR_NUMBER> exact-head check watch" \
  --work-dir <REPOSITORY_WORKTREE> \
  --wall-clock-minutes 125 \
  --no-progress-minutes 125 \
  --max-log-mb 1 \
  --log-rotations 1 \
  --preflight-check "gh pr view <PR_NUMBER> --repo <owner/name> --json headRefOid >/dev/null" \
  -- \
  python3 "${AGENTIC_OS_ROOT:-$HOME/agentic_os}/harness/skills/watch-pr-quiet/scripts/watch_pr_quiet.py" \
  --pr <PR_NUMBER> \
  --repo <owner/name> \
  --output-dir <OUTPUT_FOLDER> \
  --timeout-minutes 120 \
  --interval-minutes 5 \
  --expected-head-sha <FULL_SHA> \
  --required-check <EXACT_CHECK_NAME>
```

Record the PR number and output folder in the Agentic OS work item so future agents can resume by reading the watcher files.

## Rules

- Prefer GitHub-hosted checks when local worktree tests are unavailable, broken, or too slow for the current loop.
- Local targeted tests are still useful when they run cleanly; GitHub is the source of truth for final PR readiness.
- A delivery-grade watcher requires `--expected-head-sha` and at least one
  `--required-check`; an observational watcher cannot support a merge claim.
- Never inspect GitHub while a watcher reports `pending` or `running` just to
  check progress. An explicit user status request permits one bounded snapshot;
  otherwise the terminal watcher receipt selects the next action.
- Never paste full polling logs into chat. Reference the summary/state files instead.
- Do not use this watcher for unrelated production monitoring. It is for PR check status only.
