# Holdout QA

Run from a clean feature worktree.

1. Run the full test suite:

   ```bash
   uv run --extra dev pytest -q
   ```

2. Create a disposable installed OS root and project:

   ```bash
   TMP_ROOT=$(mktemp -d /tmp/agentic-os-automation-holdout-XXXXXX)
   ROOT="$TMP_ROOT/os"
   uv run agentic-os init --target "$ROOT"
   uv run agentic-os project create support support_intake --root "$ROOT" \
     --repo /tmp/support-intake --notion https://www.notion.so/support \
     --jira SUPPORT --lane ready
   ```

3. Create, inspect, and safely reconfigure an automation:

   ```bash
   uv run agentic-os automation create support support thread_intake --root "$ROOT"
   uv run agentic-os automation check support support thread_intake --root "$ROOT"
   uv run agentic-os automation set-maturity support support thread_intake propose --root "$ROOT"
   uv run agentic-os automation set-maturity support support thread_intake prepare --root "$ROOT"
   uv run agentic-os automation attach support support thread_intake --project support_intake --root "$ROOT"
   ```

4. Validate the root and inspect project evidence:

   ```bash
   uv run agentic-os validate --root "$ROOT"
   grep -RIn "thread_intake\|prepare\|support_intake" "$ROOT/support" "$ROOT/00-control-plane"
   ```
