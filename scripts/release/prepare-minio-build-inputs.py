#!/usr/bin/env python3
"""Verify pinned official MinIO/MC payloads before producing a build context."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "deploy/execution-fabric/minio/upstream-lock.json"
IMAGE_SOURCES = ROOT / "deploy/execution-fabric/release-image-sources.json"
HEX = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
RELEASE = re.compile(r"RELEASE\.\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z")
PUBLIC_KEY = "RWTx5Zr1tiHQLwG9keckT0c45M3AGeHD6IvimQHpyRywVWGbP1aVSGav"
ROLES = {"minio": "minio", "mc": "minio_client"}


def digest(path: Path) -> str:
    """Hash bounded files without retaining binary payloads in memory."""
    result = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def fields(value: object, expected: set[str], name: str) -> dict:
    """Reject missing, extra and mistyped structured input at the boundary."""
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{name} must contain exactly {sorted(expected)}")
    return value


def hash_value(value: object, pattern: re.Pattern, name: str) -> None:
    """Require one complete lowercase immutable hash."""
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"{name} is not a valid immutable hash")


def validate_download(value: object, expected_url: str, name: str, *, asset: bool = False) -> dict:
    """Bind downloads to an exact official source address, hash and size."""
    expected = {"url", "sha256", "size"} | ({"asset_id"} if asset else set())
    result = fields(value, expected, name)
    if result["url"] != expected_url:
        raise ValueError(f"{name} is not the exact pinned official URL")
    hash_value(result["sha256"], HEX, name)
    if type(result["size"]) is not int or not 0 < result["size"] <= 200 * 1024 * 1024:
        raise ValueError(f"{name} has an invalid bounded size")
    if asset and (type(result["asset_id"]) is not int or result["asset_id"] <= 0):
        raise ValueError(f"{name} has an invalid official asset identifier")
    return result


def validate_lock(value: object, image_sources: dict) -> dict:
    """Validate the complete role/platform closure before any download/write."""
    sources = fields(image_sources, {"schema_version", "images"}, "image sources")
    if sources["schema_version"] != "execution-fabric-release-image-sources/v1":
        raise ValueError("unsupported image sources schema")
    fields(sources["images"], {"postgres", "valkey", "minio", "minio_client"}, "image roles")
    lock = fields(value, {"schema_version", "signature_public_key", "base", "verifier", "payloads", "sources"}, "lock")
    if lock["schema_version"] != "execution-fabric-minio-source-lock/v1" or lock["signature_public_key"] != PUBLIC_KEY:
        raise ValueError("unsupported source lock or untrusted signature key")
    base = fields(lock["base"], {"repository", "digest", "platforms"}, "base")
    if base["repository"] != "registry.access.redhat.com/ubi9/ubi-minimal":
        raise ValueError("base must use the reviewed official UBI repository")
    if not isinstance(base["digest"], str) or not base["digest"].startswith("sha256:"):
        raise ValueError("base requires an immutable index digest")
    hash_value(base["digest"][7:], HEX, "base index")
    for arch, item in fields(base["platforms"], {"amd64", "arm64"}, "base platforms").items():
        fields(item, {"manifest_digest", "curl_sha256"}, f"base {arch}")
        if not isinstance(item["manifest_digest"], str) or not item["manifest_digest"].startswith("sha256:"):
            raise ValueError("base child requires an immutable digest")
        hash_value(item["manifest_digest"][7:], HEX, "base child")
        hash_value(item["curl_sha256"], HEX, "base curl")
    verifier = fields(lock["verifier"], {"version", "linux", "darwin_executable_sha256"}, "verifier")
    if verifier["version"] != "0.12":
        raise ValueError("signature verifier version must remain pinned")
    linux = fields(verifier["linux"], {"url", "sha256", "size", "members"}, "Linux verifier")
    validate_download({key: linux[key] for key in ["url", "sha256", "size"]}, "https://github.com/jedisct1/minisign/releases/download/0.12/minisign-0.12-linux.tar.gz", "Linux verifier archive")
    for arch, item in fields(linux["members"], {"amd64", "arm64"}, "verifier platforms").items():
        fields(item, {"path", "sha256"}, "verifier member")
        expected_path = f'minisign-linux/{"x86_64" if arch == "amd64" else "aarch64"}/minisign'
        if item["path"] != expected_path:
            raise ValueError("unexpected verifier archive member")
        hash_value(item["sha256"], HEX, "verifier executable")
    hash_value(verifier["darwin_executable_sha256"], HEX, "local verifier executable")
    for role, payload in fields(lock["payloads"], set(ROLES), "payload roles").items():
        fields(payload, {"version", "repository", "source_commit", "annotated_tag", "release_id", "platforms"}, role)
        version = payload["version"]
        if not isinstance(version, str) or not RELEASE.fullmatch(version):
            raise ValueError("payload requires a reviewed exact release version")
        source = image_sources["images"][ROLES[role]]
        expected_repository = f'ghcr.io/michaelwclark/genomes-agentic-os-execution-fabric-{"minio" if role == "minio" else "minio-client"}'
        if source != {"repository": expected_repository, "tag": version}:
            raise ValueError("source lock and reviewed owned-image role disagree")
        if payload["repository"] != f"minio/{role}":
            raise ValueError("payload requires the official project repository")
        hash_value(payload["source_commit"], COMMIT, "upstream source commit")
        hash_value(payload["annotated_tag"], COMMIT, "upstream annotated tag")
        if type(payload["release_id"]) is not int or payload["release_id"] <= 0:
            raise ValueError("invalid upstream release identifier")
        for arch, downloads in fields(payload["platforms"], {"amd64", "arm64"}, f"{role} platforms").items():
            fields(downloads, {"binary", "sha256sum", "minisig"}, "payload closure")
            stem = f"{role}.linux-{arch}.{version}"
            for kind, suffix in [("binary", ""), ("sha256sum", ".sha256sum"), ("minisig", ".minisig")]:
                validate_download(downloads[kind], f"https://github.com/minio/{role}/releases/download/{version}/{stem}{suffix}", f"{role}/{arch}/{kind}", asset=True)
    sources = fields(lock["sources"], {"entrypoint", "minio_license", "minio_credits", "mc_license", "mc_credits"}, "source files")
    for name, source in sources.items():
        role = "minio" if name == "entrypoint" else name.split("_")[0]
        path = "dockerscripts/docker-entrypoint.sh" if name == "entrypoint" else name.split("_")[1].upper()
        commit = lock["payloads"][role]["source_commit"]
        validate_download(source, f"https://raw.githubusercontent.com/minio/{role}/{commit}/{path}", name)
    return lock


def checked(command: list[str], *, cwd: Path | None = None) -> bytes:
    """Make execution errors distinct from a successful verification signal."""
    result = subprocess.run(command, cwd=cwd, capture_output=True, timeout=300, check=False)
    if result.returncode:
        raise ValueError(f"{command[0]} failed ({result.returncode}): {result.stderr.decode(errors='replace')[-1600:]}")
    return result.stdout


def verify_file(path: Path, item: dict) -> None:
    """Verify full downloaded bytes before use or executable permission."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size != item["size"] or digest(path) != item["sha256"]:
        raise ValueError(f"downloaded bytes do not match the pin: {path.name}")


def download(item: dict, destination: Path, *, cache: Path | None = None) -> None:
    """Use exact hash-addressed cache bytes or a bounded official download."""
    cached = cache / item["sha256"] if cache is not None else None
    if cached is not None and (cached.exists() or cached.is_symlink()):
        verify_file(cached, item)
        shutil.copyfile(cached, destination)
    elif "asset_id" in item:
        repository = "/".join(item["url"].split("/")[3:5])
        command = ["gh", "api", "--method", "GET", f'repos/{repository}/releases/assets/{item["asset_id"]}', "-H", "Accept: application/octet-stream"]
        with destination.open("xb") as output, tempfile.TemporaryFile() as error:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=error)
            if process.stdout is None:
                raise ValueError("official asset reader has no output stream")
            count = 0
            try:
                with process.stdout:
                    while chunk := process.stdout.read(1024 * 1024):
                        count += len(chunk)
                        if count > item["size"]:
                            raise ValueError("official asset exceeds its bounded pinned size")
                        output.write(chunk)
                code = process.wait(timeout=30)
                if code:
                    error.seek(0)
                    raise ValueError(f"official asset read failed ({code}): {error.read(1600).decode(errors='replace')}")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=30)
    else:
        with urlopen(item["url"], timeout=60) as response, destination.open("xb") as output:
            count = 0
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > item["size"]:
                    raise ValueError("official download exceeds its pinned size")
                output.write(chunk)
    verify_file(destination, item)
    print(f'verified {destination.name}: {item["size"]} bytes / {item["sha256"]}', file=sys.stderr, flush=True)


def validate_release(payload: dict, release: dict) -> None:
    """Bind each pinned asset to the actual official release before retrieval."""
    if release.get("id") != payload["release_id"] or release.get("tag_name") != payload["version"] or release.get("draft") is not False or not release.get("published_at"):
        raise ValueError("official release and locked identity disagree")
    assets = release.get("assets")
    if not isinstance(assets, list) or any(not isinstance(asset, dict) for asset in assets):
        raise ValueError("official release has no asset inventory")
    for downloads in payload["platforms"].values():
        for item in downloads.values():
            matches = [asset for asset in assets if asset.get("id") == item["asset_id"]]
            if len(matches) != 1 or matches[0].get("name") != item["url"].rsplit("/", 1)[1] or matches[0].get("size") != item["size"] or matches[0].get("digest") != "sha256:" + item["sha256"]:
                raise ValueError("official asset inventory and locked bytes disagree")


def verifier_binary(lock: dict, directory: Path, supplied: Path | None, cache: Path | None) -> Path:
    """Verify a pinned local Mac tool or extract only the exact Linux member."""
    machine = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine())
    if supplied is not None:
        if platform.system() != "Darwin" or supplied.is_symlink() or not supplied.is_file() or digest(supplied) != lock["verifier"]["darwin_executable_sha256"]:
            raise ValueError("explicit local verifier is not the qualified Mac executable")
        return supplied
    if platform.system() != "Linux" or machine not in {"amd64", "arm64"}:
        raise ValueError("CI signature verification requires Linux amd64/arm64")
    item = lock["verifier"]["linux"]
    archive_path = directory / "verifier.tar.gz"
    download(item, archive_path, cache=cache)
    member = item["members"][machine]
    with tarfile.open(archive_path, "r:gz") as archive:
        info = archive.getmember(member["path"])
        if not info.isfile() or not 0 < info.size < 1024 * 1024:
            raise ValueError("signature verifier is not a bounded regular file")
        stream = archive.extractfile(info)
        if stream is None:
            raise ValueError("signature verifier member is absent")
        with stream:
            data = stream.read()
    if sha256(data).hexdigest() != member["sha256"]:
        raise ValueError("signature verifier executable hash differs")
    executable = directory / "minisign"
    executable.write_bytes(data)
    executable.chmod(0o700)
    return executable


def verify_binary(path: Path, arch: str, checksum: Path, expected_hash: str) -> None:
    """Reject wrong bytes, checksum records and CPU architecture before build."""
    tokens = checksum.read_text().split()
    if len(tokens) != 2 or tokens[0] != expected_hash or digest(path) != expected_hash:
        raise ValueError("official checksum record and binary disagree")
    with path.open("rb") as stream:
        header = stream.read(20)
    if header[:6] != b"\x7fELF\x02\x01" or int.from_bytes(header[18:20], "little") != {"amd64": 62, "arm64": 183}[arch]:
        raise ValueError("official binary does not match the target architecture")


def prepare(lock_path: Path, output: Path, cache: Path | None = None, supplied_verifier: Path | None = None) -> dict:
    """Emit one verified context; any unknown/failed input refuses image builds."""
    lock = validate_lock(json.loads(lock_path.read_text()), json.loads(IMAGE_SOURCES.read_text()))
    if output.exists():
        raise ValueError("build context already exists; preserve it and select a fresh path")
    output.parent.mkdir(parents=True, exist_ok=True)
    source_sha = checked(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    source_tree = checked(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT).decode().strip()
    checked(["git", "diff", "--quiet"], cwd=ROOT)
    checked(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
    with tempfile.TemporaryDirectory(prefix="minio-inputs-", dir=output.parent) as temporary:
        staged = Path(temporary)
        verifier = verifier_binary(lock, staged, supplied_verifier, cache)
        if checked([str(verifier), "-v"]).decode().strip() != "minisign 0.12":
            raise ValueError("signature verifier version differs from the pin")
        files = {}
        for role, payload in lock["payloads"].items():
            release = json.loads(checked(["gh", "api", "--method", "GET", f'repos/{payload["repository"]}/releases/{payload["release_id"]}']))
            validate_release(payload, release)
            tag = json.loads(checked(["gh", "api", "--method", "GET", f'repos/{payload["repository"]}/git/tags/{payload["annotated_tag"]}']))
            if tag.get("tag") != payload["version"] or tag.get("object") != {"sha": payload["source_commit"], "type": "commit", "url": f'https://api.github.com/repos/{payload["repository"]}/git/commits/{payload["source_commit"]}'} or tag.get("verification", {}).get("verified") is not True:
                raise ValueError("official signed tag and pinned release source disagree")
            for arch, items in payload["platforms"].items():
                directory = staged / "bin" / arch
                directory.mkdir(parents=True, exist_ok=True)
                for kind, item in items.items():
                    name = role + ({"binary": "", "sha256sum": ".sha256sum", "minisig": ".minisig"}[kind])
                    download(item, directory / name, cache=cache)
                    files[f"bin/{arch}/{name}"] = digest(directory / name)
                binary = directory / role
                verify_binary(binary, arch, directory / (role + ".sha256sum"), items["binary"]["sha256"])
                checked([str(verifier), "-Vqm", str(binary), "-x", str(directory / (role + ".minisig")), "-P", PUBLIC_KEY])
                binary.chmod(0o555)
        contracts = staged / "contracts"
        contracts.mkdir()
        for name, item in lock["sources"].items():
            download(item, contracts / name, cache=cache)
            files["contracts/" + name] = digest(contracts / name)
        shutil.copyfile(ROOT / "deploy/execution-fabric/minio/Dockerfile", staged / "Dockerfile")
        shutil.copyfile(lock_path, staged / "upstream-lock.json")
        for name in ["Dockerfile", "upstream-lock.json"]:
            files[name] = digest(staged / name)
        receipt = {"schema_version": "execution-fabric-minio-build-inputs/v1", "status": "verified", "source_sha": source_sha, "source_tree": source_tree, "lock_sha256": digest(lock_path), "image_sources_sha256": digest(IMAGE_SOURCES), "base_image": lock["base"]["repository"] + "@" + lock["base"]["digest"], "signature_verifier_sha256": digest(verifier), "signature_verifications": 4, "files": files}
        (staged / "build-inputs.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
        staged.rename(output)
    return receipt


def main() -> int:
    """Return zero only for a complete verified build context."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=LOCK)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--local-mac-verifier", type=Path)
    args = parser.parse_args()
    try:
        receipt = prepare(args.lock, args.output_dir, args.cache_dir, args.local_mac_verifier)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        parser.error(str(error))
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
