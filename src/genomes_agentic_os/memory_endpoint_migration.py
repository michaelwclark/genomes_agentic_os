"""Guarded, byte-preserving upgrades of installed managed Brain endpoints.

This module performs no network or memory operation. A separately verified
service receipt is an input, not a substitute for live service qualification.
Rollback retains only nonsecret URL patches, never original configurations.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import secrets
import stat
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path, PurePosixPath
from typing import Any

from .scaffold import harness_source_dir

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import tomllib
except ImportError:  # Existing package commands continue to work on Python3.10.
    tomllib = None

OLD_ENDPOINT = "http://127.0.0.1:3155/mcp"
NEW_ENDPOINT = "http://127.0.0.1:3166/mcp"
ALLOWED_PATHS = frozenset({
    "harness/config.toml", "harness/shared_factory/config.toml",
    "harness/hooks/harness-emit-trace.sh",
})
MAX_FILE_BYTES = 1024 * 1024
MAX_JSON_BYTES = 256 * 1024
JOURNAL_DIR = ".memory-endpoint-migrations"
LOCK_NAME = ".memory-endpoint-migration.lock"


class MemoryEndpointMigrationError(ValueError):
    """A bounded refusal; messages never contain configuration values."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _encoded(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise MemoryEndpointMigrationError("duplicate JSON field")
        result[key] = value
    return result


def _float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise MemoryEndpointMigrationError("nonfinite JSON value")
    return result


def _json(data: bytes) -> dict:
    try:
        value = json.loads(data, object_pairs_hook=_pairs, parse_float=_float,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError):
        raise MemoryEndpointMigrationError("invalid bounded JSON document") from None
    if not isinstance(value, dict):
        raise MemoryEndpointMigrationError("JSON document must be an object")
    return value


def _identity(info: os.stat_result) -> dict:
    return {"device": info.st_dev, "inode": info.st_ino, "uid": info.st_uid,
            "gid": info.st_gid, "mode": stat.S_IMODE(info.st_mode)}


def _emitter_factory() -> tuple[bytes, bytes]:
    """Read the canonical package-owned declaration, without duplicating aliases."""
    try:
        with (harness_source_dir() / "hooks" / "harness-emit-trace.sh").open("rb") as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
    except OSError:
        raise MemoryEndpointMigrationError("canonical emitter resource unavailable") from None
    if len(data) > MAX_FILE_BYTES:
        raise MemoryEndpointMigrationError("canonical emitter resource exceeds bounded size")
    declarations = re.findall(rb"(?m)^MCP_URL=.*$", data)
    if len(declarations) != 1:
        raise MemoryEndpointMigrationError("ambiguous canonical emitter declaration")
    declaration = declarations[0].rstrip(b"\r")
    if (not declaration.startswith(b'MCP_URL="${GENOMES_BRAIN_MCP_URL:-${')
            or not declaration.endswith(NEW_ENDPOINT.encode() + b'}}"')
            or declaration.count(NEW_ENDPOINT.encode()) != 1):
        raise MemoryEndpointMigrationError("unqualified canonical emitter endpoint")
    return data, declaration


def _runtime() -> dict:
    emitter, _ = _emitter_factory()
    return {"package_version": version("genomes-agentic-os"),
            "module_sha256": _sha(Path(__file__).read_bytes()),
            "emitter_factory_sha256": _sha(emitter)}


def _regular(info: os.stat_result) -> None:
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise MemoryEndpointMigrationError("regular single-link file required")
    if info.st_uid != os.geteuid() or info.st_gid not in {os.getegid(), *os.getgroups()}:
        raise MemoryEndpointMigrationError("foreign file ownership")
    if stat.S_IMODE(info.st_mode) & 0o7022:
        raise MemoryEndpointMigrationError("unsafe file permissions")
    if getattr(info, "st_flags", 0):
        raise MemoryEndpointMigrationError("unsupported file flags")


@contextmanager
def _directory(path: str | Path):
    path = Path(path).expanduser()
    if not path.is_absolute() or ".." in path.parts:
        raise MemoryEndpointMigrationError("absolute no-follow root required")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        info = os.fstat(descriptor)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022:
            raise MemoryEndpointMigrationError("root ownership or permissions unsafe")
        yield descriptor
    except OSError:
        raise MemoryEndpointMigrationError("no-follow directory access refused") from None
    finally:
        os.close(descriptor)


@contextmanager
def _parent(root: int, relative: str):
    parts = PurePosixPath(relative).parts
    if not parts or relative.startswith("/") or any(p in {".", ".."} for p in parts):
        raise MemoryEndpointMigrationError("invalid managed relative path")
    descriptor = os.dup(root)
    try:
        for part in parts[:-1]:
            following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
            info = os.fstat(descriptor)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022:
                raise MemoryEndpointMigrationError("unsafe managed parent")
        yield descriptor, parts[-1]
    except OSError:
        raise MemoryEndpointMigrationError("managed path access refused") from None
    finally:
        os.close(descriptor)


def _read_at(parent: int, name: str, limit: int = MAX_FILE_BYTES) -> tuple[bytes, dict]:
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        before = os.fstat(descriptor)
        _regular(before)
        if hasattr(os, "listxattr") and os.listxattr(descriptor):
            raise MemoryEndpointMigrationError("unsupported extended file attributes")
        if before.st_size > limit:
            raise MemoryEndpointMigrationError("file exceeds bounded size")
        data = bytearray()
        while True:
            chunk = os.read(descriptor, min(65536, limit + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > limit:
                raise MemoryEndpointMigrationError("file exceeds bounded size")
        after = os.fstat(descriptor)
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns, _identity(before)) != (
            after.st_size, after.st_mtime_ns, after.st_ctime_ns, _identity(after)
        ):
            raise MemoryEndpointMigrationError("file changed during inventory")
        return bytes(data), _identity(after)
    finally:
        os.close(descriptor)


def _read(root: int, relative: str) -> tuple[bytes, dict]:
    with _parent(root, relative) as (parent, name):
        try:
            return _read_at(parent, name)
        except OSError:
            raise MemoryEndpointMigrationError("managed regular file access refused") from None


def read_document(path: str | Path) -> dict:
    path = Path(path).expanduser()
    with _directory(path.parent) as parent:
        try:
            return _json(_read_at(parent, path.name, MAX_JSON_BYTES)[0])
        except OSError:
            raise MemoryEndpointMigrationError("no-follow document access refused") from None


def _service(receipt: dict, host: str, *, fresh: bool = True) -> None:
    if not isinstance(receipt, dict):
        raise MemoryEndpointMigrationError("invalid service verification envelope")
    if (receipt.get("schema"), receipt.get("status"), receipt.get("service"),
        receipt.get("endpoint"), receipt.get("host"), receipt.get("machine"),
        receipt.get("health_status")) != (
        "memory-endpoint-service-verification/v1", "verified", "genomes_brain",
        NEW_ENDPOINT, host, platform.node(), "healthy",
    ):
        raise MemoryEndpointMigrationError("current Brain service identity is unqualified")
    try:
        captured = datetime.fromisoformat(receipt["verified_at"].replace("Z", "+00:00"))
        if captured.tzinfo is None:
            raise ValueError()
        age = (datetime.now(timezone.utc) - captured).total_seconds()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise MemoryEndpointMigrationError("service verification timestamp invalid") from None
    if fresh and not -60 <= age <= 900:
        raise MemoryEndpointMigrationError("service verification is stale or future-dated")


def _patch(data: bytes, offset: int, before: str, after: str) -> bytes:
    old, new = before.encode(), after.encode()
    if type(offset) is not int or offset < 0 or data[offset:offset + len(old)] != old:
        raise MemoryEndpointMigrationError("scoped URL patch no longer matches")
    return data[:offset] + new + data[offset + len(old):]


def _toml_patch(data: bytes) -> tuple[int | None, str]:
    if tomllib is None:
        raise MemoryEndpointMigrationError("TOML migration requires Python3.11 or newer")
    try:
        parsed = tomllib.loads(data.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise MemoryEndpointMigrationError("invalid or duplicate TOML configuration") from None
    servers = parsed.get("mcp_servers", {})
    if not isinstance(servers, dict):
        raise MemoryEndpointMigrationError("ambiguous MCP server table")
    server = servers.get("genomes_brain")
    if server is None:
        return None, "managed_server_absent"
    if not isinstance(server, dict):
        raise MemoryEndpointMigrationError("ambiguous managed server entry")
    if "command" in server:
        if "url" in server:
            raise MemoryEndpointMigrationError("mixed HTTP and stdio transport")
        return None, "stdio_preserved"
    value = server.get("url")
    if not isinstance(value, str):
        raise MemoryEndpointMigrationError("unsupported managed URL declaration")
    if value != OLD_ENDPOINT:
        return None, "current_endpoint" if value == NEW_ENDPOINT else "custom_url_preserved"
    headers = list(re.finditer(rb"(?m)^[ \t]*\[([^\r\n]+)\][ \t]*(?:#[^\r\n]*)?\r?$", data))
    managed = [i for i, item in enumerate(headers) if item.group(1) == b"mcp_servers.genomes_brain"]
    if len(managed) != 1:
        raise MemoryEndpointMigrationError("unsupported managed table locator")
    index = managed[0]
    start = headers[index].end()
    end = headers[index + 1].start() if index + 1 < len(headers) else len(data)
    pattern = rb"(?m)^[ \t]*url[ \t]*=[ \t]*([\"'])" + re.escape(OLD_ENDPOINT.encode()) + rb"\1[ \t]*(?:#[^\r\n]*)?\r?$"
    matches = list(re.finditer(pattern, data[start:end]))
    if len(matches) != 1:
        raise MemoryEndpointMigrationError("unsupported managed URL locator")
    return start + matches[0].start() + matches[0].group().index(OLD_ENDPOINT.encode()), "eligible"


def _hook_patch(data: bytes) -> tuple[int | None, str]:
    declarations = re.findall(rb"(?m)^MCP_URL=.*$", data)
    if len(declarations) != 1:
        raise MemoryEndpointMigrationError("ambiguous emitter endpoint declaration")
    _, declaration = _emitter_factory()
    expression = declaration.replace(NEW_ENDPOINT.encode(), OLD_ENDPOINT.encode())
    matches = list(re.finditer(rb"(?m)^" + re.escape(expression) + rb"\r?$", data))
    if not matches:
        return None, "current_or_custom_fallback_preserved"
    return matches[0].start() + expression.index(OLD_ENDPOINT.encode()), "eligible"


def plan_memory_endpoint(root: str | Path, *, host: str, paths: list[str], service_receipt: dict) -> dict:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", host):
        raise MemoryEndpointMigrationError("invalid logical host name")
    if not paths or len(paths) != len(set(paths)) or not set(paths) <= ALLOWED_PATHS:
        raise MemoryEndpointMigrationError("explicit unique managed paths required")
    _service(service_receipt, host)
    with _directory(root) as descriptor:
        _read(descriptor, ".agentic_root")
        entries = []
        for relative in sorted(paths):
            data, identity = _read(descriptor, relative)
            offset, disposition = _hook_patch(data) if relative.endswith(".sh") else _toml_patch(data)
            entry = {"path": relative, "identity": identity, "before_sha256": _sha(data),
                     "disposition": disposition}
            if offset is not None:
                changed = _patch(data, offset, OLD_ENDPOINT, NEW_ENDPOINT)
                entry.update({"offset": offset, "before": OLD_ENDPOINT, "after": NEW_ENDPOINT,
                              "after_sha256": _sha(changed)})
            entries.append(entry)
        result = {"schema": "memory-endpoint-migration-plan/v1", "host": host,
                  "machine": platform.node(), "root": str(Path(root).expanduser()),
                  "root_identity": _identity(os.fstat(descriptor)), "runtime": _runtime(),
                  "service_verification": {key: service_receipt[key] for key in (
                      "schema", "status", "service", "endpoint", "host", "machine",
                      "health_status", "verified_at")},
                  "created_at": _now(), "entries": entries}
        result["plan_id"] = _sha(_encoded(result))
        return result


def _validate_plan(plan: dict, root: int, root_path: str | Path, operation: str) -> list[dict]:
    required = {"schema", "host", "machine", "root", "root_identity", "runtime",
                "service_verification", "created_at", "entries", "plan_id"}
    if set(plan) != required or plan["schema"] != "memory-endpoint-migration-plan/v1":
        raise MemoryEndpointMigrationError("unsupported migration plan")
    if not re.fullmatch(r"[0-9a-f]{64}", str(plan["plan_id"])) or _sha(_encoded({
        key: value for key, value in plan.items() if key != "plan_id"
    })) != plan["plan_id"]:
        raise MemoryEndpointMigrationError("plan digest mismatch")
    if (plan["root"], plan["root_identity"], plan["machine"], plan["runtime"]) != (
        str(Path(root_path).expanduser()), _identity(os.fstat(root)), platform.node(), _runtime()
    ):
        raise MemoryEndpointMigrationError("root host or runtime binding changed")
    if not isinstance(plan["host"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", plan["host"]):
        raise MemoryEndpointMigrationError("invalid logical host binding")
    if not isinstance(plan["service_verification"], dict):
        raise MemoryEndpointMigrationError("invalid service verification envelope")
    _service(plan["service_verification"], plan["host"], fresh=operation == "apply")
    _read(root, ".agentic_root")
    entries = plan["entries"]
    if not isinstance(entries, list) or not entries or len(entries) > len(ALLOWED_PATHS):
        raise MemoryEndpointMigrationError("invalid managed entry set")
    seen = set()
    for entry in entries:
        if (not isinstance(entry, dict) or not isinstance(entry.get("path"), str)
                or entry["path"] not in ALLOWED_PATHS or entry["path"] in seen):
            raise MemoryEndpointMigrationError("invalid or duplicate managed entry")
        seen.add(entry["path"])
        if not isinstance(entry.get("disposition"), str) or not _valid_identity(entry.get("identity")):
            raise MemoryEndpointMigrationError("invalid entry envelope")
        keys = {"path", "identity", "before_sha256", "disposition"}
        if entry["disposition"] == "eligible":
            keys |= {"offset", "before", "after", "after_sha256"}
            if (entry.get("before"), entry.get("after")) != (OLD_ENDPOINT, NEW_ENDPOINT):
                raise MemoryEndpointMigrationError("unqualified endpoint patch")
            if type(entry.get("offset")) is not int or not 0 <= entry["offset"] <= MAX_FILE_BYTES - len(OLD_ENDPOINT):
                raise MemoryEndpointMigrationError("invalid scoped patch offset")
            if not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("after_sha256"))):
                raise MemoryEndpointMigrationError("invalid output digest")
        elif entry["disposition"] not in {"managed_server_absent", "stdio_preserved", "current_endpoint",
                                           "custom_url_preserved", "current_or_custom_fallback_preserved"}:
            raise MemoryEndpointMigrationError("unknown entry disposition")
        if set(entry) != keys or set(entry["identity"]) != {"device", "inode", "uid", "gid", "mode"}:
            raise MemoryEndpointMigrationError("invalid entry fields")
        if any(type(value) is not int for value in entry["identity"].values()):
            raise MemoryEndpointMigrationError("invalid entry identity types")
        if not re.fullmatch(r"[0-9a-f]{64}", str(entry["before_sha256"])):
            raise MemoryEndpointMigrationError("invalid entry digest")
    return [entry for entry in entries if entry["disposition"] == "eligible"]


@contextmanager
def _lock(root: int):
    if fcntl is None:
        raise MemoryEndpointMigrationError("cooperative file locking is unavailable")
    descriptor = os.open(LOCK_NAME, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=root)
    try:
        _regular(os.fstat(descriptor))
        if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o600:
            raise MemoryEndpointMigrationError("migration lock permissions invalid")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise MemoryEndpointMigrationError("another migration holds the lock") from None
        yield
    finally:
        os.close(descriptor)


def _atomic(parent: int, name: str, data: bytes, mode: int, gid: int,
            before: tuple[bytes, dict] | None = None, intent=None) -> dict:
    temporary = ".memory-endpoint-" + secrets.token_hex(12)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=parent)
    identity = _identity(os.fstat(descriptor))
    try:
        with os.fdopen(os.dup(descriptor), "wb") as stream:
            stream.write(data)
            stream.flush()
        os.fsync(descriptor)
        if os.fstat(descriptor).st_gid != gid:
            os.fchown(descriptor, -1, gid)
        os.fchmod(descriptor, mode)
        identity = _identity(os.fstat(descriptor))
        if intent is not None:
            intent({"temporary": temporary, "identity": identity, "sha256": _sha(data)})
        if before is not None:
            observed = _read_at(parent, name)
            if observed != before:
                raise MemoryEndpointMigrationError("concurrent file change before replacement")
        os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
        observed, actual_identity = _read_at(parent, name)
        if observed != data or actual_identity != identity:
            raise MemoryEndpointMigrationError("atomic replacement readback mismatch")
        return actual_identity
    finally:
        os.close(descriptor)
        try:
            info = os.stat(temporary, dir_fd=parent, follow_symlinks=False)
            if info.st_ino == identity["inode"] and info.st_dev == identity["device"]:
                os.unlink(temporary, dir_fd=parent)
        except FileNotFoundError:
            pass


@contextmanager
def _journal_directory(root: int):
    try:
        os.mkdir(JOURNAL_DIR, 0o700, dir_fd=root)
    except FileExistsError:
        pass
    descriptor = os.open(JOURNAL_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
    try:
        info = os.fstat(descriptor)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise MemoryEndpointMigrationError("migration journal custody invalid")
        yield descriptor
    finally:
        os.close(descriptor)


def _load_journal(descriptor: int, plan_id: str) -> dict | None:
    try:
        data, identity = _read_at(descriptor, plan_id + ".json", MAX_JSON_BYTES)
    except FileNotFoundError:
        return None
    if identity["mode"] != 0o600:
        raise MemoryEndpointMigrationError("journal file custody invalid")
    value = _json(data)
    if (value.get("schema"), value.get("plan_id")) != ("memory-endpoint-migration-journal/v1", plan_id):
        raise MemoryEndpointMigrationError("journal identity collision")
    if not isinstance(value.get("effects"), dict) or not isinstance(value.get("history"), list):
        raise MemoryEndpointMigrationError("journal structure invalid")
    if set(value) != {"schema", "plan_id", "effects", "history", "pending"}:
        raise MemoryEndpointMigrationError("journal fields invalid")
    for path, effect in value["effects"].items():
        if (path not in ALLOWED_PATHS or not isinstance(effect, dict)
                or set(effect) != {"operation", "identity"}
                or not isinstance(effect["operation"], str) or effect["operation"] not in {"apply", "rollback"}
                or not _valid_identity(effect["identity"])):
            raise MemoryEndpointMigrationError("journal effect invalid")
    return value


def _valid_identity(identity: Any) -> bool:
    return (isinstance(identity, dict)
            and set(identity) == {"device", "inode", "uid", "gid", "mode"}
            and all(type(value) is int and value >= 0 for value in identity.values()))


def _save_journal(descriptor: int, journal: dict) -> None:
    data = _encoded(journal)
    if len(data) > MAX_JSON_BYTES:
        raise MemoryEndpointMigrationError("journal exceeds bounded size; retain it for scoped recovery")
    _atomic(descriptor, journal["plan_id"] + ".json", data, 0o600, os.getegid())


def execute_memory_endpoint(root: str | Path, plan: dict, *, operation: str, apply: bool = False) -> dict:
    if operation not in {"apply", "rollback"}:
        raise MemoryEndpointMigrationError("unsupported migration operation")
    with _directory(root) as descriptor:
        eligible = _validate_plan(plan, descriptor, root, operation)
        # Preflight every selected file before creating a lock/journal or changing a URL.
        observations = {entry["path"]: _read(descriptor, entry["path"]) for entry in plan["entries"]}
        for entry in plan["entries"]:
            data, identity = observations[entry["path"]]
            if any(identity[key] != entry["identity"][key] for key in ("uid", "gid", "mode")):
                raise MemoryEndpointMigrationError("file owner or mode drift")
            accepted = {entry["before_sha256"]}
            if entry["disposition"] == "eligible":
                accepted.add(entry["after_sha256"])
            if _sha(data) not in accepted:
                raise MemoryEndpointMigrationError("selected file content drift")
            if entry["disposition"] != "eligible" and identity != entry["identity"]:
                raise MemoryEndpointMigrationError("preserved file identity drift")
            original = data
            if entry["disposition"] == "eligible":
                original = data if _sha(data) == entry["before_sha256"] else _patch(data, entry["offset"], NEW_ENDPOINT, OLD_ENDPOINT)
                if _sha(_patch(original, entry["offset"], OLD_ENDPOINT, NEW_ENDPOINT)) != entry["after_sha256"]:
                    raise MemoryEndpointMigrationError("planned scoped output digest mismatch")
            locator, disposition = _hook_patch(original) if entry["path"].endswith(".sh") else _toml_patch(original)
            if (locator, disposition) != (entry.get("offset"), entry["disposition"]):
                raise MemoryEndpointMigrationError("plan does not match the actual managed declaration")
        if not apply:
            return {"schema": "memory-endpoint-migration-result/v1", "status": "dry_run",
                    "operation": operation, "plan_id": plan["plan_id"], "eligible": len(eligible),
                    "target_changes": False}
        with _lock(descriptor), _journal_directory(descriptor) as journal_descriptor:
            if any(_read(descriptor, path) != observation for path, observation in observations.items()):
                raise MemoryEndpointMigrationError("selected set changed before locking")
            journal = _load_journal(journal_descriptor, plan["plan_id"])
            if journal is None:
                if operation == "rollback":
                    raise MemoryEndpointMigrationError("rollback requires an actual migration journal")
                journal = {"schema": "memory-endpoint-migration-journal/v1", "plan_id": plan["plan_id"],
                           "effects": {}, "history": [], "pending": None}
                for entry in plan["entries"]:
                    if observations[entry["path"]] != (observations[entry["path"]][0], entry["identity"]) or _sha(observations[entry["path"]][0]) != entry["before_sha256"]:
                        raise MemoryEndpointMigrationError("original file identity changed")
            if not set(journal["effects"]) <= {entry["path"] for entry in eligible}:
                raise MemoryEndpointMigrationError("journal effect set collision")
            pending = journal.get("pending")
            if pending is not None and not isinstance(pending, dict):
                raise MemoryEndpointMigrationError("invalid pending intent envelope")
            if pending is not None:
                if not isinstance(pending, dict) or set(pending) != {"path", "operation", "temporary", "identity", "sha256"}:
                    raise MemoryEndpointMigrationError("invalid pending intent envelope")
                if not isinstance(pending["operation"], str) or pending["operation"] not in {"apply", "rollback"} or not re.fullmatch(r"\.memory-endpoint-[0-9a-f]{24}", str(pending["temporary"])):
                    raise MemoryEndpointMigrationError("invalid pending temporary locator")
                if not _valid_identity(pending["identity"]) or not re.fullmatch(r"[0-9a-f]{64}", str(pending["sha256"])):
                    raise MemoryEndpointMigrationError("invalid pending intent identity")
                path = pending.get("path")
                if path not in {entry["path"] for entry in eligible}:
                    raise MemoryEndpointMigrationError("journal pending path collision")
                data, identity = _read(descriptor, path)
                if _sha(data) == pending["sha256"] and identity == pending["identity"]:
                    journal["effects"][path] = {"operation": pending["operation"], "identity": identity}
                else:
                    with _parent(descriptor, path) as (parent, _):
                        try:
                            temporary, temporary_identity = _read_at(parent, pending["temporary"])
                        except FileNotFoundError:
                            temporary = None
                        if temporary is not None:
                            if temporary_identity != pending["identity"] or _sha(temporary) != pending["sha256"]:
                                raise MemoryEndpointMigrationError("pending temporary custody changed")
                            os.unlink(pending["temporary"], dir_fd=parent)
                journal["history"].append({"operation": "recover_pending", "at": _now()})
                journal["pending"] = None
                _save_journal(journal_descriptor, journal)
            changed = []
            try:
                # Refuse the complete effect set before the first new mutation.
                for entry in eligible:
                    data, identity = _read(descriptor, entry["path"])
                    effect = journal["effects"].get(entry["path"])
                    expected_hash = entry["after_sha256"] if effect and effect["operation"] == "apply" else entry["before_sha256"]
                    expected_identity = effect["identity"] if effect else entry["identity"]
                    if _sha(data) != expected_hash or identity != expected_identity:
                        raise MemoryEndpointMigrationError("effect ownership or current state changed")
                for entry in eligible:
                    effect = journal["effects"].get(entry["path"])
                    already = effect and effect["operation"] == operation
                    if already or (operation == "rollback" and effect is None):
                        continue
                    path = entry["path"]
                    data, identity = _read(descriptor, path)
                    before, after = (entry["before"], entry["after"]) if operation == "apply" else (entry["after"], entry["before"])
                    replacement = _patch(data, entry["offset"], before, after)
                    expected = entry["after_sha256"] if operation == "apply" else entry["before_sha256"]
                    if _sha(replacement) != expected:
                        raise MemoryEndpointMigrationError("inverse scoped patch digest mismatch")
                    def intent(value, path=path):
                        journal["pending"] = {**value, "path": path, "operation": operation}
                        _save_journal(journal_descriptor, journal)
                    with _parent(descriptor, path) as (parent, name):
                        new_identity = _atomic(parent, name, replacement, identity["mode"], identity["gid"],
                                               before=(data, identity), intent=intent)
                    journal["effects"][path] = {"operation": operation, "identity": new_identity}
                    journal["pending"] = None
                    changed.append(path)
                    _save_journal(journal_descriptor, journal)
                status = "completed" if changed else "already_matches"
                journal["history"].append({"operation": operation, "status": status,
                                           "changed": changed, "at": _now()})
                _save_journal(journal_descriptor, journal)
            except (OSError, MemoryEndpointMigrationError):
                journal["history"].append({"operation": operation, "status": "partial_failure",
                                           "changed": changed, "at": _now()})
                _save_journal(journal_descriptor, journal)
                raise MemoryEndpointMigrationError("migration stopped; inspect scoped journal before recovery") from None
            return {"schema": "memory-endpoint-migration-result/v1", "status": status,
                    "operation": operation, "plan_id": plan["plan_id"], "changed": changed,
                    "target_changes": bool(changed), "journal": JOURNAL_DIR + "/" + plan["plan_id"] + ".json"}
