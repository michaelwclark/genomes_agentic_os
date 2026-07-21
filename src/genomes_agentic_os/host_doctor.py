"""Policy-composed host health reporting and bounded automatic repair.

The durable policy surface is Markdown with YAML front matter.  The engine only
executes built-in probes and repair actions; Markdown cannot inject arbitrary
shell commands.  Shared workflow policies compose with one host overlay in
stable path order, mirroring the root -> host composition used by Auto-Dev.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import tempfile
from typing import Any, Callable, Iterable
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

import yaml

from . import notion_api

REPORT_ROOT = "harness/shared_factory/06-runs-and-logs/auto-doctor"
PROGRAM_CONFIG = "lib/programs/root/host_agentic_os_health/config"
DEFAULT_SCHEDULE = ("06:00", "14:00", "22:00")
SAFE_ACTIONS = {"restart_user_service", "start_user_service", "restart_container"}

Runner = Callable[..., subprocess.CompletedProcess[str]]


def _run(
    args: list[str],
    *,
    timeout: int = 12,
    runner: Runner = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    try:
        return runner(args, check=False, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(args, 127, "", f"{type(exc).__name__}: {exc}")


def _front_matter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"policy has no YAML front matter: {path}")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError(f"policy front matter is not closed: {path}")
    value = yaml.safe_load(text[4:end]) or {}
    if not isinstance(value, dict):
        raise ValueError(f"policy front matter must be a mapping: {path}")
    return value


def load_host_policies(config_root: str | Path, host_alias: str) -> list[dict[str, Any]]:
    root = Path(config_root).expanduser().resolve()
    paths = sorted((root / "workflows").glob("*.md"))
    paths.extend(sorted((root / "hosts" / host_alias).glob("*.md")))
    policies: list[dict[str, Any]] = []
    for path in paths:
        policy = _front_matter(path)
        if policy.get("enabled", True) is False:
            continue
        if policy.get("api_version") != "auto-doctor-policy/v1":
            raise ValueError(f"unsupported policy api_version in {path}")
        policy = dict(policy)
        policy["source"] = str(path)
        policies.append(policy)
    return policies


def host_projection(policies: Iterable[dict[str, Any]]) -> dict[str, str]:
    """Return the host's declarative Notion projection, if configured."""
    for policy in reversed(list(policies)):
        page_id = policy.get("notion_page_id")
        if page_id:
            return {
                "page_id": str(page_id).replace("-", ""),
                "workspace": str(policy.get("notion_workspace") or "Genome's Notion"),
            }
    return {}


def default_config_root(root: str | Path) -> Path:
    return Path(root).expanduser().resolve() / PROGRAM_CONFIG


def _linux_memory() -> dict[str, float]:
    values: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        key, raw = line.split(":", 1)
        match = re.search(r"\d+", raw)
        if match:
            values[key] = int(match.group()) * 1024
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", values.get("MemFree", 0))
    swap_total = values.get("SwapTotal", 0)
    swap_free = values.get("SwapFree", 0)
    return {
        "memory_total_bytes": float(total),
        "memory_available_bytes": float(available),
        "memory_available_percent": round(available * 100 / total, 3) if total else 0.0,
        "swap_used_bytes": float(max(0, swap_total - swap_free)),
        "swap_used_percent": round((swap_total - swap_free) * 100 / swap_total, 3) if swap_total else 0.0,
    }


def _darwin_memory(*, runner: Runner) -> dict[str, float]:
    total_result = _run(["sysctl", "-n", "hw.memsize"], runner=runner)
    total = int(total_result.stdout.strip() or 0)
    vm = _run(["vm_stat"], runner=runner).stdout
    page_match = re.search(r"page size of (\d+) bytes", vm)
    page_size = int(page_match.group(1)) if page_match else 16384
    pages: dict[str, int] = {}
    for line in vm.splitlines():
        match = re.match(r"([^:]+):\s+(\d+)\.", line)
        if match:
            pages[match.group(1)] = int(match.group(2))
    available = page_size * sum(
        pages.get(key, 0) for key in ("Pages free", "Pages inactive", "Pages speculative", "Pages purgeable")
    )
    swap = _run(["sysctl", "-n", "vm.swapusage"], runner=runner).stdout
    total_swap = _size_from_swap(swap, "total")
    used_swap = _size_from_swap(swap, "used")
    return {
        "memory_total_bytes": float(total),
        "memory_available_bytes": float(available),
        "memory_available_percent": round(available * 100 / total, 3) if total else 0.0,
        "swap_used_bytes": float(used_swap),
        "swap_used_percent": round(used_swap * 100 / total_swap, 3) if total_swap else 0.0,
        "compressed_bytes": float(pages.get("Pages occupied by compressor", 0) * page_size),
    }


def _size_from_swap(text: str, field: str) -> int:
    match = re.search(rf"{field}\s*=\s*([0-9.]+)([MG])", text)
    if not match:
        return 0
    multiplier = 1024**3 if match.group(2) == "G" else 1024**2
    return int(float(match.group(1)) * multiplier)


def _process_rows(*, runner: Runner) -> list[dict[str, Any]]:
    result = _run(
        ["ps", "-axo", "pid=,ppid=,user=,state=,%cpu=,rss=,etime=,command="],
        timeout=15,
        runner=runner,
    )
    rows: list[dict[str, Any]] = []
    pattern = re.compile(r"^\s*(\d+)\s+(\d+)\s+(\S+)\s+(\S+)\s+([0-9.]+)\s+(\d+)\s+(\S+)\s+(.*)$")
    for line in result.stdout.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        rows.append(
            {
                "pid": int(match.group(1)),
                "ppid": int(match.group(2)),
                "user": match.group(3),
                "state": match.group(4),
                "cpu_percent": float(match.group(5)),
                "rss_bytes": int(match.group(6)) * 1024,
                "elapsed": match.group(7),
                "command": match.group(8),
            }
        )
    return rows


def _linux_pressure() -> dict[str, float]:
    metrics: dict[str, float] = {}
    for category in ("cpu", "memory", "io"):
        path = Path("/proc/pressure") / category
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            kind = line.split(maxsplit=1)[0]
            match = re.search(r"avg10=([0-9.]+)", line)
            if match:
                metrics[f"psi_{category}_{kind}_avg10"] = float(match.group(1))
    return metrics


def collect_metrics(*, runner: Runner = subprocess.run) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    system = platform.system().lower()
    load1, load5, load15 = os.getloadavg()
    cpu_count = os.cpu_count() or 1
    disk = shutil.disk_usage("/")
    metrics: dict[str, Any] = {
        "platform": system,
        "cpu_count": cpu_count,
        "load1": round(load1, 3),
        "load5": round(load5, 3),
        "load15": round(load15, 3),
        "load1_per_cpu": round(load1 / cpu_count, 3),
        "disk_used_percent": round(disk.used * 100 / disk.total, 3),
        "disk_free_bytes": disk.free,
    }
    metrics.update(_linux_memory() if system == "linux" else _darwin_memory(runner=runner))
    if system == "linux":
        metrics.update(_linux_pressure())
    processes = _process_rows(runner=runner)
    metrics.update(
        {
            "process_count": len(processes),
            "node_process_count": sum(bool(re.search(r"(^|/)node(?:\s|$)", row["command"])) for row in processes),
            "curl_process_count": sum(bool(re.search(r"(^|/)curl(?:\s|$)", row["command"])) for row in processes),
            "orphan_process_count": sum(row["ppid"] == 1 for row in processes),
        }
    )
    fsevents = [row for row in processes if row["command"].endswith("/fseventsd")]
    metrics["fseventsd_cpu_percent"] = round(sum(row["cpu_percent"] for row in fsevents), 3)
    metrics["fseventsd_rss_bytes"] = sum(row["rss_bytes"] for row in fsevents)
    return metrics, processes


def _compare(metric: float, threshold: dict[str, Any]) -> tuple[str | None, str | None]:
    checks = (
        ("critical_above", "critical", lambda value, boundary: value > boundary),
        ("critical_below", "critical", lambda value, boundary: value < boundary),
        ("warn_above", "degraded", lambda value, boundary: value > boundary),
        ("warn_below", "degraded", lambda value, boundary: value < boundary),
    )
    for key, severity, predicate in checks:
        if key in threshold and predicate(metric, float(threshold[key])):
            return severity, key
    return None, None


def _finding(policy: dict[str, Any], code: str, severity: str, summary: str, **evidence: Any) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "workflow": policy.get("workflow"),
        "summary": summary,
        "evidence": evidence,
        "policy_source": policy.get("source"),
    }


def _probe_thresholds(policy: dict[str, Any], metrics: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for name, threshold in (policy.get("thresholds") or {}).items():
        if name not in metrics or not isinstance(threshold, dict):
            continue
        severity, comparison = _compare(float(metrics[name]), threshold)
        if severity:
            findings.append(
                _finding(
                    policy,
                    f"threshold.{name}",
                    severity,
                    f"{name} is {metrics[name]} ({comparison} {threshold[comparison]})",
                    metric=name,
                    value=metrics[name],
                    threshold=threshold[comparison],
                )
            )
    return findings


def _probe_processes(
    policy: dict[str, Any], processes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for watch in policy.get("processes") or []:
        regex = re.compile(str(watch.get("command_regex") or r"$^"))
        matched = [row for row in processes if regex.search(row["command"])]
        count = len(matched)
        if count > int(watch.get("critical_above") or 10**9):
            severity = "critical"
        elif count > int(watch.get("warn_above") or 10**9):
            severity = "degraded"
        else:
            continue
        findings.append(
            _finding(
                policy,
                str(watch.get("finding_code") or f"process.{watch.get('id')}.count"),
                severity,
                f"{watch.get('title') or watch.get('id')} count is {count}",
                count=count,
                sample_pids=[row["pid"] for row in matched[:10]],
            )
        )
    return findings


def _service_status(watch: dict[str, Any], *, runner: Runner) -> tuple[bool, str]:
    kind, name = watch.get("kind"), str(watch.get("name") or "")
    if kind == "systemd_user":
        result = _run(["systemctl", "--user", "is-active", name], runner=runner)
        return result.returncode == 0 and result.stdout.strip() == "active", result.stdout.strip() or result.stderr.strip()
    if kind == "launchd":
        result = _run(["launchctl", "print", f"gui/{os.getuid()}/{name}"], runner=runner)
        return result.returncode == 0, "registered" if result.returncode == 0 else result.stderr.strip()
    if kind == "http":
        result = _run(
            ["curl", "--silent", "--show-error", "--fail", "--max-time", "5", str(watch.get("url"))],
            timeout=7,
            runner=runner,
        )
        return result.returncode == 0, f"curl_exit={result.returncode}"
    if kind == "docker":
        result = _run(["docker", "inspect", name, "--format", "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}"], runner=runner)
        state = result.stdout.strip()
        return result.returncode == 0 and (state.startswith("running|healthy") or state == "running|none"), state or result.stderr.strip()
    return False, f"unsupported service kind: {kind}"


def _probe_services(policy: dict[str, Any], *, runner: Runner) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for watch in policy.get("services") or []:
        ok, detail = _service_status(watch, runner=runner)
        if not ok:
            findings.append(
                _finding(
                    policy,
                    str(watch.get("finding_code") or f"service.{watch.get('id')}.unhealthy"),
                    str(watch.get("severity") or "critical"),
                    f"{watch.get('title') or watch.get('name')} is unhealthy",
                    kind=watch.get("kind"),
                    target=watch.get("name") or watch.get("url"),
                    detail=detail[-500:],
                )
            )
    return findings


def _overall(findings: Iterable[dict[str, Any]]) -> str:
    severities = {str(item.get("severity")) for item in findings}
    return "critical" if "critical" in severities else "degraded" if "degraded" in severities else "healthy"


def _compose_findings(findings: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply host-overlay semantics: the last policy wins for one finding code."""
    composed: dict[str, dict[str, Any]] = {}
    for finding in findings:
        composed[str(finding.get("code"))] = finding
    return list(composed.values())


def next_run_at(
    now: datetime,
    schedule: Iterable[str] = DEFAULT_SCHEDULE,
    timezone_name: str = "America/Chicago",
) -> datetime:
    zone = ZoneInfo(timezone_name)
    local = now.astimezone(zone)
    candidates: list[datetime] = []
    for day_offset in (0, 1):
        day = (local + timedelta(days=day_offset)).date()
        for value in schedule:
            hour, minute = (int(part) for part in value.split(":", 1))
            candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)
            if candidate > local:
                candidates.append(candidate)
    return min(candidates).astimezone(UTC)


def build_host_report(
    root: str | Path,
    *,
    host_alias: str | None = None,
    config_root: str | Path | None = None,
    now: datetime | None = None,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    os_root = Path(root).expanduser().resolve()
    checked = (now or datetime.now(UTC)).astimezone(UTC)
    alias = host_alias or socket.gethostname().split(".", 1)[0].lower()
    policy_root = Path(config_root).expanduser().resolve() if config_root else default_config_root(os_root)
    policies = load_host_policies(policy_root, alias)
    metrics, processes = collect_metrics(runner=runner)
    findings: list[dict[str, Any]] = []
    for policy in policies:
        platforms = {str(item).lower() for item in policy.get("platforms") or []}
        if platforms and metrics["platform"] not in platforms:
            continue
        findings.extend(_probe_thresholds(policy, metrics))
        findings.extend(_probe_processes(policy, processes))
        findings.extend(_probe_services(policy, runner=runner))
    findings = _compose_findings(findings)
    schedule = next((policy.get("schedule") for policy in reversed(policies) if policy.get("schedule")), {}) or {}
    cadence = tuple(schedule.get("local_times") or DEFAULT_SCHEDULE)
    timezone_name = str(schedule.get("timezone") or "America/Chicago")
    return {
        "api_version": "auto-doctor-report/v1",
        "host": alias,
        "checked_at": checked.isoformat().replace("+00:00", "Z"),
        "next_run_at": next_run_at(checked, cadence, timezone_name).isoformat().replace("+00:00", "Z"),
        "status": _overall(findings),
        "root": str(os_root),
        "config_root": str(policy_root),
        "policy_sources": [policy["source"] for policy in policies],
        "metrics": metrics,
        "findings": findings,
        "repairs": [],
    }


def _repair_command(action: dict[str, Any]) -> list[str] | None:
    action_id, target = str(action.get("action") or ""), str(action.get("target") or "")
    if action_id in {"restart_user_service", "start_user_service"}:
        verb = "restart" if action_id == "restart_user_service" else "start"
        return ["systemctl", "--user", verb, target]
    if action_id == "restart_container":
        return ["docker", "restart", target]
    return None


def apply_safe_repairs(
    report: dict[str, Any],
    policies: list[dict[str, Any]],
    *,
    apply: bool,
    runner: Runner = subprocess.run,
) -> list[dict[str, Any]]:
    finding_codes = {str(item.get("code")) for item in report.get("findings") or []}
    repairs: list[dict[str, Any]] = []
    for policy in policies:
        for action in policy.get("repairs") or []:
            if action.get("when") not in finding_codes:
                continue
            action_id = str(action.get("action") or "")
            eligible = (
                action_id in SAFE_ACTIONS
                and action.get("automatic") is True
                and action.get("safety") == "reconstructable"
            )
            receipt: dict[str, Any] = {
                "id": action.get("id") or action_id,
                "action": action_id,
                "target": action.get("target"),
                "eligible": eligible,
                "applied": False,
                "status": "planned" if eligible else "manual_only",
            }
            command = _repair_command(action) if eligible else None
            if apply and command:
                result = _run(command, timeout=int(action.get("timeout_seconds") or 45), runner=runner)
                receipt.update(
                    {
                        "applied": result.returncode == 0,
                        "status": "repaired" if result.returncode == 0 else "failed",
                        "exit_code": result.returncode,
                        "detail": (result.stdout or result.stderr)[-500:],
                    }
                )
            repairs.append(receipt)
            if len(repairs) >= 3:
                return repairs
    return repairs


def render_host_report(report: dict[str, Any]) -> str:
    metrics = report.get("metrics") or {}
    lines = [
        f"# {str(report['host']).title()} Host Health",
        "",
        f"**Status:** {str(report['status']).upper()}  ",
        f"**Last ran:** {report['checked_at']}  ",
        f"**Next run:** {report['next_run_at']}",
        "",
        "## Current snapshot",
        "",
        f"- Load: {metrics.get('load1')} / {metrics.get('load5')} / {metrics.get('load15')} ({metrics.get('load1_per_cpu')} per CPU)",
        f"- Memory available: {metrics.get('memory_available_percent')}%",
        f"- Swap used: {metrics.get('swap_used_percent')}%",
        f"- Root disk used: {metrics.get('disk_used_percent')}%",
        f"- Processes: {metrics.get('process_count')} total, {metrics.get('node_process_count')} Node, {metrics.get('curl_process_count')} curl",
        "",
        "## Findings",
        "",
    ]
    findings = report.get("findings") or []
    lines.extend([f"- **{item['severity'].upper()}** — {item['summary']}" for item in findings] or ["- No threshold or liveness findings."])
    lines.extend(["", "## Repair activity", ""])
    lines.extend(
        [f"- {item['status']}: {item['action']} → {item.get('target')}" for item in report.get("repairs") or []]
        or ["- No repair was required."],
    )
    lines.extend(
        [
            "",
            "## Operating boundary",
            "",
            "Automatic repairs are limited to policy-allowlisted, reconstructable service or container restarts. Root services, data deletion, reboot, indexing changes, and unknown processes remain manual approval actions.",
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


def write_host_report(root: str | Path, report: dict[str, Any]) -> dict[str, str]:
    report_root = Path(root).expanduser().resolve() / REPORT_ROOT / str(report["host"])
    stamp = str(report["checked_at"]).replace("-", "").replace(":", "")
    run_root = report_root / stamp
    paths = {
        "json": run_root / "report.json",
        "markdown": run_root / "report.md",
        "latest_json": report_root / "latest.json",
        "latest_markdown": report_root / "latest.md",
    }
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    rendered = render_host_report(report)
    for key in ("json", "latest_json"):
        _atomic_write(paths[key], payload)
    for key in ("markdown", "latest_markdown"):
        _atomic_write(paths[key], rendered)
    return {key: str(value) for key, value in paths.items()}


def _rich_text(content: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": content[:2000]}}]


def notion_blocks(report: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = report.get("metrics") or {}
    blocks: list[dict[str, Any]] = [
        {"object": "block", "type": "callout", "callout": {"rich_text": _rich_text(f"{str(report['status']).upper()} · Last ran {report['checked_at']} · Next run {report['next_run_at']}"), "icon": {"type": "emoji", "emoji": "🩺"}}},
        {"object": "block", "type": "heading_2", "heading_2": {"rich_text": _rich_text("Current snapshot")}},
        {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rich_text(f"Load {metrics.get('load1')} · memory available {metrics.get('memory_available_percent')}% · swap used {metrics.get('swap_used_percent')}% · disk used {metrics.get('disk_used_percent')}%")}},
        {"object": "block", "type": "heading_2", "heading_2": {"rich_text": _rich_text("Findings")}},
    ]
    for finding in report.get("findings") or []:
        blocks.append({"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": _rich_text(f"{str(finding['severity']).upper()}: {finding['summary']}")}})
    if not report.get("findings"):
        blocks.append({"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": _rich_text("No threshold or liveness findings.")}})
    blocks.extend(
        [
            {"object": "block", "type": "heading_2", "heading_2": {"rich_text": _rich_text("Repair activity")}},
            {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rich_text("; ".join(f"{item['status']}: {item['action']} → {item.get('target')}" for item in report.get('repairs') or []) or "No repair was required.")}},
            {"object": "block", "type": "heading_2", "heading_2": {"rich_text": _rich_text("Operating rules")}},
            {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rich_text("Auto-Doctor may only apply policy-allowlisted reconstructable repairs. Root services, reboots, deletions, indexing changes, and unknown processes require approval.")}},
        ]
    )
    return blocks


def project_host_report(
    report: dict[str, Any],
    page_id: str,
    *,
    verified_workspace: str,
    token_env: str = "GENOMES_NOTION_PAT",
) -> dict[str, Any]:
    actual = notion_api.get_bot_workspace(token_env)
    if actual != verified_workspace or actual != "Genome's Notion":
        raise RuntimeError(f"Notion workspace mismatch: expected Genome's Notion, got {actual!r}")
    notion_api.replace_block_children(page_id, notion_blocks(report), token_env)
    return {"applied": True, "workspace": actual, "page_id": page_id}


def project_losmon_report(
    report: dict[str, Any],
    url: str,
    *,
    token_env: str = "LOSMON_HOST_HEALTH_TOKEN",
    fetcher: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    """Publish one report to LOSMON without returning or logging its token."""
    token = os.environ.get(token_env)
    if not token:
        raise RuntimeError(f"LOSMON ingestion token env var {token_env!r} is not set")
    request = urllib.request.Request(
        url,
        data=json.dumps(report).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="PUT",
    )
    try:
        response = fetcher(request, timeout=20)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"LOSMON report ingestion returned HTTP {exc.code}") from None
    status = int(getattr(response, "status", 202))
    if status < 200 or status >= 300:
        raise RuntimeError(f"LOSMON report ingestion returned HTTP {status}")
    return {"applied": True, "url": url, "status": status}


def project_losmon_drop(
    latest_json: str | Path,
    target: str,
    *,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Copy a report to an SSH-backed LOSMON drop path using a fixed command."""
    if not re.fullmatch(r"[A-Za-z0-9._-]+:/[A-Za-z0-9_./-]+\.json", target):
        raise ValueError("LOSMON drop target must be ssh-alias:/absolute/path.json")
    result = _run(
        ["scp", "-q", "-o", "ConnectTimeout=8", str(Path(latest_json).resolve()), target],
        timeout=20,
        runner=runner,
    )
    if result.returncode != 0:
        raise RuntimeError(f"LOSMON SSH report drop failed with exit {result.returncode}")
    return {"applied": True, "target": target}
