from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tarfile

import pytest
import yaml

import genomes_agentic_os.artifact_migration as artifact_migration
from genomes_agentic_os.artifact_migration import (
    apply_artifact_naming_plan,
    build_artifact_migration_preflight,
    build_artifact_naming_plan,
    restore_artifact_naming_migration,
)
from genomes_agentic_os.artifact_naming import render_default_artifact_naming_config
from genomes_agentic_os.state import db, work_items


def _legacy_root(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "os"
    (root / "harness/config").mkdir(parents=True)
    (root / "harness/config/artifact-naming.yml").write_text(
        render_default_artifact_naming_config(), encoding="utf-8"
    )
    project = root / "domains/acme/projects/app"
    packet = project / "work-items/02-active/001_old_item"
    conversations = packet / "logs/conversations"
    conversations.mkdir(parents=True)
    (packet / "work.yml").write_text(
        yaml.safe_dump(
            {
                "id": "001_old_item",
                "title": "Old Item",
                "created_at": "2026-01-02T03:04:05Z",
                "packet_path": "domains/acme/projects/app/work-items/02-active/001_old_item",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (conversations / "README.md").write_text(
        "# Conversation logs\n", encoding="utf-8"
    )
    (conversations / "2026_01_02_old_item.jsonl").write_text("{}\n", encoding="utf-8")
    closeout = packet / "artifacts/thread-closeouts/stale_001_old_item_20260102T030405Z"
    closeout.mkdir(parents=True)
    (closeout / "closeout.md").write_text(f"packet: {packet}\n", encoding="utf-8")
    async_run = packet / "artifacts/async-runs/20260102T030405-old-tests"
    async_run.mkdir(parents=True)
    (async_run / "state.json").write_text(
        json.dumps({"run_dir": str(async_run)}) + "\n", encoding="utf-8"
    )
    worktree = project / "worktrees/old-checkout"
    worktree.mkdir(parents=True)
    (project / "worktrees/index.yml").write_text(
        yaml.safe_dump(
            {
                "project": "app",
                "worktrees": [
                    {
                        "id": "old-checkout",
                        "path": str(worktree),
                        "link": "worktrees/old-checkout",
                        "status": "active",
                        "created_at": "2026-01-02T03:04:05Z",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    run = root / "domains/acme/06-runs-and-logs/runs/20260102T030405Z-acme-example"
    run.mkdir(parents=True)
    (run / "run-log.md").write_text(f"path: {packet}\n", encoding="utf-8")

    conn = db.connect(db.default_db_path(root))
    try:
        work_items.upsert(
            conn,
            item_id="acme:app:001_old_item",
            title="Old Item",
            state="building",
            attention="active",
            domain="acme",
            project="app",
            packet_path=str(packet.relative_to(root)),
            worktree_path=str(worktree),
            context_summary="Migration fixture remains active.",
            verified=True,
            now="2026-01-02T03:04:05Z",
        )
    finally:
        conn.close()
    return root, packet


def test_migration_moves_entities_rewrites_registries_and_is_idempotent(
    tmp_path: Path,
) -> None:
    root, packet = _legacy_root(tmp_path)
    plan = build_artifact_naming_plan(root)
    assert plan["collisions"] == []
    assert plan["counts"]["work_item"] == 1
    assert plan["counts"]["worktree"] == 1
    assert plan["counts"]["conversation_log"] == 1
    assert all(not move["source"].endswith("/logs/conversations/README.md") for move in plan["moves"])
    assert plan["counts"]["thread_closeout"] == 1
    assert plan["counts"]["async_run"] == 1
    assert plan["counts"]["run_log"] == 1

    backup = tmp_path / "backup"
    result = apply_artifact_naming_plan(root, backup_dir=backup)
    migrated_packet = packet.with_name("010226-001_old_item")
    assert migrated_packet.is_dir()
    assert (migrated_packet / "logs/conversations/010226-old_item.jsonl").is_file()
    assert (migrated_packet / "logs/conversations/README.md").is_file()
    assert (
        migrated_packet / "artifacts/thread-closeouts/010226-stale_001_old_item-030405Z"
    ).is_dir()
    assert (migrated_packet / "artifacts/async-runs/010226-030405-old-tests").is_dir()
    assert (
        root / "domains/acme/06-runs-and-logs/runs/010226-030405Z-acme-example"
    ).is_dir()
    assert (backup / "mutable-state.tar.gz").is_file()
    assert Path(result["receipt_path"]).is_file()

    registry = (root / "domains/acme/projects/app/worktrees/index.yml").read_text(
        encoding="utf-8"
    )
    assert "010226-old-checkout" in registry
    assert "old-checkout" in registry  # retained as part of the new readable name
    assert "010226-010226-" not in registry
    metadata = (migrated_packet / "work.yml").read_text(encoding="utf-8")
    assert "010226-001_old_item" in metadata
    assert "010226-010226-" not in metadata

    conn = db.connect(db.default_db_path(root))
    try:
        item = work_items.get(conn, "acme:app:010226-001_old_item")
        assert item is not None
        assert item["packet_path"].endswith("010226-001_old_item")
        assert item["worktree_path"].endswith("010226-old-checkout")
    finally:
        conn.close()

    assert build_artifact_naming_plan(root)["move_count"] == 0


def test_migration_preserves_immutable_history_and_bounds_reference_inventory(
    tmp_path: Path,
) -> None:
    root, packet = _legacy_root(tmp_path)
    historical = packet / "logs/conversations/2026_01_02_old_item.jsonl"
    historical_content = f'{{"packet_path": "{packet}"}}\n' * 5_000
    historical.write_text(historical_content, encoding="utf-8")
    plan = build_artifact_naming_plan(root)

    preflight = build_artifact_migration_preflight(root, plan)
    result = apply_artifact_naming_plan(root, backup_dir=tmp_path / "history-backup")
    migrated_packet = packet.with_name("010226-001_old_item")
    migrated_history = migrated_packet / "logs/conversations/010226-old_item.jsonl"

    assert preflight["replacement_token_count"] > 0
    assert preflight["eligible_reference_bytes"] < len(
        historical_content.encode("utf-8")
    )
    assert migrated_history.read_text(encoding="utf-8") == historical_content
    assert str(migrated_packet.relative_to(root)) in (
        migrated_packet / "work.yml"
    ).read_text(encoding="utf-8")
    assert result["post_run_invariants"] == {"move_count": 0, "collision_count": 0}


def test_keyboard_interrupt_rolls_back_and_writes_terminal_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, packet = _legacy_root(tmp_path)

    def interrupt(*_args: object, **_kwargs: object) -> list[str]:
        raise KeyboardInterrupt("regression fixture")

    monkeypatch.setattr(artifact_migration, "_rewrite_text_references", interrupt)
    with pytest.raises(KeyboardInterrupt, match="regression fixture"):
        apply_artifact_naming_plan(root, backup_dir=tmp_path / "interrupt-backup")

    assert packet.is_dir()
    assert not packet.with_name("010226-001_old_item").exists()
    receipts = list(
        (root / "harness/shared_factory/06-runs-and-logs/migrations").glob(
            "*/terminal-receipt.json"
        )
    )
    assert len(receipts) == 1
    terminal = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert terminal["status"] == "rolled_back"
    assert terminal["rollback_status"] == "completed"
    progress = json.loads(
        (receipts[0].parent / "progress.json").read_text(encoding="utf-8")
    )
    assert progress["status"] == "rolled_back"
    assert progress["phase"] == "terminal"


def test_existing_recovery_archive_avoids_copying_immutable_move_sources(
    tmp_path: Path,
) -> None:
    root, packet = _legacy_root(tmp_path)
    recovery_archive = tmp_path / "existing-full-recovery.tar.gz"
    recovery_manifest = tmp_path / "recovery-manifest.json"
    recovery_manifest.write_text('{"fixture": true}\n', encoding="utf-8")
    with tarfile.open(recovery_archive, "w:gz") as archive:
        archive.add(recovery_manifest, arcname="migration-plan.json")

    result = apply_artifact_naming_plan(
        root,
        backup_dir=tmp_path / "incremental-backup",
        recovery_backup_archive=recovery_archive,
    )
    with tarfile.open(result["backup_archive"], "r:gz") as archive:
        archived = set(archive.getnames())

    assert result["recovery_backup_archive"] == str(recovery_archive)
    assert result["preflight"]["move_sources_in_backup"] is False
    assert (
        result["preflight"]["recovery_backup"]["first_member"] == "migration-plan.json"
    )
    historical_prefix = str((packet / "logs/conversations").relative_to(root))
    assert not any(name.startswith(historical_prefix) for name in archived)


def test_live_mutation_lock_refusal_still_writes_terminal_receipt(
    tmp_path: Path,
) -> None:
    root, _packet = _legacy_root(tmp_path)
    lock = (
        root
        / "harness/shared_factory/00-control-plane/locks/artifact-date-prefix-migration.lock"
    )
    lock.parent.mkdir(parents=True)
    lock.write_text(
        json.dumps({"run_id": "live", "pid": os.getpid()}), encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="live PID"):
        apply_artifact_naming_plan(root, backup_dir=tmp_path / "unused-backup")

    receipts = list(
        (root / "harness/shared_factory/06-runs-and-logs/migrations").glob(
            "*/terminal-receipt.json"
        )
    )
    assert len(receipts) == 1
    terminal = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert terminal["status"] == "failed"
    assert terminal["error_type"] == "RuntimeError"


def test_fixed_string_matcher_handles_incident_scale_without_regex() -> None:
    fixture_path = (
        Path(__file__).parent / "fixtures/artifact_migration_unbounded_incident.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    replacements = [
        (f"/legacy/path/{index}", f"/dated/path/{index}")
        for index in range(fixture["replacement_tokens"])
    ]
    matcher, replace = artifact_migration._replacement_engine(replacements)

    assert matcher is not None
    assert not hasattr(matcher, "pattern")
    assert (
        replace("before /legacy/path/52343 after") == "before /dated/path/52343 after"
    )


def test_migration_respects_disabled_policy(tmp_path: Path) -> None:
    root, _ = _legacy_root(tmp_path)
    config = root / "harness/config/artifact-naming.yml"
    config.write_text(
        yaml.safe_dump({"artifact_naming": {"date_prefix": {"enabled": False}}}),
        encoding="utf-8",
    )

    assert build_artifact_naming_plan(root)["move_count"] == 0


def test_restore_reverses_names_references_and_state(tmp_path: Path) -> None:
    root, packet = _legacy_root(tmp_path)
    readonly = packet / "artifacts/pr-branch-work/repo/.git/objects/aa/object"
    readonly.parent.mkdir(parents=True)
    readonly.write_text("immutable fixture\n", encoding="utf-8")
    readonly.chmod(0o444)
    result = apply_artifact_naming_plan(root, backup_dir=tmp_path / "backup")

    restored = restore_artifact_naming_migration(result["receipt_path"], apply=True)

    assert restored["restored"] is True
    assert packet.is_dir()
    assert (packet / "logs/conversations/2026_01_02_old_item.jsonl").is_file()
    assert readonly.read_text(encoding="utf-8") == "immutable fixture\n"
    assert "001_old_item" in (packet / "work.yml").read_text(encoding="utf-8")
    conn = db.connect(db.default_db_path(root))
    try:
        assert work_items.get(conn, "acme:app:001_old_item") is not None
    finally:
        conn.close()


def test_git_worktree_is_moved_through_git_metadata(tmp_path: Path) -> None:
    root = tmp_path / "os"
    (root / "harness/config").mkdir(parents=True)
    (root / "harness/config/artifact-naming.yml").write_text(
        render_default_artifact_naming_config(), encoding="utf-8"
    )
    project = root / "domains/acme/projects/app"
    worktrees = project / "worktrees"
    worktrees.mkdir(parents=True)
    repository = tmp_path / "repository"
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.name", "Test User"], check=True
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "test@example.com"],
        check=True,
    )
    (repository / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-qm", "fixture"], check=True
    )
    checkout = worktrees / "old-checkout"
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "worktree",
            "add",
            "-qb",
            "feature/test",
            str(checkout),
        ],
        check=True,
    )
    (worktrees / "index.yml").write_text(
        yaml.safe_dump(
            {
                "worktrees": [
                    {
                        "id": "old-checkout",
                        "path": str(checkout),
                        "created_at": "2026-01-02T03:04:05Z",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    plan = build_artifact_naming_plan(root)
    move = next(item for item in plan["moves"] if item["kind"] == "worktree")
    assert move["method"] == "git_worktree"
    result = apply_artifact_naming_plan(root, backup_dir=tmp_path / "git-backup")
    destination = worktrees / "010226-old-checkout"

    assert destination.is_dir()
    registered = subprocess.run(
        ["git", "-C", str(repository), "worktree", "list", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert str(destination) in registered
    assert result["collisions"] == []


def test_external_worktree_target_path_is_not_rewritten(tmp_path: Path) -> None:
    root = tmp_path / "os"
    (root / "harness/config").mkdir(parents=True)
    (root / "harness/config/artifact-naming.yml").write_text(
        render_default_artifact_naming_config(), encoding="utf-8"
    )
    worktrees = root / "domains/acme/projects/app/worktrees"
    worktrees.mkdir(parents=True)
    external = tmp_path / "old-checkout"
    external.mkdir()
    link = worktrees / "old-checkout"
    link.symlink_to(external, target_is_directory=True)
    (worktrees / "index.yml").write_text(
        yaml.safe_dump(
            {
                "worktrees": [
                    {
                        "id": "old-checkout",
                        "path": str(external),
                        "link": "worktrees/old-checkout",
                        "created_at": "2026-01-02T03:04:05Z",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    apply_artifact_naming_plan(root, backup_dir=tmp_path / "external-backup")
    migrated_link = worktrees / "010226-old-checkout"
    registry = yaml.safe_load((worktrees / "index.yml").read_text(encoding="utf-8"))
    entry = registry["worktrees"][0]

    assert migrated_link.is_symlink()
    assert migrated_link.resolve() == external.resolve()
    assert entry["id"] == "010226-old-checkout"
    assert entry["link"] == "worktrees/010226-old-checkout"
    assert entry["path"] == str(external)


def test_standalone_clone_uses_filesystem_rename(tmp_path: Path) -> None:
    root = tmp_path / "os"
    (root / "harness/config").mkdir(parents=True)
    (root / "harness/config/artifact-naming.yml").write_text(
        render_default_artifact_naming_config(), encoding="utf-8"
    )
    worktrees = root / "domains/acme/projects/app/worktrees"
    worktrees.mkdir(parents=True)
    checkout = worktrees / "standalone-clone"
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    (worktrees / "index.yml").write_text(
        yaml.safe_dump(
            {
                "worktrees": [
                    {
                        "id": "standalone-clone",
                        "path": str(checkout),
                        "link": "worktrees/standalone-clone",
                        "created_at": "2026-01-02T03:04:05Z",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    plan = build_artifact_naming_plan(root)
    move = next(item for item in plan["moves"] if item["kind"] == "worktree")
    assert move["method"] == "rename"
    apply_artifact_naming_plan(root, backup_dir=tmp_path / "clone-backup")
    destination = worktrees / "010226-standalone-clone"

    assert destination.is_dir()
    assert (
        subprocess.run(
            ["git", "-C", str(destination), "rev-parse", "--is-inside-work-tree"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        == "true"
    )


def test_linked_worktree_with_submodule_is_renamed_and_repaired(tmp_path: Path) -> None:
    root = tmp_path / "os"
    (root / "harness/config").mkdir(parents=True)
    (root / "harness/config/artifact-naming.yml").write_text(
        render_default_artifact_naming_config(), encoding="utf-8"
    )
    worktrees = root / "domains/acme/projects/app/worktrees"
    worktrees.mkdir(parents=True)
    submodule = tmp_path / "submodule"
    subprocess.run(["git", "init", "-q", str(submodule)], check=True)
    subprocess.run(
        ["git", "-C", str(submodule), "config", "user.name", "Test User"], check=True
    )
    subprocess.run(
        ["git", "-C", str(submodule), "config", "user.email", "test@example.com"],
        check=True,
    )
    (submodule / "module.txt").write_text("module\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(submodule), "add", "module.txt"], check=True)
    subprocess.run(["git", "-C", str(submodule), "commit", "-qm", "module"], check=True)
    repository = tmp_path / "repository-with-submodule"
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.name", "Test User"], check=True
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            "-q",
            str(submodule),
            "module",
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-qm", "fixture"], check=True
    )
    checkout = worktrees / "submodule-worktree"
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "worktree",
            "add",
            "-qb",
            "feature/submodule",
            str(checkout),
        ],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "update",
            "--init",
            "-q",
        ],
        check=True,
    )
    submodule_git_file = checkout / "module/.git"
    original_gitdir = (
        submodule_git_file.read_text(encoding="utf-8").strip().split(":", 1)[1].strip()
    )
    if Path(original_gitdir).is_absolute():
        stale_gitdir = f"/stale-prefix{original_gitdir}"
    else:
        stale_gitdir = f"../stale-prefix/{original_gitdir}"
    submodule_git_file.write_text(f"gitdir: {stale_gitdir}\n", encoding="utf-8")
    assert (
        subprocess.run(
            ["git", "-C", str(checkout / "module"), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        ).returncode
        != 0
    )
    (worktrees / "index.yml").write_text(
        yaml.safe_dump(
            {
                "worktrees": [
                    {
                        "id": "submodule-worktree",
                        "path": str(checkout),
                        "link": "worktrees/submodule-worktree",
                        "created_at": "2026-01-02T03:04:05Z",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    plan = build_artifact_naming_plan(root)
    move = next(item for item in plan["moves"] if item["kind"] == "worktree")
    assert move["method"] == "git_worktree_repair"
    apply_artifact_naming_plan(root, backup_dir=tmp_path / "submodule-backup")
    destination = worktrees / "010226-submodule-worktree"

    assert (
        subprocess.run(
            ["git", "-C", str(destination), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == ""
    )
    assert (
        subprocess.run(
            ["git", "-C", str(destination / "module"), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == ""
    )
