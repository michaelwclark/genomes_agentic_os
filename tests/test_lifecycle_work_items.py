from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import subprocess

import pytest
import yaml

import genomes_agentic_os.auto_dev_orchestration as auto_dev
from genomes_agentic_os.auto_dev_orchestration import (
    AUTO_DEV_STAGE_EVIDENCE_SCHEMA,
    AUTO_DEV_STAGE_ORDER,
    AutoDevStateError,
    prepare_auto_dev_health,
    record_auto_dev_stage,
    sync_delivery_projection,
)
from genomes_agentic_os.lifecycle import (
    cleanup_terminal_worktrees,
    create_project_work_item,
    local_project_work_items,
    work_item_file_content,
)


def _write_work_item(project_root: Path, slug: str, body: str) -> Path:
    item_dir = project_root / "work-items" / "02-active" / slug
    item_dir.mkdir(parents=True)
    metadata = item_dir / "work.yml"
    metadata.write_text(body, encoding="utf-8")
    return item_dir


def test_local_project_work_items_survives_malformed_metadata(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_work_item(project_root, "good_item", "id: good_item\ntitle: Good item\nstatus: in_progress\n")
    # Backtick cannot start a YAML scalar; agent-authored files hit this in the wild.
    _write_work_item(project_root, "bad_item", "id: bad_item\nacceptance_criteria:\n- `broken` bullet\n")

    records = local_project_work_items(project_root)

    by_slug = {record.slug for record in records}
    assert "good_item" in by_slug
    broken = [record for record in records if record.metadata.get("metadata_error")]
    assert len(broken) == 1
    assert "invalid yaml" in broken[0].metadata["metadata_error"]


def test_new_canonical_packet_names_the_canonical_spec_root(tmp_path: Path) -> None:
    root = tmp_path / "os"
    project = root / "domains" / "acme" / "02-projects" / "app"
    project.mkdir(parents=True)

    created = create_project_work_item(
        root,
        "acme",
        "app",
        title="Canonical packet",
        summary="Keep local specification truth in the stable packet root.",
        status="building",
    )
    packet = next(
        path
        for path in created.created
        if path.parent == project / "work-items" and (path / "work.yml").is_file()
    )
    metadata = yaml.safe_load((packet / "work.yml").read_text(encoding="utf-8"))

    assert metadata["spec_destination"] == {
        "type": "local",
        "path": "work-items",
    }


def test_new_plan_requires_architecture_read_before_code() -> None:
    plan = work_item_file_content(
        "PLAN.md",
        title="Architecture gated work",
        summary="Build safely.",
        status="building",
        work_id="fixture",
    )

    assert "## Architecture Prerequisite" in plan
    assert "Before code or state changes" in plan
    assert "canonical ports-and-adapters reference" in plan
    assert "work-item receipt" in plan


def _cleanup_fixture(tmp_path: Path, entry_fields: dict[str, object]) -> tuple[Path, Path, Path]:
    root = tmp_path / "os"
    root.mkdir()
    (root / ".agentic_root").write_text("", encoding="utf-8")
    project = root / "domains" / "acme" / "02-projects" / "app"
    (project / "config").mkdir(parents=True)
    (project / "project.yml").write_text("id: app\ndomain: acme\n", encoding="utf-8")
    repository = tmp_path / "repository"
    subprocess.run(["git", "init", "-b", "main", str(repository)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repository), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repository), "config", "user.name", "Test"], check=True)
    (repository / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-m", "fixture"], check=True, capture_output=True)
    worktree = project / "worktrees" / "feature"
    worktree.parent.mkdir(parents=True)
    subprocess.run(
        ["git", "-C", str(repository), "worktree", "add", "-b", "feature/test", str(worktree)],
        check=True,
        capture_output=True,
    )
    entry = {"id": "feature", "path": str(worktree), "status": "active", **entry_fields}
    (project / "config" / "worktrees.yml").write_text(
        yaml.safe_dump({"worktrees": {"registered": [entry]}}, sort_keys=False),
        encoding="utf-8",
    )
    return root, repository, worktree


def _registered(root: Path) -> list[dict[str, object]]:
    registry = root / "domains" / "acme" / "02-projects" / "app" / "config" / "worktrees.yml"
    return yaml.safe_load(registry.read_text(encoding="utf-8"))["worktrees"]["registered"]


def _health_gate(
    root: Path,
    worktree: Path,
    *,
    managed_runtime: bool = False,
    runtime_collision: bool = False,
    stage_order: list[str] | None = None,
    start_stage: str | None = None,
) -> tuple[Path, Path]:
    packet = (
        root
        / "domains"
        / "acme"
        / "02-projects"
        / "app"
        / "work-items"
        / "02-active"
        / "feature-health"
    )
    health = packet / "artifacts" / "auto-dev-health"
    receipts = health / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    preflight = health / "preflight.json"

    def descriptor(path: Path) -> dict[str, str]:
        return {
            "ref": path.relative_to(packet).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    def write_runtime_receipt(runtime_contract: dict[str, str]) -> Path:
        teardown_proof = receipts / "runtime-teardown-operation.txt"
        readback_proof = receipts / "runtime-readback-operation.txt"
        teardown_proof.write_text("Exact runtime teardown was recorded.\n", encoding="utf-8")
        readback_proof.write_text("Exact runtime absence was read back.\n", encoding="utf-8")
        runtime = receipts / "runtime-cleanup.json"
        runtime.write_text(
            json.dumps(
                {
                    "schema": "auto-dev-runtime-cleanup/v1",
                    "work_item_id": "feature-health",
                    "canonical_work_id": "acme:app:feature-health",
                    "runtime_identity": runtime_contract["identity"],
                    "ownership": runtime_contract["ownership"],
                    "provider": runtime_contract["provider"],
                    "teardown": {
                        "command": runtime_contract.get("teardown_command", "not_managed"),
                        **descriptor(teardown_proof),
                    },
                    "readback": {
                        "command": runtime_contract.get("readback_command", "not_managed"),
                        **descriptor(readback_proof),
                    },
                    "result": "absent" if managed_runtime else "not_managed",
                    "readback_verified": True,
                    "preflight_sha256": hashlib.sha256(preflight.read_bytes()).hexdigest(),
                    "verified_at": datetime.now(timezone.utc)
                    .replace(microsecond=0)
                    .isoformat()
                    .replace("+00:00", "Z"),
                }
            ),
            encoding="utf-8",
        )
        return runtime

    if preflight.is_file():
        existing = json.loads(preflight.read_text(encoding="utf-8"))
        return preflight, write_runtime_receipt(dict(existing["runtime"]))

    for directory in (packet / "logs" / "conversations", packet / "artifacts"):
        directory.mkdir(parents=True, exist_ok=True)
    packet_files = {
        "work.yml": "id: feature-health\ntitle: Feature health\nstatus: in_progress\n",
        "SPEC.md": "# Spec\n",
        "PLAN.md": "# Plan\n",
        "INVESTIGATION.md": "# Investigation\n",
        "JUDGMENT.md": "# Judgment\n",
        "HOLDOUT_QA.md": "# Holdout QA\n",
        "HOLDOUT_QA_RESULTS.md": "# Holdout QA results\n",
        "WORKLOG.md": "# Worklog\n",
        "SUMMARY.md": "# Summary\n",
        "NEXT.md": "# Next\n",
        "MEMORY.md": "# Memory\n",
    }
    for name, body in packet_files.items():
        (packet / name).write_text(body, encoding="utf-8")

    subject_revision = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    terminal_revision = "b" * 40
    canonical_receipts = packet / "artifacts" / "delivery"
    canonical_receipts.mkdir(parents=True, exist_ok=True)
    authority = {
        "provider": "github",
        "pull_request": "github:acme/app#1",
        "repository": "github:acme/app",
        "base_branch": "main",
        "author_identity": "github:michaelwclark",
        "author_kind": "ours",
        "readback_verified": True,
    }

    def delivery_receipt(
        state: str,
        *,
        evidence: dict[str, object],
        status: str = "completed",
    ) -> Path:
        path = canonical_receipts / f"{state}.json"
        path.write_text(
            json.dumps(
                {
                    "schema": "development-stage-evidence/v1",
                    "state": state,
                    "status": status,
                    "summary": f"Verified {state}",
                    "evidence": evidence,
                    "verified_at": "2026-07-20T19:55:00Z",
                }
            ),
            encoding="utf-8",
        )
        return path

    planned = delivery_receipt("planned", evidence={"plan": "verified"})
    local_validation = delivery_receipt(
        "local_validation", evidence={"tests": "passed"}
    )
    canonical_pr_open = delivery_receipt("pr_open", evidence=dict(authority))
    canonical_ready = delivery_receipt(
        "ready_for_merge",
        evidence={
            **authority,
            "checks_verified": True,
            "reviews_verified": True,
            "subject_revision": subject_revision,
        },
    )
    canonical_merge = delivery_receipt(
        "merged",
        evidence={
            **authority,
            "merge_sha": terminal_revision,
            "source_head_sha": subject_revision,
        },
    )
    post_deploy = delivery_receipt(
        "post_deploy_validation",
        evidence={
            "deployed_revision": terminal_revision,
            "artifact_ref": "registry.example/app@sha256:fixture",
            "environment": "test",
            "readback_verified": True,
        },
    )
    canonical_closeout = delivery_receipt(
        "delivery_complete",
        evidence={"closeout_verified": True, "receipt_refs": ["tracker:feature-health"]},
    )
    task_state = health / "task-state.json"
    runtime_contract = (
        {
            "ownership": "managed",
            "provider": "test_target_runtime",
            "identity": "acme-app-feature",
            "teardown_command": "true acme-app-feature",
            "readback_command": "true acme-app-feature",
        }
        if managed_runtime
        else {
            "ownership": "not_managed",
            "provider": "none",
            "identity": "not-managed",
        }
    )
    configured_order = list(stage_order or AUTO_DEV_STAGE_ORDER)
    task_state.write_text(
        json.dumps(
            {
                "state": "delivery_complete",
                "domain": "acme",
                "project": "app",
                "canonical_work_id": "acme:app:feature-health",
                "ticket": "feature-health",
                "run_id": "health-fixture",
                "goal": "delivery_complete",
                "auto_dev_mode": "everything",
                "requested_stage": None,
                "auto_dev_stage_order": configured_order,
                "auto_dev_start_stage": start_stage or configured_order[0],
                "auto_dev_completion_stage": "health",
                "work_item": str(packet),
                "autodev_path": str(packet / "autodev.json"),
                "subject_revision": subject_revision,
                "terminal_revision": terminal_revision,
                "deployed_revision": terminal_revision,
                "deployment_applicable": True,
                "repository": {
                    "id": "github:acme/app",
                    "root": str(root.parent / "repository"),
                    "base_branch": "main",
                },
                "authorship": {"ours": ["github:michaelwclark"]},
                "worktree": {
                    "name": "feature",
                    "path": str(worktree),
                    "branch": subprocess.run(
                        ["git", "-C", str(worktree), "branch", "--show-current"],
                        check=True,
                        capture_output=True,
                        text=True,
                    ).stdout.strip(),
                },
                "runtime": runtime_contract,
                "policy_receipt": str(health / "effective-policy.json"),
                "policy_fingerprint": "fixture-policy-fingerprint",
                "policy_sources": {},
                "failure": None,
                "receipts": [
                    {
                        "state": state,
                        "ref": str(path),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                    for state, path in (
                        ("planned", planned),
                        ("local_validation", local_validation),
                        ("pr_open", canonical_pr_open),
                        ("ready_for_merge", canonical_ready),
                        ("merged", canonical_merge),
                        ("post_deploy_validation", post_deploy),
                        ("delivery_complete", canonical_closeout),
                    )
                ],
            }
        ),
        encoding="utf-8",
    )
    (health / "effective-policy.json").write_text(
        json.dumps({"schema": "effective-development-policy/v1", "fixture": True}),
        encoding="utf-8",
    )
    task = json.loads(task_state.read_text(encoding="utf-8"))

    delivery_link = packet / "artifacts" / "development-delivery" / "run.json"
    delivery_link.parent.mkdir(parents=True, exist_ok=True)
    delivery_link.write_text(json.dumps({"task_state": str(task_state)}), encoding="utf-8")
    release_evidence = delivery_receipt(
        "release_propagation", evidence={"propagation": "verified"}
    )
    release_wrapper = task_state.parent / "stages" / "release-propagation.json"
    release_wrapper.parent.mkdir(parents=True, exist_ok=True)
    release_payload = json.loads(release_evidence.read_text(encoding="utf-8"))
    release_wrapper.write_text(
        json.dumps(
            {
                "schema": "development-stage-receipt/v1",
                "stage": "release_propagation",
                "task_state": "ready_for_merge",
                "receipt": descriptor(release_evidence)["ref"],
                "evidence_sha256": hashlib.sha256(
                    json.dumps(
                        release_payload, sort_keys=True, separators=(",", ":")
                    ).encode("utf-8")
                ).hexdigest(),
                "idempotency_key": "feature-health:release-propagation",
                "recorded_at": "2026-07-20T19:56:00Z",
            }
        ),
        encoding="utf-8",
    )
    task["stage_receipts"] = {
        "release_propagation": {
            "ref": str(release_wrapper),
            "sha256": hashlib.sha256(release_wrapper.read_bytes()).hexdigest(),
        }
    }
    task_state.write_text(json.dumps(task), encoding="utf-8")
    sync_delivery_projection(task_state)

    def record_stage(
        stage: str,
        *,
        revision: str | None = None,
        not_required: bool = False,
    ) -> None:
        evidence_path = packet / "artifacts" / "fixture-stage-evidence" / f"{stage}.json"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        if not_required:
            policy_source = health / "effective-policy.json"
            policy = evidence_path.with_name(f"{stage}-policy.json")
            policy.write_text(
                json.dumps(
                    {
                        "schema": "auto-dev-stage-policy-decision/v1",
                        "work_item_id": "feature-health",
                        "canonical_work_id": "acme:app:feature-health",
                        "domain": "acme",
                        "project": "app",
                        "stage": stage,
                        "decision": "not_required",
                        "reason": "The frozen item policy does not require this stage.",
                        "decided_by": "test:project-policy",
                        "policy_fingerprint": "fixture-policy-fingerprint",
                        "policy_source": {
                            "ref": str(policy_source),
                            "sha256": hashlib.sha256(policy_source.read_bytes()).hexdigest(),
                        },
                        "verified_at": "2026-07-20T19:57:00Z",
                    }
                ),
                encoding="utf-8",
            )
            structured: dict[str, object] = {"policy_ref": str(policy)}
            status = "not_required"
        else:
            proof = evidence_path.with_suffix(".proof.txt")
            proof.write_text(f"Verified {stage}.\n", encoding="utf-8")
            structured = {"receipt_refs": [str(proof)]}
            status = "completed"
            if stage == "finalize":
                structured.update(authority)
                structured["readiness_decision"] = "ready_for_merge"
        payload: dict[str, object] = {
            "schema": AUTO_DEV_STAGE_EVIDENCE_SCHEMA,
            "stage": stage,
            "status": status,
            "summary": f"Verified {stage}",
            "evidence": structured,
            "verified_at": "2026-07-20T19:58:00Z",
        }
        if revision:
            payload["subject_revision"] = revision
        evidence_path.write_text(json.dumps(payload), encoding="utf-8")
        record_auto_dev_stage(
            packet / "autodev.json",
            stage=stage,
            evidence_file=evidence_path,
            idempotency_key=f"feature-health:{stage}",
        )

    for stage in ("groom", "detective", "create_artifacts", "document"):
        record_stage(stage)
    # Policy skips intentionally carry no source revision. Projection must
    # still preserve the terminal not_required receipt once a reviewed head
    # exists for the surrounding work item.
    record_stage("review_others", not_required=True)
    record_stage("qa", revision=subject_revision)
    record_stage("finalize", revision=subject_revision)
    record_stage("release", revision=terminal_revision)
    if runtime_collision:
        collision = (
            root
            / "domains"
            / "acme"
            / "02-projects"
            / "app"
            / "state"
            / "development-runs"
            / "other-run"
            / "tasks"
            / "other"
            / "state.json"
        )
        collision.parent.mkdir(parents=True, exist_ok=True)
        collision.write_text(
            json.dumps(
                {
                    "canonical_work_id": "acme:app:other-runtime-owner",
                    "runtime": runtime_contract,
                }
            ),
            encoding="utf-8",
        )
    prepared = prepare_auto_dev_health(packet / "autodev.json", apply=True)
    assert Path(prepared["preflight_ref"]) == preflight
    return preflight, write_runtime_receipt(runtime_contract)


def test_physical_cleanup_requires_exact_health_gate_and_keeps_registration(tmp_path: Path) -> None:
    root, _, worktree = _cleanup_fixture(tmp_path, {"jira_status": "QA Ready"})

    with pytest.raises(ValueError, match="--health-preflight"):
        cleanup_terminal_worktrees(root, apply=True, remove_files=True)

    assert worktree.is_dir()
    assert len(_registered(root)) == 1


def test_reopen_marker_blocks_cleanup_and_keeps_registration(tmp_path: Path) -> None:
    root, _, worktree = _cleanup_fixture(tmp_path, {"pr_state": "merged"})
    (worktree / "REOPEN.md").write_text("# REOPEN\n", encoding="utf-8")
    preflight, runtime = _health_gate(root, worktree)

    result = cleanup_terminal_worktrees(
        root,
        domain="acme",
        project="app",
        worktree="feature",
        health_preflight=preflight,
        runtime_receipt=runtime,
        apply=True,
        remove_files=True,
    )

    assert worktree.is_dir()
    assert len(_registered(root)) == 1
    assert result["closed"] == []
    assert "REOPEN.md" in result["skipped"][0]["reason"]


def test_merged_cleanup_uses_exact_git_worktree_removal(tmp_path: Path) -> None:
    root, repository, worktree = _cleanup_fixture(tmp_path, {"pr_state": "merged"})
    preflight, runtime = _health_gate(root, worktree)

    result = cleanup_terminal_worktrees(
        root,
        domain="acme",
        project="app",
        worktree="feature",
        health_preflight=preflight,
        runtime_receipt=runtime,
        apply=True,
        remove_files=True,
    )

    assert not worktree.exists()
    assert _registered(root) == []
    assert len(result["closed"]) == 1
    assert result["removed"][0]["reason"] == "removed exact typed merged git worktree"
    listed = subprocess.run(
        ["git", "-C", str(repository), "worktree", "list", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert str(worktree) not in listed


def test_cleanup_accepts_configured_later_health_window_and_safe_order(
    tmp_path: Path,
) -> None:
    root, _, worktree = _cleanup_fixture(tmp_path, {"pr_state": "merged"})
    safe_order = list(AUTO_DEV_STAGE_ORDER)
    safe_order[1], safe_order[2] = safe_order[2], safe_order[1]
    preflight, runtime = _health_gate(
        root,
        worktree,
        stage_order=safe_order,
        start_stage="readiness",
    )

    result = cleanup_terminal_worktrees(
        root,
        domain="acme",
        project="app",
        worktree="feature",
        health_preflight=preflight,
        runtime_receipt=runtime,
        apply=True,
        remove_files=True,
    )

    assert not worktree.exists()
    assert _registered(root) == []
    assert len(result["closed"]) == 1


def test_clean_worktree_with_diverged_head_blocks_physical_cleanup(tmp_path: Path) -> None:
    root, _, worktree = _cleanup_fixture(tmp_path, {"pr_state": "merged"})
    preflight, runtime = _health_gate(root, worktree)
    (worktree / "after-review.txt").write_text("new local commit\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(worktree), "add", "after-review.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(worktree), "commit", "-m", "local change after review"],
        check=True,
        capture_output=True,
    )

    result = cleanup_terminal_worktrees(
        root,
        domain="acme",
        project="app",
        worktree="feature",
        health_preflight=preflight,
        runtime_receipt=runtime,
        apply=True,
        remove_files=True,
    )

    assert worktree.is_dir()
    assert len(_registered(root)) == 1
    assert result["closed"] == []
    assert "HEAD does not match" in result["skipped"][0]["reason"]


def test_health_cleanup_rejects_not_managed_result_for_registered_runtime(
    tmp_path: Path,
) -> None:
    root, _, worktree = _cleanup_fixture(tmp_path, {"pr_state": "merged"})
    preflight, runtime = _health_gate(root, worktree, managed_runtime=True)
    payload = json.loads(runtime.read_text(encoding="utf-8"))
    payload["result"] = "not_managed"
    runtime.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="strict schema"):
        cleanup_terminal_worktrees(
            root,
            domain="acme",
            project="app",
            worktree="feature",
            health_preflight=preflight,
            runtime_receipt=runtime,
            apply=True,
            remove_files=True,
        )
    assert worktree.is_dir()
    assert len(_registered(root)) == 1


def test_health_cleanup_rejects_schema_invalid_preflight_before_deletion(
    tmp_path: Path,
) -> None:
    root, _, worktree = _cleanup_fixture(tmp_path, {"pr_state": "merged"})
    preflight, runtime = _health_gate(root, worktree)
    plan = json.loads(preflight.read_text(encoding="utf-8"))
    plan["unexpected_cleanup_override"] = True
    preflight.write_text(json.dumps(plan), encoding="utf-8")
    runtime_payload = json.loads(runtime.read_text(encoding="utf-8"))
    runtime_payload["preflight_sha256"] = hashlib.sha256(preflight.read_bytes()).hexdigest()
    runtime.write_text(json.dumps(runtime_payload), encoding="utf-8")

    with pytest.raises(ValueError, match="strict schema"):
        cleanup_terminal_worktrees(
            root,
            domain="acme",
            project="app",
            worktree="feature",
            health_preflight=preflight,
            runtime_receipt=runtime,
            apply=True,
            remove_files=True,
        )
    assert worktree.is_dir()
    assert len(_registered(root)) == 1


def test_health_cleanup_rejects_a_rehashed_noncanonical_merge_snapshot(
    tmp_path: Path,
) -> None:
    root, _, worktree = _cleanup_fixture(tmp_path, {"pr_state": "merged"})
    preflight, runtime = _health_gate(root, worktree)
    plan = json.loads(preflight.read_text(encoding="utf-8"))
    packet = preflight.parents[2]
    merge_snapshot = packet / plan["merge_receipt_ref"]
    forged = json.loads(merge_snapshot.read_text(encoding="utf-8"))
    forged["evidence"]["pull_request"] = "github:acme/app#999"
    merge_snapshot.write_text(json.dumps(forged), encoding="utf-8")
    forged_hash = hashlib.sha256(merge_snapshot.read_bytes()).hexdigest()
    plan["merge_receipt_sha256"] = forged_hash

    audit_path = packet / plan["receipt_audit"]["ref"]
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["terminal_authority"]["sha256"] = forged_hash
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    plan["receipt_audit"]["sha256"] = hashlib.sha256(audit_path.read_bytes()).hexdigest()
    preflight.write_text(json.dumps(plan), encoding="utf-8")

    runtime_payload = json.loads(runtime.read_text(encoding="utf-8"))
    runtime_payload["preflight_sha256"] = hashlib.sha256(preflight.read_bytes()).hexdigest()
    runtime.write_text(json.dumps(runtime_payload), encoding="utf-8")

    with pytest.raises(ValueError, match="reviewed provider pull request"):
        cleanup_terminal_worktrees(
            root,
            domain="acme",
            project="app",
            worktree="feature",
            health_preflight=preflight,
            runtime_receipt=runtime,
            apply=True,
            remove_files=True,
        )
    assert worktree.is_dir()
    assert len(_registered(root)) == 1


def test_health_cleanup_preserves_dirty_user_changes_by_default(tmp_path: Path) -> None:
    root, _, worktree = _cleanup_fixture(tmp_path, {"pr_state": "merged"})
    (worktree / "user-change.txt").write_text("keep me\n", encoding="utf-8")
    preflight, runtime = _health_gate(root, worktree)

    result = cleanup_terminal_worktrees(
        root,
        domain="acme",
        project="app",
        worktree="feature",
        health_preflight=preflight,
        runtime_receipt=runtime,
        apply=True,
        remove_files=True,
    )

    assert worktree.is_dir()
    assert result["closed"] == []
    assert "uncommitted changes" in result["skipped"][0]["reason"]


def test_health_cleanup_still_preserves_dirty_changes_after_separate_copy_receipt(
    tmp_path: Path,
) -> None:
    root, _, worktree = _cleanup_fixture(tmp_path, {"pr_state": "merged"})
    (worktree / "user-change.txt").write_text("preserved in packet\n", encoding="utf-8")
    packet_receipt = (
        root
        / "domains/acme/02-projects/app/work-items/02-active/feature-health"
        / "artifacts/auto-dev-health/receipts/separate-copy.json"
    )
    packet_receipt.parent.mkdir(parents=True, exist_ok=True)
    packet_receipt.write_text('{"copied": true}\n', encoding="utf-8")
    preflight, runtime = _health_gate(root, worktree)

    result = cleanup_terminal_worktrees(
        root,
        domain="acme",
        project="app",
        worktree="feature",
        health_preflight=preflight,
        runtime_receipt=runtime,
        apply=True,
        remove_files=True,
    )

    assert worktree.is_dir()
    assert result["closed"] == []
    assert "uncommitted changes" in result["skipped"][0]["reason"]


def test_health_cleanup_rejects_protected_branch_and_missing_runtime_readback(
    tmp_path: Path,
) -> None:
    root, _, worktree = _cleanup_fixture(tmp_path, {"pr_state": "merged"})
    subprocess.run(
        ["git", "-C", str(worktree), "branch", "-m", "release/10.0"],
        check=True,
        capture_output=True,
    )
    preflight, runtime = _health_gate(root, worktree)
    runtime.unlink()
    with pytest.raises(ValueError, match="runtime cleanup receipt"):
        cleanup_terminal_worktrees(
            root,
            domain="acme",
            project="app",
            worktree="feature",
            health_preflight=preflight,
            runtime_receipt=runtime,
            apply=True,
            remove_files=True,
        )
    assert worktree.is_dir()

    # Recreate the exact runtime readback and prove the protected branch still blocks.
    preflight, runtime = _health_gate(root, worktree)
    result = cleanup_terminal_worktrees(
        root,
        domain="acme",
        project="app",
        worktree="feature",
        health_preflight=preflight,
        runtime_receipt=runtime,
        apply=True,
        remove_files=True,
    )
    assert worktree.is_dir()
    assert "protected branch" in result["skipped"][0]["reason"]


def test_worktree_cleanup_selector_cannot_touch_another_registered_item(tmp_path: Path) -> None:
    root, _, worktree = _cleanup_fixture(tmp_path, {"pr_state": "merged"})
    preflight, runtime = _health_gate(root, worktree)

    result = cleanup_terminal_worktrees(
        root,
        domain="acme",
        project="app",
        worktree="different-worktree",
        health_preflight=preflight,
        runtime_receipt=runtime,
        apply=True,
        remove_files=True,
    )

    assert result["worktree_selector"] == "different-worktree"
    assert result["candidate_count"] == 0
    assert result["closed"] == []
    assert worktree.is_dir()
    assert len(_registered(root)) == 1


def test_registry_only_cleanup_rejects_an_unsafe_worktree_link(tmp_path: Path) -> None:
    root, _, worktree = _cleanup_fixture(
        tmp_path,
        {"pr_state": "merged", "link": "../outside-project-worktrees"},
    )
    registry = (
        root
        / "domains"
        / "acme"
        / "02-projects"
        / "app"
        / "config"
        / "worktrees.yml"
    )
    before = registry.read_bytes()

    with pytest.raises(ValueError, match="project-relative worktrees path"):
        cleanup_terminal_worktrees(
            root,
            domain="acme",
            project="app",
            worktree="feature",
            apply=True,
            remove_files=False,
        )

    assert registry.read_bytes() == before
    assert worktree.is_dir()


def test_closed_registry_identity_is_exact_id_plus_path(tmp_path: Path) -> None:
    root, _, worktree = _cleanup_fixture(tmp_path, {"pr_state": "merged"})
    project = root / "domains" / "acme" / "02-projects" / "app"
    other_path = project / "worktrees" / "older-feature"
    closed_registry = project / "worktrees" / "closed.yml"
    closed_registry.write_text(
        yaml.safe_dump(
            {
                "project": "app",
                "worktrees": [
                    {
                        "id": "feature",
                        "path": str(other_path),
                        "status": "closed",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = cleanup_terminal_worktrees(
        root,
        domain="acme",
        project="app",
        worktree="feature",
        apply=True,
        remove_files=False,
    )

    rows = yaml.safe_load(closed_registry.read_text(encoding="utf-8"))["worktrees"]
    identities = {(row["id"], row["path"]) for row in rows}
    assert identities == {
        ("feature", str(other_path)),
        ("feature", str(worktree)),
    }
    assert result["closed"][0]["id"] == "feature"
    assert _registered(root) == []


def test_health_cleanup_rejects_stale_runtime_readback(tmp_path: Path) -> None:
    root, _, worktree = _cleanup_fixture(tmp_path, {"pr_state": "merged"})
    preflight, runtime = _health_gate(root, worktree)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    preflight_payload = json.loads(preflight.read_text(encoding="utf-8"))
    preflight_payload["prepared_at"] = (now - timedelta(minutes=30)).isoformat().replace(
        "+00:00", "Z"
    )
    preflight.write_text(json.dumps(preflight_payload), encoding="utf-8")
    runtime_payload = json.loads(runtime.read_text(encoding="utf-8"))
    runtime_payload["preflight_sha256"] = hashlib.sha256(preflight.read_bytes()).hexdigest()
    runtime_payload["verified_at"] = (now - timedelta(minutes=20)).isoformat().replace(
        "+00:00", "Z"
    )
    runtime.write_text(json.dumps(runtime_payload), encoding="utf-8")

    with pytest.raises(ValueError, match="runtime cleanup readback is stale"):
        cleanup_terminal_worktrees(
            root,
            domain="acme",
            project="app",
            worktree="feature",
            health_preflight=preflight,
            runtime_receipt=runtime,
            apply=True,
            remove_files=True,
        )
    assert worktree.is_dir()
    assert len(_registered(root)) == 1


def test_health_prepare_rejects_unproven_shared_runtime_identity(tmp_path: Path) -> None:
    root, _, worktree = _cleanup_fixture(tmp_path, {"pr_state": "merged"})

    with pytest.raises(AutoDevStateError, match="runtime identity is shared"):
        _health_gate(
            root,
            worktree,
            managed_runtime=True,
            runtime_collision=True,
        )

    assert worktree.is_dir()
    assert len(_registered(root)) == 1


def test_health_runtime_identity_can_be_reused_after_hashed_teardown_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, _ = _cleanup_fixture(tmp_path, {"pr_state": "merged"})
    project = root / "domains" / "acme" / "02-projects" / "app"
    current_packet = project / "work-items" / "02-active" / "current"
    current_packet.mkdir(parents=True)
    current_task = project / "state" / "development-runs" / "current" / "tasks" / "item" / "state.json"
    current_task.parent.mkdir(parents=True)
    current_task.write_text("{}\n", encoding="utf-8")
    runtime = {
        "ownership": "managed",
        "provider": "test_target_runtime",
        "identity": "acme-app-reusable-runtime",
        "teardown_command": "true acme-app-reusable-runtime",
        "readback_command": "true acme-app-reusable-runtime",
    }

    prior_packet = project / "work-items" / "03-complete" / "prior"
    prior_packet.mkdir(parents=True)
    cleanup_receipt = prior_packet / "runtime-cleanup.json"
    cleanup_receipt.write_text(
        json.dumps(
            {
                "schema": "auto-dev-runtime-cleanup/v1",
                "runtime_identity": runtime["identity"],
                "provider": runtime["provider"],
                "result": "removed",
                "readback_verified": True,
            }
        ),
        encoding="utf-8",
    )
    wrapper = prior_packet / "health-wrapper.json"
    wrapper.write_text(
        json.dumps(
            {
                "evidence_snapshot": {
                    "evidence": {
                        "resources": {"runtime": {"result": "removed"}},
                        "receipt_audit": {
                            "present": [
                                {
                                    "kind": "runtime_cleanup",
                                    "ref": cleanup_receipt.name,
                                    "sha256": hashlib.sha256(
                                        cleanup_receipt.read_bytes()
                                    ).hexdigest(),
                                }
                            ]
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    prior_autodev = prior_packet / "autodev.json"
    prior_autodev.write_text(
        json.dumps(
            {
                "schema": "auto-dev-work-item/v1",
                "stages": {
                    "health": {
                        "status": "completed",
                        "receipt_refs": [wrapper.name],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    prior_task = project / "state" / "development-runs" / "prior" / "tasks" / "item" / "state.json"
    prior_task.parent.mkdir(parents=True)
    prior_task.write_text(
        json.dumps(
            {
                "canonical_work_id": "acme:app:prior",
                "autodev_path": str(prior_autodev),
                "runtime": runtime,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        auto_dev,
        "_health_stage_receipt_path",
        lambda packet, stage, status, refs: wrapper,
    )

    auto_dev._assert_unique_health_runtime(
        {"domain": "acme", "project": "app"},
        current_packet,
        current_task,
        runtime,
    )
