# Holdout QA

1. Check guide references:

   ```bash
   rg "losmon validate|losmon_replacement|pr_review|failing_ci_triage|deploy_planning|thread_intake|losmon-comparison" docs/13-feature-guides/08-losmon-replacement-validation.md
   ```

2. Run the full test suite:

   ```bash
   uv run --extra dev pytest -q
   ```

3. Confirm the guide index links to
   `08-losmon-replacement-validation.md`.
