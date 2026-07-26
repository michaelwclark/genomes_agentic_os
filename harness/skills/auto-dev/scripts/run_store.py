#!/usr/bin/env python3
"""SQLite RunStore for Auto Dev v2 — Phase 1 claim guard + queryable run index.

Files (`state.json`, `step-ledger.jsonl`) stay authoritative in Phase 1; this
store owns the atomic cross-host claim lease and the in-flight index. See
`domains/los/00-programs/auto_dev_queue/design/auto-dev-v2-sqlite-migration-addendum.md`.
"""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
DEFAULT_DB_PATH = ROOT / "harness" / "state" / "agentic_os.db"
DB_ENV_VAR = "AUTO_DEV_DB"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
  run_id            TEXT PRIMARY KEY,
  work_item_id      TEXT NOT NULL UNIQUE,
  project           TEXT NOT NULL,
  domain            TEXT,
  tracker_kind      TEXT,
  tracker_id        TEXT,
  current_state     TEXT NOT NULL,
  terminal          INTEGER NOT NULL DEFAULT 0,
  lease_owner       TEXT,
  lease_host        TEXT,
  lease_pid         INTEGER,
  lease_expires_at  TEXT,
  work_item_path    TEXT NOT NULL,
  pr_url            TEXT,
  blocker           TEXT,
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS step_events (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id          TEXT NOT NULL REFERENCES runs(run_id),
  seq             INTEGER NOT NULL,
  from_state      TEXT,
  to_state        TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  ts              TEXT NOT NULL,
  receipt         TEXT,
  UNIQUE(run_id, idempotency_key)
);
"""

CLAIM_SQL = """
INSERT INTO runs (
  work_item_id, run_id, project, domain, tracker_kind, tracker_id,
  current_state, terminal, lease_owner, lease_host, lease_pid,
  lease_expires_at, work_item_path, created_at, updated_at
) VALUES (
  :work_item_id, :run_id, :project, :domain, :tracker_kind, :tracker_id,
  :current_state, 0, :owner, :host, :pid, :expires_at, :work_item_path, :now, :now
)
ON CONFLICT(work_item_id) DO UPDATE SET
  lease_owner      = excluded.lease_owner,
  lease_host       = excluded.lease_host,
  lease_pid        = excluded.lease_pid,
  lease_expires_at = excluded.lease_expires_at,
  run_id           = excluded.run_id,
  updated_at       = excluded.updated_at
WHERE runs.lease_expires_at IS NULL OR runs.lease_expires_at < :now
"""

RUN_COLUMNS = (
    "run_id",
    "work_item_id",
    "project",
    "domain",
    "tracker_kind",
    "tracker_id",
    "current_state",
    "terminal",
    "lease_owner",
    "lease_host",
    "lease_pid",
    "lease_expires_at",
    "work_item_path",
    "pr_url",
    "blocker",
    "created_at",
    "updated_at",
)

UPSERT_REF_COLUMNS = ("project", "domain", "tracker_kind", "tracker_id", "work_item_path", "pr_url", "blocker")


@dataclass(frozen=True)
class RunRow:
    run_id: str
    work_item_id: str
    project: str
    domain: str | None
    tracker_kind: str | None
    tracker_id: str | None
    current_state: str
    terminal: bool
    lease_owner: str | None
    lease_host: str | None
    lease_pid: int | None
    lease_expires_at: str | None
    work_item_path: str
    pr_url: str | None
    blocker: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ClaimResult:
    granted: bool
    reason: str | None
    row: RunRow | None


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def lease_expiry(now: str, lease_seconds: int) -> str:
    base = dt.datetime.fromisoformat(now.replace("Z", "+00:00"))
    expiry = base + dt.timedelta(seconds=lease_seconds)
    return expiry.isoformat().replace("+00:00", "Z")


def resolve_db_path() -> Path:
    override = os.environ.get(DB_ENV_VAR)
    return Path(override).expanduser() if override else DEFAULT_DB_PATH


def row_to_run(row: sqlite3.Row) -> RunRow:
    values = {column: row[column] for column in RUN_COLUMNS}
    values["terminal"] = bool(values["terminal"])
    return RunRow(**values)


class SqliteRunStore:
    """Phase 1 RunStore: DB claim lease + dual-write index over file-authoritative runs."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._bootstrapped = False

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        # busy_timeout must be set BEFORE journal_mode so ordinary lock waits
        # inside the conversion retry below block instead of throwing.
        conn.execute("PRAGMA busy_timeout=5000").close()
        # WAL persists in the db file, so this is a no-op on an already-WAL db.
        # The initial delete->WAL conversion needs an exclusive lock, and SQLite
        # returns SQLITE_BUSY on that path WITHOUT consulting the busy handler
        # when concurrent first connections race it — so tolerate the race with
        # a short bounded retry (the loser re-runs the pragma as a no-op).
        for attempt in range(20):
            try:
                conn.execute("PRAGMA journal_mode=WAL").close()
                break
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc) or attempt == 19:
                    raise
                time.sleep(0.025)
        # foreign_keys stays at SQLite's default (off): a new run claiming a
        # previously-run work item rewrites runs.run_id, and prior step_events
        # rows must survive as history rather than block the lease takeover.
        if not self._bootstrapped:
            conn.executescript(SCHEMA_SQL)
            self._bootstrapped = True
        return conn

    def claim(
        self,
        work_item_id: str,
        run_id: str,
        owner: str,
        host: str,
        pid: int,
        lease_seconds: int,
        *,
        project: str = "unknown",
        work_item_path: str = "",
        domain: str | None = None,
        tracker_kind: str | None = None,
        tracker_id: str | None = None,
        current_state: str = "claimed",
    ) -> ClaimResult:
        now = utc_now()
        params = {
            "work_item_id": work_item_id,
            "run_id": run_id,
            "project": project,
            "domain": domain,
            "tracker_kind": tracker_kind,
            "tracker_id": tracker_id,
            "current_state": current_state,
            "owner": owner,
            "host": host,
            "pid": pid,
            "expires_at": lease_expiry(now, lease_seconds),
            "work_item_path": work_item_path,
            "now": now,
        }
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(CLAIM_SQL, params)
            except sqlite3.IntegrityError as exc:
                # CLAIM_SQL's ON CONFLICT only targets work_item_id; a different
                # work item already holding this run_id trips the primary key
                # instead. Surface it as a blocked claim, not a traceback.
                if "runs.run_id" not in str(exc):
                    raise
                held = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
                conn.execute("ROLLBACK")
                return ClaimResult(granted=False, reason="duplicate_run_id", row=row_to_run(held) if held else None)
            raw = conn.execute("SELECT * FROM runs WHERE work_item_id = ?", (work_item_id,)).fetchone()
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
        row = row_to_run(raw)
        if row.run_id == run_id and row.lease_owner == owner:
            return ClaimResult(granted=True, reason=None, row=row)
        return ClaimResult(granted=False, reason="held_by_other", row=row)

    def renew(self, run_id: str, lease_seconds: int) -> bool:
        now = utc_now()
        conn = self._connect()
        try:
            cursor = conn.execute(
                "UPDATE runs SET lease_expires_at = ?, updated_at = ? WHERE run_id = ? AND lease_owner IS NOT NULL",
                (lease_expiry(now, lease_seconds), now, run_id),
            )
            return cursor.rowcount == 1
        finally:
            conn.close()

    def release(self, run_id: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE runs SET lease_owner = NULL, lease_host = NULL, lease_pid = NULL,"
                " lease_expires_at = NULL, updated_at = ? WHERE run_id = ?",
                (utc_now(), run_id),
            )
        finally:
            conn.close()

    def get(self, work_item_id: str) -> RunRow | None:
        conn = self._connect()
        try:
            raw = conn.execute("SELECT * FROM runs WHERE work_item_id = ?", (work_item_id,)).fetchone()
        finally:
            conn.close()
        return row_to_run(raw) if raw else None

    def upsert_state(self, run_id: str, current_state: str, terminal: bool, updated_at: str, refs: dict[str, Any]) -> None:
        extra = {column: refs[column] for column in UPSERT_REF_COLUMNS if column in refs}
        assignments = "current_state = :current_state, terminal = :terminal, updated_at = :updated_at"
        assignments += "".join(f", {column} = :{column}" for column in extra)
        params: dict[str, Any] = {
            "run_id": run_id,
            "current_state": current_state,
            "terminal": int(terminal),
            "updated_at": updated_at,
            **extra,
        }
        conn = self._connect()
        try:
            cursor = conn.execute(f"UPDATE runs SET {assignments} WHERE run_id = :run_id", params)
            if cursor.rowcount == 0 and refs.get("work_item_id"):
                conn.execute(
                    "INSERT OR IGNORE INTO runs (run_id, work_item_id, project, domain, tracker_kind,"
                    " tracker_id, current_state, terminal, work_item_path, pr_url, blocker, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        str(refs["work_item_id"]),
                        str(refs.get("project") or "unknown"),
                        refs.get("domain"),
                        refs.get("tracker_kind"),
                        refs.get("tracker_id"),
                        current_state,
                        int(terminal),
                        str(refs.get("work_item_path") or ""),
                        refs.get("pr_url"),
                        refs.get("blocker"),
                        updated_at,
                        updated_at,
                    ),
                )
        finally:
            conn.close()

    def record_step(
        self,
        run_id: str,
        seq: int,
        from_state: str,
        to_state: str,
        idempotency_key: str,
        ts: str,
        receipt: str | None,
    ) -> bool:
        conn = self._connect()
        try:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO step_events (run_id, seq, from_state, to_state, idempotency_key, ts, receipt)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, seq, from_state, to_state, idempotency_key, ts, receipt),
            )
            return cursor.rowcount == 1
        finally:
            conn.close()

    def list_in_flight(self, project: str | None = None) -> list[RunRow]:
        query = "SELECT * FROM runs WHERE terminal = 0"
        params: tuple[Any, ...] = ()
        if project:
            query += " AND project = ?"
            params = (project,)
        query += " ORDER BY updated_at"
        conn = self._connect()
        try:
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()
        return [row_to_run(raw) for raw in rows]


def create_run_store(db_path: Path | None = None) -> SqliteRunStore:
    return SqliteRunStore(db_path or resolve_db_path())
