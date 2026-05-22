# Holdout QA

1. Run the full test suite:

   ```bash
   uv run --extra dev pytest -q
   ```

2. Create a temp root, remove a managed file, and run doctor:

   ```bash
   uv run agentic-os init --target "$ROOT"
   rm "$ROOT/shared_factory/05-knowledge/templates/customer/client-automation-brief.md"
   uv run agentic-os doctor --root "$ROOT"
   uv run agentic-os doctor --root "$ROOT" --fix-missing
   ```

3. Create a stale run log and inspect doctor:

   ```bash
   uv run agentic-os run-log create los feature_dev --root "$ROOT"
   uv run agentic-os doctor --root "$ROOT"
   ```

4. Exercise migration planning and apply safety:

   ```bash
   uv run agentic-os migrate apply notion-sync-readme-v1 --root "$ROOT"
   uv run agentic-os migrate plan --root "$ROOT"
   echo '# changed after preview' > "$ROOT/.notion-sync/README.md"
   uv run agentic-os migrate apply notion-sync-readme-v1 --root "$ROOT"
   uv run agentic-os migrate plan --root "$ROOT"
   uv run agentic-os migrate apply notion-sync-readme-v1 --root "$ROOT"
   ```
