"""Plan, apply, and exactly restore compact context-contract migrations."""

from __future__ import annotations

import base64
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from .context_contracts import PARENT_CONTRACT_FILES, load_context_manifest, resolve_context_contract
from .scaffold import expand_path


CONTRACT_FILENAME = "context-contract.yml"
LEGACY_CONTEXT_FILES = ("ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md")
OBJECT_CONTEXT_FILES = (
    "AGENTS.md",
    "PROFILE.md",
    "CLAUDE.md",
    CONTRACT_FILENAME,
    *LEGACY_CONTEXT_FILES,
    "MEMORY.md",
    "workflow.md",
    "automation.md",
    "quick-reference.md",
    "context-pack.md",
    "permissions.md",
    "approval-rules.md",
    "runbook.md",
)
LOCAL_READ_FILES = (
    "AGENTS.md",
    "MEMORY.md",
    "workflow.md",
    "automation.md",
    "quick-reference.md",
    "context-pack.md",
    "permissions.md",
    "approval-rules.md",
    "runbook.md",
)
PLAN_SCHEMA_VERSION = 3
RECEIPT_SCHEMA_VERSION = 2
MINIMUM_REDUCTION_RATIO = 0.40


@dataclass
class ContextCheckResult:
    root: Path
    targets: int = 0
    manifests: int = 0
    legacy_fallbacks: int = 0
    duplicate_groups: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "ok": self.ok,
            "targets": self.targets,
            "manifests": self.manifests,
            "legacy_fallbacks": self.legacy_fallbacks,
            "duplicate_groups": self.duplicate_groups,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def managed_context_targets(root: str | Path) -> list[Path]:
    """Return active workflow/automation folders without evidence trees."""

    os_root = expand_path(root)
    targets: set[Path] = set()
    patterns = (
        "*/03-workflows/*/*",
        "*/04-automations/*/*",
        "harness/shared_factory/03-workflows/*/*",
        "harness/shared_factory/04-automations/*/*",
    )
    for pattern in patterns:
        for path in os_root.glob(pattern):
            if path.is_dir() and not path.is_symlink():
                targets.add(path)
    return sorted(targets)


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def duplicate_legacy_groups(targets: Iterable[Path]) -> dict[str, list[Path]]:
    by_digest: dict[str, list[Path]] = defaultdict(list)
    for target in targets:
        for filename in LEGACY_CONTEXT_FILES:
            path = target / filename
            if path.is_file():
                by_digest[file_digest(path)].append(path)
    return {
        digest: sorted(paths)
        for digest, paths in sorted(by_digest.items())
        if len({path.parent for path in paths}) > 1
    }


def check_context_contracts(root: str | Path) -> ContextCheckResult:
    os_root = expand_path(root)
    result = ContextCheckResult(root=os_root)
    targets = managed_context_targets(os_root)
    result.targets = len(targets)
    duplicate_groups = duplicate_legacy_groups(targets)
    result.duplicate_groups = len(duplicate_groups)
    for target in targets:
        manifest_path = target / CONTRACT_FILENAME
        if not manifest_path.is_file():
            result.legacy_fallbacks += 1
            result.warnings.append(f"legacy context fallback: {target.relative_to(os_root)}")
            continue
        result.manifests += 1
        try:
            manifest = load_context_manifest(manifest_path)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            result.errors.append(f"invalid context contract {manifest_path.relative_to(os_root)}: {exc}")
            continue
        if manifest is None:
            result.errors.append(f"empty context contract: {manifest_path.relative_to(os_root)}")
    for digest, paths in duplicate_groups.items():
        relative = ", ".join(str(path.relative_to(os_root)) for path in paths[:4])
        suffix = f" (+{len(paths) - 4} more)" if len(paths) > 4 else ""
        result.warnings.append(f"duplicate legacy context {digest[:12]}: {relative}{suffix}")
    return result


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _safe_inherited_source(target: Path, root: Path, filename: str, digest: str) -> Path | None:
    current = target.parent
    while True:
        candidate = current / filename
        if candidate.is_file() and not candidate.is_symlink() and file_digest(candidate) == digest:
            return candidate
        if current == root or root not in current.parents:
            return None
        current = current.parent


def _local_context_bytes(targets: Iterable[Path]) -> int:
    return sum(
        path.stat().st_size
        for target in targets
        for filename in OBJECT_CONTEXT_FILES
        if (path := target / filename).is_file() and not path.is_symlink()
    )


def _bounded_path(root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    path = path.resolve() if path.is_absolute() else (root / path).resolve()
    if path == root or root not in path.parents:
        raise ValueError(f"migration path is outside root: {value}")
    return path


def _selected_targets(root: Path, values: Iterable[str | Path]) -> list[Path]:
    managed = set(managed_context_targets(root))
    requested = list(values)
    if not requested:
        return sorted(managed)
    selected: set[Path] = set()
    for value in requested:
        path = _bounded_path(root, value)
        if path not in managed:
            raise ValueError(f"context migration target is not a managed workflow or automation: {value}")
        selected.add(path)
    return sorted(selected)


def _root_state_hash(root: Path, targets: Iterable[Path], extra_paths: Iterable[Path] = ()) -> str:
    paths = {
        target / filename
        for target in targets
        for filename in OBJECT_CONTEXT_FILES
    }
    paths.update(extra_paths)
    state: list[dict[str, Any]] = []
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            state.append({"path": relative, "type": "symlink", "target": str(path.readlink())})
        elif path.is_file():
            state.append(
                {
                    "path": relative,
                    "type": "file",
                    "sha256": file_digest(path),
                    "bytes": path.stat().st_size,
                    "mode": path.stat().st_mode & 0o777,
                }
            )
        elif path.exists():
            state.append({"path": relative, "type": "other"})
        else:
            state.append({"path": relative, "type": "absent"})
    return _canonical_hash({"files": state})


def _legacy_v1_root_state_hash(root: Path, targets: Iterable[Path]) -> str:
    """Reproduce schema-v1 receipt hashes written before absent/mode tracking."""

    legacy_files = tuple(filename for filename in OBJECT_CONTEXT_FILES if filename != "MEMORY.md")
    state: list[dict[str, Any]] = []
    for target in targets:
        for filename in legacy_files:
            path = target / filename
            if path.is_file() and not path.is_symlink():
                state.append(
                    {
                        "path": path.relative_to(root).as_posix(),
                        "sha256": file_digest(path),
                        "bytes": path.stat().st_size,
                    }
                )
    return _canonical_hash({"files": sorted(state, key=lambda item: item["path"])})


def _legacy_sources(target: Path, root: Path) -> list[Path]:
    ancestors: list[Path] = []
    current = target
    while True:
        ancestors.append(current)
        if current == root:
            break
        current = current.parent
    sources: list[Path] = []
    for directory in reversed(ancestors):
        for filename in PARENT_CONTRACT_FILES:
            path = directory / filename
            if path.is_file():
                sources.append(path)
    for filename in LOCAL_READ_FILES:
        path = target / filename
        if path.is_file() and path not in sources:
            sources.append(path)
    return sources


def _semantic_snapshot(root: Path, targets: Iterable[Path]) -> dict[str, Any]:
    snapshots: dict[str, Any] = {}
    for target in sorted(set(targets)):
        legacy = load_context_manifest(target) is None
        resolved = resolve_context_contract(
            target,
            root=root,
            legacy_sources=_legacy_sources(target, root) if legacy else (),
        )
        source_hashes = sorted(
            {
                file_digest(source.path)
                for source in (*resolved.read_first, *resolved.deferred)
                if source.exists and source.path.is_file()
            }
        )
        capabilities = {
            key: {name: value for name, value in entry.items() if name not in {"declared_by", "inherited"}}
            for key, entry in sorted(resolved.capabilities.items())
        }
        providers = {key: entry.get("value") for key, entry in sorted(resolved.providers.items())}
        value = {
            "ok": resolved.ok,
            "source_content_sha256": source_hashes,
            "excluded": sorted(set(resolved.excluded)),
            "capabilities": capabilities,
            "providers": providers,
        }
        value["semantic_sha256"] = _canonical_hash(value)
        snapshots[target.relative_to(root).as_posix()] = value
    return snapshots


def _render_manifest(target: Path) -> bytes:
    if "03-workflows" in target.parts:
        kind = "workflow"
    elif "04-automations" in target.parts:
        kind = "automation"
    else:
        raise ValueError(f"cannot infer context contract kind: {target}")
    read_first = [filename for filename in LOCAL_READ_FILES if (target / filename).is_file()]
    value = {
        "schema_version": 1,
        "kind": kind,
        "inherits": ["parent"],
        "read": {"first": read_first, "deferred": [], "exclude": []},
        "capabilities": [],
        "providers": {},
        "overrides": {"rules": []},
    }
    return yaml.safe_dump(value, sort_keys=False).encode()


def _target_reductions(root: Path, targets: Iterable[Path], actions: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    reductions: dict[str, Any] = {}
    action_list = list(actions)
    for target in targets:
        relative = target.relative_to(root).as_posix()
        relevant = [action for action in action_list if action.get("object") == relative]
        if not relevant:
            continue
        before = _local_context_bytes([target])
        removed = sum(
            int(action.get("bytes_before", 0))
            for action in relevant
            if str(action.get("action", "")).startswith("remove_")
        )
        created_local = sum(
            int(action.get("bytes_after", 0))
            for action in relevant
            if Path(str(action.get("target", ""))).parent.as_posix() == relative
            and str(action.get("action", "")).startswith("create_")
        )
        after = before - removed + created_local
        ratio = (before - after) / before if before else 0.0
        reductions[relative] = {
            "bytes_before": before,
            "bytes_after": after,
            "bytes_removed": removed,
            "bytes_created_local": created_local,
            "reduction_ratio": ratio,
        }
    return reductions


def build_compaction_plan(
    root: str | Path,
    *,
    target_paths: Iterable[str | Path] = (),
    promote_legacy: bool = False,
    capture_validation_baseline: bool = False,
    validation_validator: Callable[[Path], Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic plan of byte-identical inheritance changes.

    Legacy manifest creation is opt-in and bounded to explicit targets. Missing
    parent contracts are promoted to the immediate lane before local copies are
    removed, preserving the resolved source-content signature.
    """

    os_root = expand_path(root)
    requested_targets = tuple(target_paths)
    targets = _selected_targets(os_root, requested_targets)
    if promote_legacy and not requested_targets:
        raise ValueError("--promote-legacy requires at least one explicit target")
    all_targets = managed_context_targets(os_root)
    duplicate_groups = duplicate_legacy_groups(all_targets)
    duplicate_paths = {path for paths in duplicate_groups.values() for path in paths}
    actions: list[dict[str, Any]] = []
    rollback_files: list[dict[str, Any]] = []

    for target in targets:
        relative_object = target.relative_to(os_root).as_posix()
        try:
            manifest = load_context_manifest(target)
        except (OSError, ValueError, yaml.YAMLError):
            manifest = None
        if manifest is None and promote_legacy:
            manifest_content = _render_manifest(target)
            manifest_path = target / CONTRACT_FILENAME
            actions.append(
                {
                    "action": "create_manifest",
                    "object": relative_object,
                    "target": manifest_path.relative_to(os_root).as_posix(),
                    "status": "proposed",
                    "sha256_after": hashlib.sha256(manifest_content).hexdigest(),
                    "bytes_after": len(manifest_content),
                    "content_base64": base64.b64encode(manifest_content).decode("ascii"),
                }
            )
            for filename in LEGACY_CONTEXT_FILES:
                local = target / filename
                if not local.is_file() or local.is_symlink():
                    continue
                digest = file_digest(local)
                inherited = _safe_inherited_source(target, os_root, filename, digest)
                if inherited is None:
                    inherited = target.parent / filename
                    if inherited.exists():
                        actions.append(
                            {
                                "action": "blocked_parent_conflict",
                                "object": relative_object,
                                "target": inherited.relative_to(os_root).as_posix(),
                                "status": "blocked",
                                "reason": f"parent {filename} exists with different content",
                            }
                        )
                        continue
                    actions.append(
                        {
                            "action": "create_inherited_contract",
                            "object": relative_object,
                            "target": inherited.relative_to(os_root).as_posix(),
                            "source": local.relative_to(os_root).as_posix(),
                            "status": "proposed",
                            "sha256_after": digest,
                            "bytes_after": local.stat().st_size,
                        }
                    )
                actions.append(
                    {
                        "action": "remove_promoted_contract",
                        "object": relative_object,
                        "target": local.relative_to(os_root).as_posix(),
                        "status": "proposed",
                        "sha256_before": digest,
                        "bytes_before": local.stat().st_size,
                        "inherited_from": inherited.relative_to(os_root).as_posix(),
                        "inherited_sha256": digest,
                    }
                )
                content = local.read_bytes()
                rollback_files.append(
                    {
                        "path": local.relative_to(os_root).as_posix(),
                        "sha256": digest,
                        "content_base64": base64.b64encode(content).decode("ascii"),
                    }
                )
            continue
        if manifest is None:
            actions.append(
                {
                    "action": "create_manifest",
                    "object": relative_object,
                    "target": relative_object,
                    "status": "review_required",
                    "reason": "legacy object has no valid context contract",
                }
            )
            continue
        if not ({"parent", "domain"} & set(manifest.inherits)):
            continue
        for filename in LEGACY_CONTEXT_FILES:
            local = target / filename
            if not local.is_file() or local.is_symlink() or local not in duplicate_paths:
                continue
            digest = file_digest(local)
            inherited = _safe_inherited_source(target, os_root, filename, digest)
            if inherited is None:
                continue
            content = local.read_bytes()
            actions.append(
                {
                    "action": "remove_inherited_duplicate",
                    "object": relative_object,
                    "target": local.relative_to(os_root).as_posix(),
                    "status": "proposed",
                    "sha256_before": digest,
                    "bytes_before": len(content),
                    "inherited_from": inherited.relative_to(os_root).as_posix(),
                    "inherited_sha256": digest,
                }
            )
            rollback_files.append(
                {
                    "path": local.relative_to(os_root).as_posix(),
                    "sha256": digest,
                    "content_base64": base64.b64encode(content).decode("ascii"),
                }
            )

    actions.sort(key=lambda action: (action["target"], action["action"]))
    rollback_files.sort(key=lambda item: item["path"])
    proposed = [action for action in actions if action["status"] == "proposed"]
    candidate_targets = sorted(
        {os_root / str(action["object"]) for action in proposed if action.get("object")}
    )
    reductions = _target_reductions(os_root, candidate_targets, proposed)
    local_before = sum(item["bytes_before"] for item in reductions.values())
    local_after = sum(item["bytes_after"] for item in reductions.values())
    aggregate_ratio = (local_before - local_after) / local_before if local_before else 0.0
    state_paths = sorted(
        {
            str(action[key])
            for action in proposed
            for key in ("target", "source", "inherited_from")
            if action.get(key)
        }
    )
    extra_paths = [_bounded_path(os_root, path) for path in state_paths]
    check_before = check_context_contracts(os_root)
    validation_before = None
    if capture_validation_baseline:
        baseline_errors = _validation_errors(os_root, validation_validator)
        validation_before = _validation_snapshot(baseline_errors)
    plan: dict[str, Any] = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "mode": "dry_run",
        "root": str(os_root),
        "selection": {
            "targets": [target.relative_to(os_root).as_posix() for target in targets],
            "promote_legacy": promote_legacy,
        },
        "state_paths": state_paths,
        "root_state_sha256_before": _root_state_hash(os_root, targets, extra_paths),
        "context_check_before": check_before.as_dict(),
        "validation_before": validation_before,
        "semantic_before": _semantic_snapshot(os_root, candidate_targets),
        "target_reductions": reductions,
        "summary": {
            "targets_scanned": len(targets),
            "targets_migrated": len(candidate_targets),
            "actions": len(actions),
            "proposed_actions": len(proposed),
            "proposed_removals": sum(str(action["action"]).startswith("remove_") for action in proposed),
            "blocked_actions": sum(action["status"] == "blocked" for action in actions),
            "duplicate_groups": len(duplicate_groups),
            "files_preserved_in_rollback": len(rollback_files),
            "local_context_bytes_before": local_before,
            "local_context_bytes_after": local_after,
            "candidate_bytes_removed": sum(item["bytes_removed"] for item in reductions.values()),
            "candidate_reduction_ratio": aggregate_ratio,
            "minimum_reduction_ratio": MINIMUM_REDUCTION_RATIO,
        },
        "actions": actions,
        "rollback_manifest": {
            "schema_version": 1,
            "operation": "context_compact",
            "files": rollback_files,
        },
    }
    hashable = {key: value for key, value in plan.items() if key != "rollback_manifest"}
    plan["plan_sha256"] = _canonical_hash(hashable)
    return plan


def write_compaction_plan(
    root: str | Path,
    output_dir: str | Path,
    *,
    target_paths: Iterable[str | Path] = (),
    promote_legacy: bool = False,
    capture_validation_baseline: bool = False,
    validation_validator: Callable[[Path], Any] | None = None,
) -> tuple[Path, Path, dict[str, Any]]:
    plan = build_compaction_plan(
        root,
        target_paths=target_paths,
        promote_legacy=promote_legacy,
        capture_validation_baseline=capture_validation_baseline,
        validation_validator=validation_validator,
    )
    directory = Path(output_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    plan_path = directory / "context-compaction-plan.json"
    rollback_path = directory / "context-compaction-rollback.json"
    _write_json(plan_path, {key: value for key, value in plan.items() if key != "rollback_manifest"})
    _write_json(rollback_path, plan["rollback_manifest"])
    return plan_path, rollback_path, plan


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _load_and_verify_plan(plan_path: str | Path) -> dict[str, Any]:
    path = Path(plan_path).expanduser().resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise ValueError(f"unsupported context compaction plan: {path}")
    expected = data.get("plan_sha256")
    actual = _canonical_hash({key: value for key, value in data.items() if key != "plan_sha256"})
    if expected != actual:
        raise ValueError(f"context compaction plan hash mismatch: expected {expected}, got {actual}")
    return data


def _validation_errors(root: Path, validator: Callable[[Path], Any] | None) -> list[str]:
    if validator is None:
        from .validate import validate_root

        validator = validate_root
    result = validator(root)
    if isinstance(result, list):
        return [str(item) for item in result]
    return [str(item) for item in getattr(result, "errors", [])]


def _validation_snapshot(errors: Iterable[str]) -> dict[str, Any]:
    normalized = sorted(set(str(item) for item in errors))
    return {
        "error_count": len(normalized),
        "errors_sha256": _canonical_hash({"errors": normalized}),
        "errors": normalized,
    }


def _capture_before(root: Path, relative_paths: Iterable[str]) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for relative in sorted(set(relative_paths)):
        path = _bounded_path(root, relative)
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError(f"migration receipt path is not a regular file or absent: {relative}")
        entry: dict[str, Any] = {"path": relative, "exists_before": path.is_file()}
        if path.is_file():
            content = path.read_bytes()
            entry.update(
                {
                    "sha256_before": hashlib.sha256(content).hexdigest(),
                    "bytes_before": len(content),
                    "mode_before": path.stat().st_mode & 0o777,
                    "content_base64": base64.b64encode(content).decode("ascii"),
                }
            )
        files.append(entry)
    return files


def _restore_receipt_files(root: Path, files: Iterable[Mapping[str, Any]]) -> None:
    for entry in reversed(list(files)):
        path = _bounded_path(root, str(entry["path"]))
        exists_before = bool(entry.get("exists_before", True))
        if not exists_before:
            if path.is_file() or path.is_symlink():
                path.unlink()
            elif path.exists():
                raise ValueError(f"cannot remove non-file rollback path: {entry['path']}")
            continue
        content = base64.b64decode(str(entry["content_base64"]), validate=True)
        if hashlib.sha256(content).hexdigest() != entry["sha256_before"]:
            raise ValueError(f"rollback payload hash mismatch: {entry['path']}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        if "mode_before" in entry:
            path.chmod(int(entry["mode_before"]))


def _verify_after_state(root: Path, files: Iterable[Mapping[str, Any]]) -> None:
    for entry in files:
        path = _bounded_path(root, str(entry["path"]))
        if entry.get("exists_after"):
            if not path.is_file() or file_digest(path) != entry.get("sha256_after"):
                raise ValueError(f"post-apply file changed: {entry['path']}")
        elif path.exists():
            raise ValueError(f"post-apply removed file reappeared: {entry['path']}")


def apply_compaction_plan(
    root: str | Path,
    plan_path: str | Path,
    receipt_dir: str | Path,
    *,
    validator: Callable[[Path], Any] | None = None,
) -> dict[str, Any]:
    """Apply a reviewed plan, rolling back automatically on any failed gate."""

    os_root = expand_path(root)
    plan = _load_and_verify_plan(plan_path)
    if Path(str(plan["root"])).resolve() != os_root:
        raise ValueError(f"plan root {plan['root']} does not match apply root {os_root}")
    if int(plan["summary"].get("blocked_actions", 0)):
        raise ValueError("context compaction plan contains blocked actions")
    targets = _selected_targets(os_root, plan["selection"]["targets"])
    state_paths = [str(path) for path in plan.get("state_paths", [])]
    extra_paths = [_bounded_path(os_root, path) for path in state_paths]
    current_root_hash = _root_state_hash(os_root, targets, extra_paths)
    if current_root_hash != plan["root_state_sha256_before"]:
        raise ValueError("context root changed after planning; build and review a fresh plan")
    actions = [action for action in plan["actions"] if action.get("status") == "proposed"]
    if not actions:
        raise ValueError("context compaction plan contains no proposed actions")

    reductions = _target_reductions(os_root, targets, actions)
    for target, reduction in reductions.items():
        if reduction["reduction_ratio"] < MINIMUM_REDUCTION_RATIO:
            raise ValueError(
                f"planned context reduction for {target} is {reduction['reduction_ratio']:.1%}; "
                f"required {MINIMUM_REDUCTION_RATIO:.0%}"
            )
        if reduction != plan.get("target_reductions", {}).get(target):
            raise ValueError(f"context reduction changed after planning: {target}")

    planned_creates = {
        str(action["target"]): str(action["sha256_after"])
        for action in actions
        if str(action["action"]).startswith("create_")
    }
    action_targets: set[Path] = set()
    for action in actions:
        kind = str(action["action"])
        path = _bounded_path(os_root, str(action["target"]))
        object_root = _bounded_path(os_root, str(action["object"]))
        action_targets.add(object_root)
        if kind == "create_inherited_contract":
            source = _bounded_path(os_root, str(action["source"]))
            if path.exists() or path.name not in LEGACY_CONTEXT_FILES:
                raise ValueError(f"unsafe inherited contract creation: {action['target']}")
            if not source.is_file() or file_digest(source) != action["sha256_after"]:
                raise ValueError(f"promotion source changed: {action['source']}")
        elif kind == "create_manifest":
            content = base64.b64decode(str(action["content_base64"]), validate=True)
            if path.exists() or path.name != CONTRACT_FILENAME:
                raise ValueError(f"unsafe manifest creation: {action['target']}")
            if hashlib.sha256(content).hexdigest() != action["sha256_after"]:
                raise ValueError(f"manifest payload hash mismatch: {action['target']}")
            if load_context_manifest(object_root) is not None:
                raise ValueError(f"target manifest appeared after planning: {action['object']}")
        elif kind in {"remove_promoted_contract", "remove_inherited_duplicate"}:
            inherited = _bounded_path(os_root, str(action["inherited_from"]))
            if path.name not in LEGACY_CONTEXT_FILES or path.is_symlink() or not path.is_file():
                raise ValueError(f"unsafe or missing compaction target: {action['target']}")
            if file_digest(path) != action["sha256_before"]:
                raise ValueError(f"compaction target hash changed: {action['target']}")
            inherited_hash = file_digest(inherited) if inherited.is_file() else planned_creates.get(str(action["inherited_from"]))
            if inherited_hash != action["inherited_sha256"]:
                raise ValueError(f"inherited source hash changed: {action['inherited_from']}")
            current_manifest = load_context_manifest(object_root)
            manifest_planned = str(object_root.relative_to(os_root) / CONTRACT_FILENAME) in planned_creates
            if current_manifest is None and not manifest_planned:
                raise ValueError(f"target has no current or planned manifest: {action['object']}")
        else:
            raise ValueError(f"unsupported proposed action: {kind}")

    semantic_before = _semantic_snapshot(os_root, action_targets)
    if semantic_before != plan.get("semantic_before"):
        raise ValueError("semantic context changed after planning; build and review a fresh plan")
    mutated_paths = [str(action["target"]) for action in actions]
    receipt_files = _capture_before(os_root, mutated_paths)
    check_before = check_context_contracts(os_root)
    planned_validation_before = plan.get("validation_before")
    validation_before = None
    if planned_validation_before is not None:
        validation_before = _validation_snapshot(_validation_errors(os_root, validator))
        if validation_before != planned_validation_before:
            raise ValueError("installed-root validation baseline changed after planning")
    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "operation": "context_compact_apply",
        "status": "prepared",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "root": str(os_root),
        "plan_sha256": plan["plan_sha256"],
        "state_paths": state_paths,
        "selection": plan["selection"],
        "root_state_sha256_before": current_root_hash,
        "root_state_sha256_after": None,
        "semantic_before": semantic_before,
        "semantic_after": None,
        "target_reductions": reductions,
        "context_check_before": check_before.as_dict(),
        "context_check_after": None,
        "validation_before": validation_before,
        "validation_after": None,
        "summary": {
            "files_created": sum(str(action["action"]).startswith("create_") for action in actions),
            "files_removed": sum(str(action["action"]).startswith("remove_") for action in actions),
            "local_context_bytes_before": sum(item["bytes_before"] for item in reductions.values()),
            "local_context_bytes_after": sum(item["bytes_after"] for item in reductions.values()),
            "reduction_ratio": plan["summary"]["candidate_reduction_ratio"],
        },
        "validation_errors": [],
        "files": receipt_files,
    }
    receipt_path = Path(receipt_dir).expanduser().resolve() / f"context-compaction-{plan['plan_sha256'][:12]}.json"
    _write_json(receipt_path, receipt)

    try:
        for action in actions:
            if action["action"] == "create_inherited_contract":
                source = _bounded_path(os_root, str(action["source"]))
                target = _bounded_path(os_root, str(action["target"]))
                target.write_bytes(source.read_bytes())
                target.chmod(source.stat().st_mode & 0o777)
            elif action["action"] == "create_manifest":
                target = _bounded_path(os_root, str(action["target"]))
                target.write_bytes(base64.b64decode(str(action["content_base64"]), validate=True))
            elif str(action["action"]).startswith("remove_"):
                _bounded_path(os_root, str(action["target"])).unlink()

        semantic_after = _semantic_snapshot(os_root, action_targets)
        if semantic_after != semantic_before:
            raise ValueError("resolved context semantics changed after compaction")
        check_after = check_context_contracts(os_root)
        validation_after = _validation_snapshot(_validation_errors(os_root, validator))
        if validation_before is None:
            regression_errors = validation_after["errors"]
        else:
            regression_errors = sorted(set(validation_after["errors"]) - set(validation_before["errors"]))
        errors = check_after.errors + regression_errors
        if errors:
            receipt["validation_errors"] = errors
            raise ValueError("post-apply validation failed or regressed: " + "; ".join(errors[:5]))
        for entry in receipt_files:
            current = _bounded_path(os_root, str(entry["path"]))
            entry["exists_after"] = current.is_file()
            entry["sha256_after"] = file_digest(current) if current.is_file() else None
        receipt["status"] = "applied"
        receipt["semantic_after"] = semantic_after
        receipt["context_check_after"] = check_after.as_dict()
        receipt["validation_after"] = validation_after
        receipt["root_state_sha256_after"] = _root_state_hash(os_root, targets, extra_paths)
        receipt["completed_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(receipt_path, receipt)
        return {**receipt, "receipt_path": str(receipt_path)}
    except Exception as exc:
        try:
            _restore_receipt_files(os_root, receipt_files)
            restored_hash = _root_state_hash(os_root, targets, extra_paths)
            if restored_hash != current_root_hash:
                raise ValueError("automatic rollback did not restore the planned root hash")
            receipt["status"] = "rolled_back"
            receipt["rollback_reason"] = str(exc)
            receipt["rolled_back_at"] = datetime.now(timezone.utc).isoformat()
            _write_json(receipt_path, receipt)
        except Exception as rollback_exc:
            receipt["status"] = "rollback_failed"
            receipt["rollback_reason"] = str(exc)
            receipt["rollback_error"] = str(rollback_exc)
            _write_json(receipt_path, receipt)
            raise RuntimeError(f"compaction failed and rollback failed: {rollback_exc}") from exc
        raise ValueError(f"compaction failed and was rolled back: {exc}") from exc


def restore_compaction_receipt(root: str | Path, receipt_path: str | Path) -> dict[str, Any]:
    """Restore exact pre-apply bytes after verifying applied state is unchanged."""

    os_root = expand_path(root)
    path = Path(receipt_path).expanduser().resolve()
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("schema_version") not in {1, RECEIPT_SCHEMA_VERSION} or receipt.get("operation") != "context_compact_apply":
        raise ValueError(f"unsupported context compaction receipt: {path}")
    if receipt.get("status") != "applied":
        raise ValueError(f"receipt is not in applied state: {receipt.get('status')}")
    if Path(str(receipt["root"])).resolve() != os_root:
        raise ValueError(f"receipt root {receipt['root']} does not match restore root {os_root}")
    targets = _selected_targets(os_root, receipt.get("selection", {}).get("targets", []))
    extra_paths = [_bounded_path(os_root, value) for value in receipt.get("state_paths", [])]
    is_v1 = receipt.get("schema_version") == 1
    current_hash = (
        _legacy_v1_root_state_hash(os_root, targets)
        if is_v1
        else _root_state_hash(os_root, targets, extra_paths)
    )
    if current_hash != receipt.get("root_state_sha256_after"):
        raise ValueError("context root changed after apply; refusing to overwrite newer work")
    normalized_files: list[dict[str, Any]] = []
    for original in receipt["files"]:
        entry = dict(original)
        entry.setdefault("exists_before", True)
        entry.setdefault("exists_after", False)
        normalized_files.append(entry)
    _verify_after_state(os_root, normalized_files)
    _restore_receipt_files(os_root, normalized_files)
    restored_hash = (
        _legacy_v1_root_state_hash(os_root, targets)
        if is_v1
        else _root_state_hash(os_root, targets, extra_paths)
    )
    if restored_hash != receipt["root_state_sha256_before"]:
        raise ValueError("restore completed but exact pre-apply root hash was not recovered")
    receipt["status"] = "restored"
    receipt["restored_at"] = datetime.now(timezone.utc).isoformat()
    receipt["root_state_sha256_restored"] = restored_hash
    _write_json(path, receipt)
    return {**receipt, "receipt_path": str(path)}
