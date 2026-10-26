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
import subprocess
import tarfile
import tomllib

import yaml


ROOT = Path(__file__).resolve().parents[2]
STATIC_MANIFEST = ROOT / "release/execution-fabric-manifest.yml"
DEPENDENCY_IMAGE_SOURCES = (
    ROOT / "deploy/execution-fabric/release-image-sources.json"
)
MINIO_SOURCE_LOCK = ROOT / "deploy/execution-fabric/minio/upstream-lock.json"
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


def validate_minio_publication(path: Path | None, images: dict, version: str) -> dict:
    """Require current verified owned indexes and real both-architecture proof."""
    if path is None:
        raise ValueError("owned MinIO images require their current publication receipt")
    proof = load_json(path)
    source_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    source_tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip()
    lock = load_json(MINIO_SOURCE_LOCK)
    inputs = proof.get("inputs", {})
    if not isinstance(inputs, dict):
        raise ValueError("MinIO publication has no structured input receipt")
    if (
        proof.get("schema_version") != "execution-fabric-minio-publication/v1"
        or proof.get("status") != "verified"
        or proof.get("repository") != "michaelwclark/genomes_agentic_os"
        or proof.get("source_sha") != source_sha
        or proof.get("source_ref") != "refs/tags/v" + version
        or proof.get("source_lock_sha256") != digest(MINIO_SOURCE_LOCK)
        or inputs.get("status") != "verified"
        or inputs.get("source_sha") != source_sha
        or inputs.get("source_tree") != source_tree
        or inputs.get("signature_verifications") != 4
        or inputs.get("lock_sha256") != digest(MINIO_SOURCE_LOCK)
        or inputs.get("image_sources_sha256") != digest(DEPENDENCY_IMAGE_SOURCES)
    ):
        raise ValueError("MinIO publication/input proof is missing, stale or from another source")
    expected_files = {
        f"bin/{arch}/{role}" + {"binary": "", "sha256sum": ".sha256sum", "minisig": ".minisig"}[kind]: item["sha256"]
        for role, payload in lock["payloads"].items()
        for arch, downloads in payload["platforms"].items()
        for kind, item in downloads.items()
    }
    expected_files.update({"contracts/" + name: item["sha256"] for name, item in lock["sources"].items()})
    expected_files.update({"Dockerfile": digest(ROOT / "deploy/execution-fabric/minio/Dockerfile"), "upstream-lock.json": digest(MINIO_SOURCE_LOCK)})
    if inputs.get("files") != expected_files:
        raise ValueError("MinIO prepared source/binary/signature file inventory differs")
    expected_images = {name: images[name] for name in ("minio", "minio_client")}
    observed_images = proof.get("images")
    smokes = proof.get("runtime_smokes")
    if not isinstance(observed_images, dict) or set(observed_images) != set(expected_images) or not isinstance(smokes, dict) or set(smokes) != {"amd64", "arm64"}:
        raise ValueError("MinIO publication role/platform closure is incomplete")
    for role, image in expected_images.items():
        observed = observed_images[role]
        if not isinstance(observed, dict) or observed.get("image") != image or not isinstance(observed.get("children"), dict) or set(observed["children"]) != {"amd64", "arm64"} or not re.fullmatch(r"[0-9a-f]{64}", str(observed.get("verified_provenance_sha256", ""))):
            raise ValueError("MinIO immutable indexes or signed provenance differ")
        for child in observed["children"].values():
            if not isinstance(child, dict) or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(child.get("digest", ""))) or type(child.get("size")) is not int or child["size"] <= 0:
                raise ValueError("MinIO child manifest digest/size is invalid")
    for arch, item in smokes.items():
        if not isinstance(item, dict):
            raise ValueError("MinIO published-image smoke is not structured")
        smoke = item.get("receipt", {})
        if not isinstance(smoke, dict) or smoke.get("schema_version") != "execution-fabric-minio-runtime-smoke/v1" or smoke.get("status") != "passed" or smoke.get("platform") != "linux/" + arch or smoke.get("images") != expected_images or smoke.get("source_lock_sha256") != digest(MINIO_SOURCE_LOCK) or smoke.get("fixture_resources_removed") is not True:
            raise ValueError("MinIO published-image smoke is missing or mismatched")
        runtime_images = {role: image.split("@")[0] + "@" + observed_images[role]["children"][arch]["digest"] for role, image in expected_images.items()}
        if smoke.get("runtime_images") != runtime_images:
            raise ValueError("MinIO runtime children differ from the verified parent/platform")
        cases = smoke.get("cases", [])
        if not isinstance(cases, list) or len(cases) != 3 or any(not isinstance(case, dict) for case in cases) or {(case.get("credentials"), case.get("effective_uid")) for case in cases} != {("file", 0), ("env", 0), ("file", 1000)} or any(case.get("ready") is not True or case.get("bucket_privacy_and_versioning") is not True or case.get("object_write_read_restart_read_delete") is not True for case in cases):
            raise ValueError("MinIO actual credential/health/persistence cases are incomplete")
        for role in ("minio", "mc"):
            identities = smoke.get("identities")
            if not isinstance(identities, dict) or set(identities) != {"minio", "mc"}:
                raise ValueError("MinIO runtime identity closure is incomplete")
            identity = identities[role]
            payload = lock["payloads"][role]
            if not isinstance(identity, dict) or identity.get("binary_sha256") != payload["platforms"][arch]["binary"]["sha256"] or identity.get("release") != payload["version"] or identity.get("source_commit") != payload["source_commit"] or identity.get("curl_sha256") != lock["base"]["platforms"][arch]["curl_sha256"]:
                raise ValueError("MinIO rebuilt runtime does not match pinned upstream/base bytes")
    return proof


def build(
    output: Path,
    control_image: str,
    witness_image: str,
    worker_image: str,
    postgres_image: str,
    valkey_image: str,
    minio_image: str,
    minio_client_image: str,
    minio_publication_receipt: Path | None = None,
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
    minio_proof = validate_minio_publication(minio_publication_receipt, images, validated["versions"]["release"])
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
        "minio_publication": minio_proof,
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
            "minio_source_lock": {
                "path": str(MINIO_SOURCE_LOCK.relative_to(ROOT)),
                "sha256": digest(MINIO_SOURCE_LOCK),
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
            ROOT / "docs/development/fabric-held-restoration.md",
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
    parser.add_argument("--minio-publication-receipt", type=Path)
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
        args.minio_publication_receipt,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
