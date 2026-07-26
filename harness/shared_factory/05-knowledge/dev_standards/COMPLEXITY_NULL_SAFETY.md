# Complexity And Null Safety

Focus: no multi-nested sloppy loops; explicit None/null handling at every boundary.

## Write
- No multi-nested loops where a query, comprehension, lookup table, or early
  return does the job. Cyclomatic depth beyond ~3 levels needs a
  decomposition or a written reason.
- Explicit None/null handling at every boundary crossing; no attribute access
  on possibly-None values.

## Review
- Nested-loop scans over querysets/collections that a set/dict or SQL join
  replaces are blocking at data scale.
- Missing None guards on paths reachable with real data are blocking.

Blocking: at data scale and on reachable None paths.
