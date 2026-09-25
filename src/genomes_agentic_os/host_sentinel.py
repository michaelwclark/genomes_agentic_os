"""Off-box sentinel that watches another host for outages and unclean reboots.

A primary server host died uncleanly twice within 24 hours (2026-09-21, 2026-09-22, down
~4h45m) and nobody was alerted -- systemd units stayed failed for ~19h after
the reboot before anyone noticed. The existing tools do not cover this gap:

* ``agentic-os-notify`` is the delivery seam, but nothing was watching the
  host to call it.
* ``agentic-os-monitor`` is an interactive curses TUI, not a scheduled job.
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

    def as_dict(self) -> dict[str, Any]:
        return {
            "last_boot_id": self.last_boot_id,
            "last_seen_at": self.last_seen_at,
            "consecutive_unreachable": self.consecutive_unreachable,
            "unreachable_alerted": self.unreachable_alerted,
            "problem_streak": dict(self.problem_streak),
            "alerted_problems": list(self.alerted_problems),
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
) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = receipt_path(state_dir, host)
    receipt = {
        "api_version": "host-health-host-sentinel/v1",
        "generated_at": generated_at,
        "host": host,
        "probe": probe.as_dict(),
        "notifications": [n.as_dict() for n in notifications],
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


def run_sentinel(
    config: SentinelConfig,
    *,
    ssh_runner: SshRunner,
    notifier: Notifier,
    clock: Clock,
    state_dir: Path,
) -> RunResult:
    """One sentinel cycle: probe, compare against state, decide, notify, persist.

    All side effects (notifying, writing state/receipt) are skipped when
    ``config.dry_run`` is set -- the caller only wants to see what *would*
    happen, which is why this function is the single place that gates on it
    rather than every helper checking it individually.
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    state = load_state(state_dir, config.host)
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

        state.last_seen_at = now_iso

    if not config.dry_run:
        for note in notifications:
            _deliver(notifier, config, note)
        write_state_atomic(state_dir, config.host, state)
        write_receipt(state_dir, config.host, probe, notifications, now_iso)

    return RunResult(probe=probe, notifications=notifications, state=state, state_written=not config.dry_run)


def _deliver(notifier: Notifier, config: SentinelConfig, note: Notification) -> None:
    """Notify failures are logged, never fatal -- a broken notifier must not stop state from being recorded."""
    try:
        notifier(config, note)
    except Exception as exc:  # noqa: BLE001 - best-effort delivery, never crash the run
        sys.stderr.write(f"agentic-os-host-sentinel: notify failed for '{note.dedupe_key}': {exc}\n")


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
    subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
