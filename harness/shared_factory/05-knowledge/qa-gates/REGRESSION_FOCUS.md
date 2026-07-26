# Regression Focus

Focus: the bug that motivated the change can never silently return.

## Verify
- A regression test reproduces the exact reported failure shape (data,
  config, sequence) and fails before the fix; named/traceable to the ticket.
- Retry/repeat paths re-verified after the fix (idempotent convergence).
- Adjacent behavior that shares the changed seam gets a targeted spot check,
  not assumed coverage.

## Evidence
- The regression test path and its pre-fix failure or flake-check receipt.
- A one-line adjacency note in the packet: what nearby behavior was spot
  checked and how.

Blocking: always for changed high-risk behavior.
