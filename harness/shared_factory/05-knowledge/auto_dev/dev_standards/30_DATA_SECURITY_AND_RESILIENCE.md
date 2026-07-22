# Data, Security, and Resilience

- Minimize data read, mutation scope, and retention. Do not place secrets,
  credentials, private links, customer data, or raw production evidence in
  source, prompts, external artifacts, logs, or fixtures.
- Validate at trust boundaries and preserve tenant/account isolation across
  reads, writes, caches, background work, and error paths.
- Make mutations transactional or explicitly compensating. Record durable
  receipts for external effects and verify them by readback.
- Classify unavailable infrastructure separately from code failure. Retry only
  failures known to be recoverable and cap every retry loop.
- Design migrations, backfills, and destructive operations with rollback,
  observability, bounded batches, and interruption-safe resumption.
