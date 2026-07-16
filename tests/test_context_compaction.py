import base64
import hashlib
import json
from pathlib import Path
import shutil

import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os.config_ops import BASE_PROMPT_FILES, policy_for_layer, prompt_file_template
from genomes_agentic_os.context_compaction import (
    _legacy_v1_root_state_hash,
    apply_compaction_plan,
    build_compaction_plan,
    check_context_contracts,
    managed_context_targets,
    restore_compaction_receipt,
    write_compaction_plan,
)


def make_target(root: Path, name: str) -> Path:
    domain = root / "acme"
    domain.mkdir(parents=True, exist_ok=True)
    target = root / "acme" / "03-workflows" / "engineering" / name
    target.mkdir(parents=True)
    (target / "workflow.md").write_text(f"# {name}\n", encoding="utf-8")
    (target / "context-contract.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "kind": "workflow",
                "inherits": ["parent"],
                "read": {"first": ["workflow.md"], "deferred": [], "exclude": []},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return target


def test_compaction_plan_is_deterministic_and_contains_exact_rollback(tmp_path: Path) -> None:
    root = tmp_path / "os"
    first = make_target(root, "first")
    second = make_target(root, "second")
    duplicate = "# Generic router\n\nRoute to the parent.\n"
    (root / "acme/ROUTER.md").write_text(duplicate, encoding="utf-8")
    (first / "ROUTER.md").write_text(duplicate, encoding="utf-8")
    (second / "ROUTER.md").write_text(duplicate, encoding="utf-8")

    check = check_context_contracts(root)
    plan = build_compaction_plan(root)

    assert check.ok
    assert check.duplicate_groups == 1
    assert plan == build_compaction_plan(root)
    assert plan["summary"]["files_preserved_in_rollback"] == 2
    restored = base64.b64decode(plan["rollback_manifest"]["files"][0]["content_base64"]).decode()
    assert restored == duplicate
    assert all(action["status"] == "proposed" for action in plan["actions"])


def test_context_cli_explain_check_and_plan_receipts(tmp_path: Path, capsys) -> None:
    root = tmp_path / "os"
    assert main(["workflow", "create", "acme", "engineering", "ship", "--root", str(root)]) == 0
    assert main(["automation", "create", "acme", "engineering", "watch_ship", "--root", str(root)]) == 0
    capsys.readouterr()

    assert main(
        [
            "context",
            "explain",
            "--domain",
            "acme",
            "--lane",
            "engineering",
            "--workflow",
            "ship",
            "--root",
            str(root),
        ]
    ) == 0
    explained = yaml.safe_load(capsys.readouterr().out)
    assert explained["ok"] is True
    assert explained["legacy_fallback"] is False
    assert explained["read_first"]
    workflow_root = root / "acme/03-workflows/engineering/ship"
    assert (workflow_root / "context-contract.yml").is_file()
    for copied_contract in ("ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md"):
        assert not (workflow_root / copied_contract).exists()
    assert any(item["path"].endswith("acme/RULES.md") for item in explained["read_first"])

    legacy_words = sum(
        len(prompt_file_template(policy_for_layer("workflow_or_task"), filename).split())
        for filename in BASE_PROMPT_FILES
    )
    compact_words = sum(
        len((workflow_root / filename).read_text(encoding="utf-8").split())
        for filename in ("AGENTS.md", "PROFILE.md", "CLAUDE.md", "context-contract.yml")
    )
    assert compact_words <= legacy_words * 0.6

    assert main(["context", "check", "--root", str(root)]) == 0
    checked = yaml.safe_load(capsys.readouterr().out)
    assert checked["manifests"] == 2
    automation_root = root / "acme/04-automations/engineering/watch_ship"
    assert (automation_root / "context-contract.yml").is_file()
    for copied_contract in ("ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md"):
        assert not (automation_root / copied_contract).exists()

    assert main(["config", "install-tree", "--root", str(root), "--apply"]) == 0
    capsys.readouterr()
    for object_root in (workflow_root, automation_root):
        for copied_contract in ("ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md", "MEMORY.md"):
            assert not (object_root / copied_contract).exists()
    for object_root in (workflow_root, automation_root):
        for copied_contract in ("ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md"):
            shutil.copyfile(root / "acme" / copied_contract, object_root / copied_contract)

    receipts = tmp_path / "receipts"
    assert main(
        ["context", "compact", "--dry-run", "--root", str(root), "--output-dir", str(receipts)]
    ) == 0
    capsys.readouterr()
    plan = json.loads((receipts / "context-compaction-plan.json").read_text())
    rollback = json.loads((receipts / "context-compaction-rollback.json").read_text())
    assert plan["mode"] == "dry_run"
    assert rollback["operation"] == "context_compact"
    assert plan["summary"]["proposed_removals"] == 8
    assert plan["summary"]["candidate_reduction_ratio"] >= 0.40

    assert main(
        [
            "context",
            "compact",
            "--apply",
            "--root",
            str(root),
            "--plan",
            str(receipts / "context-compaction-plan.json"),
            "--receipt-dir",
            str(receipts),
        ]
    ) == 0
    capsys.readouterr()
    receipt_path = next(receipts.glob("context-compaction-????????????.json"))
    receipt = json.loads(receipt_path.read_text())
    assert receipt["status"] == "applied"
    assert receipt["semantic_before"] == receipt["semantic_after"]

    assert main(["context", "restore", "--root", str(root), "--receipt", str(receipt_path)]) == 0
    capsys.readouterr()
    assert json.loads(receipt_path.read_text())["status"] == "restored"


def test_context_compact_refuses_implicit_mutation(tmp_path: Path, capsys) -> None:
    assert main(["context", "compact", "--root", str(tmp_path)]) == 2
    assert "requires exactly one" in capsys.readouterr().err


def fixture_root(tmp_path: Path) -> Path:
    source = Path(__file__).parent / "fixtures/context_migration/os"
    target = tmp_path / "os"
    shutil.copytree(source, target)
    # The committed fixture is the compact after-state. Recreate the exact
    # legacy before-state in temporary space for apply/restore coverage.
    for workflow in ("first", "second"):
        workflow_root = target / f"acme/03-workflows/engineering/{workflow}"
        for filename in ("ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md"):
            shutil.copyfile(target / "acme" / filename, workflow_root / filename)
    return target


def test_apply_and_exact_restore_preserve_semantics_and_reduce_context(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    plan_dir = tmp_path / "plans"
    plan_path, _, plan = write_compaction_plan(root, plan_dir)
    before_files = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.glob("acme/03-workflows/engineering/*/*.md")
    }

    assert plan["summary"]["proposed_removals"] == 8
    assert plan["summary"]["candidate_reduction_ratio"] >= 0.40
    result = apply_compaction_plan(root, plan_path, tmp_path / "receipts", validator=lambda _: [])

    assert result["status"] == "applied"
    assert result["semantic_before"] == result["semantic_after"]
    assert result["summary"]["files_removed"] == 8
    assert result["summary"]["reduction_ratio"] >= 0.40
    for relative in before_files:
        if Path(relative).name in {"ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md"}:
            assert not (root / relative).exists()

    restored = restore_compaction_receipt(root, result["receipt_path"])
    assert restored["status"] == "restored"
    for relative, content in before_files.items():
        assert (root / relative).read_bytes() == content


def test_failed_validation_rolls_back_exact_bytes(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    plan_path, _, _ = write_compaction_plan(root, tmp_path / "plans")
    before = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*.md")
    }

    try:
        apply_compaction_plan(root, plan_path, tmp_path / "receipts", validator=lambda _: ["forced failure"])
    except ValueError as exc:
        assert "was rolled back" in str(exc)
    else:
        raise AssertionError("validation failure must abort apply")

    after = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*.md")
    }
    assert after == before
    receipt = json.loads(next((tmp_path / "receipts").glob("*.json")).read_text())
    assert receipt["status"] == "rolled_back"
    assert receipt["validation_errors"] == ["forced failure"]


def test_apply_refuses_stale_or_tampered_plan(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    plan_path, _, _ = write_compaction_plan(root, tmp_path / "plans")
    workflow = root / "acme/03-workflows/engineering/first/workflow.md"
    workflow.write_text("# changed after review\n", encoding="utf-8")
    try:
        apply_compaction_plan(root, plan_path, tmp_path / "receipts", validator=lambda _: [])
    except ValueError as exc:
        assert "changed after planning" in str(exc)
    else:
        raise AssertionError("stale plan must be rejected")

    root = fixture_root(tmp_path / "tampered")
    plan_path, _, _ = write_compaction_plan(root, tmp_path / "tampered/plans")
    data = json.loads(plan_path.read_text())
    data["summary"]["candidate_reduction_ratio"] = 1.0
    plan_path.write_text(json.dumps(data), encoding="utf-8")
    try:
        apply_compaction_plan(root, plan_path, tmp_path / "tampered/receipts", validator=lambda _: [])
    except ValueError as exc:
        assert "plan hash mismatch" in str(exc)
    else:
        raise AssertionError("tampered plan must be rejected")


def legacy_automation(root: Path) -> Path:
    target = root / "acme/04-automations/engineering/cleanup"
    target.mkdir(parents=True)
    (target / "AGENTS.md").write_text("# Automation agent\n", encoding="utf-8")
    (target / "MEMORY.md").write_text("# Durable memory\n", encoding="utf-8")
    (target / "automation.md").write_text("# Cleanup automation\n", encoding="utf-8")
    (target / "permissions.md").write_text("# Permissions\n\nGuarded.\n", encoding="utf-8")
    (target / "runbook.md").write_text("# Runbook\n\nPlan, apply, validate.\n", encoding="utf-8")
    contracts = {
        "ROUTER.md": "# Router\n\nRoute to engineering.\n" * 8,
        "CONTEXT.md": "# Context\n\nUse current receipts.\n" * 8,
        "RULES.md": "# Rules\n\nKeep changes reversible.\n" * 8,
        "TOOLS.md": "# Tools\n\nUse the guarded Agentic OS CLI.\n" * 40,
    }
    for filename, content in contracts.items():
        (target / filename).write_text(content, encoding="utf-8")
    return target


def test_promote_legacy_target_creates_manifest_and_lane_contracts(tmp_path: Path) -> None:
    root = tmp_path / "os"
    target = legacy_automation(root)
    relative = target.relative_to(root).as_posix()
    before = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in target.iterdir()
        if path.is_file()
    }
    plan_path, _, plan = write_compaction_plan(
        root,
        tmp_path / "plans",
        target_paths=[relative],
        promote_legacy=True,
    )

    assert plan["summary"]["targets_migrated"] == 1
    assert plan["summary"]["proposed_removals"] == 4
    assert plan["summary"]["blocked_actions"] == 0
    assert plan["target_reductions"][relative]["reduction_ratio"] >= 0.40
    assert sum(action["action"] == "create_inherited_contract" for action in plan["actions"]) == 4

    result = apply_compaction_plan(root, plan_path, tmp_path / "receipts", validator=lambda _: [])

    assert result["status"] == "applied"
    assert result["semantic_before"] == result["semantic_after"]
    assert result["context_check_before"]["legacy_fallbacks"] == 1
    assert result["context_check_after"]["legacy_fallbacks"] == 0
    assert result["context_check_after"]["manifests"] == 1
    assert (target / "context-contract.yml").is_file()
    for filename in ("ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md"):
        assert not (target / filename).exists()
        assert (target.parent / filename).is_file()

    restored = restore_compaction_receipt(root, result["receipt_path"])
    assert restored["status"] == "restored"
    assert not (target / "context-contract.yml").exists()
    for filename in ("ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md"):
        assert not (target.parent / filename).exists()
    after = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in target.iterdir()
        if path.is_file()
    }
    assert after == before


def test_promote_legacy_requires_explicit_target(tmp_path: Path) -> None:
    legacy_automation(tmp_path / "os")
    try:
        build_compaction_plan(tmp_path / "os", promote_legacy=True)
    except ValueError as exc:
        assert "explicit target" in str(exc)
    else:
        raise AssertionError("legacy promotion must be explicitly bounded")


def test_promote_legacy_validation_failure_removes_created_parent_files(tmp_path: Path) -> None:
    root = tmp_path / "os"
    target = legacy_automation(root)
    relative = target.relative_to(root).as_posix()
    before = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    plan_path, _, _ = write_compaction_plan(
        root,
        tmp_path / "plans",
        target_paths=[relative],
        promote_legacy=True,
    )

    try:
        apply_compaction_plan(root, plan_path, tmp_path / "receipts", validator=lambda _: ["forced failure"])
    except ValueError as exc:
        assert "was rolled back" in str(exc)
    else:
        raise AssertionError("failed manifest migration must roll back")

    after = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert after == before
    receipt = json.loads(next((tmp_path / "receipts").glob("*.json")).read_text())
    assert receipt["status"] == "rolled_back"


def test_validation_baseline_allows_existing_errors_but_rejects_regression(tmp_path: Path) -> None:
    root = tmp_path / "os"
    target = legacy_automation(root)
    relative = target.relative_to(root).as_posix()
    existing = lambda _: ["pre-existing drift"]
    plan_path, _, plan = write_compaction_plan(
        root,
        tmp_path / "plans",
        target_paths=[relative],
        promote_legacy=True,
        capture_validation_baseline=True,
        validation_validator=existing,
    )
    assert plan["validation_before"]["error_count"] == 1

    result = apply_compaction_plan(root, plan_path, tmp_path / "receipts", validator=existing)
    assert result["status"] == "applied"
    assert result["validation_before"] == result["validation_after"]
    restore_compaction_receipt(root, result["receipt_path"])

    plan_path, _, _ = write_compaction_plan(
        root,
        tmp_path / "regression-plans",
        target_paths=[relative],
        promote_legacy=True,
        capture_validation_baseline=True,
        validation_validator=existing,
    )
    calls = 0

    def regresses(_: Path) -> list[str]:
        nonlocal calls
        calls += 1
        return ["pre-existing drift"] if calls == 1 else ["pre-existing drift", "new regression"]

    try:
        apply_compaction_plan(root, plan_path, tmp_path / "regression-receipts", validator=regresses)
    except ValueError as exc:
        assert "was rolled back" in str(exc)
    else:
        raise AssertionError("a new validation error must roll back the migration")
    assert not (target / "context-contract.yml").exists()


def test_restore_accepts_schema_v1_receipt_hashes(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    targets = managed_context_targets(root)
    target = root / "acme/03-workflows/engineering/first/ROUTER.md"
    content = target.read_bytes()
    before_hash = _legacy_v1_root_state_hash(root, targets)
    target.unlink()
    after_hash = _legacy_v1_root_state_hash(root, targets)
    receipt = {
        "schema_version": 1,
        "operation": "context_compact_apply",
        "status": "applied",
        "root": str(root),
        "root_state_sha256_before": before_hash,
        "root_state_sha256_after": after_hash,
        "files": [
            {
                "path": target.relative_to(root).as_posix(),
                "sha256_before": hashlib.sha256(content).hexdigest(),
                "content_base64": base64.b64encode(content).decode("ascii"),
                "sha256_after": None,
            }
        ],
    }
    receipt_path = tmp_path / "v1-receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    restored = restore_compaction_receipt(root, receipt_path)

    assert restored["status"] == "restored"
    assert target.read_bytes() == content
