# Spec

Add a file-backed event graph for normalized events and deterministic chain rules.

## Scope

- Append normalized event envelopes.
- Maintain an inspectable ledger index.
- Test and process disabled-by-default chain rules.
- Write local queue items, processing results, idempotency state, and dead-letter records.
- Let run-log closeout emit linked event evidence.

## Out Of Scope

- Invisible agent-to-agent handoff.
- External writes or live provider calls.
- Concurrent processors or database-backed locks.
