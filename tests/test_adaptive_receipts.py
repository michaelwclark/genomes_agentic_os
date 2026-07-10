"""Adversarial coverage for the hardened adaptive receipt boundary."""

from __future__ import annotations

from dataclasses import replace
import json

import pytest

from genomes_agentic_os.adaptive_policy import (
    AdaptivePolicy,
    ModelTier,
    PolicyMode,
    ReasoningEffort,
)
from genomes_agentic_os.adaptive_receipts import (
    OverrideIndicators,
    ProviderUsage,
    RECEIPT_SCHEMA_VERSION,
    ReceiptValidationError,
    RetentionMetadata,
    RoutingOutcome,
    RoutingReceipt,
    TELEMETRY_SCHEMA_VERSION,
    aggregate_routing_receipts,
)
from genomes_agentic_os.adaptive_router import (
    OwnerCandidate,
    OwnerKind,
    PlanStatus,
    resolve_execution_plan,
)
from genomes_agentic_os.adaptive_topology import (
    AgentOutcome,
    TopologyStatus,
    apply_outcome,
    build_topology,
)


def _plan(mode: PolicyMode = PolicyMode.GUARDED):
    return resolve_execution_plan(
        "Refactor the monolith across multiple modules and update its API.",
        AdaptivePolicy(mode=mode, default_tier=ModelTier.ECONOMY),
    )


def _retry_snapshot():
    plan = resolve_execution_plan(
        "Implement a bounded change in module.py.",
        AdaptivePolicy(mode=PolicyMode.GUARDED, default_tier=ModelTier.ECONOMY),
    )
    snapshot = build_topology(plan)
    snapshot = apply_outcome(snapshot, AgentOutcome("planner", True))
    snapshot = apply_outcome(
        snapshot,
        AgentOutcome(
            "implementer",
            False,
            evidence_refs=("artifacts/test.log",),
        ),
    )
    return plan, snapshot


def test_receipt_is_snapshot_derived_versioned_and_canonical() -> None:
    plan = _plan()
    snapshot = build_topology(plan)
    receipt = RoutingReceipt.from_execution_plan(
        plan,
        project_id="genomes-agentic-os",
        topology_snapshot=snapshot,
        override_indicators=OverrideIndicators(
            tier_requested=False,
            model_requested=False,
            reasoning_requested=False,
            human_approved=False,
            applied=False,
        ),
    )

    data = json.loads(receipt.to_json())
    assert receipt.to_json() == receipt.to_json()
    assert data["schema_version"] == RECEIPT_SCHEMA_VERSION
    assert data["schema_versions"] == {
        "execution_plan": 1,
        "receipt": RECEIPT_SCHEMA_VERSION,
        "task_assessment": 1,
        "topology": 1,
    }
    assert data["routing"]["model_tier"] == "frontier"
    assert data["topology"]["status"] == "ready"
    assert data["topology"]["execution_waves"] == [list(wave) for wave in snapshot.execution_waves]
    assert data["topology"]["caps"]["effective_max_concurrency"] == 3
    assert [agent["agent_id"] for agent in data["agents"]] == [
        contract.agent_id for contract in snapshot.contracts
    ]
    assert data["escalation"]["events"] == []
    assert data["provider_usage"]["cost_cents"] is None
    assert "cost_cents" in data["provider_usage"]["unknown_fields"]


def test_ready_plan_requires_snapshot_but_non_ready_plans_may_omit_it() -> None:
    with pytest.raises(ReceiptValidationError, match="ready plans require"):
        RoutingReceipt.from_execution_plan(_plan(), project_id="project")

    cases = (
        resolve_execution_plan("Update Jira CC-214 status.", AdaptivePolicy(mode=PolicyMode.OFF)),
        resolve_execution_plan(
            "Deploy this change to production.",
            AdaptivePolicy(mode=PolicyMode.GUARDED, default_tier=ModelTier.ECONOMY),
        ),
        resolve_execution_plan(
            "Deploy this change to production.",
            AdaptivePolicy(mode=PolicyMode.OBSERVE, default_tier=ModelTier.ECONOMY),
        ),
    )
    assert {plan.status for plan in cases} == {
        PlanStatus.STATIC_FALLBACK,
        PlanStatus.BLOCKED,
        PlanStatus.HUMAN_APPROVAL_REQUIRED,
    }
    for index, plan in enumerate(cases):
        without_snapshot = RoutingReceipt.from_execution_plan(
            plan, project_id="project", receipt_id=f"non-ready-{index}"
        )
        with_snapshot = RoutingReceipt.from_execution_plan(
            plan,
            project_id="project",
            receipt_id=f"non-ready-snapshot-{index}",
            topology_snapshot=build_topology(plan),
        )
        assert without_snapshot.as_dict()["topology"] is None
        assert with_snapshot.as_dict()["topology"]["status"] == "blocked"
        assert with_snapshot.as_dict()["agents"] == []


def test_receipt_rejects_equal_but_nonidentical_plan_snapshot_pair() -> None:
    plan = _plan()
    equal_plan = replace(plan)
    assert equal_plan == plan and equal_plan is not plan

    with pytest.raises(ReceiptValidationError, match="identical plan object"):
        RoutingReceipt.from_execution_plan(
            equal_plan,
            project_id="project",
            topology_snapshot=build_topology(plan),
        )


def test_arbitrary_topology_escalation_agent_and_override_mappings_are_rejected() -> None:
    plan = _plan()
    with pytest.raises(ReceiptValidationError, match="TopologySnapshot"):
        RoutingReceipt.from_execution_plan(
            plan,
            project_id="project",
            topology_snapshot={"kind": "forged"},  # type: ignore[arg-type]
        )
    with pytest.raises(ReceiptValidationError, match="OverrideIndicators"):
        RoutingReceipt.from_execution_plan(
            plan,
            project_id="project",
            topology_snapshot=build_topology(plan),
            override_indicators={  # type: ignore[arg-type]
                "applied": True,
                "note": "customer text",
            },
        )
    with pytest.raises(TypeError):
        RoutingReceipt.from_execution_plan(
            plan,
            project_id="project",
            topology={"kind": "forged"},  # type: ignore[call-arg]
            escalation={"required": False},  # type: ignore[call-arg]
            agents=({"identifier": "forged", "role": "worker"},),  # type: ignore[call-arg]
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "model",
        "tier",
        "reasoning",
        "tools",
        "budget",
        "status",
        "kind",
        "duplicate-agent",
    ),
)
def test_cross_module_plan_topology_mismatches_fail_closed(mutation: str) -> None:
    plan = _plan()
    snapshot = build_topology(plan)
    contract = snapshot.contracts[0]
    if mutation == "model":
        object.__setattr__(contract, "authoritative_model_id", "gpt-5.6-terra")
    elif mutation == "tier":
        object.__setattr__(contract, "authoritative_model_tier", ModelTier.BALANCED)
    elif mutation == "reasoning":
        object.__setattr__(contract, "authoritative_reasoning_effort", ReasoningEffort.LOW)
    elif mutation == "tools":
        object.__setattr__(contract, "context_tools", ("unapproved_tool",))
    elif mutation == "budget":
        object.__setattr__(contract, "token_budget", plan.budgets.output_tokens + 1)
    elif mutation == "status":
        object.__setattr__(snapshot, "status", TopologyStatus.BLOCKED)
    elif mutation == "kind":
        object.__setattr__(snapshot, "kind", "operator_only")
    else:
        object.__setattr__(snapshot.contracts[1], "agent_id", contract.agent_id)

    with pytest.raises(ReceiptValidationError, match="topology|agent"):
        RoutingReceipt.from_execution_plan(
            plan,
            project_id="project",
            topology_snapshot=snapshot,
        )


@pytest.mark.parametrize(
    "unsafe_id",
    (
        "project free text",
        "123-45-6789",
        "/Users/genome/private-project",
        r"C:\Users\genome\private-project",
        "c2VjcmV0LWN1c3RvbWVyLXRva2Vu",
        "c2VjcmV0",
        "YXBpa2V5",
        "YXBpX2tleQ",
        "MTIzLTQ1LTY3ODk",
        "ghp_0123456789abcdefghijklmnop",
        "customer@example.com",
        "+1 515-555-1212",
        "4111111111111111",
    ),
)
def test_opaque_identifier_boundary_rejects_content_secrets_and_paths(unsafe_id: str) -> None:
    plan = _plan()
    with pytest.raises(ReceiptValidationError):
        RoutingReceipt.from_execution_plan(
            plan,
            project_id=unsafe_id,
            topology_snapshot=build_topology(plan),
        )


def test_plan_derived_private_owner_is_rejected_instead_of_serialized() -> None:
    plan = resolve_execution_plan(
        "Update Jira CC-214 status.",
        AdaptivePolicy(mode=PolicyMode.GUARDED, default_tier=ModelTier.ECONOMY),
        owner_candidates=(
            OwnerCandidate("/Users/genome/private-workflow", OwnerKind.WORKFLOW),
        ),
    )

    with pytest.raises(ReceiptValidationError, match="filesystem path"):
        RoutingReceipt.from_execution_plan(
            plan,
            project_id="project",
            topology_snapshot=build_topology(plan),
        )


def test_unrecognized_agent_free_text_is_rejected() -> None:
    plan = _plan()
    snapshot = build_topology(plan)
    object.__setattr__(
        snapshot.contracts[0],
        "output_contract",
        "customer SSN 123-45-6789",
    )

    with pytest.raises(ReceiptValidationError, match="output_contract"):
        RoutingReceipt.from_execution_plan(
            plan,
            project_id="project",
            topology_snapshot=snapshot,
        )


@pytest.mark.parametrize(
    "unsafe_path",
    (
        "/Users/genome/private.log",
        r"C:\Users\genome\private.log",
        "../private.log",
        "artifacts/./private.log",
        "artifacts//private.log",
        "artifacts/123-45-6789.log",
        "artifacts/c2VjcmV0LWN1c3RvbWVyLXNlY3JldA.log",
    ),
)
def test_escalation_evidence_uses_dedicated_artifact_path_normalization(
    unsafe_path: str,
) -> None:
    plan, snapshot = _retry_snapshot()
    object.__setattr__(snapshot.escalation_events[0], "evidence_refs", (unsafe_path,))

    with pytest.raises(ReceiptValidationError, match="artifact path|customer-content|encoded"):
        RoutingReceipt.from_execution_plan(
            plan,
            project_id="project",
            topology_snapshot=snapshot,
        )


@pytest.mark.parametrize(
    "kwargs",
    (
        {"input_tokens": 1.5},
        {"output_tokens": True},
        {"cached_input_tokens": -1},
        {"total_tokens": -1},
        {"cost_cents": True},
        {"cost_cents": float("nan")},
        {"cost_cents": -0.01},
        {"latency_ms": 1.5},
        {"latency_ms": True},
        {"latency_ms": -1},
    ),
)
def test_provider_usage_numeric_rules_fail_closed(kwargs: dict[str, object]) -> None:
    with pytest.raises(ReceiptValidationError):
        ProviderUsage(**kwargs)  # type: ignore[arg-type]


def test_provider_usage_counts_are_exact_and_consistent() -> None:
    usage = ProviderUsage(
        provider="openai",
        input_tokens=10,
        output_tokens=5,
        cached_input_tokens=4,
        total_tokens=15,
        cost_cents=1.25,
        latency_ms=123,
    )
    assert usage.as_dict()["unknown_fields"] == []
    with pytest.raises(ReceiptValidationError, match="cached_input_tokens"):
        ProviderUsage(input_tokens=3, cached_input_tokens=4)
    with pytest.raises(ReceiptValidationError, match="exactly equal"):
        ProviderUsage(input_tokens=10, output_tokens=5, total_tokens=14)


def test_unknown_usage_and_overrides_are_explicit_and_never_calculated() -> None:
    usage = ProviderUsage(input_tokens=12, output_tokens=None, total_tokens=None)
    payload = usage.as_dict()
    overrides = OverrideIndicators().as_dict()

    assert payload["input_tokens"] == 12
    assert payload["total_tokens"] is None
    assert payload["cost_cents"] is None
    assert {"output_tokens", "total_tokens", "cost_cents", "latency_ms"}.issubset(
        payload["unknown_fields"]
    )
    assert overrides["applied"] is None
    assert "applied" in overrides["unknown_fields"]


def test_default_receipt_ids_are_unique_but_plan_fingerprint_is_stable() -> None:
    plan = _plan()
    snapshot = build_topology(plan)
    first = RoutingReceipt.from_execution_plan(
        plan, project_id="project", topology_snapshot=snapshot
    )
    second = RoutingReceipt.from_execution_plan(
        plan, project_id="project", topology_snapshot=snapshot
    )

    assert first.receipt_id != second.receipt_id
    assert first.as_dict()["plan_fingerprint"] == second.as_dict()["plan_fingerprint"]
    aggregate_routing_receipts((first, second))


def test_markdown_is_escaped_complete_and_lossless() -> None:
    plan, snapshot = _retry_snapshot()
    receipt = RoutingReceipt.from_execution_plan(
        plan,
        project_id="project",
        topology_snapshot=snapshot,
        override_indicators=OverrideIndicators(tier_requested=True, applied=True),
        provider_usage=ProviderUsage(provider="openai", input_tokens=12),
    )
    markdown = receipt.to_markdown()

    for heading in (
        "## Identity and schema versions",
        "## Routing decision",
        "## Topology",
        "## Escalation and overrides",
        "## Usage and outcome",
        "## Canonical JSON",
    ):
        assert heading in markdown
    assert "**unknown**" in markdown
    assert "artifacts/test.log" in markdown
    assert f"    {receipt.to_json()}" in markdown


def _cohort_receipts() -> tuple[RoutingReceipt, ...]:
    adaptive_plan = _plan()
    static_plan = resolve_execution_plan(
        "Update Jira CC-214 status.", AdaptivePolicy(mode=PolicyMode.OFF)
    )
    blocked_plan = resolve_execution_plan(
        "Deploy this change to production.",
        AdaptivePolicy(mode=PolicyMode.GUARDED, default_tier=ModelTier.ECONOMY),
    )
    human_plan = resolve_execution_plan(
        "Deploy this change to production.",
        AdaptivePolicy(mode=PolicyMode.OBSERVE, default_tier=ModelTier.ECONOMY),
    )
    return (
        RoutingReceipt.from_execution_plan(
            adaptive_plan,
            project_id="project",
            customer_id="customer-opaque-1",
            receipt_id="adaptive-1",
            topology_snapshot=build_topology(adaptive_plan),
            outcome=RoutingOutcome(
                status="success",
                first_route_correct=True,
                cost_assessment="appropriate",
                quality_score=0.9,
                rework_required=False,
                latency_ms=120,
            ),
        ),
        RoutingReceipt.from_execution_plan(
            static_plan,
            project_id="project",
            customer_id="customer-opaque-1",
            receipt_id="static-1",
            outcome=RoutingOutcome(
                status="partial",
                first_route_correct=False,
                cost_assessment="too_cheap",
                quality_score=0.5,
                rework_required=True,
                latency_ms=80,
            ),
            override_indicators=OverrideIndicators(tier_requested=True, applied=True),
        ),
        RoutingReceipt.from_execution_plan(
            blocked_plan,
            project_id="project",
            customer_id="customer-opaque-1",
            receipt_id="blocked-1",
        ),
        RoutingReceipt.from_execution_plan(
            human_plan,
            project_id="project",
            customer_id="customer-opaque-1",
            receipt_id="human-gate-1",
            outcome=RoutingOutcome(status="unknown", quality_score=0.8),
        ),
    )


def test_metrics_have_four_cohorts_denominators_and_per_cohort_quality() -> None:
    telemetry = aggregate_routing_receipts(_cohort_receipts()).as_dict()
    metrics = telemetry["metrics"]

    assert telemetry["schema_version"] == TELEMETRY_SCHEMA_VERSION
    assert telemetry["advisory_only"] is True
    assert telemetry["policy_mutation_permitted"] is False
    assert metrics["cohort_counts"] == {
        "static": 1,
        "adaptive": 1,
        "blocked": 1,
        "human_gate": 1,
    }
    assert metrics["first_route_accuracy"] == {
        "known_count": 2,
        "total_count": 4,
        "unknown_count": 2,
        "value": 0.5,
    }
    assert metrics["override_rate"] == {
        "known_count": 1,
        "total_count": 4,
        "unknown_count": 3,
        "value": 1.0,
    }
    assert metrics["quality_by_cohort"]["adaptive"]["value"] == 0.9
    assert metrics["quality_by_cohort"]["static"]["value"] == 0.5
    assert metrics["quality_by_cohort"]["human_gate"]["value"] == 0.8
    assert metrics["quality_by_cohort"]["blocked"] == {
        "known_count": 0,
        "total_count": 1,
        "unknown_count": 1,
        "value": None,
    }


def test_aggregate_requires_unique_receipts_and_one_project_customer_boundary() -> None:
    first, second, *_ = _cohort_receipts()
    duplicate = replace(second, receipt_id=first.receipt_id)
    with pytest.raises(ReceiptValidationError, match="unique receipt ids"):
        aggregate_routing_receipts((first, duplicate))

    other_project = replace(second, project_id="other-project")
    with pytest.raises(ReceiptValidationError, match="boundaries"):
        aggregate_routing_receipts((first, other_project))
    other_customer = replace(second, customer_id="customer-opaque-2")
    with pytest.raises(ReceiptValidationError, match="boundaries"):
        aggregate_routing_receipts((first, other_customer))


def test_retention_metadata_is_explicit_and_conservative_in_aggregate() -> None:
    plan = resolve_execution_plan("Update Jira CC-214 status.", AdaptivePolicy(mode=PolicyMode.OFF))
    short = RoutingReceipt.from_execution_plan(
        plan,
        project_id="project",
        receipt_id="retention-short",
        retention=RetentionMetadata(retention_days=7, aggregate_retention_days=30),
    )
    long = RoutingReceipt.from_execution_plan(
        plan,
        project_id="project",
        receipt_id="retention-long",
        retention=RetentionMetadata(retention_days=14, aggregate_retention_days=60),
    )

    retention = aggregate_routing_receipts((short, long)).as_dict()["retention"]
    assert retention == {
        "aggregate_retention_days": 30,
        "contains_customer_content": False,
        "retention_days": 7,
    }
    with pytest.raises(ReceiptValidationError, match="customer content"):
        RetentionMetadata(contains_customer_content=True)
