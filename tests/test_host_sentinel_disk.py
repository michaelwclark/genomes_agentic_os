"""Disk incident alerts exercise multiple persisted five-minute cycles."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import plistlib

import pytest

from genomes_agentic_os import host_sentinel as sentinel

GIB = 1024**3


def probe(pct=50, free=1000, inode=10):
    return (f"boot_id=same\ndisk_total_bytes={2000 * GIB}\n"
            f"disk_available_bytes={int(free * GIB)}\ndisk_pct={pct}\ninode_pct={inode}\n")


@pytest.fixture
def cycle(tmp_path):
    now = datetime(2026, 10, 2, tzinfo=timezone.utc)
    delivered = []

    def run(output, *, advance=300, notifier=None, dry_run=False):
        nonlocal now
        now += timedelta(seconds=advance)
        return sentinel.run_sentinel(
            sentinel.SentinelConfig(tmp_path, "genomesbox", "genomesbox", dry_run=dry_run),
            ssh_runner=lambda *_: sentinel.SshOutcome(0, output),
            notifier=notifier or (lambda config, note: delivered.append(note)),
            clock=lambda: now, state_dir=tmp_path / "state",
        )

    return run, delivered


def test_warn_escalate_remind_and_recover(cycle):
    run, delivered = cycle
    assert run(probe()).notifications == []
    assert run(probe(pct=85)).notifications[0].level == "warning"
    assert run(probe(pct=90)).notifications == []
    assert run(probe(pct=98, free=46)).notifications[0].level == "critical"
    assert run(probe(pct=98, free=46)).notifications == []
    assert run(probe(pct=98, free=46), advance=1800).notifications[0].level == "critical"
    assert run(probe(pct=60)).notifications[0].level == "info"
    assert run(probe()).notifications == []


@pytest.mark.parametrize("output", [probe(inode=97), probe(free=3)])
def test_inode_exhaustion_and_low_absolute_free_space_are_critical(cycle, output):
    run, _ = cycle
    assert run(output).notifications[0].level == "critical"


def test_rapid_growth_and_projected_exhaustion(cycle):
    run, _ = cycle
    run(probe(pct=75, free=100))
    note = run(probe(pct=76, free=85)).notifications[0]
    assert note.level == "critical"
    assert "3.00 GiB/min" in note.message


def test_growth_estimate_ignores_long_gaps(cycle):
    run, _ = cycle
    run(probe(pct=75, free=1000))
    assert run(probe(pct=75, free=100), advance=7200).notifications == []


def test_missing_metrics_warn_and_cannot_clear_existing_critical(cycle):
    run, _ = cycle
    assert run("boot_id=same\n").notifications == []
    assert "telemetry missing" in run("boot_id=same\n").notifications[0].message
    run(probe(pct=98))
    assert run("boot_id=same\n").state.disk_alert_level == "critical"
    result = run("boot_id=same\n", advance=1800)
    assert result.notifications[0].level == "critical"
    assert "telemetry missing" in result.notifications[0].message


def test_bad_inode_metric_does_not_hide_full_disk(cycle):
    run, _ = cycle
    assert run(probe(pct=98, inode="bad")).notifications[0].level == "critical"


def test_failed_delivery_retries_next_cycle(cycle):
    run, delivered = cycle

    def fail(*_):
        raise RuntimeError("test notifier unavailable")

    first = run(probe(pct=98), notifier=fail)
    assert first.state.disk_alert_level == ""
    assert run(probe(pct=98)).notifications[0].level == "critical"
    assert len(delivered) == 1


def test_dry_run_has_no_delivery_or_state(tmp_path, cycle):
    run, delivered = cycle
    result = run(probe(pct=98), dry_run=True)
    assert result.notifications[0].level == "critical"
    assert delivered == []
    assert not (tmp_path / "state/genomesbox.state.json").exists()


def test_real_notifier_nonzero_is_reported(monkeypatch, tmp_path):
    monkeypatch.setattr(sentinel.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1))
    with pytest.raises(RuntimeError, match="exited 1"):
        sentinel.notify_via_agentic_os_notify(
            sentinel.SentinelConfig(tmp_path, "genomesbox", "genomesbox"),
            sentinel.Notification("critical", "test", "test", "test"),
        )


def test_failed_outage_alert_retries(tmp_path):
    config = sentinel.SentinelConfig(tmp_path, "genomesbox", "genomesbox", unreachable_threshold=1)

    def fail(*_):
        raise RuntimeError("test notifier unavailable")

    kwargs = dict(ssh_runner=lambda *_: sentinel.SshOutcome(255),
                  clock=lambda: datetime(2026, 10, 2, tzinfo=timezone.utc),
                  state_dir=tmp_path / "state")
    assert not sentinel.run_sentinel(config, notifier=fail, **kwargs).state.unreachable_alerted
    result = sentinel.run_sentinel(config, notifier=lambda *_: None, **kwargs)
    assert result.notifications[0].level == "critical"
    assert result.state.unreachable_alerted


def test_remote_df_units_and_fields():
    # Run the actual df/awk snippets against Linux df fixtures, with no SSH.
    script = '\n'.join(line for line in sentinel.REMOTE_PROBE_SCRIPT.splitlines() if line.startswith("LC_ALL="))
    fake_df = '''df() {
      if [ "$1" = "-Pi" ]; then
        printf 'Filesystem Inodes IUsed IFree IUse%% Mounted\n/dev/root 100 96 4 96%% /\n'
      else
        printf 'Filesystem 1024-blocks Used Available Capacity Mounted\n/dev/root 2000000 1800000 100000 95%% /\n'
      fi
    }
    '''
    result = subprocess.run(["sh", "-s"], input=fake_df + script, text=True, capture_output=True, check=True)
    parsed = sentinel.parse_probe_output(result.stdout)
    assert parsed.disk_total_bytes == 2000000 * 1024
    assert parsed.disk_available_bytes == 100000 * 1024
    assert parsed.disk_pct == 95
    assert parsed.inode_pct == 96


def test_monitor_output_logs_are_bounded(tmp_path, cycle):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    path = state_dir / "genomesbox.launchd.out.log"
    path.write_text("x" * (1024**2 + 1))
    archive = path.with_suffix(".log.1")
    archive.write_text("previous")
    run, _ = cycle
    run(probe())
    assert not path.exists()
    assert archive.stat().st_size == 1024**2 + 1


def test_launchd_template_is_valid_xml():
    path = Path(__file__).parents[1] / "templates/runtime/host-sentinel.launchd.plist.template"
    assert plistlib.loads(path.read_bytes())["StartInterval"] == 300
