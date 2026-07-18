# Execution Fabric Verification

- Fresh install contains the complete program, command, and skill projection.
- Default readback is inactive with filesystem queue mode.
- Queue and worker-pool defaults are disabled, bounded, and schema-valid.
- The vendor-neutral task envelope schema accepts the canonical task contract.
- Update installs a missing program additively.
- Update preserves operator-modified program configuration.
- First-class resource refresh discovers the program and its configuration.
- Full installed-root validation remains green.
- Codex, Claude, and non-LLM work resolve to distinct bounded queues.
- One supervisor tick runs a bounded concurrent batch while preserving one
  interactive slot and all provider/queue/pool limits.
- Priority schedules supersede stale duplicates, receive queue priority, and
  join the concurrent batch instead of serially blocking the tick.
- Legacy shell-wrapped Codex/Claude commands route to the matching provider,
  while comments alone cannot trigger provider inference.
- Detached quiet runs and watcher-owned workers hold their fabric lease until
  terminal state and inherit their declared timeout budget.
- Authoritative readers ignore stale inactive-backend projections.
- Queue admission rejects work at `max_queued`.
- Command Center exposes backend-neutral queue and worker health.
- The runtime snapshot CLI renders readable and deterministic JSON views,
  supports queue/status/limit filters, writes atomic receipts, and never exposes
  raw execution payloads, references, free-form failure text, or lease tokens.
- Concurrent writers cannot split snapshot totals from task/worker rows, and
  concurrent receipt writers use unique atomic sibling files.
- Command Center uses the same snapshot contract for detailed named-queue,
  worker-pool, worker, and explicitly sample-scoped filtered task views.
- The explicit interactive cap applies only in Execution Fabric mode;
  filesystem mode preserves legacy cross-conversation concurrency.
- An unhealthy report creates one idempotent Codex self-heal task and one
  deduplicated governed notification; the Codex repair remains directly leased
  for its entire run.
- The interim executor delegates only to the canonical supervisor.
