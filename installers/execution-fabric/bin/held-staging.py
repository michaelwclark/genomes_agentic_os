#!/usr/bin/env python3
"""Verify a pinned held bundle and stage its six inert payloads only.

Authorization belongs to the calling governed workflow. A parent receipt pin
records that workflow's existing evidence; it is not a new approval system.
Rollback is read-only verification: this tool never deletes staged data.
"""
from __future__ import annotations

import argparse
import datetime
import gzip
import hashlib
import io
import json
import os
from pathlib import PurePosixPath
import stat
import sys
import tarfile
from typing import Any
import zlib

PAYLOAD_NAMES = frozenset((
    "HOLD.json", "SHA256SUMS", "execution-fabric-config-schema.tar.gz",
    "execution-fabric-emergency-bundle.tar.gz", "execution-fabric-image-lock.json",
    "execution-fabric-release-manifest.json",
))
BUNDLE_NAMES = frozenset(("held-stage-plan.json", "held_staging.py")) | frozenset(
    "payload/" + name for name in PAYLOAD_NAMES)
EFFECT_NAMES = frozenset((
    "systemd_units", "systemd_reload", "current_pointer", "runtime_config",
    "credential_files", "docker_install", "docker_daemon", "container_pull",
    "service_start", "api_listener", "worker_dispatch", "queues", "schedules",
    "healer", "failback", "fallback_latch", "state_initialization",
))
HOLD_GATES = ("activation_admitted", "worker_admission", "scheduler_admission",
              "healer_admission", "queue_admission", "automatic_failback",
              "credential_provisioning", "canonical_config_mutation",
              "state_initialization", "api_listener")
RECEIPT_NAME = "STAGING-RECEIPT.json"
# Hard custody limits apply before decompression and archive interpretation.
MAX_BUNDLE_BYTES = 8 * 1024 * 1024
MAX_EXPANDED_BYTES = 2 * 1024 * 1024
MAX_RECEIPT_BYTES = 256 * 1024

class StageError(ValueError):
    """A closed candidate, custody or preservation boundary failed."""

def digest(data: bytes | bytearray) -> str:
    """Return a complete SHA-256 without exposing input bytes."""
    return hashlib.sha256(data).hexdigest()

def sha_valid(value: object) -> bool:
    """Require an explicit lowercase SHA-256 identity."""
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))

def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject ambiguous JSON objects."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise StageError("duplicate_json_key")
        result[key] = value
    return result

def parse_json(data: bytes) -> dict[str, Any]:
    """Parse one bounded object with duplicate-key rejection."""
    try:
        value = json.loads(data, object_pairs_hook=unique_keys)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise StageError("invalid_json") from exc
    if not isinstance(value, dict):
        raise StageError("json_object_required")
    return value

def path_parts(path: str) -> list[str]:
    """Reject relative, traversing or noncanonical paths."""
    if not isinstance(path, str) or not path.startswith("/") or "\x00" in path:
        raise StageError("absolute_path_required")
    parts = path.split("/")
    if any(p in (".", "..") for p in parts) or "//" in path or (path != "/" and path.endswith("/")):
        raise StageError("nontraversing_normalized_path_required")
    return [part for part in parts if part]

def open_directory(path: str) -> int:
    """Open every component relative to a no-follow directory descriptor."""
    parts = path_parts(path)
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise

def identity(st: os.stat_result) -> tuple[int, ...]:
    """Bind file identity and metadata across a read."""
    return (st.st_dev, st.st_ino, st.st_mode, st.st_uid, st.st_gid,
            st.st_size, st.st_mtime_ns, st.st_ctime_ns)

def bounded_regular_read(fd: int, limit: int, expected_mode: int | None = None,
                         expected_owner: int | None = None) -> bytes:
    """Read one stable regular file under a hard byte limit."""
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise StageError("bounded_regular_file_required")
    if expected_mode is not None and stat.S_IMODE(before.st_mode) != expected_mode:
        raise StageError("file_mode_mismatch")
    if expected_mode is not None and before.st_nlink != 1:
        raise StageError("shared_file_preserved")
    if expected_owner is not None and before.st_uid != expected_owner:
        raise StageError("foreign_file_preserved")
    result = bytearray()
    while len(result) < before.st_size:
        data = os.read(fd, min(1024 * 1024, before.st_size - len(result)))
        if not data:
            break
        result.extend(data)
    if len(result) != before.st_size or identity(before) != identity(os.fstat(fd)):
        raise StageError("file_changed_during_read")
    return bytes(result)

def read_path(path: str, limit: int) -> bytes:
    """Read a path with no-follow custody through its ancestors."""
    parts = path_parts(path)
    if not parts:
        raise StageError("regular_file_path_required")
    parent = "/" + "/".join(parts[:-1]) if len(parts) > 1 else "/"
    parent_fd = open_directory(parent)
    fd = None
    try:
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=parent_fd)
        return bounded_regular_read(fd, limit)
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent_fd)

def validate_plan(plan: dict[str, Any], members: dict[str, bytes]) -> dict[str, Any]:
    """Validate the closed plan, six payload pins and unadmitted HOLD."""
    if (plan.get("schema") != "rubicon-held-stage-plan/v1"
            or plan.get("operation") != "inert_file_staging"
            or plan.get("admission") != "prepared_only"
            or not isinstance(plan.get("ticket"), str) or not plan["ticket"]):
        raise StageError("closed_prepared_plan_required")
    effects = plan.get("effects")
    if (not isinstance(effects, dict) or set(effects) != EFFECT_NAMES
            or any(value is not False for value in effects.values())):
        raise StageError("operational_effects_refused")
    activation = plan.get("activation")
    if not isinstance(activation, dict) or activation.get("admitted") is not False:
        raise StageError("activation_refused")
    target = plan.get("target")
    parent = plan.get("staging_parent")
    path_parts(target)
    path_parts(parent)
    if (str(PurePosixPath(target).parent) != parent
            or PurePosixPath(parent).name != "staged"
            or PurePosixPath(target).name in ("", RECEIPT_NAME)):
        raise StageError("target_parent_mismatch")
    payload = plan.get("payload_files")
    if not isinstance(payload, dict) or set(payload) != PAYLOAD_NAMES:
        raise StageError("closed_six_payloads_required")
    for name, pin in payload.items():
        if not isinstance(pin, dict) or set(pin) != {"sha256", "bytes", "mode"}:
            raise StageError("closed_payload_pin_required")
        data = members["payload/" + name]
        if (not sha_valid(pin["sha256"]) or digest(data) != pin["sha256"]
                or type(pin["bytes"]) is not int or len(data) != pin["bytes"]
                or pin["mode"] != "0600"):
            raise StageError("payload_pin_mismatch")
    hold = parse_json(members["payload/HOLD.json"])
    if (hold.get("schema") != "rubicon-inert-staging-hold/v1"
            or hold.get("mode") != "no_start" or hold.get("ticket") != plan.get("ticket")
            or any(hold.get(key) is not False for key in HOLD_GATES)):
        raise StageError("hold_boundary_refused")
    return plan

def verify_bundle(bundle_path: str, bundle_sha256: str) -> dict[str, Any]:
    """Pin original compressed bytes before bounded archive interpretation."""
    if not sha_valid(bundle_sha256):
        raise StageError("bundle_sha256_required")
    raw = read_path(bundle_path, MAX_BUNDLE_BYTES)
    if digest(raw) != bundle_sha256:
        raise StageError("bundle_digest_mismatch")
    members = {}
    expanded = 0
    try:
        # Bound decompression before tar/PAX parsing can allocate untrusted data.
        with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as compressed:
            tar_bytes = compressed.read(MAX_EXPANDED_BYTES + 1)
        if len(tar_bytes) > MAX_EXPANDED_BYTES:
            raise StageError("expanded_archive_limit_exceeded")
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as archive:
            for member in archive:
                if (len(members) >= 8 or member.name not in BUNDLE_NAMES
                        or member.name in members or not member.isreg()
                        or member.sparse is not None
                        or member.mode != 0o600 or member.size < 0
                        or expanded + member.size > MAX_EXPANDED_BYTES):
                    raise StageError("closed_regular_eight_member_archive_required")
                if any(key.startswith("GNU.sparse") for key in member.pax_headers):
                    raise StageError("sparse_members_refused")
                stream = archive.extractfile(member)
                if stream is None:
                    raise StageError("missing_regular_member")
                with stream:
                    data = stream.read(member.size + 1)
                if len(data) != member.size:
                    raise StageError("member_size_mismatch")
                expanded += member.size
                members[member.name] = data
    except (tarfile.TarError, EOFError, OSError, zlib.error) as exc:
        raise StageError("invalid_bundle_archive") from exc
    if set(members) != BUNDLE_NAMES:
        raise StageError("closed_regular_eight_member_archive_required")
    plan = validate_plan(parse_json(members["held-stage-plan.json"]), members)
    return {"plan": plan, "bundle_sha256": bundle_sha256,
            "plan_sha256": digest(members["held-stage-plan.json"]),
            "payload": {name: members["payload/" + name] for name in PAYLOAD_NAMES}}

def public_verification(candidate: dict[str, Any]) -> dict[str, Any]:
    """Produce a receipt without raw payload or external authorization claims."""
    plan = candidate["plan"]
    return {"schema": "rubicon-held-bundle-verification/v1", "status": "verified_inert",
            "bundle_sha256": candidate["bundle_sha256"],
            "plan_sha256": candidate["plan_sha256"], "ticket": plan["ticket"],
            "target_host": plan.get("target_host"), "target": plan["target"],
            "staging_parent": plan["staging_parent"], "payload_files": plan["payload_files"],
            "effects": plan["effects"], "activation_admitted": False,
            "authorization": "calling_governed_workflow_required",
            "bootstrap_allowed": False, "operational_mutations": 0}

def parent_custody(parent_fd: int) -> dict[str, Any]:
    """Require the separately established parent to be owned and nonwritable by others."""
    st = os.fstat(parent_fd)
    if st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) & 0o022:
        raise StageError("separately_admitted_owned_parent_required")
    return {"device": st.st_dev, "inode": st.st_ino, "uid": st.st_uid,
            "mode": format(stat.S_IMODE(st.st_mode), "04o")}

def plan_stage(candidate: dict[str, Any]) -> dict[str, Any]:
    """Inspect target availability without creating any directory."""
    result = public_verification(candidate)
    parent_fd = None
    try:
        parent_fd = open_directory(candidate["plan"]["staging_parent"])
        result["parent_custody"] = parent_custody(parent_fd)
        name = PurePosixPath(candidate["plan"]["target"]).name
        try:
            os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            result["target_status"] = "absent"
        else:
            result["target_status"] = "existing_target_preserved"
    except OSError:
        result["target_status"] = "parent_unavailable_or_symlink"
    except StageError:
        result["target_status"] = "parent_custody_unqualified"
    finally:
        if parent_fd is not None:
            os.close(parent_fd)
    result["status"] = "read_only_plan"
    result["apply_admitted"] = False
    return result

def create_file(directory_fd: int, name: str, data: bytes) -> None:
    """Create and synchronize one private new file without replacement."""
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=directory_fd)
    try:
        os.fchmod(fd, 0o600)
        remaining = memoryview(data)
        while remaining:
            count = os.write(fd, remaining)
            if count <= 0:
                raise StageError("incomplete_write")
            remaining = remaining[count:]
        os.fsync(fd)
    finally:
        os.close(fd)

def stage(candidate: dict[str, Any], parent_receipt_path: str,
          parent_receipt_sha256: str, apply: bool = False) -> dict[str, Any]:
    """Write only the inert candidate after caller-owned external admission."""
    if not apply:
        raise StageError("explicit_apply_and_external_admission_required")
    if not sha_valid(parent_receipt_sha256):
        raise StageError("parent_receipt_digest_required")
    parent_raw = read_path(parent_receipt_path, MAX_RECEIPT_BYTES)
    if digest(parent_raw) != parent_receipt_sha256:
        raise StageError("parent_receipt_digest_mismatch")
    parse_json(parent_raw)  # Opaque existing normal workflow provenance; never execute it.
    plan = candidate["plan"]
    parent_fd = open_directory(plan["staging_parent"])
    target_fd = None
    try:
        custody = parent_custody(parent_fd)
        target_name = PurePosixPath(plan["target"]).name
        try:
            os.mkdir(target_name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError as exc:
            raise StageError("existing_target_preserved") from exc
        target_fd = os.open(target_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=parent_fd)
        os.fchmod(target_fd, 0o700)
        target_st = os.fstat(target_fd)
        receipt = {"schema": "rubicon-inert-stage-receipt/v1", "status": "staged_inert",
                   "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   "target": plan["target"], "staging_parent": plan["staging_parent"],
                   "target_device": target_st.st_dev, "target_inode": target_st.st_ino,
                   "owner_uid": os.geteuid(), "target_mode": "0700",
                   "parent_custody": custody, "bundle_sha256": candidate["bundle_sha256"],
                   "plan_sha256": candidate["plan_sha256"],
                   "parent_receipt_sha256": parent_receipt_sha256,
                   "parent_receipt_note": "Pinned external workflow provenance; not an authorization verdict.",
                   "payload_files": plan["payload_files"], "effects": plan["effects"],
                   "activation_admitted": False, "bootstrap_allowed": False,
                   "rollback_mode": "read_only_preserve", "operational_mutations": 0}
        for name in sorted(PAYLOAD_NAMES):
            create_file(target_fd, name, candidate["payload"][name])
        create_file(target_fd, RECEIPT_NAME,
                    (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode())
        os.fsync(target_fd)
        os.fsync(parent_fd)
        # Keep the full new/partial directory on every error. Never delete or repair it.
        checked = check_rollback(candidate, receipt)
        if checked["status"] != "unchanged_inert_stage_preserved":
            raise StageError("stage_readback_failed_partial_state_preserved")
        return receipt
    except BaseException:
        # No cleanup that could remove concurrent, foreign or altered state.
        raise
    finally:
        if target_fd is not None:
            os.close(target_fd)
        os.close(parent_fd)

def check_rollback(candidate: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    """Verify the unchanged staging directory while preserving every file."""
    plan = candidate["plan"]
    if (receipt.get("schema") != "rubicon-inert-stage-receipt/v1"
            or receipt.get("status") != "staged_inert"
            or receipt.get("target") != plan["target"]
            or receipt.get("staging_parent") != plan["staging_parent"]
            or receipt.get("bundle_sha256") != candidate["bundle_sha256"]
            or receipt.get("plan_sha256") != candidate["plan_sha256"]
            or receipt.get("payload_files") != plan["payload_files"]
            or receipt.get("effects") != plan["effects"]
            or receipt.get("activation_admitted") is not False
            or receipt.get("bootstrap_allowed") is not False
            or receipt.get("rollback_mode") != "read_only_preserve"
            or receipt.get("owner_uid") != os.geteuid()):
        raise StageError("receipt_binding_mismatch")
    parent_fd = open_directory(plan["staging_parent"])
    target_fd = None
    try:
        recorded_parent = receipt.get("parent_custody")
        if parent_custody(parent_fd) != recorded_parent:
            raise StageError("changed_parent_custody_preserved")
        target_name = PurePosixPath(plan["target"]).name
        target_fd = os.open(target_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=parent_fd)
        st = os.fstat(target_fd)
        if (st.st_dev != receipt.get("target_device") or st.st_ino != receipt.get("target_inode")
                or st.st_uid != receipt["owner_uid"] or stat.S_IMODE(st.st_mode) != 0o700):
            raise StageError("foreign_or_changed_directory_preserved")
        expected = set(PAYLOAD_NAMES) | {RECEIPT_NAME}
        if stage_names(target_fd) != expected:
            raise StageError("foreign_or_partial_files_preserved")
        file_identities = {}
        for name in expected:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=target_fd)
            try:
                data = bounded_regular_read(fd, MAX_EXPANDED_BYTES, 0o600, receipt["owner_uid"])
                file_identities[name] = identity(os.fstat(fd))
            finally:
                os.close(fd)
            if name == RECEIPT_NAME:
                if parse_json(data) != receipt:
                    raise StageError("modified_receipt_preserved")
            elif digest(data) != plan["payload_files"][name]["sha256"]:
                raise StageError("modified_files_preserved")
        # Individual stable reads alone do not prove one stable directory view.
        if stage_names(target_fd) != expected:
            raise StageError("changed_directory_entries_preserved")
        for name, file_identity in file_identities.items():
            current = os.stat(name, dir_fd=target_fd, follow_symlinks=False)
            if identity(current) != file_identity:
                raise StageError("files_changed_during_inspection_preserved")
        if identity(os.fstat(target_fd)) != identity(st):
            raise StageError("directory_changed_during_inspection_preserved")
        rebound_parent_fd = open_directory(plan["staging_parent"])
        try:
            if parent_custody(rebound_parent_fd) != recorded_parent:
                raise StageError("changed_parent_custody_preserved")
            rebound_target = os.stat(target_name, dir_fd=rebound_parent_fd,
                                     follow_symlinks=False)
            if identity(rebound_target) != identity(st):
                raise StageError("target_namespace_changed_preserved")
        finally:
            os.close(rebound_parent_fd)
        return {"schema": "rubicon-held-rollback-check/v1",
                "status": "unchanged_inert_stage_preserved", "target": plan["target"],
                "files_removed": 0, "data_removed": False, "operational_mutations": 0,
                "bootstrap_allowed": False, "cleanup_requires_separate_admission": True}
    finally:
        if target_fd is not None:
            os.close(target_fd)
        os.close(parent_fd)

def stage_names(directory_fd: int) -> set[str]:
    """Read at most eight names to validate a closed seven-file staging set."""
    names = set()
    with os.scandir(directory_fd) as entries:
        for entry in entries:
            names.add(entry.name)
            if len(names) > len(PAYLOAD_NAMES) + 1:
                raise StageError("foreign_files_preserved")
    return names

def main() -> int:
    """Dispatch explicit operations and emit bounded receipt/error objects."""
    epilog = (
        "ENVIRONMENT\n  No environment variables or product configuration are read.\n\n"
        "FILES\n  --bundle: original closed held archive; historical helper is never executed.\n"
        "  --parent-receipt: pinned existing workflow provenance for stage only.\n"
        "  --receipt: pinned staging provenance for read-only rollback verification.\n\n"
        "EXAMPLES\n  held-staging.py verify --bundle /custody/held.tar.gz --bundle-sha256 SHA256\n"
        "    Verify original bytes without extraction or writes.\n"
        "  held-staging.py plan --bundle /custody/held.tar.gz --bundle-sha256 SHA256\n"
        "    Inspect parent custody and preserve an existing target.\n"
    )
    parser = argparse.ArgumentParser(
        description="Verify and stage the six payloads of a pinned inert Fabric bundle. "
                    "Operational authorization remains with the calling governed workflow.",
        epilog=epilog, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    descriptions = {
        "verify": "Verify original archive identity, closed payload pins and held effects without writes.",
        "plan": "Inspect the existing staging parent and target availability without writes.",
        "stage": "Create six private inert payloads and one receipt after separate workflow admission. "
                 "Existing or partial state is preserved; no runtime operation is performed.",
        "rollback": "Verify exact staged custody and digests while preserving every file. "
                    "Cleanup requires a separate admitted procedure.",
    }
    for command in ("verify", "plan", "stage", "rollback"):
        child = sub.add_parser(command, help=descriptions[command],
                               description=descriptions[command],
                               formatter_class=argparse.RawDescriptionHelpFormatter)
        child.add_argument("--bundle", required=True,
                           help="Absolute no-follow path to the original held archive. Required.")
        child.add_argument("--bundle-sha256", required=True,
                           help="Separately accepted SHA-256 of original compressed bytes. Required.")
        if command == "stage":
            child.add_argument("--parent-receipt", required=True,
                               help="Absolute path to existing governed operation provenance. Required.")
            child.add_argument("--parent-receipt-sha256", required=True,
                               help="Reviewed SHA-256 of that parent receipt; not an authorization verdict. Required.")
            child.add_argument("--apply", action="store_true", required=True,
                               help="Write the six inert payloads and receipt to one new directory. Required.")
        if command == "rollback":
            child.add_argument("--receipt", required=True,
                               help="Absolute path to recorded STAGING-RECEIPT.json. Required.")
            child.add_argument("--receipt-sha256", required=True,
                               help="Separately recorded SHA-256 of the staging receipt. Required.")
    args = parser.parse_args()
    try:
        candidate = verify_bundle(args.bundle, args.bundle_sha256)
        if args.command == "verify":
            result = public_verification(candidate)
        elif args.command == "plan":
            result = plan_stage(candidate)
        elif args.command == "stage":
            result = stage(candidate, args.parent_receipt, args.parent_receipt_sha256, args.apply)
        else:
            raw = read_path(args.receipt, MAX_RECEIPT_BYTES)
            if not sha_valid(args.receipt_sha256) or digest(raw) != args.receipt_sha256:
                raise StageError("receipt_digest_mismatch")
            result = check_rollback(candidate, parse_json(raw))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, StageError, TypeError, KeyError) as exc:
        # No arbitrary file contents, OS path detail or credentials in error output.
        print(json.dumps({"schema": "rubicon-held-stage-error/v1", "status": "refused",
                          "reason": str(exc) if isinstance(exc, StageError) else type(exc).__name__,
                          "existing_state_preserved": True, "bootstrap_allowed": False}))
        return 2

if __name__ == "__main__":
    sys.exit(main())
