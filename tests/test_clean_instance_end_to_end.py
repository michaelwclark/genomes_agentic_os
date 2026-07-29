"""AGE-68: compose a clean install through durable workflow queue receipts.

This test deliberately proves the product's current execution boundary:
``workflow run-now`` queues a governed request, but does not execute business
steps or dispatch a worker.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest
import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os.library import (
    INSTALL_RECEIPT,
    MANIFEST_API_VERSION,
    init_library,
    install_library,
    library_doctor,
    object_relative_path,
    query_objects,
    refresh_registry,
    verify_library_install,
)
from genomes_agentic_os.routing import route_request
from genomes_agentic_os.state import db as state_db
from genomes_agentic_os.state import queue as state_queue
from genomes_agentic_os.state.importers import verify_import
from genomes_agentic_os.workflow_engine import (
    DEFINITION_FILE,
    EVIDENCE_ROOT,
    INSTANCE_FILE,
    create_workflow_definition,
    get_workflow_resource,
    publish_workflow,
    query_workflow_resources,
    workflow_run_now,
)


WORKFLOW_ID = "release_review"
DOMAIN = "work"
LANE = "engineering"
IDENTITY = f"workflow:{DOMAIN}:{LANE}:{WORKFLOW_ID}"
IDEMPOTENCY_KEY = "age68:e2e:clean-instance"
SKILL_ID = "release_review_helper"
RUN_QUEUE = Path("harness/shared_factory/00-control-plane/run-queue.yml")
RECEIPTS = EVIDENCE_ROOT / "receipts"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _library_remote(root: Path) -> tuple[Path, str]:
    """Create a real local bare Git remote containing one valid skill."""
    source_root = root / "source-os"
    source_root.mkdir(parents=True)
    (source_root / ".agentic_root").write_text("agentic-os\n", encoding="utf-8")
    init_library(source_root, dry_run=False, initialize_git=True)

    library_root = source_root / "lib"
    _git(library_root, "config", "user.email", "test@example.com")
    _git(library_root, "config", "user.name", "Test")
    object_root = library_root / object_relative_path("skill", SKILL_ID)
    object_root.mkdir(parents=True)
    (object_root / "SKILL.md").write_text(
        "# Release review helper\n\nCollect bounded release evidence.\n",
        encoding="utf-8",
    )
    manifest = {
        "api_version": MANIFEST_API_VERSION,
        "kind": "skill",
        "id": SKILL_ID,
        "title": "Release Review Helper",
        "description": "Collect bounded evidence for a release review.",
        "status": "active",
        "scope": {"level": "root", "domain": None, "project": None},
        "owner": {"type": "operator", "id": "Genome"},
        "entrypoint": "SKILL.md",
        "tags": ["release", "review"],
        "dependencies": [],
        "aliases": [],
        "runtime": {},
        "validation": {},
    }
    (object_root / "object.yml").write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )
    refresh_registry(source_root, dry_run=False)
    _git(library_root, "add", "-A")
    _git(library_root, "commit", "--no-verify", "-m", "seed library")
    revision = _git(library_root, "rev-parse", "HEAD")

    remote = root / "library.git"
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(library_root, "remote", "add", "origin", str(remote))
    _git(library_root, "push", "-u", "origin", "main")
    return remote, revision


def _definition() -> dict:
    """Return a governed definition linked to the installed skill.

    Top-level approvals remain empty so the run is queueable. Omitting an
    execution block selects the Agentic OS harness and materializes no worker
    command.
    """
    return {
        "schema_version": 1,
        "resource_kind": "workflow_definition",
        "id": WORKFLOW_ID,
        "domain": DOMAIN,
        "lane": LANE,
        "name": "Release Review",
        "summary": "Review a release with explicit evidence and approval gates.",
        "owner": "OS Owner",
        "availability": "active",
        "health": "healthy",
        "version": "1.0.0",
        "inputs": {"release": {"type": "string"}},
        "outputs": {"decision": {"type": "string"}},
        "approvals": [],
        "retry": {"max_attempts": 1, "backoff_seconds": 0},
        "failure_policy": "stop",
        "prompts": ["Review verified release evidence."],
        "agents": ["release_reviewer"],
        "models": ["routed"],
        "linked_capabilities": [{"kind": "skill", "id": SKILL_ID}],
        "publish": {"allowed": True},
        "steps": [
            {
                "id": "collect_evidence",
                "name": "Collect evidence",
                "summary": "Collect bounded release evidence.",
                "order": 1,
                "kind": "skill",
                "depends_on": [],
                "skills": [SKILL_ID],
                "inputs": {},
                "outputs": {"evidence": {}},
                "approvals": [],
                "retry": {"max_attempts": 2, "backoff_seconds": 5},
                "failure_policy": "stop",
            },
            {
                "id": "approve_release",
                "name": "Approve release",
                "summary": "Record the guarded release decision.",
                "order": 2,
                "kind": "approval",
                "depends_on": ["collect_evidence"],
                "inputs": {"evidence": {}},
                "outputs": {"decision": {}},
                "approvals": ["release_owner"],
                "retry": {"max_attempts": 1, "backoff_seconds": 0},
                "failure_policy": "require_approval",
            },
        ],
    }


def _receipt(root: Path, receipt_id: str) -> dict:
    path = root / RECEIPTS / f"{receipt_id}.yml"
    assert path.is_file(), f"receipt not written: {receipt_id}"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _file_snapshot(root: Path) -> dict[Path, bytes]:
    """Capture every materialized file below a run-artifact root."""
    return {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_clean_instance_installs_routes_and_queues_a_governed_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "agentic_os"

    # Real Git exercises must be deterministic and independent of host signing,
    # aliases, hooks, and default-branch configuration.
    empty_git_config = tmp_path / "empty-gitconfig"
    empty_git_config.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty_git_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")

    # A clean install needs both the filesystem scaffold and runtime state.
    assert main(["init", "--target", str(root)]) == 0
    assert main(["runtime", "init", "--root", str(root)]) == 0
    assert main(["validate", "--root", str(root)]) == 0
    assert (root / "harness/ROUTER.md").is_file()
    assert (root / RUN_QUEUE).is_file()
    assert not (root / RECEIPTS).exists()

    # Install through the production Git-backed object-library path.
    remote, revision = _library_remote(tmp_path / "library-source")
    install_plan = install_library(root, repository=str(remote), dry_run=True)
    assert install_plan["status"] == "planned"
    assert install_plan["existing"]["managed_placeholder"] is True
    assert install_plan["existing"]["projection_dirty"] is False

    installed = install_library(root, repository=str(remote), dry_run=False)
    assert installed["status"] == "installed"
    assert installed["source_revision"] == revision
    install_receipt = json.loads((root / INSTALL_RECEIPT).read_text(encoding="utf-8"))
    assert install_receipt["status"] == "installed"
    assert install_receipt["source_revision"] == revision
    assert install_receipt["content_sha256"] == installed["content_sha256"]
    assert install_receipt["projection_sha256"] == installed["projection_sha256"]
    assert (root / installed["success_receipt"]).is_file()
    verified_install = verify_library_install(root)
    assert verified_install["status"] == "verified"
    assert verified_install["doctor_status"] == "healthy"
    assert library_doctor(root)["status"] == "healthy"
    assert SKILL_ID in {item["id"] for item in query_objects(root, kind="skill")}
    assert main(["validate", "--root", str(root)]) == 0

    # Authoring creates the concrete path needed for cwd-aware routing.
    definition = _definition()
    create_plan = create_workflow_definition(root, definition)
    assert create_plan["status"] == "planned"
    created = create_workflow_definition(
        root,
        definition,
        expected_drift_hash=create_plan["drift"]["before"],
        dry_run=False,
    )
    workflow_dir = root / f"domains/{DOMAIN}/03-workflows/{LANE}/{WORKFLOW_ID}"
    assert created["readback"]["ok"] is True
    assert (workflow_dir / DEFINITION_FILE).is_file()

    create_receipt = _receipt(root, created["receipt_id"])
    assert create_receipt["api_version"] == "workflow-engine/v1"
    assert create_receipt["action"] == "workflow.create"
    assert create_receipt["identity"]["identity"] == IDENTITY
    assert create_receipt["external_effects"] == "local filesystem only"
    assert create_receipt["rollback"] == {
        "supported": True,
        "guard": "current_drift_hash_must_match_after_drift_hash",
    }
    assert create_receipt["before_drift_hash"] != create_receipt["after_drift_hash"]
    assert create_receipt["after_drift_hash"] == created["drift"]["after"]
    assert (root / create_receipt["backup"]).is_file()

    # `here route` is the CLI surface that preserves cwd. The ordinary route
    # command does not exercise this branch.
    request = "review the release for the engineering lane"
    packet = route_request(root, request, cwd=workflow_dir)
    assert packet.object_type == "workflow"
    assert packet.target_path == workflow_dir
    assert (packet.domain, packet.lane) == (DOMAIN, LANE)
    router = root / "harness/ROUTER.md"
    assert router in packet.sources_to_load
    assert router.is_file()

    registry = root / "lib/registry/objects.json"
    assert registry in packet.sources_to_load
    registry_payload = json.loads(registry.read_text(encoding="utf-8"))
    assert SKILL_ID in json.dumps(registry_payload, sort_keys=True)
    capsys.readouterr()
    with monkeypatch.context() as cwd_context:
        cwd_context.chdir(workflow_dir)
        assert main(["here", "route", request, "--root", str(root)]) == 0
    cli_packet = yaml.safe_load(capsys.readouterr().out)
    assert cli_packet["object_type"] == "workflow"
    assert cli_packet["target_path"] == str(workflow_dir)
    assert (cli_packet["domain"], cli_packet["lane"]) == (DOMAIN, LANE)

    publish_plan = publish_workflow(root, WORKFLOW_ID, domain=DOMAIN, lane=LANE)
    published = publish_workflow(
        root,
        WORKFLOW_ID,
        domain=DOMAIN,
        lane=LANE,
        expected_drift_hash=publish_plan["drift"]["before"],
        dry_run=False,
    )
    version_id = published["readback"]["version"]["id"]
    assert published["readback"]["version"]["resource_kind"] == "workflow_version"
    assert published["readback"]["instance"]["version_id"] == version_id
    assert (workflow_dir / INSTANCE_FILE).is_file()

    publish_receipt = _receipt(root, published["receipt_id"])
    assert publish_receipt["api_version"] == "workflow-engine/v1"
    assert publish_receipt["action"] == "workflow.publish"
    assert publish_receipt["identity"]["identity"] == IDENTITY
    assert publish_receipt["external_effects"] == "local filesystem only"
    assert publish_receipt["rollback"] == {
        "supported": True,
        "guard": "current_drift_hash_must_match_after_drift_hash",
    }
    assert publish_receipt["before_drift_hash"] != publish_receipt["after_drift_hash"]
    assert publish_receipt["after_drift_hash"] == published["drift"]["after"]
    assert (root / publish_receipt["backup"]).is_file()

    # The spawn guard is installed only after the real Git-backed install.
    workflow_runs_dir = workflow_dir / "runs"
    canonical_runs_dir = root / f"domains/{DOMAIN}/06-runs-and-logs/runs"
    workflow_run_artifacts_before = _file_snapshot(workflow_runs_dir)
    canonical_run_artifacts_before = _file_snapshot(canonical_runs_dir)

    def forbidden_spawn(*_args, **_kwargs):
        raise AssertionError("workflow run-now must not launch a process")

    with monkeypatch.context() as no_exec:
        no_exec.setattr(subprocess, "run", forbidden_spawn)
        no_exec.setattr(subprocess, "Popen", forbidden_spawn)
        no_exec.setattr(subprocess, "check_output", forbidden_spawn)
        no_exec.setattr(os, "system", forbidden_spawn)

        run_plan = workflow_run_now(
            root,
            WORKFLOW_ID,
            domain=DOMAIN,
            lane=LANE,
            idempotency_key=IDEMPOTENCY_KEY,
        )
        assert run_plan["status"] == "planned"
        assert run_plan["dispatch_performed"] is False
        assert run_plan["run"]["execution_status"] == "not_started"
        assert run_plan["external_effects"] == "local queue request only; no dispatch performed"

        first = workflow_run_now(
            root,
            WORKFLOW_ID,
            domain=DOMAIN,
            lane=LANE,
            idempotency_key=IDEMPOTENCY_KEY,
            expected_drift_hash=run_plan["drift"]["before"],
            dry_run=False,
        )
        second = workflow_run_now(
            root,
            WORKFLOW_ID,
            domain=DOMAIN,
            lane=LANE,
            idempotency_key=IDEMPOTENCY_KEY,
            expected_drift_hash=run_plan["drift"]["before"],
            dry_run=False,
        )

    assert first["status"] == "queued"
    assert first["queue_created"] is True
    assert second["queue_created"] is False
    assert second["run"]["id"] == first["run"]["id"]
    assert first["receipt_id"] != second["receipt_id"]

    run_receipt = _receipt(root, first["receipt_id"])
    assert run_receipt["action"] == "workflow.run-now"
    assert run_receipt["external_effects"] == "local queue request only; no dispatch performed"
    assert run_receipt["rollback"]["supported"] is False
    assert run_receipt["backup_id"] is None
    assert run_receipt["backup"] is None
    assert run_receipt["before_drift_hash"] == run_receipt["after_drift_hash"]
    assert run_receipt["readback"]["ok"] is True
    assert run_receipt["readback"]["queue_item"]["dispatch_performed"] is False

    # These independent disk reads are the anti-fabrication proof. Returned
    # dictionaries alone would let the producer grade its own work.
    run = get_workflow_resource(root, "run", first["run"]["id"])["resource"]
    assert run["status"] == "queued"
    assert run["execution_status"] == "not_started"
    assert run["dispatch_performed"] is False
    assert run["execution_contract"] == "harness_worker_required"
    assert run["execution_target"] == "agentic_os_harness"
    assert run["version_id"] == version_id
    assert len(query_workflow_resources(root, "run", workflow=WORKFLOW_ID)["items"]) == 1
    assert len(list((root / EVIDENCE_ROOT / "run-requests").glob("*.yml"))) == 1

    queue_payload = yaml.safe_load((root / RUN_QUEUE).read_text(encoding="utf-8"))
    workflow_items = [item for item in queue_payload["items"] if item.get("kind") == "workflow"]
    assert len(workflow_items) == 1
    queue_item = workflow_items[0]
    assert queue_item["id"] == first["run"]["queue_item_id"]
    assert (queue_item["kind"], queue_item["ref"], queue_item["status"]) == (
        "workflow",
        IDENTITY,
        "queued",
    )
    assert queue_item["execution_contract"] == "harness_worker_required"
    assert queue_item["dispatch_performed"] is False
    assert "command" not in queue_item
    assert "lease_owner" not in queue_item
    assert _file_snapshot(workflow_runs_dir) == workflow_run_artifacts_before
    assert _file_snapshot(canonical_runs_dir) == canonical_run_artifacts_before

    # Import the queue into SQLite, then inspect both the decoded API and the
    # actual payload_json column to prove the execution contract survived.
    assert main(["state", "init", "--root", str(root)]) == 0
    assert main(["state", "import", "--root", str(root), "--source", "run-queue"]) == 0
    db_path = state_db.default_db_path(root)
    assert db_path.is_file()
    connection = state_db.connect(db_path)
    try:
        rows = state_queue.query(connection, kind="workflow")
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == queue_item["id"]
        assert row["status"] == "queued"
        assert row["execution_target"] == "agentic_os_harness"
        assert row["payload"]["execution_contract"] == "harness_worker_required"
        assert row["payload"]["dispatch_performed"] is False

        raw_payload = connection.execute(
            "SELECT payload_json FROM run_queue WHERE id = ?",
            (queue_item["id"],),
        ).fetchone()["payload_json"]
        persisted_payload = json.loads(raw_payload)
        assert persisted_payload["execution_contract"] == "harness_worker_required"
        assert persisted_payload["dispatch_performed"] is False
        assert verify_import(connection, root)["drift"]["run_queue"] == 0
    finally:
        connection.close()
