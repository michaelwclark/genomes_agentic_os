# Holdout QA Results

## Full Suite

```text
$ uv run --extra dev pytest -q
.......................................                                  [100%]
39 passed in 3.44s
```

## LOSMon Validation Smoke

```text
project_exists=True
workflow_dirs=failing_ci_triage,pr_review; ops=deploy_planning
automation_exists=True
run_logs=3; returned_run_logs=3
artifact_exists=True; comparison_has_gap=True; repo_recorded=True
required_paths_present=True
valid: /tmp/agentic-os-losmon-holdout-kDX5JG/os
```
