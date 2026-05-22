# 33 Holdout Command Validation For 07 Doctor Validation And Migrations

Validate feature 07 through public doctor and migration CLI commands in a
disposable runtime root.

## Acceptance Mapping

- Doctor reports missing managed files and stale run logs.
- `--fix-missing` restores missing managed files additively.
- Migration apply fails before a plan exists.
- Migration plan records `notion-sync-readme-v1`, approval requirement, and
  unified diff.
- Migration apply refuses changed targets after preview.
- A fresh plan followed by apply succeeds.
