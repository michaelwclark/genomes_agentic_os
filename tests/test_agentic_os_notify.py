"""Focused contracts for the standalone native-notification bridge."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


NOTIFY_PATH = Path(__file__).parents[1] / "harness" / "bin" / "agentic-os-notify"
loader = importlib.machinery.SourceFileLoader("agentic_os_notify", str(NOTIFY_PATH))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec and spec.loader
notify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notify)


def write_config(root: Path, *, cooldown: int = 900, per_hour: int = 8) -> None:
    path = root / "harness" / "registries" / "alerts.yml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "global:\n  history_retention_hours: 48\n  default_cooldown_seconds: %s\n  max_deliveries_per_hour: %s\n"
        "sources:\n  default:\n    min_level: info\n    cooldown_seconds: %s\n    max_deliveries_per_hour: %s\n"
        % (cooldown, per_hour, cooldown, per_hour),
        encoding="utf-8",
    )


def run_notify(monkeypatch, root: Path, *arguments: str) -> int:
    monkeypatch.setenv("AGENTIC_OS_ROOT", str(root))
    monkeypatch.setattr(notify.shutil, "which", lambda _: None)
    monkeypatch.setattr(notify, "deliver_osascript", lambda *_: 0)
    monkeypatch.setattr(sys, "argv", ["agentic-os-notify", *arguments])
    return notify.main()


def test_error_level_is_a_real_severity() -> None:
    assert notify.level_int("warning") < notify.level_int("error") < notify.level_int("critical")
    assert notify.canonical_level("warn") == "warning"


def test_retention_prunes_only_expired_records(tmp_path: Path) -> None:
    log_path = tmp_path / "alerts" / "alerts.jsonl"
    log_path.parent.mkdir()
    now = datetime.now(timezone.utc)
    old = {"ts": (now - timedelta(hours=49)).isoformat().replace("+00:00", "Z")}
    fresh = {"ts": (now - timedelta(hours=47)).isoformat().replace("+00:00", "Z")}
    log_path.write_text(json.dumps(old) + "\n" + json.dumps(fresh) + "\n", encoding="utf-8")

    removed, retained = notify.cleanup_history(log_path, 48, now=now)

    assert (removed, retained) == (1, 1)
    assert [record["ts"] for record in notify.read_history(log_path)] == [fresh["ts"]]


def test_duplicate_is_suppressed_and_audited(monkeypatch, tmp_path: Path) -> None:
    write_config(tmp_path)
    command = ("--source", "test.build", "--level", "error", "--title", "Build failed", "--message", "job 17")

    assert run_notify(monkeypatch, tmp_path, *command) == 0
    assert run_notify(monkeypatch, tmp_path, *command) == 0

    history = notify.read_history(notify.history_path(tmp_path))
    assert [item["outcome"] for item in history] == ["delivered", "suppressed"]
    assert history[-1]["reason"] == "cooldown(900s)"


def test_hourly_cap_allows_critical_but_suppresses_other_alerts(monkeypatch, tmp_path: Path) -> None:
    write_config(tmp_path, cooldown=0, per_hour=1)
    base = ("--source", "test.build", "--title", "Build", "--message")

    assert run_notify(monkeypatch, tmp_path, *base, "first", "--level", "warning") == 0
    assert run_notify(monkeypatch, tmp_path, *base, "second", "--level", "error") == 0
    assert run_notify(monkeypatch, tmp_path, *base, "critical", "--level", "critical") == 0

    history = notify.read_history(notify.history_path(tmp_path))
    assert [item["outcome"] for item in history] == ["delivered", "suppressed", "delivered"]
    assert history[1]["reason"] == "hourly_limit(1)"
