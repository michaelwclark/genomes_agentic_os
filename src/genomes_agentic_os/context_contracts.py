"""Versioned, explainable context inheritance for Agentic OS objects."""

from __future__ import annotations

from dataclasses import dataclass, field
import fnmatch
import hashlib
from pathlib import Path
from typing import Any, Iterable

import yaml


MANIFEST_CANDIDATES = ("context-contract.yml", "context.yml", ".context.yml")
PARENT_CONTRACT_FILES = ("AGENTS.md", "ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md")
DEFAULT_EXCLUDES = (
    "**/worktrees/**",
    "**/runs/**",
    "**/logs/**",
    "**/artifacts/**",
    "**/snapshots/**",
    "**/archive/**",
    "**/08-archive/**",
)
ALLOWED_KINDS = {"root", "domain", "project", "workflow", "automation", "program", "task"}


@dataclass(frozen=True)
class Diagnostic:
    severity: str
    code: str
    message: str
    path: Path | None = None

    def as_dict(self) -> dict[str, str]:
        result = {"severity": self.severity, "code": self.code, "message": self.message}
        if self.path is not None:
            result["path"] = str(self.path)
        return result


@dataclass(frozen=True)
class ContextManifest:
    path: Path
    schema_version: int
    kind: str
    inherits: tuple[str, ...]
    read_first: tuple[str, ...]
    deferred: tuple[str, ...]
    excluded: tuple[str, ...]
    capabilities: tuple[dict[str, Any], ...]
    providers: dict[str, Any]
    rule_overrides: tuple[str, ...]
    diagnostics: tuple[Diagnostic, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "schema_version": self.schema_version,
            "kind": self.kind,
            "inherits": list(self.inherits),
            "read": {
                "first": list(self.read_first),
                "deferred": list(self.deferred),
                "exclude": list(self.excluded),
            },
            "capabilities": list(self.capabilities),
            "providers": self.providers,
            "overrides": {"rules": list(self.rule_overrides)},
            "diagnostics": [item.as_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True)
class ContextSource:
    path: Path
    phase: str
    declared_by: Path
    inherited: bool
    exists: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "phase": self.phase,
            "declared_by": str(self.declared_by),
            "inherited": self.inherited,
            "exists": self.exists,
        }


@dataclass
class ResolvedContextContract:
    target: Path
    manifests: list[Path] = field(default_factory=list)
    read_first: list[ContextSource] = field(default_factory=list)
    deferred: list[ContextSource] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    capabilities: dict[str, dict[str, Any]] = field(default_factory=dict)
    providers: dict[str, dict[str, Any]] = field(default_factory=dict)
    skipped_duplicates: list[dict[str, str]] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    legacy_fallback: bool = False

    @property
    def ok(self) -> bool:
        return not any(item.severity == "error" for item in self.diagnostics)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "target": str(self.target),
            "ok": self.ok,
            "legacy_fallback": self.legacy_fallback,
            "manifests": [str(path) for path in self.manifests],
            "read_first": [source.as_dict() for source in self.read_first],
            "deferred": [source.as_dict() for source in self.deferred],
            "excluded": self.excluded,
            "capabilities": self.capabilities,
            "providers": self.providers,
            "skipped_duplicates": self.skipped_duplicates,
            "diagnostics": [item.as_dict() for item in self.diagnostics],
        }


def _string_list(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{field_name} must be a list of non-empty strings")
    return tuple(item.strip() for item in value)


def _safe_relative(value: str, field_name: str) -> str:
    path = Path(value)
    if path.is_absolute() or value.startswith("~") or ".." in path.parts:
        raise ValueError(f"{field_name} entries must be safe relative paths: {value!r}")
    return value


def _normalize_capabilities(value: Any, field_name: str) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    result: list[dict[str, Any]] = []
    for entry in value:
        if isinstance(entry, str) and entry.strip():
            result.append({"id": entry.strip()})
        elif isinstance(entry, dict) and isinstance(entry.get("id"), str) and entry["id"].strip():
            result.append(dict(entry))
        else:
            raise ValueError(f"{field_name} entries require a capability id")
    return tuple(result)


def _manifest_path(path: str | Path) -> Path | None:
    candidate = Path(path).expanduser()
    if candidate.is_file():
        return candidate.resolve()
    if candidate.is_dir():
        for filename in MANIFEST_CANDIDATES:
            manifest = candidate / filename
            if manifest.is_file():
                return manifest.resolve()
    return None


def load_context_manifest(path: str | Path) -> ContextManifest | None:
    """Load a canonical or compatibility manifest. Missing is not an error."""

    manifest_path = _manifest_path(path)
    if manifest_path is None:
        return None
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("context contract must be a YAML mapping")
    version = data.get("schema_version", data.get("version"))
    if version != 1:
        raise ValueError(f"unsupported context contract schema_version: {version!r}")
    kind = str(data.get("kind") or "").strip()
    if kind not in ALLOWED_KINDS:
        raise ValueError(f"unsupported context contract kind: {kind!r}")

    inherit_value = data.get("inherits", data.get("inherit", []))
    if inherit_value is True:
        inherits = ("parent",)
    elif inherit_value is False or inherit_value is None:
        inherits = ()
    else:
        inherits = _string_list(inherit_value, "inherits")

    read = data.get("read") or {}
    if not isinstance(read, dict):
        raise ValueError("read must be a mapping")
    sources = data.get("sources") or {}
    if not isinstance(sources, dict):
        raise ValueError("sources must be a mapping")
    overrides = data.get("overrides") or {}
    if not isinstance(overrides, dict):
        raise ValueError("overrides must be a mapping")
    override_read = overrides.get("read") or {}
    if not isinstance(override_read, dict):
        raise ValueError("overrides.read must be a mapping")

    first = _string_list(read.get("first", sources.get("read_first")), "read.first")
    deferred = _string_list(read.get("deferred", sources.get("deferred")), "read.deferred")
    excluded = _string_list(read.get("exclude", sources.get("excluded")), "read.exclude")
    first += _string_list(override_read.get("first"), "overrides.read.first")
    deferred += _string_list(override_read.get("deferred"), "overrides.read.deferred")
    excluded += _string_list(override_read.get("exclude"), "overrides.read.exclude")
    first = tuple(_safe_relative(value, "read.first") for value in first)
    deferred = tuple(_safe_relative(value, "read.deferred") for value in deferred)
    excluded = tuple(_safe_relative(value, "read.exclude") for value in excluded)

    capabilities = _normalize_capabilities(data.get("capabilities"), "capabilities")
    capabilities += _normalize_capabilities(overrides.get("capabilities"), "overrides.capabilities")
    providers = data.get("providers") or {}
    if not isinstance(providers, dict):
        raise ValueError("providers must be a mapping")
    override_providers = overrides.get("providers") or {}
    if not isinstance(override_providers, dict):
        raise ValueError("overrides.providers must be a mapping")
    providers = {**providers, **override_providers}
    rules = _string_list(overrides.get("rules"), "overrides.rules")
    return ContextManifest(
        path=manifest_path,
        schema_version=1,
        kind=kind,
        inherits=inherits,
        read_first=first,
        deferred=deferred,
        excluded=excluded,
        capabilities=capabilities,
        providers=providers,
        rule_overrides=rules,
    )


def _ancestor_dirs(target: Path, root: Path) -> list[Path]:
    target = target.resolve()
    root = root.resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"context target is outside root: {target}") from exc
    parents: list[Path] = []
    current = target
    while True:
        parents.append(current)
        if current == root:
            break
        current = current.parent
    return list(reversed(parents))


def _central_provider_routes(root: Path) -> dict[str, dict[str, Any]]:
    registry = root / "harness" / "registries" / "composio-tools.yml"
    if not registry.is_file():
        return {}
    try:
        data = yaml.safe_load(registry.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    entries = data.get("composio_tools") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return {}
    routes: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        routes[str(entry["id"])] = {
            "value": list(entry.get("provider_priority") or []),
            "declared_by": str(registry),
            "source": "central_registry",
        }
    return routes


def _add_sources(
    result: ResolvedContextContract,
    values: Iterable[str],
    *,
    base: Path,
    declared_by: Path,
    phase: str,
    inherited: bool,
    seen_digest: dict[str, Path],
) -> None:
    destination = result.read_first if phase == "read_first" else result.deferred
    for value in values:
        path = (base / value).resolve()
        exists = path.is_file()
        if exists:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest in seen_digest:
                result.skipped_duplicates.append(
                    {"path": str(path), "duplicate_of": str(seen_digest[digest]), "sha256": digest}
                )
                continue
            seen_digest[digest] = path
        else:
            result.diagnostics.append(
                Diagnostic("warning", "missing_source", f"declared source does not exist: {path}", path)
            )
        destination.append(ContextSource(path, phase, declared_by, inherited, exists))


def resolve_context_contract(
    target: str | Path,
    *,
    root: str | Path | None = None,
    legacy_sources: Iterable[str | Path] = (),
) -> ResolvedContextContract:
    """Resolve inherited context and provenance without mutating the OS."""

    target_path = Path(target).expanduser().resolve()
    if target_path.is_file():
        target_path = target_path.parent
    root_path = Path(root).expanduser().resolve() if root else target_path
    result = ResolvedContextContract(target=target_path, excluded=list(DEFAULT_EXCLUDES))
    result.providers.update(_central_provider_routes(root_path))
    seen_digest: dict[str, Path] = {}
    manifests: list[ContextManifest] = []

    for directory in _ancestor_dirs(target_path, root_path):
        manifest = load_context_manifest(directory)
        if manifest is not None:
            manifests.append(manifest)

    target_manifest = load_context_manifest(target_path)
    if target_manifest is None:
        result.legacy_fallback = True
        for source in legacy_sources:
            path = Path(source).expanduser()
            if not path.is_absolute():
                path = target_path / path
            path = path.resolve()
            _add_sources(
                result,
                (str(path),),
                base=Path("/"),
                declared_by=path.parent,
                phase="read_first",
                inherited=path.parent != target_path,
                seen_digest=seen_digest,
            )
        result.diagnostics.append(
            Diagnostic("warning", "legacy_fallback", "no context-contract.yml found; legacy sources preserved", target_path)
        )
        return result

    inherit_parent = "parent" in target_manifest.inherits or "domain" in target_manifest.inherits
    effective_manifests = manifests if inherit_parent else [target_manifest]
    result.manifests = [manifest.path for manifest in effective_manifests]
    if inherit_parent:
        for directory in _ancestor_dirs(target_path.parent, root_path):
            for filename in PARENT_CONTRACT_FILES:
                path = directory / filename
                if not path.is_file():
                    continue
                _add_sources(
                    result,
                    (filename,),
                    base=directory,
                    declared_by=directory,
                    phase="read_first",
                    inherited=True,
                    seen_digest=seen_digest,
                )

    for manifest in effective_manifests:
        inherited = manifest.path.parent != target_path
        _add_sources(
            result,
            manifest.read_first,
            base=manifest.path.parent,
            declared_by=manifest.path,
            phase="read_first",
            inherited=inherited,
            seen_digest=seen_digest,
        )
        _add_sources(
            result,
            manifest.deferred,
            base=manifest.path.parent,
            declared_by=manifest.path,
            phase="deferred",
            inherited=inherited,
            seen_digest=seen_digest,
        )
        result.excluded.extend(pattern for pattern in manifest.excluded if pattern not in result.excluded)
        for capability in manifest.capabilities:
            capability_id = str(capability["id"])
            result.capabilities[capability_id] = {
                **capability,
                "declared_by": str(manifest.path),
                "inherited": inherited,
            }
        for identity, value in manifest.providers.items():
            result.providers[str(identity)] = {
                "value": value,
                "declared_by": str(manifest.path),
                "source": "manifest_override",
                "inherited": inherited,
            }
        for rule in manifest.rule_overrides:
            result.capabilities[f"rule:{rule}"] = {
                "id": f"rule:{rule}",
                "declared_by": str(manifest.path),
                "inherited": inherited,
            }
    return result


def path_is_excluded(path: str | Path, patterns: Iterable[str] = DEFAULT_EXCLUDES) -> bool:
    value = Path(path).as_posix()
    return any(fnmatch.fnmatch(value, pattern) for pattern in patterns)
