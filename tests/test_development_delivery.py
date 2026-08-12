from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import threading

import pytest
import yaml
from jsonschema import Draft202012Validator

import genomes_agentic_os.auto_dev_orchestration as auto_dev
import genomes_agentic_os.development_delivery as delivery
from genomes_agentic_os.auto_dev_orchestration import (
    AUTO_DEV_HEALTH_EVIDENCE_SCHEMA,
    AUTO_DEV_STAGE_ORDER,
    AUTO_DEV_STAGE_EVIDENCE_SCHEMA,
    AutoDevStateError,
    prepare_auto_dev_health,
    read_auto_dev_state,
    record_auto_dev_stage,
    sync_delivery_projection,
    validate_auto_dev_packet_manifest,
    validate_auto_dev_stage_order,
)
from genomes_agentic_os.cli import main
from genomes_agentic_os.development_delivery import (
    DevelopmentDeliveryError,
    TaskState,
    append_event,
    classify_validation,
    create_isolated_worktree,
    load_development_profile,
    required_test_layers,
    run_development_stage,
    select_development_repository,
    validate_workflow_contracts,
)
from genomes_agentic_os.lifecycle import sync_active_container
from genomes_agentic_os.scaffold import create_project
from genomes_agentic_os.state import work_items as canonical_work_items
from genomes_agentic_os.state.db import connect as connect_state
from genomes_agentic_os.state.db import default_db_path


def _git(*args: str, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return completed.stdout.strip()


def _work_item_packets(project: Path) -> list[Path]:
    """Return packets across the canonical root, archive, and legacy lanes."""

    work_items = project / "work-items"
    packets: list[Path] = []
    for child in work_items.iterdir():
        if not child.is_dir():
            continue
        if child.name in {"01-intake", "02-active", "03-complete", "99-archived"}:
            packets.extend(
                packet
                for packet in child.iterdir()
                if packet.is_dir() and (packet / "work.yml").is_file()
            )
        elif (child / "work.yml").is_file():
            packets.append(child)
    return sorted(packets)


def _project(
    root: Path,
    repo: Path,
    *,
    canonical: bool = True,
    repository_id: str = "github:acme/app",
    managed_runtime: bool = False,
) -> Path:
    create_project(root, "acme", "app", repo=str(repo))
    project = root / "domains" / "acme" / "02-projects" / "app"
    profile = {
        "version": 1,
        "enabled": True,
        "tracker": {"primary": "linear"},
        "repository": {
            "id": repository_id,
            "root": str(repo),
            "base_branch": "main",
        },
        "worktrees": {"directory": "worktrees", "branch_template": "feature/{ticket}-{slug}"},
        "work_items": {"active_status": "building"},
        "runtime": (
            {
                "ownership": "managed",
                "provider": "test-managed-runtime",
                "identity_template": "{domain}-{project}-{worktree}",
                "teardown_command": "true {runtime_identity}",
                "readback_command": "true {runtime_identity}",
            }
            if managed_runtime
            else {"ownership": "not_managed", "provider": "none", "identity": "not-managed"}
        ),
        "validation": {
            "commands": ["python3 -m pytest tests -q"],
            "test_policy": "risk_based_triangle",
            "ci_fallback_on_environment_failure": True,
        },
        "review": {
            "opposing_harness": {"required": True},
            "authorship": {"ours": ["github:michaelwclark"]},
        },
        "merge": {"policy": "never_auto"},
        "recovery": {"max_attempts": 3, "lease_minutes": 30, "stale_after_minutes": 45},
    }
    if canonical:
        (project / "config" / "development.yml").write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    else:
        # Simulate an installed pre-vNext project where only dev_factory exists.
        (project / "config" / "development.yml").unlink()
        data = yaml.safe_load((project / "project.yml").read_text(encoding="utf-8")) or {}
        data["dev_factory"] = {
            "enabled": True,
            "tracker": {"primary": "linear"},
            "repo": {
                "root": str(repo),
                "default_base_branch": "main",
                "branch_template": "feature/{tracker_id}-{slug}",
            },
            "validation": {"commands": {"local_validation": "python3 -m pytest tests -q"}},
            "merge": {"policy": "never_auto"},
        }
        (project / "project.yml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return project


def _context_kit_policy(root: Path) -> None:
    """Install two selector dimensions that merge into one frozen kit."""

    source_root = root / "harness" / "investigation-config" / "sources"
    source_root.mkdir(parents=True, exist_ok=True)
    common = """\
schema_version: 1
id: rules-engine-kit
kind: source
title: Rules Engine kit
priority: 18
authority:
  class: snapshot-backed test evidence
freshness:
  mode: fixture
requirements:
  kit: contract.yml
---
"""
    (source_root / "caller.md").write_text(
        "---\n"
        + common.replace(
            "authority:",
            "applies_to:\n  domains: [acme]\n  projects: [app]\n"
            "  touched_paths: [src/rules_engine.py]\nauthority:",
        )
        + "\n# Caller context\n\nLoad the caller kit.\n",
        encoding="utf-8",
    )
    (source_root / "rulebook.md").write_text(
        "---\n"
        + common.replace(
            "authority:",
            "applies_to:\n  domains: [acme]\n  projects: [app]\n"
            "  subjects: [rulebook]\nauthority:",
        )
        + "\n# Rulebook context\n\nLoad the rulebook kit.\n",
        encoding="utf-8",
    )


def _repository(tmp_path: Path) -> tuple[Path, str]:
    remote = tmp_path / "remote.git"
    _git("init", "--bare", str(remote))
    repo = tmp_path / "repo"
    _git("init", "-b", "main", str(repo))
    _git("config", "user.email", "test@example.com", cwd=repo)
    _git("config", "user.name", "Test", cwd=repo)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git("add", "README.md", cwd=repo)
    _git("commit", "-m", "base", cwd=repo)
    _git("remote", "add", "origin", str(remote), cwd=repo)
    _git("push", "-u", "origin", "main", cwd=repo)
    return repo, _git("rev-parse", "HEAD", cwd=repo)


def _state(tmp_path: Path, *, max_attempts: int = 3) -> TaskState:
    path = tmp_path / "run" / "tasks" / "cc-1" / "state.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema": "development-task/v1",
                "run_id": "run-1",
                "ticket": "CC-1",
                "state": "discovered",
                "attempts": {},
                "max_attempts": max_attempts,
                "repository": {
                    "id": "github:acme/app",
                    "base_branch": "main",
                },
                "authorship": {"ours": ["github:michaelwclark"]},
                "lease": {"until": None},
                "receipts": [],
                "failure": None,
            }
        ),
        encoding="utf-8",
    )
    return TaskState(path)


def _stage_receipt(
    tmp_path: Path,
    state: str,
    *,
    evidence: dict | None = None,
    status: str = "verified",
) -> str:
    path = tmp_path / "stage-receipts" / f"{state}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    structured = dict(evidence or {"receipt": f"proof:{state}"})
    if state in {"pr_open", "ready_for_merge", "merged"}:
        structured.setdefault("author_identity", "github:michaelwclark")
        structured.setdefault("author_kind", "ours")
    path.write_text(
        json.dumps(
            {
                "schema": "development-stage-evidence/v1",
                "state": state,
                "status": status,
                "summary": f"Verified {state}",
                "evidence": structured,
                "verified_at": "2026-07-19T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    return str(path)


def _set_reviewed_revision(
    task: TaskState,
    revision: str,
    *,
    pull_request: str = "github:acme/app#1",
) -> None:
    value = task.read()
    value["subject_revision"] = revision
    repository = value.get("repository") if isinstance(value.get("repository"), dict) else {}
    scope = {
        **({"repository": repository["id"]} if repository.get("id") else {}),
        **({"base_branch": repository["base_branch"]} if repository.get("base_branch") else {}),
    }
    pr_open = _stage_receipt(
        task.path.parent / "pr-authority",
        "pr_open",
        evidence={
            "provider": "github",
            "pull_request": pull_request,
            "author_identity": "github:michaelwclark",
            "author_kind": "ours",
            "readback_verified": True,
            **scope,
        },
    )
    ready = _stage_receipt(
        task.path.parent / "pr-authority",
        "ready_for_merge",
        evidence={
            "provider": "github",
            "pull_request": pull_request,
            "author_identity": "github:michaelwclark",
            "author_kind": "ours",
            "checks_verified": True,
            "reviews_verified": True,
            "readback_verified": True,
            "source_head_sha": revision,
            "subject_revision": revision,
            **scope,
        },
    )
    value.setdefault("receipts", []).extend(
        [
            {
                "state": "pr_open",
                "ref": pr_open,
                "sha256": hashlib.sha256(Path(pr_open).read_bytes()).hexdigest(),
            },
            {
                "state": "ready_for_merge",
                "ref": ready,
                "sha256": hashlib.sha256(Path(ready).read_bytes()).hexdigest(),
            },
        ]
    )
    task.path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _packet_proof(work_item: Path, stage: str, *, label: str | None = None) -> Path:
    """Create real, packet-local proof for one standalone Auto-Dev receipt."""

    path = work_item / "artifacts" / "test-proofs" / f"{stage}-{label or 'proof'}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"Verified {stage}: {label or 'proof'}\n", encoding="utf-8")
    return path


def _provider_authority(
    task: TaskState,
    *,
    pull_request: str,
    author_identity: str = "github:michaelwclark",
) -> dict[str, object]:
    value = task.read()
    repository = value["repository"]
    ours = {str(item).lower() for item in value["authorship"]["ours"]}
    return {
        "provider": "github",
        "pull_request": pull_request,
        "repository": repository["id"],
        "base_branch": repository["base_branch"],
        "author_identity": author_identity,
        "author_kind": "ours" if author_identity.lower() in ours else "others",
        "readback_verified": True,
    }


def _record_standalone_stage(
    task: TaskState,
    stage: str,
    *,
    revision: str | None = None,
    pull_request: str | None = None,
    status: str = "completed",
) -> dict[str, object]:
    """Record strict standalone evidence using immutable packet-local inputs."""

    value = task.read()
    work_item = Path(value["work_item"])
    evidence_path = work_item / "artifacts" / "test-stage-evidence" / f"{stage}.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    if status == "not_required":
        policy_path = _policy_decision(task, stage)
        structured: dict[str, object] = {"policy_ref": str(policy_path)}
    else:
        proof = _packet_proof(work_item, stage)
        structured = {"receipt_refs": [str(proof)]}
        if stage in {"review_others", "finalize"}:
            assert pull_request is not None
            structured.update(_provider_authority(task, pull_request=pull_request))
            if stage == "finalize":
                structured["readiness_decision"] = "ready_for_merge"
            else:
                structured.update(
                    {"review_mode": "review_no_merge", "review_result": "clean"}
                )
    payload: dict[str, object] = {
        "schema": AUTO_DEV_STAGE_EVIDENCE_SCHEMA,
        "stage": stage,
        "status": status,
        "summary": f"Verified {stage}",
        "evidence": structured,
        "verified_at": "2026-07-20T20:45:00Z",
    }
    if revision:
        payload["subject_revision"] = revision
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")
    return record_auto_dev_stage(
        value["autodev_path"],
        stage=stage,
        evidence_file=evidence_path,
        idempotency_key=f"{value['ticket']}:{stage}:{status}",
    )


def _policy_decision(task: TaskState, stage: str) -> Path:
    """Create one strict decision bound to the task's frozen effective policy."""

    value = task.read()
    work_item = Path(value["work_item"])
    policy_receipt = Path(value["policy_receipt"])
    policy_path = work_item / "artifacts" / "test-stage-evidence" / f"{stage}-policy.json"
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text(
        json.dumps(
            {
                "schema": "auto-dev-stage-policy-decision/v1",
                "work_item_id": work_item.name,
                "canonical_work_id": value["canonical_work_id"],
                "domain": value["domain"],
                "project": value["project"],
                "stage": stage,
                "decision": "not_required",
                "reason": f"Frozen effective policy makes {stage} unnecessary for this item.",
                "decided_by": "test:project-policy",
                "policy_fingerprint": value["policy_fingerprint"],
                "policy_source": {
                    "ref": str(policy_receipt),
                    "sha256": hashlib.sha256(policy_receipt.read_bytes()).hexdigest(),
                },
                "verified_at": "2026-07-20T20:44:00Z",
            }
        ),
        encoding="utf-8",
    )
    return policy_path


def _readiness_authority(
    task: TaskState,
    *,
    subject_revision: str,
    pull_request: str,
    owner: str = "finalize",
) -> dict[str, str]:
    current = read_auto_dev_state(task.read()["autodev_path"])
    work_item = Path(task.read()["work_item"])
    ref = current["stages"][owner]["receipt_refs"][0]
    path = work_item / ref
    authority = _provider_authority(task, pull_request=pull_request)
    return {
        "owner": owner,
        "ref": ref,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "provider": str(authority["provider"]),
        "pull_request": str(authority["pull_request"]),
        "repository": str(authority["repository"]),
        "base_branch": str(authority["base_branch"]),
        "subject_revision": subject_revision,
        "author_identity": str(authority["author_identity"]),
        "author_kind": str(authority["author_kind"]),
    }


def _complete_pre_merge_auto_dev(
    task: TaskState,
    *,
    subject_revision: str,
    pull_request: str,
) -> dict[str, str]:
    """Satisfy every canonical predecessor and return Finalize authority."""

    for stage in ("groom", "detective", "create_artifacts", "document"):
        _record_standalone_stage(task, stage)
    _record_standalone_stage(
        task,
        "review_others",
        revision=subject_revision,
        status="not_required",
    )
    _record_standalone_stage(task, "qa", revision=subject_revision)
    work_item = Path(task.read()["work_item"])
    run_development_stage(
        task.path,
        stage="release_propagation",
        receipts={
            "release_propagation": _stage_receipt(
                work_item / "artifacts" / "delivery",
                "release_propagation",
            )
        },
        idempotency_prefix=f"{task.read()['ticket']}:release-propagation",
    )
    _record_standalone_stage(
        task,
        "finalize",
        revision=subject_revision,
        pull_request=pull_request,
    )
    return _readiness_authority(
        task,
        subject_revision=subject_revision,
        pull_request=pull_request,
    )


def _advance_auto_dev_task_to_ready(
    task: TaskState,
    *,
    subject_revision: str,
    pull_request: str,
) -> None:
    """Advance a generated task with typed, hash-bound milestone evidence."""

    work_item = Path(task.read()["work_item"])
    for state_name in delivery.FORWARD_STATES[
        delivery.FORWARD_STATES.index("worktree_ready")
        + 1 : delivery.FORWARD_STATES.index("ready_for_merge")
        + 1
    ]:
        evidence: dict[str, object] = {"receipt": f"proof:{state_name}"}
        if state_name in {"pr_open", "ready_for_merge"}:
            evidence = _provider_authority(task, pull_request=pull_request)
        if state_name == "ready_for_merge":
            evidence.update(
                {
                    "checks_verified": True,
                    "reviews_verified": True,
                    "subject_revision": subject_revision,
                }
            )
        task.transition(
            state_name,
            receipt=_stage_receipt(
                work_item / "artifacts" / "delivery-setup" / state_name,
                state_name,
                evidence=evidence,
            ),
            idempotency_key=f"setup:{state_name}",
        )
    _set_reviewed_revision(task, subject_revision, pull_request=pull_request)
    sync_delivery_projection(task.path)


@pytest.mark.parametrize("schema_location", ["installed", "package"])
def test_health_schema_resolves_installed_and_packaged_resources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    schema_location: str,
) -> None:
    root = tmp_path / "os"
    root.mkdir()
    (root / ".agentic_root").write_text("", encoding="utf-8")
    work_item = (
        root
        / "domains"
        / "acme"
        / "02-projects"
        / "app"
        / "work-items"
        / "02-active"
        / "item"
    )
    work_item.mkdir(parents=True)
    schema_name = "auto-dev-health-evidence.schema.json"
    if schema_location == "installed":
        schema_path = root / "harness" / "schemas" / schema_name
    else:
        package_root = tmp_path / "site-packages" / "genomes_agentic_os"
        schema_path = package_root / "_resources" / "schemas" / schema_name
        monkeypatch.setattr(auto_dev, "__file__", str(package_root / "auto_dev_orchestration.py"))
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "required": ["schema"],
                "properties": {
                    "schema": {"const": AUTO_DEV_HEALTH_EVIDENCE_SCHEMA},
                },
            }
        ),
        encoding="utf-8",
    )

    auto_dev._validate_health_schema(
        {"schema": AUTO_DEV_HEALTH_EVIDENCE_SCHEMA},
        work_item,
        {"domain": "acme", "project": "app"},
    )


@pytest.mark.parametrize(
    ("domain", "project", "packet_parts"),
    [
        ("acme", "app", ("domains", "acme", "02-projects", "app", "work-items", "item")),
        ("acme", "app", ("acme", "02-projects", "app", "work-items", "03-complete", "item")),
        (
            "shared_factory",
            "genomes_agentic_lib",
            (
                "harness",
                "shared_factory",
                "02-projects",
                "genomes_agentic_lib",
                "work-items",
                "99-archived",
                "item",
            ),
        ),
    ],
)
def test_health_root_uses_marked_owner_across_supported_project_layouts(
    tmp_path: Path,
    domain: str,
    project: str,
    packet_parts: tuple[str, ...],
) -> None:
    root = tmp_path / "os"
    root.mkdir()
    (root / ".agentic_root").write_text("", encoding="utf-8")
    work_item = root.joinpath(*packet_parts)
    work_item.mkdir(parents=True)

    assert auto_dev._health_os_root(
        work_item, {"domain": domain, "project": project}
    ) == root.resolve()


def test_health_root_rejects_shared_factory_path_for_another_domain(
    tmp_path: Path,
) -> None:
    root = tmp_path / "os"
    root.mkdir()
    (root / ".agentic_root").write_text("", encoding="utf-8")
    work_item = (
        root
        / "harness"
        / "shared_factory"
        / "02-projects"
        / "app"
        / "work-items"
        / "item"
    )
    work_item.mkdir(parents=True)

    with pytest.raises(AutoDevStateError, match="cannot derive"):
        auto_dev._health_os_root(
            work_item, {"domain": "acme", "project": "app"}
        )


def test_profile_prefers_canonical_and_translates_legacy(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)
    project = _project(tmp_path / "canonical", repo)
    profile, source = load_development_profile(tmp_path / "canonical", "acme", "app")
    assert source == project / "config" / "development.yml"
    assert profile["validation"]["test_policy"] == "risk_based_triangle"

    legacy_project = _project(tmp_path / "legacy", repo, canonical=False)
    legacy, legacy_source = load_development_profile(tmp_path / "legacy", "acme", "app")
    assert legacy_source == legacy_project / "project.yml"
    assert legacy["compatibility"]["source"] == "project.yml#dev_factory"
    assert legacy["repository"]["base_branch"] == "main"
    assert legacy["worktrees"]["branch_template"] == "feature/{ticket}-{slug}"
    assert legacy["validation"]["commands"] == ["python3 -m pytest tests -q"]


def test_profile_derives_safe_defaults_for_existing_project(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)
    root = tmp_path / "os"
    project = _project(root, repo)
    (project / "config" / "development.yml").unlink()
    profile, source = load_development_profile(root, "acme", "app")
    assert source == project / "project.yml"
    assert profile["compatibility"]["source"] == "project.yml#sources"
    assert profile["repository"] == {"root": str(repo), "base_branch": "main"}
    assert profile["worktrees"]["directory"] == "worktrees"
    assert profile["merge"]["policy"] == "never_auto"


def test_repository_identity_strips_credentials_from_remote_url(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)
    _git(
        "remote",
        "set-url",
        "origin",
        "https://operator:super-secret@github.com/acme/app.git",
        cwd=repo,
    )
    root = tmp_path / "os"
    project = _project(root, repo)
    profile_path = project / "config" / "development.yml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["repository"].pop("id")
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")

    plan = delivery.start_development_run(root, "acme", "app", ["CC-CREDS"])
    serialized = json.dumps(plan, sort_keys=True)

    assert plan["repository"]["id"] == "git:github.com/acme/app"
    assert "operator" not in serialized
    assert "super-secret" not in serialized


def test_configured_stage_order_must_keep_health_last(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)
    root = tmp_path / "os"
    project = _project(root, repo)
    profile_path = project / "config" / "development.yml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    unsafe_order = list(AUTO_DEV_STAGE_ORDER)
    unsafe_order[-2], unsafe_order[-1] = unsafe_order[-1], unsafe_order[-2]
    profile["auto_dev"] = {"stage_order": unsafe_order}
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")

    with pytest.raises(DevelopmentDeliveryError, match="lifecycle precedence"):
        delivery.start_development_run(
            root,
            "acme",
            "app",
            ["CC-ORDER"],
            auto_dev_mode="everything",
        )


@pytest.mark.parametrize(
    ("stage", "after"),
    [
        ("release", "pr_create"),
        ("pr_create", "deploy"),
        ("finalize", "merge"),
    ],
)
def test_configured_stage_order_rejects_lifecycle_deadlocks(stage: str, after: str) -> None:
    order = list(AUTO_DEV_STAGE_ORDER)
    order.remove(stage)
    order.insert(order.index(after) + 1, stage)
    with pytest.raises(AutoDevStateError, match="lifecycle precedence"):
        validate_auto_dev_stage_order(order)


def test_configured_stage_order_allows_safe_friendly_stage_reordering() -> None:
    order = list(AUTO_DEV_STAGE_ORDER)
    order[1], order[2] = order[2], order[1]
    assert validate_auto_dev_stage_order(order) == order

    order.remove("document")
    order.insert(order.index("qa") + 1, "document")
    assert validate_auto_dev_stage_order(order) == order


def test_legacy_profile_stage_subset_upgrades_to_complete_auto_dev_order(
    tmp_path: Path,
) -> None:
    repo, _ = _repository(tmp_path)
    root = tmp_path / "os"
    project = _project(root, repo)
    profile_path = project / "config" / "development.yml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    legacy = [
        name
        for name in AUTO_DEV_STAGE_ORDER
        if name not in {"document", "review_others", "qa", "merge", "release", "deploy", "health"}
    ]
    profile["auto_dev"] = {"stage_order": legacy}
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")

    plan = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-LEGACY"],
        auto_dev_mode="everything",
        apply=False,
    )

    assert plan["auto_dev"]["stage_order"] == list(AUTO_DEV_STAGE_ORDER)


@pytest.mark.parametrize("action", ["merge", "deploy", "closeout", "health"])
def test_downstream_auto_dev_actions_require_existing_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], action: str
) -> None:
    assert main(
        [
            "auto-dev",
            action,
            "acme",
            "app",
            "CC-NEW",
            "--root",
            str(tmp_path),
            "--apply",
        ]
    ) == 2
    assert f"auto-dev {action} requires --state" in capsys.readouterr().err


def test_auto_dev_health_help_describes_existing_state_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["auto-dev", "health", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "existing work item" in output
    assert "never creates a replacement packet or worktree" in output


def test_multi_repository_profile_requires_and_receipts_explicit_selection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = _repository(tmp_path)
    root = tmp_path / "os"
    project = _project(root, repo)
    selected_policy = project / "config/auto_dev/dev_standards-user-web/10_USER_WEB.md"
    selected_policy.parent.mkdir(parents=True, exist_ok=True)
    selected_policy.write_text("# User Web\n\nUse the selected web repository policy.\n", encoding="utf-8")
    path = project / "config/development.yml"
    profile = yaml.safe_load(path.read_text(encoding="utf-8"))
    profile["repository"] = {
        "selection_required": True,
        "catalog": [
            {"id": "backend", "root": str(repo), "base_branch": "main"},
            {
                "id": "user_web",
                "root": str(repo),
                "base_branch": "main",
                "profile_overrides": {
                    "validation": {"commands": ["npm test"]},
                    "policies": {
                        "dev_standards": {"paths": ["config/auto_dev/dev_standards-user-web"]}
                    },
                },
            },
            {
                "id": "invalid",
                "root": str(repo),
                "base_branch": "main",
                "profile_overrides": {"validation": {"commands": "npm test"}},
            },
        ],
    }
    path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")

    loaded, _ = load_development_profile(root, "acme", "app")
    with pytest.raises(DevelopmentDeliveryError, match="repository selection is required"):
        select_development_repository(loaded, None)
    selected = select_development_repository(loaded, "user_web")
    assert selected["repository"]["id"] == "user_web"
    assert selected["validation"]["commands"] == ["npm test"]

    with pytest.raises(DevelopmentDeliveryError, match="invalid selected repository profile"):
        delivery.start_development_run(
            root, "acme", "app", ["CC-11"], repository_id="invalid", apply=False
        )

    with pytest.raises(DevelopmentDeliveryError, match="repository selection is required"):
        delivery.start_development_run(root, "acme", "app", ["CC-12"], apply=False)
    plan = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-12"],
        repository_id="backend",
        apply=False,
    )
    assert plan["repository"]["id"] == "backend"
    assert main(
        [
            "develop",
            "start",
            "acme",
            "app",
            "CC-13",
            "--repository",
            "user_web",
            "--root",
            str(root),
            "--json",
        ]
    ) == 0
    user_web_plan = json.loads(capsys.readouterr().out)
    assert user_web_plan["repository"]["id"] == "user_web"
    assert user_web_plan["policy_sources"]["dev_standards"] == [
        "domains/acme/02-projects/app/config/auto_dev/dev_standards-user-web/10_USER_WEB.md"
    ]


def test_transition_requires_receipt_is_forward_only_and_idempotent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    task = _state(tmp_path)
    assert main(
        [
            "develop",
            "transition",
            str(task.path),
            "--to",
            "claimed",
            "--receipt",
            "untyped-string",
            "--idempotency-key",
            "unsafe",
        ]
    ) == 2
    assert "direct lifecycle transitions are disabled" in capsys.readouterr().err
    assert task.read()["state"] == "discovered"
    claimed = task.transition("claimed", receipt="tracker:CC-1", idempotency_key="claim")
    assert claimed["state"] == "claimed"
    replay = task.transition("claimed", receipt="tracker:CC-1", idempotency_key="claim")
    assert len(replay["receipts"]) == 1
    with pytest.raises(DevelopmentDeliveryError, match="illegal transition"):
        task.transition("worktree_ready", receipt="worktree", idempotency_key="skip")
    with pytest.raises(DevelopmentDeliveryError, match="requires a receipt"):
        task.transition("groom_check", receipt="", idempotency_key="no-receipt")


def test_manual_delivery_stages_require_each_receipt_and_are_idempotent(tmp_path: Path) -> None:
    task = _state(tmp_path)
    for state in ("claimed", "groom_check", "context_ready", "work_item_ready", "worktree_ready"):
        task.transition(state, receipt=f"setup:{state}", idempotency_key=f"setup:{state}")
    portfolio_path = task.path.parent.parent.parent / "portfolio.json"
    portfolio_path.write_text(
        json.dumps(
            {
                "schema": "development-portfolio/v1",
                "run_id": "run-1",
                "state": "dispatching",
                "tasks": [{"ticket": "CC-1", "state_ref": str(task.path)}],
            }
        ),
        encoding="utf-8",
    )
    readiness_receipts = {"planned": _stage_receipt(tmp_path, "planned")}
    ready = run_development_stage(
        task.path,
        stage="readiness",
        receipts=readiness_receipts,
        idempotency_prefix="run:readiness",
    )
    assert ready["state"] == "planned"
    assert json.loads(portfolio_path.read_text(encoding="utf-8"))["state"] == "planned"
    assert run_development_stage(
        task.path,
        stage="readiness",
        receipts={},
        idempotency_prefix="run:readiness",
    )["state"] == "planned"
    stale_portfolio = json.loads(portfolio_path.read_text(encoding="utf-8"))
    stale_portfolio["state"] = "dispatching"
    portfolio_path.write_text(json.dumps(stale_portfolio), encoding="utf-8")
    assert run_development_stage(
        task.path,
        stage="readiness",
        receipts={},
        idempotency_prefix="run:readiness",
    )["state"] == "planned"
    assert json.loads(portfolio_path.read_text(encoding="utf-8"))["state"] == "planned"
    with pytest.raises(DevelopmentDeliveryError, match="local_validation"):
        run_development_stage(
            task.path,
            stage="implementation",
            receipts={"implementing": _stage_receipt(tmp_path, "implementing")},
            idempotency_prefix="run:implementation",
        )
    assert task.read()["state"] == "planned"
    complete = run_development_stage(
        task.path,
        stage="implementation",
        receipts={
            "implementing": _stage_receipt(tmp_path, "implementing"),
            "local_validation": _stage_receipt(tmp_path, "local_validation"),
        },
        idempotency_prefix="run:implementation",
    )
    assert complete["state"] == "local_validation"
    assert json.loads(portfolio_path.read_text(encoding="utf-8"))["state"] == "local_validation"


def test_merge_deploy_and_closeout_are_independently_runnable_stages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, merge_sha = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo)
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": "cc-merge-deploy",
            "path": "/tmp/cc-merge-deploy",
            "branch": "feature/cc-merge-deploy",
            "base_sha": merge_sha,
        },
    )
    run = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-2"],
        run_id="merge-deploy-closeout",
        auto_dev_mode="everything",
        apply=True,
    )
    task_path = Path(run["tasks"][0]["state_ref"])
    task = TaskState(task_path)
    pull_request = "github:acme/app#2"
    _advance_auto_dev_task_to_ready(
        task,
        subject_revision=merge_sha,
        pull_request=pull_request,
    )
    readiness = _complete_pre_merge_auto_dev(
        task,
        subject_revision=merge_sha,
        pull_request=pull_request,
    )

    with pytest.raises(DevelopmentDeliveryError, match="source_head_sha"):
        run_development_stage(
            task_path,
            stage="merge",
            receipts={
                "merged": _stage_receipt(
                    tmp_path,
                    "merged",
                    status="completed",
                    evidence={
                        "merge_sha": merge_sha,
                        "source_head_sha": "d" * 40,
                        **_provider_authority(task, pull_request=pull_request),
                        "readiness_authority": readiness,
                    },
                )
            },
            idempotency_prefix="cc-2:merge-stale-review",
        )
    assert task.read()["state"] == "ready_for_merge"

    merged = run_development_stage(
        task_path,
        stage="merge",
        receipts={
            "merged": _stage_receipt(
                tmp_path,
                "merged",
                status="completed",
                evidence={
                    "merge_sha": merge_sha,
                    "source_head_sha": merge_sha,
                    **_provider_authority(task, pull_request=pull_request),
                    "readiness_authority": readiness,
                },
            )
        },
        idempotency_prefix="cc-2:merge",
    )
    assert merged["state"] == "merged"
    projection = read_auto_dev_state(task.read()["autodev_path"])
    assert projection["stages"]["merge"]["status"] == "completed"
    assert projection["stages"]["deploy"]["status"] == "not_started"
    assert projection["stages"]["closeout"]["status"] == "not_started"
    _record_standalone_stage(task, "release", revision=merge_sha)

    with pytest.raises(DevelopmentDeliveryError, match="exact merged deployed_revision"):
        run_development_stage(
            task_path,
            stage="deploy",
            receipts={
                "deployment_pending": _stage_receipt(tmp_path, "deployment_pending"),
                "deploying": _stage_receipt(tmp_path, "deploying"),
                "post_deploy_validation": _stage_receipt(
                    tmp_path,
                    "post_deploy_validation",
                    evidence={
                        "deployed_revision": "deadbee",
                        "artifact_ref": "registry.example/app@sha256:1234",
                        "environment": "test",
                        "readback_verified": True,
                    },
                ),
            },
            idempotency_prefix="cc-2:deploy-invalid",
        )
    assert task.read()["state"] == "merged"

    deployed = run_development_stage(
        task_path,
        stage="deploy",
        receipts={
            "deployment_pending": _stage_receipt(tmp_path, "deployment_pending"),
            "deploying": _stage_receipt(tmp_path, "deploying"),
            "post_deploy_validation": _stage_receipt(
                tmp_path,
                "post_deploy_validation",
                evidence={
                    "deployed_revision": merge_sha,
                    "artifact_ref": "registry.example/app@sha256:5678",
                    "environment": "test",
                    "readback_verified": True,
                },
            ),
        },
        idempotency_prefix="cc-2:deploy",
    )
    assert deployed["state"] == "post_deploy_validation"
    projection = read_auto_dev_state(task.read()["autodev_path"])
    assert projection["stages"]["deploy"]["status"] == "completed"
    assert projection["stages"]["closeout"]["status"] == "not_started"

    closed = run_development_stage(
        task_path,
        stage="closeout",
        receipts={
            "delivery_complete": _stage_receipt(
                tmp_path,
                "delivery_complete",
                evidence={"closeout_verified": True, "receipt_refs": ["tracker:CC-2"]},
            )
        },
        idempotency_prefix="cc-2:closeout",
    )
    assert closed["state"] == "delivery_complete"
    projection = read_auto_dev_state(task.read()["autodev_path"])
    assert projection["stages"]["closeout"]["status"] == "completed"
    assert projection["stages"]["health"]["status"] == "not_started"


def test_policy_backed_no_deploy_flow_is_typed_and_cli_runnable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, merge_sha = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo)
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": "cc-policy-deploy",
            "path": "/tmp/cc-policy-deploy",
            "branch": "feature/cc-policy-deploy",
            "base_sha": merge_sha,
        },
    )
    run = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-POLICY"],
        run_id="policy-backed-no-deploy",
        auto_dev_mode="everything",
        apply=True,
    )
    task = TaskState(Path(run["tasks"][0]["state_ref"]))
    pull_request = "github:acme/app#1"
    _advance_auto_dev_task_to_ready(
        task,
        subject_revision=merge_sha,
        pull_request=pull_request,
    )
    readiness = _complete_pre_merge_auto_dev(
        task,
        subject_revision=merge_sha,
        pull_request=pull_request,
    )
    merge_receipt = _stage_receipt(
        tmp_path,
        "merged",
        status="completed",
        evidence={
            "merge_sha": merge_sha,
            "source_head_sha": merge_sha,
            **_provider_authority(task, pull_request=pull_request),
            "readiness_authority": readiness,
        },
    )
    assert main(
        [
            "develop",
            "stage",
            str(task.path),
            "--stage",
            "merge",
            "--receipt",
            f"merged={merge_receipt}",
            "--idempotency-prefix",
            "cc-1:merge",
        ]
    ) == 0
    _record_standalone_stage(task, "release", revision=merge_sha)
    deployment_policy = _policy_decision(task, "deploy")
    pending = _stage_receipt(
        tmp_path,
        "deployment_pending",
        status="not_required",
        evidence={"policy_ref": str(deployment_policy)},
    )
    deploying = _stage_receipt(
        tmp_path,
        "deploying",
        status="not_required",
        evidence={"policy_ref": str(deployment_policy)},
    )
    validated = _stage_receipt(
        tmp_path,
        "post_deploy_validation",
        status="not_required",
        evidence={
            "policy_ref": str(deployment_policy),
            "deployment_applicable": False,
        },
    )
    assert main(
        [
            "develop",
            "stage",
            str(task.path),
            "--stage",
            "deploy",
            "--receipt",
            f"deployment_pending={pending}",
            "--receipt",
            f"deploying={deploying}",
            "--receipt",
            f"post_deploy_validation={validated}",
            "--idempotency-prefix",
            "cc-1:deploy",
        ]
    ) == 0
    current = task.read()
    assert current["state"] == "post_deploy_validation"
    assert current["terminal_revision"] == merge_sha
    assert current["deployed_revision"] == merge_sha
    assert current["deployment_applicable"] is False


def test_merge_rejects_a_different_pull_request_with_the_same_reviewed_head(
    tmp_path: Path,
) -> None:
    task = _state(tmp_path)
    for state_name in delivery.FORWARD_STATES[
        1 : delivery.FORWARD_STATES.index("ready_for_merge") + 1
    ]:
        task.transition(
            state_name,
            receipt=f"setup:{state_name}",
            idempotency_key=f"setup:{state_name}",
        )
    reviewed_head = "a" * 40
    _set_reviewed_revision(
        task,
        reviewed_head,
        pull_request="github:acme/app#1",
    )
    with pytest.raises(DevelopmentDeliveryError, match="must match ready_for_merge"):
        run_development_stage(
            task.path,
            stage="merge",
            receipts={
                "merged": _stage_receipt(
                    tmp_path,
                    "merged",
                    status="completed",
                    evidence={
                        "merge_sha": "b" * 40,
                        "source_head_sha": reviewed_head,
                        "provider": "github",
                        "pull_request": "github:acme/app#2",
                        "repository": "github:acme/app",
                        "base_branch": "main",
                        "author_identity": "github:michaelwclark",
                        "author_kind": "ours",
                        "readback_verified": True,
                    },
                )
            },
            idempotency_prefix="cc-1:wrong-pr",
        )
    assert task.read()["state"] == "ready_for_merge"


def test_closeout_cannot_backfill_merge_or_deploy_from_ready_for_merge(
    tmp_path: Path,
) -> None:
    task = _state(tmp_path)
    for state_name in delivery.FORWARD_STATES[
        1 : delivery.FORWARD_STATES.index("ready_for_merge") + 1
    ]:
        task.transition(
            state_name,
            receipt=f"setup:{state_name}",
            idempotency_key=f"setup:{state_name}",
        )
    with pytest.raises(DevelopmentDeliveryError, match="post_deploy_validation through delivery_complete"):
        run_development_stage(
            task.path,
            stage="closeout",
            receipts={},
            idempotency_prefix="cc-1:strict-closeout",
        )
    assert task.read()["state"] == "ready_for_merge"


def test_failure_retries_then_blocks_and_recovery_resumes_owner_state(tmp_path: Path) -> None:
    task = _state(tmp_path, max_attempts=2)
    task.transition("claimed", receipt="tracker", idempotency_key="claim")
    failed = task.fail(
        kind="provider_unavailable", detail="timeout", receipt="logs/timeout", idempotency_key="fail-1"
    )
    assert failed["state"] == "claimed"
    assert failed["failure"]["recoverable"] is True
    replay = task.fail(
        kind="provider_unavailable", detail="timeout", receipt="logs/timeout", idempotency_key="fail-1"
    )
    assert replay["attempts"]["provider_unavailable"] == 1
    recovered = task.recover(receipt="provider healthy", idempotency_key="recover-1")
    assert recovered["state"] == "claimed"
    recovered_replay = task.recover(receipt="ignored replay", idempotency_key="recover-1")
    assert recovered_replay == recovered
    assert len(recovered_replay["receipts"]) == 2
    blocked = task.fail(
        kind="provider_unavailable", detail="timeout", receipt="logs/timeout-2", idempotency_key="fail-2"
    )
    assert blocked["state"] == "blocked"
    assert blocked["failure"]["recoverable"] is False


def test_executor_handoff_can_recover_after_retry_budget_exhaustion(tmp_path: Path) -> None:
    task = _state(tmp_path, max_attempts=2)
    first = task.record_executor_unavailable(stage="groom")
    assert first["handoff"]["status"] == "pending"
    task.recover(receipt="executor repaired", idempotency_key="recover-first-handoff")

    exhausted = task.record_executor_unavailable(stage="groom")
    assert exhausted["handoff"]["status"] == "blocked"
    assert task.read()["state"] == "blocked"

    recovered = task.recover(
        receipt="executor admission restored", idempotency_key="recover-exhausted-handoff"
    )
    assert recovered["state"] == "discovered"
    assert recovered["failure"] is None


def test_executor_handoff_reuses_orphaned_receipt_after_interrupted_state_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _state(tmp_path)
    original_atomic_json = delivery._atomic_json

    def interrupt_task_state_write(path: Path, value: dict[str, object]) -> None:
        if path == task.path:
            raise OSError("simulated interruption after handoff receipt")
        original_atomic_json(path, value)

    monkeypatch.setattr(delivery, "_atomic_json", interrupt_task_state_write)
    with pytest.raises(OSError, match="simulated interruption"):
        task.record_executor_unavailable(stage="groom")
    receipt_path = task.path.parent / "handoffs" / "executor-unavailable-attempt-01.json"
    assert receipt_path.is_file()
    assert task.read()["failure"] is None

    monkeypatch.setattr(delivery, "_atomic_json", original_atomic_json)
    resumed = task.record_executor_unavailable(stage="groom")
    assert resumed["replayed"] is False
    assert resumed["handoff"] == json.loads(receipt_path.read_text(encoding="utf-8"))
    assert task.read()["attempts"]["executor_unavailable"] == 1


def test_stale_lease_is_classified_for_recovery(tmp_path: Path) -> None:
    task = _state(tmp_path)
    state = task.read()
    state["lease"] = {"until": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()}
    task.path.write_text(json.dumps(state), encoding="utf-8")
    result = task.recover_stale_lease()
    assert result == {"recovered": True, "reason": "lease_expired"}
    assert task.read()["failure"]["kind"] == "lease_expired"


def test_heartbeat_renews_worker_lease_without_changing_state(tmp_path: Path) -> None:
    task = _state(tmp_path)
    state = task.heartbeat(owner="worker-1", lease_minutes=10, idempotency_key="heartbeat-1")
    assert state["state"] == "discovered"
    assert state["lease"]["owner"] == "worker-1"
    assert state["lease"]["heartbeat_at"] < state["lease"]["until"]
    replay = task.heartbeat(owner="worker-1", lease_minutes=99, idempotency_key="heartbeat-1")
    assert replay["lease"] == state["lease"]


def test_event_append_is_idempotent(tmp_path: Path) -> None:
    ledger = tmp_path / "events.jsonl"
    assert append_event(ledger, event_type="x", idempotency_key="same", payload={})["appended"] is True
    assert append_event(ledger, event_type="x", idempotency_key="same", payload={})["appended"] is False
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1


def test_risk_based_testing_and_environment_classification() -> None:
    assert required_test_layers("micro") == ["unit"]
    assert required_test_layers("standard") == ["unit", "integration"]
    assert required_test_layers("high") == ["unit", "integration", "end_to_end"]
    assert classify_validation(returncode=0) == "passed"
    assert classify_validation(returncode=1) == "code_failed"
    assert classify_validation(returncode=1, environment_evidence="docker unavailable") == "environment_unavailable"


def test_local_validation_ci_deferral_is_typed_and_profile_gated(tmp_path: Path) -> None:
    task = _state(tmp_path)
    profile = tmp_path / "development.yml"
    profile.write_text(
        yaml.safe_dump(
            {
                "validation": {
                    "ci_fallback_on_environment_failure": True,
                }
            }
        ),
        encoding="utf-8",
    )
    value = task.read()
    value["profile_source"] = str(profile)
    task.path.write_text(json.dumps(value), encoding="utf-8")
    for state in ("claimed", "groom_check", "context_ready", "work_item_ready", "worktree_ready"):
        task.transition(state, receipt=f"setup:{state}", idempotency_key=f"setup:{state}")
    run_development_stage(
        task.path,
        stage="readiness",
        receipts={"planned": _stage_receipt(tmp_path, "planned")},
        idempotency_prefix="ci-fallback:readiness",
    )
    unavailable = {
        "compileall": "passed",
        "unavailable_check": {
            "command": "pytest tests/test_changed_behavior.py",
            "classification": "infrastructure",
            "reason": "private test dependency is unavailable locally",
        },
    }
    with pytest.raises(DevelopmentDeliveryError, match="must use status=deferred_to_ci"):
        run_development_stage(
            task.path,
            stage="implementation",
            receipts={
                "implementing": _stage_receipt(tmp_path, "implementing"),
                "local_validation": _stage_receipt(
                    tmp_path,
                    "local_validation",
                    evidence=unavailable,
                    status="passed",
                ),
            },
            idempotency_prefix="ci-fallback:invalid-pass",
        )
    result = run_development_stage(
        task.path,
        stage="implementation",
        receipts={
            "implementing": _stage_receipt(tmp_path, "implementing"),
            "local_validation": _stage_receipt(
                tmp_path,
                "local_validation",
                evidence=unavailable,
                status="deferred_to_ci",
            ),
        },
        idempotency_prefix="ci-fallback:valid",
    )
    assert result["state"] == "local_validation"


def test_local_validation_ci_deferral_blocks_without_profile_authority(tmp_path: Path) -> None:
    task = _state(tmp_path)
    profile = tmp_path / "development.yml"
    profile.write_text(
        yaml.safe_dump(
            {"validation": {"ci_fallback_on_environment_failure": False}}
        ),
        encoding="utf-8",
    )
    value = task.read()
    value["profile_source"] = str(profile)
    task.path.write_text(json.dumps(value), encoding="utf-8")
    for state in ("claimed", "groom_check", "context_ready", "work_item_ready", "worktree_ready"):
        task.transition(state, receipt=f"setup:{state}", idempotency_key=f"setup:{state}")
    run_development_stage(
        task.path,
        stage="readiness",
        receipts={"planned": _stage_receipt(tmp_path, "planned")},
        idempotency_prefix="no-fallback:readiness",
    )
    with pytest.raises(DevelopmentDeliveryError, match="enables ci_fallback"):
        run_development_stage(
            task.path,
            stage="implementation",
            receipts={
                "implementing": _stage_receipt(tmp_path, "implementing"),
                "local_validation": _stage_receipt(
                    tmp_path,
                    "local_validation",
                    evidence={
                        "compileall": "passed",
                        "unavailable_check": {
                            "command": "pytest tests/test_changed_behavior.py",
                            "classification": "environment_unavailable",
                            "reason": "docker is unavailable",
                        },
                    },
                    status="deferred_to_ci",
                ),
            },
            idempotency_prefix="no-fallback:implementation",
        )


@pytest.mark.parametrize(
    ("base_allows", "selected_allows"),
    [(True, False), (False, True)],
)
def test_ci_deferral_uses_frozen_selected_repository_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    base_allows: bool,
    selected_allows: bool,
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    project = _project(root, repo)
    _context_kit_policy(root)
    profile_path = project / "config" / "development.yml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["validation"]["ci_fallback_on_environment_failure"] = base_allows
    profile["repository"] = {
        "selection_required": True,
        "catalog": [
            {
                "id": "selected",
                "root": str(repo),
                "base_branch": "main",
                "profile_overrides": {
                    "validation": {
                        "ci_fallback_on_environment_failure": selected_allows
                    }
                },
            }
        ],
    }
    profile_path.write_text(
        yaml.safe_dump(profile, sort_keys=False), encoding="utf-8"
    )
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": "ci-selected",
            "path": "/tmp/ci-selected",
            "branch": "feature/ci-selected",
            "base_sha": base_sha,
        },
    )
    run = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-CI-SELECTED"],
        run_id=f"ci-selected-{base_allows}-{selected_allows}",
        repository_id="selected",
        apply=True,
    )
    task = TaskState(Path(run["tasks"][0]["state_ref"]))
    frozen = json.loads(Path(task.read()["policy_receipt"]).read_text(encoding="utf-8"))
    assert (
        frozen["selected_profile"]["validation"][
            "ci_fallback_on_environment_failure"
        ]
        is selected_allows
    )
    run_development_stage(
        task.path,
        stage="readiness",
        receipts={
            "planned": _stage_receipt(
                tmp_path / f"readiness-{base_allows}-{selected_allows}",
                "planned",
            )
        },
        idempotency_prefix=f"ci-selected:{base_allows}:{selected_allows}:readiness",
    )

    # Drift both the base and selected override after launch. The immutable
    # effective-policy receipt, not this mutable YAML, remains authoritative.
    profile["validation"]["ci_fallback_on_environment_failure"] = not selected_allows
    profile["repository"]["catalog"][0]["profile_overrides"]["validation"][
        "ci_fallback_on_environment_failure"
    ] = not selected_allows
    profile_path.write_text(
        yaml.safe_dump(profile, sort_keys=False), encoding="utf-8"
    )
    unavailable = {
        "compileall": "passed",
        "unavailable_check": {
            "command": "pytest tests/test_changed_behavior.py",
            "classification": "infrastructure",
            "reason": "private test dependency is unavailable locally",
        },
    }
    receipts = {
        "implementing": _stage_receipt(
            tmp_path / f"implementation-{base_allows}-{selected_allows}",
            "implementing",
        ),
        "local_validation": _stage_receipt(
            tmp_path / f"implementation-{base_allows}-{selected_allows}",
            "local_validation",
            evidence=unavailable,
            status="deferred_to_ci",
        ),
    }
    if selected_allows:
        result = run_development_stage(
            task.path,
            stage="implementation",
            receipts=receipts,
            idempotency_prefix=(
                f"ci-selected:{base_allows}:{selected_allows}:implementation"
            ),
        )
        assert result["state"] == "local_validation"
    else:
        with pytest.raises(DevelopmentDeliveryError, match="enables ci_fallback"):
            run_development_stage(
                task.path,
                stage="implementation",
                receipts=receipts,
                idempotency_prefix=(
                    f"ci-selected:{base_allows}:{selected_allows}:implementation"
                ),
            )


@pytest.mark.parametrize(
    ("corruption", "message"),
    [
        ("missing", "pinned effective policy receipt is missing"),
        ("missing_ref", "pinned effective policy receipt reference is missing"),
        ("inner_tamper", "fingerprint does not match its contents"),
        ("empty_validation", "enables ci_fallback"),
    ],
)
def test_ci_deferral_fails_closed_for_frozen_policy_corruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
    message: str,
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    project = _project(root, repo)
    profile_path = project / "config" / "development.yml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["validation"]["ci_fallback_on_environment_failure"] = True
    profile["repository"] = {
        "selection_required": True,
        "catalog": [
            {
                "id": "selected",
                "root": str(repo),
                "base_branch": "main",
                "profile_overrides": {
                    "validation": {
                        "ci_fallback_on_environment_failure": False
                    }
                },
            }
        ],
    }
    profile_path.write_text(
        yaml.safe_dump(profile, sort_keys=False), encoding="utf-8"
    )
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": "ci-corruption",
            "path": "/tmp/ci-corruption",
            "branch": "feature/ci-corruption",
            "base_sha": base_sha,
        },
    )
    run = delivery.start_development_run(
        root,
        "acme",
        "app",
        [f"CC-CI-{corruption}"],
        run_id=f"ci-corruption-{corruption}",
        repository_id="selected",
        apply=True,
    )
    task = TaskState(Path(run["tasks"][0]["state_ref"]))
    run_development_stage(
        task.path,
        stage="readiness",
        receipts={
            "planned": _stage_receipt(
                tmp_path / f"corruption-{corruption}", "planned"
            )
        },
        idempotency_prefix=f"ci-corruption:{corruption}:readiness",
    )
    policy_path = Path(task.read()["policy_receipt"])
    if corruption == "missing":
        policy_path.unlink()
    elif corruption == "missing_ref":
        task_value = task.read()
        task_value["policy_receipt"] = ""
        task.path.write_text(
            json.dumps(task_value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    else:
        frozen = json.loads(policy_path.read_text(encoding="utf-8"))
        frozen["selected_profile"]["validation"] = (
            {"ci_fallback_on_environment_failure": True}
            if corruption == "inner_tamper"
            else {}
        )
        selected_payload = {
            key: value
            for key, value in frozen["selected_profile"].items()
            if key != "sha256"
        }
        frozen["selected_profile"]["sha256"] = delivery._json_sha256(
            selected_payload
        )
        if corruption == "empty_validation":
            frozen["fingerprint"] = delivery._effective_policy_snapshot_fingerprint(
                frozen
            )
            task_value = task.read()
            task_value["policy_fingerprint"] = frozen["fingerprint"]
            task.path.write_text(
                json.dumps(task_value, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        policy_path.write_text(
            json.dumps(frozen, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    unavailable = {
        "compileall": "passed",
        "unavailable_check": {
            "command": "pytest tests/test_changed_behavior.py",
            "classification": "infrastructure",
            "reason": "private test dependency is unavailable locally",
        },
    }
    with pytest.raises(DevelopmentDeliveryError, match=message):
        run_development_stage(
            task.path,
            stage="implementation",
            receipts={
                "implementing": _stage_receipt(
                    tmp_path / f"corruption-{corruption}", "implementing"
                ),
                "local_validation": _stage_receipt(
                    tmp_path / f"corruption-{corruption}",
                    "local_validation",
                    evidence=unavailable,
                    status="deferred_to_ci",
                ),
            },
            idempotency_prefix=f"ci-corruption:{corruption}:implementation",
        )


@pytest.mark.parametrize(
    ("corruption", "message"),
    [
        ("selected_profile", "fingerprint does not match its contents"),
        ("policy_body", "changed auto_dev content"),
        (
            "folder_profile",
            "changed repository folder profile content",
        ),
    ],
)
def test_resume_rejects_corrupted_effective_policy_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
    message: str,
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    project = _project(root, repo)
    policy_source = project / "config" / "auto_dev" / "00-frozen-policy.md"
    policy_source.parent.mkdir(parents=True, exist_ok=True)
    policy_source.write_text(
        "# Frozen Auto-Dev policy\n\nPreserve this exact body.\n",
        encoding="utf-8",
    )
    folder_profile = repo / "auto_dev" / "profile.yml"
    folder_profile.parent.mkdir(parents=True, exist_ok=True)
    folder_profile.write_text(
        yaml.safe_dump(
            {
                "api_version": "auto-dev-folder/v1",
                "identity": {"domain": "acme", "project": "app"},
                "lifecycle": {
                    "build": {"command": "make build"},
                    "validate": {"commands": ["make test"]},
                    "release": {"required": True},
                    "document": {"required": True},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": "policy-resume",
            "path": "/tmp/policy-resume",
            "branch": "feature/policy-resume",
            "base_sha": base_sha,
        },
    )
    run = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-POLICY-RESUME"],
        run_id="policy-resume",
        auto_dev_mode="everything",
        apply=True,
    )
    task = TaskState(Path(run["tasks"][0]["state_ref"]))
    policy_path = Path(task.read()["policy_receipt"])
    frozen = json.loads(policy_path.read_text(encoding="utf-8"))
    if corruption == "selected_profile":
        frozen["selected_profile"]["validation"][
            "ci_fallback_on_environment_failure"
        ] = False
        frozen["selected_profile"]["sha256"] = delivery._json_sha256(
            {
                key: value
                for key, value in frozen["selected_profile"].items()
                if key != "sha256"
            }
        )
    elif corruption == "policy_body":
        frozen["planes"]["auto_dev"]["sources"][0]["body_markdown"] = (
            "Tampered policy body.\n"
        )
    else:
        frozen["folder_profile"]["lifecycle"]["build"]["command"] = (
            "make unreviewed-package"
        )
    policy_path.write_text(
        json.dumps(frozen, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        DevelopmentDeliveryError,
        match=message,
    ):
        delivery.start_development_run(
            root,
            "acme",
            "app",
            ["CC-POLICY-RESUME"],
            run_id="policy-resume",
            auto_dev_mode="everything",
            selected_work_item=Path(task.read()["work_item"]),
            apply=True,
        )


def _legacy_effective_policy_snapshot() -> dict:
    planes: dict[str, dict] = {}
    for index, name in enumerate(delivery.DEVELOPMENT_POLICY_PLANES):
        body = f"# Frozen {name}\n\nKeep this policy exact.\n"
        raw = body if index % 2 == 0 else f"{body}\n"
        source = {
            "scope": "root",
            "rank": 0,
            "source_ref": f"legacy/{name}.md",
            "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "frontmatter": {},
            "body_markdown": body,
        }
        digest_input = [
            {
                "scope": source["scope"],
                "rank": source["rank"],
                "source_ref": source["source_ref"],
                "sha256": source["sha256"],
            }
        ]
        planes[name] = {
            "schema": "markdown-policy-plane/v1",
            "plane": name,
            "sources": [source],
            "fingerprint": hashlib.sha256(
                json.dumps(
                    digest_input,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        }
    snapshot = {
        "schema": "development-effective-policies/v1",
        "domain": "acme",
        "project": "app",
        "planes": planes,
    }
    snapshot["fingerprint"] = delivery._effective_policy_snapshot_fingerprint(
        snapshot
    )
    return snapshot


def test_legacy_policy_snapshot_self_authenticates_bodies_and_rejects_tamper() -> None:
    snapshot = _legacy_effective_policy_snapshot()
    assert (
        delivery._validate_effective_policy_snapshot(
            snapshot,
            require_selected_profile=False,
        )
        is None
    )
    snapshot["planes"]["auto_dev"]["sources"][0]["body_markdown"] = (
        "# Rewritten policy\n"
    )
    with pytest.raises(
        DevelopmentDeliveryError,
        match="unbound legacy auto_dev content",
    ):
        delivery._validate_effective_policy_snapshot(
            snapshot,
            require_selected_profile=False,
        )


def test_legacy_loaded_folder_profile_without_content_binding_fails_closed() -> None:
    snapshot = _legacy_effective_policy_snapshot()
    snapshot["folder_profile"] = {
        "schema": "auto-dev-folder-profile/v1",
        "status": "loaded",
        "source_ref": "auto_dev/profile.yml",
        "sha256": "a" * 64,
        "lifecycle": {"build": {"command": "make build"}},
    }
    snapshot["fingerprint"] = delivery._effective_policy_snapshot_fingerprint(
        snapshot
    )
    with pytest.raises(
        DevelopmentDeliveryError,
        match="unbound legacy repository folder profile content",
    ):
        delivery._validate_effective_policy_snapshot(
            snapshot,
            require_selected_profile=False,
        )


def test_real_worktree_uses_exact_remote_base_and_project_storage(tmp_path: Path) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    project = _project(root, repo)
    profile, _ = load_development_profile(root, "acme", "app")
    result = create_isolated_worktree(
        os_root=root,
        domain="acme",
        project="app",
        profile=profile,
        ticket="CC-9",
        title="Safe delivery",
    )
    worktree = Path(result["path"])
    assert worktree.parent == project / "worktrees"
    assert result["base_sha"] == base_sha
    assert _git("rev-parse", "HEAD", cwd=worktree) == base_sha
    registry = yaml.safe_load((project / "worktrees" / "index.yml").read_text(encoding="utf-8"))
    assert any(row["id"] == result["name"] for row in registry["worktrees"])


def test_cli_dry_run_is_non_mutating_and_multi_ticket(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, _ = _repository(tmp_path)
    root = tmp_path / "os"
    project = _project(root, repo)
    before = sorted((project / "worktrees").iterdir())
    assert main(["develop", "start", "acme", "app", "CC-1", "CC-2", "--root", str(root)]) == 0
    output = capsys.readouterr().out
    assert "CC-1" in output and "CC-2" in output
    assert not (project / "state" / "development-runs").exists()
    assert sorted((project / "worktrees").iterdir()) == before


def test_multi_ticket_provisioning_preserves_success_and_auto_recovers_retryable_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo)

    def first_attempt(**kwargs):
        if kwargs["ticket"] == "CC-1":
            raise DevelopmentDeliveryError("git fetch provider unavailable")
        return {"name": "cc-2", "path": "/tmp/cc-2", "branch": "feature/cc-2", "base_sha": base_sha}

    monkeypatch.setattr(delivery, "create_isolated_worktree", first_attempt)
    first = delivery.start_development_run(
        root, "acme", "app", ["CC-1", "CC-2"], run_id="portfolio-recovery", apply=True
    )
    assert first["state"] == "partial"
    first_states = {row["ticket"]: TaskState(Path(row["state_ref"])).read() for row in first["tasks"]}
    assert first_states["CC-1"]["failure"]["recoverable"] is True
    assert first_states["CC-2"]["state"] == "worktree_ready"

    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": kwargs["ticket"].lower(),
            "path": f"/tmp/{kwargs['ticket'].lower()}",
            "branch": f"feature/{kwargs['ticket'].lower()}",
            "base_sha": base_sha,
        },
    )
    resumed = delivery.start_development_run(
        root, "acme", "app", ["CC-1", "CC-2"], run_id="portfolio-recovery", apply=True
    )
    assert resumed["state"] == "dispatching"
    resumed_states = {row["ticket"]: TaskState(Path(row["state_ref"])).read() for row in resumed["tasks"]}
    assert all(state["state"] == "worktree_ready" for state in resumed_states.values())
    assert resumed_states["CC-1"]["attempts"]["provider_unavailable"] == 1
    rollup = root / "harness" / "shared_factory" / "00-control-plane" / "development-runs.jsonl"
    assert rollup.is_file()
    rollup_events = [json.loads(line) for line in rollup.read_text(encoding="utf-8").splitlines()]
    assert any(event["type"] == "development.task.failed" for event in rollup_events)
    assert any(event["type"] == "development.task.recovered" for event in rollup_events)
    for state in resumed_states.values():
        receipt = Path(state["work_item"]) / "artifacts" / "development-delivery" / "run.json"
        assert json.loads(receipt.read_text(encoding="utf-8"))["run_id"] == "portfolio-recovery"


def _historical_origin_main_failure(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    """Create the pre-AGE-179 failure shape without creating task source effects."""

    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    project = _project(root, repo)
    profile_path = project / "config" / "development.yml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["repository"]["base_branch"] = "origin/main"
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    first = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-179"],
        titles={"CC-179": "Retry selection"},
        run_id="origin-main-retry",
        apply=True,
    )
    task_path = Path(first["tasks"][0]["state_ref"])
    failed = TaskState(task_path).read()
    assert failed["state"] == "work_item_ready"
    assert failed["failure"]["kind"] == "provisioning_failed"
    assert "remote ref origin/main" in failed["failure"]["detail"]
    profile["repository"]["base_branch"] = "main"
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    return root, repo, task_path, base_sha


def test_correct_failed_base_selection_preserves_failure_then_allows_retry(tmp_path: Path) -> None:
    root, repo, task_path, base_sha = _historical_origin_main_failure(tmp_path)
    before = TaskState(task_path).read()
    portfolio_path = task_path.parent.parent.parent / "portfolio.json"
    assert json.loads(portfolio_path.read_text(encoding="utf-8"))["repository"]["base_branch"] == "origin/main"

    corrected = delivery.correct_failed_base_selection(
        task_path,
        corrected_base_branch="main",
        idempotency_key="cc-179:correct-main",
        apply=True,
    )

    assert corrected["result"] == "corrected"
    assert corrected["base_sha"] == base_sha
    receipt = Path(corrected["receipt"])
    recorded = json.loads(receipt.read_text(encoding="utf-8"))
    assert recorded["original"]["failure"] == before["failure"]
    assert recorded["original"]["repository"]["base_branch"] == "origin/main"
    assert recorded["corrected"]["repository"]["base_branch"] == "main"
    assert recorded["preflight"]["no_worktree_or_runtime_effect"] is True
    selected = TaskState(task_path).read()
    assert selected["failure"] == before["failure"]
    assert selected["repository"]["base_branch"] == "main"
    assert selected["base_selection_corrections"][0]["receipt"] == str(receipt)
    portfolio = json.loads(portfolio_path.read_text(encoding="utf-8"))
    assert portfolio["repository"]["base_branch"] == "main"
    assert _git("branch", "--list", "feature/cc-179-retry-selection", cwd=repo) == ""

    resumed = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-179"],
        titles={"CC-179": "Retry selection"},
        run_id="origin-main-retry",
        apply=True,
    )
    assert resumed["state"] == "dispatching"
    recovered = TaskState(task_path).read()
    assert recovered["state"] == "worktree_ready"
    assert recovered["failure"] is None
    assert recovered["base_selection_corrections"][0]["receipt"] == str(receipt)


def test_historical_origin_main_failure_cannot_resume_without_correction(tmp_path: Path) -> None:
    root, _, task_path, _ = _historical_origin_main_failure(tmp_path)

    with pytest.raises(DevelopmentDeliveryError, match="requires the recorded base-selection correction"):
        delivery.start_development_run(
            root,
            "acme",
            "app",
            ["CC-179"],
            titles={"CC-179": "Retry selection"},
            run_id="origin-main-retry",
            apply=True,
        )

    blocked = TaskState(task_path).read()
    assert blocked["state"] == "work_item_ready"
    assert blocked["failure"]["kind"] == "provisioning_failed"
    assert blocked["repository"]["base_branch"] == "origin/main"
    assert not blocked.get("worktree")
    assert not blocked.get("base_selection_corrections")


def test_correct_failed_base_selection_replay_completes_interrupted_portfolio_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, task_path, _ = _historical_origin_main_failure(tmp_path)
    portfolio_path = task_path.parent.parent.parent / "portfolio.json"
    original_atomic_json = delivery._atomic_json

    def interrupt_portfolio_write(path: Path, value: dict[str, object]) -> None:
        if path == portfolio_path:
            raise OSError("simulated interruption before portfolio correction")
        original_atomic_json(path, value)

    monkeypatch.setattr(delivery, "_atomic_json", interrupt_portfolio_write)
    with pytest.raises(OSError, match="simulated interruption"):
        delivery.correct_failed_base_selection(
            task_path,
            corrected_base_branch="main",
            idempotency_key="cc-179:recover-portfolio",
            apply=True,
        )
    interrupted = TaskState(task_path).read()
    correction = interrupted["base_selection_corrections"][0]
    assert interrupted["repository"]["base_branch"] == "main"
    assert json.loads(portfolio_path.read_text(encoding="utf-8"))["repository"]["base_branch"] == "origin/main"

    monkeypatch.setattr(delivery, "_atomic_json", original_atomic_json)
    replayed = delivery.correct_failed_base_selection(
        task_path,
        corrected_base_branch="main",
        idempotency_key="cc-179:recover-portfolio",
        apply=True,
    )

    assert replayed["result"] == "replayed"
    selected = TaskState(task_path).read()
    portfolio = json.loads(portfolio_path.read_text(encoding="utf-8"))
    assert selected["repository"]["base_branch"] == "main"
    assert portfolio["repository"]["base_branch"] == "main"
    assert selected["base_selection_corrections"] == [correction]
    assert portfolio["base_selection_corrections"] == [{**correction, "task_state_ref": str(task_path)}]
    projection = json.loads(Path(selected["autodev_path"]).read_text(encoding="utf-8"))
    assert projection["delivery"]["repository"]["base_branch"] == "main"
    events = [json.loads(line) for line in (task_path.parent / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [event["type"] for event in events].count("development.task.base_selection_corrected") == 1


def test_correct_failed_base_selection_cannot_race_resume_worktree_allocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, task_path, base_sha = _historical_origin_main_failure(tmp_path)
    preflight_started = threading.Event()
    allow_preflight = threading.Event()
    correction_finished = threading.Event()
    result: dict[str, object] = {}
    original_runner = delivery._run_command

    def block_correction_preflight(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[-3:] == ["fetch", "origin", "main"]:
            preflight_started.set()
            assert allow_preflight.wait(timeout=5)
        return original_runner(command, **kwargs)

    def correct() -> None:
        try:
            result["correction"] = delivery.correct_failed_base_selection(
                task_path,
                corrected_base_branch="main",
                idempotency_key="cc-179:race-resume",
                apply=True,
                runner=block_correction_preflight,
            )
        except Exception as exc:  # pragma: no cover - asserted after joining
            result["correction_error"] = exc
        finally:
            correction_finished.set()

    def resume() -> None:
        try:
            result["resume"] = delivery.start_development_run(
                root,
                "acme",
                "app",
                ["CC-179"],
                titles={"CC-179": "Retry selection"},
                run_id="origin-main-retry",
                apply=True,
            )
        except Exception as exc:
            result["resume_error"] = exc

    correction_thread = threading.Thread(target=correct)
    correction_thread.start()
    assert preflight_started.wait(timeout=5), result
    resume_thread = threading.Thread(target=resume)
    resume_thread.start()
    assert not correction_finished.wait(timeout=0.2)
    allow_preflight.set()
    correction_thread.join(timeout=10)
    resume_thread.join(timeout=10)

    assert not correction_thread.is_alive()
    assert not resume_thread.is_alive()
    assert "correction_error" not in result
    assert "resume_error" not in result
    assert result["correction"]["result"] == "corrected"
    assert result["resume"]["state"] == "dispatching"
    state = TaskState(task_path).read()
    assert state["worktree"]["branch"] == "feature/cc-179-retry-selection"
    assert len(state["base_selection_corrections"]) == 1

@pytest.mark.parametrize("effect", ["worktree", "local_branch", "provider_branch"])
def test_correct_failed_base_selection_rejects_every_post_failure_effect(
    tmp_path: Path, effect: str
) -> None:
    _, repo, task_path, _ = _historical_origin_main_failure(tmp_path)
    task = TaskState(task_path)
    branch = "feature/cc-179-retry-selection"
    if effect == "worktree":
        state = task.read()
        state["worktree"] = {"path": "/tmp/not-a-real-worktree", "branch": branch}
        state["updated_at"] = "2026-08-11T00:00:00Z"
        task.path.write_text(json.dumps(state), encoding="utf-8")
    elif effect == "local_branch":
        _git("branch", branch, cwd=repo)
    else:
        _git("branch", branch, cwd=repo)
        _git("push", "origin", branch, cwd=repo)
        _git("branch", "-D", branch, cwd=repo)

    with pytest.raises(DevelopmentDeliveryError, match="forbidden after"):
        delivery.correct_failed_base_selection(
            task_path,
            corrected_base_branch="main",
            idempotency_key=f"cc-179:{effect}",
            apply=True,
        )

    rejected = task.read()
    assert rejected["repository"]["base_branch"] == "origin/main"
    assert not rejected.get("base_selection_corrections")


def test_correct_failed_base_selection_rejects_any_replacement_other_than_main(tmp_path: Path) -> None:
    _, _, task_path, _ = _historical_origin_main_failure(tmp_path)
    with pytest.raises(DevelopmentDeliveryError, match="only permits"):
        delivery.correct_failed_base_selection(
            task_path,
            corrected_base_branch="release/2026-08",
            idempotency_key="cc-179:not-main",
            apply=True,
        )


def test_multi_ticket_run_can_resume_one_explicitly_selected_packet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo)
    worktree_calls: list[str] = []

    def provision(**kwargs):
        ticket = str(kwargs["ticket"])
        worktree_calls.append(ticket)
        slug = ticket.lower()
        return {
            "name": slug,
            "path": f"/tmp/{slug}",
            "branch": f"feature/{slug}",
            "base_sha": base_sha,
        }

    monkeypatch.setattr(delivery, "create_isolated_worktree", provision)
    first = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-ONE", "CC-TWO"],
        run_id="selected-member-resume",
        auto_dev_mode="everything",
        apply=True,
    )
    rows = {row["ticket"]: row for row in first["tasks"]}
    selected_state = Path(rows["CC-ONE"]["state_ref"])
    selected_packet = Path(TaskState(selected_state).read()["work_item"])
    other_state = Path(rows["CC-TWO"]["state_ref"])
    other_before = other_state.read_bytes()

    resumed = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-ONE"],
        run_id="selected-member-resume",
        auto_dev_mode="single_stage",
        requested_stage="document",
        goal="document",
        provision_worktree=False,
        selected_work_item=selected_packet,
        apply=True,
    )

    assert [row["ticket"] for row in resumed["tasks"]] == ["CC-ONE", "CC-TWO"]
    assert Path(next(row for row in resumed["tasks"] if row["ticket"] == "CC-ONE")["state_ref"]) == selected_state
    assert other_state.read_bytes() == other_before
    assert worktree_calls == ["CC-ONE", "CC-TWO"]
    selected_projection = read_auto_dev_state(selected_packet / "autodev.json")
    assert selected_projection["mode"] == "everything"
    assert selected_projection["requested_stage"] == "document"


def test_start_creates_one_linked_auto_dev_projection_and_policy_planes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo)
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": "cc-44",
            "path": "/tmp/cc-44",
            "branch": "feature/cc-44",
            "base_sha": base_sha,
        },
    )
    run = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-44"],
        run_id="auto-dev-projection",
        auto_dev_mode="everything",
        goal="delivery_complete",
        apply=True,
    )
    task = TaskState(Path(run["tasks"][0]["state_ref"])).read()
    projection = read_auto_dev_state(task["autodev_path"])
    assert Path(task["work_item"]) / "autodev.json" == Path(task["autodev_path"])
    assert projection["schema"] == "auto-dev-work-item/v1"
    assert projection["mode"] == "everything"
    assert projection["delivery"]["task_state_ref"] == run["tasks"][0]["state_ref"]
    assert projection["delivery"]["state"] == "worktree_ready"
    assert task["runtime"] == {
        "ownership": "not_managed",
        "provider": "none",
        "identity": "not-managed",
    }
    assert projection["delivery"]["runtime"] == task["runtime"]
    assert {"auto_dev", "environment_access"} <= set(projection["delivery"]["policy_sources"])
    assert projection["stages"]["develop"]["command"] == "/auto-dev-develop"
    assert projection["stages"]["review_self"]["command"] == "/auto-dev-review-self"
    assert projection["stages"]["review_others"]["command"] == "/auto-dev-review-others"
    assert not (Path(task["work_item"]) / "artifacts" / "auto-dev" / "state.json").exists()


def test_rules_engine_context_selection_is_frozen_through_delivery_and_qa_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo)
    _context_kit_policy(root)
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": "cc-rules",
            "path": "/tmp/cc-rules",
            "branch": "feature/cc-rules",
            "base_sha": base_sha,
        },
    )

    run = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-RULES"],
        run_id="rules-context",
        touched_paths=["src/rules_engine.py", "src/rules_engine.py"],
        subjects=["rulebook", "rulebook"],
        auto_dev_mode="everything",
        goal="delivery_complete",
        apply=True,
    )
    task = TaskState(Path(run["tasks"][0]["state_ref"])).read()
    frozen = json.loads(Path(task["policy_receipt"]).read_text(encoding="utf-8"))
    context = frozen["context_selection"]

    assert context["selection"]["touched_paths"] == ["src/rules_engine.py"]
    assert context["selection"]["subjects"] == ["rulebook"]
    assert len(context["selection"]["selected_documents"]) == 2
    assert [document["id"] for document in context["context_documents"]] == [
        "rules-engine-kit"
    ]
    assert len(context["context_documents"][0]["source_refs"]) == 2
    assert task["context_selection"] == context

    projection = read_auto_dev_state(task["autodev_path"])
    assert projection["delivery"]["context_selection"] == context
    refs = auto_dev._auto_dev_packet_config_refs(task)
    assert {row["kind"] for row in refs} >= {"context_policy:rules-engine-kit"}
    context_policy_refs = {
        row["ref"]: row["sha256"]
        for row in refs
        if row["kind"] == "context_policy:rules-engine-kit"
    }
    assert set(context_policy_refs) == set(context["context_documents"][0]["source_refs"])
    assert context_policy_refs == {
        row["source_ref"]: row["sha256"]
        for row in context["selection"]["selected_documents"]
    }

    # A resume with different invocation input does not replace a frozen kit.
    resumed = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-RULES"],
        run_id="rules-context",
        touched_paths=["src/unrelated.py"],
        apply=True,
    )
    assert resumed["context_selection"] == context
    assert resumed["policy_drift"]["behavior"] == "continue_with_run_snapshot"


def test_loaded_frozen_rules_engine_context_requires_available_known_findings() -> None:
    source_ref = "harness/investigation-config/sources/rules-engine.md"
    artifacts = [
        {
            "name": name,
            "ref": f"evidence/kits/applicable-documents/{name}",
            "sha256": character * 64,
        }
        for name, character in zip(
            ["contract.yml", "dictionary.yml", "checks.yml", "coverage.yml", "redundancy.yml"],
            "abcde",
            strict=True,
        )
    ]
    kit = {
        "id": "applicable-documents-v1",
        "rulebook": "ApplicableDocuments",
        "root_ref": "evidence/kits/applicable-documents",
        "artifacts": artifacts,
    }
    kit["content_sha256"] = delivery._json_sha256(kit)
    context = {
        "schema": "rules-engine-frozen-context/v1",
        "status": "loaded",
        "source_refs": [source_ref],
        "selected_rulebook_ids": ["applicabledocuments"],
        "catalog": {"status": "available"},
        "kit": kit,
        "snapshot": {"status": "usable"},
        "known_findings": {
            "status": "available",
            "ref": "evidence/findings.json",
            "sha256": "f" * 64,
            "count": 0,
            "by_severity": {},
            "items": [],
        },
        "reason_codes": [],
    }
    context["content_sha256"] = delivery._json_sha256(context)
    delivery._validate_frozen_rules_engine_context(context, document_refs={source_ref})

    for status in ("not-declared", "unavailable"):
        candidate = json.loads(json.dumps(context))
        candidate["known_findings"] = {"status": status}
        candidate["content_sha256"] = delivery._json_sha256(
            {key: value for key, value in candidate.items() if key != "content_sha256"}
        )
        with pytest.raises(DevelopmentDeliveryError, match="loaded Rules Engine kit"):
            delivery._validate_frozen_rules_engine_context(
                candidate, document_refs={source_ref}
            )


def test_develop_cli_exposes_frozen_context_kit_selection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo)
    _context_kit_policy(root)

    assert main(
        [
            "develop",
            "start",
            "acme",
            "app",
            "CC-CLI",
            "--touched-path",
            "src/rules_engine.py",
            "--subject",
            "rulebook",
            "--root",
            str(root),
            "--json",
        ]
    ) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["context_selection"]["selection"]["touched_paths"] == [
        "src/rules_engine.py"
    ]
    assert plan["context_selection"]["selection"]["subjects"] == ["rulebook"]


def test_reopen_context_requires_explicit_reselect_and_records_lineage() -> None:
    prior = {
        "schema": "development-context-selection/v1",
        "trigger": "ticket-comment",
        "output_type": "planning-evidence",
        "policy_fingerprint": "a" * 64,
        "selection": {
            "touched_paths": ["src/rules_engine.py"],
            "subjects": ["rulebook"],
            "rulebook_ids": [],
            "selected_documents": [],
        },
        "context_documents": [],
    }
    prior["content_sha256"] = delivery._json_sha256(prior)

    carried, mode = delivery._reopen_context_plan(
        prior,
        reselect_context=False,
        touched_paths=[],
        subjects=[],
        rulebook_ids=[],
    )
    assert mode == "carried"
    assert carried == prior
    provenance = delivery._reopen_context_provenance(
        mode=mode,
        prior=prior,
        selected=carried,
    )
    assert provenance["touched_paths"] == ["src/rules_engine.py"]
    assert provenance["subjects"] == ["rulebook"]

    with pytest.raises(DevelopmentDeliveryError, match="--reselect-context"):
        delivery._reopen_context_plan(
            prior,
            reselect_context=False,
            touched_paths=["src/other.py"],
            subjects=[],
            rulebook_ids=[],
        )
    selected, selected_mode = delivery._reopen_context_plan(
        prior,
        reselect_context=True,
        touched_paths=["src/other.py"],
        subjects=[],
        rulebook_ids=[],
    )
    assert selected is None
    assert selected_mode == "reselected"


@pytest.mark.parametrize("action", ["readiness", "qa"])
def test_auto_dev_routes_freeze_rules_engine_context_selection(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo)
    _context_kit_policy(root)
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": f"cc-{action}",
            "path": f"/tmp/cc-{action}",
            "branch": f"feature/cc-{action}",
            "base_sha": base_sha,
        },
    )

    assert main(
        [
            "auto-dev",
            action,
            "acme",
            "app",
            f"CC-{action.upper()}",
            "--touched-path",
            "src/rules_engine.py",
            "--subject",
            "rulebook",
            "--root",
            str(root),
            "--apply",
            "--json",
        ]
    ) == 0
    result = json.loads(capsys.readouterr().out)
    task = TaskState(Path(result["tasks"][0]["state_ref"])).read()
    selection = task["context_selection"]
    assert selection["selection"]["touched_paths"] == ["src/rules_engine.py"]
    assert selection["selection"]["subjects"] == ["rulebook"]
    projection = read_auto_dev_state(task["autodev_path"])
    assert projection["requested_stage"] == action
    assert projection["delivery"]["context_selection"] == selection


def test_start_registers_exact_managed_runtime_from_project_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    project = _project(root, repo)
    profile_path = project / "config/development.yml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["runtime"] = {
        "ownership": "managed",
        "provider": "los_fast_worktree",
        "identity_template": "{domain}-{project}-{worktree}",
        "teardown_command": "make fast-down AUTO_DEV_RUNTIME_ID={runtime_identity}",
        "readback_command": "make fast-status AUTO_DEV_RUNTIME_ID={runtime_identity}",
    }
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": "cc-44-runtime",
            "path": "/tmp/cc-44-runtime",
            "branch": "feature/cc-44-runtime",
            "base_sha": base_sha,
        },
    )

    run = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-44R"],
        run_id="managed-runtime-registration",
        apply=True,
    )
    task = TaskState(Path(run["tasks"][0]["state_ref"])).read()

    assert task["runtime"] == {
        "ownership": "managed",
        "provider": "los_fast_worktree",
        "identity": "acme-app-cc-44-runtime",
        "teardown_command": (
            "make fast-down AUTO_DEV_RUNTIME_ID=acme-app-cc-44-runtime"
        ),
        "readback_command": (
            "make fast-status AUTO_DEV_RUNTIME_ID=acme-app-cc-44-runtime"
        ),
    }


def test_start_rejects_shared_managed_runtime_identity(
    tmp_path: Path,
) -> None:
    repo, _ = _repository(tmp_path)
    root = tmp_path / "os"
    project = _project(root, repo)
    profile_path = project / "config/development.yml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["runtime"] = {
        "ownership": "managed",
        "provider": "los_fast_worktree",
        "identity_template": "shared-dev",
        "teardown_command": "make fast-down",
        "readback_command": "make fast-status",
    }
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")

    with pytest.raises(
        DevelopmentDeliveryError,
        match=r"must include \{domain\}, \{project\}, and \{worktree\}",
    ):
        delivery.start_development_run(
            root,
            "acme",
            "app",
            ["CC-SHARED-RUNTIME"],
            run_id="shared-runtime-rejected",
            apply=False,
        )


def test_health_refuses_a_delivery_task_without_runtime_registration() -> None:
    with pytest.raises(AutoDevStateError, match="explicit runtime registration"):
        auto_dev._health_runtime_registration({"state": "delivery_complete"})


def test_auto_dev_stage_receipt_is_typed_idempotent_and_does_not_transition_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo)
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": "cc-45",
            "path": "/tmp/cc-45",
            "branch": "feature/cc-45",
            "base_sha": base_sha,
        },
    )
    run = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-45"],
        run_id="auto-dev-record",
        auto_dev_mode="single_stage",
        requested_stage="document",
        goal="document",
        apply=True,
    )
    task_path = Path(run["tasks"][0]["state_ref"])
    task_before = TaskState(task_path).read()
    proof = _packet_proof(Path(task_before["work_item"]), "document")
    evidence = tmp_path / "document-evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "schema": AUTO_DEV_STAGE_EVIDENCE_SCHEMA,
                "stage": "document",
                "status": "completed",
                "summary": "Updated operator documentation and verified the rendered target.",
                "evidence": {"receipt_refs": [str(proof)]},
                "verified_at": "2026-07-20T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    first = record_auto_dev_stage(
        task_before["autodev_path"],
        stage="document",
        evidence_file=evidence,
        idempotency_key="cc-45:document",
    )
    replay = record_auto_dev_stage(
        task_before["autodev_path"],
        stage="document",
        evidence_file=evidence,
        idempotency_key="cc-45:document",
    )
    assert first["receipt"] == replay["receipt"]
    assert replay["state"]["stages"]["document"]["status"] == "completed"
    assert TaskState(task_path).read()["state"] == task_before["state"]


def test_auto_dev_plain_english_cli_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, _ = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo)
    assert main(["auto-dev", "everything", "acme", "app", "CC-46", "--root", str(root), "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["auto_dev"]["goal"] == "delivery_complete"
    assert output["auto_dev"]["mode"] == "everything"
    assert output["auto_dev"]["requested_stage"] is None
    assert set(output["auto_dev"]["stage_order"]) == set(delivery.AUTO_DEV_STAGE_ORDER)
    assert "execution" not in output
    assert not (root / "domains" / "acme" / "02-projects" / "app" / "state" / "development-runs").exists()


@pytest.mark.parametrize("managed_runtime", (False, True), ids=("unmanaged", "managed"))
def test_everything_apply_records_pending_executor_handoff(
    managed_runtime: bool,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo, managed_runtime=managed_runtime)
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": "cc-175",
            "path": "/tmp/cc-175",
            "branch": "feature/cc-175",
            "base_sha": base_sha,
        },
    )

    assert main(
        [
            "auto-dev",
            "everything",
            "acme",
            "app",
            "CC-175",
            "--root",
            str(root),
            "--apply",
            "--json",
        ]
    ) == 1
    output = json.loads(capsys.readouterr().out)

    assert output["state"] == "pending"
    assert output["execution"]["schema"] == "auto-dev-everything-execution-status/v1"
    assert output["execution"]["status"] == "pending"
    assert output["execution"]["executed"] is False
    assert output["execution"]["next_actions"] == [
        {
            "ticket": "CC-175",
            "stage": "groom",
            "command": "/auto-dev-grooming",
            "stage_receipt_recorded": False,
        }
    ]
    assert output["execution"]["handoffs"] == [
        {
            "ticket": "CC-175",
            "outcome": "executor_unavailable",
            "receipt": output["tasks"][0]["handoff"]["receipt"],
            "attempt": 1,
            "recoverable": True,
        }
    ]
    task = TaskState(Path(output["tasks"][0]["state_ref"])).read()
    assert task["state"] == "worktree_ready"
    assert task["runtime"]["ownership"] == ("managed" if managed_runtime else "not_managed")
    assert task["failure"]["kind"] == "executor_unavailable"
    assert task["failure"]["recoverable"] is True
    handoff = json.loads(Path(task["failure"]["receipt"]).read_text(encoding="utf-8"))
    assert handoff["schema"] == "development-executor-handoff/v1"
    assert handoff["status"] == "pending"
    assert handoff["worktree"] == task["worktree"]
    assert handoff["policy"]["fingerprint"] == task["policy_fingerprint"]
    assert read_auto_dev_state(task["autodev_path"])["stages"]["groom"]["status"] == "not_started"
    from genomes_agentic_os.program_run_packets import read_program_run_packet

    run_packet = read_auto_dev_state(task["autodev_path"])["run_packet"]
    run_summary = read_program_run_packet(root, run_packet["packet_id"])
    assert run_summary["state"] == "started"
    assert run_summary["running_workflows"] == []
    events = [
        json.loads(line)
        for line in (Path(output["tasks"][0]["state_ref"]).parent / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert {event["type"] for event in events} >= {
        "development.task.executor_handoff_pending",
        "development.task.failed",
    }

    # Every repeated unaccepted handoff on the exact packet must retain the
    # prior receipt and record the next bounded failure, never a
    # success-looking dispatch result.
    assert main(
        [
            "auto-dev",
            "groom",
            "--state",
            task["autodev_path"],
            "--root",
            str(root),
            "--apply",
            "--json",
        ]
    ) == 1
    groom_resume = json.loads(capsys.readouterr().out)
    assert groom_resume["state"] == "pending"
    assert groom_resume["tasks"][0]["handoff"]["attempt"] == 2
    assert groom_resume["tasks"][0]["handoff"]["receipt"] != task["failure"]["receipt"]
    first_handoff = json.loads(Path(task["failure"]["receipt"]).read_text(encoding="utf-8"))
    assert first_handoff["attempt"] == 1

    # The configured final refusal becomes terminal without an explicit
    # recovery; all previous handoff evidence remains immutable.
    assert main(
        [
            "auto-dev",
            "readiness",
            "--state",
            task["autodev_path"],
            "--root",
            str(root),
            "--apply",
            "--json",
        ]
    ) == 1
    resumed = json.loads(capsys.readouterr().out)
    assert resumed["state"] == "blocked"
    resumed_task = TaskState(Path(resumed["tasks"][0]["state_ref"])).read()
    assert resumed_task["state"] == "blocked"
    assert resumed_task["runtime"]["ownership"] == ("managed" if managed_runtime else "not_managed")
    assert resumed_task["failure"]["kind"] == "executor_unavailable"
    assert resumed_task["failure"]["recoverable"] is False
    assert resumed_task["attempts"]["executor_unavailable"] == 3
    handoff_dir = Path(resumed_task["failure"]["receipt"]).parent
    assert [
        json.loads((handoff_dir / f"executor-unavailable-attempt-{attempt:02d}.json").read_text(encoding="utf-8"))["attempt"]
        for attempt in (1, 2, 3)
    ] == [1, 2, 3]

    # Once an operator has explicitly recovered the task, a named stage must
    # use its current state rather than retain the old pending handoff that is
    # still present in the historical portfolio row.
    assert main(
        [
            "develop",
            "recover",
            output["tasks"][0]["state_ref"],
            "--receipt",
            "executor accepted the recovered task",
            "--idempotency-key",
            "cc-175:recover-after-handoff",
            "--json",
        ]
    ) == 0
    capsys.readouterr()

    assert main(
        [
            "auto-dev",
            "develop",
            "--state",
            task["autodev_path"],
            "--root",
            str(root),
            "--apply",
            "--json",
        ]
    ) == 0
    recovered_resume = json.loads(capsys.readouterr().out)
    assert recovered_resume["state"] == "dispatching"
    assert "handoff" not in recovered_resume["tasks"][0]
    recovered_task = TaskState(Path(recovered_resume["tasks"][0]["state_ref"])).read()
    assert recovered_task["state"] == "worktree_ready"
    assert recovered_task["failure"] is None


def test_everything_apply_marks_four_unmanaged_tasks_pending_without_stage_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo)
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": kwargs["ticket"].lower(),
            "path": f"/tmp/{kwargs['ticket'].lower()}",
            "branch": f"feature/{kwargs['ticket'].lower()}",
            "base_sha": base_sha,
        },
    )

    tickets = ["AGE-166", "AGE-168", "AGE-171", "AGE-172"]
    assert main(
        [
            "auto-dev",
            "everything",
            "acme",
            "app",
            *tickets,
            "--root",
            str(root),
            "--apply",
            "--json",
        ]
    ) == 1
    output = json.loads(capsys.readouterr().out)

    assert output["state"] == "pending"
    assert {row["ticket"] for row in output["tasks"]} == set(tickets)
    assert {row["ticket"] for row in output["execution"]["handoffs"]} == set(tickets)
    for row in output["tasks"]:
        task = TaskState(Path(row["state_ref"])).read()
        assert task["state"] == "worktree_ready"
        assert task["attempts"]["executor_unavailable"] == 1
        assert task["failure"]["kind"] == "executor_unavailable"
        handoff = json.loads(Path(task["failure"]["receipt"]).read_text(encoding="utf-8"))
        assert handoff["ticket"] == row["ticket"]
        assert handoff["worktree"] == task["worktree"]
        assert handoff["policy"]["receipt"] == task["policy_receipt"]
        projection = read_auto_dev_state(task["autodev_path"])
        assert projection["mode"] == "everything"
        assert projection["stages"]["groom"]["status"] == "not_started"


def test_everything_executor_handoff_blocks_after_bounded_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo)
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": kwargs["ticket"].lower(),
            "path": f"/tmp/{kwargs['ticket'].lower()}",
            "branch": f"feature/{kwargs['ticket'].lower()}",
            "base_sha": base_sha,
        },
    )

    assert main(
        [
            "auto-dev",
            "everything",
            "acme",
            "app",
            "CC-EXHAUST",
            "--root",
            str(root),
            "--apply",
            "--json",
        ]
    ) == 1
    output = json.loads(capsys.readouterr().out)
    state_ref = output["tasks"][0]["state_ref"]
    autodev_path = TaskState(Path(state_ref)).read()["autodev_path"]

    # The profile allows three attempts.  Explicit recovery is required before
    # each subsequent exact-packet handoff, so the third refusal must be
    # terminal rather than another pending result.
    for attempt in (2, 3):
        assert main(
            [
                "develop",
                "recover",
                state_ref,
                "--receipt",
                f"operator-recovery-{attempt}",
                "--idempotency-key",
                f"cc-exhaust:recover:{attempt}",
                "--json",
            ]
        ) == 0
        capsys.readouterr()
        assert main(
            [
                "auto-dev",
                "everything",
                "--state",
                autodev_path,
                "--root",
                str(root),
                "--apply",
                "--json",
            ]
        ) == 1
        output = json.loads(capsys.readouterr().out)

    assert output["state"] == "blocked"
    assert output["execution"]["status"] == "blocked"
    assert output["execution"]["executed"] is False
    assert output["execution"]["handoffs"] == [
        {
            "ticket": "CC-EXHAUST",
            "outcome": "executor_unavailable",
            "receipt": output["tasks"][0]["handoff"]["receipt"],
            "attempt": 3,
            "recoverable": False,
        }
    ]
    task = TaskState(Path(state_ref)).read()
    assert task["state"] == "blocked"
    assert task["failure"]["kind"] == "executor_unavailable"
    assert task["failure"]["recoverable"] is False
    handoff = json.loads(Path(task["failure"]["receipt"]).read_text(encoding="utf-8"))
    assert handoff["status"] == "blocked"
    assert handoff["attempt"] == 3
    assert handoff["recoverable"] is False
    portfolio = json.loads((Path(state_ref).parents[2] / "portfolio.json").read_text(encoding="utf-8"))
    assert portfolio["state"] == "blocked"


def test_everything_projection_creates_a_linked_program_run_packet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from genomes_agentic_os.program_run_packets import read_program_run_packet

    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo)
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": "cc-412",
            "path": "/tmp/cc-412",
            "branch": "feature/cc-412",
            "base_sha": base_sha,
        },
    )

    run = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-412"],
        run_id="program-packet",
        auto_dev_mode="everything",
        goal="delivery_complete",
        apply=True,
    )

    task = TaskState(Path(run["tasks"][0]["state_ref"])).read()
    projection = read_auto_dev_state(task["autodev_path"])
    link = projection["run_packet"]
    summary = read_program_run_packet(root, link["packet_id"])
    assert link["program_ref"] == "00-program.json"
    assert summary["packet"]["program_id"] == "auto_dev"
    assert summary["state"] == "started"
    assert summary["running_workflows"] == []
    assert any(item["kind"] == "effective_policy" for item in summary["packet"]["config_refs"])


def test_project_configures_default_and_everything_workflow_boundaries(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = _repository(tmp_path)
    root = tmp_path / "os"
    project = _project(root, repo)
    profile_path = project / "config" / "development.yml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["auto_dev"] = {
        "default": {"start_stage": "readiness", "completion_stage": "pr_create"},
        "everything": {"start_stage": "groom", "completion_stage": "merge"},
        "stages": {
            "document": {
                "applicability": "disabled",
                "reason": "Project documentation is not required today.",
            },
            "qa": {
                "applicability": "contextual",
                "child_delivery": {
                    "repository": "github:Lenders-Cooperative/los-qa-automation",
                    "tracker": "jira_subtask",
                },
            },
        },
    }
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")

    assert main(
        ["auto-dev", "default", "acme", "app", "CC-PR", "--root", str(root), "--json"]
    ) == 0
    default = json.loads(capsys.readouterr().out)["auto_dev"]
    assert default["mode"] == "default"
    assert default["start_stage"] == "readiness"
    assert default["completion_stage"] == "pr_create"
    assert default["goal"] == "pr_create"
    assert default["stage_policies"]["document"]["applicability"] == "disabled"

    assert main(
        ["auto-dev", "everything", "acme", "app", "CC-ALL", "--root", str(root), "--json"]
    ) == 0
    everything = json.loads(capsys.readouterr().out)["auto_dev"]
    assert everything["mode"] == "everything"
    assert everything["completion_stage"] == "merge"
    assert everything["goal"] == "merge"
    assert everything["stage_policies"]["qa"]["child_delivery"]["tracker"] == "jira_subtask"

    assert main(
        ["auto-dev", "propagate", "acme", "app", "CC-46", "--root", str(root), "--json"]
    ) == 0
    propagated = json.loads(capsys.readouterr().out)
    assert propagated["auto_dev"]["requested_stage"] == "pr_create"

    assert main(
        ["auto-dev", "health", "acme", "app", "CC-46", "--root", str(root), "--apply"]
    ) == 2
    assert "requires --state" in capsys.readouterr().err


def test_default_auto_dev_cannot_stop_before_pr_create(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _ = _repository(tmp_path)
    root = tmp_path / "os"
    project = _project(root, repo)
    profile_path = project / "config" / "development.yml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["auto_dev"] = {
        "default": {"start_stage": "readiness", "completion_stage": "develop"}
    }
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")

    assert main(
        ["auto-dev", "default", "acme", "app", "CC-NO-PR", "--root", str(root), "--json"]
    ) == 2
    assert "default Auto-Dev workflow must include PR Create" in capsys.readouterr().err


def test_same_mode_resume_keeps_frozen_workflow_boundary_after_profile_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    project = _project(root, repo)
    profile_path = project / "config" / "development.yml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["auto_dev"] = {
        "everything": {
            "start_stage": "readiness",
            "completion_stage": "health",
        }
    }
    profile_path.write_text(
        yaml.safe_dump(profile, sort_keys=False), encoding="utf-8"
    )
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": "frozen-boundary",
            "path": "/tmp/frozen-boundary",
            "branch": "feature/frozen-boundary",
            "base_sha": base_sha,
        },
    )
    run = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-FROZEN-BOUNDARY"],
        run_id="frozen-boundary",
        auto_dev_mode="everything",
        apply=True,
    )
    task = TaskState(Path(run["tasks"][0]["state_ref"]))
    profile["auto_dev"]["everything"]["start_stage"] = "groom"
    profile_path.write_text(
        yaml.safe_dump(profile, sort_keys=False), encoding="utf-8"
    )

    delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-FROZEN-BOUNDARY"],
        run_id="frozen-boundary",
        auto_dev_mode="everything",
        selected_work_item=Path(task.read()["work_item"]),
        apply=True,
    )
    projection = read_auto_dev_state(task.read()["autodev_path"])
    portfolio = json.loads(
        (task.path.parents[2] / "portfolio.json").read_text(encoding="utf-8")
    )
    assert projection["start_stage"] == "readiness"
    assert projection["completion_stage"] == "health"
    assert portfolio["auto_dev"]["start_stage"] == "readiness"
    assert portfolio["auto_dev"]["completion_stage"] == "health"


def test_resume_rejects_portfolio_only_auto_dev_boundary_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo)
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": "boundary-drift",
            "path": "/tmp/boundary-drift",
            "branch": "feature/boundary-drift",
            "base_sha": base_sha,
        },
    )
    run = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-BOUNDARY-DRIFT"],
        run_id="boundary-drift",
        auto_dev_mode="everything",
        apply=True,
    )
    task = TaskState(Path(run["tasks"][0]["state_ref"]))
    portfolio_path = task.path.parents[2] / "portfolio.json"
    portfolio = json.loads(portfolio_path.read_text(encoding="utf-8"))
    portfolio["auto_dev"]["start_stage"] = "merge"
    portfolio_path.write_text(
        json.dumps(portfolio, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        DevelopmentDeliveryError,
        match="workflow boundary differs between portfolio, task, and projection",
    ):
        delivery.start_development_run(
            root,
            "acme",
            "app",
            ["CC-BOUNDARY-DRIFT"],
            run_id="boundary-drift",
            auto_dev_mode="everything",
            selected_work_item=Path(task.read()["work_item"]),
            apply=True,
        )


def test_retry_rejects_portfolio_boundary_drift_before_work_item_provisioning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _ = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo)

    def unavailable_work_item(*args, **kwargs):
        raise OSError("work-item provider unavailable")

    monkeypatch.setattr(
        delivery,
        "create_project_work_item",
        unavailable_work_item,
    )
    run = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-EARLY-BOUNDARY"],
        run_id="early-boundary",
        auto_dev_mode="everything",
        apply=True,
    )
    task = TaskState(Path(run["tasks"][0]["state_ref"]))
    task_value = task.read()
    assert not task_value.get("work_item")
    assert task_value["auto_dev_start_stage"] == "groom"
    assert task_value["auto_dev_completion_stage"] == "health"

    portfolio_path = task.path.parents[2] / "portfolio.json"
    portfolio = json.loads(portfolio_path.read_text(encoding="utf-8"))
    portfolio["auto_dev"]["start_stage"] = "merge"
    portfolio_path.write_text(
        json.dumps(portfolio, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        DevelopmentDeliveryError,
        match="workflow boundary differs between portfolio, task, and projection",
    ):
        delivery.start_development_run(
            root,
            "acme",
            "app",
            ["CC-EARLY-BOUNDARY"],
            run_id="early-boundary",
            auto_dev_mode="everything",
            apply=True,
        )


def test_pr_create_requires_configured_jira_qa_assessment_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    project = _project(root, repo)
    profile_path = project / "config" / "development.yml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["auto_dev"] = {
        "everything": {"start_stage": "groom", "completion_stage": "merge"},
        "stages": {
            "qa": {
                "applicability": "contextual",
                "assessment": {"tracker": "jira", "always_create": True},
            }
        },
    }
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": "cc-qa-assessment",
            "path": "/tmp/cc-qa-assessment",
            "branch": "feature/cc-qa-assessment",
            "base_sha": base_sha,
        },
    )
    run = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-QA"],
        run_id="qa-assessment",
        auto_dev_mode="everything",
        apply=True,
    )
    task = TaskState(Path(run["tasks"][0]["state_ref"]))
    _advance_auto_dev_task_to_ready(
        task,
        subject_revision=base_sha,
        pull_request="github:acme/app#88",
    )
    for stage_name in ("groom", "detective", "create_artifacts", "document"):
        _record_standalone_stage(task, stage_name)
    work_item = Path(task.read()["work_item"])

    with pytest.raises(DevelopmentDeliveryError, match="QA Automation Assessment"):
        run_development_stage(
            task.path,
            stage="release_propagation",
            receipts={
                "release_propagation": _stage_receipt(
                    work_item / "artifacts" / "missing-assessment",
                    "release_propagation",
                )
            },
            idempotency_prefix="cc-qa:missing-assessment",
        )

    receipt = _stage_receipt(
        work_item / "artifacts" / "with-assessment",
        "release_propagation",
        evidence={
            "qa_automation_assessment": {
                "schema": "auto-dev-qa-assessment/v1",
                "tracker": "jira",
                "issue_key": "CC-QA-1",
                "parent_key": "CC-QA",
                "readback_verified": True,
            }
        },
    )
    result = run_development_stage(
        task.path,
        stage="release_propagation",
        receipts={"release_propagation": receipt},
        idempotency_prefix="cc-qa:with-assessment",
    )
    assert result["stage"] == "release_propagation"


def test_groom_initializes_state_without_worktree_or_false_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _ = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo)

    def unexpected_worktree(**kwargs):
        raise AssertionError(f"groom must not create a worktree: {kwargs}")

    monkeypatch.setattr(delivery, "create_isolated_worktree", unexpected_worktree)
    run = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-47"],
        run_id="groom-without-worktree",
        requested_stage="groom",
        goal="groom",
        provision_worktree=False,
        apply=True,
    )
    task = TaskState(Path(run["tasks"][0]["state_ref"])).read()
    projection = read_auto_dev_state(task["autodev_path"])
    assert task["state"] == "work_item_ready"
    assert task.get("worktree") is None
    assert run["state"] == "work_item_ready"
    assert projection["current_stage"] == "groom"
    assert projection["stages"]["groom"]["status"] == "not_started"
    assert projection["stages"]["qa"]["status"] == "out_of_scope"


def test_progressed_run_resumes_and_single_stage_retargets_same_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo)
    calls = 0

    def create_once(**kwargs):
        nonlocal calls
        calls += 1
        return {
            "name": "cc-48",
            "path": "/tmp/cc-48",
            "branch": "feature/cc-48",
            "base_sha": base_sha,
        }

    monkeypatch.setattr(delivery, "create_isolated_worktree", create_once)
    first = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-48"],
        run_id="resume-progressed",
        auto_dev_mode="everything",
        goal="delivery_complete",
        apply=True,
    )
    task_path = Path(first["tasks"][0]["state_ref"])
    run_development_stage(
        task_path,
        stage="readiness",
        receipts={"planned": _stage_receipt(tmp_path, "planned")},
        idempotency_prefix="cc-48:readiness",
    )
    before_resume = read_auto_dev_state(TaskState(task_path).read()["autodev_path"])
    assert before_resume["mode"] == "everything"
    assert TaskState(task_path).read()["auto_dev_mode"] == "everything"
    resumed = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-48"],
        run_id="resume-progressed",
        requested_stage="document",
        goal="document",
        provision_worktree=False,
        apply=True,
    )
    assert calls == 1
    assert TaskState(task_path).read()["state"] == "planned"
    assert resumed["state"] == "planned"
    projection = read_auto_dev_state(TaskState(task_path).read()["autodev_path"])
    assert projection["mode"] == "everything"
    assert TaskState(task_path).read()["auto_dev_mode"] == "everything"
    assert projection["requested_stage"] == "document"
    assert projection["current_stage"] == "document"
    assert projection["start_stage"] == before_resume["start_stage"]
    assert projection["completion_stage"] == before_resume["completion_stage"]
    assert projection["stage_policies"] == before_resume["stage_policies"]
    assert projection["stages"]["readiness"]["status"] == "completed"
    assert (
        projection["stages"]["readiness"]["receipt_refs"]
        == before_resume["stages"]["readiness"]["receipt_refs"]
    )

    assert main(
        [
            "auto-dev",
            "groom",
            "--state",
            TaskState(task_path).read()["autodev_path"],
            "--root",
            str(root),
            "--apply",
            "--json",
        ]
    ) == 0
    capsys.readouterr()
    retargeted = read_auto_dev_state(TaskState(task_path).read()["autodev_path"])
    assert retargeted["mode"] == "everything"
    assert TaskState(task_path).read()["auto_dev_mode"] == "everything"
    assert retargeted["requested_stage"] == "groom"
    assert retargeted["current_stage"] == "groom"
    assert retargeted["start_stage"] == before_resume["start_stage"]
    assert retargeted["completion_stage"] == before_resume["completion_stage"]
    assert retargeted["stages"]["readiness"]["status"] == "completed"
    assert (
        retargeted["stages"]["readiness"]["receipt_refs"]
        == before_resume["stages"]["readiness"]["receipt_refs"]
    )
    assert calls == 1


@pytest.mark.parametrize(
    ("action", "target"),
    [
        ("pr-create", "pr_create"),
        ("merge", "merge"),
        ("deploy", "deploy"),
        ("closeout", "closeout"),
    ],
)
def test_single_stage_external_action_preserves_window_and_predecessor_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    action: str,
    target: str,
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo)
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": "cc-stage-gate",
            "path": "/tmp/cc-stage-gate",
            "branch": "feature/cc-stage-gate",
            "base_sha": base_sha,
        },
    )
    run = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-STAGE-GATE"],
        run_id=f"single-stage-gate-{target}",
        auto_dev_mode="everything",
        apply=True,
    )
    task = TaskState(Path(run["tasks"][0]["state_ref"]))
    _record_standalone_stage(task, "groom")
    state_ref = task.read()["autodev_path"]
    before = read_auto_dev_state(state_ref)

    assert main(
        [
            "auto-dev",
            action,
            "--state",
            state_ref,
            "--root",
            str(root),
            "--apply",
            "--json",
        ]
    ) == 0
    capsys.readouterr()
    after = read_auto_dev_state(state_ref)
    assert after["start_stage"] == before["start_stage"]
    assert after["completion_stage"] == before["completion_stage"]
    assert after["stages"]["groom"]["status"] == "completed"
    assert (
        after["stages"]["groom"]["receipt_refs"]
        == before["stages"]["groom"]["receipt_refs"]
    )
    with pytest.raises(AutoDevStateError, match="detective"):
        auto_dev.require_auto_dev_predecessors(state_ref, target)


def test_legacy_target_only_single_stage_expands_before_external_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo)
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": "legacy-target-only",
            "path": "/tmp/legacy-target-only",
            "branch": "feature/legacy-target-only",
            "base_sha": base_sha,
        },
    )
    run = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-LEGACY-TARGET"],
        run_id="legacy-target-only",
        auto_dev_mode="everything",
        apply=True,
    )
    task = TaskState(Path(run["tasks"][0]["state_ref"]))
    _record_standalone_stage(task, "groom")
    portfolio_path = task.path.parents[2] / "portfolio.json"
    portfolio = json.loads(portfolio_path.read_text(encoding="utf-8"))
    portfolio["auto_dev"].update(
        {
            "mode": "single_stage",
            "requested_stage": "document",
            "start_stage": "document",
            "completion_stage": "document",
        }
    )
    portfolio_path.write_text(
        json.dumps(portfolio, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    task_value = task.read()
    task_value.update(
        {
            "auto_dev_mode": "single_stage",
            "requested_stage": "document",
            "auto_dev_start_stage": "document",
            "auto_dev_completion_stage": "document",
        }
    )
    task.path.write_text(
        json.dumps(task_value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    sync_delivery_projection(task.path)

    assert main(
        [
            "auto-dev",
            "merge",
            "--state",
            task.read()["autodev_path"],
            "--root",
            str(root),
            "--apply",
            "--json",
        ]
    ) == 0
    capsys.readouterr()
    repaired = read_auto_dev_state(task.read()["autodev_path"])
    assert repaired["start_stage"] == list(AUTO_DEV_STAGE_ORDER)[0]
    assert repaired["completion_stage"] == "merge"
    with pytest.raises(AutoDevStateError, match="detective"):
        auto_dev.require_auto_dev_predecessors(
            task.read()["autodev_path"], "merge"
        )


def test_delivery_projection_failure_is_non_canonical_and_transition_still_succeeds(
    tmp_path: Path,
) -> None:
    task = _state(tmp_path)
    work_item = tmp_path / "work-item"
    work_item.mkdir()
    projection = work_item / "autodev.json"
    projection.write_text("{broken", encoding="utf-8")
    state = task.read()
    state.update(
        {
            "work_item": str(work_item),
            "autodev_path": str(projection),
            "domain": "acme",
            "project": "app",
        }
    )
    task.path.write_text(json.dumps(state), encoding="utf-8")

    transitioned = task.transition("claimed", receipt="tracker:CC-1", idempotency_key="claim")
    assert transitioned["state"] == "claimed"
    assert task.read()["state"] == "claimed"
    events = [json.loads(line) for line in task.ledger.read_text(encoding="utf-8").splitlines()]
    assert any(event["type"] == "development.autodev_projection.sync_failed" for event in events)


@pytest.mark.parametrize("managed_stage", ["merge", "deploy", "closeout"])
def test_delivery_managed_stages_cannot_be_completed_by_generic_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, managed_stage: str
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo)
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": "cc-49",
            "path": "/tmp/cc-49",
            "branch": "feature/cc-49",
            "base_sha": base_sha,
        },
    )
    run = delivery.start_development_run(
        root, "acme", "app", ["CC-49"], run_id="managed-stage", auto_dev_mode="everything", apply=True
    )
    task = TaskState(Path(run["tasks"][0]["state_ref"])).read()
    evidence = tmp_path / f"{managed_stage}.json"
    evidence.write_text(
        json.dumps(
            {
                "schema": AUTO_DEV_STAGE_EVIDENCE_SCHEMA,
                "stage": managed_stage,
                "status": "completed",
                "summary": "claimed merge",
                "subject_revision": base_sha,
                "evidence": {"receipt_refs": ["anything"]},
                "verified_at": "2026-07-20T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(AutoDevStateError, match="owned by Development Delivery"):
        record_auto_dev_stage(
            task["autodev_path"],
            stage=managed_stage,
            evidence_file=evidence,
            idempotency_key=f"unsafe:{managed_stage}",
        )
    projection = read_auto_dev_state(task["autodev_path"])
    assert projection["status"] != "completed"
    assert projection["delivery"]["state"] == "worktree_ready"


def test_groom_and_qa_require_their_own_receipts_and_propagation_is_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo)
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": "cc-50",
            "path": "/tmp/cc-50",
            "branch": "feature/cc-50",
            "base_sha": base_sha,
        },
    )
    run = delivery.start_development_run(
        root, "acme", "app", ["CC-50"], run_id="stage-separation", auto_dev_mode="everything", apply=True
    )
    task_path = Path(run["tasks"][0]["state_ref"])
    task = TaskState(task_path)
    _advance_auto_dev_task_to_ready(
        task,
        subject_revision=base_sha,
        pull_request="github:acme/app#50",
    )
    stages = task_path.parent / "stages"
    stages.mkdir(exist_ok=True)
    (stages / "release-propagation.json").write_text(
        json.dumps({"recorded_at": "2026-07-20T12:00:00Z"}), encoding="utf-8"
    )
    projection = sync_delivery_projection(task_path)
    assert projection is not None
    assert projection["stages"]["groom"]["status"] == "not_started"
    assert projection["stages"]["qa"]["status"] == "not_started"
    assert projection["stages"]["review_self"]["status"] == "completed"
    assert projection["stages"]["pr_create"]["status"] == "not_started"
    (stages / "release-propagation.json").unlink()
    for stage_name in ("groom", "detective", "create_artifacts", "document"):
        _record_standalone_stage(task, stage_name)
    _record_standalone_stage(
        task,
        "review_others",
        revision=base_sha,
        status="not_required",
    )
    _record_standalone_stage(task, "qa", revision=base_sha)
    run_development_stage(
        task_path,
        stage="release_propagation",
        receipts={
            "release_propagation": _stage_receipt(tmp_path, "release_propagation")
        },
        idempotency_prefix="cc-50:release-propagation",
    )
    projection = sync_delivery_projection(task_path)
    assert projection is not None
    assert projection["stages"]["pr_create"]["status"] == "completed"
    assert projection["stages"]["release"]["status"] == "not_started"


def test_revision_sensitive_stage_receipts_can_supersede_stale_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo)
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": "cc-51",
            "path": "/tmp/cc-51",
            "branch": "feature/cc-51",
            "base_sha": base_sha,
        },
    )
    run = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-51"],
        run_id="revision-refresh",
        requested_stage="qa",
        goal="qa",
        apply=True,
    )
    task = TaskState(Path(run["tasks"][0]["state_ref"])).read()
    evidence_paths: dict[str, Path] = {}
    for suffix in ("a", "b"):
        evidence = tmp_path / f"qa-{suffix}.json"
        evidence_paths[suffix] = evidence
        proof = _packet_proof(Path(task["work_item"]), "qa", label=suffix)
        evidence.write_text(
            json.dumps(
                {
                    "schema": AUTO_DEV_STAGE_EVIDENCE_SCHEMA,
                    "stage": "qa",
                    "status": "completed",
                    "summary": f"QA passed for revision {suffix}",
                    "subject_revision": f"revision-{suffix}",
                    "evidence": {"receipt_refs": [str(proof)]},
                    "verified_at": "2026-07-20T12:00:00Z",
                }
            ),
            encoding="utf-8",
        )
        record_auto_dev_stage(
            task["autodev_path"],
            stage="qa",
            evidence_file=evidence,
            idempotency_key=f"cc-51:qa:{suffix}",
        )
    stage_dir = Path(task["work_item"]) / "artifacts/auto-dev-orchestration/stages/qa"
    versions = [path for path in stage_dir.glob("*.json") if path.name != "latest.json"]
    assert len(versions) == 2
    latest = json.loads((stage_dir / "latest.json").read_text(encoding="utf-8"))
    projection = read_auto_dev_state(task["autodev_path"])
    assert latest["subject_revision"] == "revision-b"
    assert latest.get("supersedes")
    assert projection["subject_revision"] == "revision-b"
    assert projection["stages"]["qa"]["status"] == "completed"
    record_auto_dev_stage(
        task["autodev_path"],
        stage="qa",
        evidence_file=evidence_paths["a"],
        idempotency_key="cc-51:qa:a",
    )
    replayed_latest = json.loads((stage_dir / "latest.json").read_text(encoding="utf-8"))
    replayed_projection = read_auto_dev_state(task["autodev_path"])
    assert replayed_latest["subject_revision"] == "revision-b"
    assert replayed_projection["subject_revision"] == "revision-b"


def test_release_propagation_appends_exact_head_supersession_without_rewriting_prior_wrapper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rewritten PR head must replace the current binding, not history."""

    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo, repository_id="git:github.com/acme/app")
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": "cc-52",
            "path": "/tmp/cc-52",
            "branch": "feature/cc-52",
            "base_sha": base_sha,
        },
    )
    run = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-52"],
        run_id="release-propagation-head-refresh",
        auto_dev_mode="everything",
        apply=True,
    )
    task = TaskState(Path(run["tasks"][0]["state_ref"]))
    _advance_auto_dev_task_to_ready(
        task,
        subject_revision=base_sha,
        pull_request="github:acme/app#52",
    )
    for stage_name in ("groom", "detective", "create_artifacts", "document"):
        _record_standalone_stage(task, stage_name)

    work_item = Path(task.read()["work_item"])
    task_value = task.read()
    task_value["state"] = "local_validation"
    task.path.write_text(json.dumps(task_value), encoding="utf-8")

    def family_receipt(
        name: str,
        source_head_sha: str,
        *,
        supersedes_source_head_sha: str | None = None,
        legacy_nested_identity: bool = False,
    ) -> Path:
        evidence: dict[str, object] = {
            "ticket": "CC-52",
            "repository": "git:github.com/acme/app",
            "base_branch": "main",
            "provider": "github",
            "pull_request": "github:acme/app#52",
            "source_branch": "feature/cc-52",
            "source_head_sha": source_head_sha,
            "readback_verified": True,
            "provider_observed": {"head_sha": source_head_sha},
        }
        if legacy_nested_identity:
            evidence = {
                "ticket": "CC-52",
                "source": {
                    "repository": "github:acme/app",
                    "base_branch": "main",
                    "source_branch": "feature/cc-52",
                    "source_head_sha": source_head_sha,
                },
                "provider_readback": {"head_sha": source_head_sha},
                "targets": [
                    {
                        "repository": "github:acme/app",
                        "base_branch": "main",
                        "provider": "github",
                        "pull_request": "github:acme/app#52",
                        "source_branch": "feature/cc-52",
                        "source_head_sha": source_head_sha,
                    }
                ],
            }
        if supersedes_source_head_sha:
            evidence["supersession"] = {
                "supersedes_source_head_sha": supersedes_source_head_sha,
                "reason": "The PR head changed after a commit-message rewrite.",
            }
        path = work_item / "artifacts" / "auto-dev-pr-create" / f"family-{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema": "development-stage-evidence/v1",
                    "state": "release_propagation",
                    "status": "completed",
                    "summary": f"PR family is current at {source_head_sha}",
                    "verified_at": "2026-08-11T15:10:32Z",
                    "evidence": evidence,
                }
            ),
            encoding="utf-8",
        )
        return path

    old_head = base_sha
    new_head = "b" * 40
    original_receipt = family_receipt("old", old_head, legacy_nested_identity=True)
    first = run_development_stage(
        task.path,
        stage="release_propagation",
        receipts={"release_propagation": str(original_receipt)},
        idempotency_prefix="cc-52:pr-create:old",
    )
    legacy_wrapper = task.path.parent / "stages" / "release-propagation.json"
    legacy_bytes = legacy_wrapper.read_bytes()
    legacy_binding = dict(task.read()["stage_receipts"]["release_propagation"])

    missing_supersession_receipt = family_receipt("new-without-proof", new_head)
    with pytest.raises(
        DevelopmentDeliveryError,
        match="requires provider-read new head and explicit prior-head supersession",
    ):
        run_development_stage(
            task.path,
            stage="release_propagation",
            receipts={"release_propagation": str(missing_supersession_receipt)},
            idempotency_prefix="cc-52:pr-create:missing-supersession",
        )
    assert legacy_wrapper.read_bytes() == legacy_bytes

    refreshed_receipt = family_receipt(
        "new",
        new_head,
        supersedes_source_head_sha=old_head,
    )
    post_pr_task = task.read()
    post_pr_task["state"] = "ready_for_merge"
    post_pr_task["subject_revision"] = old_head
    task.path.write_text(json.dumps(post_pr_task), encoding="utf-8")

    # Numeric PR equality is not authority: a differently qualified PR with
    # the same number cannot furnish the prior ready-for-merge acceptance.
    ready_record = next(
        item
        for item in reversed(post_pr_task["receipts"])
        if item.get("state") == "ready_for_merge"
    )
    ready_path = Path(ready_record["ref"])
    ready_bytes = ready_path.read_bytes()
    mismatched_ready = json.loads(ready_bytes)
    mismatched_ready["evidence"]["pull_request"] = "github:other/app#52"
    ready_path.write_text(json.dumps(mismatched_ready), encoding="utf-8")
    mismatched_task = json.loads(json.dumps(post_pr_task))
    mismatched_record = next(
        item
        for item in reversed(mismatched_task["receipts"])
        if item.get("state") == "ready_for_merge"
    )
    mismatched_record["sha256"] = hashlib.sha256(ready_path.read_bytes()).hexdigest()
    task.path.write_text(json.dumps(mismatched_task), encoding="utf-8")
    with pytest.raises(
        DevelopmentDeliveryError,
        match="canonical prior review authority",
    ):
        run_development_stage(
            task.path,
            stage="release_propagation",
            receipts={"release_propagation": str(refreshed_receipt)},
            idempotency_prefix="cc-52:pr-create:wrong-qualified-pr",
        )
    ready_path.write_bytes(ready_bytes)
    task.path.write_text(json.dumps(post_pr_task), encoding="utf-8")

    def set_ready_evidence(**updates: object) -> bytes:
        updated_ready = json.loads(ready_bytes)
        updated_ready["evidence"].update(updates)
        updated_ready_bytes = json.dumps(updated_ready).encode("utf-8")
        ready_path.write_bytes(updated_ready_bytes)
        updated_task = json.loads(json.dumps(post_pr_task))
        updated_record = next(
            item
            for item in reversed(updated_task["receipts"])
            if item.get("state") == "ready_for_merge"
        )
        updated_record["sha256"] = hashlib.sha256(updated_ready_bytes).hexdigest()
        task.path.write_text(json.dumps(updated_task), encoding="utf-8")
        return updated_ready_bytes

    for label, updates in (
        ("zero", {"pull_request": "0"}),
        ("malformed", {"pull_request": "not-a-pr"}),
        ("different", {"pull_request": "53"}),
        ("foreign-repository", {"repository": "git:github.com/other/app", "pull_request": "52"}),
        ("foreign-base", {"base_branch": "release", "pull_request": "52"}),
        ("foreign-provider", {"provider": "gitlab", "pull_request": "52"}),
    ):
        refused_ready_bytes = set_ready_evidence(**updates)
        with pytest.raises(
            DevelopmentDeliveryError,
            match="canonical prior review authority",
        ):
            run_development_stage(
                task.path,
                stage="release_propagation",
                receipts={"release_propagation": str(refreshed_receipt)},
                idempotency_prefix=f"cc-52:pr-create:{label}-ready-pr",
            )
        assert ready_path.read_bytes() == refused_ready_bytes

    legacy_ready_bytes = set_ready_evidence(pull_request="52")
    refreshed = run_development_stage(
        task.path,
        stage="release_propagation",
        receipts={"release_propagation": str(refreshed_receipt)},
        idempotency_prefix="cc-52:pr-create:new",
    )

    current = task.read()["stage_receipts"]["release_propagation"]
    current_wrapper = Path(current["ref"])
    assert legacy_wrapper.read_bytes() == legacy_bytes
    assert ready_path.read_bytes() == legacy_ready_bytes
    assert current_wrapper != legacy_wrapper
    assert current_wrapper.is_file()
    assert refreshed["supersedes"]["wrapper_ref"] == str(legacy_wrapper)
    assert refreshed["supersedes"]["source_head_sha"] == old_head
    assert current["sha256"] == hashlib.sha256(current_wrapper.read_bytes()).hexdigest()
    assert current_wrapper.parent.name == "release-propagation"
    assert first["receipt"] != refreshed["receipt"]
    refreshed_task = task.read()
    assert refreshed_task["state"] == "local_validation"
    assert refreshed_task["subject_revision"] is None
    assert refreshed_task["subject_supersessions"][-1]["from_subject_revision"] == old_head
    assert refreshed_task["subject_supersessions"][-1]["to_source_head_sha"] == new_head
    projection = read_auto_dev_state(task.read()["autodev_path"])
    assert projection["subject_revision"] is None
    assert projection["stages"]["pr_create"]["status"] == "completed"
    assert projection["stages"]["pr_create"]["run_ref"].endswith(current_wrapper.name)
    assert projection["stages"]["review_self"]["status"] == "not_started"
    assert projection["stages"]["qa"]["status"] == "not_started"
    assert projection["stages"]["finalize"]["status"] == "not_started"

    # Simulate interruption after the append-only wrapper write but before the
    # task binding write. The same idempotency key must finish that transaction.
    interrupted = task.read()
    interrupted["stage_receipts"]["release_propagation"] = legacy_binding
    task.path.write_text(json.dumps(interrupted), encoding="utf-8")
    recovered = run_development_stage(
        task.path,
        stage="release_propagation",
        receipts={"release_propagation": str(refreshed_receipt)},
        idempotency_prefix="cc-52:pr-create:new",
    )
    assert recovered == refreshed

    replayed = run_development_stage(
        task.path,
        stage="release_propagation",
        receipts={"release_propagation": str(refreshed_receipt)},
        idempotency_prefix="cc-52:pr-create:new",
    )
    assert replayed == refreshed

    # A second PR rewrite before any fresh review advances the active fence.
    # The intermediate B head must never be able to consume the older A->B
    # marker and become merge authority after propagation has reached C.
    newest_head = "c" * 40
    newest_receipt = family_receipt(
        "newest",
        newest_head,
        supersedes_source_head_sha=new_head,
    )
    newest = run_development_stage(
        task.path,
        stage="release_propagation",
        receipts={"release_propagation": str(newest_receipt)},
        idempotency_prefix="cc-52:pr-create:newest",
    )
    newest_task = task.read()
    assert newest["supersedes"]["source_head_sha"] == new_head
    assert [
        item["to_source_head_sha"] for item in newest_task["subject_supersessions"]
    ] == [new_head, newest_head]
    assert newest_task["state"] == "local_validation"
    assert newest_task["subject_revision"] is None
    current = newest_task["stage_receipts"]["release_propagation"]
    current_wrapper = Path(current["ref"])
    projection = read_auto_dev_state(task.read()["autodev_path"])
    assert projection["subject_revision"] is None
    assert projection["stages"]["review_self"]["status"] == "not_started"
    assert projection["stages"]["qa"]["status"] == "not_started"
    assert projection["stages"]["finalize"]["status"] == "not_started"

    def review_receipts(name: str, head: str) -> dict[str, str]:
        review_root = work_item / "artifacts" / f"review-{name}"
        authority = _provider_authority(task, pull_request="github:acme/app#52")
        return {
            "pre_pr_review": _stage_receipt(review_root, "pre_pr_review"),
            "pr_open": _stage_receipt(review_root, "pr_open", evidence=authority),
            "ci_repair": _stage_receipt(review_root, "ci_repair"),
            "review_repair": _stage_receipt(review_root, "review_repair"),
            "post_pr_review": _stage_receipt(review_root, "post_pr_review"),
            "ready_for_merge": _stage_receipt(
                review_root,
                "ready_for_merge",
                evidence={
                    **authority,
                    "checks_verified": True,
                    "reviews_verified": True,
                    "source_branch": "feature/cc-52",
                    "source_head_sha": head,
                    "subject_revision": head,
                },
            ),
        }

    # The append-only wrapper is an active fence: the intermediate B review
    # proof cannot re-promote this task after its PR head advanced to C.
    with pytest.raises(
        DevelopmentDeliveryError,
        match="must bind the refreshed release-propagation head",
    ):
        run_development_stage(
            task.path,
            stage="review",
            receipts=review_receipts("stale", new_head),
            idempotency_prefix="cc-52:review:stale",
        )
    assert task.read()["state"] == "local_validation"
    with pytest.raises(AutoDevStateError, match="qa is blocked until fresh Review Self"):
        _record_standalone_stage(task, "qa", revision=old_head)
    with pytest.raises(AutoDevStateError, match="finalize is blocked until fresh Review Self"):
        _record_standalone_stage(
            task,
            "finalize",
            revision=old_head,
            pull_request="github:acme/app#52",
        )

    reviewed = run_development_stage(
        task.path,
        stage="review",
        receipts=review_receipts("fresh", newest_head),
        idempotency_prefix="cc-52:review:fresh",
    )
    assert reviewed["state"] == "ready_for_merge"
    reviewed_task = task.read()
    assert reviewed_task["subject_revision"] == newest_head
    assert [
        item["subject_revision"]
        for item in reviewed_task["subject_supersession_resolutions"]
    ] == [newest_head, newest_head]
    projection = read_auto_dev_state(task.read()["autodev_path"])
    assert projection["subject_revision"] == newest_head
    assert projection["stages"]["review_self"]["status"] == "completed"
    assert projection["stages"]["qa"]["status"] == "not_started"
    assert projection["stages"]["finalize"]["status"] == "not_started"
    with pytest.raises(
        AutoDevStateError,
        match="qa evidence subject_revision must match the canonical reviewed pull-request head",
    ):
        _record_standalone_stage(task, "qa", revision=new_head)
    _record_standalone_stage(task, "qa", revision=newest_head)
    _record_standalone_stage(
        task,
        "finalize",
        revision=newest_head,
        pull_request="github:acme/app#52",
    )
    projection = read_auto_dev_state(task.read()["autodev_path"])
    assert projection["stages"]["qa"]["status"] == "completed"
    assert projection["stages"]["finalize"]["status"] == "completed"

    malformed_new_receipt = family_receipt(
        "malformed-new-pr",
        "d" * 40,
        supersedes_source_head_sha=newest_head,
    )
    malformed_new_payload = json.loads(malformed_new_receipt.read_text(encoding="utf-8"))
    malformed_new_payload["evidence"]["pull_request"] = "github:acme/app#"
    malformed_new_receipt.write_text(json.dumps(malformed_new_payload), encoding="utf-8")
    with pytest.raises(
        DevelopmentDeliveryError,
        match="new pull_request.*non-empty numeric identifier",
    ):
        run_development_stage(
            task.path,
            stage="release_propagation",
            receipts={"release_propagation": str(malformed_new_receipt)},
            idempotency_prefix="cc-52:pr-create:malformed-new-pr",
        )

    # A supersession is not a way to retarget this task. Both receipts can be
    # internally consistent yet still name a different repository and branch.
    task_mismatch = {
        "repository": "github:other/app",
        "base_branch": "trunk",
        "provider": "github",
        "pull_request": "github:other/app#52",
        "source_branch": "feature/other",
    }
    current_wrapper_payload = json.loads(current_wrapper.read_text(encoding="utf-8"))
    current_receipt_path = work_item / current_wrapper_payload["receipt"]
    current_receipt = json.loads(current_receipt_path.read_text(encoding="utf-8"))
    current_receipt["evidence"].update(task_mismatch)
    current_receipt_path.write_text(json.dumps(current_receipt), encoding="utf-8")
    current_wrapper_payload["evidence_sha256"] = hashlib.sha256(
        json.dumps(current_receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    current_wrapper.write_text(json.dumps(current_wrapper_payload), encoding="utf-8")
    task_mismatch_state = task.read()
    task_mismatch_state["stage_receipts"]["release_propagation"]["sha256"] = hashlib.sha256(
        current_wrapper.read_bytes()
    ).hexdigest()
    task.path.write_text(json.dumps(task_mismatch_state), encoding="utf-8")
    arbitrary_receipt = family_receipt(
        "task-mismatch",
        "d" * 40,
        supersedes_source_head_sha=newest_head,
    )
    arbitrary_payload = json.loads(arbitrary_receipt.read_text(encoding="utf-8"))
    arbitrary_payload["evidence"].update(task_mismatch)
    arbitrary_receipt.write_text(json.dumps(arbitrary_payload), encoding="utf-8")
    with pytest.raises(
        DevelopmentDeliveryError,
        match="identity must match the selected task repository",
    ):
        run_development_stage(
            task.path,
            stage="release_propagation",
            receipts={"release_propagation": str(arbitrary_receipt)},
            idempotency_prefix="cc-52:pr-create:task-mismatch",
        )

    missing_identity_payload = json.loads(arbitrary_receipt.read_text(encoding="utf-8"))
    del missing_identity_payload["evidence"]["provider"]
    arbitrary_receipt.write_text(json.dumps(missing_identity_payload), encoding="utf-8")
    with pytest.raises(
        DevelopmentDeliveryError,
        match="requires complete prior and new PR identity",
    ):
        run_development_stage(
            task.path,
            stage="release_propagation",
            receipts={"release_propagation": str(arbitrary_receipt)},
            idempotency_prefix="cc-52:pr-create:missing-new-identity",
        )

    missing_identity_payload["evidence"]["provider"] = "github"
    arbitrary_receipt.write_text(json.dumps(missing_identity_payload), encoding="utf-8")
    prior_missing_identity = json.loads(current_receipt_path.read_text(encoding="utf-8"))
    del prior_missing_identity["evidence"]["provider"]
    current_receipt_path.write_text(json.dumps(prior_missing_identity), encoding="utf-8")
    current_wrapper_payload["evidence_sha256"] = hashlib.sha256(
        json.dumps(prior_missing_identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    current_wrapper.write_text(json.dumps(current_wrapper_payload), encoding="utf-8")
    prior_missing_state = task.read()
    prior_missing_state["stage_receipts"]["release_propagation"]["sha256"] = hashlib.sha256(
        current_wrapper.read_bytes()
    ).hexdigest()
    task.path.write_text(json.dumps(prior_missing_state), encoding="utf-8")
    with pytest.raises(
        DevelopmentDeliveryError,
        match="requires complete prior and new PR identity",
    ):
        run_development_stage(
            task.path,
            stage="release_propagation",
            receipts={"release_propagation": str(arbitrary_receipt)},
            idempotency_prefix="cc-52:pr-create:missing-prior-identity",
        )

    prior_missing_identity["evidence"].update(
        {
            "repository": "git:github.com/acme/app",
            "base_branch": "main",
            "provider": "github",
            "pull_request": "github:acme/app#",
            "source_branch": "feature/cc-52",
        }
    )
    current_receipt_path.write_text(json.dumps(prior_missing_identity), encoding="utf-8")
    current_wrapper_payload["evidence_sha256"] = hashlib.sha256(
        json.dumps(prior_missing_identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    current_wrapper.write_text(json.dumps(current_wrapper_payload), encoding="utf-8")
    malformed_prior_state = task.read()
    malformed_prior_state["stage_receipts"]["release_propagation"]["sha256"] = hashlib.sha256(
        current_wrapper.read_bytes()
    ).hexdigest()
    task.path.write_text(json.dumps(malformed_prior_state), encoding="utf-8")
    malformed_prior_receipt = family_receipt(
        "malformed-prior-pr",
        "d" * 40,
        supersedes_source_head_sha=newest_head,
    )
    with pytest.raises(
        DevelopmentDeliveryError,
        match="prior pull_request.*non-empty numeric identifier",
    ):
        run_development_stage(
            task.path,
            stage="release_propagation",
            receipts={"release_propagation": str(malformed_prior_receipt)},
            idempotency_prefix="cc-52:pr-create:malformed-prior-pr",
        )


@pytest.mark.parametrize(
    (
        "repository_id",
        "legacy_repository",
        "registered_source_branch",
        "legacy_source_branch",
        "refreshed_source_branch",
        "expected_refresh_error",
    ),
    [
        (
            "git:github.com/acme/app",
            "acme/app",
            "feature/cc-53",
            "feature/cc-53",
            "feature/cc-53",
            None,
        ),
        (
            "git:github.com/acme/app",
            "acme/app",
            "feature/cc-53",
            None,
            "feature/cc-53",
            None,
        ),
        (
            "git:github.com/acme/app",
            "acme/app",
            None,
            None,
            "feature/cc-53",
            "requires complete prior and new PR identity",
        ),
        (
            "git:github.com/acme/app",
            "acme/app",
            "feature/cc-53",
            None,
            "feature/other",
            "requires complete prior and new PR identity",
        ),
        (
            "git:github.com/acme/app",
            "acme/app",
            "feature/cc-53",
            "feature/other",
            "feature/cc-53",
            "must retain the same source_branch",
        ),
        (
            "github:acme/app",
            "github:acme/app",
            "feature/cc-53",
            "feature/cc-53",
            "feature/cc-53",
            "prior pull_request.*non-empty numeric identifier",
        ),
    ],
)
def test_release_propagation_normalizes_only_selected_legacy_flat_github_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    repository_id: str,
    legacy_repository: str,
    registered_source_branch: str | None,
    legacy_source_branch: str | None,
    refreshed_source_branch: str,
    expected_refresh_error: str | None,
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo, repository_id=repository_id)
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": "cc-53",
            "path": "/tmp/cc-53",
            "branch": registered_source_branch,
            "base_sha": base_sha,
        },
    )
    run = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-53"],
        run_id="release-propagation-flat-identity",
        auto_dev_mode="everything",
        apply=True,
    )
    task = TaskState(Path(run["tasks"][0]["state_ref"]))
    _advance_auto_dev_task_to_ready(
        task,
        subject_revision=base_sha,
        pull_request="github:acme/app#53",
    )
    for stage_name in ("groom", "detective", "create_artifacts", "document"):
        _record_standalone_stage(task, stage_name)
    task_value = task.read()
    task_value["state"] = "local_validation"
    task.path.write_text(json.dumps(task_value), encoding="utf-8")
    work_item = Path(task_value["work_item"])

    def receipt(
        name: str,
        head: str,
        *,
        legacy: bool = False,
        supersedes: str = "a" * 40,
    ) -> Path:
        evidence: dict[str, object] = {
            "ticket": "CC-53",
            "repository": legacy_repository if legacy else repository_id,
            "base_branch": "main",
            "provider": "github",
            "pull_request": "53" if legacy else "github:acme/app#53",
            "source_head_sha": head,
            "readback_verified": True,
            "provider_observed": {"head_sha": head},
        }
        if not legacy or legacy_source_branch is not None:
            evidence["source_branch"] = (
                legacy_source_branch if legacy else refreshed_source_branch
            )
        if not legacy:
            evidence["supersession"] = {
                "supersedes_source_head_sha": supersedes,
                "reason": "The verified PR head changed after the prior family receipt.",
            }
        path = work_item / "artifacts" / "auto-dev-pr-create" / f"flat-{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema": "development-stage-evidence/v1",
                    "state": "release_propagation",
                    "status": "completed",
                    "summary": f"PR family is current at {head}",
                    "verified_at": "2026-08-12T08:00:00Z",
                    "evidence": evidence,
                }
            ),
            encoding="utf-8",
        )
        return path

    old = receipt("old", "a" * 40, legacy=True)
    run_development_stage(
        task.path,
        stage="release_propagation",
        receipts={"release_propagation": str(old)},
        idempotency_prefix="cc-53:pr-create:old",
    )
    old_bytes = old.read_bytes()
    old_wrapper = Path(task.read()["stage_receipts"]["release_propagation"]["ref"])
    old_wrapper_bytes = old_wrapper.read_bytes()
    refreshed = receipt("new", "b" * 40)
    if expected_refresh_error is None:
        output = run_development_stage(
            task.path,
            stage="release_propagation",
            receipts={"release_propagation": str(refreshed)},
            idempotency_prefix="cc-53:pr-create:new",
        )
        assert output["supersedes"]["source_head_sha"] == "a" * 40
        assert old.read_bytes() == old_bytes
        assert old_wrapper.read_bytes() == old_wrapper_bytes
        if legacy_source_branch is None:
            assert output["supersedes"]["legacy_identity_normalization"] == {
                "field": "source_branch",
                "source": "selected_task.worktree.branch",
                "value": registered_source_branch,
            }
        else:
            assert "legacy_identity_normalization" not in output["supersedes"]
    else:
        with pytest.raises(
            DevelopmentDeliveryError,
            match=expected_refresh_error,
        ):
            run_development_stage(
                task.path,
                stage="release_propagation",
                receipts={"release_propagation": str(refreshed)},
                idempotency_prefix="cc-53:pr-create:new",
            )
        assert old.read_bytes() == old_bytes
        assert old_wrapper.read_bytes() == old_wrapper_bytes


def test_release_propagation_normalizes_exact_legacy_family_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A historical family-complete receipt may refresh without rewriting history."""

    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo, repository_id="git:github.com/acme/app")
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": "cc-54",
            "path": "/tmp/cc-54",
            "branch": "feature/cc-54",
            "base_sha": base_sha,
        },
    )
    run = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-54"],
        run_id="release-propagation-family-identity",
        auto_dev_mode="everything",
        apply=True,
    )
    task = TaskState(Path(run["tasks"][0]["state_ref"]))
    _advance_auto_dev_task_to_ready(
        task,
        subject_revision=base_sha,
        pull_request="github:acme/app#54",
    )
    for stage_name in ("groom", "detective", "create_artifacts", "document"):
        _record_standalone_stage(task, stage_name)
    task_value = task.read()
    task_value["state"] = "local_validation"
    task.path.write_text(json.dumps(task_value), encoding="utf-8")
    work_item = Path(task_value["work_item"])

    def receipt(name: str, evidence: dict[str, object]) -> Path:
        path = work_item / "artifacts" / "auto-dev-pr-create" / f"family-{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema": "development-stage-evidence/v1",
                    "state": "release_propagation",
                    "status": "completed",
                    "summary": f"PR family receipt {name}",
                    "verified_at": "2026-08-12T18:00:00Z",
                    "evidence": evidence,
                }
            ),
            encoding="utf-8",
        )
        return path

    old = receipt(
        "old",
        {
            "family": [
                {
                    "repository": "acme/app",
                    "provider": "github",
                    "pull_request": 54,
                    "base": "main",
                    "source_branch": "feature/cc-54",
                    "source_head": base_sha,
                    "provider_readback_verified": True,
                }
            ],
            "receipt_refs": ["artifacts/auto-dev-pr-create/provider-readback.json"],
        },
    )
    run_development_stage(
        task.path,
        stage="release_propagation",
        receipts={"release_propagation": str(old)},
        idempotency_prefix="cc-54:pr-create:old",
    )
    old_wrapper = Path(task.read()["stage_receipts"]["release_propagation"]["ref"])
    old_bytes = old.read_bytes()
    old_wrapper_bytes = old_wrapper.read_bytes()

    new_head = "b" * 40
    refreshed = receipt(
        "new",
        {
            "repository": "git:github.com/acme/app",
            "base_branch": "main",
            "provider": "github",
            "pull_request": "github:acme/app#54",
            "source_branch": "feature/cc-54",
            "source_head_sha": new_head,
            "readback_verified": True,
            "provider_observed": {"head_sha": new_head},
            "supersession": {
                "supersedes_source_head_sha": base_sha,
                "reason": "The provider readback reports the refreshed PR head.",
            },
        },
    )
    output = run_development_stage(
        task.path,
        stage="release_propagation",
        receipts={"release_propagation": str(refreshed)},
        idempotency_prefix="cc-54:pr-create:new",
    )

    current_wrapper = Path(task.read()["stage_receipts"]["release_propagation"]["ref"])
    assert old.read_bytes() == old_bytes
    assert old_wrapper.read_bytes() == old_wrapper_bytes
    assert current_wrapper != old_wrapper
    assert output["supersedes"]["legacy_identity_normalization"] == {
        "source": "evidence.family[0]",
        "legacy_fields": {
            "repository": "acme/app",
            "base": "main",
            "provider": "github",
            "pull_request": 54,
            "source_branch": "feature/cc-54",
            "source_head": base_sha,
        },
        "normalized_identity": {
            "repository": "git:github.com/acme/app",
            "base_branch": "main",
            "provider": "github",
            "pull_request": "github:acme/app#54",
            "source_branch": "feature/cc-54",
            "source_head_sha": base_sha,
        },
    }


@pytest.mark.parametrize(
    ("label", "family_mutation", "successor_mutation", "error"),
    [
        (
            "missing",
            "missing",
            None,
            "requires provider-read new head and explicit prior-head supersession",
        ),
        ("empty", "empty", None, "requires exactly one object"),
        ("multiple", "multiple", None, "requires exactly one object"),
        ("non-object", "non-object", None, "requires exactly one object"),
        ("mixed", "mixed", None, "must not mix with another prior identity format"),
        ("missing-readback", "missing-readback", None, "does not exactly bind"),
        ("false-readback", "false-readback", None, "does not exactly bind"),
        ("string-pr", "string-pr", None, "does not exactly bind"),
        ("zero-pr", "zero-pr", None, "does not exactly bind"),
        ("foreign-repository", "foreign-repository", None, "does not exactly bind"),
        ("foreign-base", "foreign-base", None, "does not exactly bind"),
        ("foreign-provider", "foreign-provider", None, "does not exactly bind"),
        ("foreign-branch", "foreign-branch", None, "does not exactly bind"),
        ("malformed-head", "malformed-head", None, "does not exactly bind"),
        (
            "case-only-head",
            "uppercase-head",
            "case-only-head",
            "requires provider-read new head and explicit prior-head supersession",
        ),
        (
            "successor-readback-drift",
            None,
            "successor-readback-drift",
            "requires provider-read new head and explicit prior-head supersession",
        ),
        (
            "successor-wrong-branch",
            None,
            "successor-wrong-branch",
            "must retain the same source_branch",
        ),
    ],
)
def test_release_propagation_refuses_unsafe_legacy_family_identity_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    label: str,
    family_mutation: str | None,
    successor_mutation: str | None,
    error: str,
) -> None:
    """Malformed legacy family identity cannot mutate the active delivery binding."""

    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo, repository_id="git:github.com/acme/app")
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": f"cc-55-{label}",
            "path": f"/tmp/cc-55-{label}",
            "branch": "feature/cc-55",
            "base_sha": base_sha,
        },
    )
    run = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-55"],
        run_id=f"release-propagation-family-refusal-{label}",
        auto_dev_mode="everything",
        apply=True,
    )
    task = TaskState(Path(run["tasks"][0]["state_ref"]))
    _advance_auto_dev_task_to_ready(
        task,
        subject_revision=base_sha,
        pull_request="github:acme/app#55",
    )
    for stage_name in ("groom", "detective", "create_artifacts", "document"):
        _record_standalone_stage(task, stage_name)
    task_value = task.read()
    task_value["state"] = "local_validation"
    task.path.write_text(json.dumps(task_value), encoding="utf-8")
    work_item = Path(task_value["work_item"])

    family_item: dict[str, object] = {
        "repository": "acme/app",
        "provider": "github",
        "pull_request": 55,
        "base": "main",
        "source_branch": "feature/cc-55",
        "source_head": base_sha,
        "provider_readback_verified": True,
    }
    prior_evidence: dict[str, object] = {"family": [family_item]}
    if family_mutation == "missing":
        prior_evidence = {"receipt_refs": ["artifacts/auto-dev-pr-create/provider-readback.json"]}
    elif family_mutation == "empty":
        prior_evidence["family"] = []
    elif family_mutation == "multiple":
        prior_evidence["family"] = [family_item, dict(family_item)]
    elif family_mutation == "non-object":
        prior_evidence["family"] = ["not-an-object"]
    elif family_mutation == "mixed":
        prior_evidence["repository"] = "git:github.com/acme/app"
    elif family_mutation == "missing-readback":
        family_item.pop("provider_readback_verified")
    elif family_mutation == "false-readback":
        family_item["provider_readback_verified"] = False
    elif family_mutation == "string-pr":
        family_item["pull_request"] = "55"
    elif family_mutation == "zero-pr":
        family_item["pull_request"] = 0
    elif family_mutation == "foreign-repository":
        family_item["repository"] = "other/app"
    elif family_mutation == "foreign-base":
        family_item["base"] = "release"
    elif family_mutation == "foreign-provider":
        family_item["provider"] = "gitlab"
    elif family_mutation == "foreign-branch":
        family_item["source_branch"] = "feature/other"
    elif family_mutation == "malformed-head":
        family_item["source_head"] = "not-a-sha"
    elif family_mutation == "uppercase-head":
        family_item["source_head"] = base_sha.upper()

    def receipt(name: str, evidence: dict[str, object]) -> Path:
        path = work_item / "artifacts" / "auto-dev-pr-create" / f"refusal-{label}-{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema": "development-stage-evidence/v1",
                    "state": "release_propagation",
                    "status": "completed",
                    "summary": f"PR family receipt {name}",
                    "verified_at": "2026-08-12T18:00:00Z",
                    "evidence": evidence,
                }
            ),
            encoding="utf-8",
        )
        return path

    old = receipt("old", prior_evidence)
    run_development_stage(
        task.path,
        stage="release_propagation",
        receipts={"release_propagation": str(old)},
        idempotency_prefix=f"cc-55:{label}:old",
    )
    old_wrapper = Path(task.read()["stage_receipts"]["release_propagation"]["ref"])
    new_head = base_sha if successor_mutation == "case-only-head" else "b" * 40
    successor_evidence: dict[str, object] = {
        "repository": "git:github.com/acme/app",
        "base_branch": "main",
        "provider": "github",
        "pull_request": "github:acme/app#55",
        "source_branch": "feature/cc-55",
        "source_head_sha": new_head,
        "readback_verified": True,
        "provider_observed": {"head_sha": new_head},
        "supersession": {
            "supersedes_source_head_sha": base_sha,
            "reason": "The provider readback reports the refreshed PR head.",
        },
    }
    if successor_mutation == "successor-readback-drift":
        successor_evidence["provider_observed"] = {"head_sha": base_sha}
    elif successor_mutation == "successor-wrong-branch":
        successor_evidence["source_branch"] = "feature/other"
    refreshed = receipt("new", successor_evidence)

    def snapshot(path: Path) -> bytes | None:
        return path.read_bytes() if path.is_file() else None

    autodev_path = Path(task.read()["autodev_path"])
    before = {
        "task": snapshot(task.path),
        "autodev": snapshot(autodev_path),
        "ledger": snapshot(task.ledger),
        "wrapper": snapshot(old_wrapper),
        "prior_evidence": snapshot(old),
    }
    with pytest.raises(DevelopmentDeliveryError, match=error):
        run_development_stage(
            task.path,
            stage="release_propagation",
            receipts={"release_propagation": str(refreshed)},
            idempotency_prefix=f"cc-55:{label}:new",
        )
    assert {
        "task": snapshot(task.path),
        "autodev": snapshot(autodev_path),
        "ledger": snapshot(task.ledger),
        "wrapper": snapshot(old_wrapper),
        "prior_evidence": snapshot(old),
    } == before


def test_heartbeat_does_not_refresh_milestone_evidence_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo)
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": "cc-52",
            "path": "/tmp/cc-52",
            "branch": "feature/cc-52",
            "base_sha": base_sha,
        },
    )
    run = delivery.start_development_run(
        root, "acme", "app", ["CC-52"], run_id="heartbeat-provenance", apply=True
    )
    task_path = Path(run["tasks"][0]["state_ref"])
    TaskState(task_path).transition("planned", receipt="plan:verified", idempotency_key="planned")
    before = read_auto_dev_state(TaskState(task_path).read()["autodev_path"])
    TaskState(task_path).heartbeat(owner="worker", lease_minutes=10, idempotency_key="heartbeat")
    after = read_auto_dev_state(TaskState(task_path).read()["autodev_path"])
    assert after["stages"]["readiness"]["last_verified_at"] == before["stages"]["readiness"]["last_verified_at"]
    assert after["stages"]["readiness"]["receipt_refs"] == ["plan:verified"]


def test_auto_dev_template_satisfies_strict_runtime_schema() -> None:
    repository = Path(__file__).resolve().parents[1]
    schema = json.loads((repository / "schemas/auto-dev-work-item.schema.json").read_text(encoding="utf-8"))
    template = json.loads(
        (
            repository
            / "harness/shared_factory/00-programs/auto_dev/templates/autodev.json"
        ).read_text(encoding="utf-8")
    )
    assert list(Draft202012Validator(schema).iter_errors(template)) == []
    assert set(template["stage_order"]) == set(template["stages"])
    assert template["stage_order"][-1] == "health"


def test_shipped_auto_dev_knowledge_matches_canonical_stage_order() -> None:
    repository = Path(__file__).resolve().parents[1]
    policy_root = repository / "harness/shared_factory/05-knowledge/auto_dev"
    stage_labels = {
        "groom": "Grooming",
        "detective": "Detective",
        "create_artifacts": "Create Artifacts",
        "readiness": "Readiness",
        "develop": "Develop",
        "document": "Document",
        "pr_create": "PR Create",
        "review_self": "Review Self",
        "review_others": "Review Others",
        "qa": "QA",
        "finalize": "Finalize",
        "merge": "Merge",
        "release": "Release",
        "deploy": "Deploy",
        "closeout": "Closeout",
        "health": "Health",
    }
    expected = [stage_labels[stage] for stage in AUTO_DEV_STAGE_ORDER]

    general = (policy_root / "00-auto-dev-general.md").read_text(encoding="utf-8")
    general_lifecycle = general.split("## Canonical lifecycle", 1)[1].split(
        "## Orchestration", 1
    )[0]
    numbered_stages = [
        line.split(". ", 1)[1]
        for line in general_lifecycle.splitlines()
        if line.split(". ", 1)[0].isdigit()
    ]

    everything = (policy_root / "13-auto-dev-everything.md").read_text(
        encoding="utf-8"
    )
    everything_order = everything.split("## Exact stage order", 1)[1].split(
        "## Orchestration behavior", 1
    )[0]
    table_stages = []
    for line in everything_order.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0].isdigit():
            table_stages.append(cells[1])

    assert numbered_stages == expected
    assert table_stages == expected
    assert "Neither compatibility surface adds another Auto-Dev stage" in " ".join(
        general.split()
    )
    assert "Neither compatibility surface is a separate Auto-Dev stage" in " ".join(
        everything.split()
    )

    for command_name in ("auto-dev.md", "auto-dev-everything.md"):
        command = (
            repository / "harness" / "commands" / command_name
        ).read_text(encoding="utf-8")
        normalized_command = " ".join(command.split())
        assert "Document, PR Create, Review Self, Review Others, QA" in normalized_command
        assert "compatibility recorder/alias for PR Create" in normalized_command

    readme = (policy_root / "README.md").read_text(encoding="utf-8")
    readme_order = readme.split("## Files and execution order", 1)[1].split(
        "Each workflow has a same-named command", 1
    )[0]
    readme_stages = []
    for line in readme_order.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0].isdigit():
            readme_stages.append(cells[1])
    assert readme_stages == expected
    assert "intentionally outside this stage table" in " ".join(readme.split())

    everything_skill = (
        repository / "harness/skills/auto-dev-everything/SKILL.md"
    ).read_text(encoding="utf-8")
    normalized_skill = " ".join(everything_skill.split())
    assert (
        "Develop, Document, PR Create, Review Self, Review Others, QA, Finalize"
        in normalized_skill
    )
    assert "does not add another Auto-Dev stage" in normalized_skill

    auto_dev_skill = (
        repository / "harness/skills/auto-dev/SKILL.md"
    ).read_text(encoding="utf-8")
    numbered_skill_stages = [
        line
        for line in auto_dev_skill.splitlines()
        if re.match(r"^\d+\. ", line)
    ]
    assert len(numbered_skill_stages) == 16
    assert numbered_skill_stages[6] == "7. `$auto-dev-pr-create`"
    assert "$auto-dev-review-self" in numbered_skill_stages[7]
    assert numbered_skill_stages[9] == "10. `$auto-dev-qa`"
    assert numbered_skill_stages[10] == "11. `$auto-dev-finalize`"
    assert not any(
        "$auto-dev-release-propagation" in line
        for line in numbered_skill_stages
    )
    assert "is not counted in this list" in auto_dev_skill

    finalize_policy = (policy_root / "07-auto-dev-finalize.md").read_text(
        encoding="utf-8"
    )
    release_policy = (policy_root / "10-auto-dev-release.md").read_text(
        encoding="utf-8"
    )
    assert "required PR Create and QA dispositions" in finalize_policy
    assert "QA and Release Propagation" not in finalize_policy
    assert "lower-level compatibility recorder/alias" in " ".join(
        release_policy.split()
    )
    assert "Release Propagation is a separate stage" not in release_policy

    review_self_policy = (policy_root / "05-auto-dev-review-self.md").read_text(
        encoding="utf-8"
    )
    normalized_review_self = " ".join(review_self_policy.split())
    assert "consumes the family created by PR Create" in normalized_review_self
    assert "never creates or retargets a pull request" in normalized_review_self
    assert "Create or update the pull request" not in review_self_policy

    propagation_policy = (
        policy_root / "16-auto-dev-release-propagation.md"
    ).read_text(encoding="utf-8")
    normalized_propagation_policy = " ".join(propagation_policy.split())
    assert "Delegate the invocation to `/auto-dev-pr-create`" in (
        normalized_propagation_policy
    )
    assert "never resolves target branches" in normalized_propagation_policy
    assert "## Propagation behavior" not in propagation_policy


@pytest.mark.parametrize(
    "relative_path",
    [
        "harness/shared_factory/00-programs/auto_dev/templates/auto-dev-stage-policy-decision.json",
        "harness/shared_factory/05-knowledge/auto_dev/examples/auto-dev-stage-policy-decision.json",
    ],
)
def test_shipped_auto_dev_stage_policy_decisions_satisfy_strict_schema(
    relative_path: str,
) -> None:
    repository = Path(__file__).resolve().parents[1]
    schema = json.loads(
        (
            repository / "schemas/auto-dev-stage-policy-decision.schema.json"
        ).read_text(encoding="utf-8")
    )
    document = json.loads((repository / relative_path).read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(document)) == []


def test_release_propagation_workflow_is_pr_create_compatibility_recorder() -> None:
    repository = Path(__file__).resolve().parents[1]
    workflow_root = (
        repository
        / "harness/shared_factory/04-workflows/development_delivery/release_propagation"
    )
    contract = yaml.safe_load(
        (workflow_root / "workflow.yml").read_text(encoding="utf-8")
    )
    assert contract["version"] == 5
    assert contract["inputs"][0] == "pr_create_family_receipt"
    assert contract["outputs"] == [
        "release_propagation_stage_receipt",
        "pr_create_projection",
    ]
    assert "append_exact_head_supersession" in contract["steps"]
    assert "complete_prior_and_new_pr_identity" in contract["validations"]
    assert "qualified_nonempty_pr_identifier" in contract["validations"]
    assert "local_validation_only_for_refresh" in contract["validations"]
    forbidden_steps = {
        "read_fix_version",
        "map_targets",
        "cherry_pick",
        "open_and_watch_release_prs",
    }
    assert not (forbidden_steps & set(contract["steps"]))
    assert "no_provider_or_target_mutation" in contract["validations"]

    workflow = (workflow_root / "workflow.md").read_text(encoding="utf-8")
    normalized_workflow = " ".join(workflow.split())
    assert "lower-level compatibility recorder, not an Auto-Dev stage" in (
        normalized_workflow
    )
    assert "does not resolve targets, create branches, cherry-pick code" in (
        normalized_workflow
    )

    command = (
        repository / "harness/commands/auto-dev-release-propagation.md"
    ).read_text(encoding="utf-8")
    assert "Delegate every target-resolution decision and provider action" in (
        " ".join(command.split())
    )
    skill = (
        repository / "harness/skills/auto-dev-release-propagation/SKILL.md"
    ).read_text(encoding="utf-8")
    assert "do not resolve targets, create branches, perform provider actions" in (
        " ".join(skill.split())
    )


def test_development_delivery_orders_pr_create_before_review() -> None:
    repository = Path(__file__).resolve().parents[1]
    program_root = (
        repository / "harness/shared_factory/00-programs/development_delivery"
    )
    components = yaml.safe_load(
        (program_root / "components.yml").read_text(encoding="utf-8")
    )
    workflow_ids = [workflow["id"] for workflow in components["workflows"]]
    assert "pr_create" in workflow_ids
    assert workflow_ids.index("pr_create") < workflow_ids.index(
        "testing_review_and_pr_repair"
    )

    program = (program_root / "program.md").read_text(encoding="utf-8")
    numbered_rows = [
        line
        for line in program.splitlines()
        if line.startswith("| ") and line.split("|")[1].strip().isdigit()
    ]
    numbered_workflows = [line.split("|")[2].strip(" `") for line in numbered_rows]
    assert numbered_workflows == [
        "readiness_and_context",
        "isolated_implementation",
        "pr_create",
        "testing_review_and_pr_repair",
        "merge_deployment_and_cleanup",
    ]
    assert "invoked inside the PR Create handoff" in " ".join(program.split())

    pr_create_contract = yaml.safe_load(
        (
            repository
            / "harness/shared_factory/04-workflows/development_delivery/pr_create/workflow.yml"
        ).read_text(encoding="utf-8")
    )
    assert pr_create_contract["owner"] == "auto-dev-pr-create"
    assert "record_compatibility_receipt" in pr_create_contract["steps"]
    assert pr_create_contract["compatibility_receipt_state"] == "release_propagation"
    assert "family_complete_receipt" in pr_create_contract["receipts"]


def test_review_repair_consumes_pr_create_family_without_creating_prs() -> None:
    repository = Path(__file__).resolve().parents[1]
    workflow_root = (
        repository
        / "harness/shared_factory/04-workflows/development_delivery"
        / "testing_review_and_pr_repair"
    )
    contract = yaml.safe_load(
        (workflow_root / "workflow.yml").read_text(encoding="utf-8")
    )
    assert contract["version"] == 2
    assert contract["inputs"][0] == "pr_create_family_receipt"
    assert "open_pr" not in contract["steps"]
    assert "verify_pr_create_family" in contract["steps"]
    assert "no_pr_target_mutation" in contract["validations"]

    workflow = " ".join(
        (workflow_root / "workflow.md").read_text(encoding="utf-8").split()
    )
    assert "does not open, retarget, or add pull requests" in workflow
    assert "A missing or wrong target returns to PR Create" in workflow
    assert "pr_open stores the provider readback already created by PR Create" in (
        workflow.replace("`", "")
    )

    agent_metadata = yaml.safe_load(
        (
            repository
            / "harness/skills/auto-dev-review-repair/agents/openai.yaml"
        ).read_text(encoding="utf-8")
    )
    interface = agent_metadata["interface"]
    assert "PR Create family" in interface["short_description"]
    assert "without creating or retargeting a PR" in interface["default_prompt"]

    skill_registry = yaml.safe_load(
        (repository / "harness/skills/skill-registry.yml").read_text(
            encoding="utf-8"
        )
    )
    registry_row = next(
        row
        for row in skill_registry["skills"]
        if row["id"] == "auto-dev-review-repair"
    )
    assert "without creating or retargeting pull requests" in registry_row["purpose"]

    object_contract = yaml.safe_load(
        (
            repository / "harness/skills/auto-dev-review-repair/object.yml"
        ).read_text(encoding="utf-8")
    )
    assert object_contract["dependencies"] == ["skill:root:auto-dev-pr-create"]


@pytest.mark.parametrize(
    "relative_path",
    [
        "harness/shared_factory/00-programs/auto_dev/templates/auto-dev-health-evidence.json",
        "harness/shared_factory/05-knowledge/auto_dev/examples/auto-dev-health-evidence.json",
    ],
)
def test_shipped_auto_dev_health_examples_satisfy_strict_schema(
    relative_path: str,
) -> None:
    repository = Path(__file__).resolve().parents[1]
    schema = json.loads(
        (repository / "schemas/auto-dev-health-evidence.schema.json").read_text(
            encoding="utf-8"
        )
    )
    document = json.loads((repository / relative_path).read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(document)) == []
    structured = document["evidence"]
    audited_refs = {item["ref"] for item in structured["receipt_audit"]["present"]}
    assert audited_refs <= set(structured["receipt_refs"])
    assert structured["terminal_authority"]["kind"] == "pull_request_merge"


@pytest.mark.parametrize(
    "relative_path",
    [
        "harness/shared_factory/00-programs/auto_dev/templates/auto-dev-merge-evidence.json",
        "harness/shared_factory/05-knowledge/auto_dev/examples/auto-dev-merge-evidence.json",
    ],
)
def test_shipped_auto_dev_merge_examples_include_provider_read_authority(
    relative_path: str,
) -> None:
    repository = Path(__file__).resolve().parents[1]
    document = json.loads((repository / relative_path).read_text(encoding="utf-8"))
    assert document["schema"] == "development-stage-evidence/v1"
    assert document["state"] == "merged"
    assert document["status"] == "completed"
    structured = document["evidence"]
    assert {
        "merge_sha",
        "source_head_sha",
        "provider",
        "pull_request",
        "readback_verified",
    } <= set(structured)
    assert structured["readback_verified"] is True
    for field in ("merge_sha", "source_head_sha"):
        revision = structured[field]
        assert 7 <= len(revision) <= 64
        assert all(character in "0123456789abcdefABCDEF" for character in revision)


@pytest.mark.parametrize(
    "stem",
    [
        "health-preflight",
        "runtime-cleanup",
        "resource-cleanup",
        "closed-worktree-readback",
        "reopen",
    ],
)
def test_shipped_health_intermediate_receipts_satisfy_their_schemas(stem: str) -> None:
    repository = Path(__file__).resolve().parents[1]
    schema = json.loads(
        (repository / "schemas" / f"auto-dev-{stem}.schema.json").read_text(
            encoding="utf-8"
        )
    )
    document = json.loads(
        (
            repository
            / "harness/shared_factory/00-programs/auto_dev/templates"
            / f"auto-dev-{stem}.json"
        ).read_text(encoding="utf-8")
    )
    assert list(Draft202012Validator(schema).iter_errors(document)) == []


@pytest.mark.parametrize(
    ("schema_filename", "relative_path"),
    [
        (
            "auto-dev-health-preflight.schema.json",
            "harness/shared_factory/00-programs/auto_dev/templates/auto-dev-health-preflight.json",
        ),
        (
            "auto-dev-health-preflight.schema.json",
            "harness/shared_factory/05-knowledge/auto_dev/examples/auto-dev-health-preflight.json",
        ),
        (
            "auto-dev-runtime-cleanup.schema.json",
            "harness/shared_factory/00-programs/auto_dev/templates/auto-dev-runtime-cleanup.json",
        ),
        (
            "auto-dev-runtime-cleanup.schema.json",
            "harness/shared_factory/05-knowledge/auto_dev/examples/auto-dev-runtime-cleanup.json",
        ),
        (
            "auto-dev-resource-cleanup.schema.json",
            "harness/shared_factory/00-programs/auto_dev/templates/auto-dev-resource-cleanup.json",
        ),
        (
            "auto-dev-resource-cleanup.schema.json",
            "harness/shared_factory/05-knowledge/auto_dev/examples/auto-dev-resource-cleanup.json",
        ),
        (
            "auto-dev-closed-worktree-readback.schema.json",
            "harness/shared_factory/00-programs/auto_dev/templates/auto-dev-closed-worktree-readback.json",
        ),
        (
            "auto-dev-closed-worktree-readback.schema.json",
            "harness/shared_factory/05-knowledge/auto_dev/examples/auto-dev-closed-worktree-readback.json",
        ),
        (
            "auto-dev-reopen.schema.json",
            "harness/shared_factory/00-programs/auto_dev/templates/auto-dev-reopen.json",
        ),
        (
            "auto-dev-reopen.schema.json",
            "harness/shared_factory/05-knowledge/auto_dev/examples/auto-dev-reopen.json",
        ),
    ],
)
def test_shipped_auto_dev_health_intermediate_receipts_satisfy_strict_schemas(
    schema_filename: str,
    relative_path: str,
) -> None:
    repository = Path(__file__).resolve().parents[1]
    schema = json.loads(
        (repository / "schemas" / schema_filename).read_text(encoding="utf-8")
    )
    document = json.loads((repository / relative_path).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert list(Draft202012Validator(schema).iter_errors(document)) == []


@pytest.mark.parametrize(
    "relative_directory",
    [
        "harness/shared_factory/00-programs/auto_dev/templates",
        "harness/shared_factory/05-knowledge/auto_dev/examples",
    ],
)
def test_shipped_auto_dev_health_intermediate_receipt_bundle_is_consistent(
    relative_directory: str,
) -> None:
    repository = Path(__file__).resolve().parents[1]
    directory = repository / relative_directory
    preflight_path = directory / "auto-dev-health-preflight.json"
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    runtime = json.loads(
        (directory / "auto-dev-runtime-cleanup.json").read_text(encoding="utf-8")
    )
    resource = json.loads(
        (directory / "auto-dev-resource-cleanup.json").read_text(encoding="utf-8")
    )
    closed = json.loads(
        (directory / "auto-dev-closed-worktree-readback.json").read_text(
            encoding="utf-8"
        )
    )

    identifiers = {
        (document["work_item_id"], document["canonical_work_id"])
        for document in (preflight, runtime, resource, closed)
    }
    assert len(identifiers) == 1
    assert runtime["preflight_sha256"] == hashlib.sha256(
        preflight_path.read_bytes()
    ).hexdigest()
    assert preflight["source_head_sha"] == preflight["subject_revision"]
    assert preflight["merge_sha"] == preflight["terminal_revision"]
    assert runtime["runtime_identity"] == preflight["runtime"]["identity"]
    assert resource["runtime"]["identity"] == runtime["runtime_identity"]
    assert resource["runtime"]["result"] == runtime["result"]
    assert resource["worktree"]["identity"] == preflight["worktree"]["identity"]
    assert resource["worktree"]["path"] == preflight["worktree"]["path"]
    assert resource["preflight_ref"] == "artifacts/auto-dev-health/preflight.json"
    if "entry" in closed:
        assert closed["entry"]["id"] == preflight["worktree"]["identity"]
        assert closed["entry"]["path"] == preflight["worktree"]["path"]
        assert closed["entry"]["terminal_revision"] == preflight["terminal_revision"]
        assert closed["entry"]["health_preflight_ref"] == resource["preflight_ref"]
    else:
        assert closed["result"] == "not_managed"
        assert resource["worktree"]["result"] == "not_managed"


def test_health_relocation_semantic_hash_exempts_only_named_control_paths() -> None:
    autodev = {
        "updated_at": "2026-07-20T20:00:00Z",
        "delivery": {"work_item": "/packet/02-active/item", "state": "delivery_complete"},
        "compatibility": {"legacy_state_ref": None, "migration_mode": "not_present"},
        "source": {"system": "tracker", "key": "CC-54"},
        "stages": {"qa": {"receipt_refs": ["receipt:qa"]}},
    }
    autodev_digest = auto_dev._packet_relocation_semantic_sha256(
        "autodev.json", autodev
    )
    relocated_autodev = json.loads(json.dumps(autodev))
    relocated_autodev["updated_at"] = "2026-07-20T21:00:00Z"
    relocated_autodev["delivery"]["work_item"] = "/packet/03-complete/item"
    relocated_autodev["compatibility"]["legacy_state_ref"] = (
        "/packet/03-complete/item/artifacts/auto-dev/state.json"
    )
    assert (
        auto_dev._packet_relocation_semantic_sha256(
            "autodev.json", relocated_autodev
        )
        == autodev_digest
    )
    for field, value in (
        ("source", {"system": "tracker", "key": "CC-999"}),
        ("stages", {"qa": {"receipt_refs": ["receipt:unauthorized"]}}),
    ):
        tampered = json.loads(json.dumps(relocated_autodev))
        tampered[field] = value
        assert (
            auto_dev._packet_relocation_semantic_sha256("autodev.json", tampered)
            != autodev_digest
        )

    work = {
        "status": "validating",
        "lane": "02-active",
        "format": "folder",
        "updated_at": "2026-07-20T20:00:00Z",
        "lifecycle": {"state": "validating", "owner": "agent"},
        "source": {"system": "tracker", "key": "CC-54"},
        "receipts": ["receipt:qa"],
        "summary": "Delivery is ready for Health.",
        "history": [{"state": "validating", "receipt": "receipt:qa"}],
    }
    work_digest = auto_dev._packet_relocation_semantic_sha256("work.yml", work)
    relocated_work = yaml.safe_load(yaml.safe_dump(work)) or {}
    relocated_work.update(
        {
            "state": "finished",
            "status": "finished",
            "lane": "03-complete",
            "format": "folder",
            "updated_at": "2026-07-20T21:00:00Z",
        }
    )
    relocated_work["lifecycle"]["state"] = "finished"
    assert (
        auto_dev._packet_relocation_semantic_sha256("work.yml", relocated_work)
        == work_digest
    )
    for field, value in (
        ("source", {"system": "tracker", "key": "CC-999"}),
        ("receipts", ["receipt:qa", "receipt:unauthorized"]),
        ("summary", "Unauthorized replacement summary."),
        ("history", [{"state": "finished", "receipt": "receipt:unauthorized"}]),
    ):
        tampered = yaml.safe_load(yaml.safe_dump(relocated_work)) or {}
        tampered[field] = value
        assert (
            auto_dev._packet_relocation_semantic_sha256("work.yml", tampered)
            != work_digest
        )


def test_auto_dev_health_audits_then_relinks_finished_packet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    project = _project(root, repo)
    profile_path = project / "config" / "development.yml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    safe_order = list(AUTO_DEV_STAGE_ORDER)
    safe_order[1], safe_order[2] = safe_order[2], safe_order[1]
    profile["auto_dev"] = {
        "stage_order": safe_order,
        "everything": {
            "start_stage": "readiness",
            "completion_stage": "health",
        },
    }
    profile_path.write_text(
        yaml.safe_dump(profile, sort_keys=False), encoding="utf-8"
    )
    missing_worktree = project / "worktrees" / "cc-54"
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": "cc-54",
            "path": str(missing_worktree),
            "branch": "feature/cc-54",
            "base_sha": base_sha,
        },
    )
    run = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-54"],
        run_id="health-finished-packet",
        touched_paths=["src/rules_engine.py"],
        subjects=["rulebook"],
        auto_dev_mode="everything",
        goal="delivery_complete",
        apply=True,
    )
    task_path = Path(run["tasks"][0]["state_ref"])
    task = TaskState(task_path)
    original_context_selection = task.read()["context_selection"]
    work_item = Path(task.read()["work_item"])
    reviewed_head = "a" * 40
    pull_request = "github:acme/app#54"
    _advance_auto_dev_task_to_ready(
        task,
        subject_revision=reviewed_head,
        pull_request=pull_request,
    )
    readiness = _complete_pre_merge_auto_dev(
        task,
        subject_revision=reviewed_head,
        pull_request=pull_request,
    )
    run_development_stage(
        task_path,
        stage="merge",
        receipts={
            "merged": _stage_receipt(
                work_item / "artifacts" / "delivery",
                "merged",
                status="completed",
                evidence={
                    "merge_sha": base_sha,
                    "source_head_sha": reviewed_head,
                    **_provider_authority(task, pull_request=pull_request),
                    "readiness_authority": readiness,
                },
            )
        },
        idempotency_prefix="cc-54:merge",
    )
    _record_standalone_stage(task, "release", revision=base_sha)
    run_development_stage(
        task_path,
        stage="deploy",
        receipts={
            "deployment_pending": _stage_receipt(tmp_path, "deployment_pending"),
            "deploying": _stage_receipt(
                work_item / "artifacts" / "delivery", "deploying"
            ),
            "post_deploy_validation": _stage_receipt(
                work_item / "artifacts" / "delivery",
                "post_deploy_validation",
                evidence={
                    "deployed_revision": base_sha,
                    "artifact_ref": "registry.example/app@sha256:cc54",
                    "environment": "test",
                    "readback_verified": True,
                },
            ),
        },
        idempotency_prefix="cc-54:deploy",
    )
    run_development_stage(
        task_path,
        stage="closeout",
        receipts={
            "delivery_complete": _stage_receipt(
                work_item / "artifacts" / "delivery",
                "delivery_complete",
                evidence={"closeout_verified": True, "receipt_refs": ["tracker:CC-54"]},
            )
        },
        idempotency_prefix="cc-54:closeout",
    )
    before_health = read_auto_dev_state(work_item / "autodev.json")
    canonical_work_id = "acme:app:cc-54"
    assert task.read()["canonical_work_id"] == canonical_work_id
    assert before_health["canonical_work_id"] == canonical_work_id
    assert before_health["subject_revision"] == reviewed_head
    assert before_health["terminal_revision"] == base_sha
    assert before_health["current_stage"] == "health"

    # Exercise the status-only metadata shape used by older work.yml packets.
    active_work = yaml.safe_load((work_item / "work.yml").read_text(encoding="utf-8")) or {}
    active_work.pop("state", None)
    active_work["status"] = "validating"
    active_work["source"] = {"system": "tracker", "key": "CC-54"}
    active_work["receipts"] = ["tracker:CC-54"]
    active_work["summary"] = "Delivery is ready for its final Health audit."
    active_work["history"] = [{"state": "validating", "receipt": "tracker:CC-54"}]
    (work_item / "work.yml").write_text(
        yaml.safe_dump(active_work, sort_keys=False), encoding="utf-8"
    )

    dry_run = prepare_auto_dev_health(work_item / "autodev.json", apply=False)
    assert dry_run["writes"] == []
    assert dry_run["preflight"]["schema"] == "auto-dev-health-plan/v1"
    assert dry_run["preflight"]["mode"] == "dry-run"
    assert dry_run["preflight"]["safe_to_cleanup"] is True
    assert dry_run["preflight"]["repository"] == {
        "id": "github:acme/app",
        "base_branch": "main",
    }
    assert not (work_item / "artifacts" / "auto-dev-health" / "preflight.json").exists()

    qa_receipt = work_item / before_health["stages"]["qa"]["receipt_refs"][0]
    qa_bytes = qa_receipt.read_bytes()
    projection_path = work_item / "autodev.json"
    configured_projection_bytes = projection_path.read_bytes()
    legacy_target_only = json.loads(configured_projection_bytes)
    legacy_target_only.update(
        {
            "mode": "single_stage",
            "requested_stage": "health",
            "start_stage": "health",
            "completion_stage": "health",
        }
    )
    projection_path.write_text(
        json.dumps(legacy_target_only, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    qa_receipt.unlink()
    with pytest.raises(AutoDevStateError, match="every earlier stage"):
        prepare_auto_dev_health(work_item / "autodev.json", apply=True)
    assert not (work_item / "artifacts" / "auto-dev-health" / "preflight.json").exists()
    qa_receipt.write_bytes(qa_bytes)
    projection_path.write_bytes(configured_projection_bytes)

    statuses_before_health = {
        stage: {
            "status": before_health["stages"][stage]["status"],
            "receipt_refs": before_health["stages"][stage]["receipt_refs"],
        }
        for stage in AUTO_DEV_STAGE_ORDER
        if stage != "health"
    }
    assert main(
        [
            "auto-dev",
            "health",
            "--state",
            str(work_item / "autodev.json"),
            "--root",
            str(root),
            "--apply",
            "--json",
        ]
    ) == 0
    prepared = json.loads(capsys.readouterr().out)
    projected_after_health_launch = read_auto_dev_state(work_item / "autodev.json")
    for stage, expected in statuses_before_health.items():
        assert projected_after_health_launch["stages"][stage]["status"] == expected["status"]
        assert (
            projected_after_health_launch["stages"][stage]["receipt_refs"]
            == expected["receipt_refs"]
        )
    preflight_path = Path(prepared["preflight_ref"])
    resume_text = (
        work_item / "artifacts" / "auto-dev-health" / "RESUME.md"
    ).read_text(encoding="utf-8")
    for required_resume_text in (
        "Source ticket:",
        "Tracker receipt:",
        "Pull-request receipt:",
        "Merge receipt:",
        "QA receipt:",
        "Release receipt:",
        "Deployment receipt:",
        "Closeout receipt:",
        "Final decision:",
        "Known follow-ups:",
        "Residual risk:",
        "Why cleanup is safe:",
        "Exact worktree:",
        "Exact runtime:",
        "Cleanup plan:",
        "Reopen command:",
        "Receipt audit:",
    ):
        assert required_resume_text in resume_text
    preflight_schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "schemas/auto-dev-health-preflight.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert list(
        Draft202012Validator(preflight_schema).iter_errors(
            json.loads(preflight_path.read_text(encoding="utf-8"))
        )
    ) == []
    preflight_ref = preflight_path.relative_to(work_item).as_posix()
    prepared_payload = json.loads(preflight_path.read_text(encoding="utf-8"))
    audit_stages = [
        row["stage"]
        for row in json.loads(
            (
                work_item
                / prepared_payload["receipt_audit"]["ref"]
            ).read_text(encoding="utf-8")
        )["stages"]
    ]
    assert audit_stages == [
        stage
        for stage in safe_order[safe_order.index("readiness") :]
        if stage != "health"
    ]
    packet_manifest = work_item / prepared_payload["packet_manifest"]["ref"]
    packet_manifest_bytes = packet_manifest.read_bytes()
    packet_manifest_payload = json.loads(packet_manifest_bytes)
    manifest_controls = {
        row["ref"]: row
        for row in packet_manifest_payload["files"]
        if row["ref"] in {"autodev.json", "work.yml"}
    }
    assert set(manifest_controls) == {"autodev.json", "work.yml"}
    assert all(
        len(row["relocation_semantic_sha256"]) == 64
        for row in manifest_controls.values()
    )
    packet_manifest.unlink()
    with pytest.raises(AutoDevStateError, match="packet_manifest"):
        prepare_auto_dev_health(work_item / "autodev.json", apply=True)
    packet_manifest.write_bytes(packet_manifest_bytes)
    packet_manifest.write_bytes(packet_manifest_bytes + b"\n")
    with pytest.raises(AutoDevStateError, match="packet_manifest hash"):
        prepare_auto_dev_health(work_item / "autodev.json", apply=True)
    packet_manifest.write_bytes(packet_manifest_bytes)
    summary_bytes = (work_item / "SUMMARY.md").read_bytes()
    (work_item / "SUMMARY.md").write_text("# Summary\n\nTampered after audit.\n", encoding="utf-8")
    with pytest.raises(AutoDevStateError, match="packet file changed after audit: SUMMARY.md"):
        prepare_auto_dev_health(work_item / "autodev.json", apply=True)
    (work_item / "SUMMARY.md").write_bytes(summary_bytes)
    runtime_receipt = (
        work_item
        / "artifacts"
        / "auto-dev-health"
        / "receipts"
        / "runtime-cleanup.json"
    )
    teardown_operation = runtime_receipt.with_name("runtime-teardown-operation.txt")
    readback_operation = runtime_receipt.with_name("runtime-readback-operation.txt")
    teardown_operation.write_text("No managed runtime teardown was required.\n", encoding="utf-8")
    readback_operation.write_text("Runtime remains explicitly not managed.\n", encoding="utf-8")

    def operation_descriptor(path: Path) -> dict[str, str]:
        return {
            "command": "not_managed",
            "ref": path.relative_to(work_item).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    runtime_receipt.write_text(
        json.dumps(
            {
                "schema": "auto-dev-runtime-cleanup/v1",
                "work_item_id": work_item.name,
                "canonical_work_id": canonical_work_id,
                "runtime_identity": "not-managed",
                "ownership": "not_managed",
                "provider": "none",
                "teardown": operation_descriptor(teardown_operation),
                "readback": operation_descriptor(readback_operation),
                "result": "not_managed",
                "readback_verified": True,
                "preflight_sha256": hashlib.sha256(preflight_path.read_bytes()).hexdigest(),
                "verified_at": datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
            }
        ),
        encoding="utf-8",
    )
    runtime_schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "schemas/auto-dev-runtime-cleanup.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert list(
        Draft202012Validator(runtime_schema).iter_errors(
            json.loads(runtime_receipt.read_text(encoding="utf-8"))
        )
    ) == []

    worklog_bytes = (work_item / "WORKLOG.md").read_bytes()
    next_bytes = (work_item / "NEXT.md").read_bytes()
    assert main(
        [
            "project",
            "work-item",
            "set",
            "acme",
            "app",
            work_item.name,
            "--state",
            "finished",
            "--health-relocation",
            "--note",
            "Auto-Dev Health audit passed",
            "--root",
            str(root),
        ]
    ) == 0
    relocation_output = yaml.safe_load(capsys.readouterr().out)
    assert relocation_output["state"] == "finished"
    assert relocation_output["health_relocation"] is True
    finished = Path(relocation_output["path"])
    assert finished == work_item
    assert finished.parent == project / "work-items"
    assert (finished / "WORKLOG.md").read_bytes() == worklog_bytes
    assert (finished / "NEXT.md").read_bytes() == next_bytes
    finished_work = yaml.safe_load((finished / "work.yml").read_text(encoding="utf-8")) or {}
    assert finished_work["status"] == "finished"
    assert "state" not in finished_work
    if isinstance(finished_work.get("lifecycle"), dict) and "state" in finished_work["lifecycle"]:
        assert finished_work["lifecycle"]["state"] == "finished"
    relocation_preflight = json.loads(
        (finished / preflight_ref).read_text(encoding="utf-8")
    )
    relocated_autodev = read_auto_dev_state(finished / "autodev.json")
    relocated_autodev["updated_at"] = "2026-07-20T20:53:00Z"
    relocated_autodev["delivery"]["work_item"] = str(finished)
    (finished / "autodev.json").write_text(
        json.dumps(relocated_autodev, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    validate_auto_dev_packet_manifest(
        relocation_preflight,
        finished,
        current=relocated_autodev,
        verify_live_files=False,
    )

    # The two relocation-mutable controls are not blanket exemptions.  Their
    # semantic hashes reject changes to source, receipt, summary, and history
    # content even when the files remain valid JSON/YAML.
    relocated_autodev_bytes = (finished / "autodev.json").read_bytes()
    tampered_autodev = json.loads(relocated_autodev_bytes)
    tampered_autodev["source"]["key"] = "CC-999"
    (finished / "autodev.json").write_text(
        json.dumps(tampered_autodev, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        AutoDevStateError,
        match="packet control changed outside relocation fields: autodev.json",
    ):
        validate_auto_dev_packet_manifest(
            relocation_preflight,
            finished,
            current=relocated_autodev,
            verify_live_files=False,
        )
    (finished / "autodev.json").write_bytes(relocated_autodev_bytes)

    tampered_autodev = json.loads(relocated_autodev_bytes)
    tampered_autodev["stages"]["qa"]["receipt_refs"].append("receipt:unauthorized")
    (finished / "autodev.json").write_text(
        json.dumps(tampered_autodev, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        AutoDevStateError,
        match="packet control changed outside relocation fields: autodev.json",
    ):
        validate_auto_dev_packet_manifest(
            relocation_preflight,
            finished,
            current=relocated_autodev,
            verify_live_files=False,
        )
    (finished / "autodev.json").write_bytes(relocated_autodev_bytes)

    tampered_autodev = json.loads(relocated_autodev_bytes)
    tampered_autodev["delivery"]["work_item"] = str(finished.parent / "other-item")
    (finished / "autodev.json").write_text(
        json.dumps(tampered_autodev, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(AutoDevStateError, match="unexpected delivery.work_item path"):
        validate_auto_dev_packet_manifest(
            relocation_preflight,
            finished,
            current=relocated_autodev,
            verify_live_files=False,
        )
    (finished / "autodev.json").write_bytes(relocated_autodev_bytes)

    relocated_work_bytes = (finished / "work.yml").read_bytes()
    for field, unauthorized_value in (
        ("source", {"system": "tracker", "key": "CC-999"}),
        ("receipts", ["tracker:CC-54", "receipt:unauthorized"]),
        ("summary", "Unauthorized replacement summary."),
        ("history", [{"state": "finished", "receipt": "receipt:unauthorized"}]),
    ):
        tampered_work = yaml.safe_load(relocated_work_bytes) or {}
        tampered_work[field] = unauthorized_value
        (finished / "work.yml").write_text(
            yaml.safe_dump(tampered_work, sort_keys=False), encoding="utf-8"
        )
        with pytest.raises(
            AutoDevStateError,
            match="packet control changed outside relocation fields: work.yml",
        ):
            validate_auto_dev_packet_manifest(
                relocation_preflight,
                finished,
                current=relocated_autodev,
                verify_live_files=False,
            )
        (finished / "work.yml").write_bytes(relocated_work_bytes)

    tampered_work = yaml.safe_load(relocated_work_bytes) or {}
    tampered_work["status"] = "archived"
    (finished / "work.yml").write_text(
        yaml.safe_dump(tampered_work, sort_keys=False), encoding="utf-8"
    )
    with pytest.raises(
        AutoDevStateError,
        match="must record finished in every state field",
    ):
        validate_auto_dev_packet_manifest(
            relocation_preflight,
            finished,
            current=relocated_autodev,
            verify_live_files=False,
        )
    (finished / "work.yml").write_bytes(relocated_work_bytes)

    finished_summary = finished / "SUMMARY.md"
    finished_summary_bytes = finished_summary.read_bytes()
    finished_summary.write_text("# Summary\n\nUnauthorized finished-packet mutation.\n", encoding="utf-8")
    with pytest.raises(AutoDevStateError, match="packet file changed after audit: SUMMARY.md"):
        validate_auto_dev_packet_manifest(
            relocation_preflight,
            finished,
            current=relocated_autodev,
            verify_live_files=False,
        )
    finished_summary.write_bytes(finished_summary_bytes)
    receipt_root = finished / "artifacts" / "auto-dev-health" / "receipts"
    preflight_path = finished / preflight_ref
    runtime_receipt = receipt_root / "runtime-cleanup.json"
    authority_receipt = receipt_root / "terminal-authority.json"
    closeout_receipt = receipt_root / "closeout.json"
    audit_receipt = receipt_root / "pre-cleanup-receipt-audit.json"
    resume_receipt = finished / "artifacts" / "auto-dev-health" / "RESUME.md"
    resource_receipt = receipt_root / "resource-cleanup.json"
    work_state_receipt = receipt_root / "work-state.json"
    active_index_receipt = receipt_root / "active-index.json"
    validation_receipt = receipt_root / "validation.json"
    registry_receipt = receipt_root / "closed-worktree-readback.json"
    resource_receipt.write_text(
        json.dumps(
            {
                "schema": "auto-dev-resource-cleanup/v1",
                "work_item_id": finished.name,
                "canonical_work_id": canonical_work_id,
                "preflight_ref": preflight_ref,
                "runtime_cleanup": {
                    "ref": runtime_receipt.relative_to(finished).as_posix(),
                    "sha256": hashlib.sha256(runtime_receipt.read_bytes()).hexdigest(),
                },
                "worktree": {
                    "identity": "cc-54",
                    "path": str(missing_worktree),
                    "result": "absent",
                    "readback_verified": True,
                },
                "runtime": {
                    "identity": "not-managed",
                    "ownership": "not_managed",
                    "provider": "none",
                    "result": "not_managed",
                    "readback_verified": True,
                },
                "verified_at": "2026-07-20T20:54:00Z",
            }
        ),
        encoding="utf-8",
    )
    resource_schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "schemas/auto-dev-resource-cleanup.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert list(
        Draft202012Validator(resource_schema).iter_errors(
            json.loads(resource_receipt.read_text(encoding="utf-8"))
        )
    ) == []
    work_state_receipt.write_text(
        json.dumps({"state": "finished", "packet": str(finished)}), encoding="utf-8"
    )
    active_index_receipt.write_text(
        json.dumps({"canonical_work_id": canonical_work_id, "active": False}),
        encoding="utf-8",
    )
    validation_receipt.write_text(
        json.dumps({"command": "agentic-os validate", "passed": True}),
        encoding="utf-8",
    )

    closed_entry = {
        "id": "cc-54",
        "path": str(missing_worktree),
        "status": "closed",
        "terminal_revision": base_sha,
        "health_preflight_ref": preflight_ref,
    }
    registry_receipt.write_text(
        json.dumps(
            {
                "schema": "auto-dev-closed-worktree-readback/v1",
                "work_item_id": finished.name,
                "canonical_work_id": canonical_work_id,
                "entry": closed_entry,
                "captured_at": "2026-07-20T20:56:00Z",
            }
        ),
        encoding="utf-8",
    )
    (project / "worktrees").mkdir(exist_ok=True)
    (project / "worktrees" / "closed.yml").write_text(
        yaml.safe_dump(
            {
                "project": "app",
                "worktrees": [closed_entry],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    connection = connect_state(default_db_path(root))
    try:
        canonical_work_items.update(
            connection,
            canonical_work_id,
            state="finished",
            attention="closed",
            packet_path=str(finished),
            clear_worktree=True,
            receipt_ref=work_state_receipt.relative_to(finished).as_posix(),
            verified=True,
            now="2026-07-20T20:57:00Z",
        )
        canonical_work_items.write_active_projection(connection, root)
    finally:
        connection.close()
    sync_active_container(root)

    receipt_paths = {
        "terminal_authority": authority_receipt,
        "closeout": closeout_receipt,
        "receipt_audit": audit_receipt,
        "resume_manifest": resume_receipt,
        "packet_manifest": receipt_root / "packet-manifest.json",
        "resource_cleanup": resource_receipt,
        "runtime_cleanup": runtime_receipt,
        "work_state": work_state_receipt,
        "active_index": active_index_receipt,
        "validation": validation_receipt,
    }
    receipt_rows = [
        {
            "kind": kind,
            "ref": path.relative_to(finished).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for kind, path in receipt_paths.items()
    ]
    receipt_rows.append(
        {
            "kind": "resource_cleanup",
            "ref": registry_receipt.relative_to(finished).as_posix(),
            "sha256": hashlib.sha256(registry_receipt.read_bytes()).hexdigest(),
        }
    )
    resource_ref = resource_receipt.relative_to(finished).as_posix()
    work_state_ref = work_state_receipt.relative_to(finished).as_posix()
    active_index_ref = active_index_receipt.relative_to(finished).as_posix()
    validation_ref = validation_receipt.relative_to(finished).as_posix()
    evidence = finished / "artifacts" / "auto-dev-health" / "evidence.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(
            {
                "schema": AUTO_DEV_HEALTH_EVIDENCE_SCHEMA,
                "work_item_id": finished.name,
                "stage": "health",
                "status": "completed",
                "summary": "Audited receipts, removed reconstructable resources, and finished the packet.",
                "subject_revision": reviewed_head,
                "terminal_revision": base_sha,
                "evidence": {
                    "preflight_ref": preflight_ref,
                    "receipt_refs": [preflight_ref, *[row["ref"] for row in receipt_rows]],
                    "terminal_authority": {
                        "kind": "pull_request_merge",
                        "provider": "github",
                        "ref": "github:acme/app#54",
                        "revision": base_sha,
                        "verified_at": "2026-07-20T20:55:00Z",
                    },
                    "receipt_audit": {
                        "required": list(receipt_paths),
                        "present": receipt_rows,
                        "missing": [],
                        "resume_ready": True,
                    },
                    "resources": {
                        "worktree": {
                            "preflight": "clean, merged, no REOPEN.md",
                            "action": "none required; already absent",
                            "result": "absent",
                            "identity": "cc-54",
                            "receipt": resource_ref,
                        },
                        "runtime": {
                            "identity": "not-managed",
                            "preflight": "no shared LOS resources",
                            "action": "none required",
                            "result": "not_managed",
                            "receipt": resource_ref,
                        },
                    },
                    "work_state": {
                        "canonical_work_id": canonical_work_id,
                        "before": "validating",
                        "before_attention": "active",
                        "after": "finished",
                        "history_receipt": work_state_ref,
                        "packet_old_path": str(work_item),
                        "packet_new_path": str(finished),
                    },
                    "closed_worktree_registry_ref": registry_receipt.relative_to(finished).as_posix(),
                    "active_index_refs": [active_index_ref],
                    "validation_results": [
                        {
                            "command": "agentic-os validate --strict",
                            "result": "passed",
                            "ref": validation_ref,
                        }
                    ],
                    "residual_holds": [],
                },
                "verified_at": "2026-07-20T21:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    health_schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "schemas/auto-dev-health-evidence.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert list(
        Draft202012Validator(health_schema).iter_errors(
            json.loads(evidence.read_text(encoding="utf-8"))
        )
    ) == []
    preflight_payload = json.loads(preflight_path.read_text(encoding="utf-8"))
    preflight_bytes = preflight_path.read_bytes()
    relocated_work = yaml.safe_load((finished / "work.yml").read_text(encoding="utf-8")) or {}
    relocated_work["state"] = "finished"
    relocated_work["status"] = "finished"
    if isinstance(relocated_work.get("lifecycle"), dict):
        relocated_work["lifecycle"]["state"] = "finished"
    (finished / "work.yml").write_text(
        yaml.safe_dump(relocated_work, sort_keys=False), encoding="utf-8"
    )
    precleanup_audit = json.loads(audit_receipt.read_text(encoding="utf-8"))
    qa_snapshot_row = next(
        row for row in precleanup_audit["stages"] if row["stage"] == "qa"
    )
    qa_snapshot = finished / qa_snapshot_row["ref"]
    qa_snapshot_bytes = qa_snapshot.read_bytes()
    qa_snapshot.unlink()
    with pytest.raises(AutoDevStateError, match="stage snapshot"):
        record_auto_dev_stage(
            finished / "autodev.json",
            stage="health",
            evidence_file=evidence,
            idempotency_key="cc-54:health",
        )
    qa_snapshot.write_bytes(qa_snapshot_bytes)
    result = record_auto_dev_stage(
        finished / "autodev.json",
        stage="health",
        evidence_file=evidence,
        idempotency_key="cc-54:health",
    )
    after = task.read()
    assert Path(after["work_item"]) == finished
    assert Path(after["autodev_path"]) == finished / "autodev.json"
    assert result["state"]["stages"]["health"]["status"] == "completed"
    assert result["state"]["status"] == "completed"
    assert result["state"]["current_stage"] is None
    assert result["state"]["subject_revision"] == reviewed_head
    assert result["state"]["terminal_revision"] == base_sha
    for stage_name in ("qa", "finalize", "release"):
        assert result["state"]["stages"][stage_name]["status"] == "completed"
    assert result["state"]["stages"]["review_others"]["status"] == "not_required"
    completed_projection_path = finished / "autodev.json"
    completed_projection_bytes = completed_projection_path.read_bytes()
    completed_projection = json.loads(completed_projection_bytes)
    health_ref = completed_projection["stages"]["health"]["receipt_refs"][0]
    health_wrapper = finished / health_ref
    health_wrapper_bytes = health_wrapper.read_bytes()

    copied_wrapper = health_wrapper.with_name("copied-health-wrapper.json")
    copied_wrapper.write_bytes(health_wrapper_bytes)
    copied_ref = copied_wrapper.relative_to(finished).as_posix()
    copied_projection = json.loads(completed_projection_bytes)
    copied_projection["stages"]["health"]["run_ref"] = copied_ref
    copied_projection["stages"]["health"]["receipt_refs"] = [copied_ref]
    completed_projection_path.write_text(
        json.dumps(copied_projection, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(AutoDevStateError, match="canonical evidence path"):
        auto_dev.validate_recorded_auto_dev_health(completed_projection_path)
    completed_projection_path.write_bytes(completed_projection_bytes)
    copied_wrapper.unlink()

    mismatched_wrapper = json.loads(health_wrapper_bytes)
    mismatched_wrapper["receipt_ref"] = health_wrapper.with_name("latest.json").relative_to(
        finished
    ).as_posix()
    health_wrapper.write_text(
        json.dumps(mismatched_wrapper, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(AutoDevStateError, match="receipt_ref does not bind"):
        auto_dev.validate_recorded_auto_dev_health(completed_projection_path)
    health_wrapper.write_bytes(health_wrapper_bytes)

    for required_history_field in ("recorded_at", "idempotency_key"):
        incomplete_wrapper = json.loads(health_wrapper_bytes)
        incomplete_wrapper[required_history_field] = ""
        health_wrapper.write_text(
            json.dumps(incomplete_wrapper, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        with pytest.raises(
            AutoDevStateError,
            match="requires idempotency_key and recorded_at",
        ):
            auto_dev.validate_recorded_auto_dev_health(completed_projection_path)
        health_wrapper.write_bytes(health_wrapper_bytes)

    mismatched_projection = json.loads(completed_projection_bytes)
    mismatched_projection["stages"]["health"]["last_verified_at"] = (
        "2026-07-20T23:59:59Z"
    )
    completed_projection_path.write_text(
        json.dumps(mismatched_projection, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(AutoDevStateError, match="last_verified_at does not match"):
        auto_dev.validate_recorded_auto_dev_health(completed_projection_path)
    completed_projection_path.write_bytes(completed_projection_bytes)

    # Canonical single-root lifecycle transitions do not rewrite the delivery
    # task merely to change filesystem lanes.
    assert hashlib.sha256(task_path.read_bytes()).hexdigest() == preflight_payload[
        "task_state_sha256"
    ]
    task_snapshot = finished / preflight_payload["task_snapshot"]["ref"]
    assert hashlib.sha256(task_snapshot.read_bytes()).hexdigest() == preflight_payload[
        "task_snapshot"
    ]["sha256"]
    assert preflight_path.read_bytes() == preflight_bytes

    finished_hashes = {
        path.relative_to(finished).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in finished.rglob("*")
        if path.is_file()
    }
    connection = connect_state(default_db_path(root))
    try:
        with pytest.raises(
            canonical_work_items.WorkItemError,
            match="cannot be reactivated directly",
        ):
            canonical_work_items.update(
                connection,
                canonical_work_id,
                state="building",
                attention="active",
                context_summary="Unsafe manual reopen attempt.",
                clear_worktree=True,
                receipt_ref="test:unsafe-manual-reopen",
                verified=True,
            )
    finally:
        connection.close()
    with pytest.raises(DevelopmentDeliveryError, match="immutable finished packet"):
        delivery.start_development_run(
            root,
            "acme",
            "app",
            ["CC-54"],
            run_id="unsafe-manual-reopen",
            auto_dev_mode="single_stage",
            requested_stage="qa",
            goal="qa",
            apply=True,
        )
    assert not (project / "state" / "development-runs" / "unsafe-manual-reopen").exists()
    connection = connect_state(default_db_path(root))
    try:
        canonical_work_items.update(
            connection,
            canonical_work_id,
            state="finished",
            attention="closed",
            packet_path=str(finished),
            clear_worktree=True,
            receipt_ref=work_state_receipt.relative_to(finished).as_posix(),
            verified=True,
            # A same-state verification refreshes mutable freshness without
            # rewriting the immutable terminal transition history.
            now="2026-07-20T21:05:00Z",
        )
        canonical_after_reverification = canonical_work_items.get(
            connection, canonical_work_id
        )
        terminal_history = connection.execute(
            """
            SELECT changed_at, receipt_ref
            FROM work_item_history
            WHERE work_item_id = ? AND to_state = 'finished' AND to_attention = 'closed'
            ORDER BY id DESC
            LIMIT 1
            """,
            (canonical_work_id,),
        ).fetchone()
        assert canonical_after_reverification is not None
        assert (
            canonical_after_reverification["last_verified_at"]
            == "2026-07-20T21:05:00Z"
        )
        assert terminal_history is not None
        assert terminal_history["changed_at"] == "2026-07-20T20:57:00Z"
        assert terminal_history["receipt_ref"] == work_state_receipt.relative_to(
            finished
        ).as_posix()

        # Freshness may advance independently, but terminal history must remain
        # bound to the exact packet-local receipt audited by Health.
        auto_dev.validate_recorded_auto_dev_health(completed_projection_path)
        connection.execute(
            """
            UPDATE work_item_history
            SET receipt_ref = 'artifacts/auto-dev-health/receipts/wrong-work-state.json'
            WHERE id = (
                SELECT id
                FROM work_item_history
                WHERE work_item_id = ? AND to_state = 'finished' AND to_attention = 'closed'
                ORDER BY id DESC
                LIMIT 1
            )
            """,
            (canonical_work_id,),
        )
        connection.commit()
        with pytest.raises(
            AutoDevStateError,
            match="final finished/closed history row",
        ):
            auto_dev.validate_recorded_auto_dev_health(completed_projection_path)
        connection.execute(
            """
            UPDATE work_item_history
            SET receipt_ref = ?
            WHERE id = (
                SELECT id
                FROM work_item_history
                WHERE work_item_id = ? AND to_state = 'finished' AND to_attention = 'closed'
                ORDER BY id DESC
                LIMIT 1
            )
            """,
            (work_state_receipt.relative_to(finished).as_posix(), canonical_work_id),
        )
        connection.commit()
    finally:
        connection.close()

    fresh_worktree = project / "worktrees" / "cc-54-qa-reopen"
    reopen_provision_attempts = {"count": 0}

    def provision_reopened_worktree(**kwargs: object) -> dict[str, str]:
        reopen_provision_attempts["count"] += 1
        if reopen_provision_attempts["count"] == 1:
            raise DevelopmentDeliveryError("synthetic retryable reopen provisioning failure")
        return {
            "name": "cc-54-qa-reopen",
            "path": str(fresh_worktree),
            "branch": "feature/cc-54-qa-reopen",
            "base_sha": base_sha,
        }

    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        provision_reopened_worktree,
    )
    assert main(
        [
            "auto-dev",
            "reopen",
            "--state",
            str(finished),
            "--run-id",
            "cc-54-context-without-reselect",
            "--reason",
            "Attempted selector replacement without an explicit reselect.",
            "--touched-path",
            "src/other.py",
            "--root",
            str(root),
            "--json",
        ]
    ) == 2
    assert "--reselect-context" in capsys.readouterr().err
    reopen_args = [
        "auto-dev",
        "reopen",
        "--state",
        str(finished),
        "--run-id",
        "cc-54-qa-reopen",
        "--reason",
        "QA found a follow-up after cleanup.",
        "--stage",
        "qa",
        "--root",
        str(root),
        "--apply",
        "--json",
    ]
    active_packets_before = set(_work_item_packets(project))
    assert main(reopen_args) == 2
    assert "durably staged but provisioning failed" in capsys.readouterr().err
    active_packets_after_failure = set(_work_item_packets(project))
    assert len(active_packets_after_failure - active_packets_before) == 1
    assert {
        path.relative_to(finished).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in finished.rglob("*")
        if path.is_file()
    } == finished_hashes

    # The same request recovers the durable intent and packet; it never creates
    # a second packet after a provisioning failure or crash boundary.
    assert main(reopen_args) == 0
    reopened = json.loads(capsys.readouterr().out)
    assert reopened["status"] == "reopened"
    active_packet = Path(reopened["active_packet"])
    assert active_packet.parent == project / "work-items"
    assert active_packet != finished
    assert finished.is_dir()
    assert (active_packet / "autodev.json").is_file()
    reopen_receipt = json.loads(
        (active_packet / "artifacts" / "auto-dev-reopen" / "reopen.json").read_text(
            encoding="utf-8"
        )
    )
    reopen_schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "schemas/auto-dev-reopen.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert list(Draft202012Validator(reopen_schema).iter_errors(reopen_receipt)) == []
    assert reopen_receipt["finished_packet"] == str(finished)
    assert reopen_receipt["health_sha256"] == hashlib.sha256(
        (finished / reopen_receipt["health_receipt"]).read_bytes()
    ).hexdigest()
    assert reopen_receipt["context"]["mode"] == "carried"
    assert reopen_receipt["context"]["prior_content_sha256"] == original_context_selection[
        "content_sha256"
    ]
    assert reopen_receipt["context"]["selected_content_sha256"] == original_context_selection[
        "content_sha256"
    ]
    assert reopen_receipt["context"]["touched_paths"] == ["src/rules_engine.py"]
    assert reopen_receipt["context"]["subjects"] == ["rulebook"]
    reopened_task = TaskState(
        Path(reopened["delivery"]["tasks"][0]["state_ref"])
    ).read()
    assert Path(reopened_task["work_item"]) == active_packet
    assert reopened_task["worktree"]["name"] == "cc-54-qa-reopen"
    assert reopened_task["runtime"]["ownership"] == "not_managed"
    assert reopened_task["context_selection"] == original_context_selection
    assert {
        path.relative_to(finished).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in finished.rglob("*")
        if path.is_file()
    } == finished_hashes
    connection = connect_state(default_db_path(root))
    try:
        canonical = canonical_work_items.get(connection, canonical_work_id)
        assert canonical["state"] == "building"
        assert Path(canonical["packet_path"]) == active_packet
        assert Path(canonical["worktree_path"]) == fresh_worktree
    finally:
        connection.close()

    packet_count = len(_work_item_packets(project))
    assert main(reopen_args) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["status"] == "already_reopened"
    assert Path(replay["active_packet"]) == active_packet
    assert len(_work_item_packets(project)) == packet_count

    mismatched_reason = list(reopen_args)
    mismatched_reason[mismatched_reason.index("QA found a follow-up after cleanup.")] = (
        "A different follow-up reason."
    )
    assert main(mismatched_reason) == 2
    assert "immutable-history request" in capsys.readouterr().err
    mismatched_base = [*reopen_args[:-2], "--base-branch", "release/other", *reopen_args[-2:]]
    assert main(mismatched_base) == 2
    assert "immutable-history request" in capsys.readouterr().err
    assert len(_work_item_packets(project)) == packet_count


def test_auto_dev_health_rejects_cleanup_without_receipt_audit(tmp_path: Path) -> None:
    state = (
        tmp_path
        / "os"
        / "domains"
        / "acme"
        / "02-projects"
        / "app"
        / "work-items"
        / "03-complete"
        / "cc-55"
        / "autodev.json"
    )
    state.parent.mkdir(parents=True)
    (tmp_path / "os" / ".agentic_root").write_text("", encoding="utf-8")
    template = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "harness/shared_factory/00-programs/auto_dev/templates/autodev.json"
        ).read_text(encoding="utf-8")
    )
    template.update(
        {
            "work_item_id": "cc-55",
            "domain": "acme",
            "project": "app",
            "mode": "single_stage",
            "requested_stage": "health",
            "current_stage": "health",
            "terminal_revision": "abc1234",
        }
    )
    merged_receipt = tmp_path / "merged.json"
    merged_receipt.write_text(
        json.dumps(
            {
                "schema": "development-stage-evidence/v1",
                "state": "merged",
                "status": "completed",
                "summary": "Merged",
                "evidence": {"merge_sha": "abc1234", "readback_verified": True},
                "verified_at": "2026-07-20T20:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    task_path = tmp_path / "delivery-task.json"
    task_path.write_text(
        json.dumps(
            {
                "state": "delivery_complete",
                "domain": "acme",
                "project": "app",
                "terminal_revision": "abc1234",
                "receipts": [{"state": "merged", "ref": str(merged_receipt)}],
            }
        ),
        encoding="utf-8",
    )
    template["delivery"] = {
        "state": "delivery_complete",
        "task_state_ref": str(task_path),
        "terminal_revision": "abc1234",
    }
    state.write_text(json.dumps(template), encoding="utf-8")
    evidence = tmp_path / "unsafe-health.json"
    evidence.write_text(
        json.dumps(
            {
                "schema": AUTO_DEV_HEALTH_EVIDENCE_SCHEMA,
                "work_item_id": "cc-55",
                "stage": "health",
                "status": "completed",
                "summary": "Claimed cleanup without an audit.",
                "subject_revision": "abc1234",
                "evidence": {"receipt_refs": ["receipt:cleanup"]},
                "verified_at": "2026-07-20T21:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(AutoDevStateError, match="strict schema"):
        record_auto_dev_stage(
            state,
            stage="health",
            evidence_file=evidence,
            idempotency_key="cc-55:unsafe-health",
        )

    (state.parent / "REOPEN.md").write_text("# Resume this item\n", encoding="utf-8")
    with pytest.raises(AutoDevStateError, match="REOPEN.md"):
        record_auto_dev_stage(
            state,
            stage="health",
            evidence_file=evidence,
            idempotency_key="cc-55:reopened-health",
        )


def test_pr_open_receipt_error_names_the_fields_that_branch_checks(
    tmp_path: Path,
) -> None:
    """The message must be a replacement instruction, not a mislabelled diagnosis."""

    task = _state(tmp_path)
    for state_name in delivery.FORWARD_STATES[
        1 : delivery.FORWARD_STATES.index("pre_pr_review") + 1
    ]:
        task.transition(
            state_name,
            receipt=f"setup:{state_name}",
            idempotency_key=f"setup:{state_name}",
        )
    evidence = _provider_authority(task, pull_request="github:acme/app#1")
    evidence["author_kind"] = ""
    with pytest.raises(DevelopmentDeliveryError) as caught:
        run_development_stage(
            task.path,
            stage="review",
            receipts={
                "pr_open": _stage_receipt(tmp_path / "pr-open", "pr_open", evidence=evidence)
            },
            idempotency_prefix="cc-1:pr-open-message",
        )
    message = str(caught.value)
    assert "readback_verified" in message
    assert "author_kind" in message
    assert "ours" in message and "others" in message
    # provider/pull_request are enforced by a different check; naming them here
    # sent callers to add fields that were already present.
    assert "provider" not in message
    assert "pull_request" not in message


def test_review_stage_follows_pr_create_without_requiring_its_own_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A review records Review Self; it cannot require that result beforehand."""

    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo)
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": "cc-review-cycle",
            "path": "/tmp/cc-review-cycle",
            "branch": "feature/cc-review-cycle",
            "base_sha": base_sha,
        },
    )
    run = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["CC-REVIEW-CYCLE"],
        run_id="review-cycle",
        auto_dev_mode="everything",
        apply=True,
    )
    task = TaskState(Path(run["tasks"][0]["state_ref"]))
    work_item = Path(task.read()["work_item"])
    run_development_stage(
        task.path,
        stage="readiness",
        receipts={"planned": _stage_receipt(work_item, "planned")},
        idempotency_prefix="cc-review-cycle:readiness",
    )
    run_development_stage(
        task.path,
        stage="implementation",
        receipts={
            "implementing": _stage_receipt(work_item, "implementing"),
            "local_validation": _stage_receipt(work_item, "local_validation"),
        },
        idempotency_prefix="cc-review-cycle:implementation",
    )
    for stage_name in ("groom", "detective", "create_artifacts", "document"):
        _record_standalone_stage(task, stage_name)
    authority = _provider_authority(task, pull_request="github:acme/app#77")
    review_receipts = {
        "pre_pr_review": _stage_receipt(work_item, "pre_pr_review"),
        "pr_open": _stage_receipt(work_item, "pr_open", evidence=authority),
        "ci_repair": _stage_receipt(work_item, "ci_repair"),
        "review_repair": _stage_receipt(work_item, "review_repair"),
        "post_pr_review": _stage_receipt(work_item, "post_pr_review"),
        "ready_for_merge": _stage_receipt(
            work_item,
            "ready_for_merge",
            evidence={
                **authority,
                "checks_verified": True,
                "reviews_verified": True,
                "subject_revision": base_sha,
            },
        ),
    }
    with pytest.raises(DevelopmentDeliveryError, match="pr_create"):
        run_development_stage(
            task.path,
            stage="review",
            receipts=review_receipts,
            idempotency_prefix="cc-review-cycle:review-before-pr-create",
        )
    run_development_stage(
        task.path,
        stage="release_propagation",
        receipts={
            "release_propagation": _stage_receipt(
                work_item / "artifacts" / "delivery", "release_propagation"
            )
        },
        idempotency_prefix="cc-review-cycle:pr-create",
    )
    reviewed = run_development_stage(
        task.path,
        stage="review",
        receipts=review_receipts,
        idempotency_prefix="cc-review-cycle:review",
    )
    assert reviewed["state"] == "ready_for_merge"
    projection = read_auto_dev_state(task.read()["autodev_path"])
    assert projection["stages"]["review_self"]["status"] == "completed"


def test_record_rejects_inline_evidence_json_with_a_usage_error() -> None:
    inline = json.dumps({"schema": AUTO_DEV_STAGE_EVIDENCE_SCHEMA, "stage": "qa"})
    with pytest.raises(AutoDevStateError) as caught:
        auto_dev.resolve_evidence_file(inline)
    message = str(caught.value)
    assert "--evidence expects a file path, not inline JSON" in message
    assert "Auto-Dev state not found" not in message


def test_record_rejects_inline_json_bound_to_the_positional_state(
    tmp_path: Path,
) -> None:
    inline = json.dumps({"schema": AUTO_DEV_STAGE_EVIDENCE_SCHEMA, "stage": "qa"})
    with pytest.raises(AutoDevStateError, match="not inline JSON"):
        record_auto_dev_stage(
            inline,
            stage="qa",
            evidence_file=str(tmp_path / "evidence.json"),
            idempotency_key="cc-1:inline-state",
        )


def test_missing_evidence_file_reports_the_evidence_flag_not_the_state() -> None:
    with pytest.raises(AutoDevStateError) as caught:
        auto_dev.resolve_evidence_file("/nonexistent/evidence.json")
    message = str(caught.value)
    assert message.startswith("--evidence file not found:")
    assert "Auto-Dev state not found" not in message


def test_workflow_docs_are_complete_and_shallow() -> None:
    repository = Path(__file__).resolve().parents[1]
    assert validate_workflow_contracts(repository) == []


# The title below is the exact one that broke provisioning for FLYWL-3391 on
# 2026-08-04. It matters that it is verbatim: the defect only fires when the
# 48-character cut inside ``_slug`` lands on a separator, so the composed work id
# keeps a trailing underscore that the scaffolder's own normalisation strips.
_TRUNCATING_TITLE = "Architecture spike: consolidate global reference data in the public schema"


def test_find_delivery_work_item_matches_the_normalised_packet_name(tmp_path: Path) -> None:
    project = tmp_path / "app"
    # The composed id keeps the trailing underscore the packet name never has.
    composed = "github_acme_app_flywl_3391_architecture_spike_consolidate_global_reference_"
    packet = project / "work-items" / "02-active" / f"080526-203_{composed.rstrip('_')}"
    packet.mkdir(parents=True)
    assert delivery.find_delivery_work_item(project, composed) == packet


def test_long_title_provisions_its_own_packet_and_registry_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    project = _project(root, repo)

    work_id = f"github_acme_app_{delivery._slug('FLYWL-3391').replace('-', '_')}_" + delivery._slug(
        _TRUNCATING_TITLE
    ).replace("-", "_")
    assert work_id.endswith("_"), "fixture no longer reproduces the truncation defect"

    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": "flywl-3391",
            "path": f"{tmp_path}/wt/flywl-3391",
            "branch": "feature/flywl-3391",
            "base_sha": base_sha,
        },
    )
    run = delivery.start_development_run(
        root,
        "acme",
        "app",
        ["FLYWL-3391"],
        titles={"FLYWL-3391": _TRUNCATING_TITLE},
        run_id="long-title-provisioning",
        auto_dev_mode="everything",
        apply=True,
    )

    task = TaskState(Path(run["tasks"][0]["state_ref"])).read()
    # Surfaced first so a regression reports "work item receipt missing" rather
    # than the downstream run state it turns into.
    assert task.get("failure") is None, task.get("failure")
    assert run["state"] == "dispatching"
    work_item = Path(task["work_item"])
    assert work_item.is_dir()
    assert (work_item / "work.yml").is_file()
    assert Path(task["autodev_path"]) == work_item / "autodev.json"
    projection = read_auto_dev_state(task["autodev_path"])
    assert Path(projection["delivery"]["work_item"]) == work_item

    # The packet name is the normalised id, one character shorter than the
    # composed id. Looking it up by that composed id has to still find it.
    assert work_item.name.endswith(work_id.rstrip("_"))
    assert not work_item.name.endswith(work_id)
    assert delivery.find_delivery_work_item(project, work_id) == work_item

    connection = connect_state(default_db_path(root))
    try:
        canonical = canonical_work_items.get(connection, "acme:app:flywl-3391")
        assert canonical is not None
        assert Path(canonical["packet_path"]) == work_item
    finally:
        connection.close()


def test_long_title_retry_adopts_its_packet_instead_of_orphaning_another(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    project = _project(root, repo)

    def worktree(**kwargs):
        if not attempts:
            attempts.append("first")
            raise DevelopmentDeliveryError("git fetch provider unavailable")
        return {
            "name": "flywl-3391",
            "path": f"{tmp_path}/wt/flywl-3391",
            "branch": "feature/flywl-3391",
            "base_sha": base_sha,
        }

    attempts: list[str] = []
    monkeypatch.setattr(delivery, "create_isolated_worktree", worktree)
    for _ in range(2):
        delivery.start_development_run(
            root,
            "acme",
            "app",
            ["FLYWL-3391"],
            titles={"FLYWL-3391": _TRUNCATING_TITLE},
            run_id="long-title-retry",
            auto_dev_mode="everything",
            apply=True,
        )

    assert len(_work_item_packets(project)) == 1


def test_run_id_refuses_a_corrected_title_instead_of_reusing_the_pinned_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base_sha = _repository(tmp_path)
    root = tmp_path / "os"
    _project(root, repo)
    monkeypatch.setattr(
        delivery,
        "create_isolated_worktree",
        lambda **kwargs: {
            "name": "flywl-3391",
            "path": f"{tmp_path}/wt/flywl-3391",
            "branch": "feature/flywl-3391",
            "base_sha": base_sha,
        },
    )
    kwargs = dict(run_id="pinned-title", auto_dev_mode="everything", apply=True)
    delivery.start_development_run(
        root, "acme", "app", ["FLYWL-3391"], titles={"FLYWL-3391": _TRUNCATING_TITLE}, **kwargs
    )

    with pytest.raises(DevelopmentDeliveryError, match="already pinned the title for FLYWL-3391"):
        delivery.start_development_run(
            root,
            "acme",
            "app",
            ["FLYWL-3391"],
            titles={"FLYWL-3391": "Public schema reference data spike"},
            **kwargs,
        )

    # Resuming without an explicit title still inherits the pinned one.
    resumed = delivery.start_development_run(root, "acme", "app", ["FLYWL-3391"], **kwargs)
    assert resumed["titles"]["FLYWL-3391"] == _TRUNCATING_TITLE
