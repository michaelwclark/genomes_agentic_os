"""Automatic diagnostics never escalate into arbitrary deletion or secret reads."""

import json
from datetime import datetime, timedelta, timezone

from genomes_agentic_os.host_disk_response import DISK_DIAGNOSTIC_SCRIPT, capture_disk_diagnostics
from genomes_agentic_os.host_sentinel import SentinelConfig, SshOutcome, run_sentinel


def test_capture_is_bounded_private_and_retained(tmp_path):
    now = datetime(2026, 10, 2, tzinfo=timezone.utc)
    for i in range(14):
        result = capture_disk_diagnostics(
            state_dir=tmp_path, host="genomesbox", ssh_target="genomesbox",
            runner=lambda *_: SshOutcome(0, "x" * 70000), connect_timeout=8,
            generated_at=(now + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    paths = sorted((tmp_path / "diagnostics").glob("*.json"))
    assert len(paths) == 12
    assert result["status"] == "captured"
    assert result["output_truncated"]
    assert len(json.loads(paths[-1].read_text())["output"]) == 65536
    assert paths[-1].stat().st_mode & 0o777 == 0o600


def test_disk_alert_invokes_diagnostics_once_per_hour(tmp_path):
    now = datetime(2026, 10, 2, tzinfo=timezone.utc)
    calls = []

    def diagnose(*args):
        calls.append(args)
        return SshOutcome(0, "root breakdown")

    for minute in (0, 5, 30, 60):
        result = run_sentinel(
            SentinelConfig(tmp_path, "genomesbox", "genomesbox"),
            ssh_runner=lambda *_: SshOutcome(0, "disk_total_bytes=2000000000000\ndisk_available_bytes=30000000000\ndisk_pct=98\ninode_pct=20\n"),
            diagnostic_runner=diagnose, notifier=lambda *_: None,
            clock=lambda: now + timedelta(minutes=minute), state_dir=tmp_path / "state",
        )
    assert len(calls) == 2
    assert result.state.disk_response["status"] == "captured"


def test_dry_run_and_offline_never_start_diagnostics(tmp_path):
    def forbidden(*_):
        raise AssertionError("unexpected diagnostics")

    for dry_run in (True, False):
        result = run_sentinel(
            SentinelConfig(tmp_path, "genomesbox", "genomesbox", dry_run=dry_run),
            ssh_runner=lambda *_: SshOutcome(255), diagnostic_runner=forbidden,
            notifier=lambda *_: None, clock=lambda: datetime(2026, 10, 2, tzinfo=timezone.utc),
            state_dir=tmp_path / "state",
        )
        assert result.state.disk_response == {}


def test_failed_diagnostic_does_not_prevent_alert_or_receipt(tmp_path):
    alerts = []

    def broken(*_):
        raise OSError("test")

    result = run_sentinel(
        SentinelConfig(tmp_path, "genomesbox", "genomesbox"),
        ssh_runner=lambda *_: SshOutcome(0, "disk_pct=98\n"), diagnostic_runner=broken,
        notifier=lambda *a: alerts.append(a),
        clock=lambda: datetime(2026, 10, 2, tzinfo=timezone.utc), state_dir=tmp_path / "state",
    )
    assert alerts
    assert result.state.disk_response["status"] == "capture_failed"
    assert (tmp_path / "state/genomesbox.latest.json").exists()


def test_probe_is_metadata_only():
    assert "journalctl --disk-usage" in DISK_DIAGNOSTIC_SCRIPT
    assert "ps -eo pid=,comm=" in DISK_DIAGNOSTIC_SCRIPT
    for forbidden in ("--vacuum", "rm ", "truncate ", ".Config.Env", "ps aux", "prune"):
        assert forbidden not in DISK_DIAGNOSTIC_SCRIPT


def test_low_utilization_growth_starts_investigation(tmp_path):
    now = datetime(2026, 10, 2, tzinfo=timezone.utc)
    total = 2000 * 1024**3
    investigations, alerts = [], []

    def diagnose(*args):
        investigations.append(args)
        return SshOutcome(0, "diagnostics")

    for minute in range(0, 61, 5):
        free = round(total * (1 - (12 + 8 * minute / 1440) / 100))
        output = f"disk_total_bytes={total}\ndisk_available_bytes={free}\ndisk_pct=13\ninode_pct=10\n"
        result = run_sentinel(
            SentinelConfig(tmp_path, "genomesbox", "genomesbox"),
            ssh_runner=lambda *_: SshOutcome(0, output), diagnostic_runner=diagnose,
            notifier=lambda _, n: alerts.append(n),
            clock=lambda: now + timedelta(minutes=minute), state_dir=tmp_path / "state",
        )
    assert len(investigations) == 1
    assert len(alerts) == 1
    assert "8.00 capacity points/day" in alerts[0].message
    assert result.state.disk_response["status"] == "captured"
    receipt = json.loads((tmp_path / "state/genomesbox.latest.json").read_text())
    assert receipt["disk_trend"]["active"]
    assert receipt["probe"]["disk_pct"] < 85
