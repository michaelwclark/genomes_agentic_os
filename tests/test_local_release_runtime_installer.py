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


def _wheel(path: Path, version: str = "9.8.7") -> Path:
    wheel = path / f"genomes_agentic_os-{version}-py3-none-any.whl"
    metadata = f"Metadata-Version: 2.1\nName: genomes-agentic-os\nVersion: {version}\n"
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
        apply=True,
    )


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
    receipt = INSTALLER.install(_arguments(wheel, runtime_root, receipt_path))

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
    assert str(wheel.resolve()) == pip_command[-1]


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
