# 35 Holdout Command Validation For 08 Losmon Replacement Validation

Validate feature 08 through public CLI commands in a disposable runtime root.

## Acceptance Mapping

- `agentic-os losmon validate` creates `losmon_replacement`.
- PR review, failing CI triage, and deploy planning workflows exist.
- `thread_intake` automation exists.
- Three validation run logs are created and closed.
- `losmon-comparison.md` exists and names migration gaps.
- The generated runtime root validates.
