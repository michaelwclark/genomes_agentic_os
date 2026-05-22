# Validation Log

## Environment

- Worktree: `/Users/genome/projects/.worktrees/build-runner-59`
- Main baseline merged into branch: feature 58 completion from `main`
- Holdout root: `/tmp/agentic-os-config-holdout-D7rPo2`

## Commands Executed

```bash
uv run agentic-os --help
uv run agentic-os config install --help
uv run agentic-os config doctor --help
```

Layer matrix:

```bash
for layer in global_harness agentic_os_root customer_os_root domain_or_lane workflow_or_task automation; do
  agentic-os config install --root "$tmp/$layer" --layer "$layer" --dry-run
  agentic-os config install --root "$tmp/$layer" --layer "$layer" --apply
  agentic-os config install --root "$tmp/$layer" --layer "$layer" --apply
  agentic-os config doctor --root "$tmp/$layer" --layer "$layer"
done
```

Conflict and missing-config paths:

```bash
agentic-os config install --root "$tmp/conflict-domain" --layer domain_or_lane --apply
agentic-os config install --root "$tmp/conflict-domain" --layer domain_or_lane --apply --confirm-conflicts --backup
agentic-os config doctor --root "$tmp/conflict-domain" --layer domain_or_lane
agentic-os config doctor --root "$tmp/missing-config" --layer agentic_os_root
uv run --extra dev pytest -q
```

## Results

| Check | Result |
| --- | --- |
| `agentic-os --help` | listed `config` command |
| `agentic-os config install --help` | listed root, layer, dry-run, apply, backup, and confirm-conflicts |
| `agentic-os config doctor --help` | listed root and layer |
| All six layer dry-runs | passed with no target writes |
| All six layer applies | passed |
| All six layer repeated applies | passed idempotently |
| All six layer doctors | passed |
| Conflict apply without confirmation | blocked as expected |
| Conflict apply with confirmation and backup | passed, backup present |
| Doctor after confirmed conflict merge | passed |
| Missing config doctor | failed as expected with remediation |
| Full test suite | 46 passed in 3.14s |

## Summarizer Output

- All six Agentic OS config layers were exercised through dry-run, apply,
  idempotent re-run, and doctor validation.
- Dry-run mode produced no target directory writes for every layer.
- Apply mode generated `config.toml` and the layer prompt files, and repeated
  apply remained idempotent.
- Conflict handling blocked an unconfirmed local `model` override, then
  succeeded with `--confirm-conflicts --backup` while preserving the local
  value.
- `config doctor` passed after confirmed conflict merge and failed as expected
  for a missing config directory.
- The full test suite passed with 46 tests.
