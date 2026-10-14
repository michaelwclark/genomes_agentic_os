"""Offline source-input rejection and actual producer/consumer contracts."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import runpy
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PREPARE = ROOT / "scripts/release/prepare-minio-build-inputs.py"
VERIFY = ROOT / "scripts/release/verify-minio-image-publication.py"
LOCK = ROOT / "deploy/execution-fabric/minio/upstream-lock.json"
SOURCES = ROOT / "deploy/execution-fabric/release-image-sources.json"


@pytest.fixture
def api() -> dict:
    return runpy.run_path(str(PREPARE))


def test_same_official_versions_and_complete_verified_input_closure(api: dict) -> None:
    lock = json.loads(LOCK.read_text())
    assert api["validate_lock"](lock, json.loads(SOURCES.read_text())) is lock
    assert lock["payloads"]["minio"]["version"] == "RELEASE.2025-09-07T16-13-09Z"
    assert lock["payloads"]["mc"]["version"] == "RELEASE.2025-08-13T08-35-41Z"
    assert lock["base"]["digest"].startswith("sha256:")
    assert set(lock["base"]["platforms"]) == {"amd64", "arm64"}


@pytest.mark.parametrize("mutation", [
    lambda lock: lock.update(schema_version="unknown"),
    lambda lock: lock.update(signature_public_key="untrusted"),
    lambda lock: lock.update(extra=True),
    lambda lock: lock["base"].update(digest="latest"),
    lambda lock: lock["base"].update(repository="registry.example.test/other"),
    lambda lock: lock["base"]["platforms"].pop("arm64"),
    lambda lock: lock["base"]["platforms"]["amd64"].update(curl_sha256="bad"),
    lambda lock: lock["verifier"].update(version="latest"),
    lambda lock: lock["verifier"]["linux"]["members"]["amd64"].update(path="../escape"),
    lambda lock: lock["payloads"]["minio"].update(version="latest"),
    lambda lock: lock["payloads"]["minio"].update(source_commit="bad"),
    lambda lock: lock["payloads"]["minio"].update(repository="unreviewed/minio"),
    lambda lock: lock["payloads"]["mc"]["platforms"].pop("amd64"),
    lambda lock: lock["payloads"]["minio"]["platforms"]["amd64"].pop("minisig"),
    lambda lock: lock["payloads"]["mc"]["platforms"]["arm64"]["binary"].update(asset_id=True),
    lambda lock: lock["payloads"]["mc"]["platforms"]["arm64"]["binary"].update(size=0),
    lambda lock: lock["payloads"]["minio"]["platforms"]["amd64"]["binary"].update(url="https://mirror.example.test/minio"),
    lambda lock: lock["sources"]["entrypoint"].update(url="https://raw.githubusercontent.com/minio/minio/master/dockerscripts/docker-entrypoint.sh"),
])
def test_incomplete_mutable_foreign_or_malformed_inputs_fail_before_context(api: dict, mutation, tmp_path: Path) -> None:
    lock = json.loads(LOCK.read_text())
    mutation(lock)
    path = tmp_path / "invalid-lock.json"
    path.write_text(json.dumps(lock))
    output = tmp_path / "context"
    with pytest.raises(ValueError):
        api["prepare"](path, output)
    assert not output.exists()


def test_exact_owned_repository_is_part_of_the_source_contract(api: dict) -> None:
    sources = json.loads(SOURCES.read_text())
    sources["images"]["minio"]["repository"] = "docker.io/minio/minio"
    with pytest.raises(ValueError, match="owned-image role disagree"):
        api["validate_lock"](json.loads(LOCK.read_text()), sources)


@pytest.mark.parametrize("sources", [None, {}, {"schema_version": "wrong", "images": {}}, {"schema_version": "execution-fabric-release-image-sources/v1", "images": []}])
def test_unstructured_image_sources_fail_at_the_input_boundary(api: dict, sources) -> None:
    with pytest.raises(ValueError):
        api["validate_lock"](json.loads(LOCK.read_text()), sources)


def test_cache_bytes_are_rehashed_and_bad_cache_never_falls_back(api: dict, tmp_path: Path) -> None:
    content = b"pinned input"
    item = {"url": "https://invalid.example.test/not-used", "sha256": sha256(content).hexdigest(), "size": len(content)}
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / item["sha256"]).write_bytes(content)
    output = tmp_path / "download"
    api["download"](item, output, cache=cache)
    assert output.read_bytes() == content
    (cache / item["sha256"]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="do not match the pin"):
        api["download"](item, tmp_path / "bad", cache=cache)
    assert not (tmp_path / "bad").exists()


def test_symlink_cache_is_not_immutable_input(api: dict, tmp_path: Path) -> None:
    content = b"correct bytes behind unowned link"
    source = tmp_path / "source"
    source.write_bytes(content)
    item = {"sha256": sha256(content).hexdigest(), "size": len(content)}
    link = tmp_path / "link"
    link.symlink_to(source)
    with pytest.raises(ValueError, match="do not match the pin"):
        api["verify_file"](link, item)


@pytest.mark.parametrize("kind", ["broken-link", "directory"])
def test_unusable_cache_entry_cannot_fall_back_to_a_download(api: dict, tmp_path: Path, kind: str) -> None:
    item = {"sha256": "a" * 64, "size": 1}
    cached = tmp_path / item["sha256"]
    if kind == "broken-link":
        cached.symlink_to(tmp_path / "absent")
    else:
        cached.mkdir()
    with pytest.raises(ValueError, match="do not match the pin"):
        api["download"](item, tmp_path / "download", cache=tmp_path)
    assert not (tmp_path / "download").exists()


@pytest.mark.parametrize("arch,machine", [("amd64", 62), ("arm64", 183)])
def test_actual_binary_bytes_checksum_and_architecture_contract(api: dict, tmp_path: Path, arch: str, machine: int) -> None:
    header = bytearray(20)
    header[:6] = b"\x7fELF\x02\x01"
    header[18:20] = machine.to_bytes(2, "little")
    binary = tmp_path / "binary"
    binary.write_bytes(header)
    value = sha256(header).hexdigest()
    checksum = tmp_path / "checksum"
    checksum.write_text(value + "  binary\n")
    api["verify_binary"](binary, arch, checksum, value)
    with pytest.raises(ValueError, match="architecture"):
        api["verify_binary"](binary, "arm64" if arch == "amd64" else "amd64", checksum, value)
    binary.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        api["verify_binary"](binary, arch, checksum, value)


def test_actual_release_asset_ids_sizes_names_digests_are_required(api: dict) -> None:
    payload = json.loads(LOCK.read_text())["payloads"]["mc"]
    release = {"id": payload["release_id"], "tag_name": payload["version"], "draft": False, "published_at": "2025-08-13T00:00:00Z", "assets": [{"id": item["asset_id"], "name": item["url"].rsplit("/", 1)[1], "size": item["size"], "digest": "sha256:" + item["sha256"]} for downloads in payload["platforms"].values() for item in downloads.values()]}
    api["validate_release"](payload, release)
    for key, replacement in [("id", 1), ("size", 1), ("digest", "sha256:" + "0" * 64), ("name", "other-version")]:
        bad = deepcopy(release)
        bad["assets"][0][key] = replacement
        with pytest.raises(ValueError, match="inventory"):
            api["validate_release"](payload, bad)


def test_invalid_cli_refuses_without_download_or_context(tmp_path: Path) -> None:
    lock = tmp_path / "invalid.json"
    lock.write_text("{}")
    result = subprocess.run([sys.executable, str(PREPARE), "--lock", str(lock), "--output-dir", str(tmp_path / "context")], capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert "lock must contain exactly" in result.stderr
    assert not (tmp_path / "context").exists()


def test_published_smoke_rejects_swapped_owned_roles_before_docker(tmp_path: Path) -> None:
    source_images = json.loads(SOURCES.read_text())["images"]
    result = subprocess.run([
        sys.executable, str(ROOT / "scripts/release/smoke-minio-source-images.py"),
        "--published", "--platform", "linux/amd64", "--namespace", "minio-source-test",
        "--minio-image", source_images["minio_client"]["repository"] + "@sha256:" + "a" * 64,
        "--client-image", source_images["minio"]["repository"] + "@sha256:" + "a" * 64,
        "--output", str(tmp_path / "smoke.json"),
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert "exact owned immutable image references" in result.stderr
    assert not (tmp_path / "smoke.json").exists()


def test_rejected_image_cleans_its_owned_anonymous_volume(monkeypatch, tmp_path: Path) -> None:
    """A failed identity probe must remove the Dockerfile's anonymous /data."""
    api = runpy.run_path(str(ROOT / "scripts/release/smoke-minio-source-images.py"))
    commands = []
    container = "1" * 64

    def docker_failure(arguments, **kwargs):
        commands.append(arguments)
        if arguments[0] == "create":
            return container.encode()
        if arguments[0] == "cp":
            raise ValueError("identity probe rejected before runtime acceptance")
        return b""

    monkeypatch.setitem(api["verify_identity"].__globals__, "docker", docker_failure)
    with pytest.raises(ValueError, match="identity probe rejected"):
        api["verify_identity"]("unit-fixture", "minio", "amd64", {}, tmp_path)
    assert commands[-1] == ["rm", "--force", "--volumes", container]


def test_real_pr_smokes_gate_existing_required_check_and_tag_assets() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/test.yml").read_text())
    assert workflow["jobs"]["deployment-contracts"]["needs"] == "minio-source-images"
    assert workflow["jobs"]["minio-source-images"]["uses"] == "./.github/workflows/minio-source-images.yml"
    companion = yaml.safe_load((ROOT / ".github/workflows/minio-source-images.yml").read_text())
    assert companion["jobs"]["runtime"]["strategy"]["matrix"]["arch"] == ["amd64", "arm64"]
    builds = [step["with"] for step in companion["jobs"]["runtime"]["steps"] if step.get("uses") == "docker/build-push-action@v6"]
    assert len(builds) == 2 and all(build["push"] is False and build["load"] is True for build in builds)
    release = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    assert "minio-images" in release["jobs"]["assets"]["needs"]
    assert len(release["jobs"]["github-release"]["with"]["asset_manifest"].splitlines()) == 8


def test_registry_presentation_and_runtime_platform_proof_fail_closed() -> None:
    api = runpy.run_path(str(VERIFY))
    raw = b'{"verified":"bytes"}'
    digest = sha256(raw).hexdigest()
    assert api["canonical_bytes"](raw + b"\n", digest) == raw
    with pytest.raises(ValueError, match="manifest bytes"):
        api["canonical_bytes"](raw, "0" * 64)
    index = {"mediaType": "application/vnd.oci.image.index.v1+json", "manifests": [{"platform": {"os": "linux", "architecture": arch}, "digest": "sha256:" + "a" * 64, "size": 1} for arch in ["amd64", "arm64"]]}
    assert set(api["index_children"](index)) == {"amd64", "arm64"}
    index["manifests"].pop()
    with pytest.raises(ValueError, match="lacks"):
        api["index_children"](index)
    assert api["has_verified_subject"]([], digest) is False
    assert api["has_verified_subject"]([{"verificationResult": {"statement": {"subject": [{"digest": {"sha256": digest}}]}}}], digest) is False
    verified = [{"verificationResult": {"signature": {"certificate": {"sourceRepositoryUri": "https://github.com/michaelwclark/genomes_agentic_os"}}, "statement": {"subject": [{"digest": {"sha256": digest}}]}}}]
    assert api["has_verified_subject"](verified, digest) is True
    verified[0]["verificationResult"]["signature"]["certificate"] = "unstructured"
    assert api["has_verified_subject"](verified, digest) is False
