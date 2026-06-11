"""Host registry for <os-root>/config/hosts.yml.

Provides load/save/upsert/list helpers for the host alias registry.
No SSH connections are made here — alias-based only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _hosts_path(root: str | Path) -> Path:
    return Path(root).expanduser().resolve() / "config" / "hosts.yml"


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
        description: str
        ssh_options: list[str]
        paths: list[{path: str, purpose: str}]
    """
    if not isinstance(entry, dict):
        raise ValueError(f"Host entry for {alias!r} must be a YAML mapping, got {type(entry).__name__}")
    cleaned: dict[str, Any] = {}
    for field in ("ssh_alias", "user", "description"):
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
