"""Canonical orchestration primitives for one-to-many programming work.

The module intentionally owns only durable coordination: project policy,
task/portfolio state, receipts, retry decisions, work-item creation, and
isolated worktree creation.  Coding remains the responsibility of the active
agent harness, while CI, review, release, and deployment remain provider
adapters selected by the project profile.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence
import uuid

import yaml

from .artifact_naming import dated_name, load_artifact_naming_policy
from .lifecycle import create_project_work_item
from .policy_plane import PolicyLayer, PolicyPlaneError, public_policy_plane, resolve_markdown_plane
from .scaffold import (
    domain_path,
    expand_path,
    normalize_domain,
    project_worktree_naming_policy,
    project_worktree_root,
    register_project_worktree,
    validate_name,
)


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
    "provider_unavailable",
    "lease_expired",
    "ci_failed",
    "review_findings",
    "test_failed",
}
WORKFLOW_NAMES = (
    "readiness_and_context",
    "isolated_implementation",
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
DEVELOPMENT_POLICY_PLANES = ("dev_standards", "qa_gates", "gitflow_topology")


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


def _read_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise DevelopmentDeliveryError(f"expected a mapping: {path}")
    return value


def project_root(root: str | Path, domain: str, project: str) -> Path:
    path = domain_path(expand_path(root), normalize_domain(domain)) / "02-projects" / validate_name(project, "project")
    if not (path / "project.yml").is_file():
        raise DevelopmentDeliveryError(f"project not found: {domain}/{project}")
    return path


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
    for section in ("tracker", "repository", "worktrees", "work_items", "validation", "review", "merge", "recovery"):
        if not isinstance(profile.get(section), Mapping):
            errors.append(f"{section} must be a mapping")
    repository = profile.get("repository") if isinstance(profile.get("repository"), Mapping) else {}
    if not repository.get("root"):
        errors.append("repository.root is required")
    if not repository.get("base_branch"):
        errors.append("repository.base_branch is required")
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
    return errors


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
) -> dict[str, Any]:
    """Resolve a 1-N development policy folder list with stable provenance."""

    if plane not in DEVELOPMENT_POLICY_PLANES:
        raise DevelopmentDeliveryError(
            f"policy plane must be one of {', '.join(DEVELOPMENT_POLICY_PLANES)}"
        )
    os_root = expand_path(root)
    domain_root = domain_path(os_root, normalize_domain(domain))
    project_path = project_root(os_root, domain, project)
    profile, profile_source = load_development_profile(os_root, domain, project)
    policies = profile.get("policies") if isinstance(profile.get("policies"), Mapping) else {}
    configured = policies.get(plane) if isinstance(policies.get(plane), Mapping) else {}
    paths = configured.get("paths") if isinstance(configured, Mapping) else None
    if paths is None and isinstance(profile.get(plane), Mapping):
        paths = profile[plane].get("paths")
    if paths is not None and not isinstance(paths, list):
        raise DevelopmentDeliveryError(f"policies.{plane}.paths must be a list")
    if paths:
        layers = [
            PolicyLayer(
                scope=f"configured_{index:02d}",
                root=_policy_path(
                    str(raw), os_root=os_root, domain_root=domain_root, project_path=project_path
                ),
                rank=index,
            )
            for index, raw in enumerate(paths)
        ]
    else:
        layers = [
            PolicyLayer("root", os_root / "harness" / "shared_factory" / "05-knowledge" / plane, 0),
            PolicyLayer("domain", domain_root / "05-knowledge" / plane, 1),
            PolicyLayer("project", project_path / "config" / plane, 2),
        ]
    try:
        result = resolve_markdown_plane(os_root, layers, explicit_files=explicit_files)
    except PolicyPlaneError as exc:
        raise DevelopmentDeliveryError(str(exc)) from exc
    public = public_policy_plane(result, include_body=False)
    public.update(
        {
            "schema": "development-policy-plane/v1",
            "plane": plane,
            "domain": normalize_domain(domain),
            "project": validate_name(project, "project"),
            "profile_source": str(profile_source),
        }
    )
    return public


def resolve_development_policies(root: str | Path, domain: str, project: str) -> dict[str, Any]:
    """Resolve every development policy plane consumed by an SDLC run."""

    planes = {
        plane: resolve_development_policy(root, domain, project, plane)
        for plane in DEVELOPMENT_POLICY_PLANES
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            {name: value["fingerprint"] for name, value in planes.items()},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema": "development-effective-policies/v1",
        "domain": normalize_domain(domain),
        "project": validate_name(project, "project"),
        "fingerprint": fingerprint,
        "planes": planes,
    }


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
        state = self.read()
        current = str(state["state"])
        if state.get("last_transition_key") == idempotency_key:
            return state
        if not receipt.strip():
            raise DevelopmentDeliveryError("every transition requires a receipt")
        if not _legal_transition(current, target):
            raise DevelopmentDeliveryError(f"illegal transition: {current} -> {target}")
        now = utc_now()
        state.update({"state": target, "updated_at": now, "last_transition_key": idempotency_key})
        state.setdefault("receipts", []).append({"state": target, "ref": receipt, "recorded_at": now})
        _atomic_json(self.path, state)
        self.emit(
            event_type="development.task.transitioned",
            idempotency_key=idempotency_key,
            payload={"ticket": state["ticket"], "from": current, "to": target, "receipt": receipt},
        )
        return state

    def fail(self, *, kind: str, detail: str, receipt: str, idempotency_key: str) -> dict[str, Any]:
        state = self.read()
        if state.get("last_failure_key") == idempotency_key:
            return state
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
        self.emit(
            event_type="development.task.failed",
            idempotency_key=idempotency_key,
            payload={"ticket": state["ticket"], **state["failure"], "attempt": attempts},
        )
        return state

    def recover(self, *, receipt: str, idempotency_key: str) -> dict[str, Any]:
        state = self.read()
        failure = state.get("failure") if isinstance(state.get("failure"), Mapping) else {}
        retry_state = failure.get("retry_state")
        if not failure.get("recoverable") or not retry_state:
            raise DevelopmentDeliveryError("task has no recoverable failure")
        state["state"] = retry_state
        state["failure"] = None
        state["updated_at"] = utc_now()
        state.setdefault("receipts", []).append({"state": retry_state, "ref": receipt, "recorded_at": utc_now()})
        _atomic_json(self.path, state)
        self.emit(
            event_type="development.task.recovered",
            idempotency_key=idempotency_key,
            payload={"ticket": state["ticket"], "to": retry_state, "receipt": receipt},
        )
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
        state = self.read()
        if state.get("last_heartbeat_key") == idempotency_key:
            return state
        if state.get("state") in TERMINAL_STATES:
            raise DevelopmentDeliveryError("cannot heartbeat a terminal task")
        now = datetime.now(timezone.utc).replace(microsecond=0)
        until = (now + timedelta(minutes=lease_minutes)).isoformat().replace("+00:00", "Z")
        state["lease"] = {"owner": owner, "heartbeat_at": now.isoformat().replace("+00:00", "Z"), "until": until}
        state["updated_at"] = now.isoformat().replace("+00:00", "Z")
        state["last_heartbeat_key"] = idempotency_key
        _atomic_json(self.path, state)
        self.emit(
            event_type="development.task.heartbeat",
            idempotency_key=idempotency_key,
            payload={"ticket": state["ticket"], "owner": owner, "until": until},
        )
        return state


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:48] or "task"


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
    name = f"{_slug(ticket)}-{_slug(title)}"[:72].rstrip("-")
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
            "resumed": True,
        }
    destination.parent.mkdir(parents=True, exist_ok=True)
    created = runner(["git", "-C", str(repo), "worktree", "add", "-b", branch, str(destination), base_sha])
    if created.returncode != 0:
        raise DevelopmentDeliveryError((created.stderr or created.stdout or "git worktree add failed").strip())
    register_project_worktree(os_root, domain, project, name, path=destination)
    return {"name": name, "path": str(destination), "branch": branch, "base_sha": base_sha, "resumed": False}


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


def start_development_run(
    root: str | Path,
    domain: str,
    project: str,
    tickets: Sequence[str],
    *,
    titles: Mapping[str, str] | None = None,
    run_id: str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    if not tickets:
        raise DevelopmentDeliveryError("at least one tracker ticket is required")
    profile, source = load_development_profile(root, domain, project)
    effective_policies = resolve_development_policies(root, domain, project)
    project_path = project_root(root, domain, project)
    started_at = datetime.now(timezone.utc)
    run_id = run_id or dated_name(
        f"dev-{started_at.strftime('%H%M%SZ')}-{uuid.uuid4().hex[:6]}",
        when=started_at,
        policy=load_artifact_naming_policy(root),
        scope="development_runs",
    )
    run_dir = project_path / "state" / "development-runs" / run_id
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
        "policy_sources": {
            name: [item["source_ref"] for item in value["sources"]]
            for name, value in effective_policies["planes"].items()
        },
    }
    if not apply:
        return plan
    portfolio_path = run_dir / "portfolio.json"
    if run_dir.exists() and not portfolio_path.is_file():
        raise DevelopmentDeliveryError(f"run directory exists without a portfolio receipt: {run_dir}")
    if portfolio_path.is_file():
        existing = json.loads(portfolio_path.read_text(encoding="utf-8"))
        if existing.get("tickets") != plan["tickets"]:
            raise DevelopmentDeliveryError("run id already belongs to a different ticket portfolio")
        plan = existing
        requested_titles = dict(plan.get("titles") or requested_titles)
        policy_path = run_dir / "effective-policies.json"
        if policy_path.is_file():
            run_policies = json.loads(policy_path.read_text(encoding="utf-8"))
            if not isinstance(run_policies, dict) or run_policies.get("schema") != "development-effective-policies/v1":
                raise DevelopmentDeliveryError(f"invalid effective policy receipt: {policy_path}")
        else:
            # Backfill early runs once. Resumes thereafter remain pinned to
            # this immutable policy snapshot.
            run_policies = effective_policies
            _atomic_json(policy_path, run_policies)
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
    recovery = profile["recovery"]
    rollup_ledger = expand_path(root) / "harness" / "shared_factory" / "00-control-plane" / "development-runs.jsonl"
    prior_rows = {row.get("ticket"): row for row in plan.get("tasks", []) if isinstance(row, Mapping)}
    task_rows: list[dict[str, Any]] = []
    for ticket in plan["tickets"]:
        title = requested_titles[ticket]
        work_id = f"{_slug(ticket).replace('-', '_')}_{_slug(title).replace('-', '_')}"
        task_dir = run_dir / "tasks" / _slug(ticket)
        state_path = task_dir / "state.json"
        if not state_path.is_file():
            _write_task_state(
                state_path,
                run_id=run_id,
                ticket=ticket,
                max_attempts=int(recovery.get("max_attempts") or 3),
                lease_minutes=int(recovery.get("lease_minutes") or 30),
                rollup_ledger=rollup_ledger,
            )
        task_state = TaskState(state_path)
        current = task_state.read()
        if current.get("state") == "worktree_ready" and current.get("worktree"):
            task_rows.append(dict(prior_rows.get(ticket) or {"ticket": ticket, "state_ref": str(state_path), **current}))
            continue
        failure = current.get("failure") if isinstance(current.get("failure"), Mapping) else {}
        if failure.get("recoverable"):
            task_state.recover(
                receipt="automatic provisioning resume",
                idempotency_key=f"{run_id}:{ticket}:auto-recover:{current.get('updated_at')}",
            )
        elif current.get("state") == "blocked":
            task_rows.append(dict(prior_rows.get(ticket) or {"ticket": ticket, "state_ref": str(state_path), "error": failure}))
            continue
        try:
            work_item = next(project_path.glob(f"work-items/02-active/*{work_id}"), None)
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
                created_dirs = [path for path in result.created if path.is_dir() and path.name.endswith(work_id)]
                work_item = created_dirs[0] if created_dirs else next(project_path.glob(f"work-items/02-active/*{work_id}"), None)
            if work_item is None:
                raise DevelopmentDeliveryError(f"work item receipt missing for {ticket}")
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
                    "recorded_at": utc_now(),
                },
            )
            transition_receipts = {
                "claimed": f"tracker:{ticket}",
                "groom_check": f"tracker:{ticket}",
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
            worktree = create_isolated_worktree(
                os_root=root,
                domain=domain,
                project=project,
                profile=profile,
                ticket=ticket,
                title=title,
            )
            task_state.transition("worktree_ready", receipt=worktree["path"], idempotency_key=f"{run_id}:{ticket}:worktree")
            current = task_state.read()
            current.update({"work_item": str(work_item), "worktree": worktree})
            _atomic_json(state_path, current)
            task_rows.append({"ticket": ticket, "state_ref": str(state_path), "work_item": str(work_item), "worktree": worktree})
        except (DevelopmentDeliveryError, OSError, subprocess.SubprocessError) as exc:
            detail = str(exc)
            kind = "provider_unavailable" if any(word in detail.lower() for word in ("fetch", "timeout", "unavailable")) else "provisioning_failed"
            failed = task_state.fail(
                kind=kind,
                detail=detail,
                receipt=str(state_path),
                idempotency_key=f"{run_id}:{ticket}:provisioning-failed:{task_state.read().get('updated_at')}",
            )
            task_rows.append({"ticket": ticket, "state_ref": str(state_path), "error": failed["failure"]})
        plan["tasks"] = task_rows
        plan["state"] = "dispatching"
        _atomic_json(portfolio_path, plan)
    task_states = [TaskState(Path(row["state_ref"])).read()["state"] for row in task_rows]
    plan.update({
        "state": "dispatching" if all(state == "worktree_ready" for state in task_states) else ("blocked" if all(state == "blocked" for state in task_states) else "partial"),
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
