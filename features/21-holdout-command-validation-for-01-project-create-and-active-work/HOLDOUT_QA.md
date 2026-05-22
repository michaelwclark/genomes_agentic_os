# Holdout QA

## Command Matrix

| Command Or Check | Expected Result |
| --- | --- |
| `uv run --extra dev pytest -q` | Repository suite passes. |
| `agentic-os init --target <tmp-root>` | Temporary OS root is created. |
| `agentic-os project create los losmon_replacement --repo <repo> --notion <url> --jira FLYWL --lane engineering --root <tmp-root>` | Project is created under `los`. |
| `agentic-os validate --root <tmp-root>` | Root is valid. |
| Project file, active-work row, and source-map checks | Required files and refs exist. |
| Rerun after manual status edit | Manual edit remains. |
| `agentic-os project create lenders loan_ops --root <tmp-root>` | Project writes under `los`; no `lenders` domain is created. |
| Invalid project name | Command fails. |

