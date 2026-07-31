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
SAFE_ACTIONS = {
    "restart_user_service",
    "start_user_service",
    "restart_container",
    "prune_docker_images",
    "prune_docker_build_cache",
    "prune_ephemeral_worktrees",
}

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
            projection = {
                "page_id": str(page_id).replace("-", ""),
            }
            if policy.get("notion_workspace"):
                projection["workspace"] = str(policy["notion_workspace"])
            if policy.get("notion_token_env"):
                projection["token_env"] = str(policy["notion_token_env"])
            if policy.get("notion_parent_page_id"):
                projection["parent_page_id"] = str(
                    policy["notion_parent_page_id"]
                ).replace("-", "")
            return projection
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


def _parse_bytes(value: str) -> int:
    match = re.match(r"\s*([0-9.]+)\s*([kmgt]?i?b)?", value.lower())
    if not match:
        return 0
    units = {"": 1, "b": 1, "kb": 1000, "kib": 1024, "mb": 1000**2, "mib": 1024**2,
             "gb": 1000**3, "gib": 1024**3, "tb": 1000**4, "tib": 1024**4}
    return int(float(match.group(1)) * units.get(match.group(2) or "", 1))


def _docker_inventory(policy: dict[str, Any], *, now: datetime, runner: Runner) -> dict[str, Any]:
    config = policy.get("docker") or {}
    if not config.get("enabled"):
        return {}
    ids_result = _run(["docker", "ps", "-aq"], runner=runner)
    if ids_result.returncode != 0:
        return {"available": False, "detail": ids_result.stderr[-300:]}
    ids = ids_result.stdout.split()
    containers: list[dict[str, Any]] = []
    if ids:
        template = "{{.Name}}\t{{.State.Status}}\t{{.State.StartedAt}}\t{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}\t{{.Image}}"
        inspected = _run(["docker", "inspect", "--format", template, *ids], timeout=30, runner=runner)
        for line in inspected.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) != 5:
                continue
            name, state, started, health, image_id = parts
            try:
                started_at = datetime.fromisoformat(started.replace("Z", "+00:00"))
                age_hours = max(0.0, (now - started_at.astimezone(UTC)).total_seconds() / 3600)
            except ValueError:
                age_hours = 0.0
            containers.append({"name": name.removeprefix("/"), "state": state, "health": health,
                               "started_at": started, "age_hours": round(age_hours, 2), "image_id": image_id})
    stats_result = _run(["docker", "stats", "--no-stream", "--format", "{{json .}}"], timeout=30, runner=runner)
    stats: dict[str, dict[str, Any]] = {}
    for line in stats_result.stdout.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        name = str(item.get("Name") or item.get("Container") or "")
        stats[name] = {
            "cpu_percent": float(str(item.get("CPUPerc") or "0").rstrip("%") or 0),
            "memory_bytes": _parse_bytes(str(item.get("MemUsage") or "").split("/", 1)[0]),
        }
    for container in containers:
        container.update(stats.get(container["name"], {}))
    image_result = _run(["docker", "image", "ls", "-q", "--no-trunc"], runner=runner)
    image_ids = sorted(set(image_result.stdout.split()))
    images: list[dict[str, Any]] = []
    used_ids = {str(item["image_id"]) for item in containers}
    if image_ids:
        template = "{{.Id}}\t{{.Created}}\t{{json .RepoTags}}"
        inspected = _run(["docker", "image", "inspect", "--format", template, *image_ids], timeout=45, runner=runner)
        for line in inspected.stdout.splitlines():
            parts = line.split("\t", 2)
            if len(parts) != 3:
                continue
            image_id, created, tags_raw = parts
            try:
                created_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
                age_hours = max(0.0, (now - created_at.astimezone(UTC)).total_seconds() / 3600)
            except ValueError:
                age_hours = 0.0
            try:
                tags = json.loads(tags_raw) or []
            except json.JSONDecodeError:
                tags = []
            images.append({"id": image_id, "created_at": created, "age_hours": round(age_hours, 2),
                           "tags": tags, "used": image_id in used_ids})
    prune_hours = float(config.get("image_prune_after_hours") or 120)
    persistent = re.compile(str(config.get("persistent_name_regex") or r"$^"))
    long_hours = float(config.get("long_running_hours") or 120)
    long_running = [item for item in containers if item["state"] == "running" and item["age_hours"] > long_hours
                    and not persistent.search(item["name"])]
    memory_warn = int(config.get("container_memory_warn_bytes") or 2 * 1024**3)
    cpu_warn = float(config.get("container_cpu_warn_percent") or 150)
    restart_watch_hits: list[dict[str, Any]] = []
    by_name = {item["name"]: item for item in containers}
    for watch in config.get("restart_watches") or []:
        watched = by_name.get(str(watch.get("name") or ""))
        threshold = int(watch.get("memory_bytes_above") or 0)
        if watched and threshold and int(watched.get("memory_bytes") or 0) >= threshold:
            restart_watch_hits.append({**watched, "finding_code": str(watch.get("finding_code") or ""),
                                       "threshold_bytes": threshold})
    return {
        "available": True,
        "containers": containers,
        "images": images,
        "old_unused_images": [item for item in images if not item["used"] and item["age_hours"] >= prune_hours],
        "long_running": long_running,
        "memory_hogs": [item for item in containers if int(item.get("memory_bytes") or 0) >= memory_warn],
        "cpu_hogs": [item for item in containers if float(item.get("cpu_percent") or 0) >= cpu_warn],
        "restart_watch_hits": restart_watch_hits,
    }


def _probe_docker(policy: dict[str, Any], inventory: dict[str, Any]) -> list[dict[str, Any]]:
    if not inventory:
        return []
    if not inventory.get("available"):
        return [_finding(policy, "docker.unavailable", "degraded", "Docker/OrbStack inventory is unavailable",
                         detail=inventory.get("detail"))]
    findings: list[dict[str, Any]] = []
    old = inventory.get("old_unused_images") or []
    if old:
        findings.append(_finding(policy, "docker.old_unused_images", "degraded",
                                 f"{len(old)} unused Docker images are at least five days old",
                                 count=len(old), sample_tags=[item.get("tags") for item in old[:10]]))
    long_running = inventory.get("long_running") or []
    if long_running:
        findings.append(_finding(policy, "docker.long_running", "degraded",
                                 f"{len(long_running)} non-persistent containers exceed the host age policy",
                                 containers=[{"name": x["name"], "age_hours": x["age_hours"]} for x in long_running[:15]]))
    unhealthy = [item for item in inventory.get("containers") or []
                 if item["state"] == "running" and item["health"] not in {"none", "healthy"}]
    if unhealthy:
        findings.append(_finding(policy, "docker.unhealthy_containers", "critical",
                                 f"{len(unhealthy)} running containers are unhealthy",
                                 containers=[{"name": x["name"], "state": x["state"], "health": x["health"]} for x in unhealthy[:15]]))
    stopped = [item for item in inventory.get("containers") or [] if item["state"] != "running"]
    if stopped:
        findings.append(_finding(policy, "docker.stopped_containers", "degraded",
                                 f"{len(stopped)} containers are stopped",
                                 containers=[{"name": x["name"], "state": x["state"]} for x in stopped[:15]]))
    if inventory.get("memory_hogs"):
        findings.append(_finding(policy, "docker.memory_hogs", "degraded",
                                 f"{len(inventory['memory_hogs'])} containers exceed the memory policy",
                                 containers=[{"name": x["name"], "memory_bytes": x.get("memory_bytes")} for x in inventory["memory_hogs"][:15]]))
    if inventory.get("cpu_hogs"):
        findings.append(_finding(policy, "docker.cpu_hogs", "degraded",
                                 f"{len(inventory['cpu_hogs'])} containers exceed the CPU policy",
                                 containers=[{"name": x["name"], "cpu_percent": x.get("cpu_percent")} for x in inventory["cpu_hogs"][:15]]))
    for item in inventory.get("restart_watch_hits") or []:
        if item.get("finding_code"):
            findings.append(_finding(policy, item["finding_code"], "critical",
                                     f"{item['name']} exceeds its exact automatic-recovery memory threshold",
                                     container=item["name"], memory_bytes=item.get("memory_bytes"),
                                     threshold_bytes=item.get("threshold_bytes")))
    return findings


def _worktree_inventory(policy: dict[str, Any], *, now: datetime, runner: Runner) -> dict[str, Any]:
    config = policy.get("worktrees") or {}
    repositories = [Path(str(item)).expanduser() for item in config.get("repositories") or []]
    cleanup_days = float(config.get("cleanup_after_days") or 5)
    cleanup_regex = re.compile(str(config.get("auto_cleanup_path_regex") or r"$^"))
    auto_unlock_ephemeral = config.get("auto_unlock_ephemeral") is True
    worktrees: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for repository in repositories:
        if not repository.exists():
            continue
        result = _run(["git", "-C", str(repository), "worktree", "list", "--porcelain"], timeout=20, runner=runner)
        records: list[dict[str, Any]] = []
        current: dict[str, Any] = {}
        for line in [*result.stdout.splitlines(), ""]:
            if not line:
                if current:
                    records.append(current)
                    current = {}
                continue
            key, _, value = line.partition(" ")
            current[key] = value if value else True
        for index, record in enumerate(records):
            path = Path(str(record.get("worktree") or ""))
            if index == 0 or not path.exists():
                continue
            branch = str(record.get("branch") or "")
            log = _run(["git", "-C", str(path), "log", "-1", "--format=%ct"], runner=runner)
            try:
                age_days = max(0.0, (now.timestamp() - int(log.stdout.strip())) / 86400)
            except ValueError:
                age_days = 0.0
            item = {"repository": str(repository), "path": str(path), "branch": branch,
                    "age_days": round(age_days, 2), "locked": bool(record.get("locked"))}
            worktrees.append(item)
            if (branch.startswith("refs/heads/") and (not item["locked"] or auto_unlock_ephemeral)
                    and age_days >= cleanup_days
                    and cleanup_regex.search(str(path))):
                status = _run(["git", "-C", str(path), "status", "--porcelain", "--untracked-files=normal"],
                              timeout=20, runner=runner)
                if status.returncode == 0 and not status.stdout.strip():
                    candidates.append(item)
    return {"worktrees": worktrees, "cleanup_candidates": candidates,
            "max_cleanup_per_run": int(config.get("max_cleanup_per_run") or 20),
            "warn_above": int(config.get("warn_above") or 40),
            "critical_above": int(config.get("critical_above") or 100)}


def _probe_worktrees(policy: dict[str, Any], inventory: dict[str, Any]) -> list[dict[str, Any]]:
    if not inventory:
        return []
    count = len(inventory.get("worktrees") or [])
    severity = "critical" if count > inventory["critical_above"] else "degraded" if count > inventory["warn_above"] else None
    findings: list[dict[str, Any]] = []
    if severity:
        findings.append(_finding(policy, "worktrees.excessive", severity,
                                 f"{count} secondary Git worktrees exceed the host policy", count=count))
    candidates = inventory.get("cleanup_candidates") or []
    if candidates:
        findings.append(_finding(policy, "worktrees.cleanup_candidates", "degraded",
                                 f"{len(candidates)} clean ephemeral worktrees are eligible for bounded cleanup",
                                 count=len(candidates), sample_paths=[Path(x["path"]).name for x in candidates[:15]]))
    return findings


def _probe_memory_hogs(policy: dict[str, Any], processes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    config = policy.get("memory_hogs") or {}
    if not config:
        return []
    excluded = re.compile(str(config.get("exclude_regex") or r"$^"))
    warn = int(config.get("rss_warn_bytes") or 4 * 1024**3)
    critical = int(config.get("rss_critical_bytes") or 12 * 1024**3)
    matched = [row for row in processes if row["rss_bytes"] >= warn and not excluded.search(row["command"])]
    if not matched:
        return []
    severity = "critical" if any(row["rss_bytes"] >= critical for row in matched) else "degraded"
    return [_finding(policy, "process.memory_hogs", severity,
                     f"{len(matched)} processes exceed the resident-memory policy",
                     processes=[{"pid": x["pid"], "rss_bytes": x["rss_bytes"], "command": x["command"][:160]} for x in matched[:12]])]


def _service_status(watch: dict[str, Any], *, runner: Runner) -> tuple[bool, str]:
    kind, name = watch.get("kind"), str(watch.get("name") or "")
    if kind == "systemd_user":
        result = _run(["systemctl", "--user", "is-active", name], runner=runner)
        return result.returncode == 0 and result.stdout.strip() == "active", result.stdout.strip() or result.stderr.strip()
    if kind == "systemd_system":
        result = _run(["systemctl", "is-active", name], runner=runner)
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
    if kind == "tcp":
        try:
            with socket.create_connection((str(watch.get("host") or "127.0.0.1"), int(watch.get("port"))), timeout=3):
                return True, "connected"
        except OSError as exc:
            return False, f"{type(exc).__name__}: {exc}"
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
    inventory: dict[str, Any] = {"docker": {}, "worktrees": {}}
    for policy in policies:
        platforms = {str(item).lower() for item in policy.get("platforms") or []}
        if platforms and metrics["platform"] not in platforms:
            continue
        findings.extend(_probe_thresholds(policy, metrics))
        findings.extend(_probe_processes(policy, processes))
        findings.extend(_probe_services(policy, runner=runner))
        docker_inventory = _docker_inventory(policy, now=checked, runner=runner)
        if docker_inventory:
            inventory["docker"] = docker_inventory
            metrics.update({
                "docker_container_count": len(docker_inventory.get("containers") or []),
                "docker_long_running_count": len(docker_inventory.get("long_running") or []),
                "docker_old_unused_image_count": len(docker_inventory.get("old_unused_images") or []),
                "docker_memory_hog_count": len(docker_inventory.get("memory_hogs") or []),
                "docker_cpu_hog_count": len(docker_inventory.get("cpu_hogs") or []),
            })
            findings.extend(_probe_docker(policy, docker_inventory))
        worktree_inventory = _worktree_inventory(policy, now=checked, runner=runner)
        if worktree_inventory.get("worktrees"):
            inventory["worktrees"] = worktree_inventory
            metrics["worktree_count"] = len(worktree_inventory["worktrees"])
            metrics["worktree_cleanup_candidate_count"] = len(worktree_inventory["cleanup_candidates"])
            findings.extend(_probe_worktrees(policy, worktree_inventory))
        findings.extend(_probe_memory_hogs(policy, processes))
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
        "inventory": inventory,
        "repairs": [],
    }


def _repair_command(action: dict[str, Any]) -> list[str] | None:
    action_id, target = str(action.get("action") or ""), str(action.get("target") or "")
    if action_id in {"restart_user_service", "start_user_service"}:
        verb = "restart" if action_id == "restart_user_service" else "start"
        return ["systemctl", "--user", verb, target]
    if action_id == "restart_container":
        return ["docker", "restart", target]
    if action_id == "prune_docker_images" and re.fullmatch(r"\d+[hmd]", target):
        return ["docker", "image", "prune", "-a", "--force", "--filter", f"until={target}"]
    if action_id == "prune_docker_build_cache" and re.fullmatch(r"\d+[hmd]", target):
        return ["docker", "builder", "prune", "--all", "--force", "--filter", f"until={target}"]
    return None


def _prune_ephemeral_worktrees(report: dict[str, Any], action: dict[str, Any], *, runner: Runner) -> tuple[bool, str]:
    inventory = (report.get("inventory") or {}).get("worktrees") or {}
    candidates = list(inventory.get("cleanup_candidates") or [])
    limit = min(int(action.get("max_per_run") or inventory.get("max_cleanup_per_run") or 20), 25)
    removed: list[str] = []
    failures: list[str] = []
    repositories: set[str] = set()
    for item in candidates[:limit]:
        repository, path = str(item["repository"]), str(item["path"])
        if item.get("locked"):
            unlocked = _run(["git", "-C", repository, "worktree", "unlock", path], timeout=20, runner=runner)
            if unlocked.returncode != 0:
                failures.append(f"{Path(path).name}: unlock exit {unlocked.returncode}")
                continue
        result = _run(["git", "-C", repository, "worktree", "remove", path], timeout=45, runner=runner)
        if result.returncode == 0:
            removed.append(Path(path).name)
            repositories.add(repository)
        else:
            failures.append(f"{Path(path).name}: exit {result.returncode}")
    for repository in repositories:
        _run(["git", "-C", repository, "worktree", "prune"], runner=runner)
    detail = f"removed={len(removed)} failures={len(failures)}"
    if failures:
        detail += " " + "; ".join(failures[:5])
    return bool(removed) and not failures, detail


def _remove_old_unused_images(report: dict[str, Any], *, runner: Runner) -> tuple[bool, str]:
    inventory = (report.get("inventory") or {}).get("docker") or {}
    image_ids = [str(item.get("id") or "") for item in inventory.get("old_unused_images") or []]
    image_ids = [item for item in image_ids if item.startswith("sha256:")][:50]
    if not image_ids:
        return False, "removed=0 failures=0"
    removed = 0
    failures: list[str] = []
    for offset in range(0, len(image_ids), 25):
        batch = image_ids[offset:offset + 25]
        result = _run(["docker", "image", "rm", *batch], timeout=180, runner=runner)
        if result.returncode == 0:
            removed += len(batch)
        else:
            failures.append(f"batch-{offset // 25 + 1}: exit {result.returncode}")
    detail = f"removed={removed} failures={len(failures)}"
    if failures:
        detail += " " + "; ".join(failures)
    return bool(removed) and not failures, detail


def apply_safe_repairs(
    report: dict[str, Any],
    policies: list[dict[str, Any]],
    *,
    apply: bool,
    runner: Runner = subprocess.run,
) -> list[dict[str, Any]]:
    finding_codes = {str(item.get("code")) for item in report.get("findings") or []}
    repairs: list[dict[str, Any]] = []
    eligible_attempts = 0
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
            within_limit = eligible and eligible_attempts < 5
            if within_limit:
                eligible_attempts += 1
            receipt: dict[str, Any] = {
                "id": action.get("id") or action_id,
                "action": action_id,
                "target": action.get("target"),
                "eligible": eligible,
                "applied": False,
                "status": "planned" if within_limit else ("deferred_limit" if eligible else "manual_only"),
            }
            command = _repair_command(action) if within_limit else None
            if apply and within_limit and action_id == "prune_ephemeral_worktrees":
                success, detail = _prune_ephemeral_worktrees(report, action, runner=runner)
                receipt.update({"applied": success, "status": "repaired" if success else "failed", "detail": detail})
            elif apply and within_limit and action_id == "prune_docker_images":
                success, detail = _remove_old_unused_images(report, runner=runner)
                receipt.update({"applied": success, "status": "repaired" if success else "failed", "detail": detail})
            elif apply and command:
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
        f"- Docker/OrbStack: {metrics.get('docker_container_count', 'unavailable')} containers, {metrics.get('docker_old_unused_image_count', 0)} unused images older than policy, {metrics.get('docker_long_running_count', 0)} long-running development containers",
        f"- Worktrees: {metrics.get('worktree_count', 'unavailable')} secondary, {metrics.get('worktree_cleanup_candidate_count', 0)} safe cleanup candidates",
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


def _rich_text(content: str, *, bold: bool = False, color: str = "default") -> list[dict[str, Any]]:
    return [{
        "type": "text",
        "text": {"content": content[:2000]},
        "annotations": {"bold": bold, "color": color},
    }]


def _table_row(*cells: str, header: bool = False) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "table_row",
        "table_row": {"cells": [_rich_text(cell, bold=header) for cell in cells]},
    }


def _status_style(status: str) -> tuple[str, str]:
    return {
        "healthy": ("✅", "green_background"),
        "degraded": ("⚠️", "yellow_background"),
        "critical": ("🚨", "red_background"),
    }.get(status.lower(), ("🩺", "blue_background"))


def notion_blocks(report: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = report.get("metrics") or {}
    status = str(report.get("status") or "unknown")
    host = str(report.get("host") or "Unknown").title()
    icon, status_color = _status_style(status)
    snapshot_rows = [
        _table_row("Signal", "Current", "Why it matters", header=True),
        _table_row("Load", f"{metrics.get('load1')} / {metrics.get('load5')} / {metrics.get('load15')}", "Sustained compute pressure"),
        _table_row("Memory available", f"{metrics.get('memory_available_percent')}%", "Headroom before compression or OOM"),
        _table_row("Swap used", f"{metrics.get('swap_used_percent')}%", "Post-pressure recovery signal"),
        _table_row("Disk used", f"{metrics.get('disk_used_percent')}%", "Capacity and Docker build health"),
        _table_row("Processes", f"{metrics.get('process_count')} total · {metrics.get('node_process_count')} Node · {metrics.get('curl_process_count')} curl", "Storm and leak detection"),
        _table_row("Docker / OrbStack", f"{metrics.get('docker_container_count', 'n/a')} containers · {metrics.get('docker_long_running_count', 0)} long-running", "Development runtime pressure"),
        _table_row("Worktrees", f"{metrics.get('worktree_count', 'n/a')} total · {metrics.get('worktree_cleanup_candidate_count', 0)} safe candidates", "Filesystem watcher pressure"),
    ]
    blocks: list[dict[str, Any]] = [
        {"object": "block", "type": "callout", "callout": {"rich_text": _rich_text(f"{status.upper()} · {host} host health"), "icon": {"type": "emoji", "emoji": icon}, "color": status_color}},
        {"object": "block", "type": "column_list", "column_list": {"children": [
            {"object": "block", "type": "column", "column": {"children": [
                {"object": "block", "type": "callout", "callout": {"rich_text": _rich_text(f"Last ran\n{report['checked_at']}"), "icon": {"type": "emoji", "emoji": "🕒"}, "color": "blue_background"}},
            ]}},
            {"object": "block", "type": "column", "column": {"children": [
                {"object": "block", "type": "callout", "callout": {"rich_text": _rich_text(f"Next scheduled\n{report['next_run_at']}"), "icon": {"type": "emoji", "emoji": "⏭️"}, "color": "purple_background"}},
            ]}},
            {"object": "block", "type": "column", "column": {"children": [
                {"object": "block", "type": "callout", "callout": {"rich_text": _rich_text("Scope\nDevelopment host"), "icon": {"type": "emoji", "emoji": "🧰"}, "color": "gray_background"}},
            ]}},
        ]}},
        {"object": "block", "type": "divider", "divider": {}},
        {"object": "block", "type": "heading_2", "heading_2": {"rich_text": _rich_text("Current snapshot", color="blue")}},
        {"object": "block", "type": "table", "table": {"table_width": 3, "has_column_header": True, "has_row_header": False, "children": snapshot_rows}},
    ]
    watch = report.get("watch") or {}
    timeline = report.get("watch_timeline") or []
    if watch:
        blocks.extend([
            {"object": "block", "type": "heading_2", "heading_2": {"rich_text": _rich_text("Post-reboot watch", color="purple")}},
            {"object": "block", "type": "callout", "callout": {"rich_text": _rich_text(
                f"{watch.get('phase', 'monitoring').upper()} · sample {watch.get('samples_completed', 0)} of {watch.get('samples_total', '?')} · planned finish {watch.get('planned_finish_at', 'unknown')}"
            ), "icon": {"type": "emoji", "emoji": "📡"}, "color": "purple_background"}},
        ])
        if timeline:
            timeline_rows = [_table_row("Time", "Status", "Memory", "Swap", "fseventsd CPU", "Curl", header=True)]
            for item in timeline[-30:]:
                timeline_rows.append(_table_row(
                    str(item.get("checked_at") or ""), str(item.get("status") or "unknown").upper(),
                    f"{item.get('memory_available_percent')}%", f"{item.get('swap_used_percent')}%",
                    f"{item.get('fseventsd_cpu_percent')}%", str(item.get("curl_process_count")),
                ))
            blocks.append({"object": "block", "type": "table", "table": {
                "table_width": 6, "has_column_header": True, "has_row_header": False, "children": timeline_rows,
            }})
    blocks.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": _rich_text("Findings", color="orange")}})
    for finding in report.get("findings") or []:
        finding_icon, finding_color = _status_style(str(finding.get("severity") or "unknown"))
        blocks.append({"object": "block", "type": "callout", "callout": {"rich_text": _rich_text(str(finding["summary"])), "icon": {"type": "emoji", "emoji": finding_icon}, "color": finding_color}})
    if not report.get("findings"):
        blocks.append({"object": "block", "type": "callout", "callout": {"rich_text": _rich_text("No threshold or liveness findings."), "icon": {"type": "emoji", "emoji": "✅"}, "color": "green_background"}})
    repair_children = [
        {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": _rich_text(f"{item['status']}: {item['action']} → {item.get('target') or 'policy target'}")}}
        for item in report.get("repairs") or []
    ] or [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rich_text("No repair was required.")}}]
    blocks.extend(
        [
            {"object": "block", "type": "toggle", "toggle": {"rich_text": _rich_text("Repair activity", bold=True), "color": "green_background", "children": repair_children}},
            {"object": "block", "type": "toggle", "toggle": {"rich_text": _rich_text("Operating rules", bold=True), "color": "gray_background", "children": [
                {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": _rich_text("Only policy-allowlisted reconstructable repairs run automatically.")}},
                {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": _rich_text("Active images, Docker volumes, dirty worktrees, and database data are preserved.")}},
                {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": _rich_text("Reboots, OrbStack restarts, Spotlight changes, and unknown process termination require approval.")}},
            ]}},
            {"object": "block", "type": "toggle", "toggle": {"rich_text": _rich_text("Source and validation", bold=True), "color": "blue_background", "children": [
                {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rich_text("Source of truth: Auto-Doctor Markdown policy plus durable JSON/Markdown host receipts. This page is a live operator projection.")}},
                {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rich_text(f"Report schema {report.get('api_version', 'unknown')} · host {report.get('host', 'unknown')}")}},
            ]}},
        ]
    )
    return blocks


def project_host_report(
    report: dict[str, Any],
    page_id: str,
    *,
    verified_workspace: str,
    approved_parent_page_id: str,
    token_env: str = "NOTION_TOKEN",
) -> dict[str, Any]:
    if not verified_workspace:
        raise ValueError("verified_workspace is required for a Notion projection")
    if not approved_parent_page_id:
        raise ValueError("approved_parent_page_id is required for a Notion projection")
    actual = notion_api.get_bot_workspace(
        token_env, parent_page_id=approved_parent_page_id
    )
    if actual != verified_workspace:
        raise RuntimeError(f"Notion workspace mismatch: expected {verified_workspace!r}, got {actual!r}")
    notion_api.replace_block_children(
        page_id,
        notion_blocks(report),
        token_env,
        approved_parent_page_id=approved_parent_page_id,
    )
    return {
        "applied": True,
        "workspace": actual,
        "page_id": page_id,
        "approved_parent_page_id": approved_parent_page_id,
    }


def project_http_report(
    report: dict[str, Any],
    url: str,
    *,
    token_env: str = "HOST_HEALTH_REPORT_TOKEN",
    fetcher: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    """Publish one report to an HTTP sink without returning or logging its token."""
    token = os.environ.get(token_env)
    if not token:
        raise RuntimeError(f"report ingestion token env var {token_env!r} is not set")
    request = urllib.request.Request(
        url,
        data=json.dumps(report).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="PUT",
    )
    try:
        response = fetcher(request, timeout=20)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"report ingestion returned HTTP {exc.code}") from None
    status = int(getattr(response, "status", 202))
    if status < 200 or status >= 300:
        raise RuntimeError(f"report ingestion returned HTTP {status}")
    return {"applied": True, "url": url, "status": status}


def project_report_drop(
    latest_json: str | Path,
    target: str,
    *,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Copy a report to an SSH-backed drop path using a fixed command."""
    if not re.fullmatch(r"[A-Za-z0-9._-]+:/[A-Za-z0-9_./-]+\.json", target):
        raise ValueError("report drop target must be ssh-alias:/absolute/path.json")
    result = _run(
        ["scp", "-q", "-o", "ConnectTimeout=8", str(Path(latest_json).resolve()), target],
        timeout=20,
        runner=runner,
    )
    if result.returncode != 0:
        raise RuntimeError(f"SSH report drop failed with exit {result.returncode}")
    return {"applied": True, "target": target}
