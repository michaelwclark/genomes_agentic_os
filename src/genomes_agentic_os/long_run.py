"""Durable control plane for commands expected to run longer than two minutes."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import select
import shlex
import signal
import subprocess
import sys
import time
from typing import Any, Iterator

import yaml

from .long_running import MutationLock, atomic_json
from .scaffold import expand_path


REGISTRY_SCHEMA = "agentic-os-long-running-registry/v1"
STATE_SCHEMA = "agentic-os-long-running-state/v1"
TERMINAL_SCHEMA = "agentic-os-long-running-terminal/v1"
REGISTRY_RELATIVE = Path("harness/shared_factory/00-control-plane/long-running-runs.json")
DEFAULT_RUN_ROOT = Path("harness/shared_factory/06-runs-and-logs/async-runs")
CONFIG_RELATIVE = Path("harness/config/long-running-execution.yml")
TERMINAL_STATUSES = {
    "success",
    "failure",
    "timeout",
    "no-progress-timeout",
    "resource-budget-exceeded",
    "cancelled",
    "interrupted",
    "error",
    "stale",
}
ACTIVE_STATUSES = {"queued", "preflight", "running", "paused", "cancelling"}
MUTATING_KINDS = {
    "install",
    "sync",
    "import",
    "export",
    "backfill",
    "cleanup",
    "deployment",
    "migration",
}
SECRET_FLAG = re.compile(r"^--?(?:api[-_]?key|auth|password|secret|token)(?:=|$)", re.I)


class LongRunError(ValueError):
    """Raised when a run would violate the long-running execution contract."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value.strip().lower()).strip("-")
    return cleaned[:48] or "long-run"


def _root(root: str | Path) -> Path:
    return expand_path(root)


def registry_path(root: str | Path) -> Path:
    return _root(root) / REGISTRY_RELATIVE


def _config(root: str | Path) -> dict[str, Any]:
    path = _root(root) / CONFIG_RELATIVE
    if not path.is_file():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return loaded.get("long_running_execution", loaded) if isinstance(loaded, dict) else {}


def _process_alive(pid: object) -> bool:
    try:
        value = int(pid)
        if value <= 0:
            return False
        os.kill(value, 0)
    except (TypeError, ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True
    return True


def _atomic_state(run_dir: Path, changes: dict[str, Any]) -> dict[str, Any]:
    path = run_dir / "state.json"
    current = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    current.update(changes)
    current["updated_at"] = utc_now()
    atomic_json(path, current)
    return current


def _append_event(run_dir: Path, event: str, **fields: Any) -> None:
    payload = {"at": utc_now(), "event": event, **fields}
    path = run_dir / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def _registry_lock(path: Path) -> Iterator[None]:
    lock = path.with_name(".long-running-runs.lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a+", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def read_registry(root: str | Path) -> dict[str, Any]:
    path = registry_path(root)
    if not path.is_file():
        return {"schema": REGISTRY_SCHEMA, "updated_at": utc_now(), "runs": []}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if loaded.get("schema") != REGISTRY_SCHEMA or not isinstance(loaded.get("runs"), list):
        raise LongRunError(f"invalid long-running registry: {path}")
    return loaded


def _registry_entry(state: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "id",
        "kind",
        "label",
        "status",
        "phase",
        "created_at",
        "started_at",
        "updated_at",
        "finished_at",
        "last_progress_at",
        "pid",
        "monitor_pid",
        "run_dir",
        "work_dir",
        "exit_code",
        "terminal_reason",
        "items_completed",
        "items_total",
        "files_completed",
        "files_total",
        "bytes_completed",
        "bytes_total",
        "output_bytes",
        "log_rotations",
        "checkpoint_strategy",
        "mutation_lock",
        "terminal_receipt",
    )
    return {key: state[key] for key in fields if key in state}


def update_registry(root: str | Path, state: dict[str, Any]) -> None:
    path = registry_path(root)
    with _registry_lock(path):
        registry = read_registry(root)
        entry = _registry_entry(state)
        rows = [row for row in registry["runs"] if row.get("id") != entry.get("id")]
        rows.append(entry)
        rows.sort(key=lambda row: (str(row.get("created_at") or ""), str(row.get("id") or "")))
        registry.update({"updated_at": utc_now(), "runs": rows})
        atomic_json(path, registry)


def _write_state(root: str | Path, run_dir: Path, changes: dict[str, Any]) -> dict[str, Any]:
    state = _atomic_state(run_dir, changes)
    update_registry(root, state)
    return state


def _validate_command(command: list[str]) -> None:
    if not command:
        raise LongRunError("command required after --")
    for index, arg in enumerate(command):
        if SECRET_FLAG.match(arg) and ("=" in arg or index + 1 < len(command)):
            raise LongRunError("secret-looking command argument refused; pass credentials through the environment")


def _command_display(command: list[str], shell: bool) -> str:
    return " ".join(command) if shell else shlex.join(command)


def _generated_id(root: Path, label: str) -> str:
    config = root / "harness/config/artifact-naming.yml"
    date_format, separator, enabled = "%m%d%y", "-", True
    if config.is_file():
        loaded = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
        prefix = (loaded.get("artifact_naming") or {}).get("date_prefix") or {}
        enabled = bool(prefix.get("enabled", True)) and bool((prefix.get("scopes") or {}).get("async_runs", True))
        date_format = str(prefix.get("format") or date_format)
        separator = str(prefix.get("separator") or separator)
    current = datetime.now(timezone.utc)
    suffix = f"{current.strftime('%H%M%S')}-{_slug(label)}"
    return f"{current.strftime(date_format)}{separator}{suffix}" if enabled else suffix


def _resolve_run_root(root: Path, artifact_dir: str | None) -> Path:
    if artifact_dir:
        base = Path(artifact_dir).expanduser()
        return base if base.name == "async-runs" else base / "async-runs"
    active = os.environ.get("AGENTIC_OS_ACTIVE_WORK_ITEM")
    if active:
        return Path(active).expanduser() / "artifacts/async-runs"
    return root / DEFAULT_RUN_ROOT


def _effective_budgets(root: Path, supplied: dict[str, Any]) -> dict[str, Any]:
    defaults = (_config(root).get("budgets") or {}) if isinstance(_config(root), dict) else {}

    def value(name: str, fallback: int | float) -> Any:
        if supplied.get(name) is not None:
            return supplied[name]
        if defaults.get(name) is not None:
            return defaults[name]
        return fallback

    values = {
        "wall_clock_minutes": value("wall_clock_minutes", 60),
        "no_progress_minutes": value("no_progress_minutes", 15),
        "max_log_mb": value("max_log_mb", 25),
        "log_rotations": value("log_rotations", 4),
        "max_cpu_percent": value("max_cpu_percent", 400),
        "max_rss_mb": value("max_rss_mb", 4096),
        "resource_violation_samples": value("resource_violation_samples", 3),
        "sample_seconds": value("sample_seconds", 2),
    }
    if any(float(values[key]) <= 0 for key in values):
        raise LongRunError("all long-running budgets must be positive")
    return values


def start_run(
    root: str | Path,
    *,
    command: list[str],
    label: str,
    kind: str = "command",
    artifact_dir: str | None = None,
    run_id: str | None = None,
    work_dir: str | None = None,
    shell: bool = False,
    budgets: dict[str, Any] | None = None,
    progress_file: str | None = None,
    checkpoint_strategy: str | None = None,
    mutation_lock: str | None = None,
    preflight_checks: list[str] | None = None,
    post_run_checks: list[str] | None = None,
    collateral_processes: list[str] | None = None,
    environment_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    _validate_command(command)
    os_root = _root(root)
    preflight = list(preflight_checks or [])
    post_checks = list(post_run_checks or [])
    config = _config(os_root)
    mutating_kinds = set(config.get("mutating_kinds") or MUTATING_KINDS)
    high_risk_kinds = set(
        config.get("high_risk_kinds") or {"migration", "backfill", "cleanup", "import", "export"}
    )
    if kind in mutating_kinds and not checkpoint_strategy:
        raise LongRunError(f"{kind} runs require --checkpoint-strategy")
    if kind in high_risk_kinds and not preflight:
        raise LongRunError(
            f"{kind} runs require a --preflight-check that records complexity and performance evidence"
        )
    if kind in mutating_kinds and not (mutation_lock or post_checks):
        raise LongRunError(f"{kind} runs require --mutation-lock or --post-run-check")
    safe_environment = dict(environment_overrides or {})
    if any(re.search(r"(?:TOKEN|SECRET|PASSWORD|API_KEY|AUTH)", key, re.I) for key in safe_environment):
        raise LongRunError("secret-looking environment override refused; inherit credentials from the monitor environment")

    effective = _effective_budgets(os_root, budgets or {})
    async_root = _resolve_run_root(os_root, artifact_dir)
    base_identifier = run_id or _generated_id(os_root, label)
    identifier = base_identifier
    run_dir = async_root / identifier
    if run_id:
        run_dir.mkdir(parents=True, exist_ok=False)
    else:
        suffix = 2
        while True:
            try:
                run_dir.mkdir(parents=True, exist_ok=False)
                break
            except FileExistsError:
                identifier = f"{base_identifier}-{suffix}"
                run_dir = async_root / identifier
                suffix += 1
    created = utc_now()
    configured_collateral = _config(os_root).get("collateral_processes") or []
    payload = {
        "schema": STATE_SCHEMA,
        "id": identifier,
        "label": label,
        "kind": kind,
        "command": command,
        "command_display": _command_display(command, shell),
        "shell": shell,
        "root": str(os_root),
        "run_dir": str(run_dir),
        "work_dir": str(Path(work_dir or os.getcwd()).expanduser().resolve()),
        "created_at": created,
        "budgets": effective,
        "progress_file": str(Path(progress_file).expanduser().resolve()) if progress_file else None,
        "checkpoint_strategy": checkpoint_strategy or "restart-from-command-receipt",
        "mutation_lock": mutation_lock,
        "preflight_checks": preflight,
        "post_run_checks": post_checks,
        "collateral_processes": list(collateral_processes or configured_collateral),
        "environment_overrides": safe_environment,
    }
    atomic_json(run_dir / "command.json", payload)
    state = {
        "schema": STATE_SCHEMA,
        "id": identifier,
        "label": label,
        "kind": kind,
        "status": "queued",
        "phase": "queued",
        "created_at": created,
        "updated_at": created,
        "last_progress_at": created,
        "run_dir": str(run_dir),
        "root": str(os_root),
        "work_dir": payload["work_dir"],
        "checkpoint_strategy": payload["checkpoint_strategy"],
        "mutation_lock": mutation_lock,
        "items_completed": 0,
        "items_total": 0,
        "files_completed": 0,
        "files_total": 0,
        "bytes_completed": 0,
        "bytes_total": 0,
        "output_bytes": 0,
        "log_rotations": 0,
    }
    atomic_json(run_dir / "state.json", state)
    update_registry(os_root, state)
    _append_event(run_dir, "queued", kind=kind, label=label)

    monitor = subprocess.Popen(
        [sys.executable, "-m", "genomes_agentic_os.cli", "long-run", "_monitor", str(run_dir)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    state = _write_state(os_root, run_dir, {"monitor_pid": monitor.pid})
    _append_event(run_dir, "monitor-started", monitor_pid=monitor.pid)
    return state


class _BoundedLog:
    def __init__(self, path: Path, *, max_bytes: int, rotations: int) -> None:
        self.path = path
        self.max_bytes = max_bytes
        self.rotations = rotations
        self.size = path.stat().st_size if path.exists() else 0
        self.rotation_count = 0
        self.stream = path.open("ab")

    def _rotate(self) -> None:
        self.stream.close()
        oldest = self.path.with_name(f"{self.path.name}.{self.rotations}")
        oldest.unlink(missing_ok=True)
        for index in range(self.rotations - 1, 0, -1):
            source = self.path.with_name(f"{self.path.name}.{index}")
            if source.exists():
                source.replace(self.path.with_name(f"{self.path.name}.{index + 1}"))
        if self.path.exists():
            self.path.replace(self.path.with_name(f"{self.path.name}.1"))
        self.stream = self.path.open("ab")
        self.size = 0
        self.rotation_count += 1

    def write(self, chunk: bytes) -> None:
        while chunk:
            if self.size >= self.max_bytes:
                self._rotate()
            available = self.max_bytes - self.size
            part, chunk = chunk[:available], chunk[available:]
            self.stream.write(part)
            self.stream.flush()
            self.size += len(part)

    def close(self) -> None:
        self.stream.close()


def _sample_process(pid: int) -> dict[str, Any]:
    result = subprocess.run(
        ["ps", "-axo", "pid=,pgid=,%cpu=,rss="],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    cpu, rss, processes = 0.0, 0.0, 0
    for line in result.stdout.splitlines():
        values = line.split()
        if len(values) < 4 or int(values[1]) != pid:
            continue
        cpu += float(values[2])
        rss += float(values[3]) / 1024
        processes += 1
    return {
        "cpu_percent": cpu,
        "rss_mb": rss,
        "process_count": processes,
    }


def _sample_collateral(specs: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in specs:
        try:
            name, cpu_text, rss_text = spec.split(":", 2)
            result = subprocess.run(
                ["ps", "-axo", "comm=,%cpu=,rss="], text=True, capture_output=True, timeout=5, check=False
            )
            cpu, rss = 0.0, 0.0
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 3 and Path(parts[0]).name == name:
                    cpu += float(parts[-2])
                    rss += float(parts[-1]) / 1024
            rows.append(
                {
                    "name": name,
                    "cpu_percent": cpu,
                    "rss_mb": rss,
                    "max_cpu_percent": float(cpu_text),
                    "max_rss_mb": float(rss_text),
                    "exceeded": cpu > float(cpu_text) or rss > float(rss_text),
                }
            )
        except (ValueError, IndexError):
            rows.append({"name": spec, "exceeded": True, "error": "expected name:max_cpu_percent:max_rss_mb"})
    return rows


def _terminate_group(process: subprocess.Popen[bytes], *, grace_seconds: int = 20) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=grace_seconds)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _run_checks(checks: list[str], *, work_dir: str, phase: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for command in checks:
        started = time.monotonic()
        try:
            result = subprocess.run(
                command,
                cwd=work_dir,
                shell=True,
                text=True,
                capture_output=True,
                timeout=120,
                check=False,
            )
            results.append(
                {
                    "phase": phase,
                    "command": command,
                    "exit_code": result.returncode,
                    "ok": result.returncode == 0,
                    "duration_seconds": round(time.monotonic() - started, 3),
                    "output_tail": (result.stdout + result.stderr)[-2000:],
                }
            )
        except subprocess.TimeoutExpired:
            results.append({"phase": phase, "command": command, "ok": False, "error": "timed out after 120 seconds"})
    return results


def _progress_from_file(path: str | None) -> dict[str, Any]:
    if not path or not Path(path).is_file():
        return {}
    try:
        loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    allowed = {
        "phase",
        "items_completed",
        "items_total",
        "files_completed",
        "files_total",
        "bytes_completed",
        "bytes_total",
        "current_path",
        "last_semantic_progress_at",
    }
    return {key: loaded[key] for key in allowed if key in loaded}


def monitor_run(run_dir_value: str | Path) -> int:
    run_dir = Path(run_dir_value).expanduser()
    command = json.loads((run_dir / "command.json").read_text(encoding="utf-8"))
    root = Path(command["root"])
    budgets = command["budgets"]
    interrupted: list[int] = []

    def handle_signal(signum: int, _frame: Any) -> None:
        interrupted.append(signum)

    prior = {number: signal.signal(number, handle_signal) for number in (signal.SIGINT, signal.SIGTERM)}

    def restore_signal_handlers() -> None:
        for number, handler in prior.items():
            signal.signal(number, handler)

    _write_state(root, run_dir, {"status": "preflight", "phase": "preflight", "started_at": utc_now()})
    preflight = _run_checks(command.get("preflight_checks") or [], work_dir=command["work_dir"], phase="preflight")
    atomic_json(run_dir / "preflight.json", {"checks": preflight, "ok": all(row["ok"] for row in preflight)})
    if interrupted:
        signalled_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        cancelled = signalled_state.get("status") == "cancelling"
        result = _terminal(
            root,
            run_dir,
            command,
            status="cancelled" if cancelled else "interrupted",
            exit_code=None,
            reason=(
                "operator-cancelled-during-preflight"
                if cancelled
                else f"monitor-received-{signal.Signals(interrupted[-1]).name}-during-preflight"
            ),
            checks=preflight,
        )
        restore_signal_handlers()
        return result
    if any(not row["ok"] for row in preflight):
        result = _terminal(root, run_dir, command, status="failure", exit_code=None, reason="preflight-check-failed", checks=preflight)
        restore_signal_handlers()
        return result

    lock: MutationLock | None = None
    if command.get("mutation_lock"):
        lock_path = Path(command["mutation_lock"]).expanduser()
        if not lock_path.is_absolute():
            lock_path = root / "harness/shared_factory/00-control-plane/locks" / lock_path
        lock = MutationLock(lock_path, run_id=command["id"], operation=command["kind"])
        try:
            lock.acquire()
        except BaseException as exc:
            result = _terminal(
                root,
                run_dir,
                command,
                status="error",
                exit_code=None,
                reason=f"mutation-lock-acquire-failed: {type(exc).__name__}: {exc}",
                checks=preflight,
            )
            restore_signal_handlers()
            return result
    process: subprocess.Popen[bytes] | None = None
    logger = _BoundedLog(
        run_dir / "output.log",
        max_bytes=int(float(budgets["max_log_mb"]) * 1024 * 1024),
        rotations=int(budgets["log_rotations"]),
    )
    try:
        process = subprocess.Popen(
            command["command_display"] if command.get("shell") else command["command"],
            cwd=command["work_dir"],
            shell=bool(command.get("shell")),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            bufsize=0,
            env={**os.environ, **command.get("environment_overrides", {})},
        )
        assert process.stdout is not None
        os.set_blocking(process.stdout.fileno(), False)
        started_monotonic = time.monotonic()
        last_progress = started_monotonic
        last_progress_at = utc_now()
        last_sample = 0.0
        output_bytes = 0
        violations = 0
        resource_peak = {"cpu_percent": 0.0, "rss_mb": 0.0, "process_count": 0}
        progress_signature: str | None = None
        _write_state(
            root,
            run_dir,
            {
                "status": "running",
                "phase": "execute",
                "pid": process.pid,
                "last_progress_at": utc_now(),
                "output_log": str(run_dir / "output.log"),
            },
        )
        _append_event(run_dir, "started", pid=process.pid)
        terminal_status, terminal_reason = "error", "monitor-ended-without-status"
        while True:
            if interrupted:
                signalled_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
                if signalled_state.get("status") == "cancelling":
                    terminal_status, terminal_reason = "cancelled", "operator-cancelled"
                else:
                    terminal_status, terminal_reason = "interrupted", f"monitor-received-{signal.Signals(interrupted[-1]).name}"
                _terminate_group(
                    process,
                    grace_seconds=int(signalled_state.get("cancel_grace_seconds") or 20),
                )
                break
            readable, _, _ = select.select([process.stdout], [], [], 0.5)
            if readable:
                try:
                    chunk = os.read(process.stdout.fileno(), 65536)
                except BlockingIOError:
                    chunk = b""
                if chunk:
                    logger.write(chunk)
                    output_bytes += len(chunk)
                    last_progress = time.monotonic()
                    last_progress_at = utc_now()
            progress = _progress_from_file(command.get("progress_file"))
            if progress:
                signature = json.dumps(progress, sort_keys=True)
                if signature != progress_signature:
                    progress_signature = signature
                    last_progress_at = progress.pop("last_semantic_progress_at", utc_now())
                    progress["last_progress_at"] = last_progress_at
                    last_progress = time.monotonic()
            current = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            if current.get("status") == "paused":
                last_progress = time.monotonic()
            if current.get("status") in {"cancelling", "cancelled"}:
                terminal_status, terminal_reason = "cancelled", "operator-cancelled"
                _terminate_group(
                    process,
                    grace_seconds=int(current.get("cancel_grace_seconds") or 20),
                )
                break
            elapsed = time.monotonic() - started_monotonic
            if elapsed > float(budgets["wall_clock_minutes"]) * 60:
                terminal_status, terminal_reason = "timeout", "wall-clock-budget-exceeded"
                _terminate_group(process)
                break
            if time.monotonic() - last_progress > float(budgets["no_progress_minutes"]) * 60:
                terminal_status, terminal_reason = "no-progress-timeout", "no-progress-watchdog-fired"
                _terminate_group(process)
                break
            if time.monotonic() - last_sample >= float(budgets["sample_seconds"]):
                sample = _sample_process(process.pid)
                resource_peak = {
                    "cpu_percent": max(float(resource_peak["cpu_percent"]), float(sample.get("cpu_percent", 0))),
                    "rss_mb": max(float(resource_peak["rss_mb"]), float(sample.get("rss_mb", 0))),
                    "process_count": max(int(resource_peak["process_count"]), int(sample.get("process_count", 0))),
                }
                collateral = _sample_collateral(command.get("collateral_processes") or [])
                exceeded = (
                    sample.get("cpu_percent", 0) > float(budgets["max_cpu_percent"])
                    or sample.get("rss_mb", 0) > float(budgets["max_rss_mb"])
                    or any(row.get("exceeded") for row in collateral)
                )
                violations = violations + 1 if exceeded else 0
                state_changes = {
                    "output_bytes": output_bytes,
                    "log_rotations": logger.rotation_count,
                    "last_progress_at": last_progress_at,
                    "resource_sample": sample,
                    "resource_peak": resource_peak,
                    "collateral_samples": collateral,
                    **progress,
                }
                _write_state(root, run_dir, state_changes)
                last_sample = time.monotonic()
                if violations >= int(budgets["resource_violation_samples"]):
                    terminal_status, terminal_reason = "resource-budget-exceeded", "resource-budget-watchdog-fired"
                    _terminate_group(process)
                    break
            exit_code = process.poll()
            if exit_code is not None:
                while True:
                    try:
                        chunk = os.read(process.stdout.fileno(), 65536)
                    except BlockingIOError:
                        chunk = b""
                    if not chunk:
                        break
                    logger.write(chunk)
                    output_bytes += len(chunk)
                terminal_status = "success" if exit_code == 0 else "failure"
                terminal_reason = "command-exited"
                break

        exit_code = process.poll()
        post_checks = _run_checks(command.get("post_run_checks") or [], work_dir=command["work_dir"], phase="post-run")
        if terminal_status == "success" and any(not row["ok"] for row in post_checks):
            terminal_status, terminal_reason = "failure", "post-run-invariant-failed"
        return _terminal(
            root,
            run_dir,
            command,
            status=terminal_status,
            exit_code=exit_code,
            reason=terminal_reason,
            checks=[*preflight, *post_checks],
            extra={"output_bytes": output_bytes, "log_rotations": logger.rotation_count},
        )
    except BaseException as exc:
        if process is not None:
            _terminate_group(process)
        return _terminal(root, run_dir, command, status="error", exit_code=None, reason=f"{type(exc).__name__}: {exc}", checks=preflight)
    finally:
        logger.close()
        if lock is not None:
            lock.release()
        restore_signal_handlers()


def _terminal(
    root: Path,
    run_dir: Path,
    command: dict[str, Any],
    *,
    status: str,
    exit_code: int | None,
    reason: str,
    checks: list[dict[str, Any]],
    extra: dict[str, Any] | None = None,
) -> int:
    finished = utc_now()
    prior_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    progress_fields = (
        "phase",
        "items_completed",
        "items_total",
        "files_completed",
        "files_total",
        "bytes_completed",
        "bytes_total",
        "current_path",
        "last_progress_at",
    )
    receipt = {
        "schema": TERMINAL_SCHEMA,
        "id": command["id"],
        "kind": command["kind"],
        "label": command["label"],
        "status": status,
        "exit_code": exit_code,
        "reason": reason,
        "created_at": command["created_at"],
        "finished_at": finished,
        "checkpoint_strategy": command["checkpoint_strategy"],
        "budgets": command.get("budgets") or {},
        "progress": {key: prior_state[key] for key in progress_fields if key in prior_state},
        "resource_sample": prior_state.get("resource_sample") or {},
        "resource_peak": prior_state.get("resource_peak") or {},
        "collateral_samples": prior_state.get("collateral_samples") or [],
        "checks": checks,
        "post_run_invariants_ok": all(row.get("ok") for row in checks if row.get("phase") == "post-run"),
        "run_dir": str(run_dir),
        **(extra or {}),
    }
    terminal_path = run_dir / "terminal-receipt.json"
    atomic_json(terminal_path, receipt)
    state = _write_state(
        root,
        run_dir,
        {
            "status": status,
            "phase": "terminal",
            "finished_at": finished,
            "exit_code": exit_code,
            "terminal_reason": reason,
            "terminal_receipt": str(terminal_path),
            **(extra or {}),
        },
    )
    _append_event(run_dir, "terminal", status=status, exit_code=exit_code, reason=reason)
    _write_summary(run_dir, command, state)
    return 0


def _write_summary(run_dir: Path, command: dict[str, Any], state: dict[str, Any]) -> None:
    lines = [
        f"# {command['label']}",
        "",
        f"Status: {state['status']}",
        f"Kind: {command['kind']}",
        f"Phase: {state.get('phase')}",
        f"Updated: {state.get('updated_at')}",
        f"Exit code: {state.get('exit_code')}",
        f"Reason: {state.get('terminal_reason', '')}",
        f"Command: `{command['command_display']}`",
        f"Checkpoint/restart strategy: {command['checkpoint_strategy']}",
        f"State: `{run_dir / 'state.json'}`",
        f"Terminal receipt: `{run_dir / 'terminal-receipt.json'}`",
        f"Bounded log: `{run_dir / 'output.log'}`",
    ]
    (run_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def status_for_run(run_dir: str | Path) -> dict[str, Any]:
    path = Path(run_dir).expanduser() / "state.json"
    if not path.is_file():
        raise LongRunError(f"run state not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def control_run(run_dir: str | Path, action: str, *, grace_seconds: int = 20) -> dict[str, Any]:
    directory = Path(run_dir).expanduser()
    state = status_for_run(directory)
    worker_pid = state.get("pid")
    monitor_pid = state.get("monitor_pid")
    target_pid = worker_pid if _process_alive(worker_pid) else monitor_pid
    if not _process_alive(target_pid):
        raise LongRunError("run process is not alive; use recover --mark-stale")
    if action == "pause":
        os.killpg(int(target_pid), signal.SIGSTOP)
        next_status, event = "paused", "paused"
    elif action == "resume":
        os.killpg(int(target_pid), signal.SIGCONT)
        next_status, event = "running", "resumed"
    elif action == "cancel":
        command = json.loads((directory / "command.json").read_text(encoding="utf-8"))
        changed = _write_state(
            command["root"],
            directory,
            {
                "status": "cancelling",
                "last_progress_at": utc_now(),
                "cancel_grace_seconds": max(1, grace_seconds),
            },
        )
        os.killpg(int(target_pid), signal.SIGTERM)
        _append_event(directory, "cancel-requested", grace_seconds=grace_seconds)
        return changed
    else:
        raise LongRunError(f"unknown control action: {action}")
    command = json.loads((directory / "command.json").read_text(encoding="utf-8"))
    changed = _write_state(command["root"], directory, {"status": next_status, "last_progress_at": utc_now()})
    _append_event(directory, event)
    return changed


def recover_runs(root: str | Path, *, mark_stale: bool = False) -> dict[str, Any]:
    registry = read_registry(root)
    reports: list[dict[str, Any]] = []
    for entry in registry["runs"]:
        if entry.get("status") not in ACTIVE_STATUSES:
            continue
        worker_live = _process_alive(entry.get("pid"))
        monitor_live = _process_alive(entry.get("monitor_pid"))
        stale = not worker_live and not monitor_live
        report = {"id": entry.get("id"), "run_dir": entry.get("run_dir"), "stale": stale, "worker_live": worker_live, "monitor_live": monitor_live}
        if stale and mark_stale and entry.get("run_dir"):
            directory = Path(str(entry["run_dir"]))
            command_path = directory / "command.json"
            if (directory / "state.json").is_file() and command_path.is_file():
                command = json.loads(command_path.read_text(encoding="utf-8"))
                _terminal(
                    _root(root),
                    directory,
                    command,
                    status="stale",
                    exit_code=None,
                    reason="orphan-recovery",
                    checks=[],
                )
                report["marked_stale"] = True
        reports.append(report)
    return {"schema": REGISTRY_SCHEMA, "root": str(_root(root)), "checked_at": utc_now(), "runs": reports, "stale_count": sum(row["stale"] for row in reports)}


def recover_run(run_dir: str | Path, *, mark_stale: bool = False) -> dict[str, Any]:
    directory = Path(run_dir).expanduser()
    state = status_for_run(directory)
    worker_live = _process_alive(state.get("pid"))
    monitor_live = _process_alive(state.get("monitor_pid"))
    stale = state.get("status") in ACTIVE_STATUSES and not worker_live and not monitor_live
    report = {
        "id": state.get("id"),
        "run_dir": str(directory),
        "classification": "stale" if stale else "active" if state.get("status") in ACTIVE_STATUSES else "terminal",
        "safe_to_restart": stale or state.get("status") in TERMINAL_STATUSES,
        "worker_live": worker_live,
        "monitor_live": monitor_live,
        "state": state,
    }
    if stale and mark_stale:
        command = json.loads((directory / "command.json").read_text(encoding="utf-8"))
        _terminal(
            Path(command["root"]),
            directory,
            command,
            status="stale",
            exit_code=None,
            reason="orphan-recovery",
            checks=[],
        )
        report["marked_stale"] = True
    return report


def list_runs(root: str | Path, *, active_only: bool = False, limit: int = 100) -> dict[str, Any]:
    registry = read_registry(root)
    rows = [row for row in registry["runs"] if not active_only or row.get("status") in ACTIVE_STATUSES]
    rows = rows[-limit:]
    return {"schema": REGISTRY_SCHEMA, "root": str(_root(root)), "updated_at": registry["updated_at"], "run_count": len(rows), "runs": rows}
