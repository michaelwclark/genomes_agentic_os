"""Offline, deterministic execution-plan resolution for adaptive routing.

This module is deliberately a planner, not a runtime integration.  It composes
the privacy-safe signals from :mod:`task_assessment` with the capability-safe
selection in :mod:`adaptive_policy`; it never executes a tool or retains the
input task text in a returned plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from typing import Mapping, Optional

from .adaptive_policy import (
    AdaptivePolicy,
    CAPABILITY_RANK,
    CapabilityUnavailableError,
    CostClass,
    HumanApprovalRequiredError,
    ModelCandidate,
    ModelRequirements,
    ModelTier,
    PolicyMode,
    PolicyResolution,
    ReasoningEffort,
    RoutingRequest,
    RuntimePolicyDocument,
    TIER_CAPABILITY_FLOOR,
    TierRoute,
    at_least_tier,
    capability_safe,
    resolve_policy,
)
from .task_assessment import TaskAssessment, assess_task


PLAN_SCHEMA_VERSION = 1


class OwnerKind(str, Enum):
    WORKFLOW = "workflow"
    SKILL = "skill"


class PlanStatus(str, Enum):
    READY = "ready"
    STATIC_FALLBACK = "static_fallback"
    HUMAN_APPROVAL_REQUIRED = "human_approval_required"
    BLOCKED = "blocked"


class ReasonCode(str, Enum):
    """Stable, machine-readable reasons for non-selected route choices."""

    OWNER_CANDIDATE_PREFERRED = "owner_candidate_preferred"
    BELOW_REQUIRED_CAPABILITY = "below_required_capability"
    MORE_EXPENSIVE_THAN_REQUIRED = "more_expensive_than_required"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    HUMAN_APPROVAL_REQUIRED = "human_approval_required"
    POLICY_OFF_STATIC_FALLBACK = "policy_off_static_fallback"
    MODEL_UNAVAILABLE = "model_unavailable"
    UNSUPPORTED_REASONING_EFFORT = "unsupported_reasoning_effort"
    CUSTOMER_SAFETY_REQUIRED = "customer_safety_required"
    REQUIREMENTS_UNSATISFIED = "requirements_unsatisfied"
    NOT_SELECTED_BY_ROUTE = "not_selected_by_route"


@dataclass(frozen=True, slots=True)
class OwnerCandidate:
    """A discovered workflow or skill, considered before model selection.

    ``priority`` is ascending.  Equal priorities prefer a workflow over a
    skill, then use the identifier as a stable tie-breaker.  Candidate floors
    can strengthen assessment requirements but never weaken them.
    """

    identifier: str
    kind: OwnerKind | str
    priority: int = 100
    minimum_tier: ModelTier | str | None = None
    required_reasoning_effort: ReasoningEffort | str | None = None
    min_context_tokens: int = 0
    required_tools: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()
    approvals: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.identifier, str) or not self.identifier:
            raise ValueError("owner candidate identifier must be a non-empty string")
        object.__setattr__(self, "kind", OwnerKind(self.kind))
        if type(self.priority) is not int:
            raise ValueError("owner candidate priority must be an integer")
        if self.minimum_tier is not None:
            object.__setattr__(self, "minimum_tier", ModelTier(self.minimum_tier))
        if self.required_reasoning_effort is not None:
            object.__setattr__(
                self,
                "required_reasoning_effort",
                ReasoningEffort(self.required_reasoning_effort),
            )
        if type(self.min_context_tokens) is not int or self.min_context_tokens < 0:
            raise ValueError("owner candidate min_context_tokens must be non-negative")
        for name in ("required_tools", "verification", "approvals"):
            values = getattr(self, name)
            if (
                not isinstance(values, tuple)
                or any(not isinstance(item, str) or not item for item in values)
            ):
                raise ValueError(f"owner candidate {name} must be a tuple of strings")
            if len(set(values)) != len(values):
                raise ValueError(f"owner candidate {name} must not contain duplicates")


@dataclass(frozen=True, slots=True)
class PlanOverrides:
    """Optional request intent; the policy remains the authority for floors."""

    tier: ModelTier | str | None = None
    model_override: str | None = None
    reasoning_effort: ReasoningEffort | str | None = None
    human_approved: bool = False

    def __post_init__(self) -> None:
        if self.tier is not None:
            object.__setattr__(self, "tier", ModelTier(self.tier))
        if self.reasoning_effort is not None:
            object.__setattr__(
                self, "reasoning_effort", ReasoningEffort(self.reasoning_effort)
            )
        if self.model_override is not None and (
            not isinstance(self.model_override, str) or not self.model_override
        ):
            raise ValueError("model_override must be a non-empty string or null")
        if type(self.human_approved) is not bool:
            raise ValueError("human_approved must be a bool")


@dataclass(frozen=True, slots=True)
class PlanBudget:
    context_tokens: int
    input_tokens: int
    output_tokens: int
    cost_budget_cents: int
    timeout_seconds: int

    def __post_init__(self) -> None:
        for name in (
            "context_tokens",
            "input_tokens",
            "output_tokens",
            "timeout_seconds",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if type(self.cost_budget_cents) is not int or self.cost_budget_cents < 0:
            raise ValueError("cost_budget_cents must be a non-negative integer")
        if self.input_tokens + self.output_tokens > self.context_tokens:
            raise ValueError(
                "input_tokens plus output_tokens cannot exceed context_tokens"
            )

    def as_dict(self) -> dict[str, int]:
        return {
            "context_tokens": self.context_tokens,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_budget_cents": self.cost_budget_cents,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True, slots=True)
class RejectedAlternative:
    model_id: str | None
    cost_class: str | None
    direction: str
    reason_code: ReasonCode

    def as_dict(self) -> dict[str, str | None]:
        return {
            "model_id": self.model_id,
            "cost_class": self.cost_class,
            "direction": self.direction,
            "reason_code": self.reason_code.value,
        }


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    """A serializable, redacted dry-run plan with no raw task-text field."""

    schema_version: int
    policy_version: int
    status: PlanStatus
    selected_owner: OwnerCandidate | None
    policy_mode: PolicyMode
    model_tier: ModelTier
    model_id: str | None
    reasoning_effort: ReasoningEffort | None
    budgets: PlanBudget
    required_tools: tuple[str, ...]
    required_verification: tuple[str, ...]
    required_approvals: tuple[str, ...]
    assessment: TaskAssessment
    rejected_alternatives: tuple[RejectedAlternative, ...]
    blocker_code: ReasonCode | None = None
    static_fallback_feature: str | None = None

    def as_dict(self) -> dict[str, object]:
        owner = self.selected_owner
        return {
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "status": self.status.value,
            "selected_owner": (
                None
                if owner is None
                else {"identifier": owner.identifier, "kind": owner.kind.value}
            ),
            "policy_mode": self.policy_mode.value,
            "model_tier": self.model_tier.value,
            "model_id": self.model_id,
            "reasoning_effort": (
                self.reasoning_effort.value if self.reasoning_effort else None
            ),
            "budgets": self.budgets.as_dict(),
            "required_tools": list(self.required_tools),
            "required_verification": list(self.required_verification),
            "required_approvals": list(self.required_approvals),
            "assessment": self.assessment.as_dict(),
            "rejected_alternatives": [
                alternative.as_dict() for alternative in self.rejected_alternatives
            ],
            "blocker_code": self.blocker_code.value if self.blocker_code else None,
            "static_fallback_feature": self.static_fallback_feature,
        }

    def to_json(self) -> str:
        """Return canonical JSON suitable for deterministic receipts."""
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))


_BUDGETS: Mapping[ModelTier, PlanBudget] = {
    ModelTier.ECONOMY: PlanBudget(16_000, 8_000, 2_000, 2, 300),
    ModelTier.BALANCED: PlanBudget(48_000, 24_000, 6_000, 12, 900),
    ModelTier.FRONTIER: PlanBudget(96_000, 48_000, 12_000, 40, 1_800),
    ModelTier.FRONTIER_MAX: PlanBudget(128_000, 64_000, 16_000, 75, 2_700),
    ModelTier.HUMAN_GATE: PlanBudget(128_000, 64_000, 16_000, 75, 2_700),
}
_COST_ORDER = {
    CostClass.ECONOMY: 0,
    CostClass.STANDARD: 1,
    CostClass.PREMIUM: 2,
}


def resolve_execution_plan(
    task_text: str,
    policy: AdaptivePolicy | RuntimePolicyDocument,
    *,
    owner_candidates: tuple[OwnerCandidate, ...] = (),
    overrides: PlanOverrides = PlanOverrides(),
) -> ExecutionPlan:
    """Build a deterministic, non-executing plan from assessment and policy.

    Owner candidates are chosen before the model tier is computed.  The only
    task-text use is the local call to :func:`assess_task`; the resulting plan
    retains derived evidence only.  Capability failures and approval gates are
    represented as structured results rather than a lower-tier retry.
    """
    if not isinstance(overrides, PlanOverrides):
        raise ValueError("overrides must be PlanOverrides")
    if not isinstance(owner_candidates, tuple) or any(
        not isinstance(candidate, OwnerCandidate) for candidate in owner_candidates
    ):
        raise ValueError("owner_candidates must be a tuple of OwnerCandidate")
    owner_ids = tuple(candidate.identifier for candidate in owner_candidates)
    if len(set(owner_ids)) != len(owner_ids):
        raise ValueError("owner_candidates must not contain duplicate identifiers")

    assessment = assess_task(task_text)
    owner = _select_owner(owner_candidates)
    policy_version, policy_mode, default_tier = _policy_values(policy)
    request = RoutingRequest(
        tier=overrides.tier,
        assessment_minimum_tier=assessment.minimum_tier,
        minimum_tier=owner.minimum_tier if owner else None,
        model_override=overrides.model_override,
        reasoning_effort=overrides.reasoning_effort,
        required_reasoning_effort=(
            owner.required_reasoning_effort if owner else None
        ),
        human_approved=overrides.human_approved,
    )
    tier = at_least_tier(
        default_tier,
        *(() if request.tier is None else (request.tier,)),
        request.assessment_minimum_tier,
        *(() if request.minimum_tier is None else (request.minimum_tier,)),
    )
    tier_routes = _with_owner_context_requirement(policy, tier, owner)
    effective_tier_routes = tier_routes
    if effective_tier_routes is None:
        if isinstance(policy, RuntimePolicyDocument):
            effective_tier_routes = policy.tier_routes
        else:
            from .adaptive_policy import TIER_ROUTES

            effective_tier_routes = TIER_ROUTES
    base_kwargs = _plan_fields(assessment, owner)

    try:
        resolution = resolve_policy(policy, request, tier_routes=tier_routes)
    except HumanApprovalRequiredError:
        return _blocked_plan(
            policy_version, policy_mode, tier, assessment, owner, base_kwargs,
            ReasonCode.HUMAN_APPROVAL_REQUIRED,
        )
    except CapabilityUnavailableError:
        return _blocked_plan(
            policy_version, policy_mode, tier, assessment, owner, base_kwargs,
            ReasonCode.CAPABILITY_UNAVAILABLE,
        )

    return _plan_from_resolution(
        resolution,
        assessment,
        owner,
        policy,
        effective_tier_routes,
        base_kwargs,
    )


def _select_owner(candidates: tuple[OwnerCandidate, ...]) -> OwnerCandidate | None:
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: (
            item.priority,
            0 if item.kind is OwnerKind.WORKFLOW else 1,
            item.identifier,
        ),
    )


def _policy_values(
    policy: AdaptivePolicy | RuntimePolicyDocument,
) -> tuple[int, PolicyMode, ModelTier]:
    resolved = policy.policy if isinstance(policy, RuntimePolicyDocument) else policy
    if not isinstance(resolved, AdaptivePolicy):
        raise ValueError("policy must be an AdaptivePolicy or RuntimePolicyDocument")
    return resolved.version, resolved.mode, resolved.default_tier


def _with_owner_context_requirement(
    policy: AdaptivePolicy | RuntimePolicyDocument,
    tier: ModelTier,
    owner: OwnerCandidate | None,
) -> Mapping[ModelTier, TierRoute] | None:
    """Strengthen only the selected tier's reviewed route requirements."""
    if owner is None or not owner.min_context_tokens and not owner.required_tools:
        return None
    document = policy if isinstance(policy, RuntimePolicyDocument) else None
    routes = document.tier_routes if document else None
    if routes is None:
        # ``resolve_policy`` supplies the built-in routes for an AdaptivePolicy;
        # resolving it once would select a model before the owner contract.
        # Importing the public constant keeps those reviewed routes canonical.
        from .adaptive_policy import TIER_ROUTES

        routes = TIER_ROUTES
    route = routes[tier]
    strengthened = tuple(
        _strengthen_candidate(candidate, owner) for candidate in route.candidates
    )
    replacement = TierRoute(tier, strengthened, route.requires_human_approval)
    amended = dict(routes)
    amended[tier] = replacement
    return amended


def _strengthen_candidate(
    candidate: ModelCandidate, owner: OwnerCandidate
) -> ModelCandidate:
    requirements = candidate.requirements
    return ModelCandidate(
        candidate.model_id,
        candidate.reasoning_effort,
        ModelRequirements(
            coding=requirements.coding,
            tool_use=True if owner.required_tools else requirements.tool_use,
            min_context_tokens=max(requirements.min_context_tokens, owner.min_context_tokens),
            subagent_suitable=requirements.subagent_suitable,
        ),
    )


def _plan_fields(
    assessment: TaskAssessment, owner: OwnerCandidate | None
) -> dict[str, tuple[str, ...]]:
    tools = owner.required_tools if owner else ()
    verification = set(assessment.verification_needs)
    approvals: set[str] = set()
    if owner:
        verification.update(owner.verification)
        approvals.update(owner.approvals)
    if assessment.human_gate:
        approvals.add("human_approval")
    return {
        "required_tools": tuple(sorted(tools)),
        "required_verification": tuple(sorted(verification)),
        "required_approvals": tuple(sorted(approvals)),
    }


def _blocked_plan(
    policy_version: int,
    policy_mode: PolicyMode,
    tier: ModelTier,
    assessment: TaskAssessment,
    owner: OwnerCandidate | None,
    fields: dict[str, tuple[str, ...]],
    blocker: ReasonCode,
) -> ExecutionPlan:
    approvals = set(fields["required_approvals"])
    if blocker is ReasonCode.HUMAN_APPROVAL_REQUIRED:
        approvals.add("human_approval")
    return ExecutionPlan(
        PLAN_SCHEMA_VERSION,
        policy_version,
        PlanStatus.BLOCKED,
        owner,
        policy_mode,
        tier,
        None,
        None,
        _BUDGETS[tier],
        fields["required_tools"],
        fields["required_verification"],
        tuple(sorted(approvals)),
        assessment,
        (),
        blocker,
    )


def _plan_from_resolution(
    resolution: PolicyResolution,
    assessment: TaskAssessment,
    owner: OwnerCandidate | None,
    policy: AdaptivePolicy | RuntimePolicyDocument,
    tier_routes: Mapping[ModelTier, TierRoute],
    fields: dict[str, tuple[str, ...]],
) -> ExecutionPlan:
    if resolution.static_fallback is not None:
        return ExecutionPlan(
            PLAN_SCHEMA_VERSION, resolution.version, PlanStatus.STATIC_FALLBACK,
            owner, resolution.mode, resolution.tier, None, None,
            _BUDGETS[resolution.tier], fields["required_tools"],
            fields["required_verification"], fields["required_approvals"],
            assessment, (), ReasonCode.POLICY_OFF_STATIC_FALLBACK,
            resolution.static_fallback.feature,
        )
    selection = resolution.selection
    if selection is None:
        raise AssertionError("non-fallback policy resolution must contain a selection")
    status = (
        PlanStatus.HUMAN_APPROVAL_REQUIRED
        if resolution.human_approval_required
        else PlanStatus.READY
    )
    approvals = set(fields["required_approvals"])
    if resolution.human_approval_required:
        approvals.add("human_approval")
    return ExecutionPlan(
        PLAN_SCHEMA_VERSION, resolution.version, status, owner, resolution.mode,
        selection.tier, selection.model_id, selection.reasoning_effort,
        _BUDGETS[selection.tier], fields["required_tools"],
        fields["required_verification"], tuple(sorted(approvals)), assessment,
        _rejected_alternatives(
            policy,
            selection.model_id,
            selection.tier,
            tier_routes,
        ),
        ReasonCode.HUMAN_APPROVAL_REQUIRED if resolution.human_approval_required else None,
    )


def _rejected_alternatives(
    policy: AdaptivePolicy | RuntimePolicyDocument,
    selected_model_id: str,
    selected_tier: ModelTier,
    tier_routes: Mapping[ModelTier, TierRoute],
) -> tuple[RejectedAlternative, ...]:
    catalog = policy.catalog if isinstance(policy, RuntimePolicyDocument) else None
    if catalog is None:
        from .adaptive_policy import DEFAULT_MODEL_CATALOG

        catalog = DEFAULT_MODEL_CATALOG
    selected = catalog.get(selected_model_id)
    if selected is None:
        return ()
    route = tier_routes[selected_tier]
    route_candidates = {
        resolved.model_id: candidate
        for candidate in route.candidates
        if (resolved := catalog.get(candidate.model_id)) is not None
    }
    resolved_policy = (
        policy.policy if isinstance(policy, RuntimePolicyDocument) else policy
    )
    customer_safe_required = resolved_policy.customer_safe
    required_capability = TIER_CAPABILITY_FLOOR[selected_tier]
    result: list[RejectedAlternative] = []
    for record in sorted(catalog.records, key=lambda item: item.model_id):
        if record.model_id == selected.model_id:
            continue
        cost_comparison = (
            _COST_ORDER[record.cost_class] - _COST_ORDER[selected.cost_class]
        )
        direction = (
            "cheaper" if cost_comparison < 0
            else "more_expensive" if cost_comparison > 0
            else "equal_cost"
        )
        required_rank = CAPABILITY_RANK[required_capability]
        route_candidate = route_candidates.get(record.model_id)
        if not record.available:
            reason = ReasonCode.MODEL_UNAVAILABLE
        elif record.capability_rank < required_rank:
            reason = ReasonCode.BELOW_REQUIRED_CAPABILITY
        elif customer_safe_required and not record.customer_safe:
            reason = ReasonCode.CUSTOMER_SAFETY_REQUIRED
        elif route_candidate is None:
            reason = ReasonCode.NOT_SELECTED_BY_ROUTE
        elif not capability_safe(
            route_candidate,
            catalog,
            customer_safe_required=customer_safe_required,
            required_capability_tier=required_capability,
        ):
            if not record.supports(route_candidate.reasoning_effort):
                reason = ReasonCode.UNSUPPORTED_REASONING_EFFORT
            elif not record.satisfies(route_candidate.requirements):
                reason = ReasonCode.REQUIREMENTS_UNSATISFIED
            else:
                reason = ReasonCode.NOT_SELECTED_BY_ROUTE
        elif cost_comparison > 0:
            reason = ReasonCode.MORE_EXPENSIVE_THAN_REQUIRED
        else:
            reason = ReasonCode.NOT_SELECTED_BY_ROUTE
        result.append(
            RejectedAlternative(
                record.model_id,
                record.cost_class.value,
                direction,
                reason,
            )
        )
    return tuple(result)
