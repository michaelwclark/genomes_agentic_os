from __future__ import annotations

import argparse
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


def _review_rollout_receipt(path: Path, receipt_root: Path) -> Path:
    receipt = path / "review-rollout.json"
    receipt.write_text(
        json.dumps(
            {
                "schema_version": "review-coordination-rollout/v1",
                "release_revision": "abcdef0123456789",
                "quiesced": True,
                "active_reviews": 0,
                "receipt_strategy": "shared-existing",
                "source_receipt_roots": [str(receipt_root.resolve())],
                "target_receipt_root": str(receipt_root.resolve()),
                "migration_verified": True,
                "budget_history_preserved": True,
                "expires_at": "2099-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    return receipt


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
