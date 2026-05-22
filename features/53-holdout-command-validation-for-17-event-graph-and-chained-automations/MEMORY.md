# Memory

Feature 17 holdout confirms `event process-due --apply` writes run queue items,
processing results, and idempotency state locally. Repeated apply skips already
processed idempotency keys.

Broken enabled chain rules produce dead-letter records for operator review.
