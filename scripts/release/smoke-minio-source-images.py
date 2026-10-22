#!/usr/bin/env python3
"""Exercise actual rebuilt MinIO/MC binaries, credentials and persistence."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import runpy
import subprocess
import tempfile
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "deploy/execution-fabric/minio/upstream-lock.json"


def docker(arguments: list[str], *, required: bool = True) -> bytes:
    """Keep bounded actual Docker outcomes separate from semantic assertions."""
    result = subprocess.run(["docker", *arguments], capture_output=True, timeout=180, check=False)
    if required and result.returncode:
        raise ValueError(f"Docker {arguments[0]} failed ({result.returncode}): {result.stderr.decode(errors='replace')[-1200:]}")
    return result.stdout if result.returncode == 0 else b""


def identifier(value: bytes) -> str:
    """Accept only the immutable identity of a just-created fixture resource."""
    token = value.decode().strip()
    if not re.fullmatch(r"[0-9a-f]{64}", token):
        raise ValueError("Docker did not return a fixture resource identity")
    return token


def wait_ready(container: str) -> None:
    """Require the compose-owned curl readiness check within a bounded window."""
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        result = subprocess.run(["docker", "exec", container, "curl", "-fsS", "http://127.0.0.1:9000/minio/health/ready"], capture_output=True, timeout=10, check=False)
        if result.returncode == 0:
            return
        time.sleep(1)
    raise ValueError("MinIO did not pass its actual compose readiness check")


def verify_identity(image: str, role: str, arch: str, lock: dict, temporary: Path) -> dict:
    """Check actual image payload/version/source/base bytes before service use."""
    container = identifier(docker(["create", "--platform", "linux/" + arch, image]))
    try:
        path = temporary / role
        docker(["cp", container + ":/usr/bin/" + role, str(path)])
        actual_hash = sha256(path.read_bytes()).hexdigest()
        payload = lock["payloads"][role]
        if actual_hash != payload["platforms"][arch]["binary"]["sha256"]:
            raise ValueError("built image binary differs from the signed official payload")
        version = docker(["run", "--rm", "--platform", "linux/" + arch, "--entrypoint", "/usr/bin/" + role, image, "--version"]).decode()
        if payload["version"] not in version or payload["source_commit"] not in version:
            raise ValueError("built image release/source version differs")
        curl_path = temporary / (role + "-curl")
        docker(["cp", container + ":/usr/bin/curl", str(curl_path)])
        if sha256(curl_path.read_bytes()).hexdigest() != lock["base"]["platforms"][arch]["curl_sha256"]:
            raise ValueError("built image curl differs from the immutable base")
        image_id = json.loads(docker(["inspect", "--format", "{{json .Image}}", container]))
        return {"binary_sha256": actual_hash, "release": payload["version"], "source_commit": payload["source_commit"], "curl_sha256": lock["base"]["platforms"][arch]["curl_sha256"], "image_id": image_id}
    finally:
        docker(["rm", "--force", "--volumes", container])


def exercise(minio_image: str, client_image: str, arch: str, namespace: str, temporary: Path, credential_mode: str, uid: int) -> dict:
    """Test isolated fixture credentials, current initializer and restart data."""
    volume = namespace + "-data"
    if docker(["network", "inspect", namespace], required=False) or docker(["volume", "inspect", volume], required=False):
        raise ValueError("fixture name already exists; never reuse or remove it")
    network_id = identifier(docker(["network", "create", namespace]))
    created_volume = None
    container = None
    try:
        created_volume = docker(["volume", "create", volume]).decode().strip()
        if created_volume != volume:
            raise ValueError("Docker volume identity differs from this fixture")
        # Only the just-created test volume is writable; no host runtime is used.
        docker(["run", "--rm", "--platform", "linux/" + arch, "--mount", f"type=volume,src={volume},dst=/data", "--entrypoint", "/bin/sh", minio_image, "-c", "chmod 0777 /data"])
        arguments = ["run", "--detach", "--platform", "linux/" + arch, "--name", namespace + "-server", "--network", namespace, "--network-alias", "minio", "--security-opt", "no-new-privileges:true", "--mount", f"type=volume,src={volume},dst=/data"]
        user, password = "source-smoke-user", "source-smoke-password-2026"
        if credential_mode == "file":
            secrets = temporary / namespace
            secrets.mkdir()
            secrets.chmod(0o755)
            for name, value in [("user", user), ("password", password)]:
                path = secrets / name
                path.write_text(value)
                path.chmod(0o444)
                arguments += ["--mount", f"type=bind,src={path},dst=/run/secrets/{name},readonly", "--env", f"MINIO_ROOT_{'USER' if name == 'user' else 'PASSWORD'}_FILE=/run/secrets/{name}"]
        else:
            arguments += ["--env", "MINIO_ROOT_USER=" + user, "--env", "MINIO_ROOT_PASSWORD=" + password, "--env", "MINIO_ROOT_USER_FILE=", "--env", "MINIO_ROOT_PASSWORD_FILE="]
        if uid:
            arguments += ["--env", "MINIO_USERNAME=minio", "--env", "MINIO_GROUPNAME=minio", "--env", f"MINIO_UID={uid}", "--env", f"MINIO_GID={uid}"]
        arguments += [minio_image, "server", "/data", "--console-address", ":9001"]
        container = identifier(docker(arguments))
        wait_ready(container)
        # The unchanged upstream entrypoint may retain its shell as PID 1 when
        # it uses chroot. Observe the actual server process rather than the shell.
        process_status = docker(["exec", container, "/bin/sh", "-c", 'for path in /proc/[0-9]*/comm; do if [ "$(cat "$path" 2>/dev/null)" = minio ]; then cat "${path%/comm}/status"; fi; done']).decode()
        matches = re.findall(r"^Uid:\s+(\d+)\s+(\d+)", process_status, re.MULTILINE)
        if len(matches) != 1 or int(matches[0][1]) != uid:
            raise ValueError("entrypoint user-switch contract did not hold")

        def mc(command: list[str]) -> bytes:
            return docker(["run", "--rm", "--platform", "linux/" + arch, "--network", namespace, "--env", f"MC_HOST_fixture=http://{user}:{password}@minio:9000", client_image, *command])

        bucket = "fixture/source-image-contract"
        mc(["mb", bucket])
        mc(["anonymous", "set", "private", bucket])
        mc(["version", "enable", bucket])
        fixture = temporary / (namespace + "-object")
        expected = ("same-release-persistence-" + arch).encode()
        fixture.write_bytes(expected)
        docker(["run", "--rm", "--platform", "linux/" + arch, "--network", namespace, "--env", f"MC_HOST_fixture=http://{user}:{password}@minio:9000", "--mount", f"type=bind,src={fixture},dst=/fixture-object,readonly", client_image, "cp", "/fixture-object", bucket + "/object"])
        if mc(["cat", bucket + "/object"]) != expected:
            raise ValueError("actual object read does not match written fixture bytes")
        docker(["restart", container])
        wait_ready(container)
        if mc(["cat", bucket + "/object"]) != expected:
            raise ValueError("object bytes did not persist across actual restart")
        mc(["rm", "--versions", "--force", bucket + "/object"])
        if mc(["ls", bucket]).strip():
            raise ValueError("deleted object remains visible")
        return {"credentials": credential_mode, "effective_uid": uid, "ready": True, "bucket_privacy_and_versioning": True, "object_sha256": sha256(expected).hexdigest(), "object_write_read_restart_read_delete": True}
    finally:
        failures = []
        if container is not None:
            try:
                docker(["rm", "--force", "--volumes", container])
            except (OSError, ValueError, subprocess.TimeoutExpired) as error:
                failures.append(str(error))
        cleanup = [["network", "rm", network_id]]
        if created_volume == volume:
            cleanup.insert(0, ["volume", "rm", volume])
        for command in cleanup:
            try:
                docker(command)
            except (OSError, ValueError, subprocess.TimeoutExpired) as error:
                failures.append(str(error))
        if failures:
            raise ValueError("owned fixture cleanup failed: " + "; ".join(failures))


def validate_published_images(images: dict) -> None:
    """Keep role-specific immutable parents as the public custody identities."""
    repositories = {"minio": "minio", "minio_client": "minio-client"}
    if set(images) != set(repositories) or any(not isinstance(images[role], str) or not re.fullmatch(r"ghcr\.io/michaelwclark/genomes-agentic-os-execution-fabric-" + suffix + r"@sha256:[0-9a-f]{64}", images[role]) for role, suffix in repositories.items()):
        raise ValueError("published smoke requires exact owned immutable image references")


def publication_contract() -> dict:
    """Reuse the release verifier's canonical registry parsing without effects."""
    return runpy.run_path(str(ROOT / "scripts/release/verify-minio-image-publication.py"))


def run_smoke(images: dict, platform: str, namespace: str, output: Path, *, published: bool, expected_children: dict | None = None) -> dict:
    """Execute every container with the resolved leaf while retaining its parent."""
    if output.exists():
        raise ValueError("preserve the existing smoke receipt and use a fresh output")
    arch = platform.split("/")[1]
    runtime_images = images
    if published:
        validate_published_images(images)
        contract = publication_contract()
        runtime_images = {role: contract["resolve_runtime_child"](image, arch, lambda reference: docker(["buildx", "imagetools", "inspect", "--raw", reference])) for role, image in images.items()}
        if expected_children is not None:
            contract["verify_runtime_binding"]({"platform": platform, "images": images, "runtime_images": runtime_images}, images, expected_children, arch)
    lock = json.loads(LOCK.read_text())
    fixture_namespace = namespace + "-" + uuid4().hex
    with tempfile.TemporaryDirectory(prefix="minio-source-smoke-") as directory:
        temporary = Path(directory)
        identities = {role: verify_identity(image, role, arch, lock, temporary) for role, image in [("minio", runtime_images["minio"]), ("mc", runtime_images["minio_client"])]}
        cases = []
        for mode, uid in [("file", 0), ("env", 0), ("file", 1000)]:
            cases.append(exercise(runtime_images["minio"], runtime_images["minio_client"], arch, fixture_namespace + f"-{mode}-{uid}", temporary, mode, uid))
            print(f"verified actual {platform} credentials={mode} uid={uid} persistence", flush=True)
    receipt = {"schema_version": "execution-fabric-minio-runtime-smoke/v1", "status": "passed", "platform": platform, "images": images, "runtime_images": runtime_images, "identities": identities, "cases": cases, "fixture_resources_removed": True, "source_lock_sha256": sha256(LOCK.read_bytes()).hexdigest()}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"status": "passed", "platform": platform, "receipt": str(output)}))
    return receipt


def validate_transport_fixture(fixture: dict) -> dict:
    """Admit only reviewed immutable historical inputs for a transport regression."""
    if not isinstance(fixture, dict) or fixture.get("schema_version") != "execution-fabric-minio-published-transport-fixture/v1" or fixture.get("scope") != "transport_regression_only" or fixture.get("complete_release_or_SDK_qualification_claimed") is not False:
        raise ValueError("published transport fixture must not claim release or SDK qualification")
    if fixture.get("repository") != "michaelwclark/genomes_agentic_os" or any(not re.fullmatch(r"[0-9a-f]{40}", str(fixture.get(name, ""))) for name in ["source_sha", "source_tree", "tag_object_sha"]) or not re.fullmatch(r"refs/tags/v\d+\.\d+\.\d+", str(fixture.get("source_ref", ""))):
        raise ValueError("published fixture source/tag identity differs")
    if any(type(fixture.get(name)) is not int or fixture[name] <= 0 for name in ["release_workflow_run_id", "release_workflow_attempt"]):
        raise ValueError("published fixture requires its actual run and attempt")
    if fixture.get("source_lock_sha256") != sha256(LOCK.read_bytes()).hexdigest() or fixture.get("image_sources_sha256") != sha256((ROOT / "deploy/execution-fabric/release-image-sources.json").read_bytes()).hexdigest():
        raise ValueError("historical fixture differs from current signed input locks")
    records = fixture.get("images")
    if not isinstance(records, dict) or set(records) != {"minio", "minio_client"} or any(not isinstance(value, dict) for value in records.values()):
        raise ValueError("published fixture image role closure differs")
    images = {role: value.get("image") for role, value in records.items()}
    validate_published_images(images)
    for value in records.values():
        children = value.get("children")
        hashes = value.get("verified_statement_sha256")
        if not isinstance(children, dict) or set(children) != {"amd64", "arm64"} or any(not isinstance(child, dict) or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(child.get("digest", ""))) or type(child.get("size")) is not int or child["size"] <= 0 for child in children.values()) or not isinstance(hashes, list) or not hashes or any(not isinstance(h, str) or not re.fullmatch(r"[0-9a-f]{64}", h) for h in hashes):
            raise ValueError("published fixture child/provenance pins are incomplete")
    return images


def run_transport_regression(fixture_path: Path, namespace: str, output: Path) -> dict:
    """Exercise amd64 then arm64 on one real daemon using historical published images."""
    fixture = json.loads(fixture_path.read_text())
    images = validate_transport_fixture(fixture)
    proof_dir = output.with_name(output.stem + "-proof")
    if output.exists() or proof_dir.exists():
        raise ValueError("preserve existing published transport evidence")
    proof_dir.mkdir(parents=True)
    contract = publication_contract()
    expected_children = {role: value["children"] for role, value in fixture["images"].items()}
    invocation = f'https://github.com/{fixture["repository"]}/actions/runs/{fixture["release_workflow_run_id"]}/attempts/{fixture["release_workflow_attempt"]}'
    for role, image in images.items():
        raw = contract["canonical_bytes"](docker(["buildx", "imagetools", "inspect", "--raw", image]), image.rsplit("sha256:", 1)[1])
        children = contract["index_children"](json.loads(raw))
        if {arch: {"digest": value["digest"], "size": value["size"]} for arch, value in children.items()} != expected_children[role]:
            raise ValueError("published fixture children differ from actual registry bytes")
        index_path = proof_dir / (role + "-index.json")
        index_path.write_bytes(raw)
        command = ["gh", "attestation", "verify", index_path.name, "--repo", fixture["repository"], "--signer-workflow", "github.com/" + fixture["repository"] + "/.github/workflows/release.yml", "--signer-digest", fixture["source_sha"], "--source-digest", fixture["source_sha"], "--source-ref", fixture["source_ref"], "--deny-self-hosted-runners", "--format", "json"]
        result = subprocess.run(command, cwd=proof_dir, capture_output=True, timeout=180, check=False)
        (proof_dir / (role + "-verified-provenance.json")).write_bytes(result.stdout)
        (proof_dir / (role + "-verification.stderr")).write_bytes(result.stderr)
        (proof_dir / (role + "-verification-command.json")).write_text(json.dumps({"argv": command, "exit_code": result.returncode}, sort_keys=True, indent=2) + "\n")
        if result.returncode:
            raise ValueError("actual historical published provenance verification failed")
        verified = json.loads(result.stdout)
        if not contract["has_verified_subject"](verified, image.rsplit("sha256:", 1)[1]):
            raise ValueError("historical published provenance lacks its actual index")
        statements = [value["verificationResult"]["statement"] for value in verified]
        if not any(sha256((json.dumps(statement, sort_keys=True, separators=(",", ":")) + "\n").encode()).hexdigest() in fixture["images"][role]["verified_statement_sha256"] and statement.get("predicate", {}).get("runDetails", {}).get("metadata", {}).get("invocationId") == invocation for statement in statements):
            raise ValueError("historical signed statement/run/attempt differs from the fixture")
    engine = json.loads(docker(["info", "--format", "{{json .}}"]))
    receipts = {}
    for arch in ["amd64", "arm64"]:
        receipts[arch] = run_smoke(images, "linux/" + arch, namespace + "-" + arch, proof_dir / (arch + ".json"), published=True, expected_children=expected_children)
        if json.loads(docker(["info", "--format", "{{json .}}"])).get("ID") != engine.get("ID") or not engine.get("ID"):
            raise ValueError("published architecture regression changed Docker stores")
    receipt = {"schema_version": "execution-fabric-minio-published-transport-regression/v1", "status": "passed", "scope": "transport_regression_only", "fixture_sha256": sha256(fixture_path.read_bytes()).hexdigest(), "historical_source_sha": fixture["source_sha"], "helper_sha256": sha256(Path(__file__).read_bytes()).hexdigest(), "engine": {key: engine.get(key) for key in ["ID", "ServerVersion", "Driver", "OSType", "Architecture", "OperatingSystem"]}, "architecture_order": list(receipts), "runtime_smokes": receipts, "complete_release_or_SDK_qualification_claimed": False}
    output.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    return receipt


def main() -> int:
    """Emit a passed receipt only after every real image/fixture check closes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=["linux/amd64", "linux/arm64"])
    parser.add_argument("--minio-image")
    parser.add_argument("--client-image")
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--published", action="store_true")
    parser.add_argument("--published-fixture", type=Path, help="Run a transport-only amd64 then arm64 regression on one Docker store.")
    args = parser.parse_args()
    if not re.fullmatch(r"minio-source-[a-z0-9-]{1,70}", args.namespace):
        parser.error("fixture namespace must use the minio-source- owned prefix")
    if args.output.exists():
        parser.error("preserve the existing smoke receipt and use a fresh output")
    if args.published_fixture:
        if args.platform or args.minio_image or args.client_image or args.published:
            parser.error("published fixture supplies its own immutable images and both architectures")
        run_transport_regression(args.published_fixture, args.namespace, args.output)
    else:
        if not args.platform or not args.minio_image or not args.client_image:
            parser.error("--platform, --minio-image and --client-image are required")
        images = {"minio": args.minio_image, "minio_client": args.client_image}
        if args.published:
            try:
                validate_published_images(images)
            except ValueError as error:
                parser.error(str(error))
        run_smoke(images, args.platform, args.namespace, args.output, published=args.published)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
