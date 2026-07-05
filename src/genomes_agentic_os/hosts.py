"""Host registry for <os-root>/config/hosts.yml.

Provides load/save/upsert/list helpers for the host alias registry.
No SSH connections are made here — alias-based only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _hosts_path(root: str | Path) -> Path:
    return Path(root).expanduser().resolve() / "config" / "hosts.yml"


def _host_routing_path(root: str | Path) -> Path:
    return Path(root).expanduser().resolve() / "harness" / "registries" / "hosts-routing.yml"


def _harness_runs_log(root: str | Path) -> Path:
    return (
        Path(root).expanduser().resolve()
        / "harness"
        / "shared_factory"
        / "06-runs-and-logs"
        / "harness-runs"
        / "runs.jsonl"
    )


# ---------------------------------------------------------------------------
# Shape validation helpers
# ---------------------------------------------------------------------------

def _validate_host_alias(alias: str) -> str:
    """Raise ValueError if alias is not a safe identifier; return it otherwise."""
    if not alias or not alias.replace("-", "_").replace(".", "_").isidentifier():
        raise ValueError(
            f"Host alias must be a non-empty identifier (letters, digits, hyphens, underscores, dots): {alias!r}"
        )
    return alias


def _validate_host_entry(alias: str, entry: Any) -> dict[str, Any]:
    """Return a clean dict for *entry* or raise ValueError.

    Required shape (all fields optional):
        ssh_alias: str
        user: str
        home: str
        description: str
        ssh_options: list[str]
        paths: list[{path: str, purpose: str}]
    """
    if not isinstance(entry, dict):
        raise ValueError(f"Host entry for {alias!r} must be a YAML mapping, got {type(entry).__name__}")
    cleaned: dict[str, Any] = {}
    for field in ("ssh_alias", "user", "home", "description"):
        if field in entry:
            if not isinstance(entry[field], str):
                raise ValueError(f"Host {alias!r} field {field!r} must be a string")
            cleaned[field] = entry[field]
    if "ssh_options" in entry:
        opts = entry["ssh_options"]
        if not isinstance(opts, list) or not all(isinstance(o, str) for o in opts):
            raise ValueError(f"Host {alias!r} field 'ssh_options' must be a list of strings")
        cleaned["ssh_options"] = opts
    if "paths" in entry:
        paths = entry["paths"]
        if not isinstance(paths, list):
            raise ValueError(f"Host {alias!r} field 'paths' must be a list")
        cleaned_paths = []
        for item in paths:
            if not isinstance(item, dict) or "path" not in item:
                raise ValueError(
                    f"Host {alias!r} paths entries must be dicts with at least a 'path' key"
                )
            cleaned_paths.append(
                {"path": str(item["path"]), "purpose": str(item.get("purpose", ""))}
            )
        cleaned["paths"] = cleaned_paths
    return cleaned


def _validate_hosts_data(data: Any) -> dict[str, dict[str, Any]]:
    """Validate the top-level hosts.yml mapping. Returns the hosts dict."""
    if not isinstance(data, dict):
        raise ValueError("hosts.yml must be a YAML mapping at the top level")
    raw_hosts = data.get("hosts")
    if raw_hosts is None:
        return {}
    if not isinstance(raw_hosts, dict):
        raise ValueError("'hosts' key in hosts.yml must be a YAML mapping")
    result = {}
    for alias, entry in raw_hosts.items():
        _validate_host_alias(str(alias))
        result[str(alias)] = _validate_host_entry(str(alias), entry)
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_hosts(root: str | Path) -> dict[str, dict[str, Any]]:
    """Load hosts.yml from *root*/config/hosts.yml.

    Returns an empty dict if the file does not exist.
    Raises ValueError if the file exists but is malformed.
    """
    path = _hosts_path(root)
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return _validate_hosts_data(raw)


def load_host_routing_policy(root: str | Path) -> dict[str, Any]:
    """Load harness/registries/hosts-routing.yml from *root*.

    Returns an empty dict when the routing policy has not been installed yet.
    """
    path = _host_routing_path(root)
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return raw if isinstance(raw, dict) else {}


def save_hosts(root: str | Path, data: dict[str, dict[str, Any]]) -> None:
    """Write *data* (a hosts alias map) to hosts.yml under *root*/config/.

    The file is written as ``{hosts: <data>}``.
    """
    path = _hosts_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"hosts": data}
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def upsert_host(
    root: str | Path,
    alias: str,
    *,
    ssh_alias: str | None = None,
    user: str | None = None,
    home: str | None = None,
    description: str | None = None,
    ssh_options: list[str] | None = None,
) -> dict[str, Any]:
    """Create or update a host entry.

    Returns a dict with ``action`` (``"created"`` or ``"updated"``),
    ``alias``, and ``path`` (the hosts.yml path).
    """
    _validate_host_alias(alias)
    hosts = load_hosts(root)
    existing = hosts.get(alias, {})
    entry: dict[str, Any] = dict(existing)

    changed = False
    for field_name, value in (
        ("ssh_alias", ssh_alias),
        ("user", user),
        ("home", home),
        ("description", description),
    ):
        if value is not None and entry.get(field_name) != value:
            entry[field_name] = value
            changed = True
    if ssh_options is not None and entry.get("ssh_options") != ssh_options:
        entry["ssh_options"] = ssh_options
        changed = True

    action = "updated" if alias in hosts else "created"
    if alias in hosts and not changed:
        action = "skipped"
    else:
        hosts[alias] = entry
        save_hosts(root, hosts)

    return {"action": action, "alias": alias, "path": str(_hosts_path(root))}


def list_hosts(root: str | Path) -> list[dict[str, Any]]:
    """Return a list of host entries, each with the alias merged in."""
    hosts = load_hosts(root)
    return [{"alias": alias, **entry} for alias, entry in hosts.items()]


def _recent_harness_runs(root: str | Path, limit: int) -> list[dict[str, Any]]:
    path = _harness_runs_log(root)
    if not path.exists() or limit == 0:
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        host = row.get("host")
        if host in (None, "", "local"):
            continue
        rows.append(
            {
                "ts": row.get("ts"),
                "host": host,
                "harness": row.get("harness"),
                "task_type": row.get("task_type"),
                "exit_code": row.get("exit_code"),
                "cwd": row.get("cwd"),
                "remote_cwd": row.get("remote_cwd"),
                "local_view_path": row.get("local_view_path"),
                "output_file": row.get("output_file"),
            }
        )
    return rows[-limit:][::-1] if limit > 0 else rows[::-1]


def host_routing_status(root: str | Path, *, recent_runs: int = 8) -> dict[str, Any]:
    """Return read-only cross-host routing state for operators."""
    hosts = load_hosts(root)
    routing = load_host_routing_policy(root)
    routing_hosts = routing.get("hosts") if isinstance(routing.get("hosts"), dict) else {}

    host_rows: list[dict[str, Any]] = []
    for alias in sorted(set(hosts) | set(routing_hosts)):
        identity = hosts.get(alias, {})
        policy = routing_hosts.get(alias, {})
        project_paths = policy.get("project_paths") if isinstance(policy.get("project_paths"), dict) else {}
        host_rows.append(
            {
                "alias": alias,
                "ssh_alias": identity.get("ssh_alias") or alias,
                "home": identity.get("home"),
                "role": policy.get("role"),
                "max_concurrent": policy.get("max_concurrent"),
                "harnesses": list(policy.get("harnesses") or []),
                "projects": sorted(project_paths),
            }
        )

    return {
        "root": str(Path(root).expanduser().resolve()),
        "hosts_path": str(_hosts_path(root)),
        "routing_path": str(_host_routing_path(root)),
        "hosts": host_rows,
        "auto_route": routing.get("auto_route") or {},
        "artifact_return": routing.get("artifact_return") or {},
        "memory_plane": routing.get("memory_plane") or {},
        "recent_harness_runs": _recent_harness_runs(root, recent_runs),
    }


def format_host_routing_status(result: dict[str, Any]) -> str:
    """Format host routing state for the CLI."""
    lines = [
        f"host routing {result.get('root')}",
        f"hosts: {result.get('hosts_path')}",
        f"routing: {result.get('routing_path')}",
    ]

    auto_route = result.get("auto_route") or {}
    if auto_route:
        lines.append(
            "auto_route: "
            f"enabled={auto_route.get('enabled')} "
            f"strategy={auto_route.get('strategy')} "
            f"probe={auto_route.get('probe')} "
            f"fallback={auto_route.get('fallback_host')}"
        )

    memory_plane = result.get("memory_plane") or {}
    if memory_plane:
        lines.append(
            "memory_plane: "
            f"shared={memory_plane.get('shared')} "
            f"endpoint={memory_plane.get('endpoint_local')}"
        )

    lines.append("")
    lines.append("HOSTS")
    for host in result.get("hosts") or []:
        projects = ", ".join(host.get("projects") or [])
        harnesses = ", ".join(host.get("harnesses") or [])
        lines.append(
            f"- {host.get('alias')} "
            f"role={host.get('role') or '?'} "
            f"ssh_alias={host.get('ssh_alias')} "
            f"home={host.get('home') or '?'} "
            f"max={host.get('max_concurrent') or '?'} "
            f"harnesses=[{harnesses}] "
            f"projects=[{projects}]"
        )

    recent = result.get("recent_harness_runs") or []
    lines.append("")
    lines.append("RECENT HARNESS RUNS")
    if not recent:
        lines.append("- none")
    for run in recent:
        remote = f" remote_cwd={run.get('remote_cwd')}" if run.get("remote_cwd") else ""
        view = f" local_view={run.get('local_view_path')}" if run.get("local_view_path") else ""
        lines.append(
            f"- {run.get('ts')} host={run.get('host')} harness={run.get('harness')} "
            f"task={run.get('task_type')} exit={run.get('exit_code')}{remote}{view}"
        )
    return "\n".join(lines)
