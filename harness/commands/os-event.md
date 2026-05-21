# OS Event

Use when a source change, run closeout, approval, external action, or agent output should become durable event evidence.

## Procedure

1. Normalize the occurrence into an event envelope.
2. Link payloads instead of copying secrets, full transcripts, or large private records.
3. Record an idempotency key and correlation ID.
4. Append the event to `shared_factory/06-runs-and-logs/events/`.
5. Run `agentic-os event process-due --dry-run` before applying chain rules.

## Output

Return the event file, ledger entry, matched chain rules, dry-run queue items, and next action.
