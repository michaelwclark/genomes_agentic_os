"""Guarded post-release library reinstall orchestration.

The watcher is deliberately local to one installed OS root.  A target host runs
the same command itself after an upstream release reader has written a compact
published-release receipt.  It never opens an SSH connection or invents a
release: release publication and destructive apply authority remain separate
operator controls.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Mapping

from .library import install_library, rollback_library_install, verify_library_install
from .scaffold import expand_path, harness_path
from .update_ops import lock_data, now_stamp, read_structured


API_VERSION = "agentic-os-release-reinstall/v1"
STATE_PATH = Path("runtime/state/release-reinstall.json")
ROLLBACK_DRILL_MARKER = Path(".agentic-os-rollback-drill")
_SEMVER = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _version(value: object) -> tuple[int, int, int]:
    match = _SEMVER.fullmatch(str(value or "").strip())
    if not match:
        raise ValueError("release and installed versions must be stable SemVer (for example 1.2.3)")
    return tuple(int(part) for part in match.groups())


def _safe_relative(path: object, *, parent: Path) -> Path:
    candidate = Path(str(path or ""))
    if not str(candidate) or candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("release receipt contains an unsafe rollback path")
    if not candidate.is_relative_to(parent):
        raise ValueError("release receipt rollback path is outside runtime backups")
    return candidate


def load_release_receipt(path: str | Path) -> dict[str, Any]:
    receipt_path = expand_path(path)
    receipt = read_structured(receipt_path)
    if not isinstance(receipt, dict):
        raise ValueError(f"release receipt is missing or invalid: {receipt_path}")
    if receipt.get("published") is not True or receipt.get("draft") is True:
        raise ValueError("release receipt must prove a published, non-draft release")
    version = str(receipt.get("version") or "").removeprefix("v")
    _version(version)
    tag = str(receipt.get("tag") or "")
    if tag != f"v{version}":
        raise ValueError("release receipt tag must equal v<version>")
    normalized = dict(receipt)
    normalized["version"] = version
    normalized["tag"] = tag
    return normalized


def _state_path(root: Path) -> Path:
    return root / STATE_PATH


def _load_state(root: Path) -> dict[str, Any]:
    path = _state_path(root)
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_state(root: Path, value: Mapping[str, Any]) -> Path:
    path = _state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def update_policy_decision(root: str | Path, version: str) -> dict[str, Any]:
    """Classify a published release without weakening the major-version gate."""

    os_root = expand_path(root)
    target = _version(version)
    lock = lock_data(os_root)
    installed_text = str(lock["installed_version"])
    installed = _version(installed_text)
    policy = str(lock["update_policy"] or "operator_approved")
    if target <= installed:
        return {
            "status": "blocked",
            "reason": "release is not newer than the installed version",
            "installed_version": installed_text,
            "available_version": version,
            "policy": policy,
        }
    level = "major" if target[0] != installed[0] else ("minor" if target[1] != installed[1] else "patch")
    approval_required = level == "major" or policy != "auto_patch_minor"
    return {
        "status": "approval_required" if approval_required else "eligible",
        "reason": (
            "major releases require explicit operator approval"
            if level == "major"
            else ("installed update policy requires operator approval" if approval_required else "patch/minor auto-apply policy")
        ),
        "installed_version": installed_text,
        "available_version": version,
        "release_level": level,
        "policy": policy,
        "approval_required": approval_required,
    }


def verify_reinstall(root: str | Path, release: Mapping[str, Any]) -> dict[str, Any]:
    """Prove a reinstall's current and retained-generation receipts agree."""

    os_root = expand_path(root)
    errors: list[str] = []
    verification = verify_library_install(os_root)
    receipt_path = os_root / "runtime/state/library-install.json"
    receipt = read_structured(receipt_path)
    if verification.get("status") != "verified":
        errors.append("library install receipt or projection verification failed")
    if not isinstance(receipt, dict) or receipt.get("status") != "installed":
        errors.append("current library install receipt is missing or invalid")
    else:
        if receipt.get("source_revision") != release.get("source_revision") and release.get("source_revision"):
            errors.append("installed source revision differs from the published release receipt")
        if not isinstance(receipt.get("object_count"), int) or receipt["object_count"] < 0:
            errors.append("install receipt object_count is invalid")
        for field in ("content_sha256", "projection_sha256"):
            if not _SHA256.fullmatch(str(receipt.get(field) or "")):
                errors.append(f"install receipt {field} is invalid")
        previous_content = receipt.get("previous_content_sha256")
        previous_projection = receipt.get("previous_projection_sha256")
        if (previous_content is None) != (previous_projection is None):
            errors.append("prior-generation receipt hashes are incomplete")
        if previous_content is not None and not _SHA256.fullmatch(str(previous_content)):
            errors.append("prior-generation content hash is invalid")
        if previous_projection is not None and not _SHA256.fullmatch(str(previous_projection)):
            errors.append("prior-generation projection hash is invalid")
        if receipt.get("rollback_available") is True:
            try:
                _safe_relative(receipt.get("rollback_path"), parent=Path("runtime/backups/library"))
                _safe_relative(receipt.get("rollback_receipt"), parent=Path("runtime/backups/library-receipts"))
                rollback_plan = rollback_library_install(os_root, dry_run=True)
                if rollback_plan.get("status") != "planned":
                    errors.append("retained rollback generation is not executable")
                elif rollback_plan.get("projection_sha256") != previous_projection:
                    errors.append("retained rollback projection differs from previous receipt")
            except ValueError as exc:
                errors.append(str(exc))
    return {
        "api_version": API_VERSION,
        "action": "release-reinstall.verify",
        "status": "verified" if not errors else "failed",
        "release": {"version": release.get("version"), "tag": release.get("tag")},
        "receipt": "runtime/state/library-install.json",
        "verification": verification,
        "errors": errors,
    }


def watch_release(
    root: str | Path,
    *,
    release_receipt: str | Path,
    repository: str | None = None,
    apply: bool = False,
    approve_major: bool = False,
    approve_release: bool = False,
) -> dict[str, Any]:
    """Detect one new published release and optionally reinstall this local target."""

    os_root = expand_path(root)
    release = load_release_receipt(release_receipt)
    decision = update_policy_decision(os_root, str(release["version"]))
    prior = _load_state(os_root)
    if (prior.get("last_release") or {}).get("tag") == release["tag"]:
        result = verify_reinstall(os_root, release)
        return {
            "api_version": API_VERSION,
            "action": "release-reinstall.watch",
            "status": "already_processed" if result["status"] == "verified" else "reinstall_required",
            "release": release,
            "policy": decision,
            "verification": result,
            "mutated": False,
        }
    if decision["status"] == "blocked":
        return {
            "api_version": API_VERSION,
            "action": "release-reinstall.watch",
            "status": "blocked",
            "release": release,
            "policy": decision,
            "mutated": False,
        }
    approval_granted = approve_major if decision["release_level"] == "major" else approve_release
    if decision["approval_required"] and not approval_granted:
        return {
            "api_version": API_VERSION,
            "action": "release-reinstall.watch",
            "status": "approval_required",
            "release": release,
            "policy": decision,
            "mutated": False,
        }
    if not apply:
        return {
            "api_version": API_VERSION,
            "action": "release-reinstall.watch",
            "status": "planned",
            "release": release,
            "policy": decision,
            "repository_required": not bool(repository),
            "mutated": False,
        }

    installed = install_library(
        os_root,
        repository=repository,
        ref=str(release["tag"]),
        dry_run=False,
    )
    if installed.get("status") != "installed":
        return {
            "api_version": API_VERSION,
            "action": "release-reinstall.watch",
            "status": "blocked",
            "release": release,
            "policy": decision,
            "install": installed,
            "mutated": False,
        }
    verification = verify_reinstall(os_root, release)
    if verification["status"] != "verified":
        rollback = rollback_library_install(os_root, dry_run=False)
        return {
            "api_version": API_VERSION,
            "action": "release-reinstall.watch",
            "status": "rolled_back" if rollback.get("status") == "rolled_back" else "failed",
            "release": release,
            "policy": decision,
            "install": installed,
            "verification": verification,
            "rollback": rollback,
            "mutated": True,
        }
    state_path = _write_state(
        os_root,
        {
            "api_version": API_VERSION,
            "last_release": {"version": release["version"], "tag": release["tag"]},
            "source_revision": installed.get("source_revision"),
            "verification": verification,
            "updated_at": now_stamp(),
        },
    )
    return {
        "api_version": API_VERSION,
        "action": "release-reinstall.watch",
        "status": "reinstalled",
        "release": release,
        "policy": decision,
        "install": installed,
        "verification": verification,
        "state": str(state_path),
        "mutated": True,
    }


def rollback_drill(root: str | Path, *, apply: bool = False) -> dict[str, Any]:
    """Exercise the one-command library rollback only in a marked test target."""

    os_root = expand_path(root)
    marker = os_root / ROLLBACK_DRILL_MARKER
    if not marker.is_file():
        return {
            "api_version": API_VERSION,
            "action": "release-reinstall.rollback-drill",
            "status": "blocked",
            "blocker": f"test target marker is required: {ROLLBACK_DRILL_MARKER.as_posix()}",
            "mutated": False,
        }
    plan = rollback_library_install(os_root, dry_run=True)
    if plan.get("status") != "planned" or not apply:
        return {
            "api_version": API_VERSION,
            "action": "release-reinstall.rollback-drill",
            "status": "planned" if plan.get("status") == "planned" else "blocked",
            "rollback": plan,
            "mutated": False,
        }
    rollback = rollback_library_install(os_root, dry_run=False)
    verified = verify_library_install(os_root)
    status = "completed" if rollback.get("status") == "rolled_back" and verified.get("status") == "verified" else "failed"
    return {
        "api_version": API_VERSION,
        "action": "release-reinstall.rollback-drill",
        "status": status,
        "rollback": rollback,
        "verification": verified,
        "mutated": True,
    }
