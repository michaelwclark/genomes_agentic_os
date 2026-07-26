"""Canonical, schema-validated Execution Fabric instance configuration."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import socket
from typing import Any, Mapping

from jsonschema import Draft202012Validator
import yaml

from .scaffold import expand_path, repo_root
from .hosts import load_host_routing_policy, load_hosts
from .state.db import transaction, utc_now_iso


CONFIG_RELATIVE = Path("harness/config/execution-fabric.yml")
SCHEMA_RELATIVE = Path("schemas/execution-fabric.schema.json")
HOST_ROUTING_RELATIVE = Path("harness/registries/hosts-routing.yml")
ALERTS_RELATIVE = Path("harness/registries/alerts.yml")
SENSITIVE_KEY = re.compile(r"(?:^|_)(?:password|secret|token|credential|private_key)(?:$|_)", re.I)


class ExecutionFabricConfigError(ValueError):
    """Raised when the canonical instance configuration is invalid."""


@dataclass(frozen=True)
class EffectiveExecutionFabricConfig:
    value: dict[str, Any]
    source: Path
    source_kind: str
    schema: Path
    fingerprint: str
    layers: tuple[dict[str, Any], ...] = ()

    def provenance(self, root: str | Path) -> dict[str, Any]:
        os_root = expand_path(root)
        legacy_hosts = os_root / "config/hosts.yml"
        harness_hosts = os_root / "harness/config/hosts.yml"
        hosts_source = (
            legacy_hosts
            if legacy_hosts.exists() or not harness_hosts.exists()
            else harness_hosts
        )
        return {
            "source": str(self.source),
            "source_kind": self.source_kind,
            "schema": str(self.schema),
            "fingerprint": self.fingerprint,
            "host_id": resolve_execution_fabric_host_id(
                os_root,
                require_registered=False,
            ),
            "layers": [dict(layer) for layer in self.layers],
            "canonical_dependencies": {
                "host_identity": str(hosts_source),
                "host_routing": str(os_root / HOST_ROUTING_RELATIVE),
                "alerts": str(os_root / ALERTS_RELATIVE),
            },
        }


def _configured_host_ids(root: str | Path) -> tuple[set[str], set[str]]:
    """Return canonical identity and routing aliases without creating config."""
    try:
        host_ids = set(load_hosts(root))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise ExecutionFabricConfigError(
            f"canonical host identity registry is invalid: {exc}"
        ) from exc
    routing = load_host_routing_policy(root)
    routed = routing.get("hosts") if isinstance(routing, dict) else {}
    if routed is None:
        routed = {}
    if not isinstance(routed, dict):
        raise ExecutionFabricConfigError(
            "canonical host-routing registry hosts must be a mapping"
        )
    return host_ids, {str(alias) for alias in routed}


def _validate_registered_host(root: str | Path, host_id: str) -> str:
    identities, routed = _configured_host_ids(root)
    if not identities or not routed:
        raise ExecutionFabricConfigError(
            f"host {host_id!r} cannot activate Execution Fabric until both "
            "config/hosts.yml (or harness/config/hosts.yml) and "
            "harness/registries/hosts-routing.yml register it"
        )
    missing: list[str] = []
    if host_id not in identities:
        missing.append("host identity registry")
    if host_id not in routed:
        missing.append("host-routing registry")
    if missing:
        raise ExecutionFabricConfigError(
            f"Execution Fabric host {host_id!r} is missing from "
            + " and ".join(missing)
        )
    return host_id


def resolve_execution_fabric_host_id(
    root: str | Path,
    *,
    explicit: str | None = None,
    environ: dict[str, str] | None = None,
    require_registered: bool = True,
) -> str:
    """Resolve the one stable host ID shared by Python and Node activation."""
    environment = os.environ if environ is None else environ
    declared = {
        name: str(value).strip()
        for name, value in (
            ("explicit", explicit),
            ("FABRIC_HOST_ID", environment.get("FABRIC_HOST_ID")),
            ("AGENTIC_OS_HOST_ALIAS", environment.get("AGENTIC_OS_HOST_ALIAS")),
        )
        if value and str(value).strip()
    }
    unique = set(declared.values())
    if len(unique) > 1:
        rendered = ", ".join(f"{key}={value}" for key, value in sorted(declared.items()))
        raise ExecutionFabricConfigError(
            f"Execution Fabric host identity sources disagree: {rendered}"
        )
    host_id = next(iter(unique), socket.gethostname().split(".", 1)[0].lower())
    if re.fullmatch(r"[a-zA-Z0-9._:-]{1,128}", host_id) is None:
        raise ExecutionFabricConfigError(
            f"Execution Fabric host identity is invalid: {host_id!r}"
        )
    if require_registered:
        return _validate_registered_host(root, host_id)
    return host_id


def redact_execution_fabric_config(value: Any, *, key: str = "") -> Any:
    """Return a deterministic operator view with secret values removed."""
    if isinstance(value, dict):
        return {
            str(name): redact_execution_fabric_config(child, key=str(name))
            for name, child in value.items()
        }
    if isinstance(value, list):
        return [redact_execution_fabric_config(child, key=key) for child in value]
    if (
        key
        and not key.lower().endswith(("_env", "_file"))
        and SENSITIVE_KEY.search(key)
    ):
        return "<redacted>"
    return value


def _package_path(relative: Path) -> Path:
    return repo_root() / relative


def _source_path(root: str | Path) -> tuple[Path, str]:
    instance = expand_path(root) / CONFIG_RELATIVE
    if instance.is_file():
        return instance, "instance"
    shipped = _package_path(CONFIG_RELATIVE)
    if shipped.is_file():
        return shipped, "shipped_default"
    raise ExecutionFabricConfigError(
        f"execution-fabric configuration is missing: {instance}; reinstall the Agentic OS config assets"
    )


def _schema_path(root: str | Path) -> Path:
    installed = expand_path(root) / "harness/schemas/execution-fabric.schema.json"
    return installed if installed.is_file() else _package_path(SCHEMA_RELATIVE)


def _read_mapping(path: Path, *, label: str) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ExecutionFabricConfigError(f"{label} is unreadable: {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ExecutionFabricConfigError(f"{label} must be a YAML mapping: {path}")
    return loaded


def _merge_config(base: Any, override: Any) -> Any:
    """Merge config mappings and stable-id object arrays without positional drift."""
    if isinstance(base, dict) and isinstance(override, dict):
        merged = deepcopy(base)
        for key, value in override.items():
            merged[key] = (
                _merge_config(merged[key], value)
                if key in merged
                else deepcopy(value)
            )
        return merged
    if isinstance(base, list) and isinstance(override, list):
        rows = [*base, *override]
        stable_key = next(
            (
                candidate
                for candidate in ("id", "task_type")
                if all(
                    isinstance(row, dict) and row.get(candidate)
                    for row in rows
                )
            ),
            None,
        )
        if stable_key:
            by_id = {
                str(row[stable_key]): _merge_config({}, row)
                for row in base
                if isinstance(row, dict)
            }
            order = [
                str(row[stable_key]) for row in base if isinstance(row, dict)
            ]
            for row in override:
                row_id = str(row[stable_key])
                if row_id not in by_id:
                    order.append(row_id)
                    by_id[row_id] = {}
                by_id[row_id] = _merge_config(by_id[row_id], row)
            return [by_id[row_id] for row_id in order]
        return list(override)
    return override


def _validate_document(config: dict[str, Any], schema: dict[str, Any]) -> None:
    errors = sorted(
        Draft202012Validator(schema).iter_errors(config),
        key=lambda error: [str(part) for part in error.absolute_path],
    )
    if errors:
        first = errors[0]
        raise ExecutionFabricConfigError(
            f"invalid execution-fabric configuration at {_json_pointer(list(first.absolute_path))}: "
            f"{first.message}"
        )
    _validate_cross_references(config)


def _safety_caps(config: dict[str, Any]) -> dict[str, int]:
    fabric = config["execution_fabric"]
    admission = fabric["admission"]
    caps = {
        "admission.global_max_running": int(admission["global_max_running"]),
        "admission.max_interactive_running": int(admission["max_interactive_running"]),
    }
    caps.update(
        {
            f"admission.provider_limits.{provider}": int(limit)
            for provider, limit in admission["provider_limits"].items()
        }
    )
    for scope in ("namespace_limits", "host_limits"):
        caps.update(
            {
                f"admission.{scope}.{name}": int(limit)
                for name, limit in admission.get(scope, {}).items()
            }
        )
    for queue in fabric["queues"]:
        caps[f"queues.{queue['id']}.max_running"] = int(
            queue["concurrency"]["max_running"]
        )
        caps[f"queues.{queue['id']}.max_queued"] = int(
            queue["concurrency"]["max_queued"]
        )
    for pool in fabric["worker_pools"]:
        caps[f"worker_pools.{pool['id']}.max_workers"] = int(
            pool["capacity"]["max_workers"]
        )
        caps[f"worker_pools.{pool['id']}.max_tasks_per_worker"] = int(
            pool["capacity"]["max_tasks_per_worker"]
        )
        caps[f"worker_pools.{pool['id']}.max_attempts"] = int(
            pool["retry"]["max_attempts"]
        )
    return caps


def _assert_narrower_layer(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    layer: str,
) -> None:
    before_caps = _safety_caps(before)
    after_caps = _safety_caps(after)
    increased = sorted(
        key
        for key, value in after_caps.items()
        if key in before_caps and value > before_caps[key]
    )
    if increased:
        raise ExecutionFabricConfigError(
            f"{layer} override may tighten but not increase safety/capacity limits: "
            + ", ".join(increased)
        )


def _json_pointer(parts: list[Any]) -> str:
    return "/" + "/".join(str(part) for part in parts) if parts else "/"


def _validate_cross_references(config: dict[str, Any]) -> None:
    fabric = config["execution_fabric"]
    transport = fabric.get("transport") or {}
    if transport.get("mode", "local") in {"remote", "remote_with_local_fallback"} and not str(
        transport.get("control_plane_url") or ""
    ).strip():
        raise ExecutionFabricConfigError(
            "execution_fabric.transport.control_plane_url is required when mode is remote"
        )
    admission = fabric["admission"]
    if admission["reserved_interactive_slots"] >= admission["global_max_running"]:
        raise ExecutionFabricConfigError(
            "execution_fabric.admission.reserved_interactive_slots must be lower than global_max_running"
        )
    if admission["max_interactive_running"] > admission["global_max_running"]:
        raise ExecutionFabricConfigError(
            "execution_fabric.admission.max_interactive_running cannot exceed global_max_running"
        )
    priority_aging = fabric["scheduling"]["priority_aging"]
    if priority_aging["max_boost"] < priority_aging["boost_per_interval"]:
        raise ExecutionFabricConfigError(
            "execution_fabric.scheduling.priority_aging.max_boost must cover one boost interval"
        )

    queues = fabric["queues"]
    pools = fabric["worker_pools"]
    queue_ids = [str(row["id"]) for row in queues]
    pool_ids = [str(row["id"]) for row in pools]
    if len(queue_ids) != len(set(queue_ids)):
        raise ExecutionFabricConfigError("execution_fabric.queues ids must be unique")
    if len(pool_ids) != len(set(pool_ids)):
        raise ExecutionFabricConfigError("execution_fabric.worker_pools ids must be unique")
    queue_by_id = {str(row["id"]): row for row in queues}
    pool_by_id = {str(row["id"]): row for row in pools}
    for queue in queues:
        pool_id = str(queue["worker_pool"])
        if pool_id not in pool_by_id:
            raise ExecutionFabricConfigError(
                f"execution queue {queue['id']!r} references unknown worker pool {pool_id!r}"
            )
        if pool_by_id[pool_id]["queues"] != [queue["id"]]:
            raise ExecutionFabricConfigError(
                f"execution queue {queue['id']!r} and worker pool {pool_id!r} must reference each other"
            )
    for pool in pools:
        queue_id = str(pool["queues"][0])
        if queue_id not in queue_by_id:
            raise ExecutionFabricConfigError(
                f"worker pool {pool['id']!r} references unknown execution queue {queue_id!r}"
            )
    provider_limits = admission["provider_limits"]
    providers = {str(row["provider"]) for row in pools}
    unknown_limits = sorted(set(provider_limits) - providers)
    if unknown_limits:
        raise ExecutionFabricConfigError(
            "execution_fabric.admission.provider_limits references unknown providers: "
            + ", ".join(unknown_limits)
        )


def load_execution_fabric_config(
    root: str | Path,
    *,
    host_alias: str | None = None,
    environ: Mapping[str, str] | None = None,
    invocation_overrides: dict[str, Any] | None = None,
) -> EffectiveExecutionFabricConfig:
    """Load, validate, and fingerprint the one effective instance config."""
    source, source_kind = _source_path(root)
    schema_path = _schema_path(root)
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutionFabricConfigError(
            f"execution-fabric schema is unreadable: {schema_path}: {exc}"
        ) from exc
    release_source = _package_path(CONFIG_RELATIVE)
    release = _read_mapping(release_source, label="execution-fabric release defaults")
    instance = _read_mapping(source, label="execution-fabric configuration")
    instance_fabric = dict(instance.get("execution_fabric") or {})
    host_overrides = instance_fabric.pop("host_overrides", {}) or {}
    if not isinstance(host_overrides, dict):
        raise ExecutionFabricConfigError(
            "execution_fabric.host_overrides must be a mapping keyed by canonical host alias"
        )
    instance = {**instance, "execution_fabric": instance_fabric}
    config = (
        release
        if source.resolve(strict=False) == release_source.resolve(strict=False)
        else _merge_config(release, instance)
    )
    _validate_document(config, schema)
    if host_overrides:
        identities, routed = _configured_host_ids(root)
        for configured_host in host_overrides:
            host_name = str(configured_host)
            if host_name not in identities or host_name not in routed:
                raise ExecutionFabricConfigError(
                    f"execution_fabric.host_overrides.{host_name} must reference "
                    "the same alias in the canonical host identity and host-routing registries"
                )
    for configured_host, configured_override in host_overrides.items():
        host_name = str(configured_host)
        if not re.fullmatch(r"[a-zA-Z0-9._:-]{1,128}", host_name):
            raise ExecutionFabricConfigError(
                f"execution_fabric.host_overrides has invalid host alias {host_name!r}"
            )
        if not isinstance(configured_override, dict):
            raise ExecutionFabricConfigError(
                f"execution_fabric.host_overrides.{host_name} must be a mapping"
            )
        configured_candidate = _merge_config(
            config,
            {"execution_fabric": configured_override},
        )
        _validate_document(configured_candidate, schema)
        _assert_narrower_layer(
            config,
            configured_candidate,
            layer=f"host {host_name}",
        )
    layers: list[dict[str, Any]] = [
        {"kind": "release_default", "source": str(release_source)}
    ]
    if source_kind == "instance":
        layers.append({"kind": "instance", "source": str(source)})

    selected_host = ""
    environment = os.environ if environ is None else environ
    if host_alias or environment.get("FABRIC_HOST_ID") or environment.get(
        "AGENTIC_OS_HOST_ALIAS"
    ):
        selected_host = resolve_execution_fabric_host_id(
            root,
            explicit=host_alias,
            environ=environment,
            require_registered=True,
        )
    if selected_host:
        host_override = host_overrides.get(selected_host)
        if host_override is not None:
            if not isinstance(host_override, dict):
                raise ExecutionFabricConfigError(
                    f"execution_fabric.host_overrides.{selected_host} must be a mapping"
                )
            candidate = _merge_config(
                config,
                {"execution_fabric": host_override},
            )
            _validate_document(candidate, schema)
            _assert_narrower_layer(config, candidate, layer=f"host {selected_host}")
            config = candidate
            layers.append({"kind": "host", "host_alias": selected_host})
    if invocation_overrides:
        if not isinstance(invocation_overrides, dict):
            raise ExecutionFabricConfigError("invocation overrides must be a mapping")
        candidate = _merge_config(
            config,
            {"execution_fabric": invocation_overrides},
        )
        _validate_document(candidate, schema)
        _assert_narrower_layer(config, candidate, layer="invocation")
        config = candidate
        layers.append({"kind": "invocation"})
    normalized = json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return EffectiveExecutionFabricConfig(
        value=config,
        source=source,
        source_kind=source_kind,
        schema=schema_path,
        fingerprint=sha256(normalized.encode("utf-8")).hexdigest(),
        layers=tuple(layers),
    )


def validate_execution_fabric_config(root: str | Path) -> dict[str, Any]:
    """Return a structured validation and provenance report."""
    effective = load_execution_fabric_config(root)
    fabric = effective.value["execution_fabric"]
    transport = {
        "mode": "local",
        "control_plane_url": None,
        "request_timeout_seconds": 20,
        "long_poll_seconds": 20,
        "submit_token_env": "AGENTIC_OS_EXECUTION_FABRIC_SUBMIT_TOKEN",
        "worker_token_env": "AGENTIC_OS_EXECUTION_FABRIC_WORKER_TOKEN",
        "observer_token_env": "AGENTIC_OS_EXECUTION_FABRIC_OBSERVER_TOKEN",
        "admin_token_env": "AGENTIC_OS_EXECUTION_FABRIC_ADMIN_TOKEN",
        **(fabric.get("transport") or {}),
    }
    return {
        "ok": True,
        **effective.provenance(root),
        "transport": transport,
        "queue_count": len(fabric["queues"]),
        "worker_pool_count": len(fabric["worker_pools"]),
        "provider_limit_count": len(fabric["admission"]["provider_limits"]),
        "findings": [],
    }


def show_execution_fabric_config(root: str | Path) -> dict[str, Any]:
    """Return the redacted effective document with complete provenance."""
    effective = load_execution_fabric_config(root)
    return {
        "ok": True,
        "root": str(expand_path(root)),
        **effective.provenance(root),
        "effective": redact_execution_fabric_config(effective.value),
    }


def _desired_rows(effective: EffectiveExecutionFabricConfig) -> dict[str, Any]:
    fabric = effective.value["execution_fabric"]
    queues: dict[str, dict[str, Any]] = {}
    for row in fabric["queues"]:
        concurrency = row["concurrency"]
        queues[str(row["id"])] = {
            "name": str(row["id"]),
            "max_concurrency": int(concurrency["max_running"]),
            "enabled": bool(row["enabled"]),
            "metadata": {
                "accepted_task_types": list(row["accepted_task_types"]),
                "max_queued": int(concurrency["max_queued"]),
                "priority": int(row["priority"]),
                "config_fingerprint": effective.fingerprint,
            },
        }
    pools: dict[str, dict[str, Any]] = {}
    for row in fabric["worker_pools"]:
        capacity = row["capacity"]
        pools[str(row["id"])] = {
            "name": str(row["id"]),
            "queue_name": str(row["queues"][0]),
            "max_workers": int(capacity["max_workers"]),
            "max_concurrency": int(capacity["max_workers"])
            * int(capacity["max_tasks_per_worker"]),
            "provider": str(row["provider"]),
            "enabled": bool(row["enabled"]),
            "metadata": {
                "lease": dict(row["lease"]),
                "retry": dict(row["retry"]),
                "min_workers": int(capacity["min_workers"]),
                "max_tasks_per_worker": int(capacity["max_tasks_per_worker"]),
                "config_fingerprint": effective.fingerprint,
            },
        }
    admission = fabric["admission"]
    background_max = int(admission["global_max_running"]) - int(
        admission["reserved_interactive_slots"]
    )
    limits = {
        ("global", "*"): background_max,
        **{
            ("provider", str(provider)): int(limit)
            for provider, limit in admission["provider_limits"].items()
        },
    }
    return {
        "queues": queues,
        "worker_pools": pools,
        "limits": limits,
        "admission": {
            "global_max_running": int(admission["global_max_running"]),
            "reserved_interactive_slots": int(admission["reserved_interactive_slots"]),
            "max_interactive_running": int(admission["max_interactive_running"]),
            "background_max_running": background_max,
        },
    }


def _decode_metadata(value: str | None) -> dict[str, Any]:
    try:
        loaded = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def catalog_diff(
    conn: sqlite3.Connection,
    effective: EffectiveExecutionFabricConfig,
) -> list[dict[str, Any]]:
    """Return deterministic differences between desired config and runtime state."""
    desired = _desired_rows(effective)
    changes: list[dict[str, Any]] = []
    actual_queues = {
        str(row["name"]): dict(row)
        for row in conn.execute("SELECT * FROM execution_queues ORDER BY name").fetchall()
    }
    for name, expected in desired["queues"].items():
        actual = actual_queues.get(name)
        comparable = None if actual is None else {
            "name": name,
            "max_concurrency": int(actual["max_concurrency"]),
            "enabled": bool(actual["enabled"]),
            "metadata": _decode_metadata(actual["metadata_json"]),
        }
        if comparable != expected:
            changes.append({"kind": "queue", "id": name, "action": "create" if actual is None else "update"})
    for name, actual in actual_queues.items():
        if name not in desired["queues"] and bool(actual["enabled"]):
            changes.append({"kind": "queue", "id": name, "action": "disable"})

    actual_pools = {
        str(row["name"]): dict(row)
        for row in conn.execute("SELECT * FROM worker_pools ORDER BY name").fetchall()
    }
    for name, expected in desired["worker_pools"].items():
        actual = actual_pools.get(name)
        comparable = None if actual is None else {
            "name": name,
            "queue_name": str(actual["queue_name"]),
            "max_workers": int(actual["max_workers"]),
            "max_concurrency": int(actual["max_concurrency"]),
            "provider": str(actual["provider"] or ""),
            "enabled": bool(actual["enabled"]),
            "metadata": _decode_metadata(actual["metadata_json"]),
        }
        if comparable != expected:
            changes.append(
                {"kind": "worker_pool", "id": name, "action": "create" if actual is None else "update"}
            )
    for name, actual in actual_pools.items():
        if name not in desired["worker_pools"] and bool(actual["enabled"]):
            changes.append({"kind": "worker_pool", "id": name, "action": "disable"})

    actual_limits = {
        (str(row["scope"]), str(row["key"])): int(row["max_concurrency"])
        for row in conn.execute("SELECT scope, key, max_concurrency FROM execution_limits").fetchall()
    }
    for key, value in desired["limits"].items():
        if actual_limits.get(key) != value:
            changes.append(
                {
                    "kind": "limit",
                    "id": f"{key[0]}:{key[1]}",
                    "action": "create" if key not in actual_limits else "update",
                }
            )
    for key in sorted(set(actual_limits) - set(desired["limits"])):
        changes.append({"kind": "limit", "id": f"{key[0]}:{key[1]}", "action": "remove"})
    return changes


def reconcile_catalog(
    conn: sqlite3.Connection,
    effective: EffectiveExecutionFabricConfig,
) -> dict[str, Any]:
    """Atomically reconcile queue, pool, limit, retry, and lease configuration."""
    desired = _desired_rows(effective)
    changes = catalog_diff(conn, effective)
    if not changes:
        return {**desired["admission"], "changes": [], "reconciled": False}
    now = utc_now_iso()
    with transaction(conn):
        for row in desired["queues"].values():
            conn.execute(
                """
                INSERT INTO execution_queues
                    (name, max_concurrency, enabled, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    max_concurrency = excluded.max_concurrency,
                    enabled = excluded.enabled,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    row["name"],
                    row["max_concurrency"],
                    int(row["enabled"]),
                    json.dumps(row["metadata"], sort_keys=True),
                    now,
                    now,
                ),
            )
        for row in desired["worker_pools"].values():
            active_on_other_queue = conn.execute(
                """
                SELECT COUNT(*) FROM run_queue
                WHERE worker_pool = ? AND status = 'running' AND queue_name != ?
                """,
                (row["name"], row["queue_name"]),
            ).fetchone()[0]
            if active_on_other_queue:
                raise ExecutionFabricConfigError(
                    f"worker pool {row['name']!r} cannot change queue while it owns running tasks"
                )
            conn.execute(
                """
                INSERT INTO worker_pools (
                    name, queue_name, max_workers, max_concurrency, provider, enabled,
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    queue_name = excluded.queue_name,
                    max_workers = excluded.max_workers,
                    max_concurrency = excluded.max_concurrency,
                    provider = excluded.provider,
                    enabled = excluded.enabled,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    row["name"],
                    row["queue_name"],
                    row["max_workers"],
                    row["max_concurrency"],
                    row["provider"],
                    int(row["enabled"]),
                    json.dumps(row["metadata"], sort_keys=True),
                    now,
                    now,
                ),
            )
        queue_names = tuple(desired["queues"])
        pool_names = tuple(desired["worker_pools"])
        if queue_names:
            conn.execute(
                f"UPDATE execution_queues SET enabled = 0, updated_at = ? "
                f"WHERE name NOT IN ({','.join('?' for _ in queue_names)})",
                (now, *queue_names),
            )
        if pool_names:
            conn.execute(
                f"UPDATE worker_pools SET enabled = 0, updated_at = ? "
                f"WHERE name NOT IN ({','.join('?' for _ in pool_names)})",
                (now, *pool_names),
            )
        for (scope, key), max_concurrency in desired["limits"].items():
            conn.execute(
                """
                INSERT INTO execution_limits
                    (scope, key, max_concurrency, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(scope, key) DO UPDATE SET
                    max_concurrency = excluded.max_concurrency,
                    updated_at = excluded.updated_at
                """,
                (scope, key, max_concurrency, now, now),
            )
        desired_limit_keys = set(desired["limits"])
        for row in conn.execute("SELECT scope, key FROM execution_limits").fetchall():
            key = (str(row["scope"]), str(row["key"]))
            if key not in desired_limit_keys:
                conn.execute("DELETE FROM execution_limits WHERE scope = ? AND key = ?", key)
    return {**desired["admission"], "changes": changes, "reconciled": True}
