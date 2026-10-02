"""Off-box sentinel that watches another host for outages and unclean reboots.

A primary server host died uncleanly twice within 24 hours (2026-09-21, 2026-09-22, down
~4h45m) and nobody was alerted -- systemd units stayed failed for ~19h after
the reboot before anyone noticed. The existing tools do not cover this gap:

* ``agentic-os-notify`` is the delivery seam, but nothing was watching the
  host to call it.
* ``agentic-os-monitor`` is an interactive curses TUI, not a scheduled job.
  Its disk thresholds do not protect unattended hosts. This sentinel also
  probes root disk bytes/inodes and alerts on pressure or rapid consumption.
* Host Auto-Doctor runs *on* the host it is checking, so a host that is fully
  down cannot run its own health report.

This module is the missing off-box probe: something on a different machine
that periodically asks "is that host up, and did it come back cleanly?" and
alerts through the existing notifier when the answer changes. It has to keep
working when the thing it watches does not, which is why it depends on
nothing but the standard library and one ``ssh`` subprocess -- no Agentic OS
runtime, no queue, no network calls beyond that single probe.

Deciding what to alert on is the interesting part, and each rule exists
because a naive version fails a specific way:

* A single failed ping is not an outage -- flaky Wi-Fi and one slow ssh
  handshake are normal. Only ``unreachable_threshold`` consecutive misses (and
  not already alerted) count as down, which is why the state file tracks a
  running count instead of alerting on the first failure.
* A reboot is not always a problem -- a deliberate ``reboot`` command produces
  the same boot-id change as a kernel panic. Whether the *previous* boot's
  journal ends with a shutdown-target line is the signal that separates an
  intentional restart from a crash, so a clean reboot is ``warning`` and an
  unclean one is ``critical``.
* A single failed systemd unit after boot is often transient (a dependency
  that raced and won on retry). Only a unit or container that is *still*
  broken after ``persist_threshold`` consecutive probes is worth an alert,
  which is why streaks are tracked per problem key and reset the moment the
  problem disappears.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from .host_disk_trends import observe_disk_trend
from .host_disk_response import capture_disk_diagnostics

#: Fed to the remote host over stdin via ``ssh ... sh -s``. Never built from
#: caller-supplied strings -- it is a fixed constant, so there is no shell
#: injection surface no matter what ``--host``/``--ssh-target`` are.
REMOTE_PROBE_SCRIPT = r"""
join() {
  awk 'BEGIN{first=1} NF{if(!first) printf ","; printf "%s", $0; first=0}'
}
echo "boot_id=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || true)"
echo "uptime_s=$(awk '{printf "%d", $1}' /proc/uptime 2>/dev/null || true)"
echo "prev_boot_last_ts=$(journalctl -b -1 -n 1 -o short-unix --no-pager 2>/dev/null | awk '{print $1}' || true)"
LC_ALL=C df -Pk / 2>/dev/null | awk 'NR==2 {gsub(/%/, "", $5); printf "disk_total_bytes=%.0f\ndisk_available_bytes=%.0f\ndisk_pct=%s\n", $2*1024, $4*1024, $5}'
LC_ALL=C df -Pi / 2>/dev/null | awk 'NR==2 {gsub(/%/, "", $5); print "inode_pct=" $5}'
clean=0
if journalctl -b -1 -n 80 -o cat --no-pager 2>/dev/null | grep -Eq \
  'Reached target shutdown\.target|Reached target System Shutdown|Journal stopped|System is powering down|System is rebooting'
then
  clean=1
fi
echo "prev_boot_clean=$clean"
echo "failed_system=$(systemctl --failed --no-legend --plain 2>/dev/null | awk '{print $1}' | join || true)"
echo "failed_user=$(systemctl --user --failed --no-legend --plain 2>/dev/null | awk '{print $1}' | join || true)"
echo "unhealthy_containers=$( (docker ps --filter health=unhealthy --format '{{.Names}}' 2>/dev/null; docker ps --filter status=restarting --format '{{.Names}}' 2>/dev/null) | join || true)"
true
""".strip()

#: journalctl -b -1 lines that mark the previous boot as an intentional stop
#: rather than a crash. Presence of any one is enough.
CLEAN_SHUTDOWN_MARKERS = (
    "Reached target shutdown.target",
    "Reached target System Shutdown",
    "Journal stopped",
    "System is powering down",
    "System is rebooting",
)

_STATE_SUFFIX = ".state.json"
_RECEIPT_SUFFIX = ".latest.json"


def _parse_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_list(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class ProbeResult:
    """One probe's outcome. ``reachable=False`` means ssh itself failed."""

    reachable: bool
    boot_id: str | None = None
    uptime_s: int | None = None
    prev_boot_last_ts: float | None = None
    prev_boot_clean: bool | None = None
    failed_system: tuple[str, ...] = ()
    failed_user: tuple[str, ...] = ()
    unhealthy_containers: tuple[str, ...] = ()
    error: str | None = None
    disk_total_bytes: int | None = None
    disk_available_bytes: int | None = None
    disk_pct: int | None = None
    inode_pct: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "reachable": self.reachable,
            "boot_id": self.boot_id,
            "uptime_s": self.uptime_s,
            "prev_boot_last_ts": self.prev_boot_last_ts,
            "prev_boot_clean": self.prev_boot_clean,
            "failed_system": list(self.failed_system),
            "failed_user": list(self.failed_user),
            "unhealthy_containers": list(self.unhealthy_containers),
            "error": self.error,
            "disk_total_bytes": self.disk_total_bytes,
            "disk_available_bytes": self.disk_available_bytes,
            "disk_pct": self.disk_pct,
            "inode_pct": self.inode_pct,
        }


def parse_probe_output(stdout: str) -> ProbeResult:
    """Parse the ``key=value`` lines the remote probe script prints.

    Tolerant by construction: a missing or empty field just becomes ``None``
    or an empty tuple, because the remote script's ``|| true`` guards mean a
    partial failure (e.g. docker absent) still produces a usable result.
    """
    fields: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        fields[key.strip()] = value.strip()

    clean_raw = fields.get("prev_boot_clean")
    return ProbeResult(
        reachable=True,
        boot_id=fields.get("boot_id") or None,
        uptime_s=_parse_int(fields.get("uptime_s")),
        prev_boot_last_ts=_parse_float(fields.get("prev_boot_last_ts")),
        prev_boot_clean=(clean_raw == "1") if clean_raw in ("0", "1") else None,
        failed_system=_parse_list(fields.get("failed_system")),
        failed_user=_parse_list(fields.get("failed_user")),
        unhealthy_containers=_parse_list(fields.get("unhealthy_containers")),
        disk_total_bytes=_parse_int(fields.get("disk_total_bytes")),
        disk_available_bytes=_parse_int(fields.get("disk_available_bytes")),
        disk_pct=_parse_int(fields.get("disk_pct")),
        inode_pct=_parse_int(fields.get("inode_pct")),
    )


@dataclass(frozen=True)
class SshOutcome:
    """Raw result of the one ssh subprocess a probe makes."""

    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


#: Injected so tests never spawn a real subprocess. (target, script, timeout) -> outcome.
SshRunner = Callable[[str, str, int], SshOutcome]

#: Injected delivery seam. Never called when ``config.dry_run`` is set.
Notifier = Callable[["SentinelConfig", "Notification"], None]

#: Injected clock so alert-timing tests are deterministic.
Clock = Callable[[], datetime]


def run_ssh_probe(ssh_target: str, script: str, connect_timeout: int) -> SshOutcome:
    """The real ``SshRunner``: one ``ssh ... sh -s`` subprocess, 60s hard cap."""
    try:
        proc = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                f"ConnectTimeout={connect_timeout}",
                ssh_target,
                "sh",
                "-s",
            ],
            input=script,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return SshOutcome(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
    except subprocess.TimeoutExpired:
        return SshOutcome(returncode=-1, timed_out=True, stderr="ssh timed out")
    except OSError as exc:
        return SshOutcome(returncode=-1, stderr=f"{type(exc).__name__}: {exc}")


def probe_host(ssh_runner: SshRunner, ssh_target: str, connect_timeout: int) -> ProbeResult:
    """Run one probe and turn a failed/timed-out ssh into ``reachable=False``."""
    outcome = ssh_runner(ssh_target, REMOTE_PROBE_SCRIPT, connect_timeout)
    if outcome.timed_out or outcome.returncode != 0:
        reason = "timeout" if outcome.timed_out else f"ssh exit {outcome.returncode}"
        detail = (outcome.stderr or "").strip()[:200]
        return ProbeResult(reachable=False, error=f"{reason}: {detail}" if detail else reason)
    return parse_probe_output(outcome.stdout)


@dataclass
class SentinelConfig:
    """Everything one run needs; built once from CLI args."""

    root: Path
    host: str
    ssh_target: str
    connect_timeout: int = 10
    unreachable_threshold: int = 2
    persist_threshold: int = 2
    dry_run: bool = False
    disk_warn_pct: int = 85
    disk_critical_pct: int = 95
    disk_warn_free_bytes: int = 20 * 1024**3
    disk_critical_free_bytes: int = 5 * 1024**3


@dataclass
class Notification:
    """One alert this run decided to send (or would send, under ``--dry-run``)."""

    level: str
    title: str
    message: str
    dedupe_key: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "title": self.title,
            "message": self.message,
            "dedupe_key": self.dedupe_key,
        }


@dataclass
class SentinelState:
    """Persisted between runs at ``<state_dir>/<host>.state.json``."""

    last_boot_id: str | None = None
    last_seen_at: str | None = None
    consecutive_unreachable: int = 0
    unreachable_alerted: bool = False
    problem_streak: dict[str, int] = field(default_factory=dict)
    alerted_problems: list[str] = field(default_factory=list)
    disk_sample_at: str | None = None
    disk_available_bytes: int | None = None
    disk_missing_streak: int = 0
    disk_alert_level: str = ""
    disk_alert_at: str | None = None
    disk_trend_history: dict[str, Any] = field(default_factory=dict)
    disk_trend: dict[str, Any] = field(default_factory=dict)
    disk_response: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "last_boot_id": self.last_boot_id,
            "last_seen_at": self.last_seen_at,
            "consecutive_unreachable": self.consecutive_unreachable,
            "unreachable_alerted": self.unreachable_alerted,
            "problem_streak": dict(self.problem_streak),
            "alerted_problems": list(self.alerted_problems),
            "disk_sample_at": self.disk_sample_at,
            "disk_available_bytes": self.disk_available_bytes,
            "disk_missing_streak": self.disk_missing_streak,
            "disk_alert_level": self.disk_alert_level,
            "disk_alert_at": self.disk_alert_at,
            "disk_trend_history": self.disk_trend_history,
            "disk_trend": self.disk_trend,
            "disk_response": self.disk_response,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SentinelState":
        return cls(
            last_boot_id=data.get("last_boot_id"),
            last_seen_at=data.get("last_seen_at"),
            consecutive_unreachable=int(data.get("consecutive_unreachable", 0) or 0),
            unreachable_alerted=bool(data.get("unreachable_alerted", False)),
            problem_streak={str(k): int(v) for k, v in (data.get("problem_streak") or {}).items()},
            alerted_problems=list(data.get("alerted_problems") or []),
            disk_sample_at=data.get("disk_sample_at"),
            disk_available_bytes=data.get("disk_available_bytes"),
            disk_missing_streak=int(data.get("disk_missing_streak", 0) or 0),
            disk_alert_level=str(data.get("disk_alert_level", "")),
            disk_alert_at=data.get("disk_alert_at"),
            disk_trend_history=dict(data.get("disk_trend_history") or {}),
            disk_trend=dict(data.get("disk_trend") or {}),
            disk_response=dict(data.get("disk_response") or {}),
        )


@dataclass
class RunResult:
    """What one ``run_sentinel`` call produced, for the CLI and for tests."""

    probe: ProbeResult
    notifications: list[Notification]
    state: SentinelState
    state_written: bool


def state_path(state_dir: Path, host: str) -> Path:
    return state_dir / f"{host}{_STATE_SUFFIX}"


def receipt_path(state_dir: Path, host: str) -> Path:
    return state_dir / f"{host}{_RECEIPT_SUFFIX}"


def load_state(state_dir: Path, host: str) -> SentinelState:
    """Missing or corrupt state is treated as "first run ever", never fatal."""
    path = state_path(state_dir, host)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return SentinelState()
    if not isinstance(raw, dict):
        return SentinelState()
    return SentinelState.from_dict(raw)


def write_state_atomic(state_dir: Path, host: str, state: SentinelState) -> Path:
    """tmp + os.replace so a crash mid-write never corrupts the last-known state."""
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_path(state_dir, host)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state.as_dict(), indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def write_receipt(
    state_dir: Path,
    host: str,
    probe: ProbeResult,
    notifications: Sequence[Notification],
    generated_at: str,
    disk_trend: dict[str, Any] | None = None,
    disk_response: dict[str, Any] | None = None,
) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = receipt_path(state_dir, host)
    receipt = {
        "api_version": "host-health-host-sentinel/v1",
        "generated_at": generated_at,
        "host": host,
        "probe": probe.as_dict(),
        "notifications": [n.as_dict() for n in notifications],
        "disk_trend": disk_trend or {},
        "disk_response": disk_response or {},
    }
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return path


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _minutes_since(last_seen_at: str | None, now: datetime) -> str:
    then = _parse_iso(last_seen_at)
    if then is None:
        return "an unknown number of"
    delta = now - then
    return str(max(0, int(delta.total_seconds() // 60)))


def _problem_keys(probe: ProbeResult) -> set[str]:
    keys: set[str] = set()
    keys.update(f"sys:{unit}" for unit in probe.failed_system)
    keys.update(f"user:{unit}" for unit in probe.failed_user)
    keys.update(f"ctr:{name}" for name in probe.unhealthy_containers)
    return keys


def _digest(keys: Sequence[str]) -> str:
    return hashlib.sha1(",".join(sorted(keys)).encode("utf-8")).hexdigest()[:10]


def _handle_unreachable(config: SentinelConfig, state: SentinelState, now: datetime) -> list[Notification]:
    notifications: list[Notification] = []
    state.consecutive_unreachable += 1
    if state.consecutive_unreachable >= config.unreachable_threshold and not state.unreachable_alerted:
        minutes = _minutes_since(state.last_seen_at, now)
        notifications.append(
            Notification(
                level="critical",
                title=f"{config.host} unreachable",
                message=(
                    f"{config.host} has not responded to {state.consecutive_unreachable} consecutive "
                    f"SSH probes (last confirmed reachable {minutes} minutes ago)."
                ),
                dedupe_key=f"host-sentinel-{config.host}-unreachable",
            )
        )
        state.unreachable_alerted = True
    return notifications


def _handle_boot_change(config: SentinelConfig, state: SentinelState, probe: ProbeResult, now: datetime) -> list[Notification]:
    if not probe.boot_id:
        return []
    if state.last_boot_id is None:
        # First-ever observation: nothing to compare against yet.
        state.last_boot_id = probe.boot_id
        return []
    if probe.boot_id == state.last_boot_id:
        return []

    clean = bool(probe.prev_boot_clean)
    downtime = "an unknown number of"
    if probe.uptime_s is not None:
        boot_time = now - timedelta(seconds=probe.uptime_s)
        downtime = str(max(0, int((now - boot_time).total_seconds() // 60)))
    prev_end = "unknown"
    if probe.prev_boot_last_ts is not None:
        prev_end = datetime.fromtimestamp(probe.prev_boot_last_ts, tz=timezone.utc).astimezone().isoformat(timespec="seconds")

    message = f"Previous boot ended around {prev_end}; host was down for approximately {downtime} minutes."
    if probe.failed_system:
        message += f" Failed system units: {', '.join(probe.failed_system)}."
    if probe.failed_user:
        message += f" Failed user units: {', '.join(probe.failed_user)}."
    if probe.unhealthy_containers:
        message += f" Unhealthy/restarting containers: {', '.join(probe.unhealthy_containers)}."

    notification = Notification(
        level="warning" if clean else "critical",
        title=f"{config.host} rebooted ({'clean' if clean else 'unclean'})",
        message=message,
        dedupe_key=f"host-sentinel-{config.host}-boot-{probe.boot_id[:8]}",
    )
    state.last_boot_id = probe.boot_id
    return [notification]


def _handle_persistent_problems(config: SentinelConfig, state: SentinelState, probe: ProbeResult) -> list[Notification]:
    notifications: list[Notification] = []
    current_keys = _problem_keys(probe)

    newly_persistent: list[str] = []
    for key in sorted(current_keys):
        streak = state.problem_streak.get(key, 0) + 1
        state.problem_streak[key] = streak
        if streak >= config.persist_threshold and key not in state.alerted_problems:
            newly_persistent.append(key)

    recovered: list[str] = []
    for key in list(state.problem_streak.keys()):
        if key not in current_keys:
            del state.problem_streak[key]
            if key in state.alerted_problems:
                state.alerted_problems.remove(key)
                recovered.append(key)

    if newly_persistent:
        for key in newly_persistent:
            if key not in state.alerted_problems:
                state.alerted_problems.append(key)
        keys_sorted = sorted(newly_persistent)
        notifications.append(
            Notification(
                level="warning",
                title=f"{config.host} persistent problem(s)",
                message=(
                    f"Still failing/unhealthy after {config.persist_threshold}+ consecutive checks: "
                    f"{', '.join(keys_sorted)}."
                ),
                dedupe_key=f"host-sentinel-{config.host}-problems-{_digest(keys_sorted)}",
            )
        )

    if recovered:
        keys_sorted = sorted(recovered)
        notifications.append(
            Notification(
                level="info",
                title=f"{config.host} recovered: {', '.join(keys_sorted)}",
                message=f"No longer failing/unhealthy: {', '.join(keys_sorted)}.",
                dedupe_key=f"host-sentinel-{config.host}-recovered-{_digest(keys_sorted)}",
            )
        )

    return notifications


def _handle_disk_pressure(
    config: SentinelConfig, state: SentinelState, probe: ProbeResult, now: datetime
) -> list[Notification]:
    """Warn before exhaustion; escalate immediately and remind every 30 minutes.

    The probe only reads root filesystem metadata. It never removes data or
    stops services. Missing metrics cannot turn an existing incident healthy.
    Growth uses adjacent samples only, avoiding estimates across long outages.
    """
    level = ""
    reasons: list[str] = []

    def flag(severity: str, reason: str) -> None:
        nonlocal level
        if not level or severity == "critical":
            level = severity
        reasons.append(reason)

    total, available = probe.disk_total_bytes, probe.disk_available_bytes
    bytes_valid = total is not None and total > 0 and available is not None and 0 <= available <= total
    pct_valid = probe.disk_pct is not None and 0 <= probe.disk_pct <= 100
    inode_valid = probe.inode_pct is not None and 0 <= probe.inode_pct <= 100
    if pct_valid and probe.disk_pct >= config.disk_warn_pct:
        flag("critical" if probe.disk_pct >= config.disk_critical_pct else "warning", f"root is {probe.disk_pct}% full")
    if inode_valid and probe.inode_pct >= config.disk_warn_pct:
        flag("critical" if probe.inode_pct >= config.disk_critical_pct else "warning", f"root inodes are {probe.inode_pct}% used")
    if bytes_valid:
        state.disk_trend_history, state.disk_trend = observe_disk_trend(
            state.disk_trend_history, now=now.timestamp(), total=total, available=available,
        )
        if state.disk_trend["active"]:
            rate = state.disk_trend["recent_percentage_points_per_day"]
            remaining = state.disk_trend["projected_hours_to_exhaustion"]
            if rate is None:
                flag("warning", "previous growth incident awaiting fresh trend samples")
            else:
                baseline = state.disk_trend["baseline_bytes_per_day"]
                baseline_text = f"{baseline / total * 100:.2f} points/day" if baseline is not None else "learning"
                flag(state.disk_trend["level"], f"sustained growth {rate:.2f} capacity points/day; normal baseline {baseline_text}; projected exhaustion in {remaining / 24:.1f} days")
        if available <= config.disk_warn_free_bytes:
            flag("critical" if available <= config.disk_critical_free_bytes else "warning", f"only {available / 1024**3:.1f} GiB available")
        previous = _parse_iso(state.disk_sample_at)
        elapsed = (now - previous).total_seconds() if previous else 0
        if 60 <= elapsed <= 1800 and state.disk_available_bytes is not None:
            consumed = state.disk_available_bytes - available
            rate = consumed / elapsed
            if rate > 0:
                remaining_hours = available / rate / 3600
                if rate >= 2 * 1024**3 / 60 or (pct_valid and probe.disk_pct >= 70 and remaining_hours <= 6):
                    flag("critical" if remaining_hours <= 1 else "warning", f"free space falling {rate * 60 / 1024**3:.2f} GiB/min; about {remaining_hours:.1f} hours remaining at this rate")
        state.disk_sample_at = _iso(now)
        state.disk_available_bytes = available
    complete = bytes_valid and pct_valid and inode_valid
    state.disk_missing_streak = 0 if complete else state.disk_missing_streak + 1
    if not complete:
        if state.disk_missing_streak >= config.persist_threshold:
            flag("critical" if state.disk_alert_level == "critical" else "warning", "disk/inode telemetry missing or invalid")
        if not level:
            return []

    if not level and state.disk_alert_level:
        state.disk_alert_level = ""
        state.disk_alert_at = _iso(now)
        return [Notification("info", f"{config.host} disk pressure cleared", f"Root {probe.disk_pct}% used; {available / 1024**3:.1f} GiB available; inodes {probe.inode_pct}% used.", f"host-sentinel-{config.host}-disk-recovered")]
    if not level:
        return []
    last_alert = _parse_iso(state.disk_alert_at)
    if level == state.disk_alert_level and last_alert and (now - last_alert).total_seconds() < 1800:
        return []
    state.disk_alert_level = level
    state.disk_alert_at = _iso(now)
    return [Notification(level, f"{config.host} disk pressure", "; ".join(reasons) + ". Inspect disk writers and retention; no automatic deletion performed.", f"host-sentinel-{config.host}-disk-{level}")]


def _bound_launchd_logs(state_dir: Path, host: str) -> None:
    """Keep at most one 1 MiB archive per launchd stream between cycles."""
    for stream in ("out", "err"):
        path = state_dir / f"{host}.launchd.{stream}.log"
        try:
            if path.exists() and path.stat().st_size > 1024**2:
                path.replace(path.with_suffix(".log.1"))
        except OSError as exc:
            sys.stderr.write(f"host-sentinel: cannot rotate {stream} log: {type(exc).__name__}\n")


def run_sentinel(
    config: SentinelConfig,
    *,
    ssh_runner: SshRunner,
    notifier: Notifier,
    clock: Clock,
    state_dir: Path,
    diagnostic_runner: SshRunner | None = None,
) -> RunResult:
    """One sentinel cycle: probe, compare against state, decide, notify, persist.

    All side effects (notifying, writing state/receipt) are skipped when
    ``config.dry_run`` is set -- the caller only wants to see what *would*
    happen, which is why this function is the single place that gates on it
    rather than every helper checking it individually.
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    state = load_state(state_dir, config.host)
    previous_disk_alert = (state.disk_alert_level, state.disk_alert_at)
    now = clock()
    now_iso = _iso(now)

    probe = probe_host(ssh_runner, config.ssh_target, config.connect_timeout)
    notifications: list[Notification] = []

    if not probe.reachable:
        notifications.extend(_handle_unreachable(config, state, now))
    else:
        if state.unreachable_alerted:
            minutes = _minutes_since(state.last_seen_at, now)
            notifications.append(
                Notification(
                    level="info",
                    title=f"{config.host} reachable again",
                    message=f"{config.host} is responding again after an outage of approximately {minutes} minutes.",
                    dedupe_key=f"host-sentinel-{config.host}-reachable",
                )
            )
        state.consecutive_unreachable = 0
        state.unreachable_alerted = False

        notifications.extend(_handle_boot_change(config, state, probe, now))
        notifications.extend(_handle_persistent_problems(config, state, probe))
        notifications.extend(_handle_disk_pressure(config, state, probe, now))

        state.last_seen_at = now_iso

    if not config.dry_run:
        _bound_launchd_logs(state_dir, config.host)
        for note in notifications:
            delivered = _deliver(notifier, config, note)
            if not delivered and note.dedupe_key.startswith(f"host-sentinel-{config.host}-disk-"):
                # Do not suppress a retry merely because delivery was attempted.
                state.disk_alert_level, state.disk_alert_at = previous_disk_alert
            if not delivered and note.dedupe_key == f"host-sentinel-{config.host}-unreachable":
                state.unreachable_alerted = False
        disk_incident = any(n.level in {"warning", "critical"} and n.dedupe_key.startswith(f"host-sentinel-{config.host}-disk-") for n in notifications)
        last_capture = _parse_iso(state.disk_response.get("generated_at"))
        if probe.reachable and disk_incident and diagnostic_runner is not None and (last_capture is None or (now - last_capture).total_seconds() >= 3600):
            try:
                state.disk_response = capture_disk_diagnostics(
                    state_dir=state_dir, host=config.host, ssh_target=config.ssh_target,
                    runner=diagnostic_runner, connect_timeout=config.connect_timeout,
                    generated_at=now_iso,
                )
            except Exception as exc:  # Persist monitoring even if diagnostics fail.
                state.disk_response = {"generated_at": now_iso, "status": "capture_failed", "error_type": type(exc).__name__}
        write_state_atomic(state_dir, config.host, state)
        write_receipt(state_dir, config.host, probe, notifications, now_iso, state.disk_trend, state.disk_response)

    return RunResult(probe=probe, notifications=notifications, state=state, state_written=not config.dry_run)


def _deliver(notifier: Notifier, config: SentinelConfig, note: Notification) -> bool:
    """Notify failures are logged, never fatal -- a broken notifier must not stop state from being recorded."""
    try:
        notifier(config, note)
        return True
    except Exception as exc:  # noqa: BLE001 - best-effort delivery, never crash the run
        sys.stderr.write(f"agentic-os-host-sentinel: notify failed for '{note.dedupe_key}': {exc}\n")
        return False


def notify_via_agentic_os_notify(config: SentinelConfig, note: Notification) -> None:
    """The real ``Notifier``: shells out to the one governed delivery seam."""
    notify_bin = config.root / "harness" / "bin" / "agentic-os-notify"
    cmd = [
        sys.executable,
        str(notify_bin),
        "--source",
        "runtime.host_sentinel",
        "--level",
        note.level,
        "--title",
        note.title,
        "--message",
        note.message,
        "--dedupe-key",
        note.dedupe_key,
    ]
    env = dict(os.environ)
    env["AGENTIC_OS_ROOT"] = str(config.root)
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"agentic-os-notify exited {result.returncode}")
