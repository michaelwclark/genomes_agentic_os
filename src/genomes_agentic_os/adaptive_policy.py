"""Pure, capability-safe policy resolution for the adaptive model router.

The router returns recommendations only.  Off mode preserves Feature 62's
existing static configuration contract and never mutates config installation
state.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping, Optional, TypeVar

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode


POLICY_VERSION = 1
YAML_SCHEMA_VERSION = 1
MODEL_CATALOG_VERSION = 1


class PolicyMode(str, Enum):
    OFF = "off"
    OBSERVE = "observe"
    GUARDED = "guarded"
    ENFORCE = "enforce"


class ModelTier(str, Enum):
    ECONOMY = "economy"
    BALANCED = "balanced"
    FRONTIER = "frontier"
    FRONTIER_MAX = "frontier_max"
    HUMAN_GATE = "human_gate"


class CapabilityTier(str, Enum):
    """Model capability classes, independent from route approval states."""

    ECONOMY = "economy"
    BALANCED = "balanced"
    FRONTIER = "frontier"


class ReasoningEffort(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"
    ULTRA = "ultra"


class CostClass(str, Enum):
    ECONOMY = "economy"
    STANDARD = "standard"
    PREMIUM = "premium"


class AdaptivePolicyError(ValueError):
    """Raised when the router cannot produce a safe deterministic result."""


class PolicyValidationError(AdaptivePolicyError):
    """Raised when a versioned policy is malformed or unsafe for its context."""


class CapabilityUnavailableError(AdaptivePolicyError):
    """Raised when no approved, available model can satisfy a route."""


class HumanApprovalRequiredError(AdaptivePolicyError):
    """Raised when the human-gated tier has not received explicit approval."""


def _enum(value: object, enum_type: type[Enum], field_name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        try:
            return enum_type(value)
        except ValueError:
            pass
    raise PolicyValidationError(f"{field_name} must be a supported {enum_type.__name__}")


def parse_model_tier(value: ModelTier | str) -> ModelTier:
    return _enum(value, ModelTier, "tier")  # type: ignore[return-value]


def parse_capability_tier(value: CapabilityTier | str) -> CapabilityTier:
    return _enum(value, CapabilityTier, "capability_tier")  # type: ignore[return-value]


def parse_reasoning_effort(value: ReasoningEffort | str) -> ReasoningEffort:
    return _enum(value, ReasoningEffort, "reasoning_effort")  # type: ignore[return-value]


def parse_policy_mode(value: PolicyMode | str) -> PolicyMode:
    return _enum(value, PolicyMode, "mode")  # type: ignore[return-value]


TIER_ORDER: Mapping[ModelTier, int] = MappingProxyType(
    {
        ModelTier.ECONOMY: 0,
        ModelTier.BALANCED: 1,
        ModelTier.FRONTIER: 2,
        ModelTier.FRONTIER_MAX: 3,
        ModelTier.HUMAN_GATE: 4,
    }
)
CAPABILITY_RANK: Mapping[CapabilityTier, int] = MappingProxyType(
    {
        CapabilityTier.ECONOMY: 0,
        CapabilityTier.BALANCED: 1,
        CapabilityTier.FRONTIER: 2,
    }
)
AUTHORITATIVE_MODEL_CAPABILITY_TIERS: Mapping[str, CapabilityTier] = (
    MappingProxyType(
        {
            "gpt-5.6-luna": CapabilityTier.ECONOMY,
            "gpt-5.6-terra": CapabilityTier.BALANCED,
            "gpt-5.6-sol": CapabilityTier.FRONTIER,
        }
    )
)
EFFORT_ORDER: Mapping[ReasoningEffort, int] = MappingProxyType(
    {
        ReasoningEffort.LOW: 0,
        ReasoningEffort.MEDIUM: 1,
        ReasoningEffort.HIGH: 2,
        ReasoningEffort.XHIGH: 3,
        ReasoningEffort.MAX: 4,
        ReasoningEffort.ULTRA: 5,
    }
)
TIER_CAPABILITY_FLOOR: Mapping[ModelTier, CapabilityTier] = MappingProxyType(
    {
        ModelTier.ECONOMY: CapabilityTier.ECONOMY,
        ModelTier.BALANCED: CapabilityTier.BALANCED,
        ModelTier.FRONTIER: CapabilityTier.FRONTIER,
        ModelTier.FRONTIER_MAX: CapabilityTier.FRONTIER,
        ModelTier.HUMAN_GATE: CapabilityTier.FRONTIER,
    }
)
TIER_EFFORT_FLOOR: Mapping[ModelTier, ReasoningEffort] = MappingProxyType(
    {
        ModelTier.ECONOMY: ReasoningEffort.LOW,
        ModelTier.BALANCED: ReasoningEffort.MEDIUM,
        ModelTier.FRONTIER: ReasoningEffort.HIGH,
        ModelTier.FRONTIER_MAX: ReasoningEffort.ULTRA,
        ModelTier.HUMAN_GATE: ReasoningEffort.ULTRA,
    }
)


def at_least_tier(*tiers: ModelTier | str) -> ModelTier:
    parsed = tuple(parse_model_tier(tier) for tier in tiers)
    if not parsed:
        raise PolicyValidationError("at least one tier is required")
    return max(parsed, key=TIER_ORDER.__getitem__)


def at_least_effort(*efforts: ReasoningEffort | str) -> ReasoningEffort:
    parsed = tuple(parse_reasoning_effort(effort) for effort in efforts)
    if not parsed:
        raise PolicyValidationError("at least one reasoning effort is required")
    return max(parsed, key=EFFORT_ORDER.__getitem__)


@dataclass(frozen=True)
class ModelRequirements:
    """Capabilities required by a reviewed route."""

    coding: Optional[bool] = None
    tool_use: Optional[bool] = None
    min_context_tokens: int = 0
    subagent_suitable: Optional[bool] = None

    def __post_init__(self) -> None:
        for name in ("coding", "tool_use", "subagent_suitable"):
            value = getattr(self, name)
            if value is not None and type(value) is not bool:
                raise PolicyValidationError(f"requirements.{name} must be a bool or null")
        if type(self.min_context_tokens) is not int or self.min_context_tokens < 0:
            raise PolicyValidationError(
                "requirements.min_context_tokens must be a non-negative integer"
            )


@dataclass(frozen=True)
class ModelCapability:
    """An immutable catalog record with an enforced capability rank."""

    model_id: str
    supported_reasoning_efforts: tuple[ReasoningEffort | str, ...]
    aliases: tuple[str, ...] = ()
    capability_tier: CapabilityTier | str = CapabilityTier.BALANCED
    coding: bool = True
    tool_use: bool = True
    context_tokens: int = 128_000
    subagent_suitable: bool = True
    cost_class: CostClass | str = CostClass.STANDARD
    customer_safe: bool = True
    available: bool = True
    capability_rank: int = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.model_id, str) or not self.model_id.strip():
            raise PolicyValidationError("model_id must be a non-empty string")
        if not isinstance(self.aliases, tuple) or any(
            not isinstance(item, str) or not item for item in self.aliases
        ):
            raise PolicyValidationError("model aliases must be a tuple of non-empty strings")
        if len(set(self.aliases)) != len(self.aliases) or self.model_id in self.aliases:
            raise PolicyValidationError(
                "model aliases must be unique and cannot repeat model_id"
            )
        efforts = tuple(
            parse_reasoning_effort(value) for value in self.supported_reasoning_efforts
        )
        if not efforts or len(set(efforts)) != len(efforts):
            raise PolicyValidationError(
                "supported_reasoning_efforts must be a unique non-empty tuple"
            )
        for name in (
            "coding",
            "tool_use",
            "subagent_suitable",
            "customer_safe",
            "available",
        ):
            if type(getattr(self, name)) is not bool:
                raise PolicyValidationError(f"model capability {name} must be a bool")
        if type(self.context_tokens) is not int or self.context_tokens <= 0:
            raise PolicyValidationError(
                "model capability context_tokens must be a positive integer"
            )
        capability_tier = parse_capability_tier(self.capability_tier)
        authoritative_tier = AUTHORITATIVE_MODEL_CAPABILITY_TIERS.get(
            self.model_id
        )
        if (
            authoritative_tier is not None
            and capability_tier is not authoritative_tier
        ):
            raise PolicyValidationError(
                f"{self.model_id} capability_tier must be "
                f"{authoritative_tier.value}"
            )
        object.__setattr__(self, "supported_reasoning_efforts", efforts)
        object.__setattr__(self, "capability_tier", capability_tier)
        object.__setattr__(self, "capability_rank", CAPABILITY_RANK[capability_tier])
        object.__setattr__(
            self, "cost_class", _enum(self.cost_class, CostClass, "cost_class")
        )

    def supports(self, effort: ReasoningEffort) -> bool:
        return effort in self.supported_reasoning_efforts

    def satisfies(self, requirements: ModelRequirements) -> bool:
        return bool(
            (requirements.coding is None or self.coding is requirements.coding)
            and (requirements.tool_use is None or self.tool_use is requirements.tool_use)
            and self.context_tokens >= requirements.min_context_tokens
            and (
                requirements.subagent_suitable is None
                or self.subagent_suitable is requirements.subagent_suitable
            )
        )


@dataclass(frozen=True)
class ModelCatalog:
    """Deterministic catalog; aliases are the explicit approval and rename map."""

    records: tuple[ModelCapability, ...]
    version: int = MODEL_CATALOG_VERSION
    _by_reference: Mapping[str, ModelCapability] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != MODEL_CATALOG_VERSION:
            raise PolicyValidationError(
                f"unsupported model catalog version {self.version!r}; "
                f"expected {MODEL_CATALOG_VERSION}"
            )
        if (
            not isinstance(self.records, tuple)
            or not self.records
            or any(not isinstance(record, ModelCapability) for record in self.records)
        ):
            raise PolicyValidationError(
                "model catalog records must be a non-empty tuple of ModelCapability"
            )
        by_reference: dict[str, ModelCapability] = {}
        for record in self.records:
            for reference in (record.model_id, *record.aliases):
                if reference in by_reference:
                    raise PolicyValidationError(
                        f"model catalog contains duplicate id or alias {reference!r}"
                    )
                by_reference[reference] = record
        object.__setattr__(self, "_by_reference", MappingProxyType(by_reference))

    def get(self, model_id_or_alias: str) -> Optional[ModelCapability]:
        return self._by_reference.get(model_id_or_alias)


@dataclass(frozen=True)
class ModelCandidate:
    """A reviewed route candidate; model_id may be a catalog alias."""

    model_id: str
    reasoning_effort: ReasoningEffort | str
    requirements: ModelRequirements = ModelRequirements()

    def __post_init__(self) -> None:
        if not isinstance(self.model_id, str) or not self.model_id:
            raise PolicyValidationError(
                "candidate model_id must be a non-empty model id or alias"
            )
        object.__setattr__(
            self, "reasoning_effort", parse_reasoning_effort(self.reasoning_effort)
        )
        if not isinstance(self.requirements, ModelRequirements):
            raise PolicyValidationError(
                "candidate requirements must be ModelRequirements"
            )


@dataclass(frozen=True)
class TierRoute:
    tier: ModelTier | str
    candidates: tuple[ModelCandidate, ...]
    requires_human_approval: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "tier", parse_model_tier(self.tier))
        if (
            not isinstance(self.candidates, tuple)
            or not self.candidates
            or any(
                not isinstance(candidate, ModelCandidate)
                for candidate in self.candidates
            )
        ):
            raise PolicyValidationError(
                "tier route candidates must be a non-empty tuple of ModelCandidate"
            )
        if type(self.requires_human_approval) is not bool:
            raise PolicyValidationError(
                "tier route requires_human_approval must be a bool"
            )


@dataclass(frozen=True)
class StaticFallback:
    feature: str
    behavior: str

    def __post_init__(self) -> None:
        for name in ("feature", "behavior"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise PolicyValidationError(
                    f"static_fallback.{name} must be a non-empty string"
                )


@dataclass(frozen=True)
class AdaptivePolicy:
    """Resolved layer values."""

    version: int = POLICY_VERSION
    mode: PolicyMode = PolicyMode.OFF
    default_tier: ModelTier = ModelTier.BALANCED
    customer_safe: bool = True
    allow_model_overrides: bool = False
    allowed_model_overrides: frozenset[str] = frozenset()


@dataclass(frozen=True)
class PolicyOverrides:
    """One partial layer; fields absent here do not override."""

    version: Optional[int] = None
    mode: Optional[PolicyMode] = None
    default_tier: Optional[ModelTier] = None
    customer_safe: Optional[bool] = None
    allow_model_overrides: Optional[bool] = None
    allowed_model_overrides: Optional[frozenset[str]] = None


@dataclass(frozen=True)
class PolicyLayers:
    """Explicit precedence: host < project < workflow < customer < request."""

    host: PolicyOverrides = PolicyOverrides()
    project: PolicyOverrides = PolicyOverrides()
    workflow: PolicyOverrides = PolicyOverrides()
    customer: PolicyOverrides = PolicyOverrides()


@dataclass(frozen=True)
class RuntimePolicyDocument:
    """A complete parsed runtime policy; no YAML section is merely decorative."""

    schema_version: int
    policy_version: int
    layers: PolicyLayers
    policy: AdaptivePolicy
    catalog: ModelCatalog
    tier_routes: Mapping[ModelTier, TierRoute]
    static_fallback: StaticFallback

    def __post_init__(self) -> None:
        if self.schema_version != YAML_SCHEMA_VERSION:
            raise PolicyValidationError(
                f"unsupported adaptive router schema_version {self.schema_version!r}"
            )
        if self.policy_version != POLICY_VERSION:
            raise PolicyValidationError(
                f"unsupported adaptive policy version {self.policy_version!r}; "
                f"expected {POLICY_VERSION}"
            )
        if self.policy.version != self.policy_version:
            raise PolicyValidationError(
                "runtime policy version does not match document policy_version"
            )
        if not isinstance(self.layers, PolicyLayers):
            raise PolicyValidationError("runtime policy layers must be PolicyLayers")
        if not isinstance(self.catalog, ModelCatalog):
            raise PolicyValidationError(
                "runtime policy catalog must be a ModelCatalog"
            )
        if not isinstance(self.static_fallback, StaticFallback):
            raise PolicyValidationError(
                "runtime policy static_fallback must be StaticFallback"
            )
        routes = _validated_document_routes(self.tier_routes, self.catalog)
        object.__setattr__(self, "tier_routes", MappingProxyType(routes))


@dataclass(frozen=True)
class RoutingRequest:
    """Call inputs. Minimum fields are safety floors supplied by assessment."""

    tier: Optional[ModelTier | str] = None
    assessment_minimum_tier: Optional[ModelTier | str] = None
    minimum_tier: Optional[ModelTier | str] = None
    model_override: Optional[str] = None
    reasoning_effort: Optional[ReasoningEffort | str] = None
    required_reasoning_effort: Optional[ReasoningEffort | str] = None
    customer_safe: bool = False
    human_approved: bool = False


@dataclass(frozen=True)
class ResolvedSelection:
    model_id: str
    reasoning_effort: ReasoningEffort
    tier: ModelTier
    source: str


@dataclass(frozen=True)
class PolicyResolution:
    version: int
    mode: PolicyMode
    tier: ModelTier
    applied: bool
    selection: Optional[ResolvedSelection]
    static_fallback: Optional[StaticFallback] = None
    human_approval_required: bool = False


LUNA_EFFORTS = (
    ReasoningEffort.LOW,
    ReasoningEffort.MEDIUM,
    ReasoningEffort.HIGH,
    ReasoningEffort.XHIGH,
    ReasoningEffort.MAX,
)
TERRA_EFFORTS = LUNA_EFFORTS + (ReasoningEffort.ULTRA,)
SOL_EFFORTS = TERRA_EFFORTS
DEFAULT_MODEL_CATALOG = ModelCatalog(
    records=(
        ModelCapability(
            "gpt-5.6-luna",
            LUNA_EFFORTS,
            aliases=("economy",),
            capability_tier=CapabilityTier.ECONOMY,
            cost_class=CostClass.ECONOMY,
        ),
        ModelCapability(
            "gpt-5.6-terra",
            TERRA_EFFORTS,
            aliases=("balanced",),
            capability_tier=CapabilityTier.BALANCED,
            cost_class=CostClass.STANDARD,
        ),
        ModelCapability(
            "gpt-5.6-sol",
            SOL_EFFORTS,
            aliases=("frontier",),
            capability_tier=CapabilityTier.FRONTIER,
            cost_class=CostClass.PREMIUM,
        ),
    )
)

FEATURE_62_STATIC_FALLBACK = StaticFallback(
    feature="62-role-aware-codex-config-layers",
    behavior="preserve_existing_layer_model_and_reasoning_configuration",
)

_CODE_REQUIREMENTS = ModelRequirements(
    coding=True,
    tool_use=True,
    min_context_tokens=32_000,
    subagent_suitable=True,
)
TIER_ROUTES: Mapping[ModelTier, TierRoute] = MappingProxyType(
    {
        ModelTier.ECONOMY: TierRoute(
            ModelTier.ECONOMY,
            (
                ModelCandidate(
                    "economy", ReasoningEffort.MEDIUM, _CODE_REQUIREMENTS
                ),
                ModelCandidate(
                    "balanced", ReasoningEffort.MEDIUM, _CODE_REQUIREMENTS
                ),
            ),
        ),
        ModelTier.BALANCED: TierRoute(
            ModelTier.BALANCED,
            (
                ModelCandidate(
                    "balanced", ReasoningEffort.MEDIUM, _CODE_REQUIREMENTS
                ),
                ModelCandidate(
                    "frontier", ReasoningEffort.MEDIUM, _CODE_REQUIREMENTS
                ),
            ),
        ),
        ModelTier.FRONTIER: TierRoute(
            ModelTier.FRONTIER,
            (
                ModelCandidate(
                    "frontier", ReasoningEffort.HIGH, _CODE_REQUIREMENTS
                ),
            ),
        ),
        ModelTier.FRONTIER_MAX: TierRoute(
            ModelTier.FRONTIER_MAX,
            (
                ModelCandidate(
                    "frontier", ReasoningEffort.ULTRA, _CODE_REQUIREMENTS
                ),
            ),
        ),
        ModelTier.HUMAN_GATE: TierRoute(
            ModelTier.HUMAN_GATE,
            (
                ModelCandidate(
                    "frontier", ReasoningEffort.ULTRA, _CODE_REQUIREMENTS
                ),
            ),
            requires_human_approval=True,
        ),
    }
)


T = TypeVar("T")


def first_defined(*values: Optional[T]) -> Optional[T]:
    return next((value for value in values if value is not None), None)


def resolve_mode(
    request_mode: Optional[PolicyMode | str],
    policy_mode: Optional[PolicyMode | str],
    default: PolicyMode = PolicyMode.OFF,
) -> PolicyMode:
    value = first_defined(request_mode, policy_mode, default)
    return parse_policy_mode(value)  # type: ignore[arg-type]


def resolve_tier(
    request_tier: Optional[ModelTier | str],
    policy_tier: Optional[ModelTier | str],
    default: ModelTier = ModelTier.BALANCED,
) -> ModelTier:
    value = first_defined(request_tier, policy_tier, default)
    return parse_model_tier(value)  # type: ignore[arg-type]


def _validate_bool(value: object, name: str) -> None:
    if type(value) is not bool:
        raise PolicyValidationError(f"{name} must be a bool")


def validate_policy(
    policy: AdaptivePolicy, *, customer_safe_required: bool = False
) -> tuple[str, ...]:
    errors: list[str] = []
    if not isinstance(policy, AdaptivePolicy):
        return ("policy must be an AdaptivePolicy",)
    if type(policy.version) is not int or policy.version != POLICY_VERSION:
        errors.append(
            f"unsupported adaptive policy version {policy.version}; "
            f"expected {POLICY_VERSION}"
        )
    if not isinstance(policy.mode, PolicyMode):
        errors.append("mode must be a PolicyMode")
    if not isinstance(policy.default_tier, ModelTier):
        errors.append("default_tier must be a ModelTier")
    for name in ("customer_safe", "allow_model_overrides"):
        if type(getattr(policy, name)) is not bool:
            errors.append(f"{name} must be a bool")
    if (
        not isinstance(policy.allowed_model_overrides, frozenset)
        or any(
            not isinstance(item, str) or not item
            for item in policy.allowed_model_overrides
        )
    ):
        errors.append(
            "allowed_model_overrides must be a frozenset of non-empty strings"
        )
    if customer_safe_required and policy.customer_safe is not True:
        errors.append("customer-safe routing requires policy.customer_safe=true")
    if policy.allowed_model_overrides and policy.allow_model_overrides is not True:
        errors.append(
            "allowed_model_overrides requires allow_model_overrides=true"
        )
    return tuple(errors)


def ensure_valid_policy(
    policy: AdaptivePolicy, *, customer_safe_required: bool = False
) -> None:
    errors = validate_policy(
        policy, customer_safe_required=customer_safe_required
    )
    if errors:
        raise PolicyValidationError("; ".join(errors))


def _normalise_request(request: RoutingRequest) -> RoutingRequest:
    if not isinstance(request, RoutingRequest):
        raise PolicyValidationError("request must be a RoutingRequest")
    _validate_bool(request.customer_safe, "request.customer_safe")
    _validate_bool(request.human_approved, "request.human_approved")
    if request.model_override is not None and (
        not isinstance(request.model_override, str) or not request.model_override
    ):
        raise PolicyValidationError(
            "request.model_override must be a non-empty string or null"
        )
    return replace(
        request,
        tier=(
            parse_model_tier(request.tier)
            if request.tier is not None
            else None
        ),
        assessment_minimum_tier=(
            parse_model_tier(request.assessment_minimum_tier)
            if request.assessment_minimum_tier is not None
            else None
        ),
        minimum_tier=(
            parse_model_tier(request.minimum_tier)
            if request.minimum_tier is not None
            else None
        ),
        reasoning_effort=(
            parse_reasoning_effort(request.reasoning_effort)
            if request.reasoning_effort is not None
            else None
        ),
        required_reasoning_effort=(
            parse_reasoning_effort(request.required_reasoning_effort)
            if request.required_reasoning_effort is not None
            else None
        ),
    )


def capability_safe(
    candidate: ModelCandidate,
    catalog: ModelCatalog,
    *,
    customer_safe_required: bool,
    required_capability_tier: CapabilityTier | str = CapabilityTier.ECONOMY,
) -> bool:
    record = catalog.get(candidate.model_id)
    capability_floor = parse_capability_tier(required_capability_tier)
    return bool(
        record
        and record.available
        and record.capability_rank >= CAPABILITY_RANK[capability_floor]
        and record.supports(candidate.reasoning_effort)
        and record.satisfies(candidate.requirements)
        and (not customer_safe_required or record.customer_safe)
    )


def resolve_candidate(
    candidates: Iterable[ModelCandidate],
    catalog: ModelCatalog,
    *,
    customer_safe_required: bool,
    required_capability_tier: CapabilityTier | str = CapabilityTier.ECONOMY,
) -> ModelCandidate:
    """Choose only a reviewed route reference in declared order."""

    for candidate in candidates:
        if capability_safe(
            candidate,
            catalog,
            customer_safe_required=customer_safe_required,
            required_capability_tier=required_capability_tier,
        ):
            record = catalog.get(candidate.model_id)
            assert record is not None
            return ModelCandidate(
                record.model_id,
                candidate.reasoning_effort,
                candidate.requirements,
            )
    raise CapabilityUnavailableError(
        "no approved available model satisfies the requested capability tier, "
        "requirements, and reasoning effort"
    )


def _policy_from_layers(layers: PolicyLayers) -> AdaptivePolicy:
    if not isinstance(layers, PolicyLayers):
        raise PolicyValidationError("layers must be PolicyLayers")
    values: dict[str, object] = {
        "version": POLICY_VERSION,
        "mode": PolicyMode.OFF,
        "default_tier": ModelTier.BALANCED,
        "customer_safe": True,
        "allow_model_overrides": False,
        "allowed_model_overrides": frozenset(),
    }
    customer_safe_values: list[bool] = []
    for layer in (
        layers.host,
        layers.project,
        layers.workflow,
        layers.customer,
    ):
        if not isinstance(layer, PolicyOverrides):
            raise PolicyValidationError(
                "each policy layer must be PolicyOverrides"
            )
        for name in (
            "version",
            "mode",
            "default_tier",
            "allow_model_overrides",
            "allowed_model_overrides",
        ):
            value = getattr(layer, name)
            if value is not None:
                values[name] = value
        if layer.customer_safe is not None:
            _validate_bool(layer.customer_safe, "layer.customer_safe")
            customer_safe_values.append(layer.customer_safe)
    # Safety is a requirement. Any layer may tighten it; no later layer may
    # turn a previously true requirement off.
    values["customer_safe"] = (
        any(customer_safe_values) if customer_safe_values else True
    )
    policy = AdaptivePolicy(**values)  # type: ignore[arg-type]
    ensure_valid_policy(policy)
    return policy


def resolve_layered_policy(layers: PolicyLayers) -> AdaptivePolicy:
    return _policy_from_layers(layers)


_POLICY_VALUE_FIELDS = frozenset(
    {
        "mode",
        "default_tier",
        "customer_safe",
        "allow_model_overrides",
        "allowed_model_overrides",
    }
)
_LAYER_FIELDS = _POLICY_VALUE_FIELDS | {"policy_version"}
_LAYER_NAMES = frozenset({"host", "project", "workflow", "customer"})
_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "policy_version",
        "layers",
        "catalog",
        "static_fallback",
        "tiers",
    }
) | _POLICY_VALUE_FIELDS
_CATALOG_FIELDS = frozenset({"version", "models"})
_MODEL_FIELDS = frozenset(
    {
        "model_id",
        "aliases",
        "capability_tier",
        "supported_reasoning_efforts",
        "coding",
        "tool_use",
        "context_tokens",
        "subagent_suitable",
        "cost_class",
        "customer_safe",
        "available",
    }
)
_TIER_FIELDS = frozenset(
    {"primary", "fallbacks", "requires_human_approval"}
)
_CANDIDATE_FIELDS = frozenset(
    {"model", "reasoning_effort", "requirements"}
)
_REQUIREMENT_FIELDS = frozenset(
    {"coding", "tool_use", "min_context_tokens", "subagent_suitable"}
)
_STATIC_FALLBACK_FIELDS = frozenset({"feature", "behavior"})


def _unknown_keys(
    payload: Mapping[object, object],
    allowed: frozenset[str],
    section: str,
) -> None:
    if any(not isinstance(key, str) for key in payload):
        raise PolicyValidationError(f"{section} keys must be strings")
    unknown = set(payload) - allowed
    if unknown:
        raise PolicyValidationError(
            f"unsupported {section} keys: {', '.join(sorted(unknown))}"
        )


def _required_keys(
    payload: Mapping[str, object],
    required: frozenset[str],
    section: str,
) -> None:
    missing = required - set(payload)
    if missing:
        raise PolicyValidationError(
            f"{section} is missing required keys: {', '.join(sorted(missing))}"
        )


def _required_version(
    payload: Mapping[str, object], name: str, expected: int
) -> int:
    value = payload.get(name)
    if type(value) is not int:
        raise PolicyValidationError(f"{name} must be an integer")
    if value != expected:
        raise PolicyValidationError(
            f"unsupported {name} {value!r}; expected {expected}"
        )
    return value


def _parse_layer(
    payload: Mapping[str, object],
    *,
    root_version: int,
    section: str,
) -> PolicyOverrides:
    _unknown_keys(payload, _LAYER_FIELDS, section)

    def optional_bool(name: str) -> Optional[bool]:
        value = payload.get(name)
        if value is None:
            return None
        _validate_bool(value, f"{section}.{name}")
        return value

    version = payload.get("policy_version")
    if version is not None:
        if type(version) is not int:
            raise PolicyValidationError(
                f"{section}.policy_version must be an integer"
            )
        if version != root_version:
            raise PolicyValidationError(
                f"{section}.policy_version must match root policy_version"
            )
    overrides = payload.get("allowed_model_overrides")
    if overrides is not None:
        if (
            not isinstance(overrides, list)
            or any(not isinstance(item, str) or not item for item in overrides)
        ):
            raise PolicyValidationError(
                f"{section}.allowed_model_overrides must be a list of "
                "non-empty strings"
            )
        if len(set(overrides)) != len(overrides):
            raise PolicyValidationError(
                f"{section}.allowed_model_overrides must not contain duplicates"
            )
        parsed_overrides: Optional[frozenset[str]] = frozenset(overrides)
    else:
        parsed_overrides = None
    return PolicyOverrides(
        version=version,
        mode=(
            parse_policy_mode(payload["mode"])
            if "mode" in payload
            else None
        ),
        default_tier=(
            parse_model_tier(payload["default_tier"])
            if "default_tier" in payload
            else None
        ),
        customer_safe=optional_bool("customer_safe"),
        allow_model_overrides=optional_bool("allow_model_overrides"),
        allowed_model_overrides=parsed_overrides,
    )


def _parse_layers(
    document: Mapping[str, object], root_version: int
) -> PolicyLayers:
    legacy_fields = set(document).intersection(_POLICY_VALUE_FIELDS)
    layers_present = "layers" in document
    layer_payloads = document.get("layers")
    if layers_present and legacy_fields:
        raise PolicyValidationError(
            "adaptive router YAML cannot mix legacy top-level policy fields "
            "with layers"
        )
    if not layers_present:
        legacy_payload = {
            key: document[key] for key in legacy_fields
        }
        legacy_payload["policy_version"] = root_version
        return PolicyLayers(
            host=_parse_layer(
                legacy_payload,
                root_version=root_version,
                section="legacy policy",
            )
        )
    if not isinstance(layer_payloads, Mapping):
        raise PolicyValidationError("layers must be a mapping")
    _unknown_keys(layer_payloads, _LAYER_NAMES, "adaptive policy layers")
    parsed: dict[str, PolicyOverrides] = {}
    for name in ("host", "project", "workflow", "customer"):
        payload = layer_payloads.get(name, {})
        if not isinstance(payload, Mapping):
            raise PolicyValidationError(f"layers.{name} must be a mapping")
        parsed[name] = _parse_layer(
            payload,
            root_version=root_version,
            section=f"layers.{name}",
        )
    return PolicyLayers(**parsed)


def _parse_catalog(payload: object) -> ModelCatalog:
    if not isinstance(payload, Mapping):
        raise PolicyValidationError("catalog must be a mapping")
    _unknown_keys(payload, _CATALOG_FIELDS, "catalog")
    _required_keys(payload, _CATALOG_FIELDS, "catalog")
    version = _required_version(
        payload, "version", MODEL_CATALOG_VERSION
    )
    models = payload["models"]
    if not isinstance(models, list) or not models:
        raise PolicyValidationError("catalog.models must be a non-empty list")
    records: list[ModelCapability] = []
    for index, item in enumerate(models):
        section = f"catalog.models[{index}]"
        if not isinstance(item, Mapping):
            raise PolicyValidationError(f"{section} must be a mapping")
        _unknown_keys(item, _MODEL_FIELDS, section)
        _required_keys(item, _MODEL_FIELDS, section)
        aliases = item["aliases"]
        efforts = item["supported_reasoning_efforts"]
        if not isinstance(aliases, list):
            raise PolicyValidationError(f"{section}.aliases must be a list")
        if not isinstance(efforts, list):
            raise PolicyValidationError(
                f"{section}.supported_reasoning_efforts must be a list"
            )
        for name in (
            "coding",
            "tool_use",
            "subagent_suitable",
            "customer_safe",
            "available",
        ):
            _validate_bool(item[name], f"{section}.{name}")
        records.append(
            ModelCapability(
                model_id=item["model_id"],  # type: ignore[arg-type]
                aliases=tuple(aliases),
                capability_tier=item["capability_tier"],  # type: ignore[arg-type]
                supported_reasoning_efforts=tuple(efforts),
                coding=item["coding"],  # type: ignore[arg-type]
                tool_use=item["tool_use"],  # type: ignore[arg-type]
                context_tokens=item["context_tokens"],  # type: ignore[arg-type]
                subagent_suitable=item["subagent_suitable"],  # type: ignore[arg-type]
                cost_class=item["cost_class"],  # type: ignore[arg-type]
                customer_safe=item["customer_safe"],  # type: ignore[arg-type]
                available=item["available"],  # type: ignore[arg-type]
            )
        )
    return ModelCatalog(tuple(records), version=version)


def _parse_requirements(
    payload: object, *, section: str
) -> ModelRequirements:
    if payload is None:
        return _CODE_REQUIREMENTS
    if not isinstance(payload, Mapping):
        raise PolicyValidationError(f"{section} must be a mapping")
    _unknown_keys(payload, _REQUIREMENT_FIELDS, section)
    values: dict[str, object] = {
        "coding": _CODE_REQUIREMENTS.coding,
        "tool_use": _CODE_REQUIREMENTS.tool_use,
        "min_context_tokens": _CODE_REQUIREMENTS.min_context_tokens,
        "subagent_suitable": _CODE_REQUIREMENTS.subagent_suitable,
    }
    values.update(payload)
    return ModelRequirements(**values)  # type: ignore[arg-type]


def _parse_candidate(payload: object, *, section: str) -> ModelCandidate:
    if not isinstance(payload, Mapping):
        raise PolicyValidationError(f"{section} must be a mapping")
    _unknown_keys(payload, _CANDIDATE_FIELDS, section)
    _required_keys(
        payload, frozenset({"model", "reasoning_effort"}), section
    )
    return ModelCandidate(
        model_id=payload["model"],  # type: ignore[arg-type]
        reasoning_effort=payload["reasoning_effort"],  # type: ignore[arg-type]
        requirements=_parse_requirements(
            payload.get("requirements"),
            section=f"{section}.requirements",
        ),
    )


def _parse_tier_routes(
    payload: object, catalog: ModelCatalog
) -> Mapping[ModelTier, TierRoute]:
    if not isinstance(payload, Mapping):
        raise PolicyValidationError("tiers must be a mapping")
    if any(not isinstance(key, str) for key in payload):
        raise PolicyValidationError("tiers keys must be strings")
    expected_names = {tier.value for tier in ModelTier}
    unknown = set(payload) - expected_names
    missing = expected_names - set(payload)
    if unknown:
        raise PolicyValidationError(
            f"unsupported tiers: {', '.join(sorted(unknown))}"
        )
    if missing:
        raise PolicyValidationError(
            f"tiers is missing required tiers: {', '.join(sorted(missing))}"
        )
    routes: dict[ModelTier, TierRoute] = {}
    for tier in ModelTier:
        section = f"tiers.{tier.value}"
        route_payload = payload[tier.value]
        if not isinstance(route_payload, Mapping):
            raise PolicyValidationError(f"{section} must be a mapping")
        _unknown_keys(route_payload, _TIER_FIELDS, section)
        if "primary" not in route_payload:
            raise PolicyValidationError(
                f"{section} is missing required key: primary"
            )
        primary = _parse_candidate(
            route_payload["primary"], section=f"{section}.primary"
        )
        fallbacks = route_payload.get("fallbacks", [])
        if not isinstance(fallbacks, list):
            raise PolicyValidationError(f"{section}.fallbacks must be a list")
        candidates = (primary,) + tuple(
            _parse_candidate(
                candidate,
                section=f"{section}.fallbacks[{index}]",
            )
            for index, candidate in enumerate(fallbacks)
        )
        approval = route_payload.get(
            "requires_human_approval",
            tier is ModelTier.HUMAN_GATE,
        )
        _validate_bool(approval, f"{section}.requires_human_approval")
        routes[tier] = TierRoute(
            tier,
            candidates,
            requires_human_approval=approval,
        )
    return MappingProxyType(_validated_document_routes(routes, catalog))


def _validated_document_routes(
    routes: Mapping[ModelTier, TierRoute],
    catalog: ModelCatalog,
) -> dict[ModelTier, TierRoute]:
    if not isinstance(routes, Mapping):
        raise PolicyValidationError("tier_routes must be a mapping")
    expected = set(ModelTier)
    unknown = set(routes) - expected
    missing = expected - set(routes)
    if unknown:
        raise PolicyValidationError(
            "tier_routes contains unsupported tier keys"
        )
    if missing:
        raise PolicyValidationError(
            "tier_routes is missing required tiers: "
            + ", ".join(sorted(tier.value for tier in missing))
        )
    parsed = dict(routes)
    for tier, route in parsed.items():
        if not isinstance(route, TierRoute) or route.tier is not tier:
            raise PolicyValidationError(
                f"tier route {tier.value} must identify its own tier"
            )
        if tier is ModelTier.HUMAN_GATE and not route.requires_human_approval:
            raise PolicyValidationError(
                "human_gate route must require human approval"
            )
        capability_floor = TIER_CAPABILITY_FLOOR[tier]
        effort_floor = TIER_EFFORT_FLOOR[tier]
        for candidate in route.candidates:
            record = catalog.get(candidate.model_id)
            if record is None:
                raise PolicyValidationError(
                    f"tier {tier.value} references unknown model "
                    f"{candidate.model_id!r}"
                )
            if record.capability_rank < CAPABILITY_RANK[capability_floor]:
                raise PolicyValidationError(
                    f"unsafe tier downgrade mapping: tier {tier.value} "
                    f"requires {capability_floor.value} capability but "
                    f"{record.model_id} is {record.capability_tier.value}"
                )
            if (
                EFFORT_ORDER[candidate.reasoning_effort]
                < EFFORT_ORDER[effort_floor]
            ):
                raise PolicyValidationError(
                    f"unsafe tier effort downgrade: tier {tier.value} "
                    f"requires at least {effort_floor.value}"
                )
            if not record.supports(candidate.reasoning_effort):
                raise PolicyValidationError(
                    f"tier {tier.value} selects unsupported effort "
                    f"{candidate.reasoning_effort.value} for {record.model_id}"
                )
            if not record.satisfies(candidate.requirements):
                raise PolicyValidationError(
                    f"tier {tier.value} candidate {record.model_id} does not "
                    "satisfy its configured requirements"
                )
    return parsed


def _parse_static_fallback(payload: object) -> StaticFallback:
    if not isinstance(payload, Mapping):
        raise PolicyValidationError("static_fallback must be a mapping")
    _unknown_keys(
        payload, _STATIC_FALLBACK_FIELDS, "static_fallback"
    )
    _required_keys(
        payload, _STATIC_FALLBACK_FIELDS, "static_fallback"
    )
    return StaticFallback(
        feature=payload["feature"],  # type: ignore[arg-type]
        behavior=payload["behavior"],  # type: ignore[arg-type]
    )


def parse_adaptive_policy_document(
    document: Mapping[str, object],
) -> RuntimePolicyDocument:
    """Parse and validate a complete versioned runtime policy document."""

    if not isinstance(document, Mapping):
        raise PolicyValidationError(
            "adaptive router YAML must contain a mapping"
        )
    _unknown_keys(document, _TOP_LEVEL_FIELDS, "adaptive router top-level")
    schema_version = _required_version(
        document, "schema_version", YAML_SCHEMA_VERSION
    )
    policy_version = _required_version(
        document, "policy_version", POLICY_VERSION
    )
    for required_section in ("catalog", "tiers", "static_fallback"):
        if required_section not in document:
            raise PolicyValidationError(
                f"adaptive router YAML is missing required section "
                f"{required_section}"
            )
    layers = _parse_layers(document, policy_version)
    policy = resolve_layered_policy(layers)
    catalog = _parse_catalog(document["catalog"])
    tier_routes = _parse_tier_routes(document["tiers"], catalog)
    static_fallback = _parse_static_fallback(document["static_fallback"])
    return RuntimePolicyDocument(
        schema_version=schema_version,
        policy_version=policy_version,
        layers=layers,
        policy=policy,
        catalog=catalog,
        tier_routes=tier_routes,
        static_fallback=static_fallback,
    )


class _DuplicateKeySafeLoader(yaml.SafeLoader):
    """SafeLoader variant that rejects duplicate and merge-colliding keys."""


def _construct_unique_mapping(
    loader: _DuplicateKeySafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    loader.flatten_mapping(node)
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_DuplicateKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def load_policy_text(text: str) -> RuntimePolicyDocument:
    """Load inline YAML text; filesystem paths are never inferred."""

    if not isinstance(text, str):
        raise PolicyValidationError("policy text must be a string")
    try:
        parsed = yaml.load(text, Loader=_DuplicateKeySafeLoader)
    except yaml.YAMLError as exc:
        raise PolicyValidationError(
            f"invalid adaptive policy YAML: {exc}"
        ) from exc
    return parse_adaptive_policy_document(parsed)


def load_policy_file(path: str | Path) -> RuntimePolicyDocument:
    """Load YAML from an explicit path using the duplicate-rejecting loader."""

    if not isinstance(path, (str, Path)):
        raise PolicyValidationError(
            "policy file path must be a string or Path"
        )
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise PolicyValidationError(
            f"unable to read adaptive policy file {path!s}: {exc}"
        ) from exc
    return load_policy_text(text)


def load_adaptive_policy_yaml(text: str) -> RuntimePolicyDocument:
    """Compatibility name for inline YAML; use load_policy_file for paths."""

    return load_policy_text(text)


def _effective_candidate(
    candidate: ModelCandidate,
    requested_effort: Optional[ReasoningEffort],
    required_effort: ReasoningEffort,
) -> Optional[ModelCandidate]:
    if requested_effort is not None:
        if (
            EFFORT_ORDER[requested_effort]
            < EFFORT_ORDER[candidate.reasoning_effort]
        ):
            return None
        effort = requested_effort
    else:
        effort = at_least_effort(
            candidate.reasoning_effort, required_effort
        )
    return ModelCandidate(
        candidate.model_id, effort, candidate.requirements
    )


def resolve_policy(
    policy: AdaptivePolicy | RuntimePolicyDocument,
    request: RoutingRequest = RoutingRequest(),
    *,
    catalog: Optional[ModelCatalog] = None,
    tier_routes: Optional[Mapping[ModelTier, TierRoute]] = None,
    static_fallback: Optional[StaticFallback] = None,
    mode_override: Optional[PolicyMode | str] = None,
) -> PolicyResolution:
    """Resolve a policy safely; request values can strengthen but not lower floors."""

    document = policy if isinstance(policy, RuntimePolicyDocument) else None
    if document is not None:
        resolved_policy = document.policy
        effective_catalog = (
            catalog if catalog is not None else document.catalog
        )
        effective_routes = (
            tier_routes
            if tier_routes is not None
            else document.tier_routes
        )
        effective_fallback = (
            static_fallback
            if static_fallback is not None
            else document.static_fallback
        )
    else:
        resolved_policy = policy
        effective_catalog = (
            catalog if catalog is not None else DEFAULT_MODEL_CATALOG
        )
        effective_routes = (
            tier_routes if tier_routes is not None else TIER_ROUTES
        )
        effective_fallback = (
            static_fallback
            if static_fallback is not None
            else FEATURE_62_STATIC_FALLBACK
        )

    request = _normalise_request(request)
    if not isinstance(resolved_policy, AdaptivePolicy):
        raise PolicyValidationError(
            "policy must be an AdaptivePolicy or RuntimePolicyDocument"
        )
    _validate_bool(
        resolved_policy.customer_safe, "policy.customer_safe"
    )
    ensure_valid_policy(resolved_policy)
    customer_safe_required = (
        resolved_policy.customer_safe or request.customer_safe
    )
    if not isinstance(effective_catalog, ModelCatalog):
        raise PolicyValidationError("catalog must be a ModelCatalog")
    if not isinstance(effective_routes, Mapping):
        raise PolicyValidationError("tier_routes must be a mapping")
    if not isinstance(effective_fallback, StaticFallback):
        raise PolicyValidationError(
            "static_fallback must be a StaticFallback"
        )

    mode = resolve_mode(mode_override, resolved_policy.mode)
    tier = at_least_tier(
        resolved_policy.default_tier,
        *(() if request.tier is None else (request.tier,)),
        *(
            floor
            for floor in (
                request.assessment_minimum_tier,
                request.minimum_tier,
            )
            if floor is not None
        ),
    )

    if mode is PolicyMode.OFF:
        return PolicyResolution(
            resolved_policy.version,
            mode,
            tier,
            False,
            None,
            effective_fallback,
        )

    route = effective_routes.get(tier)
    if not isinstance(route, TierRoute) or route.tier is not tier:
        raise PolicyValidationError(
            f"no valid tier route configured for {tier.value}"
        )
    capability_floor = TIER_CAPABILITY_FLOOR[tier]
    required_effort = at_least_effort(
        TIER_EFFORT_FLOOR[tier],
        route.candidates[0].reasoning_effort,
        *(
            effort
            for effort in (request.required_reasoning_effort,)
            if effort is not None
        ),
    )
    if (
        request.reasoning_effort is not None
        and EFFORT_ORDER[request.reasoning_effort]
        < EFFORT_ORDER[required_effort]
    ):
        raise PolicyValidationError(
            f"reasoning_effort {request.reasoning_effort.value} is below "
            f"required minimum {required_effort.value}"
        )
    effort = request.reasoning_effort or required_effort

    if request.model_override is not None:
        if (
            resolved_policy.allow_model_overrides is not True
            or request.model_override
            not in resolved_policy.allowed_model_overrides
        ):
            raise PolicyValidationError(
                "model override is not approved by this policy"
            )
        candidate = ModelCandidate(
            request.model_override,
            effort,
            route.candidates[0].requirements,
        )
        if not capability_safe(
            candidate,
            effective_catalog,
            customer_safe_required=customer_safe_required,
            required_capability_tier=capability_floor,
        ):
            raise CapabilityUnavailableError(
                "explicit model override is unavailable or below the required "
                "capability tier, requirements, or reasoning effort"
            )
        record = effective_catalog.get(request.model_override)
        assert record is not None
        candidate = ModelCandidate(
            record.model_id, effort, candidate.requirements
        )
        source = "request_model_override"
    else:
        candidates = tuple(
            effective
            for item in route.candidates
            if (
                effective := _effective_candidate(
                    item,
                    request.reasoning_effort,
                    required_effort,
                )
            )
            is not None
        )
        candidate = resolve_candidate(
            candidates,
            effective_catalog,
            customer_safe_required=customer_safe_required,
            required_capability_tier=capability_floor,
        )
        source = (
            "request_reasoning_override"
            if request.reasoning_effort is not None
            else "tier_route"
        )

    selection = ResolvedSelection(
        candidate.model_id,
        candidate.reasoning_effort,
        tier,
        source,
    )
    requires_human_approval = (
        tier is ModelTier.HUMAN_GATE or route.requires_human_approval
    )
    if requires_human_approval and not request.human_approved:
        if mode is PolicyMode.OBSERVE:
            return PolicyResolution(
                resolved_policy.version,
                mode,
                tier,
                False,
                selection,
                human_approval_required=True,
            )
        raise HumanApprovalRequiredError(
            "human_gate tier requires explicit human_approved=true"
        )
    return PolicyResolution(
        resolved_policy.version,
        mode,
        tier,
        mode in (PolicyMode.GUARDED, PolicyMode.ENFORCE),
        selection,
    )
