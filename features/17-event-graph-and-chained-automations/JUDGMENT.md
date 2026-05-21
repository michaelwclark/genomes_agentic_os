# Judgment

The event graph is intentionally deterministic and local-first. Chain rules are disabled by default, process in dry-run first, and use idempotency keys before queue writes.

This gives the OS a replayable event model without turning agents into hidden dispatchers.
