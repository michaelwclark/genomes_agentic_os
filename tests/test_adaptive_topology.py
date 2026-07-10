"""Snapshot coverage for bounded offline adaptive agent topologies."""

from __future__ import annotations

from dataclasses import replace

import pytest

from genomes_agentic_os.adaptive_policy import AdaptivePolicy, ModelTier, PolicyMode
from genomes_agentic_os.adaptive_router import (
    OwnerCandidate,
    OwnerKind,
    PlanOverrides,
    resolve_execution_plan,
)
from genomes_agentic_os.adaptive_topology import (
    AgentContract,
    AgentOutcome,
    AgentRole,
    AgentRunStatus,
    ArtifactWatcherContract,
    ConcurrencyCaps,
    EscalationAction,
    EscalationEvent,
    EscalationKind,
    TopologyKind,
    TopologySnapshot,
    TopologyStatus,
    apply_outcome,
    build_topology,
)


def _plan(task: str):
    return resolve_execution_plan(
        task,
        AdaptivePolicy(mode=PolicyMode.GUARDED, default_tier=ModelTier.ECONOMY),
    )


def _manual_snapshot(
    snapshot: TopologySnapshot, **overrides: object
) -> TopologySnapshot:
    """Reconstruct a snapshot without relying on the trusted builder."""
    fields: dict[str, object] = {
        "schema_version": snapshot.schema_version,
        "status": snapshot.status,
        "kind": snapshot.kind,
        "caps": snapshot.caps,
        "contracts": snapshot.contracts,
        "execution_waves": snapshot.execution_waves,
        "agent_states": snapshot.agent_states,
        "plan": snapshot.plan,
        "escalation_events": snapshot.escalation_events,
    }
    fields.update(overrides)
    return TopologySnapshot(**fields)  # type: ignore[arg-type]


def _ready_for_verifier() -> TopologySnapshot:
    topology = build_topology(_plan("Implement a bounded change in module.py."))
    topology = apply_outcome(topology, AgentOutcome("planner", True))
    return apply_outcome(topology, AgentOutcome("implementer", True))


def test_simple_economy_jira_plan_has_only_an_operator_snapshot() -> None:
    plan = _plan("Update Jira CC-213 status and add a label.")
    topology = build_topology(plan)

    assert topology.kind is TopologyKind.OPERATOR_ONLY
    assert topology.plan is plan
    assert topology.execution_plan is plan
    assert [contract.role for contract in topology.contracts] == [AgentRole.OPERATOR]
    assert topology.contracts[0].can_self_expand is False
    assert topology.as_dict()["plan"] == plan.as_dict()
    assert topology.to_json() == build_topology(
        _plan("Update Jira CC-213 status and add a label.")
    ).to_json()


@pytest.mark.parametrize(
    "overrides",
    [
        PlanOverrides(model_override="gpt-5.6-sol"),
        PlanOverrides(tier="frontier", model_override="gpt-5.6-sol"),
    ],
)
def test_simple_topology_is_not_deepened_by_a_stronger_model_override(
    overrides: PlanOverrides,
) -> None:
    policy = AdaptivePolicy(
        mode=PolicyMode.GUARDED,
        default_tier=ModelTier.ECONOMY,
        allow_model_overrides=True,
        allowed_model_overrides=frozenset({"gpt-5.6-sol"}),
    )
    plan = resolve_execution_plan(
        "Update Jira CC-213 status and add a label.",
        policy,
        overrides=overrides,
    )

    topology = build_topology(plan)

    assert plan.model_id == "gpt-5.6-sol"
    assert topology.kind is TopologyKind.OPERATOR_ONLY
    assert [contract.role for contract in topology.contracts] == [AgentRole.OPERATOR]


def test_frontier_work_uses_independent_verifier_and_parent_integration() -> None:
    topology = build_topology(
        _plan("Refactor the monolith across multiple modules and update its API.")
    )

    assert topology.kind is TopologyKind.DEEP_MULTI_LENS
    verifier = topology.contract("verifier")
    assert verifier.is_parent_integration_verifier is True
    assert verifier.depends_on == ("researcher", "implementer", "watcher")
    assert topology.contract("watcher").watcher_contract is not None
    assert topology.contract("watcher").watcher_contract.chat_polling_forbidden is True
    assert topology.contract("watcher").context_tools == ()
    assert all(
        set(contract.context_tools) <= set(topology.plan.required_tools)
        for contract in topology.contracts
    )
    assert sum(contract.token_budget for contract in topology.contracts) == 12_000
    assert sum(contract.context_budget or 0 for contract in topology.contracts) == 48_000


def test_snapshot_rejects_tools_outside_the_parent_plan_authority() -> None:
    plan = resolve_execution_plan(
        "Implement a bounded change in module.py.",
        AdaptivePolicy(mode=PolicyMode.GUARDED, default_tier=ModelTier.ECONOMY),
        owner_candidates=(
            OwnerCandidate(
                "bounded-workflow",
                OwnerKind.WORKFLOW,
                required_tools=("repository_read",),
            ),
        ),
    )
    topology = build_topology(plan)
    implementer = topology.contract("implementer")
    injected = replace(
        implementer,
        context_tools=("repository_read", "artifact_read"),
    )

    with pytest.raises(ValueError, match="required_tools"):
        _manual_snapshot(
            topology,
            contracts=tuple(
                injected if item.agent_id == "implementer" else item
                for item in topology.contracts
            ),
        )


def test_snapshot_rejects_context_and_aggregate_token_budget_overruns() -> None:
    topology = build_topology(_plan("Implement a bounded change in module.py."))
    implementer = topology.contract("implementer")

    excessive_context = replace(
        implementer,
        context_budget=(implementer.context_budget or 0) + 1,
    )
    with pytest.raises(ValueError, match="context allocations exceed plan input"):
        _manual_snapshot(
            topology,
            contracts=tuple(
                excessive_context if item.agent_id == "implementer" else item
                for item in topology.contracts
            ),
        )

    excessive_output = replace(
        implementer,
        token_budget=implementer.token_budget + 1,
    )
    with pytest.raises(ValueError, match="token allocations exceed plan output"):
        _manual_snapshot(
            topology,
            contracts=tuple(
                excessive_output if item.agent_id == "implementer" else item
                for item in topology.contracts
            ),
        )


@pytest.mark.parametrize("caps", [
    ConcurrencyCaps(global_max_concurrency=1, per_task_max_concurrency=8),
    ConcurrencyCaps(global_max_concurrency=8, per_task_max_concurrency=1),
])
def test_concurrency_caps_split_independent_deep_lenses_deterministically(caps: ConcurrencyCaps) -> None:
    topology = build_topology(
        _plan("Refactor the monolith across multiple modules and update its API."),
        caps=caps,
    )

    assert all(len(wave) <= 1 for wave in topology.execution_waves)
    assert topology.execution_waves == (("planner",), ("researcher",), ("implementer",), ("watcher",), ("verifier",))


def test_manually_constructed_snapshot_rejects_dependency_in_the_same_wave() -> None:
    topology = build_topology(_plan("Implement a bounded change in module.py."))

    with pytest.raises(ValueError, match="strictly earlier execution wave"):
        _manual_snapshot(
            topology,
            execution_waves=(("planner", "implementer"), ("verifier",)),
        )


def test_parent_integration_dependencies_are_complete_and_deterministic() -> None:
    topology = build_topology(_plan("Implement a bounded change in module.py."))
    verifier = replace(
        topology.contract("verifier"),
        depends_on=("planner", "implementer"),
    )

    with pytest.raises(ValueError, match="deterministically depend"):
        _manual_snapshot(
            topology,
            contracts=tuple(
                verifier if item.agent_id == "verifier" else item
                for item in topology.contracts
            ),
        )


def test_execution_failure_allows_exactly_one_evidence_backed_retry() -> None:
    topology = build_topology(_plan("Implement a bounded change in module.py."))
    assert topology.kind is TopologyKind.PLANNER_IMPLEMENTER_VERIFIER

    first = apply_outcome(topology, AgentOutcome("planner", True))
    retried = apply_outcome(
        first,
        AgentOutcome("implementer", False, evidence_refs=("artifacts/test.log",)),
    )
    terminal = apply_outcome(
        retried,
        AgentOutcome("implementer", False, evidence_refs=("artifacts/test-2.log",)),
    )

    assert first.state("planner").status is AgentRunStatus.SUCCEEDED
    assert retried.status is TopologyStatus.RETRY
    assert retried.state("implementer").retry_count == 1
    assert retried.escalation_events[-1].action is EscalationAction.RETRY
    assert terminal.status is TopologyStatus.REPLAN
    assert terminal.escalation_events[-1].kind is EscalationKind.EXECUTION_FAILURE
    assert terminal.escalation_events[-1].action is EscalationAction.REPLAN


def test_manually_constructed_snapshot_rejects_multiple_or_unevidenced_retries() -> None:
    topology = build_topology(_plan("Implement a bounded change in module.py."))
    duplicate_retry_states = tuple(
        replace(state, retry_count=1) if state.agent_id != "verifier" else state
        for state in topology.agent_states
    )
    with pytest.raises(ValueError, match="only one retry total"):
        _manual_snapshot(topology, agent_states=duplicate_retry_states)

    retry_states = tuple(
        replace(state, retry_count=1)
        if state.agent_id == "implementer"
        else state
        for state in topology.agent_states
    )
    retry_event = EscalationEvent(
        EscalationKind.EXECUTION_FAILURE,
        EscalationAction.RETRY,
        "implementer",
        (),
        "implementer",
    )
    with pytest.raises(ValueError, match="evidence-backed"):
        _manual_snapshot(
            topology,
            status=TopologyStatus.RETRY,
            agent_states=retry_states,
            escalation_events=(retry_event,),
        )

    wrong_target_states = tuple(
        replace(state, retry_count=1)
        if state.agent_id == "planner"
        else state
        for state in topology.agent_states
    )
    targeted_event = replace(
        retry_event,
        evidence_refs=("artifacts/test.log",),
    )
    with pytest.raises(ValueError, match="recorded retry target"):
        _manual_snapshot(
            topology,
            status=TopologyStatus.RETRY,
            agent_states=wrong_target_states,
            escalation_events=(targeted_event,),
        )


def test_partial_failure_preserves_success_and_capability_missing_blocks() -> None:
    topology = build_topology(_plan("Implement a bounded change in module.py."))
    topology = apply_outcome(topology, AgentOutcome("planner", True))
    result = apply_outcome(
        topology,
        AgentOutcome(
            "implementer",
            False,
            escalation=EscalationKind.CAPABILITY_MISSING,
            evidence_refs=("artifacts/capability.json",),
        ),
    )

    assert result.status is TopologyStatus.BLOCKED
    assert result.state("planner").status is AgentRunStatus.SUCCEEDED
    assert result.escalation_events[-1].kind is EscalationKind.CAPABILITY_MISSING


def test_verifier_rejection_retries_the_rejected_delegated_output_once() -> None:
    topology = _ready_for_verifier()
    rejection = apply_outcome(
        topology,
        AgentOutcome(
            "verifier",
            False,
            evidence_refs=("artifacts/review.md",),
            rejected_agent_id="implementer",
        ),
    )

    assert rejection.status is TopologyStatus.RETRY
    assert rejection.state("implementer").retry_count == 1
    assert rejection.state("verifier").status is AgentRunStatus.PENDING
    assert rejection.escalation_events[-1].kind is EscalationKind.VERIFIER_REJECTION
    assert rejection.escalation_events[-1].retry_target == "implementer"
    assert rejection.escalation_events[-1].rejected_agent_id == "implementer"


@pytest.mark.parametrize("rejected_agent_id", [None, "planner", "unknown-agent"])
def test_verifier_rejection_without_a_valid_explicit_dependency_replans(
    rejected_agent_id: str | None,
) -> None:
    result = apply_outcome(
        _ready_for_verifier(),
        AgentOutcome(
            "verifier",
            False,
            evidence_refs=("artifacts/review.md",),
            rejected_agent_id=rejected_agent_id,
        ),
    )

    assert result.status is TopologyStatus.REPLAN
    assert result.escalation_events[-1].action is EscalationAction.REPLAN
    assert result.escalation_events[-1].retry_target is None


def test_verifier_retry_resets_dependent_watcher_before_parent_integration() -> None:
    topology = build_topology(
        _plan("Refactor the monolith across multiple modules and update its API.")
    )
    for agent_id in ("planner", "researcher", "implementer", "watcher"):
        topology = apply_outcome(topology, AgentOutcome(agent_id, True))

    rejection = apply_outcome(
        topology,
        AgentOutcome(
            "verifier",
            False,
            evidence_refs=("artifacts/review.md",),
            rejected_agent_id="implementer",
        ),
    )

    assert rejection.state("implementer").status is AgentRunStatus.PENDING
    assert rejection.state("watcher").status is AgentRunStatus.PENDING
    assert rejection.state("verifier").status is AgentRunStatus.PENDING


def test_scope_and_budget_escalations_never_expand_the_existing_authority() -> None:
    topology = build_topology(_plan("Update a general task."), kind=TopologyKind.WORKER_VERIFIER)
    scope = apply_outcome(
        topology,
        AgentOutcome("worker", False, escalation=EscalationKind.DISCOVERED_SCOPE),
    )
    budget = apply_outcome(
        topology,
        AgentOutcome("worker", False, escalation=EscalationKind.BUDGET_INSUFFICIENT),
    )

    assert scope.status is TopologyStatus.REPLAN
    assert budget.status is TopologyStatus.BLOCKED
    assert scope.contract("worker").authoritative_model_id == topology.contract("worker").authoritative_model_id


def test_explicit_kind_cannot_undersize_assessment_derived_topology() -> None:
    plan = _plan("Refactor the monolith across multiple modules and update its API.")

    with pytest.raises(ValueError, match="cannot override"):
        build_topology(plan, kind=TopologyKind.OPERATOR_ONLY)

    snapshot = build_topology(plan)
    with pytest.raises(ValueError, match="assessment-derived"):
        replace(snapshot, kind=TopologyKind.OPERATOR_ONLY)


def test_authority_monotonicity_rejects_model_tier_or_effort_drift() -> None:
    topology = build_topology(_plan("Implement a bounded change in module.py."))
    worker = topology.contract("implementer")
    drifted = replace(
        worker,
        authoritative_model_id="gpt-5.6-sol",
        authoritative_model_tier=ModelTier.FRONTIER,
    )
    with pytest.raises(ValueError, match="authority monotonicity"):
        replace(
            topology,
            contracts=tuple(
                drifted if item.agent_id == "implementer" else item
                for item in topology.contracts
            ),
        )


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../state.json",
        "watcher/../state.json",
        "watcher\\state.json",
        "/tmp/state.json",
        "C:/tmp/state.json",
        "C:\\tmp\\state.json",
        "//server/share/state.json",
    ],
)
def test_watcher_artifacts_reject_traversal_and_cross_platform_absolute_paths(
    unsafe_path: str,
) -> None:
    with pytest.raises(ValueError, match="relative|normalized|POSIX"):
        ArtifactWatcherContract(
            unsafe_path,
            "watcher/events.jsonl",
            "watcher/summary.md",
        )


def test_watcher_artifacts_must_be_three_distinct_relative_paths() -> None:
    with pytest.raises(ValueError, match="three distinct"):
        ArtifactWatcherContract(
            "watcher/state.json",
            "watcher/state.json",
            "watcher/summary.md",
        )


def test_agent_contract_rejects_self_expansion_and_watcher_without_artifacts() -> None:
    with pytest.raises(ValueError, match="self-expansion"):
        AgentContract(
            "worker", AgentRole.WORKER, "gpt-5.6-luna", "economy", "medium",
            ("bounded_execution",), ("workspace_read",), 10, "result", can_self_expand=True,
        )
    with pytest.raises(ValueError, match="watcher role requires"):
        AgentContract(
            "watcher", AgentRole.WATCHER, "gpt-5.6-luna", "economy", "medium",
            ("artifact_backed_watcher",), ("artifact_read",), 10, "result",
        )
