# Holdout QA Results

Passed.

| Command Or Check | Exit | Result |
| --- | ---: | --- |
| `uv run --extra dev pytest -q` | 0 | `39 passed in 3.40s` |
| `agentic-os init --target <tmp-root>` | 0 | Runtime root created. |
| `agentic-os project create los losmon_replacement ...` | 0 | Project state created. |
| `agentic-os validate --root <tmp-root>` | 0 | Root reported valid. |
| `project.yml`, active-work, and source-map checks | 0 | Required project state and references exist. |
| Rerun after manual status edit | 0 | Manual edit remained in `status.md`. |
| `agentic-os project create lenders loan_ops --root <tmp-root>` | 0 | Project created under `los`; no `lenders` domain created. |
| Invalid project name | non-zero | Bad slug rejected. |

Residual risk: the direct API/Notion URL is recorded as a reference string only;
this holdout does not validate remote Notion reachability for project records.

