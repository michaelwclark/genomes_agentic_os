from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

from genomes_agentic_os import execution_fabric_worker as worker
from genomes_agentic_os.runtime_ops import runtime_init


def _seed_runtime(root: Path) -> None:
    path = root / "harness/config/execution-fabric.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "execution_fabric": {
                    "transport": {
                        "mode": "local",
                        "control_plane_url": None,
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def test_bootstrap_writes_only_portable_instance_routing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(worker, "runtime_init", _seed_runtime)
    monkeypatch.setenv("FABRIC_HOST_ID", "los-agents-1")
    monkeypatch.setenv("FABRIC_API_BASE", "https://fabric.example.test/")
    monkeypatch.setenv("FABRIC_WORKER_MAX_CONCURRENCY", "3")

    worker.bootstrap(tmp_path)

    config = yaml.safe_load(
        (tmp_path / "harness/config/execution-fabric.yml").read_text(
            encoding="utf-8"
        )
    )
    transport = config["execution_fabric"]["transport"]
    assert transport["mode"] == "remote"
    assert transport["control_plane_url"] == "https://fabric.example.test"
    assert (
        transport["worker_token_env"]
        == "AGENTIC_OS_EXECUTION_FABRIC_WORKER_TOKEN"
    )
    hosts = yaml.safe_load(
        (tmp_path / "config/hosts.yml").read_text(encoding="utf-8")
    )
    routing = yaml.safe_load(
        (tmp_path / "harness/registries/hosts-routing.yml").read_text(
            encoding="utf-8"
        )
    )
    assert list(hosts["hosts"]) == ["los-agents-1"]
    assert routing["hosts"]["los-agents-1"]["max_concurrent"] == 3


def test_installed_host_preparation_preserves_canonical_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    policy = tmp_path / "harness/config/execution-fabric.yml"
    routing = tmp_path / "harness/registries/hosts-routing.yml"
    hosts = tmp_path / "harness/config/hosts.yml"
    for path, content in (
        (policy, "policy-sentinel\n"),
        (routing, "routing-sentinel\n"),
        (hosts, "hosts-sentinel\n"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    observed: dict[str, object] = {}

    def load(root: Path, *, environ: object) -> object:
        observed.update({"root": root, "environ": environ})
        return object()

    monkeypatch.setattr(worker, "load_execution_fabric_config", load)
    monkeypatch.setattr(
        worker,
        "bootstrap",
        lambda root: (_ for _ in ()).throw(AssertionError("portable bootstrap ran")),
    )
    monkeypatch.setenv("FABRIC_WORKER_ROOT_MODE", "installed_host")

    worker.prepare_root(tmp_path)

    assert observed["root"] == tmp_path
    assert policy.read_text(encoding="utf-8") == "policy-sentinel\n"
    assert routing.read_text(encoding="utf-8") == "routing-sentinel\n"
    assert hosts.read_text(encoding="utf-8") == "hosts-sentinel\n"


def test_host_worker_routes_client_through_explicit_gateway(
    tmp_path: Path,
    monkeypatch,
) -> None:
    observed: dict[str, object] = {}
    gateway = "http://100.117.29.53:3181"
    for name, value in {
        "AGENTIC_OS_ROOT": str(tmp_path),
        "FABRIC_API_BASE": gateway,
        "FABRIC_WORKER_ID": "bigmac-pr-reviewer-1",
        "FABRIC_WORKER_BOOTSTRAP_ID": "bigmac-pr-reviewer-1",
        "FABRIC_HOST_ID": "bigmac",
        "FABRIC_WORKER_ACCEPTED_QUEUES": "pr_reviews",
        "FABRIC_WORKER_CAPABILITIES": "pr_review",
        "FABRIC_WORKER_MAX_CONCURRENCY": "2",
    }.items():
        monkeypatch.setenv(name, value)

    monkeypatch.setattr(worker, "prepare_root", lambda _root: None)
    monkeypatch.setattr(worker, "validate_worker_routes", lambda *_args: [])

    settings = object()

    def resolve(root: Path, *, role: str, endpoint_override: str) -> object:
        observed.update(
            {"root": root, "role": role, "endpoint_override": endpoint_override}
        )
        return settings

    monkeypatch.setattr(worker, "resolve_remote_settings", resolve)
    monkeypatch.setattr(
        worker,
        "ExecutionFabricClient",
        lambda value: observed.update({"client_settings": value}) or object(),
    )

    class FakeWorker:
        def __init__(self, _client: object, **_kwargs: object) -> None:
            pass

        def work(self) -> dict[str, bool]:
            return {"failed": False}

    monkeypatch.setattr(worker, "RemoteFabricWorker", FakeWorker)

    assert worker.main([]) == 0
    assert observed == {
        "root": tmp_path,
        "role": "worker",
        "endpoint_override": gateway,
        "client_settings": settings,
    }


def test_healthcheck_uses_current_worker_receipt_and_heartbeat_age(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("FABRIC_WORKER_ID", "worker-one")
    monkeypatch.setenv("FABRIC_WORKER_HEARTBEAT_SECONDS", "15")
    path = (
        tmp_path
        / "harness/shared_factory/06-runs-and-logs/execution-fabric/worker-health"
        / "worker-one.json"
    )
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"status": "online"}), encoding="utf-8")

    assert worker.healthcheck(tmp_path) == 0
    path.write_text(json.dumps({"status": "stopped"}), encoding="utf-8")
    assert worker.healthcheck(tmp_path) == 1
    path.write_text(json.dumps({"status": "online"}), encoding="utf-8")
    os.utime(path, (0, 0))
    assert worker.healthcheck(tmp_path) == 1


def test_worker_image_route_smoke_accepts_shipped_generic_handler(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    root = tmp_path / "agentic-os"
    runtime_init(root)
    monkeypatch.setenv("AGENTIC_OS_ROOT", str(root))
    monkeypatch.setenv("FABRIC_WORKER_ACCEPTED_QUEUES", "codex")
    monkeypatch.setenv("FABRIC_WORKER_CAPABILITIES", "codex.task")

    assert worker.main(["--validate-routes"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["routes"] == [
        {
            "domain_worker": "codex_task",
            "queue": "codex",
            "task_type": "llm.codex",
        }
    ]
