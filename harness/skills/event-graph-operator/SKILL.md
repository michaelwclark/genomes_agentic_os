# Event Graph Operator

Use this skill to append events, inspect the event ledger, test chain rules, and process follow-up work safely.

## Workflow

1. Load event state from `shared_factory/00-control-plane/event-graph.yml`, `chain-rules.yml`, and `event-cursors.yml`.
2. Inspect event envelopes in `shared_factory/06-runs-and-logs/events/`.
3. Use dry-run chain processing before queue writes.
4. Check idempotency and max chain depth before enabling a rule.
5. Write dead-letter records when an enabled rule cannot be processed.
6. Summarize pending follow-up from durable events and queue items, not chat history.

## Done

- Event evidence exists on disk.
- Chain transitions are inspectable and replayable.
- No external action happens without the configured approval gate.
