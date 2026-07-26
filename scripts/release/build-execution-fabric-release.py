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
DEPENDENCY_IMAGE_SOURCES = (
    ROOT / "deploy/execution-fabric/release-image-sources.json"
)
DEPENDENCY_IMAGE_NAMES = ("postgres", "valkey", "minio", "minio_client")
DIGEST_IMAGE = re.compile(
    r"^(?P<repository>[a-z0-9.-]+(?:/[a-z0-9._-]+)+)"
    r"@sha256:(?P<digest>[0-9a-f]{64})$"
)
SOURCE_REPOSITORY = re.compile(r"^[a-z0-9.-]+(?:/[a-z0-9._-]+)+$")
SOURCE_TAG = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def load_dependency_image_sources(
    path: Path = DEPENDENCY_IMAGE_SOURCES,
) -> dict[str, dict[str, str]]:
    value = load_json(path)
    if set(value) != {"schema_version", "images"}:
        raise ValueError(
            f"{path} must contain only schema_version and images"
        )
    if value["schema_version"] != "execution-fabric-release-image-sources/v1":
        raise ValueError(f"{path} has an unsupported schema_version")
    images = value["images"]
    if not isinstance(images, dict) or set(images) != set(DEPENDENCY_IMAGE_NAMES):
        raise ValueError(
            f"{path} images must contain exactly: "
            + ", ".join(DEPENDENCY_IMAGE_NAMES)
        )

    validated: dict[str, dict[str, str]] = {}
    for name in DEPENDENCY_IMAGE_NAMES:
        image = images[name]
        if not isinstance(image, dict) or set(image) != {"repository", "tag"}:
            raise ValueError(
                f"{path} image {name} must contain only repository and tag"
            )
        repository = image["repository"]
        tag = image["tag"]
        if not isinstance(repository, str) or not SOURCE_REPOSITORY.fullmatch(
            repository
        ):
            raise ValueError(f"{path} image {name} has an invalid repository")
        if not isinstance(tag, str) or not SOURCE_TAG.fullmatch(tag):
            raise ValueError(f"{path} image {name} has an invalid reviewed tag")
        if tag.lower() == "latest" or "@" in tag or tag.startswith("sha256:"):
            raise ValueError(
                f"{path} image {name} must use a reviewed, non-latest source tag"
            )
        validated[name] = {"repository": repository, "tag": tag}
    return validated


def validate_digest_image(
    name: str,
    image: str,
    *,
    expected_repository: str,
) -> str:
    match = DIGEST_IMAGE.fullmatch(image)
    if not match:
        raise ValueError(
            f"{name} image must be an immutable repository@sha256 reference"
        )
    if match.group("repository") != expected_repository:
        raise ValueError(
            f"{name} image repository must be {expected_repository}"
        )
    return image


def validate_versions() -> dict:
    static = yaml.safe_load(STATIC_MANIFEST.read_text(encoding="utf-8"))
    dependency_image_sources = load_dependency_image_sources()
    python = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    python_version = str(python["project"]["version"])
    package_init = (ROOT / "src/genomes_agentic_os/__init__.py").read_text(
        encoding="utf-8"
    )
    init_match = re.search(r'__version__\s*=\s*"([^"]+)"', package_init)
    if not init_match:
        raise ValueError("src/genomes_agentic_os/__init__.py has no __version__")
    control_root = ROOT / "services/execution-fabric-control-plane"
    witness_root = ROOT / "services/execution-fabric-leadership-witness"
    control = load_json(control_root / "package.json")
    control_lock = load_json(control_root / "package-lock.json")
    witness = load_json(witness_root / "package.json")
    witness_lock = load_json(witness_root / "package-lock.json")
    chart = yaml.safe_load(
        (ROOT / "deploy/execution-fabric/helm/los-agents/Chart.yaml").read_text(
            encoding="utf-8"
        )
    )
    uv = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    uv_projects = [
        package
        for package in uv.get("package", [])
        if package.get("name") == str(static["python_package"])
    ]
    if len(uv_projects) != 1:
        raise ValueError(
            "uv.lock must contain exactly one genomes-agentic-os project record"
        )

    def lock_root_version(lock: dict, name: str) -> str:
        packages = lock.get("packages")
        if not isinstance(packages, dict) or not isinstance(packages.get(""), dict):
            raise ValueError(f"{name} package-lock.json has no root package record")
        return str(packages[""]["version"])

    versions = {
        "release": str(static["release_version"]),
        "python": python_version,
        "python_runtime": init_match.group(1),
        "python_lock": str(uv_projects[0]["version"]),
        "control_plane": str(control["version"]),
        "control_plane_lock": str(control_lock["version"]),
        "control_plane_lock_root": lock_root_version(
            control_lock, "control-plane"
        ),
        "leadership_witness": str(witness["version"]),
        "leadership_witness_lock": str(witness_lock["version"]),
        "leadership_witness_lock_root": lock_root_version(
            witness_lock, "leadership-witness"
        ),
        "worker_chart": str(chart["version"]),
        "worker_app": str(chart["appVersion"]),
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
    return {
        "static": static,
        "versions": versions,
        "dependency_image_sources": dependency_image_sources,
    }


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
    postgres_image: str,
    valkey_image: str,
    minio_image: str,
    minio_client_image: str,
) -> None:
    validated = validate_versions()
    static = validated["static"]
    dependency_sources = validated["dependency_image_sources"]
    images = {
        "control_plane": validate_digest_image(
            "control-plane",
            control_image,
            expected_repository=str(static["services"]["control_plane"]["image"]),
        ),
        "leadership_witness": validate_digest_image(
            "witness",
            witness_image,
            expected_repository=str(
                static["services"]["leadership_witness"]["image"]
            ),
        ),
        "worker": validate_digest_image(
            "worker",
            worker_image,
            expected_repository=str(static["services"]["worker"]["image"]),
        ),
        "postgres": validate_digest_image(
            "postgres",
            postgres_image,
            expected_repository=dependency_sources["postgres"]["repository"],
        ),
        "valkey": validate_digest_image(
            "valkey",
            valkey_image,
            expected_repository=dependency_sources["valkey"]["repository"],
        ),
        "minio": validate_digest_image(
            "minio",
            minio_image,
            expected_repository=dependency_sources["minio"]["repository"],
        ),
        "minio_client": validate_digest_image(
            "minio-client",
            minio_client_image,
            expected_repository=dependency_sources["minio_client"]["repository"],
        ),
    }
    output.mkdir(parents=True, exist_ok=True)
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
        "images": images,
        "contracts": {
            "config": {
                "path": str(config.relative_to(ROOT)),
                "sha256": digest(config),
            },
            "schema": {
                "path": str(schema.relative_to(ROOT)),
                "sha256": digest(schema),
            },
            "dependency_image_sources": {
                "path": str(DEPENDENCY_IMAGE_SOURCES.relative_to(ROOT)),
                "sha256": digest(DEPENDENCY_IMAGE_SOURCES),
            },
        },
    }
    manifest_path = output / "execution-fabric-release-manifest.json"
    write_json(manifest_path, manifest)
    image_lock_path = output / "execution-fabric-image-lock.json"
    write_json(
        image_lock_path,
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
            image_lock_path,
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
    parser.add_argument("--postgres-image")
    parser.add_argument("--valkey-image")
    parser.add_argument("--minio-image")
    parser.add_argument("--minio-client-image")
    args = parser.parse_args()
    validate_versions()
    if args.validate_only:
        return 0
    image_arguments = {
        "--control-plane-image": args.control_plane_image,
        "--witness-image": args.witness_image,
        "--worker-image": args.worker_image,
        "--postgres-image": args.postgres_image,
        "--valkey-image": args.valkey_image,
        "--minio-image": args.minio_image,
        "--minio-client-image": args.minio_client_image,
    }
    missing = [name for name, value in image_arguments.items() if not value]
    if missing:
        parser.error(
            "digest-pinned image arguments are required: " + ", ".join(missing)
        )
    build(
        args.output_dir,
        args.control_plane_image,
        args.witness_image,
        args.worker_image,
        args.postgres_image,
        args.valkey_image,
        args.minio_image,
        args.minio_client_image,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
