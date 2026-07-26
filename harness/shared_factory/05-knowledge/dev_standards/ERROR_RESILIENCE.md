# Error Handling And Resilience

Focus: loud failures with context, recovery only where meaningful, idempotent retries at the boundary.

## Write
- Fail loudly with context (ids, operation) at the failure point; catch only
  where recovery or translation happens.
- Retries live at the boundary (task/queue/port) with idempotency, not
  scattered in business logic; external side effects are recorded or
  outboxed when they must survive failure.

## Review
- Swallowed exceptions, bare excepts, retry loops without idempotency, and
  partial multi-system writes without a recovery story are blocking.

Blocking: always.
