# Activity analytics ingestion

`agentic-os activity` turns provider records into metadata-only analytics events without storing message bodies, prompts, credentials, customer data, or private links.

Sources are explicitly opted in at `harness/shared_factory/00-control-plane/activity-sources.yml`. Every source declares its provider, registered domain/project scope, dimensions, and event-to-metric bindings. Metric IDs must exist in `harness/registries/analytics-metrics.yml`; renderers consume those bindings and never execute provider queries.

```yaml
schema_version: 1
activity_sources:
  - id: command_center_github
    provider: github
    enabled: true
    opt_in: true
    scope: {domain: clarks_consulting, project: agentic_harness}
    dimensions: {repository: genomes_agentic_harness}
    metric_bindings: {github.pull_request.opened: tool_runs}
    limits: {max_pages_per_run: 20}
```

Collectors supply credential-free pages using `sources: [{id, pages: [{items, next_cursor, rate_limit_remaining}]}]`.

```bash
agentic-os activity validate --root ~/agentic_os
agentic-os activity ingest fixture.yml --root ~/agentic_os --dry-run
agentic-os activity ingest fixture.yml --root ~/agentic_os --apply
agentic-os activity health --root ~/agentic_os
```

Apply mode writes stable, deduplicated envelopes under `source-events/activity/`, advances per-source cursors, and records freshness, completeness, rate-limit state, and the last error. A failed source does not prevent other sources from ingesting.
