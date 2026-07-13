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
from pathlib import Path
import sqlite3
from typing import Any, Iterator, Sequence

from ..conversation_logging import find_os_root
from ..scaffold import SHARED_FACTORY_DOMAIN, expand_path, harness_path

MEMORY_DB_PATH = ":memory:"

# Relative to a domain root (e.g. "<agentic-root>/harness/shared_factory"),
# mirroring the existing "<domain>/00-control-plane/<file>.yml" convention.
STATE_DB_RELATIVE = Path("00-control-plane") / "state.db"

SCHEMA_TABLES: tuple[str, ...] = ("events", "run_queue", "cursors")


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
    ensure_schema(conn)
    return conn


_SCHEMA_VERSION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TEXT NOT NULL
)
"""

# Numbered, idempotent migrations. Each entry is (version, description, sql).
# Every DDL statement uses IF NOT EXISTS so re-applying an already-applied
# migration (or racing another process) is a safe no-op; the schema_version
# row is still the authoritative "have I run this" gate.
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
)


def ensure_schema(conn: sqlite3.Connection) -> int:
    """Create/upgrade the schema to the latest known version. Returns the resulting version."""
    conn.execute(_SCHEMA_VERSION_TABLE_SQL)
    current = schema_version(conn)
    for version, description, sql in _MIGRATIONS:
        if version <= current:
            continue
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_version (version, description, applied_at) VALUES (?, ?, ?)",
            (version, description, utc_now_iso()),
        )
        current = version
    return current


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
