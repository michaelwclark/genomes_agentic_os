# Holdout QA Results

## Full Suite

```text
$ uv run --extra dev pytest -q
.......................................                                  [100%]
39 passed in 3.44s
```

## Doctor And Migration Smoke

```text
doctor_missing_exit=1; ok=False; blocker_count=1
doctor_fix_ok=True; repairs=init os,install docs; missing_restored=True
stale_run_findings=1
apply_before_plan_exit=2
migration_id=notion-sync-readme-v1; approval_required=True; diff_has_unified=True
drift_exit=2
apply_ok=True; target=/private/tmp/agentic-os-doctor-holdout-ERCpMA/os/.notion-sync/README.md
```
