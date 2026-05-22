# 21 Holdout Command Validation For 01 Project Create And Active Work

## Scope

Run a fresh holdout validation pass for `agentic-os project create` and the
active-work project state created by feature 01.

## Acceptance Criteria

- Execute project creation in an isolated temporary OS root.
- Confirm project files, active-work index rows, project source references, and
  validation.
- Confirm reruns preserve an existing local edit.
- Confirm the `lenders` domain alias normalizes to `los`.
- Confirm invalid project names fail instead of creating bad runtime state.

