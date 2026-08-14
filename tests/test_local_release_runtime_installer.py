from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import zipfile

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/release/install-local-release-runtime.py"
SPEC = importlib.util.spec_from_file_location("local_release_runtime_installer", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
INSTALLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALLER)


def _wheel(
    path: Path, version: str = "9.8.7", requirements: list[str] | None = None
) -> Path:
    wheel = path / f"genomes_agentic_os-{version}-py3-none-any.whl"
    metadata = f"Metadata-Version: 2.1\nName: genomes-agentic-os\nVersion: {version}\n"
    for requirement in requirements or []:
        metadata += f"Requires-Dist: {requirement}\n"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            f"genomes_agentic_os-{version}.dist-info/METADATA",
            metadata,
        )
    return wheel


def _arguments(wheel: Path, runtime_root: Path, receipt: Path) -> argparse.Namespace:
    return argparse.Namespace(
        wheel=wheel,
        release_revision="abcdef0123456789",
        runtime_root=runtime_root,
        receipt=receipt,
        sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),
        sha256_file=None,
        allow_unverified=False,
        python="python3",
        dependency_lock=None,
        wheelhouse=None,
        review_rollout_receipt=None,
        apply=True,
    )


def _review_rollout_receipt(
    path: Path,
    receipt_root: Path,
    *,
    release_revision: str = "abcdef0123456789",
    source_roots: list[Path] | None = None,
    strategy: str = "shared-existing",
) -> Path:
    roots = source_roots or [receipt_root]
    for root in {*roots, receipt_root}:
        (root / "receipts").mkdir(parents=True, exist_ok=True)
        (root / ".locks").mkdir(parents=True, exist_ok=True)
    receipt = path / "review-rollout.json"
    receipt.write_text(
        json.dumps(
            {
                "schema_version": "review-coordination-rollout/v1",
                "release_revision": release_revision,
                "quiesced": True,
                "active_reviews": 0,
                "receipt_strategy": strategy,
                "source_receipt_roots": [str(root.resolve()) for root in roots],
                "target_receipt_root": str(receipt_root.resolve()),
                "migration_verified": True,
                "budget_history_preserved": True,
                "expires_at": "2099-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    return receipt


def _terminal_review_receipt(root: Path, key: str = "a" * 64) -> Path:
    path = root / "receipts" / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": "auto-dev-review-receipt/v1",
                "key": key,
                "status": "completed",
                "outcome": "findings",
            }
        ),
        encoding="utf-8",
    )
    return path


def test_install_builds_versioned_runtime_and_retains_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wheel = _wheel(tmp_path)
    runtime_root = tmp_path / "Application Support" / "AgenticOS"
    old_target = runtime_root / "releases/9.8.6-deadbee/runtime"
    old_target.mkdir(parents=True)
    runtime_root.mkdir(parents=True, exist_ok=True)
    for name in INSTALLER.ALIASES:
        (runtime_root / name).symlink_to(old_target)

    commands: list[list[str]] = []

    def fake_run(command: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        target = runtime_root / "releases/9.8.7-abcdef0/runtime"
        if command[1:3] == ["-m", "venv"]:
            (target / "bin").mkdir(parents=True)
            return subprocess.CompletedProcess(command, 0, "", "")
        if "-c" in command:
            module = target / "lib/python/site-packages/genomes_agentic_os/__init__.py"
            module.parent.mkdir(parents=True)
            module.write_text("", encoding="utf-8")
            payload = {
                "package": "genomes-agentic-os",
                "version": "9.8.7",
                "module_path": str(module),
            }
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        if command[-1] == "--help":
            return subprocess.CompletedProcess(command, 0, "usage: agentic-os\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(INSTALLER, "_run", fake_run)
    receipt_path = tmp_path / "receipts/install.json"
    arguments = _arguments(wheel, runtime_root, receipt_path)
    arguments.review_rollout_receipt = _review_rollout_receipt(
        tmp_path, tmp_path / "review-receipts"
    )
    receipt = INSTALLER.install(arguments)

    target = runtime_root / "releases/9.8.7-abcdef0/runtime"
    assert receipt["readback_verified"] is True
    assert receipt["rollback_retained"] is True
    assert receipt["wheel"]["checksum_verified"] is True
    assert receipt["package"]["version"] == "9.8.7"
    assert receipt["runtime"] == {
        "root": str(runtime_root),
        "target": str(target),
        "editable": False,
    }
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == receipt
    for name in INSTALLER.ALIASES:
        assert (runtime_root / name).resolve() == target.resolve()
        assert (runtime_root / f"{name}.previous").resolve() == old_target.resolve()
    pip_command = next(command for command in commands if "pip" in command)
    assert "-e" not in pip_command
    assert "--no-deps" in pip_command
    assert str(wheel.resolve()) == pip_command[-1]
    assert any(command[-2:] == ["pip", "check"] for command in commands)
    assert receipt["review_coordination_rollout"]["proof"]["quiesced"] is True
    assert receipt["review_coordination_rollout"]["verified_evidence"] == {
        "observed_active_reviews": 0,
        "held_family_locks": 0,
        "source_receipt_counts": {str((tmp_path / "review-receipts").resolve()): 0},
        "required_receipt_count": 0,
        "target_receipt_count": 0,
        "receipt_digests_matched": 0,
    }


def test_checksum_mismatch_fails_before_runtime_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wheel = _wheel(tmp_path)
    runtime_root = tmp_path / "runtime-root"
    arguments = _arguments(wheel, runtime_root, tmp_path / "receipt.json")
    arguments.sha256 = "0" * 64
    monkeypatch.setattr(
        INSTALLER,
        "_run",
        lambda command: pytest.fail(f"unexpected external command: {command}"),
    )

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        INSTALLER.install(arguments)

    assert not runtime_root.exists()


def test_release_install_requires_checksum_or_explicit_recovery_override(
    tmp_path: Path,
) -> None:
    wheel = _wheel(tmp_path)
    arguments = _arguments(wheel, tmp_path / "runtime", tmp_path / "receipt.json")
    arguments.sha256 = None

    with pytest.raises(ValueError, match="trusted --sha256"):
        INSTALLER.install(arguments)


def test_dependency_closure_is_offline_hash_pinned_and_resolution_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wheel = _wheel(tmp_path, requirements=["PyYAML>=6.0"])
    runtime_root = tmp_path / "runtime-root"
    lock = tmp_path / "requirements.lock"
    lock.write_text("PyYAML==6.0.2 --hash=sha256:" + "a" * 64 + "\n", encoding="utf-8")
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    arguments = _arguments(wheel, runtime_root, tmp_path / "receipt.json")
    arguments.dependency_lock = lock
    arguments.wheelhouse = wheelhouse
    commands: list[list[str]] = []

    def fake_run(command: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        target = runtime_root / "releases/9.8.7-abcdef0/runtime"
        if command[1:3] == ["-m", "venv"]:
            (target / "bin").mkdir(parents=True)
        elif "-c" in command:
            module = target / "lib/python/site-packages/genomes_agentic_os/__init__.py"
            module.parent.mkdir(parents=True)
            module.write_text("", encoding="utf-8")
            payload = {
                "package": "genomes-agentic-os",
                "version": "9.8.7",
                "module_path": str(module),
            }
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        elif command[-1] == "--help":
            return subprocess.CompletedProcess(command, 0, "usage: agentic-os\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(INSTALLER, "_run", fake_run)
    receipt = INSTALLER.install(arguments)

    dependency_command = next(command for command in commands if "-r" in command)
    assert "--no-index" in dependency_command
    assert "--require-hashes" in dependency_command
    assert "--no-deps" in dependency_command
    assert dependency_command[dependency_command.index("--find-links") + 1] == str(
        wheelhouse.resolve()
    )
    assert dependency_command[dependency_command.index("-r") + 1] == str(lock.resolve())
    assert receipt["dependencies"]["mode"] == "hash-pinned-wheelhouse"
    assert receipt["dependencies"]["lock_sha256"] == hashlib.sha256(
        lock.read_bytes()
    ).hexdigest()
    assert receipt["wheel"]["requires_dist"] == ["PyYAML>=6.0"]
    assert receipt["dependencies"]["pip_check"]["exit_code"] == 0


def test_runtime_dependencies_require_hash_pinned_offline_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wheel = _wheel(tmp_path, requirements=["PyYAML>=6.0", "jsonschema>=4"])
    runtime_root = tmp_path / "runtime-root"
    monkeypatch.setattr(
        INSTALLER,
        "_run",
        lambda command: pytest.fail(f"unexpected external command: {command}"),
    )

    with pytest.raises(ValueError, match="wheel declares runtime dependencies"):
        INSTALLER.install(_arguments(wheel, runtime_root, tmp_path / "receipt.json"))

    assert not runtime_root.exists()


def test_requires_dist_uses_pep508_marker_evaluation(tmp_path: Path) -> None:
    wheel = _wheel(
        tmp_path,
        requirements=[
            'pytest>=8; extra=="dev"',
            'colorama; python_version<"1"',
            'PyYAML>=6; python_version>="3"',
        ],
    )

    _, _, requirements = INSTALLER.wheel_identity(wheel)

    assert requirements == ['PyYAML>=6; python_version >= "3"']


def test_rollout_revision_accepts_case_normalized_full_and_short_sha(
    tmp_path: Path,
) -> None:
    root = tmp_path / "review-root"
    receipt = _review_rollout_receipt(
        tmp_path,
        root,
        release_revision="ABCDEF0123456789ABCDEF0123456789ABCDEF01",
    )

    proof = INSTALLER.review_rollout_proof(receipt, release_revision="abcdef0")

    assert proof["release_revision"].startswith("ABCDEF0")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("quiesced", 1, "quiesced=true"),
        ("active_reviews", False, "integer active_reviews=0"),
        ("migration_verified", 1, "migration_verified=true"),
        ("budget_history_preserved", 1, "budget_history_preserved=true"),
    ],
)
def test_rollout_proof_rejects_type_loose_claims(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    root = tmp_path / "review-root"
    receipt = _review_rollout_receipt(tmp_path, root)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload[field] = value
    receipt.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        INSTALLER.review_rollout_proof(
            receipt, release_revision="abcdef0123456789"
        )


def test_rollout_guard_verifies_receipt_budget_history_and_holds_family_locks(
    tmp_path: Path,
) -> None:
    source = tmp_path / "old-root"
    target = tmp_path / "new-root"
    receipt = _review_rollout_receipt(
        tmp_path,
        target,
        source_roots=[source],
        strategy="migrated",
    )
    source_receipt = _terminal_review_receipt(source)
    target_receipt = target / "receipts" / source_receipt.name
    target_receipt.write_bytes(source_receipt.read_bytes())
    lock = target / ".locks" / f"{'b' * 64}.lock"
    lock.touch()
    proof = INSTALLER.review_rollout_proof(
        receipt, release_revision="abcdef0123456789"
    )

    guard = INSTALLER.acquire_review_rollout_guard(proof)
    try:
        contender = lock.open("a+", encoding="utf-8")
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(contender.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            contender.close()
        assert guard.evidence["required_receipt_count"] == 1
        assert guard.evidence["receipt_digests_matched"] == 1
        assert guard.evidence["held_family_locks"] == 1
    finally:
        INSTALLER.release_review_rollout_guard(guard)


def test_rollout_guard_rejects_self_attested_but_missing_budget_history(
    tmp_path: Path,
) -> None:
    source = tmp_path / "old-root"
    target = tmp_path / "new-root"
    receipt = _review_rollout_receipt(
        tmp_path,
        target,
        source_roots=[source],
        strategy="migrated",
    )
    _terminal_review_receipt(source)
    proof = INSTALLER.review_rollout_proof(
        receipt, release_revision="abcdef0123456789"
    )

    with pytest.raises(ValueError, match="budget history is missing or changed"):
        INSTALLER.acquire_review_rollout_guard(proof)


def test_rollout_guard_rejects_self_attested_zero_with_live_family_lock(
    tmp_path: Path,
) -> None:
    root = tmp_path / "review-root"
    receipt = _review_rollout_receipt(tmp_path, root)
    lock = root / ".locks" / f"{'c' * 64}.lock"
    lock.touch()
    owner = lock.open("a+", encoding="utf-8")
    fcntl.flock(owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        proof = INSTALLER.review_rollout_proof(
            receipt, release_revision="abcdef0123456789"
        )
        with pytest.raises(ValueError, match="live family lock"):
            INSTALLER.acquire_review_rollout_guard(proof)
    finally:
        fcntl.flock(owner.fileno(), fcntl.LOCK_UN)
        owner.close()


def test_existing_runtime_requires_short_lived_review_drain_and_migration_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wheel = _wheel(tmp_path)
    runtime_root = tmp_path / "runtime-root"
    old_target = runtime_root / "releases/9.8.6-deadbee/runtime"
    old_target.mkdir(parents=True)
    for name in INSTALLER.ALIASES:
        (runtime_root / name).symlink_to(old_target)
    monkeypatch.setattr(
        INSTALLER,
        "_run",
        lambda command: pytest.fail(f"unexpected external command: {command}"),
    )

    with pytest.raises(ValueError, match="runtime upgrade requires"):
        INSTALLER.install(_arguments(wheel, runtime_root, tmp_path / "receipt.json"))

    assert not (runtime_root / "releases/9.8.7-abcdef0").exists()


def test_inconsistent_active_alias_pair_fails_before_external_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wheel = _wheel(tmp_path)
    runtime_root = tmp_path / "runtime-root"
    first = runtime_root / "releases/9.8.5-one/runtime"
    second = runtime_root / "releases/9.8.6-two/runtime"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (runtime_root / INSTALLER.ALIASES[0]).symlink_to(first)
    (runtime_root / INSTALLER.ALIASES[1]).symlink_to(second)
    monkeypatch.setattr(
        INSTALLER,
        "_run",
        lambda command: pytest.fail(f"unexpected external command: {command}"),
    )

    with pytest.raises(ValueError, match="active runtime aliases are inconsistent"):
        INSTALLER.install(_arguments(wheel, runtime_root, tmp_path / "receipt.json"))

    assert (runtime_root / INSTALLER.ALIASES[0]).resolve() == first.resolve()
    assert (runtime_root / INSTALLER.ALIASES[1]).resolve() == second.resolve()


def test_receipt_failure_restores_active_and_previous_alias_pairs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wheel = _wheel(tmp_path)
    runtime_root = tmp_path / "runtime-root"
    old_target = runtime_root / "releases/9.8.6-deadbee/runtime"
    older_target = runtime_root / "releases/9.8.5-cafebad/runtime"
    old_target.mkdir(parents=True)
    older_target.mkdir(parents=True)
    for name in INSTALLER.ALIASES:
        (runtime_root / name).symlink_to(old_target)
        (runtime_root / f"{name}.previous").symlink_to(older_target)

    def fake_run(command: list[str]) -> subprocess.CompletedProcess[str]:
        target = runtime_root / "releases/9.8.7-abcdef0/runtime"
        if command[1:3] == ["-m", "venv"]:
            (target / "bin").mkdir(parents=True)
        elif "-c" in command:
            module = target / "lib/python/site-packages/genomes_agentic_os/__init__.py"
            module.parent.mkdir(parents=True)
            module.write_text("", encoding="utf-8")
            payload = {
                "package": "genomes-agentic-os",
                "version": "9.8.7",
                "module_path": str(module),
            }
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        elif command[-1] == "--help":
            return subprocess.CompletedProcess(command, 0, "usage: agentic-os\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(INSTALLER, "_run", fake_run)
    monkeypatch.setattr(
        INSTALLER,
        "_write_json_atomic",
        lambda path, value: (_ for _ in ()).throw(OSError("receipt write failed")),
    )

    arguments = _arguments(wheel, runtime_root, tmp_path / "receipt.json")
    arguments.review_rollout_receipt = _review_rollout_receipt(
        tmp_path, tmp_path / "review-receipts"
    )
    with pytest.raises(OSError, match="receipt write failed"):
        INSTALLER.install(arguments)

    for name in INSTALLER.ALIASES:
        assert (runtime_root / name).resolve() == old_target.resolve()
        assert (runtime_root / f"{name}.previous").resolve() == older_target.resolve()
    assert not (runtime_root / "releases/9.8.7-abcdef0").exists()
