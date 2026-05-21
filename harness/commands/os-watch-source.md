# OS Watch Source

Use when a connected system needs a reviewable, provider-agnostic watch source before work is dispatched.

## Procedure

1. Identify the connected system, provider priority, credential references, and workspace verification rule.
2. Declare the exact watch source, source type, external reference, cadence, cursor, and idempotency key.
3. Keep new sources disabled until the doctor passes.
4. Run `agentic-os watch-source poll <source_id> --dry-run` before any apply path.
5. Convert provider output into normalized source events before routing or queueing work.
6. Record approval gates for external writes, customer-visible output, production, billing, legal, destructive, or credential-sensitive actions.

## Output

Return the registry paths, selected provider, doctor findings, dry-run event preview, and next action.
