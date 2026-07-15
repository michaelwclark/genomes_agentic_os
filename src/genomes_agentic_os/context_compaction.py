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

from .context_contracts import load_context_manifest, resolve_context_contract
from .scaffold import expand_path


CONTRACT_FILENAME = "context-contract.yml"
LEGACY_CONTEXT_FILES = ("ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md")
LOCAL_CONTEXT_FILES = (
    "AGENTS.md",
    "PROFILE.md",
    "CLAUDE.md",
    CONTRACT_FILENAME,
    *LEGACY_CONTEXT_FILES,
    "workflow.md",
    "automation.md",
    "quick-reference.md",
    "context-pack.md",
    "permissions.md",
    "approval-rules.md",
    "runbook.md",
)
PLAN_SCHEMA_VERSION = 2
RECEIPT_SCHEMA_VERSION = 1
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
    """Return active workflow/automation folders without traversing evidence trees."""

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
        if current == root:
            return None
        if root not in current.parents:
            return None
        current = current.parent


def _local_context_bytes(targets: Iterable[Path]) -> int:
    return sum(
        path.stat().st_size
        for target in targets
        for filename in LOCAL_CONTEXT_FILES
        if (path := target / filename).is_file() and not path.is_symlink()
    )


def _root_state_hash(root: Path, targets: Iterable[Path]) -> str:
    state: list[dict[str, Any]] = []
    for target in targets:
        for filename in LOCAL_CONTEXT_FILES:
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


def _semantic_snapshot(root: Path, targets: Iterable[Path]) -> dict[str, Any]:
    snapshots: dict[str, Any] = {}
    for target in sorted(set(targets)):
        resolved = resolve_context_contract(target, root=root)
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
        providers = {
            key: entry.get("value")
            for key, entry in sorted(resolved.providers.items())
        }
        value = {
            "ok": resolved.ok,
            "legacy_fallback": resolved.legacy_fallback,
            "source_content_sha256": source_hashes,
            "excluded": sorted(set(resolved.excluded)),
            "capabilities": capabilities,
            "providers": providers,
            "diagnostic_codes": sorted(item.code for item in resolved.diagnostics),
        }
        value["semantic_sha256"] = _canonical_hash(value)
        snapshots[target.relative_to(root).as_posix()] = value
    return snapshots


def build_compaction_plan(root: str | Path) -> dict[str, Any]:
    """Build a deterministic plan containing only inherited, byte-identical removals."""

    os_root = expand_path(root)
    targets = managed_context_targets(os_root)
    duplicate_groups = duplicate_legacy_groups(targets)
    duplicate_paths = {path for paths in duplicate_groups.values() for path in paths}
    actions: list[dict[str, Any]] = []
    rollback_files: list[dict[str, Any]] = []

    for target in targets:
        manifest_path = target / CONTRACT_FILENAME
        try:
            manifest = load_context_manifest(manifest_path) if manifest_path.is_file() else None
        except (OSError, ValueError, yaml.YAMLError):
            manifest = None
        relative_target = target.relative_to(os_root).as_posix()
        if manifest is None:
            actions.append(
                {
                    "action": "create_manifest",
                    "target": relative_target,
                    "status": "review_required",
                    "reason": "legacy object has no valid context contract",
                }
            )
            continue
        if "parent" not in manifest.inherits and "domain" not in manifest.inherits:
            continue
        for filename in LEGACY_CONTEXT_FILES:
            path = target / filename
            if not path.is_file() or path.is_symlink() or path not in duplicate_paths:
                continue
            digest = file_digest(path)
            inherited = _safe_inherited_source(target, os_root, filename, digest)
            if inherited is None:
                continue
            content = path.read_bytes()
            relative_path = path.relative_to(os_root).as_posix()
            actions.append(
                {
                    "action": "remove_inherited_duplicate",
                    "target": relative_path,
                    "status": "proposed",
                    "sha256_before": digest,
                    "bytes_before": len(content),
                    "inherited_from": inherited.relative_to(os_root).as_posix(),
                    "inherited_sha256": file_digest(inherited),
                }
            )
            rollback_files.append(
                {
                    "path": relative_path,
                    "sha256": digest,
                    "content_base64": base64.b64encode(content).decode("ascii"),
                }
            )

    actions.sort(key=lambda action: (action["target"], action["action"]))
    rollback_files.sort(key=lambda item: item["path"])
    candidate_actions = [action for action in actions if action["status"] == "proposed"]
    candidate_bytes = sum(int(action["bytes_before"]) for action in candidate_actions)
    local_bytes = _local_context_bytes(targets)
    reduction_ratio = candidate_bytes / local_bytes if local_bytes else 0.0
    candidate_targets = sorted({(os_root / action["target"]).parent for action in candidate_actions})
    plan: dict[str, Any] = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "mode": "dry_run",
        "root": str(os_root),
        "root_state_sha256_before": _root_state_hash(os_root, targets),
        "semantic_before": _semantic_snapshot(os_root, candidate_targets),
        "summary": {
            "targets": len(targets),
            "actions": len(actions),
            "proposed_removals": len(candidate_actions),
            "duplicate_groups": len(duplicate_groups),
            "files_preserved_in_rollback": len(rollback_files),
            "local_context_bytes_before": local_bytes,
            "candidate_bytes_removed": candidate_bytes,
            "candidate_reduction_ratio": reduction_ratio,
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


def write_compaction_plan(root: str | Path, output_dir: str | Path) -> tuple[Path, Path, dict[str, Any]]:
    plan = build_compaction_plan(root)
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


def _bounded_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if path == root or root not in path.parents:
        raise ValueError(f"migration path is outside root: {relative}")
    return path


def _validation_errors(root: Path, validator: Callable[[Path], Any] | None) -> list[str]:
    if validator is None:
        from .validate import validate_root

        validator = validate_root
    result = validator(root)
    if isinstance(result, list):
        return [str(item) for item in result]
    return [str(item) for item in getattr(result, "errors", [])]


def _restore_exact_files(root: Path, files: Iterable[Mapping[str, Any]]) -> None:
    for entry in files:
        path = _bounded_path(root, str(entry["path"]))
        content = base64.b64decode(str(entry["content_base64"]), validate=True)
        if hashlib.sha256(content).hexdigest() != entry["sha256_before"]:
            raise ValueError(f"rollback payload hash mismatch: {entry['path']}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        if "mode_before" in entry:
            path.chmod(int(entry["mode_before"]))


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
    targets = managed_context_targets(os_root)
    current_root_hash = _root_state_hash(os_root, targets)
    if current_root_hash != plan["root_state_sha256_before"]:
        raise ValueError("context root changed after planning; build and review a fresh plan")

    actions = [action for action in plan["actions"] if action.get("status") == "proposed"]
    if not actions:
        raise ValueError("context compaction plan contains no proposed removals")
    current_local_bytes = _local_context_bytes(targets)
    planned_removed_bytes = sum(int(action.get("bytes_before", 0)) for action in actions)
    ratio = planned_removed_bytes / current_local_bytes if current_local_bytes else 0.0
    if ratio < MINIMUM_REDUCTION_RATIO:
        raise ValueError(
            f"planned context reduction {ratio:.1%} is below required {MINIMUM_REDUCTION_RATIO:.0%}"
        )

    receipt_files: list[dict[str, Any]] = []
    action_targets: set[Path] = set()
    for action in actions:
        if action.get("action") != "remove_inherited_duplicate":
            raise ValueError(f"unsupported proposed action: {action.get('action')}")
        path = _bounded_path(os_root, str(action["target"]))
        inherited = _bounded_path(os_root, str(action["inherited_from"]))
        if path.name not in LEGACY_CONTEXT_FILES or path.is_symlink() or not path.is_file():
            raise ValueError(f"unsafe or missing compaction target: {action['target']}")
        if file_digest(path) != action["sha256_before"]:
            raise ValueError(f"compaction target hash changed: {action['target']}")
        if not inherited.is_file() or file_digest(inherited) != action["inherited_sha256"]:
            raise ValueError(f"inherited source hash changed: {action['inherited_from']}")
        manifest = load_context_manifest(path.parent / CONTRACT_FILENAME)
        if manifest is None or not ({"parent", "domain"} & set(manifest.inherits)):
            raise ValueError(f"target no longer inherits parent context: {path.parent}")
        content = path.read_bytes()
        receipt_files.append(
            {
                "path": action["target"],
                "sha256_before": file_digest(path),
                "bytes_before": len(content),
                "mode_before": path.stat().st_mode & 0o777,
                "content_base64": base64.b64encode(content).decode("ascii"),
                "sha256_after": None,
            }
        )
        action_targets.add(path.parent)

    semantic_before = _semantic_snapshot(os_root, action_targets)
    if semantic_before != plan.get("semantic_before"):
        raise ValueError("semantic context changed after planning; build and review a fresh plan")
    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "operation": "context_compact_apply",
        "status": "prepared",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "root": str(os_root),
        "plan_sha256": plan["plan_sha256"],
        "root_state_sha256_before": current_root_hash,
        "root_state_sha256_after": None,
        "semantic_before": semantic_before,
        "semantic_after": None,
        "summary": {
            "files_removed": len(receipt_files),
            "bytes_before": int(plan["summary"]["local_context_bytes_before"]),
            "bytes_removed": sum(item["bytes_before"] for item in receipt_files),
            "reduction_ratio": ratio,
        },
        "validation_errors": [],
        "files": sorted(receipt_files, key=lambda item: item["path"]),
    }
    receipt_path = Path(receipt_dir).expanduser().resolve() / f"context-compaction-{plan['plan_sha256'][:12]}.json"
    _write_json(receipt_path, receipt)

    try:
        for entry in receipt["files"]:
            _bounded_path(os_root, entry["path"]).unlink()
        semantic_after = _semantic_snapshot(os_root, action_targets)
        if semantic_after != semantic_before:
            raise ValueError("resolved context semantics changed after compaction")
        errors = check_context_contracts(os_root).errors + _validation_errors(os_root, validator)
        if errors:
            receipt["validation_errors"] = errors
            raise ValueError("post-apply validation failed: " + "; ".join(errors[:5]))
        receipt["status"] = "applied"
        receipt["semantic_after"] = semantic_after
        receipt["root_state_sha256_after"] = _root_state_hash(os_root, managed_context_targets(os_root))
        receipt["completed_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(receipt_path, receipt)
        return {**receipt, "receipt_path": str(receipt_path)}
    except Exception as exc:
        try:
            _restore_exact_files(os_root, receipt["files"])
            restored_hash = _root_state_hash(os_root, managed_context_targets(os_root))
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
    """Restore exact pre-apply bytes after verifying the applied state is unchanged."""

    os_root = expand_path(root)
    path = Path(receipt_path).expanduser().resolve()
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION or receipt.get("operation") != "context_compact_apply":
        raise ValueError(f"unsupported context compaction receipt: {path}")
    if receipt.get("status") != "applied":
        raise ValueError(f"receipt is not in applied state: {receipt.get('status')}")
    if Path(str(receipt["root"])).resolve() != os_root:
        raise ValueError(f"receipt root {receipt['root']} does not match restore root {os_root}")
    current_hash = _root_state_hash(os_root, managed_context_targets(os_root))
    if current_hash != receipt.get("root_state_sha256_after"):
        raise ValueError("context root changed after apply; refusing to overwrite newer work")
    for entry in receipt["files"]:
        target = _bounded_path(os_root, entry["path"])
        if target.exists():
            raise ValueError(f"expected compacted file to be absent before restore: {entry['path']}")
    _restore_exact_files(os_root, receipt["files"])
    restored_hash = _root_state_hash(os_root, managed_context_targets(os_root))
    if restored_hash != receipt["root_state_sha256_before"]:
        raise ValueError("restore completed but exact pre-apply root hash was not recovered")
    receipt["status"] = "restored"
    receipt["restored_at"] = datetime.now(timezone.utc).isoformat()
    receipt["root_state_sha256_restored"] = restored_hash
    _write_json(path, receipt)
    return {**receipt, "receipt_path": str(path)}
