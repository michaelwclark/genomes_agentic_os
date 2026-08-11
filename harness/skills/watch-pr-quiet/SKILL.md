---
name: watch-pr-quiet
description: Use when an agent needs to monitor GitHub pull request checks without repeatedly printing polling output into the conversation. Starts or uses a file-based PR watcher that writes status artifacts under a specified output folder, usually the task's durable artifact folder, and then the orchestrator inspects those files on a schedule.
---

# /watch-pr-quiet

Use this skill whenever you need to watch GitHub PR checks, CI, or branch protection state over time.

Do not repeatedly run `gh pr checks`, `gh run watch`, or long polling loops in the main conversation. Start the quiet watcher and inspect its files later.

The watcher reads pull-request metadata and workflow runs through the versioned
`@genomes/github` port bridge. Configure `GENOMES_GITHUB_BRIDGE_COMMAND` with
the reviewed bridge executable and provide `GITHUB_TOKEN` or `GH_TOKEN` in the
watcher environment. The watcher never shells out to `gh` for provider reads.

## Canonical Command

```bash
python3 "${AGENTIC_OS_ROOT:-$HOME/agentic_os}/harness/skills/watch-pr-quiet/scripts/watch_pr_quiet.py" \
  --pr <PR_NUMBER> \
  --output-dir <OUTPUT_FOLDER> \
  --timeout-minutes <MINUTES> \
  --interval-minutes <MINUTES> \
  [--expected-head-sha <FULL_SHA>] \
  [--required-check <EXACT_CHECK_NAME>] \
  [--repo owner/name]
```

For LOS work, prefer the Agentic OS work item artifact folder:

```bash
python3 "${AGENTIC_OS_ROOT:-$HOME/agentic_os}/harness/skills/watch-pr-quiet/scripts/watch_pr_quiet.py" \
  --pr 12345 \
  --repo thesummitgrp/los-app-los-django \
  --output-dir <os-root>/domains/los/02-projects/los_app_los_django/work-items/<date>-<id>/artifacts/pr-watch \
  --timeout-minutes 90 \
  --interval-minutes 5 \
  --expected-head-sha <FULL_SHA> \
  --required-check "PR Smoke"
```

The script prints nothing. It writes:

- `pr-<PR>-watch-state.json`: latest machine-readable status
- `pr-<PR>-watch-events.jsonl`: append-only polling history
- `pr-<PR>-watch-summary.md`: compact human-readable status

## Status Meanings

- `success`: all current-head workflow runs passed
- `failure`: at least one current-head workflow run failed, timed out, was cancelled, or requires action
- `pending`: checks are queued, in progress, expected, or not yet observed
- `timeout`: timeframe expired before a terminal pass/fail state
- `error`: the watcher could not query GitHub or write artifacts

## Orchestrator Pattern

1. Resolve and record the exact current PR head SHA before starting a
   delivery-grade watch.
2. Read the exact-head `check_run.name` values and name every required check
   with repeatable `--required-check` arguments. These are job-context names,
   not workflow display labels: use `Docs link policy` and `Python suite and
   packaging`, not `Docs`, `Test`, or `Python suite`. `--min-checks` alone
   cannot distinguish stale or unrelated checks.
3. Put the watcher output in the task's durable artifact folder, not in `/tmp`.
4. For a watch expected to exceed two minutes, start it through
   `agentic-os long-run`; direct background processes and raw `nohup` are not
   permitted.
5. Schedule a heartbeat or reminder every 10 minutes to inspect `pr-<PR>-watch-state.json`.
6. If `status` is `failure`, dispatch the applicable subagent with the state file path and PR number.
7. If `status` is `success`, verify `sha`, `expected_head_sha`,
   `head_matches_expected`, and `missing_required_checks` before updating the
   task tracker.
8. If `status` is `timeout` or `error`, inspect the summary file and decide whether to restart with a new timeframe.

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
  --preflight-check 'test -n "$GENOMES_GITHUB_BRIDGE_COMMAND" && test -n "${GITHUB_TOKEN:-${GH_TOKEN:-}}"' \
  -- \
  python3 "${AGENTIC_OS_ROOT:-$HOME/agentic_os}/harness/skills/watch-pr-quiet/scripts/watch_pr_quiet.py" \
  --pr <PR_NUMBER> \
  --output-dir <OUTPUT_FOLDER> \
  --timeout-minutes 120 \
  --interval-minutes 5 \
  --repo <owner/name> \
  --expected-head-sha <FULL_SHA> \
  --required-check <EXACT_CHECK_NAME>
```

Record the PR number and output folder in the Agentic OS work item so future agents can resume by reading the watcher files.

## Rules

- Prefer GitHub-hosted checks when local worktree tests are unavailable, broken, or too slow for the current loop.
- Local targeted tests are still useful when they run cleanly; GitHub is the source of truth for final PR readiness.
- A delivery-grade success claim requires `--expected-head-sha` and at least
  one `--required-check`. A watch without those arguments is observational
  only and must not be used as a terminal PR receipt.
- Checks from a head observed before the expected SHA are ignored. After the
  expected SHA is observed, any head change is terminal failure.
- A named required check passes only with an explicit `success` conclusion;
  `neutral` and `skipped` are not delivery-grade success.
- When the exact-head check context has settled, supplied `--required-check`
  values that are not emitted `check_run.name` values fail immediately with
  `invalid_required_checks` and the observed check names in the state receipt;
  they must be corrected and the watcher restarted. Do not wait for a stale
  workflow display label to time out.
- Never paste full polling logs into chat. Reference the summary/state files instead.
- Do not use this watcher for unrelated production monitoring. It is for PR check status only.
