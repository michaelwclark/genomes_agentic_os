from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os import filesystem_resource_actions as lifecycle


def _init(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root)]) == 0
    capsys.readouterr()
    assert main(["runtime", "init", "--root", str(root)]) == 0
    capsys.readouterr()


def _json(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def _create(root: Path, capsys, kind: str, name: str, *, domain: str | None = None, lane: str | None = None) -> dict:
    args = ["resource", "create", kind, name]
    if domain:
        args.extend(["--domain", domain])
    if lane:
        args.extend(["--lane", lane])
    args.extend(["--root", str(root), "--apply", "--json"])
    assert main(args) == 0
    return _json(capsys)


def _get(root: Path, capsys, kind: str, name: str, *, domain: str | None = None, lane: str | None = None) -> dict:
    args = ["resource", "get", kind, name]
    if domain:
        args.extend(["--domain", domain])
    if lane:
        args.extend(["--lane", lane])
    args.extend(["--root", str(root), "--json"])
    assert main(args) == 0
    return _json(capsys)


def _enable_automation(root: Path, capsys, name: str = "demo_auto") -> dict:
    current = _get(root, capsys, "automation", name, domain="personal", lane="engineering")
    args = [
        "resource",
        "update",
        "automation",
        name,
        "--domain",
        "personal",
        "--lane",
        "engineering",
        "--enabled",
        "--status",
        "active",
        "--expected-drift-hash",
        current["resource"]["drift_hash"],
        "--root",
        str(root),
        "--apply",
        "--json",
    ]
    assert main(args) == 0
    return _json(capsys)


def test_canonical_create_list_get_and_definition_instance_identity(tmp_path: Path, capsys) -> None:
    root = tmp_path / "os"
    _init(root, capsys)
    _create(root, capsys, "automation", "demo_auto", domain="personal", lane="engineering")
    _create(root, capsys, "workflow", "demo_flow", domain="personal", lane="engineering")
    _create(root, capsys, "program", "demo_program")
    _create(root, capsys, "instance-program", "demo_program", domain="personal")

    for kind, extra in (
        ("automation", ["--domain", "personal", "--lane", "engineering"]),
        ("workflow", ["--domain", "personal", "--lane", "engineering"]),
        ("program", []),
        ("instance-program", ["--domain", "personal"]),
    ):
        assert main(["resource", "list", kind, *extra, "--root", str(root), "--json"]) == 0
        listed = _json(capsys)
        expected_id = "demo_program" if "program" in kind else ("demo_auto" if kind == "automation" else "demo_flow")
        assert expected_id in {item["id"] for item in listed["resources"]}

    definition = _get(root, capsys, "program", "demo_program")["resource"]
    instance = _get(root, capsys, "instance-program", "demo_program", domain="personal")["resource"]
    assert definition["kind"] == "program"
    assert definition["domain"] is None
    assert instance["kind"] == "instance-program"
    assert instance["definition_id"] == "demo_program"
    assert Path(definition["path"]) != Path(instance["path"])


def test_update_is_allowlisted_drift_checked_and_preserves_unknown_fields(tmp_path: Path, capsys) -> None:
    root = tmp_path / "os"
    _init(root, capsys)
    _create(root, capsys, "program", "demo_program")
    current = _get(root, capsys, "program", "demo_program")["resource"]
    overlay = Path(current["path"]) / lifecycle.OVERLAY_NAME
    payload = yaml.safe_load(overlay.read_text(encoding="utf-8"))
    payload["future_extension"] = {"keep": True}
    overlay.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    current = _get(root, capsys, "program", "demo_program")["resource"]

    assert main(
        [
            "resource",
            "update",
            "program",
            "demo_program",
            "--summary",
            "Updated operator summary.",
            "--expected-drift-hash",
            current["drift_hash"],
            "--root",
            str(root),
            "--apply",
            "--json",
        ]
    ) == 0
    updated = _json(capsys)
    assert "summary" in {item["field"] for item in updated["resource"]["diff"]}
    assert updated["readback"]["metadata"]["future_extension"] == {"keep": True}

    with pytest.raises(ValueError, match="unsupported program fields"):
        lifecycle.update_filesystem_resource(root, "program", "demo_program", changes={"path": "/tmp/escape"})

    stale = current["drift_hash"]
    Path(current["primary_file"]).write_text("# changed outside the plan\n", encoding="utf-8")
    assert main(
        [
            "resource",
            "update",
            "program",
            "demo_program",
            "--summary",
            "Should not apply.",
            "--expected-drift-hash",
            stale,
            "--root",
            str(root),
            "--apply",
            "--json",
        ]
    ) == 2
    assert "stale resource plan" in capsys.readouterr().err


def test_archive_restore_and_rollback_are_reversible(tmp_path: Path, capsys) -> None:
    root = tmp_path / "os"
    _init(root, capsys)
    _create(root, capsys, "program", "demo_program")
    original = _get(root, capsys, "program", "demo_program")["resource"]

    assert main(
        [
            "resource",
            "archive",
            "program",
            "demo_program",
            "--expected-drift-hash",
            original["drift_hash"],
            "--root",
            str(root),
            "--apply",
            "--json",
        ]
    ) == 0
    archived = _json(capsys)
    assert archived["readback"]["metadata"]["status"] == "archived"
    assert Path(archived["resource"]["path"]).is_dir()

    archived_view = _get(root, capsys, "program", "demo_program")["resource"]
    assert main(
        [
            "resource",
            "restore",
            "program",
            "demo_program",
            "--expected-drift-hash",
            archived_view["drift_hash"],
            "--root",
            str(root),
            "--apply",
            "--json",
        ]
    ) == 0
    restored = _json(capsys)
    assert restored["readback"]["metadata"]["status"] == "draft"

    current = _get(root, capsys, "program", "demo_program")["resource"]
    assert main(
        [
            "resource",
            "update",
            "program",
            "demo_program",
            "--summary",
            "Temporary summary.",
            "--expected-drift-hash",
            current["drift_hash"],
            "--root",
            str(root),
            "--apply",
            "--json",
        ]
    ) == 0
    changed = _json(capsys)
    changed_view = _get(root, capsys, "program", "demo_program")["resource"]
    assert main(
        [
            "resource",
            "rollback",
            "program",
            "demo_program",
            "--backup-id",
            changed["backup_id"],
            "--expected-drift-hash",
            changed_view["drift_hash"],
            "--root",
            str(root),
            "--apply",
            "--json",
        ]
    ) == 0
    rolled_back = _json(capsys)
    assert rolled_back["readback"]["ok"] is True
    assert _get(root, capsys, "program", "demo_program")["resource"]["summary"] != "Temporary summary."


def test_failed_readback_restores_exact_prior_overlay_bytes(tmp_path: Path, capsys, monkeypatch) -> None:
    root = tmp_path / "os"
    _init(root, capsys)
    _create(root, capsys, "program", "demo_program")
    current = _get(root, capsys, "program", "demo_program")["resource"]
    overlay = Path(current["path"]) / lifecycle.OVERLAY_NAME
    exact_before = overlay.read_bytes()
    original_load = lifecycle._load_overlay
    calls = 0

    def mismatched_readback(targets):
        nonlocal calls
        calls += 1
        metadata, explicit = original_load(targets)
        if calls >= 2:
            metadata = dict(metadata)
            metadata["summary"] = "simulated readback mismatch"
        return metadata, explicit

    monkeypatch.setattr(lifecycle, "_load_overlay", mismatched_readback)
    with pytest.raises(ValueError, match="exact prior overlay bytes restored"):
        lifecycle.update_filesystem_resource(
            root,
            "program",
            "demo_program",
            changes={"summary": "Will be rolled back."},
            expected_drift_hash=current["drift_hash"],
            dry_run=False,
        )
    assert overlay.read_bytes() == exact_before


def test_repair_fixes_lifecycle_identity_and_preserves_unknown_fields(tmp_path: Path, capsys) -> None:
    root = tmp_path / "os"
    _init(root, capsys)
    _create(root, capsys, "program", "demo_program")
    current = _get(root, capsys, "program", "demo_program")["resource"]
    overlay = Path(current["path"]) / lifecycle.OVERLAY_NAME
    payload = yaml.safe_load(overlay.read_text(encoding="utf-8"))
    payload.update({"kind": "workflow", "status": "broken", "future_extension": "preserve"})
    overlay.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    assert main(
        ["resource", "repair", "program", "demo_program", "--root", str(root), "--json"]
    ) == 0
    planned = _json(capsys)
    assert planned["status"] == "planned"
    assert main(
        [
            "resource",
            "repair",
            "program",
            "demo_program",
            "--expected-drift-hash",
            planned["drift"]["before"],
            "--root",
            str(root),
            "--apply",
            "--json",
        ]
    ) == 0
    repaired = _json(capsys)
    assert repaired["readback"]["metadata"]["kind"] == "program"
    assert repaired["readback"]["metadata"]["status"] == "draft"
    assert repaired["readback"]["metadata"]["future_extension"] == "preserve"


def test_destination_and_backup_target_tampering_are_denied(tmp_path: Path, capsys) -> None:
    root = tmp_path / "os"
    _init(root, capsys)
    outside = tmp_path / "outside"
    outside.mkdir()
    escaped = root / "domains/personal/04-automations/engineering/escaped_auto"
    escaped.symlink_to(outside, target_is_directory=True)
    assert main(
        [
            "resource",
            "create",
            "automation",
            "escaped_auto",
            "--domain",
            "personal",
            "--lane",
            "engineering",
            "--root",
            str(root),
            "--json",
        ]
    ) == 2
    assert "escaped the installed root" in capsys.readouterr().err

    _create(root, capsys, "program", "demo_program")
    current = _get(root, capsys, "program", "demo_program")["resource"]
    result = lifecycle.update_filesystem_resource(
        root,
        "program",
        "demo_program",
        changes={"summary": "Backup target test."},
        expected_drift_hash=current["drift_hash"],
        dry_run=False,
    )
    backup = root / lifecycle.EVIDENCE_ROOT / "backups" / f"{result['backup_id']}.yml"
    bundle = yaml.safe_load(backup.read_text(encoding="utf-8"))
    bundle["target"] = "personal/00-programs/some_other_program"
    backup.write_text(yaml.safe_dump(bundle, sort_keys=False), encoding="utf-8")
    changed = lifecycle.filesystem_resource_get(root, "program", "demo_program")["resource"]
    with pytest.raises(ValueError, match="backup target does not match"):
        lifecycle.rollback_filesystem_resource(
            root,
            "program",
            "demo_program",
            backup_id=result["backup_id"],
            expected_drift_hash=changed["drift_hash"],
            dry_run=False,
        )


def test_run_now_is_queue_only_idempotent_and_schedule_has_derived_command(tmp_path: Path, capsys) -> None:
    root = tmp_path / "os"
    _init(root, capsys)
    _create(root, capsys, "automation", "demo_auto", domain="personal", lane="engineering")
    _enable_automation(root, capsys)
    current = _get(root, capsys, "automation", "demo_auto", domain="personal", lane="engineering")["resource"]

    run_args = [
        "resource",
        "run-now",
        "automation",
        "demo_auto",
        "--domain",
        "personal",
        "--lane",
        "engineering",
        "--idempotency-key",
        "cc306:test:run",
        "--expected-drift-hash",
        current["drift_hash"],
        "--root",
        str(root),
        "--apply",
        "--json",
    ]
    assert main(run_args) == 0
    first = _json(capsys)
    assert first["queue_created"] is True
    assert first["queue_item"]["dispatch_performed"] is False
    assert "command" not in first["queue_item"]
    assert main(run_args) == 0
    second = _json(capsys)
    assert second["queue_created"] is False
    assert second["status"] == "unchanged"

    planned = lifecycle.configure_automation_schedule(
        root,
        "demo_auto",
        domain="personal",
        lane="engineering",
        cadence="daily",
        local_time="08:30",
    )
    applied = lifecycle.configure_automation_schedule(
        root,
        "demo_auto",
        domain="personal",
        lane="engineering",
        cadence="daily",
        local_time="08:30",
        enabled=True,
        expected_drift_hash=planned["drift_hash"],
        dry_run=False,
    )
    schedule = applied["readback"]["schedule"]
    assert schedule["command"] == (
        "agentic-os resource run-now automation demo_auto --domain personal "
        "--lane engineering --root <root> --apply"
    )
    assert schedule["local_time"] == "08:30"
    assert applied["dispatch_performed"] is False

    preserve_plan = lifecycle.configure_automation_schedule(
        root,
        "demo_auto",
        domain="personal",
        lane="engineering",
        cadence="weekly",
    )
    preserved = lifecycle.configure_automation_schedule(
        root,
        "demo_auto",
        domain="personal",
        lane="engineering",
        cadence="weekly",
        expected_drift_hash=preserve_plan["drift_hash"],
        dry_run=False,
    )
    assert preserved["readback"]["schedule"]["enabled"] is True
