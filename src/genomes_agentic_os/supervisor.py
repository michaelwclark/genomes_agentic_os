"""Single-tick runtime supervisor.

Composes the runtime subsystems into one auditable "tick" so an external
scheduler (launchd / systemd / cron) can drive the OS without a bespoke daemon.
This is the file-first answer to "the OS has a runtime surface but nothing makes
it tick": the scheduler calls `agentic-os runtime supervise --apply` on a
cadence, and this module runs each subsystem once, in order, collecting an
auditable report.

Design notes:
- **Dry-run by default**, matching the rest of the runtime surface. Pass
  `dry_run=False` (CLI `--apply`) to allow real effects.
- **Composition, not reinvention.** Each step calls the existing per-subsystem
  op; this module only orders them and assembles the report. New subsystems get
  one line here.
- **Isolated steps.** A failing step is recorded and the tick continues, so one
  broken subsystem never silences the others.
- **Health is read-only and always collected** (it never mutates), so a tick
  doubles as a heartbeat for monitoring.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Callable

import yaml

from .event_graph import process_due
from .long_run import start_run
from .runtime_ops import (
    heartbeat_list,
    heartbeat_run,
    runtime_doctor,
    runtime_prepare_priority_ref,
    runtime_priority_dispatch_refs,
    runtime_run_batch,
    schedule_run_due,
)
from .source_watch import run_due_watch_sources
from .state.db import DEFAULT_STATE_BACKUP_INTERVAL_HOURS, backup_state_database


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _summarize(result: dict[str, Any]) -> dict[str, Any]:
    """Pull a compact summary from a subsystem result dict.

    Keeps the supervise report readable: scalar status fields plus a count for
    every list-valued field, dropping verbose nested payloads.
    """
    summary: dict[str, Any] = {}
    if not isinstance(result, dict):
        return summary
    for key in ("ok", "status", "dry_run", "run_id", "run_dir"):
        if key in result:
            summary[key] = result[key]
    for key, value in result.items():
        if isinstance(value, list):
            summary[f"{key}_count"] = len(value)
    return summary


def _dispatch_run_queue(root: str | Path, *, dry_run: bool) -> dict[str, Any]:
    """Preview synchronously or dispatch one applied queue item asynchronously."""

    if dry_run:
        return runtime_run_batch(root, dry_run=True)

    os_root = Path(root).expanduser().resolve()
    state = start_run(
        os_root,
        command=[
            sys.executable,
            "-m",
            "genomes_agentic_os.cli",
            "runtime",
            "run-next",
            "--root",
            str(os_root),
            "--apply",
        ],
        label="runtime supervisor run-queue dispatch",
        kind="command",
        work_dir=str(os_root),
        # No budgets override here on purpose. Detaching this dispatch into
        # start_run is what keeps the supervisor tick responsive, so the
        # queue item's own runtime no longer needs to be capped at the old
        # 15-minute tick cadence -- long_run's wall-clock budget is a hard
        # SIGTERM->SIGKILL process-group kill, not a soft warning, and
        # killing a legitimately long queue item here would trade tick
        # starvation for silent forced termination of the exact work this
        # dispatch exists to accommodate. Let long_run._effective_budgets
        # apply the operator's harness/config/long-running-execution.yml
        # budgets.wall_clock_minutes if configured, falling back to the
        # module's own 60-minute default otherwise.
        budgets=None,
    )
    return {
        "ok": True,
        "status": "dispatched",
        "run_id": state["id"],
        "run_dir": state["run_dir"],
    }


def supervise_tick(root: str | Path, *, dry_run: bool = True) -> dict[str, Any]:
    """Run one supervisor tick across the runtime surface.

    Order: heartbeats -> schedules -> watch sources -> events -> run queue ->
    state backup, then a read-only health check. Returns an auditable report; `ok` is true
    when every mutating step completed without raising.
    """
    steps: list[dict[str, Any]] = []

    def _run(step: str, fn: Callable[[], dict[str, Any]]) -> None:
        try:
            steps.append({"step": step, "ok": True, "summary": _summarize(fn())})
        except Exception as exc:  # report and continue; never abort the tick
            steps.append({"step": step, "ok": False, "error": f"{type(exc).__name__}: {exc}"})

    def _heartbeats() -> dict[str, Any]:
        ran: list[dict[str, Any]] = []
        for heartbeat in heartbeat_list(root).get("heartbeats", []):
            heartbeat_id = heartbeat.get("id")
            if not heartbeat_id or heartbeat.get("enabled") is False:
                continue
            ran.append({"id": heartbeat_id, "result": _summarize(heartbeat_run(root, heartbeat_id, dry_run=dry_run))})
        return {"ok": True, "ran": ran}

    def _priority_run_queue() -> dict[str, Any]:
        dispatched: list[dict[str, Any]] = []
        for ref in runtime_priority_dispatch_refs(root):
            result = runtime_prepare_priority_ref(root, ref, dry_run=dry_run)
            dispatched.append({"ref": ref, "result": _summarize(result)})
        return {"ok": True, "dispatched": dispatched}

    _run("heartbeats", _heartbeats)
    _run("schedules", lambda: schedule_run_due(root, dry_run=dry_run))
    _run("watch_sources", lambda: run_due_watch_sources(root, dry_run=dry_run))
    _run("events", lambda: process_due(root, dry_run=dry_run))
    _run("priority_run_queue", _priority_run_queue)
    _run("run_queue", lambda: _dispatch_run_queue(root, dry_run=dry_run))
    _run(
        "state_backup",
        lambda: backup_state_database(
            root,
            if_due_hours=DEFAULT_STATE_BACKUP_INTERVAL_HOURS,
            dry_run=dry_run,
        ),
    )

    # Health is read-only — collected every tick, never gates mutation.
    try:
        health = runtime_doctor(root)
    except Exception as exc:
        health = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    steps.append({"step": "health", "ok": bool(health.get("ok")), "summary": _summarize(health)})

    mutating_ok = all(step["ok"] for step in steps if step["step"] != "health")
    return {
        "tick": _utc_now(),
        "root": str(Path(root).expanduser()),
        "dry_run": dry_run,
        "ok": mutating_ok,
        "health_ok": bool(health.get("ok")),
        "steps": steps,
    }


def format_supervise_result(result: dict[str, Any]) -> str:
    return yaml.safe_dump(result, sort_keys=False).strip()
