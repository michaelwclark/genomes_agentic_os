# Performance And Leaks

Focus: hot paths stay fast and long-lived processes do not grow.

## Write
- No unbounded caches or accumulating module-level state; close or
  context-manage files, connections, and cursors.
- Stream or paginate large datasets; move heavy work out of request paths;
  no O(n) network/DB calls inside loops.

## Review
- Check hot paths for growth over time (long-lived processes and workers
  leak first), repeated identical lookups, missing pagination on list
  endpoints, and payloads that scale with tenant data size.

Blocking: always for leaks and hot-path regressions.
