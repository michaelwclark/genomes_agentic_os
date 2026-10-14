#!/usr/bin/env python3
"""Exercise actual rebuilt MinIO/MC binaries, credentials and persistence."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
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


def main() -> int:
    """Emit a passed receipt only after every real image/fixture check closes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=["linux/amd64", "linux/arm64"], required=True)
    parser.add_argument("--minio-image", required=True)
    parser.add_argument("--client-image", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--published", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"minio-source-[a-z0-9-]{1,70}", args.namespace):
        parser.error("fixture namespace must use the minio-source- owned prefix")
    published_roles = {"minio": args.minio_image, "minio-client": args.client_image}
    if args.published and any(not re.fullmatch(r"ghcr\.io/michaelwclark/genomes-agentic-os-execution-fabric-" + role + r"@sha256:[0-9a-f]{64}", image) for role, image in published_roles.items()):
        parser.error("published smoke requires exact owned immutable image references")
    if args.output.exists():
        parser.error("preserve the existing smoke receipt and use a fresh output")
    lock = json.loads(LOCK.read_text())
    arch = args.platform.split("/")[1]
    fixture_namespace = args.namespace + "-" + uuid4().hex
    with tempfile.TemporaryDirectory(prefix="minio-source-smoke-") as directory:
        temporary = Path(directory)
        identities = {role: verify_identity(image, role, arch, lock, temporary) for role, image in [("minio", args.minio_image), ("mc", args.client_image)]}
        cases = []
        for mode, uid in [("file", 0), ("env", 0), ("file", 1000)]:
            cases.append(exercise(args.minio_image, args.client_image, arch, fixture_namespace + f"-{mode}-{uid}", temporary, mode, uid))
            print(f"verified actual {args.platform} credentials={mode} uid={uid} persistence", flush=True)
    receipt = {"schema_version": "execution-fabric-minio-runtime-smoke/v1", "status": "passed", "platform": args.platform, "images": {"minio": args.minio_image, "minio_client": args.client_image}, "identities": identities, "cases": cases, "fixture_resources_removed": True, "source_lock_sha256": sha256(LOCK.read_bytes()).hexdigest()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"status": "passed", "platform": args.platform, "receipt": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
