# Holdout QA Results

## Guide Reference Check

```text
$ rg "losmon validate|losmon_replacement|pr_review|failing_ci_triage|deploy_planning|thread_intake|losmon-comparison" docs/13-feature-guides/08-losmon-replacement-validation.md
agentic-os losmon validate --root ~/agentic_os --repo <los_or_losmon_repo>
- project: `los/02-projects/losmon_replacement/`
  - `los/03-workflows/engineering/pr_review/`
  - `los/03-workflows/engineering/failing_ci_triage/`
  - `los/03-workflows/operations/deploy_planning/`
- automation: `los/04-automations/support/thread_intake/`
  `los/02-projects/losmon_replacement/artifacts/losmon-comparison.md`
`losmon-comparison.md` keeps migration gaps visible.
```

## Full Suite

```text
$ uv run --extra dev pytest -q
.......................................                                  [100%]
39 passed in 3.42s
```
