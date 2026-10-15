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
    published = [step for step in companion["jobs"]["runtime"]["steps"] if "--published-fixture" in step.get("run", "")]
    assert len(published) == 1 and published[0]["if"] == "matrix.arch == 'amd64'"
    assert "tests/fixtures/minio_published_transport_v0_11_1.json" in published[0]["run"]
    assert published[0].get("continue-on-error", False) is False
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
    index = {"mediaType": "application/vnd.oci.image.index.v1+json", "manifests": [{"mediaType": "application/vnd.oci.image.manifest.v1+json", "platform": {"os": "linux", "architecture": arch}, "digest": "sha256:" + "a" * 64, "size": 1} for arch in ["amd64", "arm64"]]}
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


def _runtime_registry() -> tuple[dict, dict, dict]:
    """Build content-addressed unit manifests with distinct role/arch leaves."""
    images, manifests, children = {}, {}, {}
    repositories = json.loads(SOURCES.read_text())["images"]
    media = "application/vnd.oci.image.manifest.v1+json"
    for role in ["minio", "minio_client"]:
        descriptors = []
        children[role] = {}
        for arch in ["amd64", "arm64"]:
            raw = json.dumps({"schemaVersion": 2, "mediaType": media,
                              "config": {"digest": "sha256:" + "a" * 64, "size": 1},
                              "layers": [], "annotations": {"unit-role": role, "unit-arch": arch}},
                             sort_keys=True).encode()
            child = {"digest": "sha256:" + sha256(raw).hexdigest(), "size": len(raw)}
            children[role][arch] = child
            manifests[repositories[role]["repository"] + "@" + child["digest"]] = raw
            descriptors.append({**child, "mediaType": media, "platform": {"os": "linux", "architecture": arch}})
        raw = json.dumps({"schemaVersion": 2, "mediaType": "application/vnd.oci.image.index.v1+json",
                          "manifests": descriptors}, sort_keys=True).encode()
        parent = repositories[role]["repository"] + "@sha256:" + sha256(raw).hexdigest()
        images[role] = parent
        manifests[parent] = raw
    return images, manifests, children


@pytest.mark.parametrize("role,arch", [("minio", "amd64"), ("minio", "arm64"), ("minio_client", "amd64"), ("minio_client", "arm64")])
def test_runtime_resolver_verifies_parent_and_selected_leaf(role: str, arch: str) -> None:
    api = runpy.run_path(str(VERIFY))
    images, manifests, children = _runtime_registry()
    reads = []

    def read_manifest(reference: str) -> bytes:
        reads.append(reference)
        return manifests[reference] + b"\n"

    selected = images[role].split("@")[0] + "@" + children[role][arch]["digest"]
    assert api["resolve_runtime_child"](images[role], arch, read_manifest) == selected
    assert reads == [images[role], selected]


@pytest.mark.parametrize("corruption", [
    "parent-bytes", "parent-media", "missing-arch", "duplicate-arch", "foreign-arch",
    "descriptor-media", "descriptor-digest", "descriptor-size-bool", "child-bytes",
    "child-size", "child-media", "child-schema",
])
def test_runtime_resolver_rejects_invalid_content_or_platform(corruption: str) -> None:
    api = runpy.run_path(str(VERIFY))
    images, manifests, _ = _runtime_registry()
    parent = images["minio"]
    index = json.loads(manifests[parent])
    descriptor = index["manifests"][0]
    child_reference = parent.split("@")[0] + "@" + descriptor["digest"]
    if corruption == "parent-bytes":
        manifests[parent] += b"invalid"
    else:
        if corruption == "parent-media":
            index["mediaType"] = "application/vnd.oci.image.manifest.v1+json"
        elif corruption == "missing-arch":
            index["manifests"].pop()
        elif corruption == "duplicate-arch":
            index["manifests"].append(deepcopy(descriptor))
        elif corruption == "foreign-arch":
            descriptor["platform"]["architecture"] = "riscv64"
        elif corruption == "descriptor-media":
            descriptor["mediaType"] = "application/vnd.oci.image.index.v1+json"
        elif corruption == "descriptor-digest":
            descriptor["digest"] = "mutable"
        elif corruption == "descriptor-size-bool":
            descriptor["size"] = True
        elif corruption == "child-bytes":
            manifests[child_reference] += b"invalid"
        elif corruption == "child-size":
            descriptor["size"] += 1
        else:
            child = json.loads(manifests[child_reference])
            child["mediaType" if corruption == "child-media" else "schemaVersion"] = "wrong"
            raw = json.dumps(child, sort_keys=True).encode()
            descriptor["digest"] = "sha256:" + sha256(raw).hexdigest()
            descriptor["size"] = len(raw)
            manifests[parent.split("@")[0] + "@" + descriptor["digest"]] = raw
        raw = json.dumps(index, sort_keys=True).encode()
        parent = parent.split("@")[0] + "@sha256:" + sha256(raw).hexdigest()
        manifests[parent] = raw
    with pytest.raises(ValueError):
        api["resolve_runtime_child"](parent, "amd64", manifests.__getitem__)


@pytest.mark.parametrize("corruption", ["wrong-arch", "parent", "foreign", "missing"])
def test_published_runtime_receipt_must_bind_the_matching_owned_children(corruption: str) -> None:
    api = runpy.run_path(str(VERIFY))
    images, _, children = _runtime_registry()
    runtime = {role: image.split("@")[0] + "@" + children[role]["arm64"]["digest"] for role, image in images.items()}
    smoke = {"images": images, "platform": "linux/arm64", "runtime_images": runtime}
    api["verify_runtime_binding"](smoke, images, children, "arm64")
    if corruption == "wrong-arch":
        runtime["minio"] = images["minio"].split("@")[0] + "@" + children["minio"]["amd64"]["digest"]
    elif corruption == "parent":
        runtime["minio"] = images["minio"]
    elif corruption == "foreign":
        runtime["minio"] = "registry.example.test/other@" + children["minio"]["arm64"]["digest"]
    else:
        smoke.pop("runtime_images")
    with pytest.raises(ValueError, match="verified parent/platform"):
        api["verify_runtime_binding"](smoke, images, children, "arm64")


@pytest.mark.parametrize("published", [True, False])
def test_all_smoke_consumers_receive_runtime_leaves_while_custody_retains_parents(monkeypatch, tmp_path: Path, published: bool) -> None:
    api = runpy.run_path(str(ROOT / "scripts/release/smoke-minio-source-images.py"))
    images, manifests, children = _runtime_registry()
    if not published:
        images = {"minio": "local-minio:unit", "minio_client": "local-mc:unit"}
    reads, identities, cases = [], [], []

    def docker(arguments: list[str], **kwargs) -> bytes:
        assert arguments[:4] == ["buildx", "imagetools", "inspect", "--raw"]
        reads.append(arguments[-1])
        return manifests[arguments[-1]]

    def identity(image: str, role: str, arch: str, lock: dict, temporary: Path) -> dict:
        identities.append((image, role, arch))
        return {"unit": True}

    def exercise(minio: str, client: str, arch: str, namespace: str, temporary: Path, mode: str, uid: int) -> dict:
        cases.append((minio, client, arch, mode, uid))
        return {"credentials": mode, "effective_uid": uid}

    namespace = api["run_smoke"].__globals__
    for name, value in [("docker", docker), ("verify_identity", identity), ("exercise", exercise)]:
        monkeypatch.setitem(namespace, name, value)
    receipt = api["run_smoke"](images, "linux/arm64", "minio-source-unit", tmp_path / "smoke.json", published=published)
    expected = {role: image.split("@")[0] + "@" + children[role]["arm64"]["digest"] for role, image in images.items()} if published else images
    assert receipt["images"] == images
    assert receipt["runtime_images"] == expected
    assert identities == [(expected["minio"], "minio", "arm64"), (expected["minio_client"], "mc", "arm64")]
    assert cases == [(expected["minio"], expected["minio_client"], "arm64", mode, uid) for mode, uid in [("file", 0), ("env", 0), ("file", 1000)]]
    assert len(reads) == (4 if published else 0)
    assert json.loads((tmp_path / "smoke.json").read_text()) == receipt


def test_actual_identity_command_transport_uses_the_selected_child(monkeypatch, tmp_path: Path) -> None:
    api = runpy.run_path(str(ROOT / "scripts/release/smoke-minio-source-images.py"))
    image = "ghcr.io/michaelwclark/genomes-agentic-os-execution-fabric-minio@sha256:" + "a" * 64
    container = "1" * 64
    commands = []
    binary, curl = b"unit-official-payload", b"unit-base-curl"
    lock = {"payloads": {"minio": {"version": "release-unit", "source_commit": "source-unit",
             "platforms": {"arm64": {"binary": {"sha256": sha256(binary).hexdigest()}}}}},
            "base": {"platforms": {"arm64": {"curl_sha256": sha256(curl).hexdigest()}}}}

    def docker(arguments: list[str], **kwargs) -> bytes:
        commands.append(arguments)
        if arguments[0] == "create":
            assert arguments == ["create", "--platform", "linux/arm64", image]
            return container.encode()
        if arguments[0] == "cp":
            Path(arguments[2]).write_bytes(curl if arguments[1].endswith("/curl") else binary)
        if arguments[0] == "run":
            assert arguments == ["run", "--rm", "--platform", "linux/arm64", "--entrypoint", "/usr/bin/minio", image, "--version"]
            return b"release-unit source-unit"
        if arguments[0] == "inspect":
            return b'"sha256:unit-image-id"'
        return b""

    monkeypatch.setitem(api["verify_identity"].__globals__, "docker", docker)
    result = api["verify_identity"](image, "minio", "arm64", lock, tmp_path)
    assert result["binary_sha256"] == sha256(binary).hexdigest()
    assert commands[-1] == ["rm", "--force", "--volumes", container]


def test_actual_runtime_command_transport_uses_server_and_client_children(monkeypatch, tmp_path: Path) -> None:
    api = runpy.run_path(str(ROOT / "scripts/release/smoke-minio-source-images.py"))
    images, _, children = _runtime_registry()
    server, client = [images[role].split("@")[0] + "@" + children[role]["arm64"]["digest"] for role in ["minio", "minio_client"]]
    commands = []
    namespace, network, container = "minio-source-unit", "1" * 64, "2" * 64

    def docker(arguments: list[str], **kwargs) -> bytes:
        commands.append(arguments)
        if arguments[:2] in [["network", "inspect"], ["volume", "inspect"]]:
            return b""
        if arguments[:2] == ["network", "create"]:
            return network.encode()
        if arguments[:2] == ["volume", "create"]:
            return (namespace + "-data").encode()
        if arguments[0] == "run":
            assert server in arguments or client in arguments
            assert all(image not in arguments for image in images.values())
            if "--detach" in arguments:
                return container.encode()
            if "cat" in arguments:
                return b"same-release-persistence-arm64"
        if arguments[0] == "exec":
            return b"Uid:\t1000\t1000\t1000\t1000\n"
        return b""

    namespace_globals = api["exercise"].__globals__
    monkeypatch.setitem(namespace_globals, "docker", docker)
    monkeypatch.setitem(namespace_globals, "wait_ready", lambda container: None)
    receipt = api["exercise"](server, client, "arm64", namespace, tmp_path, "file", 1000)
    assert receipt["object_write_read_restart_read_delete"] is True
    assert len([command for command in commands if command[0] == "run" and client in command]) == 8
    assert ["restart", container] in commands
    assert commands[-3:] == [["rm", "--force", "--volumes", container], ["volume", "rm", namespace + "-data"], ["network", "rm", network]]


@pytest.mark.parametrize("mutation", [
    lambda fixture: fixture.update(scope="release_qualification"),
    lambda fixture: fixture.update(complete_release_or_SDK_qualification_claimed=True),
    lambda fixture: fixture.update(repository="untrusted/repository"),
    lambda fixture: fixture.update(source_sha="unknown"),
    lambda fixture: fixture.update(source_ref="refs/heads/main"),
    lambda fixture: fixture.update(release_workflow_attempt=True),
    lambda fixture: fixture.update(source_lock_sha256="0" * 64),
    lambda fixture: fixture.update(image_sources_sha256="0" * 64),
    lambda fixture: fixture["images"].pop("minio_client"),
    lambda fixture: fixture["images"]["minio"].update(image="minio:latest"),
    lambda fixture: fixture["images"]["minio"]["children"].pop("arm64"),
    lambda fixture: fixture["images"]["minio"]["children"]["arm64"].update(size=True),
    lambda fixture: fixture["images"]["minio"].update(verified_statement_sha256=[]),
])
def test_historical_transport_fixture_cannot_replace_release_qualification(mutation) -> None:
    api = runpy.run_path(str(ROOT / "scripts/release/smoke-minio-source-images.py"))
    fixture = json.loads((ROOT / "tests/fixtures/minio_published_transport_v0_11_1.json").read_text())
    assert set(api["validate_transport_fixture"](fixture)) == {"minio", "minio_client"}
    mutation(fixture)
    with pytest.raises(ValueError):
        api["validate_transport_fixture"](fixture)


@pytest.mark.parametrize("failure", [None, "verification", "certificate", "statement", "attempt", "store"])
def test_single_store_regression_binds_verified_historical_inputs_and_both_architectures(monkeypatch, tmp_path: Path, failure: str | None) -> None:
    api = runpy.run_path(str(ROOT / "scripts/release/smoke-minio-source-images.py"))
    images, manifests, children = _runtime_registry()
    fixture = json.loads((ROOT / "tests/fixtures/minio_published_transport_v0_11_1.json").read_text())
    verifications = {}
    for role, parent in images.items():
        statement = {"subject": [{"digest": {"sha256": parent.rsplit("sha256:", 1)[1]}}],
                     "predicate": {"runDetails": {"metadata": {"invocationId":
                         "https://github.com/michaelwclark/genomes_agentic_os/actions/runs/38658509852/attempts/" + ("1" if failure == "attempt" else "2")}}}}
        fixture["images"][role] = {"image": parent, "children": children[role],
                                  "verified_statement_sha256": [sha256((json.dumps(statement, sort_keys=True, separators=(",", ":")) + "\n").encode()).hexdigest()]}
        verifications[role] = [{"verificationResult": {"statement": statement, "signature": {"certificate": {"unit": True}}}}]
    if failure == "certificate":
        verifications["minio"][0]["verificationResult"]["signature"].pop("certificate")
    if failure == "statement":
        fixture["images"]["minio"]["verified_statement_sha256"] = ["0" * 64]
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(fixture))
    infos, commands, cases = [], [], []

    def docker(arguments: list[str], **kwargs) -> bytes:
        if arguments[:4] == ["buildx", "imagetools", "inspect", "--raw"]:
            return manifests[arguments[-1]]
        assert arguments == ["info", "--format", "{{json .}}"]
        infos.append(arguments)
        return json.dumps({"ID": "different-store" if failure == "store" and len(infos) > 1 else "one-store",
                           "ServerVersion": "unit-only", "Driver": "overlay2", "OSType": "linux", "Architecture": "x86_64"}).encode()

    def verify(command: list[str], **kwargs) -> subprocess.CompletedProcess:
        commands.append(command)
        assert command[0:2] == ["gh", "attestation"]
        assert "--deny-self-hosted-runners" in command
        for flag, expected in [("--signer-digest", fixture["source_sha"]), ("--source-digest", fixture["source_sha"]),
                               ("--source-ref", fixture["source_ref"]), ("--repo", fixture["repository"]),
                               ("--signer-workflow", "github.com/michaelwclark/genomes_agentic_os/.github/workflows/release.yml")]:
            assert command[command.index(flag) + 1] == expected
        role = command[3].removesuffix("-index.json")
        return subprocess.CompletedProcess(command, 1 if failure == "verification" else 0, json.dumps(verifications[role]).encode(), b"")

    def exercise(server: str, client: str, arch: str, namespace: str, temporary: Path, mode: str, uid: int) -> dict:
        expected = [images[role].split("@")[0] + "@" + children[role][arch]["digest"] for role in ["minio", "minio_client"]]
        assert [server, client] == expected
        cases.append((arch, mode, uid))
        return {"credentials": mode, "effective_uid": uid}

    globals_ = api["run_transport_regression"].__globals__
    monkeypatch.setitem(globals_, "docker", docker)
    monkeypatch.setitem(globals_, "verify_identity", lambda *args: {"unit": True})
    monkeypatch.setitem(globals_, "exercise", exercise)
    monkeypatch.setattr(subprocess, "run", verify)
    output = tmp_path / "regression.json"
    if failure:
        with pytest.raises(ValueError):
            api["run_transport_regression"](fixture_path, "minio-source-unit", output)
        assert not output.exists()
        assert len(cases) == (3 if failure == "store" else 0)
    else:
        result = api["run_transport_regression"](fixture_path, "minio-source-unit", output)
        assert result["architecture_order"] == ["amd64", "arm64"]
        assert result["engine"]["ID"] == "one-store"
        assert len(infos) == 3
        assert len(commands) == 2
        assert cases == [(arch, mode, uid) for arch in ["amd64", "arm64"] for mode, uid in [("file", 0), ("env", 0), ("file", 1000)]]
        assert result["scope"] == "transport_regression_only"
        assert result["complete_release_or_SDK_qualification_claimed"] is False
        assert json.loads(output.read_text()) == result
