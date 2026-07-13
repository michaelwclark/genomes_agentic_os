# OS Cockpit

Use when the operator asks to open the Agentic OS cockpit, inspect current work
across domains, find conversations or reports, review source suggestions, or
see host and cleanup state together.

Primary skill: `cockpit`.

## CLI Surface

```bash
agentic-os cockpit snapshot --root ~/agentic_os
agentic-os cockpit build --root ~/agentic_os
agentic-os cockpit open --root ~/agentic_os
```

Use `--no-harness-sessions` when the projection should exclude local
Claude/Codex session metadata. Use `--max-files` to bound collection.

## Operating Contract

1. Treat filesystem work items, registries, logs, and reports as authoritative.
2. Build a disposable versioned JSON snapshot.
3. Render a self-contained local HTML projection with no permanent server.
4. Show full-source links and guarded CLI suggestions; do not execute cleanup,
   configure watchers, contact hosts, or write to external systems.
5. If an optional source is malformed, preserve the remaining cockpit and show
   a diagnostic.

## Output

Default artifacts:

```text
~/agentic_os/harness/shared_factory/06-runs-and-logs/cockpit/latest/
  snapshot.json
  index.html
```

## Safety

- Collection is local and read-only.
- Harness transcripts are ingested as bounded metadata; raw prompts are not
  displayed by the v1 collector.
- No secret environment values, raw connector payloads, or credentials belong
  in the snapshot.
- Cleanup commands are copyable plans only.
- Notion, Jira, GitHub, Slack, remote hosts, and customer OS installs are not
  mutated by cockpit generation.
