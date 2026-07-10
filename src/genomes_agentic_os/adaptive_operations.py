"""Pure operator controls for the adaptive-routing rollout.

These helpers deliberately only read explicit operator inputs and return
canonical, redacted dictionaries.  They do not install policy, execute an
execution plan, write receipts, or infer a policy/holdout path.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from .adaptive_evaluation import (
    FixtureBaselineResolver,
    EvaluationValidationError,
    evaluate_holdout,
    load_holdout_fixture,
    validate_report,
)
from .adaptive_policy import (
    FEATURE_62_STATIC_FALLBACK,
    PolicyMode,
    RuntimePolicyDocument,
    load_policy_file,
)
from .adaptive_router import (
    OwnerCandidate,
    OwnerKind,
    PlanOverrides,
    PlanStatus,
    resolve_execution_plan,
)
from .adaptive_topology import TopologyKind, build_topology


OPERATION_SCHEMA_VERSION = 1
EXIT_OK = 0
EXIT_INVALID_INPUT = 2
EXIT_BLOCKED = 3
FIRST_ACTIVE_MODE = PolicyMode.GUARDED
_OPERATOR_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_SECRET_REFERENCE = re.compile(
    r"(?:^sk[_-]|^ghp_|^github_pat_|api[_-]?key|secret|password|bearer|"
    r"access[_-]?token|auth[_-]?token)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class HoldoutEvidence:
    report: Mapping[str, object]
    runtime_policy_fingerprint: str | None


def canonical_json(value: Mapping[str, object]) -> str:
    """Return stable JSON suitable for an operator-owned dry-run receipt."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def load_explicit_policy(path: str | Path) -> RuntimePolicyDocument:
    """Load a policy without including a caller-controlled path in errors."""
    try:
        document = load_policy_file(path)
    except (OSError, ValueError) as exc:
        raise ValueError("unable to load a valid explicit policy file") from exc
    if document.static_fallback != FEATURE_62_STATIC_FALLBACK:
        raise ValueError("policy must preserve the reviewed Feature 62 static fallback")
    return document


def _policy_metadata(document: RuntimePolicyDocument) -> dict[str, object]:
    payload = {
        "policy_version": document.policy_version,
        "mode": document.policy.mode.value,
        "default_tier": document.policy.default_tier.value,
        "static_fallback_feature": FEATURE_62_STATIC_FALLBACK.feature,
    }
    fingerprint = runtime_policy_fingerprint(document)
    return {**payload, "fingerprint": fingerprint}


def runtime_policy_fingerprint(document: RuntimePolicyDocument) -> str:
    """Commit every runtime routing input used by enforce eligibility."""
    def layer_payload(layer: object) -> dict[str, object]:
        return {
            "version": getattr(layer, "version"),
            "mode": getattr(layer, "mode").value if getattr(layer, "mode") else None,
            "default_tier": (
                getattr(layer, "default_tier").value
                if getattr(layer, "default_tier") else None
            ),
            "customer_safe": getattr(layer, "customer_safe"),
            "allow_model_overrides": getattr(layer, "allow_model_overrides"),
            "allowed_model_overrides": (
                sorted(getattr(layer, "allowed_model_overrides"))
                if getattr(layer, "allowed_model_overrides") is not None else None
            ),
        }

    policy = document.policy
    payload: dict[str, object] = {
        "schema_version": document.schema_version,
        "policy_version": document.policy_version,
        "layers": {
            name: layer_payload(getattr(document.layers, name))
            for name in ("host", "project", "workflow", "customer")
        },
        "policy": {
            "version": policy.version,
            "mode": policy.mode.value,
            "default_tier": policy.default_tier.value,
            "customer_safe": policy.customer_safe,
            "allow_model_overrides": policy.allow_model_overrides,
            "allowed_model_overrides": sorted(policy.allowed_model_overrides),
        },
        "catalog": [
            {
                "model_id": record.model_id,
                "aliases": sorted(record.aliases),
                "capability_tier": record.capability_tier.value,
                "supported_reasoning_efforts": [
                    effort.value for effort in record.supported_reasoning_efforts
                ],
                "coding": record.coding,
                "tool_use": record.tool_use,
                "context_tokens": record.context_tokens,
                "subagent_suitable": record.subagent_suitable,
                "cost_class": record.cost_class.value,
                "customer_safe": record.customer_safe,
                "available": record.available,
            }
            for record in sorted(document.catalog.records, key=lambda item: item.model_id)
        ],
        "tier_routes": {
            tier.value: {
                "requires_human_approval": route.requires_human_approval,
                "candidates": [
                    {
                        "model_id": candidate.model_id,
                        "reasoning_effort": candidate.reasoning_effort.value,
                        "requirements": {
                            "coding": candidate.requirements.coding,
                            "tool_use": candidate.requirements.tool_use,
                            "min_context_tokens": candidate.requirements.min_context_tokens,
                            "subagent_suitable": candidate.requirements.subagent_suitable,
                        },
                    }
                    for candidate in route.candidates
                ],
            }
            for tier, route in sorted(
                document.tier_routes.items(), key=lambda item: item[0].value
            )
        },
        "static_fallback": {
            "feature": document.static_fallback.feature,
            "behavior": document.static_fallback.behavior,
        },
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _opted_out_layer(document: RuntimePolicyDocument) -> str | None:
    """Project/customer off is a one-way safety opt-out for this rollout."""
    for name in ("project", "customer"):
        layer = getattr(document.layers, name)
        if layer.mode is PolicyMode.OFF:
            return name
    return None


def _static_document(document: RuntimePolicyDocument) -> RuntimePolicyDocument:
    return replace(document, policy=replace(document.policy, mode=PolicyMode.OFF))


def load_holdout_report(path: str | Path | None) -> HoldoutEvidence | None:
    if path is None:
        return None
    try:
        parsed = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("unable to load a valid explicit holdout report") from exc
    if not isinstance(parsed, dict):
        raise ValueError("holdout report must be a JSON object")
    binding: str | None = None
    if parsed.get("operation") == "adaptive-routing-evaluate":
        binding = parsed.get("runtime_policy_fingerprint")  # type: ignore[assignment]
        parsed = parsed.get("report")
    if not isinstance(parsed, dict) or (
        binding is not None
        and (not isinstance(binding, str) or not re.fullmatch(r"[0-9a-f]{64}", binding))
    ):
        raise ValueError("holdout report must contain an evaluation report object")
    return HoldoutEvidence(parsed, binding)


def enforce_eligibility(
    document: RuntimePolicyDocument,
    report: HoldoutEvidence | Mapping[str, object] | None,
) -> dict[str, object]:
    """Evaluate the sole allowed entry gate for enforce mode, without writes."""
    evidence = (
        HoldoutEvidence(report, None)
        if isinstance(report, Mapping)
        else report
    )
    if evidence is not None:
        try:
            validate_report(evidence.report)
        except EvaluationValidationError as exc:
            raise ValueError("holdout report does not satisfy the evaluation contract") from exc
    if document.policy.mode is not PolicyMode.ENFORCE:
        return {
            "required": False,
            "eligible": True,
            "reason": "policy_not_enforce",
        }
    if evidence is None:
        return {
            "required": True,
            "eligible": False,
            "reason": "approved_no_breach_holdout_report_required",
        }
    if evidence.runtime_policy_fingerprint != runtime_policy_fingerprint(document):
        return {
            "required": True,
            "eligible": False,
            "reason": "holdout_runtime_policy_fingerprint_mismatch",
        }
    guarded = evidence.report["guarded_mode"]
    breaches = evidence.report["threshold_breaches"]
    approved = isinstance(guarded, Mapping) and guarded.get("approval_granted") is True
    no_breaches = isinstance(breaches, list) and not breaches
    eligible = approved and no_breaches and guarded.get("decision") == "go"
    return {
        "required": True,
        "eligible": eligible,
        "reason": "approved_no_breach_holdout_report" if eligible else "holdout_report_not_approved_or_has_breaches",
    }


def _owner_candidate(
    *,
    identifier: str | None,
    kind: str | None,
    minimum_tier: str | None,
    required_verification: tuple[str, ...],
) -> tuple[OwnerCandidate, ...]:
    supplied = (identifier, kind, minimum_tier, required_verification)
    if not any(supplied):
        return ()
    if not identifier or not kind:
        raise ValueError("owner override requires both owner identifier and owner kind")
    if not _OPERATOR_REFERENCE.fullmatch(identifier) or _SECRET_REFERENCE.search(identifier):
        raise ValueError("owner identifier must be an opaque, path-free reference")
    if any(
        not _OPERATOR_REFERENCE.fullmatch(item) or _SECRET_REFERENCE.search(item)
        for item in required_verification
    ):
        raise ValueError("owner verification overrides must be opaque, path-free references")
    return (
        OwnerCandidate(
            identifier=identifier,
            kind=OwnerKind(kind),
            minimum_tier=minimum_tier,
            verification=required_verification,
        ),
    )


def _customer_safety_eligibility(
    document: RuntimePolicyDocument,
    model_id: str | None,
) -> dict[str, object]:
    """Fail closed if a customer-safe policy would select an unsafe model."""
    if document.policy.customer_safe is not True:
        return {"required": False, "eligible": True, "reason": "not_required"}
    if model_id is None:
        return {
            "required": True,
            "eligible": True,
            "reason": "no_adaptive_model_selected",
        }
    record = document.catalog.get(model_id)
    eligible = record is not None and record.customer_safe is True
    return {
        "required": True,
        "eligible": eligible,
        "reason": "customer_safe_model" if eligible else "customer_safe_model_required",
    }


def build_plan(
    *,
    task: str,
    document: RuntimePolicyDocument,
    tier: str | None = None,
    model_override: str | None = None,
    reasoning_effort: str | None = None,
    owner_identifier: str | None = None,
    owner_kind: str | None = None,
    owner_minimum_tier: str | None = None,
    owner_verification: tuple[str, ...] = (),
    no_sub_agents: bool = False,
    holdout_report: HoldoutEvidence | Mapping[str, object] | None = None,
) -> tuple[dict[str, object], int]:
    """Build a fully offline plan and topology; never dispatches its contracts."""
    if not isinstance(task, str) or not task.strip():
        raise ValueError("task must be a non-empty explicit string")
    if type(no_sub_agents) is not bool:
        raise ValueError("no_sub_agents must be a bool")
    if not isinstance(owner_verification, tuple) or any(
        not isinstance(item, str) or not item for item in owner_verification
    ):
        raise ValueError("owner verification overrides must be non-empty strings")
    owners = _owner_candidate(
        identifier=owner_identifier,
        kind=owner_kind,
        minimum_tier=owner_minimum_tier,
        required_verification=owner_verification,
    )
    eligibility = enforce_eligibility(document, holdout_report)
    opted_out = _opted_out_layer(document)
    effective_document = _static_document(document) if opted_out else document
    plan = resolve_execution_plan(
        task,
        effective_document,
        owner_candidates=owners,
        overrides=PlanOverrides(
            tier=tier,
            model_override=model_override,
            reasoning_effort=reasoning_effort,
        ),
    )
    topology = build_topology(plan)
    customer_safety = _customer_safety_eligibility(
        effective_document,
        plan.model_id,
    )
    blocker: str | None = None
    operation_status = "ready"
    if opted_out:
        operation_status = "static_fallback"
        blocker = f"{opted_out}_opt_out_forces_static_fallback"
    elif not eligibility["eligible"]:
        operation_status = "blocked"
        blocker = str(eligibility["reason"])
    elif plan.status is PlanStatus.STATIC_FALLBACK:
        operation_status = "static_fallback"
    elif plan.status is not PlanStatus.READY:
        operation_status = "blocked"
        blocker = (
            plan.blocker_code.value
            if plan.blocker_code is not None
            else "routing_plan_not_ready"
        )
    elif not customer_safety["eligible"]:
        operation_status = "blocked"
        blocker = str(customer_safety["reason"])
    elif no_sub_agents and topology.kind is not TopologyKind.OPERATOR_ONLY:
        operation_status = "replan_required"
        blocker = "no_sub_agents_would_remove_required_verification"
    result: dict[str, object] = {
        "schema_version": OPERATION_SCHEMA_VERSION,
        "operation": "adaptive-routing-plan",
        "execution": "never",
        "policy": _policy_metadata(effective_document),
        "rollout": {
            "lifecycle": effective_document.policy.mode.value,
            "first_active_mode": FIRST_ACTIVE_MODE.value,
            "project_or_customer_opt_out": opted_out,
            "enforce_eligibility": eligibility,
            "customer_safety": customer_safety,
        },
        "operation_status": operation_status,
        "blocker": blocker,
        "execution_plan": plan.as_dict(),
        "topology": topology.as_dict(),
        "subagent_policy": {
            "requested_no_sub_agents": no_sub_agents,
            "accepted": not no_sub_agents or topology.kind is TopologyKind.OPERATOR_ONLY,
            "required_topology": topology.kind.value,
            "verification_preserved": True,
        },
    }
    return result, EXIT_OK if operation_status in {"ready", "static_fallback"} else EXIT_BLOCKED


def evaluate(
    *,
    holdout_file: str | Path,
    document: RuntimePolicyDocument,
    approval_granted: bool,
) -> tuple[dict[str, object], int]:
    """Produce an observe-only report with explicit built-in evidence inputs."""
    if type(approval_granted) is not bool:
        raise ValueError("approval_granted must be a bool")
    try:
        fixture = load_holdout_fixture(holdout_file)
    except (OSError, ValueError) as exc:
        raise ValueError("unable to load a valid explicit holdout file") from exc
    report = evaluate_holdout(
        fixture,
        catalog=document.catalog,
        baseline_resolver=FixtureBaselineResolver.from_fixture(fixture),
        runtime_policy=document,
        approval_granted=approval_granted,
    )
    return {
        "schema_version": OPERATION_SCHEMA_VERSION,
        "operation": "adaptive-routing-evaluate",
        "execution": "never",
        "catalog": "built_in_default_model_catalog",
        "baseline": "fixture_explicit_baseline",
        "runtime_policy_fingerprint": runtime_policy_fingerprint(document),
        "report": report,
    }, EXIT_OK


def status(
    *,
    document: RuntimePolicyDocument,
    holdout_report: HoldoutEvidence | Mapping[str, object] | None = None,
) -> tuple[dict[str, object], int]:
    """Show only read-only rollout state and the enforce gate."""
    opted_out = _opted_out_layer(document)
    eligibility = enforce_eligibility(document, holdout_report)
    mode = PolicyMode.OFF if opted_out else document.policy.mode
    result: dict[str, object] = {
        "schema_version": OPERATION_SCHEMA_VERSION,
        "operation": "adaptive-routing-status",
        "execution": "never",
        "policy": _policy_metadata(
            _static_document(document) if opted_out else document
        ),
        "rollout": {
            "lifecycle": mode.value,
            "first_active_mode": FIRST_ACTIVE_MODE.value,
            "project_or_customer_opt_out": opted_out,
            "enforce_eligibility": eligibility,
            "customer_safety_required": document.policy.customer_safe,
        },
    }
    return result, EXIT_OK if eligibility["eligible"] or mode is not PolicyMode.ENFORCE else EXIT_BLOCKED


def rollback_plan(
    *,
    document: RuntimePolicyDocument,
    last_known_good: RuntimePolicyDocument | None = None,
) -> tuple[dict[str, object], int]:
    """Return static-only rollback instructions without changing any state."""
    known_good = last_known_good or document
    result: dict[str, object] = {
        "schema_version": OPERATION_SCHEMA_VERSION,
        "operation": "adaptive-routing-rollback-plan",
        "execution": "never",
        "rollback": {
            "target_mode": PolicyMode.OFF.value,
            "adaptive_routing": "disabled",
            "static_fallback": {
                "feature": FEATURE_62_STATIC_FALLBACK.feature,
                "behavior": FEATURE_62_STATIC_FALLBACK.behavior,
            },
            "last_known_good_policy": _policy_metadata(known_good),
            "receipt_path_semantics": {
                "historical_receipts": "preserve_unchanged",
                "write_path": None,
                "deletion": "forbidden",
            },
            "instructions": [
                "Set adaptive routing mode to off through the normal reviewed configuration path.",
                "Preserve all historical policy, evaluation, plan, and topology receipts unchanged.",
                "Resume Feature 62 static layer model and reasoning configuration.",
            ],
        },
    }
    return result, EXIT_OK
