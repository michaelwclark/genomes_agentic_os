---
name: quiet-async-runner
description: Use when a command, test suite, Docker setup, PR check, watcher, or external wait is expected to run longer than a normal interactive turn and should write artifact-backed state instead of keeping chat alive with polling.
---

# Quiet Async Runner

Use this skill whenever work is expected to wait on a slow local command, Docker
stack, dependency install, test suite, pre-commit, PR check, CI watcher, or other
asynchronous operation.

The goal is to keep the main agent's context clean. Long waits belong in a
detached runner, watcher, or scoped subagent that writes receipt artifacts. Chat
only receives a blocker, a terminal result, or a user decision point.

## Trigger Conditions

Use this workflow for:

- Commands expected to run longer than two minutes.
- Docker image builds, `make fast-up`, integration tests, full test suites,
  pre-commit, package installs, and browser/CI watchers.
- Any repeated status check where the only new information would be "still
  running".
- Any run where raw logs may exceed a few screenfuls.

Do not use this workflow for a one-line command whose output is short and needed
immediately.

## Output Contract

- Emit at most one chat line when the run is started, including the artifact
  path.
- Do not send heartbeat updates, ETA guesses, status rereads, or progress
  narration.
- Poll state quietly. If status is still `running`, write nothing to chat.
- Speak only when status becomes `success`, `failure`, `timeout`, `error`, or a
  user decision is required.
- Any chat claim about pass/fail must point to a receipt artifact written before
  the claim.

## Artifact Shape

Use the active work item when available:

```text
$AGENTIC_OS_ACTIVE_WORK_ITEM/artifacts/async-runs/<run-id>/
  command.json
  state.json
  events.jsonl
  summary.md
  output.log
```

If there is no active work item, use:

```text
/Users/genome/agentic_os/harness/shared_factory/06-runs-and-logs/async-runs/<run-id>/
```

Never store secrets, `.env` values, bearer tokens, cookies, or copied credential
output in these artifacts.

## Runner Preference

Prefer a project or workflow-specific quiet watcher when one exists, such as a
PR watcher for GitHub checks. Otherwise use the local Agentic OS wrapper:

```bash
/Users/genome/agentic_os/harness/bin/agentic-os-quiet-run start \
  --artifact-dir "$AGENTIC_OS_ACTIVE_WORK_ITEM/artifacts" \
  --label "targeted tests" \
  --work-dir "$PWD" \
  --timeout-minutes 60 \
  -- make t TESTS=path/to/test.py
```

The wrapper starts a detached monitor and returns immediately with the run
folder. The monitor updates `state.json`, appends `events.jsonl`, and writes
command output to `output.log`.

If the wrapper is unavailable, use the same artifact shape with `nohup` or the
current harness background-process primitive.

## Context Mode Use

- Use context-mode for large log analysis: summarize `output.log` with
  `ctx_execute_file` or index/search artifacts with `ctx_index` and
  `ctx_search`.
- Do not read full logs into chat to decide what failed.
- For "still running" checks, inspect only `state.json`.

## Main-Agent Protocol

1. Choose the artifact root and run id.
2. Start the command through a quiet runner, watcher, or subagent.
3. Record the command, start time, work directory, and expected timeout.
4. Return to other useful work, or if no useful work remains, report the
   artifact path and stop the turn.
5. On resume, inspect `state.json` first. If still running, stay silent unless
   the user explicitly asked for status.
6. On terminal status, inspect summarized logs privately, update `summary.md`,
   and report only the actionable outcome with receipt path.

## Subagent Protocol

For long-running verification, prefer a scoped verification subagent over the
main chat loop. The subagent must:

- Run the command through the quiet async artifact shape.
- Avoid progress chatter.
- Return only the final status, receipt path, and next action.

## Failure Handling

- `failure`: summarize the root cause from the smallest useful log slice and
  name the next action.
- `timeout`: stop the run if the wrapper did not already do so, record whether
  the process was killed, and decide whether CI or a narrower test can
  substitute.
- `running` beyond a reasonable wall clock: do not narrate; either keep waiting
  silently, escalate one blocker with receipt, or stop and re-scope.
