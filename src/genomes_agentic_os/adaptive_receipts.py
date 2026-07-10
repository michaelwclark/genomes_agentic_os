"""Validated, privacy-safe receipts and advisory adaptive-routing telemetry.

The receipt boundary accepts only the authoritative ``ExecutionPlan`` and its
validated ``TopologySnapshot``.  Callers cannot supply parallel agent,
topology, or escalation mappings that might disagree with controller state.
All retained strings are either opaque identifiers, enumerated values,
allowlisted topology contract text, or normalized relative artifact paths.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import html
import json
import math
from pathlib import PurePosixPath, PureWindowsPath
import re
import uuid
from typing import Any, Mapping, Sequence

from .adaptive_router import (
    PLAN_SCHEMA_VERSION,
    ExecutionPlan,
    PlanStatus,
)
from .adaptive_topology import (
    AgentRole,
    TopologySnapshot,
    TopologyStatus,
)


RECEIPT_SCHEMA_VERSION = 2
TELEMETRY_SCHEMA_VERSION = 2

_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_ARTIFACT_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SSN = re.compile(r"(?<!\d)\d{3}[- ]?\d{2}[- ]?\d{4}(?!\d)")
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\d)(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}(?!\d)")
_PAYMENT_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_SECRET_MARKER = re.compile(
    r"(?:api[_-]?key|secret|password|bearer|access[_-]?token|auth[_-]?token)"
    r"(?:[:=_-]|$)",
    re.IGNORECASE,
)
_CREDENTIAL_PREFIX = re.compile(
    r"^(?:sk-[A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9]{12,}|github_pat_[A-Za-z0-9_]{12,}"
    r"|xox[baprs]-[A-Za-z0-9-]{12,}|AKIA[A-Z0-9]{16}|AIza[A-Za-z0-9_-]{20,})$"
)
_JWT = re.compile(r"^[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}$")
_BASE64ISH = re.compile(r"^[A-Za-z0-9_-]{8,}={0,2}$")
_LONG_HEX = re.compile(r"^[A-Fa-f0-9]{32,}$")

_TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "total_tokens",
)
_USAGE_FIELDS = (
    "provider",
    *_TOKEN_FIELDS,
    "cost_cents",
    "latency_ms",
)
_OUTCOME_STATUSES = frozenset({"unknown", "success", "failure", "partial"})
_COST_ASSESSMENTS = frozenset(
    {"unknown", "appropriate", "too_cheap", "too_expensive"}
)
_VERIFICATION_STATUSES = frozenset(
    {"unknown", "pending", "passed", "failed", "not_required"}
)
_COHORTS = ("static", "adaptive", "blocked", "human_gate")

_PLAN_KEYS = frozenset(
    {
        "schema_version",
        "policy_version",
        "status",
        "selected_owner",
        "policy_mode",
        "model_tier",
        "model_id",
        "reasoning_effort",
        "budgets",
        "required_tools",
        "required_verification",
        "required_approvals",
        "assessment",
        "rejected_alternatives",
        "blocker_code",
        "static_fallback_feature",
    }
)
_ASSESSMENT_KEYS = frozenset(
    {
        "schema_version",
        "task_family",
        "code_scope",
        "context_depth",
        "mutation_scope",
        "uncertainty",
        "expected_duration",
        "risk_flags",
        "minimum_tier",
        "verification_needs",
        "human_gate",
        "confidence",
        "evidence",
    }
)
_BUDGET_KEYS = frozenset(
    {
        "context_tokens",
        "input_tokens",
        "output_tokens",
        "cost_budget_cents",
        "timeout_seconds",
    }
)
_ALTERNATIVE_KEYS = frozenset(
    {"model_id", "cost_class", "direction", "reason_code"}
)

_ROLE_SKILLS = {
    AgentRole.OPERATOR: ("task_execution",),
    AgentRole.WORKER: ("bounded_execution",),
    AgentRole.PLANNER: ("implementation_planning",),
    AgentRole.IMPLEMENTER: ("implementation",),
    AgentRole.RESEARCHER: ("independent_analysis",),
    AgentRole.VERIFIER: ("integration_verification",),
    AgentRole.WATCHER: ("artifact_backed_watcher",),
}
_ROLE_OUTPUT_CONTRACTS = {
    AgentRole.OPERATOR: "bounded outcome with required readback evidence",
    AgentRole.WORKER: "delegated result and evidence artifacts",
    AgentRole.PLANNER: "bounded implementation plan and acceptance checks",
    AgentRole.IMPLEMENTER: "bounded implementation result and test artifacts",
    AgentRole.RESEARCHER: "independent risk and scope evidence",
    AgentRole.VERIFIER: "parent integration verdict over every delegated output",
    AgentRole.WATCHER: "watcher state, events, and summary artifacts; no chat polling",
}


class ReceiptValidationError(ValueError):
    """Raised when input cannot be represented as a safe routing receipt."""


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _looks_encoded(value: str) -> bool:
    if _JWT.fullmatch(value) or _LONG_HEX.fullmatch(value):
        return True
    if not _BASE64ISH.fullmatch(value):
        return False
    if re.fullmatch(r"route-[0-9a-f]{24}", value):
        return False
    mixed_alphabet = (
        any(character.islower() for character in value)
        and any(character.isupper() for character in value)
        and any(character.isdigit() for character in value)
    )
    if (len(value.rstrip("=")) >= 16 and mixed_alphabet) or value.endswith("="):
        return True
    try:
        candidate = value.rstrip("=").replace("-", "+").replace("_", "/")
        padding = "=" * ((4 - len(candidate) % 4) % 4)
        import base64

        decoded = base64.b64decode(candidate + padding, validate=True)
    except (ValueError, TypeError):
        return False
    decoded_value = decoded.decode("ascii", errors="ignore")
    decoded_text = decoded_value.lower()
    if (
        _SSN.search(decoded_value)
        or _EMAIL.search(decoded_value)
        or _PHONE.search(decoded_value)
        or _PAYMENT_CARD.search(decoded_value)
        or _SECRET_MARKER.search(decoded_value)
        or _CREDENTIAL_PREFIX.fullmatch(decoded_value)
    ):
        return True
    if any(
        marker in decoded_text
        for marker in ("secret", "password", "token", "credential", "customer", "ssn")
    ):
        return True
    if len(decoded) < 12:
        return False
    printable = sum(byte in b"\t\n\r" or 32 <= byte <= 126 for byte in decoded)
    return printable / len(decoded) >= 0.85 and mixed_alphabet


def _reject_sensitive(value: str, field: str, *, permit_path: bool = False) -> None:
    if not value or "\x00" in value or any(ord(character) < 32 for character in value):
        raise ReceiptValidationError(f"{field} must not be empty or contain control characters")
    if not permit_path and ("/" in value or "\\" in value or value.startswith("~")):
        raise ReceiptValidationError(f"{field} must not contain a filesystem path")
    if (
        _SSN.search(value)
        or _EMAIL.search(value)
        or _PHONE.search(value)
        or _PAYMENT_CARD.search(value)
    ):
        raise ReceiptValidationError(f"{field} contains customer-content or personal-data patterns")
    if _SECRET_MARKER.search(value) or _CREDENTIAL_PREFIX.fullmatch(value):
        raise ReceiptValidationError(f"{field} contains a secret-like value")
    if _looks_encoded(value):
        raise ReceiptValidationError(f"{field} contains an encoded or base64-like value")


def _identifier(value: object, field: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise ReceiptValidationError(f"{field} must be an opaque identifier")
    _reject_sensitive(value, field)
    if not _OPAQUE_ID.fullmatch(value):
        raise ReceiptValidationError(
            f"{field} must be an opaque identifier containing only letters, digits, .:_-"
        )
    return value


def _identifier_list(value: object, field: str) -> list[str]:
    if not isinstance(value, (tuple, list)):
        raise ReceiptValidationError(f"{field} must be a list of opaque identifiers")
    result = [_identifier(item, field) for item in value]
    assert all(isinstance(item, str) for item in result)
    identifiers = [item for item in result if isinstance(item, str)]
    if len(identifiers) != len(set(identifiers)):
        raise ReceiptValidationError(f"{field} must not contain duplicates")
    return identifiers


def _artifact_path(value: object, field: str) -> str:
    """Return one normalized relative POSIX artifact path or fail closed."""
    if not isinstance(value, str) or not value or len(value) > 512 or "\x00" in value:
        raise ReceiptValidationError(f"{field} must be a non-empty relative artifact path")
    if "\\" in value:
        raise ReceiptValidationError(f"{field} must use a relative POSIX artifact path")
    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or not posix_path.parts
        or any(part in {".", ".."} for part in posix_path.parts)
        or posix_path.as_posix() != value
    ):
        raise ReceiptValidationError(f"{field} must be a normalized relative artifact path")
    for part in posix_path.parts:
        _reject_sensitive(part, field)
        if any(_looks_encoded(token) for token in part.split(".") if token):
            raise ReceiptValidationError(f"{field} contains an encoded or base64-like value")
        if not _ARTIFACT_SEGMENT.fullmatch(part):
            raise ReceiptValidationError(
                f"{field} artifact path segments may contain only letters, digits, ._-"
            )
    return value


def _exact_integer(
    value: object,
    field: str,
    *,
    nullable: bool = False,
    positive: bool = False,
) -> int | None:
    if value is None and nullable:
        return None
    minimum = 1 if positive else 0
    if type(value) is not int or value < minimum:
        qualifier = "positive" if positive else "non-negative"
        null_suffix = " or null" if nullable else ""
        raise ReceiptValidationError(f"{field} must be an exact {qualifier} integer{null_suffix}")
    return value


def _number(value: object, field: str, *, nullable: bool = False) -> int | float | None:
    if value is None and nullable:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        null_suffix = " or null" if nullable else ""
        raise ReceiptValidationError(f"{field} must be a finite non-negative number{null_suffix}")
    return value


def _score(value: object, field: str) -> float | None:
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ReceiptValidationError(f"{field} must be a number from 0 through 1 or null")
    return float(value)


def _expect_keys(value: object, expected: frozenset[str], field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReceiptValidationError(f"{field} must be a mapping")
    keys = set(value)
    if keys != expected:
        unknown = sorted(keys - expected)
        missing = sorted(expected - keys)
        raise ReceiptValidationError(
            f"{field} fields are not allowlisted; unknown={unknown}, missing={missing}"
        )
    return value


def _validated_plan_projection(plan: ExecutionPlan) -> dict[str, Any]:
    """Validate and return a complete, privacy-safe execution-plan projection."""
    if type(plan) is not ExecutionPlan:
        raise ReceiptValidationError("plan must be an authoritative ExecutionPlan")
    try:
        raw = plan.as_dict()
    except (AttributeError, TypeError, ValueError) as exc:
        raise ReceiptValidationError(f"plan is malformed: {exc}") from exc
    data = _expect_keys(raw, _PLAN_KEYS, "plan")
    if (
        _exact_integer(data["schema_version"], "plan.schema_version", positive=True)
        != PLAN_SCHEMA_VERSION
    ):
        raise ReceiptValidationError("unsupported execution plan schema_version")
    _exact_integer(data["policy_version"], "plan.policy_version", positive=True)

    status = _identifier(data["status"], "plan.status")
    if status not in {item.value for item in PlanStatus}:
        raise ReceiptValidationError("plan.status is invalid")
    policy_mode = _identifier(data["policy_mode"], "plan.policy_mode")
    model_tier = _identifier(data["model_tier"], "plan.model_tier")
    model_id = _identifier(data["model_id"], "plan.model_id", nullable=True)
    reasoning_effort = _identifier(
        data["reasoning_effort"], "plan.reasoning_effort", nullable=True
    )
    blocker_code = _identifier(data["blocker_code"], "plan.blocker_code", nullable=True)
    static_fallback_feature = _identifier(
        data["static_fallback_feature"], "plan.static_fallback_feature", nullable=True
    )
    if status == PlanStatus.READY.value and (model_id is None or reasoning_effort is None):
        raise ReceiptValidationError("ready plan requires model and reasoning authority")
    if status in {PlanStatus.STATIC_FALLBACK.value, PlanStatus.BLOCKED.value} and (
        model_id is not None or reasoning_effort is not None
    ):
        raise ReceiptValidationError(
            "static or blocked plan cannot declare executable model authority"
        )
    if status == PlanStatus.READY.value and blocker_code is not None:
        raise ReceiptValidationError("ready plan cannot declare a blocker")
    if status == PlanStatus.STATIC_FALLBACK.value and static_fallback_feature is None:
        raise ReceiptValidationError("static fallback plan requires its fallback feature")
    if status != PlanStatus.STATIC_FALLBACK.value and static_fallback_feature is not None:
        raise ReceiptValidationError("only static fallback plans may name a fallback feature")

    owner = data["selected_owner"]
    safe_owner: dict[str, str] | None = None
    if owner is not None:
        owner_data = _expect_keys(owner, frozenset({"identifier", "kind"}), "plan.selected_owner")
        safe_owner = {
            "identifier": str(
                _identifier(owner_data["identifier"], "plan.selected_owner.identifier")
            ),
            "kind": str(_identifier(owner_data["kind"], "plan.selected_owner.kind")),
        }

    budgets = _expect_keys(data["budgets"], _BUDGET_KEYS, "plan.budgets")
    safe_budgets = {
        "context_tokens": _exact_integer(
            budgets["context_tokens"], "plan.budgets.context_tokens", positive=True
        ),
        "input_tokens": _exact_integer(
            budgets["input_tokens"], "plan.budgets.input_tokens", positive=True
        ),
        "output_tokens": _exact_integer(
            budgets["output_tokens"], "plan.budgets.output_tokens", positive=True
        ),
        "cost_budget_cents": _exact_integer(
            budgets["cost_budget_cents"], "plan.budgets.cost_budget_cents"
        ),
        "timeout_seconds": _exact_integer(
            budgets["timeout_seconds"], "plan.budgets.timeout_seconds", positive=True
        ),
    }
    assert all(isinstance(value, int) for value in safe_budgets.values())
    if (
        safe_budgets["input_tokens"] + safe_budgets["output_tokens"]
        > safe_budgets["context_tokens"]
    ):
        raise ReceiptValidationError("plan input and output budgets exceed context budget")

    assessment = _expect_keys(data["assessment"], _ASSESSMENT_KEYS, "plan.assessment")
    safe_assessment = {
        "schema_version": _exact_integer(
            assessment["schema_version"], "plan.assessment.schema_version", positive=True
        ),
        "task_family": _identifier(assessment["task_family"], "plan.assessment.task_family"),
        "code_scope": _identifier(assessment["code_scope"], "plan.assessment.code_scope"),
        "context_depth": _identifier(
            assessment["context_depth"], "plan.assessment.context_depth"
        ),
        "mutation_scope": _identifier(
            assessment["mutation_scope"], "plan.assessment.mutation_scope"
        ),
        "uncertainty": _identifier(assessment["uncertainty"], "plan.assessment.uncertainty"),
        "expected_duration": _identifier(
            assessment["expected_duration"], "plan.assessment.expected_duration"
        ),
        "risk_flags": _identifier_list(assessment["risk_flags"], "plan.assessment.risk_flags"),
        "minimum_tier": _identifier(
            assessment["minimum_tier"], "plan.assessment.minimum_tier"
        ),
        "verification_needs": _identifier_list(
            assessment["verification_needs"], "plan.assessment.verification_needs"
        ),
        "human_gate": assessment["human_gate"],
        "confidence": _score(assessment["confidence"], "plan.assessment.confidence"),
        "evidence": _identifier_list(assessment["evidence"], "plan.assessment.evidence"),
    }
    if type(safe_assessment["human_gate"]) is not bool:
        raise ReceiptValidationError("plan.assessment.human_gate must be a bool")

    alternatives = data["rejected_alternatives"]
    if not isinstance(alternatives, list):
        raise ReceiptValidationError("plan.rejected_alternatives must be a list")
    safe_alternatives: list[dict[str, str | None]] = []
    for index, alternative in enumerate(alternatives):
        entry = _expect_keys(
            alternative, _ALTERNATIVE_KEYS, f"plan.rejected_alternatives[{index}]"
        )
        safe_alternatives.append(
            {
                "model_id": _identifier(
                    entry["model_id"],
                    f"plan.rejected_alternatives[{index}].model_id",
                    nullable=True,
                ),
                "cost_class": _identifier(
                    entry["cost_class"],
                    f"plan.rejected_alternatives[{index}].cost_class",
                    nullable=True,
                ),
                "direction": _identifier(
                    entry["direction"], f"plan.rejected_alternatives[{index}].direction"
                ),
                "reason_code": _identifier(
                    entry["reason_code"], f"plan.rejected_alternatives[{index}].reason_code"
                ),
            }
        )

    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "policy_version": data["policy_version"],
        "status": status,
        "selected_owner": safe_owner,
        "policy_mode": policy_mode,
        "model_tier": model_tier,
        "model_id": model_id,
        "reasoning_effort": reasoning_effort,
        "budgets": safe_budgets,
        "required_tools": _identifier_list(data["required_tools"], "plan.required_tools"),
        "required_verification": _identifier_list(
            data["required_verification"], "plan.required_verification"
        ),
        "required_approvals": _identifier_list(
            data["required_approvals"], "plan.required_approvals"
        ),
        "assessment": safe_assessment,
        "rejected_alternatives": safe_alternatives,
        "blocker_code": blocker_code,
        "static_fallback_feature": static_fallback_feature,
    }


def _agent_projection(snapshot: TopologySnapshot) -> list[dict[str, Any]]:
    agents: list[dict[str, Any]] = []
    ids: list[str] = []
    for index, contract in enumerate(snapshot.contracts):
        field = f"topology_snapshot.contracts[{index}]"
        agent_id = str(_identifier(contract.agent_id, f"{field}.agent_id"))
        ids.append(agent_id)
        role = contract.role
        if role not in _ROLE_SKILLS or contract.skills != _ROLE_SKILLS[role]:
            raise ReceiptValidationError(
                f"{field}.skills are not allowlisted for role {role.value}"
            )
        expected_output = _ROLE_OUTPUT_CONTRACTS[role]
        if contract.output_contract != expected_output:
            raise ReceiptValidationError(f"{field}.output_contract is unrecognized free text")
        watcher = contract.watcher_contract
        safe_watcher: dict[str, Any] | None = None
        if watcher is not None:
            safe_watcher = {
                "state_artifact": _artifact_path(
                    watcher.state_artifact, f"{field}.watcher_contract.state_artifact"
                ),
                "events_artifact": _artifact_path(
                    watcher.events_artifact, f"{field}.watcher_contract.events_artifact"
                ),
                "summary_artifact": _artifact_path(
                    watcher.summary_artifact, f"{field}.watcher_contract.summary_artifact"
                ),
                "chat_polling_forbidden": watcher.chat_polling_forbidden,
            }
        agents.append(
            {
                "agent_id": agent_id,
                "role": role.value,
                "authoritative_model_id": _identifier(
                    contract.authoritative_model_id, f"{field}.authoritative_model_id"
                ),
                "authoritative_model_tier": contract.authoritative_model_tier.value,
                "authoritative_reasoning_effort": contract.authoritative_reasoning_effort.value,
                "skills": list(contract.skills),
                "context_tools": _identifier_list(contract.context_tools, f"{field}.context_tools"),
                "context_budget": _exact_integer(
                    contract.context_budget, f"{field}.context_budget", positive=True
                ),
                "token_budget": _exact_integer(
                    contract.token_budget, f"{field}.token_budget", positive=True
                ),
                "output_contract": expected_output,
                "depends_on": _identifier_list(contract.depends_on, f"{field}.depends_on"),
                "is_parent_integration_verifier": contract.is_parent_integration_verifier,
                "can_self_expand": contract.can_self_expand,
                "watcher_contract": safe_watcher,
            }
        )
    if len(ids) != len(set(ids)):
        raise ReceiptValidationError("topology_snapshot agents must have unique agent ids")
    return agents


def _escalation_events(snapshot: TopologySnapshot | None) -> list[dict[str, Any]]:
    if snapshot is None:
        return []
    events: list[dict[str, Any]] = []
    for index, event in enumerate(snapshot.escalation_events):
        field = f"topology_snapshot.escalation_events[{index}]"
        evidence = [_artifact_path(item, f"{field}.evidence_refs") for item in event.evidence_refs]
        if len(evidence) != len(set(evidence)):
            raise ReceiptValidationError(f"{field}.evidence_refs must not contain duplicates")
        events.append(
            {
                "kind": event.kind.value,
                "action": event.action.value,
                "agent_id": _identifier(event.agent_id, f"{field}.agent_id"),
                "evidence_refs": evidence,
                "retry_target": _identifier(
                    event.retry_target, f"{field}.retry_target", nullable=True
                ),
                "rejected_agent_id": _identifier(
                    event.rejected_agent_id, f"{field}.rejected_agent_id", nullable=True
                ),
            }
        )
    return events


def _topology_projection(snapshot: TopologySnapshot | None) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    waves = [
        _identifier_list(wave, f"topology_snapshot.execution_waves[{index}]")
        for index, wave in enumerate(snapshot.execution_waves)
    ]
    states = [
        {
            "agent_id": _identifier(state.agent_id, "topology_snapshot.agent_states.agent_id"),
            "status": state.status.value,
            "retry_count": _exact_integer(
                state.retry_count, "topology_snapshot.agent_states.retry_count"
            ),
        }
        for state in snapshot.agent_states
    ]
    return {
        "schema_version": snapshot.schema_version,
        "status": snapshot.status.value,
        "kind": snapshot.kind.value,
        "caps": {
            "global_max_concurrency": snapshot.caps.global_max_concurrency,
            "per_task_max_concurrency": snapshot.caps.per_task_max_concurrency,
            "effective_max_concurrency": snapshot.caps.effective_max_concurrency,
        },
        "execution_waves": waves,
        "agent_states": states,
    }


def _validate_snapshot(
    snapshot: TopologySnapshot | None,
    plan: ExecutionPlan,
    plan_data: Mapping[str, Any],
) -> None:
    if snapshot is None:
        if plan.status is PlanStatus.READY:
            raise ReceiptValidationError("ready plans require a validated TopologySnapshot")
        return
    if type(snapshot) is not TopologySnapshot:
        raise ReceiptValidationError("topology_snapshot must be a validated TopologySnapshot")
    if snapshot.plan is not plan or snapshot.execution_plan is not plan:
        raise ReceiptValidationError("topology_snapshot must retain the identical plan object")

    # Reconstruct from the supplied fields to re-run every topology invariant in
    # case a frozen object was unsafely mutated after construction.
    try:
        TopologySnapshot(
            schema_version=snapshot.schema_version,
            status=snapshot.status,
            kind=snapshot.kind,
            caps=snapshot.caps,
            contracts=snapshot.contracts,
            execution_waves=snapshot.execution_waves,
            agent_states=snapshot.agent_states,
            plan=snapshot.plan,
            escalation_events=snapshot.escalation_events,
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise ReceiptValidationError(f"topology_snapshot failed validation: {exc}") from exc

    if plan.status is PlanStatus.READY:
        if snapshot.status is TopologyStatus.BLOCKED:
            raise ReceiptValidationError("ready plan cannot have a blocked topology snapshot")
    elif (
        snapshot.status is not TopologyStatus.BLOCKED
        or snapshot.contracts
        or snapshot.execution_waves
        or snapshot.agent_states
        or snapshot.escalation_events
    ):
        raise ReceiptValidationError(
            "non-ready plans may only use an empty blocked topology snapshot"
        )

    parent_tools = set(plan_data["required_tools"])
    context_total = 0
    output_total = 0
    ids: list[str] = []
    for contract in snapshot.contracts:
        ids.append(contract.agent_id)
        if contract.authoritative_model_id != plan_data["model_id"]:
            raise ReceiptValidationError("agent model authority differs from execution plan")
        if contract.authoritative_model_tier.value != plan_data["model_tier"]:
            raise ReceiptValidationError("agent model tier differs from execution plan")
        if contract.authoritative_reasoning_effort.value != plan_data["reasoning_effort"]:
            raise ReceiptValidationError("agent reasoning authority differs from execution plan")
        if not set(contract.context_tools).issubset(parent_tools):
            raise ReceiptValidationError("agent tools exceed execution plan authority")
        context_total += contract.context_budget or 0
        output_total += contract.token_budget
    if len(ids) != len(set(ids)):
        raise ReceiptValidationError("topology_snapshot agents must have unique agent ids")
    budgets = plan_data["budgets"]
    if context_total > budgets["input_tokens"]:
        raise ReceiptValidationError("agent context budgets exceed execution plan input budget")
    if output_total > budgets["output_tokens"]:
        raise ReceiptValidationError("agent token budgets exceed execution plan output budget")
    if context_total + output_total > budgets["context_tokens"]:
        raise ReceiptValidationError("agent allocations exceed execution plan context budget")

    # Privacy validation is part of acceptance, not deferred until serialization.
    _agent_projection(snapshot)
    _topology_projection(snapshot)
    _escalation_events(snapshot)


@dataclass(frozen=True, slots=True)
class RetentionMetadata:
    """Explicit retention contract; customer content is never permitted."""

    retention_days: int = 30
    aggregate_retention_days: int = 90
    contains_customer_content: bool = False

    def __post_init__(self) -> None:
        _exact_integer(self.retention_days, "retention_days", positive=True)
        _exact_integer(
            self.aggregate_retention_days, "aggregate_retention_days", positive=True
        )
        if self.aggregate_retention_days < self.retention_days:
            raise ReceiptValidationError(
                "aggregate retention cannot be shorter than receipt retention"
            )
        if self.contains_customer_content is not False:
            raise ReceiptValidationError("routing receipts cannot retain customer content")

    def as_dict(self) -> dict[str, Any]:
        return {
            "aggregate_retention_days": self.aggregate_retention_days,
            "contains_customer_content": False,
            "retention_days": self.retention_days,
        }


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    """Exact reported usage; absent values remain explicit unknowns."""

    provider: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    total_tokens: int | None = None
    cost_cents: int | float | None = None
    latency_ms: int | None = None

    def __post_init__(self) -> None:
        _identifier(self.provider, "provider_usage.provider", nullable=True)
        for field in _TOKEN_FIELDS:
            _exact_integer(
                getattr(self, field), f"provider_usage.{field}", nullable=True
            )
        _number(self.cost_cents, "provider_usage.cost_cents", nullable=True)
        _exact_integer(
            self.latency_ms, "provider_usage.latency_ms", nullable=True
        )
        if (
            self.cached_input_tokens is not None
            and self.input_tokens is not None
            and self.cached_input_tokens > self.input_tokens
        ):
            raise ReceiptValidationError(
                "provider_usage.cached_input_tokens cannot exceed input_tokens"
            )
        if (
            self.total_tokens is not None
            and self.input_tokens is not None
            and self.output_tokens is not None
            and self.total_tokens != self.input_tokens + self.output_tokens
        ):
            raise ReceiptValidationError(
                "provider_usage.total_tokens must exactly equal input_tokens plus output_tokens"
            )

    def as_dict(self) -> dict[str, Any]:
        values = {field: getattr(self, field) for field in _USAGE_FIELDS}
        values["unknown_fields"] = [field for field in _USAGE_FIELDS if values[field] is None]
        return values


@dataclass(frozen=True, slots=True)
class RoutingOutcome:
    """Observed outcome supplied after routing; no value is inferred."""

    status: str = "unknown"
    first_route_correct: bool | None = None
    cost_assessment: str = "unknown"
    quality_score: float | None = None
    rework_required: bool | None = None
    latency_ms: int | None = None

    def __post_init__(self) -> None:
        if self.status not in _OUTCOME_STATUSES:
            raise ReceiptValidationError("outcome status is invalid")
        if self.cost_assessment not in _COST_ASSESSMENTS:
            raise ReceiptValidationError("outcome cost_assessment is invalid")
        for field in ("first_route_correct", "rework_required"):
            value = getattr(self, field)
            if value is not None and type(value) is not bool:
                raise ReceiptValidationError(f"outcome {field} must be bool or null")
        _score(self.quality_score, "outcome.quality_score")
        _exact_integer(self.latency_ms, "outcome.latency_ms", nullable=True)

    def as_dict(self) -> dict[str, Any]:
        return {
            "cost_assessment": self.cost_assessment,
            "first_route_correct": self.first_route_correct,
            "latency_ms": self.latency_ms,
            "quality_score": self.quality_score,
            "rework_required": self.rework_required,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class OverrideIndicators:
    """Allowlisted override facts.  ``None`` means unknown, never false."""

    tier_requested: bool | None = None
    model_requested: bool | None = None
    reasoning_requested: bool | None = None
    human_approved: bool | None = None
    applied: bool | None = None

    def __post_init__(self) -> None:
        for field in (
            "tier_requested",
            "model_requested",
            "reasoning_requested",
            "human_approved",
            "applied",
        ):
            value = getattr(self, field)
            if value is not None and type(value) is not bool:
                raise ReceiptValidationError(f"overrides.{field} must be bool or null")

    def as_dict(self) -> dict[str, Any]:
        fields = (
            "tier_requested",
            "model_requested",
            "reasoning_requested",
            "human_approved",
            "applied",
        )
        values = {field: getattr(self, field) for field in fields}
        values["unknown_fields"] = [field for field in fields if values[field] is None]
        return values


@dataclass(frozen=True, slots=True)
class RoutingReceipt:
    """Canonical receipt bound to one plan and its controller snapshot."""

    receipt_id: str
    project_id: str
    customer_id: str | None
    plan: ExecutionPlan
    retention: RetentionMetadata = RetentionMetadata()
    topology_snapshot: TopologySnapshot | None = None
    override_indicators: OverrideIndicators = OverrideIndicators()
    verification_status: str = "unknown"
    outcome: RoutingOutcome = RoutingOutcome()
    provider_usage: ProviderUsage = ProviderUsage()
    schema_version: int = RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RECEIPT_SCHEMA_VERSION:
            raise ReceiptValidationError("unsupported routing receipt schema_version")
        _identifier(self.receipt_id, "receipt_id")
        _identifier(self.project_id, "project_id")
        _identifier(self.customer_id, "customer_id", nullable=True)
        if type(self.retention) is not RetentionMetadata:
            raise ReceiptValidationError("retention must be RetentionMetadata")
        if type(self.override_indicators) is not OverrideIndicators:
            raise ReceiptValidationError("override_indicators must be OverrideIndicators")
        if type(self.outcome) is not RoutingOutcome:
            raise ReceiptValidationError("outcome must be RoutingOutcome")
        if type(self.provider_usage) is not ProviderUsage:
            raise ReceiptValidationError("provider_usage must be ProviderUsage")
        if self.verification_status not in _VERIFICATION_STATUSES:
            raise ReceiptValidationError("verification_status is invalid")
        plan_data = _validated_plan_projection(self.plan)
        _validate_snapshot(self.topology_snapshot, self.plan, plan_data)

    @classmethod
    def from_execution_plan(
        cls,
        plan: ExecutionPlan,
        *,
        project_id: str,
        customer_id: str | None = None,
        receipt_id: str | None = None,
        retention: RetentionMetadata = RetentionMetadata(),
        topology_snapshot: TopologySnapshot | None = None,
        override_indicators: OverrideIndicators = OverrideIndicators(),
        verification_status: str = "unknown",
        outcome: RoutingOutcome = RoutingOutcome(),
        provider_usage: ProviderUsage = ProviderUsage(),
    ) -> "RoutingReceipt":
        _validated_plan_projection(plan)
        execution_nonce = uuid.uuid4().hex[:24]
        generated_id = "route-" + "x".join(
            execution_nonce[index:index + 4]
            for index in range(0, len(execution_nonce), 4)
        )
        return cls(
            receipt_id=receipt_id or generated_id,
            project_id=project_id,
            customer_id=customer_id,
            plan=plan,
            retention=retention,
            topology_snapshot=topology_snapshot,
            override_indicators=override_indicators,
            verification_status=verification_status,
            outcome=outcome,
            provider_usage=provider_usage,
        )

    def as_dict(self) -> dict[str, Any]:
        plan = _validated_plan_projection(self.plan)
        _validate_snapshot(self.topology_snapshot, self.plan, plan)
        assessment = plan["assessment"]
        events = _escalation_events(self.topology_snapshot)
        plan_fingerprint = hashlib.sha256(
            _canonical_json(plan).encode("utf-8")
        ).hexdigest()[:24]
        return {
            "agents": (
                []
                if self.topology_snapshot is None
                else _agent_projection(self.topology_snapshot)
            ),
            "assessment": assessment,
            "customer_id": self.customer_id,
            "escalation": {
                "events": events,
                "required": bool(plan["required_approvals"] or events)
                or plan["status"]
                in {PlanStatus.BLOCKED.value, PlanStatus.HUMAN_APPROVAL_REQUIRED.value},
                "required_approvals": plan["required_approvals"],
            },
            "outcome": self.outcome.as_dict(),
            "overrides": self.override_indicators.as_dict(),
            "policy": {"mode": plan["policy_mode"], "version": plan["policy_version"]},
            "project_id": self.project_id,
            "plan_fingerprint": f"plan-{plan_fingerprint}",
            "provider_usage": self.provider_usage.as_dict(),
            "receipt_id": self.receipt_id,
            "retention": self.retention.as_dict(),
            "routing": {
                "blocker_code": plan["blocker_code"],
                "budgets": plan["budgets"],
                "execution_plan_schema_version": plan["schema_version"],
                "model_id": plan["model_id"],
                "model_tier": plan["model_tier"],
                "reasoning_effort": plan["reasoning_effort"],
                "rejected_alternatives": plan["rejected_alternatives"],
                "required_tools": plan["required_tools"],
                "selected_owner": plan["selected_owner"],
                "static_fallback_feature": plan["static_fallback_feature"],
                "status": plan["status"],
            },
            "schema_version": self.schema_version,
            "schema_versions": {
                "execution_plan": plan["schema_version"],
                "receipt": self.schema_version,
                "task_assessment": assessment["schema_version"],
                "topology": (
                    None
                    if self.topology_snapshot is None
                    else self.topology_snapshot.schema_version
                ),
            },
            "topology": _topology_projection(self.topology_snapshot),
            "verification": {
                "required": plan["required_verification"],
                "status": self.verification_status,
            },
        }

    def to_json(self) -> str:
        return _canonical_json(self.as_dict())

    def to_markdown(self) -> str:
        """Return a readable and lossless escaped projection of the receipt."""
        data = self.as_dict()
        routing = data["routing"]
        usage = data["provider_usage"]
        topology = data["topology"]
        schema_versions = data["schema_versions"]
        assert isinstance(routing, Mapping)
        assert isinstance(usage, Mapping)
        assert isinstance(schema_versions, Mapping)

        lines = [
            "# Adaptive Routing Receipt",
            "",
            "## Identity and schema versions",
            "",
            "| Field | Value |",
            "| --- | --- |",
            f"| Receipt | {_markdown_value(data['receipt_id'])} |",
            f"| Project | {_markdown_value(data['project_id'])} |",
            f"| Customer scope | {_markdown_value(data['customer_id'])} |",
            f"| Receipt schema | {_markdown_value(schema_versions['receipt'])} |",
            f"| Execution plan schema | {_markdown_value(schema_versions['execution_plan'])} |",
            f"| Task assessment schema | {_markdown_value(schema_versions['task_assessment'])} |",
            f"| Topology schema | {_markdown_value(schema_versions['topology'])} |",
            "",
            "## Routing decision",
            "",
            f"- Policy: {_markdown_value(data['policy'])}",
            f"- Status: {_markdown_value(routing['status'])}",
            "- Model authority: "
            + _markdown_value(
                {
                    "model_id": routing["model_id"],
                    "model_tier": routing["model_tier"],
                    "reasoning_effort": routing["reasoning_effort"],
                }
            ),
            f"- Owner: {_markdown_value(routing['selected_owner'])}",
            f"- Tools: {_markdown_value(routing['required_tools'])}",
            f"- Budgets: {_markdown_value(routing['budgets'])}",
            f"- Blocker: {_markdown_value(routing['blocker_code'])}",
            f"- Static fallback: {_markdown_value(routing['static_fallback_feature'])}",
            f"- Rejected alternatives: {_markdown_value(routing['rejected_alternatives'])}",
            "",
            "## Assessment and verification",
            "",
            f"- Assessment: {_markdown_value(data['assessment'])}",
            f"- Verification: {_markdown_value(data['verification'])}",
            "",
            "## Topology",
            "",
            f"- Snapshot: {_markdown_value(topology)}",
            f"- Agents: {_markdown_value(data['agents'])}",
            "",
            "## Escalation and overrides",
            "",
            f"- Escalation: {_markdown_value(data['escalation'])}",
            f"- Overrides: {_markdown_value(data['overrides'])}",
            "",
            "## Usage and outcome",
            "",
            "| Usage field | Value |",
            "| --- | ---: |",
        ]
        for field in _USAGE_FIELDS:
            lines.append(f"| {html.escape(field)} | {_markdown_value(usage[field])} |")
        lines.extend(
            [
                f"| Unknown usage fields | {_markdown_value(usage['unknown_fields'])} |",
                "",
                f"- Outcome: {_markdown_value(data['outcome'])}",
                f"- Retention: {_markdown_value(data['retention'])}",
                "",
                "## Canonical JSON",
                "",
                "The indented JSON below is the complete canonical validated receipt.",
                "",
                f"    {self.to_json()}",
                "",
            ]
        )
        return "\n".join(lines)


def _markdown_value(value: object) -> str:
    if value is None:
        return "**unknown**"
    if isinstance(value, bool):
        raw = "true" if value else "false"
    elif isinstance(value, str):
        raw = value
    elif type(value) in (int, float):
        raw = str(value)
    else:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"<code>{html.escape(raw, quote=True).replace('|', '&#124;')}</code>"


@dataclass(frozen=True, slots=True)
class MetricSummary:
    """One advisory metric with an explicit known/unknown denominator."""

    value: float | None
    known_count: int
    unknown_count: int

    def __post_init__(self) -> None:
        _exact_integer(self.known_count, "metric.known_count")
        _exact_integer(self.unknown_count, "metric.unknown_count")
        if self.known_count == 0 and self.value is not None:
            raise ReceiptValidationError("metric without known observations must be null")
        if self.known_count > 0:
            _number(self.value, "metric.value")

    def as_dict(self) -> dict[str, int | float | None]:
        return {
            "known_count": self.known_count,
            "total_count": self.known_count + self.unknown_count,
            "unknown_count": self.unknown_count,
            "value": self.value,
        }


@dataclass(frozen=True, slots=True)
class CohortCounts:
    static: int = 0
    adaptive: int = 0
    blocked: int = 0
    human_gate: int = 0

    def __post_init__(self) -> None:
        for field in _COHORTS:
            _exact_integer(getattr(self, field), f"cohort_counts.{field}")

    def as_dict(self) -> dict[str, int]:
        return {field: getattr(self, field) for field in _COHORTS}


@dataclass(frozen=True, slots=True)
class CohortQuality:
    static: MetricSummary
    adaptive: MetricSummary
    blocked: MetricSummary
    human_gate: MetricSummary

    def __post_init__(self) -> None:
        for field in _COHORTS:
            if type(getattr(self, field)) is not MetricSummary:
                raise ReceiptValidationError(
                    f"quality_by_cohort.{field} must be MetricSummary"
                )

    def as_dict(self) -> dict[str, dict[str, int | float | None]]:
        return {field: getattr(self, field).as_dict() for field in _COHORTS}


@dataclass(frozen=True, slots=True)
class RoutingMetrics:
    cohort_counts: CohortCounts
    false_cheap_rate: MetricSummary
    false_expensive_rate: MetricSummary
    first_route_accuracy: MetricSummary
    latency_ms_average: MetricSummary
    override_rate: MetricSummary
    quality_average: MetricSummary
    rework_rate: MetricSummary
    quality_by_cohort: CohortQuality

    def __post_init__(self) -> None:
        if type(self.cohort_counts) is not CohortCounts:
            raise ReceiptValidationError("metrics.cohort_counts must be CohortCounts")
        for field in (
            "false_cheap_rate",
            "false_expensive_rate",
            "first_route_accuracy",
            "latency_ms_average",
            "override_rate",
            "quality_average",
            "rework_rate",
        ):
            if type(getattr(self, field)) is not MetricSummary:
                raise ReceiptValidationError(f"metrics.{field} must be MetricSummary")
        if type(self.quality_by_cohort) is not CohortQuality:
            raise ReceiptValidationError(
                "metrics.quality_by_cohort must be CohortQuality"
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "cohort_counts": self.cohort_counts.as_dict(),
            "false_cheap_rate": self.false_cheap_rate.as_dict(),
            "false_expensive_rate": self.false_expensive_rate.as_dict(),
            "first_route_accuracy": self.first_route_accuracy.as_dict(),
            "latency_ms_average": self.latency_ms_average.as_dict(),
            "override_rate": self.override_rate.as_dict(),
            "quality_average": self.quality_average.as_dict(),
            "quality_by_cohort": self.quality_by_cohort.as_dict(),
            "rework_rate": self.rework_rate.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class RoutingTelemetry:
    """Offline advisory aggregate with no policy-write surface."""

    project_id: str
    customer_id: str | None
    receipt_count: int
    metrics: RoutingMetrics
    retention: RetentionMetadata
    schema_version: int = TELEMETRY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != TELEMETRY_SCHEMA_VERSION:
            raise ReceiptValidationError("unsupported routing telemetry schema_version")
        _identifier(self.project_id, "telemetry.project_id")
        _identifier(self.customer_id, "telemetry.customer_id", nullable=True)
        _exact_integer(self.receipt_count, "telemetry.receipt_count", positive=True)
        if type(self.metrics) is not RoutingMetrics:
            raise ReceiptValidationError("telemetry.metrics must be RoutingMetrics")
        if type(self.retention) is not RetentionMetadata:
            raise ReceiptValidationError("telemetry.retention must be RetentionMetadata")
        if sum(self.metrics.cohort_counts.as_dict().values()) != self.receipt_count:
            raise ReceiptValidationError("telemetry cohort counts must cover every receipt")

    def as_dict(self) -> dict[str, Any]:
        return {
            "advisory_only": True,
            "customer_id": self.customer_id,
            "metrics": self.metrics.as_dict(),
            "policy_mutation_permitted": False,
            "project_id": self.project_id,
            "receipt_count": self.receipt_count,
            "retention": self.retention.as_dict(),
            "schema_version": self.schema_version,
        }

    def to_json(self) -> str:
        return _canonical_json(self.as_dict())


def _cohort(receipt: RoutingReceipt) -> str:
    return {
        PlanStatus.STATIC_FALLBACK: "static",
        PlanStatus.READY: "adaptive",
        PlanStatus.BLOCKED: "blocked",
        PlanStatus.HUMAN_APPROVAL_REQUIRED: "human_gate",
    }[receipt.plan.status]


def _metric(values: Sequence[bool | int | float | None]) -> MetricSummary:
    known = [value for value in values if value is not None]
    value = None if not known else float(sum(known) / len(known))
    return MetricSummary(
        value=value,
        known_count=len(known),
        unknown_count=len(values) - len(known),
    )


def aggregate_routing_receipts(receipts: Sequence[RoutingReceipt]) -> RoutingTelemetry:
    """Aggregate exactly one project/customer boundary into advisory telemetry."""
    if not isinstance(receipts, Sequence) or not receipts:
        raise ReceiptValidationError("receipts must be a non-empty sequence")
    if any(type(receipt) is not RoutingReceipt for receipt in receipts):
        raise ReceiptValidationError("receipts must contain RoutingReceipt values")
    for receipt in receipts:
        receipt.as_dict()
    receipt_ids = [receipt.receipt_id for receipt in receipts]
    if len(receipt_ids) != len(set(receipt_ids)):
        raise ReceiptValidationError("aggregate requires unique receipt ids")
    project_ids = {receipt.project_id for receipt in receipts}
    customer_ids = {receipt.customer_id for receipt in receipts}
    if len(project_ids) != 1 or len(customer_ids) != 1:
        raise ReceiptValidationError("aggregate cannot cross project or customer boundaries")

    outcomes = [receipt.outcome for receipt in receipts]
    cohorts = [_cohort(receipt) for receipt in receipts]
    cohort_counts = CohortCounts(
        **{name: cohorts.count(name) for name in _COHORTS}
    )
    quality_by_cohort = CohortQuality(
        **{
            name: _metric(
                [
                    receipt.outcome.quality_score
                    for receipt, cohort in zip(receipts, cohorts)
                    if cohort == name
                ]
            )
            for name in _COHORTS
        }
    )
    metrics = RoutingMetrics(
        cohort_counts=cohort_counts,
        false_cheap_rate=_metric(
            [
                None
                if outcome.cost_assessment == "unknown"
                else outcome.cost_assessment == "too_cheap"
                for outcome in outcomes
            ]
        ),
        false_expensive_rate=_metric(
            [
                None
                if outcome.cost_assessment == "unknown"
                else outcome.cost_assessment == "too_expensive"
                for outcome in outcomes
            ]
        ),
        first_route_accuracy=_metric([outcome.first_route_correct for outcome in outcomes]),
        latency_ms_average=_metric([outcome.latency_ms for outcome in outcomes]),
        override_rate=_metric(
            [receipt.override_indicators.applied for receipt in receipts]
        ),
        quality_average=_metric([outcome.quality_score for outcome in outcomes]),
        rework_rate=_metric([outcome.rework_required for outcome in outcomes]),
        quality_by_cohort=quality_by_cohort,
    )
    retention = RetentionMetadata(
        retention_days=min(receipt.retention.retention_days for receipt in receipts),
        aggregate_retention_days=min(
            receipt.retention.aggregate_retention_days for receipt in receipts
        ),
    )
    return RoutingTelemetry(
        project_id=next(iter(project_ids)),
        customer_id=next(iter(customer_ids)),
        receipt_count=len(receipts),
        metrics=metrics,
        retention=retention,
    )
