from __future__ import annotations

import json
from pathlib import Path
import subprocess

import yaml
import pytest

import genomes_agentic_os.release_reinstall as release_reinstall
from genomes_agentic_os.library import (
    MANIFEST_API_VERSION,
    init_library,
    object_relative_path,
    refresh_registry,
    verify_library_install,
)
from genomes_agentic_os.release_reinstall import (
    ROLLBACK_DRILL_MARKER,
    rollback_drill,
    update_policy_decision,
    verify_reinstall,
    watch_release,
)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _root(path: Path, *, version: str = "1.2.3", policy: str = "auto_patch_minor") -> Path:
    path.mkdir(parents=True)
    (path / ".agentic_root").write_text("agentic-os\n", encoding="utf-8")
    lock = path / "harness/agentic-os.lock.json"
    lock.parent.mkdir(parents=True)
    lock.write_text(
        json.dumps({"installed_version": version, "update_policy": policy}) + "\n",
        encoding="utf-8",
    )
    return path


def _object(root: Path, object_id: str) -> None:
    target = root / "lib" / object_relative_path("skill", object_id)
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text(f"# {object_id}\n", encoding="utf-8")
    (target / "object.yml").write_text(
        yaml.safe_dump(
            {
                "api_version": MANIFEST_API_VERSION,
                "kind": "skill",
                "id": object_id,
                "title": object_id,
                "description": "Release reinstall test object.",
                "status": "active",
                "scope": {"level": "root", "domain": None, "project": None},
                "owner": {"type": "operator", "id": "Genome"},
                "entrypoint": "SKILL.md",
                "tags": [],
                "dependencies": [],
                "aliases": [],
                "runtime": {},
                "validation": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _source(tmp_path: Path) -> tuple[Path, Path, str]:
    source_root = _root(tmp_path / "source")
    init_library(source_root, dry_run=False, initialize_git=True)
    source = source_root / "lib"
    _git(source, "config", "user.email", "test@example.com")
    _git(source, "config", "user.name", "Test")
    _object(source_root, "first")
    refresh_registry(source_root, dry_run=False)
    _git(source, "add", "-A")
    _git(source, "commit", "--no-verify", "-m", "first library")
    first_revision = _git(source, "rev-parse", "HEAD")
    _git(source, "tag", "v1.2.4")
    remote = tmp_path / "library.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    _git(source, "remote", "add", "origin", str(remote))
    _git(source, "push", "-u", "origin", "main")
    _git(source, "push", "origin", "--tags")
    return source_root, remote, first_revision


def _release(path: Path, version: str, revision: str) -> Path:
    path.write_text(
        json.dumps(
            {
                "published": True,
                "draft": False,
                "version": version,
                "tag": f"v{version}",
                "source_revision": revision,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_policy_auto_applies_patch_minor_and_keeps_major_and_legacy_policy_gated(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path / "target")

    assert update_policy_decision(root, "1.2.4")["status"] == "eligible"
    assert update_policy_decision(root, "1.3.0")["status"] == "eligible"
    assert update_policy_decision(root, "2.0.0")["status"] == "approval_required"

    legacy = _root(tmp_path / "legacy", policy="operator_approved")
    assert update_policy_decision(legacy, "1.2.4")["status"] == "approval_required"


def test_watch_reinstalls_once_verifies_receipts_and_exercises_marked_rollback_drill(
    tmp_path: Path,
) -> None:
    source_root, remote, first_revision = _source(tmp_path)
    target = _root(tmp_path / "target")
    first_release = _release(tmp_path / "first-release.json", "1.2.4", first_revision)

    planned = watch_release(target, release_receipt=first_release, repository=str(remote))
    assert planned["status"] == "planned"
    assert not (target / "lib").exists()

    applied = watch_release(
        target,
        release_receipt=first_release,
        repository=str(remote),
        apply=True,
    )
    assert applied["status"] == "reinstalled"
    assert applied["verification"]["status"] == "verified"
    assert watch_release(target, release_receipt=first_release)["status"] == "already_processed"

    source = source_root / "lib"
    _object(source_root, "second")
    refresh_registry(source_root, dry_run=False)
    _git(source, "add", "-A")
    _git(source, "commit", "--no-verify", "-m", "second library")
    second_revision = _git(source, "rev-parse", "HEAD")
    _git(source, "tag", "v1.3.0")
    _git(source, "push", "origin", "main")
    _git(source, "push", "origin", "--tags")
    second_release = _release(tmp_path / "second-release.json", "1.3.0", second_revision)

    second = watch_release(
        target,
        release_receipt=second_release,
        repository=str(remote),
        apply=True,
    )
    assert second["status"] == "reinstalled"
    assert second["verification"]["status"] == "verified"
    assert second["install"]["rollback_available"] is True

    (target / ROLLBACK_DRILL_MARKER).write_text("test target\n", encoding="utf-8")
    drill = rollback_drill(target, apply=True)
    assert drill["status"] == "completed"
    assert drill["rollback"]["source_revision"] == first_revision


def test_verification_fails_loudly_for_a_release_revision_mismatch(tmp_path: Path) -> None:
    _source_root, remote, revision = _source(tmp_path)
    target = _root(tmp_path / "target")
    release = _release(tmp_path / "release.json", "1.2.4", revision)
    assert watch_release(target, release_receipt=release, repository=str(remote), apply=True)["status"] == "reinstalled"

    wrong_release = _release(tmp_path / "wrong.json", "1.2.4", "a" * 40)
    verification = verify_reinstall(target, json.loads(wrong_release.read_text(encoding="utf-8")))
    assert verification["status"] == "failed"
    assert "source revision" in verification["errors"][0]


def test_watcher_rolls_back_a_failed_post_install_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, remote, first_revision = _source(tmp_path)
    target = _root(tmp_path / "target")
    first_release = _release(tmp_path / "first-release.json", "1.2.4", first_revision)
    assert watch_release(
        target,
        release_receipt=first_release,
        repository=str(remote),
        apply=True,
    )["status"] == "reinstalled"

    source = source_root / "lib"
    _object(source_root, "second")
    refresh_registry(source_root, dry_run=False)
    _git(source, "add", "-A")
    _git(source, "commit", "--no-verify", "-m", "second library")
    second_revision = _git(source, "rev-parse", "HEAD")
    _git(source, "tag", "v1.3.0")
    _git(source, "push", "origin", "main")
    _git(source, "push", "origin", "--tags")
    second_release = _release(tmp_path / "second-release.json", "1.3.0", second_revision)

    monkeypatch.setattr(
        release_reinstall,
        "verify_reinstall",
        lambda *_args, **_kwargs: {"status": "failed", "errors": ["forced mismatch"]},
    )
    result = release_reinstall.watch_release(
        target,
        release_receipt=second_release,
        repository=str(remote),
        apply=True,
    )

    assert result["status"] == "rolled_back"
    assert result["rollback"]["verification"]["status"] == "verified"
    assert verify_library_install(target)["source_revision"] == first_revision
