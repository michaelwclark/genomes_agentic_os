"""Backend-neutral queue and worker health, remediation, and notifications."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Callable

import yaml

from .runtime_backend import queue_mode_status, runtime_queue_items

RUNTIME_REGISTRY = "harness/shared_factory/00-control-plane/runtime-registry.yml"
REPORT_ROOT = "harness/shared_factory/06-runs-and-logs/runtime-health"
SUPERVISOR_LOG = "harness/shared_factory/06-runs-and-logs/supervisor.out.log"
SUPERVISOR_LABEL = "com.genome.agentic-os.supervisor"


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_hours(value: object, now: datetime) -> float | None:
    parsed = _parse_time(value)
    return None if parsed is None else max(0.0, (now - parsed).total_seconds() / 3600)


def _ref(item: dict[str, Any]) -> str:
    return str(item.get("ref") or item.get("schedule_id") or item.get("work_type") or "unknown")


def _running_is_stale(item: dict[str, Any], now: datetime) -> bool:
    age = _age_hours(item.get("started_at") or item.get("updated_at"), now)
    if age is None:
        return False
    try:
        timeout_hours = max(0.0, float(item.get("timeout_seconds") or 0) / 3600)
    except (TypeError, ValueError):
        timeout_hours = 0.0
    return age > max(1.0, timeout_hours + 0.25)


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _default_launchctl() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{SUPERVISOR_LABEL}"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _supervisor_health(
    root: Path,
    now: datetime,
    launchctl_runner: Callable[[], subprocess.CompletedProcess[str]],
) -> dict[str, Any]:
    log_path = root / SUPERVISOR_LOG
    log_age = max(0.0, (now.timestamp() - log_path.stat().st_mtime) / 3600) if log_path.is_file() else None
    try:
        result = launchctl_runner()
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "healthy": False,
            "registered": False,
            "state": "unknown",
            "last_exit_code": None,
            "log_age_hours": log_age,
            "reason": f"launchctl check failed: {type(exc).__name__}",
        }
    output = f"{result.stdout}\n{result.stderr}"
    state_match = re.search(r"\bstate = ([^\n]+)", output)
    exit_match = re.search(r"\blast exit code = (-?\d+)", output)
    state = state_match.group(1).strip() if state_match else "unknown"
    last_exit = int(exit_match.group(1)) if exit_match else None
    # This is an interval LaunchAgent; `not running` between ticks is normal.
    healthy = result.returncode == 0 and last_exit in {None, 0} and log_age is not None and log_age <= 0.5
    reasons: list[str] = []
    if result.returncode != 0:
        reasons.append("LaunchAgent is not registered")
    if last_exit not in {None, 0}:
        reasons.append(f"last supervisor exit code is {last_exit}")
    if log_age is None:
        reasons.append("supervisor log is missing")
    elif log_age > 0.5:
        reasons.append(f"supervisor log is stale ({log_age:.1f}h)")
    return {
        "healthy": healthy,
        "registered": result.returncode == 0,
        "state": state,
        "last_exit_code": last_exit,
        "log_age_hours": round(log_age, 3) if log_age is not None else None,
        "reason": "; ".join(reasons) if reasons else "LaunchAgent and recent supervisor tick are healthy",
    }


def build_runtime_health(
    root: str | Path,
    *,
    now: datetime | None = None,
    launchctl_runner: Callable[[], subprocess.CompletedProcess[str]] = _default_launchctl,
) -> dict[str, Any]:
    os_root = Path(root).expanduser().resolve()
    checked_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    registry = _load_yaml(os_root / RUNTIME_REGISTRY)
    items = runtime_queue_items(os_root)
    mode_status = queue_mode_status(os_root)
    fabric_metrics = mode_status["metrics"]
    statuses = Counter(str(item.get("status") or "unknown") for item in items)
    queued = [item for item in items if item.get("status") == "queued"]
    running = [item for item in items if item.get("status") == "running"]
    queued_ages = [
        age
        for item in queued
        if (age := _age_hours(item.get("due_at") or item.get("created_at"), checked_at)) is not None
    ]
    stale_queued = sum(age > 24 for age in queued_ages)
    stale_running = sum(_running_is_stale(item, checked_at) for item in running)
    expired_running = sum(
        1
        for item in running
        if (lease_until := _parse_time(item.get("lease_until"))) is not None and lease_until < checked_at
    )
    recent_terminal = [
        item
        for item in items
        if item.get("status") in {"done", "failed"}
        and (
            (age := _age_hours(item.get("finished_at") or item.get("updated_at"), checked_at)) is not None and age <= 1
        )
    ]
    recent_statuses = Counter(str(item.get("status")) for item in recent_terminal)
    backlog_refs = Counter(_ref(item) for item in queued)
    schedules = [item for item in registry.get("schedules") or [] if isinstance(item, dict)]
    enabled = [item for item in schedules if item.get("enabled") is not False]
    priority = [
        item
        for item in enabled
        if item.get("supervisor_priority")
        or (isinstance(item.get("supervisor"), dict) and item["supervisor"].get("priority_dispatch"))
    ]
    supervisor = _supervisor_health(os_root, checked_at, launchctl_runner)

    findings: list[str] = []
    severity = "healthy"
    if not supervisor["healthy"]:
        severity = "critical"
        findings.append(supervisor["reason"])
    if stale_running:
        severity = "critical"
        findings.append(f"{stale_running} worker dispatches exceeded their configured runtime budget")
    if expired_running:
        severity = "critical"
        findings.append(f"{expired_running} running tasks have expired worker leases")
    if stale_queued:
        severity = "critical"
        findings.append(f"{stale_queued} queued items are older than 24 hours")
    elif len(queued) > 100:
        severity = "degraded" if severity == "healthy" else severity
        findings.append(f"queue depth is elevated at {len(queued)} items")
    if recent_statuses.get("failed", 0) > recent_statuses.get("done", 0) and recent_statuses.get("failed", 0):
        severity = "degraded" if severity == "healthy" else severity
        findings.append("dispatch failures exceeded successful dispatches in the last hour")
    dead_letters = int(fabric_metrics.get("dead_letter_count") or statuses.get("dead-letter", 0))
    unhealthy_workers = int(fabric_metrics.get("unhealthy_worker_count") or 0)
    if dead_letters:
        severity = "critical"
        findings.append(f"{dead_letters} tasks are in dead-letter state")
    if unhealthy_workers:
        severity = "critical" if running else ("degraded" if severity == "healthy" else severity)
        findings.append(f"{unhealthy_workers} execution workers are offline or lease-expired")
    for named_queue in fabric_metrics.get("queues") or []:
        named_statuses = named_queue.get("statuses") or {}
        named_depth = int(named_statuses.get("queued", 0)) + int(named_statuses.get("approval-needed", 0))
        max_queued = int(named_queue.get("max_queued") or 0)
        if max_queued and named_depth >= max_queued:
            severity = "critical"
            findings.append(f"queue {named_queue['queue_name']} reached its admission limit ({named_depth}/{max_queued})")
        elif max_queued and named_depth >= max_queued * 0.8:
            severity = "degraded" if severity == "healthy" else severity
            findings.append(f"queue {named_queue['queue_name']} is above 80% capacity ({named_depth}/{max_queued})")
    if not findings:
        findings.append("queue depth, dispatch activity, and supervisor freshness are within thresholds")
    return {
        "schema_version": 2,
        "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
        "root": str(os_root),
        "status": severity,
        "technology": {
            "queue": "transactional named queues" if mode_status["queue_mode"] == "execution_fabric" else "file-backed YAML ledger",
            "scheduler": "Python Agentic OS runtime",
            "supervisor": "macOS LaunchAgent",
            "workers": "bounded per-job subprocesses",
            "external_broker": False,
            "queue_mode": mode_status["queue_mode"],
        },
        "queue": {
            "total_records": len(items),
            "status_counts": dict(statuses),
            "queued": len(queued),
            "stale_queued_over_24h": stale_queued,
            "oldest_queued_age_hours": round(max(queued_ages), 3) if queued_ages else 0.0,
            "top_backlogs": [{"ref": ref, "queued": count} for ref, count in backlog_refs.most_common(10)],
            "named_queues": fabric_metrics.get("queues", []),
            "dead_letter": dead_letters,
        },
        "workers": {
            "running": len(running),
            "stale_running_over_budget": stale_running,
            "expired_running_leases": expired_running,
            "completed_last_hour": recent_statuses.get("done", 0),
            "failed_last_hour": recent_statuses.get("failed", 0),
            "supervisor": supervisor,
            "pools": fabric_metrics.get("worker_pools", []),
            "registered": int(fabric_metrics.get("worker_count") or 0),
            "live": int(fabric_metrics.get("live_worker_count") or 0),
            "unhealthy": unhealthy_workers,
        },
        "schedules": {"enabled": len(enabled), "priority": len(priority)},
        "findings": findings,
    }


def render_runtime_health(report: dict[str, Any]) -> str:
    queue, workers = report["queue"], report["workers"]
    supervisor = workers["supervisor"]
    lines = [
        "# Queue & Worker Health",
        "",
        f"Status: **{str(report['status']).upper()}**",
        f"Checked: `{report['checked_at']}`",
        "",
        "## Queue",
        "",
        f"- Actionable queued: **{queue['queued']}**",
        f"- Stale over 24h: **{queue['stale_queued_over_24h']}**",
        f"- Oldest queued age: **{queue['oldest_queued_age_hours']:.1f}h**",
        f"- Total retained records: **{queue['total_records']}**",
        "",
        "## Workers",
        "",
        f"- Supervisor healthy: **{'yes' if supervisor['healthy'] else 'no'}**",
        f"- Supervisor state: **{supervisor['state']}** (interval jobs may be idle between ticks)",
        f"- Completed last hour: **{workers['completed_last_hour']}**",
        f"- Failed last hour: **{workers['failed_last_hour']}**",
        f"- Currently running: **{workers['running']}**",
        "",
        "## Findings",
        "",
        *[f"- {finding}" for finding in report["findings"]],
        "",
        "## Top Backlogs",
        "",
    ]
    lines.extend([f"- `{item['ref']}`: {item['queued']}" for item in queue["top_backlogs"]] or ["- None"])
    lines.extend(
        [
            "",
            "## Runtime Technology",
            "",
            f"The selected queue backend is `{report['technology']['queue_mode']}`. The scheduler and dispatcher remain local and brokerless.",
            "",
        ]
    )
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def write_runtime_health(root: str | Path, report: dict[str, Any]) -> dict[str, str]:
    report_root = Path(root).expanduser().resolve() / REPORT_ROOT
    stamp = str(report["checked_at"]).replace("-", "").replace(":", "")
    run_root = report_root / stamp
    paths = {
        "json": run_root / "report.json",
        "markdown": run_root / "report.md",
        "latest_json": report_root / "latest.json",
        "latest_markdown": report_root / "latest.md",
    }
    json_text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    markdown = render_runtime_health(report)
    for key in ("json", "latest_json"):
        _atomic_write(paths[key], json_text)
    for key in ("markdown", "latest_markdown"):
        _atomic_write(paths[key], markdown)
    return {key: str(path) for key, path in paths.items()}


def _incident_fingerprint(report: dict[str, Any]) -> str:
    findings = [re.sub(r"\b\d+(?:\.\d+)?\b", "#", str(item)) for item in report.get("findings") or []]
    material = json.dumps(
        {"status": report.get("status"), "findings": findings, "queue_mode": report.get("technology", {}).get("queue_mode")},
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _incident_window(report: dict[str, Any]) -> str:
    checked = _parse_time(report.get("checked_at")) or datetime.now(timezone.utc)
    return checked.strftime("%Y%m%dT%H")


def queue_runtime_self_heal(root: str | Path, report: dict[str, Any], paths: dict[str, str]) -> dict[str, Any]:
    """Queue one bounded Codex diagnosis per distinct unhealthy incident."""
    if report.get("status") not in {"degraded", "critical"}:
        return {"queued": False, "reason": "healthy"}
    os_root = Path(root).expanduser().resolve()
    fingerprint = _incident_fingerprint(report)
    incident_key = f"{fingerprint}-{_incident_window(report)}"
    action_root = os_root / REPORT_ROOT / "self-heal" / fingerprint
    prompt_path = action_root / "prompt.md"
    prompt = f"""# Agentic OS runtime self-heal

Diagnose and safely repair the local queue/worker incident described in `{paths['latest_json']}`.

Constraints:
- Treat runtime.queue_mode as authoritative; never mutate the inactive backend.
- Prefer bounded local repairs, preserve queued work, and produce test/receipt evidence.
- Do not mutate production systems, external services, Jira, Notion, Slack, or GitHub.
- If safe repair is not possible, write a blocker-grade local receipt and stop.

Incident fingerprint: `{fingerprint}`
"""
    _atomic_write(prompt_path, prompt)
    from .runtime_ops import append_run_queue_item

    result = append_run_queue_item(
        os_root,
        {
            "id": f"queue_runtime_health_self_heal_{incident_key}",
            "kind": "runtime_self_heal",
            "ref": "queue_worker_health_report",
            "status": "queued",
            "approval_state": "not_required",
            "priority": 100 if report.get("status") == "critical" else 80,
            "idempotency_key": f"runtime-health-self-heal:{incident_key}",
            "execution_target": "codex_harness",
            "task_type": "llm.codex",
            "queue_name": "codex",
            "worker_pool": "codex_workers",
            "instructions": prompt,
            "prompt_path": str(prompt_path.relative_to(os_root)),
            "incident_fingerprint": fingerprint,
            "evidence": [{"type": "runtime_health", "path": paths["latest_json"]}],
        },
    )
    return {"queued": bool(result["created"]), "fingerprint": fingerprint, "incident_window": _incident_window(report), **result}


def notify_runtime_health(
    root: str | Path,
    report: dict[str, Any],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    if report.get("status") not in {"degraded", "critical"}:
        return {"sent": False, "reason": "healthy"}
    os_root = Path(root).expanduser().resolve()
    fingerprint = _incident_fingerprint(report)
    try:
        completed = runner(
            [
                str(os_root / "harness/bin/agentic-os-notify"),
                "--source", "runtime.execution_fabric.health",
                "--level", "critical" if report.get("status") == "critical" else "warning",
                "--title", f"Agentic OS runtime {report.get('status')}",
                "--message", "; ".join(str(item) for item in report.get("findings") or [])[:500],
                "--dedupe-key", f"runtime-health-{fingerprint}",
            ],
            cwd=os_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"sent": False, "error": f"{type(exc).__name__}: {exc}", "fingerprint": fingerprint}
    return {"sent": completed.returncode == 0, "returncode": completed.returncode, "fingerprint": fingerprint}


def project_runtime_health(
    root: str | Path,
    report: dict[str, Any],
    paths: dict[str, str],
    *,
    automation_id: str = "queue-worker-health",
) -> dict[str, Any]:
    os_root = Path(root).expanduser().resolve()
    completed = subprocess.run(
        [
            str(os_root / "harness/bin/agentic-os-automation-run-summary"),
            "--automation-id",
            automation_id,
            "--status",
            str(report["status"]),
            "--summary-file",
            paths["latest_markdown"],
            "--evidence",
            f"local_report={paths['json']}",
        ],
        cwd=os_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
    }
