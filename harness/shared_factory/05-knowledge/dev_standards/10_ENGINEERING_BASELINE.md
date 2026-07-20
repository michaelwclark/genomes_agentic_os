# Engineering Baseline

- Start from observable behavior and acceptance criteria, then identify the
  smallest coherent code seam that owns the invariant.
- Prefer existing good project patterns over a new local abstraction. Record a
  decision when the established pattern is unsafe or materially incomplete.
- Keep changes cohesive, reversible, and free of unrelated cleanup. Preserve
  compatibility unless the work item explicitly authorizes a break.
- Treat errors, partial failure, retries, cancellation, idempotency, and
  cleanup as first-class behavior—not afterthoughts.
- Never call work complete without evidence that the changed behavior works
  and important unchanged behavior still works.
