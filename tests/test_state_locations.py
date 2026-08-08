from pathlib import Path
import sqlite3

import pytest

from genomes_agentic_os.state.db import connect
from genomes_agentic_os.state.locations import (
    LEGACY_STORE_RELATIVE_PATHS,
    ControlPlaneLocations,
    migrate_legacy_store,
)


def test_all_four_locations_route_to_one_canonical_store(tmp_path: Path) -> None:
    locations = ControlPlaneLocations.for_root(tmp_path)
    assert len(locations.routes) == 4
    assert {locations.route(path) for path in LEGACY_STORE_RELATIVE_PATHS} == {locations.canonical}
    assert locations.plan()["cleanup"] == "not_permitted"


def test_migration_is_dry_run_by_default_and_preserves_source(tmp_path: Path) -> None:
    source = tmp_path / "runtime/state/state.db"
    source.parent.mkdir(parents=True)
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE events (id TEXT PRIMARY KEY, payload TEXT)")
        conn.execute("INSERT INTO events VALUES ('evt-1', '{}')")
    destination = tmp_path / "harness/shared_factory/00-control-plane/state.db"
    dry_run = migrate_legacy_store(source, destination)
    assert dry_run["applied"] is False
    assert dry_run["source_unchanged"] is True
    assert not destination.exists()


def test_migration_copies_common_rows_and_never_allows_cleanup(tmp_path: Path) -> None:
    source = tmp_path / "legacy.db"
    with sqlite3.connect(source) as conn:
        conn.execute(
            "CREATE TABLE events (id TEXT PRIMARY KEY, type TEXT NOT NULL, schema_version INTEGER NOT NULL, "
            "occurred_at TEXT NOT NULL, observed_at TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO events (id, type, schema_version, occurred_at, observed_at, payload_json, created_at) "
            "VALUES ('evt-1', 'legacy', 1, '2026-08-08T00:00:00Z', '2026-08-08T00:00:00Z', '{}', '2026-08-08T00:00:00Z')"
        )
    destination = tmp_path / "control.db"
    with connect(destination):
        pass
    result = migrate_legacy_store(source, destination, apply=True)
    assert result["copied"] == {"events": 1}
    with connect(destination) as conn:
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    with pytest.raises(ValueError, match="cleanup is not supported"):
        migrate_legacy_store(source, destination, cleanup=True)
