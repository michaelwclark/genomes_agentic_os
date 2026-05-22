# 19 Holdout Command Validation For 00 Current State And Gap Map

Source card: https://www.notion.so/19-Holdout-Command-Validation-For-00-Current-State-And-Gap-Map-368683b48dab812fa145c9ae5900ff10

## Goal

Provide a repeatable holdout validation package for feature 00 that can be run by a fresh operator without performing live Notion writes.

## Acceptance Criteria

- Validate that feature 00 has the canonical Build Runner audit files.
- Validate that `RUN_STATE.json` records prefix 00 as done.
- Validate that source plans needed by feature 00 exist.
- Validate that a disposable installed runtime includes the plan backlog and passes `agentic-os validate`.
- Keep live Notion access out of the holdout command.
