# Holdout QA

Run from a clean feature worktree.

1. Run the full test suite:

   ```bash
   uv run --extra dev pytest -q
   ```

2. Create a disposable runtime root:

   ```bash
   TMP_ROOT=$(mktemp -d /tmp/agentic-os-notion-sync-holdout-XXXXXX)
   ROOT="$TMP_ROOT/os"
   uv run agentic-os init --target "$ROOT"
   uv run agentic-os project create los losmon_replacement --root "$ROOT" \
     --repo /tmp/losmon --notion https://www.notion.so/losmon --jira DLOS --lane ready
   uv run agentic-os workflow create los engineering feature_dev --root "$ROOT"
   uv run agentic-os automation create los support production_thread_intake --root "$ROOT"
   uv run agentic-os run-log create los feature_dev --root "$ROOT"
   ```

3. Validate planning, refusal, apply, and no-op dry-run:

   ```bash
   uv run agentic-os notion plan-sync --root "$ROOT"
   uv run agentic-os notion sync --root "$ROOT" --apply
   uv run agentic-os notion sync --root "$ROOT" --apply --verified-workspace "Genome's Notion"
   uv run agentic-os notion sync --root "$ROOT" --dry-run
   test -f "$ROOT/.notion-sync/mapping.yml"
   ```
