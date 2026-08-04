"""Metrics refresh — compute scorecards and baselines from local OS artefacts.

Reads run logs, doctor findings, and automation maturity levels from the
installed OS root and writes a YAML scorecard into the metrics area of the
shared factory.  No external calls are made; all inputs are local files.

Target output path (matches the 07-metrics template shape):
  harness/shared_factory/07-metrics/scorecard.yml

Usage:
    from genomes_agentic_os.metrics_ops import metrics_refresh
    result = metrics_refresh("/path/to/agentic_os")
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .scaffold import expand_path, harness_path, shared_factory_path
from .runtime_backend import queue_mode_status


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

METRICS_DIR = ("07-metrics",)
SCORECARD_FILENAME = "scorecard.yml"
RUNS_DIR = ("06-runs-and-logs", "runs")
HEARTBEAT_DIR = ("06-runs-and-logs", "heartbeats")
BACKUP_LOGS_DIR_REL = ("logs", "backups")
UPDATE_LOGS_DIR_REL = ("logs", "updates")
DOCTOR_FINDINGS_REL = ("registries", "doctor-findings.yml")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _count_yaml_files(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return sum(1 for f in directory.rglob("*.yml") if f.is_file())


def _count_closed_runs(runs_dir: Path) -> tuple[int, int, int]:
    """Return (total, done, failed) counts from run log YAML files."""
    total = done = failed = 0
    if not runs_dir.is_dir():
        return total, done, failed
    for path in runs_dir.rglob("*.yml"):
        data = _read_yaml(path)
        status = str(data.get("status") or "").lower()
        if status:
            total += 1
            if status == "done":
                done += 1
            elif status in ("failed", "error"):
                failed += 1
    return total, done, failed


def _automation_maturity_counts(root: Path) -> dict[str, int]:
    """Walk domain 04-automations trees and count each maturity level."""
    counts: dict[str, int] = {}
    domain_dirs = {
        *root.glob("*/"),
        *root.glob("domains/*/"),
    }
    for domain_dir in sorted(domain_dirs):
        if not domain_dir.is_dir() or domain_dir.name.startswith("."):
            continue
        automations_root = domain_dir / "04-automations"
        if not automations_root.is_dir():
            continue
        for lane_dir in sorted(automations_root.iterdir()):
            if not lane_dir.is_dir():
                continue
            for auto_dir in sorted(lane_dir.iterdir()):
                if not auto_dir.is_dir():
                    continue
                spec = _read_yaml(auto_dir / "automation.yml")
                maturity = str(spec.get("maturity_level") or spec.get("maturity") or "observe").lower()
                counts[maturity] = counts.get(maturity, 0) + 1
    return counts


def _doctor_finding_counts(root: Path) -> dict[str, int]:
    """Parse doctor findings file for error / warning / ok counts."""
    findings_path = harness_path(root, *DOCTOR_FINDINGS_REL)
    data = _read_yaml(findings_path)
    findings = data.get("findings") or []
    counts: dict[str, int] = {"error": 0, "warning": 0, "ok": 0}
    for item in findings:
        if not isinstance(item, dict):
            continue
        level = str(item.get("level") or item.get("status") or "ok").lower()
        if level in counts:
            counts[level] += 1
        else:
            counts["ok"] += 1
    return counts


def _backup_run_counts(root: Path) -> dict[str, int]:
    backup_dir = harness_path(root, *BACKUP_LOGS_DIR_REL)
    completed = skipped = 0
    if backup_dir.is_dir():
        for path in backup_dir.rglob("*.yml"):
            data = _read_yaml(path)
            status = str(data.get("status") or "").lower()
            if "skip" in status or status == "planned":
                skipped += 1
            elif status in ("completed", "pushed"):
                completed += 1
    return {"completed": completed, "skipped": skipped}


def _parse_timestamp(value: Any) -> datetime | None:
    """Return a timezone-aware ISO timestamp, or ``None`` for absent evidence."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _coordination_baseline(root: Path, runs_dir: Path) -> dict[str, Any]:
    """Build a read-only baseline from existing run receipts and queue state.

    The baseline deliberately does not infer people, work content, or provider
    activity.  It reports only observable receipt gaps and timings so operators
    can address coordination failures without introducing another backend.
    """
    records = [_read_yaml(path) for path in runs_dir.rglob("*.yml")] if runs_dir.is_dir() else []
    records = [record for record in records if record]
    active_statuses = {"queued", "running", "approval-needed", "blocked"}
    missed_handoffs = sum(
        1
        for record in records
        if str(record.get("status") or "").lower() in active_statuses
        and not str(record.get("next_action") or "").strip()
    )

    idempotency_counts: dict[str, int] = {}
    for record in records:
        key = str(record.get("idempotency_key") or "").strip()
        if key:
            idempotency_counts[key] = idempotency_counts.get(key, 0) + 1
    duplicate_work = sum(count - 1 for count in idempotency_counts.values() if count > 1)

    discovery_minutes: list[float] = []
    operator_minutes: list[float] = []
    for record in records:
        created = _parse_timestamp(record.get("created_at"))
        started = _parse_timestamp(record.get("started_at"))
        finished = _parse_timestamp(record.get("finished_at"))
        if created and started and started >= created:
            discovery_minutes.append((started - created).total_seconds() / 60)
        if started and finished and finished >= started:
            operator_minutes.append((finished - started).total_seconds() / 60)

    try:
        runtime = queue_mode_status(root)
        queues = (runtime.get("metrics") or {}).get("queues") or []
    except Exception:  # queue projection is optional in a freshly initialized OS
        runtime = {"queue_mode": "unavailable", "metrics": {"queues": []}}
        queues = []
    queue_statuses: dict[str, int] = {}
    for queue in queues:
        for status, count in (queue.get("statuses") or {}).items():
            queue_statuses[str(status)] = queue_statuses.get(str(status), 0) + int(count)
    queue_waiting = queue_statuses.get("queued", 0) + queue_statuses.get("approval-needed", 0)
    queue_failures = queue_statuses.get("failed", 0) + queue_statuses.get("dead-letter", 0)

    return {
        "evidence": {
            "run_receipts_scanned": len(records),
            "queue_mode": runtime.get("queue_mode"),
            "queue_count": len(queues),
        },
        "missed_handoffs": {
            "count": missed_handoffs,
            "definition": "active run receipts without a next_action",
        },
        "duplicate_work": {
            "count": duplicate_work,
            "definition": "extra run receipts sharing an idempotency_key",
        },
        "discovery_time_minutes": {
            "median": round(_median(discovery_minutes), 2),
            "samples": len(discovery_minutes),
            "definition": "created_at to started_at on run receipts",
        },
        "operator_time_minutes": {
            "median": round(_median(operator_minutes), 2),
            "samples": len(operator_minutes),
            "definition": "started_at to finished_at on run receipts",
        },
        "queue_health": {
            "waiting": queue_waiting,
            "failed_or_dead_letter": queue_failures,
            "statuses": queue_statuses,
        },
        "top_coordination_failures": [
            {
                "id": "missed_handoffs",
                "count": missed_handoffs,
                "evidence": "active run receipts lack next_action",
            },
            {
                "id": "duplicate_work",
                "count": duplicate_work,
                "evidence": "run receipts reuse an idempotency_key",
            },
            {
                "id": "queue_pressure",
                "count": queue_waiting + queue_failures,
                "evidence": "runtime queue status projection",
            },
        ],
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def metrics_refresh(root: str | Path) -> dict[str, Any]:
    """Compute and write a metrics scorecard from local OS artefacts.

    Reads run logs, doctor findings, and automation maturity data from the
    installed OS root and writes the result into
    ``harness/shared_factory/07-metrics/scorecard.yml``.

    Returns the scorecard dict plus ``scorecard_path``.
    """
    os_root = expand_path(root)
    metrics_dir = shared_factory_path(os_root, *METRICS_DIR)
    metrics_dir.mkdir(parents=True, exist_ok=True)

    # Run counts
    runs_dir = shared_factory_path(os_root, *RUNS_DIR)
    total_runs, done_runs, failed_runs = _count_closed_runs(runs_dir)
    run_success_rate = (done_runs / total_runs) if total_runs > 0 else 0.0

    # Heartbeat count
    heartbeat_count = _count_yaml_files(shared_factory_path(os_root, *HEARTBEAT_DIR))

    # Backup counts
    backup_counts = _backup_run_counts(os_root)

    # Coordination baseline: receipt and queue projections only, no new backend.
    coordination_baseline = _coordination_baseline(os_root, runs_dir)

    # Doctor findings
    doctor_counts = _doctor_finding_counts(os_root)

    # Automation maturity
    maturity_counts = _automation_maturity_counts(os_root)
    maturity_levels = ["observe", "prepare", "propose", "execute_approved", "execute_guarded"]
    total_automations = sum(maturity_counts.values())
    advanced = sum(
        maturity_counts.get(level, 0)
        for level in ("execute_approved", "execute_guarded")
    )
    automation_maturity_score = (advanced / total_automations) if total_automations > 0 else 0.0

    scorecard: dict[str, Any] = {
        "schema_version": 1,
        "root": str(os_root),
        "run_health": {
            "total_runs": total_runs,
            "done": done_runs,
            "failed": failed_runs,
            "success_rate": round(run_success_rate, 3),
        },
        "heartbeats": {
            "log_count": heartbeat_count,
        },
        "backups": backup_counts,
        "coordination_baseline": coordination_baseline,
        "doctor_findings": doctor_counts,
        "automation_maturity": {
            "total": total_automations,
            "by_level": {level: maturity_counts.get(level, 0) for level in maturity_levels},
            "advanced_fraction": round(automation_maturity_score, 3),
        },
        "baseline_note": (
            "Computed from local files only.  Run `agentic-os metrics refresh` "
            "after each cycle to update."
        ),
    }

    scorecard_path = metrics_dir / SCORECARD_FILENAME
    scorecard_path.write_text(yaml.safe_dump(scorecard, sort_keys=False), encoding="utf-8")

    return {"scorecard_path": str(scorecard_path), **scorecard}


def format_metrics_result(result: dict[str, Any]) -> str:
    return yaml.safe_dump(result, sort_keys=False).strip()
