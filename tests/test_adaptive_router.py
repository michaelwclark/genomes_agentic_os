"""Deterministic dry-run coverage for the adaptive execution-plan resolver."""

from __future__ import annotations

from dataclasses import replace

import pytest

from genomes_agentic_os.adaptive_policy import (
    AdaptivePolicy,
    ModelCatalog,
    ModelCandidate,
    ModelTier,
    PolicyLayers,
    PolicyMode,
    RuntimePolicyDocument,
    DEFAULT_MODEL_CATALOG,
    FEATURE_62_STATIC_FALLBACK,
    TIER_ROUTES,
    TierRoute,
    ReasoningEffort,
)
from genomes_agentic_os.adaptive_router import (
    OwnerCandidate,
    OwnerKind,
    PlanBudget,
    PlanOverrides,
    PlanStatus,
    ReasonCode,
    resolve_execution_plan,
)


def _policy(mode: PolicyMode = PolicyMode.GUARDED) -> AdaptivePolicy:
    return AdaptivePolicy(mode=mode, default_tier=ModelTier.ECONOMY)


def test_simple_jira_plan_is_economy_with_tracker_readback() -> None:
    plan = resolve_execution_plan(
        "Update Jira CC-212 status and add a triage label.", _policy()
    )

    assert plan.status is PlanStatus.READY
    assert plan.model_tier is ModelTier.ECONOMY
    assert plan.model_id == "gpt-5.6-luna"
    assert plan.reasoning_effort is not None
    assert plan.reasoning_effort.value == "medium"
    assert plan.required_verification == ("tracker_readback",)
    assert plan.budgets.context_tokens == 16_000
    assert any(item.direction == "more_expensive" for item in plan.rejected_alternatives)


def test_complex_monolith_plan_uses_frontier_and_rejects_cheaper_models() -> None:
    plan = resolve_execution_plan(
        "Refactor the monolith across multiple modules and update its API.", _policy()
    )

    assert plan.status is PlanStatus.READY
    assert plan.model_tier is ModelTier.FRONTIER
    assert plan.model_id == "gpt-5.6-sol"
    assert {item.model_id for item in plan.rejected_alternatives} == {
        "gpt-5.6-luna", "gpt-5.6-terra"
    }
    assert {item.reason_code for item in plan.rejected_alternatives} == {
        ReasonCode.BELOW_REQUIRED_CAPABILITY
    }


def test_owner_workflow_is_chosen_before_model_topology() -> None:
    candidates = (
        OwnerCandidate("quick-skill", OwnerKind.SKILL, priority=10),
        OwnerCandidate(
            "monolith-workflow",
            OwnerKind.WORKFLOW,
            priority=10,
            minimum_tier="frontier",
            required_tools=("repository_read",),
            verification=("owner_review",),
            approvals=("change_owner",),
        ),
    )
    plan = resolve_execution_plan("Update a Jira ticket status.", _policy(), owner_candidates=candidates)

    assert plan.selected_owner is not None
    assert plan.selected_owner.identifier == "monolith-workflow"
    assert plan.model_tier is ModelTier.FRONTIER
    assert plan.required_tools == ("repository_read",)
    assert plan.required_verification == ("owner_review", "tracker_readback")
    assert plan.required_approvals == ("change_owner",)


def test_overrides_can_strengthen_but_cannot_bypass_assessment_floor() -> None:
    policy = AdaptivePolicy(
        mode=PolicyMode.OBSERVE,
        default_tier=ModelTier.ECONOMY,
        allow_model_overrides=True,
        allowed_model_overrides=frozenset({"economy", "frontier"}),
    )
    plan = resolve_execution_plan(
        "Deploy this change to production.",
        policy,
        overrides=PlanOverrides(tier="economy", model_override="economy"),
    )

    assert plan.model_tier is ModelTier.HUMAN_GATE
    assert plan.status is PlanStatus.BLOCKED
    assert plan.blocker_code is ReasonCode.CAPABILITY_UNAVAILABLE
    assert plan.model_id is None


def test_overrides_cannot_lower_policy_default_floor() -> None:
    policy = AdaptivePolicy(
        mode=PolicyMode.ENFORCE,
        default_tier=ModelTier.FRONTIER,
        allow_model_overrides=True,
        allowed_model_overrides=frozenset({"gpt-5.6-luna"}),
    )
    plan = resolve_execution_plan(
        "Update Jira CC-212 status.",
        policy,
        overrides=PlanOverrides(tier="economy", model_override="gpt-5.6-luna"),
    )

    assert plan.model_tier is ModelTier.FRONTIER
    assert plan.status is PlanStatus.BLOCKED
    assert plan.blocker_code is ReasonCode.CAPABILITY_UNAVAILABLE


def test_human_gate_returns_structured_approval_requirement() -> None:
    plan = resolve_execution_plan(
        "Deploy this change to production.",
        AdaptivePolicy(mode=PolicyMode.OBSERVE, default_tier=ModelTier.ECONOMY),
    )

    assert plan.status is PlanStatus.HUMAN_APPROVAL_REQUIRED
    assert plan.model_id == "gpt-5.6-sol"
    assert plan.blocker_code is ReasonCode.HUMAN_APPROVAL_REQUIRED
    assert "human_approval" in plan.required_approvals


def test_off_policy_uses_existing_static_fallback_without_model_selection() -> None:
    plan = resolve_execution_plan(
        "Update Jira CC-212 status.", AdaptivePolicy(mode=PolicyMode.OFF)
    )

    assert plan.status is PlanStatus.STATIC_FALLBACK
    assert plan.blocker_code is ReasonCode.POLICY_OFF_STATIC_FALLBACK
    assert plan.static_fallback_feature == "62-role-aware-codex-config-layers"
    assert plan.model_id is None


def test_unavailable_required_capability_is_structured_blocker_without_downgrade() -> None:
    unavailable = tuple(
        replace(record, available=False)
        if record.model_id == "gpt-5.6-sol"
        else record
        for record in DEFAULT_MODEL_CATALOG.records
    )
    document = RuntimePolicyDocument(
        schema_version=1,
        policy_version=1,
        layers=PolicyLayers(),
        policy=AdaptivePolicy(mode=PolicyMode.GUARDED, default_tier=ModelTier.ECONOMY),
        catalog=ModelCatalog(unavailable),
        tier_routes=TIER_ROUTES,
        static_fallback=FEATURE_62_STATIC_FALLBACK,
    )
    plan = resolve_execution_plan(
        "Refactor the monolith across multiple modules.", document
    )

    assert plan.status is PlanStatus.BLOCKED
    assert plan.blocker_code is ReasonCode.CAPABILITY_UNAVAILABLE
    assert plan.model_id is None
    assert plan.model_tier is ModelTier.FRONTIER


def test_duplicate_owner_identifiers_are_rejected_deterministically() -> None:
    owners = (
        OwnerCandidate("owner", OwnerKind.WORKFLOW, minimum_tier="economy"),
        OwnerCandidate("owner", OwnerKind.WORKFLOW, minimum_tier="frontier"),
    )

    with pytest.raises(ValueError, match="duplicate identifiers"):
        resolve_execution_plan(
            "Update Jira CC-212 status.",
            _policy(),
            owner_candidates=owners,
        )


def test_rejected_alternatives_use_eligibility_and_equal_cost_reasons() -> None:
    records = tuple(
        replace(record, available=False)
        if record.model_id == "gpt-5.6-luna"
        else replace(record, cost_class="standard")
        if record.model_id == "gpt-5.6-sol"
        else record
        for record in DEFAULT_MODEL_CATALOG.records
    )
    document = RuntimePolicyDocument(
        schema_version=1,
        policy_version=1,
        layers=PolicyLayers(),
        policy=AdaptivePolicy(
            mode=PolicyMode.GUARDED,
            default_tier=ModelTier.BALANCED,
        ),
        catalog=ModelCatalog(records),
        tier_routes=TIER_ROUTES,
        static_fallback=FEATURE_62_STATIC_FALLBACK,
    )

    plan = resolve_execution_plan("Update Jira CC-212 status.", document)
    rejected = {item.model_id: item for item in plan.rejected_alternatives}

    assert rejected["gpt-5.6-luna"].reason_code is ReasonCode.MODEL_UNAVAILABLE
    assert rejected["gpt-5.6-sol"].direction == "equal_cost"
    assert rejected["gpt-5.6-sol"].reason_code is ReasonCode.NOT_SELECTED_BY_ROUTE


def test_alternative_uses_its_configured_effort_not_selected_effort() -> None:
    records = tuple(
        replace(
            record,
            supported_reasoning_efforts=(
                ReasoningEffort.HIGH,
                ReasoningEffort.ULTRA,
            ),
        )
        if record.model_id == "gpt-5.6-sol"
        else record
        for record in DEFAULT_MODEL_CATALOG.records
    )
    routes = dict(TIER_ROUTES)
    balanced = routes[ModelTier.BALANCED]
    routes[ModelTier.BALANCED] = TierRoute(
        ModelTier.BALANCED,
        (
            balanced.candidates[0],
            ModelCandidate(
                "frontier",
                ReasoningEffort.HIGH,
                balanced.candidates[1].requirements,
            ),
        ),
    )
    document = RuntimePolicyDocument(
        schema_version=1,
        policy_version=1,
        layers=PolicyLayers(),
        policy=AdaptivePolicy(
            mode=PolicyMode.GUARDED,
            default_tier=ModelTier.BALANCED,
        ),
        catalog=ModelCatalog(records),
        tier_routes=routes,
        static_fallback=FEATURE_62_STATIC_FALLBACK,
    )

    plan = resolve_execution_plan("Handle this somehow.", document)
    rejected = {item.model_id: item for item in plan.rejected_alternatives}

    assert rejected["gpt-5.6-sol"].reason_code is ReasonCode.MORE_EXPENSIVE_THAN_REQUIRED


def test_owner_strengthened_requirements_explain_ineligible_alternative() -> None:
    records = tuple(
        replace(record, context_tokens=32_000)
        if record.model_id == "gpt-5.6-luna"
        else record
        for record in DEFAULT_MODEL_CATALOG.records
    )
    document = RuntimePolicyDocument(
        schema_version=1,
        policy_version=1,
        layers=PolicyLayers(),
        policy=AdaptivePolicy(
            mode=PolicyMode.GUARDED,
            default_tier=ModelTier.ECONOMY,
        ),
        catalog=ModelCatalog(records),
        tier_routes=TIER_ROUTES,
        static_fallback=FEATURE_62_STATIC_FALLBACK,
    )
    owner = OwnerCandidate(
        "large-context-owner",
        OwnerKind.WORKFLOW,
        min_context_tokens=64_000,
    )

    plan = resolve_execution_plan(
        "Update Jira CC-212 status.",
        document,
        owner_candidates=(owner,),
    )
    rejected = {item.model_id: item for item in plan.rejected_alternatives}

    assert plan.model_id == "gpt-5.6-terra"
    assert rejected["gpt-5.6-luna"].reason_code is ReasonCode.REQUIREMENTS_UNSATISFIED


def test_serialization_is_stable_and_redacts_raw_task_text_and_secrets() -> None:
    task = "Update Jira CC-212. api_key=super-secret-value and token=abc123"
    first = resolve_execution_plan(task, _policy())
    second = resolve_execution_plan(task, _policy())

    assert first.to_json() == second.to_json()
    assert task not in first.to_json()
    assert "super-secret-value" not in first.to_json()
    assert "abc123" not in first.to_json()


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"output_tokens": 0}, "output_tokens"),
        ({"input_tokens": -1}, "input_tokens"),
        ({"timeout_seconds": 1.5}, "timeout_seconds"),
        ({"cost_budget_cents": -1}, "cost_budget_cents"),
        (
            {"context_tokens": 10, "input_tokens": 8, "output_tokens": 4},
            "cannot exceed context_tokens",
        ),
    ],
)
def test_plan_budget_rejects_invalid_authority(
    kwargs: dict[str, int | float], message: str
) -> None:
    values: dict[str, int | float] = {
        "context_tokens": 100,
        "input_tokens": 50,
        "output_tokens": 20,
        "cost_budget_cents": 1,
        "timeout_seconds": 30,
    }
    values.update(kwargs)

    with pytest.raises(ValueError, match=message):
        PlanBudget(**values)  # type: ignore[arg-type]
