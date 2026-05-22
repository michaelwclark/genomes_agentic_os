# Holdout QA Results

## Guide Reference Check

```text
$ rg "doctor|--fix-missing|migrate plan|migrate apply|notion-sync-readme-v1|changed after preview" docs/13-feature-guides/07-doctor-validation-and-migrations.md
- [Doctor Commands](#doctor-commands)
- [Doctor Findings](#doctor-findings)
This repository owns the doctor checks, managed repair rules, and migration
agentic-os doctor --root ~/agentic_os
agentic-os doctor --root ~/agentic_os --fix-missing
`--fix-missing` only runs additive managed-file repairs.
agentic-os migrate plan --root ~/agentic_os
agentic-os migrate apply notion-sync-readme-v1 --root ~/agentic_os
The current migration ID is `notion-sync-readme-v1`.
`migrate plan` writes `.migrations/notion-sync-readme-v1.yml`
`migrate apply` reads that saved preview before writing.
If migration apply says the target changed after preview, do not force apply.
```

## Full Suite

```text
$ uv run --extra dev pytest -q
.......................................                                  [100%]
39 passed in 3.26s
```
