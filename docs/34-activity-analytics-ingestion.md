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

## Automatic local collection

An enabled, opted-in `agentic_os` source can collect canonical local event ledger files and runtime `run-log.yml` receipts without a fixture:

```bash
agentic-os activity collect-local agentic_os_local --root ~/agentic_os --limit 25 --dry-run
agentic-os activity collect-local agentic_os_local --root ~/agentic_os --limit 25 --apply
```

The collector reads only `events/evt_*.yml` and `runs/*/run-log.yml`. It derives a stable record hash, timestamp, canonical event type, and allowlisted status/kind metadata. It never projects summaries, commands, arguments, stdout/stderr, payloads, paths, URLs, credentials, customer data, email addresses, prompts, responses, or message bodies.

Run/tool receipts map to `os.automation.ran` or `os.tool.ran`; failed, error, unavailable, and regression evidence maps to `os.error.recorded`; canonical message events map to `os.conversation.message`. Unknown evidence is counted as unsupported and skipped.

The filesystem cursor is ordered by receipt modification time plus a hashed relative identity. Dry-run does not mutate it. Apply mode advances the cursor only through the bounded scanned batch; malformed receipts produce degraded health without exposing their path or contents. Disable the source to stop collection. Cursor and activity event files are the bounded rollback surfaces.
