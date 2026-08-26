from __future__ import annotations

import json
import hashlib
from pathlib import Path
import shutil

import pytest
import yaml

from genomes_agentic_os import execution_fabric_remote
from genomes_agentic_os.cli import main
from genomes_agentic_os.execution_fabric_config import (
    ExecutionFabricConfigError,
    load_execution_fabric_config,
    resolve_execution_fabric_host_id,
)
from genomes_agentic_os.execution_fabric_remote import TEAM_PR_HELPER_STALE_SECONDS
from genomes_agentic_os.runtime_backend import (
    RuntimeBackendError,
    apply_queue_mode,
    execution_fabric_config_status,
    reconcile_execution_fabric_configuration,
)
from genomes_agentic_os.scaffold import install_docs
from genomes_agentic_os.state import db
from genomes_agentic_os.state import execution_fabric as fabric_state


SOURCE_ROOT = Path(__file__).parents[1]


def _root(tmp_path: Path, *, install_config: bool = True) -> Path:
    root = tmp_path / "agentic_os"
    control = root / "harness/shared_factory/00-control-plane"
    control.mkdir(parents=True)
    (control / "runtime-registry.yml").write_text(
        yaml.safe_dump({"version": "0.1.0", "execution_targets": []}, sort_keys=False),
        encoding="utf-8",
    )
    (control / "run-queue.yml").write_text(
        yaml.safe_dump({"version": "0.1.0", "items": []}, sort_keys=False),
        encoding="utf-8",
    )
    if install_config:
        config = root / "harness/config/execution-fabric.yml"
        config.parent.mkdir(parents=True)
        shutil.copy2(SOURCE_ROOT / "harness/config/execution-fabric.yml", config)
    return root


def _edit(root: Path) -> dict:
    path = root / "harness/config/execution-fabric.yml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    fabric = loaded["execution_fabric"]
    fabric["admission"].update(
        {
            "global_max_running": 7,
            "reserved_interactive_slots": 2,
            "max_interactive_running": 2,
        }
    )
    fabric["admission"]["provider_limits"]["codex"] = 1
    codex_queue = next(row for row in fabric["queues"] if row["id"] == "codex")
    codex_queue["enabled"] = False
    codex_queue["concurrency"] = {"max_running": 1, "max_queued": 7}
    codex_pool = next(row for row in fabric["worker_pools"] if row["id"] == "codex_workers")
    codex_pool["enabled"] = False
    codex_pool["capacity"] = {
        "min_workers": 0,
        "max_workers": 1,
        "max_tasks_per_worker": 1,
    }
    codex_pool["lease"] = {"timeout_seconds": 600, "heartbeat_seconds": 20}
    codex_pool["retry"] = {"max_attempts": 4, "backoff_seconds": 17}
    path.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")
    return loaded


def _install_hosts(root: Path) -> None:
    identity = root / "config/hosts.yml"
    identity.parent.mkdir(parents=True, exist_ok=True)
    identity.write_text(
        yaml.safe_dump(
            {
                "hosts": {
                    "genomesbox": {"ssh_alias": "genomesbox"},
                    "bigmac": {"ssh_alias": "bigmac"},
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    routing = root / "harness/registries/hosts-routing.yml"
    routing.parent.mkdir(parents=True, exist_ok=True)
    routing.write_text(
        yaml.safe_dump(
            {
                "hosts": {
                    "genomesbox": {"role": "primary"},
                    "bigmac": {"role": "standby"},
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_docs_install_additively_delivers_and_preserves_instance_config(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    target = root / "harness/config/execution-fabric.yml"

    install_docs(root)
    assert target.is_file()
    assert load_execution_fabric_config(root).source_kind == "instance"

    target.write_text("locally: preserved\n", encoding="utf-8")
    install_docs(root)
    assert target.read_text(encoding="utf-8") == "locally: preserved\n"


def test_schema_manifest_upgrades_managed_files_and_preserves_local_overrides(
    tmp_path: Path,
) -> None:
    root = tmp_path / "agentic_os"
    install_docs(root)
    schema = root / "harness/schemas/execution-fabric.schema.json"
    manifest = root / "harness/schemas/package-manifest.yml"
    assert manifest.is_file()

    old = b'{"managed":"old"}\n'
    schema.write_bytes(old)
    payload = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    entry = next(
        row
        for row in payload["entries"]
        if row["destination"] == "harness/schemas/execution-fabric.schema.json"
    )
    entry["managed_checksum"] = "sha256:" + hashlib.sha256(old).hexdigest()
    entry["observed_checksum"] = entry["managed_checksum"]
    manifest.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    install_docs(root)
    assert schema.read_bytes() == (
        SOURCE_ROOT / "schemas/execution-fabric.schema.json"
    ).read_bytes()

    schema.write_text('{"operator":"override"}\n', encoding="utf-8")
    install_docs(root)
    assert schema.read_text(encoding="utf-8") == '{"operator":"override"}\n'
    assert schema.with_name("execution-fabric.schema.json.new").read_bytes() == (
        SOURCE_ROOT / "schemas/execution-fabric.schema.json"
    ).read_bytes()


def test_effective_config_reports_source_fingerprint_and_canonical_dependencies(tmp_path: Path) -> None:
    root = _root(tmp_path)
    first = execution_fabric_config_status(root)

    assert first["ok"] is True
    assert first["source_kind"] == "instance"
    assert first["transport"]["mode"] == "local"
    assert first["transport"]["submit_token_env"] == (
        "AGENTIC_OS_EXECUTION_FABRIC_SUBMIT_TOKEN"
    )
    assert first["transport"]["worker_token_env"] == (
        "AGENTIC_OS_EXECUTION_FABRIC_WORKER_TOKEN"
    )
    assert first["transport"]["observer_token_env"] == (
        "AGENTIC_OS_EXECUTION_FABRIC_OBSERVER_TOKEN"
    )
    assert first["source"].endswith("harness/config/execution-fabric.yml")
    assert len(first["fingerprint"]) == 64
    assert first["canonical_dependencies"]["host_identity"].endswith("config/hosts.yml")
    assert first["canonical_dependencies"]["host_routing"].endswith(
        "harness/registries/hosts-routing.yml"
    )
    assert first["canonical_dependencies"]["alerts"].endswith("harness/registries/alerts.yml")
    pr_review_pool = next(
        pool
        for pool in load_execution_fabric_config(root).value["execution_fabric"][
            "worker_pools"
        ]
        if pool["id"] == "pr_reviewers"
    )
    assert pr_review_pool["capacity"]["max_tasks_per_worker"] == 2
    assert pr_review_pool["retry"] == {"max_attempts": 9, "backoff_seconds": 600}
    assert (
        pr_review_pool["lease"]["timeout_seconds"]
        + pr_review_pool["retry"]["backoff_seconds"]
        > TEAM_PR_HELPER_STALE_SECONDS
    )
    assert (
        (pr_review_pool["retry"]["max_attempts"] - 1)
        * pr_review_pool["retry"]["backoff_seconds"]
        > TEAM_PR_HELPER_STALE_SECONDS
    )
    team_pr_route = next(
        route
        for route in load_execution_fabric_config(root).value["execution_fabric"][
            "task_routes"
        ]
        if route["task_type"] == "los.team_pr.ai_review.v1"
    )
    assert team_pr_route["execution"]["allowed_host_ids"] == ["bigmac"]
    assert team_pr_route["payload"]["properties"]["retry_nonce"] == {
        "type": "string",
        "pattern": "^[a-f0-9]{12}$",
    }
    assert execution_fabric_remote._eligible_worker_queues(
        root, "bigmac", ["pr_reviews"]
    ) == ["pr_reviews"]
    assert execution_fabric_remote._eligible_worker_queues(
        root, "genomesbox", ["pr_reviews"]
    ) == []
    fullsail_pool = next(
        pool
        for pool in load_execution_fabric_config(root).value["execution_fabric"][
            "worker_pools"
        ]
        if pool["id"] == "los_fullsail_workers"
    )
    assert (
        fullsail_pool["lease"]["timeout_seconds"]
        > execution_fabric_remote.FULLSAIL_CONTROLLER_TIMEOUT_SECONDS
    )
    fullsail_route = next(
        route
        for route in load_execution_fabric_config(root).value["execution_fabric"][
            "task_routes"
        ]
        if route["task_type"] == "los.fullsail_updater.job.v1"
    )
    assert fullsail_route["execution"]["allowed_host_ids"] == ["bigmac"]
    assert execution_fabric_remote._eligible_worker_queues(
        root, "bigmac", ["los_fullsail"]
    ) == ["los_fullsail"]
    assert execution_fabric_remote._eligible_worker_queues(
        root, "genomesbox", ["los_fullsail"]
    ) == []

    _edit(root)
    second = execution_fabric_config_status(root)
    assert second["fingerprint"] != first["fingerprint"]


def test_schema_and_cross_reference_validation_are_strict(tmp_path: Path) -> None:
    root = _root(tmp_path)
    path = root / "harness/config/execution-fabric.yml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    loaded["execution_fabric"]["queues"][0]["worker_pool"] = "missing_pool"
    path.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")

    with pytest.raises(ExecutionFabricConfigError, match="unknown worker pool"):
        load_execution_fabric_config(root)


def test_standalone_primary_requires_explicit_exact_host_config(tmp_path: Path) -> None:
    root = _root(tmp_path)
    path = root / "harness/config/execution-fabric.yml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    loaded["execution_fabric"]["standalone_primary"] = {
        "enabled": True,
        "host_id": "genomesbox",
    }
    path.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")
    effective = load_execution_fabric_config(root)
    assert effective.value["execution_fabric"]["standalone_primary"] == {
        "enabled": True,
        "host_id": "genomesbox",
    }

    loaded["execution_fabric"]["standalone_primary"]["unexpected"] = True
    path.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")
    with pytest.raises(ExecutionFabricConfigError, match="Additional properties"):
        load_execution_fabric_config(root)


def test_effective_config_applies_host_and_invocation_overrides_by_stable_id(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    _install_hosts(root)
    path = root / "harness/config/execution-fabric.yml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    loaded["execution_fabric"]["host_overrides"] = {
        "bigmac": {
            "admission": {"global_max_running": 5},
            "queues": [
                {"id": "codex", "concurrency": {"max_running": 1, "max_queued": 50}}
            ],
        }
    }
    path.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")

    effective = load_execution_fabric_config(
        root,
        host_alias="bigmac",
        invocation_overrides={
            "admission": {"global_max_running": 4},
            "task_routes": [
                {
                    "task_type": "los.team_pr.ai_review.v1",
                    "scheduling_class": "background",
                }
            ],
            "worker_pools": [
                {
                    "id": "codex_workers",
                    "capacity": {
                        "min_workers": 0,
                        "max_workers": 1,
                        "max_tasks_per_worker": 1,
                    },
                }
            ],
        },
    )
    fabric = effective.value["execution_fabric"]
    codex = next(row for row in fabric["queues"] if row["id"] == "codex")
    codex_pool = next(
        row for row in fabric["worker_pools"] if row["id"] == "codex_workers"
    )
    team_route = next(
        row
        for row in fabric["task_routes"]
        if row["task_type"] == "los.team_pr.ai_review.v1"
    )

    assert fabric["admission"]["global_max_running"] == 4
    assert codex["concurrency"] == {"max_running": 1, "max_queued": 50}
    assert codex_pool["capacity"]["max_workers"] == 1
    assert team_route["scheduling_class"] == "background"
    assert team_route["execution"]["domain_worker"] == "team_pr_ai_review"
    assert {row["task_type"] for row in fabric["task_routes"]} >= {
        "llm.codex",
        "los.team_pr.ai_review.v1",
        "los.environment.deployment.observed",
    }
    assert "host_overrides" not in fabric
    assert [layer["kind"] for layer in effective.layers] == [
        "release_default",
        "instance",
        "host",
        "invocation",
    ]


def test_host_and_invocation_overrides_cannot_increase_capacity(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _install_hosts(root)
    path = root / "harness/config/execution-fabric.yml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    loaded["execution_fabric"]["host_overrides"] = {
        "bigmac": {"admission": {"global_max_running": 99}}
    }
    path.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")

    with pytest.raises(ExecutionFabricConfigError, match="may tighten"):
        load_execution_fabric_config(root, host_alias="bigmac")
    with pytest.raises(ExecutionFabricConfigError, match="may tighten"):
        load_execution_fabric_config(root, host_alias="genomesbox")
    with pytest.raises(ExecutionFabricConfigError, match="may tighten"):
        load_execution_fabric_config(
            root,
            invocation_overrides={"admission": {"global_max_running": 99}},
        )


def test_host_overlay_requires_same_canonical_identity_and_routing_alias(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    _install_hosts(root)
    routing = root / "harness/registries/hosts-routing.yml"
    routing.write_text(
        yaml.safe_dump({"hosts": {"genomesbox": {"role": "primary"}}}),
        encoding="utf-8",
    )
    config = yaml.safe_load(
        (root / "harness/config/execution-fabric.yml").read_text(encoding="utf-8")
    )
    config["execution_fabric"]["host_overrides"] = {
        "bigmac": {"admission": {"global_max_running": 4}}
    }
    (root / "harness/config/execution-fabric.yml").write_text(
        yaml.safe_dump(config, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ExecutionFabricConfigError, match="same alias"):
        load_execution_fabric_config(root)


def test_python_and_node_host_identity_environment_must_agree(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _install_hosts(root)

    assert (
        resolve_execution_fabric_host_id(
            root,
            environ={
                "FABRIC_HOST_ID": "bigmac",
                "AGENTIC_OS_HOST_ALIAS": "bigmac",
            },
        )
        == "bigmac"
    )
    with pytest.raises(ExecutionFabricConfigError, match="sources disagree"):
        resolve_execution_fabric_host_id(
            root,
            environ={
                "FABRIC_HOST_ID": "genomesbox",
                "AGENTIC_OS_HOST_ALIAS": "bigmac",
            },
        )


def test_config_validate_cli_returns_a_structured_nonzero_finding(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _root(tmp_path)
    path = root / "harness/config/execution-fabric.yml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    loaded["execution_fabric"]["admission"]["global_max_running"] = 0
    path.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")

    assert main(["runtime", "config", "validate", "--root", str(root), "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False
    assert result["findings"][0]["severity"] == "error"


def test_config_reconciliation_is_dry_run_first_and_updates_existing_rows_atomically(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    apply_queue_mode(root, "execution_fabric", dry_run=False)
    before = execution_fabric_config_status(root)
    assert before["drift_count"] == 0

    _edit(root)
    planned = reconcile_execution_fabric_configuration(root)
    assert planned["ready"] is True
    assert planned["applied"] is False
    assert planned["drift_count"] >= 5

    conn = db.connect(db.default_db_path(root))
    try:
        assert tuple(
            conn.execute(
                "SELECT max_concurrency, enabled FROM execution_queues WHERE name = 'codex'"
            ).fetchone()
        ) == (2, 1)
    finally:
        conn.close()

    applied = reconcile_execution_fabric_configuration(root, dry_run=False)
    assert applied["status"] == "reconciled"
    assert applied["drift_count"] == 0

    conn = db.connect(db.default_db_path(root))
    try:
        queue = conn.execute(
            "SELECT max_concurrency, enabled, metadata_json FROM execution_queues WHERE name = 'codex'"
        ).fetchone()
        pool = conn.execute(
            """
            SELECT max_workers, max_concurrency, enabled, metadata_json
            FROM worker_pools WHERE name = 'codex_workers'
            """
        ).fetchone()
        queue_metadata = json.loads(queue["metadata_json"])
        pool_metadata = json.loads(pool["metadata_json"])
        assert (queue["max_concurrency"], queue["enabled"]) == (1, 0)
        assert queue_metadata["max_queued"] == 7
        assert (pool["max_workers"], pool["max_concurrency"], pool["enabled"]) == (1, 1, 0)
        assert pool_metadata["lease"] == {"timeout_seconds": 600, "heartbeat_seconds": 20}
        assert pool_metadata["retry"] == {"max_attempts": 4, "backoff_seconds": 17}
        assert conn.execute(
            "SELECT max_concurrency FROM execution_limits WHERE scope = 'global' AND key = '*'"
        ).fetchone()[0] == 5
        assert conn.execute(
            "SELECT max_concurrency FROM execution_limits WHERE scope = 'provider' AND key = 'codex'"
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_filesystem_mode_never_allows_config_to_become_a_second_writer(tmp_path: Path) -> None:
    root = _root(tmp_path)
    state_path = db.default_db_path(root)

    planned = reconcile_execution_fabric_configuration(root)
    assert planned["ready"] is False
    assert planned["queue_mode"] == "filesystem"
    assert state_path.exists() is False

    with pytest.raises(RuntimeBackendError, match="not the authoritative queue mode"):
        reconcile_execution_fabric_configuration(root, dry_run=False)
    assert state_path.exists() is False


def test_reconcile_rolls_back_every_catalog_change_when_a_live_pool_move_is_unsafe(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    apply_queue_mode(root, "execution_fabric", dry_run=False)
    conn = db.connect(db.default_db_path(root))
    try:
        worker = fabric_state.register_worker(conn, "codex-live", pool_name="codex_workers")
        task = fabric_state.enqueue_task(
            conn,
            queue_name="codex",
            worker_pool="codex_workers",
            kind="test",
        )
        assert (
            fabric_state.claim_next(
                conn,
                worker_id="codex-live",
                worker_token=worker["lease_token"],
                item_id=task["id"],
            )
            is not None
        )
    finally:
        conn.close()

    path = root / "harness/config/execution-fabric.yml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    by_queue = {row["id"]: row for row in loaded["execution_fabric"]["queues"]}
    by_pool = {row["id"]: row for row in loaded["execution_fabric"]["worker_pools"]}
    by_queue["codex"]["worker_pool"] = "claude_workers"
    by_queue["claude"]["worker_pool"] = "codex_workers"
    by_pool["codex_workers"]["queues"] = ["claude"]
    by_pool["claude_workers"]["queues"] = ["codex"]
    by_queue["non_llm"]["concurrency"]["max_running"] = 1
    path.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")

    with pytest.raises(ExecutionFabricConfigError, match="cannot change queue"):
        reconcile_execution_fabric_configuration(root, dry_run=False)

    conn = db.connect(db.default_db_path(root))
    try:
        assert conn.execute(
            "SELECT max_concurrency FROM execution_queues WHERE name = 'non_llm'"
        ).fetchone()[0] == 4
        assert conn.execute(
            "SELECT queue_name FROM worker_pools WHERE name = 'codex_workers'"
        ).fetchone()[0] == "codex"
    finally:
        conn.close()


def test_runtime_config_cli_reports_and_reconciles_with_explicit_apply(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _root(tmp_path)
    assert main(["runtime", "config", "validate", "--root", str(root), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True

    apply_queue_mode(root, "execution_fabric", dry_run=False)
    _edit(root)
    assert main(["runtime", "config", "reconcile", "--root", str(root), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["applied"] is False

    assert (
        main(
            [
                "runtime",
                "config",
                "reconcile",
                "--root",
                str(root),
                "--apply",
                "--json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "reconciled"
    assert result["fingerprint"] == load_execution_fabric_config(root).fingerprint


def test_runtime_config_show_is_redacted_and_reports_layer_provenance(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _root(tmp_path)
    assert main(["runtime", "config", "show", "--root", str(root), "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)

    assert shown["source_kind"] == "instance"
    assert shown["layers"][0]["kind"] == "release_default"
    assert shown["effective"]["execution_fabric"]["transport"]["admin_token_env"] == (
        "AGENTIC_OS_EXECUTION_FABRIC_ADMIN_TOKEN"
    )
