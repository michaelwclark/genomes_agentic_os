# Review Standard

Review the actual diff, its call sites, tests, configuration, migrations, and
operational effects. Prioritize findings that can cause incorrect behavior,
data loss, security or tenant leakage, compatibility breaks, unrecoverable
operations, misleading observability, or missing test coverage.

For each actionable finding, name the affected path and behavior, explain the
failure mode with concrete evidence, and state the smallest safe correction.
Do not manufacture findings to appear thorough. Distinguish blockers,
follow-ups, questions, and optional polish. Re-read the final head after repairs
before declaring it ready.

## Performance is a blocking review lane

Treat changes to request handlers, API services, serializers, managers,
selectors, queryset construction, list endpoints, and provider/object-storage
adapters as performance-risk changes even when the ticket is functional.

- Trace database, serializer, payload, and remote-I/O work through the changed
  path. A thin proxy must not become a whole-object serializer or unbounded
  relation graph without deliberate field selection/eager loading.
- Require a regression test with representative relation fan-out and an
  explicit query budget (`assertNumQueries`, `django_assert_num_queries`, or an
  equivalent stack-native assertion) for request-path or ORM relation changes.
- Require measured latency/trace evidence when the path performs remote I/O or
  builds a payload that scales with tenant data. Functional test success is not
  performance evidence.
- Withhold readiness for missing query-budget evidence, per-row database or
  remote calls, unbounded list/summary work, or evidence captured against a
  different branch, deployed revision, tenant shape, or fixture.

## Executable configuration is a blocking review lane

Treat migrations that rewrite persisted rules, jq, templates, feature flags, or
tenant data as production-code changes. Require the complete dependency
closure, exact composed runtime compilation before write, tenant-override
preservation, idempotency/recovery, and old/new pod compatibility. Row-count
tests and marker guards are not sufficient.
