# Architecture and Boundaries

- Put behavior at the layer that owns it. Keep provider transport, domain
  policy, persistence, and presentation concerns separable.
- Make dependencies explicit. Avoid hidden global state, implicit fallbacks,
  circular imports, and configuration that silently changes semantics.
- Preserve stable public contracts. Version data formats and receipts; support
  safe migration or fail with an actionable diagnostic.
- Reuse one canonical engine behind multiple adapters. Compatibility aliases
  may route to the engine but may not fork its behavior.
- For concurrency or distributed work, define ownership, idempotency,
  retryability, terminal states, and stale-lease recovery before scaling out.
