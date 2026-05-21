# Holdout QA

## Checks

- Fresh install contains event graph templates, commands, and skill.
- `docs update` restores missing event graph command and template.
- `event append` writes an event file and ledger index row.
- `chain test` previews a queue item from a matching event.
- `event process-due --dry-run` does not write queue items.
- `event process-due --apply` writes queue items once and skips duplicate idempotency keys.
- Broken enabled rules write dead-letter records.
- `run-log close --emit-events` writes global and run-local event evidence.
