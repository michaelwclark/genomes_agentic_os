# Holdout QA

1. Check guide references:

   ```bash
   rg "doctor|--fix-missing|migrate plan|migrate apply|notion-sync-readme-v1|changed after preview" docs/13-feature-guides/07-doctor-validation-and-migrations.md
   ```

2. Run the full test suite:

   ```bash
   uv run --extra dev pytest -q
   ```

3. Confirm the guide index links to
   `07-doctor-validation-and-migrations.md`.
