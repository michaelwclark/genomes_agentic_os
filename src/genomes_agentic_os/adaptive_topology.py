"""Offline, bounded agent topology and escalation planning.

This module is intentionally a controller *specification*, not an agent
runtime.  It consumes the redacted :class:`ExecutionPlan` produced by
``adaptive_router`` and returns immutable contracts, scheduling waves, and
state transitions.  In particular, it never starts agents, waits for CI, or
polls chat.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import json
from pathlib import PurePosixPath, PureWindowsPath
from .adaptive_policy import (
    AUTHORITATIVE_MODEL_CAPABILITY_TIERS,
    CAPABILITY_RANK,
    EFFORT_ORDER,
    TIER_CAPABILITY_FLOOR,
    TIER_ORDER,
    ModelTier,
    ReasoningEffort,
)
from .adaptive_router import ExecutionPlan, PlanStatus


TOPOLOGY_SCHEMA_VERSION = 1


class TopologyKind(str, Enum):
    OPERATOR_ONLY = "operator_only"
    WORKER_VERIFIER = "worker_verifier"
    PLANNER_IMPLEMENTER_VERIFIER = "planner_implementer_verifier"
    DEEP_MULTI_LENS = "deep_multi_lens"


class AgentRole(str, Enum):
    OPERATOR = "operator"
    WORKER = "worker"
    PLANNER = "planner"
    IMPLEMENTER = "implementer"
    RESEARCHER = "researcher"
    VERIFIER = "verifier"
    WATCHER = "watcher"


class AgentRunStatus(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class TopologyStatus(str, Enum):
    READY = "ready"
    RETRY = "retry"
    REPLAN = "replan"
    BLOCKED = "blocked"
    COMPLETED = "completed"


class EscalationKind(str, Enum):
    DISCOVERED_SCOPE = "discovered_scope"
    EXECUTION_FAILURE = "execution_failure"
    CAPABILITY_MISSING = "capability_missing"
    VERIFIER_REJECTION = "verifier_rejection"
    BUDGET_INSUFFICIENT = "budget_insufficient"


class EscalationAction(str, Enum):
    RETRY = "retry"
    REPLAN = "replan"
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class ConcurrencyCaps:
    """Reviewed capacity bounds; runtime capacity is never inferred here."""

    global_max_concurrency: int = 4
    per_task_max_concurrency: int = 3

    def __post_init__(self) -> None:
        for name in ("global_max_concurrency", "per_task_max_concurrency"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")

    @property
    def effective_max_concurrency(self) -> int:
        return min(self.global_max_concurrency, self.per_task_max_concurrency)


@dataclass(frozen=True, slots=True)
class ArtifactWatcherContract:
    """The sole allowed long-wait interface: durable artifacts, never chat."""

    state_artifact: str
    events_artifact: str
    summary_artifact: str
    chat_polling_forbidden: bool = True

    def __post_init__(self) -> None:
        artifacts = tuple(
            getattr(self, name)
            for name in ("state_artifact", "events_artifact", "summary_artifact")
        )
        for name, value in zip(
            ("state_artifact", "events_artifact", "summary_artifact"), artifacts
        ):
            _validate_relative_artifact_path(name, value)
        if len(set(artifacts)) != 3:
            raise ValueError("watcher artifacts must be three distinct relative paths")
        if self.chat_polling_forbidden is not True:
            raise ValueError("artifact watcher contracts must forbid chat polling")

    def as_dict(self) -> dict[str, object]:
        return {
            "state_artifact": self.state_artifact,
            "events_artifact": self.events_artifact,
            "summary_artifact": self.summary_artifact,
            "chat_polling_forbidden": self.chat_polling_forbidden,
        }


@dataclass(frozen=True, slots=True)
class AgentContract:
    """A bounded, non-self-expanding contract for one declared role."""

    agent_id: str
    role: AgentRole | str
    authoritative_model_id: str
    authoritative_model_tier: ModelTier | str
    authoritative_reasoning_effort: ReasoningEffort | str
    skills: tuple[str, ...]
    context_tools: tuple[str, ...]
    token_budget: int
    output_contract: str
    depends_on: tuple[str, ...] = ()
    is_parent_integration_verifier: bool = False
    can_self_expand: bool = False
    watcher_contract: ArtifactWatcherContract | None = None
    context_budget: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.agent_id, str) or not self.agent_id:
            raise ValueError("agent_id must be a non-empty string")
        object.__setattr__(self, "role", AgentRole(self.role))
        if (
            not isinstance(self.authoritative_model_id, str)
            or self.authoritative_model_id not in AUTHORITATIVE_MODEL_CAPABILITY_TIERS
        ):
            raise ValueError("authoritative_model_id must be an authoritative GPT-5.6 model")
        object.__setattr__(self, "authoritative_model_tier", ModelTier(self.authoritative_model_tier))
        object.__setattr__(
            self,
            "authoritative_reasoning_effort",
            ReasoningEffort(self.authoritative_reasoning_effort),
        )
        if CAPABILITY_RANK[
            AUTHORITATIVE_MODEL_CAPABILITY_TIERS[self.authoritative_model_id]
        ] < CAPABILITY_RANK[TIER_CAPABILITY_FLOOR[self.authoritative_model_tier]]:
            raise ValueError("authoritative model does not satisfy its declared tier")
        for name in ("skills", "context_tools", "depends_on"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(
                not isinstance(item, str) or not item for item in values
            ):
                raise ValueError(f"{name} must be a tuple of non-empty strings")
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must not contain duplicates")
        if type(self.token_budget) is not int or self.token_budget < 1:
            raise ValueError("token_budget must be a positive integer")
        if self.context_budget is None:
            object.__setattr__(self, "context_budget", self.token_budget)
        if type(self.context_budget) is not int or self.context_budget < 1:
            raise ValueError("context_budget must be a positive integer")
        if not isinstance(self.output_contract, str) or not self.output_contract:
            raise ValueError("output_contract must be a non-empty string")
        if self.can_self_expand is not False:
            raise ValueError("agent contracts must forbid self-expansion")
        if self.role is AgentRole.WATCHER:
            if self.watcher_contract is None:
                raise ValueError("watcher role requires an artifact watcher contract")
        elif self.watcher_contract is not None:
            raise ValueError("only watcher roles may carry an artifact watcher contract")

    def as_dict(self) -> dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "role": self.role.value,
            "authoritative_model_id": self.authoritative_model_id,
            "authoritative_model_tier": self.authoritative_model_tier.value,
            "authoritative_reasoning_effort": self.authoritative_reasoning_effort.value,
            "skills": list(self.skills),
            "context_tools": list(self.context_tools),
            "context_budget": self.context_budget,
            "token_budget": self.token_budget,
            "output_contract": self.output_contract,
            "depends_on": list(self.depends_on),
            "is_parent_integration_verifier": self.is_parent_integration_verifier,
            "can_self_expand": self.can_self_expand,
            "watcher_contract": (
                None if self.watcher_contract is None else self.watcher_contract.as_dict()
            ),
        }

    @property
    def context_token_budget(self) -> int:
        """Compatibility alias that makes the allocation unit explicit."""
        assert self.context_budget is not None
        return self.context_budget


@dataclass(frozen=True, slots=True)
class AgentState:
    agent_id: str
    status: AgentRunStatus = AgentRunStatus.PENDING
    retry_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.agent_id, str) or not self.agent_id:
            raise ValueError("agent state requires a non-empty agent_id")
        object.__setattr__(self, "status", AgentRunStatus(self.status))
        if type(self.retry_count) is not int or self.retry_count < 0:
            raise ValueError("retry_count must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class EscalationEvent:
    kind: EscalationKind | str
    action: EscalationAction | str
    agent_id: str
    evidence_refs: tuple[str, ...]
    retry_target: str | None = None
    rejected_agent_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", EscalationKind(self.kind))
        object.__setattr__(self, "action", EscalationAction(self.action))
        if not isinstance(self.agent_id, str) or not self.agent_id:
            raise ValueError("escalation event requires agent_id")
        if not isinstance(self.evidence_refs, tuple) or any(
            not isinstance(item, str) or not item for item in self.evidence_refs
        ):
            raise ValueError("evidence_refs must be a tuple of non-empty strings")
        if self.retry_target is not None and (
            not isinstance(self.retry_target, str) or not self.retry_target
        ):
            raise ValueError("retry_target must be a non-empty string or null")
        if self.rejected_agent_id is not None and (
            not isinstance(self.rejected_agent_id, str) or not self.rejected_agent_id
        ):
            raise ValueError("rejected_agent_id must be a non-empty string or null")

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "action": self.action.value,
            "agent_id": self.agent_id,
            "evidence_refs": list(self.evidence_refs),
            "retry_target": self.retry_target,
            "rejected_agent_id": self.rejected_agent_id,
        }


@dataclass(frozen=True, slots=True)
class AgentOutcome:
    """A runtime receipt that may be applied by a future runtime adapter."""

    agent_id: str
    succeeded: bool
    escalation: EscalationKind | str | None = None
    evidence_refs: tuple[str, ...] = ()
    rejected_agent_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.agent_id, str) or not self.agent_id:
            raise ValueError("outcome requires agent_id")
        if type(self.succeeded) is not bool:
            raise ValueError("outcome succeeded must be a bool")
        if self.escalation is not None:
            object.__setattr__(self, "escalation", EscalationKind(self.escalation))
        if not isinstance(self.evidence_refs, tuple) or any(
            not isinstance(item, str) or not item for item in self.evidence_refs
        ):
            raise ValueError("evidence_refs must be a tuple of non-empty strings")
        if self.rejected_agent_id is not None and (
            not isinstance(self.rejected_agent_id, str) or not self.rejected_agent_id
        ):
            raise ValueError("rejected_agent_id must be a non-empty string or null")
        if self.succeeded and self.rejected_agent_id is not None:
            raise ValueError("successful outcomes cannot reject an agent")
        if (
            self.escalation is not None
            and self.escalation is not EscalationKind.VERIFIER_REJECTION
            and self.rejected_agent_id is not None
        ):
            raise ValueError("rejected_agent_id is only valid for verifier rejection")


@dataclass(frozen=True, slots=True)
class TopologySnapshot:
    """Immutable topology plus controller state; safe for receipt storage."""

    schema_version: int
    status: TopologyStatus | str
    kind: TopologyKind | str
    caps: ConcurrencyCaps
    contracts: tuple[AgentContract, ...]
    execution_waves: tuple[tuple[str, ...], ...]
    agent_states: tuple[AgentState, ...]
    plan: ExecutionPlan
    escalation_events: tuple[EscalationEvent, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", TopologyStatus(self.status))
        object.__setattr__(self, "kind", TopologyKind(self.kind))
        if self.schema_version != TOPOLOGY_SCHEMA_VERSION:
            raise ValueError("unsupported topology schema version")
        if not isinstance(self.caps, ConcurrencyCaps):
            raise ValueError("caps must be ConcurrencyCaps")
        if not isinstance(self.plan, ExecutionPlan):
            raise ValueError("plan must be the authoritative ExecutionPlan")
        if self.kind is not select_topology(self.plan):
            raise ValueError(
                "topology kind must match the assessment-derived topology"
            )
        ids = tuple(contract.agent_id for contract in self.contracts)
        if len(ids) != len(set(ids)):
            raise ValueError("agent contracts must have unique ids")
        states = tuple(state.agent_id for state in self.agent_states)
        if states != ids:
            raise ValueError("agent states must be in contract order and cover every contract")
        _validate_execution_waves(self, ids)
        known = set(ids)
        if any(event.agent_id not in known for event in self.escalation_events):
            raise ValueError("escalation event references unknown agent")
        if any(
            event.retry_target is not None and event.retry_target not in known
            for event in self.escalation_events
        ):
            raise ValueError("escalation retry target references unknown agent")
        validate_authority_monotonicity(self)
        _validate_budget_allocations(self)
        _validate_parent_integration(self)
        _validate_watcher_requirements(self)
        _validate_retry_history(self)

    def contract(self, agent_id: str) -> AgentContract:
        for contract in self.contracts:
            if contract.agent_id == agent_id:
                return contract
        raise ValueError(f"unknown agent_id: {agent_id}")

    def state(self, agent_id: str) -> AgentState:
        for state in self.agent_states:
            if state.agent_id == agent_id:
                return state
        raise ValueError(f"unknown agent_id: {agent_id}")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "kind": self.kind.value,
            "plan": self.plan.as_dict(),
            "caps": {
                "global_max_concurrency": self.caps.global_max_concurrency,
                "per_task_max_concurrency": self.caps.per_task_max_concurrency,
                "effective_max_concurrency": self.caps.effective_max_concurrency,
            },
            "contracts": [contract.as_dict() for contract in self.contracts],
            "execution_waves": [list(wave) for wave in self.execution_waves],
            "agent_states": [
                {
                    "agent_id": state.agent_id,
                    "status": state.status.value,
                    "retry_count": state.retry_count,
                }
                for state in self.agent_states
            ],
            "escalation_events": [event.as_dict() for event in self.escalation_events],
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))

    @property
    def execution_plan(self) -> ExecutionPlan:
        """Expose the immutable parent authority under an explicit alias."""
        return self.plan


def select_topology(plan: ExecutionPlan) -> TopologyKind:
    """Choose the smallest reviewed topology that meets derived plan signals."""
    assessment = plan.assessment
    verification = set(assessment.verification_needs) | set(plan.required_verification)
    if (
        assessment.task_family == "simple_jira_grunt_work"
        and assessment.code_scope == "none"
        and assessment.context_depth == "shallow"
        and assessment.uncertainty == "low"
        and verification <= {"tracker_readback"}
    ):
        return TopologyKind.OPERATOR_ONLY
    if (
        assessment.code_scope == "cross_module"
        or assessment.context_depth == "deep"
        or verification.intersection(
            {
                "change_review",
                "data_impact_review",
                "deployment_plan",
                "integration_tests",
                "migration_plan",
                "rollback_plan",
                "security_review",
            }
        )
    ):
        return TopologyKind.DEEP_MULTI_LENS
    if assessment.code_scope != "none" or assessment.uncertainty == "high":
        return TopologyKind.PLANNER_IMPLEMENTER_VERIFIER
    return TopologyKind.WORKER_VERIFIER


def build_topology(
    plan: ExecutionPlan,
    *,
    caps: ConcurrencyCaps = ConcurrencyCaps(),
    kind: TopologyKind | str | None = None,
) -> TopologySnapshot:
    """Build an offline topology from a ready plan without spawning anything."""
    if not isinstance(plan, ExecutionPlan):
        raise ValueError("plan must be an ExecutionPlan")
    if not isinstance(caps, ConcurrencyCaps):
        raise ValueError("caps must be ConcurrencyCaps")
    required_kind = select_topology(plan)
    selected_kind = required_kind if kind is None else TopologyKind(kind)
    if selected_kind is not required_kind:
        raise ValueError(
            "explicit topology kind cannot override the assessment-derived topology"
        )
    if plan.status is not PlanStatus.READY:
        return TopologySnapshot(
            schema_version=TOPOLOGY_SCHEMA_VERSION,
            status=TopologyStatus.BLOCKED,
            kind=selected_kind,
            caps=caps,
            contracts=(),
            execution_waves=(),
            agent_states=(),
            plan=plan,
        )
    if not plan.model_id or plan.reasoning_effort is None:
        raise ValueError("ready plan must contain an authoritative model and reasoning effort")

    roles = _roles_for(selected_kind, plan.assessment.expected_duration == "long")
    context_allocations = _allocate_tokens(plan.budgets.input_tokens, roles)
    token_allocations = _allocate_tokens(plan.budgets.output_tokens, roles)
    contracts = tuple(
        _contract_for(
            role,
            plan,
            context_allocations[role],
            token_allocations[role],
            _dependencies(role, roles),
        )
        for role in roles
    )
    waves = _waves(tuple(contract.agent_id for contract in contracts), contracts, caps)
    return TopologySnapshot(
        schema_version=TOPOLOGY_SCHEMA_VERSION,
        status=TopologyStatus.READY,
        kind=selected_kind,
        caps=caps,
        contracts=contracts,
        execution_waves=waves,
        agent_states=tuple(AgentState(contract.agent_id) for contract in contracts),
        plan=plan,
    )


def apply_outcome(snapshot: TopologySnapshot, outcome: AgentOutcome) -> TopologySnapshot:
    """Apply one evidence receipt using the bounded retry/escalation policy.

    A retry is allowed at most once for the topology and only when the
    failure/rejection provides evidence artifacts.  Scope, capability, and
    budget changes do not retry under the old plan because that could silently
    expand authority or budget.
    """
    if not isinstance(snapshot, TopologySnapshot) or not isinstance(outcome, AgentOutcome):
        raise ValueError("snapshot and outcome must use topology controller types")
    if snapshot.status not in {TopologyStatus.READY, TopologyStatus.RETRY}:
        raise ValueError("outcomes can only be applied to ready or retry topologies")
    contract = snapshot.contract(outcome.agent_id)
    current = snapshot.state(outcome.agent_id)
    if current.status is not AgentRunStatus.PENDING:
        raise ValueError("outcome agent is not pending")
    if any(
        snapshot.state(parent).status is not AgentRunStatus.SUCCEEDED
        for parent in contract.depends_on
    ):
        raise ValueError("outcome dependencies have not succeeded")

    if outcome.succeeded:
        states = _replace_state(snapshot.agent_states, replace(current, status=AgentRunStatus.SUCCEEDED))
        status = TopologyStatus.COMPLETED if all(
            state.status is AgentRunStatus.SUCCEEDED for state in states
        ) else TopologyStatus.READY
        return replace(snapshot, status=status, agent_states=states)

    kind = outcome.escalation or (
        EscalationKind.VERIFIER_REJECTION
        if contract.role is AgentRole.VERIFIER
        else EscalationKind.EXECUTION_FAILURE
    )
    target = _retry_target(contract, kind, outcome.rejected_agent_id)
    retry_allowed = (
        kind in {EscalationKind.EXECUTION_FAILURE, EscalationKind.VERIFIER_REJECTION}
        and bool(outcome.evidence_refs)
        and sum(state.retry_count for state in snapshot.agent_states) < 1
        and target is not None
    )
    if retry_allowed:
        assert target is not None
        event = EscalationEvent(
            kind,
            EscalationAction.RETRY,
            outcome.agent_id,
            outcome.evidence_refs,
            target,
            outcome.rejected_agent_id,
        )
        states = _states_for_retry(snapshot, outcome.agent_id, target)
        return replace(
            snapshot,
            status=TopologyStatus.RETRY,
            agent_states=states,
            escalation_events=snapshot.escalation_events + (event,),
        )

    action = _terminal_action(kind)
    event = EscalationEvent(
        kind,
        action,
        outcome.agent_id,
        outcome.evidence_refs,
        rejected_agent_id=outcome.rejected_agent_id,
    )
    states = _replace_state(snapshot.agent_states, replace(current, status=AgentRunStatus.FAILED))
    return replace(
        snapshot,
        status=TopologyStatus.REPLAN if action is EscalationAction.REPLAN else TopologyStatus.BLOCKED,
        agent_states=states,
        escalation_events=snapshot.escalation_events + (event,),
    )


def validate_authority_monotonicity(snapshot: TopologySnapshot) -> None:
    """Reject any role that weakens or upgrades the parent plan authority."""
    if not snapshot.contracts:
        return
    plan = snapshot.plan
    if plan.status is not PlanStatus.READY or not plan.model_id or plan.reasoning_effort is None:
        raise ValueError("topology contracts require a ready authoritative plan")
    allowed_tools = set(plan.required_tools)
    for contract in snapshot.contracts:
        if contract.authoritative_model_id != plan.model_id:
            raise ValueError("topology role model violates authority monotonicity")
        if TIER_ORDER[contract.authoritative_model_tier] != TIER_ORDER[plan.model_tier]:
            raise ValueError("topology role model tier violates authority monotonicity")
        if EFFORT_ORDER[contract.authoritative_reasoning_effort] != EFFORT_ORDER[plan.reasoning_effort]:
            raise ValueError("topology role reasoning violates authority monotonicity")
        if not set(contract.context_tools).issubset(allowed_tools):
            raise ValueError("topology role tools exceed authoritative plan required_tools")


def _roles_for(kind: TopologyKind, long_wait: bool) -> tuple[AgentRole, ...]:
    base = {
        TopologyKind.OPERATOR_ONLY: (AgentRole.OPERATOR,),
        TopologyKind.WORKER_VERIFIER: (AgentRole.WORKER, AgentRole.VERIFIER),
        TopologyKind.PLANNER_IMPLEMENTER_VERIFIER: (
            AgentRole.PLANNER,
            AgentRole.IMPLEMENTER,
            AgentRole.VERIFIER,
        ),
        TopologyKind.DEEP_MULTI_LENS: (
            AgentRole.PLANNER,
            AgentRole.RESEARCHER,
            AgentRole.IMPLEMENTER,
            AgentRole.VERIFIER,
        ),
    }[kind]
    if long_wait and AgentRole.VERIFIER in base:
        # The verifier must integrate the watcher's durable receipt, so the
        # watcher is a declared predecessor rather than an afterthought.
        return base[:-1] + (AgentRole.WATCHER, AgentRole.VERIFIER)
    return base


def _dependencies(role: AgentRole, roles: tuple[AgentRole, ...]) -> tuple[str, ...]:
    if role is AgentRole.OPERATOR or role is AgentRole.PLANNER:
        return ()
    if role in {AgentRole.WORKER, AgentRole.RESEARCHER}:
        return ("planner",) if AgentRole.PLANNER in roles else ()
    if role is AgentRole.IMPLEMENTER:
        return ("planner",)
    if role is AgentRole.WATCHER:
        return ("implementer",) if AgentRole.IMPLEMENTER in roles else ("worker",)
    if role is AgentRole.VERIFIER:
        parents = [
            candidate.value
            for candidate in (AgentRole.WORKER, AgentRole.RESEARCHER, AgentRole.IMPLEMENTER)
            if candidate in roles
        ]
        if AgentRole.WATCHER in roles:
            parents.append("watcher")
        return tuple(parents)
    raise AssertionError(f"unhandled role: {role}")


def _allocate_tokens(total: int, roles: tuple[AgentRole, ...]) -> dict[AgentRole, int]:
    if total < len(roles):
        raise ValueError("plan token budget cannot allocate one token to every role")
    weights = {
        AgentRole.OPERATOR: 1,
        AgentRole.WORKER: 2,
        AgentRole.PLANNER: 2,
        AgentRole.IMPLEMENTER: 3,
        AgentRole.RESEARCHER: 2,
        AgentRole.VERIFIER: 2,
        AgentRole.WATCHER: 1,
    }
    denominator = sum(weights[role] for role in roles)
    allocations = {role: max(1, total * weights[role] // denominator) for role in roles}
    remainder = total - sum(allocations.values())
    index = 0
    while remainder > 0:
        allocations[roles[index % len(roles)]] += 1
        remainder -= 1
        index += 1
    return allocations


def _contract_for(
    role: AgentRole,
    plan: ExecutionPlan,
    context_budget: int,
    token_budget: int,
    depends_on: tuple[str, ...],
) -> AgentContract:
    skills, tools, output = _role_contract(role, plan)
    watcher = (
        ArtifactWatcherContract(
            "watcher/state.json", "watcher/events.jsonl", "watcher/summary.md"
        )
        if role is AgentRole.WATCHER
        else None
    )
    return AgentContract(
        role.value,
        role,
        plan.model_id or "",
        plan.model_tier,
        plan.reasoning_effort or ReasoningEffort.LOW,
        skills,
        tools,
        token_budget,
        output,
        depends_on,
        role is AgentRole.VERIFIER and bool(depends_on),
        False,
        watcher,
        context_budget,
    )


def _role_contract(
    role: AgentRole, plan: ExecutionPlan
) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    plan_tools = plan.required_tools
    if role is AgentRole.OPERATOR:
        return ("task_execution",), plan_tools, "bounded outcome with required readback evidence"
    if role is AgentRole.WORKER:
        return ("bounded_execution",), plan_tools, "delegated result and evidence artifacts"
    if role is AgentRole.PLANNER:
        return (
            ("implementation_planning",),
            plan_tools,
            "bounded implementation plan and acceptance checks",
        )
    if role is AgentRole.IMPLEMENTER:
        return ("implementation",), plan_tools, "bounded implementation result and test artifacts"
    if role is AgentRole.RESEARCHER:
        return ("independent_analysis",), plan_tools, "independent risk and scope evidence"
    if role is AgentRole.VERIFIER:
        return ("integration_verification",), plan_tools, "parent integration verdict over every delegated output"
    if role is AgentRole.WATCHER:
        return (
            ("artifact_backed_watcher",),
            (),
            "watcher state, events, and summary artifacts; no chat polling",
        )
    raise AssertionError(f"unhandled role: {role}")


def _waves(
    ids: tuple[str, ...], contracts: tuple[AgentContract, ...], caps: ConcurrencyCaps
) -> tuple[tuple[str, ...], ...]:
    # Contracts are already topologically sorted.  A role can share a wave only
    # with an earlier-ready sibling; cap slicing preserves deterministic order.
    waves: list[tuple[str, ...]] = []
    current: list[str] = []
    completed: set[str] = set()
    for contract in contracts:
        ready_with_current = all(dep in completed for dep in contract.depends_on)
        if not ready_with_current or len(current) >= caps.effective_max_concurrency:
            if current:
                waves.append(tuple(current))
                completed.update(current)
            current = []
        current.append(contract.agent_id)
    if current:
        waves.append(tuple(current))
    if tuple(agent for wave in waves for agent in wave) != ids:
        raise AssertionError("wave builder lost a contract")
    return tuple(waves)


def _replace_state(states: tuple[AgentState, ...], replacement: AgentState) -> tuple[AgentState, ...]:
    return tuple(replacement if state.agent_id == replacement.agent_id else state for state in states)


def _retry_target(
    contract: AgentContract,
    kind: EscalationKind,
    rejected_agent_id: str | None,
) -> str | None:
    if kind is EscalationKind.VERIFIER_REJECTION:
        if (
            contract.role is AgentRole.VERIFIER
            and contract.is_parent_integration_verifier
            and rejected_agent_id in contract.depends_on
        ):
            return rejected_agent_id
        return None
    return contract.agent_id


def _states_for_retry(
    snapshot: TopologySnapshot,
    outcome_agent_id: str,
    target_agent_id: str,
) -> tuple[AgentState, ...]:
    """Reset the rejected output and its downstream integration chain."""
    target_state = snapshot.state(target_agent_id)
    states = _replace_state(
        snapshot.agent_states,
        replace(
            target_state,
            status=AgentRunStatus.PENDING,
            retry_count=target_state.retry_count + 1,
        ),
    )
    if target_agent_id == outcome_agent_id:
        return states

    affected = {target_agent_id}
    for contract in snapshot.contracts:
        if any(parent in affected for parent in contract.depends_on):
            affected.add(contract.agent_id)
    for agent_id in affected - {target_agent_id}:
        state = snapshot.state(agent_id)
        states = _replace_state(states, replace(state, status=AgentRunStatus.PENDING))
    return states


def _terminal_action(kind: EscalationKind) -> EscalationAction:
    if kind in {EscalationKind.DISCOVERED_SCOPE, EscalationKind.EXECUTION_FAILURE, EscalationKind.VERIFIER_REJECTION}:
        return EscalationAction.REPLAN
    return EscalationAction.BLOCK


def _validate_relative_artifact_path(name: str, value: object) -> None:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError(f"{name} must be a non-empty relative artifact path")
    if "\\" in value:
        raise ValueError(f"{name} must use a relative POSIX artifact path")
    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or any(part in {".", ".."} for part in posix_path.parts)
        or not posix_path.parts
        or posix_path.as_posix() != value
    ):
        raise ValueError(f"{name} must be a normalized relative artifact path")


def _validate_execution_waves(
    snapshot: TopologySnapshot, ids: tuple[str, ...]
) -> None:
    if any(not wave for wave in snapshot.execution_waves):
        raise ValueError("execution waves must not be empty")
    if any(
        len(wave) > snapshot.caps.effective_max_concurrency
        for wave in snapshot.execution_waves
    ):
        raise ValueError("execution waves exceed effective concurrency cap")
    if tuple(agent for wave in snapshot.execution_waves for agent in wave) != ids:
        raise ValueError("execution waves must cover contracts exactly once in contract order")

    contract_index = {agent_id: index for index, agent_id in enumerate(ids)}
    wave_index = {
        agent_id: index
        for index, wave in enumerate(snapshot.execution_waves)
        for agent_id in wave
    }
    for contract in snapshot.contracts:
        for parent in contract.depends_on:
            if parent not in contract_index or contract_index[parent] >= contract_index[contract.agent_id]:
                raise ValueError("contract dependencies must refer to earlier contracts")
            if wave_index[parent] >= wave_index[contract.agent_id]:
                raise ValueError(
                    "contract dependencies must run in a strictly earlier execution wave"
                )


def _validate_budget_allocations(snapshot: TopologySnapshot) -> None:
    if not snapshot.contracts:
        return
    total_context = sum(contract.context_budget or 0 for contract in snapshot.contracts)
    total_output = sum(contract.token_budget for contract in snapshot.contracts)
    budgets = snapshot.plan.budgets
    if total_context > budgets.input_tokens:
        raise ValueError("aggregate agent context allocations exceed plan input budget")
    if total_output > budgets.output_tokens:
        raise ValueError("aggregate agent token allocations exceed plan output budget")
    if total_context + total_output > budgets.context_tokens:
        raise ValueError("aggregate agent context and token allocations exceed plan context budget")


def _validate_parent_integration(snapshot: TopologySnapshot) -> None:
    delegated_outputs = tuple(
        contract.agent_id
        for contract in snapshot.contracts
        if contract.role
        in {AgentRole.WORKER, AgentRole.IMPLEMENTER, AgentRole.RESEARCHER, AgentRole.WATCHER}
    )
    verifiers = tuple(
        contract for contract in snapshot.contracts if contract.role is AgentRole.VERIFIER
    )
    integration_verifiers = tuple(
        contract for contract in verifiers if contract.is_parent_integration_verifier
    )
    if not delegated_outputs:
        if integration_verifiers:
            raise ValueError("non-delegated topology cannot declare a parent integration verifier")
        return
    if len(verifiers) != 1 or len(integration_verifiers) != 1:
        raise ValueError("delegated topologies require exactly one parent integration verifier")
    verifier = integration_verifiers[0]
    if snapshot.contracts[-1] is not verifier:
        raise ValueError("parent integration verifier must be the final contract")
    if verifier.depends_on != delegated_outputs:
        raise ValueError(
            "parent integration verifier must deterministically depend on every delegated output"
        )


def _validate_watcher_requirements(snapshot: TopologySnapshot) -> None:
    # A watcher is the only long-wait/CI role in this offline contract, and its
    # constructor rejects chat polling or non-artifact receipts.
    for contract in snapshot.contracts:
        if contract.role is AgentRole.WATCHER and contract.watcher_contract is None:
            raise ValueError("long wait role is missing artifact watcher contract")


def _validate_retry_history(snapshot: TopologySnapshot) -> None:
    retry_events = tuple(
        event
        for event in snapshot.escalation_events
        if event.action is EscalationAction.RETRY
    )
    retry_count = sum(state.retry_count for state in snapshot.agent_states)
    if retry_count > 1 or len(retry_events) > 1:
        raise ValueError("topology permits only one retry total")
    if retry_count != len(retry_events):
        raise ValueError("retry state must match the escalation history")
    if snapshot.status is TopologyStatus.RETRY and len(retry_events) != 1:
        raise ValueError("retry status requires one recorded retry")

    for event in retry_events:
        if not event.evidence_refs:
            raise ValueError("retry must be evidence-backed")
        if event.retry_target is None:
            raise ValueError("retry event requires a retry target")
        if snapshot.state(event.retry_target).retry_count != 1:
            raise ValueError("retry count must belong to the recorded retry target")
        contract = snapshot.contract(event.agent_id)
        if event.kind is EscalationKind.EXECUTION_FAILURE:
            if event.retry_target != event.agent_id or event.rejected_agent_id is not None:
                raise ValueError("execution retry must target the failed agent")
        elif event.kind is EscalationKind.VERIFIER_REJECTION:
            if (
                contract.role is not AgentRole.VERIFIER
                or not contract.is_parent_integration_verifier
                or event.rejected_agent_id != event.retry_target
                or event.retry_target not in contract.depends_on
            ):
                raise ValueError(
                    "verifier retry must identify a rejected verifier dependency"
                )
        else:
            raise ValueError("only execution failure or verifier rejection may retry")
