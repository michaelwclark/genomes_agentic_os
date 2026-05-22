# Memory

- Feature 15's runtime holdout command shape is mixed: base install uses `agentic-os init --target <root>`, while runtime and validation commands use `--root <root>`.
- `notion track-runtime --apply` fails closed with exit 2 unless `--verified-workspace "Genome's Notion"` is supplied.
- `schedule run-due --dry-run` can report queued schedule items without persisting `runtime-run-queue.yml`; that is expected dry-run behavior in this holdout.
