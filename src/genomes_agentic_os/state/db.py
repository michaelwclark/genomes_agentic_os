"""SQLite connection management for the Agentic OS state plane.

Owns pragma setup (WAL, foreign_keys, busy_timeout), the numbered-migration
``schema_version`` mechanism, and database path resolution. Every other
``state/`` module receives an already-open ``sqlite3.Connection`` from its
caller rather than opening its own — this module is the single place that
knows how to create one.

Path resolution reuses the codebase's existing ``.agentic_root`` discovery
(``find_os_root`` in ``conversation_logging.py``) rather than a second
implementation, per AGE-39 scope.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any, Iterator, Sequence

from ..conversation_logging import find_os_root
from ..scaffold import SHARED_FACTORY_DOMAIN, expand_path, harness_path

MEMORY_DB_PATH = ":memory:"

# Relative to a domain root (e.g. "<agentic-root>/harness/shared_factory"),
# mirroring the existing "<domain>/00-control-plane/<file>.yml" convention.
STATE_DB_RELATIVE = Path("00-control-plane") / "state.db"
STATE_BACKUP_RELATIVE = Path("06-runs-and-logs") / "state-backups"
DEFAULT_STATE_BACKUP_RETENTION = 7
DEFAULT_STATE_BACKUP_INTERVAL_HOURS = 24

SCHEMA_TABLES: tuple[str, ...] = (
    "events",
    "run_queue",
    "cursors",
    "work_items",
    "work_item_history",
)


class StateDbError(RuntimeError):
    """Raised for state-plane connection/schema problems."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def days_ago_iso(days: int, *, now: str | None = None) -> str:
    base = parse_iso(now) if now else datetime.now(timezone.utc)
    return (base - timedelta(days=days)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def resolve_os_root(root: str | Path | None = None) -> Path:
    """Resolve the installed Agentic OS root.

    An explicit ``root`` is expanded and returned as-is (matches every other
    CLI command's ``--root`` handling). When ``root`` is omitted, falls back
    to the existing cwd-walking ``.agentic_root`` discovery.
    """
    if root is not None:
        return expand_path(root)
    discovered = find_os_root(Path.cwd())
    if discovered is None:
        raise StateDbError(
            "Could not discover the Agentic OS root from the current directory. "
            "Pass --root explicitly or set AGENTIC_OS_ROOT."
        )
    return discovered


def default_db_path(root: str | Path | None = None, *, domain: str = SHARED_FACTORY_DOMAIN) -> Path:
    """Default state.db location: ``<root>/harness/<domain>/00-control-plane/state.db``.

    Colocated with that domain's existing ``00-control-plane/`` YAML files,
    mirroring the per-domain convention already used throughout the OS.
    """
    return harness_path(resolve_os_root(root), domain, *STATE_DB_RELATIVE.parts)


def connect(db_path: str | Path = MEMORY_DB_PATH, *, busy_timeout_ms: int = 5000) -> sqlite3.Connection:
    """Open a state-plane connection: pragmas set, schema migrated, ready to use.

    ``db_path`` may be a filesystem path or the literal ``":memory:"`` for an
    ephemeral, disk-free database (used by dry-run/count-only callers that
    must never create a file). Every call ensures the schema is current —
    the migrations are idempotent, so opening an already-current database is
    a cheap no-op.
    """
    path_str = str(db_path)
    is_memory = path_str in (MEMORY_DB_PATH, "")
    if not is_memory:
        resolved = expand_path(db_path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        path_str = str(resolved)
    conn = sqlite3.connect(path_str, isolation_level=None, timeout=busy_timeout_ms / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # silently stays "memory" for :memory: connections
    # The state plane is low throughput and authoritative. Prefer waiting for
    # the WAL frame to reach durable storage over NORMAL's smaller latency.
    conn.execute("PRAGMA synchronous = FULL")
    ensure_schema(conn)
    return conn


def state_backup_dir(root: str | Path | None = None, *, domain: str = SHARED_FACTORY_DOMAIN) -> Path:
    return harness_path(resolve_os_root(root), domain, *STATE_BACKUP_RELATIVE.parts)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def backup_database(
    db_path: str | Path,
    backup_dir: str | Path,
    *,
    retention: int = DEFAULT_STATE_BACKUP_RETENTION,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Publish one consistent, integrity-checked SQLite snapshot and receipt."""
    if retention < 1:
        raise StateDbError("state backup retention must be at least 1")
    source_path = expand_path(db_path)
    if not source_path.is_file():
        raise StateDbError(f"state database is missing: {source_path}")
    destination_dir = expand_path(backup_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    captured = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    stamp = captured.strftime("%Y%m%dT%H%M%SZ")
    target = destination_dir / f"state-{stamp}.db"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=destination_dir)
    os.close(descriptor)
    temporary = Path(temporary_name)
    source: sqlite3.Connection | None = None
    destination: sqlite3.Connection | None = None
    try:
        source = sqlite3.connect(str(source_path), isolation_level=None, timeout=5)
        source.execute("PRAGMA busy_timeout = 5000")
        destination = sqlite3.connect(str(temporary), isolation_level=None, timeout=5)
        source.backup(destination)
        integrity = str(destination.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise StateDbError(f"state backup integrity check failed: {integrity}")
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()
    try:
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    snapshots = sorted(destination_dir.glob("state-*.db"), key=lambda path: (path.stat().st_mtime, path.name))
    pruned: list[str] = []
    for stale in snapshots[:-retention]:
        stale.unlink()
        pruned.append(str(stale))
        stale.with_suffix(".json").unlink(missing_ok=True)
    receipt = {
        "schema_version": "agentic-os-state-backup/v1",
        "status": "completed",
        "captured_at": captured.isoformat().replace("+00:00", "Z"),
        "source": str(source_path),
        "snapshot": str(target),
        "integrity_check": "ok",
        "retention": retention,
        "pruned": pruned,
    }
    receipt_path = destination_dir / f"state-{stamp}.json"
    _write_json_atomic(receipt_path, receipt)
    _write_json_atomic(destination_dir / "latest.json", {**receipt, "receipt": str(receipt_path)})
    return {**receipt, "receipt": str(receipt_path)}


def backup_state_database(
    root: str | Path | None = None,
    *,
    domain: str = SHARED_FACTORY_DOMAIN,
    retention: int = DEFAULT_STATE_BACKUP_RETENTION,
    if_due_hours: int | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Back up the authoritative state database, optionally only when due."""
    os_root = resolve_os_root(root)
    db_path = default_db_path(os_root, domain=domain)
    destination = state_backup_dir(os_root, domain=domain)
    captured = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not db_path.is_file():
        return {
            "status": "not_initialized",
            "dry_run": dry_run,
            "db_path": str(db_path),
            "message": "state database does not exist yet; no snapshot is required",
        }
    latest = max(destination.glob("state-*.db"), key=lambda path: path.stat().st_mtime, default=None)
    if if_due_hours is not None and latest is not None:
        age_seconds = max(0.0, captured.timestamp() - latest.stat().st_mtime)
        if age_seconds < max(1, if_due_hours) * 3600:
            return {
                "status": "not_due",
                "dry_run": dry_run,
                "db_path": str(db_path),
                "latest_snapshot": str(latest),
                "age_seconds": round(age_seconds, 3),
            }
    if dry_run:
        return {
            "status": "would_backup",
            "dry_run": True,
            "db_path": str(db_path),
            "backup_dir": str(destination),
            "retention": retention,
        }
    return {
        **backup_database(db_path, destination, retention=retention, now=captured),
        "dry_run": False,
        "db_path": str(db_path),
    }


_SCHEMA_VERSION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TEXT NOT NULL
)
"""

# Numbered, idempotent migrations. Each entry is (version, description, sql).
# Migrations run under BEGIN IMMEDIATE and re-read schema_version after taking
# the write lock, so concurrent process startup cannot apply the same ALTER
# twice. CREATE statements also use IF NOT EXISTS for repair-friendly replay.
_MIGRATIONS: tuple[tuple[int, str, str], ...] = (
    (
        1,
        "events, run_queue, and cursors tables",
        """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    occurred_at TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    source_ref TEXT,
    correlation_id TEXT,
    idempotency_key TEXT,
    summary TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    contains_secret INTEGER NOT NULL DEFAULT 0,
    contains_customer_data INTEGER NOT NULL DEFAULT 0,
    run_log_link TEXT,
    source_url TEXT,
    domain TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_type_occurred_at ON events(type, occurred_at);
CREATE INDEX IF NOT EXISTS idx_events_correlation_id ON events(correlation_id);
CREATE INDEX IF NOT EXISTS idx_events_domain ON events(domain);
CREATE INDEX IF NOT EXISTS idx_events_idempotency_key ON events(idempotency_key);

CREATE TABLE IF NOT EXISTS run_queue (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    ref TEXT,
    status TEXT NOT NULL,
    approval_state TEXT NOT NULL DEFAULT 'not_required',
    priority INTEGER NOT NULL DEFAULT 0,
    idempotency_key TEXT UNIQUE,
    execution_target TEXT,
    dry_run INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    due_at TEXT,
    started_at TEXT,
    finished_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT,
    lease_until TEXT,
    blocked_reason TEXT,
    error TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_run_queue_status_due_at ON run_queue(status, due_at);
CREATE INDEX IF NOT EXISTS idx_run_queue_lease_until ON run_queue(lease_until);

CREATE TABLE IF NOT EXISTS cursors (
    name TEXT PRIMARY KEY,
    cursor_type TEXT,
    last_value TEXT,
    last_idempotency_key TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);
""",
    ),
    (
        2,
        "canonical work-item state and attention tracking",
        """
CREATE TABLE IF NOT EXISTS work_items (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    state TEXT NOT NULL CHECK (
        state IN (
            'captured', 'triaged', 'specified', 'ready', 'building',
            'validating', 'blocked', 'finished', 'documented', 'archived'
        )
    ),
    attention TEXT NOT NULL DEFAULT 'queued' CHECK (
        attention IN ('active', 'queued', 'parked', 'closed')
    ),
    domain TEXT,
    project TEXT,
    source_system TEXT,
    source_key TEXT,
    source_url TEXT,
    owner TEXT,
    priority INTEGER NOT NULL DEFAULT 0,
    packet_path TEXT,
    worktree_path TEXT,
    branch TEXT,
    context_summary TEXT NOT NULL DEFAULT '',
    blocked_reason TEXT,
    previous_state TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_verified_at TEXT,
    closed_at TEXT,
    UNIQUE(source_system, source_key)
);
CREATE INDEX IF NOT EXISTS idx_work_items_attention_state
    ON work_items(attention, state, priority DESC, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_work_items_domain_project
    ON work_items(domain, project, attention, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_work_items_source
    ON work_items(source_system, source_key);

CREATE TABLE IF NOT EXISTS work_item_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_item_id TEXT NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
    changed_at TEXT NOT NULL,
    actor TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    from_attention TEXT,
    to_attention TEXT NOT NULL,
    summary TEXT,
    receipt_ref TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_work_item_history_item_changed
    ON work_item_history(work_item_id, changed_at DESC);

CREATE VIEW IF NOT EXISTS active_now AS
SELECT *
FROM work_items
WHERE attention = 'active'
  AND state NOT IN ('finished', 'documented', 'archived');
""",
    ),
    (
        3,
        "execution-fabric named queues and worker pools",
        """
ALTER TABLE run_queue ADD COLUMN queue_name TEXT NOT NULL DEFAULT 'default';
ALTER TABLE run_queue ADD COLUMN worker_pool TEXT NOT NULL DEFAULT 'default';
ALTER TABLE run_queue ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 3;
ALTER TABLE run_queue ADD COLUMN dead_letter_queue TEXT;
ALTER TABLE run_queue ADD COLUMN lease_token TEXT;
CREATE INDEX IF NOT EXISTS idx_run_queue_named_claim
    ON run_queue(queue_name, worker_pool, status, priority, due_at);

CREATE TABLE IF NOT EXISTS execution_queues (
    name TEXT PRIMARY KEY,
    max_concurrency INTEGER NOT NULL CHECK(max_concurrency > 0),
    enabled INTEGER NOT NULL DEFAULT 1,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS worker_pools (
    name TEXT PRIMARY KEY,
    queue_name TEXT NOT NULL REFERENCES execution_queues(name),
    max_workers INTEGER NOT NULL CHECK(max_workers > 0),
    max_concurrency INTEGER NOT NULL CHECK(max_concurrency > 0),
    provider TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_worker_pools_queue_name ON worker_pools(queue_name);

CREATE TABLE IF NOT EXISTS execution_limits (
    scope TEXT NOT NULL CHECK(scope IN ('global', 'provider')),
    key TEXT NOT NULL,
    max_concurrency INTEGER NOT NULL CHECK(max_concurrency > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(scope, key)
);

CREATE TABLE IF NOT EXISTS execution_workers (
    id TEXT PRIMARY KEY,
    pool_name TEXT NOT NULL REFERENCES worker_pools(name),
    status TEXT NOT NULL DEFAULT 'online',
    capacity INTEGER NOT NULL DEFAULT 1 CHECK(capacity > 0),
    active_tasks INTEGER NOT NULL DEFAULT 0 CHECK(active_tasks >= 0),
    heartbeat_at TEXT NOT NULL,
    lease_until TEXT NOT NULL,
    lease_token TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_execution_workers_pool_status
    ON execution_workers(pool_name, status, lease_until);
""",
    ),
)


def ensure_schema(conn: sqlite3.Connection) -> int:
    """Create/upgrade the schema to the latest known version. Returns the resulting version."""
    conn.execute(_SCHEMA_VERSION_TABLE_SQL)
    latest = _MIGRATIONS[-1][0] if _MIGRATIONS else 0
    current = schema_version(conn)
    if current >= latest:
        return current
    for version, description, sql in _MIGRATIONS:
        with transaction(conn):
            current = schema_version(conn)
            if version <= current:
                continue
            for statement in sql.split(";"):
                statement = statement.strip()
                if statement:
                    conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_version (version, description, applied_at) VALUES (?, ?, ?)",
                (version, description, utc_now_iso()),
            )
    return schema_version(conn)


def schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()
    return int(row[0]) if row else 0


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Atomic write section. Uses BEGIN IMMEDIATE so a concurrent claimant
    blocks (up to busy_timeout) rather than racing the same row.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def table_counts(conn: sqlite3.Connection, tables: Sequence[str] = SCHEMA_TABLES) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in tables:
        if table not in SCHEMA_TABLES:
            raise StateDbError(f"unknown state table: {table}")
        counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return counts
