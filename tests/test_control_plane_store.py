"""Contract coverage for the provider-neutral control-plane port."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from genomes_agentic_os.state.control_plane import (
    ControlPlaneConfigurationError,
    ControlPlaneStore,
    ControlPlaneStoreConfig,
    UnsupportedControlPlaneBackend,
    build_control_plane_store,
)


def test_sqlite_store_satisfies_event_and_cursor_contract(tmp_path: Path) -> None:
    store: ControlPlaneStore = build_control_plane_store(
        ControlPlaneStoreConfig.from_mapping(
            {"backend": "sqlite", "sqlite": {"path": str(tmp_path / "control-plane.db")}}
        )
    )

    stored = store.append_event(
        "source.completed",
        id="evt_contract",
        correlation_id="work-146",
        payload={"result": "success"},
    )
    assert stored["id"] == "evt_contract"
    assert store.get_event("evt_contract")["payload"] == {"result": "success"}  # type: ignore[index]
    assert [event["id"] for event in store.query_events(correlation_id="work-146")] == ["evt_contract"]

    cursor = store.set_cursor("github", cursor_type="timestamp", last_value="2026-08-02T00:00:00Z")
    assert cursor["name"] == "github"
    assert store.get_cursor("github")["last_value"] == "2026-08-02T00:00:00Z"  # type: ignore[index]


def test_backend_selection_is_explicit_and_never_fakes_postgres(tmp_path: Path) -> None:
    config = ControlPlaneStoreConfig("sqlite", sqlite_path=tmp_path / "control-plane.db")
    assert build_control_plane_store(config).backend == "sqlite"

    with pytest.raises(UnsupportedControlPlaneBackend, match="driver, migrations, and passed lease/idempotency"):
        build_control_plane_store(ControlPlaneStoreConfig("postgres"))


def test_sqlite_requires_a_path_and_valid_timeout() -> None:
    with pytest.raises(ControlPlaneConfigurationError, match="sqlite.path is required"):
        build_control_plane_store(ControlPlaneStoreConfig("sqlite"))
    with pytest.raises(ControlPlaneConfigurationError, match="busy_timeout_ms"):
        ControlPlaneStoreConfig.from_mapping({"sqlite": {"path": "state.db", "busy_timeout_ms": 0}})


def test_port_boundary_does_not_import_a_concrete_datastore_driver() -> None:
    port_path = Path(__file__).parents[1] / "src" / "genomes_agentic_os" / "state" / "control_plane.py"
    tree = ast.parse(port_path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "sqlite3" not in imported
