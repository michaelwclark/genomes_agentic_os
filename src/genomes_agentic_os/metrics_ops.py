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

from pathlib import Path
from typing import Any

import yaml

from .scaffold import expand_path, harness_path, shared_factory_path


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
