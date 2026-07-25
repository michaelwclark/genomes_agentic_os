"""Install and inspect the versioned Agentic OS object-library projection.

The configured external source repository owns durable definitions.
``<os-root>/lib`` is a disposable, receipt-backed projection of one validated
source revision.  The unified JSON index and per-kind YAML registries are
atomic generated read surfaces, not independent authoring owners.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
from typing import Any, Iterator, Mapping
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import yaml

from .scaffold import expand_path

API_VERSION = "agentic-os-library/v1"
MANIFEST_API_VERSION = "agentic-os-library-object/v1"
REGISTRY_API_VERSION = "agentic-os-library-registry/v1"
LIBRARY_DIR = Path("lib")
REGISTRY_DIR = LIBRARY_DIR / "registry"
UNIFIED_REGISTRY = REGISTRY_DIR / "objects.json"
LOCK_PATH = LIBRARY_DIR / ".registry.lock"
MANIFEST_NAME = "object.yml"
LIBRARY_REPOSITORY_ENV = "AGENTIC_OS_LIBRARY_REPOSITORY"
INSTALL_RECEIPT = Path("runtime/state/library-install.json")
INSTALL_RECEIPT_DIR = Path("runtime/artifacts/library-installs")
INSTALL_BACKUP_DIR = Path("runtime/backups/library")
INSTALL_RECEIPT_BACKUP_DIR = Path("runtime/backups/library-receipts")
INSTALL_JOURNAL = Path("runtime/state/library-install-transaction.json")
INSTALL_LOCK = Path("runtime/locks/library-install.lock")
INSTALL_JOURNAL_API_VERSION = "agentic-os-library-install-transaction/v1"
MANAGED_PLACEHOLDER_MARKER = LIBRARY_DIR / ".managed-placeholder.json"
MANAGED_PLACEHOLDER_API_VERSION = "agentic-os-library-placeholder/v1"
MANAGED_LIBRARY_FALLBACK = Path(
    "harness/shared_factory/05-knowledge/library-bootstrap/lib"
)

OBJECT_KINDS = (
    "automation",
    "command",
    "hook",
    "program",
    "reference",
    "rule",
    "skill",
    "template",
    "toolkit",
    "workflow",
)
PLURAL_BY_KIND = {
    "automation": "automations",
    "command": "commands",
    "hook": "hooks",
    "program": "programs",
    "reference": "references",
    "rule": "rules",
    "skill": "skills",
    "template": "templates",
    "toolkit": "toolkits",
    "workflow": "workflows",
}
OBJECT_STATES = {"active", "disabled", "deprecated", "archived"}
SCOPE_LEVELS = {"root", "domain", "project"}
IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
RUNTIME_PARTS = {
    ".features",
    ".git",
    ".venv",
    "SPECS",
    "__pycache__",
    "artifacts",
    "archive",
    "backups",
    "blockers",
    "build",
    "cache",
    "coverage",
    "logs",
    "node_modules",
    "output",
    "outputs",
    "raw",
    "receipts",
    "reports",
    "run-logs",
    "runs",
    "state",
    "tenant_config_snapshots",
    "temp",
    "tmp",
    "worker-runs",
    "worktrees",
}
IGNORED_FILE_SUFFIXES = {
    ".db",
    ".gif",
    ".jpeg",
    ".jpg",
    ".jsonl",
    ".log",
    ".ndjson",
    ".pdf",
    ".pid",
    ".png",
    ".sqlite",
    ".sqlite3",
    ".webp",
    ".xls",
    ".xlsx",
}
SECRET_FILE_PATTERNS = (
    re.compile(r"^\.env(?:\..+)?$", re.IGNORECASE),
    re.compile(r"(?:^|[-_.])(credential|secret|token|cookie)(?:[-_.]|$)", re.IGNORECASE),
)
CONVENTIONAL_ENTRYPOINTS = {
    "automation": ("automation.md", "README.md"),
    "command": ("command.md",),
    "hook": ("hook.py", "hook.sh", "README.md"),
    "program": ("program.md", "README.md"),
    "reference": ("reference.md", "README.md"),
    "rule": ("rule.md", "README.md"),
    "skill": ("SKILL.md",),
    "template": ("README.md",),
    "toolkit": ("README.md",),
    "workflow": ("workflow.md", "README.md"),
}
LEGACY_KIND_MAP = {
    "automation": "automation",
    "automation_instance": "automation",
    "command": "command",
    "program": "program",
    "program_instance": "program",
    "rule": "rule",
    "skill": "skill",
    "workflow": "workflow",
    "workflow_instance": "workflow",
}
_PROCESS_LOCK = threading.RLock()
_INSTALL_PROCESS_LOCK = threading.RLock()


class LibraryError(ValueError):
    """Raised when the installed object library contract is invalid."""


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _identifier(value: Any, label: str) -> str:
    normalized = str(value or "").strip().lower()
    if not IDENTIFIER_PATTERN.fullmatch(normalized):
        raise LibraryError(
            f"{label} must use lowercase letters, numbers, hyphens, and underscores: {value!r}"
        )
    return normalized


def _kind(value: Any) -> str:
    normalized = _identifier(value, "kind")
    if normalized not in OBJECT_KINDS:
        raise LibraryError(f"unsupported object kind: {normalized}")
    return normalized


def library_root(root: str | Path) -> Path:
    return expand_path(root) / LIBRARY_DIR


def object_relative_path(
    kind: str,
    object_id: str,
    *,
    level: str = "root",
    domain: str | None = None,
    project: str | None = None,
) -> Path:
    kind = _kind(kind)
    object_id = _identifier(object_id, "object id")
    level = _identifier(level, "scope level")
    if level not in SCOPE_LEVELS:
        raise LibraryError(f"unsupported scope level: {level}")
    plural = PLURAL_BY_KIND[kind]
    if level == "root":
        if domain or project:
            raise LibraryError("root-scoped objects cannot declare domain or project")
        return Path(plural) / "root" / object_id
    domain = _identifier(domain, "domain")
    if level == "domain":
        if project:
            raise LibraryError("domain-scoped objects cannot declare project")
        return Path(plural) / "domains" / domain / object_id
    project = _identifier(project, "project")
    return Path(plural) / "domains" / domain / "projects" / project / object_id


def object_path(
    root: str | Path,
    kind: str,
    object_id: str,
    *,
    level: str = "root",
    domain: str | None = None,
    project: str | None = None,
) -> Path:
    return library_root(root) / object_relative_path(
        kind,
        object_id,
        level=level,
        domain=domain,
        project=project,
    )


def canonical_object_id(
    kind: str,
    object_id: str,
    *,
    level: str = "root",
    domain: str | None = None,
    project: str | None = None,
) -> str:
    kind = _kind(kind)
    object_id = _identifier(object_id, "object id")
    level = _identifier(level, "scope level")
    domain = _identifier(domain, "domain") if domain else None
    project = _identifier(project, "project") if project else None
    object_relative_path(
        kind,
        object_id,
        level=level,
        domain=domain,
        project=project,
    )
    if level == "root":
        return f"{kind}:root:{object_id}"
    if level == "domain":
        return f"{kind}:domain:{domain}:{object_id}"
    return f"{kind}:project:{domain}:{project}:{object_id}"


def _safe_relative(value: Any, label: str) -> str:
    path = Path(str(value or "").strip())
    if not str(path) or path.is_absolute() or ".." in path.parts:
        raise LibraryError(f"{label} must be a non-empty object-relative path")
    return path.as_posix()


def _string_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise LibraryError(f"{label} must be a list")
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if not text:
            raise LibraryError(f"{label} cannot contain empty values")
        result.append(text)
    return sorted(set(result))


def normalize_manifest(
    value: Mapping[str, Any],
    *,
    manifest_path: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise LibraryError("object manifest must be a mapping")
    if value.get("api_version") != MANIFEST_API_VERSION:
        raise LibraryError(f"object manifest requires api_version: {MANIFEST_API_VERSION}")
    kind = _kind(value.get("kind"))
    native_id = _identifier(value.get("id"), "object id")
    scope_value = value.get("scope") or {}
    if not isinstance(scope_value, Mapping):
        raise LibraryError("scope must be a mapping")
    level = _identifier(scope_value.get("level") or "root", "scope level")
    domain = scope_value.get("domain")
    project = scope_value.get("project")
    relative = object_relative_path(
        kind,
        native_id,
        level=level,
        domain=str(domain) if domain else None,
        project=str(project) if project else None,
    )
    normalized_scope = {
        "level": level,
        "domain": _identifier(domain, "domain") if domain else None,
        "project": _identifier(project, "project") if project else None,
    }
    status = str(value.get("status") or "active").strip().lower()
    if status not in OBJECT_STATES:
        raise LibraryError(f"unsupported object status: {status}")
    title = str(value.get("title") or native_id.replace("_", " ").replace("-", " ").title()).strip()
    description = str(value.get("description") or "").strip()
    entrypoint = _safe_relative(value.get("entrypoint"), "entrypoint")
    owner = value.get("owner") or {}
    if not isinstance(owner, Mapping):
        raise LibraryError("owner must be a mapping")
    normalized = {
        "api_version": MANIFEST_API_VERSION,
        "object_id": canonical_object_id(
            kind,
            native_id,
            level=level,
            domain=normalized_scope["domain"],
            project=normalized_scope["project"],
        ),
        "kind": kind,
        "id": native_id,
        "title": title,
        "description": description,
        "status": status,
        "scope": normalized_scope,
        "owner": {
            "type": str(owner.get("type") or "operator").strip(),
            "id": str(owner.get("id") or "Genome").strip(),
        },
        "entrypoint": entrypoint,
        "tags": _string_list(value.get("tags"), "tags"),
        "dependencies": _string_list(value.get("dependencies"), "dependencies"),
        "aliases": _string_list(value.get("aliases"), "aliases"),
        "runtime": deepcopy(value.get("runtime") or {}),
        "validation": deepcopy(value.get("validation") or {}),
    }
    if not isinstance(normalized["runtime"], dict):
        raise LibraryError("runtime must be a mapping")
    if not isinstance(normalized["validation"], dict):
        raise LibraryError("validation must be a mapping")
    if manifest_path is not None and root is not None:
        expected = (root / LIBRARY_DIR / relative / MANIFEST_NAME).resolve()
        if manifest_path.resolve() != expected:
            raise LibraryError(
                f"manifest path does not match kind/id/scope: {manifest_path} != {expected}"
            )
        entrypoint_path = manifest_path.parent / entrypoint
        if not entrypoint_path.exists():
            raise LibraryError(f"entrypoint does not exist: {entrypoint_path}")
    return normalized


def _read_manifest(path: Path, root: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise LibraryError(f"could not read manifest {path}: {exc}") from exc
    return normalize_manifest(value, manifest_path=path, root=root)


def _definition_digest(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if any(part in {".git", *RUNTIME_PARTS} for part in relative.parts):
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(b"symlink\0")
            digest.update(os.readlink(path).encode("utf-8"))
        elif path.is_file():
            digest.update(b"file+x\0" if os.access(path, os.X_OK) else b"file\0")
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        else:
            digest.update(b"directory\0")
        digest.update(b"\0")
    return digest.hexdigest()


def discover_objects(root: str | Path) -> list[dict[str, Any]]:
    os_root = expand_path(root)
    lib = os_root / LIBRARY_DIR
    if not lib.exists():
        return []
    objects: list[dict[str, Any]] = []
    seen: dict[str, Path] = {}
    for manifest_path in sorted(lib.rglob(MANIFEST_NAME)):
        if any(part in {".git", "registry", "schemas"} for part in manifest_path.relative_to(lib).parts):
            continue
        item = _read_manifest(manifest_path, os_root)
        object_id = item["object_id"]
        if object_id in seen:
            raise LibraryError(
                f"duplicate object id {object_id}: {seen[object_id]} and {manifest_path}"
            )
        seen[object_id] = manifest_path
        item["path"] = manifest_path.parent.relative_to(os_root).as_posix()
        item["manifest"] = manifest_path.relative_to(os_root).as_posix()
        item["definition_sha256"] = _definition_digest(manifest_path.parent)
        objects.append(item)
    return sorted(objects, key=lambda item: item["object_id"])


def _registry_payload(objects: list[dict[str, Any]], generated_at: str) -> dict[str, Any]:
    serializable = deepcopy(objects)
    content = json.dumps(serializable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "api_version": REGISTRY_API_VERSION,
        "generated_at": generated_at,
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "object_count": len(serializable),
        "objects": serializable,
    }


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def build_registry(root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    objects = discover_objects(os_root)
    existing = _load_json(os_root / UNIFIED_REGISTRY)
    generated_at = _now()
    candidate = _registry_payload(objects, generated_at)
    if existing and existing.get("content_sha256") == candidate["content_sha256"]:
        candidate["generated_at"] = existing.get("generated_at") or generated_at
    return candidate


def _registry_projection_diagnostics(
    root: Path,
    payload: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Compare every generated registry byte-model with the manifest model."""

    diagnostics: list[dict[str, str]] = []
    current = _load_json(root / UNIFIED_REGISTRY)
    if current is None:
        diagnostics.append(
            {
                "severity": "error",
                "code": "registry_missing",
                "path": UNIFIED_REGISTRY.as_posix(),
            }
        )
        return diagnostics
    if current != dict(payload):
        diagnostics.append(
            {
                "severity": "error",
                "code": "registry_stale",
                "path": UNIFIED_REGISTRY.as_posix(),
                "message": "unified registry contents do not match object manifests",
            }
        )

    for kind in OBJECT_KINDS:
        plural = PLURAL_BY_KIND[kind]
        relative = REGISTRY_DIR / f"{plural}.yml"
        path = root / relative
        if not path.is_file():
            diagnostics.append(
                {
                    "severity": "error",
                    "code": "type_registry_missing",
                    "path": relative.as_posix(),
                }
            )
            continue
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            value = None
        expected = {
            "api_version": REGISTRY_API_VERSION,
            "generated_at": payload.get("generated_at"),
            "content_sha256": payload.get("content_sha256"),
            plural: [
                item
                for item in payload.get("objects", [])
                if isinstance(item, Mapping) and item.get("kind") == kind
            ],
        }
        if value != expected:
            diagnostics.append(
                {
                    "severity": "error",
                    "code": "type_registry_stale",
                    "path": relative.as_posix(),
                    "message": f"{plural} registry contents do not match object manifests",
                }
            )
    return diagnostics


def _projection_sha256(path: Path) -> str:
    """Hash the complete installed projection, excluding operational metadata."""

    digest = hashlib.sha256()
    if path.is_symlink():
        digest.update(b"root-symlink\0")
        digest.update(os.readlink(path).encode("utf-8"))
        return digest.hexdigest()
    if not path.is_dir():
        raise LibraryError(f"library projection is not a directory: {path}")
    try:
        paths = sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix())
        for item in paths:
            relative = item.relative_to(path)
            # Git metadata is deliberately removed from installed projections.
            # The registry lock is an operational mutex, not source content.
            if (
                relative.parts[0] == ".git"
                or relative == Path(".registry.lock")
                or relative == MANAGED_PLACEHOLDER_MARKER.relative_to(LIBRARY_DIR)
                or "__pycache__" in relative.parts
                or relative.suffix in {".pyc", ".pyo"}
            ):
                continue
            digest.update(relative.as_posix().encode("utf-8"))
            digest.update(b"\0")
            mode = os.lstat(item).st_mode
            if item.is_symlink():
                digest.update(b"symlink\0")
                digest.update(os.readlink(item).encode("utf-8"))
            elif item.is_file():
                digest.update(b"file+x\0" if mode & 0o111 else b"file\0")
                with item.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
            elif item.is_dir():
                digest.update(b"directory\0")
            else:
                raise LibraryError(
                    f"unsupported file type in library projection: {relative.as_posix()}"
                )
            digest.update(b"\0")
    except OSError as exc:
        raise LibraryError(f"could not hash library projection {path}: {exc}") from exc
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _registry_lock(root: Path) -> Iterator[None]:
    path = root / LOCK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with _PROCESS_LOCK, path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def refresh_registry(root: str | Path, *, dry_run: bool = True) -> dict[str, Any]:
    os_root = expand_path(root)
    payload = build_registry(os_root)
    current = _load_json(os_root / UNIFIED_REGISTRY)
    changed = current != payload
    result = {
        "api_version": API_VERSION,
        "action": "library.refresh",
        "status": "unchanged" if not changed else ("planned" if dry_run else "refreshed"),
        "dry_run": dry_run,
        "registry": UNIFIED_REGISTRY.as_posix(),
        "object_count": payload["object_count"],
        "content_sha256": payload["content_sha256"],
        "changed": changed,
    }
    if dry_run or not changed:
        return result
    with _registry_lock(os_root):
        payload = build_registry(os_root)
        _atomic_write(
            os_root / UNIFIED_REGISTRY,
            (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
        for kind in OBJECT_KINDS:
            plural = PLURAL_BY_KIND[kind]
            kind_payload = {
                "api_version": REGISTRY_API_VERSION,
                "generated_at": payload["generated_at"],
                "content_sha256": payload["content_sha256"],
                plural: [item for item in payload["objects"] if item["kind"] == kind],
            }
            _atomic_write(
                os_root / REGISTRY_DIR / f"{plural}.yml",
                yaml.safe_dump(kind_payload, sort_keys=False).encode("utf-8"),
            )
    result["readback_ok"] = not _registry_projection_diagnostics(os_root, payload)
    if not result["readback_ok"]:
        raise LibraryError("library registry readback did not match generated content")
    return result


def query_objects(
    root: str | Path,
    *,
    kind: str | None = None,
    level: str | None = None,
    domain: str | None = None,
    project: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    os_root = expand_path(root)
    payload = _load_json(os_root / UNIFIED_REGISTRY) or build_registry(os_root)
    objects = payload.get("objects") or []
    if not isinstance(objects, list):
        raise LibraryError("library registry objects must be a list")
    normalized_kind = _kind(kind) if kind else None
    normalized_level = _identifier(level, "scope level") if level else None
    normalized_domain = _identifier(domain, "domain") if domain else None
    normalized_project = _identifier(project, "project") if project else None
    return [
        deepcopy(item)
        for item in objects
        if isinstance(item, dict)
        and (not normalized_kind or item.get("kind") == normalized_kind)
        and (not normalized_level or (item.get("scope") or {}).get("level") == normalized_level)
        and (not normalized_domain or (item.get("scope") or {}).get("domain") == normalized_domain)
        and (not normalized_project or (item.get("scope") or {}).get("project") == normalized_project)
        and (not status or item.get("status") == status)
    ]


def get_object(root: str | Path, object_id: str) -> dict[str, Any]:
    matches = [item for item in query_objects(root) if item.get("object_id") == object_id]
    if not matches:
        raise LibraryError(f"library object not found: {object_id}")
    if len(matches) > 1:
        raise LibraryError(f"library object is ambiguous: {object_id}")
    return matches[0]


def _default_entrypoint(kind: str) -> str:
    return CONVENTIONAL_ENTRYPOINTS[_kind(kind)][0]


def _entrypoint_scaffold(kind: str, object_id: str, title: str, description: str) -> str:
    if kind == "skill":
        return (
            f"---\nname: {object_id}\ndescription: {description or title}\n---\n\n"
            f"# {title}\n\n{description}\n"
        )
    return f"# {title}\n\n{description}\n"


def create_object(
    root: str | Path,
    kind: str,
    object_id: str,
    *,
    level: str = "root",
    domain: str | None = None,
    project: str | None = None,
    title: str | None = None,
    description: str = "",
    entrypoint: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    os_root = expand_path(root)
    kind = _kind(kind)
    object_id = _identifier(object_id, "object id")
    target = object_path(
        os_root,
        kind,
        object_id,
        level=level,
        domain=domain,
        project=project,
    )
    relative_target = target.relative_to(os_root)
    entrypoint = _safe_relative(entrypoint or _default_entrypoint(kind), "entrypoint")
    display_title = str(title or object_id.replace("_", " ").replace("-", " ").title()).strip()
    manifest = {
        "api_version": MANIFEST_API_VERSION,
        "kind": kind,
        "id": object_id,
        "title": display_title,
        "description": str(description or "").strip(),
        "status": "active",
        "scope": {"level": level, "domain": domain, "project": project},
        "owner": {"type": "operator", "id": "Genome"},
        "entrypoint": entrypoint,
        "tags": [kind],
        "dependencies": [],
        "aliases": [],
        "runtime": {
            "root": (
                Path("runtime/objects")
                / PLURAL_BY_KIND[kind]
                / canonical_object_id(
                    kind,
                    object_id,
                    level=level,
                    domain=domain,
                    project=project,
                ).replace(":", "/")
            ).as_posix()
        },
        "validation": {"commands": []},
    }
    normalized = normalize_manifest(manifest)
    result = {
        "api_version": API_VERSION,
        "action": "library.create",
        "status": "exists" if (target / MANIFEST_NAME).exists() else ("planned" if dry_run else "created"),
        "dry_run": dry_run,
        "object": {**normalized, "path": relative_target.as_posix()},
    }
    if result["status"] == "exists" or dry_run:
        return result
    target.mkdir(parents=True, exist_ok=False)
    entrypoint_path = target / entrypoint
    entrypoint_path.parent.mkdir(parents=True, exist_ok=True)
    entrypoint_path.write_text(
        _entrypoint_scaffold(kind, object_id, display_title, description),
        encoding="utf-8",
    )
    (target / MANIFEST_NAME).write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )
    normalize_manifest(manifest, manifest_path=target / MANIFEST_NAME, root=os_root)
    result["registry"] = refresh_registry(os_root, dry_run=False)
    return result


def library_doctor(root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    diagnostics: list[dict[str, str]] = []
    lib = os_root / LIBRARY_DIR
    if lib.is_symlink() or not lib.is_dir():
        diagnostics.append(
            {"severity": "error", "code": "library_missing", "path": LIBRARY_DIR.as_posix()}
        )
        return {
            "api_version": API_VERSION,
            "status": "failed",
            "object_count": 0,
            "diagnostics": diagnostics,
        }
    try:
        payload = build_registry(os_root)
    except LibraryError as exc:
        diagnostics.append(
            {"severity": "error", "code": "manifest_invalid", "message": str(exc)}
        )
        return {
            "api_version": API_VERSION,
            "status": "failed",
            "object_count": 0,
            "diagnostics": diagnostics,
        }
    try:
        projection_sha256 = _projection_sha256(lib)
    except LibraryError as exc:
        projection_sha256 = None
        diagnostics.append(
            {
                "severity": "error",
                "code": "projection_unreadable",
                "path": LIBRARY_DIR.as_posix(),
                "message": str(exc),
            }
        )
    diagnostics.extend(_registry_projection_diagnostics(os_root, payload))

    receipt_path = os_root / INSTALL_RECEIPT
    install_receipt = _load_json(receipt_path)
    if receipt_path.is_file() and install_receipt is None:
        diagnostics.append(
            {
                "severity": "error",
                "code": "install_receipt_invalid",
                "path": INSTALL_RECEIPT.as_posix(),
            }
        )
    elif install_receipt and install_receipt.get("status") == "installed":
        if (lib / ".git").exists() or (lib / ".git").is_symlink():
            diagnostics.append(
                {
                    "severity": "error",
                    "code": "installed_git_metadata_present",
                    "path": "lib/.git",
                    "message": "installed projections must not regain Git metadata",
                }
            )
        receipt_matches = bool(
            projection_sha256
            and install_receipt.get("content_sha256") == payload.get("content_sha256")
            and install_receipt.get("object_count") == payload.get("object_count")
            and install_receipt.get("projection_sha256") == projection_sha256
        )
        if not receipt_matches:
            diagnostics.append(
                {
                    "severity": "error",
                    "code": "installed_projection_drift",
                    "path": LIBRARY_DIR.as_posix(),
                    "message": "installed projection does not match its install receipt",
                }
            )
    elif not (lib / ".git").exists():
        diagnostics.append(
            {
                "severity": "warning",
                "code": "git_missing",
                "path": "lib/.git",
                "message": "installed libraries require a matching external install receipt",
            }
        )
    return {
        "api_version": API_VERSION,
        "status": "failed"
        if any(item["severity"] == "error" for item in diagnostics)
        else ("warning" if diagnostics else "healthy"),
        "object_count": payload["object_count"],
        "content_sha256": payload["content_sha256"],
        "projection_sha256": projection_sha256,
        "diagnostics": diagnostics,
    }


def _safe_repository(value: str) -> str:
    """Return a receipt-safe repository location without URL credentials."""

    if "://" not in value:
        scp_remote = re.fullmatch(
            r"(?P<userinfo>[^/@]+)@(?P<host>\[[^\]]+\]|[^/:]+):(?P<path>.+)",
            value,
        )
        if scp_remote:
            return f"{scp_remote.group('host')}:{scp_remote.group('path')}"
        return value
    parsed = urlsplit(value)
    hostname = parsed.hostname or ""
    if parsed.port:
        hostname = f"{hostname}:{parsed.port}"
    return urlunsplit((parsed.scheme, hostname, parsed.path, "", ""))


def _git_output(*args: str, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )
    return completed.stdout.strip()


def _installed_git_state(lib: Path) -> dict[str, Any]:
    if not (lib / ".git").exists():
        return {"present": False, "dirty_count": 0, "linked_worktrees": []}
    status = _git_output("-C", str(lib), "status", "--porcelain=v1")
    worktree_output = _git_output("-C", str(lib), "worktree", "list", "--porcelain")
    worktrees = [
        line.removeprefix("worktree ")
        for line in worktree_output.splitlines()
        if line.startswith("worktree ")
    ]
    linked = [
        path
        for path in worktrees
        if Path(path).expanduser().resolve() != lib.resolve()
    ]
    return {
        "present": True,
        "dirty_count": len([line for line in status.splitlines() if line]),
        "linked_worktrees": linked,
    }


def _remove_git_metadata(path: Path) -> None:
    git = path / ".git"
    if git.is_dir():
        shutil.rmtree(git)
    elif git.exists() or git.is_symlink():
        git.unlink()


@contextmanager
def _install_lock(root: Path) -> Iterator[None]:
    path = root / INSTALL_LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    with _INSTALL_PROCESS_LOCK, path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def _atomic_unlink(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    path.unlink()
    _fsync_directory(path.parent)


def _write_install_journal(root: Path, journal: Mapping[str, Any]) -> None:
    _atomic_write(
        root / INSTALL_JOURNAL,
        (json.dumps(dict(journal), indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


def _load_install_journal(root: Path) -> dict[str, Any] | None:
    path = root / INSTALL_JOURNAL
    if not path.exists():
        return None
    journal = _load_json(path)
    if journal is None or journal.get("api_version") != INSTALL_JOURNAL_API_VERSION:
        raise LibraryError(
            f"invalid interrupted library install journal: {INSTALL_JOURNAL.as_posix()}"
        )
    return journal


def _journal_path(
    root: Path,
    journal: Mapping[str, Any],
    key: str,
    parent: Path,
    *,
    optional: bool = False,
) -> Path | None:
    raw = journal.get(key)
    if raw is None and optional:
        return None
    relative = Path(str(raw or ""))
    if not str(relative) or relative.is_absolute() or ".." in relative.parts:
        raise LibraryError(f"invalid {key} in interrupted library install journal")
    candidate = (root / relative).resolve()
    allowed = (root / parent).resolve()
    try:
        candidate.relative_to(allowed)
    except ValueError as exc:
        raise LibraryError(f"unsafe {key} in interrupted library install journal") from exc
    return candidate


def _finish_install_transaction(root: Path, journal: Mapping[str, Any]) -> None:
    staging_root = _journal_path(root, journal, "staging_root", Path("runtime/tmp"))
    if staging_root is not None:
        _remove_path(staging_root)
    _atomic_unlink(root / INSTALL_JOURNAL)


def _recover_install_transaction(root: Path) -> dict[str, Any] | None:
    """Finalize a committed install or restore the exact pre-swap state."""

    journal = _load_install_journal(root)
    if journal is None:
        return None
    target = root / LIBRARY_DIR
    backup = _journal_path(root, journal, "backup", INSTALL_BACKUP_DIR)
    staging_root = _journal_path(root, journal, "staging_root", Path("runtime/tmp"))
    previous_receipt_backup = _journal_path(
        root,
        journal,
        "previous_receipt_backup",
        INSTALL_RECEIPT_BACKUP_DIR,
        optional=True,
    )
    success_receipt = _journal_path(
        root,
        journal,
        "success_receipt",
        INSTALL_RECEIPT_DIR,
    )
    phase = str(journal.get("phase") or "")
    if phase == "committed" and verify_library_install(root).get("status") == "verified":
        _finish_install_transaction(root, journal)
        return {"status": "finalized", "run_id": journal.get("run_id")}

    had_previous_target = journal.get("had_previous_target") is True
    if backup is not None and (backup.exists() or backup.is_symlink()):
        _remove_path(target)
        backup.replace(target)
        _fsync_directory(target.parent)
        _fsync_directory(backup.parent)
    elif not had_previous_target:
        _remove_path(target)
    elif not target.exists() and not target.is_symlink():
        raise LibraryError(
            "interrupted library install cannot restore its missing previous projection"
        )

    receipt_path = root / INSTALL_RECEIPT
    if journal.get("had_previous_receipt") is True:
        if previous_receipt_backup is None or not previous_receipt_backup.is_file():
            raise LibraryError(
                "interrupted library install is missing its previous receipt backup"
            )
        _atomic_write(receipt_path, previous_receipt_backup.read_bytes())
    else:
        _atomic_unlink(receipt_path)

    previous_projection_sha256 = journal.get("previous_projection_sha256")
    if had_previous_target and previous_projection_sha256:
        restored_sha256 = _projection_sha256(target)
        if restored_sha256 != previous_projection_sha256:
            raise LibraryError(
                "interrupted library install restored a different previous projection"
            )

    if success_receipt is not None and journal.get("success_receipt_created") is True:
        _remove_path(success_receipt)
    if staging_root is not None:
        _remove_path(staging_root)
    if previous_receipt_backup is not None:
        _remove_path(previous_receipt_backup)
    _atomic_unlink(root / INSTALL_JOURNAL)
    return {"status": "rolled_back", "run_id": journal.get("run_id")}


def _installed_projection_state(root: Path, target: Path) -> dict[str, Any]:
    present = target.exists() or target.is_symlink()
    if target.is_symlink():
        git_state = {"present": False, "dirty_count": 0, "linked_worktrees": []}
    else:
        git_state = _installed_git_state(target) if present else {
            "present": False,
            "dirty_count": 0,
            "linked_worktrees": [],
        }
    projection_sha256: str | None = None
    projection_error: str | None = None
    if present:
        try:
            projection_sha256 = _projection_sha256(target)
        except LibraryError as exc:
            projection_error = str(exc)
    receipt = _load_json(root / INSTALL_RECEIPT)
    receipt_projection_sha256 = (
        receipt.get("projection_sha256")
        if receipt and receipt.get("status") == "installed"
        else None
    )
    unexpected_git = bool(receipt_projection_sha256 and git_state["present"])
    receipt_backed = bool(
        projection_sha256
        and receipt_projection_sha256 == projection_sha256
        and not unexpected_git
    )
    marker = _load_json(root / MANAGED_PLACEHOLDER_MARKER)
    marker_backed = bool(
        marker
        and marker.get("api_version") == MANAGED_PLACEHOLDER_API_VERSION
        and marker.get("projection_sha256") == projection_sha256
        and not git_state["present"]
        and not receipt_projection_sha256
    )
    legacy_managed_placeholder = bool(
        present
        and not marker
        and not git_state["present"]
        and not receipt_projection_sha256
        and _looks_like_legacy_managed_placeholder(root, projection_sha256)
    )
    managed_placeholder = marker_backed or legacy_managed_placeholder
    projection_dirty = bool(
        present
        and (
            projection_error
            or unexpected_git
            or (
                not git_state["present"]
                and not receipt_backed
                and not managed_placeholder
            )
        )
    )
    return {
        **git_state,
        "projection_sha256": projection_sha256,
        "receipt_projection_sha256": receipt_projection_sha256,
        "receipt_backed": receipt_backed,
        "managed_placeholder": managed_placeholder,
        "projection_dirty": projection_dirty,
        "projection_error": projection_error,
    }


def _looks_like_legacy_managed_placeholder(
    root: Path,
    projection_sha256: str | None,
) -> bool:
    """Recognize only an exact package fallback emitted before marker support."""

    lib = root / LIBRARY_DIR
    fallback = root / MANAGED_LIBRARY_FALLBACK
    if (
        not lib.is_dir()
        or (lib / ".git").exists()
        or not fallback.is_dir()
        or not projection_sha256
    ):
        return False
    try:
        fallback_sha256 = _projection_sha256(fallback)
    except LibraryError:
        return False
    return fallback_sha256 == projection_sha256


def verify_library_install(root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    receipt = _load_json(os_root / INSTALL_RECEIPT)
    doctor = library_doctor(os_root)
    matches = bool(
        receipt
        and receipt.get("status") == "installed"
        and receipt.get("content_sha256") == doctor.get("content_sha256")
        and receipt.get("object_count") == doctor.get("object_count")
        and receipt.get("projection_sha256") == doctor.get("projection_sha256")
        and doctor.get("status") == "healthy"
    )
    return {
        "api_version": API_VERSION,
        "action": "library.verify-install",
        "status": "verified" if matches else "failed",
        "receipt": INSTALL_RECEIPT.as_posix(),
        "source_revision": receipt.get("source_revision") if receipt else None,
        "object_count": doctor.get("object_count", 0),
        "content_sha256": doctor.get("content_sha256"),
        "projection_sha256": doctor.get("projection_sha256"),
        "doctor_status": doctor.get("status"),
        "diagnostics": doctor.get("diagnostics", []),
    }


def install_library(
    root: str | Path,
    *,
    repository: str | None = None,
    ref: str = "main",
    replace_dirty: bool = False,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Install an exact validated source revision as a disposable projection."""

    os_root = expand_path(root)
    repository = str(repository or os.environ.get(LIBRARY_REPOSITORY_ENV) or "").strip()
    if dry_run:
        if (os_root / INSTALL_JOURNAL).exists():
            return {
                "api_version": API_VERSION,
                "action": "library.install",
                "status": "blocked",
                "dry_run": True,
                "repository": _safe_repository(repository) if repository else None,
                "ref": ref,
                "target": LIBRARY_DIR.as_posix(),
                "replace_dirty": replace_dirty,
                "receipt": INSTALL_RECEIPT.as_posix(),
                "blocker": (
                    "an interrupted library install requires rollback or finalization; "
                    "rerun with --apply under the install lock"
                ),
            }
        return _install_library_locked(
            os_root,
            repository=repository,
            ref=ref,
            replace_dirty=replace_dirty,
            dry_run=True,
            recovery=None,
        )
    with _install_lock(os_root):
        recovery = _recover_install_transaction(os_root)
        return _install_library_locked(
            os_root,
            repository=repository,
            ref=ref,
            replace_dirty=replace_dirty,
            dry_run=False,
            recovery=recovery,
        )


def _install_library_locked(
    os_root: Path,
    *,
    repository: str,
    ref: str,
    replace_dirty: bool,
    dry_run: bool,
    recovery: Mapping[str, Any] | None,
) -> dict[str, Any]:
    target = os_root / LIBRARY_DIR
    installed_state = _installed_projection_state(os_root, target)
    plan = {
        "api_version": API_VERSION,
        "action": "library.install",
        "status": "planned",
        "dry_run": dry_run,
        "repository": _safe_repository(repository) if repository else None,
        "ref": ref,
        "target": LIBRARY_DIR.as_posix(),
        "existing": installed_state,
        "replace_dirty": replace_dirty,
        "receipt": INSTALL_RECEIPT.as_posix(),
        "recovery": dict(recovery) if recovery else None,
    }
    if not repository:
        plan["status"] = "blocked"
        plan["blocker"] = (
            "library source repository is required; pass --repository or set "
            f"{LIBRARY_REPOSITORY_ENV}"
        )
        return plan
    if installed_state["linked_worktrees"]:
        plan["status"] = "blocked"
        plan["blocker"] = (
            "installed lib owns linked Git worktrees; re-home or close them before replacement"
        )
        return plan
    if installed_state["dirty_count"] and not replace_dirty:
        plan["status"] = "blocked"
        plan["blocker"] = (
            "installed lib has uncommitted changes; capture them in source or use "
            "--replace-dirty only for a receipt-backed migration"
        )
        return plan
    if installed_state["projection_dirty"] and not replace_dirty:
        plan["status"] = "blocked"
        plan["blocker"] = (
            "installed lib has uncaptured changes or does not match its install receipt; "
            "capture them in source or use --replace-dirty only for a receipt-backed migration"
        )
        return plan
    if dry_run:
        return plan

    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    staging_root = os_root / "runtime" / "tmp" / f"library-install-{run_id}"
    staged_lib = staging_root / LIBRARY_DIR
    backup = os_root / INSTALL_BACKUP_DIR / run_id
    previous_receipt_backup = os_root / INSTALL_RECEIPT_BACKUP_DIR / f"{run_id}.json"
    success_receipt = os_root / INSTALL_RECEIPT_DIR / f"{run_id}.json"
    staging_root.parent.mkdir(parents=True, exist_ok=True)
    staging_root.mkdir(parents=True, exist_ok=False)
    backup.parent.mkdir(parents=True, exist_ok=True)
    receipt_path = os_root / INSTALL_RECEIPT
    had_previous_receipt = receipt_path.is_file()
    previous_receipt_bytes = receipt_path.read_bytes() if had_previous_receipt else None
    if had_previous_receipt:
        assert previous_receipt_bytes is not None
        _atomic_write(previous_receipt_backup, previous_receipt_bytes)
    previous_payload: dict[str, Any] | None = None
    if target.is_dir():
        try:
            previous_payload = build_registry(os_root)
        except LibraryError:
            previous_payload = None
    had_previous_target = target.exists() or target.is_symlink()
    journal: dict[str, Any] = {
        "api_version": INSTALL_JOURNAL_API_VERSION,
        "action": "library.install-transaction",
        "run_id": run_id,
        "phase": "staging",
        "repository": _safe_repository(repository),
        "requested_ref": ref,
        "staging_root": staging_root.relative_to(os_root).as_posix(),
        "backup": backup.relative_to(os_root).as_posix(),
        "previous_receipt_backup": (
            previous_receipt_backup.relative_to(os_root).as_posix()
            if had_previous_receipt
            else None
        ),
        "success_receipt": success_receipt.relative_to(os_root).as_posix(),
        "success_receipt_created": True,
        "had_previous_target": had_previous_target,
        "had_previous_receipt": had_previous_receipt,
        "previous_projection_sha256": installed_state.get("projection_sha256"),
    }
    try:
        _write_install_journal(os_root, journal)
        _git_output("clone", "--filter=blob:none", repository, str(staged_lib))
        try:
            source_revision = _git_output(
                "-C",
                str(staged_lib),
                "rev-parse",
                "--verify",
                f"{ref}^{{commit}}",
            )
        except subprocess.CalledProcessError:
            source_revision = _git_output(
                "-C",
                str(staged_lib),
                "rev-parse",
                "--verify",
                f"origin/{ref}^{{commit}}",
            )
        _git_output("-C", str(staged_lib), "checkout", "--detach", source_revision)
        source_status = _git_output(
            "-C",
            str(staged_lib),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignored=matching",
        )
        if source_status:
            raise LibraryError("staged library checkout is unexpectedly dirty")
        staged_doctor = library_doctor(staging_root)
        if staged_doctor["status"] != "healthy":
            raise LibraryError(
                "staged library failed doctor: "
                + json.dumps(staged_doctor.get("diagnostics", []), sort_keys=True)
            )
        validator = staged_lib / "scripts" / "validate_library.py"
        if validator.is_file():
            validation = subprocess.run(
                [sys.executable, str(validator), "--repo", str(staged_lib)],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if validation.returncode:
                raise LibraryError("staged standalone library validation failed")
        # Standalone validators may write declared ignored build evidence such
        # as dist/ receipts.  The install projection must still be the clean
        # Git revision, so discard ignored validator output inside this fresh
        # staging clone before the exact cleanliness/readback check.  Tracked
        # changes and non-ignored untracked files remain visible and blocking.
        _git_output("-C", str(staged_lib), "clean", "-fdX")
        source_status = _git_output(
            "-C",
            str(staged_lib),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignored=matching",
        )
        if source_status:
            raise LibraryError("staged library validation changed the source checkout")
        _remove_git_metadata(staged_lib)
        staged_projection_sha256 = _projection_sha256(staged_lib)
        journal["phase"] = "validated"
        journal["source_revision"] = source_revision
        journal["new_projection_sha256"] = staged_projection_sha256
        _write_install_journal(os_root, journal)

        journal["phase"] = "replacing"
        _write_install_journal(os_root, journal)
        if had_previous_target:
            target.replace(backup)
            _fsync_directory(target.parent)
            _fsync_directory(backup.parent)
        staged_lib.replace(target)
        _fsync_directory(target.parent)
        _fsync_directory(staging_root)
        journal["phase"] = "swapped"
        _write_install_journal(os_root, journal)

        readback = build_registry(os_root)
        if (
            readback.get("content_sha256") != staged_doctor.get("content_sha256")
            or readback.get("object_count") != staged_doctor.get("object_count")
            or _registry_projection_diagnostics(os_root, readback)
            or _projection_sha256(target) != staged_projection_sha256
        ):
            raise LibraryError("installed library readback differs from staged validation")
        receipt = {
            "api_version": API_VERSION,
            "action": "library.install",
            "status": "installed",
            "installed_at": _now(),
            "repository": _safe_repository(repository),
            "requested_ref": ref,
            "run_id": run_id,
            "source_revision": source_revision,
            "object_count": readback["object_count"],
            "content_sha256": readback["content_sha256"],
            "projection_sha256": staged_projection_sha256,
            "replaced_git_dirty_count": installed_state["dirty_count"],
            "replaced_projection_drift": installed_state["projection_dirty"],
            "previous_content_sha256": (
                previous_payload.get("content_sha256") if previous_payload else None
            ),
            "previous_projection_sha256": installed_state.get("projection_sha256"),
            "rollback_path": (
                backup.relative_to(os_root).as_posix() if had_previous_target else None
            ),
            "rollback_receipt": (
                previous_receipt_backup.relative_to(os_root).as_posix()
                if had_previous_target and previous_receipt_bytes is not None
                else None
            ),
            "rollback_receipt_sha256": (
                hashlib.sha256(previous_receipt_bytes).hexdigest()
                if had_previous_target and previous_receipt_bytes is not None
                else None
            ),
            "rollback_available": bool(
                had_previous_target and previous_receipt_bytes is not None
            ),
            "success_receipt": success_receipt.relative_to(os_root).as_posix(),
        }
        receipt_bytes = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
        _atomic_write(os_root / INSTALL_RECEIPT, receipt_bytes)
        journal["phase"] = "receipt_written"
        _write_install_journal(os_root, journal)
        verification = verify_library_install(os_root)
        if verification["status"] != "verified":
            raise LibraryError("installed library did not pass receipt-backed verification")
        journal["phase"] = "verified"
        _write_install_journal(os_root, journal)
        _atomic_write(success_receipt, receipt_bytes)
        journal["phase"] = "committed"
        _write_install_journal(os_root, journal)
        _finish_install_transaction(os_root, journal)
        return {
            **plan,
            **receipt,
            "dry_run": False,
            "verification": verification,
        }
    except BaseException as exc:
        try:
            if (os_root / INSTALL_JOURNAL).exists():
                _recover_install_transaction(os_root)
            else:
                _remove_path(staging_root)
                _remove_path(previous_receipt_backup)
        except Exception as recovery_exc:
            raise LibraryError(
                "library install failed and automatic recovery could not complete; "
                f"inspect {INSTALL_JOURNAL.as_posix()}"
            ) from recovery_exc
        if isinstance(exc, subprocess.SubprocessError):
            raise LibraryError(
                "library source command failed for " + _safe_repository(repository)
            ) from None
        raise


def _rollback_candidate(root: Path) -> dict[str, Any]:
    current_receipt = _load_json(root / INSTALL_RECEIPT)
    if not current_receipt or current_receipt.get("status") != "installed":
        raise LibraryError("current installed library receipt is missing or invalid")
    if verify_library_install(root).get("status") != "verified":
        raise LibraryError("current installed projection is not verified; rollback is blocked")
    if current_receipt.get("rollback_available") is not True:
        raise LibraryError("current install has no receipt-backed rollback generation")
    backup = _journal_path(root, current_receipt, "rollback_path", INSTALL_BACKUP_DIR)
    rollback_receipt_path = _journal_path(
        root,
        current_receipt,
        "rollback_receipt",
        INSTALL_RECEIPT_BACKUP_DIR,
    )
    if backup is None or backup.is_symlink() or not backup.is_dir():
        raise LibraryError("retained rollback projection is missing or invalid")
    if rollback_receipt_path is None or not rollback_receipt_path.is_file():
        raise LibraryError("retained rollback receipt is missing")
    rollback_receipt_bytes = rollback_receipt_path.read_bytes()
    if hashlib.sha256(rollback_receipt_bytes).hexdigest() != current_receipt.get(
        "rollback_receipt_sha256"
    ):
        raise LibraryError("retained rollback receipt hash does not match current receipt")
    try:
        rollback_receipt = json.loads(rollback_receipt_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LibraryError("retained rollback receipt is invalid JSON") from exc
    if not isinstance(rollback_receipt, dict) or rollback_receipt.get("status") != "installed":
        raise LibraryError("retained rollback receipt is not an installed receipt")
    backup_sha256 = _projection_sha256(backup)
    expected_sha256 = current_receipt.get("previous_projection_sha256")
    if (
        not expected_sha256
        or backup_sha256 != expected_sha256
        or rollback_receipt.get("projection_sha256") != expected_sha256
    ):
        raise LibraryError("retained rollback projection does not match its prior receipt")
    historical_receipt = _journal_path(
        root,
        rollback_receipt,
        "success_receipt",
        INSTALL_RECEIPT_DIR,
    )
    if historical_receipt is None or not historical_receipt.is_file():
        raise LibraryError("prior generation historical success receipt is missing")
    if historical_receipt.read_bytes() != rollback_receipt_bytes:
        raise LibraryError("retained rollback receipt differs from historical success receipt")
    return {
        "current_receipt": current_receipt,
        "backup": backup,
        "rollback_receipt_path": rollback_receipt_path,
        "rollback_receipt": rollback_receipt,
        "rollback_receipt_bytes": rollback_receipt_bytes,
        "historical_receipt": historical_receipt,
        "projection_sha256": backup_sha256,
    }


def rollback_library_install(
    root: str | Path,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Restore the retained prior projection and its exact verified receipt."""

    os_root = expand_path(root)
    base = {
        "api_version": API_VERSION,
        "action": "library.rollback-install",
        "status": "planned",
        "dry_run": dry_run,
        "target": LIBRARY_DIR.as_posix(),
        "receipt": INSTALL_RECEIPT.as_posix(),
    }
    if dry_run and (os_root / INSTALL_JOURNAL).exists():
        return {
            **base,
            "status": "blocked",
            "blocker": "an interrupted library transaction must be recovered before rollback",
        }

    def planned(candidate: Mapping[str, Any], recovery: Mapping[str, Any] | None) -> dict[str, Any]:
        rollback_receipt = candidate["rollback_receipt"]
        return {
            **base,
            "recovery": dict(recovery) if recovery else None,
            "rollback_path": candidate["backup"].relative_to(os_root).as_posix(),
            "rollback_receipt": candidate["rollback_receipt_path"]
            .relative_to(os_root)
            .as_posix(),
            "source_revision": rollback_receipt.get("source_revision"),
            "object_count": rollback_receipt.get("object_count"),
            "content_sha256": rollback_receipt.get("content_sha256"),
            "projection_sha256": candidate["projection_sha256"],
        }

    if dry_run:
        try:
            return planned(_rollback_candidate(os_root), None)
        except LibraryError as exc:
            return {**base, "status": "blocked", "blocker": str(exc)}

    with _install_lock(os_root):
        recovery = _recover_install_transaction(os_root)
        try:
            candidate = _rollback_candidate(os_root)
        except LibraryError as exc:
            return {
                **base,
                "status": "blocked",
                "dry_run": False,
                "recovery": recovery,
                "blocker": str(exc),
            }
        plan = planned(candidate, recovery)
        run_id = f"rollback-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
        staging_root = os_root / "runtime" / "tmp" / f"library-install-{run_id}"
        staged_lib = staging_root / LIBRARY_DIR
        replaced_backup = os_root / INSTALL_BACKUP_DIR / run_id
        replaced_receipt = os_root / INSTALL_RECEIPT_BACKUP_DIR / f"{run_id}.json"
        current_receipt_bytes = (os_root / INSTALL_RECEIPT).read_bytes()
        staging_root.parent.mkdir(parents=True, exist_ok=True)
        staging_root.mkdir(parents=True, exist_ok=False)
        shutil.copytree(candidate["backup"], staged_lib, symlinks=True)
        if _projection_sha256(staged_lib) != candidate["projection_sha256"]:
            _remove_path(staging_root)
            raise LibraryError("staged rollback projection changed during copy")
        _atomic_write(replaced_receipt, current_receipt_bytes)
        journal: dict[str, Any] = {
            "api_version": INSTALL_JOURNAL_API_VERSION,
            "action": "library.rollback-install-transaction",
            "run_id": run_id,
            "phase": "validated",
            "staging_root": staging_root.relative_to(os_root).as_posix(),
            "backup": replaced_backup.relative_to(os_root).as_posix(),
            "previous_receipt_backup": replaced_receipt.relative_to(os_root).as_posix(),
            "success_receipt": candidate["historical_receipt"]
            .relative_to(os_root)
            .as_posix(),
            "success_receipt_created": False,
            "had_previous_target": True,
            "had_previous_receipt": True,
            "previous_projection_sha256": candidate["current_receipt"].get(
                "projection_sha256"
            ),
            "new_projection_sha256": candidate["projection_sha256"],
        }
        try:
            _write_install_journal(os_root, journal)
            journal["phase"] = "replacing"
            _write_install_journal(os_root, journal)
            (os_root / LIBRARY_DIR).replace(replaced_backup)
            _fsync_directory(os_root)
            _fsync_directory(replaced_backup.parent)
            staged_lib.replace(os_root / LIBRARY_DIR)
            _fsync_directory(os_root)
            _fsync_directory(staging_root)
            journal["phase"] = "swapped"
            _write_install_journal(os_root, journal)
            if _projection_sha256(os_root / LIBRARY_DIR) != candidate["projection_sha256"]:
                raise LibraryError("rollback projection readback differs from retained generation")
            _atomic_write(os_root / INSTALL_RECEIPT, candidate["rollback_receipt_bytes"])
            journal["phase"] = "receipt_written"
            _write_install_journal(os_root, journal)
            verification = verify_library_install(os_root)
            if verification.get("status") != "verified":
                raise LibraryError("restored library did not pass receipt-backed verification")
            journal["phase"] = "committed"
            _write_install_journal(os_root, journal)
            _finish_install_transaction(os_root, journal)
            return {
                **plan,
                "status": "rolled_back",
                "dry_run": False,
                "run_id": run_id,
                "replaced_backup_path": replaced_backup.relative_to(os_root).as_posix(),
                "replaced_receipt_path": replaced_receipt.relative_to(os_root).as_posix(),
                "verification": verification,
            }
        except BaseException:
            if (os_root / INSTALL_JOURNAL).exists():
                _recover_install_transaction(os_root)
            else:
                _remove_path(staging_root)
                _remove_path(replaced_receipt)
            raise


def _library_readme() -> str:
    return """# Agentic OS Object Library

This directory is an installed projection of the canonical
external source repository. Do not author durable changes here;
use the registered source project and reinstall an exact validated revision.

Each object owns an object.yml manifest. Do not edit generated files under
registry/ directly. Use `agentic-os library verify-install` to confirm source
revision, registry digest, and object-count provenance.

Runtime logs, state, worktrees, receipts, caches, secrets, and generated outputs
are not versioned here.
"""


def _gitignore() -> str:
    return """# Runtime and generated content
**/.venv/
**/__pycache__/
**/node_modules/
**/logs/
**/runs/
**/run-logs/
**/worker-runs/
**/worktrees/
**/artifacts/
**/receipts/
**/cache/
**/state/
**/output/
**/outputs/
*.log
*.pid
*.sqlite
*.sqlite3
*.db
*.jsonl
*.ndjson
*.xlsx
*.xls

# Secrets and local credentials
**/.env
**/.env.*
**/*credential*
**/*secret*
**/*token*
**/*cookie*

# Host noise
.DS_Store
.registry.lock
"""


def _precommit_hook() -> str:
    return """#!/bin/sh
set -eu
repo=$(git rev-parse --show-toplevel)
if [ -f "$repo/scripts/validate_library.py" ]; then
  python3 "$repo/scripts/validate_library.py" --repo "$repo" >/dev/null
else
  root=$(cd "$repo/.." && pwd)
  agentic-os library refresh --root "$root" --apply >/dev/null
  agentic-os library doctor --root "$root" >/dev/null
  git diff --exit-code -- registry
fi
"""


def init_library(
    root: str | Path,
    *,
    dry_run: bool = True,
    initialize_git: bool = False,
) -> dict[str, Any]:
    os_root = expand_path(root)
    lib = os_root / LIBRARY_DIR
    receipt = _load_json(os_root / INSTALL_RECEIPT)
    receipt_backed = bool(receipt and receipt.get("status") == "installed")
    existing_state = (
        _installed_projection_state(os_root, lib)
        if lib.exists() or lib.is_symlink()
        else None
    )
    managed_placeholder = bool(
        existing_state and existing_state.get("managed_placeholder")
    )
    create_managed_placeholder = not lib.exists() or managed_placeholder
    planned = [
        LIBRARY_DIR / "README.md",
        LIBRARY_DIR / ".gitignore",
        REGISTRY_DIR,
        LIBRARY_DIR / "schemas",
        *[LIBRARY_DIR / plural for plural in PLURAL_BY_KIND.values()],
    ]
    result = {
        "api_version": API_VERSION,
        "action": "library.init",
        "status": "planned" if dry_run else "initialized",
        "dry_run": dry_run,
        "paths": [path.as_posix() for path in planned],
        "git_requested": initialize_git,
        "receipt_backed": receipt_backed,
        "managed_placeholder": create_managed_placeholder and not initialize_git,
    }
    if receipt_backed:
        # A package update may refresh the separate bootstrap fallback, but
        # init itself has no authority to change a receipt-backed external
        # projection or regenerate its registries.
        result["status"] = "preserved"
        result["paths"] = []
        return result
    if dry_run:
        return result
    bootstrap = os_root / MANAGED_LIBRARY_FALLBACK
    if bootstrap.is_dir() and create_managed_placeholder:
        shutil.copytree(bootstrap, lib, dirs_exist_ok=True, symlinks=True)
    lib.mkdir(parents=True, exist_ok=True)
    for plural in PLURAL_BY_KIND.values():
        (lib / plural / "root").mkdir(parents=True, exist_ok=True)
        (lib / plural / "domains").mkdir(parents=True, exist_ok=True)
    (os_root / REGISTRY_DIR).mkdir(parents=True, exist_ok=True)
    (lib / "schemas").mkdir(parents=True, exist_ok=True)
    readme = lib / "README.md"
    ignore = lib / ".gitignore"
    if not readme.exists():
        readme.write_text(_library_readme(), encoding="utf-8")
    if not ignore.exists():
        ignore.write_text(_gitignore(), encoding="utf-8")
    if initialize_git and not (lib / ".git").exists():
        subprocess.run(["git", "init", "-b", "main", str(lib)], check=True, capture_output=True, text=True)
    if initialize_git:
        (os_root / MANAGED_PLACEHOLDER_MARKER).unlink(missing_ok=True)
        hook = lib / ".githooks/pre-commit"
        hook.parent.mkdir(parents=True, exist_ok=True)
        if not hook.exists():
            hook.write_text(_precommit_hook(), encoding="utf-8")
            hook.chmod(0o755)
        subprocess.run(
            ["git", "-C", str(lib), "config", "core.hooksPath", ".githooks"],
            check=True,
            capture_output=True,
            text=True,
        )
    refresh_registry(os_root, dry_run=False)
    if create_managed_placeholder and not initialize_git:
        _atomic_write(
            os_root / MANAGED_PLACEHOLDER_MARKER,
            (
                json.dumps(
                    {
                        "api_version": MANAGED_PLACEHOLDER_API_VERSION,
                        "managed_by": "genomes_agentic_os",
                        "projection_sha256": _projection_sha256(lib),
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8"),
        )
    return result


def _first_heading(path: Path, fallback: str) -> tuple[str, str]:
    if not path.is_file() or path.stat().st_size > 1_000_000:
        return fallback.replace("_", " ").replace("-", " ").title(), ""
    try:
        body = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return fallback.replace("_", " ").replace("-", " ").title(), ""
    title = next(
        (line.lstrip("#").strip() for line in body.splitlines() if line.startswith("# ")),
        fallback.replace("_", " ").replace("-", " ").title(),
    )
    paragraph: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "---", "<!--")):
            if paragraph:
                break
            continue
        paragraph.append(stripped)
        if sum(len(item) for item in paragraph) >= 400:
            break
    return title, " ".join(paragraph)[:600]


def _legacy_native_id(kind: str, source: Path) -> str:
    if source.is_dir():
        return _identifier(source.name, "legacy object id")
    if kind == "skill" and source.name == "SKILL.md":
        return _identifier(source.parent.name, "legacy object id")
    stem = source.stem
    if kind == "command" and stem.startswith("os-"):
        stem = stem[3:]
    return _identifier(stem, "legacy object id")


def _legacy_scope(item: Mapping[str, Any]) -> dict[str, str | None]:
    scope = item.get("scope") or {}
    domain = str(scope.get("domain") or "").strip() if isinstance(scope, Mapping) else ""
    project = str(scope.get("project") or "").strip() if isinstance(scope, Mapping) else ""
    if domain in {"", "shared_factory", "harness"}:
        return {"level": "root", "domain": None, "project": None}
    if project:
        return {
            "level": "project",
            "domain": _identifier(domain, "domain"),
            "project": _identifier(project, "project"),
        }
    return {
        "level": "domain",
        "domain": _identifier(domain, "domain"),
        "project": None,
    }


def legacy_migration_plan(root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    source_registry = os_root / "harness/registries/first-class-resources.json"
    payload = _load_json(source_registry)
    if not payload or not isinstance(payload.get("resources"), list):
        raise LibraryError(
            "legacy migration requires harness/registries/first-class-resources.json"
        )
    candidates: dict[str, dict[str, Any]] = {}
    diagnostics: list[dict[str, str]] = []
    for item in payload["resources"]:
        if not isinstance(item, Mapping):
            continue
        kind = LEGACY_KIND_MAP.get(str(item.get("kind") or ""))
        subtype = str(item.get("subtype") or "")
        if (
            not kind
            or subtype in {"tracking_instance"}
            or (kind == "rule" and subtype != "registry_entry")
        ):
            continue
        source_value = str(item.get("source") or "").strip()
        if not source_value:
            continue
        relative_source = Path(source_value)
        if relative_source.is_absolute() or ".." in relative_source.parts:
            diagnostics.append(
                {"code": "unsafe_source", "source": source_value, "severity": "error"}
            )
            continue
        source = os_root / relative_source
        if not source.exists():
            diagnostics.append(
                {"code": "source_missing", "source": source_value, "severity": "warning"}
            )
            continue
        if source.is_file() and source.name in {"program.md", "workflow.md", "automation.md"}:
            source = source.parent
            relative_source = source.relative_to(os_root)
        try:
            registry_native_id = str(item.get("native_id") or "").strip()
            native_id = (
                _identifier(registry_native_id, "legacy object id")
                if kind in {"command", "rule", "skill"} and registry_native_id
                else _legacy_native_id(kind, source)
            )
            scope = _legacy_scope(item)
            target_relative = LIBRARY_DIR / object_relative_path(
                kind,
                native_id,
                level=str(scope["level"]),
                domain=scope["domain"],
                project=scope["project"],
            )
            canonical_id = canonical_object_id(
                kind,
                native_id,
                level=str(scope["level"]),
                domain=scope["domain"],
                project=scope["project"],
            )
        except LibraryError as exc:
            diagnostics.append(
                {
                    "code": "identity_invalid",
                    "source": source_value,
                    "severity": "error",
                    "message": str(exc),
                }
            )
            continue
        candidate = {
            "object_id": canonical_id,
            "kind": kind,
            "id": native_id,
            "scope": scope,
            "source": relative_source.as_posix(),
            "target": target_relative.as_posix(),
            "title": str(item.get("title") or native_id),
            "description": str(item.get("summary") or ""),
            "tags": sorted({str(tag) for tag in item.get("tags") or [] if str(tag)}),
            "runtime_sources": (
                [
                    path.relative_to(os_root).as_posix()
                    for path in sorted(source.iterdir())
                    if path.is_dir() and _is_runtime_directory_name(path.name)
                ]
                if source.is_dir()
                else []
            ),
        }
        existing = candidates.get(canonical_id)
        if existing and existing["source"] != candidate["source"]:
            lane = source.parent.name if source.is_dir() else source.parent.parent.name
            collision_id = _identifier(f"{lane}_{native_id}", "collision object id")
            target_relative = LIBRARY_DIR / object_relative_path(
                kind,
                collision_id,
                level=str(scope["level"]),
                domain=scope["domain"],
                project=scope["project"],
            )
            collision_canonical_id = canonical_object_id(
                kind,
                collision_id,
                level=str(scope["level"]),
                domain=scope["domain"],
                project=scope["project"],
            )
            if collision_canonical_id in candidates:
                diagnostics.append(
                    {
                        "code": "identity_collision",
                        "severity": "error",
                        "source": candidate["source"],
                        "message": f"{canonical_id} also maps from {existing['source']}",
                    }
                )
                continue
            diagnostics.append(
                {
                    "code": "identity_disambiguated",
                    "severity": "warning",
                    "source": candidate["source"],
                    "message": f"{canonical_id} preserved as {collision_canonical_id}",
                }
            )
            candidate.update(
                {
                    "object_id": collision_canonical_id,
                    "id": collision_id,
                    "target": target_relative.as_posix(),
                }
            )
            canonical_id = collision_canonical_id
        candidates[canonical_id] = candidate
    hooks_registry = os_root / "harness/registries/hooks.yml"
    if hooks_registry.is_file():
        hooks_payload = yaml.safe_load(hooks_registry.read_text(encoding="utf-8")) or {}
        for hook in hooks_payload.get("hooks") or []:
            if not isinstance(hook, Mapping) or not hook.get("id"):
                continue
            native_id = _identifier(hook.get("id"), "hook id")
            canonical_id = canonical_object_id("hook", native_id)
            source_value = str(hook.get("source") or "").strip()
            relative_source = Path(source_value) if source_value else None
            local_source = bool(
                relative_source
                and not relative_source.is_absolute()
                and ".." not in relative_source.parts
                and (os_root / relative_source).is_file()
            )
            candidates[canonical_id] = {
                "object_id": canonical_id,
                "kind": "hook",
                "id": native_id,
                "scope": {"level": "root", "domain": None, "project": None},
                "source": relative_source.as_posix() if local_source and relative_source else "",
                "external_source": None if local_source else source_value or None,
                "target": (LIBRARY_DIR / object_relative_path("hook", native_id)).as_posix(),
                "title": str(hook.get("name") or native_id),
                "description": str(hook.get("description") or ""),
                "tags": ["hook", *[str(event) for event in str(hook.get("events") or "").split(",") if event]],
                "virtual": not local_source,
            }
    supplemental_roots = (
        ("template", os_root / "harness/shared_factory/05-knowledge/templates"),
        ("toolkit", os_root / "harness/shared_factory/05-knowledge/toolkits"),
    )
    for kind, base in supplemental_roots:
        if not base.is_dir():
            continue
        for source in sorted(base.iterdir()):
            if source.name == "README.md" or (kind == "toolkit" and source.suffix == ".zip"):
                continue
            native_id = _identifier(source.stem if source.is_file() else source.name, f"{kind} id")
            canonical_id = canonical_object_id(kind, native_id)
            relative_source = source.relative_to(os_root)
            candidates[canonical_id] = {
                "object_id": canonical_id,
                "kind": kind,
                "id": native_id,
                "scope": {"level": "root", "domain": None, "project": None},
                "source": relative_source.as_posix(),
                "target": (LIBRARY_DIR / object_relative_path(kind, native_id)).as_posix(),
                "title": native_id.replace("_", " ").replace("-", " ").title(),
                "description": f"Migrated Agentic OS {kind}.",
                "tags": [kind],
            }
    domain_roots = {
        *os_root.glob("*/"),
        *os_root.glob("domains/*/"),
    }
    for domain_root in sorted(domain_roots):
        knowledge_root = domain_root / "05-knowledge"
        if (
            domain_root.name == "archive"
            or not (domain_root / "domain.yml").is_file()
            or not knowledge_root.is_dir()
        ):
            continue
        for source in sorted(path for path in knowledge_root.iterdir() if path.is_file()):
            native_id = _identifier(source.stem.replace(".", "_"), "reference id")
            scope = {"level": "domain", "domain": domain_root.name, "project": None}
            canonical_id = canonical_object_id(
                "reference",
                native_id,
                level="domain",
                domain=domain_root.name,
            )
            if canonical_id in candidates:
                native_id = _identifier(
                    f"{native_id}_{source.suffix.lstrip('.')}",
                    "reference id",
                )
                canonical_id = canonical_object_id(
                    "reference",
                    native_id,
                    level="domain",
                    domain=domain_root.name,
                )
            candidates[canonical_id] = {
                "object_id": canonical_id,
                "kind": "reference",
                "id": native_id,
                "scope": scope,
                "source": source.relative_to(os_root).as_posix(),
                "target": (
                    LIBRARY_DIR
                    / object_relative_path(
                        "reference",
                        native_id,
                        level="domain",
                        domain=domain_root.name,
                    )
                ).as_posix(),
                "title": native_id.replace("_", " ").replace("-", " ").title(),
                "description": f"Migrated {domain_root.name} domain reference.",
                "tags": ["reference", domain_root.name],
            }
    return {
        "api_version": API_VERSION,
        "action": "library.migrate-legacy",
        "status": "planned",
        "source_registry": source_registry.relative_to(os_root).as_posix(),
        "candidate_count": len(candidates),
        "diagnostics": diagnostics,
        "objects": [candidates[key] for key in sorted(candidates)],
    }


def _is_secret_name(name: str) -> bool:
    return any(pattern.search(name) for pattern in SECRET_FILE_PATTERNS)


def _is_runtime_directory_name(name: str) -> bool:
    return name in RUNTIME_PARTS or name.lower().endswith(
        ("_outputs", "-outputs", "_snapshots", "-snapshots")
    )


def _definition_ignore(directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        path = Path(directory) / name
        backup_file = bool(
            re.search(r"(?:\.bak(?:[-.]|$)|\.backup(?:[-.]|$)|\.orig$|\.rej$)", name)
        )
        if _is_runtime_directory_name(name) or backup_file or _is_secret_name(name):
            ignored.add(name)
        elif path.is_file() and path.suffix.lower() in IGNORED_FILE_SUFFIXES:
            ignored.add(name)
        elif path.is_file() and path.stat().st_size > 10_000_000:
            ignored.add(name)
    return ignored


def _entrypoint(kind: str, copied_root: Path, source_name: str | None = None) -> str:
    if source_name and (copied_root / source_name).is_file():
        return source_name
    for candidate in CONVENTIONAL_ENTRYPOINTS[kind]:
        if (copied_root / candidate).is_file():
            return candidate
    files = sorted(path for path in copied_root.rglob("*") if path.is_file() and path.name != MANIFEST_NAME)
    if not files:
        raise LibraryError(f"migrated object has no definition entrypoint: {copied_root}")
    return files[0].relative_to(copied_root).as_posix()


def apply_legacy_migration(root: str | Path, *, dry_run: bool = True) -> dict[str, Any]:
    os_root = expand_path(root)
    plan = legacy_migration_plan(os_root)
    if any(item.get("severity") == "error" for item in plan["diagnostics"]):
        plan["status"] = "blocked"
        return plan
    if dry_run:
        return plan
    copied = 0
    existing = 0
    for item in plan["objects"]:
        source = os_root / item["source"] if item.get("source") else None
        target = os_root / item["target"]
        manifest_path = target / MANIFEST_NAME
        if manifest_path.exists():
            existing += 1
            continue
        target.mkdir(parents=True, exist_ok=True)
        if item.get("virtual"):
            source_name = "hook.md"
            external_source = item.get("external_source") or "registry-managed"
            (target / source_name).write_text(
                f"# {item['title']}\n\n{item['description']}\n\nExternal source: {external_source}\n",
                encoding="utf-8",
            )
        elif source is not None and source.is_dir():
            shutil.copytree(
                source,
                target,
                dirs_exist_ok=True,
                symlinks=True,
                ignore=_definition_ignore,
            )
            source_name = None
        elif source is not None:
            shutil.copy2(source, target / source.name)
            source_name = source.name
        else:
            raise LibraryError(f"migration source is missing: {item['object_id']}")
        definition_files = [
            path
            for path in target.rglob("*")
            if path.is_file() and path.name != MANIFEST_NAME
        ]
        if not definition_files:
            source_label = item.get("source") or "the legacy registry"
            (target / "README.md").write_text(
                f"# {item['title']}\n\n"
                f"{item['description']}\n\n"
                "This registered object had no definition files at migration time. "
                f"Its identity is preserved from `{source_label}` so it can be "
                "reviewed, implemented, disabled, or archived explicitly.\n",
                encoding="utf-8",
            )
        entrypoint = _entrypoint(item["kind"], target, source_name)
        title, description = _first_heading(target / entrypoint, item["id"])
        manifest = {
            "api_version": MANIFEST_API_VERSION,
            "kind": item["kind"],
            "id": item["id"],
            "title": item["title"] or title,
            "description": item["description"] or description,
            "status": "active",
            "scope": item["scope"],
            "owner": {"type": "operator", "id": "Genome"},
            "entrypoint": entrypoint,
            "tags": item["tags"],
            "dependencies": [],
            "aliases": [item["source"]] if item.get("source") else [],
            "runtime": {
                "root": (
                    Path("runtime/objects")
                    / PLURAL_BY_KIND[item["kind"]]
                    / item["object_id"].replace(":", "/")
                ).as_posix(),
                "legacy_roots": item.get("runtime_sources") or [],
            },
            "validation": {"commands": []},
        }
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
        normalize_manifest(manifest, manifest_path=manifest_path, root=os_root)
        copied += 1
    refresh = refresh_registry(os_root, dry_run=False)
    return {
        **plan,
        "status": "migrated",
        "dry_run": False,
        "copied": copied,
        "existing": existing,
        "registry": refresh,
    }
