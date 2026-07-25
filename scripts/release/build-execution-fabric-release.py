#!/usr/bin/env python3
"""Validate and assemble immutable Execution Fabric release assets."""

from __future__ import annotations

import argparse
from hashlib import sha256
import gzip
import io
import json
from pathlib import Path
import re
import tarfile
import tomllib

import yaml


ROOT = Path(__file__).resolve().parents[2]
STATIC_MANIFEST = ROOT / "release/execution-fabric-manifest.yml"
DIGEST_IMAGE = re.compile(r"^ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+@sha256:[0-9a-f]{64}$")


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def validate_versions() -> dict:
    static = yaml.safe_load(STATIC_MANIFEST.read_text(encoding="utf-8"))
    python = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    python_version = str(python["project"]["version"])
    package_init = (ROOT / "src/genomes_agentic_os/__init__.py").read_text(
        encoding="utf-8"
    )
    init_match = re.search(r'__version__\s*=\s*"([^"]+)"', package_init)
    if not init_match:
        raise ValueError("src/genomes_agentic_os/__init__.py has no __version__")
    control = load_json(ROOT / "services/execution-fabric-control-plane/package.json")
    witness = load_json(ROOT / "services/execution-fabric-leadership-witness/package.json")
    versions = {
        "release": str(static["release_version"]),
        "python": python_version,
        "python_runtime": init_match.group(1),
        "control_plane": str(control["version"]),
        "leadership_witness": str(witness["version"]),
    }
    if len(set(versions.values())) != 1:
        raise ValueError(f"release versions differ: {versions}")
    openapi = (ROOT / str(static["contracts"]["openapi"])).read_text(encoding="utf-8")
    expected_api = f'version: "{static["service_api_version"]}"'
    if expected_api not in openapi:
        raise ValueError(
            f"OpenAPI version does not match {static['service_api_version']}"
        )
    for contract in ("config", "schema", "openapi"):
        path = ROOT / str(static["contracts"][contract])
        if not path.is_file():
            raise ValueError(f"release contract missing: {path.relative_to(ROOT)}")
    return {"static": static, "versions": versions}


def add_file(archive: tarfile.TarFile, source: Path, name: str) -> None:
    data = source.read_bytes()
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o755 if source.stat().st_mode & 0o111 else 0o644
    info.mtime = 0
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    archive.addfile(info, io.BytesIO(data))


def deterministic_tar(output: Path, paths: list[Path]) -> None:
    with output.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(
                fileobj=compressed,
                mode="w",
                format=tarfile.PAX_FORMAT,
            ) as archive:
                for base in paths:
                    if base.is_dir():
                        files = sorted(
                            path for path in base.rglob("*") if path.is_file()
                        )
                    else:
                        files = [base]
                    for path in files:
                        try:
                            name = str(path.relative_to(ROOT))
                        except ValueError:
                            name = f"release-generated/{path.name}"
                        add_file(archive, path, name)


def write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build(
    output: Path,
    control_image: str,
    witness_image: str,
    worker_image: str,
) -> None:
    validated = validate_versions()
    if not DIGEST_IMAGE.fullmatch(control_image):
        raise ValueError("control-plane image must be a digest-pinned GHCR reference")
    if not DIGEST_IMAGE.fullmatch(witness_image):
        raise ValueError("witness image must be a digest-pinned GHCR reference")
    if not DIGEST_IMAGE.fullmatch(worker_image):
        raise ValueError("worker image must be a digest-pinned GHCR reference")
    output.mkdir(parents=True, exist_ok=True)
    static = validated["static"]
    config = ROOT / str(static["contracts"]["config"])
    schema = ROOT / str(static["contracts"]["schema"])
    manifest = {
        "schema_version": "execution-fabric-release/v1",
        "release_version": validated["versions"]["release"],
        "service_api_version": str(static["service_api_version"]),
        "python_package": {
            "name": static["python_package"],
            "version": validated["versions"]["python"],
        },
        "images": {
            "control_plane": control_image,
            "leadership_witness": witness_image,
            "worker": worker_image,
        },
        "contracts": {
            "config": {
                "path": str(config.relative_to(ROOT)),
                "sha256": digest(config),
            },
            "schema": {
                "path": str(schema.relative_to(ROOT)),
                "sha256": digest(schema),
            },
        },
    }
    manifest_path = output / "execution-fabric-release-manifest.json"
    write_json(manifest_path, manifest)
    write_json(
        output / "execution-fabric-image-lock.json",
        {
            "schema_version": "execution-fabric-image-lock/v1",
            "release_version": validated["versions"]["release"],
            "images": manifest["images"],
        },
    )
    deterministic_tar(
        output / "execution-fabric-config-schema.tar.gz",
        [config, schema, STATIC_MANIFEST],
    )
    deterministic_tar(
        output / "execution-fabric-emergency-bundle.tar.gz",
        [
            ROOT / "deploy/execution-fabric",
            ROOT / "installers/execution-fabric",
            config,
            schema,
            STATIC_MANIFEST,
            manifest_path,
        ],
    )
    assets = sorted(path for path in output.iterdir() if path.is_file())
    (output / "SHA256SUMS").write_text(
        "".join(f"{digest(path)}  {path.name}\n" for path in assets),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist/release")
    parser.add_argument("--control-plane-image")
    parser.add_argument("--witness-image")
    parser.add_argument("--worker-image")
    args = parser.parse_args()
    validate_versions()
    if args.validate_only:
        return 0
    if not args.control_plane_image or not args.witness_image or not args.worker_image:
        parser.error(
            "digest-pinned --control-plane-image, --witness-image, and --worker-image are required"
        )
    build(
        args.output_dir,
        args.control_plane_image,
        args.witness_image,
        args.worker_image,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
