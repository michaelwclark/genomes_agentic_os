#!/usr/bin/env python3
"""Read back exact owned OCI indexes, children, source and signed provenance."""
from __future__ import annotations

import argparse
from collections.abc import Callable
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "deploy/execution-fabric/minio/upstream-lock.json"
SOURCES = ROOT / "deploy/execution-fabric/release-image-sources.json"


def execute(command: list[str], path: Path) -> bytes:
    """Preserve raw verification output and fail on actual command failure."""
    result = subprocess.run(command, capture_output=True, timeout=180, check=False)
    path.write_bytes(result.stdout)
    path.with_name(path.name + ".stderr").write_bytes(result.stderr)
    if result.returncode:
        raise ValueError(f"{command[0]} verification failed ({result.returncode}): {result.stderr.decode(errors='replace')[-1600:]}")
    return result.stdout


def canonical_bytes(value: bytes, digest: str, size: int | None = None) -> bytes:
    """Permit only Docker's presentation newline beyond exact registry bytes."""
    data = value if sha256(value).hexdigest() == digest else value.removesuffix(b"\n")
    if sha256(data).hexdigest() != digest or size is not None and len(data) != size:
        raise ValueError("registry manifest bytes differ from the asserted digest/size")
    return data


def index_children(value: object) -> dict[str, dict]:
    """Require exactly one real Linux child for each shipped architecture."""
    if not isinstance(value, dict) or value.get("mediaType") not in {"application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json"}:
        raise ValueError("published object is not a multiarch index")
    children = {}
    manifests = value.get("manifests")
    if not isinstance(manifests, list):
        raise ValueError("published index has no structured manifest inventory")
    for item in manifests:
        if not isinstance(item, dict) or not isinstance(item.get("platform"), dict):
            raise ValueError("published child has no structured platform")
        platform = item.get("platform", {})
        if platform.get("os") != "linux":
            continue  # BuildKit's attestation manifests are not runtime platforms.
        architecture = platform.get("architecture")
        if architecture not in {"amd64", "arm64"} or architecture in children:
            raise ValueError("unexpected or duplicate runtime platform")
        if item.get("mediaType") not in {"application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json"}:
            raise ValueError("runtime child is not an image manifest")
        if not isinstance(item.get("digest"), str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", item["digest"]) or type(item.get("size")) is not int or item["size"] <= 0:
            raise ValueError("runtime child has no exact digest/size")
        children[architecture] = item
    if set(children) != {"amd64", "arm64"}:
        raise ValueError("published index lacks a required architecture")
    return children


def resolve_runtime_child(image: str, arch: str, read_manifest: Callable[[str], bytes]) -> str:
    """Bind a runtime leaf to exact parent and child registry bytes."""
    if arch not in {"amd64", "arm64"} or not re.fullmatch(r"[^@\s]+@sha256:[0-9a-f]{64}", image):
        raise ValueError("runtime resolution requires an immutable index and architecture")
    index = canonical_bytes(read_manifest(image), image.rsplit("sha256:", 1)[1])
    child = index_children(json.loads(index))[arch]
    reference = image.split("@")[0] + "@" + child["digest"]
    raw = canonical_bytes(read_manifest(reference), child["digest"][7:], child["size"])
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 2 or manifest.get("mediaType") != child["mediaType"]:
        raise ValueError("runtime child manifest media type or schema differs")
    return reference


def verify_runtime_binding(smoke: dict, images: dict, children: dict, arch: str) -> None:
    """Require executed runtime leaves to belong to the signed parent indexes."""
    expected = {role: image.split("@")[0] + "@" + children[role][arch]["digest"] for role, image in images.items()}
    if smoke.get("images") != images or smoke.get("platform") != "linux/" + arch or smoke.get("runtime_images") != expected:
        raise ValueError("published runtime children differ from the verified parent/platform")


def has_verified_subject(value: object, digest: str) -> bool:
    """Consume the actual gh verification envelope, never an output keyword."""
    if not isinstance(value, list) or not value:
        return False
    for result in value:
        if not isinstance(result, dict):
            return False
        verification = result.get("verificationResult", {})
        if not isinstance(verification, dict):
            return False
        statement = verification.get("statement", {})
        signature = verification.get("signature", {})
        if not isinstance(statement, dict) or not isinstance(signature, dict):
            return False
        certificate = signature.get("certificate")
        subjects = statement.get("subject")
        if not isinstance(certificate, dict) or not certificate or not isinstance(subjects, list):
            return False
        if any(isinstance(subject, dict) and isinstance(subject.get("digest"), dict) and subject["digest"].get("sha256") == digest for subject in subjects):
            return True
    return False


def main() -> int:
    """Emit custody only after both indexes and actual current proofs succeed."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minio-image", required=True)
    parser.add_argument("--client-image", required=True)
    parser.add_argument("--input-receipt", type=Path, required=True)
    parser.add_argument("--smoke-dir", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.repository != "michaelwclark/genomes_agentic_os" or not re.fullmatch(r"[0-9a-f]{40}", args.source_sha) or not re.fullmatch(r"refs/tags/v\d+\.\d+\.\d+", args.source_ref):
        parser.error("publication custody requires the canonical repository/tag/source")
    current = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    current_tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip()
    inputs = json.loads(args.input_receipt.read_text())
    lock_hash = sha256(LOCK.read_bytes()).hexdigest()
    if current != args.source_sha or inputs.get("source_sha") != current or inputs.get("source_tree") != current_tree or inputs.get("status") != "verified" or inputs.get("signature_verifications") != 4 or inputs.get("lock_sha256") != lock_hash or inputs.get("image_sources_sha256") != sha256(SOURCES.read_bytes()).hexdigest():
        parser.error("current source and verified upstream input receipt disagree")
    if args.output_dir.exists():
        parser.error("preserve existing publication custody and select a fresh path")
    sources = json.loads(SOURCES.read_text())["images"]
    images = {"minio": args.minio_image, "minio_client": args.client_image}
    for role, image in images.items():
        if not re.fullmatch(re.escape(sources[role]["repository"]) + r"@sha256:[0-9a-f]{64}", image):
            parser.error("owned published image repository or immutable digest differs")
    smokes = {}
    for arch in ["amd64", "arm64"]:
        path = args.smoke_dir / (arch + ".json")
        smoke = json.loads(path.read_text())
        if smoke.get("schema_version") != "execution-fabric-minio-runtime-smoke/v1" or smoke.get("status") != "passed" or smoke.get("platform") != "linux/" + arch or smoke.get("images") != images or smoke.get("source_lock_sha256") != lock_hash or smoke.get("fixture_resources_removed") is not True or len(smoke.get("cases", [])) != 3:
            parser.error("actual current published-image smoke closure is missing")
        smokes[arch] = {"sha256": sha256(path.read_bytes()).hexdigest(), "receipt": smoke}
    args.output_dir.mkdir(parents=True)
    custody = {}
    for role, image in images.items():
        digest = image.rsplit("sha256:", 1)[1]
        raw_path = args.output_dir / (role + "-index.json")
        raw = execute(["docker", "buildx", "imagetools", "inspect", "--raw", image], raw_path)
        data = canonical_bytes(raw, digest)
        raw_path.write_bytes(data)
        children = index_children(json.loads(data))
        observed = {}
        repository = image.split("@")[0]
        for arch, item in children.items():
            child_path = args.output_dir / (role + "-" + arch + ".json")
            raw = execute(["docker", "buildx", "imagetools", "inspect", "--raw", repository + "@" + item["digest"]], child_path)
            child = canonical_bytes(raw, item["digest"][7:], item["size"])
            child_path.write_bytes(child)
            json.loads(child)
            observed[arch] = {"digest": item["digest"], "size": len(child)}
        provenance_path = args.output_dir / (role + "-verified-provenance.json")
        provenance = execute(["gh", "attestation", "verify", str(raw_path), "--repo", args.repository, "--signer-workflow", "github.com/" + args.repository + "/.github/workflows/release.yml", "--signer-digest", args.source_sha, "--source-digest", args.source_sha, "--source-ref", args.source_ref, "--deny-self-hosted-runners", "--format", "json"], provenance_path)
        if not has_verified_subject(json.loads(provenance), digest):
            raise ValueError("verified provenance does not contain the current OCI index")
        custody[role] = {"image": image, "children": observed, "verified_provenance_sha256": sha256(provenance).hexdigest()}
    for arch, smoke in smokes.items():
        verify_runtime_binding(smoke["receipt"], images, {role: value["children"] for role, value in custody.items()}, arch)
    receipt = {"schema_version": "execution-fabric-minio-publication/v1", "status": "verified", "repository": args.repository, "source_sha": args.source_sha, "source_ref": args.source_ref, "source_lock_sha256": lock_hash, "inputs": inputs, "images": custody, "runtime_smokes": smokes}
    (args.output_dir / "publication-custody.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"status": "verified", "receipt": str(args.output_dir / "publication-custody.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
