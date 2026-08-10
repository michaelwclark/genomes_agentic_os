# Performance Safety Gate

This policy is intentionally explicit because performance regressions often
pass ordinary unit tests while degrading production request latency.

## Required evidence

Every performance-risk diff must carry:

1. an exact changed-path classification;
2. a representative fan-out fixture and bounded query-count assertion;
3. deliberate relation loading or bounded projection evidence; and
4. a measured remote-call/latency receipt when SQL, object storage, or a
   provider is involved.

The evidence names the exact reviewed head and fixture shape and stays local;
external tracker/PR text receives only a scrubbed summary.

## Gate

Run `harness/bin/agentic-os-performance-gate` before review. The command fails
closed when a request-path diff has no query-budget regression test. It is a
necessary screening check, not a substitute for reviewer inspection of the
actual budget and runtime evidence.

Blocking: always for missing evidence, unbounded work, N+1 query growth, or
per-row remote I/O.
