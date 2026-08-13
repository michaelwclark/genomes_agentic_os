"""Canonical orchestration primitives for one-to-many programming work.

The module intentionally owns only durable coordination: project policy,
task/portfolio state, receipts, retry decisions, work-item creation, and
isolated worktree creation.  Coding remains the responsibility of the active
agent harness, while CI, review, release, and deployment remain provider
adapters selected by the project profile.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import time
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit
import uuid

import yaml

from .auto_dev_orchestration import (
    AUTO_DEV_MODES,
    AUTO_DEV_STAGE_ORDER,
    AutoDevStateError,
    auto_dev_workflow_window,
    materialize_auto_dev_policy_decision,
    read_auto_dev_state,
    require_auto_dev_predecessors,
    resolve_evidence_file,
    same_pull_request_authority,
    sync_delivery_projection,
    validate_recorded_auto_dev_health,
    validate_auto_dev_readiness_authority,
    validate_auto_dev_stage_order,
    validate_auto_dev_stage_policies,
    validate_pull_request_authority,
)
from .artifact_naming import dated_name, load_artifact_naming_policy
from .lifecycle import (
    create_project_work_item,
    lane_root as work_item_lane_root,
    next_work_item_index,
    slugify_work_id,
    worktree_entries_for_project,
)
from .policy_plane import (
    PolicyLayer,
    PolicyPlaneError,
    markdown_files,
    public_policy_plane,
    resolve_markdown_plane,
)
from .scaffold import (
    domain_path,
    expand_path,
    normalize_domain,
    project_worktree_naming_policy,
    project_worktree_root,
    register_project_worktree,
    validate_name,
)
from .state import work_items as canonical_work_items
from .state.db import connect as connect_state
from .state.db import default_db_path


PROFILE_VERSION = 1
FORWARD_STATES = (
    "discovered",
    "claimed",
    "groom_check",
    "context_ready",
    "work_item_ready",
    "worktree_ready",
    "planned",
    "implementing",
    "local_validation",
    "pre_pr_review",
    "pr_open",
    "ci_repair",
    "review_repair",
    "post_pr_review",
    "ready_for_merge",
    "merged",
    "deployment_pending",
    "deploying",
    "post_deploy_validation",
    "delivery_complete",
)
TERMINAL_STATES = {"delivery_complete", "blocked", "abandoned", "cancelled"}
RETRYABLE_FAILURES = {
    "environment_unavailable",
    "executor_unavailable",
    "provider_unavailable",
    "lease_expired",
    "ci_failed",
    "review_findings",
    "test_failed",
    "provisioning_failed",
}
CANONICAL_ADMISSION_MAX_ATTEMPTS = 4
CANONICAL_ADMISSION_BUSY_TIMEOUT_MS = 250
CANONICAL_ADMISSION_BACKOFF_SECONDS = 0.05
WORKFLOW_NAMES = (
    "readiness_and_context",
    "isolated_implementation",
    "pr_create",
    "testing_review_and_pr_repair",
    "release_propagation",
    "merge_deployment_and_cleanup",
)
WORKFLOW_DOC_SECTIONS = (
    "What this does",
    "Inputs",
    "Outputs",
    "States",
    "Steps",
    "Validations",
    "Success modes",
    "Failure modes and recovery",
    "Events and receipts",
    "Cleanup and handoff",
)
DEVELOPMENT_POLICY_PLANES = (
    "dev_standards",
    "qa_gates",
    "gitflow_topology",
    "auto_dev",
    "environment_access",
)

# Auto-Dev owns one visible configuration tree.  The workflow policy remains
# at the tree root while the other four independent planes live beneath it.
# Keeping these as distinct resolver roots avoids loading the same Markdown
# into more than one effective policy fingerprint.
AUTO_DEV_POLICY_SUBDIRECTORY = {
    "auto_dev": "",
    "dev_standards": "dev_standards",
    "qa_gates": "qa_gates",
    "gitflow_topology": "gitflow_topology",
    "environment_access": "environment_access",
}
AUTO_DEV_FOLDER_PROFILE_VERSION = "auto-dev-folder/v1"
DEVELOPMENT_STAGE_RANGES = {
    "readiness": ("worktree_ready", "planned"),
    "implementation": ("planned", "local_validation"),
    "review": ("local_validation", "ready_for_merge"),
    "merge": ("ready_for_merge", "merged"),
    "deploy": ("merged", "post_deploy_validation"),
    "closeout": ("post_deploy_validation", "delivery_complete"),
}
ACTIVE_WORKTREE_READY_DELIVERY_RECOVERY_SCHEMA = "active-worktree-ready-delivery-recovery/v1"
ACTIVE_WORKTREE_READY_PR_CREATE_DELIVERY_RECOVERY_SCHEMA = (
    "active-worktree-ready-pr-create-delivery-recovery/v1"
)
ACTIVE_WORKTREE_READY_RELEASE_PROPAGATION_CONTINUATION_SCHEMA = (
    "active-worktree-ready-release-propagation-continuation/v1"
)
ACTIVE_PR_CREATE_DELIVERY_ESCALATION_SCHEMA = "active-pr-create-delivery-escalation/v1"
_ACTIVE_WORKTREE_READY_RELEASE_PROPAGATION_RECOVERY_VARIANTS = (
    {
        "history_key": "active_worktree_ready_delivery_recoveries",
        "schema": ACTIVE_WORKTREE_READY_DELIVERY_RECOVERY_SCHEMA,
        "kind": "recover-active-worktree-ready-delivery",
        "directory": "active-worktree-ready-delivery-recovery",
        "event_type": "development.task.active_worktree_ready_delivery_recovered",
        "recovery_shape": None,
        "derived_requested_stages": (None,),
    },
    {
        "history_key": "active_worktree_ready_pr_create_delivery_recoveries",
        "schema": ACTIVE_WORKTREE_READY_PR_CREATE_DELIVERY_RECOVERY_SCHEMA,
        "kind": "recover-active-worktree-ready-pr-create-delivery",
        "directory": "active-worktree-ready-pr-create-delivery-recovery",
        "event_type": "development.task.active_worktree_ready_pr_create_delivery_recovered",
        "recovery_shape": "single_stage_pr_create_worktree_ready",
        # A current projection can carry the selected Review Self entrypoint
        # after the PR-Create recovery synchronizes it.  This is not Review
        # authority: both task and projection must remain receipt-free.
        "derived_requested_stages": (None, "review_self"),
    },
)
_ACTIVE_WORKTREE_READY_DELIVERY_FRESH_STAGES = (
    "review_self",
    "review_others",
    "qa",
    "finalize",
    "merge",
)
_ACTIVE_PR_CREATE_ESCALATION_POST_PR_STAGES = (
    "review_self",
    "review_others",
    "qa",
    "finalize",
    "merge",
    "release",
    "deploy",
    "closeout",
    "health",
)


class DevelopmentDeliveryError(ValueError):
    """Raised when a run cannot safely continue."""


def _mapping_copy(value: Any) -> dict[str, Any]:
    """Return a mutable mapping without accepting ambiguous scalar config."""

    return dict(value) if isinstance(value, Mapping) else {}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


@contextmanager
def _file_lock(path: Path):
    """Serialize state and JSONL mutations across concurrent harnesses."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise DevelopmentDeliveryError(f"expected a mapping: {path}")
    return value


def project_root(root: str | Path, domain: str, project: str) -> Path:
    projects_root = domain_path(expand_path(root), normalize_domain(domain)) / "02-projects"
    normalized_project = validate_name(project, "project")
    path = projects_root / normalized_project
    if not (path / "project.yml").is_file() and "_" in normalized_project:
        # Compatibility for recovered pre-canonical rooms whose directory used
        # kebab-case. New project IDs remain snake_case, and this lookup never
        # creates a second project owner or symlink.
        legacy_path = projects_root / normalized_project.replace("_", "-")
        if (legacy_path / "project.yml").is_file():
            path = legacy_path
    if not (path / "project.yml").is_file():
        raise DevelopmentDeliveryError(f"project not found: {domain}/{project}")
    return path


def _project_work_item_lane(packet: Path, project_path: Path) -> str | None:
    """Return the packet lane, including the canonical root-level active layout."""

    try:
        relative = packet.expanduser().resolve().relative_to(
            (project_path / "work-items").resolve()
        )
    except ValueError:
        return None
    if not relative.parts:
        return None
    if len(relative.parts) == 1 and relative.parts[0] not in {
        "01-intake",
        "02-active",
        "03-complete",
        "99-archived",
    }:
        return "02-active"
    return relative.parts[0]


def _project_work_item_is_finished(packet: Path, project_path: Path) -> bool:
    """Recognize immutable history by bounded location or lifecycle metadata."""

    if _project_work_item_lane(packet, project_path) in {
        "03-complete",
        "99-archived",
    }:
        return True
    metadata = _read_mapping(packet / "work.yml")
    states = {
        str(metadata.get(key) or "").strip().lower()
        for key in ("state", "status")
        if metadata.get(key)
    }
    lifecycle = metadata.get("lifecycle")
    if isinstance(lifecycle, Mapping) and lifecycle.get("state"):
        states.add(str(lifecycle["state"]).strip().lower())
    return bool(states & canonical_work_items.TERMINAL_STATES)


def _compatibility_profile(project_data: Mapping[str, Any]) -> dict[str, Any]:
    """Translate the prior ``dev_factory`` block without inventing behavior."""
    legacy = project_data.get("dev_factory")
    if not isinstance(legacy, Mapping):
        sources = project_data.get("sources") if isinstance(project_data.get("sources"), Mapping) else {}
        # Existing projects predate both development.yml and dev_factory. They
        # still receive the safe convention defaults, but repository absence
        # remains a blocking configuration error rather than an invented path.
        return {
            "version": PROFILE_VERSION,
            "enabled": True,
            "tracker": {"primary": "filesystem"},
            "repository": {"root": sources.get("repo"), "base_branch": "main"},
            "worktrees": {
                "directory": "worktrees",
                "branch_template": "feature/{ticket}-{slug}",
                "date_prefix": "inherit",
            },
            "work_items": {"active_status": "building"},
            "runtime": {
                "ownership": "not_managed",
                "provider": "none",
                "identity": "not-managed",
            },
            "validation": {
                "commands": [],
                "ci_fallback_on_environment_failure": True,
                "test_policy": "risk_based_triangle",
            },
            "pull_request": {},
            "review": {
                "opposing_harness": {
                    "required": True,
                    "preferred": "claude",
                    "fallback": "codex",
                    "unavailable_policy": "continue_with_receipt",
                }
            },
            "merge": {"policy": "never_auto"},
            "release": {"fix_version_drives_targets": True},
            "deployment": {"required": False, "monitor_after_merge": True},
            "recovery": {"max_attempts": 3, "lease_minutes": 30, "stale_after_minutes": 45},
            "policies": {},
            "compatibility": {"source": "project.yml#sources"},
        }
    repo = legacy.get("repo") if isinstance(legacy.get("repo"), Mapping) else {}
    validation = legacy.get("validation") if isinstance(legacy.get("validation"), Mapping) else {}
    legacy_commands = validation.get("commands") or []
    if isinstance(legacy_commands, Mapping):
        commands = [str(value) for value in legacy_commands.values() if value]
    elif isinstance(legacy_commands, list):
        commands = [str(value) for value in legacy_commands]
    else:
        commands = [str(legacy_commands)] if legacy_commands else []
    branch_template = str(repo.get("branch_template") or "feature/{ticket}-{slug}").replace(
        "{tracker_id}", "{ticket}"
    )
    return {
        "version": PROFILE_VERSION,
        "enabled": bool(legacy.get("enabled", True)),
            "tracker": _mapping_copy(legacy.get("tracker")),
        "repository": {
            "root": repo.get("root"),
            "base_branch": repo.get("base_branch") or repo.get("default_base_branch") or repo.get("base") or "main",
        },
        "worktrees": {
            "directory": "worktrees",
            "branch_template": branch_template,
            "date_prefix": "inherit",
        },
        "work_items": {"active_status": "building"},
        "runtime": {
            "ownership": "not_managed",
            "provider": "none",
            "identity": "not-managed",
        },
        "validation": {
            "commands": commands,
            "ci_fallback_on_environment_failure": bool(
                validation.get(
                    "ci_fallback_on_environment_failure",
                    validation.get("allow_ci_fallback_when_local_blocked", True),
                )
            ),
            "test_policy": "risk_based_triangle",
        },
        "pull_request": _mapping_copy(legacy.get("pull_request")),
        "review": {
            "finishing": _mapping_copy(legacy.get("finishing_review")),
            "copilot": _mapping_copy(legacy.get("copilot")),
            "authorship": _mapping_copy(legacy.get("authorship")),
        },
        "merge": _mapping_copy(legacy.get("merge")) or {"policy": "never_auto"},
        "release": _mapping_copy(legacy.get("release")),
        "deployment": _mapping_copy(legacy.get("deployment")),
        "recovery": {"max_attempts": 3, "lease_minutes": 30, "stale_after_minutes": 45},
        "policies": {
            "dev_standards": _mapping_copy(legacy.get("dev_standards") or legacy.get("quality_gates")),
            "qa_gates": _mapping_copy(legacy.get("qa_gates")),
            "gitflow_topology": _mapping_copy(legacy.get("gitflow_topology")),
        },
        "compatibility": {"source": "project.yml#dev_factory"},
    }


def validate_profile(profile: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if profile.get("version") != PROFILE_VERSION:
        errors.append(f"version must be {PROFILE_VERSION}")
    if profile.get("enabled") is not True:
        errors.append("enabled must be true")
    for section in (
        "tracker",
        "repository",
        "worktrees",
        "work_items",
        "runtime",
        "validation",
        "review",
        "merge",
        "recovery",
    ):
        if not isinstance(profile.get(section), Mapping):
            errors.append(f"{section} must be a mapping")
    repository = profile.get("repository") if isinstance(profile.get("repository"), Mapping) else {}
    catalog = repository.get("catalog")
    catalog_rows: list[Mapping[str, Any]] = []
    if isinstance(catalog, Mapping):
        catalog_rows = [
            {"id": key, **dict(value)}
            for key, value in catalog.items()
            if isinstance(value, Mapping)
        ]
        if len(catalog_rows) != len(catalog):
            errors.append("repository.catalog values must be mappings")
    elif isinstance(catalog, list):
        catalog_rows = [item for item in catalog if isinstance(item, Mapping)]
        if len(catalog_rows) != len(catalog):
            errors.append("repository.catalog entries must be mappings")
    elif catalog is not None:
        errors.append("repository.catalog must be a mapping or list")
    if repository.get("root"):
        if not repository.get("base_branch"):
            errors.append("repository.base_branch is required")
    elif not catalog_rows:
        errors.append("repository.root or repository.catalog is required")
    catalog_ids: set[str] = set()
    for index, row in enumerate(catalog_rows):
        identity = str(row.get("id") or "").strip()
        if not identity:
            errors.append(f"repository.catalog[{index}].id is required")
        elif identity in catalog_ids:
            errors.append(f"repository.catalog id is duplicated: {identity}")
        else:
            catalog_ids.add(identity)
        if not row.get("root") or not row.get("base_branch"):
            errors.append(f"repository.catalog[{identity or index}] requires root and base_branch")
        if "profile_overrides" in row and not isinstance(row.get("profile_overrides"), Mapping):
            errors.append(f"repository.catalog[{identity or index}].profile_overrides must be a mapping")
    if repository.get("selection_required") is True and not catalog_rows:
        errors.append("repository.selection_required needs repository.catalog")
    if repository.get("default") and str(repository.get("default")) not in catalog_ids:
        errors.append("repository.default must match a catalog id")
    review = profile.get("review") if isinstance(profile.get("review"), Mapping) else {}
    authorship = review.get("authorship") if isinstance(review.get("authorship"), Mapping) else {}
    ours = authorship.get("ours")
    if ours is not None and not (
        isinstance(ours, list)
        and all(isinstance(identity, str) and identity.strip() and ":" in identity for identity in ours)
    ):
        errors.append(
            "review.authorship.ours must contain only provider-qualified identities "
            "such as github:username"
        )
    recovery = profile.get("recovery") if isinstance(profile.get("recovery"), Mapping) else {}
    if int(recovery.get("max_attempts") or 0) < 1:
        errors.append("recovery.max_attempts must be at least 1")
    validation = profile.get("validation") if isinstance(profile.get("validation"), Mapping) else {}
    if not isinstance(validation.get("commands", []), list):
        errors.append("validation.commands must be a list")
    worktrees = profile.get("worktrees") if isinstance(profile.get("worktrees"), Mapping) else {}
    date_prefix = worktrees.get("date_prefix", "inherit")
    if date_prefix != "inherit" and not isinstance(date_prefix, bool):
        errors.append("worktrees.date_prefix must be 'inherit', true, or false")
    directory = worktrees.get("directory")
    if not isinstance(directory, str) or not directory.strip():
        errors.append("worktrees.directory must be a non-empty path")
    template = str(worktrees.get("branch_template") or "")
    try:
        template.format(ticket="ticket", slug="slug")
    except (KeyError, ValueError) as exc:
        errors.append(f"worktrees.branch_template is invalid: {exc}")
    runtime = profile.get("runtime") if isinstance(profile.get("runtime"), Mapping) else {}
    ownership = str(runtime.get("ownership") or "").strip()
    provider = str(runtime.get("provider") or "").strip()
    if ownership == "not_managed":
        if provider != "none":
            errors.append("runtime.provider must be none when ownership is not_managed")
        if runtime.get("identity") != "not-managed":
            errors.append("runtime.identity must be not-managed when ownership is not_managed")
    elif ownership == "managed":
        identity_template = str(runtime.get("identity_template") or "").strip()
        if not provider or provider == "none":
            errors.append("managed runtime.provider must name the project runtime provider")
        if not identity_template:
            errors.append("managed runtime.identity_template is required")
        else:
            required_identity_fields = {"{domain}", "{project}", "{worktree}"}
            missing_identity_fields = sorted(
                field for field in required_identity_fields if field not in identity_template
            )
            if missing_identity_fields:
                errors.append(
                    "managed runtime.identity_template must include {domain}, {project}, "
                    "and {worktree} for globally item-unique ownership"
                )
            try:
                resolved_identity = identity_template.format(
                    domain="domain",
                    project="project",
                    worktree="worktree",
                    worktree_path="/worktree/path",
                    ticket="ticket",
                )
                if not resolved_identity.strip() or resolved_identity == "not-managed":
                    errors.append("managed runtime.identity_template must resolve to a managed identity")
            except (KeyError, ValueError) as exc:
                errors.append(f"managed runtime.identity_template is invalid: {exc}")
        for field in ("teardown_command", "readback_command"):
            command_template = str(runtime.get(field) or "").strip()
            if not command_template:
                errors.append(f"managed runtime.{field} is required")
            elif "{runtime_identity}" not in command_template:
                errors.append(
                    f"managed runtime.{field} must include {{runtime_identity}} for exact-target execution"
                )
            elif any(
                forbidden in command_template.lower()
                for forbidden in (
                    "system prune",
                    "container prune",
                    "volume prune",
                    "worktree prune",
                    "--all",
                    "delete all",
                )
            ):
                errors.append(f"managed runtime.{field} contains a forbidden global cleanup operation")
    elif ownership:
        errors.append("runtime.ownership must be managed or not_managed")
    elif isinstance(profile.get("runtime"), Mapping):
        errors.append("runtime.ownership is required")
    return errors


def _normalized_repository_identity(repository: Mapping[str, Any]) -> str:
    """Return one non-empty repository identity for all provider receipts.

    Catalog IDs are authoritative.  A single-repository profile is upgraded
    from its Git remote when possible; a content-stable local identity is the
    fail-closed fallback for repositories without a remote.
    """

    configured = str(repository.get("id") or "").strip()
    if configured:
        return configured
    root = expand_path(str(repository.get("root") or ""))
    remote = subprocess.run(
        ["git", "-C", str(root), "config", "--get", "remote.origin.url"],
        capture_output=True,
        text=True,
        check=False,
    )
    value = remote.stdout.strip() if remote.returncode == 0 else ""
    if value:
        value = value.removesuffix(".git")
        if value.startswith("git@") and ":" in value:
            host, path = value[4:].split(":", 1)
            value = f"{host.lower()}/{path.strip('/')}"
        else:
            parsed = urlsplit(value if "://" in value else f"ssh://{value}")
            host = (parsed.hostname or "").lower()
            path = parsed.path.strip("/")
            value = f"{host}/{path}" if host and path else ""
        if value:
            return f"git:{value}"
    resolved = str(root.resolve())
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]
    return f"local:{root.name or 'repository'}:{digest}"


def _configured_authorship(
    profile: Mapping[str, Any], *, required: bool = False
) -> dict[str, list[str]]:
    review = profile.get("review") if isinstance(profile.get("review"), Mapping) else {}
    authorship = review.get("authorship") if isinstance(review.get("authorship"), Mapping) else {}
    ours = sorted({str(value).strip() for value in authorship.get("ours") or [] if str(value).strip()})
    if required and not ours:
        raise DevelopmentDeliveryError(
            "review.authorship.ours must configure at least one provider-qualified identity"
        )
    return {"ours": ours}


def _runtime_registration(
    profile: Mapping[str, Any],
    worktree: Mapping[str, Any],
    *,
    domain: str,
    project: str,
    ticket: str,
) -> dict[str, str]:
    """Resolve one immutable, project-owned runtime registration for a task."""

    runtime = profile.get("runtime") if isinstance(profile.get("runtime"), Mapping) else {}
    ownership = str(runtime.get("ownership") or "")
    if ownership == "not_managed":
        return {
            "ownership": "not_managed",
            "provider": "none",
            "identity": "not-managed",
        }
    if ownership != "managed":
        raise DevelopmentDeliveryError("development runtime ownership is not configured")
    identity_template = str(runtime.get("identity_template") or "")
    if not all(field in identity_template for field in ("{domain}", "{project}", "{worktree}")):
        raise DevelopmentDeliveryError(
            "managed runtime identity_template must include {domain}, {project}, and {worktree}"
        )
    context = {
        "domain": normalize_domain(domain),
        "project": validate_name(project, "project"),
        "repository_root": str(
            expand_path(
                str(
                    (
                        profile.get("repository")
                        if isinstance(profile.get("repository"), Mapping)
                        else {}
                    ).get("root")
                    or ""
                )
            )
        ),
        "worktree": str(worktree.get("name") or ""),
        "worktree_path": str(worktree.get("path") or ""),
        "ticket": ticket,
    }
    try:
        identity = identity_template.format(**context).strip()
    except (KeyError, ValueError) as exc:
        raise DevelopmentDeliveryError(f"cannot resolve managed runtime identity: {exc}") from exc
    if not identity or identity == "not-managed":
        raise DevelopmentDeliveryError("managed runtime identity resolved to an unsafe value")
    command_context = {**context, "runtime_identity": identity}
    try:
        teardown_command = str(runtime["teardown_command"]).format(**command_context).strip()
        readback_command = str(runtime["readback_command"]).format(**command_context).strip()
    except (KeyError, ValueError) as exc:
        raise DevelopmentDeliveryError(f"cannot resolve managed runtime commands: {exc}") from exc
    return {
        "ownership": "managed",
        "provider": str(runtime["provider"]),
        "identity": identity,
        "teardown_command": teardown_command,
        "readback_command": readback_command,
    }


def select_development_repository(
    profile: Mapping[str, Any], repository_id: str | None
) -> dict[str, Any]:
    """Select one configured repository without guessing in multi-repo projects."""

    selected_profile = deepcopy(dict(profile))
    repository = profile.get("repository") if isinstance(profile.get("repository"), Mapping) else {}
    raw_catalog = repository.get("catalog")
    catalog: list[dict[str, Any]] = []
    if isinstance(raw_catalog, Mapping):
        catalog = [{"id": str(key), **dict(value)} for key, value in raw_catalog.items() if isinstance(value, Mapping)]
    elif isinstance(raw_catalog, list):
        catalog = [dict(item) for item in raw_catalog if isinstance(item, Mapping)]
    if not catalog:
        if repository_id:
            raise DevelopmentDeliveryError("--repository is only valid when repository.catalog is configured")
        selected_profile["repository"] = dict(repository)
        return selected_profile
    requested = repository_id or repository.get("default")
    if requested is None and len(catalog) == 1 and repository.get("selection_required") is not True:
        requested = catalog[0].get("id")
    if requested is None:
        choices = ", ".join(sorted(str(row["id"]) for row in catalog))
        raise DevelopmentDeliveryError(f"repository selection is required; choose one of: {choices}")
    match = next((row for row in catalog if str(row.get("id")) == str(requested)), None)
    if match is None:
        choices = ", ".join(sorted(str(row["id"]) for row in catalog))
        raise DevelopmentDeliveryError(f"unknown repository {requested!r}; choose one of: {choices}")
    overrides = match.get("profile_overrides") if isinstance(match.get("profile_overrides"), Mapping) else {}
    for section, value in overrides.items():
        if isinstance(selected_profile.get(section), Mapping) and isinstance(value, Mapping):
            selected_profile[section] = {**dict(selected_profile[section]), **deepcopy(dict(value))}
        else:
            selected_profile[section] = deepcopy(value)
    inherited = {
        key: deepcopy(value)
        for key, value in repository.items()
        if key not in {"catalog", "selection_required", "default", "root", "base_branch", "id"}
    }
    selected_repository = {key: value for key, value in match.items() if key != "profile_overrides"}
    selected_profile["repository"] = {**inherited, **deepcopy(selected_repository), "id": str(match["id"])}
    return selected_profile


def load_development_profile(root: str | Path, domain: str, project: str) -> tuple[dict[str, Any], Path]:
    root_path = project_root(root, domain, project)
    canonical = root_path / "config" / "development.yml"
    if canonical.is_file():
        profile = _read_mapping(canonical)
        source = canonical
    else:
        profile = _compatibility_profile(_read_mapping(root_path / "project.yml"))
        source = root_path / "project.yml"
    errors = validate_profile(profile)
    if errors:
        raise DevelopmentDeliveryError("invalid development profile: " + "; ".join(errors))
    profile["loaded_from"] = str(source)
    return profile, source


def load_development_policy_profile(
    root: str | Path,
    domain: str,
    project: str,
) -> tuple[dict[str, Any], Path]:
    """Load policy configuration without pretending an unrooted project can run."""

    root_path = project_root(root, domain, project)
    canonical = root_path / "config" / "development.yml"
    if canonical.is_file():
        profile = _read_mapping(canonical)
        source = canonical
    else:
        profile = _compatibility_profile(_read_mapping(root_path / "project.yml"))
        source = root_path / "project.yml"
    errors = [
        error
        for error in validate_profile(profile)
        if error != "repository.root or repository.catalog is required"
    ]
    if errors:
        raise DevelopmentDeliveryError("invalid development profile: " + "; ".join(errors))
    profile["loaded_from"] = str(source)
    return profile, source


def _policy_path(
    raw: str,
    *,
    os_root: Path,
    domain_root: Path,
    project_path: Path,
) -> Path:
    expanded = raw.format(root=str(os_root), domain_root=str(domain_root), project_root=str(project_path))
    path = Path(expanded).expanduser()
    if not path.is_absolute():
        if path.parts and path.parts[0] in {"harness", "domains"}:
            path = os_root / path
        else:
            path = project_path / path
    resolved = path.resolve()
    try:
        resolved.relative_to(os_root)
    except ValueError as exc:
        raise DevelopmentDeliveryError(f"development policy path is outside the Agentic OS root: {raw}") from exc
    return resolved


def resolve_development_policy(
    root: str | Path,
    domain: str,
    project: str,
    plane: str,
    *,
    explicit_files: Sequence[str | Path] = (),
    selected_profile: Mapping[str, Any] | None = None,
    profile_source: str | Path | None = None,
    include_body: bool = False,
) -> dict[str, Any]:
    """Resolve a 1-N development policy folder list with stable provenance."""

    if plane not in DEVELOPMENT_POLICY_PLANES:
        raise DevelopmentDeliveryError(
            f"policy plane must be one of {', '.join(DEVELOPMENT_POLICY_PLANES)}"
        )
    os_root = expand_path(root)
    domain_root = domain_path(os_root, normalize_domain(domain))
    project_path = project_root(os_root, domain, project)
    if selected_profile is None:
        profile, loaded_profile_source = load_development_policy_profile(
            os_root,
            domain,
            project,
        )
    else:
        profile = deepcopy(dict(selected_profile))
        loaded_profile_source = Path(profile_source).expanduser().resolve() if profile_source else project_path / "config" / "development.yml"
    policies = profile.get("policies") if isinstance(profile.get("policies"), Mapping) else {}
    configured = policies.get(plane) if isinstance(policies.get(plane), Mapping) else {}
    paths = configured.get("paths") if isinstance(configured, Mapping) else None
    if paths is None and isinstance(profile.get(plane), Mapping):
        paths = profile[plane].get("paths")
    if paths is not None and not isinstance(paths, list):
        raise DevelopmentDeliveryError(f"policies.{plane}.paths must be a list")

    subdirectory = AUTO_DEV_POLICY_SUBDIRECTORY[plane]
    canonical_suffix = Path("auto_dev") / subdirectory if subdirectory else Path("auto_dev")
    legacy_suffix = Path(plane)
    reserved_children = tuple(
        name for name in DEVELOPMENT_POLICY_PLANES if name != "auto_dev"
    )

    def has_active_markdown(path: Path) -> bool:
        return bool(
            markdown_files(
                path,
                excluded_subdirectories=(
                    reserved_children if plane == "auto_dev" else ()
                ),
            )
        )

    def conventional_root(canonical_parent: Path, legacy_parent: Path) -> Path:
        """Select one policy root without merging canonical and compatibility files.

        Domain policy now follows the same ``config/auto_dev`` shape as project
        policy.  The historic ``05-knowledge/auto_dev`` tree remains a fallback
        until a domain is migrated.  A still-older flat ``<plane>`` folder is
        also retained as a compatibility fallback for every scope.
        """

        candidates: list[Path] = []
        for candidate in (
            canonical_parent / canonical_suffix,
            legacy_parent / canonical_suffix,
            legacy_parent / legacy_suffix,
        ):
            if candidate not in candidates:
                candidates.append(candidate)
        # Existing installations can still be read before they are migrated.
        # A README-only canonical scaffold must not hide substantive legacy
        # policy, and the candidate roots are never merged.
        for candidate in candidates:
            if has_active_markdown(candidate):
                return candidate
        for candidate in candidates:
            if candidate.is_dir():
                return candidate
        return candidates[0]

    conventional_parents = (
        (
            os_root / "harness" / "shared_factory" / "05-knowledge",
            os_root / "harness" / "shared_factory" / "05-knowledge",
        ),
        (domain_root / "config", domain_root / "05-knowledge"),
        (project_path / "config", project_path / "config"),
    )

    def configured_root(raw: str) -> Path:
        selected = _policy_path(
            raw,
            os_root=os_root,
            domain_root=domain_root,
            project_path=project_path,
        )
        for canonical_parent, legacy_parent in conventional_parents:
            conventional_members = {
                (canonical_parent / canonical_suffix).resolve(),
                (canonical_parent / legacy_suffix).resolve(),
                (legacy_parent / canonical_suffix).resolve(),
                (legacy_parent / legacy_suffix).resolve(),
            }
            if selected in conventional_members:
                return conventional_root(canonical_parent, legacy_parent)
        return selected

    if paths:
        layers = [
            PolicyLayer(
                scope=f"configured_{index:02d}",
                root=configured_root(str(raw)),
                rank=index,
            )
            for index, raw in enumerate(paths)
        ]
    else:
        layers = [
            PolicyLayer(
                "root",
                conventional_root(*conventional_parents[0]),
                0,
            ),
            PolicyLayer("domain", conventional_root(*conventional_parents[1]), 1),
            PolicyLayer("project", conventional_root(*conventional_parents[2]), 2),
        ]
    try:
        result = resolve_markdown_plane(
            os_root,
            layers,
            explicit_files=explicit_files,
            # The Auto-Dev parent also contains the four sibling policy
            # planes. Preserve recursive workflow addenda while excluding
            # those independently fingerprinted child roots.
            excluded_subdirectories=(
                reserved_children
                if plane == "auto_dev"
                else ()
            ),
        )
    except PolicyPlaneError as exc:
        raise DevelopmentDeliveryError(str(exc)) from exc
    public = public_policy_plane(result, include_body=include_body)
    public.update(
        {
            "schema": "development-policy-plane/v1",
            "plane": plane,
            "domain": normalize_domain(domain),
            "project": validate_name(project, "project"),
            "profile_source": str(loaded_profile_source),
        }
    )
    return public


def resolve_auto_dev_folder_profile(
    profile: Mapping[str, Any],
    *,
    domain: str,
    project: str,
) -> dict[str, Any]:
    """Load the portable repository-level Auto-Dev overlay when it exists."""

    repository = (
        profile.get("repository")
        if isinstance(profile.get("repository"), Mapping)
        else {}
    )
    raw_root = repository.get("root")
    if not raw_root:
        return {"status": "not_configured"}
    repo_root = Path(str(raw_root)).expanduser().resolve()
    source = (repo_root / "auto_dev" / "profile.yml").resolve()
    try:
        source.relative_to(repo_root)
    except ValueError as exc:
        raise DevelopmentDeliveryError(
            "repository Auto-Dev profile escapes the repository root"
        ) from exc
    if not source.is_file():
        return {"status": "not_configured"}
    if source.stat().st_size > 256_000:
        raise DevelopmentDeliveryError("repository Auto-Dev profile is too large")
    raw = source.read_bytes()
    try:
        value = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise DevelopmentDeliveryError(
            "repository auto_dev/profile.yml is invalid YAML"
        ) from exc
    if not isinstance(value, Mapping):
        raise DevelopmentDeliveryError(
            "repository auto_dev/profile.yml must be a mapping"
        )
    if value.get("api_version") != AUTO_DEV_FOLDER_PROFILE_VERSION:
        raise DevelopmentDeliveryError(
            f"repository auto_dev/profile.yml api_version must be {AUTO_DEV_FOLDER_PROFILE_VERSION}"
        )
    identity = value.get("identity")
    lifecycle = value.get("lifecycle")
    if not isinstance(identity, Mapping):
        raise DevelopmentDeliveryError(
            "repository auto_dev/profile.yml identity must be a mapping"
        )
    expected_domain = normalize_domain(domain)
    expected_project = validate_name(project, "project")
    raw_identity_domain = identity.get("domain")
    raw_identity_project = identity.get("project")
    if not isinstance(raw_identity_domain, str) or not raw_identity_domain.strip():
        raise DevelopmentDeliveryError(
            "repository auto_dev/profile.yml identity.domain is required"
        )
    if not isinstance(raw_identity_project, str) or not raw_identity_project.strip():
        raise DevelopmentDeliveryError(
            "repository auto_dev/profile.yml identity.project is required"
        )
    try:
        identity_domain = normalize_domain(raw_identity_domain)
    except ValueError as exc:
        raise DevelopmentDeliveryError(
            f"repository auto_dev/profile.yml identity.domain is invalid: {exc}"
        ) from exc
    try:
        identity_project = validate_name(
            raw_identity_project,
            "repository auto_dev/profile.yml identity.project",
        )
    except ValueError as exc:
        raise DevelopmentDeliveryError(str(exc)) from exc
    if identity_domain != expected_domain:
        raise DevelopmentDeliveryError(
            "repository auto_dev/profile.yml identity.domain does not match "
            f"requested domain {expected_domain!r}: {identity_domain!r}"
        )
    if identity_project != expected_project:
        raise DevelopmentDeliveryError(
            "repository auto_dev/profile.yml identity.project does not match "
            f"requested project {expected_project!r}: {identity_project!r}"
        )
    if not isinstance(lifecycle, Mapping):
        raise DevelopmentDeliveryError(
            "repository auto_dev/profile.yml lifecycle must be a mapping"
        )
    for stage in ("build", "validate", "release", "document"):
        if not isinstance(lifecycle.get(stage), Mapping):
            raise DevelopmentDeliveryError(
                f"repository auto_dev/profile.yml lifecycle.{stage} must be a mapping"
            )
    validated_identity = deepcopy(dict(identity))
    validated_identity.update(
        {"domain": identity_domain, "project": identity_project}
    )
    result = {
        "status": "loaded",
        "schema": AUTO_DEV_FOLDER_PROFILE_VERSION,
        "source_ref": "auto_dev/profile.yml",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "identity": validated_identity,
        "lifecycle": deepcopy(dict(lifecycle)),
    }
    result["content_sha256"] = _json_sha256(result)
    return result


def _json_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _legacy_policy_source_content_is_bound(source: Mapping[str, Any]) -> bool:
    """Validate the only legacy policy shape whose raw digest is recoverable.

    Early effective-policy receipts stored the parsed Markdown body beside the
    SHA-256 of the raw source, but did not bind the whole plane.  Empty
    frontmatter lets us recover the raw content exactly apart from the one
    trailing-newline normalization used by the parser.  Any richer legacy
    shape must fail closed instead of pretending its body is immutable.
    """

    frontmatter = source.get("frontmatter")
    body = source.get("body_markdown")
    expected = str(source.get("sha256") or "")
    if not (
        isinstance(frontmatter, Mapping)
        and not frontmatter
        and isinstance(body, str)
        and re.fullmatch(r"[a-f0-9]{64}", expected)
    ):
        return False
    candidates = (body, f"{body}\n")
    return any(
        hashlib.sha256(candidate.encode("utf-8")).hexdigest() == expected
        for candidate in candidates
    )


def _explicit_auto_dev_boundary(
    value: Mapping[str, Any] | None,
    *,
    mode_key: str,
    start_key: str,
    completion_key: str,
    label: str,
) -> tuple[str, str, str] | None:
    """Return one complete durable boundary, rejecting partial state."""

    if not isinstance(value, Mapping):
        return None
    start = str(value.get(start_key) or "").strip()
    completion = str(value.get(completion_key) or "").strip()
    if bool(start) != bool(completion):
        raise DevelopmentDeliveryError(
            f"{label} has an incomplete Auto-Dev workflow boundary"
        )
    if not start:
        return None
    mode = str(value.get(mode_key) or "").strip()
    if not mode:
        raise DevelopmentDeliveryError(
            f"{label} has an Auto-Dev workflow boundary without a mode"
        )
    return mode, start, completion


def _selected_profile_policy_authority(
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    repository = (
        profile.get("repository")
        if isinstance(profile.get("repository"), Mapping)
        else {}
    )
    validation = (
        profile.get("validation")
        if isinstance(profile.get("validation"), Mapping)
        else {}
    )
    authority = {
        "schema": "development-selected-profile/v1",
        "repository_id": str(repository.get("id") or ""),
        "validation": deepcopy(dict(validation)),
    }
    authority["sha256"] = _json_sha256(authority)
    return authority


def _effective_policy_snapshot_fingerprint(
    snapshot: Mapping[str, Any],
) -> str:
    planes = (
        snapshot.get("planes")
        if isinstance(snapshot.get("planes"), Mapping)
        else {}
    )
    digest_values = {
        name: str(
            (
                planes.get(name)
                if isinstance(planes.get(name), Mapping)
                else {}
            ).get("fingerprint")
            or ""
        )
        for name in DEVELOPMENT_POLICY_PLANES
    }
    for name in DEVELOPMENT_POLICY_PLANES:
        plane = planes.get(name)
        if isinstance(plane, Mapping) and plane.get("content_sha256"):
            digest_values[f"{name}_content"] = str(plane["content_sha256"])
    folder_profile = (
        snapshot.get("folder_profile")
        if isinstance(snapshot.get("folder_profile"), Mapping)
        else {}
    )
    if folder_profile.get("status") == "loaded":
        digest_values["folder_profile"] = str(folder_profile.get("sha256") or "")
        if folder_profile.get("content_sha256"):
            digest_values["folder_profile_content"] = str(
                folder_profile["content_sha256"]
            )
    selected_profile = snapshot.get("selected_profile")
    if isinstance(selected_profile, Mapping):
        digest_values["selected_profile"] = str(
            selected_profile.get("sha256") or ""
        )
    context_selection = snapshot.get("context_selection")
    if isinstance(context_selection, Mapping):
        digest_values["context_selection"] = str(
            context_selection.get("content_sha256") or ""
        )
    return _json_sha256(digest_values)


def _resolve_development_context_selection(
    root: str | Path,
    domain: str,
    project: str,
    *,
    touched_paths: Sequence[str] = (),
    subjects: Sequence[str] = (),
    rulebook_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Pin path/subject-selected investigation context into a delivery run.

    Development Delivery remains the lifecycle owner.  Investigation contracts
    are used here only as a deterministic, read-only context selector, so a
    selected Rules Engine evidence is frozen once and reused by Readiness,
    implementation, review, and QA instead of being rediscovered per stage.
    """

    # Keep this import local: investigation contracts may use artifact helpers
    # that are intentionally independent from the lifecycle engine at module
    # import time.
    from .investigation_contracts import (
        InvestigationContractError,
        resolve_investigation_contract,
    )

    try:
        resolution = resolve_investigation_contract(
            root,
            trigger="ticket-comment",
            output_type="planning-evidence",
            domain=domain,
            project=project,
            touched_paths=touched_paths,
            subjects=subjects,
            rulebook_ids=rulebook_ids,
        )
    except InvestigationContractError as exc:
        raise DevelopmentDeliveryError(
            f"invalid development context selection: {exc}"
        ) from exc

    selection = resolution.get("selection")
    if not isinstance(selection, Mapping):
        raise DevelopmentDeliveryError("investigation context selection is missing")
    selected_documents = selection.get("selected_documents")
    if not isinstance(selected_documents, list):
        raise DevelopmentDeliveryError("investigation context selection is malformed")
    selected_refs = {
        str(item.get("source_ref") or "")
        for item in selected_documents
        if isinstance(item, Mapping) and str(item.get("source_ref") or "")
    }
    effective = resolution.get("effective")
    effective_documents = (
        effective.get("documents")
        if isinstance(effective, Mapping) and isinstance(effective.get("documents"), list)
        else []
    )
    context_documents: list[dict[str, Any]] = []
    for document in effective_documents:
        if not isinstance(document, Mapping):
            continue
        source_refs = document.get("source_refs")
        if not isinstance(source_refs, list) or not selected_refs.intersection(
            str(item) for item in source_refs
        ):
            continue
        # Store only the deterministic, operator-relevant contract surface.
        # The source hashes in ``selection`` bind these instructions to their
        # exact Markdown inputs without duplicating arbitrary policy metadata.
        context_documents.append(
            {
                key: deepcopy(document[key])
                for key in (
                    "id",
                    "kind",
                    "title",
                    "source_refs",
                    "authority",
                    "freshness",
                    "requirements",
                    "tools",
                    "evidence",
                    "failure",
                    "instructions_markdown",
                )
                if key in document
            }
        )
    context_documents.sort(
        key=lambda item: (str(item.get("id") or ""), str(item.get("title") or ""))
    )
    value: dict[str, Any] = {
        "schema": "development-context-selection/v1",
        "trigger": resolution["trigger"],
        "output_type": resolution["output_type"],
        "policy_fingerprint": resolution["fingerprint"],
        "selection": deepcopy(dict(selection)),
        # These are policy documents, not kit artifacts.  A Rules Engine kit
        # is represented separately below only after concrete files and local
        # evidence have been resolved and hashed.
        "context_documents": context_documents,
    }
    rules_engine_context = selection.get("rules_engine_context")
    if isinstance(rules_engine_context, Mapping):
        value["rules_engine_context"] = deepcopy(dict(rules_engine_context))
    value["content_sha256"] = _json_sha256(value)
    return value


def _validate_frozen_rules_engine_context(
    value: Mapping[str, Any],
    *,
    document_refs: set[str],
) -> None:
    """Verify that only concrete, privacy-safe Rules Engine evidence is loaded."""

    payload = {key: deepcopy(item) for key, item in value.items() if key != "content_sha256"}
    if not (
        value.get("schema") == "rules-engine-frozen-context/v1"
        and value.get("status") in {"loaded", "kit-unavailable", "insufficient-evidence"}
        and isinstance(value.get("source_refs"), list)
        and all(isinstance(item, str) and item in document_refs for item in value["source_refs"])
        and isinstance(value.get("selected_rulebook_ids"), list)
        and all(isinstance(item, str) and item for item in value["selected_rulebook_ids"])
        and value["selected_rulebook_ids"] == sorted(set(value["selected_rulebook_ids"]))
        and isinstance(value.get("catalog"), Mapping)
        and isinstance(value.get("snapshot"), Mapping)
        and isinstance(value.get("known_findings"), Mapping)
        and isinstance(value.get("reason_codes"), list)
        and all(isinstance(item, str) and item for item in value["reason_codes"])
        and re.fullmatch(r"[a-f0-9]{64}", str(value.get("content_sha256") or ""))
        and value.get("content_sha256") == _json_sha256(payload)
    ):
        raise DevelopmentDeliveryError(
            "effective policy receipt has malformed frozen Rules Engine context"
        )
    kit = value.get("kit")
    if value.get("status") != "loaded":
        if kit is not None:
            if not isinstance(kit, Mapping):
                raise DevelopmentDeliveryError(
                    "effective policy receipt has malformed unavailable Rules Engine kit"
                )
        return
    known_findings = value["known_findings"]
    if not (
        isinstance(kit, Mapping)
        and isinstance(kit.get("id"), str)
        and isinstance(kit.get("rulebook"), str)
        and isinstance(kit.get("root_ref"), str)
        and isinstance(kit.get("artifacts"), list)
        and [item.get("name") for item in kit["artifacts"] if isinstance(item, Mapping)]
        == ["contract.yml", "dictionary.yml", "checks.yml", "coverage.yml", "redundancy.yml"]
        and len(kit["artifacts"]) == 5
        and all(
            isinstance(item, Mapping)
            and isinstance(item.get("ref"), str)
            and re.fullmatch(r"[a-f0-9]{64}", str(item.get("sha256") or ""))
            for item in kit["artifacts"]
        )
        and re.fullmatch(r"[a-f0-9]{64}", str(kit.get("content_sha256") or ""))
        and kit.get("content_sha256")
        == _json_sha256({key: deepcopy(item) for key, item in kit.items() if key != "content_sha256"})
        and value["snapshot"].get("status") == "usable"
        and known_findings.get("status") == "available"
        and isinstance(known_findings.get("ref"), str)
        and bool(known_findings["ref"])
        and re.fullmatch(r"[a-f0-9]{64}", str(known_findings.get("sha256") or ""))
        and isinstance(known_findings.get("count"), int)
        and not isinstance(known_findings["count"], bool)
        and known_findings["count"] >= 0
        and isinstance(known_findings.get("items"), list)
        and len(known_findings["items"]) <= min(known_findings["count"], 100)
    ):
        raise DevelopmentDeliveryError(
            "effective policy receipt claims a loaded Rules Engine kit without concrete usable evidence"
        )


def _validate_development_context_selection(value: Mapping[str, Any]) -> None:
    """Reject a tampered or incomplete frozen context selector receipt."""

    payload = {
        key: deepcopy(item)
        for key, item in value.items()
        if key != "content_sha256"
    }
    if not (
        value.get("schema") == "development-context-selection/v1"
        and value.get("trigger") == "ticket-comment"
        and value.get("output_type") == "planning-evidence"
        and re.fullmatch(r"[a-f0-9]{64}", str(value.get("policy_fingerprint") or ""))
        and isinstance(value.get("selection"), Mapping)
        and isinstance(value.get("context_documents", value.get("kits")), list)
        and re.fullmatch(r"[a-f0-9]{64}", str(value.get("content_sha256") or ""))
        and value.get("content_sha256") == _json_sha256(payload)
    ):
        raise DevelopmentDeliveryError(
            "effective policy receipt has invalid frozen context selection"
        )
    selection = value["selection"]
    touched_paths = selection.get("touched_paths")
    subjects = selection.get("subjects")
    rulebook_ids = selection.get("rulebook_ids", [])
    selected_documents = selection.get("selected_documents")
    if not (
        isinstance(touched_paths, list)
        and isinstance(subjects, list)
        and isinstance(rulebook_ids, list)
        and isinstance(selected_documents, list)
        and all(isinstance(item, str) and item for item in touched_paths + subjects + rulebook_ids)
        and touched_paths == sorted(set(touched_paths))
        and subjects == sorted(set(subjects))
        and rulebook_ids == sorted(set(rulebook_ids))
    ):
        raise DevelopmentDeliveryError(
            "effective policy receipt has malformed frozen context selection inputs"
        )
    document_refs: set[str] = set()
    for document in selected_documents:
        if not (
            isinstance(document, Mapping)
            and isinstance(document.get("source_ref"), str)
            and re.fullmatch(r"[a-f0-9]{64}", str(document.get("sha256") or ""))
            and isinstance(document.get("selectors"), Mapping)
        ):
            raise DevelopmentDeliveryError(
                "effective policy receipt has malformed frozen context selection provenance"
            )
        document_refs.add(document["source_ref"])
    context_documents = value.get("context_documents", value.get("kits", []))
    for kit in context_documents:
        refs = kit.get("source_refs") if isinstance(kit, Mapping) else None
        if not (
            isinstance(kit, Mapping)
            and isinstance(kit.get("id"), str)
            and isinstance(refs, list)
            and document_refs.intersection(str(ref) for ref in refs)
        ):
            raise DevelopmentDeliveryError(
                "effective policy receipt has malformed frozen context kit"
            )
    rules_engine_context = value.get("rules_engine_context")
    if rules_engine_context is not None:
        if not isinstance(rules_engine_context, Mapping):
            raise DevelopmentDeliveryError(
                "effective policy receipt has malformed frozen Rules Engine context"
            )
        _validate_frozen_rules_engine_context(
            rules_engine_context,
            document_refs=document_refs,
        )


def _validate_effective_policy_snapshot(
    snapshot: Mapping[str, Any],
    *,
    require_selected_profile: bool,
) -> Mapping[str, Any] | None:
    """Verify every digest in an immutable development-policy snapshot."""

    if snapshot.get("schema") != "development-effective-policies/v1":
        raise DevelopmentDeliveryError("invalid effective policy receipt schema")
    planes = (
        snapshot.get("planes")
        if isinstance(snapshot.get("planes"), Mapping)
        else {}
    )
    for name in DEVELOPMENT_POLICY_PLANES:
        plane = planes.get(name)
        if not (
            isinstance(plane, Mapping)
            and re.fullmatch(r"[a-f0-9]{64}", str(plane.get("fingerprint") or ""))
        ):
            raise DevelopmentDeliveryError(
                f"effective policy receipt has invalid {name} fingerprint"
            )
        sources = plane.get("sources")
        if not isinstance(sources, list):
            raise DevelopmentDeliveryError(
                f"effective policy receipt has invalid {name} sources"
            )
        digest_input: list[dict[str, Any]] = []
        for source in sources:
            if not (
                isinstance(source, Mapping)
                and isinstance(source.get("scope"), str)
                and isinstance(source.get("rank"), int)
                and isinstance(source.get("source_ref"), str)
                and re.fullmatch(
                    r"[a-f0-9]{64}", str(source.get("sha256") or "")
                )
            ):
                raise DevelopmentDeliveryError(
                    f"effective policy receipt has invalid {name} source evidence"
                )
            digest_input.append(
                {
                    "scope": source["scope"],
                    "rank": source["rank"],
                    "source_ref": source["source_ref"],
                    "sha256": source["sha256"],
                }
            )
        if plane.get("fingerprint") != hashlib.sha256(
            json.dumps(
                digest_input,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest():
            raise DevelopmentDeliveryError(
                f"effective policy receipt has changed {name} source evidence"
            )
        content_hash = plane.get("content_sha256")
        if content_hash is not None:
            content_payload = {
                key: deepcopy(value)
                for key, value in plane.items()
                if key != "content_sha256"
            }
            if not (
                re.fullmatch(r"[a-f0-9]{64}", str(content_hash))
                and content_hash == _json_sha256(content_payload)
            ):
                raise DevelopmentDeliveryError(
                    f"effective policy receipt has changed {name} content"
                )
        elif not all(
            isinstance(source, Mapping)
            and _legacy_policy_source_content_is_bound(source)
            for source in sources
        ):
            raise DevelopmentDeliveryError(
                f"effective policy receipt has unbound legacy {name} content"
            )
    folder_profile = snapshot.get("folder_profile")
    if "folder_profile" in snapshot:
        if (
            not isinstance(folder_profile, Mapping)
            or folder_profile.get("status")
            not in {"loaded", "not_configured"}
        ):
            raise DevelopmentDeliveryError(
                "effective policy receipt has invalid repository folder profile"
            )
        if (
            folder_profile.get("status") == "loaded"
            and not re.fullmatch(
                r"[a-f0-9]{64}", str(folder_profile.get("sha256") or "")
            )
        ):
            raise DevelopmentDeliveryError(
                "effective policy receipt has invalid repository folder profile hash"
            )
        folder_content_hash = folder_profile.get("content_sha256")
        if folder_content_hash is not None:
            folder_content_payload = {
                key: deepcopy(value)
                for key, value in folder_profile.items()
                if key != "content_sha256"
            }
            if not (
                re.fullmatch(r"[a-f0-9]{64}", str(folder_content_hash))
                and folder_content_hash == _json_sha256(folder_content_payload)
            ):
                raise DevelopmentDeliveryError(
                    "effective policy receipt has changed repository folder profile content"
                )
        elif folder_profile.get("status") == "loaded":
            raise DevelopmentDeliveryError(
                "effective policy receipt has unbound legacy repository folder profile content"
            )
    selected_profile = snapshot.get("selected_profile")
    if selected_profile is None:
        if require_selected_profile:
            raise DevelopmentDeliveryError(
                "effective policy receipt lacks frozen selected repository authority"
            )
    elif not isinstance(selected_profile, Mapping):
        raise DevelopmentDeliveryError(
            "effective policy receipt has malformed selected repository authority"
        )
    else:
        selected_payload = {
            key: deepcopy(value)
            for key, value in selected_profile.items()
            if key != "sha256"
        }
        if not (
            selected_profile.get("schema") == "development-selected-profile/v1"
            and isinstance(selected_profile.get("validation"), Mapping)
            and re.fullmatch(
                r"[a-f0-9]{64}", str(selected_profile.get("sha256") or "")
            )
            and selected_profile.get("sha256") == _json_sha256(selected_payload)
        ):
            raise DevelopmentDeliveryError(
                "effective policy receipt has invalid selected repository authority"
            )
    context_selection = snapshot.get("context_selection")
    if context_selection is not None:
        if not isinstance(context_selection, Mapping):
            raise DevelopmentDeliveryError(
                "effective policy receipt has malformed frozen context selection"
            )
        _validate_development_context_selection(context_selection)
    expected = _effective_policy_snapshot_fingerprint(snapshot)
    if (
        not re.fullmatch(r"[a-f0-9]{64}", str(snapshot.get("fingerprint") or ""))
        or snapshot.get("fingerprint") != expected
    ):
        raise DevelopmentDeliveryError(
            "effective policy receipt fingerprint does not match its contents"
        )
    return selected_profile if isinstance(selected_profile, Mapping) else None


def resolve_development_policies(
    root: str | Path,
    domain: str,
    project: str,
    *,
    explicit_files: Mapping[str, Sequence[str | Path]] | None = None,
    selected_profile: Mapping[str, Any] | None = None,
    profile_source: str | Path | None = None,
    include_body: bool = False,
    touched_paths: Sequence[str] = (),
    subjects: Sequence[str] = (),
    rulebook_ids: Sequence[str] = (),
    context_selection_override: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve every development policy plane consumed by an SDLC run."""

    if selected_profile is None:
        effective_profile, effective_source = load_development_policy_profile(
            root,
            domain,
            project,
        )
    else:
        effective_profile = deepcopy(dict(selected_profile))
        effective_source = profile_source
    planes = {
        plane: resolve_development_policy(
            root,
            domain,
            project,
            plane,
            explicit_files=(explicit_files or {}).get(plane, ()),
            selected_profile=effective_profile,
            profile_source=effective_source,
            include_body=include_body,
        )
        for plane in DEVELOPMENT_POLICY_PLANES
    }
    for plane in planes.values():
        plane["content_sha256"] = _json_sha256(plane)
    folder_profile = resolve_auto_dev_folder_profile(
        effective_profile,
        domain=domain,
        project=project,
    )
    selected_profile_authority = _selected_profile_policy_authority(
        effective_profile
    )
    if context_selection_override is None:
        context_selection = _resolve_development_context_selection(
            root,
            domain,
            project,
            touched_paths=touched_paths,
            subjects=subjects,
            rulebook_ids=rulebook_ids,
        )
    else:
        context_selection = deepcopy(dict(context_selection_override))
        _validate_development_context_selection(context_selection)
    value = {
        "schema": "development-effective-policies/v1",
        "domain": normalize_domain(domain),
        "project": validate_name(project, "project"),
        "planes": planes,
        "folder_profile": folder_profile,
        "selected_profile": selected_profile_authority,
        "context_selection": context_selection,
    }
    value["fingerprint"] = _effective_policy_snapshot_fingerprint(value)
    _validate_effective_policy_snapshot(value, require_selected_profile=True)
    return value


def required_test_layers(risk: str, *, changed_behavior: bool = True) -> list[str]:
    """Return the smallest complete testing triangle justified by risk."""
    normalized = risk.strip().lower()
    if normalized not in {"micro", "standard", "high"}:
        raise DevelopmentDeliveryError("risk must be one of micro, standard, high")
    if not changed_behavior:
        return ["static_validation"]
    return {
        "micro": ["unit"],
        "standard": ["unit", "integration"],
        "high": ["unit", "integration", "end_to_end"],
    }[normalized]


def classify_validation(*, returncode: int, environment_evidence: str | None = None) -> str:
    if returncode == 0:
        return "passed"
    if environment_evidence and environment_evidence.strip():
        return "environment_unavailable"
    return "code_failed"


def _event_id(idempotency_key: str) -> str:
    return "dev_evt_" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:16]


def append_event(ledger: Path, *, event_type: str, idempotency_key: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Append once to JSONL; replaying an idempotency key is a no-op."""
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with _file_lock(ledger.with_suffix(ledger.suffix + ".lock")):
        if ledger.is_file():
            for line in ledger.read_text(encoding="utf-8").splitlines():
                if line.strip() and json.loads(line).get("idempotency_key") == idempotency_key:
                    return {"appended": False, "event_id": _event_id(idempotency_key)}
        event = {
            "id": _event_id(idempotency_key),
            "type": event_type,
            "occurred_at": utc_now(),
            "idempotency_key": idempotency_key,
            "payload": dict(payload),
        }
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
    return {"appended": True, "event_id": event["id"]}


def _legal_transition(current: str, target: str) -> bool:
    if target in {"blocked", "abandoned", "cancelled"} and current not in TERMINAL_STATES:
        return True
    if current not in FORWARD_STATES or target not in FORWARD_STATES:
        return False
    return FORWARD_STATES.index(target) == FORWARD_STATES.index(current) + 1


def _portfolio_rollup(states: Sequence[str]) -> str:
    if not states:
        return "accepted"
    distinct = set(states)
    if len(distinct) == 1:
        only = states[0]
        return "dispatching" if only == "worktree_ready" else only
    if all(state == "blocked" for state in states):
        return "blocked"
    return "partial"


def _refresh_portfolio_state(task_state_path: Path) -> None:
    """Roll task state into its portfolio after every governed mutation."""

    run_dir = task_state_path.parent.parent.parent
    portfolio_path = run_dir / "portfolio.json"
    if not portfolio_path.is_file():
        return
    with _file_lock(portfolio_path.with_suffix(portfolio_path.suffix + ".lock")):
        portfolio = _read_mapping(portfolio_path)
        states: list[str] = []
        for row in portfolio.get("tasks") or []:
            if not isinstance(row, Mapping) or not row.get("state_ref"):
                continue
            candidate = Path(str(row["state_ref"])).expanduser()
            if not candidate.is_absolute():
                candidate = (run_dir / candidate).resolve()
            if not candidate.is_file():
                continue
            payload = _read_mapping(candidate)
            if payload.get("state"):
                states.append(str(payload["state"]))
        if not states:
            return
        rollup = _portfolio_rollup(states)
        if portfolio.get("state") == rollup:
            return
        portfolio["state"] = rollup
        portfolio["updated_at"] = utc_now()
        _atomic_json(portfolio_path, portfolio)


def _sync_auto_dev_projection(task_state_path: Path) -> dict[str, Any] | None:
    """Refresh the non-canonical projection without rolling back committed delivery state."""

    try:
        return sync_delivery_projection(task_state_path)
    except (AutoDevStateError, OSError) as exc:
        task = _read_mapping(task_state_path)
        append_event(
            task_state_path.parent / "events.jsonl",
            event_type="development.autodev_projection.sync_failed",
            idempotency_key=(
                f"{task.get('run_id')}:{task.get('ticket')}:projection-sync-failed:"
                f"{task.get('updated_at')}"
            ),
            payload={
                "ticket": task.get("ticket"),
                "projection": task.get("autodev_path"),
                "error": str(exc),
                "recovery": "repair autodev.json, then run agentic-os auto-dev sync",
            },
        )
        return None


@dataclass
class TaskState:
    path: Path

    @property
    def ledger(self) -> Path:
        return self.path.parent / "events.jsonl"

    def read(self) -> dict[str, Any]:
        if not self.path.is_file():
            raise DevelopmentDeliveryError(f"task state not found: {self.path}")
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise DevelopmentDeliveryError(f"invalid task state: {self.path}")
        return value

    def emit(self, *, event_type: str, idempotency_key: str, payload: Mapping[str, Any]) -> None:
        """Write the task ledger and its optional root rollup pointer ledger."""
        append_event(self.ledger, event_type=event_type, idempotency_key=idempotency_key, payload=payload)
        state = self.read()
        rollup = state.get("rollup_ledger")
        if rollup:
            append_event(Path(str(rollup)), event_type=event_type, idempotency_key=idempotency_key, payload=payload)

    def transition(self, target: str, *, receipt: str, idempotency_key: str) -> dict[str, Any]:
        replayed = False
        with _file_lock(self.path.with_suffix(self.path.suffix + ".lock")):
            state = self.read()
            current = str(state["state"])
            if state.get("last_transition_key") == idempotency_key:
                replayed = True
            else:
                if not receipt.strip():
                    raise DevelopmentDeliveryError("every transition requires a receipt")
                if not _legal_transition(current, target):
                    raise DevelopmentDeliveryError(f"illegal transition: {current} -> {target}")
                now = utc_now()
                state.update({"state": target, "updated_at": now, "last_transition_key": idempotency_key})
                receipt_row = {"state": target, "ref": receipt, "recorded_at": now}
                receipt_path = Path(receipt).expanduser()
                if receipt_path.is_file():
                    receipt_row["sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
                state.setdefault("receipts", []).append(receipt_row)
                _atomic_json(self.path, state)
        if replayed:
            _refresh_portfolio_state(self.path)
            _sync_auto_dev_projection(self.path)
            _sync_canonical_task_progress(self.path)
            return state
        self.emit(
            event_type="development.task.transitioned",
            idempotency_key=idempotency_key,
            payload={"ticket": state["ticket"], "from": current, "to": target, "receipt": receipt},
        )
        _refresh_portfolio_state(self.path)
        _sync_auto_dev_projection(self.path)
        _sync_canonical_task_progress(self.path)
        return state

    def fail(
        self,
        *,
        kind: str,
        detail: str,
        receipt: str,
        idempotency_key: str,
        sync_canonical: bool = True,
    ) -> dict[str, Any]:
        replayed = False
        with _file_lock(self.path.with_suffix(self.path.suffix + ".lock")):
            state = self.read()
            if state.get("last_failure_key") == idempotency_key:
                replayed = True
            else:
                attempts = int(state.get("attempts", {}).get(kind, 0)) + 1
                state.setdefault("attempts", {})[kind] = attempts
                maximum = int(state.get("max_attempts", 3))
                recoverable = kind in RETRYABLE_FAILURES and attempts < maximum
                state["failure"] = {
                    "kind": kind,
                    "detail": detail,
                    "receipt": receipt,
                    "recoverable": recoverable,
                    "failed_at": utc_now(),
                    "retry_state": state["state"] if recoverable else None,
                }
                if not recoverable:
                    state["state"] = "blocked"
                state["updated_at"] = utc_now()
                state["last_failure_key"] = idempotency_key
                _atomic_json(self.path, state)
        if replayed:
            _refresh_portfolio_state(self.path)
            _sync_auto_dev_projection(self.path)
            if sync_canonical:
                _sync_canonical_task_progress(self.path)
            return state
        self.emit(
            event_type="development.task.failed",
            idempotency_key=idempotency_key,
            payload={"ticket": state["ticket"], **state["failure"], "attempt": attempts},
        )
        _refresh_portfolio_state(self.path)
        _sync_auto_dev_projection(self.path)
        if sync_canonical:
            _sync_canonical_task_progress(self.path)
        return state

    def record_executor_unavailable(self, *, stage: str | None) -> dict[str, Any]:
        """Atomically bind one unaccepted post-materialization handoff to its task.

        A runtime registration establishes only resource ownership; it is not
        executor admission.  Keep the provisioned worktree intact until a
        recorded acceptance or bounded synchronous stage attempt exists, but
        make the missing handoff durable and retry-bounded instead of returning
        a successful-looking dispatch result.
        """

        replayed = False
        handoff: dict[str, Any]
        with _file_lock(self.path.with_suffix(self.path.suffix + ".lock")):
            state = self.read()
            failure = state.get("failure") if isinstance(state.get("failure"), Mapping) else {}
            prior_receipt = Path(str(failure.get("receipt") or "")).expanduser()
            prior_attempt = int(state.get("attempts", {}).get("executor_unavailable", 0))
            maximum = int(state.get("max_attempts", 3))
            if (
                failure.get("kind") == "executor_unavailable"
                and prior_receipt.is_file()
                and prior_attempt >= maximum
            ):
                # A terminal refusal is idempotent: preserve the bound receipt
                # instead of creating an unbounded fourth handoff.
                handoff = _read_mapping(prior_receipt)
                replayed = True
            else:
                # A still-pending refusal is a new failed handoff on the exact
                # packet. Keep its prior receipt immutable and advance toward
                # the configured bound; only an orphaned receipt from an
                # interrupted first write is reused below.
                attempt = prior_attempt + 1
                recoverable = attempt < maximum
                runtime = state.get("runtime") if isinstance(state.get("runtime"), Mapping) else {}
                worktree = state.get("worktree") if isinstance(state.get("worktree"), Mapping) else {}
                receipt_path = (
                    self.path.parent
                    / "handoffs"
                    / f"executor-unavailable-attempt-{attempt:02d}.json"
                )
                handoff = {
                    "schema": "development-executor-handoff/v1",
                    "status": "pending" if recoverable else "blocked",
                    "outcome": "executor_unavailable",
                    "attempt": attempt,
                    "max_attempts": maximum,
                    "recoverable": recoverable,
                    "run_id": state.get("run_id"),
                    "ticket": state.get("ticket"),
                    "canonical_work_id": state.get("canonical_work_id"),
                    "task_state": str(self.path),
                    "task_state_before_handoff": state.get("state"),
                    "requested_stage": state.get("requested_stage"),
                    "next_stage": stage,
                    "worktree": dict(worktree),
                    "policy": {
                        "fingerprint": state.get("policy_fingerprint"),
                        "receipt": state.get("policy_receipt"),
                    },
                    "runtime": dict(runtime),
                    "reason": (
                        "No recorded executor acceptance or bounded synchronous stage attempt "
                        "followed the post-materialization Auto-Dev handoff; no stage was "
                        "executed or receipted."
                        if recoverable
                        else "No recorded executor acceptance or bounded synchronous stage attempt "
                        "followed the post-materialization Auto-Dev handoff before the retry "
                        "budget was exhausted; no stage was executed or receipted."
                    ),
                    "next_action": (
                        "Record executor acceptance or a bounded synchronous stage attempt, then "
                        "resume this exact task; do not infer completion from the preserved worktree."
                        if recoverable
                        else "Correct the executor acceptance path and explicitly reopen or recover "
                        "this blocked task before attempting another handoff."
                    ),
                    "recorded_at": utc_now(),
                }
                if receipt_path.is_file():
                    existing_handoff = _read_mapping(receipt_path)
                    comparable_existing = {
                        key: value
                        for key, value in existing_handoff.items()
                        if key != "recorded_at"
                    }
                    comparable_handoff = {
                        key: value for key, value in handoff.items() if key != "recorded_at"
                    }
                    if comparable_existing != comparable_handoff:
                        raise DevelopmentDeliveryError("executor handoff receipt collision")
                    # A crash after the receipt write but before the state write
                    # leaves this exact, valid receipt orphaned. Reuse it so the
                    # retry can atomically finish binding the failure to its task.
                    handoff = existing_handoff
                else:
                    _atomic_json(receipt_path, handoff)
                state.setdefault("attempts", {})["executor_unavailable"] = attempt
                state["failure"] = {
                    "kind": "executor_unavailable",
                    "detail": handoff["reason"],
                    "receipt": str(receipt_path),
                    "recoverable": recoverable,
                    "failed_at": handoff["recorded_at"],
                    # A terminal executor refusal still has an operator-supported
                    # recovery path once executor admission is repaired.
                    "retry_state": state["state"],
                }
                if not recoverable:
                    state["state"] = "blocked"
                state["updated_at"] = utc_now()
                state["last_failure_key"] = (
                    f"{state['run_id']}:{state['ticket']}:executor-unavailable:{attempt}"
                )
                _atomic_json(self.path, state)
        if replayed:
            _refresh_portfolio_state(self.path)
            _sync_auto_dev_projection(self.path)
            _sync_canonical_task_progress(self.path)
            return {"task": state, "handoff": handoff, "replayed": True}
        self.emit(
            event_type=(
                "development.task.executor_handoff_pending"
                if handoff["status"] == "pending"
                else "development.task.executor_handoff_blocked"
            ),
            idempotency_key=state["last_failure_key"],
            payload={
                "ticket": state["ticket"],
                "stage": stage,
                "attempt": handoff["attempt"],
                "receipt": str(self.path.parent / "handoffs" / f"executor-unavailable-attempt-{handoff['attempt']:02d}.json"),
                "recoverable": handoff["recoverable"],
            },
        )
        self.emit(
            event_type="development.task.failed",
            idempotency_key=f"{state['last_failure_key']}:failed",
            payload={"ticket": state["ticket"], **state["failure"], "attempt": handoff["attempt"]},
        )
        _refresh_portfolio_state(self.path)
        _sync_auto_dev_projection(self.path)
        _sync_canonical_task_progress(self.path)
        return {"task": state, "handoff": handoff, "replayed": False}

    def recover(self, *, receipt: str, idempotency_key: str) -> dict[str, Any]:
        replayed = False
        with _file_lock(self.path.with_suffix(self.path.suffix + ".lock")):
            state = self.read()
            if state.get("last_recovery_key") == idempotency_key:
                replayed = True
            else:
                if not receipt.strip():
                    raise DevelopmentDeliveryError("recovery requires a receipt")
                failure = state.get("failure") if isinstance(state.get("failure"), Mapping) else {}
                retry_state = failure.get("retry_state")
                terminal_executor_handoff = (
                    failure.get("kind") == "executor_unavailable" and retry_state
                )
                if not retry_state or (
                    not failure.get("recoverable") and not terminal_executor_handoff
                ):
                    raise DevelopmentDeliveryError("task has no recoverable failure")
                now = utc_now()
                state["state"] = retry_state
                state["failure"] = None
                state["updated_at"] = now
                state["last_recovery_key"] = idempotency_key
                state.setdefault("receipts", []).append({"state": retry_state, "ref": receipt, "recorded_at": now})
                _atomic_json(self.path, state)
        if replayed:
            _refresh_portfolio_state(self.path)
            _sync_auto_dev_projection(self.path)
            _sync_canonical_task_progress(self.path, allow_unblock=True)
            return state
        self.emit(
            event_type="development.task.recovered",
            idempotency_key=idempotency_key,
            payload={"ticket": state["ticket"], "to": retry_state, "receipt": receipt},
        )
        _refresh_portfolio_state(self.path)
        _sync_auto_dev_projection(self.path)
        _sync_canonical_task_progress(self.path, allow_unblock=True)
        return state

    def recover_stale_lease(self, *, now: datetime | None = None) -> dict[str, Any]:
        state = self.read()
        lease = state.get("lease") if isinstance(state.get("lease"), Mapping) else {}
        until = lease.get("until")
        if not until:
            return {"recovered": False, "reason": "no_lease"}
        current = now or datetime.now(timezone.utc)
        expiry = datetime.fromisoformat(str(until).replace("Z", "+00:00"))
        if expiry > current:
            return {"recovered": False, "reason": "lease_active"}
        key = f"{state['run_id']}:{state['ticket']}:stale-lease:{until}"
        self.fail(kind="lease_expired", detail="worker heartbeat lease expired", receipt=str(self.path), idempotency_key=key)
        return {"recovered": True, "reason": "lease_expired"}

    def heartbeat(self, *, owner: str, lease_minutes: int, idempotency_key: str) -> dict[str, Any]:
        """Renew task ownership without changing lifecycle state."""
        if not owner.strip() or lease_minutes < 1:
            raise DevelopmentDeliveryError("heartbeat requires an owner and positive lease_minutes")
        with _file_lock(self.path.with_suffix(self.path.suffix + ".lock")):
            state = self.read()
            if state.get("last_heartbeat_key") == idempotency_key:
                _sync_auto_dev_projection(self.path)
                return state
            if state.get("state") in TERMINAL_STATES:
                raise DevelopmentDeliveryError("cannot heartbeat a terminal task")
            now = datetime.now(timezone.utc).replace(microsecond=0)
            until = (now + timedelta(minutes=lease_minutes)).isoformat().replace("+00:00", "Z")
            state["lease"] = {
                "owner": owner,
                "heartbeat_at": now.isoformat().replace("+00:00", "Z"),
                "until": until,
            }
            state["updated_at"] = now.isoformat().replace("+00:00", "Z")
            state["last_heartbeat_key"] = idempotency_key
            _atomic_json(self.path, state)
        self.emit(
            event_type="development.task.heartbeat",
            idempotency_key=idempotency_key,
            payload={"ticket": state["ticket"], "owner": owner, "until": until},
        )
        _sync_auto_dev_projection(self.path)
        return state


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:48] or "task"


def _canonical_development_work_id(domain: str, project: str, ticket: str) -> str:
    return f"{normalize_domain(domain)}:{validate_name(project, 'project')}:{_slug(ticket)}"


def _canonical_source_match(
    connection,
    *,
    domain: str,
    project: str,
    tracker: str,
    ticket: str,
    preferred_id: str | None = None,
) -> dict[str, Any] | None:
    """Resolve one canonical row without silently changing source identity."""

    normalized_domain = normalize_domain(domain)
    normalized_project = validate_name(project, "project")
    source_row = connection.execute(
        "SELECT id FROM work_items WHERE source_system = ? AND source_key = ?",
        (tracker, ticket),
    ).fetchone()
    source_match = (
        canonical_work_items.get(connection, str(source_row["id"]))
        if source_row is not None
        else None
    )
    if source_match and (
        source_match.get("domain") != normalized_domain
        or source_match.get("project") != normalized_project
    ):
        raise DevelopmentDeliveryError(
            f"canonical source identity {tracker}:{ticket} belongs to another project"
        )
    preferred = canonical_work_items.get(connection, preferred_id) if preferred_id else None
    if preferred is not None:
        if (
            preferred.get("domain") != normalized_domain
            or preferred.get("project") != normalized_project
            or str(preferred.get("source_key") or "") != ticket
        ):
            raise DevelopmentDeliveryError(
                f"canonical work item identity does not match {ticket}: {preferred_id}"
            )
        if source_match and source_match["id"] != preferred["id"]:
            raise DevelopmentDeliveryError(
                f"canonical source identity for {ticket} conflicts with {preferred_id}"
            )
        return preferred
    if source_match:
        return source_match
    derived_id = _canonical_development_work_id(domain, project, ticket)
    derived = canonical_work_items.get(connection, derived_id)
    if derived is not None:
        derived_source = (
            str(derived.get("source_system") or ""),
            str(derived.get("source_key") or ""),
        )
        if (
            derived.get("domain") != normalized_domain
            or derived.get("project") != normalized_project
            or derived_source not in {("", ""), (tracker, ticket)}
        ):
            raise DevelopmentDeliveryError(
                f"derived canonical work id already belongs to another source: {derived_id}"
            )
    return derived


def _resolve_canonical_development_work_id(
    root: str | Path,
    *,
    domain: str,
    project: str,
    tracker: str,
    ticket: str,
    preferred_id: str | None = None,
    packet: Path | None = None,
    diagnostic_root: Path | None = None,
) -> str:
    def resolve() -> str:
        connection = connect_state(
            default_db_path(root),
            busy_timeout_ms=CANONICAL_ADMISSION_BUSY_TIMEOUT_MS,
        )
        try:
            existing = _canonical_source_match(
                connection,
                domain=domain,
                project=project,
                tracker=tracker,
                ticket=ticket,
                preferred_id=preferred_id,
            )
            return str(
                (existing or {}).get("id")
                or preferred_id
                or _canonical_development_work_id(domain, project, ticket)
            )
        finally:
            connection.close()

    return str(
        _run_canonical_admission(
            resolve,
            ticket=ticket,
            canonical_work_id=preferred_id or _canonical_development_work_id(domain, project, ticket),
            operation="resolve_canonical_development_work_id",
            packet=packet,
            diagnostic_root=diagnostic_root,
        )
    )


def _read_canonical_development_work(
    root: str | Path,
    *,
    canonical_work_id: str,
    ticket: str,
    packet: Path | None = None,
    diagnostic_root: Path | None = None,
) -> dict[str, Any] | None:
    """Read one canonical row through the same bounded admission boundary."""

    def read() -> dict[str, Any] | None:
        connection = connect_state(
            default_db_path(root),
            busy_timeout_ms=CANONICAL_ADMISSION_BUSY_TIMEOUT_MS,
        )
        try:
            return canonical_work_items.get(connection, canonical_work_id)
        finally:
            connection.close()

    result = _run_canonical_admission(
        read,
        ticket=ticket,
        canonical_work_id=canonical_work_id,
        operation="read_canonical_development_work",
        packet=packet,
        diagnostic_root=diagnostic_root,
    )
    return dict(result) if isinstance(result, Mapping) else None


def _canonical_packet_match(
    root: str | Path,
    *,
    domain: str,
    project: str,
    ticket: str,
    packet: Path,
) -> dict[str, Any]:
    """Resolve one existing canonical row by its exact packet path for migration."""

    os_root = expand_path(root)
    def query() -> list[dict[str, Any]]:
        connection = connect_state(
            default_db_path(root),
            busy_timeout_ms=CANONICAL_ADMISSION_BUSY_TIMEOUT_MS,
        )
        try:
            return canonical_work_items.query(
                connection,
                domain=normalize_domain(domain),
                project=validate_name(project, "project"),
                limit=10000,
            )
        finally:
            connection.close()

    rows = _run_canonical_admission(
        query,
        ticket=ticket,
        canonical_work_id=None,
        operation="query_canonical_development_packets",
        packet=packet,
    )
    matches: list[dict[str, Any]] = []
    for row in rows:
        raw = str(row.get("packet_path") or "").strip()
        if not raw:
            continue
        value = Path(raw).expanduser()
        resolved = value.resolve() if value.is_absolute() else (os_root / value).resolve()
        if resolved == packet.resolve():
            matches.append(row)
    if len(matches) != 1:
        raise DevelopmentDeliveryError(
            "Auto-Dev adoption requires exactly one canonical work row for the selected packet"
        )
    row = matches[0]
    if str(row.get("source_key") or "") != ticket:
        raise DevelopmentDeliveryError(
            "Auto-Dev adoption ticket does not match the selected packet's canonical source key"
        )
    if row.get("state") in canonical_work_items.TERMINAL_STATES or row.get("attention") == "closed":
        raise DevelopmentDeliveryError("Auto-Dev adoption requires an active canonical work item")
    return row


def _canonical_state_for_delivery(
    delivery_state: str,
    *,
    worktree: Mapping[str, Any] | None,
) -> str:
    if delivery_state == "blocked":
        return "blocked"
    if delivery_state in FORWARD_STATES:
        index = FORWARD_STATES.index(delivery_state)
        if index >= FORWARD_STATES.index("local_validation"):
            return "validating"
        if index >= FORWARD_STATES.index("worktree_ready") or worktree:
            return "building"
    return "ready"


def _is_transient_sqlite_contention(exc: sqlite3.OperationalError) -> bool:
    """Return whether SQLite rejected a write because another owner is active."""

    detail = str(exc).lower()
    return "database is locked" in detail or "database is busy" in detail


def _canonical_admission_contention_receipt(
    packet: Path | None,
    *,
    ticket: str,
    canonical_work_id: str | None,
    attempts: int,
    delays: Sequence[float],
    error: str,
    outcome: str,
    operation: str,
    diagnostic_root: Path | None = None,
) -> str | None:
    """Persist a compact diagnostic for a contended canonical admission.

    The control-plane row is intentionally not used for this receipt.  Once a
    packet exists it owns the durable diagnostic; before packet admission, the
    caller provides a project-scoped preflight location instead of creating a
    partial run directory that a same-run-id retry could not resume.
    """

    if packet is not None and packet.is_dir():
        directory = packet / "artifacts" / "development-delivery"
    elif diagnostic_root is not None:
        directory = diagnostic_root / "admission-receipts"
    else:
        return None
    recorded_at = utc_now()
    receipt = directory / (
        "canonical-admission-contention-"
        f"{recorded_at.replace(':', '').replace('-', '').replace('+00:00', 'Z')}-"
        f"{uuid.uuid4().hex[:12]}.json"
    )
    if outcome == "exhausted":
        next_action = (
            "Resume the existing Auto-Dev packet after the current state-db writer releases its transaction."
            if packet is not None and packet.is_dir()
            else "Re-run this exact Auto-Dev run after the current state-db writer releases its transaction."
        )
    else:
        next_action = "Canonical admission completed without creating a second lifecycle transition."
    payload = {
        "schema": "development-canonical-admission-contention/v1",
        "ticket": ticket,
        "canonical_work_id": canonical_work_id,
        "operation": operation,
        "outcome": outcome,
        "attempts": attempts,
        "backoff_seconds": list(delays),
        "error": error,
        "recorded_at": recorded_at,
        "next_action": next_action,
    }
    _atomic_json(
        receipt,
        payload,
    )
    _atomic_json(
        directory / "canonical-admission-contention-latest.json",
        {
            "schema": "development-canonical-admission-contention-latest/v1",
            "latest_receipt": str(receipt),
            "latest_receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
            "updated_at": recorded_at,
        },
    )
    return str(receipt)


def _preflight_admission_diagnostic_root(project_path: Path, run_id: str) -> Path:
    """Return the durable, non-run-directory receipt root for preflight.

    Canonical identity lookup happens before ``portfolio.json`` is created.
    A failed lookup must therefore not create ``state/development-runs/<id>``:
    that directory denotes an admitted run and its presence without a
    portfolio receipt is intentionally rejected on replay.  Keep the
    append-only diagnostics adjacent to project artifacts until admission can
    establish the run directory atomically through its portfolio receipt.
    """

    return (
        project_path
        / "artifacts"
        / "development-delivery"
        / "admission-preflight"
        / run_id
    )


def _run_canonical_admission(
    operation_fn: Callable[[], Any],
    *,
    ticket: str,
    canonical_work_id: str | None,
    operation: str,
    packet: Path | None = None,
    diagnostic_root: Path | None = None,
) -> Any:
    """Run every canonical-state DB access under one bounded lock policy."""

    delays: list[float] = []
    last_error: sqlite3.OperationalError | None = None
    for attempt in range(1, CANONICAL_ADMISSION_MAX_ATTEMPTS + 1):
        try:
            result = operation_fn()
        except sqlite3.OperationalError as exc:
            if not _is_transient_sqlite_contention(exc):
                raise
            last_error = exc
            if attempt == CANONICAL_ADMISSION_MAX_ATTEMPTS:
                receipt = _canonical_admission_contention_receipt(
                    packet,
                    ticket=ticket,
                    canonical_work_id=canonical_work_id,
                    attempts=attempt,
                    delays=delays,
                    error=str(exc),
                    outcome="exhausted",
                    operation=operation,
                    diagnostic_root=diagnostic_root,
                )
                recovery = (
                    "Resume the existing packet; do not create a replacement run."
                    if packet is not None and packet.is_dir()
                    else "Re-run this exact Auto-Dev run; do not create a replacement packet."
                )
                diagnostic = f" Diagnostic receipt: {receipt}." if receipt else ""
                raise DevelopmentDeliveryError(
                    "canonical Auto-Dev admission could not acquire the state database write lock "
                    f"after {attempt} bounded attempts.{diagnostic} {recovery}"
                ) from exc
            delay = CANONICAL_ADMISSION_BACKOFF_SECONDS * (2 ** (attempt - 1))
            delays.append(delay)
            time.sleep(delay)
        else:
            if last_error is not None:
                _canonical_admission_contention_receipt(
                    packet,
                    ticket=ticket,
                    canonical_work_id=canonical_work_id,
                    attempts=attempt,
                    delays=delays,
                    error=str(last_error),
                    outcome="retried",
                    operation=operation,
                    diagnostic_root=diagnostic_root,
                )
            return result
    raise AssertionError("canonical admission retry loop exhausted without a result")


def _sync_canonical_development_work(
    root: str | Path,
    *,
    domain: str,
    project: str,
    ticket: str,
    title: str,
    run_id: str,
    tracker: str,
    packet: Path,
    worktree: Mapping[str, Any] | None,
    delivery_state: str,
    canonical_work_id: str | None = None,
    blocked_reason: str | None = None,
    allow_unblock: bool = False,
) -> dict[str, Any]:
    """Synchronize canonical state with bounded retry for a busy SQLite writer.

    Each attempt opens and closes a fresh connection before backoff.  That
    makes an interrupted supervisor tick unable to keep the next Auto-Dev
    admission pinned behind its abandoned transaction, while the upsert's
    stable work id keeps replay from creating a duplicate lifecycle row.
    """

    return _run_canonical_admission(
        lambda: _sync_canonical_development_work_once(
            root,
            domain=domain,
            project=project,
            ticket=ticket,
            title=title,
            run_id=run_id,
            tracker=tracker,
            packet=packet,
            worktree=worktree,
            delivery_state=delivery_state,
            canonical_work_id=canonical_work_id,
            blocked_reason=blocked_reason,
            allow_unblock=allow_unblock,
        ),
        ticket=ticket,
        canonical_work_id=canonical_work_id,
        operation="sync_canonical_development_work",
        packet=packet,
    )


def _sync_canonical_development_work_once(
    root: str | Path,
    *,
    domain: str,
    project: str,
    ticket: str,
    title: str,
    run_id: str,
    tracker: str,
    packet: Path,
    worktree: Mapping[str, Any] | None,
    delivery_state: str,
    canonical_work_id: str | None = None,
    blocked_reason: str | None = None,
    allow_unblock: bool = False,
) -> dict[str, Any]:
    """Create or refresh the canonical state.db row for one delivery task."""

    if _project_work_item_is_finished(
        packet, project_root(root, domain, project)
    ) and delivery_state != "delivery_complete":
        raise DevelopmentDeliveryError(
            "finished or archived Auto-Dev packets are immutable; use `agentic-os auto-dev reopen` "
            "to create a new active packet and delivery run"
        )

    connection = connect_state(
        default_db_path(root),
        busy_timeout_ms=CANONICAL_ADMISSION_BUSY_TIMEOUT_MS,
    )
    try:
        existing = _canonical_source_match(
            connection,
            domain=domain,
            project=project,
            tracker=tracker,
            ticket=ticket,
            preferred_id=canonical_work_id,
        )
        item_id = str(
            (existing or {}).get("id")
            or canonical_work_id
            or _canonical_development_work_id(domain, project, ticket)
        )
        if existing and existing.get("state") in canonical_work_items.TERMINAL_STATES:
            packet_value = Path(str(existing.get("packet_path") or "")).expanduser()
            existing_packet = (
                packet_value.resolve()
                if packet_value.is_absolute()
                else (expand_path(root) / packet_value).resolve()
            )
            if delivery_state == "delivery_complete" and existing_packet == packet.resolve():
                canonical_work_items.write_active_projection(connection, root)
                return existing
            raise DevelopmentDeliveryError(
                f"canonical work item is already terminal and cannot be reprovisioned: {item_id}"
            )
        if existing and existing.get("packet_path"):
            packet_value = Path(str(existing["packet_path"])).expanduser()
            existing_packet = (
                packet_value.resolve()
                if packet_value.is_absolute()
                else (expand_path(root) / packet_value).resolve()
            )
            if existing_packet != packet.resolve():
                same_moved_packet = (
                    existing_packet.name == packet.name
                    and not existing_packet.exists()
                    and packet.is_dir()
                )
                if not same_moved_packet:
                    raise DevelopmentDeliveryError(
                        f"canonical work item {item_id} already points to another packet"
                    )
        desired_state = _canonical_state_for_delivery(delivery_state, worktree=worktree)
        desired_attention = "active"
        desired_blocker = blocked_reason
        if existing and existing.get("state") == "blocked" and not allow_unblock:
            desired_state = "blocked"
            desired_attention = str(existing.get("attention") or "active")
            desired_blocker = str(existing.get("blocked_reason") or "canonical blocker remains unresolved")
        elif existing and desired_state != "blocked":
            progress_rank = {"ready": 0, "building": 1, "validating": 2}
            existing_state = str(existing.get("state") or "")
            if progress_rank.get(existing_state, -1) > progress_rank.get(desired_state, -1):
                desired_state = existing_state
        row = canonical_work_items.upsert(
            connection,
            item_id=item_id,
            title=title,
            state=desired_state,
            attention=desired_attention,
            domain=domain,
            project=project,
            source_system=(existing or {}).get("source_system") or tracker,
            source_key=(existing or {}).get("source_key") or ticket,
            source_url=(existing or {}).get("source_url"),
            owner=(existing or {}).get("owner"),
            priority=int((existing or {}).get("priority") or 0),
            packet_path=str(packet),
            worktree_path=str(worktree.get("path")) if worktree and worktree.get("path") else None,
            branch=str(worktree.get("branch")) if worktree and worktree.get("branch") else None,
            context_summary=f"Auto-Dev run {run_id} for {ticket}; resume from the linked packet and autodev.json.",
            metadata={
                **dict((existing or {}).get("metadata") or {}),
                "development_run_id": run_id,
                "autodev_path": str(packet / "autodev.json"),
            },
            blocked_reason=desired_blocker,
            actor="development-delivery",
            receipt_ref=str(packet / "autodev.json"),
            verified=True,
        )
        canonical_work_items.write_active_projection(connection, root)
        return row
    finally:
        connection.close()


def _sync_canonical_task_progress(
    task_state_path: Path,
    *,
    allow_unblock: bool = False,
) -> dict[str, Any] | None:
    """Project a linked delivery task into canonical work state monotonically."""

    task = _read_mapping(task_state_path)
    required = (
        task.get("os_root"),
        task.get("domain"),
        task.get("project"),
        task.get("ticket"),
        task.get("work_item"),
        task.get("canonical_work_id"),
    )
    if not all(required):
        return None
    failure = task.get("failure") if isinstance(task.get("failure"), Mapping) else {}
    worktree = task.get("worktree") if isinstance(task.get("worktree"), Mapping) else None
    return _sync_canonical_development_work(
        str(task["os_root"]),
        domain=str(task["domain"]),
        project=str(task["project"]),
        ticket=str(task["ticket"]),
        title=str(task.get("title") or f"Implement {task['ticket']}"),
        run_id=str(task.get("run_id") or "development-delivery"),
        tracker=str((task.get("source") or {}).get("system") or "filesystem"),
        packet=Path(str(task["work_item"])).expanduser().resolve(),
        worktree=worktree,
        delivery_state=str(task.get("state") or ""),
        canonical_work_id=str(task["canonical_work_id"]),
        blocked_reason=str(failure.get("detail") or "") or None,
        allow_unblock=allow_unblock,
    )


def find_delivery_work_item(project_path: Path, work_id: str) -> Path | None:
    """Find one canonical or legacy packet, including retained archive history."""
    root = project_path / "work-items"
    if not root.is_dir():
        return None
    # Packet directories carry the id the scaffolder normalised, not the raw id
    # composed here. A long title truncates on a separator, so the raw id keeps a
    # trailing underscore the folder name never has; match the normalised form so
    # a retry adopts the packet an earlier attempt already created.
    pattern = slugify_work_id(work_id)
    candidates: list[Path] = []
    candidates.extend(path for path in root.glob(f"*{pattern}*") if path.is_dir())
    archive = root / "99-archived"
    if archive.is_dir():
        candidates.extend(path for path in archive.glob(f"*{pattern}*") if path.is_dir())
    for lane in ("01-intake", "02-active", "03-complete"):
        lane_root = root / lane
        if lane_root.is_dir():
            candidates.extend(path for path in lane_root.glob(f"*{pattern}*") if path.is_dir())
    unique = sorted({path.resolve(): path for path in candidates}.values(), key=str)
    if len(unique) > 1:
        raise DevelopmentDeliveryError(
            f"multiple work items match {work_id}: " + ", ".join(str(path) for path in unique)
        )
    return unique[0] if unique else None


def _task_branch(template: str, ticket: str, slug: str) -> str:
    return template.format(ticket=ticket.lower(), slug=slug)


def _run_command(command: Sequence[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603


def create_isolated_worktree(
    *,
    os_root: str | Path,
    domain: str,
    project: str,
    profile: Mapping[str, Any],
    ticket: str,
    title: str,
    runner: Any = _run_command,
) -> dict[str, Any]:
    project_path = project_root(os_root, domain, project)
    repository = profile["repository"]
    worktrees = profile["worktrees"]
    repo = expand_path(str(repository["root"]))
    base = str(repository["base_branch"])
    repository_id = _slug(str(repository.get("id") or "")) if repository.get("id") else None
    task_name = f"{repository_id}-{_slug(ticket)}-{_slug(title)}" if repository_id else f"{_slug(ticket)}-{_slug(title)}"
    name = task_name[:72].rstrip("-")
    name = dated_name(
        name,
        when=datetime.now(timezone.utc),
        policy=project_worktree_naming_policy(os_root, {"worktrees": dict(worktrees)}),
        scope="worktrees",
    )
    destination = project_worktree_root(project_path, {"worktrees": dict(worktrees)}) / name
    branch = _task_branch(str(worktrees.get("branch_template") or "feature/{ticket}-{slug}"), ticket, _slug(title))
    fetched = runner(["git", "-C", str(repo), "fetch", "origin", base])
    if fetched.returncode != 0:
        raise DevelopmentDeliveryError((fetched.stderr or fetched.stdout or "git fetch failed").strip())
    resolved = runner(["git", "-C", str(repo), "rev-parse", f"origin/{base}"])
    if resolved.returncode != 0:
        raise DevelopmentDeliveryError((resolved.stderr or resolved.stdout or "base revision missing").strip())
    base_sha = resolved.stdout.strip()
    if destination.exists() or destination.is_symlink():
        # A crash can occur after git creates the worktree but before the OS
        # registry/state receipt is written. Resume only when branch ownership
        # proves this exact task created the destination.
        actual_branch = runner(["git", "-C", str(destination), "branch", "--show-current"])
        if actual_branch.returncode != 0 or actual_branch.stdout.strip() != branch:
            raise DevelopmentDeliveryError(f"worktree ownership conflict: {destination}")
        register_project_worktree(os_root, domain, project, name, path=destination)
        return {
            "name": name,
            "path": str(destination),
            "branch": branch,
            "base_sha": base_sha,
            "repository_id": repository.get("id"),
            "resumed": True,
        }
    destination.parent.mkdir(parents=True, exist_ok=True)
    created = runner(["git", "-C", str(repo), "worktree", "add", "-b", branch, str(destination), base_sha])
    if created.returncode != 0:
        raise DevelopmentDeliveryError((created.stderr or created.stdout or "git worktree add failed").strip())
    register_project_worktree(os_root, domain, project, name, path=destination)
    return {
        "name": name,
        "path": str(destination),
        "branch": branch,
        "base_sha": base_sha,
        "repository_id": repository.get("id"),
        "resumed": False,
    }


@contextmanager
def _task_provisioning_admission_lock(state_path: Path):
    """Serialize correction of a failed selection with later provisioning.

    A historical base-selection correction is valid only while the task has
    produced no worktree, branch, or runtime effect.  Normal resume creates
    those effects outside the task-state lock, so it must share this narrower
    admission lock with correction rather than racing the preflight proof.
    """

    with _file_lock(state_path.with_suffix(state_path.suffix + ".provisioning-admission.lock")):
        yield


def _worktree_ready_recovery_read_file(
    candidate: Path,
    *,
    label: str,
    work_item: Path | None = None,
) -> tuple[Path, bytes]:
    """Read one stable regular input without following a replacement symlink."""

    if not candidate.is_absolute():
        raise DevelopmentDeliveryError(
            f"worktree_ready delivery recovery {label} must be an absolute regular file"
        )
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise DevelopmentDeliveryError(
            f"worktree_ready delivery recovery {label} is missing or unsafe"
        ) from exc
    if work_item is not None:
        try:
            resolved.relative_to(work_item)
        except ValueError as exc:
            raise DevelopmentDeliveryError(
                f"worktree_ready delivery recovery {label} is outside its work-item packet"
            ) from exc
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        raise DevelopmentDeliveryError(
            f"worktree_ready delivery recovery {label} cannot be opened safely on this platform"
        )
    try:
        descriptor = os.open(candidate, os.O_RDONLY | no_follow)
    except OSError as exc:
        raise DevelopmentDeliveryError(
            f"worktree_ready delivery recovery {label} is missing or unsafe"
        ) from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise DevelopmentDeliveryError(
                f"worktree_ready delivery recovery {label} is missing or unsafe"
            )
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            content = handle.read()
        try:
            current_entry = os.stat(candidate, follow_symlinks=False)
            current_resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise DevelopmentDeliveryError(
                f"worktree_ready delivery recovery {label} is missing or unsafe"
            ) from exc
        if not (
            stat.S_ISREG(current_entry.st_mode)
            and (current_entry.st_dev, current_entry.st_ino)
            == (opened.st_dev, opened.st_ino)
            and current_resolved == resolved
        ):
            raise DevelopmentDeliveryError(
                f"worktree_ready delivery recovery {label} is missing or unsafe"
            )
        if work_item is not None:
            try:
                current_resolved.relative_to(work_item)
            except ValueError as exc:
                raise DevelopmentDeliveryError(
                    f"worktree_ready delivery recovery {label} is outside its work-item packet"
                ) from exc
        return resolved, content
    finally:
        os.close(descriptor)


def _worktree_ready_recovery_packet_file(
    raw_path: Any,
    *,
    work_item: Path,
    label: str,
) -> tuple[Path, bytes]:
    """Resolve a packet-local immutable input while refusing traversal and links."""

    raw = str(raw_path or "").strip()
    if not raw:
        raise DevelopmentDeliveryError(
            f"worktree_ready delivery recovery {label} is missing"
        )
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = work_item / candidate
    return _worktree_ready_recovery_read_file(
        candidate, label=label, work_item=work_item
    )


def _worktree_ready_recovery_mapping(content: bytes, *, label: str) -> dict[str, Any]:
    """Decode a descriptor-verified immutable JSON/YAML mapping."""

    try:
        value = yaml.safe_load(content.decode("utf-8")) or {}
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise DevelopmentDeliveryError(
            f"worktree_ready delivery recovery {label} is malformed"
        ) from exc
    if not isinstance(value, Mapping):
        raise DevelopmentDeliveryError(
            f"worktree_ready delivery recovery {label} is malformed"
        )
    return dict(value)


def _worktree_ready_recovery_registered_head(task: Mapping[str, Any]) -> str:
    """Return the clean, registered Git worktree HEAD without guessing history."""

    worktree = task.get("worktree") if isinstance(task.get("worktree"), Mapping) else {}
    raw_path = str(worktree.get("path") or "").strip()
    branch = str(worktree.get("branch") or "").strip()
    if not raw_path or not branch:
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery requires the original registered Git worktree"
        )
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute() or candidate.is_symlink():
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery registered worktree is missing or unsafe"
        )
    try:
        worktree_path = candidate.resolve(strict=True)
        entry = candidate.lstat()
    except OSError as exc:
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery registered worktree is missing or unsafe"
        ) from exc
    if not stat.S_ISDIR(entry.st_mode) or worktree_path != candidate:
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery registered worktree is missing or unsafe"
        )

    def git_output(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(worktree_path), *arguments],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if completed.returncode:
            raise DevelopmentDeliveryError(
                "worktree_ready delivery recovery requires a clean registered Git worktree"
            )
        return completed.stdout.strip()

    if git_output("rev-parse", "--is-inside-work-tree") != "true":
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery requires a clean registered Git worktree"
        )
    if git_output("rev-parse", "--show-toplevel") != str(worktree_path):
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery registered worktree root changed"
        )
    if git_output("branch", "--show-current") != branch:
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery registered worktree branch changed"
        )
    if git_output("status", "--porcelain=v1", "--untracked-files=all"):
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery requires a clean registered Git worktree"
        )
    head = git_output("rev-parse", "--verify", "HEAD^{commit}")
    if not re.fullmatch(r"[a-fA-F0-9]{40}", head):
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery registered worktree HEAD is invalid"
        )
    return head.lower()


def _worktree_ready_recovery_release_identity(
    task: Mapping[str, Any],
    *,
    work_item: Path,
    family_ref: Path | None = None,
    require_current_worktree_head: bool = True,
) -> dict[str, Any]:
    """Bind current PR evidence to the clean registered worktree HEAD only."""

    repository = task.get("repository") if isinstance(task.get("repository"), Mapping) else {}
    worktree = task.get("worktree") if isinstance(task.get("worktree"), Mapping) else {}
    repository_id = str(repository.get("id") or "").strip()
    base_branch = str(repository.get("base_branch") or "").strip()
    source_branch = str(worktree.get("branch") or "").strip()
    if not repository_id.startswith("git:github.com/") or not base_branch or not source_branch:
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery requires the selected GitHub repository, base, and worktree branch"
        )
    if not require_current_worktree_head and family_ref is None:
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery allows an older source head only for its exact recovery-bound predecessor"
        )
    worktree_head = _worktree_ready_recovery_registered_head(task)
    github_repository = repository_id.removeprefix("git:github.com/")
    evidence_root = work_item / "artifacts" / "auto-dev-pr-create"
    candidates: list[dict[str, Any]] = []
    family_candidates = (
        [family_ref]
        if family_ref is not None
        else sorted(evidence_root.glob("refresh-*-family-complete.json"))
    )
    for family_candidate in family_candidates:
        family_path, family_bytes = _worktree_ready_recovery_read_file(
            family_candidate, label="release family evidence", work_item=work_item
        )
        if family_path.parent != evidence_root.resolve():
            continue
        family = _worktree_ready_recovery_mapping(family_bytes, label="release family evidence")
        details = family.get("evidence") if isinstance(family.get("evidence"), Mapping) else {}
        source_head_sha = str(details.get("source_head_sha") or "").strip()
        observed = (
            details.get("provider_observed")
            if isinstance(details.get("provider_observed"), Mapping)
            else {}
        )
        pull_request = str(details.get("pull_request") or "").strip()
        base_sha = str(details.get("base_sha") or "").strip()
        if not (
            family.get("schema") == "development-stage-evidence/v1"
            and family.get("state") == "release_propagation"
            and family.get("status") == "completed"
            and details.get("repository") == repository_id
            and details.get("base_branch") == base_branch
            and str(details.get("provider") or "").lower() == "github"
            and pull_request.startswith(f"github:{github_repository}#")
            and re.fullmatch(r"[1-9][0-9]*", pull_request.rsplit("#", 1)[-1])
            and details.get("source_branch") == source_branch
            and re.fullmatch(r"[a-fA-F0-9]{7,64}", source_head_sha)
            and re.fullmatch(r"[a-fA-F0-9]{7,64}", base_sha)
            and details.get("readback_verified") is True
            and observed.get("state") == "OPEN"
            and observed.get("is_draft") is False
            and str(observed.get("head_sha") or "").strip() == source_head_sha
            and str(observed.get("base_sha") or "").strip() == base_sha
            and family_path.name
            == f"refresh-{source_head_sha.lower()[:8]}-family-complete.json"
        ):
            continue
        provider_path, provider_bytes = _worktree_ready_recovery_packet_file(
            family_path.with_name(
                f"refresh-{source_head_sha.lower()[:8]}-provider-readback.json"
            ),
            work_item=work_item,
            label="release provider readback",
        )
        provider = _worktree_ready_recovery_mapping(
            provider_bytes, label="release provider readback"
        )
        if not (
            str(provider.get("provider") or "").lower() == "github"
            and provider.get("repository") == repository_id
            and provider.get("base_branch") == base_branch
            and str(provider.get("base_sha") or "").strip() == base_sha
            and provider.get("pull_request") == pull_request
            and provider.get("source_branch") == source_branch
            and str(provider.get("source_head_sha") or "").strip() == source_head_sha
            and provider.get("readback_verified") is True
            and provider.get("state") == "OPEN"
            and provider.get("is_draft") is False
            and provider_path.name
            == f"refresh-{source_head_sha.lower()[:8]}-provider-readback.json"
        ):
            continue
        candidates.append(
            {
                "family": family_path,
                "family_sha256": hashlib.sha256(family_bytes).hexdigest(),
                "provider": provider_path,
                "provider_sha256": hashlib.sha256(provider_bytes).hexdigest(),
                "pull_request_identity": {
                    "provider": "github",
                    "repository": repository_id,
                    "base_branch": base_branch,
                    "base_sha": base_sha,
                    "pull_request": pull_request,
                    "source_branch": source_branch,
                    "source_head_sha": source_head_sha,
                },
            }
        )
    matching = (
        [
            candidate
            for candidate in candidates
            if candidate["pull_request_identity"]["source_head_sha"].lower() == worktree_head
        ]
        if require_current_worktree_head
        else candidates
    )
    if len(matching) != 1:
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery requires exactly one hash-bound release family/readback pair"
            + (" for the registered worktree HEAD" if require_current_worktree_head else "")
        )
    return matching[0]


def _worktree_ready_recovery_post_review_self_handoffs(
    task: Mapping[str, Any], *, state_path: Path
) -> None:
    """Prove the one recoverable executor boundary emitted before Review Self.

    The only extended compatibility shape is a packet that entered Everything
    through the normal Review Self admission path, but could not obtain an
    executor before any stage was recorded.  Its original Everything dispatch
    may have one pending groom handoff; every later handoff must be the exact
    pending Review Self retry.  Anything else is a generic Everything packet
    and remains ineligible for this recovery.
    """

    failure = task.get("failure") if isinstance(task.get("failure"), Mapping) else {}
    attempts = task.get("attempts") if isinstance(task.get("attempts"), Mapping) else {}
    count = attempts.get("executor_unavailable")
    maximum = task.get("max_attempts")
    if not (
        set(attempts) == {"executor_unavailable"}
        and type(count) is int
        and type(maximum) is int
        and 1 <= count < maximum
        and failure.get("kind") == "executor_unavailable"
        and failure.get("recoverable") is True
        and failure.get("retry_state") == "worktree_ready"
        and task.get("last_failure_key")
        == f"{task.get('run_id')}:{task.get('ticket')}:executor-unavailable:{count}"
    ):
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery requires only the bounded recoverable Review Self executor handoff"
        )
    handoff_root = state_path.parent / "handoffs"
    try:
        root_stat = handoff_root.lstat()
        names = sorted(path.name for path in handoff_root.iterdir())
    except OSError as exc:
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery requires the exact pending executor handoff receipts"
        ) from exc
    expected_names = [f"executor-unavailable-attempt-{attempt:02d}.json" for attempt in range(1, count + 1)]
    if not stat.S_ISDIR(root_stat.st_mode) or names != expected_names:
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery requires only the exact pending executor handoff receipts"
        )
    worktree = task.get("worktree") if isinstance(task.get("worktree"), Mapping) else {}
    runtime = task.get("runtime") if isinstance(task.get("runtime"), Mapping) else {}
    for attempt, name in enumerate(expected_names, start=1):
        receipt_path, receipt_bytes = _worktree_ready_recovery_read_file(
            handoff_root / name, label="executor handoff"
        )
        handoff = _worktree_ready_recovery_mapping(receipt_bytes, label="executor handoff")
        review_self_handoff = attempt > 1 or count == 1
        requested_stage = "review_self" if review_self_handoff else None
        next_stage = "review_self" if review_self_handoff else "groom"
        if not (
            receipt_path == (handoff_root / name).resolve()
            and handoff.get("schema") == "development-executor-handoff/v1"
            and handoff.get("status") == "pending"
            and handoff.get("outcome") == "executor_unavailable"
            and handoff.get("attempt") == attempt
            and handoff.get("max_attempts") == maximum
            and handoff.get("recoverable") is True
            and handoff.get("run_id") == task.get("run_id")
            and handoff.get("ticket") == task.get("ticket")
            and handoff.get("canonical_work_id") == task.get("canonical_work_id")
            and Path(str(handoff.get("task_state") or "")).expanduser().resolve() == state_path
            and handoff.get("task_state_before_handoff") == "worktree_ready"
            and handoff.get("requested_stage") == requested_stage
            and handoff.get("next_stage") == next_stage
            and handoff.get("worktree") == worktree
            and handoff.get("runtime") == runtime
            and isinstance(handoff.get("policy"), Mapping)
            and handoff["policy"].get("fingerprint") == task.get("policy_fingerprint")
            and handoff["policy"].get("receipt") == task.get("policy_receipt")
            and str(handoff.get("recorded_at") or "").strip()
        ):
            raise DevelopmentDeliveryError(
                "worktree_ready delivery recovery executor handoff does not match the exact Review Self admission"
            )
        if attempt == count and not (
            Path(str(failure.get("receipt") or "")).expanduser().resolve() == receipt_path
            and failure.get("failed_at") == handoff.get("recorded_at")
        ):
            raise DevelopmentDeliveryError(
                "worktree_ready delivery recovery current executor handoff does not match task failure"
            )


def _worktree_ready_recovery_portfolio(
    portfolio: Mapping[str, Any],
    *,
    task: Mapping[str, Any],
    state_path: Path,
    post_review_self_admission: bool,
    pr_create_worktree_ready: bool = False,
) -> dict[str, Any]:
    """Recognize only explicitly supported historical portfolio shapes."""

    auto_dev = portfolio.get("auto_dev") if isinstance(portfolio.get("auto_dev"), Mapping) else {}
    rows = portfolio.get("tasks") if isinstance(portfolio.get("tasks"), list) else []
    ticket = str(task.get("ticket") or "")
    common = (
        portfolio.get("run_id") == task.get("run_id")
        and portfolio.get("tickets") == [ticket]
        and auto_dev.get("stage_order") == task.get("auto_dev_stage_order")
        and auto_dev.get("stage_policies") == task.get("auto_dev_stage_policies")
        and not portfolio.get("active_worktree_ready_delivery_recoveries")
        and not portfolio.get("active_worktree_ready_pr_create_delivery_recoveries")
        and len(rows) == 1
        and isinstance(rows[0], Mapping)
        and rows[0].get("ticket") == ticket
        and Path(str(rows[0].get("state_ref") or "")).expanduser().resolve() == state_path
        and rows[0].get("canonical_work_id") == task.get("canonical_work_id")
    )
    legacy_detective_readiness = (
        portfolio.get("state") == "dispatching"
        and auto_dev.get("mode") == "single_stage"
        # This legacy shape was emitted with detective as the portfolio selector
        # while its task and completion boundary remained readiness.  Accepting
        # either selector would turn this narrow migration into a generic widen.
        and auto_dev.get("requested_stage") == "detective"
        and auto_dev.get("goal") == "readiness"
        and auto_dev.get("start_stage") == "groom"
        and auto_dev.get("completion_stage") == "readiness"
        and auto_dev.get("provision_worktree") is False
    )
    normal_groom_readiness = (
        portfolio.get("state") == "dispatching"
        and auto_dev.get("mode") == "single_stage"
        # This separately named historical selector is the normal groom
        # start, but it remains bound to the same readiness-only boundary.
        and auto_dev.get("requested_stage") == "groom"
        and auto_dev.get("goal") == "readiness"
        and auto_dev.get("start_stage") == "groom"
        and auto_dev.get("completion_stage") == "readiness"
        and auto_dev.get("provision_worktree") is False
    )
    post_review_self = (
        portfolio.get("state") == "pending"
        and auto_dev.get("mode") == "everything"
        and auto_dev.get("requested_stage") is None
        and auto_dev.get("goal") == "delivery_complete"
        and auto_dev.get("start_stage") == "groom"
        and auto_dev.get("completion_stage") == "health"
        and auto_dev.get("provision_worktree") is True
    )
    pr_create_worktree = (
        portfolio.get("state") == "dispatching"
        and auto_dev.get("mode") == "single_stage"
        # This legacy selector was emitted as develop while the task and
        # projection were bounded to PR Create.  It is intentionally not a
        # generic single-stage admission.
        and auto_dev.get("requested_stage") == "develop"
        and auto_dev.get("goal") == "pr_create"
        and auto_dev.get("start_stage") == "groom"
        and auto_dev.get("completion_stage") == "pr_create"
        and auto_dev.get("provision_worktree") is True
    )
    if not common or not (
        pr_create_worktree
        if pr_create_worktree_ready
        else post_review_self
        if post_review_self_admission
        else legacy_detective_readiness or normal_groom_readiness
    ):
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery requires the exact active one-task portfolio boundary"
        )
    return dict(auto_dev)


def _active_worktree_ready_delivery_recovery_context(
    state_path: Path, *, pr_create_worktree_ready: bool = False
) -> dict[str, Any]:
    """Prove the sole historical readiness packet is safe to widen once.

    This is intentionally disjoint from both blocked-task recovery and the
    local-validation PR Create escalation.  It neither invents past workflow
    receipts nor accepts any previous review/QA/finalize/merge authority.
    """

    state_path = state_path.expanduser().resolve()
    task_path, task_bytes = _worktree_ready_recovery_read_file(
        state_path, label="task state"
    )
    task = _worktree_ready_recovery_mapping(task_bytes, label="task state")
    common_task_shape = (
        task.get("state") == "worktree_ready"
        and task.get("stage_receipts") in (None, {})
        and not task.get("active_worktree_ready_delivery_recoveries")
        and not task.get("active_worktree_ready_pr_create_delivery_recoveries")
        and not task.get("subject_supersessions")
        and not task.get("subject_supersession_resolutions")
        and not any(
            task.get(field)
            for field in ("subject_revision", "terminal_revision", "deployed_revision")
        )
    )
    legacy_readiness = (
        common_task_shape
        and task.get("failure") is None
        and task.get("auto_dev_mode") == "single_stage"
        and task.get("requested_stage") == "readiness"
        and task.get("goal") == "readiness"
        and task.get("auto_dev_start_stage") == "groom"
        and task.get("auto_dev_completion_stage") == "readiness"
    )
    post_review_self_admission = (
        common_task_shape
        and isinstance(task.get("failure"), Mapping)
        and task.get("auto_dev_mode") == "everything"
        and task.get("requested_stage") == "review_self"
        and task.get("goal") == "delivery_complete"
        and task.get("auto_dev_start_stage") == "groom"
        and task.get("auto_dev_completion_stage") == "health"
    )
    pr_create_worktree = (
        common_task_shape
        and task.get("failure") is None
        and task.get("auto_dev_mode") == "single_stage"
        and task.get("requested_stage") == "pr_create"
        and task.get("goal") == "pr_create"
        and task.get("auto_dev_start_stage") == "groom"
        and task.get("auto_dev_completion_stage") == "pr_create"
    )
    if post_review_self_admission:
        _worktree_ready_recovery_post_review_self_handoffs(task, state_path=state_path)
    if not (
        pr_create_worktree if pr_create_worktree_ready else legacy_readiness or post_review_self_admission
    ):
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery requires the exact active supported task boundary"
        )
    recovery_shape = (
        "single_stage_pr_create_worktree_ready"
        if pr_create_worktree_ready
        else "post_review_self_executor_handoff"
        if post_review_self_admission
        else "single_stage_readiness"
    )
    required = (
        "os_root",
        "domain",
        "project",
        "ticket",
        "run_id",
        "work_item",
        "autodev_path",
        "canonical_work_id",
    )
    if not all(str(task.get(field) or "").strip() for field in required):
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery requires a fully linked canonical task"
        )
    expected_receipts = {
        "claimed",
        "groom_check",
        "context_ready",
        "work_item_ready",
        "worktree_ready",
    }
    receipts = task.get("receipts")
    if not (
        isinstance(receipts, list)
        and len(receipts) == len(expected_receipts)
        and {
            str(row.get("state") or "")
            for row in receipts
            if isinstance(row, Mapping) and str(row.get("ref") or "").strip()
        }
        == expected_receipts
    ):
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery requires exactly the immutable pre-delivery task receipts"
        )
    stage_order = validate_auto_dev_stage_order(list(task.get("auto_dev_stage_order") or []))
    stage_policies = validate_auto_dev_stage_policies(
        task.get("auto_dev_stage_policies")
        if isinstance(task.get("auto_dev_stage_policies"), Mapping)
        else {}
    )
    root = expand_path(str(task["os_root"]))
    domain = normalize_domain(str(task["domain"]))
    project = validate_name(str(task["project"]), "project")
    ticket = str(task["ticket"])
    work_item = Path(str(task["work_item"])).expanduser().resolve()
    project_path = project_root(root, domain, project)
    if not (
        work_item.is_dir()
        and (work_item / "work.yml").is_file()
        and _project_work_item_lane(work_item, project_path) == "02-active"
    ):
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery requires one active canonical work-item packet"
        )
    autodev_path, autodev_bytes = _worktree_ready_recovery_read_file(
        Path(str(task["autodev_path"])).expanduser(),
        label="Auto-Dev projection",
        work_item=work_item,
    )
    if autodev_path != (work_item / "autodev.json").resolve():
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery Auto-Dev projection is not packet-local"
        )
    projection = _worktree_ready_recovery_mapping(
        autodev_bytes, label="Auto-Dev projection"
    )
    projection_delivery = (
        projection.get("delivery") if isinstance(projection.get("delivery"), Mapping) else {}
    )
    stages = projection.get("stages") if isinstance(projection.get("stages"), Mapping) else {}
    common_projection = (
        projection.get("canonical_work_id") == task["canonical_work_id"]
        and projection.get("subject_revision") in (None, "")
        and projection.get("terminal_revision") in (None, "")
        and projection.get("deployed_revision") in (None, "")
        and projection_delivery.get("state") == "worktree_ready"
        and projection_delivery.get("run_id") == task["run_id"]
        and projection_delivery.get("subject_revision") in (None, "")
        and projection_delivery.get("terminal_revision") in (None, "")
        and projection_delivery.get("deployed_revision") in (None, "")
        and Path(str(projection_delivery.get("task_state_ref") or "")).expanduser().resolve()
        == state_path
        and Path(str(projection_delivery.get("work_item") or "")).expanduser().resolve()
        == work_item
        and projection_delivery.get("canonical_work_id") == task["canonical_work_id"]
        and isinstance(projection.get("source"), Mapping)
        and projection["source"].get("key") == ticket
        and set(stages) == set(AUTO_DEV_STAGE_ORDER)
        and all(
            isinstance(row, Mapping)
            and row.get("status") in {"not_started", "out_of_scope"}
            and row.get("receipt_refs") == []
            for row in stages.values()
        )
    )
    legacy_projection = (
        common_projection
        and projection.get("mode") == "single_stage"
        and projection.get("requested_stage") == "readiness"
        and projection.get("start_stage") == "groom"
        and projection.get("completion_stage") == "readiness"
        and projection.get("current_stage") == "readiness"
        and projection_delivery.get("goal") == "readiness"
    )
    pr_create_worktree_projection = (
        common_projection
        and projection.get("mode") == "single_stage"
        and projection.get("requested_stage") == "pr_create"
        and projection.get("start_stage") == "groom"
        and projection.get("completion_stage") == "pr_create"
        and projection.get("current_stage") == "pr_create"
        and projection.get("status") == "ready"
        and projection.get("blocker") is None
        and projection_delivery.get("goal") == "pr_create"
    )
    post_review_self_projection = (
        common_projection
        and projection.get("mode") == "everything"
        and projection.get("requested_stage") == "review_self"
        and projection.get("start_stage") == "groom"
        and projection.get("completion_stage") == "health"
        and projection.get("current_stage") == "review_self"
        and projection.get("status") == "paused"
        and projection.get("blocker") == task.get("failure")
        and projection_delivery.get("goal") == "delivery_complete"
    )
    if not (
        pr_create_worktree_projection
        if pr_create_worktree_ready
        else post_review_self_projection
        if post_review_self_admission
        else legacy_projection
    ):
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery requires the exact eligible Auto-Dev projection"
        )
    stage_root = work_item / "artifacts" / "auto-dev-orchestration" / "stages"
    stages_without_authority = (
        AUTO_DEV_STAGE_ORDER
        if post_review_self_admission or pr_create_worktree_ready
        else _ACTIVE_WORKTREE_READY_DELIVERY_FRESH_STAGES
    )
    for stage in stages_without_authority:
        if any(
            path.exists() or path.is_symlink()
            for path in (stage_root / f"{stage}.json", stage_root / stage / "latest.json")
        ):
            raise DevelopmentDeliveryError(
                "worktree_ready delivery recovery refuses latent downstream authority artifacts"
            )
    worktree = task.get("worktree") if isinstance(task.get("worktree"), Mapping) else {}
    worktree_path = Path(str(worktree.get("path") or "")).expanduser()
    if not (
        worktree_path.is_dir()
        and str(worktree.get("branch") or "").strip()
        and re.fullmatch(r"[a-fA-F0-9]{7,64}", str(worktree.get("base_sha") or "").strip())
    ):
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery requires the original registered worktree receipt"
        )
    release = _worktree_ready_recovery_release_identity(task, work_item=work_item)
    run_dir = state_path.parent.parent.parent.resolve()
    portfolio_path, portfolio_bytes = _worktree_ready_recovery_read_file(
        run_dir / "portfolio.json", label="portfolio"
    )
    portfolio = _worktree_ready_recovery_mapping(portfolio_bytes, label="portfolio")
    portfolio_auto_dev = _worktree_ready_recovery_portfolio(
        portfolio,
        task=task,
        state_path=state_path,
        post_review_self_admission=post_review_self_admission,
        pr_create_worktree_ready=pr_create_worktree_ready,
    )
    if not pr_create_worktree_ready and not post_review_self_admission:
        recovery_shape = (
            "single_stage_groom_readiness"
            if portfolio_auto_dev.get("requested_stage") == "groom"
            else "single_stage_readiness"
        )
    canonical = _read_canonical_development_work(
        root,
        canonical_work_id=str(task["canonical_work_id"]),
        ticket=ticket,
        packet=work_item,
        diagnostic_root=run_dir,
    )
    if not (
        isinstance(canonical, Mapping)
        and canonical.get("id") == task["canonical_work_id"]
        and canonical.get("state") == "building"
        and canonical.get("attention") == "active"
        and canonical.get("domain") == domain
        and canonical.get("project") == project
        and canonical.get("source_key") == ticket
        and canonical.get("packet_path") == str(work_item)
        and canonical.get("worktree_path") == str(worktree_path)
        and canonical.get("branch") == worktree.get("branch")
    ):
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery requires one active canonical worktree-ready row"
        )
    recovered_portfolio_auto_dev = {
        **portfolio_auto_dev,
        "mode": "everything",
        "requested_stage": None,
        "goal": "merge",
        "stage_order": stage_order,
        "start_stage": "review_self",
        "completion_stage": "merge",
        "stage_policies": stage_policies,
    }
    return {
        "task": task,
        "state_path": state_path,
        "task_sha256": hashlib.sha256(task_bytes).hexdigest(),
        "work_item": work_item,
        "autodev_path": autodev_path,
        "autodev_sha256": hashlib.sha256(autodev_bytes).hexdigest(),
        "portfolio_path": portfolio_path,
        "portfolio_sha256": hashlib.sha256(portfolio_bytes).hexdigest(),
        "portfolio_auto_dev": portfolio_auto_dev,
        "recovered_portfolio_auto_dev": recovered_portfolio_auto_dev,
        "canonical": dict(canonical),
        "canonical_sha256": _json_sha256(dict(canonical)),
        "stage_order": stage_order,
        "stage_policies": stage_policies,
        "worktree": dict(worktree),
        "recovery_shape": recovery_shape,
        "release": release,
    }


def _active_worktree_ready_pr_create_delivery_recovery_context(
    state_path: Path,
) -> dict[str, Any]:
    """Prove the one historical PR Create packet can start fresh review delivery."""

    return _active_worktree_ready_delivery_recovery_context(
        state_path, pr_create_worktree_ready=True
    )


def _worktree_ready_recovery_original(context: Mapping[str, Any]) -> dict[str, Any]:
    release = context["release"]
    return {
        "task_state_ref": str(context["state_path"]),
        "task_state_sha256": context["task_sha256"],
        "portfolio_ref": str(context["portfolio_path"]),
        "portfolio_sha256": context["portfolio_sha256"],
        "autodev_ref": str(context["autodev_path"]),
        "autodev_sha256": context["autodev_sha256"],
        "canonical_work_id": context["task"]["canonical_work_id"],
        "canonical_sha256": context["canonical_sha256"],
        "work_item": str(context["work_item"]),
        "worktree": context["worktree"],
        "recovery_shape": context["recovery_shape"],
        "release_propagation": {
            "family_ref": str(release["family"]),
            "family_sha256": release["family_sha256"],
            "provider_ref": str(release["provider"]),
            "provider_sha256": release["provider_sha256"],
            "pull_request_identity": release["pull_request_identity"],
        },
        "stage_receipts_sha256": _json_sha256(context["task"].get("stage_receipts") or {}),
    }


def _worktree_ready_recovery_projection_is_derived(
    projection: Mapping[str, Any],
    *,
    task: Mapping[str, Any],
    state_path: Path,
    stage_order: Sequence[str],
    stage_policies: Mapping[str, Any],
    requested_stage: str | None = None,
) -> bool:
    delivery = projection.get("delivery") if isinstance(projection.get("delivery"), Mapping) else {}
    stages = projection.get("stages") if isinstance(projection.get("stages"), Mapping) else {}
    expected_stage_order = tuple(stage_order)
    if "review_self" not in expected_stage_order:
        return False
    pre_review_stages = tuple(
        stage
        for stage in expected_stage_order[: expected_stage_order.index("review_self")]
        if stage != "develop"
    )
    local_validation_refs = [
        str(row.get("ref") or "")
        for row in task.get("receipts") or []
        if isinstance(row, Mapping) and row.get("state") == "local_validation"
    ]
    return bool(
        projection.get("mode") == "everything"
        and task.get("requested_stage") == requested_stage
        and projection.get("requested_stage") == requested_stage
        and projection.get("start_stage") == "review_self"
        and projection.get("completion_stage") == "merge"
        and projection.get("current_stage") == "review_self"
        and projection.get("status") == "ready"
        and projection.get("blocker") is None
        and projection.get("stage_order") == list(expected_stage_order)
        and projection.get("stage_policies") == stage_policies
        and projection.get("canonical_work_id") == task.get("canonical_work_id")
        and projection.get("subject_revision") is None
        and projection.get("terminal_revision") is None
        and projection.get("deployed_revision") is None
        and delivery.get("state") == "local_validation"
        and delivery.get("goal") == "merge"
        and delivery.get("run_id") == task.get("run_id")
        and Path(str(delivery.get("task_state_ref") or "")).expanduser().resolve()
        == state_path
        and delivery.get("subject_revision") in (None, "")
        and delivery.get("terminal_revision") in (None, "")
        and delivery.get("deployed_revision") in (None, "")
        # Mapping keys cannot carry duplicate stages, while the separately
        # hash-bound order proves their exact canonical sequence.  Do not use
        # the mutable task order here: a recovery provenance receipt owns it.
        and set(stages) == set(expected_stage_order)
        and all(
            isinstance(stages.get(stage), Mapping)
            and stages[stage].get("status") == "out_of_scope"
            and stages[stage].get("receipt_refs") == []
            for stage in pre_review_stages
        )
        # The recovery provenance is a local-validation receipt, which the
        # projection convention maps to develop.  It is the only permitted
        # pre-Review-Self projection authority and is never a PR Create receipt.
        and len(local_validation_refs) == 1
        and isinstance(stages.get("develop"), Mapping)
        and stages["develop"].get("status") == "completed"
        and stages["develop"].get("receipt_refs") == local_validation_refs
        and all(
            isinstance(stages.get(stage), Mapping)
            and stages[stage].get("status") == "not_started"
            and stages[stage].get("receipt_refs") == []
            for stage in _ACTIVE_WORKTREE_READY_DELIVERY_FRESH_STAGES
        )
    )


def _worktree_ready_recovery_stage_contract(
    recovered: Mapping[str, Any],
) -> tuple[tuple[str, ...], dict[str, Any]]:
    """Return only a current or known pre-validation-stage recovery contract."""

    recorded_order = recovered.get("stage_order")
    recorded_policies = recovered.get("stage_policies")
    if not isinstance(recorded_order, list) or not isinstance(recorded_policies, Mapping):
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery provenance has no complete stage contract"
        )
    portfolio_auto_dev = recovered.get("portfolio_auto_dev")
    expected_current = tuple(AUTO_DEV_STAGE_ORDER)
    expected_legacy = tuple(
        stage for stage in AUTO_DEV_STAGE_ORDER if stage != "validate_production_release"
    )
    stage_order = tuple(str(stage) for stage in recorded_order)
    if stage_order not in {expected_current, expected_legacy}:
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery provenance has an unsupported stage order"
        )
    if set(recorded_policies) != set(stage_order) or not all(
        isinstance(policy, Mapping) for policy in recorded_policies.values()
    ):
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery provenance has an unsupported stage policy map"
        )
    if not (
        isinstance(portfolio_auto_dev, Mapping)
        and portfolio_auto_dev.get("stage_order") == list(stage_order)
        and portfolio_auto_dev.get("stage_policies") == recorded_policies
    ):
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery provenance has an inconsistent portfolio stage contract"
        )
    return stage_order, dict(recorded_policies)


def _worktree_ready_recovery_is_anchored_by_local_validation_receipt(
    current: Mapping[str, Any],
    *,
    receipt_path: Path,
    receipt_sha256: str,
    recorded_at: str | None,
) -> bool:
    """Require the recovery payload to match its immutable task receipt row."""

    rows = [
        row
        for row in current.get("receipts") or []
        if isinstance(row, Mapping) and row.get("state") == "local_validation"
    ]
    if len(rows) != 1:
        return False
    row = rows[0]
    ref = str(row.get("ref") or "").strip()
    if not ref:
        return False
    try:
        resolved_ref = Path(ref).expanduser().resolve()
    except (OSError, RuntimeError):
        return False
    return bool(
        resolved_ref == receipt_path
        and row.get("sha256") == receipt_sha256
        and row.get("recorded_at") == recorded_at
    )


def _complete_active_worktree_ready_delivery_recovery(
    state_path: Path,
    *,
    current: Mapping[str, Any],
    recovery: Mapping[str, Any],
    apply: bool,
    recovery_schema: str = ACTIVE_WORKTREE_READY_DELIVERY_RECOVERY_SCHEMA,
    recovery_kind: str = "recover-active-worktree-ready-delivery",
    recovery_history_key: str = "active_worktree_ready_delivery_recoveries",
    recovery_event_type: str = "development.task.active_worktree_ready_delivery_recovered",
    derived_requested_stages: Sequence[str | None] = (None,),
) -> None:
    """Finish only the derived state of an exact interrupted recovery replay."""

    work_item = Path(str(current.get("work_item") or "")).expanduser().resolve()
    receipt_path, receipt_bytes = _worktree_ready_recovery_packet_file(
        recovery.get("receipt"), work_item=work_item, label="recovery provenance"
    )
    receipt = _worktree_ready_recovery_mapping(receipt_bytes, label="recovery provenance")
    if not (
        receipt.get("schema") == recovery_schema
        and receipt.get("kind") == recovery_kind
        and receipt.get("idempotency_key") == recovery.get("idempotency_key")
        and _json_sha256(receipt) == recovery.get("sha256")
    ):
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery provenance does not match task state"
        )
    recovered = receipt.get("recovered") if isinstance(receipt.get("recovered"), Mapping) else {}
    stage_order, stage_policies = _worktree_ready_recovery_stage_contract(recovered)
    if not _worktree_ready_recovery_is_anchored_by_local_validation_receipt(
        current,
        receipt_path=receipt_path,
        receipt_sha256=_json_sha256(receipt),
        recorded_at=str(receipt.get("recorded_at") or "") or None,
    ):
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery provenance is not anchored by its immutable local_validation receipt"
        )
    expected_portfolio_auto_dev = recovered.get("portfolio_auto_dev")
    requested_stage = current.get("requested_stage")
    if not (
        current.get("state") == "local_validation"
        and current.get("failure") is None
        and current.get("auto_dev_mode") == "everything"
        and requested_stage in derived_requested_stages
        and current.get("goal") == "merge"
        and current.get("auto_dev_start_stage") == "review_self"
        and current.get("auto_dev_completion_stage") == "merge"
        and current.get("auto_dev_stage_order") == list(stage_order)
        and current.get("auto_dev_stage_policies") == stage_policies
        and isinstance(expected_portfolio_auto_dev, Mapping)
    ):
        raise DevelopmentDeliveryError("worktree_ready delivery recovery task state is not replayable")
    matching = [
        row
        for row in current.get(recovery_history_key) or []
        if isinstance(row, Mapping) and row.get("idempotency_key") == recovery.get("idempotency_key")
    ]
    if len(matching) != 1 or dict(matching[0]) != dict(recovery):
        raise DevelopmentDeliveryError("worktree_ready delivery recovery history is not replayable")
    original = receipt.get("original") if isinstance(receipt.get("original"), Mapping) else {}
    original_release = (
        original.get("release_propagation")
        if isinstance(original.get("release_propagation"), Mapping)
        else {}
    )
    release = _worktree_ready_recovery_release_identity(
        current,
        work_item=work_item,
        family_ref=Path(str(original_release.get("family_ref") or "")).expanduser(),
        # Replay validates the immutable pre-rebase family path from recovery
        # provenance; all newly selected successor evidence remains HEAD-bound.
        require_current_worktree_head=False,
    )
    expected_release = {
        "family_ref": str(release["family"]),
        "family_sha256": release["family_sha256"],
        "provider_ref": str(release["provider"]),
        "provider_sha256": release["provider_sha256"],
        "pull_request_identity": release["pull_request_identity"],
    }
    if not (
        original.get("release_propagation") == expected_release
        and original.get("stage_receipts_sha256")
        == _json_sha256(current.get("stage_receipts") or {})
        and original.get("task_state_ref") == str(state_path)
        and current.get("worktree") == original.get("worktree")
        and not any(
            current.get(field)
            for field in ("subject_revision", "terminal_revision", "deployed_revision")
        )
    ):
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery immutable release evidence changed before replay"
        )
    autodev_path, autodev_bytes = _worktree_ready_recovery_read_file(
        Path(str(current.get("autodev_path") or "")).expanduser(),
        label="Auto-Dev projection",
        work_item=work_item,
    )
    projection = _worktree_ready_recovery_mapping(autodev_bytes, label="Auto-Dev projection")
    if not (
        str(autodev_path) == str(original.get("autodev_ref") or "")
        and (
            hashlib.sha256(autodev_bytes).hexdigest() == original.get("autodev_sha256")
            or _worktree_ready_recovery_projection_is_derived(
                projection,
                task=current,
                state_path=state_path,
                stage_order=stage_order,
                stage_policies=stage_policies,
                requested_stage=requested_stage,
            )
        )
    ):
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery Auto-Dev projection changed before replay"
        )
    run_dir = state_path.parent.parent.parent.resolve()
    root = expand_path(str(current.get("os_root") or ""))
    canonical = _read_canonical_development_work(
        root,
        canonical_work_id=str(current.get("canonical_work_id") or ""),
        ticket=str(current.get("ticket") or ""),
        packet=work_item,
        diagnostic_root=run_dir,
    )
    known_derived_canonical = (
        isinstance(canonical, Mapping)
        and canonical.get("state") == "validating"
        and canonical.get("attention") == "active"
        and canonical.get("id") == current.get("canonical_work_id")
        and canonical.get("domain") == current.get("domain")
        and canonical.get("project") == current.get("project")
        and canonical.get("source_key") == current.get("ticket")
        and canonical.get("packet_path") == str(work_item)
        and canonical.get("worktree_path") == str((current.get("worktree") or {}).get("path") or "")
        and canonical.get("branch") == (current.get("worktree") or {}).get("branch")
    )
    if not (
        isinstance(canonical, Mapping)
        and (
            _json_sha256(dict(canonical)) == original.get("canonical_sha256")
            or known_derived_canonical
        )
    ):
        raise DevelopmentDeliveryError(
            "canonical work row changed before worktree_ready delivery recovery replay"
        )
    if not apply:
        return
    portfolio_path = run_dir / "portfolio.json"
    with _file_lock(portfolio_path.with_suffix(portfolio_path.suffix + ".lock")):
        portfolio_path_checked, portfolio_bytes = _worktree_ready_recovery_read_file(
            portfolio_path, label="portfolio"
        )
        portfolio = _worktree_ready_recovery_mapping(portfolio_bytes, label="portfolio")
        rows = portfolio.get("tasks") if isinstance(portfolio.get("tasks"), list) else []
        expected_row = {**dict(recovery), "task_state_ref": str(state_path)}
        recorded = [
            row
            for row in portfolio.get(recovery_history_key) or []
            if isinstance(row, Mapping) and row.get("idempotency_key") == recovery.get("idempotency_key")
        ]
        if not (
            portfolio_path_checked == portfolio_path
            and portfolio.get("run_id") == current.get("run_id")
            and portfolio.get("tickets") == [current.get("ticket")]
            and len(rows) == 1
            and isinstance(rows[0], Mapping)
            and Path(str(rows[0].get("state_ref") or "")).expanduser().resolve() == state_path
            and rows[0].get("canonical_work_id") == current.get("canonical_work_id")
            and len(recorded) <= 1
            and (not recorded or dict(recorded[0]) == expected_row)
        ):
            raise DevelopmentDeliveryError(
                "portfolio changed during worktree_ready delivery recovery; rerun preflight"
            )
        changed = False
        if portfolio.get("auto_dev") != expected_portfolio_auto_dev:
            if (
                hashlib.sha256(portfolio_bytes).hexdigest() != original.get("portfolio_sha256")
                or str(portfolio_path) != str(original.get("portfolio_ref") or "")
                or recorded
            ):
                raise DevelopmentDeliveryError(
                    "worktree_ready delivery recovery refuses a portfolio outside its exact recovered projection"
                )
            portfolio["auto_dev"] = dict(expected_portfolio_auto_dev)
            portfolio["state"] = "local_validation"
            changed = True
        elif portfolio.get("state") != "local_validation":
            raise DevelopmentDeliveryError(
                "worktree_ready delivery recovery refuses a partial portfolio projection"
            )
        if not recorded:
            portfolio.setdefault(recovery_history_key, []).append(expected_row)
            changed = True
        if changed:
            portfolio["updated_at"] = utc_now()
            _atomic_json(portfolio_path, portfolio)

    synced = _sync_auto_dev_projection(state_path)
    if not (
        isinstance(synced, Mapping)
        and _worktree_ready_recovery_projection_is_derived(
            synced,
            task=current,
            state_path=state_path,
            stage_order=stage_order,
            stage_policies=stage_policies,
            requested_stage=requested_stage,
        )
    ):
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery could not refresh its fresh-authority Auto-Dev projection"
        )
    _sync_canonical_task_progress(state_path)
    canonical = _read_canonical_development_work(
        root,
        canonical_work_id=str(current.get("canonical_work_id") or ""),
        ticket=str(current.get("ticket") or ""),
        packet=work_item,
        diagnostic_root=run_dir,
    )
    if not (
        isinstance(canonical, Mapping)
        and canonical.get("state") == "validating"
        and canonical.get("attention") == "active"
        and canonical.get("packet_path") == str(work_item)
        and canonical.get("branch") == (current.get("worktree") or {}).get("branch")
    ):
        raise DevelopmentDeliveryError(
            "worktree_ready delivery recovery could not refresh the canonical work projection"
        )
    TaskState(state_path).emit(
        event_type=recovery_event_type,
        idempotency_key=str(recovery["idempotency_key"]),
        payload={
            "ticket": current.get("ticket"),
            "receipt": str(receipt_path),
            "next_action": "record fresh review_self, review_others, qa, finalize, and merge evidence",
        },
    )


def _recover_active_worktree_ready_delivery(
    state_file: str | Path,
    *,
    reason: str,
    idempotency_key: str,
    apply: bool = False,
    context_loader: Callable[[Path], dict[str, Any]],
    recovery_schema: str,
    recovery_kind: str,
    recovery_result_schema: str,
    recovery_history_key: str,
    recovery_latest_key: str,
    recovery_directory: str,
    recovery_event_type: str,
) -> dict[str, Any]:
    """Recover one exact worktree-ready packet into fresh governed delivery."""

    state_path = Path(state_file).expanduser().resolve()
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise DevelopmentDeliveryError("worktree_ready delivery recovery requires a reason")
    if not idempotency_key.strip():
        raise DevelopmentDeliveryError("worktree_ready delivery recovery requires an idempotency key")
    state = TaskState(state_path)
    with _task_provisioning_admission_lock(state_path):
        current = state.read()
        recoveries = current.get(recovery_history_key)
        if isinstance(recoveries, list):
            for recovery in recoveries:
                if not isinstance(recovery, Mapping) or recovery.get("idempotency_key") != idempotency_key:
                    continue
                if recovery.get("reason") != normalized_reason:
                    raise DevelopmentDeliveryError(
                        "idempotency key belongs to a different worktree_ready delivery recovery"
                    )
                _complete_active_worktree_ready_delivery_recovery(
                    state_path,
                    current=current,
                    recovery=recovery,
                    apply=apply,
                    recovery_schema=recovery_schema,
                    recovery_kind=recovery_kind,
                    recovery_history_key=recovery_history_key,
                    recovery_event_type=recovery_event_type,
                )
                return {
                    "schema": recovery_result_schema,
                    "result": "replayed",
                    "state": str(state_path),
                    "ticket": current.get("ticket"),
                    "receipt": str(recovery["receipt"]),
                    "receipt_sha256": str(recovery["sha256"]),
                    "next_action": "record fresh review_self, review_others, qa, finalize, and merge evidence",
                }
        context = context_loader(state_path)
        original = _worktree_ready_recovery_original(context)
        receipt_path = (
            context["work_item"]
            / "artifacts"
            / "development-delivery"
            / recovery_directory
            / f"{hashlib.sha256(idempotency_key.encode('utf-8')).hexdigest()[:20]}.json"
        )
        recovered = {
            "state": "local_validation",
            "mode": "everything",
            "requested_stage": None,
            "goal": "merge",
            "stage_order": context["stage_order"],
            "start_stage": "review_self",
            "completion_stage": "merge",
            "stage_policies": context["stage_policies"],
            "portfolio_auto_dev": context["recovered_portfolio_auto_dev"],
            "fresh_stages_required": list(_ACTIVE_WORKTREE_READY_DELIVERY_FRESH_STAGES),
        }
        receipt = {
            "schema": recovery_schema,
            "kind": recovery_kind,
            "idempotency_key": idempotency_key,
            "reason": normalized_reason,
            "recorded_at": utc_now(),
            "original": original,
            "recovered": recovered,
        }
        if receipt_path.exists() or receipt_path.is_symlink():
            _, existing_bytes = _worktree_ready_recovery_packet_file(
                receipt_path, work_item=context["work_item"], label="recovery provenance"
            )
            existing = _worktree_ready_recovery_mapping(
                existing_bytes, label="recovery provenance"
            )
            if not (
                existing.get("schema") == receipt["schema"]
                and existing.get("kind") == receipt["kind"]
                and existing.get("idempotency_key") == idempotency_key
                and existing.get("reason") == normalized_reason
                and existing.get("original") == original
                and existing.get("recovered") == recovered
            ):
                raise DevelopmentDeliveryError(
                    "worktree_ready delivery recovery receipt path already has different content"
                )
            receipt = existing
        receipt_sha256 = _json_sha256(receipt)
        result = {
            "schema": recovery_result_schema,
            "result": "planned" if not apply else "recovered",
            "state": str(state_path),
            "ticket": current.get("ticket"),
            "receipt": str(receipt_path),
            "receipt_sha256": receipt_sha256,
            "next_action": "record fresh review_self, review_others, qa, finalize, and merge evidence",
        }
        if not apply:
            return result
        with _file_lock(context["portfolio_path"].with_suffix(context["portfolio_path"].suffix + ".lock")):
            locked = context_loader(state_path)
            if not (
                locked["task_sha256"] == context["task_sha256"]
                and locked["portfolio_sha256"] == context["portfolio_sha256"]
                and locked["autodev_sha256"] == context["autodev_sha256"]
                and locked["canonical_sha256"] == context["canonical_sha256"]
                and _worktree_ready_recovery_original(locked) == original
            ):
                raise DevelopmentDeliveryError(
                    "portfolio, task, projection, canonical row, or release evidence changed during worktree_ready delivery recovery; rerun preflight"
                )
            with _file_lock(state_path.with_suffix(state_path.suffix + ".lock")):
                _, latest_bytes = _worktree_ready_recovery_read_file(
                    state_path, label="task state"
                )
                if hashlib.sha256(latest_bytes).hexdigest() != context["task_sha256"]:
                    raise DevelopmentDeliveryError(
                        "task changed during worktree_ready delivery recovery; rerun preflight"
                    )
                if receipt_path.exists() or receipt_path.is_symlink():
                    _, current_receipt = _worktree_ready_recovery_packet_file(
                        receipt_path, work_item=context["work_item"], label="recovery provenance"
                    )
                    if _worktree_ready_recovery_mapping(
                        current_receipt, label="recovery provenance"
                    ) != receipt:
                        raise DevelopmentDeliveryError(
                            "worktree_ready delivery recovery receipt path changed during preflight"
                        )
                else:
                    _atomic_json(receipt_path, receipt)
                recovery = {
                    "idempotency_key": idempotency_key,
                    "reason": normalized_reason,
                    "receipt": str(receipt_path),
                    "sha256": receipt_sha256,
                    "recorded_at": receipt["recorded_at"],
                }
                latest = state.read()
                latest.update(
                    {
                        "state": "local_validation",
                        "failure": None,
                        "auto_dev_mode": "everything",
                        "requested_stage": None,
                        "goal": "merge",
                        "auto_dev_stage_order": context["stage_order"],
                        "auto_dev_start_stage": "review_self",
                        "auto_dev_completion_stage": "merge",
                        "auto_dev_stage_policies": context["stage_policies"],
                        "updated_at": utc_now(),
                        recovery_latest_key: idempotency_key,
                    }
                )
                latest.setdefault(recovery_history_key, []).append(recovery)
                latest.setdefault("receipts", []).append(
                    {
                        "state": "local_validation",
                        "ref": str(receipt_path),
                        "sha256": receipt_sha256,
                        "recorded_at": receipt["recorded_at"],
                    }
                )
                _atomic_json(state_path, latest)
        _complete_active_worktree_ready_delivery_recovery(
            state_path,
            current=latest,
            recovery=recovery,
            apply=True,
            recovery_schema=recovery_schema,
            recovery_kind=recovery_kind,
            recovery_history_key=recovery_history_key,
            recovery_event_type=recovery_event_type,
        )
        return result


def recover_active_worktree_ready_delivery(
    state_file: str | Path,
    *,
    reason: str,
    idempotency_key: str,
    apply: bool = False,
) -> dict[str, Any]:
    """Recover one active legacy readiness packet into fresh governed delivery."""

    return _recover_active_worktree_ready_delivery(
        state_file,
        reason=reason,
        idempotency_key=idempotency_key,
        apply=apply,
        context_loader=_active_worktree_ready_delivery_recovery_context,
        recovery_schema=ACTIVE_WORKTREE_READY_DELIVERY_RECOVERY_SCHEMA,
        recovery_kind="recover-active-worktree-ready-delivery",
        recovery_result_schema="active-worktree-ready-delivery-recovery-result/v1",
        recovery_history_key="active_worktree_ready_delivery_recoveries",
        recovery_latest_key="last_active_worktree_ready_delivery_recovery_key",
        recovery_directory="active-worktree-ready-delivery-recovery",
        recovery_event_type="development.task.active_worktree_ready_delivery_recovered",
    )


def recover_active_worktree_ready_pr_create_delivery(
    state_file: str | Path,
    *,
    reason: str,
    idempotency_key: str,
    apply: bool = False,
) -> dict[str, Any]:
    """Recover the exact historical PR Create boundary into fresh review delivery."""

    return _recover_active_worktree_ready_delivery(
        state_file,
        reason=reason,
        idempotency_key=idempotency_key,
        apply=apply,
        context_loader=_active_worktree_ready_pr_create_delivery_recovery_context,
        recovery_schema=ACTIVE_WORKTREE_READY_PR_CREATE_DELIVERY_RECOVERY_SCHEMA,
        recovery_kind="recover-active-worktree-ready-pr-create-delivery",
        recovery_result_schema="active-worktree-ready-pr-create-delivery-recovery-result/v1",
        recovery_history_key="active_worktree_ready_pr_create_delivery_recoveries",
        recovery_latest_key="last_active_worktree_ready_pr_create_delivery_recovery_key",
        recovery_directory="active-worktree-ready-pr-create-delivery-recovery",
        recovery_event_type="development.task.active_worktree_ready_pr_create_delivery_recovered",
    )


def _active_worktree_ready_release_propagation_recovery_variant(
    task: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Select one exact recovery provenance admitted for family continuation."""

    populated: list[tuple[dict[str, Any], list[Any]]] = []
    for configured in _ACTIVE_WORKTREE_READY_RELEASE_PROPAGATION_RECOVERY_VARIANTS:
        rows = task.get(str(configured["history_key"]))
        if rows in (None, []):
            continue
        if not isinstance(rows, list):
            raise DevelopmentDeliveryError(
                "recovered release-propagation continuation recovery history is malformed"
            )
        populated.append((dict(configured), rows))
    if len(populated) != 1:
        raise DevelopmentDeliveryError(
            "recovered release-propagation continuation requires exactly one supported recovery history"
        )
    configured, rows = populated[0]
    if len(rows) != 1 or not isinstance(rows[0], Mapping):
        raise DevelopmentDeliveryError(
            "recovered release-propagation continuation recovery history is ambiguous"
        )
    return configured, dict(rows[0])


def _active_worktree_ready_release_propagation_continuation_context(
    state_path: Path, *, family_ref: str | Path
) -> dict[str, Any]:
    """Prove one recovered packet may bind one current PR-family successor.

    This intentionally does not use the normal release-propagation stage:
    that stage records completed PR Create authority, which a recovered packet
    must never backfill.  The only permitted continuation is an immutable
    successor of the family pinned by its worktree-ready recovery provenance.
    """

    state_path = state_path.expanduser().resolve()
    _, task_bytes = _worktree_ready_recovery_read_file(state_path, label="task state")
    task = _worktree_ready_recovery_mapping(task_bytes, label="task state")
    work_item = Path(str(task.get("work_item") or "")).expanduser().resolve()
    continuations = task.get("active_worktree_ready_release_propagation_continuations")
    if not (
        continuations in (None, [])
        or (
            isinstance(continuations, list)
            and len(continuations) == 1
            and isinstance(continuations[0], Mapping)
        )
    ):
        raise DevelopmentDeliveryError(
            "recovered release-propagation continuation requires at most one continuation"
        )
    if not work_item.is_dir():
        raise DevelopmentDeliveryError(
            "recovered release-propagation continuation requires its active packet"
        )
    recovery_variant, recovery = _active_worktree_ready_release_propagation_recovery_variant(
        task
    )
    recovery_path, recovery_bytes = _worktree_ready_recovery_packet_file(
        recovery.get("receipt"), work_item=work_item, label="recovery provenance"
    )
    recovery_receipt = _worktree_ready_recovery_mapping(
        recovery_bytes, label="recovery provenance"
    )
    if not (
        recovery_path
        == (
            work_item
            / "artifacts"
            / "development-delivery"
            / str(recovery_variant["directory"])
            / f"{hashlib.sha256(str(recovery.get('idempotency_key') or '').encode('utf-8')).hexdigest()[:20]}.json"
        ).resolve()
        and recovery_receipt.get("schema")
        == recovery_variant["schema"]
        and recovery_receipt.get("kind") == recovery_variant["kind"]
        and recovery_receipt.get("idempotency_key") == recovery.get("idempotency_key")
        and recovery_receipt.get("reason") == recovery.get("reason")
        and recovery_receipt.get("recorded_at") == recovery.get("recorded_at")
        and _json_sha256(recovery_receipt) == recovery.get("sha256")
        and (
            recovery_variant["recovery_shape"] is None
            or (
                isinstance(recovery_receipt.get("original"), Mapping)
                and recovery_receipt["original"].get("recovery_shape")
                == recovery_variant["recovery_shape"]
            )
        )
    ):
        raise DevelopmentDeliveryError(
            "recovered release-propagation continuation recovery provenance is not immutable"
        )
    # Reuse the recovery's own replay verifier before admitting this narrower
    # continuation.  It checks the recovered task/projection/canonical state
    # and the original receipt pair without changing any derived projection.
    _complete_active_worktree_ready_delivery_recovery(
        state_path,
        current=task,
        recovery=recovery,
        apply=False,
        recovery_schema=str(recovery_variant["schema"]),
        recovery_kind=str(recovery_variant["kind"]),
        recovery_history_key=str(recovery_variant["history_key"]),
        recovery_event_type=str(recovery_variant["event_type"]),
        derived_requested_stages=tuple(recovery_variant["derived_requested_stages"]),
    )
    expected_receipt_states = {
        "claimed",
        "groom_check",
        "context_ready",
        "work_item_ready",
        "worktree_ready",
        "local_validation",
    }
    task_receipts = task.get("receipts")
    if not (
        isinstance(task_receipts, list)
        and len(task_receipts) == len(expected_receipt_states)
        and {
            str(row.get("state") or "")
            for row in task_receipts
            if isinstance(row, Mapping) and str(row.get("ref") or "").strip()
        }
        == expected_receipt_states
        and sum(
            1
            for row in task_receipts
            if isinstance(row, Mapping) and row.get("state") == "local_validation"
        )
        == 1
        and not task.get("subject_supersessions")
        and not task.get("subject_supersession_resolutions")
    ):
        raise DevelopmentDeliveryError(
            "recovered release-propagation continuation requires only its immutable pre-delivery and recovery receipts"
        )
    original = (
        recovery_receipt.get("original")
        if isinstance(recovery_receipt.get("original"), Mapping)
        else {}
    )
    original_release = (
        original.get("release_propagation")
        if isinstance(original.get("release_propagation"), Mapping)
        else {}
    )
    predecessor = _worktree_ready_recovery_release_identity(
        task,
        work_item=work_item,
        family_ref=Path(str(original_release.get("family_ref") or "")).expanduser(),
        # Only the stored recovery predecessor may predate the clean worktree
        # HEAD.  The successor call below intentionally uses the strict default.
        require_current_worktree_head=False,
    )
    expected_predecessor = {
        "family_ref": str(predecessor["family"]),
        "family_sha256": predecessor["family_sha256"],
        "provider_ref": str(predecessor["provider"]),
        "provider_sha256": predecessor["provider_sha256"],
        "pull_request_identity": predecessor["pull_request_identity"],
    }
    if original_release != expected_predecessor:
        raise DevelopmentDeliveryError(
            "recovered release-propagation continuation predecessor evidence changed"
        )
    successor_path, successor_bytes = _worktree_ready_recovery_packet_file(
        family_ref, work_item=work_item, label="current release family evidence"
    )
    successor = _worktree_ready_recovery_release_identity(
        task, work_item=work_item, family_ref=successor_path
    )
    successor_payload = _worktree_ready_recovery_mapping(
        successor_bytes, label="current release family evidence"
    )
    predecessor_identity = predecessor["pull_request_identity"]
    successor_identity = successor["pull_request_identity"]
    matching_identity_fields = (
        "provider",
        "repository",
        "base_branch",
        "pull_request",
        "source_branch",
    )
    old_head = str(predecessor_identity["source_head_sha"] or "").strip()
    new_head = str(successor_identity["source_head_sha"] or "").strip()
    supersession = (
        successor_payload.get("evidence", {}).get("supersession")
        if isinstance(successor_payload.get("evidence"), Mapping)
        and isinstance(successor_payload["evidence"].get("supersession"), Mapping)
        else {}
    )
    if not (
        successor_path != predecessor["family"]
        and all(
            successor_identity[field] == predecessor_identity[field]
            for field in matching_identity_fields
        )
        and old_head.lower() != new_head.lower()
        and str(supersession.get("supersedes_source_head_sha") or "").strip().lower()
        == old_head.lower()
        and str(supersession.get("reason") or "").strip()
    ):
        raise DevelopmentDeliveryError(
            "recovered release-propagation continuation requires the exact current successor of its recovery-bound PR family"
        )
    return {
        "state_path": state_path,
        "task": task,
        "task_sha256": hashlib.sha256(task_bytes).hexdigest(),
        "work_item": work_item,
        "recovery_variant": recovery_variant,
        "recovery": recovery,
        "recovery_receipt": recovery_receipt,
        "predecessor": expected_predecessor,
        "successor": {
            "family_ref": str(successor["family"]),
            "family_sha256": successor["family_sha256"],
            "provider_ref": str(successor["provider"]),
            "provider_sha256": successor["provider_sha256"],
            "pull_request_identity": successor_identity,
        },
        "continuations": list(continuations or []),
    }


def bind_recovered_worktree_ready_pr_family(
    state_file: str | Path,
    *,
    family_ref: str | Path,
    reason: str,
    idempotency_key: str,
    apply: bool = False,
) -> dict[str, Any]:
    """Append one provenance-bound PR-family successor to a recovered packet.

    This is a compatibility continuation, not PR Create.  It never records a
    normal stage receipt or alters the fresh Review/QA/Finalize/Merge boundary.
    """

    state_path = Path(state_file).expanduser().resolve()
    normalized_reason = reason.strip()
    normalized_key = idempotency_key.strip()
    if not normalized_reason or not normalized_key:
        raise DevelopmentDeliveryError(
            "recovered release-propagation continuation requires a reason and idempotency key"
        )
    state = TaskState(state_path)
    with _task_provisioning_admission_lock(state_path):
        context = _active_worktree_ready_release_propagation_continuation_context(
            state_path, family_ref=family_ref
        )
        original = {
            "recovery": {
                "receipt": str(context["recovery"]["receipt"]),
                "sha256": str(context["recovery"]["sha256"]),
                "idempotency_key": str(context["recovery"]["idempotency_key"]),
            },
            "release_propagation": context["predecessor"],
        }
        continuation = {
            "release_propagation": context["successor"],
            "fresh_stages_required": list(_ACTIVE_WORKTREE_READY_DELIVERY_FRESH_STAGES),
        }
        receipt_path = (
            context["work_item"]
            / "artifacts"
            / "development-delivery"
            / "active-worktree-ready-release-propagation-continuation"
            / f"{hashlib.sha256(normalized_key.encode('utf-8')).hexdigest()[:20]}.json"
        )
        existing_records = context["continuations"]
        if existing_records:
            existing_record = dict(existing_records[0])
            if existing_record.get("idempotency_key") != normalized_key:
                raise DevelopmentDeliveryError(
                    "recovered release-propagation continuation is already bound to a different successor"
                )
            if existing_record.get("reason") != normalized_reason:
                raise DevelopmentDeliveryError(
                    "idempotency key belongs to a different recovered release-propagation continuation"
                )
            existing_path, existing_bytes = _worktree_ready_recovery_packet_file(
                existing_record.get("receipt"),
                work_item=context["work_item"],
                label="release-propagation continuation provenance",
            )
            existing_receipt = _worktree_ready_recovery_mapping(
                existing_bytes, label="release-propagation continuation provenance"
            )
            expected_without_timestamp = {
                "schema": ACTIVE_WORKTREE_READY_RELEASE_PROPAGATION_CONTINUATION_SCHEMA,
                "kind": "bind-recovered-worktree-ready-pr-family",
                "idempotency_key": normalized_key,
                "reason": normalized_reason,
                "original": original,
                "continuation": continuation,
            }
            if not (
                existing_path == receipt_path
                and _json_sha256(existing_receipt) == existing_record.get("sha256")
                and {
                    key: value
                    for key, value in existing_receipt.items()
                    if key != "recorded_at"
                }
                == expected_without_timestamp
            ):
                raise DevelopmentDeliveryError(
                    "recovered release-propagation continuation provenance does not match task state"
                )
            return {
                "schema": "active-worktree-ready-release-propagation-continuation-result/v1",
                "result": "replayed",
                "state": str(state_path),
                "ticket": context["task"].get("ticket"),
                "receipt": str(existing_path),
                "receipt_sha256": str(existing_record["sha256"]),
                "next_action": "record fresh review_self, review_others, qa, finalize, and merge evidence",
            }
        receipt = {
            "schema": ACTIVE_WORKTREE_READY_RELEASE_PROPAGATION_CONTINUATION_SCHEMA,
            "kind": "bind-recovered-worktree-ready-pr-family",
            "idempotency_key": normalized_key,
            "reason": normalized_reason,
            "recorded_at": utc_now(),
            "original": original,
            "continuation": continuation,
        }
        if receipt_path.exists() or receipt_path.is_symlink():
            _, existing_bytes = _worktree_ready_recovery_packet_file(
                receipt_path,
                work_item=context["work_item"],
                label="release-propagation continuation provenance",
            )
            existing_receipt = _worktree_ready_recovery_mapping(
                existing_bytes, label="release-propagation continuation provenance"
            )
            if {
                key: value
                for key, value in existing_receipt.items()
                if key != "recorded_at"
            } != {
                key: value for key, value in receipt.items() if key != "recorded_at"
            }:
                raise DevelopmentDeliveryError(
                    "recovered release-propagation continuation receipt path already has different content"
                )
            receipt = existing_receipt
        receipt_sha256 = _json_sha256(receipt)
        result = {
            "schema": "active-worktree-ready-release-propagation-continuation-result/v1",
            "result": "planned" if not apply else "bound",
            "state": str(state_path),
            "ticket": context["task"].get("ticket"),
            "receipt": str(receipt_path),
            "receipt_sha256": receipt_sha256,
            "next_action": "record fresh review_self, review_others, qa, finalize, and merge evidence",
        }
        if not apply:
            return result
        with _file_lock(state_path.with_suffix(state_path.suffix + ".lock")):
            locked = _active_worktree_ready_release_propagation_continuation_context(
                state_path, family_ref=family_ref
            )
            if not (
                locked["task_sha256"] == context["task_sha256"]
                and locked["recovery"] == context["recovery"]
                and locked["predecessor"] == context["predecessor"]
                and locked["successor"] == context["successor"]
                and not locked["continuations"]
            ):
                raise DevelopmentDeliveryError(
                    "task, recovery provenance, or PR-family evidence changed during recovered release-propagation continuation; rerun preflight"
                )
            if receipt_path.exists() or receipt_path.is_symlink():
                _, existing_bytes = _worktree_ready_recovery_packet_file(
                    receipt_path,
                    work_item=context["work_item"],
                    label="release-propagation continuation provenance",
                )
                if _worktree_ready_recovery_mapping(
                    existing_bytes, label="release-propagation continuation provenance"
                ) != receipt:
                    raise DevelopmentDeliveryError(
                        "recovered release-propagation continuation receipt path already has different content"
                    )
            else:
                _atomic_json(receipt_path, receipt)
            latest = deepcopy(locked["task"])
            latest.setdefault(
                "active_worktree_ready_release_propagation_continuations", []
            ).append(
                {
                    "idempotency_key": normalized_key,
                    "reason": normalized_reason,
                    "receipt": str(receipt_path),
                    "sha256": receipt_sha256,
                    "recorded_at": receipt["recorded_at"],
                }
            )
            latest["updated_at"] = utc_now()
            _atomic_json(state_path, latest)
        state.emit(
            event_type="development.task.recovered_pr_family_bound",
            idempotency_key=normalized_key,
            payload={
                "ticket": context["task"].get("ticket"),
                "receipt": str(receipt_path),
                "next_action": result["next_action"],
            },
        )
        return result


def _active_pr_create_escalation_regular_file(
    raw_path: Any,
    *,
    label: str,
) -> tuple[Path, bytes]:
    """Read one immutable absolute input through the shared no-follow guard."""

    raw = str(raw_path or "").strip()
    candidate = Path(raw).expanduser()
    if not raw or not candidate.is_absolute():
        raise DevelopmentDeliveryError(
            f"active pr_create escalation {label} must be an absolute regular file"
        )
    return _worktree_ready_recovery_read_file(candidate, label=label)


def _active_pr_create_escalation_packet_file(
    raw_path: Any,
    *,
    work_item: Path,
    label: str,
) -> tuple[Path, bytes]:
    """Read one packet-local immutable input without traversal or links."""

    raw = str(raw_path or "").strip()
    if not raw:
        raise DevelopmentDeliveryError(
            f"active pr_create escalation {label} is missing"
        )
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = work_item / candidate
    return _worktree_ready_recovery_read_file(
        candidate, label=label, work_item=work_item
    )


def _active_pr_create_escalation_mapping(
    content: bytes,
    *,
    label: str,
) -> dict[str, Any]:
    """Decode one descriptor-verified immutable mapping."""

    try:
        value = yaml.safe_load(content.decode("utf-8")) or {}
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise DevelopmentDeliveryError(
            f"active pr_create escalation {label} is malformed"
        ) from exc
    if not isinstance(value, Mapping):
        raise DevelopmentDeliveryError(
            f"active pr_create escalation {label} is malformed"
        )
    return dict(value)


def _active_pr_create_escalation_release_identity(
    task: Mapping[str, Any],
    *,
    state_path: Path,
    work_item: Path,
    run_dir: Path,
) -> dict[str, Any]:
    """Verify the one immutable PR Create receipt retained by the migration."""

    stage_receipts = task.get("stage_receipts")
    if not isinstance(stage_receipts, Mapping) or set(stage_receipts) != {
        "release_propagation"
    }:
        raise DevelopmentDeliveryError(
            "active pr_create escalation requires exactly one release_propagation stage receipt"
        )
    descriptor = stage_receipts["release_propagation"]
    if not isinstance(descriptor, Mapping):
        raise DevelopmentDeliveryError(
            "active pr_create escalation requires a hash-bound release_propagation receipt"
        )
    wrapper, wrapper_bytes = _active_pr_create_escalation_regular_file(
        descriptor.get("ref"), label="release_propagation wrapper"
    )
    try:
        wrapper.relative_to(run_dir)
    except ValueError as exc:
        raise DevelopmentDeliveryError(
            "active pr_create escalation release_propagation receipt is outside task/run scope"
        ) from exc
    expected_wrapper_sha256 = str(descriptor.get("sha256") or "").strip().lower()
    actual_wrapper_sha256 = hashlib.sha256(wrapper_bytes).hexdigest()
    if not re.fullmatch(r"[a-f0-9]{64}", expected_wrapper_sha256) or (
        actual_wrapper_sha256 != expected_wrapper_sha256
    ):
        raise DevelopmentDeliveryError(
            "active pr_create escalation release_propagation receipt digest does not match"
        )
    wrapper_payload = _active_pr_create_escalation_mapping(
        wrapper_bytes, label="release_propagation wrapper"
    )
    if not (
        wrapper_payload.get("schema") == "development-stage-receipt/v1"
        and wrapper_payload.get("stage") == "release_propagation"
        and str(wrapper_payload.get("idempotency_key") or "").strip()
    ):
        raise DevelopmentDeliveryError(
            "active pr_create escalation release_propagation wrapper is malformed"
        )
    evidence_path, evidence_bytes = _active_pr_create_escalation_packet_file(
        wrapper_payload.get("receipt"),
        work_item=work_item,
        label="release_propagation evidence",
    )
    evidence = _active_pr_create_escalation_mapping(
        evidence_bytes, label="release_propagation evidence"
    )
    evidence_sha256 = _json_sha256(evidence)
    if (
        wrapper_payload.get("evidence_sha256") != evidence_sha256
        or evidence.get("schema") != "development-stage-evidence/v1"
        or evidence.get("state") != "release_propagation"
        or evidence.get("status") not in {"verified", "passed", "completed"}
    ):
        raise DevelopmentDeliveryError(
            "active pr_create escalation release_propagation evidence is missing or changed"
        )
    details = (
        evidence.get("evidence") if isinstance(evidence.get("evidence"), Mapping) else {}
    )
    repository = task.get("repository") if isinstance(task.get("repository"), Mapping) else {}
    worktree = task.get("worktree") if isinstance(task.get("worktree"), Mapping) else {}
    repository_id = str(repository.get("id") or "").strip()
    base_branch = str(repository.get("base_branch") or "").strip()
    source_branch = str(worktree.get("branch") or "").strip()
    if not repository_id.startswith("git:github.com/"):
        raise DevelopmentDeliveryError(
            "active pr_create escalation requires a selected GitHub repository identity"
        )
    github_repository = repository_id.removeprefix("git:github.com/")
    family = details.get("family") if isinstance(details.get("family"), list) else []
    row = family[0] if len(family) == 1 and isinstance(family[0], Mapping) else {}
    pull_request_number = row.get("pull_request")
    source_head_sha = str(row.get("source_head") or "").strip()
    base_sha = str(row.get("base_sha") or "").strip()
    expected_snapshot = work_item / "artifacts" / "auto-dev-pr-create" / "source-snapshot.json"
    expected_provider = work_item / "artifacts" / "auto-dev-pr-create" / "provider-readback.json"
    receipt_refs = details.get("receipt_refs") if isinstance(details.get("receipt_refs"), list) else []
    snapshot_path, snapshot_bytes = _active_pr_create_escalation_packet_file(
        expected_snapshot, work_item=work_item, label="source snapshot"
    )
    provider_path, provider_bytes = _active_pr_create_escalation_packet_file(
        expected_provider, work_item=work_item, label="provider readback"
    )
    snapshot = _active_pr_create_escalation_mapping(snapshot_bytes, label="source snapshot")
    provider = _active_pr_create_escalation_mapping(provider_bytes, label="provider readback")
    pull_request = f"github:{github_repository}#{pull_request_number}"
    if not (
        repository_id
        and base_branch
        and source_branch
        and len(family) == 1
        and row.get("base") == base_branch
        and re.fullmatch(r"[a-fA-F0-9]{7,64}", base_sha)
        and base_sha.lower()
        == str(worktree.get("base_sha") or "").strip().lower()
        and str(row.get("classification") or "") == "created"
        and row.get("merged") is False
        and str(row.get("provider") or "").strip().lower() == "github"
        and row.get("provider_readback_verified") is True
        and isinstance(pull_request_number, int)
        and pull_request_number > 0
        and row.get("repository") == github_repository
        and row.get("source_branch") == source_branch
        and re.fullmatch(r"[a-fA-F0-9]{7,64}", source_head_sha)
        and str(row.get("state") or "").strip().lower() == "open"
        and row.get("url") == f"https://github.com/{github_repository}/pull/{pull_request_number}"
        and str(expected_snapshot.relative_to(work_item)) in receipt_refs
        and str(expected_provider.relative_to(work_item)) in receipt_refs
        and snapshot_path == expected_snapshot.resolve()
        and snapshot.get("schema") == "auto-dev-pr-create-source-snapshot/v1"
        and snapshot.get("repository") == github_repository
        and str(snapshot.get("provider") or "").lower() == "github"
        and snapshot.get("base_branch") == base_branch
        and str(snapshot.get("base_sha") or "") == base_sha
        and snapshot.get("source_branch") == source_branch
        and str(snapshot.get("source_head_sha") or "") == source_head_sha
        and str(snapshot.get("remote_head_sha") or "") == source_head_sha
        and snapshot.get("remote_head_matches_local") is True
        and provider_path == expected_provider.resolve()
        and provider.get("schema") == "auto-dev-pr-create-provider-readback/v1"
        and provider.get("repository") == github_repository
        and str(provider.get("provider") or "").lower() == "github"
        and provider.get("pull_request") == pull_request_number
        and provider.get("url") == row.get("url")
        and provider.get("state") == "OPEN"
        and provider.get("is_draft") is False
        and provider.get("base_branch") == base_branch
        and str(provider.get("base_sha") or "") == base_sha
        and provider.get("source_branch") == source_branch
        and str(provider.get("source_head_sha") or "") == source_head_sha
    ):
        raise DevelopmentDeliveryError(
            "active pr_create escalation release_propagation evidence identity is incomplete or does not match the selected task"
        )
    return {
        "wrapper": wrapper,
        "wrapper_sha256": actual_wrapper_sha256,
        "evidence": evidence_path,
        "evidence_sha256": evidence_sha256,
        "source_snapshot": snapshot_path,
        "source_snapshot_sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
        "provider_readback": provider_path,
        "provider_readback_sha256": hashlib.sha256(provider_bytes).hexdigest(),
        "pull_request_identity": {
            "provider": "github",
            "repository": repository_id,
            "base_branch": base_branch,
            "pull_request": pull_request,
            "source_branch": source_branch,
            "source_head_sha": source_head_sha,
        },
        "task_state": state_path,
    }


def _validate_active_pr_create_escalation_portfolio(
    portfolio: Mapping[str, Any],
    *,
    task: Mapping[str, Any],
    state_path: Path,
) -> dict[str, Any]:
    """Accept only AGE-190's recorded one-task PR Create portfolio boundary."""

    auto_dev = (
        portfolio.get("auto_dev") if isinstance(portfolio.get("auto_dev"), Mapping) else {}
    )
    rows = portfolio.get("tasks") if isinstance(portfolio.get("tasks"), list) else []
    ticket = str(task.get("ticket") or "")
    if not (
        portfolio.get("state") == "local_validation"
        and portfolio.get("run_id") == task.get("run_id")
        and portfolio.get("tickets") == [ticket]
        and auto_dev.get("mode") == "single_stage"
        # AGE-190 recorded develop as the portfolio selector while the task and
        # packet projection selected the completed PR Create boundary.
        and auto_dev.get("requested_stage") == "develop"
        and auto_dev.get("goal") == "pr_create"
        and auto_dev.get("start_stage") == "groom"
        and auto_dev.get("completion_stage") == "pr_create"
        and auto_dev.get("provision_worktree") is True
        and auto_dev.get("stage_order") == task.get("auto_dev_stage_order")
        and auto_dev.get("stage_policies") == task.get("auto_dev_stage_policies")
        and not portfolio.get("active_pr_create_delivery_escalations")
        and len(rows) == 1
        and isinstance(rows[0], Mapping)
        and rows[0].get("ticket") == ticket
        and Path(str(rows[0].get("state_ref") or "")).expanduser().resolve()
        == state_path
        and rows[0].get("canonical_work_id") == task.get("canonical_work_id")
    ):
        raise DevelopmentDeliveryError(
            "active pr_create escalation requires the exact AGE-190 nonblocked one-task pr_create portfolio"
        )
    return dict(auto_dev)


def _active_pr_create_delivery_escalation_context(state_path: Path) -> dict[str, Any]:
    """Prove the sole legacy local-validation PR Create boundary is recoverable."""

    state_path = state_path.expanduser().resolve()
    _, task_bytes = _active_pr_create_escalation_regular_file(
        state_path, label="task state"
    )
    task = _active_pr_create_escalation_mapping(task_bytes, label="task state")
    if not (
        task.get("state") == "local_validation"
        and task.get("failure") is None
        and task.get("auto_dev_mode") == "single_stage"
        and task.get("requested_stage") == "pr_create"
        and task.get("goal") == "pr_create"
        and task.get("auto_dev_start_stage") == "groom"
        and task.get("auto_dev_completion_stage") == "pr_create"
        and not task.get("active_pr_create_delivery_escalations")
        and not task.get("subject_supersessions")
        and not task.get("subject_supersession_resolutions")
        and not any(
            task.get(field)
            for field in ("subject_revision", "terminal_revision", "deployed_revision")
        )
    ):
        raise DevelopmentDeliveryError(
            "active pr_create escalation requires the exact active nonblocked local_validation single-stage pr_create task"
        )
    required = (
        "os_root",
        "domain",
        "project",
        "ticket",
        "run_id",
        "work_item",
        "autodev_path",
        "canonical_work_id",
    )
    if not all(str(task.get(field) or "").strip() for field in required):
        raise DevelopmentDeliveryError(
            "active pr_create escalation requires a fully linked canonical task"
        )
    stage_order = validate_auto_dev_stage_order(list(task.get("auto_dev_stage_order") or []))
    stage_policies = validate_auto_dev_stage_policies(
        task.get("auto_dev_stage_policies")
        if isinstance(task.get("auto_dev_stage_policies"), Mapping)
        else {}
    )
    root = expand_path(str(task["os_root"]))
    domain = normalize_domain(str(task["domain"]))
    project = validate_name(str(task["project"]), "project")
    ticket = str(task["ticket"])
    work_item = Path(str(task["work_item"])).expanduser().resolve()
    project_path = project_root(root, domain, project)
    if not (
        work_item.is_dir()
        and (work_item / "work.yml").is_file()
        and _project_work_item_lane(work_item, project_path) == "02-active"
    ):
        raise DevelopmentDeliveryError(
            "active pr_create escalation requires one active canonical work-item packet"
        )
    autodev_path = Path(str(task["autodev_path"])).expanduser().resolve()
    if autodev_path != (work_item / "autodev.json").resolve():
        raise DevelopmentDeliveryError(
            "active pr_create escalation Auto-Dev projection is not packet-local"
        )
    _, autodev_bytes = _active_pr_create_escalation_packet_file(
        autodev_path, work_item=work_item, label="Auto-Dev projection"
    )
    projection = _active_pr_create_escalation_mapping(
        autodev_bytes, label="Auto-Dev projection"
    )
    projection_delivery = (
        projection.get("delivery") if isinstance(projection.get("delivery"), Mapping) else {}
    )
    stages = projection.get("stages") if isinstance(projection.get("stages"), Mapping) else {}
    if not (
        projection.get("mode") == "single_stage"
        and projection.get("requested_stage") == "pr_create"
        and projection.get("start_stage") == "groom"
        and projection.get("completion_stage") == "pr_create"
        and projection_delivery.get("state") == "local_validation"
        and projection_delivery.get("goal") == "pr_create"
        and projection_delivery.get("run_id") == task["run_id"]
        and Path(str(projection_delivery.get("task_state_ref") or "")).expanduser().resolve()
        == state_path
        and Path(str(projection_delivery.get("work_item") or "")).expanduser().resolve()
        == work_item
        and projection_delivery.get("canonical_work_id") == task["canonical_work_id"]
        and projection.get("canonical_work_id") == task["canonical_work_id"]
        and isinstance(projection.get("source"), Mapping)
        and projection["source"].get("key") == ticket
    ):
        raise DevelopmentDeliveryError(
            "active pr_create escalation requires the exact single-stage Auto-Dev projection"
        )
    pr_index = stage_order.index("pr_create")
    for stage in stage_order[: pr_index + 1]:
        row = stages.get(stage)
        if not (
            isinstance(row, Mapping)
            and row.get("status") in {"completed", "not_required"}
            and isinstance(row.get("receipt_refs"), list)
            and row.get("receipt_refs")
        ):
            raise DevelopmentDeliveryError(
                "active pr_create escalation requires every pre-PR stage to be terminal and receipt-backed"
            )
    for stage in _ACTIVE_PR_CREATE_ESCALATION_POST_PR_STAGES:
        row = stages.get(stage)
        if not (
            isinstance(row, Mapping)
            and row.get("status") == "out_of_scope"
            and row.get("receipt_refs") == []
        ):
            raise DevelopmentDeliveryError(
                "active pr_create escalation refuses existing post-PR authority"
            )
    stage_root = work_item / "artifacts" / "auto-dev-orchestration" / "stages"
    for stage in _ACTIVE_PR_CREATE_ESCALATION_POST_PR_STAGES:
        candidates = [stage_root / f"{stage}.json", stage_root / stage / "latest.json"]
        if any(path.exists() or path.is_symlink() for path in candidates):
            raise DevelopmentDeliveryError(
                "active pr_create escalation refuses latent post-PR authority artifacts"
            )
    receipts = task.get("receipts")
    if not (
        isinstance(receipts, list)
        and receipts
        and all(
            isinstance(row, Mapping)
            and str(row.get("state") or "").strip()
            and str(row.get("ref") or "").strip()
            for row in receipts
        )
    ):
        raise DevelopmentDeliveryError(
            "active pr_create escalation requires immutable original task receipts"
        )
    forbidden_states = {
        "pre_pr_review",
        "pr_open",
        "ci_repair",
        "review_repair",
        "post_pr_review",
        "ready_for_merge",
        "merged",
        "deployment_pending",
        "deploying",
        "post_deploy_validation",
        "delivery_complete",
    }
    if forbidden_states & {str(row.get("state") or "") for row in receipts}:
        raise DevelopmentDeliveryError(
            "active pr_create escalation refuses prior review, QA, Finalize, or terminal delivery authority"
        )
    local_validation = [row for row in receipts if row.get("state") == "local_validation"]
    if len(local_validation) != 1:
        raise DevelopmentDeliveryError(
            "active pr_create escalation requires exactly one immutable local_validation receipt"
        )
    local_sha256 = str(local_validation[0].get("sha256") or "").strip().lower()
    try:
        _, local_bytes = _active_pr_create_escalation_packet_file(
            local_validation[0].get("ref"),
            work_item=work_item,
            label="local_validation receipt",
        )
    except DevelopmentDeliveryError as exc:
        raise DevelopmentDeliveryError(
            "active pr_create escalation local_validation receipt is not immutable and packet-bound"
        ) from exc
    if not re.fullmatch(r"[a-f0-9]{64}", local_sha256) or (
        hashlib.sha256(local_bytes).hexdigest() != local_sha256
    ):
        raise DevelopmentDeliveryError(
            "active pr_create escalation local_validation receipt is not immutable and packet-bound"
        )
    worktree = task.get("worktree") if isinstance(task.get("worktree"), Mapping) else {}
    worktree_path = Path(str(worktree.get("path") or "")).expanduser()
    if not (
        worktree_path.is_dir()
        and not worktree_path.is_symlink()
        and str(worktree.get("branch") or "").strip()
        and re.fullmatch(r"[a-fA-F0-9]{7,64}", str(worktree.get("base_sha") or "").strip())
    ):
        raise DevelopmentDeliveryError(
            "active pr_create escalation requires the original registered worktree receipt"
        )
    run_dir = state_path.parent.parent.parent.resolve()
    release = _active_pr_create_escalation_release_identity(
        task, state_path=state_path, work_item=work_item, run_dir=run_dir
    )
    projected_wrapper_paths: list[Path] = []
    for ref in stages["pr_create"].get("receipt_refs") or []:
        candidate = Path(str(ref or "").strip()).expanduser()
        if candidate.is_absolute():
            projected_path, _ = _active_pr_create_escalation_regular_file(
                candidate, label="projected pr_create wrapper"
            )
        else:
            projected_path, _ = _active_pr_create_escalation_packet_file(
                candidate, work_item=work_item, label="projected pr_create wrapper"
            )
        projected_wrapper_paths.append(projected_path)
    if not any(path == release["wrapper"] for path in projected_wrapper_paths):
        raise DevelopmentDeliveryError(
            "active pr_create escalation projection does not bind the immutable release_propagation wrapper"
        )
    portfolio_path = run_dir / "portfolio.json"
    _, portfolio_bytes = _active_pr_create_escalation_regular_file(
        portfolio_path, label="portfolio"
    )
    portfolio = _active_pr_create_escalation_mapping(portfolio_bytes, label="portfolio")
    portfolio_auto_dev = _validate_active_pr_create_escalation_portfolio(
        portfolio, task=task, state_path=state_path
    )
    canonical = _read_canonical_development_work(
        root,
        canonical_work_id=str(task["canonical_work_id"]),
        ticket=ticket,
        packet=work_item,
        diagnostic_root=run_dir,
    )
    if not (
        isinstance(canonical, Mapping)
        and canonical.get("id") == task["canonical_work_id"]
        and canonical.get("state") == "validating"
        and canonical.get("attention") == "active"
        and canonical.get("domain") == domain
        and canonical.get("project") == project
        and canonical.get("source_key") == ticket
        and canonical.get("packet_path") == str(work_item)
        and canonical.get("worktree_path") == str(worktree_path)
        and canonical.get("branch") == worktree.get("branch")
    ):
        raise DevelopmentDeliveryError(
            "active pr_create escalation requires one active canonical local-validation work row"
        )
    escalated_portfolio_auto_dev = {
        **portfolio_auto_dev,
        "mode": "everything",
        "requested_stage": None,
        "goal": "merge",
        "stage_order": stage_order,
        "start_stage": "groom",
        "completion_stage": "merge",
        "stage_policies": stage_policies,
    }
    return {
        "task": task,
        "task_sha256": hashlib.sha256(task_bytes).hexdigest(),
        "work_item": work_item,
        "autodev_path": autodev_path,
        "autodev_sha256": hashlib.sha256(autodev_bytes).hexdigest(),
        "portfolio": portfolio,
        "portfolio_path": portfolio_path,
        "portfolio_sha256": hashlib.sha256(portfolio_bytes).hexdigest(),
        "portfolio_auto_dev": portfolio_auto_dev,
        "escalated_portfolio_auto_dev": escalated_portfolio_auto_dev,
        "canonical": dict(canonical),
        "canonical_sha256": _json_sha256(dict(canonical)),
        "stage_order": stage_order,
        "stage_policies": stage_policies,
        "worktree": dict(worktree),
        "release": release,
    }


def _revalidate_active_pr_create_escalation_release(
    current: Mapping[str, Any],
    *,
    state_path: Path,
    original: Mapping[str, Any],
) -> None:
    """Re-prove the original PR family before resuming an interrupted replay."""

    work_item = Path(str(current.get("work_item") or "")).expanduser().resolve()
    run_dir = state_path.parent.parent.parent.resolve()
    release = _active_pr_create_escalation_release_identity(
        current, state_path=state_path, work_item=work_item, run_dir=run_dir
    )
    expected_release = {
        "wrapper_ref": str(release["wrapper"]),
        "wrapper_sha256": release["wrapper_sha256"],
        "evidence_ref": str(release["evidence"]),
        "evidence_sha256": release["evidence_sha256"],
        "source_snapshot_ref": str(release["source_snapshot"]),
        "source_snapshot_sha256": release["source_snapshot_sha256"],
        "provider_readback_ref": str(release["provider_readback"]),
        "provider_readback_sha256": release["provider_readback_sha256"],
        "pull_request_identity": release["pull_request_identity"],
    }
    recorded_release = (
        original.get("release_propagation")
        if isinstance(original.get("release_propagation"), Mapping)
        else {}
    )
    if not (
        dict(recorded_release) == expected_release
        and original.get("stage_receipts_sha256")
        == _json_sha256(current.get("stage_receipts") or {})
    ):
        raise DevelopmentDeliveryError(
            "active pr_create escalation immutable release_propagation identity changed before replay"
        )


def _revalidate_active_pr_create_escalation_projection(
    current: Mapping[str, Any],
    *,
    state_path: Path,
    original: Mapping[str, Any],
) -> None:
    """Accept only the immutable original or exact derived fresh-authority view."""

    work_item = Path(str(current.get("work_item") or "")).expanduser().resolve()
    autodev_path, autodev_bytes = _active_pr_create_escalation_packet_file(
        current.get("autodev_path"), work_item=work_item, label="Auto-Dev projection"
    )
    expected_original_sha256 = str(original.get("autodev_sha256") or "").lower()
    if not (
        original.get("autodev_ref") == str(autodev_path)
        and re.fullmatch(r"[a-f0-9]{64}", expected_original_sha256)
    ):
        raise DevelopmentDeliveryError(
            "active pr_create escalation original Auto-Dev projection identity is malformed"
        )
    if hashlib.sha256(autodev_bytes).hexdigest() == expected_original_sha256:
        return

    projection = _active_pr_create_escalation_mapping(
        autodev_bytes, label="Auto-Dev projection"
    )
    delivery = (
        projection.get("delivery") if isinstance(projection.get("delivery"), Mapping) else {}
    )
    stages = projection.get("stages") if isinstance(projection.get("stages"), Mapping) else {}
    stage_order = current.get("auto_dev_stage_order")
    if not isinstance(stage_order, list) or "pr_create" not in stage_order:
        raise DevelopmentDeliveryError(
            "active pr_create escalation task stage order is not replayable"
        )
    pre_pr_stages = stage_order[: stage_order.index("pr_create") + 1]
    fresh_stages = ("review_self", "review_others", "qa", "finalize", "merge")
    projected_known_derived = (
        projection.get("schema") == "auto-dev-work-item/v1"
        and projection.get("mode") == "everything"
        and projection.get("requested_stage") is None
        and projection.get("start_stage") == "groom"
        and projection.get("completion_stage") == "merge"
        and projection.get("current_stage") == "review_self"
        and projection.get("stage_order") == stage_order
        and projection.get("stage_policies") == current.get("auto_dev_stage_policies")
        and projection.get("canonical_work_id") == current.get("canonical_work_id")
        and projection.get("domain") == current.get("domain")
        and projection.get("project") == current.get("project")
        and projection.get("subject_revision") is None
        and projection.get("terminal_revision") is None
        and delivery.get("state") == "local_validation"
        and delivery.get("goal") == "merge"
        and delivery.get("run_id") == current.get("run_id")
        and Path(str(delivery.get("task_state_ref") or "")).expanduser().resolve()
        == state_path
        and Path(str(delivery.get("work_item") or "")).expanduser().resolve()
        == work_item
        and delivery.get("canonical_work_id") == current.get("canonical_work_id")
        and all(
            isinstance(stages.get(stage), Mapping)
            and stages[stage].get("status") in {"completed", "not_required"}
            and isinstance(stages[stage].get("receipt_refs"), list)
            and stages[stage].get("receipt_refs")
            for stage in pre_pr_stages
        )
        and all(
            isinstance(stages.get(stage), Mapping)
            and stages[stage].get("status") == "not_started"
            and stages[stage].get("receipt_refs") == []
            for stage in fresh_stages
        )
        and all(
            isinstance(stages.get(stage), Mapping)
            and stages[stage].get("status") == "out_of_scope"
            and stages[stage].get("receipt_refs") == []
            for stage in ("release", "deploy", "closeout", "health")
        )
    )
    if not projected_known_derived:
        raise DevelopmentDeliveryError(
            "active pr_create escalation Auto-Dev projection changed before replay"
        )


def _complete_active_pr_create_delivery_escalation(
    state_path: Path,
    *,
    current: Mapping[str, Any],
    escalation: Mapping[str, Any],
    apply: bool,
) -> dict[str, Any]:
    """Complete only the derived state of a receipt-backed exact replay."""

    work_item = Path(str(current.get("work_item") or "")).expanduser().resolve()
    try:
        receipt_path, receipt_bytes = _active_pr_create_escalation_packet_file(
            escalation.get("receipt"),
            work_item=work_item,
            label="escalation receipt",
        )
    except DevelopmentDeliveryError as exc:
        raise DevelopmentDeliveryError("active pr_create escalation receipt is missing") from exc
    receipt = _active_pr_create_escalation_mapping(
        receipt_bytes, label="escalation receipt"
    )
    if not (
        receipt.get("schema") == ACTIVE_PR_CREATE_DELIVERY_ESCALATION_SCHEMA
        and receipt.get("kind") == "escalate-active-nonblocked-pr-create-delivery"
        and receipt.get("idempotency_key") == escalation.get("idempotency_key")
        and _json_sha256(receipt) == escalation.get("sha256")
    ):
        raise DevelopmentDeliveryError(
            "active pr_create escalation receipt identity does not match task state"
        )
    escalated = receipt.get("escalated") if isinstance(receipt.get("escalated"), Mapping) else {}
    expected_portfolio_auto_dev = escalated.get("portfolio_auto_dev")
    if not (
        escalated.get("state") == "local_validation"
        and escalated.get("mode") == "everything"
        and escalated.get("requested_stage") is None
        and escalated.get("goal") == "merge"
        and escalated.get("start_stage") == "groom"
        and escalated.get("completion_stage") == "merge"
        and isinstance(escalated.get("stage_order"), list)
        and isinstance(escalated.get("stage_policies"), Mapping)
        and isinstance(expected_portfolio_auto_dev, Mapping)
        and current.get("state") == "local_validation"
        and current.get("failure") is None
        and current.get("auto_dev_mode") == "everything"
        and current.get("requested_stage") is None
        and current.get("goal") == "merge"
        and current.get("auto_dev_start_stage") == "groom"
        and current.get("auto_dev_completion_stage") == "merge"
        and current.get("auto_dev_stage_order") == escalated.get("stage_order")
        and current.get("auto_dev_stage_policies") == escalated.get("stage_policies")
    ):
        raise DevelopmentDeliveryError(
            "active pr_create escalation task state is not replayable"
        )
    matching_rows = [
        row
        for row in current.get("active_pr_create_delivery_escalations") or []
        if isinstance(row, Mapping)
        and row.get("idempotency_key") == escalation.get("idempotency_key")
    ]
    if len(matching_rows) != 1 or dict(matching_rows[0]) != dict(escalation):
        raise DevelopmentDeliveryError(
            "active pr_create escalation history is not replayable"
        )
    original = receipt.get("original") if isinstance(receipt.get("original"), Mapping) else {}
    _revalidate_active_pr_create_escalation_release(
        current, state_path=state_path, original=original
    )
    _revalidate_active_pr_create_escalation_projection(
        current, state_path=state_path, original=original
    )
    if not apply:
        return receipt

    run_dir = state_path.parent.parent.parent.resolve()
    root = expand_path(str(current.get("os_root") or ""))
    canonical = _read_canonical_development_work(
        root,
        canonical_work_id=str(current.get("canonical_work_id") or ""),
        ticket=str(current.get("ticket") or ""),
        packet=work_item,
        diagnostic_root=run_dir,
    )
    if not isinstance(canonical, Mapping) or _json_sha256(dict(canonical)) != original.get(
        "canonical_sha256"
    ):
        raise DevelopmentDeliveryError(
            "canonical work row changed during active pr_create escalation; rerun preflight"
        )
    portfolio_path = run_dir / "portfolio.json"
    with _file_lock(portfolio_path.with_suffix(portfolio_path.suffix + ".lock")):
        _, portfolio_bytes = _active_pr_create_escalation_regular_file(
            portfolio_path, label="portfolio"
        )
        portfolio = _active_pr_create_escalation_mapping(portfolio_bytes, label="portfolio")
        rows = portfolio.get("tasks") if isinstance(portfolio.get("tasks"), list) else []
        if not (
            portfolio.get("run_id") == current.get("run_id")
            and portfolio.get("tickets") == [current.get("ticket")]
            and len(rows) == 1
            and isinstance(rows[0], Mapping)
            and Path(str(rows[0].get("state_ref") or "")).expanduser().resolve()
            == state_path
            and rows[0].get("canonical_work_id") == current.get("canonical_work_id")
        ):
            raise DevelopmentDeliveryError(
                "portfolio changed during active pr_create escalation; rerun preflight"
            )
        expected_row = {**dict(escalation), "task_state_ref": str(state_path)}
        recorded_rows = [
            row
            for row in portfolio.get("active_pr_create_delivery_escalations") or []
            if isinstance(row, Mapping)
            and row.get("idempotency_key") == escalation.get("idempotency_key")
        ]
        if len(recorded_rows) > 1 or (
            recorded_rows and dict(recorded_rows[0]) != expected_row
        ):
            raise DevelopmentDeliveryError(
                "active pr_create escalation portfolio history is not replayable"
            )
        changed = False
        if portfolio.get("auto_dev") != expected_portfolio_auto_dev:
            if (
                original.get("portfolio_ref") != str(portfolio_path)
                or original.get("portfolio_sha256")
                != hashlib.sha256(portfolio_bytes).hexdigest()
                or recorded_rows
            ):
                raise DevelopmentDeliveryError(
                    "active pr_create escalation refuses a portfolio that is not its exact escalated projection"
                )
            portfolio["auto_dev"] = dict(expected_portfolio_auto_dev)
            changed = True
        if not recorded_rows:
            portfolio.setdefault("active_pr_create_delivery_escalations", []).append(
                expected_row
            )
            changed = True
        if changed:
            portfolio["updated_at"] = utc_now()
            _atomic_json(portfolio_path, portfolio)

    projection = _sync_auto_dev_projection(state_path)
    if not (
        isinstance(projection, Mapping)
        and projection.get("mode") == "everything"
        and projection.get("requested_stage") is None
        and projection.get("start_stage") == "groom"
        and projection.get("completion_stage") == "merge"
        and projection.get("current_stage") == "review_self"
        and projection.get("delivery", {}).get("state") == "local_validation"
        and projection.get("stages", {}).get("pr_create", {}).get("status") == "completed"
        and all(
            projection.get("stages", {}).get(stage, {}).get("status") == "not_started"
            for stage in ("review_self", "review_others", "qa", "finalize", "merge")
        )
    ):
        raise DevelopmentDeliveryError(
            "active pr_create escalation could not refresh its fresh-authority Auto-Dev projection"
        )
    TaskState(state_path).emit(
        event_type="development.task.active_pr_create_delivery_escalated",
        idempotency_key=str(escalation["idempotency_key"]),
        payload={
            "ticket": current.get("ticket"),
            "receipt": str(receipt_path),
            "next_action": "record fresh review_self, review_others, qa, finalize, and merge evidence",
        },
    )
    return receipt


def escalate_active_nonblocked_pr_create_delivery(
    state_file: str | Path,
    *,
    reason: str,
    idempotency_key: str,
    apply: bool = False,
) -> dict[str, Any]:
    """Escalate only AGE-190's immutable nonblocked PR Create boundary.

    This is a receipt-backed migration rather than a stage override.  It keeps
    the original PR identity unchanged and never creates a provider action.
    Fresh Review Self, Review Others, QA, Finalize, and Merge evidence remain
    mandatory after the new boundary is installed.
    """

    state_path = Path(state_file).expanduser().resolve()
    normalized_reason = reason.strip()
    normalized_key = idempotency_key.strip()
    if not normalized_reason:
        raise DevelopmentDeliveryError("active pr_create escalation requires a reason")
    if not normalized_key:
        raise DevelopmentDeliveryError(
            "active pr_create escalation requires an idempotency key"
        )
    state = TaskState(state_path)
    with _task_provisioning_admission_lock(state_path):
        current = state.read()
        escalations = current.get("active_pr_create_delivery_escalations")
        if isinstance(escalations, list):
            for escalation in escalations:
                if not isinstance(escalation, Mapping) or escalation.get(
                    "idempotency_key"
                ) != normalized_key:
                    continue
                if escalation.get("reason") != normalized_reason:
                    raise DevelopmentDeliveryError(
                        "idempotency key belongs to a different active pr_create escalation"
                    )
                _complete_active_pr_create_delivery_escalation(
                    state_path,
                    current=current,
                    escalation=escalation,
                    apply=apply,
                )
                return {
                    "schema": "active-pr-create-delivery-escalation-result/v1",
                    "result": "replayed",
                    "state": str(state_path),
                    "ticket": current.get("ticket"),
                    "receipt": str(escalation["receipt"]),
                    "receipt_sha256": str(escalation["sha256"]),
                    "next_action": "record fresh review_self, review_others, qa, finalize, and merge evidence",
                }
        context = _active_pr_create_delivery_escalation_context(state_path)
        receipt = {
            "schema": ACTIVE_PR_CREATE_DELIVERY_ESCALATION_SCHEMA,
            "kind": "escalate-active-nonblocked-pr-create-delivery",
            "idempotency_key": normalized_key,
            "reason": normalized_reason,
            "recorded_at": utc_now(),
            "original": {
                "task_state_ref": str(state_path),
                "task_state_sha256": context["task_sha256"],
                "portfolio_ref": str(context["portfolio_path"]),
                "portfolio_sha256": context["portfolio_sha256"],
                "autodev_ref": str(context["autodev_path"]),
                "autodev_sha256": context["autodev_sha256"],
                "canonical_work_id": context["task"]["canonical_work_id"],
                "canonical_sha256": context["canonical_sha256"],
                "work_item": str(context["work_item"]),
                "worktree": context["worktree"],
                "release_propagation": {
                    "wrapper_ref": str(context["release"]["wrapper"]),
                    "wrapper_sha256": context["release"]["wrapper_sha256"],
                    "evidence_ref": str(context["release"]["evidence"]),
                    "evidence_sha256": context["release"]["evidence_sha256"],
                    "source_snapshot_ref": str(
                        context["release"]["source_snapshot"]
                    ),
                    "source_snapshot_sha256": context["release"][
                        "source_snapshot_sha256"
                    ],
                    "provider_readback_ref": str(
                        context["release"]["provider_readback"]
                    ),
                    "provider_readback_sha256": context["release"][
                        "provider_readback_sha256"
                    ],
                    "pull_request_identity": context["release"]["pull_request_identity"],
                },
                "stage_receipts_sha256": _json_sha256(
                    context["task"].get("stage_receipts") or {}
                ),
            },
            "escalated": {
                "state": "local_validation",
                "mode": "everything",
                "requested_stage": None,
                "goal": "merge",
                "stage_order": context["stage_order"],
                "start_stage": "groom",
                "completion_stage": "merge",
                "stage_policies": context["stage_policies"],
                "portfolio_auto_dev": context["escalated_portfolio_auto_dev"],
                "fresh_stages_required": list(_ACTIVE_WORKTREE_READY_DELIVERY_FRESH_STAGES),
            },
        }
        digest = _json_sha256(receipt)
        receipt_path = (
            context["work_item"]
            / "artifacts"
            / "development-delivery"
            / "active-pr-create-delivery-escalation"
            / f"{digest}.json"
        )
        result = {
            "schema": "active-pr-create-delivery-escalation-result/v1",
            "result": "planned" if not apply else "escalated",
            "state": str(state_path),
            "ticket": current.get("ticket"),
            "receipt": str(receipt_path),
            "receipt_sha256": digest,
            "next_action": "record fresh review_self, review_others, qa, finalize, and merge evidence",
        }
        if not apply:
            return result
        portfolio_path = context["portfolio_path"]
        with _file_lock(portfolio_path.with_suffix(portfolio_path.suffix + ".lock")):
            locked_context = _active_pr_create_delivery_escalation_context(state_path)
            if not (
                locked_context["task_sha256"] == context["task_sha256"]
                and locked_context["portfolio_sha256"] == context["portfolio_sha256"]
                and locked_context["autodev_sha256"] == context["autodev_sha256"]
                and locked_context["canonical_sha256"] == context["canonical_sha256"]
            ):
                raise DevelopmentDeliveryError(
                    "portfolio, task, projection, or canonical row changed during active pr_create escalation; rerun preflight"
                )
            with _file_lock(state_path.with_suffix(state_path.suffix + ".lock")):
                latest = state.read()
                if hashlib.sha256(state_path.read_bytes()).hexdigest() != context[
                    "task_sha256"
                ]:
                    raise DevelopmentDeliveryError(
                        "task changed during active pr_create escalation; rerun preflight"
                    )
                encoded_receipt = (
                    json.dumps(receipt, indent=2, sort_keys=True) + "\n"
                ).encode("utf-8")
                if receipt_path.exists() or receipt_path.is_symlink():
                    _, existing_receipt = _active_pr_create_escalation_packet_file(
                        receipt_path,
                        work_item=context["work_item"],
                        label="escalation receipt",
                    )
                    if existing_receipt != encoded_receipt:
                        raise DevelopmentDeliveryError(
                            "active pr_create escalation receipt path already has different content"
                        )
                _atomic_json(receipt_path, receipt)
                escalation = {
                    "idempotency_key": normalized_key,
                    "reason": normalized_reason,
                    "receipt": str(receipt_path),
                    "sha256": digest,
                    "recorded_at": receipt["recorded_at"],
                }
                latest.update(
                    {
                        "auto_dev_mode": "everything",
                        "requested_stage": None,
                        "goal": "merge",
                        "auto_dev_stage_order": context["stage_order"],
                        "auto_dev_start_stage": "groom",
                        "auto_dev_completion_stage": "merge",
                        "auto_dev_stage_policies": context["stage_policies"],
                        "updated_at": utc_now(),
                        "last_active_pr_create_delivery_escalation_key": normalized_key,
                    }
                )
                latest.setdefault("active_pr_create_delivery_escalations", []).append(
                    escalation
                )
                latest.setdefault("receipts", []).append(
                    {
                        "state": "local_validation",
                        "ref": str(receipt_path),
                        "sha256": digest,
                        "recorded_at": receipt["recorded_at"],
                    }
                )
                _atomic_json(state_path, latest)
            locked_portfolio = _read_mapping(portfolio_path)
            locked_portfolio["auto_dev"] = dict(context["escalated_portfolio_auto_dev"])
            locked_portfolio.setdefault("active_pr_create_delivery_escalations", []).append(
                {**escalation, "task_state_ref": str(state_path)}
            )
            locked_portfolio["updated_at"] = utc_now()
            _atomic_json(portfolio_path, locked_portfolio)
        _complete_active_pr_create_delivery_escalation(
            state_path,
            current=latest,
            escalation=escalation,
            apply=True,
        )
        return result


def _is_retryable_origin_main_provisioning_failure(task: Mapping[str, Any]) -> bool:
    """Return whether a task carries the narrowly recognized legacy failure."""

    failure = task.get("failure") if isinstance(task.get("failure"), Mapping) else {}
    detail = str(failure.get("detail") or "").lower()
    return bool(
        task.get("state") == "work_item_ready"
        and failure.get("kind") == "provisioning_failed"
        and failure.get("recoverable") is True
        and failure.get("retry_state") == "work_item_ready"
        and "origin/main" in detail
        and "remote ref" in detail
    )


def _base_selection_correction_context(
    state_path: Path,
    *,
    corrected_base_branch: str,
    runner: Any,
) -> dict[str, Any]:
    """Prove an old invalid-base failure is still safe to correct.

    This is deliberately narrower than normal recovery.  It recognizes only
    the historical ``origin/main`` provisioning failure, and every check here
    runs before the correction receipt or either mutable selection is changed.
    """

    task = TaskState(state_path).read()
    requested = corrected_base_branch.strip()
    if requested != "main":
        raise DevelopmentDeliveryError(
            "base-selection correction only permits the verified branch 'main'"
        )
    failure = task.get("failure") if isinstance(task.get("failure"), Mapping) else {}
    if not _is_retryable_origin_main_provisioning_failure(task):
        raise DevelopmentDeliveryError(
            "base-selection correction requires the exact retryable origin/main provisioning failure"
        )
    if task.get("worktree") or task.get("runtime"):
        raise DevelopmentDeliveryError(
            "base-selection correction is forbidden after a worktree or runtime effect"
        )
    repository = task.get("repository") if isinstance(task.get("repository"), Mapping) else {}
    if repository.get("base_branch") != "origin/main":
        raise DevelopmentDeliveryError(
            "base-selection correction requires the recorded base branch origin/main"
        )
    os_root = str(task.get("os_root") or "").strip()
    domain = str(task.get("domain") or "").strip()
    project = str(task.get("project") or "").strip()
    title = str(task.get("title") or "").strip()
    ticket = str(task.get("ticket") or "").strip()
    work_item_raw = str(task.get("work_item") or "").strip()
    if not all((os_root, domain, project, title, ticket, work_item_raw)):
        raise DevelopmentDeliveryError(
            "base-selection correction requires a fully linked pre-worktree delivery task"
        )
    project_path = project_root(os_root, domain, project)
    work_item = Path(work_item_raw).expanduser().resolve()
    try:
        work_item.relative_to((project_path / "work-items").resolve())
    except ValueError as exc:
        raise DevelopmentDeliveryError(
            "base-selection correction work item is outside the owning project"
        ) from exc
    if not work_item.is_dir():
        raise DevelopmentDeliveryError("base-selection correction work item is missing")
    run_dir = state_path.parent.parent.parent
    portfolio_path = run_dir / "portfolio.json"
    portfolio = _read_mapping(portfolio_path)
    portfolio_repository = (
        portfolio.get("repository") if isinstance(portfolio.get("repository"), Mapping) else {}
    )
    if portfolio_repository != repository:
        raise DevelopmentDeliveryError(
            "base-selection correction requires matching task and portfolio selections"
        )
    profile, _ = load_development_profile(os_root, domain, project)
    configured_repository = (
        profile.get("repository") if isinstance(profile.get("repository"), Mapping) else {}
    )
    if configured_repository.get("base_branch") != "main":
        raise DevelopmentDeliveryError(
            "base-selection correction requires the current project base branch to be main"
        )
    repo = expand_path(str(repository.get("root") or ""))
    configured_root = expand_path(str(configured_repository.get("root") or ""))
    if not repo.is_dir() or repo.resolve() != configured_root.resolve():
        raise DevelopmentDeliveryError(
            "base-selection correction repository does not match the current project profile"
        )
    branch = _task_branch(
        str(profile["worktrees"].get("branch_template") or "feature/{ticket}-{slug}"),
        ticket,
        _slug(title),
    )
    worktrees = runner(["git", "-C", str(repo), "worktree", "list", "--porcelain"])
    if worktrees.returncode != 0:
        raise DevelopmentDeliveryError(
            (worktrees.stderr or worktrees.stdout or "git worktree inspection failed").strip()
        )
    if f"branch refs/heads/{branch}" in worktrees.stdout:
        raise DevelopmentDeliveryError(
            "base-selection correction is forbidden after the task worktree exists"
        )
    local_branch = runner(
        ["git", "-C", str(repo), "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"]
    )
    if local_branch.returncode == 0:
        raise DevelopmentDeliveryError(
            "base-selection correction is forbidden after a task source branch exists"
        )
    if local_branch.returncode not in {0, 1}:
        raise DevelopmentDeliveryError("cannot prove the task source branch is absent")
    remote_branch = runner(["git", "-C", str(repo), "ls-remote", "--heads", "origin", branch])
    if remote_branch.returncode != 0:
        raise DevelopmentDeliveryError(
            (remote_branch.stderr or remote_branch.stdout or "cannot inspect origin task branch").strip()
        )
    if remote_branch.stdout.strip():
        raise DevelopmentDeliveryError(
            "base-selection correction is forbidden after a provider task branch exists"
        )
    fetched = runner(["git", "-C", str(repo), "fetch", "origin", "main"])
    if fetched.returncode != 0:
        raise DevelopmentDeliveryError(
            (fetched.stderr or fetched.stdout or "cannot verify origin/main").strip()
        )
    resolved = runner(["git", "-C", str(repo), "rev-parse", "origin/main"])
    base_sha = resolved.stdout.strip()
    if resolved.returncode != 0 or not re.fullmatch(r"[a-fA-F0-9]{7,64}", base_sha):
        raise DevelopmentDeliveryError("cannot prove the corrected origin/main revision")
    return {
        "task": task,
        "failure": dict(failure),
        "repository": dict(repository),
        "portfolio": portfolio,
        "portfolio_path": portfolio_path,
        "work_item": work_item,
        "run_dir": run_dir,
        "branch": branch,
        "base_sha": base_sha,
        "corrected_repository": {**dict(repository), "base_branch": "main"},
    }


def _complete_base_selection_correction(
    state_path: Path,
    *,
    current: Mapping[str, Any],
    correction: Mapping[str, Any],
    apply: bool,
) -> dict[str, Any]:
    """Validate an immutable correction receipt and finish its idempotent effects.

    A process can fail after task state is corrected but before the portfolio,
    event, or Auto-Dev projection is updated.  The task row therefore is not a
    completion marker by itself: replay verifies the immutable receipt and
    completes each remaining derived effect.
    """

    receipt_path = Path(str(correction.get("receipt") or "")).expanduser()
    if not receipt_path.is_file():
        raise DevelopmentDeliveryError("base-selection correction receipt is missing")
    receipt = _read_mapping(receipt_path)
    digest = str(correction.get("sha256") or "")
    if not digest or _json_sha256(receipt) != digest:
        raise DevelopmentDeliveryError("base-selection correction receipt digest does not match task state")
    if (
        receipt.get("schema") != "development-base-selection-correction/v1"
        or receipt.get("kind") != "retryable-pre-worktree-base-selection-correction"
        or receipt.get("idempotency_key") != correction.get("idempotency_key")
    ):
        raise DevelopmentDeliveryError("base-selection correction receipt identity does not match task state")
    original = receipt.get("original") if isinstance(receipt.get("original"), Mapping) else {}
    corrected = receipt.get("corrected") if isinstance(receipt.get("corrected"), Mapping) else {}
    original_repository = (
        original.get("repository") if isinstance(original.get("repository"), Mapping) else {}
    )
    corrected_repository = (
        corrected.get("repository") if isinstance(corrected.get("repository"), Mapping) else {}
    )
    if (
        not original_repository
        or original_repository.get("base_branch") != "origin/main"
        or not corrected_repository
        or corrected_repository.get("base_branch") != "main"
        or current.get("repository") != corrected_repository
        or correction.get("from_base_branch") != "origin/main"
        or correction.get("to_base_branch") != "main"
    ):
        raise DevelopmentDeliveryError("base-selection correction receipt content does not match corrected task state")
    matching_rows = [
        row
        for row in current.get("base_selection_corrections") or []
        if isinstance(row, Mapping) and row.get("idempotency_key") == correction.get("idempotency_key")
    ]
    if len(matching_rows) != 1 or dict(matching_rows[0]) != dict(correction):
        raise DevelopmentDeliveryError("base-selection correction task history is not replayable")
    if not apply:
        return receipt

    run_dir = state_path.parent.parent.parent
    portfolio_path = run_dir / "portfolio.json"
    with _file_lock(portfolio_path.with_suffix(portfolio_path.suffix + ".lock")):
        portfolio = _read_mapping(portfolio_path)
        portfolio_repository = portfolio.get("repository")
        if portfolio_repository not in (original_repository, corrected_repository):
            raise DevelopmentDeliveryError(
                "portfolio changed during base-selection correction; manual reconciliation required"
            )
        portfolio_rows = [
            row
            for row in portfolio.get("base_selection_corrections") or []
            if isinstance(row, Mapping) and row.get("idempotency_key") == correction.get("idempotency_key")
        ]
        expected_portfolio_row = {**dict(correction), "task_state_ref": str(state_path)}
        if len(portfolio_rows) > 1 or (portfolio_rows and dict(portfolio_rows[0]) != expected_portfolio_row):
            raise DevelopmentDeliveryError("portfolio base-selection correction history is not replayable")
        changed = portfolio_repository != corrected_repository or not portfolio_rows
        if changed:
            portfolio["repository"] = dict(corrected_repository)
            if not portfolio_rows:
                portfolio.setdefault("base_selection_corrections", []).append(expected_portfolio_row)
            portfolio["updated_at"] = utc_now()
            _atomic_json(portfolio_path, portfolio)

    state = TaskState(state_path)
    state.emit(
        event_type="development.task.base_selection_corrected",
        idempotency_key=str(correction["idempotency_key"]),
        payload={
            "ticket": current.get("ticket"),
            "from_base_branch": "origin/main",
            "to_base_branch": "main",
            "base_sha": corrected.get("base_sha"),
            "receipt": str(receipt_path),
        },
    )
    _sync_auto_dev_projection(state_path)
    _refresh_portfolio_state(state_path)
    return receipt


def _has_valid_base_selection_correction(
    state_path: Path,
    *,
    current: Mapping[str, Any],
    apply: bool,
) -> bool:
    """Prove a legacy failure has a completed, immutable correction boundary."""

    candidates = [
        row
        for row in current.get("base_selection_corrections") or []
        if isinstance(row, Mapping)
        and row.get("from_base_branch") == "origin/main"
        and row.get("to_base_branch") == "main"
    ]
    if not candidates:
        return False
    if len(candidates) != 1:
        raise DevelopmentDeliveryError("historical base-selection correction has ambiguous task history")
    _complete_base_selection_correction(
        state_path,
        current=current,
        correction=candidates[0],
        apply=apply,
    )
    return True


def correct_failed_base_selection(
    state_file: str | Path,
    *,
    corrected_base_branch: str,
    idempotency_key: str,
    apply: bool = False,
    runner: Any = _run_command,
) -> dict[str, Any]:
    """Correct one historical pre-worktree ``origin/main`` failure safely.

    The immutable receipt snapshots the original failure before normal resume
    clears it.  This operation never creates a worktree, source branch, or
    provider branch; the caller must resume Auto-Dev separately after apply.
    """

    state_path = Path(state_file).expanduser().resolve()
    if not idempotency_key.strip():
        raise DevelopmentDeliveryError("base-selection correction requires an idempotency key")
    state = TaskState(state_path)
    with _task_provisioning_admission_lock(state_path):
        current = state.read()
        corrections = current.get("base_selection_corrections")
        if isinstance(corrections, list):
            for correction in corrections:
                if not isinstance(correction, Mapping) or correction.get("idempotency_key") != idempotency_key:
                    continue
                if correction.get("to_base_branch") != corrected_base_branch.strip():
                    raise DevelopmentDeliveryError("idempotency key belongs to a different base-selection correction")
                receipt = _complete_base_selection_correction(
                    state_path,
                    current=current,
                    correction=correction,
                    apply=apply,
                )
                return {
                    "schema": "development-base-selection-correction-result/v1",
                    "result": "replayed",
                    "state": str(state_path),
                    "ticket": current.get("ticket"),
                    "correction": dict(correction),
                    "receipt": str(correction["receipt"]),
                    "receipt_sha256": str(correction["sha256"]),
                    "corrected_base_branch": "main",
                    "base_sha": (receipt.get("corrected") or {}).get("base_sha"),
                    "next_action": "resume the same Auto-Dev run after this receipt is recorded",
                }
        context = _base_selection_correction_context(
            state_path,
            corrected_base_branch=corrected_base_branch,
            runner=runner,
        )
        original_state_sha256 = hashlib.sha256(state_path.read_bytes()).hexdigest()
        original_failure = context["failure"]
        original_failure_sha256 = _json_sha256(original_failure)
        receipt = {
            "schema": "development-base-selection-correction/v1",
            "kind": "retryable-pre-worktree-base-selection-correction",
            "idempotency_key": idempotency_key,
            "run_id": context["task"].get("run_id"),
            "ticket": context["task"].get("ticket"),
            "recorded_at": utc_now(),
            "original": {
                "repository": context["repository"],
                "failure": original_failure,
                "failure_sha256": original_failure_sha256,
                "task_state_ref": str(state_path),
                "task_state_sha256_before_correction": original_state_sha256,
            },
            "corrected": {
                "repository": context["corrected_repository"],
                "verified_remote_ref": "origin/main",
                "base_sha": context["base_sha"],
            },
            "preflight": {
                "task_branch": context["branch"],
                "no_worktree_or_runtime_effect": True,
                "no_local_task_branch": True,
                "no_provider_task_branch": True,
            },
        }
        digest = _json_sha256(receipt)
        receipt_path = (
            context["work_item"]
            / "artifacts"
            / "development-delivery"
            / "base-selection-corrections"
            / f"{digest}.json"
        )
        result = {
            "schema": "development-base-selection-correction-result/v1",
            "result": "planned" if not apply else "corrected",
            "state": str(state_path),
            "ticket": context["task"].get("ticket"),
            "receipt": str(receipt_path),
            "receipt_sha256": digest,
            "corrected_base_branch": "main",
            "base_sha": context["base_sha"],
            "next_action": "resume the same Auto-Dev run after this receipt is recorded",
        }
        if not apply:
            return result
        with _file_lock(state_path.with_suffix(state_path.suffix + ".lock")):
            latest = state.read()
            if latest.get("updated_at") != context["task"].get("updated_at"):
                raise DevelopmentDeliveryError("task changed during base-selection correction; rerun preflight")
            _atomic_json(receipt_path, receipt)
            latest["repository"] = context["corrected_repository"]
            correction_row = {
                "idempotency_key": idempotency_key,
                "from_base_branch": "origin/main",
                "to_base_branch": "main",
                "receipt": str(receipt_path),
                "sha256": digest,
                "recorded_at": receipt["recorded_at"],
            }
            latest.setdefault("base_selection_corrections", []).append(correction_row)
            latest.setdefault("receipts", []).append(
                {"state": latest["state"], "ref": str(receipt_path), "sha256": digest, "recorded_at": receipt["recorded_at"]}
            )
            latest["updated_at"] = utc_now()
            latest["last_base_selection_correction_key"] = idempotency_key
            _atomic_json(state_path, latest)
        _complete_base_selection_correction(
            state_path,
            current=latest,
            correction=correction_row,
            apply=True,
        )
        return result


def _adopt_registered_worktree(
    *,
    os_root: str | Path,
    domain: str,
    project: str,
    profile: Mapping[str, Any],
    canonical_row: Mapping[str, Any],
    runner: Any = _run_command,
) -> dict[str, Any] | None:
    """Attach only the exact canonical and project-registered existing worktree."""

    raw_path = str(canonical_row.get("worktree_path") or "").strip()
    if not raw_path:
        return None
    raw = Path(raw_path).expanduser()
    if not raw.is_absolute():
        raw = Path(os_root).expanduser() / raw
    path = raw.resolve()
    project_path = project_root(os_root, domain, project)
    storage_root = project_worktree_root(
        project_path, {"worktrees": dict(profile["worktrees"])}
    ).resolve()
    link_boundary = (project_path / "worktrees").resolve()
    active_entries = [
        row
        for row in worktree_entries_for_project(project_path)
        if str(row.get("status") or "active") == "active"
    ]

    def registered_target(row: Mapping[str, Any]) -> Path | None:
        value = str(row.get("path") or "").strip()
        if not value:
            return None
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = project_path / candidate
        return candidate.resolve()

    def registry_identity(row: Mapping[str, Any]) -> str:
        return str(row.get("id") or row.get("name") or "").strip()

    matches = [
        row
        for row in active_entries
        if registry_identity(row)
        and str(row.get("path") or "").strip()
        and registered_target(row) == path
    ]
    if not matches:
        raise DevelopmentDeliveryError("adopted worktree is not present in the active project registry")
    names = {registry_identity(row) for row in matches}
    if len(names) != 1:
        raise DevelopmentDeliveryError("adopted worktree has conflicting registry identities")
    name = names.pop()
    identity_rows = [
        row
        for row in active_entries
        if registry_identity(row) == name
    ]
    if any(registered_target(row) != path for row in identity_rows):
        raise DevelopmentDeliveryError("adopted worktree has conflicting registry targets")

    in_place = (
        storage_root == link_boundary
        and (link_boundary == path.parent or link_boundary in path.parents)
    )
    external = not in_place
    registered_links: set[Path] = set()
    for row in identity_rows:
        raw_link = str(row.get("link") or "").strip()
        link = Path(raw_link).expanduser() if raw_link else link_boundary / name
        if raw_link and not link.is_absolute():
            link = project_path / link
        link_parent = link.parent.resolve()
        if link_parent != link_boundary and link_boundary not in link_parent.parents:
            raise DevelopmentDeliveryError(
                "adopted worktree registry link is outside the visible project worktrees boundary"
            )
        registered_links.add(link)
        if not link.exists() and not link.is_symlink():
            raise DevelopmentDeliveryError("adopted worktree registry link is missing")
        if link.resolve() != path:
            raise DevelopmentDeliveryError(
                "adopted worktree registry link does not resolve to its registered target"
            )
        policy = str(row.get("link_policy") or "").strip()
        if external and (policy != "symlink_to_external_worktree" or not link.is_symlink()):
            raise DevelopmentDeliveryError(
                "adopted external worktree is not registered through the external symlink policy"
            )
        if not external and policy == "symlink_to_external_worktree":
            raise DevelopmentDeliveryError(
                "adopted worktree registry policy does not match its target"
            )
    if len(registered_links) != 1:
        raise DevelopmentDeliveryError("adopted worktree has conflicting registry links")

    canonical_branch = str(canonical_row.get("branch") or "").strip()
    registered_branches = {
        str(row.get("branch") or "").strip() for row in identity_rows if row.get("branch")
    }
    if len(registered_branches) > 1:
        raise DevelopmentDeliveryError("adopted worktree has conflicting registered branches")
    actual = runner(["git", "-C", str(path), "branch", "--show-current"])
    actual_branch = actual.stdout.strip() if actual.returncode == 0 else ""
    if not actual_branch or (canonical_branch and actual_branch != canonical_branch) or (
        registered_branches and actual_branch not in registered_branches
    ):
        raise DevelopmentDeliveryError("adopted worktree branch does not match canonical registration")
    repository = profile["repository"]
    repo = expand_path(str(repository["root"]))
    base = str(repository["base_branch"])
    registered_bases = {
        str(row.get("base_branch") or "").strip()
        for row in identity_rows
        if row.get("base_branch")
    }
    if len(registered_bases) > 1 or (registered_bases and registered_bases != {base}):
        raise DevelopmentDeliveryError(
            "adopted worktree base branch does not match project registration"
        )
    registered = runner(["git", "-C", str(repo), "worktree", "list", "--porcelain"])
    registered_paths = {
        Path(line.removeprefix("worktree ")).expanduser().resolve()
        for line in registered.stdout.splitlines()
        if line.startswith("worktree ")
    }
    if registered.returncode != 0 or path not in registered_paths:
        raise DevelopmentDeliveryError("adopted worktree is not registered in Git worktree metadata")
    repo_top = runner(["git", "-C", str(repo), "rev-parse", "--show-toplevel"])
    worktree_top = runner(["git", "-C", str(path), "rev-parse", "--show-toplevel"])
    repo_common = runner(["git", "-C", str(repo), "rev-parse", "--git-common-dir"])
    worktree_common = runner(["git", "-C", str(path), "rev-parse", "--git-common-dir"])

    def resolved_git_path(cwd: Path, value: str) -> Path:
        candidate = Path(value.strip()).expanduser()
        if not candidate.is_absolute():
            candidate = cwd / candidate
        return candidate.resolve()

    if (
        repo_top.returncode != 0
        or worktree_top.returncode != 0
        or repo_common.returncode != 0
        or worktree_common.returncode != 0
        or Path(worktree_top.stdout.strip()).expanduser().resolve() != path
        or resolved_git_path(repo, repo_common.stdout)
        != resolved_git_path(path, worktree_common.stdout)
    ):
        raise DevelopmentDeliveryError(
            "adopted worktree repository does not match project registration"
        )
    merge_base = runner(["git", "-C", str(path), "merge-base", "HEAD", f"origin/{base}"])
    if merge_base.returncode != 0:
        merge_base = runner(["git", "-C", str(path), "merge-base", "HEAD", base])
    base_sha = merge_base.stdout.strip() if merge_base.returncode == 0 else ""
    if not re.fullmatch(r"[a-fA-F0-9]{7,64}", base_sha):
        raise DevelopmentDeliveryError("adopted worktree base revision could not be proven")
    return {
        "name": name,
        "path": str(path),
        "branch": actual_branch,
        "base_sha": base_sha,
        "repository_id": repository.get("id"),
        "resumed": True,
    }


def _write_task_state(
    path: Path,
    *,
    run_id: str,
    ticket: str,
    max_attempts: int,
    lease_minutes: int,
    rollup_ledger: Path | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    state = {
        "schema": "development-task/v1",
        "run_id": run_id,
        "ticket": ticket,
        "state": "discovered",
        "attempts": {},
        "max_attempts": max_attempts,
        "lease": {"owner": None, "until": (now + timedelta(minutes=lease_minutes)).isoformat().replace("+00:00", "Z")},
        "receipts": [],
        "failure": None,
        "rollup_ledger": str(rollup_ledger) if rollup_ledger else None,
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "updated_at": now.isoformat().replace("+00:00", "Z"),
    }
    _atomic_json(path, state)
    return state


def _record_post_materialization_handoff(
    task_state: TaskState,
    *,
    require_executor_handoff: bool,
) -> dict[str, Any] | None:
    """Record the exact no-executor boundary after a governed worktree exists."""

    if not require_executor_handoff:
        return None
    task = task_state.read()
    projection_path = Path(str(task.get("autodev_path") or "")).expanduser()
    projection = read_auto_dev_state(projection_path) if projection_path.is_file() else {}
    result = task_state.record_executor_unavailable(
        stage=str(projection.get("current_stage") or task.get("requested_stage") or "") or None
    )
    return {
        "schema": result["handoff"]["schema"],
        "status": result["handoff"]["status"],
        "outcome": result["handoff"]["outcome"],
        "receipt": result["task"]["failure"]["receipt"],
        "attempt": result["handoff"]["attempt"],
        "recoverable": result["handoff"]["recoverable"],
        "next_stage": result["handoff"]["next_stage"],
    }


def start_development_run(
    root: str | Path,
    domain: str,
    project: str,
    tickets: Sequence[str],
    *,
    titles: Mapping[str, str] | None = None,
    run_id: str | None = None,
    repository_id: str | None = None,
    base_branch: str | None = None,
    policy_overlays: Mapping[str, Sequence[str | Path]] | None = None,
    touched_paths: Sequence[str] = (),
    subjects: Sequence[str] = (),
    rulebook_ids: Sequence[str] = (),
    context_selection_override: Mapping[str, Any] | None = None,
    auto_dev_mode: str = "single_stage",
    requested_stage: str | None = None,
    goal: str | None = None,
    provision_worktree: bool = True,
    selected_work_item: str | Path | None = None,
    adopt_existing: bool = False,
    existing_state_only: bool = False,
    require_executor_handoff: bool = False,
    apply: bool = False,
) -> dict[str, Any]:
    if not tickets:
        raise DevelopmentDeliveryError("at least one tracker ticket is required")
    if auto_dev_mode not in AUTO_DEV_MODES:
        raise DevelopmentDeliveryError(f"Auto-Dev mode must be one of: {', '.join(AUTO_DEV_MODES)}")
    if requested_stage is not None:
        requested_stage = requested_stage.strip().lower().replace("-", "_")
        if requested_stage not in AUTO_DEV_STAGE_ORDER:
            raise DevelopmentDeliveryError(
                f"requested Auto-Dev stage must be one of: {', '.join(AUTO_DEV_STAGE_ORDER)}"
            )
    if auto_dev_mode == "single_stage" and not requested_stage:
        requested_stage = "develop"
    if auto_dev_mode in {"default", "everything"}:
        requested_stage = None
    selected_packet = (
        Path(selected_work_item).expanduser().resolve() if selected_work_item is not None else None
    )
    adoption_row: dict[str, Any] | None = None
    if selected_packet is not None:
        if len(dict.fromkeys(tickets)) != 1:
            raise DevelopmentDeliveryError("a selected work item can belong to only one ticket")
        if not selected_packet.is_dir():
            raise DevelopmentDeliveryError(
                f"selected Auto-Dev work item is missing or incomplete: {selected_packet}"
            )
        projection_exists = (selected_packet / "autodev.json").is_file()
        if adopt_existing:
            if projection_exists:
                raise DevelopmentDeliveryError(
                    "selected packet already has autodev.json; resume it instead of adopting it"
                )
            work_metadata = _read_mapping(selected_packet / "work.yml")
            work_metadata_id = str(work_metadata.get("id") or "").lower().replace("-", "_")
            ticket_token = _slug(str(tickets[0])).replace("-", "_")
            if not work_metadata_id or ticket_token not in work_metadata_id:
                raise DevelopmentDeliveryError(
                    "Auto-Dev adoption ticket must be represented in work.yml id"
                )
            adoption_row = _canonical_packet_match(
                root,
                domain=domain,
                project=project,
                ticket=str(tickets[0]),
                packet=selected_packet,
            )
        elif not projection_exists:
            raise DevelopmentDeliveryError(
                f"selected Auto-Dev work item is missing or incomplete: {selected_packet}"
            )
    elif adopt_existing:
        raise DevelopmentDeliveryError("Auto-Dev adoption requires an exact selected work-item packet")
    if existing_state_only and selected_packet is None:
        raise DevelopmentDeliveryError("this Auto-Dev action requires an existing work-item state")
    profile, source = load_development_profile(root, domain, project)
    profile = select_development_repository(profile, repository_id)
    profile_auto_dev = profile.get("auto_dev") if isinstance(profile.get("auto_dev"), Mapping) else {}
    configured_stage_order = profile_auto_dev.get("stage_order")
    if configured_stage_order is None:
        auto_dev_stage_order = list(AUTO_DEV_STAGE_ORDER)
    elif (
        not isinstance(configured_stage_order, list)
        or not all(isinstance(name, str) for name in configured_stage_order)
    ):
        raise DevelopmentDeliveryError(
            "auto_dev.stage_order must contain every canonical Auto-Dev stage exactly once"
        )
    else:
        if (
            len(configured_stage_order) == len(set(configured_stage_order))
            and set(configured_stage_order) < set(AUTO_DEV_STAGE_ORDER)
            and configured_stage_order
            == [name for name in AUTO_DEV_STAGE_ORDER if name in configured_stage_order]
        ):
            configured_stage_order = list(AUTO_DEV_STAGE_ORDER)
        try:
            auto_dev_stage_order = validate_auto_dev_stage_order(configured_stage_order)
        except AutoDevStateError as exc:
            raise DevelopmentDeliveryError(str(exc)) from exc
    workflow_policy = (
        profile_auto_dev.get(auto_dev_mode)
        if isinstance(profile_auto_dev.get(auto_dev_mode), Mapping)
        else {}
    )
    if auto_dev_mode == "single_stage":
        # A named workflow is the dispatch focus, not permission to erase its
        # predecessors. New single-stage items therefore begin at the first
        # frozen stage and end at the requested stage. Resumes widen this
        # durable window below; they never collapse it to target -> target.
        auto_dev_start_stage = auto_dev_stage_order[0]
        auto_dev_completion_stage = str(requested_stage)
    else:
        default_start = "readiness" if auto_dev_mode == "default" else auto_dev_stage_order[0]
        default_completion = "pr_create" if auto_dev_mode == "default" else auto_dev_stage_order[-1]
        auto_dev_start_stage = str(workflow_policy.get("start_stage") or default_start)
        auto_dev_completion_stage = str(
            workflow_policy.get("completion_stage") or default_completion
        )
    try:
        workflow_window = auto_dev_workflow_window(
            auto_dev_stage_order,
            auto_dev_start_stage,
            auto_dev_completion_stage,
        )
        if auto_dev_mode == "default" and "pr_create" not in workflow_window:
            raise AutoDevStateError(
                "The default Auto-Dev workflow must include PR Create; "
                "configure completion_stage as pr_create or a later stage"
            )
        auto_dev_stage_policies = validate_auto_dev_stage_policies(
            profile_auto_dev.get("stages")
            if isinstance(profile_auto_dev.get("stages"), Mapping)
            else {}
        )
    except AutoDevStateError as exc:
        raise DevelopmentDeliveryError(str(exc)) from exc
    goal = goal or (
        "delivery_complete"
        if auto_dev_completion_stage == "health"
        else auto_dev_completion_stage
    )
    if base_branch is not None:
        requested_base = str(base_branch).strip()
        if not requested_base or requested_base.startswith("-") or any(character.isspace() for character in requested_base):
            raise DevelopmentDeliveryError("--base-branch must be a non-empty git ref without whitespace")
        profile["repository"] = {**dict(profile["repository"]), "base_branch": requested_base}
    profile["repository"] = {
        **dict(profile["repository"]),
        "id": _normalized_repository_identity(profile["repository"]),
    }
    selected_errors = validate_profile(profile)
    if selected_errors:
        raise DevelopmentDeliveryError(
            "invalid selected repository profile: " + "; ".join(selected_errors)
        )
    adopted_worktree_preflight: dict[str, Any] | None = None
    adopted_runtime_preflight: dict[str, str] | None = None
    if adoption_row is not None:
        # Adoption is a migration of existing state, so every external
        # identity check must pass before the run directory, packet, task, or
        # canonical work row is changed. A failed preflight is safe to fix and
        # rerun because it leaves no partial autodev.json behind.
        adopted_worktree_preflight = _adopt_registered_worktree(
            os_root=root,
            domain=domain,
            project=project,
            profile=profile,
            canonical_row=adoption_row,
        )
        if adopted_worktree_preflight is not None:
            adopted_runtime_preflight = _runtime_registration(
                profile,
                adopted_worktree_preflight,
                domain=domain,
                project=project,
                ticket=str(tickets[0]),
            )
    authorship_required = auto_dev_mode in {"default", "everything"} or requested_stage in {
        "review_self",
        "review_others",
        "qa",
        "pr_create",
        "finalize",
        "merge",
        "release",
        "deploy",
        "closeout",
        "health",
    }
    configured_authorship = _configured_authorship(
        profile, required=authorship_required
    )
    effective_policies = resolve_development_policies(
        root,
        domain,
        project,
        explicit_files=policy_overlays,
        selected_profile=profile,
        profile_source=source,
        include_body=True,
        touched_paths=touched_paths,
        subjects=subjects,
        rulebook_ids=rulebook_ids,
        context_selection_override=context_selection_override,
    )
    project_path = project_root(root, domain, project)
    # Allocate the deterministic run destination before admission preflight so
    # an unavailable state database still leaves durable, bounded diagnostics.
    started_at = datetime.now(timezone.utc)
    run_id = run_id or dated_name(
        f"dev-{started_at.strftime('%H%M%SZ')}-{uuid.uuid4().hex[:6]}",
        when=started_at,
        policy=load_artifact_naming_policy(root),
        scope="development_runs",
    )
    run_dir = project_path / "state" / "development-runs" / run_id
    if apply and selected_packet is None:
        preflight_diagnostic_root = _preflight_admission_diagnostic_root(
            project_path, run_id
        )
        tracker_name = str(profile["tracker"].get("primary") or "filesystem")
        for ticket in dict.fromkeys(tickets):
            canonical_id = _resolve_canonical_development_work_id(
                root,
                domain=normalize_domain(domain),
                project=validate_name(project, "project"),
                tracker=tracker_name,
                ticket=ticket,
                diagnostic_root=preflight_diagnostic_root,
            )
            canonical_existing = _read_canonical_development_work(
                root,
                canonical_work_id=canonical_id,
                ticket=ticket,
                diagnostic_root=preflight_diagnostic_root,
            )
            packet_raw = (
                str(canonical_existing.get("packet_path") or "").strip()
                if isinstance(canonical_existing, Mapping)
                else ""
            )
            if not packet_raw:
                continue
            packet_value = Path(packet_raw).expanduser()
            packet = (
                packet_value.resolve()
                if packet_value.is_absolute()
                else (expand_path(root) / packet_value).resolve()
            )
            packet_lane = _project_work_item_lane(packet, project_path)
            if (
                packet_lane in {"03-complete", "99-archived"}
                or canonical_existing.get("state")
                in canonical_work_items.TERMINAL_STATES
            ):
                raise DevelopmentDeliveryError(
                    f"{ticket} points to an immutable finished packet; use "
                    "`agentic-os auto-dev reopen --state <finished-packet>`"
                )
            if packet_lane != "02-active":
                raise DevelopmentDeliveryError(
                    f"{ticket} canonical packet is outside the active work-item lane"
                )
            projection = packet / "autodev.json"
            if projection.is_file():
                existing_projection = _read_mapping(projection)
                linked_task = str(
                    (existing_projection.get("delivery") or {}).get("task_state_ref") or ""
                ).strip()
                if linked_task:
                    linked_path = Path(linked_task).expanduser()
                    linked_run_id = ""
                    if linked_path.is_file():
                        linked_run_id = str(_read_mapping(linked_path).get("run_id") or "")
                    if run_id and linked_run_id == run_id:
                        continue
                    raise DevelopmentDeliveryError(
                        f"{ticket} already has a live Auto-Dev item; resume it with "
                        f"--state {projection} so its delivery and pull-request history cannot be replaced"
                    )
    requested_titles = {ticket: (titles or {}).get(ticket) or f"Implement {ticket}" for ticket in dict.fromkeys(tickets)}
    plan = {
        "schema": "development-portfolio/v1",
        "run_id": run_id,
        "domain": normalize_domain(domain),
        "project": validate_name(project, "project"),
        "profile_source": str(source),
        "state": "accepted",
        "tickets": list(dict.fromkeys(tickets)),
        "titles": requested_titles,
        "run_dir": str(run_dir),
        "apply": apply,
        "policy_fingerprint": effective_policies["fingerprint"],
        "repository": {
            "id": profile["repository"].get("id"),
            "root": profile["repository"]["root"],
            "base_branch": profile["repository"]["base_branch"],
        },
        "authorship": configured_authorship,
        "policy_sources": {
            name: [item["source_ref"] for item in value["sources"]]
            for name, value in effective_policies["planes"].items()
        },
        "context_selection": effective_policies["context_selection"],
        "auto_dev": {
            "mode": auto_dev_mode,
            "requested_stage": requested_stage,
            "goal": goal,
            "stage_order": auto_dev_stage_order,
            "start_stage": auto_dev_start_stage,
            "completion_stage": auto_dev_completion_stage,
            "stage_policies": auto_dev_stage_policies,
            "provision_worktree": provision_worktree,
        },
    }
    if not apply:
        return plan
    portfolio_path = run_dir / "portfolio.json"
    portfolio_existed = portfolio_path.is_file()
    if run_dir.exists() and not portfolio_path.is_file():
        raise DevelopmentDeliveryError(f"run directory exists without a portfolio receipt: {run_dir}")
    if portfolio_existed:
        for ticket in dict.fromkeys(tickets):
            state_path = run_dir / "tasks" / _slug(ticket) / "state.json"
            if not state_path.is_file():
                continue
            with _task_provisioning_admission_lock(state_path):
                current = TaskState(state_path).read()
                if _is_retryable_origin_main_provisioning_failure(current) and not _has_valid_base_selection_correction(
                    state_path,
                    current=current,
                    apply=True,
                ):
                    raise DevelopmentDeliveryError(
                        "historical origin/main provisioning failure requires the recorded "
                        "base-selection correction before resume"
                    )
    if portfolio_path.is_file():
        existing = json.loads(portfolio_path.read_text(encoding="utf-8"))
        selected_tickets = list(dict.fromkeys(tickets))
        selected_member_resume = (
            selected_packet is not None
            and len(selected_tickets) == 1
            and selected_tickets[0] in (existing.get("tickets") or [])
        )
        if existing.get("tickets") != plan["tickets"] and not selected_member_resume:
            raise DevelopmentDeliveryError("run id already belongs to a different ticket portfolio")
        # Runs created before repository catalogs did not include this field.
        # Backfill that one compatibility shape, but never permit a recorded
        # selection to drift to another repository on resume.
        existing_repository = (
            existing.get("repository")
            if isinstance(existing.get("repository"), Mapping)
            else None
        )
        if existing_repository is None:
            existing["repository"] = plan["repository"]
            _atomic_json(portfolio_path, existing)
        elif (
            not str(existing_repository.get("id") or "").strip()
            and existing_repository.get("root") == plan["repository"]["root"]
            and existing_repository.get("base_branch") == plan["repository"]["base_branch"]
        ):
            existing["repository"] = plan["repository"]
            _atomic_json(portfolio_path, existing)
        elif existing.get("repository") != plan["repository"]:
            raise DevelopmentDeliveryError("run id already belongs to a different repository selection")
        if existing.get("authorship") is None:
            existing["authorship"] = plan["authorship"]
            _atomic_json(portfolio_path, existing)
        elif existing.get("authorship") != plan["authorship"]:
            raise DevelopmentDeliveryError(
                "run id authorship boundary differs from the selected project profile"
            )
        plan = existing
        pinned_titles = dict(plan.get("titles") or {})
        # A portfolio pins each title when the run id is created. Silently reusing
        # the pinned title hid corrected retries behind an identical failure, so a
        # caller supplying a different one has to learn the run id is the wrong lever.
        for pinned_ticket, supplied_title in (titles or {}).items():
            pinned_title = pinned_titles.get(pinned_ticket)
            if pinned_title is not None and supplied_title and supplied_title != pinned_title:
                raise DevelopmentDeliveryError(
                    f"run id already pinned the title for {pinned_ticket}: {pinned_title!r}; "
                    "start a new run id to deliver that ticket under a different title"
                )
        requested_titles = pinned_titles or requested_titles
        policy_path = run_dir / "effective-policies.json"
        if policy_path.is_file():
            run_policies = json.loads(policy_path.read_text(encoding="utf-8"))
            if not isinstance(run_policies, dict):
                raise DevelopmentDeliveryError(f"invalid effective policy receipt: {policy_path}")
            try:
                frozen_selected_profile = _validate_effective_policy_snapshot(
                    run_policies,
                    require_selected_profile=False,
                )
            except DevelopmentDeliveryError as exc:
                raise DevelopmentDeliveryError(
                    f"invalid effective policy receipt: {policy_path}: {exc}"
                ) from exc
            recorded_fingerprint = str(existing.get("policy_fingerprint") or "")
            if (
                recorded_fingerprint
                and run_policies.get("fingerprint") != recorded_fingerprint
            ):
                raise DevelopmentDeliveryError(
                    "effective policy receipt no longer matches the portfolio fingerprint"
                )
            existing_repository = (
                existing.get("repository")
                if isinstance(existing.get("repository"), Mapping)
                else {}
            )
            if not (
                run_policies.get("domain") == existing.get("domain")
                and run_policies.get("project") == existing.get("project")
                and (
                    frozen_selected_profile is None
                    or frozen_selected_profile.get("repository_id")
                    == existing_repository.get("id")
                )
            ):
                raise DevelopmentDeliveryError(
                    "effective policy receipt identity does not match its portfolio"
                )
        else:
            if existing.get("policy_fingerprint"):
                raise DevelopmentDeliveryError(
                    f"recorded effective policy receipt is missing: {policy_path}"
                )
            # Backfill only truly early runs that never recorded a policy
            # fingerprint. Resumes thereafter remain pinned to this snapshot.
            run_policies = effective_policies
            existing["policy_fingerprint"] = run_policies["fingerprint"]
            _atomic_json(policy_path, run_policies)
            _atomic_json(portfolio_path, existing)
        if run_policies.get("fingerprint") != effective_policies.get("fingerprint"):
            plan["policy_drift"] = {
                "run_fingerprint": run_policies.get("fingerprint"),
                "current_fingerprint": effective_policies.get("fingerprint"),
                "behavior": "continue_with_run_snapshot",
                "observed_at": utc_now(),
            }
    else:
        run_dir.mkdir(parents=True)
        plan["created_at"] = utc_now()
        run_policies = effective_policies
        _atomic_json(run_dir / "effective-policies.json", run_policies)
        _atomic_json(portfolio_path, plan)

    operation_tickets = (
        list(dict.fromkeys(tickets)) if selected_packet is not None else list(plan["tickets"])
    )
    frozen_context_selection = run_policies.get("context_selection")
    if isinstance(frozen_context_selection, Mapping):
        if plan.get("context_selection") is None:
            plan["context_selection"] = deepcopy(dict(frozen_context_selection))
            _atomic_json(portfolio_path, plan)
        elif plan.get("context_selection") != frozen_context_selection:
            raise DevelopmentDeliveryError(
                "frozen context selection differs between portfolio and effective policy receipt"
            )
    plan.setdefault(
        "policy_sources",
        {
            name: [item["source_ref"] for item in value["sources"]]
            for name, value in run_policies["planes"].items()
        },
    )
    recorded_auto_dev = plan.get("auto_dev") if isinstance(plan.get("auto_dev"), Mapping) else None
    recorded_portfolio_boundary = _explicit_auto_dev_boundary(
        recorded_auto_dev,
        mode_key="mode",
        start_key="start_stage",
        completion_key="completion_stage",
        label="development portfolio",
    )
    recorded_mode = auto_dev_mode
    durable_auto_dev_mode = auto_dev_mode
    if recorded_auto_dev:
        recorded_mode = str(recorded_auto_dev.get("mode") or auto_dev_mode)
        durable_auto_dev_mode = recorded_mode
        recorded_order = list(recorded_auto_dev.get("stage_order") or auto_dev_stage_order)
        if (
            len(recorded_order) == len(set(recorded_order))
            and set(recorded_order) < set(AUTO_DEV_STAGE_ORDER)
            and recorded_order == [name for name in AUTO_DEV_STAGE_ORDER if name in recorded_order]
        ):
            auto_dev_stage_order = list(AUTO_DEV_STAGE_ORDER)
        else:
            try:
                auto_dev_stage_order = validate_auto_dev_stage_order(recorded_order)
            except AutoDevStateError as exc:
                raise DevelopmentDeliveryError(
                    f"recorded auto_dev.stage_order is unsafe: {exc}"
                ) from exc
        recorded_start = (
            recorded_portfolio_boundary[1]
            if recorded_portfolio_boundary is not None
            else auto_dev_start_stage
        )
        recorded_completion = (
            recorded_portfolio_boundary[2]
            if recorded_portfolio_boundary is not None
            else auto_dev_completion_stage
        )
        if (
            recorded_mode == "single_stage"
            and recorded_start == recorded_completion
        ):
            # Normalize target-only state emitted by the PR83 preview. Keeping
            # health -> health would make Health's predecessor audit empty.
            recorded_start = auto_dev_stage_order[0]
        try:
            auto_dev_workflow_window(
                auto_dev_stage_order,
                recorded_start,
                recorded_completion,
            )
            auto_dev_stage_policies = validate_auto_dev_stage_policies(
                recorded_auto_dev.get("stage_policies")
                if isinstance(recorded_auto_dev.get("stage_policies"), Mapping)
                else auto_dev_stage_policies
            )
            recorded_start_index = auto_dev_stage_order.index(recorded_start)
            recorded_completion_index = auto_dev_stage_order.index(recorded_completion)
            if auto_dev_mode == "single_stage":
                requested_index = auto_dev_stage_order.index(str(requested_stage))
                start_index = min(recorded_start_index, requested_index)
                completion_index = max(recorded_completion_index, requested_index)
            elif (
                auto_dev_mode == recorded_mode
                or recorded_mode == "everything"
            ):
                # A same-mode resume consumes the frozen run slice even when
                # development.yml has drifted. Default cannot narrow a run
                # already promoted to Everything.
                start_index = recorded_start_index
                completion_index = recorded_completion_index
            else:
                # Explicitly promoting single-stage -> Default/Everything or
                # Default -> Everything may widen the durable window once.
                requested_start_index = auto_dev_stage_order.index(auto_dev_start_stage)
                requested_completion_index = auto_dev_stage_order.index(
                    auto_dev_completion_stage
                )
                start_index = min(recorded_start_index, requested_start_index)
                completion_index = max(
                    recorded_completion_index,
                    requested_completion_index,
                )
                durable_auto_dev_mode = auto_dev_mode
            auto_dev_start_stage = auto_dev_stage_order[start_index]
            auto_dev_completion_stage = auto_dev_stage_order[completion_index]
            auto_dev_workflow_window(
                auto_dev_stage_order,
                auto_dev_start_stage,
                auto_dev_completion_stage,
            )
        except (AutoDevStateError, ValueError) as exc:
            raise DevelopmentDeliveryError(
                f"recorded Auto-Dev workflow policy is unsafe: {exc}"
            ) from exc
        goal = (
            "delivery_complete"
            if auto_dev_completion_stage == "health"
            else auto_dev_completion_stage
        )
    if recorded_auto_dev is None:
        plan["auto_dev"] = {
            "mode": auto_dev_mode,
            "requested_stage": requested_stage,
            "goal": goal,
            "stage_order": auto_dev_stage_order,
            "start_stage": auto_dev_start_stage,
            "completion_stage": auto_dev_completion_stage,
            "stage_policies": auto_dev_stage_policies,
            "provision_worktree": provision_worktree,
            "requested_at": utc_now(),
        }
    else:
        # Portfolio state is the durable boundary. It may expand when a later
        # named workflow is requested, but it must never shrink and erase
        # receipt-backed history.
        plan["auto_dev"] = {
            **dict(recorded_auto_dev),
            "mode": durable_auto_dev_mode,
            "goal": goal,
            "stage_order": auto_dev_stage_order,
            "start_stage": auto_dev_start_stage,
            "completion_stage": auto_dev_completion_stage,
            "stage_policies": auto_dev_stage_policies,
        }
    recovery = profile["recovery"]
    rollup_ledger = expand_path(root) / "harness" / "shared_factory" / "00-control-plane" / "development-runs.jsonl"
    prior_rows = {row.get("ticket"): row for row in plan.get("tasks", []) if isinstance(row, Mapping)}
    task_rows: list[dict[str, Any]] = []
    for ticket in operation_tickets:
        title = requested_titles[ticket]
        repository_prefix = ""
        if profile["repository"].get("id"):
            repository_prefix = _slug(str(profile["repository"]["id"])).replace("-", "_") + "_"
        work_id = f"{repository_prefix}{_slug(ticket).replace('-', '_')}_{_slug(title).replace('-', '_')}"
        task_dir = run_dir / "tasks" / _slug(ticket)
        state_path = task_dir / "state.json"
        state_created = not state_path.is_file()
        if state_created:
            _write_task_state(
                state_path,
                run_id=run_id,
                ticket=ticket,
                max_attempts=int(recovery.get("max_attempts") or 3),
                lease_minutes=int(recovery.get("lease_minutes") or 30),
                rollup_ledger=rollup_ledger,
            )
            seeded_state = TaskState(state_path).read()
            seeded_state.update(
                {
                    "auto_dev_mode": durable_auto_dev_mode,
                    "requested_stage": requested_stage,
                    "goal": goal,
                    "auto_dev_stage_order": auto_dev_stage_order,
                    "auto_dev_start_stage": auto_dev_start_stage,
                    "auto_dev_completion_stage": auto_dev_completion_stage,
                    "auto_dev_stage_policies": auto_dev_stage_policies,
                }
            )
            _atomic_json(state_path, seeded_state)
        task_state = TaskState(state_path)
        with _task_provisioning_admission_lock(state_path):
            current = task_state.read()
            failure = current.get("failure") if isinstance(current.get("failure"), Mapping) else {}
            if _is_retryable_origin_main_provisioning_failure(current) and not _has_valid_base_selection_correction(
                state_path,
                current=current,
                apply=True,
            ):
                raise DevelopmentDeliveryError(
                    "historical origin/main provisioning failure requires the recorded "
                    "base-selection correction before resume"
                )
            # An unaccepted executor handoff is a durable, idempotent pending
            # boundary.  Do not clear it merely because the same Everything
            # packet is resumed: that would make the second invocation look like
            # a fresh worktree-ready success while retaining no failed handoff
            # evidence.  A distinct recovery after executor remediation remains
            # the only way to advance this retry-bounded failure.
            if failure.get("recoverable") and failure.get("kind") != "executor_unavailable":
                task_state.recover(
                    receipt="automatic provisioning resume",
                    idempotency_key=f"{run_id}:{ticket}:auto-recover:{current.get('updated_at')}",
                )
                current = task_state.read()
            elif current.get("state") == "blocked":
                task_rows.append(dict(prior_rows.get(ticket) or {"ticket": ticket, "state_ref": str(state_path), "error": failure}))
                continue
        selected_projection: Mapping[str, Any] = {}
        if selected_packet is not None:
            work_items_root = (project_path / "work-items").resolve()
            try:
                selected_packet.relative_to(work_items_root)
            except ValueError as exc:
                raise DevelopmentDeliveryError(
                    "selected Auto-Dev packet is outside the owning project's work-items tree"
                ) from exc
            selected_lane = _project_work_item_lane(selected_packet, project_path)
            if selected_lane not in {
                "02-active",
                "03-complete",
                "99-archived",
            }:
                raise DevelopmentDeliveryError(
                    "selected Auto-Dev packet must be canonical, archived, or in a retained legacy lane"
                )
            if (
                _project_work_item_is_finished(selected_packet, project_path)
                and requested_stage != "health"
            ):
                raise DevelopmentDeliveryError(
                    "finished Auto-Dev packets are immutable; use the explicit work-item "
                    "reopen path to start a new delivery run before changing them"
                )
            selected_projection = (
                _read_mapping(selected_packet / "autodev.json")
                if (selected_packet / "autodev.json").is_file()
                else {}
            )
            selected_delivery = (
                selected_projection.get("delivery")
                if isinstance(selected_projection.get("delivery"), Mapping)
                else {}
            )
            linked_task = str(selected_delivery.get("task_state_ref") or "").strip()
            if linked_task and Path(linked_task).expanduser().resolve() != state_path.resolve():
                raise DevelopmentDeliveryError(
                    "selected Auto-Dev packet belongs to a different delivery task"
                )
            if selected_projection and (
                str(selected_projection.get("domain") or "") != plan["domain"]
                or str(selected_projection.get("project") or "") != plan["project"]
                or str((selected_projection.get("source") or {}).get("key") or "") != ticket
            ):
                raise DevelopmentDeliveryError(
                    "selected Auto-Dev packet identity does not match the requested task"
                )
            prior_packet = Path(str(current.get("work_item") or selected_packet)).expanduser()
            if prior_packet.name != selected_packet.name:
                raise DevelopmentDeliveryError(
                    "selected Auto-Dev packet name does not match the linked delivery packet"
                )
            current["work_item"] = str(selected_packet)
            current["autodev_path"] = str(selected_packet / "autodev.json")
            if adoption_row is not None:
                current["canonical_work_id"] = adoption_row["id"]
                current["source"] = {
                    "system": adoption_row.get("source_system") or "filesystem",
                    "key": adoption_row.get("source_key") or ticket,
                    "url": adoption_row.get("source_url"),
                }
                if adopted_worktree_preflight is not None:
                    current["worktree"] = adopted_worktree_preflight
                    current["runtime"] = adopted_runtime_preflight
            if not current.get("canonical_work_id") and selected_projection.get("canonical_work_id"):
                current["canonical_work_id"] = selected_projection["canonical_work_id"]
            _atomic_json(state_path, current)
        elif current.get("autodev_path"):
            projection_path = Path(str(current["autodev_path"])).expanduser()
            if projection_path.is_file():
                selected_projection = _read_mapping(projection_path)
        if portfolio_existed and not state_created:
            task_boundary = _explicit_auto_dev_boundary(
                current,
                mode_key="auto_dev_mode",
                start_key="auto_dev_start_stage",
                completion_key="auto_dev_completion_stage",
                label=f"delivery task {ticket}",
            )
            projection_boundary = _explicit_auto_dev_boundary(
                selected_projection,
                mode_key="mode",
                start_key="start_stage",
                completion_key="completion_stage",
                label=f"Auto-Dev projection {ticket}",
            )
            task_mode = str(current.get("auto_dev_mode") or "").strip()
            projection_mode = str(selected_projection.get("mode") or "").strip()
            if (
                (task_mode and task_mode != recorded_mode)
                or task_boundary != recorded_portfolio_boundary
                or (
                    current.get("work_item")
                    and (
                        (projection_mode and projection_mode != recorded_mode)
                        or projection_boundary != recorded_portfolio_boundary
                    )
                )
            ):
                raise DevelopmentDeliveryError(
                    "recorded Auto-Dev workflow boundary differs between "
                    "portfolio, task, and projection"
                )
        existing_work_item_raw = current.get("work_item")
        existing_work_item = Path(str(existing_work_item_raw)).expanduser() if existing_work_item_raw else None
        current_name = str(current.get("state") or "")
        if (
            existing_work_item is not None
            and existing_work_item.is_dir()
            and current_name in FORWARD_STATES
            and FORWARD_STATES.index(current_name) >= FORWARD_STATES.index("work_item_ready")
        ):
            current_source = (
                current.get("source")
                if isinstance(current.get("source"), Mapping)
                else {}
            )
            task_tracker = str(
                current_source.get("system")
                or profile["tracker"].get("primary")
                or "filesystem"
            )
            canonical_work_id = _resolve_canonical_development_work_id(
                root,
                domain=plan["domain"],
                project=plan["project"],
                tracker=task_tracker,
                ticket=ticket,
                preferred_id=(
                    str(current["canonical_work_id"])
                    if current.get("canonical_work_id")
                    else None
                ),
                packet=existing_work_item,
                diagnostic_root=run_dir,
            )
            current.update(
                {
                    "os_root": str(expand_path(root)),
                    "domain": plan["domain"],
                    "project": plan["project"],
                    "title": title,
                    "source": {
                        "system": task_tracker,
                        "key": ticket,
                        "url": current_source.get("url"),
                    },
                    "autodev_path": str(existing_work_item / "autodev.json"),
                    "auto_dev_mode": durable_auto_dev_mode,
                    "requested_stage": requested_stage,
                    "goal": goal,
                    "auto_dev_stage_order": auto_dev_stage_order,
                    "auto_dev_start_stage": auto_dev_start_stage,
                    "auto_dev_completion_stage": auto_dev_completion_stage,
                    "auto_dev_stage_policies": auto_dev_stage_policies,
                    "profile_source": str(source),
                    "policy_receipt": str(run_dir / "effective-policies.json"),
                    "policy_fingerprint": run_policies["fingerprint"],
                    "policy_sources": plan["policy_sources"],
                    "context_selection": run_policies.get("context_selection"),
                    "repository": plan["repository"],
                    "authorship": plan["authorship"],
                    "canonical_work_id": canonical_work_id,
                }
            )
            _atomic_json(state_path, current)
            _sync_auto_dev_projection(state_path)
            _sync_canonical_development_work(
                root,
                domain=plan["domain"],
                project=plan["project"],
                ticket=ticket,
                title=title,
                run_id=run_id,
                tracker=task_tracker,
                packet=existing_work_item,
                worktree=(current.get("worktree") if isinstance(current.get("worktree"), Mapping) else None),
                delivery_state=current_name,
                canonical_work_id=canonical_work_id,
            )
            current_index = FORWARD_STATES.index(current_name)
            worktree_index = FORWARD_STATES.index("worktree_ready")
            if not provision_worktree or (current_index >= worktree_index and current.get("worktree")):
                handoff = _record_post_materialization_handoff(
                    task_state,
                    require_executor_handoff=require_executor_handoff,
                )
                row = dict(
                    prior_rows.get(ticket)
                    or {"ticket": ticket, "state_ref": str(state_path), **current}
                )
                if handoff is not None:
                    row["handoff"] = handoff
                else:
                    # A recovery clears the task failure, so a later named-stage
                    # resume must not keep the old pending handoff copied from
                    # the portfolio projection. Pending status is current-task
                    # state, not an append-only history marker.
                    row.pop("handoff", None)
                task_rows.append(row)
                continue
            if current_index > FORWARD_STATES.index("work_item_ready"):
                raise DevelopmentDeliveryError(
                    f"progressed task {ticket} is missing its worktree receipt"
                )
        if existing_state_only:
            raise DevelopmentDeliveryError(
                "existing-state-only Auto-Dev action could not resolve its linked work item"
            )
        try:
            current_source = current.get("source") if isinstance(current.get("source"), Mapping) else {}
            profile_tracker = str(
                current_source.get("system")
                or profile["tracker"].get("primary")
                or "filesystem"
            )
            canonical_work_id = _resolve_canonical_development_work_id(
                root,
                domain=plan["domain"],
                project=plan["project"],
                tracker=profile_tracker,
                ticket=ticket,
                preferred_id=(str(current.get("canonical_work_id")) if current.get("canonical_work_id") else None),
                packet=selected_packet,
                diagnostic_root=run_dir,
            )
            canonical_existing = _read_canonical_development_work(
                root,
                canonical_work_id=canonical_work_id,
                ticket=ticket,
                packet=selected_packet,
                diagnostic_root=run_dir,
            )
            work_item = selected_packet if adoption_row is not None else None
            if canonical_existing and canonical_existing.get("packet_path"):
                if canonical_existing.get("state") in canonical_work_items.TERMINAL_STATES:
                    raise DevelopmentDeliveryError(
                        f"canonical work item is already terminal: {canonical_work_id}"
                    )
                packet_value = Path(str(canonical_existing["packet_path"])).expanduser()
                canonical_packet = (
                    packet_value.resolve()
                    if packet_value.is_absolute()
                    else (expand_path(root) / packet_value).resolve()
                )
                if canonical_packet.is_dir():
                    if _project_work_item_lane(canonical_packet, project_path) != "02-active":
                        raise DevelopmentDeliveryError(
                            "canonical work item points to a non-active packet; use the explicit "
                            "Auto-Dev reopen command for finished history"
                        )
                    work_item = canonical_packet
            if work_item is None:
                work_item = find_delivery_work_item(project_path, work_id)
                if (
                    work_item is not None
                    and _project_work_item_lane(work_item, project_path) != "02-active"
                ):
                    raise DevelopmentDeliveryError(
                        "existing work item is outside the active lane; use the explicit "
                        "Auto-Dev reopen command for finished or archived history"
                    )
            if work_item is None:
                result = create_project_work_item(
                    root,
                    domain,
                    project,
                    title=title,
                    summary=f"Canonical development-delivery run {run_id} for {ticket}.",
                    status=str(profile["work_items"].get("active_status") or "building"),
                    work_id=work_id,
                    item_format="packet",
                )
                # Trust the packet the scaffolder reports it created. Re-deriving
                # it from directory names loses to the id normalisation the
                # scaffolder applies, and every miss left the run an orphan packet.
                work_item = result.entity_path
                if work_item is None or not work_item.is_dir():
                    work_item = find_delivery_work_item(project_path, work_id)
            if work_item is None:
                raise DevelopmentDeliveryError(f"work item receipt missing for {ticket}")
            current = task_state.read()
            current.update(
                {
                    "os_root": str(expand_path(root)),
                    "domain": plan["domain"],
                    "project": plan["project"],
                    "title": title,
                    "source": {"system": profile_tracker, "key": ticket, "url": None},
                    "work_item": str(work_item),
                    "autodev_path": str(work_item / "autodev.json"),
                    "auto_dev_mode": durable_auto_dev_mode,
                    "requested_stage": requested_stage,
                    "goal": goal,
                    "auto_dev_stage_order": auto_dev_stage_order,
                    "auto_dev_start_stage": auto_dev_start_stage,
                    "auto_dev_completion_stage": auto_dev_completion_stage,
                    "auto_dev_stage_policies": auto_dev_stage_policies,
                    "profile_source": str(source),
                    "policy_receipt": str(run_dir / "effective-policies.json"),
                    "policy_fingerprint": run_policies["fingerprint"],
                    "policy_sources": plan["policy_sources"],
                    "context_selection": run_policies.get("context_selection"),
                    "repository": plan["repository"],
                    "authorship": plan["authorship"],
                    "canonical_work_id": canonical_work_id,
                }
            )
            _atomic_json(state_path, current)
            _sync_auto_dev_projection(state_path)
            _sync_canonical_development_work(
                root,
                domain=plan["domain"],
                project=plan["project"],
                ticket=ticket,
                title=title,
                run_id=run_id,
                tracker=profile_tracker,
                packet=work_item,
                worktree=(
                    current.get("worktree")
                    if isinstance(current.get("worktree"), Mapping)
                    else None
                ),
                delivery_state=str(current.get("state") or "work_item_ready"),
                canonical_work_id=canonical_work_id,
            )
            _atomic_json(
                work_item / "artifacts" / "development-delivery" / "run.json",
                {
                    "schema": "development-work-item-link/v1",
                    "run_id": run_id,
                    "ticket": ticket,
                    "task_state": str(state_path),
                    "profile_source": str(source),
                    "policy_receipt": str(run_dir / "effective-policies.json"),
                    "policy_fingerprint": run_policies["fingerprint"],
                    "repository": plan["repository"],
                    "authorship": plan["authorship"],
                    "recorded_at": utc_now(),
                },
            )
            transition_receipts = {
                "claimed": f"{profile_tracker}:{ticket}",
                "groom_check": f"{profile_tracker}:{ticket}",
                "context_ready": str(work_item / "SPEC.md"),
                "work_item_ready": str(work_item),
            }
            while task_state.read()["state"] != "work_item_ready":
                current_name = str(task_state.read()["state"])
                target = FORWARD_STATES[FORWARD_STATES.index(current_name) + 1]
                if target not in transition_receipts:
                    raise DevelopmentDeliveryError(f"cannot provision from state: {current_name}")
                task_state.transition(
                    target,
                    receipt=transition_receipts[target],
                    idempotency_key=f"{run_id}:{ticket}:{target}",
                )
            adopted_worktree = (
                adopted_worktree_preflight if adoption_row is not None else None
            )
            if adopted_worktree is not None:
                with _task_provisioning_admission_lock(state_path):
                    runtime_registration = adopted_runtime_preflight
                    if runtime_registration is None:
                        raise DevelopmentDeliveryError(
                            "adopted worktree passed preflight without a runtime ownership receipt"
                        )
                    task_state.transition(
                        "worktree_ready",
                        receipt=adopted_worktree["path"],
                        idempotency_key=f"{run_id}:{ticket}:adopt-worktree",
                    )
                    current = task_state.read()
                    current.update(
                        {
                            "work_item": str(work_item),
                            "worktree": adopted_worktree,
                            "runtime": runtime_registration,
                        }
                    )
                    _atomic_json(state_path, current)
                _sync_auto_dev_projection(state_path)
                _sync_canonical_development_work(
                    root,
                    domain=plan["domain"],
                    project=plan["project"],
                    ticket=ticket,
                    title=title,
                    run_id=run_id,
                    tracker=profile_tracker,
                    packet=work_item,
                    worktree=adopted_worktree,
                    delivery_state="worktree_ready",
                    canonical_work_id=canonical_work_id,
                )
                handoff = _record_post_materialization_handoff(
                    task_state,
                    require_executor_handoff=require_executor_handoff,
                )
                row = {
                    "ticket": ticket,
                    "state_ref": str(state_path),
                    "work_item": str(work_item),
                    "worktree": adopted_worktree,
                    "runtime": runtime_registration,
                    "canonical_work_id": canonical_work_id,
                }
                if handoff is not None:
                    row["handoff"] = handoff
                task_rows.append(row)
                continue
            if not provision_worktree:
                current = task_state.read()
                task_rows.append(
                    {
                        "ticket": ticket,
                        "state_ref": str(state_path),
                        "work_item": str(work_item),
                        "canonical_work_id": canonical_work_id,
                    }
                )
                continue
            with _task_provisioning_admission_lock(state_path):
                worktree = create_isolated_worktree(
                    os_root=root,
                    domain=domain,
                    project=project,
                    profile=profile,
                    ticket=ticket,
                    title=title,
                )
                runtime_registration = _runtime_registration(
                    profile,
                    worktree,
                    domain=domain,
                    project=project,
                    ticket=ticket,
                )
                task_state.transition("worktree_ready", receipt=worktree["path"], idempotency_key=f"{run_id}:{ticket}:worktree")
                current = task_state.read()
                current.update(
                    {
                        "work_item": str(work_item),
                        "worktree": worktree,
                        "runtime": runtime_registration,
                    }
                )
                _atomic_json(state_path, current)
            _sync_auto_dev_projection(state_path)
            _sync_canonical_development_work(
                root,
                domain=plan["domain"],
                project=plan["project"],
                ticket=ticket,
                title=title,
                run_id=run_id,
                tracker=profile_tracker,
                packet=work_item,
                worktree=worktree,
                delivery_state=str(current.get("state") or "worktree_ready"),
                canonical_work_id=canonical_work_id,
            )
            handoff = _record_post_materialization_handoff(
                task_state,
                require_executor_handoff=require_executor_handoff,
            )
            row = {
                "ticket": ticket,
                "state_ref": str(state_path),
                "work_item": str(work_item),
                "worktree": worktree,
                "runtime": runtime_registration,
                "canonical_work_id": canonical_work_id,
            }
            if handoff is not None:
                row["handoff"] = handoff
            task_rows.append(row)
        except (DevelopmentDeliveryError, OSError, subprocess.SubprocessError) as exc:
            detail = str(exc)
            kind = "provider_unavailable" if any(word in detail.lower() for word in ("fetch", "timeout", "unavailable")) else "provisioning_failed"
            admission_contended = "canonical Auto-Dev admission could not acquire" in detail
            failed = task_state.fail(
                kind=kind,
                detail=detail,
                receipt=str(state_path),
                idempotency_key=f"{run_id}:{ticket}:provisioning-failed:{task_state.read().get('updated_at')}",
                # The original bounded admission receipt is authoritative while
                # the state DB is locked. Do not immediately retry that same
                # unavailable writer just to project this local failure.
                sync_canonical=not admission_contended,
            )
            if admission_contended:
                raise
            task_rows.append({"ticket": ticket, "state_ref": str(state_path), "error": failed["failure"]})
    merged_task_rows = {
        str(row.get("ticket")): dict(row)
        for row in plan.get("tasks", [])
        if isinstance(row, Mapping) and row.get("ticket")
    }
    merged_task_rows.update(
        {
            str(row.get("ticket")): dict(row)
            for row in task_rows
            if isinstance(row, Mapping) and row.get("ticket")
        }
    )
    task_rows = [merged_task_rows[ticket] for ticket in plan["tickets"] if ticket in merged_task_rows]
    task_states = [TaskState(Path(row["state_ref"])).read()["state"] for row in task_rows]
    portfolio_state = _portfolio_rollup(task_states)
    pending_handoffs = [
        row
        for row in task_rows
        if isinstance(row.get("handoff"), Mapping)
        and row["handoff"].get("status") == "pending"
    ]
    plan.update({
        "state": (
            "blocked"
            if portfolio_state == "blocked"
            else "pending"
            if pending_handoffs
            else portfolio_state
        ),
        "tasks": task_rows,
        "updated_at": utc_now(),
    })
    _atomic_json(portfolio_path, plan)
    append_event(
        project_path / "state" / "development-runs" / "events.jsonl",
        event_type="development.portfolio.started",
        idempotency_key=f"{run_id}:portfolio-started",
        payload={"run_id": run_id, "tickets": plan["tickets"]},
    )
    append_event(
        rollup_ledger,
        event_type="development.portfolio.started",
        idempotency_key=f"{run_id}:portfolio-started",
        payload={
            "run_id": run_id,
            "domain": plan["domain"],
            "project": plan["project"],
            "state": plan["state"],
            "tickets": plan["tickets"],
            "portfolio_ref": str(portfolio_path),
        },
    )
    return plan


def _prior_reopen_context_selection(projection: Mapping[str, Any]) -> dict[str, Any] | None:
    """Read the prior frozen context from the finished Auto-Dev projection."""

    delivery = projection.get("delivery")
    if not isinstance(delivery, Mapping) or delivery.get("context_selection") is None:
        return None
    context = delivery.get("context_selection")
    if not isinstance(context, Mapping):
        raise DevelopmentDeliveryError(
            "finished Auto-Dev state has malformed frozen context selection"
        )
    frozen = deepcopy(dict(context))
    _validate_development_context_selection(frozen)
    return frozen


def _reopen_context_plan(
    prior: Mapping[str, Any] | None,
    *,
    reselect_context: bool,
    touched_paths: Sequence[str],
    subjects: Sequence[str],
    rulebook_ids: Sequence[str],
) -> tuple[dict[str, Any] | None, str]:
    """Choose carry-forward versus explicit Rules Engine context reselection."""

    supplied = bool(touched_paths or subjects or rulebook_ids)
    if reselect_context:
        if not supplied:
            raise DevelopmentDeliveryError(
                "Auto-Dev reopen --reselect-context requires --touched-path, --subject, or --rulebook-id"
            )
        return None, "reselected"
    if supplied:
        raise DevelopmentDeliveryError(
            "Auto-Dev reopen preserves its prior frozen context by default; pass "
            "--reselect-context to provide new --touched-path, --subject, or --rulebook-id values"
        )
    if prior is None:
        return None, "not-present"
    return deepcopy(dict(prior)), "carried"


def _reopen_context_provenance(
    *,
    mode: str,
    prior: Mapping[str, Any] | None,
    selected: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return the compact, idempotency-bound context lineage for reopen."""

    selection = (
        selected.get("selection")
        if isinstance(selected, Mapping) and isinstance(selected.get("selection"), Mapping)
        else {}
    )
    rules_engine = (
        selected.get("rules_engine_context")
        if isinstance(selected, Mapping)
        and isinstance(selected.get("rules_engine_context"), Mapping)
        else {}
    )
    return {
        "mode": mode,
        "prior_content_sha256": (
            str(prior.get("content_sha256") or "") if isinstance(prior, Mapping) else None
        ),
        "selected_content_sha256": (
            str(selected.get("content_sha256") or "") if isinstance(selected, Mapping) else None
        ),
        "touched_paths": list(selection.get("touched_paths") or []),
        "subjects": list(selection.get("subjects") or []),
        "rulebook_ids": list(selection.get("rulebook_ids") or []),
        "rules_engine_status": (
            str(rules_engine.get("status") or "") if isinstance(rules_engine, Mapping) else None
        ),
    }


def reopen_auto_dev_item(
    root: str | Path,
    state_file: str | Path,
    *,
    run_id: str,
    reason: str,
    requested_stage: str = "qa",
    repository_id: str | None = None,
    base_branch: str | None = None,
    touched_paths: Sequence[str] = (),
    subjects: Sequence[str] = (),
    rulebook_ids: Sequence[str] = (),
    reselect_context: bool = False,
    apply: bool = False,
) -> dict[str, Any]:
    """Reopen immutable Health history into one fresh active packet and run."""

    run_id = str(run_id or "").strip()
    reason = str(reason or "").strip()
    requested_stage = str(requested_stage or "").strip().lower().replace("-", "_")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", run_id):
        raise DevelopmentDeliveryError(
            "Auto-Dev reopen --run-id must contain only letters, numbers, dot, underscore, and hyphen"
        )
    if not reason:
        raise DevelopmentDeliveryError("Auto-Dev reopen requires a durable --reason")
    if requested_stage not in {"develop", "qa"}:
        raise DevelopmentDeliveryError("Auto-Dev reopen --stage must be develop or qa")

    selected = Path(state_file).expanduser().resolve()
    if selected.is_dir():
        selected = selected / "autodev.json"
    if not selected.is_file():
        raise DevelopmentDeliveryError(f"finished Auto-Dev state is missing: {selected}")
    finished_packet = selected.parent
    projection = read_auto_dev_state(selected)
    domain = str(projection.get("domain") or "")
    project = str(projection.get("project") or "")
    source = projection.get("source") if isinstance(projection.get("source"), Mapping) else {}
    ticket = str(source.get("key") or "")
    canonical_work_id = str(projection.get("canonical_work_id") or "")
    if not all((domain, project, ticket, canonical_work_id)):
        raise DevelopmentDeliveryError(
            "finished Auto-Dev state lacks domain, project, source key, or canonical work id"
        )
    project_path = project_root(root, domain, project)
    if not _project_work_item_is_finished(finished_packet, project_path):
        raise DevelopmentDeliveryError(
            "Auto-Dev reopen requires a finished canonical, archived, or legacy completed packet"
        )
    health = (
        (projection.get("stages") or {}).get("health")
        if isinstance(projection.get("stages"), Mapping)
        else None
    )
    if not isinstance(health, Mapping) or health.get("status") != "completed":
        raise DevelopmentDeliveryError("Auto-Dev reopen requires completed Health evidence")
    finished_autodev_sha256 = hashlib.sha256(selected.read_bytes()).hexdigest()

    connection = connect_state(default_db_path(root))
    try:
        canonical = canonical_work_items.get(connection, canonical_work_id)
    finally:
        connection.close()
    if canonical is None:
        raise DevelopmentDeliveryError(f"canonical work item is missing: {canonical_work_id}")
    canonical_packet_raw = Path(str(canonical.get("packet_path") or "")).expanduser()
    canonical_packet = (
        canonical_packet_raw.resolve()
        if canonical_packet_raw.is_absolute()
        else (expand_path(root) / canonical_packet_raw).resolve()
    )
    try:
        health_receipt = validate_recorded_auto_dev_health(
            selected,
            allow_reopened=canonical_packet != finished_packet,
        )
    except AutoDevStateError as exc:
        raise DevelopmentDeliveryError(
            f"completed Health evidence is not valid for reopen: {exc}"
        ) from exc
    health_sha256 = hashlib.sha256(health_receipt.read_bytes()).hexdigest()
    health_receipt_ref = health_receipt.relative_to(finished_packet).as_posix()
    title = str(canonical.get("title") or f"Implement {ticket}")
    prior_context_selection = _prior_reopen_context_selection(projection)
    context_override, context_mode = _reopen_context_plan(
        prior_context_selection,
        reselect_context=reselect_context,
        touched_paths=touched_paths,
        subjects=subjects,
        rulebook_ids=rulebook_ids,
    )
    launch_preflight = start_development_run(
        root,
        domain,
        project,
        [ticket],
        titles={ticket: title},
        run_id=run_id,
        repository_id=repository_id,
        base_branch=base_branch,
        touched_paths=touched_paths,
        subjects=subjects,
        rulebook_ids=rulebook_ids,
        context_selection_override=context_override,
        auto_dev_mode="single_stage",
        requested_stage=requested_stage,
        goal=requested_stage,
        provision_worktree=True,
        apply=False,
    )
    selected_context_selection = launch_preflight.get("context_selection")
    if not isinstance(selected_context_selection, Mapping):
        raise DevelopmentDeliveryError("Auto-Dev reopen preflight did not return frozen context selection")
    selected_context_selection = deepcopy(dict(selected_context_selection))
    _validate_development_context_selection(selected_context_selection)
    # Freeze a reselect at preflight time.  Launch consumes this exact payload
    # rather than resolving dynamic catalog/snapshot state a second time.
    launch_context_override = selected_context_selection
    context_provenance = _reopen_context_provenance(
        mode=context_mode,
        prior=prior_context_selection,
        selected=(selected_context_selection if context_mode != "not-present" else None),
    )
    selected_repository = dict(launch_preflight["repository"])
    request = {
        "run_id": run_id,
        "reason": reason,
        "requested_stage": requested_stage,
        "canonical_work_id": canonical_work_id,
        "domain": domain,
        "project": project,
        "ticket": ticket,
        "finished_packet": str(finished_packet),
        "finished_autodev_sha256": finished_autodev_sha256,
        "health_receipt": health_receipt_ref,
        "health_sha256": health_sha256,
        "repository": selected_repository,
        "context": context_provenance,
    }
    request_fingerprint = hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    plan = {
        "schema": "auto-dev-reopen-plan/v1",
        "status": "planned" if not apply else "reopening",
        "run_id": run_id,
        "reason": reason,
        "requested_stage": requested_stage,
        "canonical_work_id": canonical_work_id,
        "domain": domain,
        "project": project,
        "ticket": ticket,
        "finished_packet": str(finished_packet),
        "health_receipt": str(health_receipt),
        "health_sha256": health_sha256,
        "repository": selected_repository,
        "context": context_provenance,
        "request_fingerprint": request_fingerprint,
        "safety": {
            "preserve_finished_packet": True,
            "new_active_packet": True,
            "fresh_worktree": True,
            "fresh_runtime_registration": True,
        },
    }
    intent_dir = project_path / "state" / "auto-dev-reopen"
    intent_path = intent_dir / f"{run_id}.json"
    intent_lock = intent_dir / ".lock"
    active_root = work_item_lane_root(project_path, "building")

    def resolved_packet(raw: Any) -> Path:
        value = Path(str(raw or "")).expanduser()
        return value.resolve() if value.is_absolute() else (expand_path(root) / value).resolve()

    def validate_intent(value: Mapping[str, Any]) -> Path:
        active = resolved_packet(value.get("active_packet"))
        try:
            active_relative = active.relative_to(active_root.resolve())
        except ValueError as exc:
            raise DevelopmentDeliveryError(
                "Auto-Dev reopen intent points outside the active work-item lane"
            ) from exc
        if len(active_relative.parts) != 1 or _project_work_item_is_finished(
            active, project_path
        ):
            raise DevelopmentDeliveryError(
                "Auto-Dev reopen intent points outside the active work-item lane"
            )
        if not (
            value.get("schema") == "auto-dev-reopen-intent/v1"
            and value.get("run_id") == run_id
            and value.get("request_fingerprint") == request_fingerprint
            and value.get("request") == request
            and str(value.get("seed_work_id") or "").strip()
            and str(value.get("created_at") or "").strip()
        ):
            raise DevelopmentDeliveryError(
                "reopen run id is already bound to different inputs, Health evidence, "
                "or repository selection"
            )
        return active

    def validate_reopen_receipt(path: Path, active_packet: Path) -> dict[str, Any]:
        value = _read_mapping(path)
        prior_finished = resolved_packet(value.get("finished_packet"))
        if not (
            value.get("schema") == "auto-dev-reopen/v1"
            and value.get("run_id") == run_id
            and value.get("reason") == reason
            and value.get("requested_stage") == requested_stage
            and value.get("canonical_work_id") == canonical_work_id
            and value.get("request_fingerprint") == request_fingerprint
            and value.get("repository") == selected_repository
            and value.get("finished_autodev_sha256") == finished_autodev_sha256
            and value.get("health_receipt") == health_receipt_ref
            and value.get("health_sha256") == health_sha256
            and value.get("context") == context_provenance
            and prior_finished == finished_packet
            and resolved_packet(value.get("active_packet")) == active_packet
        ):
            raise DevelopmentDeliveryError(
                "existing reopen receipt does not match this exact immutable-history request"
            )
        return value

    def launch(active_packet: Path, receipt: Path) -> dict[str, Any]:
        launched = start_development_run(
            root,
            domain,
            project,
            [ticket],
            titles={ticket: title},
            run_id=run_id,
            repository_id=repository_id,
            base_branch=base_branch,
            context_selection_override=launch_context_override,
            auto_dev_mode="single_stage",
            requested_stage=requested_stage,
            goal=requested_stage,
            provision_worktree=True,
            selected_work_item=active_packet,
            adopt_existing=not (active_packet / "autodev.json").is_file(),
            apply=True,
        )
        rows = [row for row in launched.get("tasks", []) if isinstance(row, Mapping)]
        failures = [row for row in rows if row.get("error")]
        successful = [
            row
            for row in rows
            if not row.get("error")
            and row.get("state_ref")
            and isinstance(row.get("worktree"), Mapping)
        ]
        with _file_lock(intent_lock):
            intent = _read_mapping(intent_path)
            validate_intent(intent)
            intent["state"] = "launched" if len(successful) == 1 and not failures else "provisioning_failed"
            intent["updated_at"] = utc_now()
            intent["delivery_run"] = str(project_path / "state" / "development-runs" / run_id)
            if successful:
                intent["task_state_ref"] = str(successful[0]["state_ref"])
                intent["worktree"] = dict(successful[0]["worktree"])
            _atomic_json(intent_path, intent)
        if failures or len(successful) != 1:
            detail = failures[0].get("error") if failures else "fresh worktree receipt is missing"
            raise DevelopmentDeliveryError(
                f"Auto-Dev reopen is durably staged but provisioning failed; rerun the same "
                f"command after correcting the cause: {detail}"
            )
        return launched

    if canonical_packet != finished_packet:
        if _project_work_item_lane(canonical_packet, project_path) != "02-active":
            raise DevelopmentDeliveryError(
                "canonical work item does not point to the selected finished packet or a valid reopen"
            )
        prior_receipt = (
            canonical_packet / "artifacts" / "auto-dev-reopen" / "reopen.json"
        )
        if not prior_receipt.is_file() or not intent_path.is_file():
            raise DevelopmentDeliveryError(
                "canonical work item does not have a complete durable reopen transaction"
            )
        validate_reopen_receipt(prior_receipt, canonical_packet)
        prior_intent = _read_mapping(intent_path)
        validate_intent(prior_intent)
        if not apply:
            return {
                **plan,
                "schema": "auto-dev-reopen-result/v1",
                "status": "already_reopened",
                "active_packet": str(canonical_packet),
                "reopen_receipt": str(prior_receipt),
                "autodev_path": str(canonical_packet / "autodev.json"),
            }
        was_launched = prior_intent.get("state") == "launched"
        launched = launch(canonical_packet, prior_receipt)
        return {
            **plan,
            "schema": "auto-dev-reopen-result/v1",
            "status": "already_reopened" if was_launched else "reopened",
            "active_packet": str(canonical_packet),
            "reopen_receipt": str(prior_receipt),
            "autodev_path": str(canonical_packet / "autodev.json"),
            "delivery": launched,
        }

    if (
        canonical.get("state") not in canonical_work_items.TERMINAL_STATES
        or canonical.get("attention") != "closed"
    ):
        raise DevelopmentDeliveryError(
            "canonical work item must still be terminal and closed; use only the explicit "
            "Auto-Dev reopen workflow"
        )
    if canonical.get("worktree_path") or canonical.get("branch"):
        raise DevelopmentDeliveryError(
            "finished canonical work still has live worktree pointers; rerun Health before reopen"
        )
    if not apply:
        return plan

    with _file_lock(intent_lock):
        if intent_path.is_file():
            intent = _read_mapping(intent_path)
            active_packet = validate_intent(intent)
        else:
            created_at = utc_now()
            seed_work_id = (
                f"{next_work_item_index(project_path):03d}_"
                f"{_slug(ticket).replace('-', '_')}_reopen_"
                f"{_slug(run_id).replace('-', '_')}"
            )
            active_name = dated_name(
                seed_work_id,
                when=created_at,
                policy=load_artifact_naming_policy(root),
                scope="work_items",
            )
            active_packet = active_root / active_name
            intent = {
                "schema": "auto-dev-reopen-intent/v1",
                "run_id": run_id,
                "request_fingerprint": request_fingerprint,
                "request": request,
                "seed_work_id": seed_work_id,
                "active_packet": str(active_packet),
                "state": "planned",
                "created_at": created_at,
                "updated_at": created_at,
            }
            _atomic_json(intent_path, intent)

        connection = connect_state(default_db_path(root))
        try:
            live = canonical_work_items.get(connection, canonical_work_id)
        finally:
            connection.close()
        if live is None:
            raise DevelopmentDeliveryError("canonical work disappeared during reopen")
        live_packet = resolved_packet(live.get("packet_path"))
        if live_packet != finished_packet:
            raise DevelopmentDeliveryError(
                "canonical packet changed during reopen preflight; no new packet was created"
            )
        if (
            live.get("state") not in canonical_work_items.TERMINAL_STATES
            or live.get("attention") != "closed"
            or live.get("worktree_path")
            or live.get("branch")
        ):
            raise DevelopmentDeliveryError(
                "canonical work changed during reopen preflight; rerun Health or inspect the work state"
            )

        existing_metadata = _read_mapping(active_packet / "work.yml")
        if existing_metadata and existing_metadata.get("id") != active_packet.name:
            raise DevelopmentDeliveryError(
                "planned reopen packet path is occupied by a different work item"
            )
        create_project_work_item(
            root,
            domain,
            project,
            title=title,
            summary=(
                f"Receipt-backed {requested_stage} follow-up for {ticket}. The completed packet "
                f"at {finished_packet} remains immutable. Reason: {reason}"
            ),
            status="building",
            work_id=str(intent["seed_work_id"]),
            item_format="packet",
            naming_time=str(intent["created_at"]),
        )
        if not active_packet.is_dir():
            raise DevelopmentDeliveryError(
                "reopen did not create or recover its exact planned active packet"
            )
        receipt = active_packet / "artifacts" / "auto-dev-reopen" / "reopen.json"
        receipt_payload = {
            "schema": "auto-dev-reopen/v1",
            "run_id": run_id,
            "reason": reason,
            "requested_stage": requested_stage,
            "canonical_work_id": canonical_work_id,
            "source": {
                "system": canonical.get("source_system"),
                "key": canonical.get("source_key"),
                "url": canonical.get("source_url"),
            },
            "repository": selected_repository,
            "request_fingerprint": request_fingerprint,
            "finished_packet": str(finished_packet),
            "finished_autodev_sha256": finished_autodev_sha256,
            "health_receipt": health_receipt_ref,
            "health_sha256": health_sha256,
            "context": context_provenance,
            "active_packet": str(active_packet),
            "decision": "preserve finished history and provision fresh resources",
            "created_at": str(intent["created_at"]),
        }
        if receipt.is_file():
            validate_reopen_receipt(receipt, active_packet)
        else:
            _atomic_json(receipt, receipt_payload)

        connection = connect_state(default_db_path(root))
        try:
            live = canonical_work_items.get(connection, canonical_work_id)
            if live is None or live.get("state") not in canonical_work_items.TERMINAL_STATES:
                raise DevelopmentDeliveryError("canonical work changed during reopen commit")
            if resolved_packet(live.get("packet_path")) != finished_packet:
                raise DevelopmentDeliveryError("canonical packet changed during reopen commit")
            canonical_work_items.update(
                connection,
                canonical_work_id,
                state="building",
                attention="active",
                context_summary=(
                    f"Auto-Dev reopen run {run_id} for {ticket}; prior finished packet is "
                    f"preserved. Reason: {reason}"
                ),
                packet_path=str(active_packet),
                clear_worktree=True,
                actor="auto-dev-reopen",
                receipt_ref=str(receipt),
                verified=True,
                allow_terminal_reopen=True,
            )
            canonical_work_items.write_active_projection(connection, root)
        finally:
            connection.close()
        intent["state"] = "canonical_relinked"
        intent["updated_at"] = utc_now()
        intent["reopen_receipt"] = str(receipt)
        _atomic_json(intent_path, intent)

    launched = launch(active_packet, receipt)
    return {
        **plan,
        "schema": "auto-dev-reopen-result/v1",
        "status": "reopened",
        "active_packet": str(active_packet),
        "reopen_receipt": str(receipt),
        "autodev_path": str(active_packet / "autodev.json"),
        "delivery": launched,
    }


def _normalize_exact_legacy_family_identity(
    details: Mapping[str, Any],
    *,
    expected_repository: str,
    expected_base_branch: str,
    expected_provider: str,
    expected_source_branch: str,
    pull_request_prefix: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Normalize one exact legacy ``evidence.family`` item for refresh comparison.

    This is intentionally not a general family parser.  It admits only the
    historical GitHub shape that can be fully bound to the selected task before
    the immutable predecessor receipt is compared to a refreshed PR head.
    """

    family = details.get("family")
    if not isinstance(family, list) or len(family) != 1 or not isinstance(family[0], Mapping):
        raise DevelopmentDeliveryError(
            "legacy evidence.family identity requires exactly one object"
        )
    if any(
        details.get(field) is not None
        for field in (
            "repository",
            "base_branch",
            "provider",
            "pull_request",
            "source_branch",
            "source_head_sha",
            "source",
            "targets",
        )
    ):
        raise DevelopmentDeliveryError(
            "legacy evidence.family identity must not mix with another prior identity format"
        )
    if not (
        expected_repository.startswith("git:github.com/")
        and expected_provider == "github"
        and expected_base_branch
        and expected_source_branch
    ):
        raise DevelopmentDeliveryError(
            "legacy evidence.family identity must bind the selected GitHub task"
        )

    item = family[0]
    repository = str(item.get("repository") or "").strip()
    base_branch = str(item.get("base") or "").strip()
    provider = str(item.get("provider") or "").strip().lower()
    pull_request = item.get("pull_request")
    source_branch = str(item.get("source_branch") or "").strip()
    source_head = str(item.get("source_head") or "").strip()
    expected_legacy_repository = expected_repository.removeprefix("git:github.com/")
    if not (
        repository == expected_legacy_repository
        and base_branch == expected_base_branch
        and provider == expected_provider
        and type(pull_request) is int
        and pull_request > 0
        and source_branch == expected_source_branch
        and re.fullmatch(r"[a-fA-F0-9]{7,64}", source_head)
        and item.get("provider_readback_verified") is True
    ):
        raise DevelopmentDeliveryError(
            "legacy evidence.family identity does not exactly bind the selected task"
        )

    normalized_pull_request = f"{pull_request_prefix}{pull_request}"
    normalized = {
        **details,
        "repository": expected_repository,
        "base_branch": expected_base_branch,
        "provider": expected_provider,
        "pull_request": normalized_pull_request,
        "source_branch": expected_source_branch,
        "source_head_sha": source_head,
    }
    provenance = {
        "source": "evidence.family[0]",
        "legacy_fields": {
            "repository": repository,
            "base": base_branch,
            "provider": provider,
            "pull_request": pull_request,
            "source_branch": source_branch,
            "source_head": source_head,
        },
        "normalized_identity": {
            "repository": expected_repository,
            "base_branch": expected_base_branch,
            "provider": expected_provider,
            "pull_request": normalized_pull_request,
            "source_branch": expected_source_branch,
            "source_head_sha": source_head,
        },
    }
    return normalized, provenance


def run_development_stage(
    state_file: str | Path,
    *,
    stage: str,
    receipts: Mapping[str, str],
    idempotency_prefix: str,
) -> dict[str, Any]:
    """Record a completed manual Auto-Dev stage from typed evidence receipts."""

    state = TaskState(Path(state_file).expanduser().resolve())
    validated_payloads: dict[str, dict[str, Any]] = {}

    def receipt_payload(target: str) -> dict[str, Any] | None:
        payload = validated_payloads.get(target)
        if isinstance(payload, Mapping):
            return dict(payload)
        for item in reversed(state.read().get("receipts") or []):
            if not isinstance(item, Mapping) or item.get("state") != target:
                continue
            ref = Path(str(item.get("ref") or "")).expanduser()
            if not ref.is_file():
                continue
            expected_hash = str(item.get("sha256") or "").strip().lower()
            if expected_hash and hashlib.sha256(ref.read_bytes()).hexdigest() != expected_hash:
                raise DevelopmentDeliveryError(
                    f"immutable {target} receipt changed after its transition"
                )
            if state.read().get("work_item") and not expected_hash:
                raise DevelopmentDeliveryError(
                    f"canonical {target} receipt lacks an immutable sha256 binding"
                )
            try:
                prior = json.loads(ref.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(prior, Mapping):
                return dict(prior)
        return None

    def merged_revision() -> str | None:
        """Return the exact merged revision from this preflight or task history."""

        payload = receipt_payload("merged")
        evidence = payload.get("evidence") if isinstance(payload, Mapping) else None
        if isinstance(evidence, Mapping) and evidence.get("merge_sha"):
            return str(evidence["merge_sha"])
        return None

    def reviewed_revision() -> str | None:
        """Return the exact head revision that passed the merge-readiness gate."""

        task_value = state.read()
        ready_payload = receipt_payload("ready_for_merge")
        ready_evidence = (
            ready_payload.get("evidence") if isinstance(ready_payload, Mapping) else None
        )
        canonical = (
            str(ready_evidence.get("subject_revision") or "").strip()
            if isinstance(ready_evidence, Mapping)
            else ""
        )
        if not canonical:
            return None
        projections = [str(task_value.get("subject_revision") or "").strip()]
        autodev_ref = str(task_value.get("autodev_path") or "").strip()
        if autodev_ref:
            autodev_path = Path(autodev_ref).expanduser()
            if autodev_path.is_file():
                try:
                    autodev = json.loads(autodev_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    autodev = {}
                projections.append(str(autodev.get("subject_revision") or "").strip())
        if any(value and value != canonical for value in projections):
            raise DevelopmentDeliveryError(
                "task or autodev subject_revision drifted from the canonical ready_for_merge receipt"
            )
        return canonical

    def pull_request_authority(
        target: str,
        evidence: Mapping[str, Any],
    ) -> dict[str, str]:
        """Return and validate the provider identity for one PR milestone."""
        try:
            return validate_pull_request_authority(state.read(), evidence, target)
        except AutoDevStateError as exc:
            raise DevelopmentDeliveryError(str(exc)) from exc

    def prior_pull_request_authority(target: str) -> dict[str, str]:
        payload = receipt_payload(target)
        evidence = payload.get("evidence") if isinstance(payload, Mapping) else None
        if not isinstance(evidence, Mapping):
            raise DevelopmentDeliveryError(
                f"delivery task lacks typed {target} pull-request authority"
            )
        return pull_request_authority(target, evidence)

    def require_same_pull_request(
        target: str,
        authority: Mapping[str, str],
        prior_target: str,
        prior: Mapping[str, str],
    ) -> None:
        if not same_pull_request_authority(authority, prior):
            raise DevelopmentDeliveryError(
                f"{target} receipt PR authority must match {prior_target}"
            )

    def supersession_identifier(item: Mapping[str, Any]) -> str:
        return str(
            item.get("supersession_id")
            or item.get("release_propagation_wrapper")
            or ""
        ).strip()

    def pending_subject_supersessions(
        task_value: Mapping[str, Any],
    ) -> list[Mapping[str, Any]]:
        """Return every refreshed PR head that lacks fresh review authority."""

        resolutions = task_value.get("subject_supersession_resolutions")
        resolved = {
            supersession_identifier(item)
            for item in resolutions or []
            if isinstance(item, Mapping)
        }
        pending: list[Mapping[str, Any]] = []
        supersessions = task_value.get("subject_supersessions")
        for item in supersessions or []:
            if not isinstance(item, Mapping):
                continue
            identifier = supersession_identifier(item)
            if not identifier or identifier in resolved:
                continue
            if all(
                str(item.get(field) or "").strip()
                for field in ("from_subject_revision", "to_source_head_sha")
            ):
                pending.append(item)
        return pending

    def pending_subject_supersession(
        task_value: Mapping[str, Any],
    ) -> Mapping[str, Any] | None:
        """Return the newest refreshed head without fresh review authority."""

        pending = pending_subject_supersessions(task_value)
        return pending[-1] if pending else None

    def persist_delivery_revision_metadata() -> dict[str, Any]:
        """Keep reviewed-head and terminal merge/deploy revisions distinct."""

        merge_sha = merged_revision()
        ready_payload = receipt_payload("ready_for_merge")
        ready_evidence = (
            ready_payload.get("evidence") if isinstance(ready_payload, Mapping) else None
        )
        review_sha = (
            str(ready_evidence.get("subject_revision") or "").strip()
            if isinstance(ready_evidence, Mapping)
            else ""
        )
        deploy_payload = receipt_payload("post_deploy_validation")
        deploy_evidence = (
            deploy_payload.get("evidence") if isinstance(deploy_payload, Mapping) else None
        )
        changed = False
        with _file_lock(state.path.with_suffix(state.path.suffix + ".lock")):
            task_value = state.read()
            if review_sha and task_value.get("subject_revision") != review_sha:
                task_value["subject_revision"] = review_sha
                changed = True
            pending_supersessions = pending_subject_supersessions(task_value)
            pending_supersession = (
                pending_supersessions[-1] if pending_supersessions else None
            )
            if (
                pending_supersession is not None
                and review_sha
                and review_sha
                == str(pending_supersession.get("to_source_head_sha") or "").strip()
            ):
                task_value.setdefault("subject_supersession_resolutions", []).extend(
                    {
                        "supersession_id": supersession_identifier(item),
                        "subject_revision": review_sha,
                        "recorded_at": utc_now(),
                    }
                    for item in pending_supersessions
                )
                changed = True
            if merge_sha and task_value.get("terminal_revision") != merge_sha:
                task_value["terminal_revision"] = merge_sha
                changed = True
            if isinstance(deploy_payload, Mapping) and isinstance(deploy_evidence, Mapping):
                applicable = deploy_payload.get("status") != "not_required"
                deployed_revision = str(
                    deploy_evidence.get("deployed_revision") or merge_sha or ""
                ) or None
                if task_value.get("deployment_applicable") is not applicable:
                    task_value["deployment_applicable"] = applicable
                    changed = True
                if deployed_revision and task_value.get("deployed_revision") != deployed_revision:
                    task_value["deployed_revision"] = deployed_revision
                    changed = True
            if changed:
                task_value["updated_at"] = utc_now()
                _atomic_json(state.path, task_value)
        if changed:
            _refresh_portfolio_state(state.path)
            _sync_auto_dev_projection(state.path)
        return state.read()

    def validate_receipt(target: str, raw: str) -> tuple[str, dict[str, Any]]:
        path = Path(raw).expanduser().resolve()
        if not path.is_file():
            raise DevelopmentDeliveryError(f"{target} receipt file not found: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise DevelopmentDeliveryError(f"{target} receipt must be valid JSON: {path}") from exc
        if not isinstance(payload, dict) or payload.get("schema") != "development-stage-evidence/v1":
            raise DevelopmentDeliveryError(f"{target} receipt must use development-stage-evidence/v1")
        if payload.get("state") != target:
            raise DevelopmentDeliveryError(f"{target} receipt state does not match its transition")
        status = str(payload.get("status") or "")
        if status not in {
            "verified",
            "passed",
            "completed",
            "not_required",
            "deferred_to_ci",
        }:
            raise DevelopmentDeliveryError(f"{target} receipt status is not terminal evidence")
        if not str(payload.get("summary") or "").strip() or not payload.get("verified_at"):
            raise DevelopmentDeliveryError(f"{target} receipt requires summary and verified_at")
        evidence = payload.get("evidence")
        if not isinstance(evidence, (Mapping, list)) or not evidence:
            raise DevelopmentDeliveryError(f"{target} receipt requires structured evidence")
        if target == "local_validation" and isinstance(evidence, Mapping):
            unavailable = evidence.get("unavailable_check")
            if unavailable is not None and status != "deferred_to_ci":
                raise DevelopmentDeliveryError(
                    "local_validation with an unavailable check must use "
                    "status=deferred_to_ci, not passed"
                )
            if status == "deferred_to_ci":
                task_value = state.read()
                validation: Mapping[str, Any] = {}
                policy_ref = str(task_value.get("policy_receipt") or "").strip()
                policy_path = Path(policy_ref).expanduser() if policy_ref else None
                if policy_path is not None:
                    if not policy_path.is_file():
                        raise DevelopmentDeliveryError(
                            "pinned effective policy receipt is missing"
                        )
                    frozen_policies = _read_mapping(policy_path)
                    frozen_profile = _validate_effective_policy_snapshot(
                        frozen_policies,
                        require_selected_profile=True,
                    )
                    task_repository = (
                        task_value.get("repository")
                        if isinstance(task_value.get("repository"), Mapping)
                        else {}
                    )
                    if not (
                        isinstance(frozen_profile, Mapping)
                        and frozen_profile.get("repository_id")
                        == task_repository.get("id")
                        and frozen_policies.get("fingerprint")
                        == task_value.get("policy_fingerprint")
                    ):
                        raise DevelopmentDeliveryError(
                            "pinned selected repository validation policy is invalid"
                        )
                    validation = frozen_profile["validation"]
                else:
                    # Compatibility is limited to tasks that predate policy
                    # receipts entirely. A missing or legacy run receipt may
                    # never fall through to mutable base repository policy.
                    if task_value.get("policy_fingerprint"):
                        raise DevelopmentDeliveryError(
                            "pinned effective policy receipt reference is missing"
                        )
                    profile_ref = str(task_value.get("profile_source") or "").strip()
                    profile_path = (
                        Path(profile_ref).expanduser() if profile_ref else None
                    )
                    profile = (
                        _read_mapping(profile_path)
                        if profile_path is not None and profile_path.is_file()
                        else {}
                    )
                    validation = (
                        profile.get("validation")
                        if isinstance(profile.get("validation"), Mapping)
                        else {}
                    )
                if validation.get("ci_fallback_on_environment_failure") is not True:
                    raise DevelopmentDeliveryError(
                        "local_validation may defer to CI only when the pinned project "
                        "profile enables ci_fallback_on_environment_failure"
                    )
                if not isinstance(unavailable, Mapping):
                    raise DevelopmentDeliveryError(
                        "deferred_to_ci local_validation requires evidence.unavailable_check"
                    )
                if not all(
                    str(unavailable.get(key) or "").strip()
                    for key in ("command", "classification", "reason")
                ):
                    raise DevelopmentDeliveryError(
                        "deferred_to_ci unavailable_check requires command, classification, and reason"
                    )
                if unavailable.get("classification") not in {
                    "environment_unavailable",
                    "infrastructure",
                }:
                    raise DevelopmentDeliveryError(
                        "deferred_to_ci is reserved for environment or infrastructure failures"
                    )
                if not any(value == "passed" for key, value in evidence.items() if key != "unavailable_check"):
                    raise DevelopmentDeliveryError(
                        "deferred_to_ci local_validation requires at least one passed local check"
                    )
        elif status == "deferred_to_ci":
            raise DevelopmentDeliveryError(
                "deferred_to_ci is valid only for local_validation"
            )
        if status == "not_required":
            policy_stage = {
                "release_propagation": "release_propagation",
                "deployment_pending": "deploy",
                "deploying": "deploy",
                "post_deploy_validation": "deploy",
            }.get(target)
            if not policy_stage or not isinstance(evidence, Mapping):
                raise DevelopmentDeliveryError(
                    f"{target} cannot use a not_required delivery receipt"
                )
            raw_policy = str(evidence.get("policy_ref") or "").strip()
            policy_candidate = Path(raw_policy).expanduser()
            task_value = state.read()
            work_item_raw = str(task_value.get("work_item") or "").strip()
            work_item = Path(work_item_raw).expanduser().resolve() if work_item_raw else None
            candidates = [policy_candidate] if policy_candidate.is_absolute() else [
                path.parent / policy_candidate,
                *(([work_item / policy_candidate]) if work_item is not None else []),
            ]
            policy_path = next((item.resolve() for item in candidates if item.resolve().is_file()), None)
            if policy_path is None:
                raise DevelopmentDeliveryError(
                    f"{target} not_required policy_ref must resolve to a typed receipt"
                )
            try:
                policy_payload = json.loads(policy_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                raise DevelopmentDeliveryError(
                    f"{target} not_required policy receipt must be valid JSON"
                ) from exc
            durable_root = work_item if work_item is not None else state.path.parent
            autodev_raw = str(task_value.get("autodev_path") or "").strip()
            if work_item is None or not autodev_raw:
                raise DevelopmentDeliveryError(
                    f"{target} not_required requires the linked Auto-Dev work-item state"
                )
            try:
                descriptor = materialize_auto_dev_policy_decision(
                    policy_path,
                    policy_stage,
                    work_item=durable_root,
                    current=read_auto_dev_state(autodev_raw),
                )
            except AutoDevStateError as exc:
                raise DevelopmentDeliveryError(str(exc)) from exc
            canonical_evidence = dict(evidence)
            canonical_evidence["policy_ref"] = descriptor["ref"]
            canonical_evidence["policy_sha256"] = descriptor["sha256"]
            payload = {**payload, "evidence": canonical_evidence}
            evidence = canonical_evidence
        if target == "pr_open":
            if not (
                isinstance(evidence, Mapping)
                and evidence.get("readback_verified") is True
                and evidence.get("author_kind") in {"ours", "others"}
            ):
                raise DevelopmentDeliveryError(
                    "pr_open receipt requires evidence.readback_verified=true and "
                    "evidence.author_kind set to ours or others"
                )
            pull_request_authority(target, evidence)
        if target == "ready_for_merge":
            if not (
                isinstance(evidence, Mapping)
                and evidence.get("checks_verified") is True
                and evidence.get("reviews_verified") is True
                and evidence.get("readback_verified") is True
                and re.fullmatch(
                    r"[a-fA-F0-9]{7,64}", str(evidence.get("subject_revision") or "")
                )
            ):
                raise DevelopmentDeliveryError(
                    "ready_for_merge receipt requires checks_verified, reviews_verified, "
                    "readback_verified, and the exact subject_revision"
                )
            ready_authority = pull_request_authority(target, evidence)
            require_same_pull_request(
                target,
                ready_authority,
                "pr_open",
                prior_pull_request_authority("pr_open"),
            )
            pending_supersession = pending_subject_supersession(state.read())
            if pending_supersession is not None:
                expected_identity = pending_supersession.get("pull_request_identity")
                expected_head = str(
                    pending_supersession.get("to_source_head_sha") or ""
                ).strip()
                if not (
                    isinstance(expected_identity, Mapping)
                    and all(
                        str(evidence.get(field) or "").strip()
                        == str(expected_identity.get(field) or "").strip()
                        for field in (
                            "repository",
                            "base_branch",
                            "provider",
                            "pull_request",
                            "source_branch",
                        )
                    )
                    and str(evidence.get("source_head_sha") or "").strip()
                    == expected_head
                    and str(evidence.get("subject_revision") or "").strip()
                    == expected_head
                ):
                    raise DevelopmentDeliveryError(
                        "ready_for_merge receipt must bind the refreshed release-propagation "
                        "head and exact pull-request identity"
                    )
        if target == "merged":
            expected_subject = reviewed_revision()
            source_head_sha = (
                str(evidence.get("source_head_sha") or "")
                if isinstance(evidence, Mapping)
                else ""
            )
            merge_authority = (
                pull_request_authority(target, evidence)
                if isinstance(evidence, Mapping)
                else {}
            )
            if not (
                status == "completed"
                and isinstance(evidence, Mapping)
                and re.fullmatch(r"[a-fA-F0-9]{7,64}", str(evidence.get("merge_sha") or ""))
                and re.fullmatch(r"[a-fA-F0-9]{7,64}", source_head_sha)
                and expected_subject
                and source_head_sha == expected_subject
                and evidence.get("readback_verified") is True
            ):
                raise DevelopmentDeliveryError(
                    "merged receipt requires completed status, merge_sha, provider-read "
                    "source_head_sha equal to the reviewed subject_revision, provider, "
                    "pull_request, and readback_verified"
                )
            ready_authority = prior_pull_request_authority("ready_for_merge")
            require_same_pull_request(
                target,
                merge_authority,
                "ready_for_merge",
                ready_authority,
            )
            if (
                merge_authority.get("author_kind") not in {"ours", "others"}
                or merge_authority.get("author_kind") != ready_authority.get("author_kind")
            ):
                raise DevelopmentDeliveryError(
                    "merged receipt author_kind must match the provider-read ready_for_merge receipt"
                )
            task_value = state.read()
            autodev_ref = str(task_value.get("autodev_path") or "").strip()
            if task_value.get("work_item") and not autodev_ref:
                raise DevelopmentDeliveryError(
                    "Auto-Dev Merge requires the work item's canonical autodev.json linkage"
                )
            if autodev_ref:
                readiness = evidence.get("readiness_authority")
                if not isinstance(readiness, Mapping):
                    raise DevelopmentDeliveryError(
                        "merged receipt requires evidence.readiness_authority from Finalize or Review Others"
                    )
                try:
                    validate_auto_dev_readiness_authority(
                        autodev_ref,
                        readiness,
                        expected_subject=expected_subject,
                        expected_pull_request=ready_authority,
                    )
                except AutoDevStateError as exc:
                    raise DevelopmentDeliveryError(str(exc)) from exc
        if target == "post_deploy_validation":
            if status == "not_required":
                if not (
                    isinstance(evidence, Mapping)
                    and evidence.get("policy_ref")
                    and evidence.get("deployment_applicable") is False
                ):
                    raise DevelopmentDeliveryError(
                        "post_deploy_validation not_required receipt requires "
                        "policy_ref and deployment_applicable=false"
                    )
            else:
                expected_revision = merged_revision()
                deployed_revision = (
                    str(evidence.get("deployed_revision") or "")
                    if isinstance(evidence, Mapping)
                    else ""
                )
                artifact_ref = (
                    str(evidence.get("artifact_ref") or "")
                    if isinstance(evidence, Mapping)
                    else ""
                )
                environment = (
                    str(evidence.get("environment") or "")
                    if isinstance(evidence, Mapping)
                    else ""
                )
                if not (
                    expected_revision
                    and deployed_revision == expected_revision
                    and artifact_ref.strip()
                    and environment.strip()
                    and isinstance(evidence, Mapping)
                    and evidence.get("readback_verified") is True
                ):
                    raise DevelopmentDeliveryError(
                        "post_deploy_validation receipt requires the exact merged "
                        "deployed_revision, artifact_ref, environment, and readback_verified"
                    )
        if target == "delivery_complete" and not (
            isinstance(evidence, Mapping) and evidence.get("closeout_verified") is True
        ):
            raise DevelopmentDeliveryError(
                "delivery_complete receipt requires evidence.closeout_verified"
            )
        task_value = state.read()
        work_item_raw = str(task_value.get("work_item") or "").strip()
        if work_item_raw:
            work_item = Path(work_item_raw).expanduser().resolve()
            receipt_sha256 = hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            snapshot = (
                work_item
                / "artifacts"
                / "development-delivery"
                / "evidence"
                / f"{target}-{receipt_sha256[:20]}.json"
            )
            if snapshot.is_file():
                try:
                    existing = json.loads(snapshot.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    raise DevelopmentDeliveryError(
                        "immutable delivery evidence snapshot is invalid"
                    ) from exc
                if existing != payload:
                    raise DevelopmentDeliveryError("immutable delivery evidence snapshot collision")
            else:
                _atomic_json(snapshot, payload)
            path = snapshot
        return str(path), payload

    stage_name = stage.strip().lower().replace("-", "_")
    if stage_name == "release_propagation":
        current = state.read()
        autodev_ref = str(current.get("autodev_path") or "").strip()
        if current.get("work_item") and not autodev_ref:
            raise DevelopmentDeliveryError(
                "Auto-Dev release_propagation requires canonical autodev.json linkage"
            )
        if autodev_ref:
            _sync_auto_dev_projection(state.path)
            try:
                require_auto_dev_predecessors(autodev_ref, "pr_create")
            except AutoDevStateError as exc:
                raise DevelopmentDeliveryError(str(exc)) from exc
        if current.get("state") not in {"local_validation", "ready_for_merge", "merged"}:
            raise DevelopmentDeliveryError(
                "PR Create compatibility recording requires local_validation, "
                "ready_for_merge, or merged state"
            )
        raw_receipt = str(receipts.get("release_propagation") or "").strip()
        if not raw_receipt:
            raise DevelopmentDeliveryError(
                "release_propagation requires --receipt release_propagation=<ref>"
            )
        receipt, release_receipt_payload = validate_receipt("release_propagation", raw_receipt)
        qa_stage_policy = (
            current.get("auto_dev_stage_policies", {}).get("qa", {})
            if isinstance(current.get("auto_dev_stage_policies"), Mapping)
            else {}
        )
        assessment_policy = (
            qa_stage_policy.get("assessment", {})
            if isinstance(qa_stage_policy, Mapping)
            and isinstance(qa_stage_policy.get("assessment"), Mapping)
            else {}
        )
        if assessment_policy.get("always_create") is True:
            receipt_evidence = (
                release_receipt_payload.get("evidence")
                if isinstance(release_receipt_payload.get("evidence"), Mapping)
                else {}
            )
            assessment = receipt_evidence.get("qa_automation_assessment")
            if not (
                isinstance(assessment, Mapping)
                and assessment.get("schema") == "auto-dev-qa-assessment/v1"
                and assessment.get("tracker") == "jira"
                and str(assessment.get("issue_key") or "").strip()
                and str(assessment.get("parent_key") or "").strip()
                and assessment.get("readback_verified") is True
            ):
                raise DevelopmentDeliveryError(
                    "PR Create family recording requires a provider-read Jira QA "
                    "Automation Assessment subtask receipt for this project"
                )
        work_item: Path | None = None
        work_item_raw = str(current.get("work_item") or "").strip()
        if work_item_raw:
            work_item = Path(work_item_raw).expanduser().resolve()
            try:
                receipt = Path(receipt).expanduser().resolve().relative_to(work_item).as_posix()
            except ValueError as exc:
                raise DevelopmentDeliveryError(
                    "release_propagation evidence must be snapshotted inside the work item"
                ) from exc
        validated_payloads["release_propagation"] = release_receipt_payload
        legacy_output = state.path.parent / "stages" / "release-propagation.json"
        payload = {
            "schema": "development-stage-receipt/v1",
            "stage": "release_propagation",
            "task_state": current.get("state"),
            "receipt": receipt,
            "evidence_sha256": hashlib.sha256(
                json.dumps(release_receipt_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "idempotency_key": f"{idempotency_prefix}:release_propagation",
            "recorded_at": utc_now(),
        }
        output = legacy_output
        with _file_lock(state.path.with_suffix(state.path.suffix + ".lock")):
            task_value = state.read()
            superseded_ready_for_merge = False
            refreshed_subject_fence = False
            stage_receipts = (
                task_value.get("stage_receipts")
                if isinstance(task_value.get("stage_receipts"), Mapping)
                else {}
            )
            descriptor = stage_receipts.get("release_propagation")
            active_output: Path | None = None
            if isinstance(descriptor, Mapping):
                raw_ref = str(descriptor.get("ref") or "").strip()
                candidate = Path(raw_ref).expanduser() if raw_ref else None
                if candidate is None or not candidate.is_absolute():
                    raise DevelopmentDeliveryError(
                        "release propagation task binding must use an absolute immutable wrapper reference"
                    )
                candidate = candidate.resolve()
                stages_root = legacy_output.parent.resolve()
                if not candidate.is_relative_to(stages_root) or not candidate.is_file():
                    raise DevelopmentDeliveryError(
                        "release propagation task binding does not resolve inside its stage directory"
                    )
                expected_sha = str(descriptor.get("sha256") or "").strip().lower()
                actual_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
                if expected_sha != actual_sha:
                    raise DevelopmentDeliveryError(
                        "release propagation task binding no longer matches its immutable wrapper"
                    )
                active_output = candidate
            elif legacy_output.is_file():
                active_output = legacy_output

            if active_output is not None:
                try:
                    existing = json.loads(active_output.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    raise DevelopmentDeliveryError(
                        "release propagation wrapper must be valid JSON"
                    ) from exc
                if not isinstance(existing, Mapping):
                    raise DevelopmentDeliveryError("release propagation wrapper must be an object")
                if existing.get("idempotency_key") == payload["idempotency_key"]:
                    if (
                        existing.get("receipt") != payload["receipt"]
                        or existing.get("evidence_sha256") != payload["evidence_sha256"]
                    ):
                        raise DevelopmentDeliveryError(
                            "release propagation idempotency key is already bound to different evidence"
                        )
                    payload = dict(existing)
                    output = active_output
                elif (
                    existing.get("receipt") == payload["receipt"]
                    and existing.get("evidence_sha256") == payload["evidence_sha256"]
                ):
                    payload = dict(existing)
                    output = active_output
                else:
                    previous_receipt = str(existing.get("receipt") or "").strip()
                    if not Path(previous_receipt).is_absolute() and work_item is None:
                        raise DevelopmentDeliveryError(
                            "release propagation refresh requires packet-local prior evidence"
                        )
                    previous_evidence_path = (
                        Path(previous_receipt).expanduser()
                        if Path(previous_receipt).is_absolute()
                        else work_item / previous_receipt
                    )
                    if not previous_evidence_path.is_file():
                        raise DevelopmentDeliveryError(
                            "release propagation prior wrapper does not reference readable evidence"
                        )
                    try:
                        previous_evidence = json.loads(
                            previous_evidence_path.read_text(encoding="utf-8")
                        )
                    except json.JSONDecodeError as exc:
                        raise DevelopmentDeliveryError(
                            "release propagation prior evidence must be valid JSON"
                        ) from exc
                    if not isinstance(previous_evidence, Mapping):
                        raise DevelopmentDeliveryError(
                            "release propagation prior evidence must be an object"
                        )
                    previous_evidence_hash = hashlib.sha256(
                        json.dumps(
                            previous_evidence, sort_keys=True, separators=(",", ":")
                        ).encode("utf-8")
                    ).hexdigest()
                    if existing.get("evidence_sha256") != previous_evidence_hash:
                        raise DevelopmentDeliveryError(
                            "release propagation prior wrapper evidence no longer matches its digest"
                        )
                    previous_details = (
                        previous_evidence.get("evidence")
                        if isinstance(previous_evidence.get("evidence"), Mapping)
                        else {}
                    )
                    # Older PR-family receipts nested their identity under
                    # ``source`` and ``targets``.  Keep their immutable bytes
                    # intact, but normalize that shape before comparing it to a
                    # current exact-head refresh.
                    if not previous_details.get("source_head_sha"):
                        legacy_source = previous_details.get("source")
                        legacy_targets = previous_details.get("targets")
                        legacy_target = (
                            legacy_targets[0]
                            if isinstance(legacy_targets, list)
                            and legacy_targets
                            and isinstance(legacy_targets[0], Mapping)
                            else {}
                        )
                        if isinstance(legacy_source, Mapping):
                            legacy_repository = str(
                                legacy_source.get("repository") or ""
                            ).strip()
                            if legacy_repository.startswith("github:"):
                                legacy_repository = "git:github.com/" + legacy_repository.removeprefix(
                                    "github:"
                                )
                            previous_details = {
                                **previous_details,
                                "repository": legacy_repository,
                                "base_branch": str(
                                    legacy_source.get("base_branch") or ""
                                ).strip(),
                                "provider": str(
                                    legacy_target.get("provider") or "github"
                                ).strip(),
                                "pull_request": str(
                                    legacy_target.get("pull_request") or ""
                                ).strip(),
                                "source_branch": str(
                                    legacy_source.get("source_branch") or ""
                                ).strip(),
                                "source_head_sha": str(
                                    legacy_source.get("source_head_sha") or ""
                                ).strip(),
                            }
                    task_repository = (
                        task_value.get("repository")
                        if isinstance(task_value.get("repository"), Mapping)
                        else {}
                    )
                    expected_repository = str(task_repository.get("id") or "").strip()
                    expected_base_branch = str(task_repository.get("base_branch") or "").strip()
                    worktree = (
                        task_value.get("worktree")
                        if isinstance(task_value.get("worktree"), Mapping)
                        else {}
                    )
                    expected_source_branch = str(worktree.get("branch") or "").strip()
                    expected_provider = ""
                    if expected_repository.startswith(("github:", "git:github.com/")):
                        expected_provider = "github"
                    elif expected_repository.startswith(("gitlab:", "git:gitlab.com/")):
                        expected_provider = "gitlab"
                    elif expected_repository.startswith(("bitbucket:", "git:bitbucket.org/")):
                        expected_provider = "bitbucket"
                    pull_request_repository = expected_repository
                    if expected_repository.startswith("git:github.com/"):
                        pull_request_repository = "github:" + expected_repository.removeprefix(
                            "git:github.com/"
                        )
                    elif expected_repository.startswith("git:gitlab.com/"):
                        pull_request_repository = "gitlab:" + expected_repository.removeprefix(
                            "git:gitlab.com/"
                        )
                    elif expected_repository.startswith("git:bitbucket.org/"):
                        pull_request_repository = "bitbucket:" + expected_repository.removeprefix(
                            "git:bitbucket.org/"
                        )
                    pull_request_prefix = f"{pull_request_repository}#"
                    legacy_family_identity_normalization: dict[str, Any] | None = None
                    if (
                        not previous_details.get("source_head_sha")
                        and "family" in previous_details
                    ):
                        (
                            previous_details,
                            legacy_family_identity_normalization,
                        ) = _normalize_exact_legacy_family_identity(
                            previous_details,
                            expected_repository=expected_repository,
                            expected_base_branch=expected_base_branch,
                            expected_provider=expected_provider,
                            expected_source_branch=expected_source_branch,
                            pull_request_prefix=pull_request_prefix,
                        )
                    # The immediate predecessor of the repository-qualified
                    # family contract stored a bare GitHub owner/repository
                    # and numeric PR.  Normalize only that exact historical
                    # shape and only when the selected task binds it to the
                    # same GitHub repository.  The original receipt remains
                    # immutable and all later identity checks stay strict.
                    legacy_repository = expected_repository.removeprefix("git:github.com/")
                    legacy_pull_request = str(previous_details.get("pull_request") or "").strip()
                    legacy_flat_github_identity = False
                    legacy_canonical_github_identity = False
                    legacy_expected_pull_request = ""
                    if (
                        expected_repository.startswith("git:github.com/")
                        and expected_provider == "github"
                        and str(previous_details.get("provider") or "").strip().lower()
                        == "github"
                        and str(previous_details.get("repository") or "").strip()
                        == legacy_repository
                        and re.fullmatch(r"[1-9][0-9]*", legacy_pull_request)
                    ):
                        previous_details = {
                            **previous_details,
                            "repository": expected_repository,
                            "pull_request": pull_request_prefix + legacy_pull_request,
                        }
                        legacy_flat_github_identity = True
                        legacy_expected_pull_request = (
                            pull_request_prefix + legacy_pull_request
                        )
                    # A later predecessor already used the canonical GitHub
                    # repository and qualified PR fields, but can still lack
                    # only source_branch.  Treat that distinct historical
                    # shape as compatible solely when every available prior
                    # identity field already binds to the selected task.
                    # Unlike the flat predecessor above, no field is
                    # normalized here.
                    canonical_pull_request = str(
                        previous_details.get("pull_request") or ""
                    ).strip()
                    canonical_pull_request_identifier = canonical_pull_request.removeprefix(
                        pull_request_prefix
                    )
                    if (
                        not legacy_flat_github_identity
                        and expected_repository.startswith("git:github.com/")
                        and expected_provider == "github"
                        and expected_base_branch
                        and not str(previous_details.get("source_branch") or "").strip()
                        and str(previous_details.get("repository") or "").strip()
                        == expected_repository
                        and str(previous_details.get("base_branch") or "").strip()
                        == expected_base_branch
                        and str(previous_details.get("provider") or "").strip().lower()
                        == "github"
                        and canonical_pull_request.startswith(pull_request_prefix)
                        and re.fullmatch(
                            r"[1-9][0-9]*", canonical_pull_request_identifier
                        )
                    ):
                        legacy_canonical_github_identity = True
                        legacy_expected_pull_request = canonical_pull_request
                    refreshed_details = (
                        release_receipt_payload.get("evidence")
                        if isinstance(release_receipt_payload.get("evidence"), Mapping)
                        else {}
                    )
                    previous_head = str(previous_details.get("source_head_sha") or "").strip()
                    refreshed_head = str(refreshed_details.get("source_head_sha") or "").strip()
                    previous_head_identity = previous_head.lower()
                    refreshed_head_identity = refreshed_head.lower()
                    provider_observed = refreshed_details.get("provider_observed")
                    supersession = refreshed_details.get("supersession")
                    superseded_head_identity = (
                        str(supersession.get("supersedes_source_head_sha") or "").strip().lower()
                        if isinstance(supersession, Mapping)
                        else ""
                    )
                    identity_fields = (
                        "repository",
                        "base_branch",
                        "provider",
                        "pull_request",
                        "source_branch",
                    )
                    refreshed_identity = {
                        field: str(refreshed_details.get(field) or "").strip()
                        for field in identity_fields
                    }
                    if not (
                        re.fullmatch(r"[a-fA-F0-9]{7,64}", previous_head)
                        and re.fullmatch(r"[a-fA-F0-9]{7,64}", refreshed_head)
                        and previous_head_identity != refreshed_head_identity
                        and refreshed_details.get("readback_verified") is True
                        and isinstance(provider_observed, Mapping)
                        and str(provider_observed.get("head_sha") or "").strip() == refreshed_head
                        and isinstance(supersession, Mapping)
                        and superseded_head_identity == previous_head_identity
                        and str(supersession.get("reason") or "").strip()
                    ):
                        raise DevelopmentDeliveryError(
                            "release propagation refresh requires provider-read new head and explicit prior-head supersession"
                        )
                    # The same immediate legacy receipt shape can omit its
                    # source branch.  Derive that one comparison field only
                    # after the selected task, the legacy record, and the
                    # provider-read successor all bind the same GitHub PR
                    # family and exact superseded head.  The immutable prior
                    # evidence is never rewritten.
                    legacy_source_branch_derived = False
                    if (
                        (
                            legacy_flat_github_identity
                            or legacy_canonical_github_identity
                        )
                        and not str(previous_details.get("source_branch") or "").strip()
                        and expected_base_branch
                        and expected_source_branch
                        and str(previous_details.get("repository") or "").strip()
                        == expected_repository
                        and str(previous_details.get("base_branch") or "").strip()
                        == expected_base_branch
                        and str(previous_details.get("provider") or "").strip().lower()
                        == expected_provider
                        and str(previous_details.get("pull_request") or "").strip()
                        == legacy_expected_pull_request
                        and refreshed_identity["repository"] == expected_repository
                        and refreshed_identity["base_branch"] == expected_base_branch
                        and refreshed_identity["provider"].lower() == expected_provider
                        and refreshed_identity["pull_request"]
                        == legacy_expected_pull_request
                        and refreshed_identity["source_branch"] == expected_source_branch
                    ):
                        previous_details = {
                            **previous_details,
                            "source_branch": expected_source_branch,
                        }
                        legacy_source_branch_derived = True
                    previous_identity = {
                        field: str(previous_details.get(field) or "").strip()
                        for field in identity_fields
                    }
                    if not all(previous_identity.values()) or not all(refreshed_identity.values()):
                        raise DevelopmentDeliveryError(
                            "release propagation refresh requires complete prior and new PR identity"
                        )
                    for label, identity in (
                        ("prior", previous_identity),
                        ("new", refreshed_identity),
                    ):
                        if not re.fullmatch(r".+#[1-9][0-9]*", identity["pull_request"]):
                            raise DevelopmentDeliveryError(
                                "release propagation refresh "
                                f"{label} pull_request must contain a non-empty numeric identifier"
                            )
                    for field in identity_fields:
                        if refreshed_identity[field] != previous_identity[field]:
                            raise DevelopmentDeliveryError(
                                "release propagation refresh must retain the same " + field
                            )
                    if not (
                        expected_repository
                        and expected_base_branch
                        and expected_source_branch
                        and previous_identity["repository"] == expected_repository
                        and previous_identity["base_branch"] == expected_base_branch
                        and previous_identity["source_branch"] == expected_source_branch
                    ):
                        raise DevelopmentDeliveryError(
                            "release propagation refresh identity must match the selected task repository, base branch, and worktree branch"
                        )
                    if expected_provider and previous_identity["provider"].lower() != expected_provider:
                        raise DevelopmentDeliveryError(
                            "release propagation refresh provider must match the selected task repository"
                        )
                    for label, identity in (
                        ("prior", previous_identity),
                        ("new", refreshed_identity),
                    ):
                        pull_request = identity["pull_request"]
                        identifier = pull_request.removeprefix(pull_request_prefix)
                        if not (
                            pull_request.startswith(pull_request_prefix)
                            and re.fullmatch(r"[1-9][0-9]*", identifier)
                        ):
                            raise DevelopmentDeliveryError(
                                "release propagation refresh "
                                f"{label} pull_request must be qualified by the selected task repository "
                                "and contain a non-empty numeric identifier"
                            )
                    if task_value.get("state") not in {"local_validation", "ready_for_merge"}:
                        raise DevelopmentDeliveryError(
                            "release propagation refresh is only allowed from local_validation or an "
                            "unmerged ready_for_merge task"
                        )
                    if task_value.get("state") == "ready_for_merge":
                        ready_payload = receipt_payload("ready_for_merge")
                        ready_evidence = (
                            ready_payload.get("evidence")
                            if isinstance(ready_payload, Mapping)
                            else {}
                        )
                        ready_repository = str(
                            ready_evidence.get("repository") or ""
                        ).strip()
                        ready_base_branch = str(
                            ready_evidence.get("base_branch") or ""
                        ).strip()
                        ready_provider = str(
                            ready_evidence.get("provider") or ""
                        ).strip()
                        ready_pull_request = str(
                            ready_evidence.get("pull_request") or ""
                        ).strip()
                        # The same immediate predecessor that emitted a flat
                        # GitHub PR-family receipt could record its immutable
                        # ready-for-merge authority with a bare numeric PR.
                        # Qualify that value only for this comparison and only
                        # after its repository, base, and provider bind it to
                        # the selected task; never rewrite the receipt.
                        if (
                            expected_repository.startswith("git:github.com/")
                            and expected_provider == "github"
                            and ready_repository == expected_repository
                            and ready_base_branch == expected_base_branch
                            and ready_provider.lower() == "github"
                            and re.fullmatch(r"[1-9][0-9]*", ready_pull_request)
                        ):
                            ready_pull_request = pull_request_prefix + ready_pull_request
                        autodev_subject = ""
                        if autodev_ref and Path(autodev_ref).expanduser().is_file():
                            autodev_subject = str(
                                _read_mapping(Path(autodev_ref).expanduser()).get("subject_revision")
                                or ""
                            ).strip()
                        if not (
                            isinstance(ready_evidence, Mapping)
                            and ready_evidence.get("checks_verified") is True
                            and ready_evidence.get("reviews_verified") is True
                            and ready_evidence.get("readback_verified") is True
                            and ready_repository == expected_repository
                            and ready_base_branch == expected_base_branch
                            and ready_provider.lower() == expected_provider
                            and ready_pull_request == previous_identity["pull_request"]
                            and str(ready_evidence.get("source_head_sha") or "").strip()
                            == previous_head
                            and str(ready_evidence.get("subject_revision") or "").strip()
                            == previous_head
                            and str(task_value.get("subject_revision") or "").strip()
                            == previous_head
                            and (not autodev_subject or autodev_subject == previous_head)
                        ):
                            raise DevelopmentDeliveryError(
                                "ready_for_merge supersession requires the canonical prior review "
                                "authority for the superseded PR head"
                            )
                        superseded_ready_for_merge = True
                    payload["supersedes"] = {
                        "wrapper_ref": str(active_output),
                        "wrapper_sha256": hashlib.sha256(active_output.read_bytes()).hexdigest(),
                        "evidence_sha256": previous_evidence_hash,
                        "source_head_sha": previous_head,
                    }
                    if legacy_source_branch_derived:
                        legacy_normalization = {
                            "field": "source_branch",
                            "source": "selected_task.worktree.branch",
                            "value": expected_source_branch,
                        }
                    if legacy_family_identity_normalization is not None:
                        payload["supersedes"]["legacy_identity_normalization"] = (
                            legacy_family_identity_normalization
                        )
                    elif legacy_source_branch_derived:
                        if legacy_canonical_github_identity:
                            legacy_normalization["identity_shape"] = (
                                "canonical_qualified_github"
                            )
                        payload["supersedes"]["legacy_identity_normalization"] = (
                            legacy_normalization
                        )
                    supersession_key = hashlib.sha256(
                        json.dumps(
                            {
                                "idempotency_key": payload["idempotency_key"],
                                "receipt": payload["receipt"],
                                "evidence_sha256": payload["evidence_sha256"],
                                "supersedes": payload["supersedes"],
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest()
                    refreshed_subject_fence = (
                        superseded_ready_for_merge
                        or pending_subject_supersession(task_value) is not None
                    )
                    output = (
                        legacy_output.parent
                        / "release-propagation"
                        / f"{supersession_key[:20]}.json"
                    )
                    if output.is_file():
                        stored = json.loads(output.read_text(encoding="utf-8"))
                        stored_without_timestamp = (
                            {
                                key: value
                                for key, value in stored.items()
                                if key not in {"recorded_at", "task_state"}
                            }
                            if isinstance(stored, Mapping)
                            else None
                        )
                        payload_without_timestamp = {
                            key: value
                            for key, value in payload.items()
                            if key not in {"recorded_at", "task_state"}
                        }
                        if stored_without_timestamp != payload_without_timestamp:
                            raise DevelopmentDeliveryError(
                                "release propagation supersession wrapper collision"
                            )
                        payload = dict(stored)
                    else:
                        _atomic_json(output, payload)
            else:
                _atomic_json(output, payload)
            task_value.setdefault("stage_receipts", {})["release_propagation"] = {
                "ref": str(output),
                "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            }
            if refreshed_subject_fence:
                supersession_id = f"release-propagation:{supersession_key}"
                existing_fences = task_value.setdefault("subject_supersessions", [])
                if not any(
                    isinstance(item, Mapping)
                    and str(item.get("supersession_id") or "") == supersession_id
                    for item in existing_fences
                ):
                    existing_fences.append(
                        {
                            "supersession_id": supersession_id,
                            "from_subject_revision": payload["supersedes"]["source_head_sha"],
                            "to_source_head_sha": refreshed_head,
                            "pull_request_identity": refreshed_identity,
                            "release_propagation_wrapper": str(output),
                            "recorded_at": utc_now(),
                        }
                    )
                task_value["state"] = "local_validation"
                task_value["subject_revision"] = None
            _atomic_json(state.path, task_value)
        state.emit(
            event_type="development.stage.release_propagated",
            idempotency_key=payload["idempotency_key"],
            payload={
                "ticket": current.get("ticket"),
                "receipt": receipt,
                "invalidated_ready_for_merge": superseded_ready_for_merge,
            },
        )
        _sync_auto_dev_projection(state.path)
        return payload
    normalized = "closeout" if stage_name in {"cleanup", "merge_deployment_cleanup"} else stage_name
    if normalized not in DEVELOPMENT_STAGE_RANGES:
        choices = ", ".join([*DEVELOPMENT_STAGE_RANGES, "release_propagation"])
        raise DevelopmentDeliveryError(f"stage must be one of: {choices}")
    start_name, end_name = DEVELOPMENT_STAGE_RANGES[normalized]
    current = state.read()
    autodev_ref = str(current.get("autodev_path") or "").strip()
    predecessor_target = {
        # The predecessor helper validates stages before this target, so
        # review_self correctly requires the completed PR Create stage without
        # treating its own eventual ready_for_merge projection as a prerequisite.
        "review": "review_self",
        "merge": "merge",
        "deploy": "deploy",
        "closeout": "closeout",
    }.get(normalized)
    if current.get("work_item") and predecessor_target and not autodev_ref:
        raise DevelopmentDeliveryError(
            f"Auto-Dev {normalized} requires the work item's canonical autodev.json linkage"
        )
    if autodev_ref and predecessor_target:
        _sync_auto_dev_projection(state.path)
        try:
            require_auto_dev_predecessors(autodev_ref, predecessor_target)
        except AutoDevStateError as exc:
            raise DevelopmentDeliveryError(str(exc)) from exc
    current_name = str(current.get("state"))
    if current_name == end_name:
        current = persist_delivery_revision_metadata()
        _refresh_portfolio_state(state.path)
        _sync_auto_dev_projection(state.path)
        return current
    if current_name not in FORWARD_STATES:
        raise DevelopmentDeliveryError(f"cannot run {normalized} from state {current_name}")
    current_index = FORWARD_STATES.index(current_name)
    start_index = FORWARD_STATES.index(start_name)
    end_index = FORWARD_STATES.index(end_name)
    if current_index < start_index or current_index > end_index:
        raise DevelopmentDeliveryError(
            f"{normalized} expects a state from {start_name} through {end_name}; got {current_name}"
        )
    required_targets = list(FORWARD_STATES[current_index + 1 : end_index + 1])
    validated: dict[str, str] = {}
    # Preflight the entire stage before the first state mutation.
    for target in required_targets:
        raw_receipt = str(receipts.get(target) or "").strip()
        if not raw_receipt:
            raise DevelopmentDeliveryError(f"{normalized} requires --receipt {target}=<ref>")
        validated[target], validated_payloads[target] = validate_receipt(target, raw_receipt)
    for target in required_targets:
        current = state.transition(
            target,
            receipt=validated[target],
            idempotency_key=f"{idempotency_prefix}:{target}",
        )
    return persist_delivery_revision_metadata()


HISTORICAL_DELIVERY_RECONCILIATION_SCHEMA = "auto-dev-historical-delivery-reconciliation/v1"


def reconcile_historical_delivery(
    state_file: str | Path,
    *,
    evidence_file: str | Path,
    idempotency_key: str,
    apply: bool = False,
) -> dict[str, Any]:
    """Bind a legacy ``worktree_ready`` task to provider-read delivery evidence.

    This is deliberately not a shortcut for Closeout: callers must provide a
    complete, typed receipt for every missing delivery state.  The function
    first cross-checks the reviewed head, merge, release, and installed
    revision, then snapshots the supplied proof inside the packet before any
    state transition.  It never deletes or relocates a packet or worktree.
    """
    task = TaskState(Path(state_file).expanduser().resolve())
    current = task.read()
    if current.get("state") != "worktree_ready":
        raise DevelopmentDeliveryError(
            "historical reconciliation requires an exact legacy worktree_ready task"
        )
    work_item_raw = str(current.get("work_item") or "").strip()
    autodev_raw = str(current.get("autodev_path") or "").strip()
    if not work_item_raw or not autodev_raw:
        raise DevelopmentDeliveryError(
            "historical reconciliation requires linked packet and autodev.json state"
        )
    work_item = Path(work_item_raw).expanduser().resolve()
    autodev = Path(autodev_raw).expanduser().resolve()
    if not work_item.is_dir() or not autodev.is_file():
        raise DevelopmentDeliveryError("historical reconciliation packet linkage is unreadable")
    try:
        evidence_path = resolve_evidence_file(evidence_file)
    except AutoDevStateError as exc:
        raise DevelopmentDeliveryError(str(exc)) from exc
    try:
        source = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DevelopmentDeliveryError("historical reconciliation evidence must be valid JSON") from exc
    if not isinstance(source, Mapping) or source.get("schema") != HISTORICAL_DELIVERY_RECONCILIATION_SCHEMA:
        raise DevelopmentDeliveryError(
            f"historical reconciliation evidence must use {HISTORICAL_DELIVERY_RECONCILIATION_SCHEMA}"
        )
    subject = str(source.get("subject_revision") or "").strip()
    terminal = str(source.get("terminal_revision") or "").strip()
    if not re.fullmatch(r"[a-fA-F0-9]{7,64}", subject) or not re.fullmatch(r"[a-fA-F0-9]{7,64}", terminal):
        raise DevelopmentDeliveryError("historical reconciliation requires exact subject_revision and terminal_revision")
    merge = source.get("merge")
    release = source.get("release")
    install = source.get("install")
    receipts = source.get("delivery_receipts")
    if not all(isinstance(item, Mapping) for item in (merge, release, install, receipts)):
        raise DevelopmentDeliveryError("historical reconciliation requires merge, release, install, and delivery_receipts objects")
    if not (
        merge.get("readback_verified") is True
        and str(merge.get("source_head_sha") or "") == subject
        and str(merge.get("merge_sha") or "") == terminal
        and str(merge.get("provider") or "").strip()
        and str(merge.get("pull_request") or "").strip()
        and str(merge.get("repository") or "").strip()
        and merge.get("author_kind") in {"ours", "others"}
    ):
        raise DevelopmentDeliveryError("historical merge evidence does not bind the reviewed head to the exact merged revision")
    if not (
        release.get("readback_verified") is True
        and str(release.get("revision") or "") == terminal
        and str(release.get("tag") or "").strip()
    ):
        raise DevelopmentDeliveryError("historical release evidence must read back a tag bound to terminal_revision")
    if not (
        install.get("readback_verified") is True
        and str(install.get("revision") or "") == terminal
        and str(install.get("artifact_ref") or "").strip()
        and str(install.get("environment") or "").strip()
    ):
        raise DevelopmentDeliveryError("historical install evidence must read back the exact terminal_revision")
    required = list(FORWARD_STATES[FORWARD_STATES.index("worktree_ready") + 1 :])
    if set(receipts) != set(required):
        raise DevelopmentDeliveryError("historical reconciliation must provide one receipt for every missing delivery state")
    normalized: dict[str, dict[str, Any]] = {}
    for name in required:
        row = receipts.get(name)
        if not isinstance(row, Mapping) or row.get("schema") != "development-stage-evidence/v1" or row.get("state") != name:
            raise DevelopmentDeliveryError(f"historical {name} receipt is not typed for its exact delivery state")
        if not str(row.get("summary") or "").strip() or not row.get("verified_at") or not isinstance(row.get("evidence"), (Mapping, list)):
            raise DevelopmentDeliveryError(f"historical {name} receipt lacks terminal structured evidence")
        normalized[name] = dict(row)
    pr_keys = ("provider", "pull_request", "repository", "author_kind")
    for name in ("pr_open", "ready_for_merge", "merged"):
        row = normalized[name].get("evidence")
        if not isinstance(row, Mapping) or any(str(row.get(key) or "") != str(merge.get(key) or "") for key in pr_keys):
            raise DevelopmentDeliveryError(f"historical {name} receipt does not match the provider-read merge authority")
    if normalized["ready_for_merge"]["evidence"].get("subject_revision") != subject:
        raise DevelopmentDeliveryError("historical ready_for_merge receipt does not match subject_revision")
    merged_evidence = normalized["merged"]["evidence"]
    if not isinstance(merged_evidence, Mapping) or merged_evidence.get("source_head_sha") != subject or merged_evidence.get("merge_sha") != terminal:
        raise DevelopmentDeliveryError("historical merged receipt does not match the reviewed and terminal revisions")
    deployed = normalized["post_deploy_validation"]["evidence"]
    if not isinstance(deployed, Mapping) or deployed.get("deployed_revision") != terminal or deployed.get("artifact_ref") != install.get("artifact_ref") or deployed.get("environment") != install.get("environment"):
        raise DevelopmentDeliveryError("historical deployment receipt does not match installed provider evidence")
    # This establishes that the missing delivery ledger is compatible with the
    # already-recorded Auto-Dev predecessor chain before any durable mutation.
    try:
        require_auto_dev_predecessors(autodev, "closeout")
    except AutoDevStateError as exc:
        raise DevelopmentDeliveryError(f"historical reconciliation cannot bypass missing Auto-Dev evidence: {exc}") from exc
    digest = hashlib.sha256(json.dumps(source, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    output_dir = work_item / "artifacts" / "development-delivery" / "historical-reconciliation"
    receipt_path = output_dir / f"{digest[:20]}.json"
    plan = {
        "schema": HISTORICAL_DELIVERY_RECONCILIATION_SCHEMA,
        "status": "planned" if not apply else "reconciled",
        "task_state": str(task.path),
        "work_item": str(work_item),
        "subject_revision": subject,
        "terminal_revision": terminal,
        "receipt": str(receipt_path),
        "states": required,
        "preserved": {"packet": str(work_item), "worktree": current.get("worktree")},
    }
    if not apply:
        return plan
    output_dir.mkdir(parents=True, exist_ok=True)
    if receipt_path.exists():
        existing = _read_mapping(receipt_path)
        if existing.get("idempotency_key") != idempotency_key or existing.get("evidence_sha256") != digest:
            raise DevelopmentDeliveryError("historical reconciliation receipt already exists with different evidence")
    else:
        _atomic_json(receipt_path, {**source, "evidence_sha256": digest, "idempotency_key": idempotency_key, "reconciled_at": utc_now()})
    evidence_dir = output_dir / "receipts" / digest[:20]
    evidence_dir.mkdir(parents=True, exist_ok=True)
    refs: dict[str, str] = {}
    for name, row in normalized.items():
        path = evidence_dir / f"{name}.json"
        _atomic_json(path, row)
        refs[name] = str(path)
    for stage, start, end in (
        ("readiness", "worktree_ready", "planned"),
        ("implementation", "planned", "local_validation"),
        ("review", "local_validation", "ready_for_merge"),
        ("merge", "ready_for_merge", "merged"),
        ("deploy", "merged", "post_deploy_validation"),
        ("closeout", "post_deploy_validation", "delivery_complete"),
    ):
        selected = {name: refs[name] for name in FORWARD_STATES[FORWARD_STATES.index(start) + 1 : FORWARD_STATES.index(end) + 1]}
        run_development_stage(task.path, stage=stage, receipts=selected, idempotency_prefix=f"{idempotency_key}:{stage}")
    return {**plan, "status": "reconciled", "receipt": str(receipt_path), "task": task.read()}


def validate_workflow_contracts(repository_root: str | Path) -> list[str]:
    findings: list[str] = []
    base = expand_path(repository_root) / "harness" / "shared_factory" / "04-workflows" / "development_delivery"
    for name in WORKFLOW_NAMES:
        folder = base / name
        doc = folder / "workflow.md"
        contract = folder / "workflow.yml"
        extras = sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []
        if extras and extras != ["workflow.md", "workflow.yml"]:
            findings.append(f"{name}: expected only workflow.md and workflow.yml, found {', '.join(extras)}")
        if not doc.is_file():
            findings.append(f"{name}: missing workflow.md")
        else:
            text = doc.read_text(encoding="utf-8")
            for section in WORKFLOW_DOC_SECTIONS:
                if f"## {section}" not in text:
                    findings.append(f"{name}: workflow.md missing section {section}")
        if not contract.is_file():
            findings.append(f"{name}: missing workflow.yml")
        else:
            data = _read_mapping(contract)
            for key in ("id", "version", "owner", "inputs", "outputs", "states", "steps", "validations", "failure_modes", "events", "receipts"):
                if key not in data:
                    findings.append(f"{name}: workflow.yml missing {key}")
    return findings
