from __future__ import annotations

from importlib import resources
from hashlib import sha256
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tarfile
import tomllib

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/release/build-execution-fabric-release.py"
IMAGE_SOURCES = ROOT / "deploy/execution-fabric/release-image-sources.json"


def _image_arguments(digest: str) -> list[str]:
    return [
        "--control-plane-image",
        "ghcr.io/michaelwclark/"
        f"genomes-agentic-os-execution-fabric-control-plane@sha256:{digest}",
        "--witness-image",
        "ghcr.io/michaelwclark/"
        f"genomes-agentic-os-execution-fabric-leadership-witness@sha256:{digest}",
        "--worker-image",
        "ghcr.io/michaelwclark/"
        f"genomes-agentic-os-execution-fabric-worker@sha256:{digest}",
        "--postgres-image",
        f"docker.io/library/postgres@sha256:{digest}",
        "--valkey-image",
        f"docker.io/valkey/valkey@sha256:{digest}",
        "--minio-image",
        f"ghcr.io/michaelwclark/genomes-agentic-os-execution-fabric-minio@sha256:{digest}",
        "--minio-client-image",
        f"ghcr.io/michaelwclark/genomes-agentic-os-execution-fabric-minio-client@sha256:{digest}",
    ]


def _minio_publication_fixture(path: Path, digest: str) -> Path:
    """Model a closed CI producer receipt for consumer boundary unit tests."""
    lock_path = ROOT / "deploy/execution-fabric/minio/upstream-lock.json"
    lock = json.loads(lock_path.read_text())
    lock_hash = sha256(lock_path.read_bytes()).hexdigest()
    images = {name: json.loads(IMAGE_SOURCES.read_text())["images"][name]["repository"] + "@sha256:" + digest for name in ["minio", "minio_client"]}
    files = {f"bin/{arch}/{role}" + {"binary": "", "sha256sum": ".sha256sum", "minisig": ".minisig"}[kind]: item["sha256"] for role, payload in lock["payloads"].items() for arch, downloads in payload["platforms"].items() for kind, item in downloads.items()}
    files.update({"contracts/" + name: item["sha256"] for name, item in lock["sources"].items()})
    files.update({"Dockerfile": sha256((ROOT / "deploy/execution-fabric/minio/Dockerfile").read_bytes()).hexdigest(), "upstream-lock.json": lock_hash})
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip()
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    inputs = {"status": "verified", "source_sha": source, "source_tree": tree, "signature_verifications": 4, "lock_sha256": lock_hash, "image_sources_sha256": sha256(IMAGE_SOURCES.read_bytes()).hexdigest(), "files": files}
    smokes = {}
    for arch in ["amd64", "arm64"]:
        identities = {role: {"binary_sha256": payload["platforms"][arch]["binary"]["sha256"], "release": payload["version"], "source_commit": payload["source_commit"], "curl_sha256": lock["base"]["platforms"][arch]["curl_sha256"]} for role, payload in lock["payloads"].items()}
        cases = [{"credentials": mode, "effective_uid": uid, "ready": True, "bucket_privacy_and_versioning": True, "object_write_read_restart_read_delete": True} for mode, uid in [("file", 0), ("env", 0), ("file", 1000)]]
        smokes[arch] = {"receipt": {"schema_version": "execution-fabric-minio-runtime-smoke/v1", "status": "passed", "platform": "linux/" + arch, "images": images, "source_lock_sha256": lock_hash, "fixture_resources_removed": True, "identities": identities, "cases": cases}}
    value = {"schema_version": "execution-fabric-minio-publication/v1", "status": "verified", "repository": "michaelwclark/genomes_agentic_os", "source_sha": source, "source_ref": "refs/tags/v" + version, "source_lock_sha256": lock_hash, "inputs": inputs, "runtime_smokes": smokes, "images": {role: {"image": image, "children": {arch: {"digest": "sha256:" + digest, "size": 100} for arch in ["amd64", "arm64"]}, "verified_provenance_sha256": "b" * 64} for role, image in images.items()}}
    path.write_text(json.dumps(value))
    return path


def test_published_distribution_validation_is_release_gated() -> None:
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    for tree in ("harness", "templates", "operating-manual", "schemas"):
        assert f"recursive-include {tree} *" in manifest
    workflow = (ROOT / ".github/workflows/test.yml").read_text(encoding="utf-8")
    assert "python scripts/qa/validate-python-distributions.py" in workflow


def test_release_versions_and_contracts_are_coherent() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--validate-only"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_release_validator_covers_every_canonical_version_source() -> None:
    namespace = runpy.run_path(str(SCRIPT))
    validated = namespace["validate_versions"]()
    versions = validated["versions"]
    assert set(versions) == {
        "release",
        "python",
        "python_runtime",
        "python_lock",
        "control_plane",
        "control_plane_lock",
        "control_plane_lock_root",
        "leadership_witness",
        "leadership_witness_lock",
        "leadership_witness_lock_root",
        "worker_chart",
        "worker_app",
    }
    assert len(set(versions.values())) == 1


def test_release_checksum_staging_file_is_outside_the_asset_directory() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert 'mktemp "${RUNNER_TEMP}/execution-fabric-SHA256SUMS.' in workflow
    assert "SHA256SUMS.tmp" not in workflow


def test_release_workflow_requires_main_ancestry_and_additive_contract() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert 'git fetch --no-tags origin "+refs/heads/main:refs/remotes/origin/main"' in workflow
    assert 'git merge-base --is-ancestor "${GITHUB_SHA}" origin/main' in workflow
    assert "uses: ./.github/workflows/release-contract.yml" in workflow
    assert "tag_mode: verify" in workflow
    assert "artifact_name: execution-fabric-release-assets" in workflow
    assert "execution-fabric-release-manifest.json" in workflow
    assert "SHA256SUMS" in workflow
    assert "--clobber" not in workflow
    assert "exit 73" not in workflow


def test_release_workflow_resolves_dependency_multiarch_index_digests() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "deploy/execution-fabric/release-image-sources.json" in workflow
    assert '"{{json .Manifest}}"' in workflow
    assert "application/vnd.oci.image.index.v1+json" in workflow
    assert "application/vnd.docker.distribution.manifest.list.v2+json" in workflow
    assert '{"linux/amd64", "linux/arm64"}' in workflow
    for name in ("postgres", "valkey"):
        assert f"{name}: ${{{{ steps.resolve.outputs.{name} }}}}" in workflow
        assert f"needs.dependency-images.outputs.{name}" in workflow
    for name in ("minio", "minio_client"):
        assert f"needs.minio-images.outputs.{name}" in workflow


def test_dependency_image_sources_are_canonical_and_reviewed() -> None:
    sources = json.loads(IMAGE_SOURCES.read_text(encoding="utf-8"))
    assert sources == {
        "schema_version": "execution-fabric-release-image-sources/v1",
        "images": {
            "postgres": {
                "repository": "docker.io/library/postgres",
                "tag": "17.10-alpine",
            },
            "valkey": {
                "repository": "docker.io/valkey/valkey",
                "tag": "8.1.9-alpine",
            },
            "minio": {
                "repository": "ghcr.io/michaelwclark/genomes-agentic-os-execution-fabric-minio",
                "tag": "RELEASE.2025-09-07T16-13-09Z",
            },
            "minio_client": {
                "repository": "ghcr.io/michaelwclark/genomes-agentic-os-execution-fabric-minio-client",
                "tag": "RELEASE.2025-08-13T08-35-41Z",
            },
        },
    }


def test_dependency_image_source_validator_fails_closed(tmp_path: Path) -> None:
    namespace = runpy.run_path(str(SCRIPT))
    validate_sources = namespace["load_dependency_image_sources"]
    invalid = json.loads(IMAGE_SOURCES.read_text(encoding="utf-8"))
    invalid["images"]["postgres"]["tag"] = "latest"
    invalid_path = tmp_path / "invalid-sources.json"
    invalid_path.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(ValueError, match="non-latest"):
        validate_sources(invalid_path)


def test_ci_runs_the_real_witness_oci_smoke() -> None:
    workflow = (ROOT / ".github/workflows/test.yml").read_text(encoding="utf-8")
    assert "tests/scripts/run-witness-oci-smoke.sh" in workflow


def test_release_builder_emits_digest_locked_portable_assets(tmp_path: Path) -> None:
    digest = "a" * 64
    fixture = _minio_publication_fixture(tmp_path / "producer-fixture.json", digest)
    tmp_path = tmp_path / "assets"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--output-dir",
            str(tmp_path),
            *_image_arguments(digest),
            "--minio-publication-receipt",
            str(fixture),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    manifest = json.loads(
        (tmp_path / "execution-fabric-release-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    package_version = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["version"]
    assert manifest["python_package"]["version"] == package_version
    assert set(manifest["images"]) == {
        "control_plane",
        "leadership_witness",
        "worker",
        "postgres",
        "valkey",
        "minio",
        "minio_client",
    }
    image_lock = json.loads(
        (tmp_path / "execution-fabric-image-lock.json").read_text(
            encoding="utf-8"
        )
    )
    assert image_lock["images"] == manifest["images"]
    materialized = subprocess.run(
        [
            "sh",
            str(
                ROOT
                / "installers/execution-fabric/bin/materialize-image-lock.sh"
            ),
            str(tmp_path / "execution-fabric-image-lock.json"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert materialized.returncode == 0, materialized.stderr
    assert len(materialized.stdout.splitlines()) == 7
    assert "FABRIC_WITNESS_IMAGE=" in materialized.stdout
    assert "FABRIC_WORKER_IMAGE=" in materialized.stdout
    digest_image = runpy.run_path(str(SCRIPT))["DIGEST_IMAGE"]
    for image in image_lock["images"].values():
        assert digest_image.fullmatch(image)
        assert ":latest" not in image
        assert image.count("@") == 1
    source_contract = manifest["contracts"]["dependency_image_sources"]
    assert source_contract["path"] == str(IMAGE_SOURCES.relative_to(ROOT))
    assert len(source_contract["sha256"]) == 64
    assert (tmp_path / "execution-fabric-emergency-bundle.tar.gz").is_file()
    with tarfile.open(
        tmp_path / "execution-fabric-emergency-bundle.tar.gz", "r:gz"
    ) as archive:
        assert (
            "release-generated/execution-fabric-image-lock.json"
            in archive.getnames()
        )
    assert "execution-fabric-image-lock.json" in (
        tmp_path / "SHA256SUMS"
    ).read_text(encoding="utf-8")


def test_release_builder_rejects_mutable_or_wrong_repository_images(
    tmp_path: Path,
) -> None:
    digest = "c" * 64
    arguments = _image_arguments(digest)
    arguments[arguments.index("--postgres-image") + 1] = (
        "docker.io/library/postgres:17.10-alpine"
    )
    mutable = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--output-dir",
            str(tmp_path / "mutable"),
            *arguments,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert mutable.returncode != 0
    assert "immutable repository@sha256" in mutable.stderr

    arguments = _image_arguments(digest)
    arguments[arguments.index("--postgres-image") + 1] = (
        f"docker.io/example/postgres@sha256:{digest}"
    )
    wrong_repository = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--output-dir",
            str(tmp_path / "wrong-repository"),
            *arguments,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert wrong_repository.returncode != 0
    assert "repository must be docker.io/library/postgres" in wrong_repository.stderr


def test_release_builder_requires_all_seven_exact_images(tmp_path: Path) -> None:
    arguments = _image_arguments("d" * 64)
    minio_client_index = arguments.index("--minio-client-image")
    del arguments[minio_client_index : minio_client_index + 2]
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--output-dir",
            str(tmp_path),
            *arguments,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "--minio-client-image" in result.stderr


def test_wheel_resource_index_keeps_large_assets_out_of_installed_root() -> None:
    index = resources.files("genomes_agentic_os").joinpath(
        "resources/release-assets.json"
    )
    value = json.loads(index.read_text(encoding="utf-8"))
    assert value["portable_bundle"].endswith(".tar.gz")
    assert value["repository_env"] == "GENOMES_AGENTIC_OS_RELEASE_REPOSITORY"
    assert "{repository}" in value["release_url_template"]
    assert value["release_url_template"].startswith("https://github.com/")


def test_portable_archives_are_reproducible(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    digest = "b" * 64
    for output in (first, second):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--output-dir",
                str(output),
                *_image_arguments(digest),
                "--minio-publication-receipt",
                str(_minio_publication_fixture(tmp_path / "producer-fixture.json", digest)),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    for name in (
        "execution-fabric-emergency-bundle.tar.gz",
        "execution-fabric-config-schema.tar.gz",
    ):
        assert (first / name).read_bytes() == (second / name).read_bytes()


@pytest.mark.parametrize("missing", ["provenance", "platform", "signature", "source", "persistence", "binary", "child"])
def test_release_assets_refuse_unqualified_owned_minio_inputs(tmp_path: Path, missing: str) -> None:
    digest = "d" * 64
    path = _minio_publication_fixture(tmp_path / "proof.json", digest)
    proof = json.loads(path.read_text())
    if missing == "provenance":
        proof["images"]["minio"].pop("verified_provenance_sha256")
    elif missing == "platform":
        proof["runtime_smokes"].pop("arm64")
    elif missing == "signature":
        proof["inputs"]["signature_verifications"] = 3
    elif missing == "source":
        proof["source_sha"] = "0" * 40
    elif missing == "persistence":
        proof["runtime_smokes"]["amd64"]["receipt"]["cases"][0]["object_write_read_restart_read_delete"] = False
    elif missing == "child":
        proof["images"]["minio_client"]["children"]["amd64"]["digest"] = "mutable"
    else:
        proof["runtime_smokes"]["arm64"]["receipt"]["identities"]["mc"]["binary_sha256"] = "0" * 64
    path.write_text(json.dumps(proof))
    result = subprocess.run([sys.executable, str(SCRIPT), "--output-dir", str(tmp_path / "assets"), *_image_arguments(digest), "--minio-publication-receipt", str(path)], capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert not (tmp_path / "assets").exists()
