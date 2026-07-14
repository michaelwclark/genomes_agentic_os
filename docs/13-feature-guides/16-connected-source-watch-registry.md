# 16 Connected Source Watch Registry

## Table Of Contents

- [Purpose](#purpose)
- [Installed Surface](#installed-surface)
- [Operating Flow](#operating-flow)
- [Commands](#commands)
- [Registry Files](#registry-files)
- [Creating A Watch Source](#creating-a-watch-source)
- [Dry-Run And Apply Behavior](#dry-run-and-apply-behavior)
- [Doctor Checks](#doctor-checks)
- [Validation](#validation)
- [Troubleshooting](#troubleshooting)
- [Source Artifacts](#source-artifacts)

## Purpose

The connected source watch registry gives the OS a file-backed way to describe
external sources before automation reads from them.

Use it when a workflow needs to watch a Notion database, local file source, or
future provider-backed source without turning Notion into the runtime database.
The registry records the connected system, provider priority, source identity,
cursor, dedupe rule, trigger route, and output path. Polling can run in dry-run
mode before any local event file or cursor state is written.

## Installed Surface

Feature 16 installs these runtime knowledge files:

```text
shared_factory/05-knowledge/templates/runtime/connected-system.yml
shared_factory/05-knowledge/templates/runtime/source-provider.yml
shared_factory/05-knowledge/templates/runtime/watch-source.yml
shared_factory/05-knowledge/templates/runtime/watch-cursor.yml
shared_factory/05-knowledge/templates/runtime/source-event.yml
shared_factory/05-knowledge/templates/runtime/trigger-rule.yml
shared_factory/05-knowledge/commands/os-watch-source.md
shared_factory/05-knowledge/skills/source-watcher/SKILL.md
shared_factory/05-knowledge/references/source-priority.md
```

The installed runtime registries live under:

```text
shared_factory/00-control-plane/connected-systems.yml
shared_factory/00-control-plane/source-providers.yml
shared_factory/00-control-plane/watch-sources.yml
shared_factory/00-control-plane/watch-cursors.yml
shared_factory/06-runs-and-logs/source-events/
```

## Operating Flow

```text
connected system registry
  -> provider selection
  -> watch source definition
  -> watch source doctor
  -> dry-run poll
  -> normalized source event preview
  -> apply poll or run-due
  -> source event file and cursor state
```

The flow stays local until an integration-specific provider is added. The
current poll operation emits a normalized event from registry metadata; it does
not read the external system during dry-run.

## Commands

List connected systems and selected providers:

```bash
agentic-os connected-system list --root ~/agentic_os
```

Check one connected system:

```bash
agentic-os connected-system doctor notion_genome --root ~/agentic_os
```

List watch sources:

```bash
agentic-os watch-source list --root ~/agentic_os
```

Create a watch source:

```bash
agentic-os watch-source create agentic_os_kanban \
  --root ~/agentic_os \
  --external-ref database_id=366683b48dab81a1ab5fc73e7e1f5c60 \
  --enabled
```

Check one watch source:

```bash
agentic-os watch-source doctor agentic_os_kanban --root ~/agentic_os
```

Preview one source poll:

```bash
agentic-os watch-source poll agentic_os_kanban --root ~/agentic_os --dry-run
```

Dry-run output includes the selected provider adapter metadata and any matching
trigger action previews. It must not write source event files, event-ledger
events, cursor state, or run-queue items.

Poll enabled sources and write local source events:

```bash
agentic-os watch-source run-due --root ~/agentic_os --apply
```

Validate the installed OS after template or registry changes:

```bash
agentic-os validate --root ~/agentic_os
```

## Registry Files

`connected-systems.yml` describes durable systems such as `notion_genome` and
`filesystem_local`. Each connected system can declare provider priority,
credential references, workspace verification expectations, permissions,
approval gates, and a health-check command.

`source-providers.yml` describes provider capabilities. Feature 16 ships
planned entries for Composio, Notion MCP, Notion connector, direct API, and an
available local filesystem provider.

`watch-sources.yml` describes the source to poll. A source includes:

- `connected_system`
- `source_type`
- `external_ref`
- `watch_method`
- `cadence`
- `enabled`
- `cursor`
- `dedupe`
- `trigger_rules`
- `route`
- `outputs`

`watch-cursors.yml` stores the last applied event cursor per watch source.
Dry-run polling does not update this file. Apply mode records the emitted event
ID and timestamp.

`source-events/` stores normalized source event YAML files produced by apply
mode. Downstream event graph and chain commands can consume those files without
querying the external source again.

Inline `trigger_rules` can convert a source event into a local event-ledger
event, a run-queue item, or both. This gives source watchers a deterministic
handoff path without relying on chat history.

## Creating A Watch Source

The default `watch-source create` command creates a Notion database source
connected to `notion_genome`. The only required argument is the source ID.

Use `--external-ref key=value` to capture provider-specific identity without
hard-coding a provider API call into the registry. You can pass the option more
than once.

Use `--route-to <domain>` when the fallback route should land outside
`shared_factory`.

Use `--enabled` only after the source can pass doctor checks. Disabled sources
remain in the registry and are skipped by `watch-source run-due`.

## Dry-Run And Apply Behavior

`watch-source poll <source_id> --dry-run` returns a normalized source event
preview with:

- source watch ID
- connected system
- selected provider
- source type
- dedupe idempotency key
- route metadata
- dry-run marker

Dry-run mode does not write source event files and does not update cursor
state.

`watch-source poll <source_id> --apply` writes one event file under
`shared_factory/06-runs-and-logs/source-events/` and records the cursor in
`shared_factory/00-control-plane/watch-cursors.yml`.

If an enabled trigger rule matches, apply mode can also emit an event under
`shared_factory/06-runs-and-logs/events/` and enqueue work in
`shared_factory/00-control-plane/run-queue.yml`. Queue writes are idempotent by
the trigger rule's idempotency key.

`watch-source run-due --apply` polls every enabled source and skips disabled
sources. Use `run-due --dry-run` before apply when operating a new registry.

## Doctor Checks

`connected-system doctor` fails closed when a connected system has no provider
priority, references missing providers, has no healthy selected provider, or is
missing expected workspace verification or health-check metadata.

`watch-source doctor` fails closed when a source is missing its connected
system, source type, external reference, cursor type or state reference,
dedupe idempotency key, or route command/context/fallback values. Enabled
sources must also keep at least one trigger rule, and enabled trigger rules
must declare an ID, event type, action, and idempotency key.

These checks are structural. Provider-specific live reads should be added
behind explicit integration approval and should preserve the same dry-run first
posture.

## Validation

Run the full validation command after install, docs update, or manual registry
edits:

```bash
agentic-os validate --root ~/agentic_os
```

Validation should confirm that the watch-source command prompt, source-watcher
skill, runtime source templates, and source-priority reference are present in
the installed OS.

For source-package development, run:

```bash
uv run --extra dev pytest -q
```

The test suite covers registry initialization, watch source creation, provider
example coverage, doctor checks, dry-run polling, safe dedupe template
expansion, apply-mode event writes, cursor state, trigger event/queue actions,
docs update repair, and negative doctor findings.

## Troubleshooting

If `connected-system doctor notion_genome` reports missing providers, inspect:

```text
shared_factory/00-control-plane/source-providers.yml
```

If `watch-source doctor <source_id>` reports a missing cursor or dedupe key,
inspect:

```text
shared_factory/00-control-plane/watch-sources.yml
```

If `watch-source run-due --apply` skips a source, confirm the source has:

```yaml
enabled: true
```

If dry-run works but apply does not write an event, verify the output directory
is available:

```text
shared_factory/06-runs-and-logs/source-events/
```

If Notion is the connected system, verify the active workspace before adding
provider-specific live reads or write paths. The intended workspace is Genome's
Notion.

## Source Artifacts

- Historical Spec: migrated into the installed project's canonical `work-items/` lifecycle.
- Installed worklog spec: `worklogs/source-features/16-connected-source-watch-registry/SPEC.md`
- Installed worklog QA: `worklogs/source-features/16-connected-source-watch-registry/HOLDOUT_QA.md`
- Installed worklog QA results: `worklogs/source-features/16-connected-source-watch-registry/HOLDOUT_QA_RESULTS.md`
- Command prompt: `harness/commands/os-watch-source.md`
- Skill: `harness/skills/source-watcher/SKILL.md`
- Runtime templates: `templates/runtime/connected-system.yml`, `templates/runtime/source-provider.yml`, `templates/runtime/watch-source.yml`, `templates/runtime/watch-cursor.yml`, `templates/runtime/source-event.yml`, `templates/runtime/trigger-rule.yml`
- Runtime implementation: `src/genomes_agentic_os/source_watch.py`
- CLI registration: `src/genomes_agentic_os/cli.py`
- Runtime validation: `src/genomes_agentic_os/validate.py`
- Test coverage: `tests/test_cli_scaffold.py`
