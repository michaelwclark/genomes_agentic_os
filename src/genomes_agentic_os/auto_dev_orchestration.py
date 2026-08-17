"""Plain-English Auto-Dev orchestration state.

``autodev.json`` is a resumable operator projection.  It coordinates the
named Auto-Dev workflows, but it never replaces the SQLite work registry,
tracker/provider truth, or Development Delivery's receipt-backed state
machine.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence
import uuid

import yaml
from jsonschema import Draft202012Validator

from .program_run_packets import read_program_run_packet, record_program_workflow, start_program_run_packet


AUTO_DEV_SCHEMA = "auto-dev-work-item/v1"
AUTO_DEV_STAGE_EVIDENCE_SCHEMA = "auto-dev-stage-evidence/v1"
AUTO_DEV_HEALTH_EVIDENCE_SCHEMA = "auto-dev-health-evidence/v1"
AUTO_DEV_HEALTH_PREFLIGHT_SCHEMA = "auto-dev-health-preflight/v1"
AUTO_DEV_RUNTIME_CLEANUP_SCHEMA = "auto-dev-runtime-cleanup/v1"
AUTO_DEV_PACKET_MANIFEST_SCHEMA = "auto-dev-packet-manifest/v1"
ACTIVE_PR_CREATE_DELIVERY_ESCALATION_SCHEMA = "active-pr-create-delivery-escalation/v1"
_ACTIVE_PR_CREATE_DELIVERY_ESCALATION_KIND = (
    "escalate-active-nonblocked-pr-create-delivery"
)
AUTO_DEV_STAGE_ORDER = (
    "groom",
    "detective",
    "create_artifacts",
    "readiness",
    "develop",
    "document",
    "pr_create",
    "review_self",
    "review_others",
    "qa",
    "finalize",
    "validate_production_release",
    "merge",
    "release",
    "deploy",
    "closeout",
    "health",
)
AUTO_DEV_MODES = ("default", "everything", "single_stage")
AUTO_DEV_STAGE_COMMANDS = {
    "groom": "/auto-dev-grooming",
    "detective": "/auto-dev-detective",
    "create_artifacts": "/auto-dev-create-artifacts",
    "readiness": "/auto-dev-readiness",
    "develop": "/auto-dev-develop",
    "document": "/auto-dev-document",
    "pr_create": "/auto-dev-pr-create",
    "review_self": "/auto-dev-review-self",
    "review_others": "/auto-dev-review-others",
    "qa": "/auto-dev-qa",
    "finalize": "/auto-dev-finalize",
    "validate_production_release": "/auto-dev-validate-production-release",
    "release": "/auto-dev-release",
    "merge": "/auto-dev-merge",
    "deploy": "/auto-dev-deploy",
    "closeout": "/auto-dev-closeout",
    "health": "/auto-dev-health",
}
TERMINAL_STAGE_STATUSES = {"completed", "not_required"}
NON_ACTIONABLE_STAGE_STATUSES = TERMINAL_STAGE_STATUSES | {"out_of_scope"}
AUTO_DEV_STAGE_APPLICABILITY = {"required", "contextual", "disabled"}
NOT_REQUIRED_ALLOWED_STAGES = {
    "detective",
    "create_artifacts",
    "document",
    "review_others",
    "qa",
    "finalize",
    "release",
}
READINESS_AUTHORITY_STAGES = {"finalize", "review_others"}
DELIVERY_MANAGED_STAGES = {
    "readiness",
    "develop",
    "pr_create",
    "review_self",
    "merge",
    "deploy",
    "closeout",
}
REVIEW_REVISION_STAGES = {"qa", "review_others", "finalize"}
TERMINAL_REVISION_STAGES = {"release"}
REVISION_SENSITIVE_STAGES = REVIEW_REVISION_STAGES | TERMINAL_REVISION_STAGES | {"health"}
STAGE_MINIMUM_DELIVERY_STATE = {
    "qa": "worktree_ready",
    "finalize": "ready_for_merge",
    "validate_production_release": "ready_for_merge",
    "release": "merged",
    "health": "delivery_complete",
}
HEALTH_DISPOSITIONS = {"removed", "absent", "not_managed"}
HEALTH_REQUIRED_RECEIPT_KINDS = {
    "terminal_authority",
    "closeout",
    "receipt_audit",
    "resume_manifest",
    "packet_manifest",
    "resource_cleanup",
    "runtime_cleanup",
    "work_state",
    "active_index",
    "validation",
}
AUTO_DEV_PACKET_FILES = (
    "work.yml",
    "autodev.json",
    "SPEC.md",
    "PLAN.md",
    "INVESTIGATION.md",
    "JUDGMENT.md",
    "HOLDOUT_QA.md",
    "HOLDOUT_QA_RESULTS.md",
    "WORKLOG.md",
    "SUMMARY.md",
    "NEXT.md",
    "MEMORY.md",
)
AUTO_DEV_PACKET_DIRECTORIES = ("artifacts", "logs", "logs/conversations")
_PACKET_RELOCATION_ALLOWED_PATHS = {
    "autodev.json": (
        ("status",),
        ("current_stage",),
        ("next_action",),
        ("updated_at",),
        ("delivery", "work_item"),
        ("compatibility", "legacy_state_ref"),
        ("stages", "health", "status"),
        ("stages", "health", "run_ref"),
        ("stages", "health", "receipt_refs"),
        ("stages", "health", "last_verified_at"),
        ("stages", "health", "next_action"),
    ),
    "work.yml": (
        ("state",),
        ("status",),
        ("lane",),
        ("format",),
        ("updated_at",),
        ("lifecycle", "state"),
    ),
}
ORDERED_DELIVERY_STAGES = (
    "readiness",
    "develop",
    "pr_create",
    "review_self",
    "merge",
    "deploy",
    "closeout",
    "health",
)

# These workflows have lifecycle preconditions that make their relative
# position non-negotiable even when a project customizes the friendly order.
REQUIRED_STAGE_PRECEDENCE = (
    ("groom", "readiness"),
    ("detective", "readiness"),
    ("create_artifacts", "readiness"),
    ("readiness", "develop"),
    ("develop", "document"),
    ("develop", "pr_create"),
    ("pr_create", "review_self"),
    ("review_self", "review_others"),
    ("review_others", "qa"),
    ("qa", "finalize"),
    ("finalize", "validate_production_release"),
    ("validate_production_release", "merge"),
    ("finalize", "merge"),
    ("pr_create", "merge"),
    ("merge", "release"),
    ("release", "deploy"),
    ("deploy", "closeout"),
    ("document", "closeout"),
    ("closeout", "health"),
)


class AutoDevStateError(ValueError):
    """Raised when Auto-Dev orchestration state is unsafe or incomplete."""


def validate_pull_request_authority(
    task: Mapping[str, Any],
    evidence: Mapping[str, Any],
    target: str,
) -> dict[str, str]:
    """Classify one provider-read PR identity against the frozen task profile."""

    authority = {
        "provider": str(evidence.get("provider") or "").strip().lower(),
        "pull_request": str(evidence.get("pull_request") or "").strip(),
        "repository": str(evidence.get("repository") or "").strip(),
        "base_branch": str(evidence.get("base_branch") or "").strip(),
        "author_identity": str(evidence.get("author_identity") or "").strip().lower(),
        "author_kind": str(evidence.get("author_kind") or "").strip(),
    }
    if not all(
        authority[field]
        for field in (
            "provider",
            "pull_request",
            "repository",
            "base_branch",
            "author_identity",
        )
    ):
        raise AutoDevStateError(
            f"{target} requires provider, pull_request, repository, base_branch, "
            "and provider-read author_identity"
        )
    provider_prefix = "".join(
        character
        for character in authority["provider"]
        if character.isalnum() or character in {"_", "-"}
    )
    if not provider_prefix or not authority["author_identity"].startswith(
        f"{provider_prefix}:"
    ):
        raise AutoDevStateError(
            f"{target} author_identity must be qualified by its provider"
        )
    repository = task.get("repository") if isinstance(task.get("repository"), Mapping) else {}
    expected_repository = str(repository.get("id") or "").strip()
    expected_base = str(repository.get("base_branch") or "").strip()
    if not expected_repository or authority["repository"] != expected_repository:
        raise AutoDevStateError(
            f"{target} repository must match the canonical selected repository"
        )
    if not expected_base or authority["base_branch"] != expected_base:
        raise AutoDevStateError(
            f"{target} base_branch must match the canonical selected base branch"
        )
    authorship = task.get("authorship") if isinstance(task.get("authorship"), Mapping) else {}
    ours = {
        str(value).strip().lower()
        for value in authorship.get("ours") or []
        if str(value).strip()
    }
    if not ours:
        raise AutoDevStateError(
            f"{target} cannot classify authorship without task.authorship.ours"
        )
    classified = "ours" if authority["author_identity"] in ours else "others"
    if authority["author_kind"] != classified:
        raise AutoDevStateError(
            f"{target} author_kind must be derived from provider-read author_identity"
        )
    return authority


def same_pull_request_authority(
    left: Mapping[str, str], right: Mapping[str, str]
) -> bool:
    """Require every stable provider/PR/repository/authorship field to match."""

    fields = (
        "provider",
        "pull_request",
        "repository",
        "base_branch",
        "author_identity",
        "author_kind",
    )
    return all(left.get(field) and left.get(field) == right.get(field) for field in fields)


def validate_auto_dev_stage_order(stage_order: list[str] | tuple[str, ...]) -> list[str]:
    """Allow project ordering without violating lifecycle dependencies."""

    value = [str(name) for name in stage_order]
    if len(value) != len(AUTO_DEV_STAGE_ORDER) or len(value) != len(set(value)):
        raise AutoDevStateError(
            "Auto-Dev stage order must contain every canonical stage exactly once"
        )
    if set(value) != set(AUTO_DEV_STAGE_ORDER):
        raise AutoDevStateError(
            "Auto-Dev stage order must contain every canonical stage exactly once"
        )
    positions = {name: index for index, name in enumerate(value)}
    violations = [
        f"{before} before {after}"
        for before, after in REQUIRED_STAGE_PRECEDENCE
        if positions[before] >= positions[after]
    ]
    if violations:
        raise AutoDevStateError(
            "Auto-Dev stage order violates required lifecycle precedence: "
            + ", ".join(violations)
        )
    return value


def validate_auto_dev_stage_policies(value: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Validate project stage applicability while preserving policy metadata."""

    policies: dict[str, dict[str, Any]] = {
        name: {
            "applicability": (
                "contextual" if name in NOT_REQUIRED_ALLOWED_STAGES else "required"
            )
        }
        for name in AUTO_DEV_STAGE_ORDER
    }
    for raw_name, raw_policy in (value or {}).items():
        name = str(raw_name).strip().lower().replace("-", "_")
        if name not in AUTO_DEV_STAGE_ORDER:
            raise AutoDevStateError(f"unknown Auto-Dev stage policy: {name}")
        if not isinstance(raw_policy, Mapping):
            raise AutoDevStateError(f"Auto-Dev stage policy must be an object: {name}")
        policy = dict(raw_policy)
        applicability = str(policy.get("applicability") or "required").strip().lower()
        if applicability not in AUTO_DEV_STAGE_APPLICABILITY:
            raise AutoDevStateError(
                f"Auto-Dev {name} applicability must be one of: "
                + ", ".join(sorted(AUTO_DEV_STAGE_APPLICABILITY))
            )
        if applicability != "required" and name not in NOT_REQUIRED_ALLOWED_STAGES:
            raise AutoDevStateError(f"Auto-Dev {name} cannot be optional or disabled")
        policy["applicability"] = applicability
        policies[name] = policy
    return policies


def auto_dev_workflow_window(
    stage_order: list[str] | tuple[str, ...], start_stage: str, completion_stage: str
) -> list[str]:
    """Return the configured inclusive workflow window."""

    order = validate_auto_dev_stage_order(stage_order)
    if start_stage not in order or completion_stage not in order:
        raise AutoDevStateError("Auto-Dev workflow boundaries must name canonical stages")
    start = order.index(start_stage)
    completion = order.index(completion_stage)
    if start > completion:
        raise AutoDevStateError("Auto-Dev start_stage must not follow completion_stage")
    return order[start : completion + 1]


def configured_auto_dev_workflow_stages(
    current: Mapping[str, Any], *, include_health: bool = True
) -> list[str]:
    """Return the frozen configured workflow slice for one projected item."""

    stage_order = list(current.get("stage_order") or AUTO_DEV_STAGE_ORDER)
    active = auto_dev_workflow_window(
        stage_order,
        str(current.get("start_stage") or stage_order[0]),
        str(current.get("completion_stage") or stage_order[-1]),
    )
    if current.get("mode") == "single_stage" and len(active) == 1:
        # PR83 preview state could persist health -> health and thereby make
        # Health audit an empty predecessor set. Treat every target-only
        # single-stage window as legacy state whose safe lower bound is the
        # first frozen stage.
        active = stage_order[: stage_order.index(active[0]) + 1]
    return active if include_health else [stage for stage in active if stage != "health"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(value)
    temporary.replace(path)


@contextmanager
def _file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def resolve_evidence_file(raw: str | Path, flag: str = "--evidence") -> Path:
    """Reject inline JSON so a file-path flag never reports a bogus missing path.

    Passing the receipt body directly makes the JSON resolve as a relative
    filesystem path, and the resulting "not found" error reads like a path bug
    rather than the usage error it is.
    """

    text = str(raw).strip()
    if text.startswith(("{", "[")):
        raise AutoDevStateError(
            f"{flag} expects a file path, not inline JSON; write the JSON to a "
            "file first and pass that path"
        )
    path = Path(text).expanduser().resolve()
    if not path.is_file():
        raise AutoDevStateError(f"{flag} file not found: {path}")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise AutoDevStateError(f"Auto-Dev state not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AutoDevStateError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise AutoDevStateError(f"expected a JSON object: {path}")
    return value


def _portable_packet_ref(ref: Any, work_item: Path) -> str:
    """Return a readable packet-local reference after a lifecycle lane move."""

    raw = str(ref or "").strip()
    if not raw:
        return raw
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        local = (work_item / candidate).resolve()
        if local.exists() and work_item.resolve() in local.parents:
            return local.relative_to(work_item.resolve()).as_posix()
        return raw
    try:
        relative = candidate.resolve().relative_to(work_item)
    except (OSError, ValueError):
        relative = None
    if relative is not None:
        return relative.as_posix()
    if candidate.exists():
        return str(candidate)
    matching_offsets = [
        offset for offset, part in enumerate(candidate.parts) if part == work_item.name
    ]
    for offset in reversed(matching_offsets):
        rebased = work_item.joinpath(*candidate.parts[offset + 1 :])
        if rebased.exists():
            return rebased.relative_to(work_item).as_posix()
    return raw


def _relink_moved_work_item(task_path: Path, state_path: Path, current: Mapping[str, Any]) -> bool:
    """Repair delivery pointers after the lifecycle command moves a packet.

    Current packets remain at ``work-items/<item>`` while lifecycle state
    changes.  Work Item Archive Health may later move a terminal packet to
    ``work-items/99-archived/<item>``; older installs may instead have moved it
    to ``work-items/03-complete/<item>``.  Those two bounded moves are the only
    cases where the delivery projection may need its packet path repaired.
    """
    work_item = state_path.parent
    if _health_packet_location(work_item) not in {"archived", "legacy_finished"}:
        return False
    delivery = current.get("delivery") if isinstance(current.get("delivery"), Mapping) else {}
    old_raw = delivery.get("work_item") or None
    with _file_lock(task_path.with_suffix(task_path.suffix + ".lock")):
        task = _read_json(task_path)
        old_raw = task.get("work_item") or old_raw
        if not old_raw or Path(str(old_raw)).expanduser().name != work_item.name:
            raise AutoDevStateError("refusing to relink delivery state to a different work item")
        expected_domain = str(current.get("domain") or "")
        expected_project = str(current.get("project") or "")
        if expected_domain and str(task.get("domain") or "") != expected_domain:
            raise AutoDevStateError("refusing to relink delivery state across domains")
        if expected_project and str(task.get("project") or "") != expected_project:
            raise AutoDevStateError("refusing to relink delivery state across projects")
        if task.get("work_item") == str(work_item) and task.get("autodev_path") == str(state_path):
            return False
        task["work_item"] = str(work_item)
        task["autodev_path"] = str(state_path)
        task["updated_at"] = _utc_now()
        _atomic_json(task_path, task)
    return True


def _append_event(ledger: Path, event_type: str, payload: Mapping[str, Any]) -> None:
    ledger.parent.mkdir(parents=True, exist_ok=True)
    event = {"type": event_type, "occurred_at": _utc_now(), "payload": dict(payload)}
    with _file_lock(ledger.with_suffix(ledger.suffix + ".lock")):
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")


def _stage_row(name: str) -> dict[str, Any]:
    return {
        "status": "not_started",
        "owner": "agent",
        "command": AUTO_DEV_STAGE_COMMANDS[name],
        "run_ref": None,
        "receipt_refs": [],
        "last_verified_at": None,
        "next_action": f"Run {AUTO_DEV_STAGE_COMMANDS[name]}",
    }


def _state_index(state: str) -> int:
    lifecycle = (
        "discovered", "claimed", "groom_check", "context_ready", "work_item_ready",
        "worktree_ready", "planned", "implementing", "local_validation",
        "pre_pr_review", "pr_open", "ci_repair", "review_repair",
        "post_pr_review", "ready_for_merge", "merged", "deployment_pending",
        "deploying", "post_deploy_validation", "delivery_complete",
    )
    return lifecycle.index(state) if state in lifecycle else -1


def _complete_from_delivery(stages: dict[str, dict[str, Any]], task: Mapping[str, Any]) -> None:
    """Project delivery milestones onto workflow names without inventing proof."""
    state = str(task.get("state") or "")
    index = _state_index(state)
    milestones = {
        "readiness": "planned",
        "develop": "local_validation",
        "review_self": "ready_for_merge",
        "merge": "merged",
        "deploy": "post_deploy_validation",
        "closeout": "delivery_complete",
    }
    receipts = [receipt for receipt in task.get("receipts") or [] if isinstance(receipt, Mapping)]
    for name, milestone in milestones.items():
        # A PR-head refresh from ready_for_merge deliberately demotes the task
        # until a *new* Review Self receipt accepts the refreshed head.  The
        # historical receipt remains auditable, but it must not project as
        # active workflow authority while that supersession is unresolved.
        if name == "review_self" and task.get("_subject_supersession_pending"):
            continue
        if index >= _state_index(milestone):
            receipt = next(
                (item for item in reversed(receipts) if item.get("state") == milestone),
                None,
            )
            if receipt is None:
                continue
            row = stages[name]
            projected_status = "completed"
            receipt_ref = str(receipt.get("ref") or "").strip()
            if name == "deploy" and receipt_ref:
                try:
                    delivery_receipt = _read_json(Path(receipt_ref).expanduser())
                except (AutoDevStateError, OSError):
                    delivery_receipt = {}
                if delivery_receipt.get("status") == "not_required":
                    projected_status = "not_required"
            row.update(
                {
                    "status": projected_status,
                    "run_ref": receipt.get("ref") or task.get("task_state_ref"),
                    "receipt_refs": [str(receipt.get("ref"))] if receipt.get("ref") else [],
                    "last_verified_at": receipt.get("recorded_at"),
                    "next_action": None,
                }
            )
    if state == "implementing" and stages["develop"]["status"] == "not_started":
        stages["develop"]["status"] = "running"
    if state in {"pre_pr_review", "pr_open", "ci_repair", "review_repair", "post_pr_review"}:
        stages["review_self"]["status"] = "running"
        stages["qa"]["status"] = "running"
    if state in {"deployment_pending", "deploying"}:
        stages["deploy"]["status"] = "running"


def _load_stage_receipts(
    work_item: Path,
    stages: dict[str, dict[str, Any]],
    *,
    subject_revision: str | None,
    terminal_revision: str | None,
    invalidated_subject_revision: str | None = None,
    suppress_revision_sensitive_stages: bool = False,
) -> None:
    stage_dir = work_item / "artifacts" / "auto-dev-orchestration" / "stages"
    if stage_dir.is_dir():
        candidates = [*sorted(stage_dir.glob("*.json")), *sorted(stage_dir.glob("*/latest.json"))]
        for path in candidates:
            payload = _read_json(path)
            name = str(payload.get("stage") or "")
            if name not in stages:
                continue
            status = str(payload.get("status") or "")
            if status not in TERMINAL_STAGE_STATUSES:
                continue
            receipt_revision = payload.get("subject_revision")
            if (
                status == "completed"
                and name in REVISION_SENSITIVE_STAGES
                and suppress_revision_sensitive_stages
            ):
                # A pending PR-head supersession has no accepted subject yet.
                # Historical receipts remain on disk, but none can project as
                # active QA/review/finalize authority until fresh Review Self
                # binds the newest provider-read head.
                continue
            if (
                status == "completed"
                and name in REVISION_SENSITIVE_STAGES
                and invalidated_subject_revision
                and receipt_revision == invalidated_subject_revision
            ):
                # Keep old receipts immutable, but never let the obsolete
                # review/QA/finalize authority satisfy a refreshed PR head.
                continue
            expected_revision = (
                terminal_revision if name in TERMINAL_REVISION_STAGES else subject_revision
            )
            if (
                status == "completed"
                and name in REVISION_SENSITIVE_STAGES
                and expected_revision
                and receipt_revision != expected_revision
            ):
                continue
            if (
                name == "health"
                and terminal_revision
                and payload.get("terminal_revision") != terminal_revision
            ):
                continue
            projection_path = path
            if name == "health":
                _, projection_path = _health_local_receipt(
                    work_item,
                    payload.get("receipt_ref"),
                    "health latest wrapper receipt_ref",
                )
                if not projection_path.is_file() or _read_json(projection_path) != payload:
                    raise AutoDevStateError(
                        "health latest wrapper does not match its immutable receipt"
                    )
                _validate_stage_wrapper_identity(
                    work_item,
                    name,
                    projection_path,
                    payload,
                )
            stages[name].update(
                {
                    "status": status,
                    "run_ref": _portable_packet_ref(projection_path, work_item),
                    # The packet-local stage receipt embeds the validated
                    # evidence snapshot. Keep this projection portable when
                    # Health moves the packet between lifecycle lanes.
                    "receipt_refs": [
                        _portable_packet_ref(projection_path, work_item)
                    ],
                    "last_verified_at": payload.get("recorded_at"),
                    "next_action": None,
                }
            )
    delivery_stage = work_item / "artifacts" / "development-delivery" / "run.json"
    if delivery_stage.is_file():
        link = _read_json(delivery_stage)
        task_ref = link.get("task_state")
        if task_ref:
            task_path = Path(str(task_ref)).expanduser()
            task = _read_json(task_path) if task_path.is_file() else {}
            descriptor = (
                task.get("stage_receipts", {}).get("release_propagation")
                if isinstance(task.get("stage_receipts"), Mapping)
                else None
            )
            release_receipt: Path | None = None
            if isinstance(descriptor, Mapping):
                resolved = _resolve_health_receipt(
                    descriptor.get("ref"), work_item, task_path=task_path
                )
                expected_sha = str(descriptor.get("sha256") or "").strip().lower()
                if (
                    resolved is not None
                    and resolved.is_file()
                    and expected_sha
                    and hashlib.sha256(resolved.read_bytes()).hexdigest() == expected_sha
                ):
                    release_receipt = resolved
            else:
                legacy_receipt = task_path.parent / "stages" / "release-propagation.json"
                if legacy_receipt.is_file():
                    release_receipt = legacy_receipt
            if release_receipt is not None:
                wrapper = _read_json(release_receipt)
                evidence_ref = _resolve_health_receipt(
                    wrapper.get("receipt"), work_item, task_path=task_path
                )
                evidence_payload = (
                    _read_json(evidence_ref)
                    if evidence_ref is not None and evidence_ref.is_file()
                    else {}
                )
                expected_hash = hashlib.sha256(
                    json.dumps(
                        evidence_payload, sort_keys=True, separators=(",", ":")
                    ).encode("utf-8")
                ).hexdigest()
                if (
                    wrapper.get("schema") == "development-stage-receipt/v1"
                    and wrapper.get("stage") == "release_propagation"
                    and str(wrapper.get("idempotency_key") or "").strip()
                    and wrapper.get("evidence_sha256") == expected_hash
                    and evidence_payload.get("schema") == "development-stage-evidence/v1"
                    and evidence_payload.get("state") == "release_propagation"
                    and evidence_payload.get("status")
                    in {"verified", "passed", "completed", "not_required"}
                ):
                    stages["pr_create"].update(
                        {
                            "status": (
                                "not_required"
                                if evidence_payload.get("status") == "not_required"
                                else "completed"
                            ),
                            "run_ref": _portable_packet_ref(release_receipt, work_item),
                            "receipt_refs": [
                                _portable_packet_ref(release_receipt, work_item)
                            ],
                            "last_verified_at": wrapper.get("recorded_at"),
                            "next_action": None,
                        }
                    )


def _next_stage(
    stages: Mapping[str, Mapping[str, Any]],
    requested_stage: str | None,
    stage_order: tuple[str, ...] | list[str] = AUTO_DEV_STAGE_ORDER,
    *,
    start_stage: str | None = None,
    completion_stage: str | None = None,
) -> str | None:
    names = (requested_stage,) if requested_stage else (
        auto_dev_workflow_window(
            stage_order,
            start_stage or str(stage_order[0]),
            completion_stage or str(stage_order[-1]),
        )
    )
    for name in names:
        if name and stages[name].get("status") not in NON_ACTIONABLE_STAGE_STATUSES:
            return name
    return None


def _auto_dev_packet_transport(task: Mapping[str, Any]) -> dict[str, Any]:
    runtime = task.get("runtime") if isinstance(task.get("runtime"), Mapping) else {}
    provider = str(runtime.get("provider") or "").strip()
    mode = "execution_fabric" if provider == "execution_fabric" else "queue" if provider == "queue" else "direct"
    return {
        "driver": "development_delivery",
        "mode": mode,
        "queue_ref": str(runtime.get("queue_ref") or "").strip() or None,
        "worker_ref": str(runtime.get("worker_ref") or "").strip() or None,
        "attempt_ref": str(runtime.get("attempt_ref") or "").strip() or None,
        "run_ref": str(task.get("run_id") or "").strip() or None,
    }


def _auto_dev_packet_config_refs(task: Mapping[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    policy_ref = str(task.get("policy_receipt") or "").strip()
    if policy_ref:
        policy_path = Path(policy_ref).expanduser()
        refs.append(
            {
                "kind": "effective_policy",
                "ref": policy_ref,
                "sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest()
                if policy_path.is_file()
                else None,
            }
        )
    sources = task.get("policy_sources")
    if isinstance(sources, Mapping):
        for plane, values in sources.items():
            if not isinstance(values, list):
                continue
            for ref in values:
                if str(ref).strip():
                    refs.append(
                        {
                            "kind": f"policy:{plane}",
                            "ref": str(ref).strip(),
                            "sha256": None,
                        }
                    )
    context_selection = task.get("context_selection")
    if isinstance(context_selection, Mapping):
        policy_hash = str(context_selection.get("content_sha256") or "").strip() or None
        selection = (
            context_selection.get("selection")
            if isinstance(context_selection.get("selection"), Mapping)
            else {}
        )
        source_hashes = {
            str(item.get("source_ref")): str(item.get("sha256"))
            for item in selection.get("selected_documents") or []
            if isinstance(item, Mapping)
            and str(item.get("source_ref") or "").strip()
            and str(item.get("sha256") or "").strip()
        }
        context_documents = context_selection.get(
            "context_documents", context_selection.get("kits", [])
        )
        for document in context_documents or []:
            if not isinstance(document, Mapping):
                continue
            document_id = (
                str(document.get("id") or "context-policy").strip()
                or "context-policy"
            )
            for ref in document.get("source_refs") or []:
                if str(ref).strip():
                    refs.append(
                        {
                            "kind": f"context_policy:{document_id}",
                            "ref": str(ref).strip(),
                            "sha256": source_hashes.get(str(ref).strip(), policy_hash),
                        }
                    )
        rules_engine_context = context_selection.get("rules_engine_context")
        if isinstance(rules_engine_context, Mapping):
            kit = rules_engine_context.get("kit")
            if isinstance(kit, Mapping):
                kit_id = str(kit.get("id") or "rules-engine-kit").strip() or "rules-engine-kit"
                for artifact in kit.get("artifacts") or []:
                    if not isinstance(artifact, Mapping):
                        continue
                    ref = str(artifact.get("ref") or "").strip()
                    sha256 = str(artifact.get("sha256") or "").strip()
                    name = str(artifact.get("name") or "artifact").strip() or "artifact"
                    if ref and sha256:
                        refs.append(
                            {
                                "kind": f"rules_engine_kit:{kit_id}:{name}",
                                "ref": ref,
                                "sha256": sha256,
                            }
                        )
    return refs


def _auto_dev_stage_quality(
    work_item: Path,
    stage: str,
    row: Mapping[str, Any],
) -> dict[str, Any]:
    if stage != "qa" or row.get("status") == "not_required":
        return {"status": "not_applicable", "failures": []}
    raw_ref = str(row.get("run_ref") or "").strip()
    if raw_ref:
        candidate = Path(raw_ref).expanduser()
        if not candidate.is_absolute():
            candidate = work_item / candidate
        if candidate.is_file():
            wrapper = _read_json(candidate)
            snapshot = wrapper.get("evidence_snapshot") if isinstance(wrapper, Mapping) else {}
            structured = snapshot.get("evidence") if isinstance(snapshot, Mapping) else {}
            quality = structured.get("quality") if isinstance(structured, Mapping) else None
            if isinstance(quality, Mapping):
                return dict(quality)
    return {"status": "passed", "failures": []}


def _auto_dev_next_packet_stage(
    stage_order: Sequence[str], stages: Mapping[str, Mapping[str, Any]], stage: str
) -> str | None:
    try:
        start = list(stage_order).index(stage) + 1
    except ValueError:
        return None
    for candidate in stage_order[start:]:
        row = stages.get(candidate)
        if isinstance(row, Mapping) and row.get("status") != "out_of_scope":
            return candidate
    return None


def _sync_auto_dev_program_run_packet(
    task: Mapping[str, Any],
    value: Mapping[str, Any],
    work_item: Path,
) -> dict[str, str] | None:
    """Project an Everything run into the generic immutable packet contract.

    Development Delivery and the Auto-Dev projection remain authoritative. This
    adapter only observes their typed receipts and preserves the independent
    execution-versus-quality result classification for cross-program metrics.
    """

    if value.get("mode") != "everything":
        return None
    os_root = str(task.get("os_root") or "").strip()
    run_id = str(task.get("run_id") or "").strip()
    ticket = str(task.get("ticket") or "").strip()
    if not os_root or not run_id or not ticket:
        return None
    prior = value.get("run_packet") if isinstance(value.get("run_packet"), Mapping) else {}
    packet_id = str(prior.get("packet_id") or f"{run_id}-{ticket}-auto-dev")
    source = task.get("source") if isinstance(task.get("source"), Mapping) else {}
    subject = {
        "canonical_work_id": str(task.get("canonical_work_id") or "").strip(),
        "tracker_ref": f"{source.get('system') or 'tracker'}:{source.get('key') or ticket}",
        "repository": str(
            (task.get("repository") or {}).get("id")
            if isinstance(task.get("repository"), Mapping)
            else ""
        ).strip(),
    }
    descriptor = start_program_run_packet(
        os_root,
        packet_id=packet_id,
        program_id="auto_dev",
        run_id=run_id,
        title=str(task.get("title") or ticket),
        subject={key: item for key, item in subject.items() if item},
        execution=_auto_dev_packet_transport(task),
        config_refs=_auto_dev_packet_config_refs(task),
        started_at=str(value.get("created_at") or task.get("created_at") or _utc_now()),
    )
    sealed_workflows = {
        str(record.get("workflow_id") or "")
        for record in read_program_run_packet(os_root, packet_id).get("workflows", [])
        if isinstance(record, Mapping)
    }
    stages = value.get("stages") if isinstance(value.get("stages"), Mapping) else {}
    stage_order = [str(name) for name in value.get("stage_order") or AUTO_DEV_STAGE_ORDER]
    transport = _auto_dev_packet_transport(task)
    for stage in stage_order:
        row = stages.get(stage)
        if not isinstance(row, Mapping) or row.get("status") not in TERMINAL_STAGE_STATUSES:
            continue
        if stage in sealed_workflows:
            continue
        receipt_ref = str(row.get("run_ref") or "").strip()
        record_program_workflow(
            os_root,
            packet_id=packet_id,
            workflow_id=stage,
            execution={"status": "completed", "transport": transport},
            quality=_auto_dev_stage_quality(work_item, stage, row),
            idempotency_key=f"{run_id}:{ticket}:{stage}:completed",
            finished_at=str(row.get("last_verified_at") or value.get("updated_at") or _utc_now()),
            next_workflow_id=_auto_dev_next_packet_stage(stage_order, stages, stage),
            receipt_refs=[receipt_ref] if receipt_ref else [],
        )
    current_stage = str(value.get("current_stage") or "").strip()
    failure = task.get("failure") if isinstance(task.get("failure"), Mapping) else None
    # An executor handoff happens before a workflow starts. It is a durable
    # task-level pending/blocked boundary, not an immutable workflow result.
    # Recording it as execution_failed would permanently misstate a stage that
    # has not run and would prevent the later accepted execution from closing
    # the packet correctly.
    pre_execution_handoff = (
        isinstance(failure, Mapping) and failure.get("kind") == "executor_unavailable"
    )
    if failure and not pre_execution_handoff and current_stage and current_stage not in sealed_workflows:
        record_program_workflow(
            os_root,
            packet_id=packet_id,
            workflow_id=current_stage,
            execution={
                "status": "failed",
                "transport": transport,
                "failure": {
                    "kind": str(failure.get("kind") or "unexpected_exit"),
                    "reason": str(failure.get("detail") or failure.get("reason") or "task failed"),
                    "receipt_ref": str(failure.get("receipt") or "").strip() or None,
                },
            },
            quality={"status": "unknown", "failures": []},
            idempotency_key=f"{run_id}:{ticket}:{current_stage}:execution-failed",
            finished_at=str(value.get("updated_at") or _utc_now()),
            receipt_refs=[str(failure.get("receipt") or "").strip()] if failure.get("receipt") else [],
        )
    # Creating or resuming a packet does not execute its current stage. A
    # workflow result is written only after terminal stage evidence exists or
    # an actual non-handoff task failure is recorded above.
    return descriptor


def _pending_subject_supersession(task: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Return the latest PR-head refresh that lacks fresh review acceptance."""

    resolutions = task.get("subject_supersession_resolutions")
    resolved = {
        str(item.get("supersession_id") or item.get("release_propagation_wrapper") or "")
        for item in resolutions or []
        if isinstance(item, Mapping)
    }
    supersessions = task.get("subject_supersessions")
    for item in reversed(supersessions or []):
        if not isinstance(item, Mapping):
            continue
        identifier = str(
            item.get("supersession_id") or item.get("release_propagation_wrapper") or ""
        )
        if not identifier or identifier in resolved:
            continue
        if all(
            str(item.get(field) or "").strip()
            for field in ("from_subject_revision", "to_source_head_sha")
        ):
            return item
    return None


def sync_delivery_projection(task_state_path: str | Path) -> dict[str, Any] | None:
    """Refresh ``autodev.json`` from canonical delivery state when linked."""
    task_path = Path(task_state_path).expanduser().resolve()
    task = _read_json(task_path)
    work_item_raw = task.get("work_item")
    if not work_item_raw:
        return None
    work_item = Path(str(work_item_raw)).expanduser().resolve()
    if not work_item.is_dir():
        return None
    state_path = Path(str(task.get("autodev_path") or work_item / "autodev.json")).expanduser().resolve()
    with _file_lock(state_path.with_suffix(state_path.suffix + ".lock")):
        existing = _read_json(state_path) if state_path.is_file() else {}
        mode = str(task.get("auto_dev_mode") or existing.get("mode") or "single_stage")
        requested_stage = (
            task.get("requested_stage")
            if "requested_stage" in task
            else existing.get("requested_stage")
        )
        raw_stage_order = task.get("auto_dev_stage_order") or existing.get("stage_order") or AUTO_DEV_STAGE_ORDER
        if any(str(name) == "release_propagation" for name in raw_stage_order):
            # v1 placed Release Propagation after QA. PR Create is its canonical
            # owner and runs before Review Self, so alias replacement must also
            # migrate the position rather than preserving the unsafe old slot.
            stage_order = list(AUTO_DEV_STAGE_ORDER)
        else:
            stage_order = list(dict.fromkeys(str(name) for name in raw_stage_order))
        if (
            len(stage_order) == len(set(stage_order))
            and set(stage_order) < set(AUTO_DEV_STAGE_ORDER)
            and stage_order == [name for name in AUTO_DEV_STAGE_ORDER if name in stage_order]
        ):
            stage_order = list(AUTO_DEV_STAGE_ORDER)
        stage_order = validate_auto_dev_stage_order(stage_order)
        start_stage = str(
            task.get("auto_dev_start_stage")
            or existing.get("start_stage")
            or (requested_stage if requested_stage else stage_order[0])
        )
        completion_stage = str(
            task.get("auto_dev_completion_stage")
            or existing.get("completion_stage")
            or (requested_stage if requested_stage else stage_order[-1])
        )
        stage_policies = validate_auto_dev_stage_policies(
            task.get("auto_dev_stage_policies")
            if isinstance(task.get("auto_dev_stage_policies"), Mapping)
            else existing.get("stage_policies")
            if isinstance(existing.get("stage_policies"), Mapping)
            else {}
        )
        active_stages = set(
            auto_dev_workflow_window(stage_order, start_stage, completion_stage)
        )
        pending_supersession = _pending_subject_supersession(task)
        stages = {name: _stage_row(name) for name in AUTO_DEV_STAGE_ORDER}
        task_view = {
            **task,
            "task_state_ref": str(task_path),
            "_subject_supersession_pending": pending_supersession is not None,
        }
        _complete_from_delivery(stages, task_view)
        subject_revision = (
            str(task.get("subject_revision") or "") or None
            if pending_supersession is not None
            else str(task.get("subject_revision") or existing.get("subject_revision") or "") or None
        )
        terminal_revision = str(
            task.get("terminal_revision") or existing.get("terminal_revision") or ""
        ) or None
        _load_stage_receipts(
            work_item,
            stages,
            subject_revision=subject_revision,
            terminal_revision=terminal_revision,
            invalidated_subject_revision=(
                str(pending_supersession.get("from_subject_revision") or "")
                if pending_supersession is not None
                else None
            ),
            suppress_revision_sensitive_stages=pending_supersession is not None,
        )
        for name, row in stages.items():
            policy = stage_policies.get(name, {"applicability": "required"})
            row["applicability"] = policy["applicability"]
            if name not in active_stages and not (
                row.get("status") in TERMINAL_STAGE_STATUSES
                and row.get("receipt_refs")
            ):
                row.update({"status": "out_of_scope", "next_action": None})
            elif (
                row.get("status") not in TERMINAL_STAGE_STATUSES
                and policy["applicability"] == "disabled"
            ):
                row["next_action"] = (
                    f"Record typed not_required policy evidence for {name}"
                )
        current_stage = _next_stage(
            stages,
            str(requested_stage) if requested_stage else None,
            stage_order,
            start_stage=start_stage,
            completion_stage=completion_stage,
        )
        failure = task.get("failure") if isinstance(task.get("failure"), Mapping) else None
        if str(task.get("state")) == "blocked":
            status = "blocked"
        elif failure and failure.get("recoverable"):
            status = "paused"
        elif current_stage is None:
            status = "completed"
        elif any(row.get("status") == "running" for row in stages.values()):
            status = "running"
        else:
            status = "ready"
        legacy = work_item / "artifacts" / "auto-dev" / "state.json"
        value = {
            "schema": AUTO_DEV_SCHEMA,
            "work_item_id": work_item.name,
            "canonical_work_id": task.get("canonical_work_id") or existing.get("canonical_work_id"),
            "domain": task.get("domain"),
            "project": task.get("project"),
            "source": existing.get("source") or task.get("source") or {
                "system": "tracker",
                "key": task.get("ticket"),
                "url": None,
            },
            "mode": mode,
            "requested_stage": requested_stage,
            "start_stage": start_stage,
            "completion_stage": completion_stage,
            "subject_revision": subject_revision,
            "terminal_revision": terminal_revision,
            "status": status,
            "current_stage": current_stage,
            "stage_order": stage_order,
            "stage_policies": stage_policies,
            "stages": stages,
            "delivery": {
                "engine": "development_delivery",
                "state": task.get("state"),
                "goal": task.get("goal"),
                "run_id": task.get("run_id"),
                "portfolio_ref": str(task_path.parent.parent.parent / "portfolio.json"),
                "task_state_ref": str(task_path),
                "policy_receipt": task.get("policy_receipt"),
                "policy_fingerprint": task.get("policy_fingerprint"),
                "policy_sources": task.get("policy_sources") or {},
                "context_selection": task.get("context_selection"),
                "repository": task.get("repository"),
                "worktree": task.get("worktree"),
                "runtime": task.get("runtime"),
                "work_item": str(work_item),
                "terminal_revision": terminal_revision,
                "deployed_revision": task.get("deployed_revision"),
                "canonical_work_id": task.get("canonical_work_id") or existing.get("canonical_work_id"),
            },
            "run_packet": existing.get("run_packet"),
            "compatibility": {
                "legacy_state_ref": str(legacy) if legacy.is_file() else None,
                "migration_mode": "reference_only" if legacy.is_file() else "not_present",
            },
            "blocker": failure,
            "next_action": stages[current_stage]["next_action"] if current_stage else None,
            "created_at": existing.get("created_at") or _utc_now(),
            "updated_at": _utc_now(),
        }
        run_packet = _sync_auto_dev_program_run_packet(task, value, work_item)
        if run_packet is not None:
            value["run_packet"] = run_packet
        before = {key: val for key, val in existing.items() if key != "updated_at"}
        after = {key: val for key, val in value.items() if key != "updated_at"}
        changed = before != after
        if not changed and state_path.is_file():
            return existing
        _atomic_json(state_path, value)
    health_row = value.get("stages", {}).get("health", {})
    if not (
        isinstance(health_row, Mapping)
        and health_row.get("status") == "completed"
    ):
        digest = hashlib.sha256(
            json.dumps(after, sort_keys=True).encode("utf-8")
        ).hexdigest()
        _append_event(
            work_item / "artifacts" / "auto-dev-orchestration" / "events.jsonl",
            "auto_dev.projection.synced",
            {"state": value["status"], "current_stage": current_stage, "sha256": digest},
        )
    return value


def read_auto_dev_state(path: str | Path) -> dict[str, Any]:
    state_path = Path(path).expanduser().resolve()
    if state_path.is_dir():
        state_path = state_path / "autodev.json"
    value = _read_json(state_path)
    if value.get("schema") != AUTO_DEV_SCHEMA:
        raise AutoDevStateError(f"expected {AUTO_DEV_SCHEMA}: {state_path}")
    return value


def _required_text(value: Mapping[str, Any], key: str, label: str) -> str:
    result = str(value.get(key) or "").strip()
    if not result:
        raise AutoDevStateError(f"health evidence requires {label}.{key}")
    return result


def _health_local_receipt(work_item: Path, ref: Any, label: str) -> tuple[str, Path]:
    raw = str(ref or "").strip()
    if not raw:
        raise AutoDevStateError(f"health evidence requires {label}")
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise AutoDevStateError(f"health {label} must be work-item-relative")
    path = (work_item / relative).resolve()
    if work_item not in path.parents or not path.is_file():
        raise AutoDevStateError(f"health {label} is missing: {raw}")
    return relative.as_posix(), path


def _health_os_root(work_item: Path, current: Mapping[str, Any]) -> Path:
    return _health_owner_roots(work_item, current)[0]


def _health_owner_roots(
    work_item: Path, current: Mapping[str, Any]
) -> tuple[Path, Path]:
    """Return the marked OS root and exact owning project ancestor.

    Packet depth varies between the canonical single-root layout, the retained
    archive, and legacy lifecycle lanes.  Derive ownership from ``.agentic_root``
    and then prove that the state-declared project is an ancestor of the packet
    in one of the supported domain layouts.
    """

    domain = str(current.get("domain") or "").strip()
    project = str(current.get("project") or "").strip()
    if (
        not domain
        or not project
        or Path(domain).name != domain
        or Path(project).name != project
        or domain in {".", ".."}
        or project in {".", ".."}
    ):
        raise AutoDevStateError(
            "health cannot derive the owning Agentic OS root without a valid domain and project"
        )

    lineage = {work_item.resolve(), *(parent.resolve() for parent in work_item.parents)}
    for candidate in (work_item, *work_item.parents):
        if not (candidate / ".agentic_root").is_file():
            continue
        os_root = candidate.resolve()
        project_candidates = [
            os_root / "domains" / domain / "02-projects" / project,
            os_root / domain / "02-projects" / project,
        ]
        if domain == "shared_factory":
            project_candidates.append(
                os_root / "harness" / "shared_factory" / "02-projects" / project
            )
        for project_root in project_candidates:
            resolved_project = project_root.resolve()
            if resolved_project in lineage:
                return os_root, resolved_project
    raise AutoDevStateError("health cannot derive the owning Agentic OS root from the packet")


def _health_project_root(work_item: Path, current: Mapping[str, Any]) -> Path:
    return _health_owner_roots(work_item, current)[1]


def _health_packet_location(work_item: Path) -> str | None:
    """Classify one packet without treating lifecycle metadata as a directory."""

    for work_items_root in work_item.parents:
        if work_items_root.name != "work-items":
            continue
        try:
            parts = work_item.relative_to(work_items_root).parts
        except ValueError:
            return None
        if len(parts) == 1 and parts[0] not in {
            "01-intake",
            "02-active",
            "03-complete",
            "99-archived",
        }:
            return "canonical"
        if len(parts) == 2 and parts[0] == "99-archived":
            return "archived"
        if len(parts) == 2 and parts[0] == "03-complete":
            return "legacy_finished"
        return None
    return None


def _resolve_health_receipt(
    raw_ref: Any,
    work_item: Path,
    *,
    task_path: Path | None = None,
) -> Path | None:
    """Resolve a receipt, rebasing packet-local paths after an active-to-complete move."""

    raw = str(raw_ref or "").strip()
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    candidates: list[Path] = []
    if candidate.is_absolute():
        candidates.append(candidate)
    else:
        candidates.append(work_item / candidate)
        if task_path is not None:
            candidates.append(task_path.parent / candidate)
    for offset, part in enumerate(candidate.parts):
        if part == work_item.name:
            candidates.append(work_item.joinpath(*candidate.parts[offset + 1 :]))
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved.is_file():
            return resolved
    return None


def _health_task_receipt(
    task: Mapping[str, Any],
    target_state: str,
    work_item: Path,
    *,
    task_path: Path,
) -> tuple[Path, dict[str, Any]]:
    """Return the newest canonical typed receipt for one delivery milestone."""

    for item in reversed(task.get("receipts") or []):
        if not isinstance(item, Mapping) or item.get("state") != target_state:
            continue
        ref = _resolve_health_receipt(item.get("ref"), work_item, task_path=task_path)
        if ref is None:
            continue
        expected_hash = str(item.get("sha256") or "").strip().lower()
        if (
            len(expected_hash) != 64
            or hashlib.sha256(ref.read_bytes()).hexdigest() != expected_hash
        ):
            raise AutoDevStateError(
                f"health typed {target_state} receipt lacks its immutable task-state hash"
            )
        try:
            payload = json.loads(ref.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if (
            isinstance(payload, dict)
            and payload.get("schema") == "development-stage-evidence/v1"
            and payload.get("state") == target_state
        ):
            return ref, payload
    raise AutoDevStateError(
        f"health requires a readable typed {target_state} delivery receipt"
    )


def _health_pull_request_authority(
    payload: Mapping[str, Any],
    target: str,
    *,
    task: Mapping[str, Any],
) -> dict[str, str]:
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), Mapping) else {}
    return validate_pull_request_authority(task, evidence, f"health {target} receipt")


def _health_same_pull_request(
    left: Mapping[str, str],
    right: Mapping[str, str],
) -> bool:
    return same_pull_request_authority(left, right)


def _health_delivery_authority(
    current: Mapping[str, Any],
    work_item: Path,
) -> tuple[str, dict[str, Any], Path, dict[str, Any], Path, dict[str, Any]]:
    delivery = current.get("delivery") if isinstance(current.get("delivery"), Mapping) else {}
    task_ref = str(delivery.get("task_state_ref") or "").strip()
    if not task_ref:
        raise AutoDevStateError("health requires a linked Development Delivery task")
    task_path = Path(task_ref).expanduser().resolve()
    task = _read_json(task_path)
    if task.get("state") != "delivery_complete":
        raise AutoDevStateError("health requires canonical delivery state delivery_complete")
    if str(task.get("domain") or "") != str(current.get("domain") or ""):
        raise AutoDevStateError("health delivery task domain does not match autodev.json")
    if str(task.get("project") or "") != str(current.get("project") or ""):
        raise AutoDevStateError("health delivery task project does not match autodev.json")
    _, pr_open_payload = _health_task_receipt(
        task, "pr_open", work_item, task_path=task_path
    )
    _, ready_payload = _health_task_receipt(
        task, "ready_for_merge", work_item, task_path=task_path
    )
    pr_open_evidence = (
        pr_open_payload.get("evidence")
        if isinstance(pr_open_payload.get("evidence"), Mapping)
        else {}
    )
    ready_evidence = (
        ready_payload.get("evidence")
        if isinstance(ready_payload.get("evidence"), Mapping)
        else {}
    )
    pr_open_authority = _health_pull_request_authority(
        pr_open_payload, "pr_open", task=task
    )
    ready_authority = _health_pull_request_authority(
        ready_payload, "ready_for_merge", task=task
    )
    if not (
        pr_open_payload.get("status") in {"verified", "passed", "completed"}
        and pr_open_evidence.get("readback_verified") is True
        and ready_payload.get("status") in {"verified", "passed", "completed"}
        and ready_evidence.get("checks_verified") is True
        and ready_evidence.get("reviews_verified") is True
        and ready_evidence.get("readback_verified") is True
        and _health_same_pull_request(pr_open_authority, ready_authority)
    ):
        raise AutoDevStateError(
            "health requires pr_open and ready_for_merge receipts for the same provider-read pull request"
        )
    merged_path, merged_payload = _health_task_receipt(
        task, "merged", work_item, task_path=task_path
    )
    evidence = merged_payload.get("evidence") if isinstance(merged_payload, Mapping) else None
    merge_sha = str(evidence.get("merge_sha") or "") if isinstance(evidence, Mapping) else ""
    source_head_sha = (
        str(evidence.get("source_head_sha") or "") if isinstance(evidence, Mapping) else ""
    )
    reviewed_revision = str(current.get("subject_revision") or task.get("subject_revision") or "")
    merge_authority = _health_pull_request_authority(
        merged_payload, "merged", task=task
    )
    if not (
        merged_payload
        and merged_payload.get("schema") == "development-stage-evidence/v1"
        and merged_payload.get("status") == "completed"
        and 7 <= len(merge_sha) <= 64
        and all(character in "0123456789abcdefABCDEF" for character in merge_sha)
        and 7 <= len(source_head_sha) <= 64
        and all(character in "0123456789abcdefABCDEF" for character in source_head_sha)
        and reviewed_revision
        and source_head_sha == reviewed_revision
        and isinstance(evidence, Mapping)
        and evidence.get("readback_verified") is True
        and _health_same_pull_request(ready_authority, merge_authority)
    ):
        raise AutoDevStateError(
            "health requires a typed merged receipt whose provider-read source_head_sha "
            "matches the reviewed subject_revision and whose provider/ref matches the "
            "reviewed pull request"
        )
    if task.get("terminal_revision") != merge_sha:
        raise AutoDevStateError("health delivery terminal_revision does not match the merged receipt")
    closeout_path, closeout_payload = _health_task_receipt(
        task, "delivery_complete", work_item, task_path=task_path
    )
    closeout_evidence = closeout_payload.get("evidence")
    if not (
        closeout_payload.get("status") in {"verified", "passed", "completed"}
        and isinstance(closeout_evidence, Mapping)
        and closeout_evidence.get("closeout_verified") is True
    ):
        raise AutoDevStateError("health requires the typed verified Closeout receipt")
    return merge_sha, task, merged_path, merged_payload, closeout_path, closeout_payload


def _health_delivery_merge_revision(current: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """Compatibility helper used by final Health validation."""

    delivery = current.get("delivery") if isinstance(current.get("delivery"), Mapping) else {}
    work_item = Path(str(delivery.get("work_item") or "")).expanduser()
    if not work_item.is_dir():
        raise AutoDevStateError("health delivery work-item pointer is not readable")
    merge_sha, task, *_ = _health_delivery_authority(current, work_item.resolve())
    return merge_sha, task


_DELIVERY_STAGE_RECEIPT_STATES = {
    "readiness": "planned",
    "develop": "local_validation",
    "review_self": "ready_for_merge",
    "merge": "merged",
    "deploy": "post_deploy_validation",
    "closeout": "delivery_complete",
}


def _validate_health_stage_source(
    work_item: Path,
    stage: str,
    status: str,
    path: Path,
) -> dict[str, Any]:
    def validate_delivery_policy(evidence_payload: Mapping[str, Any], policy_stage: str) -> None:
        if evidence_payload.get("status") != "not_required":
            return
        structured = evidence_payload.get("evidence")
        if not isinstance(structured, Mapping):
            raise AutoDevStateError(f"{stage} not_required receipt lacks policy evidence")
        _, policy_path = _health_local_receipt(
            work_item, structured.get("policy_ref"), f"{stage} policy_ref"
        )
        if structured.get("policy_sha256") != hashlib.sha256(policy_path.read_bytes()).hexdigest():
            raise AutoDevStateError(f"{stage} policy snapshot hash no longer matches")
        _validate_policy_decision(
            _read_json(policy_path),
            policy_stage,
            work_item=work_item,
            current=read_auto_dev_state(work_item / "autodev.json"),
        )

    if stage not in DELIVERY_MANAGED_STAGES:
        return _validate_auto_dev_stage_receipt(work_item, stage, status, path)
    payload = _read_json(path)
    if stage == "pr_create":
        if not (
            payload.get("schema") == "development-stage-receipt/v1"
            and payload.get("stage") == "release_propagation"
            and str(payload.get("idempotency_key") or "").strip()
        ):
            raise AutoDevStateError("pr_create compatibility wrapper is malformed")
        _, evidence_path = _health_local_receipt(
            work_item, payload.get("receipt"), "pr_create receipt"
        )
        evidence = _read_json(evidence_path)
        actual_hash = hashlib.sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if not (
            payload.get("evidence_sha256") == actual_hash
            and evidence.get("schema") == "development-stage-evidence/v1"
            and evidence.get("state") == "release_propagation"
            and evidence.get("status")
            in {"verified", "passed", "completed", "not_required"}
        ):
            raise AutoDevStateError("pr_create evidence is missing or changed")
        validate_delivery_policy(evidence, "release_propagation")
        return payload
    expected_state = _DELIVERY_STAGE_RECEIPT_STATES.get(stage)
    if not (
        expected_state
        and payload.get("schema") == "development-stage-evidence/v1"
        and payload.get("state") == expected_state
        and payload.get("status") in {"verified", "passed", "completed", "not_required"}
        and str(payload.get("summary") or "").strip()
        and str(payload.get("verified_at") or "").strip()
    ):
        raise AutoDevStateError(f"{stage} delivery receipt is malformed or not terminal")
    validate_delivery_policy(payload, "deploy" if stage == "deploy" else stage)
    return payload


def _health_stage_receipt_path(work_item: Path, stage: str, status: str, refs: Any) -> Path:
    if not isinstance(refs, list):
        raise AutoDevStateError("health stage receipt references must be a list")
    for ref in refs:
        resolved = _resolve_health_receipt(ref, work_item)
        if resolved is not None:
            _validate_health_stage_source(work_item, stage, status, resolved)
            return resolved
    raise AutoDevStateError("health stage lacks a readable receipt")


def _validate_delivery_stage_task_binding(
    current: Mapping[str, Any],
    work_item: Path,
    stage: str,
    path: Path,
) -> None:
    if stage not in DELIVERY_MANAGED_STAGES:
        return
    task_ref = str(current.get("delivery", {}).get("task_state_ref") or "").strip()
    if not task_ref:
        raise AutoDevStateError(f"{stage} lacks its linked delivery task")
    task_path = Path(task_ref).expanduser().resolve()
    task = _read_json(task_path)
    if stage == "pr_create":
        descriptor = (
            task.get("stage_receipts", {}).get("release_propagation")
            if isinstance(task.get("stage_receipts"), Mapping)
            else None
        )
        if not isinstance(descriptor, Mapping):
            raise AutoDevStateError("pr_create lacks its immutable task binding")
        resolved = _resolve_health_receipt(
            descriptor.get("ref"), work_item, task_path=task_path
        )
        if not (
            resolved is not None
            and resolved.resolve() == path.resolve()
            and descriptor.get("sha256") == hashlib.sha256(path.read_bytes()).hexdigest()
        ):
            raise AutoDevStateError("pr_create task binding no longer matches")
        return
    target = _DELIVERY_STAGE_RECEIPT_STATES.get(stage)
    for row in reversed(task.get("receipts") or []):
        if not isinstance(row, Mapping) or row.get("state") != target:
            continue
        resolved = _resolve_health_receipt(row.get("ref"), work_item, task_path=task_path)
        if not (
            resolved is not None
            and resolved.resolve() == path.resolve()
            and row.get("sha256") == hashlib.sha256(path.read_bytes()).hexdigest()
        ):
            raise AutoDevStateError(f"{stage} receipt is not bound to immutable task history")
        return
    raise AutoDevStateError(f"{stage} lacks immutable task receipt history")


def _validate_active_pr_create_escalation_develop_predecessor(
    current: Mapping[str, Any],
    work_item: Path,
    *,
    target_stage: str,
) -> None:
    """Validate the sole AGE-190 escalation as a Develop predecessor.

    An active PR-Create escalation projects ``develop`` as completed so a
    fresh Review Self can start from its immutable PR family.  Its receipt is
    deliberately not generic implementation evidence.  It may remain the
    Develop predecessor for that same governed chain through Merge, but only
    after every intervening stage has supplied its normal immutable authority.
    """

    task_ref = str(current.get("delivery", {}).get("task_state_ref") or "").strip()
    if not task_ref:
        raise AutoDevStateError("active pr_create escalation develop predecessor lacks a task")
    task_path = Path(task_ref).expanduser().resolve()
    task = _read_json(task_path)
    histories = task.get("active_pr_create_delivery_escalations")
    if not isinstance(histories, list) or len(histories) != 1 or not isinstance(
        histories[0], Mapping
    ):
        raise AutoDevStateError(
            "active pr_create escalation develop predecessor requires one verified escalation history"
        )
    history = histories[0]
    key = str(history.get("idempotency_key") or "").strip()
    receipt_ref = str(history.get("receipt") or "").strip()
    receipt_sha256 = str(history.get("sha256") or "").strip().lower()
    if not key or not receipt_ref or len(receipt_sha256) != 64:
        raise AutoDevStateError(
            "active pr_create escalation develop predecessor history is malformed"
        )
    expected_path = (
        work_item
        / "artifacts"
        / "development-delivery"
        / "active-pr-create-delivery-escalation"
        / f"{hashlib.sha256(key.encode('utf-8')).hexdigest()[:20]}.json"
    ).resolve()
    candidate = Path(receipt_ref).expanduser()
    if not (
        candidate.is_absolute()
        and not candidate.is_symlink()
        and candidate.resolve() == expected_path
        and expected_path.is_file()
        and not expected_path.is_symlink()
    ):
        raise AutoDevStateError(
            "active pr_create escalation develop predecessor receipt is not packet-canonical"
        )
    receipt_bytes = expected_path.read_bytes()
    try:
        receipt = json.loads(receipt_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AutoDevStateError(
            "active pr_create escalation develop predecessor receipt is malformed"
        ) from exc
    if not isinstance(receipt, Mapping):
        raise AutoDevStateError(
            "active pr_create escalation develop predecessor receipt is malformed"
        )
    if hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest() != receipt_sha256:
        raise AutoDevStateError(
            "active pr_create escalation develop predecessor receipt hash changed"
        )
    escalated = receipt.get("escalated") if isinstance(receipt.get("escalated"), Mapping) else {}
    original = receipt.get("original") if isinstance(receipt.get("original"), Mapping) else {}
    delivery = current.get("delivery") if isinstance(current.get("delivery"), Mapping) else {}
    stage_order = list(AUTO_DEV_STAGE_ORDER)
    stage_policies = task.get("auto_dev_stage_policies")
    expected_contract = {
        "state": "local_validation",
        "mode": "everything",
        "requested_stage": None,
        "goal": "merge",
        "start_stage": "groom",
        "completion_stage": "merge",
        "stage_order": stage_order,
        "stage_policies": stage_policies,
    }
    expected_portfolio_contract = {
        field: expected_contract[field]
        for field in (
            "mode",
            "requested_stage",
            "goal",
            "start_stage",
            "completion_stage",
            "stage_order",
            "stage_policies",
        )
    }
    portfolio_auto_dev = (
        escalated.get("portfolio_auto_dev")
        if isinstance(escalated.get("portfolio_auto_dev"), Mapping)
        else {}
    )
    if not (
        receipt.get("schema") == ACTIVE_PR_CREATE_DELIVERY_ESCALATION_SCHEMA
        and receipt.get("kind") == _ACTIVE_PR_CREATE_DELIVERY_ESCALATION_KIND
        and receipt.get("idempotency_key") == key
        and receipt.get("recorded_at") == history.get("recorded_at")
        and original.get("task_state_ref") == str(task_path)
        and original.get("canonical_work_id") == task.get("canonical_work_id")
        and original.get("work_item") == str(work_item)
        and original.get("worktree") == task.get("worktree")
        and all(escalated.get(field) == value for field, value in expected_contract.items())
        and all(
            portfolio_auto_dev.get(field) == value
            for field, value in expected_portfolio_contract.items()
        )
    ):
        raise AutoDevStateError(
            "active pr_create escalation develop predecessor receipt contract is invalid"
        )
    matching_receipts = [
        row
        for row in task.get("receipts") or []
        if isinstance(row, Mapping)
        and row.get("state") == "local_validation"
        and row.get("ref") == receipt_ref
        and row.get("sha256") == receipt_sha256
        and row.get("recorded_at") == history.get("recorded_at")
    ]
    stages = current.get("stages") if isinstance(current.get("stages"), Mapping) else {}
    develop = stages.get("develop") if isinstance(stages.get("develop"), Mapping) else {}
    fresh_stages = (
        "review_self",
        "review_others",
        "qa",
        "finalize",
        "validate_production_release",
        "merge",
    )
    requested_stage = current.get("requested_stage")
    dispatch_selector_is_bound = (
        requested_stage == task.get("requested_stage")
        and requested_stage in {None, target_stage}
    )
    base_contract = (
        len(matching_receipts) == 1
        and current.get("mode") == "everything"
        # The immutable escalation receipt records the original Everything
        # selector. A later named-stage resume may set the coupled live task
        # and projection selector to precisely the stage being admitted.
        and dispatch_selector_is_bound
        and current.get("start_stage") == "groom"
        and current.get("completion_stage") == "merge"
        and current.get("stage_order") == stage_order
        and current.get("stage_policies") == stage_policies
        and delivery.get("goal") == "merge"
        and develop.get("status") == "completed"
        and develop.get("receipt_refs") == [receipt_ref]
    )
    if target_stage == "review_self":
        if not (
            base_contract
            and current.get("current_stage") == "review_self"
            and task.get("state") == "local_validation"
            and task.get("failure") is None
            and task.get("auto_dev_mode") == "everything"
            and task.get("goal") == "merge"
            and task.get("auto_dev_start_stage") == "groom"
            and task.get("auto_dev_completion_stage") == "merge"
            and task.get("auto_dev_stage_order") == stage_order
            and task.get("auto_dev_stage_policies") == stage_policies
            and not any(
                task.get(field)
                for field in ("subject_revision", "terminal_revision", "deployed_revision")
            )
            and delivery.get("state") == "local_validation"
            and all(
                isinstance(stages.get(stage), Mapping)
                and stages[stage].get("status") == "not_started"
                and stages[stage].get("receipt_refs") == []
                for stage in fresh_stages
            )
        ):
            raise AutoDevStateError(
                "active pr_create escalation develop predecessor grants stale downstream authority"
            )
        return
    if target_stage not in {
        "review_others",
        "qa",
        "finalize",
        "validate_production_release",
        "merge",
    }:
        raise AutoDevStateError(
            "active pr_create escalation develop predecessor is only valid through governed Merge"
        )
    subject_revision = str(task.get("subject_revision") or "").strip()
    if not (
        base_contract
        and task.get("state") == "ready_for_merge"
        and task.get("failure") is None
        and task.get("auto_dev_mode") == "everything"
        and task.get("goal") == "merge"
        and task.get("auto_dev_start_stage") == "groom"
        and task.get("auto_dev_completion_stage") == "merge"
        and task.get("auto_dev_stage_order") == stage_order
        and task.get("auto_dev_stage_policies") == stage_policies
        and len(subject_revision) >= 7
        and not any(task.get(field) for field in ("terminal_revision", "deployed_revision"))
        and delivery.get("state") == "ready_for_merge"
        and current.get("subject_revision") == subject_revision
    ):
        raise AutoDevStateError(
            "active pr_create escalation develop predecessor chain is not ready for governed Merge"
        )


def _packet_relative(path: Path, work_item: Path) -> str:
    try:
        return path.resolve().relative_to(work_item.resolve()).as_posix()
    except ValueError as exc:
        raise AutoDevStateError(f"receipt must be inside the work-item packet: {path}") from exc


def _stage_source_path(raw: Any, evidence_path: Path, work_item: Path, label: str) -> Path:
    value = str(raw or "").strip()
    if not value:
        raise AutoDevStateError(f"{label} must be a readable file reference")
    candidate = Path(value).expanduser()
    candidates = [candidate] if candidate.is_absolute() else [
        evidence_path.parent / candidate,
        work_item / candidate,
    ]
    for item in candidates:
        resolved = item.resolve()
        if resolved.is_file():
            return resolved
    raise AutoDevStateError(
        f"{label} must resolve to a file; materialize provider readback inside the work-item packet first"
    )


def _materialize_stage_source(
    source: Path,
    work_item: Path,
    *,
    stage: str,
    kind: str,
) -> dict[str, str]:
    """Copy one proof into a packet-local content-addressed snapshot."""

    payload = source.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    suffix = source.suffix if source.suffix and len(source.suffix) <= 12 else ".receipt"
    snapshot = (
        work_item
        / "artifacts"
        / "auto-dev-orchestration"
        / "proofs"
        / stage
        / f"{kind}-{digest[:20]}{suffix}"
    )
    if snapshot.is_file():
        if snapshot.read_bytes() != payload:
            raise AutoDevStateError(
                f"immutable {stage} {kind} snapshot path contains different content"
            )
    else:
        _atomic_bytes(snapshot, payload)
    return {"ref": _packet_relative(snapshot, work_item), "sha256": digest}


def _validate_policy_decision(
    payload: Mapping[str, Any],
    stage: str,
    *,
    work_item: Path | None = None,
    current: Mapping[str, Any] | None = None,
) -> None:
    required = {
        "schema",
        "work_item_id",
        "canonical_work_id",
        "domain",
        "project",
        "stage",
        "decision",
        "reason",
        "decided_by",
        "policy_fingerprint",
        "policy_source",
        "verified_at",
    }
    if set(payload) != required or not (
        payload.get("schema") == "auto-dev-stage-policy-decision/v1"
        and payload.get("stage") == stage
        and payload.get("decision") == "not_required"
        and str(payload.get("reason") or "").strip()
        and str(payload.get("decided_by") or "").strip()
        and str(payload.get("policy_fingerprint") or "").strip()
        and str(payload.get("verified_at") or "").strip()
        and isinstance(payload.get("policy_source"), Mapping)
    ):
        raise AutoDevStateError(
            f"{stage} not_required requires a strict auto-dev-stage-policy-decision/v1 receipt"
        )
    if work_item is None or current is None:
        return
    _validate_health_document_schema(
        payload,
        work_item,
        current,
        schema_name="auto-dev-stage-policy-decision.schema.json",
        label=f"{stage} policy decision",
    )
    for field in ("work_item_id", "canonical_work_id", "domain", "project"):
        if str(payload.get(field) or "") != str(current.get(field) or ""):
            raise AutoDevStateError(f"{stage} policy decision {field} does not match autodev.json")
    descriptor = payload["policy_source"]
    _, source_path = _health_local_receipt(
        work_item, descriptor.get("ref"), f"{stage} policy_source.ref"
    )
    if descriptor.get("sha256") != hashlib.sha256(source_path.read_bytes()).hexdigest():
        raise AutoDevStateError(f"{stage} policy_source hash no longer matches")
    task_ref = str(current.get("delivery", {}).get("task_state_ref") or "").strip()
    if not task_ref:
        raise AutoDevStateError(f"{stage} policy decision requires a linked delivery task")
    task = _read_json(Path(task_ref).expanduser().resolve())
    if payload.get("policy_fingerprint") != task.get("policy_fingerprint"):
        raise AutoDevStateError(
            f"{stage} policy decision fingerprint does not match the frozen delivery policy"
        )


def materialize_auto_dev_policy_decision(
    decision_file: str | Path,
    stage: str,
    *,
    work_item: Path,
    current: Mapping[str, Any],
) -> dict[str, str]:
    """Bind a not-required decision to the run policy and copy both into the packet."""

    decision_path = Path(decision_file).expanduser().resolve()
    payload = _read_json(decision_path)
    _validate_policy_decision(payload, stage)
    task_ref = str(current.get("delivery", {}).get("task_state_ref") or "").strip()
    if not task_ref:
        raise AutoDevStateError(f"{stage} policy decision requires a linked delivery task")
    task = _read_json(Path(task_ref).expanduser().resolve())
    for field in ("work_item_id", "canonical_work_id", "domain", "project"):
        if str(payload.get(field) or "") != str(current.get(field) or ""):
            raise AutoDevStateError(f"{stage} policy decision {field} does not match autodev.json")
    if payload.get("policy_fingerprint") != task.get("policy_fingerprint"):
        raise AutoDevStateError(
            f"{stage} policy decision fingerprint does not match the frozen delivery policy"
        )
    source_descriptor = payload.get("policy_source")
    if not isinstance(source_descriptor, Mapping):
        raise AutoDevStateError(f"{stage} policy decision lacks policy_source")
    source_path = _stage_source_path(
        source_descriptor.get("ref"),
        decision_path,
        work_item,
        f"{stage} policy_source.ref",
    )
    task_policy = Path(str(task.get("policy_receipt") or "")).expanduser().resolve()
    if not task_policy.is_file() or source_path != task_policy:
        raise AutoDevStateError(
            f"{stage} policy_source must be the delivery run's frozen effective policy receipt"
        )
    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    if source_descriptor.get("sha256") != source_hash:
        raise AutoDevStateError(f"{stage} policy_source hash does not match the frozen policy")
    source_snapshot = _materialize_stage_source(
        source_path, work_item, stage=stage, kind="policy-source"
    )
    canonical = json.loads(json.dumps(payload))
    canonical["policy_source"] = source_snapshot
    canonical_bytes = (
        json.dumps(canonical, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    digest = hashlib.sha256(canonical_bytes).hexdigest()
    snapshot = (
        work_item
        / "artifacts"
        / "auto-dev-orchestration"
        / "proofs"
        / stage
        / f"policy-decision-{digest[:20]}.json"
    )
    if snapshot.is_file() and snapshot.read_bytes() != canonical_bytes:
        raise AutoDevStateError("immutable policy decision snapshot collision")
    if not snapshot.is_file():
        _atomic_bytes(snapshot, canonical_bytes)
    _validate_policy_decision(canonical, stage, work_item=work_item, current=current)
    return {"ref": _packet_relative(snapshot, work_item), "sha256": digest}


def _readiness_stage_authority(
    stage: str,
    evidence: Mapping[str, Any],
    subject_revision: str | None,
) -> dict[str, str]:
    structured = evidence.get("evidence")
    if not isinstance(structured, Mapping):
        raise AutoDevStateError(f"{stage} readiness evidence must be an object")
    authority = {
        "provider": str(structured.get("provider") or "").strip().lower(),
        "pull_request": str(structured.get("pull_request") or "").strip(),
        "repository": str(structured.get("repository") or "").strip(),
        "base_branch": str(structured.get("base_branch") or "").strip(),
        "subject_revision": str(subject_revision or "").strip(),
        "author_identity": str(structured.get("author_identity") or "").strip().lower(),
        "author_kind": str(structured.get("author_kind") or "").strip(),
    }
    if not (
        authority["provider"]
        and authority["pull_request"]
        and authority["repository"]
        and authority["base_branch"]
        and authority["subject_revision"]
        and authority["author_identity"].startswith(f"{authority['provider']}:")
        and authority["author_kind"] in {"ours", "others"}
        and structured.get("readback_verified") is True
    ):
        raise AutoDevStateError(
            f"{stage} must bind provider, pull_request, repository, base_branch, "
            "subject_revision, and provider readback"
        )
    expected_author_kind = (
        "ours" if stage in {"finalize", "validate_production_release"} else "others"
    )
    if authority["author_kind"] != expected_author_kind:
        raise AutoDevStateError(
            f"{stage} can authorize only author_kind={expected_author_kind}"
        )
    if (
        stage in {"finalize", "validate_production_release"}
        and structured.get("readiness_decision") != "ready_for_merge"
    ):
        raise AutoDevStateError(
            f"{stage} must record readiness_decision=ready_for_merge and cannot execute the merge"
        )
    if stage == "validate_production_release":
        check_matrix = structured.get("check_matrix")
        if not isinstance(check_matrix, list) or not check_matrix:
            raise AutoDevStateError(
                "validate_production_release requires a non-empty check_matrix"
            )
        check_ids = {
            str(row.get("check_id") or "").strip()
            for row in check_matrix
            if isinstance(row, Mapping)
        }
        required_check_ids = {
            "jira_github_alignment",
            "exact_release_identity",
            "qa_per_jira",
            "whole_diff_policy",
            "risk_gates",
            "artifact_rollback_observability",
            "runtime_consumer_contracts",
        }
        missing_check_ids = sorted(required_check_ids - check_ids)
        if missing_check_ids:
            raise AutoDevStateError(
                "validate_production_release check_matrix is missing: "
                + ", ".join(missing_check_ids)
            )
        if not isinstance(structured.get("qa_runs"), list) or not structured[
            "qa_runs"
        ]:
            raise AutoDevStateError(
                "validate_production_release requires qa_runs per Jira item"
            )
        for field, identity_field in (
            ("consumer_contract_matrix", "consumer_id"),
            ("tenant_impact_matrix", "tenant"),
        ):
            matrix = structured.get(field)
            if not isinstance(matrix, list) or not matrix:
                raise AutoDevStateError(
                    f"validate_production_release requires non-empty {field}"
                )
            invalid = [
                row
                for row in matrix
                if not isinstance(row, Mapping)
                or row.get("status") != "pass"
                or not str(row.get(identity_field) or "").strip()
                or not str(row.get("evidence_ref") or "").strip()
            ]
            if invalid:
                raise AutoDevStateError(
                    f"validate_production_release requires passing, evidence-backed {field}"
                )
        if not str(structured.get("compatibility_strategy") or "").strip():
            raise AutoDevStateError(
                "validate_production_release requires compatibility_strategy"
            )
        for field in ("contract_test_runs", "runtime_readbacks"):
            if not isinstance(structured.get(field), list) or not structured[field]:
                raise AutoDevStateError(
                    f"validate_production_release requires non-empty {field}"
                )
        if not str(structured.get("policy_fingerprint") or "").strip():
            raise AutoDevStateError(
                "validate_production_release requires policy_fingerprint"
            )
        if not isinstance(structured.get("provider_readbacks"), list) or not structured[
            "provider_readbacks"
        ]:
            raise AutoDevStateError(
                "validate_production_release requires provider_readbacks"
            )
    if stage == "review_others" and not (
        structured.get("review_mode") == "review_no_merge"
        and structured.get("review_result") == "clean"
    ):
        raise AutoDevStateError(
            "review_others must record a clean review_no_merge result"
        )
    return authority


def _validate_stage_wrapper_identity(
    work_item: Path,
    stage: str,
    path: Path,
    wrapper: Mapping[str, Any],
) -> str:
    """Bind a stage wrapper to its canonical evidence-derived path and history."""

    evidence = wrapper.get("evidence_snapshot")
    evidence_sha256 = str(wrapper.get("evidence_sha256") or "").strip().lower()
    if not isinstance(evidence, Mapping) or evidence_sha256 != hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest():
        raise AutoDevStateError(f"{stage} stage wrapper evidence hash no longer matches")
    canonical_path = (
        work_item
        / "artifacts"
        / "auto-dev-orchestration"
        / "stages"
        / stage
        / f"{evidence_sha256[:20]}.json"
    ).resolve()
    if path.resolve() != canonical_path:
        raise AutoDevStateError(
            f"{stage} stage wrapper is not stored at its canonical evidence path"
        )
    _, declared_path = _health_local_receipt(
        work_item,
        wrapper.get("receipt_ref"),
        f"{stage} stage wrapper receipt_ref",
    )
    if declared_path.resolve() != path.resolve():
        raise AutoDevStateError(
            f"{stage} stage wrapper receipt_ref does not bind the selected wrapper"
        )
    idempotency_key = str(wrapper.get("idempotency_key") or "").strip()
    recorded_at = str(wrapper.get("recorded_at") or "").strip()
    if not idempotency_key or not recorded_at:
        raise AutoDevStateError(
            f"{stage} stage wrapper requires idempotency_key and recorded_at"
        )
    return recorded_at


def _validate_auto_dev_stage_receipt(
    work_item: Path,
    stage: str,
    status: str,
    path: Path,
    *,
    allow_reopened_health: bool = False,
) -> dict[str, Any]:
    """Validate a standalone stage wrapper and all proof it embeds."""

    wrapper = _read_json(path)
    evidence = wrapper.get("evidence_snapshot")
    expected_evidence_schema = (
        AUTO_DEV_HEALTH_EVIDENCE_SCHEMA
        if stage == "health"
        else AUTO_DEV_STAGE_EVIDENCE_SCHEMA
    )
    if not (
        wrapper.get("schema") == "auto-dev-stage-receipt/v1"
        and wrapper.get("stage") == stage
        and wrapper.get("status") == status
        and isinstance(evidence, Mapping)
        and evidence.get("schema") == expected_evidence_schema
        and str(evidence.get("stage") or "").replace("-", "_") == stage
        and evidence.get("status") == status
        and wrapper.get("evidence_sha256")
        == hashlib.sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    ):
        raise AutoDevStateError(f"{stage} stage receipt wrapper is malformed or changed")
    if stage == "health":
        _validate_stage_wrapper_identity(work_item, stage, path, wrapper)
    structured = evidence.get("evidence")
    if not isinstance(structured, Mapping):
        raise AutoDevStateError(f"{stage} stage receipt lacks structured evidence")
    if status == "completed" and stage == "health":
        current = read_auto_dev_state(work_item / "autodev.json")
        subject_revision = str(wrapper.get("subject_revision") or "").strip() or None
        if not (
            evidence.get("schema") == AUTO_DEV_HEALTH_EVIDENCE_SCHEMA
            and wrapper.get("terminal_revision") == evidence.get("terminal_revision")
            and subject_revision == evidence.get("subject_revision")
        ):
            raise AutoDevStateError("health stage wrapper lacks its canonical revisions")
        _validate_health_evidence(
            evidence,
            structured,
            current,
            work_item / "autodev.json",
            subject_revision,
            allow_reopened=allow_reopened_health,
        )
        return wrapper
    if status == "completed":
        proofs = wrapper.get("proofs")
        refs = structured.get("receipt_refs")
        if not isinstance(proofs, list) or not proofs or not isinstance(refs, list):
            raise AutoDevStateError(f"{stage} stage receipt lacks hashed packet-local proof")
        expected_refs: set[str] = set()
        for ref in refs:
            normalized, _ = _health_local_receipt(work_item, ref, f"{stage} receipt_ref")
            expected_refs.add(normalized)
        actual_refs: set[str] = set()
        for descriptor in proofs:
            if not isinstance(descriptor, Mapping):
                raise AutoDevStateError(f"{stage} proof descriptors must be objects")
            normalized, proof_path = _health_local_receipt(
                work_item, descriptor.get("ref"), f"{stage} proof"
            )
            if descriptor.get("sha256") != hashlib.sha256(proof_path.read_bytes()).hexdigest():
                raise AutoDevStateError(f"{stage} packet-local proof hash no longer matches")
            actual_refs.add(normalized)
        if expected_refs != actual_refs:
            raise AutoDevStateError(f"{stage} proof descriptors do not match evidence.receipt_refs")
        if stage in READINESS_AUTHORITY_STAGES:
            _readiness_stage_authority(stage, evidence, wrapper.get("subject_revision"))
    else:
        if stage not in NOT_REQUIRED_ALLOWED_STAGES:
            raise AutoDevStateError(f"{stage} cannot be marked not_required")
        descriptor = wrapper.get("policy_snapshot")
        if not isinstance(descriptor, Mapping):
            raise AutoDevStateError(f"{stage} not_required receipt lacks a policy snapshot")
        normalized, policy_path = _health_local_receipt(
            work_item, descriptor.get("ref"), f"{stage} policy snapshot"
        )
        if descriptor.get("sha256") != hashlib.sha256(policy_path.read_bytes()).hexdigest():
            raise AutoDevStateError(f"{stage} policy snapshot hash no longer matches")
        if structured.get("policy_ref") != normalized:
            raise AutoDevStateError(f"{stage} policy snapshot does not match evidence.policy_ref")
        _validate_policy_decision(
            _read_json(policy_path),
            stage,
            work_item=work_item,
            current=read_auto_dev_state(work_item / "autodev.json"),
        )
    return wrapper


def validate_recorded_auto_dev_health(
    state_file: str | Path,
    *,
    allow_reopened: bool = False,
) -> Path:
    """Validate the exact recorded Health wrapper and return its local path.

    ``allow_reopened`` preserves every packet-local and cleanup proof while
    permitting the canonical work row and active projections to point at the
    fresh packet created by the explicit reopen transaction.
    """

    state_path = Path(state_file).expanduser().resolve()
    if state_path.is_dir():
        state_path = state_path / "autodev.json"
    current = read_auto_dev_state(state_path)
    health = (
        current.get("stages", {}).get("health")
        if isinstance(current.get("stages"), Mapping)
        else None
    )
    if not isinstance(health, Mapping) or health.get("status") != "completed":
        raise AutoDevStateError("Auto-Dev reopen requires completed Health evidence")
    refs = health.get("receipt_refs")
    if not isinstance(refs, list) or not refs:
        raise AutoDevStateError("completed Health state has no packet-local wrapper")
    normalized, path = _health_local_receipt(
        state_path.parent,
        refs[0],
        "completed Health wrapper",
    )
    if len(refs) != 1 or health.get("run_ref") != normalized:
        raise AutoDevStateError("completed Health state must bind exactly one canonical wrapper")
    _validate_auto_dev_stage_receipt(
        state_path.parent,
        "health",
        "completed",
        path,
        allow_reopened_health=allow_reopened,
    )
    return path


def require_auto_dev_predecessors(state_file: str | Path, stage: str) -> dict[str, Any]:
    """Fail unless every in-scope configured predecessor is terminal."""

    current = read_auto_dev_state(state_file)
    name = stage.strip().lower().replace("-", "_")
    if name not in AUTO_DEV_STAGE_ORDER:
        raise AutoDevStateError(f"unknown Auto-Dev predecessor target: {name}")
    stages = current.get("stages") if isinstance(current.get("stages"), Mapping) else {}
    work_item = Path(state_file).expanduser().resolve()
    if work_item.is_file():
        work_item = work_item.parent
    missing: list[str] = []
    stage_order = list(current.get("stage_order") or AUTO_DEV_STAGE_ORDER)
    active_order = auto_dev_workflow_window(
        stage_order,
        str(current.get("start_stage") or stage_order[0]),
        str(current.get("completion_stage") or stage_order[-1]),
    )
    if (
        current.get("mode") == "single_stage"
        and active_order == [name]
    ):
        # Defense in depth for unsafe v2 previews that persisted target-only
        # bounds. A named external mutation never gets a vacuous predecessor
        # slice merely because old state collapsed its durable window.
        active_order = stage_order[: stage_order.index(name) + 1]
    if name not in active_order:
        raise AutoDevStateError(f"{name} is outside this Auto-Dev workflow boundary")
    for predecessor in active_order[: active_order.index(name)]:
        row = stages.get(predecessor)
        if (
            not isinstance(row, Mapping)
            or row.get("status") not in TERMINAL_STAGE_STATUSES
            or not row.get("receipt_refs")
        ):
            missing.append(predecessor)
            continue
        try:
            if predecessor == "develop" and name in {
                "review_self",
                "review_others",
                "qa",
                "finalize",
                "validate_production_release",
                "merge",
            }:
                # Keep ordinary completed Develop receipts on the normal
                # immutable task-binding path.  An AGE-190 escalation is
                # recognisable either from its task-history slot or the
                # receipt's exact schema/kind; the latter makes deleted
                # history fail closed rather than turning into a generic
                # implementation bypass.
                delivery = (
                    current.get("delivery")
                    if isinstance(current.get("delivery"), Mapping)
                    else {}
                )
                task_ref = str(delivery.get("task_state_ref") or "").strip()
                task = (
                    _read_json(Path(task_ref).expanduser().resolve())
                    if task_ref
                    else {}
                )

                def active_escalation_receipt(raw_ref: Any) -> bool:
                    candidate = Path(str(raw_ref or "")).expanduser()
                    if not candidate.is_file():
                        return False
                    try:
                        receipt = _read_json(candidate.resolve())
                    except AutoDevStateError:
                        return False
                    return (
                        receipt.get("schema")
                        == ACTIVE_PR_CREATE_DELIVERY_ESCALATION_SCHEMA
                        and receipt.get("kind")
                        == _ACTIVE_PR_CREATE_DELIVERY_ESCALATION_KIND
                    )

                receipt_refs = row.get("receipt_refs")
                projected_active_receipt = (
                    isinstance(receipt_refs, list)
                    and len(receipt_refs) == 1
                    and active_escalation_receipt(receipt_refs[0])
                )
                recorded_active_receipt = any(
                    isinstance(receipt, Mapping)
                    and active_escalation_receipt(receipt.get("ref"))
                    for receipt in task.get("receipts") or []
                )
                is_active_escalation = (
                    "active_pr_create_delivery_escalations" in task
                    or projected_active_receipt
                    or recorded_active_receipt
                )
                if is_active_escalation:
                    _validate_active_pr_create_escalation_develop_predecessor(
                        current, work_item, target_stage=name
                    )
                else:
                    receipt_path = _health_stage_receipt_path(
                        work_item,
                        predecessor,
                        str(row.get("status") or ""),
                        receipt_refs,
                    )
                    _validate_delivery_stage_task_binding(
                        current, work_item, predecessor, receipt_path
                    )
            else:
                receipt_path = _health_stage_receipt_path(
                    work_item,
                    predecessor,
                    str(row.get("status") or ""),
                    row.get("receipt_refs"),
                )
                _validate_delivery_stage_task_binding(
                    current, work_item, predecessor, receipt_path
                )
        except AutoDevStateError:
            missing.append(predecessor)
    if missing:
        raise AutoDevStateError(
            f"{name} cannot mutate external state until earlier Auto-Dev stages are "
            "terminal and receipt-backed: " + ", ".join(missing)
        )
    return current


def validate_auto_dev_readiness_authority(
    state_file: str | Path,
    descriptor: Mapping[str, Any],
    *,
    expected_subject: str,
    expected_pull_request: Mapping[str, str],
) -> dict[str, Any]:
    """Validate the immutable Finalize or Review Others authority used by Merge."""

    state_path = Path(state_file).expanduser().resolve()
    if state_path.is_dir():
        state_path = state_path / "autodev.json"
    current = read_auto_dev_state(state_path)
    work_item = state_path.parent.resolve()
    owner = str(descriptor.get("owner") or "").strip().replace("-", "_")
    if owner not in READINESS_AUTHORITY_STAGES:
        raise AutoDevStateError("merge readiness_authority.owner must be finalize or review_others")
    required_keys = {
        "owner",
        "ref",
        "sha256",
        "provider",
        "pull_request",
        "repository",
        "base_branch",
        "subject_revision",
        "author_identity",
        "author_kind",
    }
    if set(descriptor) != required_keys:
        raise AutoDevStateError(
            "merge readiness_authority must contain only owner, ref, sha256, provider, "
            "pull_request, repository, base_branch, subject_revision, author_identity, "
            "and author_kind"
        )
    normalized, path = _health_local_receipt(
        work_item, descriptor.get("ref"), "merge readiness_authority.ref"
    )
    digest = str(descriptor.get("sha256") or "").lower()
    if digest != hashlib.sha256(path.read_bytes()).hexdigest():
        raise AutoDevStateError("merge readiness_authority hash no longer matches")
    row = current.get("stages", {}).get(owner)
    if not isinstance(row, Mapping) or row.get("status") != "completed":
        raise AutoDevStateError(f"merge requires a completed {owner} stage")
    recorded_paths = {
        resolved.resolve()
        for ref in [row.get("run_ref"), *(row.get("receipt_refs") or [])]
        if (resolved := _resolve_health_receipt(ref, work_item)) is not None
    }
    if path.resolve() not in recorded_paths:
        raise AutoDevStateError(
            "merge readiness_authority must reference the completed stage receipt in autodev.json"
        )
    wrapper = _validate_auto_dev_stage_receipt(work_item, owner, "completed", path)
    authority = _readiness_stage_authority(
        owner,
        wrapper["evidence_snapshot"],
        str(wrapper.get("subject_revision") or ""),
    )
    expected = {
        "provider": str(expected_pull_request.get("provider") or "").strip(),
        "pull_request": str(expected_pull_request.get("pull_request") or "").strip(),
        "repository": str(expected_pull_request.get("repository") or "").strip(),
        "base_branch": str(expected_pull_request.get("base_branch") or "").strip(),
        "subject_revision": str(expected_subject or "").strip(),
        "author_identity": str(expected_pull_request.get("author_identity") or "").strip().lower(),
        "author_kind": str(expected_pull_request.get("author_kind") or "").strip(),
    }
    described = {key: str(descriptor.get(key) or "").strip() for key in expected}
    if authority != expected or described != expected:
        raise AutoDevStateError(
            "merge readiness_authority must bind the canonical reviewed pull request and subject revision"
        )
    return {
        "owner": owner,
        "ref": normalized,
        "sha256": digest,
        **authority,
    }


def _health_runtime_registration(task: Mapping[str, Any]) -> dict[str, str]:
    """Return the exact runtime identity registered when the worktree was created."""

    raw = task.get("runtime")
    if not isinstance(raw, Mapping):
        raise AutoDevStateError(
            "health requires an explicit runtime registration in the delivery task"
        )
    ownership = str(raw.get("ownership") or "").strip()
    provider = str(raw.get("provider") or "").strip()
    identity = str(raw.get("identity") or "").strip()
    if ownership == "not_managed":
        if set(raw) != {"ownership", "provider", "identity"} or (
            provider != "none" or identity != "not-managed"
        ):
            raise AutoDevStateError("health not-managed runtime registration is malformed")
        return {
            "ownership": ownership,
            "provider": provider,
            "identity": identity,
        }
    if ownership != "managed":
        raise AutoDevStateError("health runtime ownership must be managed or not_managed")
    required = {
        "ownership",
        "provider",
        "identity",
        "teardown_command",
        "readback_command",
    }
    if set(raw) != required or not all(str(raw.get(key) or "").strip() for key in required):
        raise AutoDevStateError("health managed runtime registration is incomplete")
    if provider == "none" or identity == "not-managed":
        raise AutoDevStateError("health managed runtime registration uses an unsafe identity")
    if identity not in str(raw.get("teardown_command") or "") or identity not in str(
        raw.get("readback_command") or ""
    ):
        raise AutoDevStateError(
            "health managed runtime commands must bind the exact registered identity"
        )
    return {key: str(raw[key]) for key in required}


def _assert_unique_health_runtime(
    current: Mapping[str, Any],
    work_item: Path,
    task_path: Path,
    runtime: Mapping[str, str],
) -> None:
    if runtime.get("ownership") != "managed":
        return
    os_root = _health_os_root(work_item, current)
    collisions: list[str] = []
    from .lifecycle import root_project_dirs

    def teardown_proven(other: Mapping[str, Any]) -> bool:
        autodev_raw = str(other.get("autodev_path") or "").strip()
        if not autodev_raw:
            return False
        autodev_path = Path(autodev_raw).expanduser()
        if not autodev_path.is_file():
            return False
        other_packet = autodev_path.resolve().parent
        try:
            other_state = read_auto_dev_state(autodev_path)
            row = other_state.get("stages", {}).get("health")
            if not isinstance(row, Mapping) or row.get("status") != "completed":
                return False
            receipt = _health_stage_receipt_path(
                other_packet, "health", "completed", row.get("receipt_refs")
            )
            wrapper = _read_json(receipt)
            evidence = wrapper.get("evidence_snapshot")
            structured = evidence.get("evidence") if isinstance(evidence, Mapping) else {}
            resources = structured.get("resources") if isinstance(structured, Mapping) else {}
            disposition = resources.get("runtime") if isinstance(resources, Mapping) else {}
            audit = structured.get("receipt_audit") if isinstance(structured, Mapping) else {}
            present = audit.get("present") if isinstance(audit, Mapping) else []
            descriptors = [
                item
                for item in present
                if isinstance(item, Mapping) and item.get("kind") == "runtime_cleanup"
            ]
            if not descriptors or disposition.get("result") not in {"removed", "absent"}:
                return False
            for descriptor in descriptors:
                _, cleanup_path = _health_local_receipt(
                    other_packet, descriptor.get("ref"), "prior runtime cleanup receipt"
                )
                if descriptor.get("sha256") != hashlib.sha256(cleanup_path.read_bytes()).hexdigest():
                    continue
                cleanup = _read_json(cleanup_path)
                if (
                    cleanup.get("schema") == AUTO_DEV_RUNTIME_CLEANUP_SCHEMA
                    and cleanup.get("runtime_identity") == runtime.get("identity")
                    and cleanup.get("provider") == runtime.get("provider")
                    and cleanup.get("result") in {"removed", "absent"}
                    and cleanup.get("readback_verified") is True
                ):
                    return True
        except (AutoDevStateError, OSError):
            return False
        return False

    candidates = {
        candidate.resolve()
        for project_root in root_project_dirs(os_root)
        for candidate in project_root.glob("state/development-runs/*/tasks/*/state.json")
    }
    for candidate in sorted(candidates):
        if candidate.resolve() == task_path.resolve():
            continue
        try:
            other = _read_json(candidate)
        except AutoDevStateError:
            continue
        other_runtime = other.get("runtime") if isinstance(other.get("runtime"), Mapping) else {}
        if (
            other_runtime.get("ownership") == "managed"
            and other_runtime.get("provider") == runtime.get("provider")
            and other_runtime.get("identity") == runtime.get("identity")
            and not teardown_proven(other)
        ):
            collisions.append(str(other.get("canonical_work_id") or candidate))
    if collisions:
        raise AutoDevStateError(
            "health runtime identity is shared by another active delivery task: "
            + ", ".join(sorted(collisions))
        )


_HEALTH_TASK_RELOCATION_FIELDS = {"work_item", "autodev_path", "updated_at"}


def _health_task_semantics(task: Mapping[str, Any]) -> dict[str, Any]:
    """Ignore only fields changed by the canonical active-to-finished relink."""

    return {
        key: value
        for key, value in task.items()
        if key not in _HEALTH_TASK_RELOCATION_FIELDS
    }


def _verified_health_task_snapshot(
    preflight: Mapping[str, Any],
    work_item: Path,
    live_task: Mapping[str, Any],
) -> tuple[str, Path, dict[str, Any]]:
    descriptor = preflight.get("task_snapshot")
    if not isinstance(descriptor, Mapping):
        raise AutoDevStateError("health preflight lacks its immutable task_snapshot")
    ref, path = _health_local_receipt(
        work_item, descriptor.get("ref"), "preflight.task_snapshot.ref"
    )
    expected_hash = str(descriptor.get("sha256") or "").lower()
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
        raise AutoDevStateError("health preflight task_snapshot hash no longer matches")
    snapshot = _read_json(path)
    if _health_task_semantics(snapshot) != _health_task_semantics(live_task):
        raise AutoDevStateError(
            "health delivery task changed after the immutable pre-cleanup snapshot"
        )
    return ref, path, snapshot


def _validate_health_precleanup_audit(
    preflight: Mapping[str, Any],
    work_item: Path,
    *,
    verify_packet_files: bool = True,
) -> tuple[str, Path, dict[str, Any]]:
    descriptor = preflight.get("receipt_audit")
    if not isinstance(descriptor, Mapping):
        raise AutoDevStateError("health preflight lacks receipt_audit")
    ref, path = _health_local_receipt(
        work_item, descriptor.get("ref"), "preflight.receipt_audit.ref"
    )
    if descriptor.get("sha256") != hashlib.sha256(path.read_bytes()).hexdigest():
        raise AutoDevStateError("health preflight receipt_audit hash no longer matches")
    audit = _read_json(path)
    stages = audit.get("stages") if isinstance(audit.get("stages"), list) else []
    current = read_auto_dev_state(work_item / "autodev.json")
    expected_stages = configured_auto_dev_workflow_stages(
        current, include_health=False
    )
    merge_descriptor = {
        "ref": preflight.get("merge_receipt_ref"),
        "sha256": preflight.get("merge_receipt_sha256"),
    }
    closeout_descriptor = {
        "ref": preflight.get("closeout_receipt_ref"),
        "sha256": preflight.get("closeout_receipt_sha256"),
    }
    packet_manifest_descriptor = preflight.get("packet_manifest")
    if not (
        audit.get("schema") == "auto-dev-health-receipt-audit/v1"
        and audit.get("work_item_id") == preflight.get("work_item_id")
        and audit.get("canonical_work_id") == preflight.get("canonical_work_id")
        and audit.get("missing") == []
        and audit.get("resume_ready") is True
        and audit.get("terminal_authority") == merge_descriptor
        and audit.get("closeout") == closeout_descriptor
        and audit.get("packet_manifest") == packet_manifest_descriptor
        and [row.get("stage") for row in stages if isinstance(row, Mapping)]
        == expected_stages
        and len(stages) == len(expected_stages)
    ):
        raise AutoDevStateError(
            "health pre-cleanup receipt audit is incomplete or belongs to another item"
        )
    validate_auto_dev_packet_manifest(
        preflight,
        work_item,
        current=current,
        verify_live_files=verify_packet_files,
    )
    for row in stages:
        if not isinstance(row, Mapping) or row.get("status") not in TERMINAL_STAGE_STATUSES:
            raise AutoDevStateError(
                "health pre-cleanup receipt audit contains a non-terminal stage"
            )
        _, stage_path = _health_local_receipt(
            work_item, row.get("ref"), f"{row.get('stage')} stage snapshot"
        )
        if row.get("sha256") != hashlib.sha256(stage_path.read_bytes()).hexdigest():
            raise AutoDevStateError(
                f"health pre-cleanup stage snapshot hash no longer matches: {row.get('stage')}"
            )
        _validate_health_stage_source(
            work_item,
            str(row.get("stage") or ""),
            str(row.get("status") or ""),
            stage_path,
        )
    return ref, path, audit


def _work_yml_declared_files(work_item: Path) -> set[str]:
    """Return packet-local file declarations without permitting path escape."""

    metadata_path = work_item / "work.yml"
    try:
        metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise AutoDevStateError("health requires a readable work.yml packet manifest") from exc
    if not isinstance(metadata, Mapping):
        raise AutoDevStateError("health work.yml must be a mapping")
    raw_values: list[Any] = []
    for key in ("files", "required_files"):
        value = metadata.get(key)
        if isinstance(value, list):
            raw_values.extend(value)
        elif isinstance(value, Mapping):
            raw_values.extend(value.values())
    lifecycle = metadata.get("lifecycle") if isinstance(metadata.get("lifecycle"), Mapping) else {}
    if isinstance(lifecycle.get("required_files"), list):
        raw_values.extend(lifecycle["required_files"])
    declared: set[str] = set()
    for raw in raw_values:
        value = str(raw or "").strip()
        if not value or value == "this file":
            continue
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts:
            raise AutoDevStateError("health work.yml file declarations must stay inside the packet")
        declared.add(relative.as_posix())
    return declared


def _packet_control_document(path: Path, ref: str) -> dict[str, Any]:
    """Parse one relocation-mutable packet control without losing its structure."""

    try:
        if ref == "autodev.json":
            value = json.loads(path.read_text(encoding="utf-8"))
        elif ref == "work.yml":
            value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        else:  # pragma: no cover - callers are constrained by the constant above.
            raise AutoDevStateError(f"unsupported Health packet control: {ref}")
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise AutoDevStateError(f"health packet control is unreadable: {ref}") from exc
    if not isinstance(value, Mapping):
        raise AutoDevStateError(f"health packet control must be a mapping: {ref}")
    return dict(value)


def _packet_relocation_semantic_sha256(ref: str, document: Mapping[str, Any]) -> str:
    """Hash every semantic value except the fixed relocation-only paths.

    The allowlist is code-owned rather than manifest-owned.  A packet cannot
    widen its own exemption by editing the manifest or either control file.
    """

    allowed_paths = _PACKET_RELOCATION_ALLOWED_PATHS.get(ref)
    if allowed_paths is None:
        raise AutoDevStateError(f"unsupported Health packet control: {ref}")
    canonical = deepcopy(dict(document))
    for path in allowed_paths:
        parent: Any = canonical
        for part in path[:-1]:
            if not isinstance(parent, dict) or part not in parent:
                parent = None
                break
            parent = parent[part]
        if isinstance(parent, dict):
            parent.pop(path[-1], None)
    payload = yaml.safe_dump(
        canonical,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_relocated_packet_controls(
    preflight: Mapping[str, Any],
    work_item: Path,
    *,
    autodev: Mapping[str, Any],
    work: Mapping[str, Any],
) -> None:
    """Require the allowlisted fields to contain only canonical relocation values."""

    _validate_health_document_schema(
        autodev,
        work_item,
        autodev,
        schema_name="auto-dev-work-item.schema.json",
        label="health relocated autodev.json",
    )
    if not (
        autodev.get("schema") == AUTO_DEV_SCHEMA
        and autodev.get("work_item_id") == preflight.get("work_item_id")
        and autodev.get("canonical_work_id") == preflight.get("canonical_work_id")
    ):
        raise AutoDevStateError("health relocated autodev.json changed packet identity")
    if not str(autodev.get("updated_at") or "").strip():
        raise AutoDevStateError("health relocated autodev.json lacks updated_at")
    health = (
        autodev.get("stages", {}).get("health")
        if isinstance(autodev.get("stages"), Mapping)
        else None
    )
    completed_health = (
        autodev.get("status") == "completed"
        and autodev.get("current_stage") is None
        and autodev.get("next_action") is None
        and isinstance(health, Mapping)
        and health.get("status") == "completed"
        and health.get("next_action") is None
        and str(health.get("last_verified_at") or "").strip()
    )
    pending_health = (
        autodev.get("status") in {"ready", "running"}
        and autodev.get("current_stage") == "health"
        and isinstance(health, Mapping)
        and health.get("status") in {"not_started", "running"}
        and not health.get("run_ref")
        and health.get("receipt_refs") == []
        and not health.get("last_verified_at")
        and str(health.get("next_action") or "").strip()
    )
    if not (completed_health or pending_health):
        raise AutoDevStateError(
            "health relocated autodev.json lacks canonical pending or completed Health state"
        )
    if completed_health:
        health_refs = health.get("receipt_refs")
        if not isinstance(health_refs, list) or len(health_refs) != 1:
            raise AutoDevStateError(
                "health relocated autodev.json must bind one Health wrapper"
            )
        health_ref, health_path = _health_local_receipt(
            work_item, health_refs[0], "health relocated wrapper"
        )
        wrapper = _read_json(health_path)
        if not (
            health.get("run_ref") == health_ref
            and wrapper.get("schema") == "auto-dev-stage-receipt/v1"
            and wrapper.get("stage") == "health"
            and wrapper.get("status") == "completed"
            and isinstance(wrapper.get("evidence_snapshot"), Mapping)
            and wrapper["evidence_snapshot"].get("schema")
            == AUTO_DEV_HEALTH_EVIDENCE_SCHEMA
        ):
            raise AutoDevStateError(
                "health relocated autodev.json does not bind its canonical Health wrapper"
            )
        recorded_at = _validate_stage_wrapper_identity(
            work_item, "health", health_path, wrapper
        )
        if health.get("last_verified_at") != recorded_at:
            raise AutoDevStateError(
                "health relocated autodev.json last_verified_at does not match its Health wrapper"
            )
    delivery = autodev.get("delivery")
    if not isinstance(delivery, Mapping):
        raise AutoDevStateError("health relocated autodev.json lacks delivery state")
    old_packet = str(Path(str(preflight.get("packet_path") or "")).expanduser().resolve())
    new_packet = str(work_item.resolve())
    if str(delivery.get("work_item") or "") not in {old_packet, new_packet}:
        raise AutoDevStateError(
            "health relocated autodev.json has an unexpected delivery.work_item path"
        )
    compatibility = autodev.get("compatibility")
    if isinstance(compatibility, Mapping):
        legacy_ref = compatibility.get("legacy_state_ref")
        if legacy_ref is not None:
            expected_legacy_refs = {
                str(Path(old_packet) / "artifacts" / "auto-dev" / "state.json"),
                str(Path(new_packet) / "artifacts" / "auto-dev" / "state.json"),
            }
            if str(legacy_ref) not in expected_legacy_refs:
                raise AutoDevStateError(
                    "health relocated autodev.json has an unexpected legacy_state_ref"
                )

    state_values = [work[key] for key in ("state", "status") if key in work]
    if not state_values or any(str(value) != "finished" for value in state_values):
        raise AutoDevStateError(
            "health relocated work.yml must record finished in every state field"
        )
    lifecycle = work.get("lifecycle")
    if isinstance(lifecycle, Mapping) and "state" in lifecycle:
        if lifecycle.get("state") != "finished":
            raise AutoDevStateError(
                "health relocated work.yml lifecycle.state must be finished"
            )
    if work.get("lane") != "03-complete" or work.get("format") != "folder":
        raise AutoDevStateError(
            "health relocated work.yml must record the canonical finished lane and folder format"
        )
    if not str(work.get("updated_at") or "").strip():
        raise AutoDevStateError("health relocated work.yml lacks updated_at")


def _build_packet_manifest(
    work_item: Path, current: Mapping[str, Any]
) -> dict[str, Any]:
    required_files = set(AUTO_DEV_PACKET_FILES) | _work_yml_declared_files(work_item)
    health_root = work_item / "artifacts" / "auto-dev-health"
    for candidate in work_item.rglob("*"):
        if not candidate.is_file() or health_root in candidate.parents:
            continue
        if candidate.name.endswith((".lock", ".tmp")):
            continue
        required_files.add(candidate.relative_to(work_item).as_posix())
    missing: list[str] = []
    files: list[dict[str, Any]] = []
    for ref in sorted(required_files):
        path = (work_item / ref).resolve()
        if work_item not in path.parents or not path.is_file():
            missing.append(ref)
            continue
        payload = path.read_bytes()
        row = {
            "ref": ref,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        }
        if ref in _PACKET_RELOCATION_ALLOWED_PATHS:
            row["relocation_semantic_sha256"] = _packet_relocation_semantic_sha256(
                ref, _packet_control_document(path, ref)
            )
        files.append(row)
    directories: list[str] = []
    for ref in AUTO_DEV_PACKET_DIRECTORIES:
        path = (work_item / ref).resolve()
        if work_item not in path.parents or not path.is_dir():
            missing.append(ref + "/")
        else:
            directories.append(ref)
    if missing:
        raise AutoDevStateError(
            "health cannot mark the packet resume-ready; required packet surfaces are missing: "
            + ", ".join(missing)
        )
    return {
        "schema": AUTO_DEV_PACKET_MANIFEST_SCHEMA,
        "work_item_id": str(current.get("work_item_id") or work_item.name),
        "canonical_work_id": str(current.get("canonical_work_id") or ""),
        "files": files,
        "directories": directories,
        "missing": [],
        "resume_ready": True,
        "verified_at": _utc_now(),
    }


def validate_auto_dev_packet_manifest(
    preflight: Mapping[str, Any],
    work_item: Path,
    *,
    current: Mapping[str, Any] | None = None,
    verify_live_files: bool = True,
) -> dict[str, Any]:
    """Validate the immutable manifest and, before deletion, every live packet file."""

    descriptor = preflight.get("packet_manifest")
    if not isinstance(descriptor, Mapping):
        raise AutoDevStateError("health preflight lacks packet_manifest")
    _, path = _health_local_receipt(
        work_item, descriptor.get("ref"), "preflight.packet_manifest.ref"
    )
    if descriptor.get("sha256") != hashlib.sha256(path.read_bytes()).hexdigest():
        raise AutoDevStateError("health preflight packet_manifest hash no longer matches")
    manifest = _read_json(path)
    if current is None:
        current = read_auto_dev_state(work_item / "autodev.json")
    _validate_health_document_schema(
        manifest,
        work_item,
        current,
        schema_name="auto-dev-packet-manifest.schema.json",
        label="health packet manifest",
    )
    if not (
        manifest.get("schema") == AUTO_DEV_PACKET_MANIFEST_SCHEMA
        and manifest.get("work_item_id") == preflight.get("work_item_id")
        and manifest.get("canonical_work_id") == preflight.get("canonical_work_id")
        and manifest.get("missing") == []
        and manifest.get("resume_ready") is True
        and set(manifest.get("directories") or []) == set(AUTO_DEV_PACKET_DIRECTORIES)
    ):
        raise AutoDevStateError("health packet manifest is incomplete or belongs to another item")
    mutable_controls = set(_PACKET_RELOCATION_ALLOWED_PATHS)
    relocated_controls: dict[str, dict[str, Any]] = {}
    for row in manifest.get("files") or []:
        if not isinstance(row, Mapping):
            raise AutoDevStateError("health packet manifest file entries must be objects")
        ref, live = _health_local_receipt(work_item, row.get("ref"), "packet manifest file")
        payload = live.read_bytes()
        if not verify_live_files and ref in mutable_controls:
            document = _packet_control_document(live, ref)
            semantic_sha256 = str(row.get("relocation_semantic_sha256") or "")
            if (
                len(semantic_sha256) != 64
                or _packet_relocation_semantic_sha256(ref, document)
                != semantic_sha256
            ):
                raise AutoDevStateError(
                    "health packet control changed outside relocation fields: " + ref
                )
            relocated_controls[ref] = document
        elif (
            row.get("sha256") != hashlib.sha256(payload).hexdigest()
            or row.get("size") != len(payload)
        ):
            raise AutoDevStateError(f"health packet file changed after audit: {ref}")
    if not verify_live_files:
        if set(relocated_controls) != mutable_controls:
            raise AutoDevStateError(
                "health packet manifest lacks relocation controls: "
                + ", ".join(sorted(mutable_controls - set(relocated_controls)))
            )
        _validate_relocated_packet_controls(
            preflight,
            work_item,
            autodev=relocated_controls["autodev.json"],
            work=relocated_controls["work.yml"],
        )
    for ref in AUTO_DEV_PACKET_DIRECTORIES:
        if not (work_item / ref).is_dir():
            raise AutoDevStateError(f"health packet directory disappeared after audit: {ref}")
    return manifest


def prepare_auto_dev_health(
    state_file: str | Path,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Audit a delivered item and write the pre-deletion Health gate.

    This deliberately stops before runtime or worktree deletion.  The cleanup
    command must consume the generated preflight plus a verified runtime
    teardown receipt, so a crash can never turn a post-hoc audit into safety.
    """

    state_path = Path(state_file).expanduser().resolve()
    if state_path.is_dir():
        state_path = state_path / "autodev.json"
    current = read_auto_dev_state(state_path)
    work_item = state_path.parent.resolve()
    delivery = current.get("delivery") if isinstance(current.get("delivery"), Mapping) else {}
    task_ref = str(delivery.get("task_state_ref") or "").strip()
    if not task_ref:
        raise AutoDevStateError("health requires a linked Development Delivery task")
    task_path = Path(task_ref).expanduser().resolve()
    if _health_packet_location(work_item) in {"archived", "legacy_finished"}:
        _relink_moved_work_item(task_path, state_path, current)
        refreshed = sync_delivery_projection(task_path)
        current = refreshed if isinstance(refreshed, Mapping) else read_auto_dev_state(state_path)
    if (work_item / "REOPEN.md").exists():
        raise AutoDevStateError("health is blocked by the packet root REOPEN.md hold")
    if current.get("blocker"):
        raise AutoDevStateError("health is blocked by unresolved delivery failure state")

    merge_sha, task, merge_path, merge_payload, closeout_path, closeout_payload = (
        _health_delivery_authority(current, work_item)
    )
    subject_revision = str(current.get("subject_revision") or "").strip()
    terminal_revision = str(current.get("terminal_revision") or "").strip()
    if not subject_revision or terminal_revision != merge_sha:
        raise AutoDevStateError(
            "health requires reviewed subject_revision and typed terminal_revision"
        )

    stages = current.get("stages") if isinstance(current.get("stages"), Mapping) else {}
    missing_stages: list[str] = []
    stage_sources: list[tuple[str, str, Path]] = []
    for stage in configured_auto_dev_workflow_stages(
        current, include_health=False
    ):
        row = stages.get(stage) if isinstance(stages.get(stage), Mapping) else {}
        status = str(row.get("status") or "")
        if status not in TERMINAL_STAGE_STATUSES:
            missing_stages.append(str(stage))
            continue
        try:
            receipt_path = _health_stage_receipt_path(
                work_item, str(stage), status, row.get("receipt_refs")
            )
            _validate_delivery_stage_task_binding(
                current, work_item, str(stage), receipt_path
            )
        except AutoDevStateError:
            missing_stages.append(str(stage))
            continue
        stage_sources.append((str(stage), status, receipt_path))
    if missing_stages:
        raise AutoDevStateError(
            "health requires readable terminal receipts for every earlier stage: "
            + ", ".join(sorted(set(missing_stages)))
        )

    worktree = task.get("worktree") if isinstance(task.get("worktree"), Mapping) else {}
    worktree_identity = str(worktree.get("name") or "not-managed")
    worktree_path = str(worktree.get("path") or "")
    worktree_branch = str(worktree.get("branch") or "")
    runtime = _health_runtime_registration(task)
    runtime_identity = runtime["identity"]
    _assert_unique_health_runtime(current, work_item, task_path, runtime)
    repository = task.get("repository") if isinstance(task.get("repository"), Mapping) else {}
    repository_authority = {
        "id": repository.get("id"),
        "base_branch": str(repository.get("base_branch") or "").strip(),
    }
    if not repository_authority["id"] or not repository_authority["base_branch"]:
        raise AutoDevStateError(
            "health requires the canonical repository identity and base_branch"
        )
    task_snapshot_bytes = (
        json.dumps(task, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    task_snapshot_sha256 = hashlib.sha256(task_snapshot_bytes).hexdigest()
    task_snapshot_ref = (
        "artifacts/auto-dev-health/snapshots/"
        f"delivery-task-{task_snapshot_sha256[:16]}.json"
    )
    health_root = work_item / "artifacts" / "auto-dev-health"
    existing_preflight = health_root / "preflight.json"
    if apply and existing_preflight.is_file():
        existing = _read_json(existing_preflight)
        try:
            existing_packet = Path(str(existing.get("packet_path") or "")).expanduser()
            same_packet = existing_packet.name == work_item.name
            task_ref_matches = (
                Path(str(existing.get("task_state_ref") or "")).expanduser().resolve()
                == task_path
            )
        except (OSError, ValueError):
            same_packet = False
            task_ref_matches = False
        if not (
            existing.get("schema") == AUTO_DEV_HEALTH_PREFLIGHT_SCHEMA
            and existing.get("mode") == "apply"
            and existing.get("safe_to_cleanup") is True
            and existing.get("residual_holds") == []
            and existing.get("work_item_id") == str(current.get("work_item_id") or work_item.name)
            and existing.get("canonical_work_id") == str(current.get("canonical_work_id") or "")
            and existing.get("domain") == str(current.get("domain") or "")
            and existing.get("project") == str(current.get("project") or "")
            and existing.get("subject_revision") == subject_revision
            and existing.get("terminal_revision") == terminal_revision
            and existing.get("source_head_sha") == str(merge_payload["evidence"]["source_head_sha"])
            and existing.get("merge_sha") == merge_sha
            and existing.get("runtime") == runtime
            and existing.get("repository") == repository_authority
            and same_packet
            and task_ref_matches
        ):
            raise AutoDevStateError(
                "existing Health preflight belongs to different delivery authority; refusing to overwrite it"
            )
        _verified_health_task_snapshot(existing, work_item, task)
        _validate_health_precleanup_audit(existing, work_item)
        for descriptor_name, canonical_payload in (
            ("merge", merge_payload),
            ("closeout", closeout_payload),
        ):
            descriptor = {
                "ref": existing.get(f"{descriptor_name}_receipt_ref"),
                "sha256": existing.get(f"{descriptor_name}_receipt_sha256"),
            }
            _, snapshot_path = _health_local_receipt(
                work_item, descriptor["ref"], f"existing {descriptor_name} snapshot"
            )
            if (
                descriptor["sha256"]
                != hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
                or _read_json(snapshot_path) != canonical_payload
            ):
                raise AutoDevStateError(
                    f"existing Health {descriptor_name} snapshot no longer matches delivery authority"
                )
        return {
            "preflight": existing,
            "preflight_ref": str(existing_preflight),
            "runtime_identity": str(existing.get("runtime", {}).get("identity") or ""),
            "stage_count": len(stage_sources),
            "writes": [],
        }
    plan = {
        "schema": (
            AUTO_DEV_HEALTH_PREFLIGHT_SCHEMA
            if apply
            else "auto-dev-health-plan/v1"
        ),
        "mode": "apply" if apply else "dry-run",
        "work_item_id": str(current.get("work_item_id") or work_item.name),
        "canonical_work_id": str(current.get("canonical_work_id") or ""),
        "domain": str(current.get("domain") or ""),
        "project": str(current.get("project") or ""),
        "packet_path": str(work_item),
        "task_state_ref": str(task_path),
        "task_state_sha256": hashlib.sha256(task_path.read_bytes()).hexdigest(),
        "task_snapshot": {
            "ref": task_snapshot_ref,
            "sha256": task_snapshot_sha256,
        },
        "subject_revision": subject_revision,
        "terminal_revision": terminal_revision,
        "source_head_sha": str(merge_payload["evidence"]["source_head_sha"]),
        "merge_sha": merge_sha,
        "worktree": {
            "identity": worktree_identity,
            "path": worktree_path,
            "branch": worktree_branch,
        },
        "runtime": runtime,
        "repository": repository_authority,
        "dirty_disposition": "clean_only",
        "residual_holds": [],
        "safe_to_cleanup": True,
        "prepared_at": _utc_now(),
    }
    if not apply:
        return {"preflight": plan, "stage_count": len(stage_sources), "writes": []}

    snapshots = health_root / "snapshots"
    receipts = health_root / "receipts"
    snapshots.mkdir(parents=True, exist_ok=True)
    receipts.mkdir(parents=True, exist_ok=True)
    task_snapshot_path = work_item / task_snapshot_ref
    if task_snapshot_path.is_file():
        if task_snapshot_path.read_bytes() != task_snapshot_bytes:
            raise AutoDevStateError(
                "immutable Health task snapshot path already contains different content"
            )
    else:
        _atomic_json(task_snapshot_path, task)
    stage_rows: list[dict[str, Any]] = []
    for stage, status, source in stage_sources:
        payload = _read_json(source)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        snapshot = snapshots / f"{stage}-{digest[:16]}.json"
        _atomic_json(snapshot, payload)
        stage_rows.append(
            {
                "stage": stage,
                "status": status,
                "ref": _packet_relative(snapshot, work_item),
                "sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
            }
        )

    authority_copy = receipts / "terminal-authority.json"
    closeout_copy = receipts / "closeout.json"
    _atomic_json(authority_copy, merge_payload)
    _atomic_json(closeout_copy, closeout_payload)
    _append_event(
        work_item / "artifacts" / "auto-dev-orchestration" / "events.jsonl",
        "auto_dev.health.preflight_verified",
        {
            "work_item_id": plan["work_item_id"],
            "preflight": "artifacts/auto-dev-health/preflight.json",
            "terminal_revision": merge_sha,
        },
    )
    packet_manifest_path = receipts / "packet-manifest.json"
    _atomic_json(packet_manifest_path, _build_packet_manifest(work_item, current))
    resume = health_root / "RESUME.md"
    merge_evidence = (
        merge_payload.get("evidence")
        if isinstance(merge_payload.get("evidence"), Mapping)
        else {}
    )
    closeout_evidence = (
        closeout_payload.get("evidence")
        if isinstance(closeout_payload.get("evidence"), Mapping)
        else {}
    )
    source = current.get("source") if isinstance(current.get("source"), Mapping) else {}
    stage_receipts = {str(row["stage"]): str(row["ref"]) for row in stage_rows}
    tracker_refs = closeout_evidence.get("receipt_refs", [])
    if not isinstance(tracker_refs, list):
        tracker_refs = [tracker_refs]
    tracker_refs_text = ", ".join(str(ref) for ref in tracker_refs if ref) or "none recorded"
    resume.write_text(
        "\n".join(
            [
                "# Auto-Dev resume manifest",
                "",
                "## Identity and final authority",
                "",
                f"- Work item: {plan['work_item_id']}",
                f"- Canonical work ID: {plan['canonical_work_id']}",
                f"- Source ticket: {source.get('system')} {source.get('key')} ({source.get('url') or 'no URL recorded'})",
                f"- Domain and project: {plan['domain']}/{plan['project']}",
                f"- Repository and base: {repository_authority['id']} @ {repository_authority['base_branch']}",
                f"- Original branch: {worktree_branch or 'not managed'}",
                f"- Pull request: {merge_evidence.get('provider')} {merge_evidence.get('pull_request')}",
                f"- Reviewed revision: {subject_revision}",
                f"- Final merged revision: {merge_sha}",
                f"- Exact worktree: {worktree_identity} ({worktree_path or 'not managed'})",
                f"- Exact runtime: {runtime_identity}",
                "",
                "## Receipt map",
                "",
                f"- Tracker receipt: {tracker_refs_text}; task snapshot: {task_snapshot_ref}",
                f"- Pull-request receipt: {stage_receipts.get('review_self', 'not recorded')}",
                f"- Merge receipt: {_packet_relative(authority_copy, work_item)}",
                f"- QA receipt: {stage_receipts.get('qa', 'not recorded')}",
                f"- Release receipt: {stage_receipts.get('release', 'not recorded')}",
                f"- Deployment receipt: {stage_receipts.get('deploy', 'not recorded')}",
                f"- Closeout receipt: {_packet_relative(closeout_copy, work_item)}",
                "",
                "## Decision and cleanup safety",
                "",
                "- Final decision: delivery is complete and this exact item's Health cleanup is authorized.",
                "- Known follow-ups: reopen only for a new QA or support change; do not edit this finished packet.",
                "- Residual risk: recreated environments must be validated again because no live worktree or runtime is preserved.",
                "- Why cleanup is safe: the provider-read merged pull request, Closeout proof, complete stage snapshots, packet hashes, and exact clean resource identities were all verified before cleanup.",
                "- Cleanup plan: tear down and read back only the registered runtime, remove only the exact clean registered worktree, move this packet to finished, then read back canonical work state and indexes.",
                "",
                "## Recreate or resume",
                "",
                "- Receipt audit: artifacts/auto-dev-health/receipts/pre-cleanup-receipt-audit.json",
                "- Packet manifest: artifacts/auto-dev-health/receipts/packet-manifest.json",
                "- Cleanup preflight: artifacts/auto-dev-health/preflight.json",
                "- Reopen command: `agentic-os auto-dev reopen --state <this-finished-packet-or-autodev.json> --run-id <new-run-id> --reason \"<QA or support reason>\" --root <os-root> --apply`.",
                f"- The reopen command must create a new active packet and a fresh worktree from merged revision {merge_sha} in {repository_authority['id']}; it must preserve this packet unchanged.",
                "- Create a fresh target-local runtime from the owning project's current configuration. Never reuse the retired runtime identity, and run readiness/QA validation again.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    audit_path = receipts / "pre-cleanup-receipt-audit.json"
    audit_payload = {
        "schema": "auto-dev-health-receipt-audit/v1",
        "work_item_id": plan["work_item_id"],
        "canonical_work_id": plan["canonical_work_id"],
        "stages": stage_rows,
        "terminal_authority": {
            "ref": _packet_relative(authority_copy, work_item),
            "sha256": hashlib.sha256(authority_copy.read_bytes()).hexdigest(),
        },
        "closeout": {
            "ref": _packet_relative(closeout_copy, work_item),
            "sha256": hashlib.sha256(closeout_copy.read_bytes()).hexdigest(),
        },
        "packet_manifest": {
            "ref": _packet_relative(packet_manifest_path, work_item),
            "sha256": hashlib.sha256(packet_manifest_path.read_bytes()).hexdigest(),
        },
        "missing": [],
        "resume_ready": True,
        "verified_at": _utc_now(),
    }
    _atomic_json(audit_path, audit_payload)
    plan.update(
        {
            "merge_receipt_ref": _packet_relative(authority_copy, work_item),
            "merge_receipt_sha256": hashlib.sha256(authority_copy.read_bytes()).hexdigest(),
            "closeout_receipt_ref": _packet_relative(closeout_copy, work_item),
            "closeout_receipt_sha256": hashlib.sha256(closeout_copy.read_bytes()).hexdigest(),
            "resume_manifest": {
                "ref": _packet_relative(resume, work_item),
                "sha256": hashlib.sha256(resume.read_bytes()).hexdigest(),
            },
            "packet_manifest": {
                "ref": _packet_relative(packet_manifest_path, work_item),
                "sha256": hashlib.sha256(packet_manifest_path.read_bytes()).hexdigest(),
            },
            "receipt_audit": {
                "ref": _packet_relative(audit_path, work_item),
                "sha256": hashlib.sha256(audit_path.read_bytes()).hexdigest(),
            },
        }
    )
    preflight = health_root / "preflight.json"
    _atomic_json(preflight, plan)
    return {
        "preflight": plan,
        "preflight_ref": str(preflight),
        "runtime_identity": runtime_identity,
        "stage_count": len(stage_rows),
        "writes": [
            str(preflight),
            str(task_snapshot_path),
            str(audit_path),
            str(packet_manifest_path),
            str(resume),
        ],
    }


def _validate_health_document_schema(
    document: Mapping[str, Any],
    work_item: Path,
    current: Mapping[str, Any],
    *,
    schema_name: str,
    label: str,
) -> None:
    os_root = _health_os_root(work_item, current)
    candidates = (
        os_root / "harness" / "schemas" / schema_name,
        os_root / "schemas" / schema_name,
        Path(__file__).resolve().parent / "_resources" / "schemas" / schema_name,
        Path(__file__).resolve().parents[2] / "schemas" / schema_name,
    )
    schema_path = next((path for path in candidates if path.is_file()), None)
    if schema_path is None:
        raise AutoDevStateError(f"{label} schema is unavailable")
    schema = _read_json(schema_path)
    findings = sorted(
        Draft202012Validator(schema).iter_errors(dict(document)),
        key=lambda item: list(item.absolute_path),
    )
    if findings:
        first = findings[0]
        location = ".".join(str(part) for part in first.absolute_path) or "root"
        raise AutoDevStateError(
            f"{label} violates its strict schema at {location}: {first.message}"
        )


def _validate_health_schema(
    evidence: Mapping[str, Any], work_item: Path, current: Mapping[str, Any]
) -> None:
    _validate_health_document_schema(
        evidence,
        work_item,
        current,
        schema_name="auto-dev-health-evidence.schema.json",
        label="health evidence",
    )


def _same_json(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return json.dumps(left, sort_keys=True, separators=(",", ":")) == json.dumps(
        right, sort_keys=True, separators=(",", ":")
    )


def _validate_health_evidence(
    evidence: Mapping[str, Any],
    structured: Mapping[str, Any],
    current: Mapping[str, Any],
    state_path: Path,
    subject_revision: str | None,
    *,
    allow_reopened: bool = False,
) -> None:
    """Validate the item-scoped, receipt-first cleanup manifest."""
    work_item = state_path.parent.resolve()
    terminal_revision = str(evidence.get("terminal_revision") or "").strip() or None
    if str(evidence.get("work_item_id") or "") != str(current.get("work_item_id") or ""):
        raise AutoDevStateError("health evidence work_item_id does not match autodev.json")
    if _health_packet_location(work_item) not in {
        "canonical",
        "archived",
        "legacy_finished",
    }:
        raise AutoDevStateError(
            "health must be recorded from work-items/<item>, "
            "work-items/99-archived/<item>, or legacy work-items/03-complete/<item>"
        )
    if (work_item / "REOPEN.md").exists():
        raise AutoDevStateError("health is blocked by the packet root REOPEN.md hold")

    _validate_health_schema(evidence, work_item, current)
    stages = current.get("stages") if isinstance(current.get("stages"), Mapping) else {}
    incomplete = [
        str(stage)
        for stage in configured_auto_dev_workflow_stages(
            current, include_health=False
        )
        if (
            not isinstance(stages.get(stage), Mapping)
            or stages[stage].get("status") not in TERMINAL_STAGE_STATUSES
            or not stages[stage].get("receipt_refs")
        )
    ]
    if incomplete:
        raise AutoDevStateError(
            "health cannot finish before every earlier applicable Auto-Dev stage has "
            "terminal receipt-backed state: " + ", ".join(incomplete)
        )

    (
        merge_revision,
        task,
        merge_receipt_path,
        merge_receipt_payload,
        closeout_receipt_path,
        closeout_receipt_payload,
    ) = _health_delivery_authority(current, work_item)

    preflight_ref, preflight_path = _health_local_receipt(
        work_item,
        _required_text(structured, "preflight_ref", "evidence"),
        "preflight_ref",
    )
    preflight = _read_json(preflight_path)
    _validate_health_document_schema(
        preflight,
        work_item,
        current,
        schema_name="auto-dev-health-preflight.schema.json",
        label="health preflight",
    )
    task_path = Path(str(current.get("delivery", {}).get("task_state_ref") or "")).expanduser().resolve()
    if not (
        preflight.get("schema") == AUTO_DEV_HEALTH_PREFLIGHT_SCHEMA
        and preflight.get("mode") == "apply"
        and preflight.get("safe_to_cleanup") is True
        and preflight.get("residual_holds") == []
        and preflight.get("work_item_id") == current.get("work_item_id")
        and preflight.get("canonical_work_id") == current.get("canonical_work_id")
        and preflight.get("domain") == current.get("domain")
        and preflight.get("project") == current.get("project")
        and preflight.get("subject_revision") == current.get("subject_revision")
        and preflight.get("terminal_revision") == merge_revision
        and preflight.get("source_head_sha") == current.get("subject_revision")
        and preflight.get("merge_sha") == merge_revision
        and Path(str(preflight.get("task_state_ref") or "")).expanduser().resolve() == task_path
    ):
        raise AutoDevStateError("health final evidence does not match the verified pre-cleanup gate")
    _verified_health_task_snapshot(preflight, work_item, task)
    task_runtime = _health_runtime_registration(task)
    if preflight.get("runtime") != task_runtime:
        raise AutoDevStateError(
            "health preflight runtime does not match the registered delivery runtime"
        )
    task_repository = task.get("repository") if isinstance(task.get("repository"), Mapping) else {}
    if preflight.get("repository") != {
        "id": task_repository.get("id"),
        "base_branch": str(task_repository.get("base_branch") or "").strip(),
    }:
        raise AutoDevStateError(
            "health preflight repository does not match the canonical delivery task"
        )
    for gate_name in ("resume_manifest",):
        gate = preflight.get(gate_name)
        if not isinstance(gate, Mapping):
            raise AutoDevStateError(f"health preflight lacks {gate_name}")
        _, gate_path = _health_local_receipt(
            work_item, gate.get("ref"), f"preflight.{gate_name}.ref"
        )
        if gate.get("sha256") != hashlib.sha256(gate_path.read_bytes()).hexdigest():
            raise AutoDevStateError(f"health preflight {gate_name} hash no longer matches")
    _validate_health_precleanup_audit(
        preflight, work_item, verify_packet_files=False
    )

    authority = structured.get("terminal_authority")
    if not isinstance(authority, Mapping):
        raise AutoDevStateError("health evidence requires evidence.terminal_authority")
    for key in ("kind", "provider", "ref", "revision", "verified_at"):
        _required_text(authority, key, "terminal_authority")
    if authority.get("kind") != "pull_request_merge":
        raise AutoDevStateError("health terminal_authority.kind must be pull_request_merge")
    merge_authority = merge_receipt_payload.get("evidence")
    if not (
        isinstance(merge_authority, Mapping)
        and authority.get("provider") == merge_authority.get("provider")
        and authority.get("ref") == merge_authority.get("pull_request")
    ):
        raise AutoDevStateError(
            "health terminal_authority provider and ref must match the typed merged receipt"
        )
    if subject_revision != str(current.get("subject_revision") or ""):
        raise AutoDevStateError(
            "health subject_revision must match the reviewed pull-request head"
        )
    if terminal_revision != merge_revision or authority.get("revision") != merge_revision:
        raise AutoDevStateError(
            "health terminal_revision and terminal_authority.revision must match the typed merge revision"
        )

    audit = structured.get("receipt_audit")
    if not isinstance(audit, Mapping):
        raise AutoDevStateError("health evidence requires evidence.receipt_audit")
    required = audit.get("required")
    present = audit.get("present")
    if not isinstance(required, list) or not required or not all(
        isinstance(item, str) and item.strip() for item in required
    ):
        raise AutoDevStateError("health receipt_audit.required must be a non-empty string list")
    missing_required = sorted(HEALTH_REQUIRED_RECEIPT_KINDS - set(required))
    if missing_required:
        raise AutoDevStateError(
            "health receipt_audit.required lacks canonical kinds: "
            + ", ".join(missing_required)
        )
    if audit.get("missing") != [] or audit.get("resume_ready") is not True:
        raise AutoDevStateError("health cleanup requires no missing receipts and resume_ready=true")
    if not isinstance(present, list) or not present:
        raise AutoDevStateError("health receipt_audit.present must contain hashed local receipts")
    present_kinds: set[str] = set()
    audited_refs: dict[str, set[str]] = {}
    for item in present:
        if not isinstance(item, Mapping):
            raise AutoDevStateError("health receipt_audit.present entries must be objects")
        kind = _required_text(item, "kind", "receipt_audit.present")
        ref = _required_text(item, "ref", "receipt_audit.present")
        expected_hash = _required_text(item, "sha256", "receipt_audit.present").lower()
        if len(expected_hash) != 64 or any(character not in "0123456789abcdef" for character in expected_hash):
            raise AutoDevStateError("health receipt_audit.present sha256 values must be 64 hex characters")
        normalized_ref, receipt_path = _health_local_receipt(
            work_item, ref, "receipt_audit.present.ref"
        )
        actual_hash = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            raise AutoDevStateError(f"health audited receipt hash does not match: {ref}")
        present_kinds.add(kind)
        audited_refs.setdefault(kind, set()).add(normalized_ref)
    missing_kinds = sorted(set(required) - present_kinds)
    if missing_kinds:
        raise AutoDevStateError(f"health receipt audit lacks required kinds: {', '.join(missing_kinds)}")
    for kind, descriptor_name in (
        ("receipt_audit", "receipt_audit"),
        ("resume_manifest", "resume_manifest"),
        ("packet_manifest", "packet_manifest"),
    ):
        descriptor = preflight.get(descriptor_name)
        if not isinstance(descriptor, Mapping):
            raise AutoDevStateError(f"health preflight lacks {descriptor_name}")
        canonical_ref, canonical_path = _health_local_receipt(
            work_item,
            descriptor.get("ref"),
            f"preflight.{descriptor_name}.ref",
        )
        if (
            descriptor.get("sha256")
            != hashlib.sha256(canonical_path.read_bytes()).hexdigest()
            or audited_refs.get(kind, set()) != {canonical_ref}
        ):
            raise AutoDevStateError(
                f"health {kind} audit must bind the canonical preflight descriptor"
            )

    def audited_payload_matches(kind: str, canonical: Mapping[str, Any]) -> bool:
        for ref in audited_refs.get(kind, set()):
            _, path = _health_local_receipt(work_item, ref, f"{kind} audited receipt")
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(payload, Mapping) and _same_json(payload, canonical):
                return True
        return False

    if not audited_payload_matches("terminal_authority", merge_receipt_payload):
        raise AutoDevStateError(
            "health terminal_authority audit is not an exact snapshot of the typed merged receipt"
        )
    if not audited_payload_matches("closeout", closeout_receipt_payload):
        raise AutoDevStateError(
            "health closeout audit is not an exact snapshot of the typed delivery_complete receipt"
        )
    merge_copy = _resolve_health_receipt(preflight.get("merge_receipt_ref"), work_item)
    closeout_copy = _resolve_health_receipt(preflight.get("closeout_receipt_ref"), work_item)
    if not (
        merge_copy
        and closeout_copy
        and preflight.get("merge_receipt_sha256")
        == hashlib.sha256(merge_copy.read_bytes()).hexdigest()
        and preflight.get("closeout_receipt_sha256")
        == hashlib.sha256(closeout_copy.read_bytes()).hexdigest()
        and _same_json(_read_json(merge_copy), merge_receipt_payload)
        and _same_json(_read_json(closeout_copy), closeout_receipt_payload)
    ):
        raise AutoDevStateError("health preflight authority snapshots are missing or changed")

    receipt_refs = structured.get("receipt_refs")
    if not isinstance(receipt_refs, list) or not receipt_refs:
        raise AutoDevStateError("health evidence.receipt_refs must be a non-empty list")
    normalized_receipt_refs = {
        _health_local_receipt(work_item, ref, "receipt_refs entry")[0]
        for ref in receipt_refs
    }
    canonical_audited_refs = {
        ref
        for kind in HEALTH_REQUIRED_RECEIPT_KINDS
        for ref in audited_refs.get(kind, set())
    }
    if not canonical_audited_refs.issubset(normalized_receipt_refs):
        raise AutoDevStateError("health receipt_refs must include every canonical audited receipt")
    if preflight_ref not in normalized_receipt_refs:
        raise AutoDevStateError("health receipt_refs must include the verified preflight")

    resources = structured.get("resources")
    if not isinstance(resources, Mapping):
        raise AutoDevStateError("health evidence requires evidence.resources")
    for resource_name in ("worktree", "runtime"):
        resource = resources.get(resource_name)
        if not isinstance(resource, Mapping):
            raise AutoDevStateError(f"health evidence requires resources.{resource_name}")
        for key in ("identity", "preflight", "action", "result", "receipt"):
            _required_text(resource, key, f"resources.{resource_name}")
        if resource.get("result") not in HEALTH_DISPOSITIONS:
            raise AutoDevStateError(
                f"health resources.{resource_name}.result must be removed, absent, or not_managed"
            )
        resource_ref, _ = _health_local_receipt(
            work_item, resource.get("receipt"), f"resources.{resource_name}.receipt"
        )
        if resource_ref not in audited_refs.get("resource_cleanup", set()):
            raise AutoDevStateError(
                f"health resources.{resource_name}.receipt must be audited as resource_cleanup"
            )

    cleanup_receipt_refs = {
        _health_local_receipt(
            work_item,
            resources[name].get("receipt"),
            f"resources.{name}.receipt",
        )[0]
        for name in ("worktree", "runtime")
    }
    if len(cleanup_receipt_refs) != 1:
        raise AutoDevStateError(
            "health worktree and runtime dispositions must share one atomic cleanup receipt"
        )
    cleanup_ref = next(iter(cleanup_receipt_refs))
    _, cleanup_path = _health_local_receipt(work_item, cleanup_ref, "resource cleanup receipt")
    cleanup_payload = _read_json(cleanup_path)
    _validate_health_document_schema(
        cleanup_payload,
        work_item,
        current,
        schema_name="auto-dev-resource-cleanup.schema.json",
        label="health resource cleanup receipt",
    )
    cleanup_worktree = (
        cleanup_payload.get("worktree")
        if isinstance(cleanup_payload.get("worktree"), Mapping)
        else {}
    )
    cleanup_runtime = (
        cleanup_payload.get("runtime")
        if isinstance(cleanup_payload.get("runtime"), Mapping)
        else {}
    )
    runtime_cleanup_descriptor = cleanup_payload.get("runtime_cleanup")
    if not isinstance(runtime_cleanup_descriptor, Mapping):
        raise AutoDevStateError(
            "health resource cleanup receipt must bind the destructive runtime authorization receipt"
        )
    runtime_cleanup_ref, runtime_cleanup_path = _health_local_receipt(
        work_item,
        runtime_cleanup_descriptor.get("ref"),
        "resource_cleanup.runtime_cleanup.ref",
    )
    if (
        runtime_cleanup_descriptor.get("sha256")
        != hashlib.sha256(runtime_cleanup_path.read_bytes()).hexdigest()
        or runtime_cleanup_ref not in audited_refs.get("runtime_cleanup", set())
    ):
        raise AutoDevStateError(
            "health runtime cleanup authorization must be hash-verified and audited"
        )
    runtime_cleanup_payload = _read_json(runtime_cleanup_path)
    _validate_health_document_schema(
        runtime_cleanup_payload,
        work_item,
        current,
        schema_name="auto-dev-runtime-cleanup.schema.json",
        label="health runtime cleanup authorization",
    )
    teardown_operation = runtime_cleanup_payload.get("teardown")
    readback_operation = runtime_cleanup_payload.get("readback")
    if not isinstance(teardown_operation, Mapping) or not isinstance(readback_operation, Mapping):
        raise AutoDevStateError(
            "health runtime cleanup authorization lacks teardown/readback operation receipts"
        )
    for operation_name, operation in (
        ("teardown", teardown_operation),
        ("readback", readback_operation),
    ):
        _, operation_path = _health_local_receipt(
            work_item,
            operation.get("ref"),
            f"runtime_cleanup.{operation_name}.ref",
        )
        if operation.get("sha256") != hashlib.sha256(operation_path.read_bytes()).hexdigest():
            raise AutoDevStateError(
                f"health runtime cleanup {operation_name} readback hash no longer matches"
            )
    expected_teardown = (
        task_runtime.get("teardown_command")
        if task_runtime.get("ownership") == "managed"
        else "not_managed"
    )
    expected_readback = (
        task_runtime.get("readback_command")
        if task_runtime.get("ownership") == "managed"
        else "not_managed"
    )
    if not (
        runtime_cleanup_payload.get("schema") == AUTO_DEV_RUNTIME_CLEANUP_SCHEMA
        and runtime_cleanup_payload.get("work_item_id") == current.get("work_item_id")
        and runtime_cleanup_payload.get("canonical_work_id") == current.get("canonical_work_id")
        and runtime_cleanup_payload.get("runtime_identity") == task_runtime.get("identity")
        and runtime_cleanup_payload.get("ownership") == task_runtime.get("ownership")
        and runtime_cleanup_payload.get("provider") == task_runtime.get("provider")
        and runtime_cleanup_payload.get("result") == cleanup_runtime.get("result")
        and runtime_cleanup_payload.get("readback_verified") is True
        and runtime_cleanup_payload.get("preflight_sha256")
        == hashlib.sha256(preflight_path.read_bytes()).hexdigest()
        and teardown_operation.get("command") == expected_teardown
        and readback_operation.get("command") == expected_readback
    ):
        raise AutoDevStateError(
            "health runtime cleanup authorization does not match the exact preflight and runtime disposition"
        )
    if not (
        cleanup_payload.get("schema") == "auto-dev-resource-cleanup/v1"
        and cleanup_payload.get("work_item_id") == current.get("work_item_id")
        and cleanup_payload.get("canonical_work_id") == current.get("canonical_work_id")
        and cleanup_payload.get("preflight_ref") == preflight_ref
        and cleanup_worktree.get("identity") == resources["worktree"].get("identity")
        and cleanup_worktree.get("path") == str(
            (task.get("worktree") or {}).get("path")
            if isinstance(task.get("worktree"), Mapping)
            else ""
        )
        and cleanup_worktree.get("result") == resources["worktree"].get("result")
        and cleanup_worktree.get("readback_verified") is True
        and cleanup_runtime.get("identity") == resources["runtime"].get("identity")
        and cleanup_runtime.get("ownership") == task_runtime.get("ownership")
        and cleanup_runtime.get("provider") == task_runtime.get("provider")
        and cleanup_runtime.get("result") == resources["runtime"].get("result")
        and cleanup_runtime.get("readback_verified") is True
        and str(cleanup_payload.get("verified_at") or "").strip()
    ):
        raise AutoDevStateError(
            "health resource cleanup receipt must atomically bind exact worktree and runtime readback"
        )

    worktree = resources["worktree"]
    task_worktree = task.get("worktree") if isinstance(task.get("worktree"), Mapping) else {}
    task_worktree_raw = str(task_worktree.get("path") or "").strip()
    task_worktree_path = Path(task_worktree_raw).expanduser() if task_worktree_raw else None
    if task_worktree and worktree.get("result") == "not_managed":
        raise AutoDevStateError("health cannot mark a linked managed worktree as not_managed")
    if not task_worktree and not (
        worktree.get("identity") == "not-managed"
        and worktree.get("result") == "not_managed"
    ):
        raise AutoDevStateError(
            "health requires identity=not-managed and result=not_managed when no worktree was registered"
        )
    if (
        worktree.get("identity")
        != str(task_worktree.get("name") or task_worktree_raw or "not-managed")
    ):
        raise AutoDevStateError("health worktree identity does not match the linked delivery task")
    if (
        worktree.get("result") in {"removed", "absent"}
        and task_worktree_path is not None
        and task_worktree_path.exists()
    ):
        raise AutoDevStateError("health worktree disposition conflicts with an existing task worktree")
    expected_runtime_identity = str(preflight.get("runtime", {}).get("identity") or "")
    if resources["runtime"].get("identity") != expected_runtime_identity:
        raise AutoDevStateError("health runtime identity does not match the pre-cleanup gate")
    runtime_result = str(resources["runtime"].get("result") or "")
    if task_runtime["ownership"] == "managed" and runtime_result not in {"removed", "absent"}:
        raise AutoDevStateError("health managed runtime requires removed or absent readback")
    if task_runtime["ownership"] == "not_managed" and runtime_result != "not_managed":
        raise AutoDevStateError("health not-managed runtime requires not_managed readback")

    work_state = structured.get("work_state")
    if not isinstance(work_state, Mapping):
        raise AutoDevStateError("health evidence requires evidence.work_state")
    for key in (
        "canonical_work_id",
        "before",
        "before_attention",
        "after",
        "history_receipt",
        "packet_old_path",
        "packet_new_path",
    ):
        _required_text(work_state, key, "work_state")
    if work_state.get("after") != "finished":
        raise AutoDevStateError("health work_state.after must be finished")
    if str(work_state.get("canonical_work_id")) != str(current.get("canonical_work_id") or ""):
        raise AutoDevStateError("health canonical_work_id does not match autodev.json")
    packet_project_root = _health_project_root(work_item, current)

    def resolved_packet_path(raw: Any) -> Path:
        candidate = Path(str(raw or "")).expanduser()
        return (
            candidate.resolve()
            if candidate.is_absolute()
            else (packet_project_root / candidate).resolve()
        )

    if resolved_packet_path(work_state.get("packet_new_path")) != work_item:
        raise AutoDevStateError("health packet_new_path must match the finished work-item location")
    history_ref, history_path = _health_local_receipt(
        work_item, work_state.get("history_receipt"), "work_state.history_receipt"
    )
    if history_ref not in audited_refs.get("work_state", set()):
        raise AutoDevStateError("health history_receipt must be audited as work_state")

    os_root = _health_os_root(work_item, current)
    from .state import work_items as canonical_work_items
    from .state.db import connect as connect_state
    from .state.db import default_db_path

    db_path = default_db_path(os_root)
    if not db_path.is_file():
        raise AutoDevStateError("health canonical state.db is missing")
    connection = connect_state(db_path)
    try:
        canonical = canonical_work_items.get(
            connection, str(work_state.get("canonical_work_id"))
        )
        history_row = connection.execute(
            (
                """
                SELECT changed_at, from_state, to_state, from_attention, to_attention, receipt_ref
                FROM work_item_history
                WHERE work_item_id = ? AND to_state = 'finished' AND to_attention = 'closed'
                ORDER BY id DESC
                LIMIT 1
                """
                if allow_reopened
                else """
                SELECT changed_at, from_state, to_state, from_attention, to_attention, receipt_ref
                FROM work_item_history
                WHERE work_item_id = ?
                ORDER BY id DESC
                LIMIT 1
                """
            ),
            (str(work_state.get("canonical_work_id")),),
        ).fetchone()
    finally:
        connection.close()
    if canonical is None:
        raise AutoDevStateError("health canonical work item is missing from state.db")
    packet_value = Path(str(canonical.get("packet_path") or "")).expanduser()
    canonical_packet = (
        packet_value.resolve() if packet_value.is_absolute() else (os_root / packet_value).resolve()
    )
    canonical_identity_matches = (
        canonical.get("domain") == current.get("domain")
        and canonical.get("project") == current.get("project")
        and canonical.get("last_verified_at")
    )
    live_finished_state = (
        canonical.get("state") == "finished"
        and canonical.get("attention") == "closed"
        and canonical_packet == work_item
        and not canonical.get("worktree_path")
        and not canonical.get("branch")
    )
    explicit_reopen_state = (
        allow_reopened
        and canonical.get("state") not in canonical_work_items.TERMINAL_STATES
        and canonical.get("attention") in {"active", "parked"}
        and canonical_packet != work_item
    )
    if not canonical_identity_matches or not (
        live_finished_state or explicit_reopen_state
    ):
        raise AutoDevStateError(
            "health canonical work state must be verified, finished, closed, packet-linked, and worktree-free"
        )
    history_values = dict(history_row) if history_row is not None else {}
    history_receipt_raw = str(history_values.get("receipt_ref") or "").strip()
    history_receipt_matches = history_receipt_raw == history_ref
    if history_receipt_raw:
        history_receipt_value = Path(history_receipt_raw).expanduser()
        history_receipt_matches = (
            history_receipt_value.resolve() == history_path
            if history_receipt_value.is_absolute()
            else history_receipt_value.as_posix() == history_ref
        )
    # The terminal history row is immutable transition evidence. Canonical
    # last_verified_at is mutable freshness metadata and may advance after a
    # same-state verification without creating another history row.
    if not (
        history_values.get("to_state") == "finished"
        and history_values.get("to_attention") == "closed"
        and history_values.get("from_state") == work_state.get("before")
        and history_values.get("from_attention") == work_state.get("before_attention")
        and history_receipt_matches
    ):
        raise AutoDevStateError(
            "health requires the final finished/closed history row to reference the audited work-state receipt"
        )

    active_now_path = (
        os_root / "harness" / "shared_factory" / "00-control-plane" / "active-now.json"
    )
    active_now = _read_json(active_now_path)
    canonical_work_id = str(work_state.get("canonical_work_id"))
    if not allow_reopened and any(
        isinstance(item, Mapping) and str(item.get("id") or "") == canonical_work_id
        for item in active_now.get("items") or []
    ):
        raise AutoDevStateError("health canonical work item still appears in active-now.json")
    active_index_path = os_root / "00-control-plane" / "active" / "index.yml"
    if not active_index_path.is_file():
        raise AutoDevStateError("health global active-work index readback is missing")
    active_index = yaml.safe_load(active_index_path.read_text(encoding="utf-8")) or {}
    active_rows = [
        *(active_index.get("work_items") or []),
        *(active_index.get("worktrees") or []),
    ]
    old_packet = resolved_packet_path(work_state.get("packet_old_path"))
    for row in active_rows:
        if not isinstance(row, Mapping):
            continue
        target_raw = str(row.get("target") or "").strip()
        target = Path(target_raw).expanduser().resolve() if target_raw else None
        if (
            (not allow_reopened and str(row.get("id") or "") == canonical_work_id)
            or target in {work_item, old_packet}
        ):
            raise AutoDevStateError("health work item still appears in the global active index")

    def worktree_rows(path: Path) -> list[Mapping[str, Any]]:
        if not path.is_file():
            return []
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raw = value.get("worktrees") if isinstance(value, Mapping) else []
        if isinstance(raw, Mapping):
            raw = raw.get("registered") or raw.get("worktrees") or []
        return [row for row in raw if isinstance(row, Mapping)] if isinstance(raw, list) else []

    closed_target: Mapping[str, Any] | None = None
    if task_worktree:
        project_root = Path(task_worktree_raw).expanduser().resolve().parent.parent
        if (
            project_root.name != str(current.get("project") or "")
            or os_root not in project_root.parents
        ):
            raise AutoDevStateError(
                "health cannot derive the owning project from the canonical worktree path"
            )
        active_registry_rows = [
            *worktree_rows(project_root / "worktrees" / "index.yml"),
            *worktree_rows(project_root / "config" / "worktrees.yml"),
        ]
        closed_registry_rows = worktree_rows(project_root / "worktrees" / "closed.yml")
        task_identity = str(task_worktree.get("name") or "")

        def is_target(row: Mapping[str, Any]) -> bool:
            row_path = str(row.get("path") or "").strip()
            identity_matches = (
                not task_identity
                or str(row.get("id") or row.get("name") or "") == task_identity
            )
            return bool(
                identity_matches
                and task_worktree_raw
                and row_path
                and Path(row_path).expanduser().resolve()
                == Path(task_worktree_raw).expanduser().resolve()
            )

        if any(is_target(row) for row in active_registry_rows):
            raise AutoDevStateError("health target worktree remains in an active registry")
        closed_target = next((row for row in closed_registry_rows if is_target(row)), None)
        if closed_target is None:
            raise AutoDevStateError("health target worktree is missing from the live closed registry")
        if not (
            closed_target.get("status") == "closed"
            and closed_target.get("terminal_revision") == merge_revision
            and closed_target.get("health_preflight_ref") == preflight_ref
        ):
            raise AutoDevStateError(
                "health live closed worktree entry lacks typed terminal authority and preflight linkage"
            )

    registry_ref, registry_path = _health_local_receipt(
        work_item,
        _required_text(structured, "closed_worktree_registry_ref", "evidence"),
        "closed_worktree_registry_ref",
    )
    if registry_ref not in audited_refs.get("resource_cleanup", set()):
        raise AutoDevStateError(
            "health closed_worktree_registry_ref must be audited as resource_cleanup"
        )
    registry_snapshot = _read_json(registry_path)
    snapshot_entry = (
        registry_snapshot.get("entry")
        if isinstance(registry_snapshot.get("entry"), Mapping)
        else None
    )
    if task_worktree:
        if not (
            registry_snapshot.get("schema") == "auto-dev-closed-worktree-readback/v1"
            and registry_snapshot.get("work_item_id") == current.get("work_item_id")
            and registry_snapshot.get("canonical_work_id") == current.get("canonical_work_id")
            and snapshot_entry is not None
            and closed_target is not None
            and str(snapshot_entry.get("id") or snapshot_entry.get("name") or "")
            == str(closed_target.get("id") or closed_target.get("name") or "")
            and str(snapshot_entry.get("path") or "") == str(closed_target.get("path") or "")
            and snapshot_entry.get("status") == "closed"
            and snapshot_entry.get("terminal_revision") == merge_revision
            and snapshot_entry.get("health_preflight_ref") == preflight_ref
            and str(registry_snapshot.get("captured_at") or "").strip()
        ):
            raise AutoDevStateError(
                "health packet-local closed worktree readback does not match the live registry"
            )
    elif not (
        registry_snapshot.get("schema") == "auto-dev-closed-worktree-readback/v1"
        and registry_snapshot.get("result") == "not_managed"
    ):
        raise AutoDevStateError("health requires a packet-local not-managed registry readback")
    active_refs = structured.get("active_index_refs")
    if not isinstance(active_refs, list) or not active_refs or not all(
        isinstance(item, str) and item.strip() for item in active_refs
    ):
        raise AutoDevStateError("health active_index_refs must contain post-cleanup readback receipts")
    for ref in active_refs:
        normalized, _ = _health_local_receipt(work_item, ref, "active_index_refs entry")
        if normalized not in audited_refs.get("active_index", set()):
            raise AutoDevStateError(
                "health active_index_refs entries must be audited as active_index"
            )
    validations = structured.get("validation_results")
    if not isinstance(validations, list) or not validations:
        raise AutoDevStateError("health validation_results must contain at least one readback")
    for validation in validations:
        if not isinstance(validation, Mapping):
            raise AutoDevStateError("health validation_results entries must be objects")
        for key in ("command", "result", "ref"):
            _required_text(validation, key, "validation_results")
        if validation.get("result") != "passed":
            raise AutoDevStateError("health validation results must all be passed")
        normalized, _ = _health_local_receipt(
            work_item, validation.get("ref"), "validation_results.ref"
        )
        if normalized not in audited_refs.get("validation", set()):
            raise AutoDevStateError(
                "health validation_results refs must be audited as validation"
            )
    if structured.get("residual_holds") != []:
        raise AutoDevStateError("health cannot complete while residual holds remain")


def record_auto_dev_stage(
    state_file: str | Path,
    *,
    stage: str,
    evidence_file: str | Path,
    idempotency_key: str,
) -> dict[str, Any]:
    """Record a completed or policy-skipped workflow from typed evidence."""
    if str(state_file).strip().startswith(("{", "[")):
        raise AutoDevStateError(
            "state expects a work-item directory or autodev.json path, not inline "
            "JSON; pass the evidence body to --evidence as a file path"
        )
    state_path = Path(state_file).expanduser().resolve()
    if state_path.is_dir():
        state_path = state_path / "autodev.json"
    current = read_auto_dev_state(state_path)
    work_item = state_path.parent.resolve()
    name = stage.strip().lower().replace("-", "_")
    if name not in AUTO_DEV_STAGE_ORDER:
        raise AutoDevStateError(f"stage must be one of: {', '.join(AUTO_DEV_STAGE_ORDER)}")
    if name in DELIVERY_MANAGED_STAGES:
        raise AutoDevStateError(
            f"{name} is owned by Development Delivery; record it with agentic-os develop stage"
        )
    evidence_path = resolve_evidence_file(evidence_file)
    evidence = _read_json(evidence_path)
    expected_schema = (
        AUTO_DEV_HEALTH_EVIDENCE_SCHEMA if name == "health" else AUTO_DEV_STAGE_EVIDENCE_SCHEMA
    )
    if evidence.get("schema") != expected_schema:
        raise AutoDevStateError(f"{name} evidence must use {expected_schema}")
    if str(evidence.get("stage") or "").replace("-", "_") != name:
        raise AutoDevStateError("stage evidence does not match the requested stage")
    status = str(evidence.get("status") or "")
    if status not in TERMINAL_STAGE_STATUSES:
        raise AutoDevStateError("stage evidence status must be completed or not_required")
    if not str(evidence.get("summary") or "").strip() or not evidence.get("verified_at"):
        raise AutoDevStateError("stage evidence requires summary and verified_at")
    structured = evidence.get("evidence")
    if not isinstance(structured, Mapping) or not structured:
        raise AutoDevStateError("stage evidence requires a structured evidence object")
    task_ref = str(current.get("delivery", {}).get("task_state_ref") or "").strip()
    if name in {"qa", "review_others", "finalize"} and task_ref:
        task_path = Path(task_ref).expanduser().resolve()
        if task_path.is_file() and _pending_subject_supersession(_read_json(task_path)):
            raise AutoDevStateError(
                f"{name} is blocked until fresh Review Self accepts the refreshed PR head"
            )
    policy_source: Path | None = None
    proof_sources: list[Path] = []
    if status == "not_required":
        if name not in NOT_REQUIRED_ALLOWED_STAGES:
            raise AutoDevStateError(f"{name} cannot be marked not_required")
        stage_policies = (
            current.get("stage_policies")
            if isinstance(current.get("stage_policies"), Mapping)
            else {}
        )
        stage_policy = (
            stage_policies.get(name)
            if isinstance(stage_policies.get(name), Mapping)
            else {"applicability": "required"}
        )
        if stage_policy.get("applicability") == "required":
            raise AutoDevStateError(
                f"{name} is required by the frozen project Auto-Dev policy"
            )
        policy_source = _stage_source_path(
            structured.get("policy_ref"), evidence_path, work_item, f"{name} policy_ref"
        )
        _validate_policy_decision(_read_json(policy_source), name)
    if name == "health" and status != "completed":
        raise AutoDevStateError(
            "health always performs a final audit; record a completed no-op "
            "when nothing needs pruning"
        )
    if status == "completed":
        receipt_refs = structured.get("receipt_refs")
        if not (
            isinstance(receipt_refs, list)
            and receipt_refs
            and all(isinstance(item, str) and item.strip() for item in receipt_refs)
        ):
            raise AutoDevStateError(
                "completed stage evidence requires evidence.receipt_refs as a non-empty string list"
            )
        if name != "health":
            proof_sources = [
                _stage_source_path(ref, evidence_path, work_item, f"{name} receipt_ref")
                for ref in receipt_refs
            ]
    if name == "health":
        if (state_path.parent / "REOPEN.md").exists():
            raise AutoDevStateError("health is blocked by the packet root REOPEN.md hold")
        # Reject malformed cleanup manifests before applying semantic revision
        # checks so operators receive the strict contract failure first.
        _validate_health_schema(evidence, state_path.parent, current)
    subject_revision = str(evidence.get("subject_revision") or "").strip() or None
    evidence_terminal_revision = (
        str(evidence.get("terminal_revision") or "").strip() or None
    )
    if status == "completed" and name in REVISION_SENSITIVE_STAGES and not subject_revision:
        raise AutoDevStateError(f"{name} evidence requires subject_revision")
    if name == "qa" and status == "completed" and task_ref:
        task_path = Path(task_ref).expanduser().resolve()
        task = _read_json(task_path) if task_path.is_file() else {}
        canonical_subject = str(task.get("subject_revision") or "").strip()
        if canonical_subject and subject_revision != canonical_subject:
            raise AutoDevStateError(
                "qa evidence subject_revision must match the canonical reviewed pull-request head"
            )
    if status == "completed" and name in READINESS_AUTHORITY_STAGES:
        stage_authority = _readiness_stage_authority(name, evidence, subject_revision)
        if not task_ref:
            raise AutoDevStateError(f"{name} requires a linked Development Delivery task")
        task_path = Path(task_ref).expanduser().resolve()
        task = _read_json(task_path)
        _, ready_payload = _health_task_receipt(
            task, "ready_for_merge", work_item, task_path=task_path
        )
        ready_evidence = (
            ready_payload.get("evidence")
            if isinstance(ready_payload.get("evidence"), Mapping)
            else {}
        )
        ready_authority = validate_pull_request_authority(
            task, ready_evidence, f"{name} canonical ready_for_merge receipt"
        )
        expected_stage_authority = {
            **ready_authority,
            "subject_revision": str(ready_evidence.get("subject_revision") or "").strip(),
        }
        if stage_authority != expected_stage_authority:
            raise AutoDevStateError(
                f"{name} must bind the canonical provider-read PR authorship and repository"
            )
        canonical_subject = str(ready_evidence.get("subject_revision") or "").strip()
        task_subject = str(task.get("subject_revision") or "").strip()
        projected_subject = str(current.get("subject_revision") or "").strip()
        if not canonical_subject or any(
            value and value != canonical_subject
            for value in (subject_revision, task_subject, projected_subject)
        ):
            raise AutoDevStateError(
                f"{name} subject_revision must match the canonical ready_for_merge receipt"
            )
    current_terminal_revision = str(current.get("terminal_revision") or "").strip() or None
    if (
        status == "completed"
        and name in TERMINAL_REVISION_STAGES
        and current_terminal_revision
        and subject_revision != current_terminal_revision
    ):
        raise AutoDevStateError(
            f"{name} evidence subject_revision must match terminal_revision"
        )
    if name == "health" and (
        subject_revision != (str(current.get("subject_revision") or "").strip() or None)
        or not current_terminal_revision
        or evidence_terminal_revision != current_terminal_revision
    ):
        raise AutoDevStateError(
            "health evidence must keep the reviewed subject_revision distinct from "
            "terminal_revision and match both canonical revisions"
        )
    minimum = STAGE_MINIMUM_DELIVERY_STATE.get(name)
    delivery_state = str(current.get("delivery", {}).get("state") or "")
    if status == "completed" and minimum and _state_index(delivery_state) < _state_index(minimum):
        raise AutoDevStateError(f"{name} requires canonical delivery state {minimum} or later")
    if name == "health":
        _validate_health_evidence(evidence, structured, current, state_path, subject_revision)
    canonical_evidence = json.loads(json.dumps(evidence))
    canonical_structured = canonical_evidence.get("evidence")
    proofs: list[dict[str, str]] = []
    policy_snapshot: dict[str, str] | None = None
    if name != "health" and status == "completed":
        proofs = [
            _materialize_stage_source(
                source, work_item, stage=name, kind=f"proof-{index:02d}"
            )
            for index, source in enumerate(proof_sources, start=1)
        ]
        canonical_structured["receipt_refs"] = [item["ref"] for item in proofs]
    elif status == "not_required" and policy_source is not None:
        policy_snapshot = materialize_auto_dev_policy_decision(
            policy_source,
            name,
            work_item=work_item,
            current=current,
        )
        canonical_structured["policy_ref"] = policy_snapshot["ref"]
    stage_dir = work_item / "artifacts" / "auto-dev-orchestration" / "stages" / name
    evidence_sha256 = hashlib.sha256(
        json.dumps(canonical_evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    output = stage_dir / f"{evidence_sha256[:20]}.json"
    latest = stage_dir / "latest.json"
    receipt = {
        "schema": "auto-dev-stage-receipt/v1",
        "stage": name,
        "status": status,
        "evidence_ref": _portable_packet_ref(evidence_path, work_item),
        "evidence_snapshot": canonical_evidence,
        "evidence_sha256": evidence_sha256,
        "subject_revision": subject_revision,
        "idempotency_key": idempotency_key,
        "recorded_at": _utc_now(),
    }
    if proofs:
        receipt["proofs"] = proofs
    if policy_snapshot is not None:
        receipt["policy_snapshot"] = policy_snapshot
    if name == "health":
        receipt["terminal_revision"] = evidence_terminal_revision
    created = False
    promoted_latest = False
    with _file_lock(stage_dir / ".lock"):
        latest_before = _read_json(latest) if latest.is_file() else None
        for prior_path in sorted(stage_dir.glob("*.json")):
            if prior_path.name == "latest.json":
                continue
            prior = _read_json(prior_path)
            if prior.get("idempotency_key") == idempotency_key:
                if prior.get("evidence_sha256") != evidence_sha256:
                    raise AutoDevStateError(f"{name} idempotency key already has different evidence")
                receipt = prior
                output = prior_path
                break
        if output.is_file():
            existing = _read_json(output)
            receipt = existing
        else:
            previous = latest_before
            if previous:
                receipt["supersedes"] = previous.get("receipt_ref") or str(latest)
            receipt["receipt_ref"] = (
                _portable_packet_ref(output, work_item)
                if name == "health"
                else str(output)
            )
            _atomic_json(output, receipt)
            created = True
            promoted_latest = True
        if latest_before is None:
            promoted_latest = True
        elif (
            latest_before.get("receipt_ref") == receipt.get("receipt_ref")
            or latest_before.get("evidence_sha256") == receipt.get("evidence_sha256")
        ):
            promoted_latest = True
        if promoted_latest:
            _atomic_json(latest, receipt)
    for stage_name in AUTO_DEV_STAGE_ORDER:
        current.setdefault("stages", {}).setdefault(stage_name, _stage_row(stage_name))
    if promoted_latest and subject_revision and name in TERMINAL_REVISION_STAGES:
        current["terminal_revision"] = subject_revision
        _atomic_json(state_path, current)
    elif promoted_latest and subject_revision:
        current["subject_revision"] = subject_revision
        _atomic_json(state_path, current)
    task_ref = current.get("delivery", {}).get("task_state_ref")
    if task_ref and Path(str(task_ref)).expanduser().is_file():
        if name == "health":
            _relink_moved_work_item(Path(str(task_ref)).expanduser().resolve(), state_path, current)
        refreshed = sync_delivery_projection(str(task_ref))
    else:
        current["stages"][name].update(
            {
                "status": status,
                "run_ref": _portable_packet_ref(output, work_item),
                "receipt_refs": [_portable_packet_ref(output, work_item)],
                "last_verified_at": receipt["recorded_at"],
                "next_action": None,
            }
        )
        current["current_stage"] = _next_stage(
            current["stages"],
            current.get("requested_stage"),
            current["stage_order"],
            start_stage=current.get("start_stage"),
            completion_stage=current.get("completion_stage"),
        )
        current["status"] = (
            "completed"
            if current["current_stage"] is None
            else "ready"
        )
        current["next_action"] = (
            current["stages"][current["current_stage"]]["next_action"]
            if current["current_stage"]
            else None
        )
        current["updated_at"] = _utc_now()
        _atomic_json(state_path, current)
        refreshed = current
    # Health is the packet-sealing stage. Its typed wrapper is the durable
    # event; appending to the pre-existing packet event log after the
    # pre-cleanup manifest would invalidate the immutable resume packet.
    if created and name != "health":
        _append_event(
            work_item / "artifacts" / "auto-dev-orchestration" / "events.jsonl",
            "auto_dev.stage.recorded",
            {"stage": name, "status": status, "receipt": str(output)},
        )
    return {"receipt": receipt, "state": refreshed}
