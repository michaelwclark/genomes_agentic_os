# SQLite State Plane (AGE-39)

Status: module, CLI surface, importers, and tests shipped 2026-07-13. Cutover of live
writers (`runtime_ops.py`'s run-queue read/write path, `event_graph.py`'s event-append
path) is explicitly **not** part of this change — see Non-Goals below.

## Why This Exists

The installed OS keeps mutable state in files that get rewritten wholesale on every tick.
Measured on the live instance the same night this shipped: `run-queue.yml` was
13.01MB / 261,184 lines / 10,850 items and growing at roughly 500 items/day, with
completed/failed items never pruned automatically — every schedule/heartbeat/watcher tick
anywhere in the OS parses and rewrites the entire file. The event ledger and cursor files
have the same shape of problem at smaller scale today (one YAML file per event; whole-file
cursor rewrites on every watcher poll).

`genomes_agentic_os.state` replaces that pattern with an indexed, WAL-mode SQLite database,
using only the Python standard library (`sqlite3` — no new dependency added to
`pyproject.toml`). It does not replace the files tonight; it gives the OS an importable,
queryable mirror of them and the CLI surface to operate that mirror, so a future change can
flip individual read/write paths over once shadow-parity is proven.

## Database Location Convention

```
<agentic-root>/harness/<domain>/00-control-plane/state.db
```

One SQLite file per domain, colocated with that domain's existing `00-control-plane/` YAML
files — the same convention `event_graph.py` and `source_watch.py` already use for their
own control-plane files. Default domain is `shared_factory`, since that is where all the
measured pain lives; `state.db.default_db_path(root, domain=...)` accepts an override for
future per-domain databases.

`<agentic-root>` is resolved by `state.db.resolve_os_root`, which reuses the codebase's
existing `.agentic_root` discovery (`find_os_root` in `conversation_logging.py`) rather than
a second implementation: an explicit `--root` is expanded as-is (matching every other CLI
command); when omitted, it falls back to the same cwd-walking discovery every other
best-effort caller in this codebase already uses.

Every `state` CLI subcommand also accepts an independent `--db` override, separate from
`--root`. This is deliberate, not incidental: `--root` names where *source* files live,
`--db` names where the *target* database lives, and they must never be forced to be the same
path. A dry-run import against a real installed OS must be able to report counts with zero
risk of ever creating a `state.db` there as a side effect of merely opening a connection —
see "Import Workflow" below.

## Table Reference

Schema is applied via `state.db.ensure_schema`, an idempotent, numbered migration list
(currently one migration, version 1) gated by a `schema_version` table
(`version INTEGER PRIMARY KEY, description TEXT, applied_at TEXT`). Every `CREATE TABLE`/
`CREATE INDEX` in a migration uses `IF NOT EXISTS`, so re-applying an already-applied
migration — or opening an already-current database — is a safe no-op.

Connection-level pragmas set on every `connect()`: `journal_mode=WAL`, `foreign_keys=ON`,
`busy_timeout` (default 5000ms, configurable). `:memory:` connections silently keep SQLite's
in-memory journal mode instead of WAL (SQLite doesn't support WAL for `:memory:`) — this is
expected, not an error, and is how dry-run counting can exercise the same code path with zero
disk writes (see below).

### `events` — append-only ledger

```sql
CREATE TABLE events (
    id TEXT PRIMARY KEY,               -- evt_<sha256[:12]> from the real ledger, or evt_<uuid[:12]>
    type TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    occurred_at TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    source_ref TEXT,
    correlation_id TEXT,
    idempotency_key TEXT,              -- indexed, NOT unique -- see note below
    summary TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    contains_secret INTEGER NOT NULL DEFAULT 0,
    contains_customer_data INTEGER NOT NULL DEFAULT 0,
    run_log_link TEXT,
    source_url TEXT,
    domain TEXT,
    created_at TEXT NOT NULL
);
-- indexes: (type, occurred_at), (correlation_id), (domain), (idempotency_key)
```

Column set and values are a direct, verified mapping from the real `evt_*.yml` envelope
(`event_graph.append_event`'s output — `source.ref`, `correlation.correlation_id`,
`privacy.contains_secret`/`contains_customer_data`, `links.run_log`/`source_url`,
`payload_ref` serialized whole into `payload_json`).

**Why `idempotency_key` is not `UNIQUE`, despite the audit's initial sketch suggesting it:**
`event_graph.append_event` derives it as `f"{event_type}:{sha256(source_ref)[:16]}"` — it
does not incorporate `observed_at`. Two distinct, legitimate events of the same type from the
same `source_ref` observed at different times share an idempotency_key but have different
`id`s. The natural per-row idempotency key — the one the real ledger already uses as its
filename, and the one the importer dedupes on — is `id`. Appending (`events.append`,
`events.batch_append`) is `INSERT OR IGNORE` keyed by `id`. There is deliberately no
update/delete API: the table is append-only by construction, matching the source ledger's own
write-once contract (`write_yaml_once` never overwrites an existing `evt_*.yml`).
`prune_events(older_than_days, dry_run)` is the one explicit, separately-named retention call
— never a generic delete.

### `run_queue` — the dispatch queue

```sql
CREATE TABLE run_queue (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,                -- e.g. "schedule" (100% of live items) or "event_chain"
    ref TEXT,
    status TEXT NOT NULL,              -- dry-run|queued|approval-needed|running|blocked|done|failed|skipped
    approval_state TEXT NOT NULL DEFAULT 'not_required',
    priority INTEGER NOT NULL DEFAULT 0,      -- new: no YAML equivalent, see below
    idempotency_key TEXT UNIQUE,       -- verified unique across all 10,921 live items
    execution_target TEXT,
    dry_run INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    due_at TEXT,
    started_at TEXT,
    finished_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,      -- new
    lease_owner TEXT,                          -- new
    lease_until TEXT,                          -- new
    blocked_reason TEXT,
    error TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}'   -- catch-all: command/log/dispatch_log/evidence/...
);
-- indexes: (status, due_at), (lease_until)
```

This is the dispatch queue, distinct from the `events` audit ledger and from any future
`runs` audit-log table (not built tonight — see Non-Goals).

The column set was grounded in the **real, live `run-queue.yml`** by structural inspection
(stream-parsed, never fully loaded into a conversation or catted — 10,921 items at the time
of inspection), not just the audit's sketch. The real per-item key union is: `approval_state,
blocked_reason, command, created_at, dispatch_log, dry_run, due_at, error, evidence,
execution_target, external_effect, finished_at, id, idempotency_key, kind, log, ref,
started_at, status, updated_at`. Fields that are meaningful across every item kind became
dedicated columns; fields specific to only some kinds (`command`, `log`, `dispatch_log`,
`evidence`, `external_effect`, and the event-chain-only fields `work_type`/`route_to`/
`workflow`/`context_profile`/`maturity`/`correlation_id`/`chain_depth`/`source_event_id`
defined in `event_graph.queue_item_for` but not yet present in live data since chain rules
are disabled) land in `payload_json`, mirroring the event ledger's own `payload_ref`
catch-all pattern. Status/approval_state are **not** SQL `CHECK`-constrained: the importer
must faithfully mirror whatever the file contains even if it drifts from the documented
vocabulary, and validation instead happens in `queue.enqueue`'s Python code for
application-created rows.

`priority`, `attempts`, `lease_owner`, `lease_until` do not exist in the YAML format at all.
They exist to back `queue.claim_next` — a lease-based claim per the FORGE outbox pattern
(`forge-notifications`' `claimNextPending`/`markSent`/`markFailed`): `BEGIN IMMEDIATE` makes
the candidate-select-then-update atomic, so two concurrent claimants cannot win the same row
(the second blocks up to `busy_timeout`, then re-evaluates and sees the row already leased).
Reclaiming an abandoned lease (a crashed worker) requires explicitly including the in-flight
status in `claim_next(statuses=...)` — see the function's docstring; a bare `claim_next()`
call never silently reclaims a "running" item. The importer's `INSERT ... ON CONFLICT(id) DO
UPDATE` deliberately never touches these four columns on re-import, since they have no
source-of-truth in the file and re-mirroring must not clobber SQLite-native claim state.

### `cursors` — named cursor KV store

```sql
CREATE TABLE cursors (
    name TEXT PRIMARY KEY,
    cursor_type TEXT,
    last_value TEXT,
    last_idempotency_key TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);
```

Covers both real cursor file formats generically. `watch-cursors.yml`
(`watch_cursors: [{id, watch_source_id, cursor_type, last_value, last_idempotency_key,
updated_at}, ...]`) maps one row per entry, `name = watch_source_id`. `event-cursors.yml`
(`processed_idempotency_keys: [...]`) has no natural per-row name — it's a single growing
dedupe set, not a list of named cursors — so it folds into exactly one fixed-name row
(`name="event_chain_dedupe"`, `cursor_type="idempotency_key_set"`, the whole key list in
`payload_json`), created whenever the source file exists, independent of whether the list is
currently empty (it is, on the live instance today — chain rules are all disabled). This is a
deliberate mapping choice, not an obvious 1:1 translation; flagged here for anyone extending
it. Unlike `events`, `set_cursor` is a true upsert — a cursor's entire purpose is being
overwritten as it advances.

### Control-plane facts and read models

Schema migration 4 adds two small durable fact tables for integration adapters:

- `approval_requests` records one wait state with the requesting actor, named
  approver, decision, expiry, and decision timestamp. A decision can only be
  written by the named approver before expiry; expiry is a separate explicit
  transition. Chat messages are never approval authority.
- `artifact_references` stores only a URI, SHA-256 content hash,
  classification, retention interval, and optional source reference. It has no
  artifact-body column or renderer payload.

`state.control_plane.control_plane_projection` derives an operator read model
from these rows. It can calculate that a still-persisted wait state has expired,
but it never writes that conclusion: `expire_approvals` is the explicit durable
transition. This preserves SQLite facts as the source of truth and keeps UI
projections disposable.

`state.control_plane.validate_change_linkage` is the shared pre-commit/CI
contract for code-changing integrations. It requires one canonical work item
with a Linear `TEAM-123` source key, registered worktree path, and branch; it
does not invent an alternate tracker or worktree registry.

Use `scripts/check-change-linkage.py --db <canonical-state.db> --work-item
<id>` from a CI job or harness hook. The guard opens the existing database
read-only, emits a normalized receipt, and fails when any link is absent. It is
not installed into the repository's shared Git hook path, which intentionally
contains only commit-message validation for multi-worktree safety.

## Import Workflow

`state/importers.py` has two deliberately separate function families:

- **`scan_*`** (`scan_run_queue`, `scan_events`, `scan_cursors`, `scan_all`) — pure source
  reads. Parse YAML, count, return. They import nothing from `.db`/`.events`/`.queue`/
  `.cursors` and never accept or open a connection — structurally, not just by convention,
  they cannot create a database file. This is what `state import --dry-run` calls.
- **`import_*`** (`import_run_queue`, `import_events`, `import_cursors`, `import_all`) — take
  an already-open connection, provided by the caller, and write. This module never opens or
  resolves a connection itself, and never calls `event_graph`'s writer functions
  (`ensure_event_state`/`append_event`/`write_yaml`) — only its pure `load_yaml` reader.
  Source files are never mutated.

The CLI wires this so `state import --dry-run` takes the `scan_*` path unconditionally —
regardless of what `--db` would otherwise resolve to, no connection is ever attempted.
`state import` without `--dry-run` connects to `--db` (or the path `default_db_path(--root)`
resolves to) and takes the `import_*` path.

```
agentic-os state import --root ~/agentic_os --source all --dry-run   # counts only, no db touched
agentic-os state import --root ~/agentic_os --db ~/agentic_os/harness/shared_factory/00-control-plane/state.db --source all
agentic-os state verify-import --root ~/agentic_os                    # file counts vs table counts, drift report
agentic-os state status --db <path>
agentic-os state query --db <path> --table run_queue --status queued --json
agentic-os state prune --db <path> --older-than-days 30                # dry run by default
agentic-os state prune --db <path> --older-than-days 30 --apply        # actually deletes
```

Re-running any import is idempotent (verified by tests: importing the same fixture tree
twice produces identical table counts): `run_queue` upserts by `id` (refreshes the
YAML-mirrored columns, leaves `priority`/`attempts`/`lease_owner`/`lease_until` alone);
`events` is insert-or-ignore by `id`; `cursors` upserts by `name`.

## Cutover Plan

The audit that preceded this change (`audit-forge-sqlite.md`) recommended sequencing the
cutover of *live writers* — not tonight's scaffolding, which ships all three tables and
importers together — by risk, separately from pain:

1. **Milestone 1 — events ledger dual-write (AGE-53).** `event_graph.append_event` writes
   the YAML file (ground truth, unchanged) and, only when
   `event-graph.yml` enables `event_graph.state_ledger.dual_write: true`, appends its
   normalized projection to `events` through `state.events.append`. Reads remain file-backed:
   establish parity with `state verify-import` for one cycle before any read-path cutover of
   `list_events` or `summarize_events`. This proves the migration tooling, backup story, and
   WAL behavior without changing consumers.
2. **Milestone 2 — run_queue backend flip.** Once Milestone 1's pattern is proven,
   `runtime_ops.py`'s queue read/write path (`_write_queue`, `_queue`,
   `_append_queue_item_to_queue`, and the scheduler's "what's due" scan) moves from
   whole-file YAML rewrite to indexed `run_queue` reads and `UPDATE ... WHERE id=` writes.
   This is where the actual payoff is: a 13MB rewrite becomes an O(1) update. Highest
   measured pain, but not the first cut, precisely because `runtime_ops.py` (2,773 lines, 83
   functions) is load-bearing for every heartbeat/schedule/watcher tick in the OS — a cutover
   bug there breaks the OS's aliveness, not just one feature.

## Retention Policy

- `run_queue.prune(older_than_days, statuses=("done","failed","skipped"), dry_run=True)` —
  replaces the currently-manual `run-queue-prune` step described in the audit. Dry run by
  default at both the function layer and the CLI layer (`state prune` requires `--apply` to
  actually delete).
- `events.prune_events(older_than_days, dry_run=True)` — the one explicit retention call for
  the append-only ledger, separate from any generic delete API (there isn't one).
- `cursors` has no time-based retention (a cursor row's whole purpose is to reflect current
  position; there is no "old cursor" concept). `delete_cursor(name)` exists for explicit
  removal of a retired source.

## Non-Goals Tonight

- **No read-path or queue-writer cutover.** `runtime_ops.py`, `source_watch.py`, and all
  `event_graph.py` readers still use YAML files exactly as before. AGE-53 adds only the
  config-gated SQLite shadow append for events; it does not make the database authoritative.
- **No `runs` (audit-log), `work_items`, `watcher_state`, or `intake_cursors` tables.** The
  audit sketched these for a *future* milestone; tonight's scope is exactly the three stores
  named in the AGE-39 task (events, run_queue, cursors), matching what's actually
  measured-painful today.
- **No CLI wiring into `cli.py`.** Another concurrent effort is splitting `cli.py` into a
  `cli/` package; this change never imports from or modifies `cli.py`, `cli_help.py`, any
  `cli/` package file, or `pyproject.toml`. Integration is exactly one import and one call:

  ```python
  from genomes_agentic_os.state import register_state_cli
  register_state_cli(subparsers)  # subparsers = parser.add_subparsers(dest="command", required=True)
  ```
- **No new dependency.** `sqlite3` is standard library; `pyproject.toml` is unchanged.
- **No status/approval_state `CHECK` constraints on `run_queue`.** Deliberate: the importer
  must be able to faithfully mirror a file that has drifted from the documented vocabulary
  without the whole import failing. `queue.py`'s application-facing API (`enqueue`,
  `update_status`, `complete`) validates against `VALID_STATUSES`/`VALID_APPROVAL_STATES` in
  Python instead.
