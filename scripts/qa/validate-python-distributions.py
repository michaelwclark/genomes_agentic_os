#!/usr/bin/env python3
"""Prove the published Python distribution is complete and reinstall-safe.

The source distribution is the important boundary: release tooling commonly
builds the upload wheel from the sdist rather than from the repository. This
check compares the package-owned runtime resources in both wheel paths, then
installs only the sdist-derived wheel into an empty virtual environment and
exercises first install, validation, and the external object-library lifecycle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import venv
import zipfile


RESOURCE_ROOT = "genomes_agentic_os/_resources/"
REQUIRED_RESOURCE_TREES = ("harness", "templates", "operating-manual", "schemas")


def run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def wheel_resources(path: Path) -> dict[str, str]:
    inventory: dict[str, str] = {}
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if not name.startswith(RESOURCE_ROOT) or name.endswith("/"):
                continue
            relative = name.removeprefix(RESOURCE_ROOT)
            inventory[relative] = hashlib.sha256(archive.read(name)).hexdigest()
    for tree in REQUIRED_RESOURCE_TREES:
        if not any(name.startswith(f"{tree}/") for name in inventory):
            raise RuntimeError(f"wheel is missing package runtime tree: {tree}")
    forbidden = tuple(
        name
        for name in inventory
        if "__pycache__/" in name
        or name.endswith((".pyc", ".pyo"))
        or "/.git/" in f"/{name}"
        or name.endswith("/.DS_Store")
        or name == ".DS_Store"
    )
    if forbidden:
        raise RuntimeError(f"wheel contains cache or private VCS paths: {forbidden!r}")
    return inventory


def inventory_digest(inventory: dict[str, str]) -> str:
    encoded = json.dumps(
        inventory,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def extract_sdist(path: Path, destination: Path) -> Path:
    destination.mkdir(parents=True)
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            candidate = (destination / member.name).resolve()
            if destination.resolve() not in candidate.parents:
                raise RuntimeError(f"unsafe sdist member: {member.name}")
        archive.extractall(destination, filter="data")
    roots = [item for item in destination.iterdir() if item.is_dir()]
    if len(roots) != 1:
        raise RuntimeError("source distribution must contain exactly one root directory")
    return roots[0]


def executable(environment: Path, name: str) -> Path:
    scripts = "Scripts" if sys.platform == "win32" else "bin"
    suffix = ".exe" if sys.platform == "win32" else ""
    return environment / scripts / f"{name}{suffix}"


def exercise_installed_wheel(wheel: Path, scratch: Path) -> str:
    environment = scratch / "venv"
    venv.EnvBuilder(with_pip=True, clear=True).create(environment)
    python = executable(environment, "python")
    agentic_os = executable(environment, "agentic-os")
    run(
        str(python),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        str(wheel),
    )

    target = scratch / "installed-os"
    run(str(agentic_os), "init", "--target", str(target))
    run(str(agentic_os), "validate", "--root", str(target))

    source = scratch / "external-library-source"
    run(str(agentic_os), "library", "init", "--root", str(source), "--apply", "--git")
    run(
        str(agentic_os),
        "library",
        "create",
        "--root",
        str(source),
        "skill",
        "distribution-sentinel",
        "--description",
        "Published wheel external-library validation sentinel.",
        "--apply",
    )
    library_repository = source / "lib"
    run("git", "config", "user.email", "packaging-test@example.invalid", cwd=library_repository)
    run("git", "config", "user.name", "Packaging Test", cwd=library_repository)
    run("git", "add", "-A", cwd=library_repository)
    run("git", "commit", "--no-verify", "-m", "seed validation library", cwd=library_repository)

    sentinel = target / ".operator-owned-distribution-sentinel"
    sentinel.write_text("operator-owned\n", encoding="utf-8")
    before = hashlib.sha256(sentinel.read_bytes()).hexdigest()
    for _ in range(2):
        run(
            str(agentic_os),
            "library",
            "install",
            "--root",
            str(target),
            "--repository",
            str(library_repository),
            "--ref",
            "main",
            "--apply",
        )
        run(str(agentic_os), "library", "verify-install", "--root", str(target))
    run(str(agentic_os), "validate", "--root", str(target))
    after = hashlib.sha256(sentinel.read_bytes()).hexdigest()
    if before != after:
        raise RuntimeError("operator-owned sentinel changed during library reinstall")
    return after


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="dist")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    output = (root / args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="gaos-distribution-validation-") as raw:
        scratch = Path(raw)
        direct = scratch / "direct"
        from_sdist = scratch / "from-sdist"
        run(
            sys.executable,
            "-m",
            "build",
            "--sdist",
            "--wheel",
            "--outdir",
            str(direct),
            str(root),
            cwd=scratch,
        )
        source_distribution = next(direct.glob("*.tar.gz"))
        extracted = extract_sdist(source_distribution, scratch / "extracted")
        run(
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--outdir",
            str(from_sdist),
            str(extracted),
            cwd=scratch,
        )
        direct_wheel = next(direct.glob("*.whl"))
        published_wheel = next(from_sdist.glob("*.whl"))
        direct_inventory = wheel_resources(direct_wheel)
        published_inventory = wheel_resources(published_wheel)
        if direct_inventory != published_inventory:
            missing = sorted(set(direct_inventory) - set(published_inventory))
            extra = sorted(set(published_inventory) - set(direct_inventory))
            changed = sorted(
                name
                for name in set(direct_inventory) & set(published_inventory)
                if direct_inventory[name] != published_inventory[name]
            )
            raise RuntimeError(
                "direct and sdist-derived wheel resources differ: "
                f"missing={missing!r}, extra={extra!r}, changed={changed!r}"
            )
        sentinel_sha256 = exercise_installed_wheel(published_wheel, scratch)
        shutil.copy2(source_distribution, output / source_distribution.name)
        shutil.copy2(published_wheel, output / published_wheel.name)

    receipt = {
        "schema": "genomes-agentic-os-distribution-validation/v1",
        "status": "passed",
        "resource_count": len(published_inventory),
        "resource_inventory_sha256": inventory_digest(published_inventory),
        "sentinel_sha256": sentinel_sha256,
        "checks": [
            "direct_and_sdist_wheel_resources_identical",
            "fresh_wheel_init",
            "fresh_wheel_validate",
            "external_library_install",
            "external_library_verify",
            "external_library_reinstall",
            "operator_sentinel_preserved",
        ],
    }
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
