# os-quiet-run

Start long-running local commands with artifact-backed state so agents do not
keep chat alive with polling.

## Command

```bash
/Users/genome/agentic_os/harness/bin/agentic-os-quiet-run start \
  --artifact-dir "$AGENTIC_OS_ACTIVE_WORK_ITEM/artifacts" \
  --label "targeted tests" \
  --work-dir "$PWD" \
  --timeout-minutes 60 \
  -- make t TESTS=path/to/test.py

/Users/genome/agentic_os/harness/bin/agentic-os-quiet-run status \
  --run-dir <run-dir> --json
```

## Use When

- A command is expected to run longer than two minutes.
- Docker, dependency setup, test suites, pre-commit, CI checks, or watchers would
  otherwise cause repeated status messages.
- Raw output is too large for chat and should be inspected from an artifact.

## Output

The start command creates:

```text
<artifact-dir>/async-runs/<run-id>/
  command.json
  state.json
  events.jsonl
  summary.md
  output.log
```

The command returns immediately. Agents should inspect only `state.json` for
status and use context-mode against `output.log` for failure summarization.

## Chat Rule

After starting a quiet run, report at most the artifact path. Do not report
"still running" updates. Report only terminal success, failure, timeout, error,
or a user decision point, with the receipt path.
