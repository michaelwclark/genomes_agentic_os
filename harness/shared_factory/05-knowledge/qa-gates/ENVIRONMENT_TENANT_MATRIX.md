# Environment And Tenant Matrix

Focus: validation runs where the behavior actually differs.

## Verify
- Identify which environments (local, QA, preprod, prod-adjacent) and which
  tenant/config shapes change the behavior; validate each distinct cell, not
  just the default.
- Multi-tenant changes prove isolation: the other-tenant path is exercised,
  not reasoned about.
- Config-gated behavior is verified in both gate positions when both ship.

## Evidence
- A small matrix (environment x tenant/config x result) in the packet or QA
  handoff; cells marked verified / not-applicable / deferred-to-human with
  reasons.

Blocking: when a distinct cell that changes behavior was never exercised.
