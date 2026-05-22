# Holdout QA Results

Passed.

| Command Or Check | Exit | Result |
| --- | ---: | --- |
| `uv run --extra dev pytest -q` | 0 | `39 passed in 3.40s` |
| `workflow create` and `workflow check` | 0 | Workflow state created and readiness findings returned. |
| `run-log create` | 0 | Run log directory created. |
| Done closeout without validation | non-zero | Error contained `cannot close a run as done without validation evidence`. |
| Done closeout with validation | 0 | Closeout succeeded with summary, validation, artifact, approval, next action, learning, and project linkage. |
| `agentic-os validate --root <tmp-root>` | 0 | Root reported valid. |

Residual risk: this validates filesystem closeout behavior, not external
approval workflow integrations.

