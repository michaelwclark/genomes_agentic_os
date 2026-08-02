from __future__ import annotations

from pathlib import Path

import yaml

from genomes_agentic_os import event_graph
from genomes_agentic_os.state import db, events


def _enable_state_ledger(root: Path) -> None:
    event_graph.ensure_event_state(root)
    config_path = root / event_graph.EVENT_GRAPH_FILE
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["event_graph"]["state_ledger"]["dual_write"] = True
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def test_append_event_keeps_default_file_only_behavior(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"

    event = event_graph.append_event(root, event_type="os.example.observed", source_ref="fixture/default")

    assert Path(event["path"]).is_file()
    assert not db.default_db_path(root).exists()


def test_append_event_dual_writes_normalized_sqlite_projection(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    _enable_state_ledger(root)

    event = event_graph.append_event(
        root,
        event_type="os.example.observed",
        source_ref="fixture/dual-write",
        summary="Dual-write fixture",
        correlation_id="corr-dual-write",
        payload_ref={"type": "inline", "value": "fixture"},
        run_log="runs/fixture.md",
    )

    assert Path(event["path"]).is_file()
    connection = db.connect(db.default_db_path(root))
    try:
        stored = events.get(connection, event["id"])
    finally:
        connection.close()
    assert stored is not None
    assert stored["id"] == event["id"]
    assert stored["type"] == event["type"]
    assert stored["source_ref"] == "fixture/dual-write"
    assert stored["correlation_id"] == "corr-dual-write"
    assert stored["payload"] == {"type": "inline", "value": "fixture"}
    assert stored["run_log_link"] == "runs/fixture.md"
    assert stored["domain"] == "shared_factory"
    # The live read path remains the YAML ledger during the parity window.
    assert event_graph.list_events(root)["events"] == [{**event}]
