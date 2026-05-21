# Memory

Event graph state is local-first:

- Rules: `shared_factory/00-control-plane/chain-rules.yml`
- Queue: `shared_factory/00-control-plane/run-queue.yml`
- Events: `shared_factory/06-runs-and-logs/events/`
- Dead letters: `shared_factory/06-runs-and-logs/events/dead-letter/`

Use dry-run processing before apply and keep new chain rules disabled until `chain doctor` passes.
