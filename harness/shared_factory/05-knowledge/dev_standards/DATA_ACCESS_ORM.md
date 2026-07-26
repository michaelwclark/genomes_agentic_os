# Data Access And ORM Discipline

Focus: batched reads, deliberate relation loading, transactional invariants.

## Write
- Batch reads (select/prefetch per the stack addendum), bulk writes where the
  ORM supports them, transactions around multi-write invariants.
- Read-your-write consistency handled deliberately (primary vs replica).

## Review
- N+1 query patterns, per-row saves in loops, missing transaction boundaries
  around multi-model invariants, and replica-lag-sensitive reads before
  writes are blocking.

Blocking: always.
