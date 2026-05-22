# Holdout QA

| Command Or Check | Expected Result |
| --- | --- |
| `uv run --extra dev pytest -q` | Repository suite passes. |
| `agentic-os workflow check` | Returns readiness findings. |
| `agentic-os run-log close --status done` without validation | Fails. |
| `agentic-os run-log close --status done --validation ...` | Succeeds. |
| `agentic-os validate` | Runtime root remains valid. |

