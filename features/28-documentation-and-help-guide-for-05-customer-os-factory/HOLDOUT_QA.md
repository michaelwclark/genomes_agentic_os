# Holdout QA

1. Check that the guide contains the required command and validation terms:

   ```bash
   rg "customer init|customer update|customer validate|core_errors|profile_warnings|private source" docs/13-feature-guides/05-customer-os-factory.md
   ```

2. Run the full test suite:

   ```bash
   uv run --extra dev pytest -q
   ```

3. Confirm the guide index links to `05-customer-os-factory.md`.
