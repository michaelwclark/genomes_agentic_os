"""Behavior tests for the off-box host sentinel.

Each test exercises one alerting decision the sentinel is supposed to make
(or deliberately not make) across successive runs, using fake ssh/notifier/
clock callables so no real subprocess or wall-clock time is involved.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from genomes_agentic_os.host_sentinel import (
    Notification,
    ProbeResult,
    SentinelConfig,
    SentinelState,
    SshOutcome,
    load_state,
    parse_probe_output,
    run_sentinel,
    state_path,
)

FULL_PROBE = (
    "boot_id=aaaaaaaa-1111-2222-3333-444444444444\n"
    "uptime_s=12345\n"
    "prev_boot_last_ts=1758000000.5\n"
    "prev_boot_clean=1\n"
    "failed_system=unit-a.service,unit-b.service\n"
    "failed_user=user-unit.service\n"
    "unhealthy_containers=ctr-a,ctr-b\n"
)


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


class FakeNotifier:
    def __init__(self) -> None:
        self.calls: list[tuple[SentinelConfig, Notification]] = []

    def __call__(self, config: SentinelConfig, note: Notification) -> None:
        self.calls.append((config, note))


def make_config(tmp_path: Path, **overrides) -> SentinelConfig:
    defaults = dict(
        root=tmp_path,
        host="genomesbox",
        ssh_target="genomesbox",
        connect_timeout=10,
        unreachable_threshold=2,
        persist_threshold=2,
        dry_run=False,
    )
    defaults.update(overrides)
    return SentinelConfig(**defaults)


def ssh_ok(stdout: str):
    def runner(target: str, script: str, timeout: int) -> SshOutcome:
        return SshOutcome(returncode=0, stdout=stdout)

    return runner


def ssh_unreachable(*, timed_out: bool = False, returncode: int = 255):
    def runner(target: str, script: str, timeout: int) -> SshOutcome:
        if timed_out:
            return SshOutcome(returncode=-1, timed_out=True, stderr="ssh timed out")
        return SshOutcome(returncode=returncode, stderr="ssh: connect refused")

    return runner


class TestParseProbeOutput:
    def test_parses_a_full_probe(self):
        result = parse_probe_output(FULL_PROBE)

        assert result.reachable is True
        assert result.boot_id == "aaaaaaaa-1111-2222-3333-444444444444"
        assert result.uptime_s == 12345
        assert result.prev_boot_last_ts == 1758000000.5
        assert result.prev_boot_clean is True
        assert result.failed_system == ("unit-a.service", "unit-b.service")
        assert result.failed_user == ("user-unit.service",)
        assert result.unhealthy_containers == ("ctr-a", "ctr-b")

    def test_parses_missing_and_empty_fields_without_raising(self):
        result = parse_probe_output("boot_id=abc123\nuptime_s=\nfailed_system=\n")

        assert result.boot_id == "abc123"
        assert result.uptime_s is None
        assert result.prev_boot_last_ts is None
        assert result.prev_boot_clean is None
        assert result.failed_system == ()
        assert result.unhealthy_containers == ()


class TestFirstRun:
    def test_first_run_records_boot_id_with_no_notifications(self, tmp_path):
        config = make_config(tmp_path)
        notifier = FakeNotifier()

        result = run_sentinel(
            config,
            ssh_runner=ssh_ok(FULL_PROBE),
            notifier=notifier,
            clock=FakeClock(datetime(2026, 9, 25, tzinfo=timezone.utc)),
            state_dir=tmp_path / "state",
        )

        assert result.notifications == []
        assert result.state.last_boot_id == "aaaaaaaa-1111-2222-3333-444444444444"
        assert notifier.calls == []


class TestUnreachable:
    def test_single_miss_does_not_alert(self, tmp_path):
        config = make_config(tmp_path, unreachable_threshold=2)
        notifier = FakeNotifier()

        result = run_sentinel(
            config,
            ssh_runner=ssh_unreachable(),
            notifier=notifier,
            clock=FakeClock(datetime(2026, 9, 25, tzinfo=timezone.utc)),
            state_dir=tmp_path / "state",
        )

        assert result.notifications == []
        assert result.state.consecutive_unreachable == 1

    def test_second_consecutive_miss_sends_one_critical_alert(self, tmp_path):
        config = make_config(tmp_path, unreachable_threshold=2)
        notifier = FakeNotifier()
        state_dir = tmp_path / "state"
        clock = FakeClock(datetime(2026, 9, 25, tzinfo=timezone.utc))

        run_sentinel(config, ssh_runner=ssh_unreachable(), notifier=notifier, clock=clock, state_dir=state_dir)
        clock.advance(minutes=5)
        result = run_sentinel(config, ssh_runner=ssh_unreachable(), notifier=notifier, clock=clock, state_dir=state_dir)

        assert len(result.notifications) == 1
        assert result.notifications[0].level == "critical"
        assert result.notifications[0].dedupe_key == "host-sentinel-genomesbox-unreachable"
        assert len(notifier.calls) == 1

    def test_third_consecutive_miss_does_not_duplicate_the_alert(self, tmp_path):
        config = make_config(tmp_path, unreachable_threshold=2)
        notifier = FakeNotifier()
        state_dir = tmp_path / "state"
        clock = FakeClock(datetime(2026, 9, 25, tzinfo=timezone.utc))

        for _ in range(3):
            run_sentinel(config, ssh_runner=ssh_unreachable(), notifier=notifier, clock=clock, state_dir=state_dir)
            clock.advance(minutes=5)

        assert len(notifier.calls) == 1

    def test_recovery_after_alerted_outage_sends_info_notification(self, tmp_path):
        config = make_config(tmp_path, unreachable_threshold=2)
        notifier = FakeNotifier()
        state_dir = tmp_path / "state"
        clock = FakeClock(datetime(2026, 9, 25, tzinfo=timezone.utc))

        run_sentinel(config, ssh_runner=ssh_unreachable(), notifier=notifier, clock=clock, state_dir=state_dir)
        clock.advance(minutes=5)
        run_sentinel(config, ssh_runner=ssh_unreachable(), notifier=notifier, clock=clock, state_dir=state_dir)
        clock.advance(minutes=10)

        result = run_sentinel(config, ssh_runner=ssh_ok(FULL_PROBE), notifier=notifier, clock=clock, state_dir=state_dir)

        recovery = [n for n in result.notifications if n.level == "info" and "reachable again" in n.title]
        assert len(recovery) == 1
        assert result.state.unreachable_alerted is False
        assert result.state.consecutive_unreachable == 0

    def test_ssh_timeout_is_treated_as_unreachable(self, tmp_path):
        config = make_config(tmp_path, unreachable_threshold=1)
        notifier = FakeNotifier()

        result = run_sentinel(
            config,
            ssh_runner=ssh_unreachable(timed_out=True),
            notifier=notifier,
            clock=FakeClock(datetime(2026, 9, 25, tzinfo=timezone.utc)),
            state_dir=tmp_path / "state",
        )

        assert result.probe.reachable is False
        assert len(result.notifications) == 1
        assert result.notifications[0].level == "critical"


class TestBootChange:
    def _seed_state(self, tmp_path, state_dir, boot_id: str) -> None:
        state_dir.mkdir(parents=True, exist_ok=True)
        state = SentinelState(last_boot_id=boot_id, last_seen_at="2026-09-25T00:00:00Z")
        (state_dir / "genomesbox.state.json").write_text(json.dumps(state.as_dict()))

    def test_unclean_reboot_is_critical_with_downtime(self, tmp_path):
        state_dir = tmp_path / "state"
        self._seed_state(tmp_path, state_dir, boot_id="oldoldold-0000-0000-0000-000000000000")
        config = make_config(tmp_path)
        notifier = FakeNotifier()
        unclean_probe = FULL_PROBE.replace("prev_boot_clean=1", "prev_boot_clean=0")

        result = run_sentinel(
            config,
            ssh_runner=ssh_ok(unclean_probe),
            notifier=notifier,
            clock=FakeClock(datetime(2026, 9, 25, 1, 0, 0, tzinfo=timezone.utc)),
            state_dir=state_dir,
        )

        boot_alerts = [n for n in result.notifications if "rebooted" in n.title]
        assert len(boot_alerts) == 1
        assert boot_alerts[0].level == "critical"
        assert "unclean" in boot_alerts[0].title
        assert "down for approximately" in boot_alerts[0].message

    def test_clean_reboot_is_warning(self, tmp_path):
        state_dir = tmp_path / "state"
        self._seed_state(tmp_path, state_dir, boot_id="oldoldold-0000-0000-0000-000000000000")
        config = make_config(tmp_path)
        notifier = FakeNotifier()

        result = run_sentinel(
            config,
            ssh_runner=ssh_ok(FULL_PROBE),
            notifier=notifier,
            clock=FakeClock(datetime(2026, 9, 25, 1, 0, 0, tzinfo=timezone.utc)),
            state_dir=state_dir,
        )

        boot_alerts = [n for n in result.notifications if "rebooted" in n.title]
        assert len(boot_alerts) == 1
        assert boot_alerts[0].level == "warning"
        assert "clean" in boot_alerts[0].title

    def test_same_boot_id_produces_no_boot_notification(self, tmp_path):
        state_dir = tmp_path / "state"
        self._seed_state(tmp_path, state_dir, boot_id="aaaaaaaa-1111-2222-3333-444444444444")
        config = make_config(tmp_path)
        notifier = FakeNotifier()

        result = run_sentinel(
            config,
            ssh_runner=ssh_ok(FULL_PROBE),
            notifier=notifier,
            clock=FakeClock(datetime(2026, 9, 25, 1, 0, 0, tzinfo=timezone.utc)),
            state_dir=state_dir,
        )

        assert not any("rebooted" in n.title for n in result.notifications)


class TestPersistentProblems:
    def test_first_sighting_of_a_failed_unit_does_not_alert(self, tmp_path):
        config = make_config(tmp_path, persist_threshold=2)
        notifier = FakeNotifier()
        probe = "boot_id=b1\nfailed_system=unit-a.service\n"

        result = run_sentinel(
            config,
            ssh_runner=ssh_ok(probe),
            notifier=notifier,
            clock=FakeClock(datetime(2026, 9, 25, tzinfo=timezone.utc)),
            state_dir=tmp_path / "state",
        )

        assert result.notifications == []
        assert result.state.problem_streak == {"sys:unit-a.service": 1}

    def test_second_consecutive_sighting_sends_one_warning(self, tmp_path):
        config = make_config(tmp_path, persist_threshold=2)
        notifier = FakeNotifier()
        state_dir = tmp_path / "state"
        probe = "boot_id=b1\nfailed_system=unit-a.service\n"
        clock = FakeClock(datetime(2026, 9, 25, tzinfo=timezone.utc))

        run_sentinel(config, ssh_runner=ssh_ok(probe), notifier=notifier, clock=clock, state_dir=state_dir)
        clock.advance(minutes=5)
        result = run_sentinel(config, ssh_runner=ssh_ok(probe), notifier=notifier, clock=clock, state_dir=state_dir)

        persistent = [n for n in result.notifications if n.level == "warning" and "persistent" in n.title]
        assert len(persistent) == 1
        assert "unit-a.service" in persistent[0].message

    def test_third_consecutive_sighting_does_not_duplicate(self, tmp_path):
        config = make_config(tmp_path, persist_threshold=2)
        notifier = FakeNotifier()
        state_dir = tmp_path / "state"
        probe = "boot_id=b1\nfailed_system=unit-a.service\n"
        clock = FakeClock(datetime(2026, 9, 25, tzinfo=timezone.utc))

        for _ in range(3):
            run_sentinel(config, ssh_runner=ssh_ok(probe), notifier=notifier, clock=clock, state_dir=state_dir)
            clock.advance(minutes=5)

        persistent_calls = [n for _, n in notifier.calls if "persistent" in n.title]
        assert len(persistent_calls) == 1

    def test_unit_disappearing_sends_recovered_notification(self, tmp_path):
        config = make_config(tmp_path, persist_threshold=2)
        notifier = FakeNotifier()
        state_dir = tmp_path / "state"
        broken = "boot_id=b1\nfailed_system=unit-a.service\n"
        fixed = "boot_id=b1\nfailed_system=\n"
        clock = FakeClock(datetime(2026, 9, 25, tzinfo=timezone.utc))

        run_sentinel(config, ssh_runner=ssh_ok(broken), notifier=notifier, clock=clock, state_dir=state_dir)
        clock.advance(minutes=5)
        run_sentinel(config, ssh_runner=ssh_ok(broken), notifier=notifier, clock=clock, state_dir=state_dir)
        clock.advance(minutes=5)

        result = run_sentinel(config, ssh_runner=ssh_ok(fixed), notifier=notifier, clock=clock, state_dir=state_dir)

        recovered = [n for n in result.notifications if n.level == "info" and "recovered" in n.title]
        assert len(recovered) == 1
        assert result.state.problem_streak == {}
        assert result.state.alerted_problems == []


class TestDryRun:
    def test_dry_run_writes_no_state_and_calls_no_notifier(self, tmp_path):
        config = make_config(tmp_path, dry_run=True, unreachable_threshold=1)
        notifier = FakeNotifier()
        state_dir = tmp_path / "state"

        run_sentinel(
            config,
            ssh_runner=ssh_unreachable(),
            notifier=notifier,
            clock=FakeClock(datetime(2026, 9, 25, tzinfo=timezone.utc)),
            state_dir=state_dir,
        )

        assert notifier.calls == []
        assert not state_path(state_dir, "genomesbox").exists()

    def test_dry_run_still_computes_would_be_notifications(self, tmp_path):
        config = make_config(tmp_path, dry_run=True, unreachable_threshold=1)
        notifier = FakeNotifier()

        result = run_sentinel(
            config,
            ssh_runner=ssh_unreachable(),
            notifier=notifier,
            clock=FakeClock(datetime(2026, 9, 25, tzinfo=timezone.utc)),
            state_dir=tmp_path / "state",
        )

        assert len(result.notifications) == 1
        assert result.state_written is False


class TestStateRoundTrip:
    def test_load_state_missing_file_returns_defaults(self, tmp_path):
        state = load_state(tmp_path, "genomesbox")

        assert state == SentinelState()

    def test_load_state_corrupt_file_returns_defaults(self, tmp_path):
        tmp_path.mkdir(exist_ok=True)
        (tmp_path / "genomesbox.state.json").write_text("{not json")

        state = load_state(tmp_path, "genomesbox")

        assert state == SentinelState()
