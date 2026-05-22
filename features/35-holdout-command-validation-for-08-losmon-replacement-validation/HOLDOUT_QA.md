# Holdout QA

1. Run the full test suite:

   ```bash
   uv run --extra dev pytest -q
   ```

2. Create a temp root and generate the LOSMon package:

   ```bash
   uv run agentic-os init --target "$ROOT"
   uv run agentic-os losmon validate --root "$ROOT" --repo /tmp/losmon-repo
   uv run agentic-os validate --root "$ROOT"
   ```

3. Confirm:

   - `los/02-projects/losmon_replacement/` exists.
   - `pr_review`, `failing_ci_triage`, and `deploy_planning` workflows exist.
   - `los/04-automations/support/thread_intake/` exists.
   - three run logs exist.
   - `losmon-comparison.md` includes `LOSMon Still Better / Required`.
