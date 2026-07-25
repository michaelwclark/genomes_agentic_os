"""Portable Kubernetes/OCI entrypoint for a commandless Execution Fabric worker."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time

import yaml

from .execution_fabric_remote import (
    ExecutionFabricClient,
    RemoteFabricWorker,
    resolve_remote_settings,
    validate_worker_routes,
)
from .runtime_ops import runtime_init


def _required(name: str) -> str:
    value = str(os.environ.get(name) or "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _csv(name: str) -> list[str]:
    values = [value.strip() for value in _required(name).split(",")]
    if not all(values):
        raise ValueError(f"{name} contains an empty value")
    return list(dict.fromkeys(values))


def _write_yaml(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        yaml.safe_dump(value, sort_keys=False),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def bootstrap(root: Path) -> None:
    """Install immutable defaults, then write only pod-local instance routing."""
    runtime_init(root)
    host_id = _required("FABRIC_HOST_ID")
    api_base = _required("FABRIC_API_BASE").rstrip("/")
    config_path = root / "harness/config/execution-fabric.yml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    transport = config["execution_fabric"]["transport"]
    transport.update(
        {
            "mode": "remote",
            "control_plane_url": api_base,
            "submit_token_env": "AGENTIC_OS_EXECUTION_FABRIC_SUBMIT_TOKEN",
            "worker_token_env": "AGENTIC_OS_EXECUTION_FABRIC_WORKER_TOKEN",
            "observer_token_env": "AGENTIC_OS_EXECUTION_FABRIC_OBSERVER_TOKEN",
            "admin_token_env": "AGENTIC_OS_EXECUTION_FABRIC_ADMIN_TOKEN",
        }
    )
    _write_yaml(config_path, config)
    _write_yaml(
        root / "config/hosts.yml",
        {"hosts": {host_id: {"description": "OCI Execution Fabric worker"}}},
    )
    _write_yaml(
        root / "harness/registries/hosts-routing.yml",
        {
            "hosts": {
                host_id: {
                    "role": "worker",
                    "max_concurrent": int(
                        os.environ.get("FABRIC_WORKER_MAX_CONCURRENCY", "1")
                    ),
                    "harnesses": ["claude", "gpt"],
                    "project_paths": {},
                    "path_rewrite": [],
                }
            }
        },
    )


def healthcheck(root: Path) -> int:
    worker_id = _required("FABRIC_WORKER_ID")
    path = (
        root
        / "harness/shared_factory/06-runs-and-logs/execution-fabric/worker-health"
        / f"{worker_id}.json"
    )
    if not path.is_file():
        return 1
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        age_seconds = time.time() - path.stat().st_mtime
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return 1
    max_age = max(
        30,
        int(os.environ.get("FABRIC_WORKER_HEARTBEAT_SECONDS", "15")) * 3,
    )
    return 0 if value.get("status") == "online" and age_seconds <= max_age else 1


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(os.environ.get("AGENTIC_OS_ROOT", "/var/lib/agentic-os")).resolve()
    if args == ["--healthcheck"]:
        return healthcheck(root)
    if args == ["--validate-routes"]:
        runtime_init(root)
        routes = validate_worker_routes(
            root,
            _csv("FABRIC_WORKER_ACCEPTED_QUEUES"),
            _csv("FABRIC_WORKER_CAPABILITIES"),
        )
        print(json.dumps({"status": "valid", "routes": routes}, sort_keys=True))
        return 0
    bootstrap(root)
    settings = resolve_remote_settings(root, role="worker")
    queues = _csv("FABRIC_WORKER_ACCEPTED_QUEUES")
    capabilities = _csv("FABRIC_WORKER_CAPABILITIES")
    validate_worker_routes(root, queues, capabilities)
    worker = RemoteFabricWorker(
        ExecutionFabricClient(settings),
        root=root,
        worker_id=_required("FABRIC_WORKER_ID"),
        bootstrap_id=_required("FABRIC_WORKER_BOOTSTRAP_ID"),
        host_id=_required("FABRIC_HOST_ID"),
        queues=queues,
        capabilities=capabilities,
        max_concurrency=int(_required("FABRIC_WORKER_MAX_CONCURRENCY")),
        heartbeat_seconds=int(
            os.environ.get("FABRIC_WORKER_HEARTBEAT_SECONDS", "15")
        ),
        spool_drain_seconds=int(
            os.environ.get("FABRIC_WORKER_SPOOL_DRAIN_SECONDS", "30")
        ),
    )
    result = worker.work()
    print(json.dumps(result, sort_keys=True))
    return 0 if not result.get("failed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
