"""Tests for F-003 deferred half: doctor --all snapshot persistence and regression events.

Coverage:
- First run writes snapshot, emits nothing.
- Induced regression (delete required runtime file) emits exactly one event with
  correct payload.
- Running again with no change emits nothing more.
- Recovery (restore the file) emits nothing and updates the snapshot.
- Events appear via the normal event listing path (event_graph.list_events).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os.doctor import (
    _DOCTOR_SNAPSHOT_FILE,
    _build_snapshot,
    _detect_regressions,
    _load_snapshot,
    doctor_all,
)
from genomes_agentic_os.event_graph import list_events


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_root(tmp_path: Path) -> Path:
    root = tmp_path / "agentic_os"
    assert main(["init", "--target", str(root)]) == 0
    return root


def _snapshot_path(root: Path) -> Path:
    return root / _DOCTOR_SNAPSHOT_FILE


def _capabilities_file(root: Path) -> Path:
    """Path to capabilities.yml that validate_root (core doctor) requires."""
    return root / "harness" / "registries" / "capabilities.yml"


def _events(root: Path) -> list[dict[str, Any]]:
    """Return all events in this root's ledger."""
    return list_events(root)["events"]


def _regression_events(root: Path) -> list[dict[str, Any]]:
    return [e for e in _events(root) if e.get("type") == "os.doctor.regression"]


# ---------------------------------------------------------------------------
# Unit-level helpers
# ---------------------------------------------------------------------------


def test_build_snapshot_shape() -> None:
    """_build_snapshot returns schema_version, captured_at, and per-subsystem state."""
    fake_subsystems: dict[str, Any] = {
        "core": {"ok": True, "findings": []},
        "runtime": {
            "ok": False,
            "findings": [
                {"severity": "blocker", "message": "missing file"},
                {"severity": "cleanup", "message": "stale entry"},
            ],
        },
    }
    snap = _build_snapshot(fake_subsystems, "2026-06-10T00:00:00Z")
    assert snap["schema_version"] == 1
    assert snap["captured_at"] == "2026-06-10T00:00:00Z"
    assert snap["subsystems"]["core"]["ok"] is True
    assert snap["subsystems"]["core"]["blocker_count"] == 0
    assert snap["subsystems"]["runtime"]["ok"] is False
    assert snap["subsystems"]["runtime"]["blocker_count"] == 1


def test_detect_regressions_no_change() -> None:
    """No regression when health is identical."""
    prev = {
        "subsystems": {
            "core": {"ok": True, "blocker_count": 0},
        }
    }
    curr = {
        "subsystems": {
            "core": {"ok": True, "blocker_count": 0},
        }
    }
    assert _detect_regressions(prev, curr) == []


def test_detect_regressions_ok_flipped() -> None:
    """Regression when ok flips from True to False."""
    prev = {"subsystems": {"core": {"ok": True, "blocker_count": 0}}}
    curr = {"subsystems": {"core": {"ok": False, "blocker_count": 1}}}
    regressions = _detect_regressions(prev, curr)
    assert len(regressions) == 1
    r = regressions[0]
    assert r["subsystem"] == "core"
    assert r["was_ok"] is True
    assert r["is_ok"] is False
    assert r["prev_blocker_count"] == 0
    assert r["curr_blocker_count"] == 1


def test_detect_regressions_blocker_count_increased() -> None:
    """Regression when blocker count increases even if ok stays False."""
    prev = {"subsystems": {"runtime": {"ok": False, "blocker_count": 1}}}
    curr = {"subsystems": {"runtime": {"ok": False, "blocker_count": 3}}}
    regressions = _detect_regressions(prev, curr)
    assert len(regressions) == 1
    assert regressions[0]["prev_blocker_count"] == 1
    assert regressions[0]["curr_blocker_count"] == 3


def test_detect_regressions_improvement_not_regression() -> None:
    """Improvement (blocker count drops) is not a regression."""
    prev = {"subsystems": {"runtime": {"ok": False, "blocker_count": 3}}}
    curr = {"subsystems": {"runtime": {"ok": True, "blocker_count": 0}}}
    assert _detect_regressions(prev, curr) == []


def test_detect_regressions_new_subsystem_not_regression() -> None:
    """A subsystem that didn't exist in the prior snapshot is not a regression."""
    prev = {"subsystems": {}}
    curr = {"subsystems": {"runtime": {"ok": False, "blocker_count": 2}}}
    assert _detect_regressions(prev, curr) == []


# ---------------------------------------------------------------------------
# Integration — first run
# ---------------------------------------------------------------------------


def test_first_run_writes_snapshot_emits_nothing(tmp_path: Path) -> None:
    """First doctor_all run writes snapshot and emits no regression event."""
    root = _init_root(tmp_path)

    result = doctor_all(root)

    # Return contract
    assert "regression_event" in result
    assert result["regression_event"] is None

    # Snapshot exists
    snap_path = _snapshot_path(root)
    assert snap_path.is_file(), "snapshot should be written after first run"
    snap = yaml.safe_load(snap_path.read_text(encoding="utf-8"))
    assert snap["schema_version"] == 1
    assert "captured_at" in snap
    assert set(snap["subsystems"].keys()) >= {"core", "runtime", "event_graph", "config"}

    # No regression event in ledger
    assert _regression_events(root) == []


# ---------------------------------------------------------------------------
# Integration — induced regression
# ---------------------------------------------------------------------------


def test_induced_regression_emits_one_event(tmp_path: Path) -> None:
    """Deleting a required core file between runs triggers exactly one event."""
    root = _init_root(tmp_path)

    # Run 1: establish baseline — core should be ok on a fresh install
    result1 = doctor_all(root)
    assert result1["regression_event"] is None
    snap1 = _load_snapshot(root)
    assert snap1 is not None
    assert snap1["subsystems"]["core"]["ok"] is True, "core should be healthy after init"

    # Induce regression: remove capabilities.yml so validate_root reports a blocker
    cap = _capabilities_file(root)
    assert cap.is_file(), "capabilities.yml must exist after init"
    backup = cap.read_bytes()
    cap.unlink()

    # Run 2: should detect regression in core
    result2 = doctor_all(root)

    assert result2["regression_event"] is not None, "regression event should be emitted"
    event = result2["regression_event"]
    assert event["type"] == "os.doctor.regression"

    # Payload carries regression detail
    payload = event.get("payload_ref") or {}
    assert payload.get("type") == "inline"
    regressions = payload.get("regressions") or []
    subsystem_names = [r["subsystem"] for r in regressions]
    assert "core" in subsystem_names

    # Verify regression record content
    core_reg = next(r for r in regressions if r["subsystem"] == "core")
    assert core_reg["was_ok"] is True
    assert core_reg["is_ok"] is False

    # Exactly one regression event in ledger
    reg_events = _regression_events(root)
    assert len(reg_events) == 1

    # Restore file for subsequent sub-tests
    cap.write_bytes(backup)


# ---------------------------------------------------------------------------
# Integration — no change second run
# ---------------------------------------------------------------------------


def test_no_change_run_emits_nothing(tmp_path: Path) -> None:
    """Consecutive identical runs do not accumulate regression events."""
    root = _init_root(tmp_path)

    doctor_all(root)  # run 1 — baseline
    doctor_all(root)  # run 2 — no change
    doctor_all(root)  # run 3 — no change

    assert _regression_events(root) == []


# ---------------------------------------------------------------------------
# Integration — recovery
# ---------------------------------------------------------------------------


def test_recovery_emits_nothing_updates_snapshot(tmp_path: Path) -> None:
    """Restoring health after a regression emits nothing and updates the snapshot."""
    root = _init_root(tmp_path)

    # Run 1: baseline
    doctor_all(root)

    # Induce regression
    cap = _capabilities_file(root)
    backup = cap.read_bytes()
    cap.unlink()

    # Run 2: regression
    result2 = doctor_all(root)
    assert result2["regression_event"] is not None

    # Restore health
    cap.write_bytes(backup)

    # Run 3: recovery — no new event
    result3 = doctor_all(root)
    assert result3["regression_event"] is None, "recovery should not emit an event"

    # Still exactly one regression event in ledger (from run 2)
    assert len(_regression_events(root)) == 1

    # Snapshot now reflects healthy state again
    snap = _load_snapshot(root)
    assert snap is not None
    assert "captured_at" in snap


# ---------------------------------------------------------------------------
# Integration — events visible via normal listing path
# ---------------------------------------------------------------------------


def test_regression_event_visible_via_event_listing(tmp_path: Path) -> None:
    """Regression event is visible through the standard list_events path."""
    root = _init_root(tmp_path)

    # Baseline
    doctor_all(root)

    # Induce regression
    cap = _capabilities_file(root)
    backup = cap.read_bytes()
    cap.unlink()

    doctor_all(root)

    # Restore
    cap.write_bytes(backup)

    events = _events(root)
    types = [e.get("type") for e in events]
    assert "os.doctor.regression" in types, f"regression event not in ledger; found types: {types}"

    # Event privacy flags — no secrets, no customer data
    reg_event = next(e for e in events if e.get("type") == "os.doctor.regression")
    privacy = reg_event.get("privacy") or {}
    assert privacy.get("contains_secret") is False
    assert privacy.get("contains_customer_data") is False


# ---------------------------------------------------------------------------
# Integration — CLI round-trip
# ---------------------------------------------------------------------------


def test_cli_doctor_all_regression_event_in_output(tmp_path: Path, capsys: Any) -> None:
    """CLI doctor --all output includes regression_event key."""
    root = _init_root(tmp_path)

    # Run once to establish baseline snapshot (fresh install may have blockers
    # in runtime/config — we only care that the snapshot file is written)
    main(["doctor", "--all", "--root", str(root)])
    capsys.readouterr()  # discard

    # Induce regression in core
    cap = _capabilities_file(root)
    backup = cap.read_bytes()
    cap.unlink()

    # Second run via CLI — must produce YAML output with regression_event key
    main(["doctor", "--all", "--root", str(root)])
    out = capsys.readouterr().out
    assert out.strip(), "doctor --all should produce output"
    parsed = yaml.safe_load(out)
    assert "regression_event" in parsed
    assert parsed["regression_event"] is not None, "regression event should be present after core regression"

    cap.write_bytes(backup)
