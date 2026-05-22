# 23 Holdout Command Validation For 02 Routing And Context Builder

## Scope

Run a fresh holdout validation pass for routing and context packet behavior from
feature 02.

## Acceptance Criteria

- Execute `agentic-os route` against a project request.
- Execute `agentic-os context build` against explicit domain/project inputs.
- Execute `agentic-os here context build` from a linked repository.
- Confirm low-confidence routing fails instead of guessing.
- Summarize residual risk and documentation alignment.

