"""Local update-channel operations for installed Agentic OS roots."""

from __future__ import annotations

from datetime import datetime, timezone
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
from typing import Any

import yaml

from .scaffold import (
    DEFAULT_UPDATE_CHANNEL,
    DEFAULT_UPDATE_POLICY,
    DEFAULT_PROJECTS_SOURCE,
    SOURCE_PACKAGE_VERSION,
    ScaffoldResult,
    domain_path,
    ensure_default_domains,
    installed_domain_names,
    ensure_project_operating_surface,
    ensure_root_files,
    ensure_update_metadata,
    ensure_visible_capability_surface,
    expand_path,
    harness_path,
    install_docs,
    shared_factory_path,
)


RISKY_CHANGE_TYPES = {"executable", "hook", "mcp", "rule", "permission"}
LEGACY_ROOT_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    "CONTEXT.md",
    "INVENTORY.md",
    "MEMORY.md",
    "PROFILE.md",
    "README.md",
    "ROUTER.md",
    "RULES.md",
    "TOOLS.md",
    "UPDATE_POLICY.md",
    "agentic-os.lock.json",
    "config.toml",
)
LEGACY_ROOT_CAPABILITY_DIRS = (
    "artifact-config",
    "bin",
    "commands",
    "config",
    "hooks",
    "investigation-config",
    "libraries",
    "logs",
    "mcp",
    "plugins",
    "registries",
    "reports",
    "rules",
    "schemas",
    "security",
    "skills",
)
CRITICAL_BACKUP_PATHS = (
    ".agentic_root",
    "lib/",
    "harness/AGENTS.md",
    "harness/artifact-config/",
    "harness/ROUTER.md",
    "harness/CONTEXT.md",
    "harness/RULES.md",
    "harness/TOOLS.md",
    "harness/bin/",
    "harness/commands/",
    "harness/investigation-config/",
    "harness/registries/",
    "harness/reports/",
    "harness/rules/",
    "harness/skills/",
    "harness/shared_factory/00-control-plane/",
)
PROTECTED_RESTORE_PATHS = (
    "projects/",
    "harness/logs/",
    "harness/security/ssh/",
)


def now_stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def path_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def status_path(root: Path) -> Path:
    return harness_path(root, "registries", "update-status.yml")


def plan_path(root: Path) -> Path:
    return harness_path(root, "registries", "update-plan.yml")


def snapshots_dir(root: Path) -> Path:
    return harness_path(root, "logs", "updates", "snapshots")


def read_structured(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        data = json.loads(text)
    else:
        data = yaml.safe_load(text) or {}
    return data if isinstance(data, dict) else {}


def lock_data(root: Path) -> dict[str, Any]:
    data = read_structured(harness_path(root, "agentic-os.lock.json"))
    return {
        "installed_version": data.get("installed_version") or SOURCE_PACKAGE_VERSION,
        "update_channel": data.get("update_channel") or DEFAULT_UPDATE_CHANNEL,
        "update_policy": data.get("update_policy") or DEFAULT_UPDATE_POLICY,
        "status": data.get("status") or "installed",
    }


def local_manifest(root: Path) -> dict[str, Any]:
    lock = lock_data(root)
    updates = read_structured(harness_path(root, "registries", "updates.yml")).get("updates") or {}
    return {
        "version": updates.get("latest_known_version") or SOURCE_PACKAGE_VERSION,
        "channel": updates.get("channel") or lock["update_channel"],
        "policy": updates.get("policy") or lock["update_policy"],
        "changes": [],
        "safe_additive_paths": ["templates", "registries", "commands", "skills", "operating-manual"],
    }


def load_manifest(root: Path, manifest: str | Path | None = None) -> dict[str, Any]:
    if manifest:
        data = read_structured(expand_path(manifest))
        if data:
            return data
    return local_manifest(root)


def risky_changes(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    changes = manifest.get("changes") or []
    return [
        change
        for change in changes
        if isinstance(change, dict) and str(change.get("type") or "").lower() in RISKY_CHANGE_TYPES
    ]


def update_check(root: str | Path, *, manifest: str | Path | None = None) -> dict[str, Any]:
    os_root = expand_path(root)
    lock = lock_data(os_root)
    manifest_data = load_manifest(os_root, manifest)
    latest = str(manifest_data.get("version") or SOURCE_PACKAGE_VERSION)
    installed = str(lock["installed_version"])
    return {
        "root": str(os_root),
        "installed_version": installed,
        "available_version": latest,
        "update_available": latest != installed,
        "channel": manifest_data.get("channel") or lock["update_channel"],
        "policy": manifest_data.get("policy") or lock["update_policy"],
        "mutated": False,
        "risky_changes": risky_changes(manifest_data),
    }


def update_plan(root: str | Path, *, manifest: str | Path | None = None) -> dict[str, Any]:
    os_root = expand_path(root)
    manifest_data = load_manifest(os_root, manifest)
    plan = {
        "created_at": now_stamp(),
        "root": str(os_root),
        "installed": lock_data(os_root),
        "target": {
            "version": manifest_data.get("version") or SOURCE_PACKAGE_VERSION,
            "channel": manifest_data.get("channel") or DEFAULT_UPDATE_CHANNEL,
            "policy": manifest_data.get("policy") or DEFAULT_UPDATE_POLICY,
        },
        "safe_additive_paths": manifest_data.get("safe_additive_paths")
        or ["templates", "registries", "commands", "skills", "operating-manual"],
        "risky_changes": risky_changes(manifest_data),
        "approval_required": bool(risky_changes(manifest_data)),
        "operations": [
            "add missing templates",
            "add missing registry entries",
            "add missing command and skill definitions",
            "preserve existing local edits",
            "run post-update doctor checks",
        ],
    }
    path = plan_path(os_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")
    return {"root": str(os_root), "plan_path": str(path), "plan": plan}


def write_status(root: Path, status: dict[str, Any]) -> None:
    path = status_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(status, sort_keys=False), encoding="utf-8")


def customer_identity_path(root: Path) -> Path:
    return harness_path(root, "registries", "customer-identity.json")


def update_grant_path(root: Path) -> Path:
    return harness_path(root, "registries", "update-grant.json")


def read_customer_identity(root: Path) -> dict[str, Any]:
    data = read_structured(customer_identity_path(root))
    return data if data else {"schema_version": 1, "license": {"status": "inactive"}}


def write_customer_identity(root: Path, data: dict[str, Any]) -> None:
    path = customer_identity_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def activate_license(root: str | Path, *, key: str) -> dict[str, Any]:
    os_root = expand_path(root)
    identity = read_customer_identity(os_root)
    license_data = identity.setdefault("license", {})
    license_data["status"] = "active"
    license_data["activated_at"] = now_stamp()
    license_data["key_hash"] = hashlib.sha256(key.encode("utf-8")).hexdigest()
    identity.setdefault("update_grant", {"status": "not_registered", "path": "harness/registries/update-grant.json"})
    write_customer_identity(os_root, identity)
    return {
        "root": str(os_root),
        "license": {
            "status": license_data["status"],
            "activated_at": license_data["activated_at"],
            "key_hash": license_data["key_hash"],
        },
    }


def ensure_keypair(root: Path, name: str) -> tuple[Path, Path, str]:
    key_dir = harness_path(root, "security", "ssh")
    key_dir.mkdir(parents=True, exist_ok=True)
    private_key = key_dir / name
    public_key = key_dir / f"{name}.pub"
    if private_key.is_file() and public_key.is_file():
        os.chmod(private_key, 0o600)
        return private_key, public_key, public_key.read_text(encoding="utf-8").strip()

    ssh_keygen = shutil.which("ssh-keygen")
    if ssh_keygen:
        subprocess.run(
            [ssh_keygen, "-t", "ed25519", "-N", "", "-C", f"agentic-os-{name}", "-f", str(private_key)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        private_material = f"agentic-os pseudo private key {name} {secrets.token_urlsafe(48)}\n"
        private_key.write_text(private_material, encoding="utf-8")
        public_key.write_text(
            "ssh-ed25519 "
            + hashlib.sha256(private_material.encode("utf-8")).hexdigest()
            + f" agentic-os-{name}\n",
            encoding="utf-8",
        )
    os.chmod(private_key, 0o600)
    return private_key, public_key, public_key.read_text(encoding="utf-8").strip()


def fake_provisioning_response(root: Path, update_public_key: str, backup_public_key: str) -> dict[str, Any]:
    install_id = read_customer_identity(root).get("install_id") or root.name
    safe_id = str(install_id).replace("/", "-") or root.name
    return {
        "provider": "fake",
        "status": "active",
        "expires_at": "2099-12-31T00:00:00Z",
        "remotes": {
            "update": {
                "name": "agentic-os-update",
                "url": f"git@github.com:genome/{safe_id}-agentic-os-updates.git",
                "access": "read-only",
            },
            "backup": {
                "name": "agentic-os-backup",
                "url": f"git@github.com:genome/{safe_id}-agentic-os-backups.git",
                "access": "write",
            },
        },
        "public_keys": {
            "update": update_public_key,
            "backup": backup_public_key,
        },
        "allowed_capabilities": ["templates", "registries", "commands", "skills", "docs", "backups"],
    }


def write_ssh_config(root: Path, grant: dict[str, Any]) -> Path:
    config_path = harness_path(root, "security", "ssh", "config")
    remotes = grant["remotes"]
    config = f"""Host agentic-os-update
  HostName github.com
  User git
  IdentityFile {harness_path(root, "security", "ssh", "update_ed25519")}
  IdentitiesOnly yes
  # Remote: {remotes["update"]["url"]}

Host agentic-os-backup
  HostName github.com
  User git
  IdentityFile {harness_path(root, "security", "ssh", "backup_ed25519")}
  IdentitiesOnly yes
  # Remote: {remotes["backup"]["url"]}
"""
    config_path.write_text(config, encoding="utf-8")
    return config_path


def update_register(root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    identity = read_customer_identity(os_root)
    if identity.get("license", {}).get("status") != "active":
        raise ValueError(
            "billing inactive: activate a customer license before registering update access "
            "(run `agentic-os license activate`)"
        )
    _update_private, _update_public, update_public_key = ensure_keypair(os_root, "update_ed25519")
    _backup_private, _backup_public, backup_public_key = ensure_keypair(os_root, "backup_ed25519")
    grant = {
        "schema_version": 1,
        **fake_provisioning_response(os_root, update_public_key, backup_public_key),
        "registered_at": now_stamp(),
    }
    path = update_grant_path(os_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(grant, indent=2) + "\n", encoding="utf-8")
    config_path = write_ssh_config(os_root, grant)

    identity = read_customer_identity(os_root)
    identity["update_grant"] = {"status": "registered", "path": "harness/registries/update-grant.json", "registered_at": grant["registered_at"]}
    write_customer_identity(os_root, identity)

    return {
        "root": str(os_root),
        "grant_path": str(path),
        "ssh_config": str(config_path),
        "remotes": grant["remotes"],
        "public_keys": grant["public_keys"],
        "private_keys": "stored locally under harness/security/ssh with mode 0600",
    }


def load_update_grant(root: Path) -> dict[str, Any]:
    grant = read_structured(update_grant_path(root))
    if not grant:
        raise ValueError(f"update grant is missing; run update register first: {update_grant_path(root)}")
    return grant


def write_run_log(root: Path, folder: str, prefix: str, payload: dict[str, Any]) -> Path:
    destination = harness_path(root, "logs", folder, f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.yml")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return destination


def backup_logs_dir(root: Path) -> Path:
    return harness_path(root, "logs", "backups")


def _normalize_policy_path(path: str) -> str:
    value = str(path or "").strip()
    if value.startswith("./"):
        value = value[2:]
    return value.rstrip("/")


def _policy_entry_covers(path: str, include_entry: str) -> bool:
    rel = _normalize_policy_path(path)
    include = _normalize_policy_path(include_entry)
    if not include:
        return False
    if any(char in include for char in "*?["):
        return fnmatch.fnmatch(rel, include) or fnmatch.fnmatch(f"{rel}/", include)
    return rel == include or rel.startswith(f"{include}/")


def _policy_covers(path: str, include: list[str]) -> bool:
    return any(_policy_entry_covers(path, entry) for entry in include)


def backup_policy_coverage(root: Path, policy: dict[str, Any]) -> dict[str, Any]:
    include = [str(entry) for entry in (policy.get("include") or [])]
    exclude = [str(entry) for entry in (policy.get("exclude") or [])]
    existing_critical = [
        path
        for path in CRITICAL_BACKUP_PATHS
        if (root / _normalize_policy_path(path)).exists()
    ]
    missing_critical = [
        path
        for path in existing_critical
        if not _policy_covers(path, include)
    ]
    missing_include_paths = [
        path
        for path in include
        if not any(char in path for char in "*?[")
        and not (root / _normalize_policy_path(path)).exists()
    ]
    protected_excluded = [
        path
        for path in PROTECTED_RESTORE_PATHS
        if any(_policy_entry_covers(path, entry) for entry in exclude)
    ]
    return {
        "status": "covered" if not missing_critical else "incomplete",
        "critical_paths": list(CRITICAL_BACKUP_PATHS),
        "covered_critical_paths": [
            path for path in existing_critical if path not in missing_critical
        ],
        "missing_critical_paths": missing_critical,
        "missing_include_paths": missing_include_paths,
        "protected_excluded_paths": protected_excluded,
    }


def update_pull(root: str | Path, *, dry_run: bool = True) -> dict[str, Any]:
    os_root = expand_path(root)
    grant = load_update_grant(os_root)
    payload = {
        "status": "planned" if dry_run else "pulled",
        "dry_run": dry_run,
        "created_at": now_stamp(),
        "remote": grant["remotes"]["update"],
        "allowed_capabilities": grant.get("allowed_capabilities") or [],
        "local_effect": "no network operation performed by V1 dry run" if dry_run else "recorded approved pull intent",
    }
    log_path = write_run_log(os_root, "updates", "update-pull", payload)
    status = {"status": payload["status"], "last_update_log": str(log_path), "checked_at": payload["created_at"]}
    write_status(os_root, status)
    return {"root": str(os_root), "log_path": str(log_path), **payload}


def backup_run(root: str | Path, *, dry_run: bool = True) -> dict[str, Any]:
    os_root = expand_path(root)
    grant = load_update_grant(os_root)
    policy = read_structured(harness_path(os_root, "registries", "backup-policy.yml")).get("backup_policy") or {}
    coverage = backup_policy_coverage(os_root, policy)
    payload = {
        "status": "planned" if dry_run else "completed",
        "dry_run": dry_run,
        "created_at": now_stamp(),
        "remote": grant["remotes"]["backup"],
        "include": policy.get("include") or [],
        "exclude": policy.get("exclude") or [],
        "coverage": coverage,
        "manifest": [] if dry_run else sorted(policy.get("include") or []),
    }
    log_path = write_run_log(os_root, "backups", "backup", payload)
    return {"root": str(os_root), "log_path": str(log_path), **payload}


def backup_push(root: str | Path) -> dict[str, Any]:
    """Record a local backup push run log.

    When no update grant is present (not yet registered) the remote push is
    skipped and the log records ``remote_skipped: true``.  A local log entry
    is always written so the operator can audit what happened.
    """
    os_root = expand_path(root)
    policy = read_structured(harness_path(os_root, "registries", "backup-policy.yml")).get("backup_policy") or {}
    remote: dict[str, Any] = {}
    remote_skipped = False
    skip_reason = ""
    try:
        grant = load_update_grant(os_root)
        remote = grant["remotes"].get("backup") or {}
    except ValueError as exc:
        remote_skipped = True
        skip_reason = str(exc)

    payload: dict[str, Any] = {
        "status": "skipped_no_grant" if remote_skipped else "pushed",
        "created_at": now_stamp(),
        "remote_skipped": remote_skipped,
        "include": policy.get("include") or [],
        "exclude": policy.get("exclude") or [],
    }
    if remote_skipped:
        payload["skip_reason"] = skip_reason
    else:
        payload["remote"] = remote
    log_path = write_run_log(os_root, "backups", "backup-push", payload)
    return {"root": str(os_root), "log_path": str(log_path), **payload}


def latest_backup_log(root: Path) -> Path | None:
    candidates = sorted(backup_logs_dir(root).glob("backup*.yml"))
    return candidates[-1] if candidates else None


def backup_restore_plan(root: str | Path, *, backup_log: str | Path | None = None) -> dict[str, Any]:
    """Build a read-only restore readiness plan from backup policy and logs."""

    os_root = expand_path(root)
    policy = read_structured(harness_path(os_root, "registries", "backup-policy.yml")).get("backup_policy") or {}
    selected_log = expand_path(backup_log) if backup_log else latest_backup_log(os_root)
    backup_payload = read_structured(selected_log) if selected_log else {}
    remote: dict[str, Any] = {}
    grant_present = True
    grant_error = ""
    try:
        grant = load_update_grant(os_root)
        remote = grant.get("remotes", {}).get("backup") or {}
    except ValueError as exc:
        grant_present = False
        grant_error = str(exc)
        configured_remote = policy.get("remote") if isinstance(policy.get("remote"), dict) else {}
        remote = configured_remote if isinstance(configured_remote, dict) else {}

    coverage = backup_policy_coverage(os_root, policy)
    latest_status = backup_payload.get("status") or "missing"
    blockers: list[str] = []
    if not selected_log:
        blockers.append("no local backup log found; run `agentic-os backup run --dry-run` first")
    if not grant_present:
        blockers.append(grant_error)
    if not (remote.get("url") or backup_payload.get("remote", {}).get("url")):
        blockers.append("backup remote URL is missing")
    if coverage["missing_critical_paths"]:
        blockers.append(
            "backup policy missing critical installed harness path(s): "
            + ", ".join(coverage["missing_critical_paths"])
        )
    ready = bool(
        selected_log
        and grant_present
        and (remote.get("url") or backup_payload.get("remote", {}).get("url"))
        and not coverage["missing_critical_paths"]
    )

    return {
        "root": str(os_root),
        "status": "ready" if ready else "blocked",
        "mutated": False,
        "restore_mode": "operator_reviewed_plan_only",
        "latest_backup_log": str(selected_log) if selected_log else "",
        "latest_backup_status": latest_status,
        "remote": remote,
        "include": policy.get("include") or backup_payload.get("include") or [],
        "exclude": policy.get("exclude") or backup_payload.get("exclude") or [],
        "coverage": coverage,
        "blockers": blockers,
        "steps": [
            "Verify the backup remote is private and accessible with the registered backup key.",
            "Clone or fetch the backup remote into a temporary review directory.",
            "Compare only the included paths against the installed OS root.",
            "Do not restore excluded paths such as logs, security/ssh, .env files, secrets, or token-shaped files.",
            "Copy reviewed files back selectively; do not overwrite local memories, logs, or active work without explicit approval.",
            "Run `agentic-os validate --root <restored-root>` and a fresh `agentic-os backup run --dry-run` after restore.",
        ],
    }


def fleet_push(customer_slug: str, *, source: str = "latest") -> dict[str, Any]:
    """Record a simulated operator-push event for a customer installation.

    V1 uses the local fake provisioning provider only — no real SSH, GitHub,
    or MCP calls are made.  The result is a structured log entry that can be
    inspected and acted upon by an operator.  Real network wiring is
    policy-gated and deferred to a future plan.
    """
    if not customer_slug or not customer_slug.replace("_", "").isalnum():
        raise ValueError(f"customer_slug must be snake_case alphanumeric: {customer_slug!r}")

    payload: dict[str, Any] = {
        "customer_slug": customer_slug,
        "source": source,
        "provider": "fake_local",
        "status": "recorded",
        "created_at": now_stamp(),
        "note": (
            "V1 local-only: no SSH, GitHub, or MCP calls performed. "
            "Real push wiring is policy-gated and deferred."
        ),
        "update_status": "recorded_intent",
        "backup_status": "not_run",
        "blocked_risky_changes": [],
    }
    return payload


def snapshot_update_state(root: Path) -> Path:
    snapshot = {
        "created_at": now_stamp(),
        "lock": read_structured(harness_path(root, "agentic-os.lock.json")),
        "status": read_structured(status_path(root)),
    }
    destination = snapshots_dir(root) / f"snapshot-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.yml"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(yaml.safe_dump(snapshot, sort_keys=False), encoding="utf-8")
    return destination


def unique_destination(path: Path) -> Path:
    if not path.exists():
        return path
    if path.suffix:
        stem = path.with_suffix("")
        suffix = path.suffix
    else:
        stem = path
        suffix = ""
    for index in range(1, 1000):
        candidate = stem.with_name(f"{stem.name}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise ValueError(f"could not allocate unique archive path for {path}")


def move_to_archive(source: Path, archive_root: Path, relative: Path, result: ScaffoldResult) -> Path:
    destination = unique_destination(archive_root / relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    result.updated.append(destination)
    return destination


def merge_legacy_directory(source: Path, destination: Path, archive_root: Path, relative: Path, result: ScaffoldResult) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for item in sorted(source.iterdir(), key=lambda path: path.name):
        target = destination / item.name
        item_relative = relative / item.name
        if not target.exists():
            shutil.move(str(item), str(target))
            result.updated.append(target)
            continue
        if item.is_dir() and target.is_dir():
            merge_legacy_directory(item, target, archive_root, item_relative, result)
            continue
        move_to_archive(item, archive_root, item_relative, result)
    try:
        source.rmdir()
    except OSError:
        move_to_archive(source, archive_root, relative, result)


def migrate_harness_layout(root: str | Path) -> ScaffoldResult:
    """Move pre-harness root files into the canonical harness layout.

    Root prompt/config files are archived instead of moved into place so the new
    harness entrypoint can be regenerated from the current installer templates.
    Stateful directories such as registries, logs, security, and shared_factory
    are merged into harness/ while preserving conflicting legacy content in a
    migration archive.
    """
    os_root = expand_path(root)
    result = ScaffoldResult()
    legacy_paths = [
        *(os_root / filename for filename in LEGACY_ROOT_FILES),
        *(os_root / dirname for dirname in LEGACY_ROOT_CAPABILITY_DIRS),
        os_root / "shared_factory",
    ]
    if not any(path.exists() for path in legacy_paths):
        return result

    archive_root = harness_path(os_root, "logs", "migrations", f"harness-layout-{path_stamp()}", "legacy-root")
    for filename in LEGACY_ROOT_FILES:
        source = os_root / filename
        if source.exists():
            move_to_archive(source, archive_root, Path(filename), result)

    shared_factory = os_root / "shared_factory"
    if shared_factory.is_dir():
        merge_legacy_directory(shared_factory, shared_factory_path(os_root), archive_root, Path("shared_factory"), result)

    for dirname in LEGACY_ROOT_CAPABILITY_DIRS:
        source = os_root / dirname
        if source.is_dir():
            merge_legacy_directory(source, harness_path(os_root, dirname), archive_root, Path(dirname), result)
    return result


def project_surface_metadata(project_root: Path) -> tuple[str, str | None]:
    data = read_structured(project_root / "project.yml")
    status = str(data.get("status") or "active") if isinstance(data, dict) else "active"
    lane_value = data.get("lane") if isinstance(data, dict) else None
    lane = str(lane_value) if lane_value else None
    return status, lane


def repair_project_operating_surfaces(root: str | Path) -> ScaffoldResult:
    """Backfill lifecycle scaffolding for projects created by older installers."""
    os_root = expand_path(root)
    result = ScaffoldResult()
    domain_names = installed_domain_names(os_root)
    for domain_name in domain_names:
        domain_root = domain_path(os_root, domain_name)
        projects_root = domain_root / "02-projects"
        if not projects_root.is_dir():
            continue
        for project_root in sorted(path for path in projects_root.iterdir() if path.is_dir()):
            if not (project_root / "project.yml").is_file():
                continue
            status, lane = project_surface_metadata(project_root)
            ensure_project_operating_surface(project_root, domain_root.name, project_root.name, status, lane, result)
    return result


def update_apply(
    root: str | Path,
    *,
    plan: str | Path | None = None,
    approve_risky: bool = False,
) -> dict[str, Any]:
    os_root = expand_path(root)
    plan_data = read_structured(expand_path(plan)) if plan else read_structured(plan_path(os_root))
    if not plan_data:
        plan_data = update_plan(os_root)["plan"]
    risky = plan_data.get("risky_changes") or []
    if risky and not approve_risky:
        status = {
            "status": "blocked",
            "reason": "risky changes require approval",
            "risky_changes": risky,
            "checked_at": now_stamp(),
        }
        write_status(os_root, status)
        return {"root": str(os_root), "applied": False, "blocked": True, "status": status}

    snapshot = snapshot_update_state(os_root)
    result = ScaffoldResult()
    layout_migration = migrate_harness_layout(os_root)
    result.extend(layout_migration)
    # Update is additive relative to the operator's installed domain set:
    # never plant built-in default domains into a tree that already has its
    # own domains. Fresh/degenerate trees fall back to the neutral defaults.
    existing_domains = installed_domain_names(os_root)
    ensure_root_files(os_root, result, DEFAULT_PROJECTS_SOURCE, domains=existing_domains or None)
    ensure_default_domains(os_root, result, domains=existing_domains or None)
    ensure_visible_capability_surface(os_root, result)
    ensure_update_metadata(os_root, result)
    result.extend(install_docs(os_root))
    from .runtime_ops import reconcile_runtime_defaults

    runtime_defaults = reconcile_runtime_defaults(os_root)
    if runtime_defaults.get("changed"):
        result.updated.append(Path(str(runtime_defaults["runtime_registry"])))
    project_repair = repair_project_operating_surfaces(os_root)
    result.extend(project_repair)
    status = {
        "status": "applied",
        "applied_at": now_stamp(),
        "target": plan_data.get("target") or {},
        "snapshot": str(snapshot),
        "layout_migration": bool(layout_migration.updated),
        "project_surface_repair": bool(project_repair.created or project_repair.updated),
        "created": [str(path) for path in result.created],
        "updated": [str(path) for path in result.updated],
        "skipped": [str(path) for path in result.skipped],
    }
    write_status(os_root, status)
    return {"root": str(os_root), "applied": True, "blocked": False, "status": status}


def update_rollback(root: str | Path, *, snapshot: str | Path | None = None) -> dict[str, Any]:
    os_root = expand_path(root)
    snapshot_path = expand_path(snapshot) if snapshot else latest_snapshot(os_root)
    status = {
        "status": "rollback_recorded",
        "rolled_back_at": now_stamp(),
        "snapshot": str(snapshot_path) if snapshot_path else "",
        "note": "V1 records rollback intent and snapshot evidence; destructive restore remains operator-driven.",
    }
    write_status(os_root, status)
    return {"root": str(os_root), "rolled_back": bool(snapshot_path), "status": status}


def latest_snapshot(root: Path) -> Path | None:
    candidates = sorted(snapshots_dir(root).glob("snapshot-*.yml"))
    return candidates[-1] if candidates else None


def update_status(root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    return {
        "root": str(os_root),
        "lock": lock_data(os_root),
        "status": read_structured(status_path(os_root)) or {"status": "unknown"},
        "plan_path": str(plan_path(os_root)) if plan_path(os_root).is_file() else "",
    }


def phone_home_payload(root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    lock = lock_data(os_root)
    registries = harness_path(os_root, "registries")
    registry_counts: dict[str, int] = {}
    if registries.is_dir():
        for path in sorted(registries.glob("*.yml")):
            data = read_structured(path)
            first_value = next(iter(data.values()), [])
            registry_counts[path.stem] = len(first_value) if isinstance(first_value, list) else 1
    return {
        "schema_version": 1,
        "reported_at": now_stamp(),
        "install": {
            "root_name": os_root.name,
            "installed_version": lock["installed_version"],
            "channel": lock["update_channel"],
            "policy": lock["update_policy"],
        },
        "health": {
            "root_marker_present": (os_root / ".agentic_root").is_file(),
            "inventory_present": harness_path(os_root, "INVENTORY.md").is_file(),
            "registry_counts": registry_counts,
        },
        "privacy": {
            "excludes": ["prompts", "customer files", "source code", "logs", "secrets"],
        },
    }


def format_update_result(result: dict[str, Any]) -> str:
    return yaml.safe_dump(result, sort_keys=False).strip()
