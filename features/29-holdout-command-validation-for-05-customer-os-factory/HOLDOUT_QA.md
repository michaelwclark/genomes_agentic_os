# Holdout QA

Run from a clean feature worktree.

1. Run the full test suite:

   ```bash
   uv run --extra dev pytest -q
   ```

2. Create a disposable customer OS root:

   ```bash
   TMP_ROOT=$(mktemp -d /tmp/agentic-os-customer-holdout-XXXXXX)
   PROFILE="$PWD/customer_profiles/example-customer.yml"
   ROOT="$TMP_ROOT/acme_os"
   uv run agentic-os customer init acme_ops --profile "$PROFILE" --target "$ROOT"
   ```

3. Add a local edit and run additive update:

   ```bash
   echo "# local holdout note" >> "$ROOT/customer/handoff-checklist.md"
   uv run agentic-os customer update acme_ops --root "$ROOT"
   grep -n "local holdout note" "$ROOT/customer/handoff-checklist.md"
   ```

4. Validate the generated customer root:

   ```bash
   uv run agentic-os customer validate --root "$ROOT"
   ```

5. Scan generated markdown and YAML for private source-owner names:

   ```bash
   grep -RInE 'Michael Clark|Genome'\''s Agentic OS|Flywheel|source-owner|source owner' "$ROOT" \
     --include='*.md' --include='*.yml' --include='*.yaml'
   ```
