# Documentation and Observability

- Name things for the domain behavior they own. Public APIs, schemas, events,
  state transitions, and failure codes should be searchable and unambiguous.
- Comments explain why a non-obvious invariant, historical edge case, fallback,
  or recovery seam exists; they do not narrate syntax.
- Emit the minimum useful telemetry for success, latency, failure class,
  retries, queue age, and terminal outcome. Avoid unbounded cardinality and
  sensitive payloads.
- Update operator docs, runbooks, configuration examples, and failure recovery
  whenever behavior or ownership changes.
- A run is not complete until another agent can identify the result, evidence,
  unresolved gaps, and next action from its receipts without chat history.
