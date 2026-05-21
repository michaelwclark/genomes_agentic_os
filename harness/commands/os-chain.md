# OS Chain

Use when normalized events should deterministically enqueue follow-up work.

## Procedure

1. Inspect `shared_factory/00-control-plane/chain-rules.yml`.
2. Keep new chain rules disabled until `chain doctor` passes.
3. Test a chain with `agentic-os chain test <chain_rule_id> --event <event_file>`.
4. Verify idempotency key, max chain depth, cooldown, approval gate, and route/context contract.
5. Process with `agentic-os event process-due --dry-run` before `--apply`.
6. Dead-letter failed events with a failure reason and next action.

## Output

Return matching rule, queue item preview, idempotency key, approval status, and replay instructions.
