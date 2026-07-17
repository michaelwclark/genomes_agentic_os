# Context: Project Domain Intelligence

## Source precedence

1. Checked-out project source, tests, configuration, and runtime observations.
2. Evidence-backed domain articles and their freshness status.
3. The domain context receipt consumed by the current development entrypoint.
4. Generated summaries and reports.

Articles guide investigation; they never establish source-code correctness.
Stale or invalid articles are excluded or explicitly downgraded. A missing
index fails open only with a `no_context` receipt, never invented guidance.
