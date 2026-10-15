#!/usr/bin/env python3
"""Bounded read-only recovery metadata inventory; never authorizes recovery.

Source-owned administrator metadata utility. No subprocess, network, database, environment/config
loading, service operation, file mutation, privilege acquisition or extraction.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import stat
import sys
from typing import Any

# Hard traversal and byte budgets cannot be raised by command-line input.
TOOL_SCHEMA = "rubicon-admin-recovery-inventory/v1"
HARD_DEPTH = 4
HARD_ENTRIES = 2000
HARD_HASH_BYTES = 83886080
HEADER_BYTES = 512
CHUNK_BYTES = 1048576
PROTECTED_TOKENS = (
    "secret", "credential", "password", "passwd", "shadow", "token",
    "private", "authorized_keys", "known_hosts", ".ssh", ".gnupg",
    ".aws", ".azure", ".claude", ".codex", ".kube", ".docker",
    "account", "cookie", "session", "auth", "config", ".env", "runtime.env",
)
PROTECTED_SUFFIXES = (".env", ".pem", ".key", ".p12", ".pfx", ".conf",
                      ".ini", ".yaml", ".yml", ".toml", ".json", ".log",
                      ".jsonl", ".csv", ".txt")
HASH_SUFFIXES = (".tar", ".tar.gz", ".tgz", ".tar.xz", ".txz", ".tar.zst",
                 ".zst", ".gz", ".zip", ".sqlite", ".sqlite3", ".db",
                 ".dump", ".backup", ".bak", ".rdb", ".age", ".gpg", ".enc")
ROLE_HINTS = {
    "postgresql": ("postgres", "pgdata", "pg_wal", "pg_xlog", "pg_control",
                   "pg_version", "basebackup", "wal"),
    "witness": ("witness", "leader", "epoch", "sentinel"),
    "objects": ("minio", "object", "artifact", "report", "blob"),
    "fabric_state": ("fabric", "sqlite", "execution-state"),
    "release": ("release", "emergency", "bundle", "image-lock", "manifest"),
}

def iso_time(ns: int) -> str:
    """Format filesystem timestamps in UTC."""
    return datetime.datetime.fromtimestamp(ns / 1000000000,
        datetime.timezone.utc).isoformat()

def metadata(st: os.stat_result) -> dict[str, int | str]:
    """Return custody fields without reading file data."""
    return {"mode": format(stat.S_IMODE(st.st_mode), "04o"), "uid": st.st_uid,
            "gid": st.st_gid, "size": st.st_size, "mtime_utc": iso_time(st.st_mtime_ns),
            "device": st.st_dev, "inode": st.st_ino}

def kind(st: os.stat_result) -> str:
    """Classify links and special files without opening them."""
    if stat.S_ISDIR(st.st_mode):
        return "directory"
    if stat.S_ISREG(st.st_mode):
        return "regular_file"
    if stat.S_ISLNK(st.st_mode):
        return "symlink_not_followed"
    return "special_file_not_opened"

def open_root_nofollow(root: str) -> int:
    """Open an admitted absolute directory without following any ancestor link."""
    # Every component is opened relative to an already checked directory.
    if not os.path.isabs(root) or any(x in (".", "..") for x in root.split("/")):
        raise ValueError("root_must_be_absolute_without_dot_components")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open("/", directory_flags)
    try:
        for component in filter(None, root.split("/")):
            child = os.open(component, directory_flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise

def protected(relative: str) -> bool:
    """Keep named credential, configuration and log custody metadata-only."""
    lowered = relative.lower()
    return (any(token in lowered for token in PROTECTED_TOKENS)
            or lowered.endswith(PROTECTED_SUFFIXES)
            or "/logs/" in "/" + lowered + "/"
            or lowered.startswith("logs/"))

def role_hints(relative: str) -> list[str]:
    """Identify filename candidates without asserting datastore authority."""
    # Filename hints are candidates only, never positive datastore identification.
    lowered = relative.lower()
    return [role for role, tokens in ROLE_HINTS.items()
            if any(token in lowered for token in tokens)]

def safe_header_kind(header: bytes) -> str:
    """Emit a fixed binary-magic classification, never header bytes."""
    # Emit only fixed classifications, never bytes, strings or decoded content.
    if header.startswith(b"SQLite format 3\x00"):
        return "sqlite_magic"
    if header.startswith(b"\x1f\x8b"):
        return "gzip_magic"
    if header.startswith(b"PK\x03\x04"):
        return "zip_magic"
    if header.startswith(b"\xfd7zXZ\x00"):
        return "xz_magic"
    if header.startswith(b"\x28\xb5\x2f\xfd"):
        return "zstd_magic"
    if len(header) >= 262 and header[257:262] == b"ustar":
        return "tar_magic"
    return "unrecognized_header"

def error_status(exc: OSError) -> str:
    """Preserve absence, access denial and unavailable evidence distinctions."""
    if isinstance(exc, PermissionError):
        return "inaccessible"
    if isinstance(exc, FileNotFoundError):
        return "absent_or_changed_during_inventory"
    return "unavailable_or_changed_during_inventory"

def script_sha256() -> str:
    """Pin the stable regular script used for this receipt."""
    fd = os.open(os.path.abspath(__file__), os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > 131072:
            raise ValueError("unqualified_script_file")
        digest = hashlib.sha256()
        remaining = 131073
        while remaining:
            data = os.read(fd, min(CHUNK_BYTES, remaining))
            if not data:
                break
            remaining -= len(data)
            digest.update(data)
        after = os.fstat(fd)
        if remaining == 0 or (before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError("script_changed_during_read")
        return digest.hexdigest()
    finally:
        os.close(fd)

def inventory(root: str, max_depth: int, max_entries: int,
              max_hash_bytes: int) -> dict[str, Any]:
    """Produce bounded no-follow metadata without authorizing any bootstrap."""
    if not (1 <= max_depth <= HARD_DEPTH and 1 <= max_entries <= HARD_ENTRIES
            and 0 <= max_hash_bytes <= HARD_HASH_BYTES):
        raise ValueError("requested_bounds_exceed_reviewed_hard_limits")
    rows = []
    counts = {"listed_entries": 0, "hashed_bytes": 0, "hashed_files": 0,
              "inaccessible": 0, "unavailable_or_changed": 0,
              "symlinks_skipped": 0, "special_files_skipped": 0,
              "protected_files_metadata_only": 0, "protected_directories_skipped": 0,
              "depth_truncated": 0,
              "entry_limit_reached": False, "directory_listing_truncated": 0,
              "hash_budget_skipped": 0, "cross_device_files_skipped": 0}
    candidates = {role: [] for role in ROLE_HINTS}
    def append_row(row: dict[str, Any]) -> None:
        """Append a bounded row and its filename-only role hints."""
        rows.append(row)
        for role in row.get("candidate_roles", []):
            candidates[role].append(row["relative_path"])

    def hash_eligible_file(parent_fd: int, name: str, expected: os.stat_result,
                           row: dict[str, Any]) -> None:
        """Read only allowlisted stable payloads within the aggregate budget."""
        if expected.st_dev != root_device:
            row["data_read"] = "none_different_device"
            counts["cross_device_files_skipped"] += 1
            return
        if protected(row["relative_path"]):
            row["data_read"] = "none_protected_metadata_only"
            counts["protected_files_metadata_only"] += 1
            return
        if not name.lower().endswith(HASH_SUFFIXES):
            row["data_read"] = "none_not_payload_allowlist"
            return
        if expected.st_size > max_hash_bytes - counts["hashed_bytes"]:
            row["data_read"] = "none_hash_budget"
            counts["hash_budget_skipped"] += 1
            return
        fd = None
        try:
            # O_NONBLOCK also prevents a race to a FIFO from blocking this reader.
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=parent_fd)
            before = os.fstat(fd)
            identity = lambda st: (st.st_dev, st.st_ino, st.st_mode,
                                   st.st_size, st.st_mtime_ns, st.st_ctime_ns)
            if not stat.S_ISREG(before.st_mode) or identity(before) != identity(expected):
                row["status"] = "changed_before_read"
                counts["unavailable_or_changed"] += 1
                return
            digest = hashlib.sha256()
            header = b""
            bytes_read = 0
            while bytes_read < before.st_size:
                data = os.read(fd, min(CHUNK_BYTES, before.st_size - bytes_read))
                if not data:
                    break
                if len(header) < HEADER_BYTES:
                    header += data[:HEADER_BYTES-len(header)]
                digest.update(data)
                bytes_read += len(data)
                counts["hashed_bytes"] += len(data)
            after = os.fstat(fd)
            if identity(before) != identity(after) or bytes_read != before.st_size:
                row["status"] = "changed_during_read"
                row["data_read"] = "unstable_no_digest_emitted"
                counts["unavailable_or_changed"] += 1
                return
            row["sha256"] = digest.hexdigest()
            row["safe_header_classification"] = safe_header_kind(header)
            row["data_read"] = "eligible_payload_full_digest_only"
            counts["hashed_files"] += 1
        except OSError as exc:
            row["status"] = error_status(exc)
            counts["inaccessible" if isinstance(exc, PermissionError)
                   else "unavailable_or_changed"] += 1
        finally:
            if fd is not None:
                os.close(fd)

    def walk(directory_fd: int, prefix: str, depth: int) -> None:
        """Traverse at most the remaining entry budget without following links."""
        # Stream at most remaining-budget + 1 names. Never materialize an
        # arbitrarily large directory listing or inspect overflow entries.
        names = []
        remaining = max_entries - counts["listed_entries"]
        if remaining <= 0:
            counts["entry_limit_reached"] = True
            return
        try:
            with os.scandir(directory_fd) as listing:
                for entry in listing:
                    if len(names) >= remaining:
                        counts["directory_listing_truncated"] += 1
                        counts["entry_limit_reached"] = True
                        break
                    names.append(entry.name)
        except OSError as exc:
            append_row({"relative_path": prefix or ".", "status": error_status(exc),
                        "type": "directory_listing_error"})
            counts["inaccessible" if isinstance(exc, PermissionError)
                   else "unavailable_or_changed"] += 1
            return
        for name in sorted(names):
            if counts["listed_entries"] >= max_entries:
                counts["entry_limit_reached"] = True
                break
            counts["listed_entries"] += 1
            relative = prefix + "/" + name if prefix else name
            row = {"relative_path": relative, "candidate_roles": role_hints(relative)}
            try:
                st = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                row.update(metadata(st))
                row["type"] = kind(st)
                row["status"] = "observed"
                if stat.S_ISREG(st.st_mode):
                    hash_eligible_file(directory_fd, name, st, row)
                elif stat.S_ISLNK(st.st_mode):
                    counts["symlinks_skipped"] += 1
                elif not stat.S_ISDIR(st.st_mode):
                    counts["special_files_skipped"] += 1
                append_row(row)
                if stat.S_ISDIR(st.st_mode):
                    if protected(relative):
                        row["descent"] = "protected_directory_not_opened"
                        counts["protected_directories_skipped"] += 1
                    elif depth >= max_depth:
                        row["descent"] = "depth_limit"
                        counts["depth_truncated"] += 1
                    elif counts["listed_entries"] >= max_entries:
                        row["descent"] = "entry_limit"
                        counts["entry_limit_reached"] = True
                    else:
                        child_fd = None
                        try:
                            child_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY
                                               | os.O_NOFOLLOW, dir_fd=directory_fd)
                            opened = os.fstat(child_fd)
                            if (opened.st_dev, opened.st_ino) != (st.st_dev, st.st_ino):
                                row["descent"] = "changed_before_open"
                                counts["unavailable_or_changed"] += 1
                            elif opened.st_dev != root_device:
                                row["descent"] = "different_device_not_entered"
                                counts["depth_truncated"] += 1
                            else:
                                row["descent"] = "opened_nofollow"
                                walk(child_fd, relative, depth + 1)
                        except OSError as exc:
                            row["descent"] = error_status(exc)
                            counts["inaccessible" if isinstance(exc, PermissionError)
                                   else "unavailable_or_changed"] += 1
                        finally:
                            if child_fd is not None:
                                os.close(child_fd)
            except OSError as exc:
                row["status"] = error_status(exc)
                append_row(row)
                counts["inaccessible" if isinstance(exc, PermissionError)
                       else "unavailable_or_changed"] += 1

    result = {
        "schema": TOOL_SCHEMA, "generated_at_utc": datetime.datetime.now(
            datetime.timezone.utc).isoformat(), "host_name": os.uname().nodename,
        "operator_uid": os.getuid(), "operator_euid": os.geteuid(), "root_path": root,
        "bounds": {"max_depth": max_depth, "max_entries": max_entries,
                   "max_hash_bytes": max_hash_bytes, "header_bytes": HEADER_BYTES,
                   "cross_device_descent": False},
        "bootstrap_allowed": False, "authority": "unproven",
        "authority_requirements": ["accepted PG system identity and WAL recovery point",
            "accepted witness epoch leader and sentinel",
            "accepted object and report hash manifest",
            "current source policy host owner and context bindings"],
        "rows": rows, "counts": counts, "candidate_roles": candidates,
        "candidate_note": "Filename hints only; absence in bounded inventory is not proof of loss."
    }
    fd = None
    try:
        fd = open_root_nofollow(root)
        root_st = os.fstat(fd)
        root_device = root_st.st_dev
        result["root_metadata"] = metadata(root_st)
        result["root_status"] = "observed"
        walk(fd, "", 1)
    except (OSError, ValueError) as exc:
        result["root_status"] = error_status(exc) if isinstance(exc, OSError) else "invalid_root"
        counts["inaccessible" if isinstance(exc, PermissionError)
               else "unavailable_or_changed"] += 1
    finally:
        if fd is not None:
            os.close(fd)
    result["bounded_inventory_complete"] = (result["root_status"] == "observed"
        and not counts["inaccessible"] and not counts["unavailable_or_changed"]
        and not counts["depth_truncated"] and not counts["entry_limit_reached"]
        and not counts["hash_budget_skipped"]
        and not counts["cross_device_files_skipped"]
        and not counts["protected_directories_skipped"])
    result["recovery_set_complete"] = False
    result["operator_review_required"] = True
    return result

def main() -> int:
    """Check the tool pin and explicit bounds before emitting a JSON receipt."""
    epilog = (
        "ENVIRONMENT\n  No environment values or product configuration are read.\n\n"
        "FILES\n  --root: one explicitly admitted directory, bounded no-follow traversal.\n"
        "  Protected Env/config/credentials/logs are metadata only.\n"
        "  The script reads itself to report the reviewed source digest.\n\n"
        "EXAMPLES\n  recovery-inventory.py --root /recovery/fabric --expected-script-sha256 SHA256 --json\n"
        "    Emit bounded metadata with bootstrap disallowed.\n"
        "  recovery-inventory.py --root /recovery/fabric --expected-script-sha256 SHA256 --max-hash-bytes 0 --json\n"
        "    Emit metadata without hashing any recovery payload.\n"
    )
    parser = argparse.ArgumentParser(
        description="Inventory bounded recovery metadata without following links or exposing contents. "
                    "The receipt never establishes datastore or bootstrap authority.",
        epilog=epilog, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", required=True,
                        help="One admitted absolute recovery directory; no symlink components. Required.")
    parser.add_argument("--max-depth", type=int, default=HARD_DEPTH,
                        help="Maximum entry depth, hard ceiling 4 (default: %(default)s).")
    parser.add_argument("--max-entries", type=int, default=HARD_ENTRIES,
                        help="Maximum metadata entries, hard ceiling 2000 (default: %(default)s).")
    parser.add_argument("--max-hash-bytes", type=int, default=HARD_HASH_BYTES,
                        help="Aggregate payload hash bytes, hard ceiling 80 MiB (default: %(default)s).")
    parser.add_argument("--expected-script-sha256", required=True,
                        help="Separately reviewed SHA-256 of this trusted script copy. Required.")
    parser.add_argument("--json", action="store_true", required=True,
                        help="Emit escaped JSON metadata only to stdout. Required.")
    args = parser.parse_args()
    if not (1 <= args.max_depth <= HARD_DEPTH and 1 <= args.max_entries <= HARD_ENTRIES
            and 0 <= args.max_hash_bytes <= HARD_HASH_BYTES):
        parser.error("requested bounds exceed reviewed hard limits")
    if len(args.expected_script_sha256) != 64 or any(
            c not in "0123456789abcdef" for c in args.expected_script_sha256):
        parser.error("expected script SHA-256 must be a lowercase 64-digit digest")
    try:
        actual = script_sha256()
    except (OSError, ValueError):
        parser.error("script identity could not be safely verified")
    if actual != args.expected_script_sha256:
        parser.error("script digest differs from reviewed artifact")
    result = inventory(args.root, args.max_depth, args.max_entries, args.max_hash_bytes)
    result["script_sha256"] = actual
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True))
    return 0 if result["root_status"] == "observed" else 2

if __name__ == "__main__":
    sys.exit(main())
