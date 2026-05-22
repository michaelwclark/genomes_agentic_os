# Holdout QA Results

## Full Suite

```text
$ uv run --extra dev pytest -q
.......................................                                  [100%]
39 passed in 3.27s
```

## Customer Factory Smoke

Commands:

```bash
TMP_ROOT=$(mktemp -d /tmp/agentic-os-customer-holdout-XXXXXX)
PROFILE="$PWD/customer_profiles/example-customer.yml"
ROOT="$TMP_ROOT/acme_os"
uv run agentic-os customer init acme_ops --profile "$PROFILE" --target "$ROOT"
echo "# local holdout note" >> "$ROOT/customer/handoff-checklist.md"
uv run agentic-os customer update acme_ops --root "$ROOT"
uv run agentic-os customer validate --root "$ROOT"
grep -n "local holdout note" "$ROOT/customer/handoff-checklist.md"
grep -RInE 'Michael Clark|Genome'\''s Agentic OS|Flywheel|source-owner|source owner' "$ROOT" \
  --include='*.md' --include='*.yml' --include='*.yaml'
```

Observed validation result:

```text
ok: true
core_errors: []
profile_warnings: []
```

Observed local edit check:

```text
41:# local holdout note
```

Observed private-name scan:

```text
no private source-owner names found
```

Generated customer root included `customer.yml`, customer handoff materials,
approved domain folders, customer workflow assets, and customer automation
assets.
