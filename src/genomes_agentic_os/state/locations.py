"""Canonical control-plane location and guarded legacy-store migration.

AGE-85 deliberately separates *routing* from *cleanup*.  All four historical
SQLite locations resolve to the shared control-plane path for new callers, but
existing files remain untouched until an explicit, read-back-verified copy is
requested.  This module never removes a legacy file.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import sqlite3
from typing import Any

from .db import connect, default_db_path, transaction

LEGACY_STORE_RELATIVE_PATHS: tuple[Path, ...] = (
    Path("runtime/state/state.db"),
    Path("harness/shared_factory/00-control-plane/state.db"),
    Path("harness/shared_factory/06-runs-and-logs/state.db"),
    Path("harness/state/agentic_os.db"),
)


@dataclass(frozen=True)
class ControlPlaneLocations:
    root: Path
    canonical: Path
    routes: dict[Path, Path]

    @classmethod
    def for_root(cls, root: str | Path) -> "ControlPlaneLocations":
        resolved = Path(root).expanduser().resolve()
        canonical = default_db_path(resolved)
        routes = {resolved / relative: canonical for relative in LEGACY_STORE_RELATIVE_PATHS}
        return cls(resolved, canonical, routes)

    def route(self, path: str | Path) -> Path:
        """Return the canonical destination for a known path, else the path."""
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.root / candidate
        return self.routes.get(candidate.resolve(), candidate.resolve())

    def existing_legacy(self) -> tuple[Path, ...]:
        return tuple(path for path in self.routes if path != self.canonical and path.is_file())

    def plan(self) -> dict[str, Any]:
        return {
            "canonical": str(self.canonical),
            "routes": {str(source): str(destination) for source, destination in self.routes.items()},
            "existing_legacy": [str(path) for path in self.existing_legacy()],
            "cleanup": "not_permitted",
            "source_of_truth": "canonical_control_plane",
        }


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def migrate_legacy_store(
    source: str | Path,
    destination: str | Path,
    *,
    apply: bool = False,
    cleanup: bool = False,
) -> dict[str, Any]:
    """Copy compatible tables without deleting or altering the source.

    The operation is opt-in and additive: only columns shared by source and
    destination tables are copied with ``INSERT OR IGNORE``.  ``cleanup`` is
    intentionally rejected; deletion requires a separately reviewed rollout.
    """
    if cleanup:
        raise ValueError("legacy cleanup is not supported by AGE-85 migration")
    source_path = Path(source).expanduser().resolve()
    destination_path = Path(destination).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    before_digest = _digest(source_path)
    with sqlite3.connect(f"file:{source_path}?mode=ro", uri=True) as source_conn:
        source_conn.row_factory = sqlite3.Row
        source_tables = {
            row[0]
            for row in source_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if row[0] != "sqlite_sequence"
        }
        source_counts = {table: int(source_conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]) for table in source_tables}
        copied: dict[str, int] = {}
        if apply:
            with connect(destination_path) as destination_conn:
                destination_tables = {
                    row[0]
                    for row in destination_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    if row[0] != "schema_version"
                }
                for table in sorted(source_tables & destination_tables):
                    source_columns = [row[1] for row in source_conn.execute(f'PRAGMA table_info("{table}")')]
                    destination_columns = {row[1] for row in destination_conn.execute(f'PRAGMA table_info("{table}")')}
                    columns = [column for column in source_columns if column in destination_columns]
                    if not columns:
                        continue
                    quoted = ", ".join(f'"{column}"' for column in columns)
                    rows = source_conn.execute(f'SELECT {quoted} FROM "{table}"').fetchall()
                    with transaction(destination_conn):
                        destination_conn.executemany(
                            f'INSERT OR IGNORE INTO "{table}" ({quoted}) VALUES ({", ".join("?" for _ in columns)})',
                            [tuple(row[column] for column in columns) for row in rows],
                        )
                    copied[table] = len(rows)
    after_digest = _digest(source_path)
    return {
        "source": str(source_path),
        "destination": str(destination_path),
        "applied": apply,
        "copied": copied,
        "source_counts": source_counts,
        "source_unchanged": before_digest == after_digest,
        "cleanup": "not_performed",
    }

