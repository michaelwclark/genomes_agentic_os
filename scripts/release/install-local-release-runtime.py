#!/usr/bin/env python3
"""Install one released wheel into the rollback-safe macOS local runtime.

The installer builds a non-editable, versioned virtual environment and only
switches the dispatcher aliases after package and CLI readback succeeds.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from email.parser import Parser
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
import zipfile


PACKAGE = "genomes-agentic-os"
MODULE = "genomes_agentic_os"
ALIASES = ("development-delivery-runtime", "layout-v2-runtime")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9a-fA-F]{7,64}$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def wheel_identity(path: Path) -> tuple[str, str]:
    if not path.is_file() or path.suffix != ".whl":
        raise ValueError(f"release wheel is missing or not a .whl file: {path}")
    with zipfile.ZipFile(path) as archive:
        metadata_files = [
            name
            for name in archive.namelist()
            if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_files) != 1:
            raise ValueError("wheel must contain exactly one dist-info/METADATA file")
        metadata = Parser().parsestr(
            archive.read(metadata_files[0]).decode("utf-8")
        )
    name = metadata.get("Name", "").strip().lower().replace("_", "-")
    version = metadata.get("Version", "").strip()
    if name != PACKAGE or not version:
        raise ValueError(
            f"expected {PACKAGE} wheel metadata, found name={name!r} version={version!r}"
        )
    return name, version


def expected_sha256(
    wheel: Path,
    *,
    value: str | None,
    checksum_file: Path | None,
) -> str | None:
    if value:
        normalized = value.lower().removeprefix("sha256:")
        if not SHA256.fullmatch(normalized):
            raise ValueError("--sha256 must be exactly 64 hexadecimal characters")
        return normalized
    if checksum_file is None:
        return None
    if not checksum_file.is_file():
        raise ValueError(f"checksum file does not exist: {checksum_file}")
    candidates: list[tuple[str, str | None]] = []
    for raw_line in checksum_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        digest = fields[0].lower().removeprefix("sha256:")
        if not SHA256.fullmatch(digest):
            continue
        filename = fields[-1].lstrip("*") if len(fields) > 1 else None
        candidates.append((digest, filename))
    named = [digest for digest, name in candidates if name == wheel.name]
    if len(named) == 1:
        return named[0]
    if len(candidates) == 1:
        return candidates[0][0]
    raise ValueError(
        f"checksum file must contain one unambiguous entry for {wheel.name}"
    )


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )


def _link_snapshot(path: Path) -> dict[str, str | None]:
    if not os.path.lexists(path):
        return {"raw": None, "resolved": None}
    if not path.is_symlink():
        raise ValueError(f"refusing to replace non-symlink runtime path: {path}")
    raw = os.readlink(path)
    raw_path = Path(raw)
    resolved = raw_path if raw_path.is_absolute() else path.parent / raw_path
    return {"raw": raw, "resolved": str(resolved.resolve(strict=False))}


def _replace_symlink(path: Path, target: str | Path) -> None:
    temporary = path.with_name(f".{path.name}.swap-{uuid.uuid4().hex}")
    os.symlink(str(target), temporary)
    try:
        os.replace(temporary, path)
    finally:
        if os.path.lexists(temporary):
            temporary.unlink()


def _restore_symlink(path: Path, snapshot: dict[str, str | None]) -> None:
    raw = snapshot["raw"]
    if raw is None:
        if os.path.lexists(path):
            path.unlink()
        return
    _replace_symlink(path, raw)


def activate_aliases(runtime_root: Path, target: Path) -> list[dict[str, object]]:
    aliases = [runtime_root / name for name in ALIASES]
    snapshots = {alias: _link_snapshot(alias) for alias in aliases}
    previous_paths = {alias: alias.with_name(f"{alias.name}.previous") for alias in aliases}
    previous_snapshots = {
        alias: _link_snapshot(previous_paths[alias]) for alias in aliases
    }
    switched: list[Path] = []
    try:
        for alias in aliases:
            prior = snapshots[alias]["resolved"]
            if prior is not None:
                _replace_symlink(previous_paths[alias], prior)
            elif os.path.lexists(previous_paths[alias]):
                previous_paths[alias].unlink()
        for alias in aliases:
            _replace_symlink(alias, target)
            switched.append(alias)
    except Exception:
        for alias in reversed(switched):
            _restore_symlink(alias, snapshots[alias])
        for alias in aliases:
            _restore_symlink(previous_paths[alias], previous_snapshots[alias])
        raise

    return [
        {
            "alias": str(alias),
            "prior_target": snapshots[alias]["resolved"],
            "new_target": str(target),
            "readback_target": str(alias.resolve(strict=True)),
            "rollback_pointer": str(previous_paths[alias]),
            "rollback_target": (
                str(previous_paths[alias].resolve(strict=True))
                if previous_paths[alias].exists()
                else None
            ),
        }
        for alias in aliases
    ]


def _readback(target: Path, version: str) -> dict[str, object]:
    python = target / "bin" / "python"
    cli = target / "bin" / "agentic-os"
    code = (
        "import importlib, importlib.metadata, json, pathlib; "
        f"m=importlib.import_module('{MODULE}'); "
        f"print(json.dumps({{'package':'{PACKAGE}',"
        f"'version':importlib.metadata.version('{PACKAGE}'),"
        "'module_path':str(pathlib.Path(m.__file__).resolve())}))"
    )
    package_result = _run([str(python), "-c", code])
    package = json.loads(package_result.stdout)
    if package.get("version") != version:
        raise ValueError(
            f"installed version mismatch: expected {version}, got {package.get('version')}"
        )
    module_path = Path(str(package.get("module_path", ""))).resolve(strict=False)
    if target.resolve(strict=False) not in module_path.parents:
        raise ValueError(f"installed module escaped the versioned runtime: {module_path}")
    smoke = _run([str(cli), "--help"])
    return {
        "package": package,
        "smoke": {
            "command": [str(cli), "--help"],
            "exit_code": smoke.returncode,
            "stdout_nonempty": bool(smoke.stdout.strip()),
        },
    }


def _write_json_atomic(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def install(arguments: argparse.Namespace) -> dict[str, object]:
    wheel = arguments.wheel.expanduser().resolve(strict=False)
    runtime_root = arguments.runtime_root.expanduser().resolve(strict=False)
    receipt_path = arguments.receipt.expanduser().resolve(strict=False)
    package_name, version = wheel_identity(wheel)
    if not REVISION.fullmatch(arguments.release_revision):
        raise ValueError("--release-revision must be a 7-64 character Git SHA")
    expected = expected_sha256(
        wheel,
        value=arguments.sha256,
        checksum_file=arguments.sha256_file,
    )
    if expected is None and not arguments.allow_unverified:
        raise ValueError(
            "a trusted --sha256 or --sha256-file is required; "
            "use --allow-unverified only for an explicit non-release recovery"
        )
    actual = sha256(wheel)
    if expected is not None and actual != expected:
        raise ValueError(f"wheel SHA-256 mismatch: expected {expected}, got {actual}")

    release_dir = runtime_root / "releases" / f"{version}-{arguments.release_revision[:7].lower()}"
    target = release_dir / "runtime"
    if os.path.lexists(target):
        raise ValueError(f"versioned runtime already exists; refusing to overwrite: {target}")
    runtime_root.mkdir(parents=True, exist_ok=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    for alias_name in ALIASES:
        _link_snapshot(runtime_root / alias_name)

    created = False
    activated_aliases: list[dict[str, object]] = []
    try:
        release_dir.mkdir(parents=True, exist_ok=False)
        created = True
        _run([arguments.python, "-m", "venv", str(target)])
        _run(
            [
                str(target / "bin" / "python"),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                str(wheel),
            ]
        )
        validation = _readback(target, version)
        aliases = activate_aliases(runtime_root, target)
        activated_aliases = aliases
        receipt: dict[str, object] = {
            "schema_version": "local-release-runtime-install/v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "package": {
                "name": package_name,
                "version": version,
                "module": MODULE,
                "module_path": validation["package"]["module_path"],
            },
            "release_revision": arguments.release_revision.lower(),
            "wheel": {
                "path": str(wheel),
                "sha256": actual,
                "expected_sha256": expected,
                "checksum_verified": expected is not None,
            },
            "runtime": {
                "root": str(runtime_root),
                "target": str(target),
                "editable": False,
            },
            "aliases": aliases,
            "smoke": validation["smoke"],
            "readback_verified": True,
            "rollback_retained": all(
                entry["prior_target"] is None or entry["rollback_target"] == entry["prior_target"]
                for entry in aliases
            ),
        }
        _write_json_atomic(receipt_path, receipt)
        return receipt
    except Exception:
        for entry in reversed(activated_aliases):
            alias = Path(str(entry["alias"]))
            prior = entry["prior_target"]
            if prior is None:
                if os.path.lexists(alias):
                    alias.unlink()
            else:
                _replace_symlink(alias, str(prior))
        if created and release_dir.exists():
            shutil.rmtree(release_dir)
        raise


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--release-revision", required=True)
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=Path.home() / "Library/Application Support/AgenticOS",
    )
    parser.add_argument("--receipt", type=Path, required=True)
    checksum = parser.add_mutually_exclusive_group()
    checksum.add_argument("--sha256")
    checksum.add_argument("--sha256-file", type=Path)
    parser.add_argument("--allow-unverified", action="store_true")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args(argv)
    if not arguments.apply:
        parser.error("installation mutates runtime aliases; pass --apply")
    return arguments


def main(argv: list[str] | None = None) -> int:
    arguments = parse_args(argv)
    try:
        receipt = install(arguments)
    except (OSError, ValueError, subprocess.CalledProcessError, zipfile.BadZipFile) as error:
        raise SystemExit(f"local release runtime install failed: {error}") from error
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
