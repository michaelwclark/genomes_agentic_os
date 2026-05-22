# 27 Holdout Command Validation For 04 Automation Maturity And Reconfiguration

Validate feature 04 through the public CLI in a disposable installed OS root.

## Source Feature

- `features/04-automation-maturity-and-reconfiguration/SPEC.md`
- `features/04-automation-maturity-and-reconfiguration/HOLDOUT_QA.md`
- `docs/13-feature-guides/04-automation-maturity-and-reconfiguration.md`

## Acceptance Mapping

- `automation check` reports required contract and maturity evidence gaps.
- New automations start at `observe`.
- `set-maturity ... prepare` succeeds as a safe start level.
- Higher levels such as `propose` are blocked until file-first evidence exists.
- `automation attach` writes project status and source-map references.
- The installed OS root remains valid after reconfiguration.
