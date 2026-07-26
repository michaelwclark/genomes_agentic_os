# Cleanliness And Readability

Focus: the diff reads like one thoughtful person wrote it.

## Write
- Intention-revealing names, guard clauses over nesting, no dead or
  commented-out code, no debug prints, functions do one thing.
- File and function sizes match the surrounding codebase norms.

## Review
- Flag god functions, misleading names, mixed abstraction levels, and
  unrelated drive-by edits that bloat the diff.

Blocking: no (fix when trivial, otherwise log with rationale).
