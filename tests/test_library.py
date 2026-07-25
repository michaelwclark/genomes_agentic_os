from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import threading

import pytest
import yaml

import genomes_agentic_os.library as library_module
from genomes_agentic_os.cli import main
from genomes_agentic_os.library import (
    MANIFEST_API_VERSION,
    UNIFIED_REGISTRY,
    LibraryError,
    apply_legacy_migration,
    canonical_object_id,
    create_object,
    init_library,
    install_library,
    legacy_migration_plan,
    library_doctor,
    object_relative_path,
    query_objects,
    refresh_registry,
    verify_library_install,
)
from genomes_agentic_os.validate import ValidationResult, validate_object_library


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "os"
    root.mkdir(parents=True)
    (root / ".agentic_root").write_text("agentic-os\n", encoding="utf-8")
    return root


def _object(
    root: Path,
    kind: str,
    object_id: str,
    *,
    level: str = "root",
    domain: str | None = None,
    project: str | None = None,
    entrypoint: str,
) -> Path:
    relative = object_relative_path(
        kind,
        object_id,
        level=level,
        domain=domain,
        project=project,
    )
    target = root / "lib" / relative
    target.mkdir(parents=True, exist_ok=True)
    (target / entrypoint).write_text(f"# {object_id}\n", encoding="utf-8")
    manifest = {
        "api_version": MANIFEST_API_VERSION,
        "kind": kind,
        "id": object_id,
        "title": object_id,
        "description": "Test object.",
        "status": "active",
        "scope": {"level": level, "domain": domain, "project": project},
        "owner": {"type": "operator", "id": "Genome"},
        "entrypoint": entrypoint,
        "tags": [],
        "dependencies": [],
        "aliases": [],
        "runtime": {},
        "validation": {},
    }
    (target / "object.yml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return target


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _library_remote(tmp_path: Path, *, stale: bool = False) -> tuple[Path, str]:
    source_root = tmp_path / "source-os"
    source_root.mkdir()
    (source_root / ".agentic_root").write_text("agentic-os\n", encoding="utf-8")
    init_library(source_root, dry_run=False, initialize_git=True)
    source = source_root / "lib"
    _git(source, "config", "user.email", "test@example.com")
    _git(source, "config", "user.name", "Test")
    _object(source_root, "skill", "from-source", entrypoint="SKILL.md")
    refresh_registry(source_root, dry_run=False)
    if stale:
        (source / "skills/root/from-source/SKILL.md").write_text(
            "# Changed after registry\n",
            encoding="utf-8",
        )
    _git(source, "add", "-A")
    _git(source, "commit", "--no-verify", "-m", "seed library")
    revision = _git(source, "rev-parse", "HEAD")
    remote = tmp_path / "library.git"
    subprocess.run(
        ["git", "init", "--bare", str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(source, "remote", "add", "origin", str(remote))
    _git(source, "push", "-u", "origin", "main")
    return remote, revision


def test_scope_paths_and_ids() -> None:
    assert object_relative_path("program", "one") == Path("programs/root/one")
    assert object_relative_path("workflow", "two", level="domain", domain="los") == Path(
        "workflows/domains/los/two"
    )
    assert object_relative_path(
        "automation",
        "three",
        level="project",
        domain="los",
        project="django",
    ) == Path("automations/domains/los/projects/django/three")
    assert canonical_object_id(
        "automation",
        "three",
        level="project",
        domain="los",
        project="django",
    ) == "automation:project:los:django:three"


def test_init_is_dry_run_first_and_can_initialize_git(tmp_path: Path) -> None:
    root = _root(tmp_path)
    planned = init_library(root, dry_run=True, initialize_git=True)
    assert planned["status"] == "planned"
    assert not (root / "lib").exists()

    applied = init_library(root, dry_run=False, initialize_git=True)
    assert applied["status"] == "initialized"
    assert (root / "lib/.git").exists()
    assert (root / UNIFIED_REGISTRY).is_file()
    assert (
        __import__("subprocess")
        .run(
            ["git", "-C", str(root / "lib"), "config", "--get", "core.hooksPath"],
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
        == ".githooks"
    )


def test_create_object_is_dry_run_first_and_refreshes_registry(tmp_path: Path) -> None:
    root = _root(tmp_path)
    init_library(root, dry_run=False)
    planned = create_object(root, "program", "night_shift", domain="los", level="domain")
    assert planned["status"] == "planned"
    assert not (root / "lib/programs/domains/los/night_shift").exists()

    created = create_object(
        root,
        "program",
        "night_shift",
        domain="los",
        level="domain",
        description="Run the night shift.",
        dry_run=False,
    )
    assert created["status"] == "created"
    assert len(query_objects(root, kind="program", domain="los")) == 1


def test_refresh_writes_unified_and_per_type_registries_idempotently(tmp_path: Path) -> None:
    root = _root(tmp_path)
    init_library(root, dry_run=False)
    _object(root, "skill", "review", entrypoint="SKILL.md")
    _object(root, "program", "delivery", level="domain", domain="los", entrypoint="program.md")

    first = refresh_registry(root, dry_run=False)
    assert first["status"] == "refreshed"
    payload = json.loads((root / UNIFIED_REGISTRY).read_text(encoding="utf-8"))
    assert payload["object_count"] == 2
    assert (root / "lib/registry/skills.yml").is_file()
    assert (root / "lib/registry/programs.yml").is_file()

    second = refresh_registry(root, dry_run=False)
    assert second["status"] == "unchanged"
    assert len(query_objects(root, domain="los")) == 1


def test_doctor_reports_stale_registry(tmp_path: Path) -> None:
    root = _root(tmp_path)
    init_library(root, dry_run=False)
    _object(root, "command", "one", entrypoint="command.md")
    result = library_doctor(root)
    assert result["status"] == "failed"
    assert any(item["code"] == "registry_stale" for item in result["diagnostics"])


def test_definition_change_makes_registry_stale(tmp_path: Path) -> None:
    root = _root(tmp_path)
    init_library(root, dry_run=False)
    target = _object(root, "command", "one", entrypoint="command.md")
    refresh_registry(root, dry_run=False)
    (target / "command.md").write_text("# One\n\nChanged.\n", encoding="utf-8")
    result = library_doctor(root)
    assert any(item["code"] == "registry_stale" for item in result["diagnostics"])


def test_install_clones_validates_and_atomically_replaces_projection(tmp_path: Path) -> None:
    remote, revision = _library_remote(tmp_path)
    root = _root(tmp_path / "target")
    init_library(root, dry_run=False)
    _object(root, "command", "old", entrypoint="command.md")
    refresh_registry(root, dry_run=False)

    blocked = install_library(root, repository=str(remote), dry_run=True)
    assert blocked["status"] == "blocked"
    assert blocked["existing"]["projection_dirty"] is True
    planned = install_library(
        root,
        repository=str(remote),
        replace_dirty=True,
        dry_run=True,
    )
    assert planned["status"] == "planned"
    assert not (root / "runtime").exists()
    assert query_objects(root, kind="command")[0]["id"] == "old"
    applied = install_library(
        root,
        repository=str(remote),
        replace_dirty=True,
        dry_run=False,
    )

    assert applied["status"] == "installed"
    assert applied["source_revision"] == revision
    assert not (root / "lib/.git").exists()
    assert not query_objects(root, kind="command")
    assert len(query_objects(root, kind="skill")) == 1
    assert (root / applied["rollback_path"]).is_dir()
    assert verify_library_install(root)["status"] == "verified"
    assert library_doctor(root)["status"] == "healthy"

    installed_entrypoint = root / "lib/skills/root/from-source/SKILL.md"
    installed_entrypoint.write_text("# Locally changed\n", encoding="utf-8")
    assert verify_library_install(root)["status"] == "failed"


def test_pristine_managed_placeholder_allows_first_external_install_without_override(
    tmp_path: Path,
) -> None:
    remote, revision = _library_remote(tmp_path)
    root = tmp_path / "installed-os"
    assert main(["init", "--target", str(root)]) == 0

    planned = install_library(root, repository=str(remote), dry_run=True)
    assert planned["status"] == "planned"
    assert planned["existing"]["managed_placeholder"] is True
    assert planned["existing"]["projection_dirty"] is False
    installed = install_library(root, repository=str(remote), dry_run=False)
    assert installed["status"] == "installed"
    assert installed["source_revision"] == revision
    assert verify_library_install(root)["status"] == "verified"


def test_init_never_mutates_receipt_backed_library_and_ignores_python_cache(
    tmp_path: Path,
) -> None:
    remote, _ = _library_remote(tmp_path)
    root = tmp_path / "installed-os"
    assert main(["init", "--target", str(root)]) == 0
    install_library(root, repository=str(remote), dry_run=False)
    before_projection = library_module._projection_sha256(root / "lib")
    before_receipt = (root / library_module.INSTALL_RECEIPT).read_bytes()
    before_registry = (root / UNIFIED_REGISTRY).read_bytes()

    cache = root / "lib/skills/root/from-source/__pycache__"
    cache.mkdir()
    (cache / "runtime.cpython-313.pyc").write_bytes(b"runtime-cache")
    assert verify_library_install(root)["status"] == "verified"

    initialized = init_library(root, dry_run=False)
    assert initialized["status"] == "preserved"
    assert main(["init", "--target", str(root)]) == 0
    assert (root / library_module.INSTALL_RECEIPT).read_bytes() == before_receipt
    assert (root / UNIFIED_REGISTRY).read_bytes() == before_registry
    assert library_module._projection_sha256(root / "lib") == before_projection
    assert verify_library_install(root)["status"] == "verified"


def test_install_discards_ignored_validator_outputs_before_projection(
    tmp_path: Path,
) -> None:
    remote, _ = _library_remote(tmp_path)
    source = tmp_path / "source-os" / "lib"
    (source / ".gitignore").write_text("dist/\n", encoding="utf-8")
    validator = source / "scripts" / "validate_library.py"
    validator.parent.mkdir(parents=True)
    validator.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "repo = Path(sys.argv[sys.argv.index('--repo') + 1])\n"
        "output = repo / 'dist' / 'validation-receipt.json'\n"
        "output.parent.mkdir(parents=True, exist_ok=True)\n"
        "output.write_text('verified\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    _git(source, "add", ".gitignore", "scripts/validate_library.py")
    _git(source, "commit", "--no-verify", "-m", "add standalone validator")
    _git(source, "push", "origin", "main")

    root = _root(tmp_path / "target")
    installed = install_library(root, repository=str(remote), dry_run=False)

    assert installed["status"] == "installed"
    assert not (root / "lib" / "dist").exists()
    assert verify_library_install(root)["status"] == "verified"


def test_installed_projection_drift_blocks_replacement_without_override(tmp_path: Path) -> None:
    remote, _ = _library_remote(tmp_path)
    root = _root(tmp_path / "target")
    install_library(root, repository=str(remote), dry_run=False)
    installed_entrypoint = root / "lib/skills/root/from-source/SKILL.md"
    installed_entrypoint.write_text("# Uncaptured local edit\n", encoding="utf-8")

    blocked = install_library(root, repository=str(remote), dry_run=False)

    assert blocked["status"] == "blocked"
    assert blocked["existing"]["projection_dirty"] is True
    assert "install receipt" in blocked["blocker"]
    assert installed_entrypoint.read_text(encoding="utf-8") == "# Uncaptured local edit\n"

    replaced = install_library(
        root,
        repository=str(remote),
        replace_dirty=True,
        dry_run=False,
    )
    assert replaced["replaced_projection_drift"] is True
    assert verify_library_install(root)["status"] == "verified"


def test_verify_covers_top_level_content_and_exact_registry_projections(tmp_path: Path) -> None:
    remote, _ = _library_remote(tmp_path)
    source = tmp_path / "source-os/lib"
    script = source / "scripts/library_check.py"
    schema = source / "schemas/library-object-extra.json"
    script.parent.mkdir(parents=True)
    schema.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("print('checked')\n", encoding="utf-8")
    schema.write_text('{"type": "object"}\n', encoding="utf-8")
    _git(source, "add", "scripts/library_check.py", "schemas/library-object-extra.json")
    _git(source, "commit", "--no-verify", "-m", "add top-level source assets")
    _git(source, "push", "origin", "main")

    root = _root(tmp_path / "target")
    install_library(root, repository=str(remote), dry_run=False)
    installed_script = root / "lib/scripts/library_check.py"
    installed_schema = root / "lib/schemas/library-object-extra.json"

    for target, replacement in (
        (installed_script, "print('tampered')\n"),
        (installed_schema, '{"type": "array"}\n'),
    ):
        original = target.read_bytes()
        target.write_text(replacement, encoding="utf-8")
        assert verify_library_install(root)["status"] == "failed"
        target.write_bytes(original)
        assert verify_library_install(root)["status"] == "verified"

    unified = root / UNIFIED_REGISTRY
    original_unified = unified.read_bytes()
    unified_payload = json.loads(original_unified)
    unified_payload["objects"][0]["title"] = "Tampered registry title"
    unified.write_text(json.dumps(unified_payload, indent=2) + "\n", encoding="utf-8")
    unified_verification = verify_library_install(root)
    assert unified_verification["status"] == "failed"
    assert any(
        item["code"] == "registry_stale"
        for item in unified_verification["diagnostics"]
    )
    unified.write_bytes(original_unified)
    assert verify_library_install(root)["status"] == "verified"

    typed = root / "lib/registry/skills.yml"
    original_typed = typed.read_bytes()
    typed_payload = yaml.safe_load(original_typed)
    typed_payload["skills"][0]["title"] = "Tampered typed title"
    typed.write_text(yaml.safe_dump(typed_payload, sort_keys=False), encoding="utf-8")
    typed_verification = verify_library_install(root)
    assert typed_verification["status"] == "failed"
    assert any(
        item["code"] == "type_registry_stale"
        for item in typed_verification["diagnostics"]
    )
    typed.write_bytes(original_typed)
    assert verify_library_install(root)["status"] == "verified"


def test_install_lock_serializes_overlapping_applies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote, _ = _library_remote(tmp_path)
    root = _root(tmp_path / "target")
    original_git_output = library_module._git_output
    first_clone_started = threading.Event()
    release_first_clone = threading.Event()
    second_clone_started = threading.Event()
    clone_count = 0
    count_lock = threading.Lock()

    def gated_git_output(*args: str, cwd: Path | None = None) -> str:
        nonlocal clone_count
        if args[:2] == ("clone", "--filter=blob:none"):
            with count_lock:
                clone_count += 1
                index = clone_count
            if index == 1:
                first_clone_started.set()
                if not release_first_clone.wait(timeout=10):
                    raise AssertionError("timed out waiting to release first clone")
            elif index == 2:
                second_clone_started.set()
        return original_git_output(*args, cwd=cwd)

    monkeypatch.setattr(library_module, "_git_output", gated_git_output)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            install_library,
            root,
            repository=str(remote),
            dry_run=False,
        )
        assert first_clone_started.wait(timeout=10)
        second = executor.submit(
            install_library,
            root,
            repository=str(remote),
            dry_run=False,
        )
        try:
            assert not second_clone_started.wait(timeout=0.2)
        finally:
            release_first_clone.set()
        assert first.result(timeout=20)["status"] == "installed"
        assert second.result(timeout=20)["status"] == "installed"
    assert second_clone_started.is_set()
    assert verify_library_install(root)["status"] == "verified"


def test_keyboard_interrupt_after_swap_restores_projection_and_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote, _ = _library_remote(tmp_path)
    root = _root(tmp_path / "target")
    install_library(root, repository=str(remote), dry_run=False)
    before_projection = library_module._projection_sha256(root / "lib")
    before_receipt = (root / library_module.INSTALL_RECEIPT).read_bytes()
    original_write_journal = library_module._write_install_journal

    def interrupt_after_swap(path: Path, journal: dict[str, object]) -> None:
        original_write_journal(path, journal)
        if journal.get("phase") == "swapped":
            raise KeyboardInterrupt

    monkeypatch.setattr(library_module, "_write_install_journal", interrupt_after_swap)
    with pytest.raises(KeyboardInterrupt):
        install_library(root, repository=str(remote), dry_run=False)

    assert library_module._projection_sha256(root / "lib") == before_projection
    assert (root / library_module.INSTALL_RECEIPT).read_bytes() == before_receipt
    assert not (root / library_module.INSTALL_JOURNAL).exists()
    assert verify_library_install(root)["status"] == "verified"


def test_persisted_swap_journal_is_dry_run_safe_and_restart_recoverable(
    tmp_path: Path,
) -> None:
    remote, _ = _library_remote(tmp_path)
    root = _root(tmp_path / "target")
    install_library(root, repository=str(remote), dry_run=False)
    previous_projection = library_module._projection_sha256(root / "lib")
    previous_receipt = (root / library_module.INSTALL_RECEIPT).read_bytes()
    run_id = "persisted-interruption"
    backup = root / library_module.INSTALL_BACKUP_DIR / run_id
    receipt_backup = root / library_module.INSTALL_RECEIPT_BACKUP_DIR / f"{run_id}.json"
    staging_root = root / "runtime/tmp" / f"library-install-{run_id}"
    success_receipt = root / library_module.INSTALL_RECEIPT_DIR / f"{run_id}.json"
    backup.parent.mkdir(parents=True, exist_ok=True)
    staging_root.mkdir(parents=True)
    library_module._atomic_write(receipt_backup, previous_receipt)
    journal = {
        "api_version": library_module.INSTALL_JOURNAL_API_VERSION,
        "action": "library.install-transaction",
        "run_id": run_id,
        "phase": "swapped",
        "repository": str(remote),
        "requested_ref": "main",
        "staging_root": staging_root.relative_to(root).as_posix(),
        "backup": backup.relative_to(root).as_posix(),
        "previous_receipt_backup": receipt_backup.relative_to(root).as_posix(),
        "success_receipt": success_receipt.relative_to(root).as_posix(),
        "had_previous_target": True,
        "had_previous_receipt": True,
        "previous_projection_sha256": previous_projection,
    }
    library_module._write_install_journal(root, journal)
    (root / "lib").replace(backup)
    shutil.copytree(backup, root / "lib")
    (root / "lib/skills/root/from-source/SKILL.md").write_text(
        "# Interrupted replacement\n",
        encoding="utf-8",
    )

    dry_run = install_library(root, repository=str(remote), dry_run=True)
    assert dry_run["status"] == "blocked"
    assert (root / library_module.INSTALL_JOURNAL).exists()
    assert library_module._projection_sha256(root / "lib") != previous_projection

    with library_module._install_lock(root):
        recovery = library_module._recover_install_transaction(root)

    assert recovery == {"status": "rolled_back", "run_id": run_id}
    assert library_module._projection_sha256(root / "lib") == previous_projection
    assert (root / library_module.INSTALL_RECEIPT).read_bytes() == previous_receipt
    assert not (root / library_module.INSTALL_JOURNAL).exists()
    assert not receipt_backup.exists()
    assert not success_receipt.exists()
    assert verify_library_install(root)["status"] == "verified"


def test_install_resolves_branch_tag_and_commit_refs(tmp_path: Path) -> None:
    remote, _ = _library_remote(tmp_path)
    source_root = tmp_path / "source-os"
    source = source_root / "lib"
    _git(source, "checkout", "-b", "alternate")
    (source / "skills/root/from-source/SKILL.md").write_text(
        "# Alternate revision\n",
        encoding="utf-8",
    )
    refresh_registry(source_root, dry_run=False)
    _git(source, "add", "-A")
    _git(source, "commit", "--no-verify", "-m", "alternate revision")
    revision = _git(source, "rev-parse", "HEAD")
    _git(source, "tag", "exact-tag")
    _git(source, "push", "origin", "alternate")
    _git(source, "push", "origin", "exact-tag")

    for index, ref in enumerate(("alternate", "exact-tag", revision)):
        root = _root(tmp_path / f"target-{index}")
        applied = install_library(
            root,
            repository=str(remote),
            ref=ref,
            dry_run=False,
        )
        assert applied["source_revision"] == revision
        assert verify_library_install(root)["status"] == "verified"


def test_successful_install_retains_receipt_bound_generation_and_rolls_back(
    tmp_path: Path,
) -> None:
    remote, first_revision = _library_remote(tmp_path)
    root = _root(tmp_path / "target")
    first = install_library(root, repository=str(remote), dry_run=False)
    first_receipt_bytes = (root / library_module.INSTALL_RECEIPT).read_bytes()
    first_projection_sha256 = first["projection_sha256"]
    source_root = tmp_path / "source-os"
    source = source_root / "lib"
    (source / "skills/root/from-source/SKILL.md").write_text(
        "# Second generation\n",
        encoding="utf-8",
    )
    refresh_registry(source_root, dry_run=False)
    _git(source, "add", "-A")
    _git(source, "commit", "--no-verify", "-m", "second generation")
    second_revision = _git(source, "rev-parse", "HEAD")
    _git(source, "push", "origin", "main")

    second = install_library(root, repository=str(remote), dry_run=False)
    second_receipt_bytes = (root / library_module.INSTALL_RECEIPT).read_bytes()
    second_projection_sha256 = second["projection_sha256"]
    retained_projection = root / second["rollback_path"]
    retained_receipt = root / second["rollback_receipt"]

    assert second_revision != first_revision
    assert second["rollback_available"] is True
    assert library_module._projection_sha256(retained_projection) == first_projection_sha256
    assert retained_receipt.read_bytes() == first_receipt_bytes
    assert hashlib.sha256(first_receipt_bytes).hexdigest() == second[
        "rollback_receipt_sha256"
    ]

    planned = library_module.rollback_library_install(root)
    assert planned["status"] == "planned"
    assert planned["source_revision"] == first_revision
    restored = library_module.rollback_library_install(root, dry_run=False)

    assert restored["status"] == "rolled_back"
    assert restored["source_revision"] == first_revision
    assert restored["verification"]["status"] == "verified"
    assert (root / library_module.INSTALL_RECEIPT).read_bytes() == first_receipt_bytes
    assert library_module._projection_sha256(root / "lib") == first_projection_sha256
    assert (
        root / "lib/skills/root/from-source/SKILL.md"
    ).read_text(encoding="utf-8") == "# from-source\n"
    assert verify_library_install(root)["status"] == "verified"

    replaced_projection = root / restored["replaced_backup_path"]
    replaced_receipt = root / restored["replaced_receipt_path"]
    assert library_module._projection_sha256(replaced_projection) == second_projection_sha256
    assert replaced_receipt.read_bytes() == second_receipt_bytes


def test_rollback_blocks_when_retained_receipt_no_longer_matches(tmp_path: Path) -> None:
    remote, _ = _library_remote(tmp_path)
    root = _root(tmp_path / "target")
    install_library(root, repository=str(remote), dry_run=False)
    install_library(root, repository=str(remote), dry_run=False)
    receipt = json.loads(
        (root / library_module.INSTALL_RECEIPT).read_text(encoding="utf-8")
    )
    retained_receipt = root / receipt["rollback_receipt"]
    retained_receipt.write_text("{}\n", encoding="utf-8")

    blocked = library_module.rollback_library_install(root)

    assert blocked["status"] == "blocked"
    assert "receipt hash" in blocked["blocker"]
    assert verify_library_install(root)["status"] == "verified"


def test_install_rolls_back_post_replace_verification_failure_without_success_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote, _ = _library_remote(tmp_path)
    root = _root(tmp_path / "target")
    init_library(root, dry_run=False)
    _object(root, "command", "old", entrypoint="command.md")
    refresh_registry(root, dry_run=False)
    before = library_doctor(root)["content_sha256"]

    monkeypatch.setattr(
        library_module,
        "verify_library_install",
        lambda _root: {"status": "failed"},
    )
    with pytest.raises(LibraryError, match="receipt-backed verification"):
        install_library(
            root,
            repository=str(remote),
            replace_dirty=True,
            dry_run=False,
        )

    assert library_doctor(root)["content_sha256"] == before
    assert query_objects(root, kind="command")[0]["id"] == "old"
    assert not (root / "runtime/state/library-install.json").exists()
    receipts = root / "runtime/artifacts/library-installs"
    assert not receipts.exists() or not list(receipts.glob("*.json"))
    backups = root / "runtime/backups/library"
    assert not backups.exists() or not list(backups.iterdir())


@pytest.mark.parametrize(
    ("secret_repository", "safe_repository", "secret_markers"),
    (
        (
            "https://operator:super-secret@example.invalid/library.git",
            "https://example.invalid/library.git",
            ("operator", "super-secret"),
        ),
        (
            "super-secret@example.invalid:org/library.git",
            "example.invalid:org/library.git",
            ("super-secret",),
        ),
    ),
)
def test_install_redacts_repository_credentials_from_plan_receipt_and_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    secret_repository: str,
    safe_repository: str,
    secret_markers: tuple[str, ...],
) -> None:
    remote, _ = _library_remote(tmp_path)
    root = _root(tmp_path / "target")

    planned = install_library(
        root,
        repository=secret_repository,
        dry_run=True,
    )
    assert planned["repository"] == safe_repository
    assert all(marker not in json.dumps(planned) for marker in secret_markers)

    original_git_output = library_module._git_output
    original_write_journal = library_module._write_install_journal
    journal_payloads: list[str] = []

    def capture_journal(path: Path, journal: dict[str, object]) -> None:
        journal_payloads.append(json.dumps(journal, sort_keys=True))
        original_write_journal(path, journal)

    def redirect_clone(*args: str, cwd: Path | None = None) -> str:
        rewritten = list(args)
        if rewritten[:2] == ["clone", "--filter=blob:none"]:
            rewritten[2] = str(remote)
        return original_git_output(*rewritten, cwd=cwd)

    monkeypatch.setattr(library_module, "_git_output", redirect_clone)
    monkeypatch.setattr(library_module, "_write_install_journal", capture_journal)
    applied = install_library(
        root,
        repository=secret_repository,
        dry_run=False,
    )
    serialized = json.dumps(applied, sort_keys=True) + (
        root / "runtime/state/library-install.json"
    ).read_text(encoding="utf-8")
    assert applied["repository"] == safe_repository
    assert all(marker not in serialized for marker in secret_markers)
    assert all(
        marker not in payload
        for payload in journal_payloads
        for marker in secret_markers
    )

    def fail_clone(*args: str, cwd: Path | None = None) -> str:
        if args[:2] == ("clone", "--filter=blob:none"):
            raise subprocess.CalledProcessError(
                128,
                ["git", *args],
                stderr=f"failed to clone {secret_repository}",
            )
        return original_git_output(*args, cwd=cwd)

    monkeypatch.setattr(library_module, "_git_output", fail_clone)
    failed_root = _root(tmp_path / "failed-target")
    with pytest.raises(LibraryError) as exc_info:
        install_library(
            failed_root,
            repository=secret_repository,
            dry_run=False,
        )
    assert safe_repository in str(exc_info.value)
    assert all(marker not in str(exc_info.value) for marker in secret_markers)


def test_install_refuses_dirty_or_linked_installed_git(tmp_path: Path) -> None:
    remote, _ = _library_remote(tmp_path)
    root = _root(tmp_path / "target")
    init_library(root, dry_run=False, initialize_git=True)
    lib = root / "lib"
    _git(lib, "config", "user.email", "test@example.com")
    _git(lib, "config", "user.name", "Test")
    _git(lib, "add", "-A")
    _git(lib, "commit", "-m", "installed baseline")
    (lib / "README.md").write_text("dirty\n", encoding="utf-8")

    dirty = install_library(root, repository=str(remote), dry_run=False)
    assert dirty["status"] == "blocked"
    assert "uncommitted" in dirty["blocker"]

    _git(lib, "add", "README.md")
    _git(lib, "commit", "-m", "clean")
    linked = tmp_path / "linked"
    _git(lib, "worktree", "add", "-b", "linked-test", str(linked))
    linked_result = install_library(root, repository=str(remote), dry_run=False)
    assert linked_result["status"] == "blocked"
    assert linked_result["existing"]["linked_worktrees"] == [str(linked)]


def test_invalid_staged_source_leaves_previous_library_in_place(tmp_path: Path) -> None:
    remote, _ = _library_remote(tmp_path, stale=True)
    root = _root(tmp_path / "target")
    init_library(root, dry_run=False)
    _object(root, "command", "old", entrypoint="command.md")
    refresh_registry(root, dry_run=False)
    before = library_doctor(root)["content_sha256"]

    with pytest.raises(LibraryError, match="staged library failed doctor"):
        install_library(
            root,
            repository=str(remote),
            replace_dirty=True,
            dry_run=False,
        )

    assert library_doctor(root)["content_sha256"] == before
    assert query_objects(root, kind="command")[0]["id"] == "old"
    assert not (root / "runtime/state/library-install.json").exists()


def test_legacy_migration_uses_compact_registry_and_excludes_runtime(tmp_path: Path) -> None:
    root = _root(tmp_path)
    source = root / "domains/los/03-workflows/engineering/example"
    source.mkdir(parents=True)
    (source / "workflow.md").write_text("# Example\n\nMigrated workflow.\n", encoding="utf-8")
    (source / "runs").mkdir()
    (source / "runs/result.log").write_text("runtime", encoding="utf-8")
    (source / ".features").mkdir()
    (source / ".features/state.json").write_text("{}", encoding="utf-8")
    (source / "tenant_config_snapshots").mkdir()
    (source / "tenant_config_snapshots/customer.json").write_text("{}", encoding="utf-8")
    (source / "tenant_config_toolkit_outputs").mkdir()
    (source / "tenant_config_toolkit_outputs/result.json").write_text("{}", encoding="utf-8")
    (source / "reports").mkdir()
    (source / "reports/result.md").write_text("runtime", encoding="utf-8")
    (source / "raw").mkdir()
    (source / "raw/evidence.json").write_text("{}", encoding="utf-8")
    (source / "config.toml.bak-20260718").write_text("legacy", encoding="utf-8")
    registry = root / "harness/registries/first-class-resources.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps(
            {
                "resources": [
                    {
                        "kind": "workflow_instance",
                        "native_id": "workflow_instance:los:example",
                        "source": "domains/los/03-workflows/engineering/example",
                        "title": "Example",
                        "summary": "Migrated workflow.",
                        "scope": {"domain": "los", "project": None},
                        "tags": ["workflow"],
                        "subtype": "instance",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    init_library(root, dry_run=False)
    planned = apply_legacy_migration(root, dry_run=True)
    assert planned["candidate_count"] == 1
    assert not (root / "lib/workflows/domains/los/example").exists()

    applied = apply_legacy_migration(root, dry_run=False)
    assert applied["copied"] == 1
    target = root / "lib/workflows/domains/los/example"
    assert (target / "workflow.md").is_file()
    assert not (target / "runs").exists()
    assert not (target / ".features").exists()
    assert not (target / "tenant_config_snapshots").exists()
    assert not (target / "tenant_config_toolkit_outputs").exists()
    assert not (target / "reports").exists()
    assert not (target / "raw").exists()
    assert not (target / "config.toml.bak-20260718").exists()
    manifest = yaml.safe_load((target / "object.yml").read_text(encoding="utf-8"))
    assert manifest["aliases"] == ["domains/los/03-workflows/engineering/example"]
    assert manifest["runtime"]["legacy_roots"] == [
        "domains/los/03-workflows/engineering/example/.features",
        "domains/los/03-workflows/engineering/example/raw",
        "domains/los/03-workflows/engineering/example/reports",
        "domains/los/03-workflows/engineering/example/runs",
        "domains/los/03-workflows/engineering/example/tenant_config_snapshots",
        "domains/los/03-workflows/engineering/example/tenant_config_toolkit_outputs",
    ]


def test_legacy_migration_preserves_registered_empty_object_for_review(tmp_path: Path) -> None:
    root = _root(tmp_path)
    source = root / "harness/shared_factory/05-knowledge/templates/thread-lifecycle"
    source.mkdir(parents=True)
    registry = root / "harness/registries/first-class-resources.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps(
            {
                "resources": [
                    {
                        "kind": "template",
                        "native_id": "template:thread-lifecycle",
                        "source": source.relative_to(root).as_posix(),
                        "title": "Thread Lifecycle",
                        "summary": "Registered placeholder.",
                        "scope": {"domain": None, "project": None},
                        "tags": ["template"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    init_library(root, dry_run=False)

    applied = apply_legacy_migration(root, dry_run=False)

    assert applied["copied"] == 1
    target = root / "lib/templates/root/thread-lifecycle"
    assert "had no definition files" in (target / "README.md").read_text(encoding="utf-8")
    manifest = yaml.safe_load((target / "object.yml").read_text(encoding="utf-8"))
    assert manifest["entrypoint"] == "README.md"


def test_domain_references_preserve_same_stem_different_extensions(tmp_path: Path) -> None:
    root = _root(tmp_path)
    registry = root / "harness/registries/first-class-resources.json"
    registry.parent.mkdir(parents=True)
    registry.write_text('{"resources": []}\n', encoding="utf-8")
    knowledge = root / "domains/los/05-knowledge"
    knowledge.mkdir(parents=True)
    (root / "domains/los/domain.yml").write_text("name: los\n", encoding="utf-8")
    (knowledge / "team-identities.md").write_text("# Team identities\n", encoding="utf-8")
    (knowledge / "team-identities.yml").write_text("people: []\n", encoding="utf-8")
    plan = legacy_migration_plan(root)
    references = [item for item in plan["objects"] if item["kind"] == "reference"]
    assert {item["id"] for item in references} == {
        "team-identities",
        "team-identities_yml",
    }


def test_library_cli_round_trip(tmp_path: Path, capsys) -> None:
    root = _root(tmp_path)
    assert main(["library", "init", "--root", str(root), "--apply"]) == 0
    capsys.readouterr()
    _object(root, "hook", "conversation-log", entrypoint="hook.py")
    assert main(["library", "refresh", "--root", str(root), "--apply"]) == 0
    capsys.readouterr()
    assert main(["library", "list", "--root", str(root), "--kind", "hook"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1


def test_library_install_cli_dry_run_apply_and_verify(tmp_path: Path, capsys) -> None:
    remote, revision = _library_remote(tmp_path)
    root = _root(tmp_path / "target")

    assert (
        main(
            [
                "library",
                "install",
                "--root",
                str(root),
                "--repository",
                str(remote),
            ]
        )
        == 0
    )
    planned = json.loads(capsys.readouterr().out)
    assert planned["status"] == "planned"
    assert not (root / "lib").exists()

    assert (
        main(
            [
                "library",
                "install",
                "--root",
                str(root),
                "--repository",
                str(remote),
                "--apply",
            ]
        )
        == 0
    )
    installed = json.loads(capsys.readouterr().out)
    assert installed["source_revision"] == revision
    assert main(["library", "verify-install", "--root", str(root)]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["status"] == "verified"


def test_install_requires_explicit_or_environment_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENTIC_OS_LIBRARY_REPOSITORY", raising=False)
    root = _root(tmp_path / "missing")
    blocked = install_library(root)
    assert blocked["status"] == "blocked"
    assert blocked["repository"] is None
    assert "AGENTIC_OS_LIBRARY_REPOSITORY" in blocked["blocker"]
    assert not (root / "lib").exists()
    assert not (root / "runtime").exists()

    remote, revision = _library_remote(tmp_path)
    monkeypatch.setenv("AGENTIC_OS_LIBRARY_REPOSITORY", str(remote))
    installed = install_library(_root(tmp_path / "configured"), dry_run=False)
    assert installed["source_revision"] == revision


def test_library_source_stage_adapters_forward_only_confirmed_arguments(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    scripts = source / "scripts"
    scripts.mkdir(parents=True)
    helper = (
        "import json\n"
        "from pathlib import Path\n"
        "import sys\n"
        "print(json.dumps({'script': Path(__file__).name, 'argv': sys.argv[1:]}))\n"
    )
    for name in (
        "build_library.py",
        "validate_library.py",
        "render_release_notes.py",
        "verify_release_readback.py",
    ):
        (scripts / name).write_text(helper, encoding="utf-8")
    source_root = str(source.resolve())

    assert (
        main(
            [
                "library",
                "build",
                "--source-root",
                str(source),
                "--output-dir",
                "dist",
                "--require-clean",
                "--require-revision",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "script": "build_library.py",
        "argv": [
            "--repo",
            source_root,
            "--output-dir",
            "dist",
            "--require-clean",
            "--require-revision",
        ],
    }

    assert (
        main(
            [
                "library",
                "validate",
                "--source-root",
                str(source),
                "--receipt",
                "dist/build-receipt.json",
                "--archive",
                "dist/library.tar.gz",
                "--write-receipt",
                "dist/qa.json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "script": "validate_library.py",
        "argv": [
            "--repo",
            source_root,
            "--receipt",
            "dist/build-receipt.json",
            "--archive",
            "dist/library.tar.gz",
            "--write-receipt",
            "dist/qa.json",
        ],
    }

    assert (
        main(
            [
                "library",
                "release",
                "--source-root",
                str(source),
                "--output",
                "dist/release-notes.md",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "script": "render_release_notes.py",
        "argv": ["--repo", source_root, "--output", "dist/release-notes.md"],
    }

    assert (
        main(
            [
                "library",
                "document",
                "--source-root",
                str(source),
                "--input",
                "dist/provider.json",
                "--required-asset",
                "library.tar.gz",
                "--required-asset",
                "build-receipt.json",
                "--notes",
                "dist/release-notes.md",
                "--write-receipt",
                "dist/readback.json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "script": "verify_release_readback.py",
        "argv": [
            "--repo",
            source_root,
            "--input",
            "dist/provider.json",
            "--required-asset",
            "library.tar.gz",
            "--required-asset",
            "build-receipt.json",
            "--notes",
            "dist/release-notes.md",
            "--write-receipt",
            "dist/readback.json",
        ],
    }


def test_library_source_stage_adapter_blocks_when_helper_is_missing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    assert main(["library", "build", "--source-root", str(source)]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "blocked"
    assert payload["auto_dev_stage"] == "develop"
    assert payload["blocker"] == "source helper not found: scripts/build_library.py"


@pytest.mark.parametrize(
    "command",
    (
        "build",
        "validate",
        "release",
        "document",
        "install",
        "verify-install",
        "rollback-install",
    ),
)
def test_library_operational_subcommand_parser_smoke(
    command: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as help_result:
        main(["library", command, "--help"])
    assert help_result.value.code == 0
    assert f"library {command}" in capsys.readouterr().out


def test_library_cli_help_describes_disposable_projection(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as library_help:
        main(["library", "--help"])
    assert library_help.value.code == 0
    output = capsys.readouterr().out
    assert "disposable, receipt-backed projection" in output
    assert "normal installed projections use 'library install'" in " ".join(
        output.split()
    )

    with pytest.raises(SystemExit) as init_help:
        main(["library", "init", "--help"])
    assert init_help.value.code == 0
    output = capsys.readouterr().out
    assert "Legacy source-fixture compatibility only" in output
    assert "normal installed projections never contain lib/.git" in " ".join(
        output.split()
    )

    with pytest.raises(SystemExit) as install_help:
        main(["library", "install", "--help"])
    assert install_help.value.code == 0
    output = capsys.readouterr().out
    assert "AGENTIC_OS_LIBRARY_REPOSITORY" in output

    with pytest.raises(SystemExit) as release_help:
        main(["library", "release", "--help"])
    assert release_help.value.code == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "protected CI/operator owns publication" in output


def test_root_validation_only_enforces_library_after_opt_in(tmp_path: Path) -> None:
    root = _root(tmp_path)
    legacy = ValidationResult(root=root)
    validate_object_library(root, legacy)
    assert legacy.errors == []

    init_library(root, dry_run=False)
    _object(root, "rule", "one", entrypoint="rule.md")
    opted_in = ValidationResult(root=root)
    validate_object_library(root, opted_in)
    assert any("registry_stale" in error for error in opted_in.errors)
