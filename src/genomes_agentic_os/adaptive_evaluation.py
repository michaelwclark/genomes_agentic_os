"""Strict, privacy-safe Gate 3A evaluation for adaptive routing.

The evaluator is deliberately offline.  It assesses reviewed holdout tasks,
resolves plans against an explicitly supplied model catalog, and compares the
redacted recommendations with independently reviewed bounds, outcomes, and
static-baseline observations.  It never executes a plan and never emits task
text in a report.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode

from . import adaptive_router as _adaptive_router_module
from . import adaptive_topology as _adaptive_topology_module
from . import task_assessment as _task_assessment_module
from .adaptive_policy import (
    DEFAULT_MODEL_CATALOG,
    FEATURE_62_STATIC_FALLBACK,
    POLICY_VERSION,
    TIER_ROUTES,
    AdaptivePolicy,
    CostClass,
    ModelCatalog,
    ModelTier,
    PolicyLayers,
    PolicyMode,
    ReasoningEffort,
    RuntimePolicyDocument,
    TIER_ORDER,
    YAML_SCHEMA_VERSION as POLICY_SCHEMA_VERSION,
)
from .adaptive_router import OwnerCandidate, OwnerKind, PlanStatus, resolve_execution_plan
from .adaptive_topology import TopologyKind, build_topology
from .task_assessment import TaskAssessment, assess_task


EVALUATOR_VERSION = 2
EVALUATION_SCHEMA_VERSION = 2
FIXTURE_SCHEMA_VERSION = 2
BASELINE_SCHEMA_VERSION = 1

REQUIRED_TAXONOMY = frozenset(
    {
        "jira_grunt",
        "jira_status",
        "docs",
        "bounded_fix",
        "debugging",
        "cross_module_monolith",
        "migration",
        "security",
        "auth",
        "billing",
        "customer_data",
        "architecture",
        "production_planning",
        "infrastructure_release",
        "long_ci_watcher",
        "ambiguous",
        "adversarial",
    }
)

_OPAQUE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{1,255}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_COST_ORDER = {
    CostClass.ECONOMY: 0,
    CostClass.STANDARD: 1,
    CostClass.PREMIUM: 2,
}
_KNOWN_GATES = frozenset(
    {
        "change_review",
        "data_impact_review",
        "deployment_plan",
        "human_approval",
        "integration_tests",
        "migration_plan",
        "rollback_plan",
        "security_review",
        "targeted_tests",
        "tracker_readback",
    }
)
_KNOWN_ESCALATIONS = frozenset(
    {
        "adversarial_instruction",
        "approval_missing",
        "ci_failure",
        "data_impact_failure",
        "deployment_plan_failure",
        "design_conflict",
        "documentation_conflict",
        "integration_failure",
        "migration_failure",
        "reproduction_missing",
        "rollback_required",
        "root_cause_unknown",
        "scope_ambiguity",
        "security_review_failure",
        "source_ambiguity",
        "test_failure",
        "tracker_permission_denied",
        "tracker_readback_failure",
        "tracker_state_conflict",
        "tracker_write_rejected",
    }
)
_SAFETY_REASONS = frozenset(
    {
        "baseline_observation_mismatch",
        "below_minimum_safe_tier",
        "false_cheap_cost_class",
        "missing_human_approval_gate",
        "missing_required_gate",
        "no_selected_model_cost_class",
        "owner_mismatch",
        "reviewed_safety_mismatch",
        "route_status_invalid",
    }
)
_FINGERPRINT_KEYS = frozenset(
    {
        "policy_rules",
        "policy_config",
        "evaluated_catalog",
        "evaluator",
        "canonical_corpus",
        "evaluation_config",
        "reviewed_projection_root",
    }
)

_FIXTURE_FIELDS = frozenset(
    {
        "schema_version",
        "evaluator_version",
        "policy_version",
        "fingerprints",
        "catalog",
        "baseline",
        "thresholds",
        "cases",
    }
)
_CASE_FIELDS = frozenset(
    {
        "id",
        "taxonomy",
        "task",
        "provenance",
        "discovered_owner",
        "expected_owner",
        "minimum_safe_tier",
        "maximum_justified_tier",
        "required_gates",
        "expected_topology",
        "escalation_triggers",
        "observed_static_route",
        "reviewed_outcome",
    }
)
_PROVENANCE_FIELDS = frozenset({"review_status", "evidence_ref"})
_EXPECTED_OWNER_FIELDS = frozenset({"identifier", "kind"})
_DISCOVERED_OWNER_FIELDS = frozenset(
    {
        "identifier",
        "kind",
        "priority",
        "minimum_tier",
        "required_reasoning_effort",
    }
)
_BASELINE_FIELDS = frozenset(
    {"schema_version", "resolver_id", "resolver_version", "evidence_ref"}
)
_BASELINE_ROUTE_FIELDS = frozenset(
    {"outcome_category", "tier", "model_id", "cost_class", "evidence_ref"}
)
_REVIEWED_OUTCOME_FIELDS = frozenset({"quality", "safety", "evidence_ref"})
_THRESHOLD_FIELDS = frozenset(
    {
        "safety_violations",
        "false_cheap",
        "false_expensive",
        "quality_parity",
        "taxonomy_coverage",
        "repeated_run_stability",
    }
)
_MAX_THRESHOLD_FIELDS = frozenset({"max_count", "max_rate"})
_MIN_THRESHOLD_FIELDS = frozenset({"minimum_count", "minimum_rate"})

_REPORT_FIELDS = frozenset(
    {
        "schema_version",
        "evaluator_version",
        "policy_version",
        "mode",
        "fingerprints",
        "drift",
        "catalog",
        "baseline",
        "case_count",
        "cases",
        "metrics",
        "repeated_run_stability",
        "thresholds",
        "threshold_breaches",
        "guarded_mode",
    }
)
_REPORT_FINGERPRINT_FIELDS = frozenset({"reviewed", "evaluated"})
_REPORT_CASE_FIELDS = frozenset(
    {
        "id",
        "reviewed_case_fingerprint",
        "corpus_case_fingerprint",
        "facts_fingerprint",
        "taxonomy",
        "provenance",
        "assessment",
        "discovered_owner",
        "expected_owner",
        "observed_static_route",
        "resolved_static_route",
        "recommended_route",
        "expected_bounds",
        "reviewed_outcome",
        "derived",
        "safety_reasons",
    }
)
_ASSESSMENT_FIELDS = frozenset(
    {
        "schema_version",
        "task_family",
        "mutation_scope",
        "code_scope",
        "risk_flags",
        "uncertainty",
        "verification_needs",
        "context_depth",
        "expected_duration",
        "confidence",
        "minimum_tier",
        "human_gate",
        "evidence",
    }
)
_RECOMMENDED_ROUTE_FIELDS = frozenset(
    {
        "outcome_category",
        "tier",
        "model_id",
        "reasoning_effort",
        "selected_owner",
        "required_gates",
        "topology",
    }
)
_EXPECTED_BOUNDS_FIELDS = frozenset(
    {
        "minimum_safe_tier",
        "maximum_justified_tier",
        "required_gates",
        "expected_topology",
        "escalation_triggers",
    }
)
_DERIVED_FIELDS = frozenset(
    {
        "owner_match",
        "topology_match",
        "required_gates_match",
        "baseline_match",
        "route_status_valid",
        "within_minimum_safe_tier",
        "within_maximum_justified_tier",
        "selected_cost_class",
        "minimum_safe_cost_class",
        "maximum_justified_cost_class",
        "static_cost_class",
        "cost_eligible",
        "false_cheap",
        "more_expensive_than_maximum_justified",
        "more_expensive_than_static",
        "false_expensive",
        "cost_class_movement",
        "derived_quality_pass",
        "quality_parity_match",
        "reviewed_safety_match",
    }
)
_METRIC_FIELDS = frozenset(
    {
        "safety_violations",
        "false_cheap",
        "false_expensive",
        "quality_parity",
        "taxonomy_coverage",
        "projected_cost_class_movement",
    }
)
_COUNT_RATE_FIELDS = frozenset({"count", "eligible_count", "rate", "case_ids"})
_QUALITY_METRIC_FIELDS = frozenset(
    {"matched_count", "eligible_count", "rate", "mismatched_case_ids"}
)
_TAXONOMY_METRIC_FIELDS = frozenset(
    {"covered_count", "eligible_count", "rate", "counts", "missing"}
)
_MOVEMENT_METRIC_FIELDS = frozenset(
    {"eligible_count", "counts", "case_ids_by_movement"}
)
_STABILITY_FIELDS = frozenset({"runs", "matching_runs", "stable", "rate"})
_GUARDED_MODE_FIELDS = frozenset(
    {
        "decision",
        "would_go_with_explicit_approval",
        "explicit_approval_required",
        "approval_granted",
    }
)
_CATALOG_FIELDS = frozenset({"fingerprint", "snapshot"})
_CATALOG_SNAPSHOT_FIELDS = frozenset({"version", "models"})
_CATALOG_MODEL_FIELDS = frozenset(
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


class EvaluationValidationError(ValueError):
    """Raised when a fixture or report is not a reviewed evaluation contract."""


class ReviewStatus(str, Enum):
    REVIEWED = "reviewed"


class OutcomeState(str, Enum):
    PASS = "pass"
    FAIL = "fail"


class CostMovement(str, Enum):
    CHEAPER = "cheaper"
    SAME = "same"
    MORE_EXPENSIVE = "more_expensive"
    INELIGIBLE = "ineligible"


@dataclass(frozen=True, slots=True)
class BaselineRoute:
    """One typed, reviewed static-route observation."""

    outcome_category: PlanStatus
    tier: ModelTier
    model_id: str | None
    cost_class: CostClass | None
    evidence_ref: str

    def as_dict(self) -> dict[str, object]:
        return {
            "outcome_category": self.outcome_category.value,
            "tier": self.tier.value,
            "model_id": self.model_id,
            "cost_class": self.cost_class.value if self.cost_class else None,
            "evidence_ref": self.evidence_ref,
        }


class BaselineResolver(ABC):
    """Typed boundary for canonical static-baseline evidence."""

    resolver_id: str
    version: int

    @abstractmethod
    def resolve(
        self,
        *,
        case_id: str,
        reviewed_observation: BaselineRoute,
        catalog: ModelCatalog,
    ) -> BaselineRoute:
        """Resolve one canonical observation without receiving task text."""


@dataclass(frozen=True, slots=True)
class FixtureBaselineResolver(BaselineResolver):
    """Resolve the reviewed fixture's canonical static observation."""

    resolver_id: str
    version: int

    def __post_init__(self) -> None:
        _require_opaque_id(self.resolver_id, "baseline resolver_id")
        _require_int(self.version, "baseline resolver_version", minimum=1)

    @classmethod
    def from_fixture(cls, fixture: Mapping[str, object]) -> "FixtureBaselineResolver":
        baseline = _require_mapping(fixture.get("baseline"), "fixture.baseline")
        return cls(
            _require_opaque_id(baseline.get("resolver_id"), "fixture.baseline.resolver_id"),
            _require_int(
                baseline.get("resolver_version"),
                "fixture.baseline.resolver_version",
                minimum=1,
            ),
        )

    def resolve(
        self,
        *,
        case_id: str,
        reviewed_observation: BaselineRoute,
        catalog: ModelCatalog,
    ) -> BaselineRoute:
        del case_id, catalog
        if not isinstance(reviewed_observation, BaselineRoute):
            raise EvaluationValidationError("reviewed baseline must be a BaselineRoute")
        return reviewed_observation


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate keys at every depth."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader, node: MappingNode, deep: bool = False
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
                "found an unhashable mapping key",
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


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise EvaluationValidationError(f"{name} must be a mapping with string keys")
    return value


def _require_exact_keys(
    value: Mapping[str, object], required: frozenset[str], name: str
) -> None:
    missing = required - set(value)
    unknown = set(value) - required
    if missing or unknown:
        details = []
        if missing:
            details.append(f"missing {sorted(missing)!r}")
        if unknown:
            details.append(f"unknown {sorted(unknown)!r}")
        raise EvaluationValidationError(f"{name} schema mismatch: {'; '.join(details)}")


def _require_int(
    value: object, name: str, *, minimum: int | None = None, expected: int | None = None
) -> int:
    if type(value) is not int:
        raise EvaluationValidationError(f"{name} must be an exact integer")
    if minimum is not None and value < minimum:
        raise EvaluationValidationError(f"{name} must be at least {minimum}")
    if expected is not None and value != expected:
        raise EvaluationValidationError(f"{name} must equal {expected}")
    return value


def _require_float(
    value: object,
    name: str,
    *,
    minimum: float = 0.0,
    maximum: float = 1.0,
) -> float:
    if type(value) is not float:
        raise EvaluationValidationError(f"{name} must be an exact float")
    if not minimum <= value <= maximum:
        raise EvaluationValidationError(
            f"{name} must be within [{minimum}, {maximum}]"
        )
    return value


def _require_bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise EvaluationValidationError(f"{name} must be a bool")
    return value


def _require_opaque_id(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or not _OPAQUE_ID.fullmatch(value):
        raise EvaluationValidationError(f"{name} must be a nonblank opaque identifier")
    return value


def _require_sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise EvaluationValidationError(f"{name} must be a lowercase SHA-256 fingerprint")
    return value


def _require_enum(value: object, enum_type: type[Enum], name: str) -> Enum:
    if not isinstance(value, str):
        raise EvaluationValidationError(f"{name} must be a supported {enum_type.__name__}")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise EvaluationValidationError(
            f"{name} must be a supported {enum_type.__name__}"
        ) from exc


def _require_unique_enum_list(
    value: object, allowed: frozenset[str], name: str, *, nonempty: bool = False
) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value):
        raise EvaluationValidationError(f"{name} must be a{' non-empty' if nonempty else ''} list")
    if any(not isinstance(item, str) or item not in allowed for item in value):
        raise EvaluationValidationError(f"{name} contains an unsupported value")
    if len(value) != len(set(value)):
        raise EvaluationValidationError(f"{name} must contain unique values")
    return value


def _require_unique_opaque_list(value: object, name: str) -> list[str]:
    if not isinstance(value, list):
        raise EvaluationValidationError(f"{name} must be a list")
    result = [_require_opaque_id(item, f"{name} item") for item in value]
    if len(result) != len(set(result)):
        raise EvaluationValidationError(f"{name} must contain unique values")
    return result


def catalog_snapshot(catalog: ModelCatalog) -> dict[str, object]:
    """Return the complete supplied catalog contract; no provider is queried."""
    if not isinstance(catalog, ModelCatalog):
        raise EvaluationValidationError("catalog must be explicitly supplied as ModelCatalog")
    models = []
    for record in sorted(catalog.records, key=lambda item: item.model_id):
        models.append(
            {
                "model_id": record.model_id,
                "aliases": sorted(record.aliases),
                "capability_tier": record.capability_tier.value,
                "supported_reasoning_efforts": [
                    item.value for item in record.supported_reasoning_efforts
                ],
                "coding": record.coding,
                "tool_use": record.tool_use,
                "context_tokens": record.context_tokens,
                "subagent_suitable": record.subagent_suitable,
                "cost_class": record.cost_class.value,
                "customer_safe": record.customer_safe,
                "available": record.available,
            }
        )
    return {"version": catalog.version, "models": models}


def catalog_fingerprint(catalog: ModelCatalog) -> str:
    return _sha256(catalog_snapshot(catalog))


def _source_fingerprint(module: Any) -> str:
    source_path = Path(module.__file__)
    return hashlib.sha256(source_path.read_bytes()).hexdigest()


def policy_rules_fingerprint() -> str:
    """Fingerprint assessment, routing, and topology rule implementations."""
    return _sha256(
        {
            "policy_version": POLICY_VERSION,
            "task_assessment": _source_fingerprint(_task_assessment_module),
            "adaptive_router": _source_fingerprint(_adaptive_router_module),
            "adaptive_topology": _source_fingerprint(_adaptive_topology_module),
        }
    )


def _requirements_snapshot(requirements: object) -> dict[str, object]:
    return {
        "coding": getattr(requirements, "coding"),
        "tool_use": getattr(requirements, "tool_use"),
        "min_context_tokens": getattr(requirements, "min_context_tokens"),
        "subagent_suitable": getattr(requirements, "subagent_suitable"),
    }


def policy_config_snapshot() -> dict[str, object]:
    routes: dict[str, object] = {}
    for tier in sorted(TIER_ROUTES, key=TIER_ORDER.__getitem__):
        route = TIER_ROUTES[tier]
        routes[tier.value] = {
            "requires_human_approval": route.requires_human_approval,
            "candidates": [
                {
                    "model": candidate.model_id,
                    "reasoning_effort": candidate.reasoning_effort.value,
                    "requirements": _requirements_snapshot(candidate.requirements),
                }
                for candidate in route.candidates
            ],
        }
    return {
        "policy_schema_version": POLICY_SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "evaluation_policy": {
            "mode": PolicyMode.OBSERVE.value,
            "default_tier": ModelTier.ECONOMY.value,
            "customer_safe": True,
            "allow_model_overrides": False,
            "allowed_model_overrides": [],
        },
        "tier_routes": routes,
        "static_fallback": {
            "feature": FEATURE_62_STATIC_FALLBACK.feature,
            "behavior": FEATURE_62_STATIC_FALLBACK.behavior,
        },
    }


def policy_config_fingerprint() -> str:
    return _sha256(policy_config_snapshot())


def evaluator_fingerprint() -> str:
    """Fingerprint the versioned evaluator schema, not mutable fixture data."""
    return _sha256(
        {
            "evaluator_version": EVALUATOR_VERSION,
            "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
            "fixture_schema_version": FIXTURE_SCHEMA_VERSION,
            "baseline_schema_version": BASELINE_SCHEMA_VERSION,
            "required_taxonomy": sorted(REQUIRED_TAXONOMY),
            "fixture_fields": sorted(_FIXTURE_FIELDS),
            "case_fields": sorted(_CASE_FIELDS),
            "report_fields": sorted(_REPORT_FIELDS),
            "report_case_fields": sorted(_REPORT_CASE_FIELDS),
            "threshold_fields": sorted(_THRESHOLD_FIELDS),
        }
    )


def case_fingerprint(case: Mapping[str, object]) -> str:
    return _sha256(case)


def corpus_fingerprint(cases: Sequence[Mapping[str, object]]) -> str:
    """Commit to every complete case, including task text and review evidence."""
    return _sha256([case_fingerprint(case) for case in cases])


def evaluation_config_fingerprint(thresholds: Mapping[str, object]) -> str:
    """Commit guarded-mode thresholds to the reviewed evaluation config."""
    return _sha256(_require_mapping(thresholds, "thresholds"))


def _reviewed_projection_fingerprint(case: Mapping[str, object]) -> str:
    """Bind every reviewed, redacted case fact used to judge the route."""
    return _sha256(
        {
            key: case[key]
            for key in (
                "id",
                "corpus_case_fingerprint",
                "taxonomy",
                "provenance",
                "discovered_owner",
                "expected_owner",
                "observed_static_route",
                "expected_bounds",
                "reviewed_outcome",
            )
        }
    )


def reviewed_projection_root(cases: Sequence[Mapping[str, object]]) -> str:
    """Commit the reviewed redacted projection independently of derived facts."""
    fingerprints: list[str] = []
    for case in cases:
        projection = {
            "id": case["id"],
            "corpus_case_fingerprint": case_fingerprint(case),
            "taxonomy": sorted(case["taxonomy"]),
            "provenance": dict(_require_mapping(case["provenance"], "provenance")),
            "discovered_owner": case["discovered_owner"],
            "expected_owner": case["expected_owner"],
            "observed_static_route": dict(
                _require_mapping(case["observed_static_route"], "observed_static_route")
            ),
            "expected_bounds": {
                "minimum_safe_tier": case["minimum_safe_tier"],
                "maximum_justified_tier": case["maximum_justified_tier"],
                "required_gates": sorted(case["required_gates"]),
                "expected_topology": case["expected_topology"],
                "escalation_triggers": sorted(case["escalation_triggers"]),
            },
            "reviewed_outcome": dict(
                _require_mapping(case["reviewed_outcome"], "reviewed_outcome")
            ),
        }
        fingerprints.append(_sha256(projection))
    return _sha256(fingerprints)


def _facts_fingerprint(case: Mapping[str, object]) -> str:
    return _sha256({key: value for key, value in case.items() if key != "facts_fingerprint"})


def load_holdout_fixture(path: str | Path) -> dict[str, object]:
    """Load YAML with duplicate-key rejection, then validate the full fixture."""
    try:
        raw = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except (OSError, yaml.YAMLError) as exc:
        raise EvaluationValidationError(f"unable to load evaluation fixture: {exc}") from exc
    fixture = _require_mapping(raw, "fixture")
    validate_fixture(fixture)
    return dict(fixture)


def _validate_catalog_snapshot(snapshot: object, name: str) -> Mapping[str, object]:
    result = _require_mapping(snapshot, name)
    _require_exact_keys(result, _CATALOG_SNAPSHOT_FIELDS, name)
    _require_int(result["version"], f"{name}.version", minimum=1)
    models = result["models"]
    if not isinstance(models, list) or not models:
        raise EvaluationValidationError(f"{name}.models must be a non-empty list")
    references: set[str] = set()
    model_ids: set[str] = set()
    for index, raw_model in enumerate(models):
        section = f"{name}.models[{index}]"
        model = _require_mapping(raw_model, section)
        _require_exact_keys(model, _CATALOG_MODEL_FIELDS, section)
        model_id = _require_opaque_id(model["model_id"], f"{section}.model_id")
        if model_id in model_ids:
            raise EvaluationValidationError(f"{name} contains duplicate model ids")
        model_ids.add(model_id)
        aliases = _require_unique_opaque_list(model["aliases"], f"{section}.aliases")
        for reference in (model_id, *aliases):
            if reference in references:
                raise EvaluationValidationError(f"{name} contains duplicate model references")
            references.add(reference)
        if model["capability_tier"] not in {"economy", "balanced", "frontier"}:
            raise EvaluationValidationError(f"{section}.capability_tier is unsupported")
        _require_unique_enum_list(
            model["supported_reasoning_efforts"],
            frozenset(item.value for item in ReasoningEffort),
            f"{section}.supported_reasoning_efforts",
            nonempty=True,
        )
        for field in (
            "coding",
            "tool_use",
            "subagent_suitable",
            "customer_safe",
            "available",
        ):
            _require_bool(model[field], f"{section}.{field}")
        _require_int(model["context_tokens"], f"{section}.context_tokens", minimum=1)
        _require_enum(model["cost_class"], CostClass, f"{section}.cost_class")
    return result


def _snapshot_model(snapshot: Mapping[str, object], reference: str) -> Mapping[str, object] | None:
    for raw_model in snapshot["models"]:  # validated by _validate_catalog_snapshot
        model = _require_mapping(raw_model, "catalog model")
        if reference == model["model_id"] or reference in model["aliases"]:
            return model
    return None


def _validate_fingerprints(value: object, name: str) -> Mapping[str, object]:
    fingerprints = _require_mapping(value, name)
    _require_exact_keys(fingerprints, _FINGERPRINT_KEYS, name)
    for key in sorted(_FINGERPRINT_KEYS):
        _require_sha256(fingerprints[key], f"{name}.{key}")
    return fingerprints


def _validate_thresholds(value: object, name: str) -> Mapping[str, object]:
    thresholds = _require_mapping(value, name)
    _require_exact_keys(thresholds, _THRESHOLD_FIELDS, name)
    for metric in ("safety_violations", "false_cheap", "false_expensive"):
        section = _require_mapping(thresholds[metric], f"{name}.{metric}")
        _require_exact_keys(section, _MAX_THRESHOLD_FIELDS, f"{name}.{metric}")
        _require_int(section["max_count"], f"{name}.{metric}.max_count", minimum=0)
        _require_float(section["max_rate"], f"{name}.{metric}.max_rate")
    for metric in (
        "quality_parity",
        "taxonomy_coverage",
        "repeated_run_stability",
    ):
        section = _require_mapping(thresholds[metric], f"{name}.{metric}")
        _require_exact_keys(section, _MIN_THRESHOLD_FIELDS, f"{name}.{metric}")
        _require_int(
            section["minimum_count"], f"{name}.{metric}.minimum_count", minimum=0
        )
        _require_float(section["minimum_rate"], f"{name}.{metric}.minimum_rate")
    safety = _require_mapping(thresholds["safety_violations"], "safety threshold")
    if safety["max_count"] != 0 or safety["max_rate"] != 0.0:
        raise EvaluationValidationError("safety thresholds must allow zero violations")
    return thresholds


def _validate_provenance(value: object, name: str) -> Mapping[str, object]:
    provenance = _require_mapping(value, name)
    _require_exact_keys(provenance, _PROVENANCE_FIELDS, name)
    _require_enum(provenance["review_status"], ReviewStatus, f"{name}.review_status")
    _require_opaque_id(provenance["evidence_ref"], f"{name}.evidence_ref")
    return provenance


def _validate_expected_owner(value: object, name: str) -> Mapping[str, object] | None:
    if value is None:
        return None
    owner = _require_mapping(value, name)
    _require_exact_keys(owner, _EXPECTED_OWNER_FIELDS, name)
    _require_opaque_id(owner["identifier"], f"{name}.identifier")
    _require_enum(owner["kind"], OwnerKind, f"{name}.kind")
    return owner


def _validate_discovered_owner(value: object, name: str) -> Mapping[str, object] | None:
    if value is None:
        return None
    owner = _require_mapping(value, name)
    _require_exact_keys(owner, _DISCOVERED_OWNER_FIELDS, name)
    _require_opaque_id(owner["identifier"], f"{name}.identifier")
    _require_enum(owner["kind"], OwnerKind, f"{name}.kind")
    _require_int(owner["priority"], f"{name}.priority", minimum=0)
    if owner["minimum_tier"] is not None:
        _require_enum(owner["minimum_tier"], ModelTier, f"{name}.minimum_tier")
    if owner["required_reasoning_effort"] is not None:
        _require_enum(
            owner["required_reasoning_effort"],
            ReasoningEffort,
            f"{name}.required_reasoning_effort",
        )
    return owner


def _validate_baseline_route(
    value: object,
    name: str,
    catalog: Mapping[str, object] | None = None,
) -> BaselineRoute:
    route = _require_mapping(value, name)
    _require_exact_keys(route, _BASELINE_ROUTE_FIELDS, name)
    outcome = _require_enum(
        route["outcome_category"], PlanStatus, f"{name}.outcome_category"
    )
    tier = _require_enum(route["tier"], ModelTier, f"{name}.tier")
    model_id = route["model_id"]
    cost_value = route["cost_class"]
    if (model_id is None) != (cost_value is None):
        raise EvaluationValidationError(
            f"{name}.model_id and cost_class must both be null or both be present"
        )
    parsed_cost: CostClass | None = None
    if model_id is not None:
        model_id = _require_opaque_id(model_id, f"{name}.model_id")
        parsed_cost = _require_enum(cost_value, CostClass, f"{name}.cost_class")  # type: ignore[assignment]
        if catalog is not None:
            model = _snapshot_model(catalog, model_id)
            if model is None:
                raise EvaluationValidationError(f"{name}.model_id is absent from catalog")
            if model["cost_class"] != parsed_cost.value:
                raise EvaluationValidationError(f"{name}.cost_class mismatches catalog")
    evidence_ref = _require_opaque_id(route["evidence_ref"], f"{name}.evidence_ref")
    return BaselineRoute(
        outcome,  # type: ignore[arg-type]
        tier,  # type: ignore[arg-type]
        model_id,  # type: ignore[arg-type]
        parsed_cost,
        evidence_ref,
    )


def _validate_reviewed_outcome(value: object, name: str) -> Mapping[str, object]:
    outcome = _require_mapping(value, name)
    _require_exact_keys(outcome, _REVIEWED_OUTCOME_FIELDS, name)
    _require_enum(outcome["quality"], OutcomeState, f"{name}.quality")
    _require_enum(outcome["safety"], OutcomeState, f"{name}.safety")
    _require_opaque_id(outcome["evidence_ref"], f"{name}.evidence_ref")
    return outcome


def _taxonomy_semantically_matches(label: str, assessment: TaskAssessment) -> bool:
    risks = set(assessment.risk_flags)
    evidence = set(assessment.evidence)
    predicates = {
        "jira_grunt": assessment.task_family == "simple_jira_grunt_work",
        "jira_status": assessment.mutation_scope == "tracker_update",
        "docs": assessment.task_family == "general_task"
        and assessment.code_scope == "none"
        and not risks,
        "bounded_fix": assessment.task_family == "bounded_code_change",
        "debugging": assessment.task_family == "bounded_code_change",
        "cross_module_monolith": assessment.task_family == "cross_module_monolith",
        "migration": "migration" in risks,
        "security": "auth_security" in risks,
        "auth": "auth_security" in risks,
        "billing": "billing" in risks,
        "customer_data": "customer_data" in risks,
        "architecture": assessment.task_family == "cross_module_monolith",
        "production_planning": "production" in risks,
        "infrastructure_release": bool({"infrastructure", "release"}.intersection(risks)),
        "long_ci_watcher": assessment.task_family in {"general_task", "bounded_code_change"}
        and assessment.human_gate is False,
        "ambiguous": assessment.uncertainty in {"medium", "high"},
        "adversarial": "adversarial_instruction_detected" in evidence,
    }
    return predicates[label]


def _validate_case(
    raw_case: object,
    index: int,
    catalog: Mapping[str, object],
) -> tuple[Mapping[str, object], TaskAssessment]:
    name = f"fixture.cases[{index}]"
    case = _require_mapping(raw_case, name)
    _require_exact_keys(case, _CASE_FIELDS, name)
    _require_opaque_id(case["id"], f"{name}.id")
    taxonomy = _require_unique_enum_list(
        case["taxonomy"], REQUIRED_TAXONOMY, f"{name}.taxonomy", nonempty=True
    )
    task = case["task"]
    if not isinstance(task, str) or not task.strip():
        raise EvaluationValidationError(f"{name}.task must be nonblank evaluation-only text")
    assessment = assess_task(task)
    for label in taxonomy:
        if not _taxonomy_semantically_matches(label, assessment):
            raise EvaluationValidationError(
                f"{name}.taxonomy label {label!r} does not match assessed task semantics"
            )
    _validate_provenance(case["provenance"], f"{name}.provenance")
    _validate_discovered_owner(case["discovered_owner"], f"{name}.discovered_owner")
    _validate_expected_owner(case["expected_owner"], f"{name}.expected_owner")
    minimum = _require_enum(case["minimum_safe_tier"], ModelTier, f"{name}.minimum_safe_tier")
    maximum = _require_enum(
        case["maximum_justified_tier"], ModelTier, f"{name}.maximum_justified_tier"
    )
    if TIER_ORDER[minimum] > TIER_ORDER[maximum]:  # type: ignore[index]
        raise EvaluationValidationError(
            f"{name}.minimum_safe_tier cannot exceed maximum_justified_tier"
        )
    _require_unique_enum_list(case["required_gates"], _KNOWN_GATES, f"{name}.required_gates")
    _require_enum(case["expected_topology"], TopologyKind, f"{name}.expected_topology")
    _require_unique_enum_list(
        case["escalation_triggers"],
        _KNOWN_ESCALATIONS,
        f"{name}.escalation_triggers",
    )
    _validate_baseline_route(
        case["observed_static_route"], f"{name}.observed_static_route", catalog
    )
    _validate_reviewed_outcome(case["reviewed_outcome"], f"{name}.reviewed_outcome")
    return case, assessment


def validate_fixture(fixture: Mapping[str, object]) -> None:
    """Fail closed on malformed, drifted, or unreviewed corpus evidence."""
    fixture = _require_mapping(fixture, "fixture")
    _require_exact_keys(fixture, _FIXTURE_FIELDS, "fixture")
    _require_int(
        fixture["schema_version"],
        "fixture.schema_version",
        expected=FIXTURE_SCHEMA_VERSION,
    )
    _require_int(
        fixture["evaluator_version"],
        "fixture.evaluator_version",
        expected=EVALUATOR_VERSION,
    )
    _require_int(
        fixture["policy_version"],
        "fixture.policy_version",
        expected=POLICY_VERSION,
    )
    fingerprints = _validate_fingerprints(fixture["fingerprints"], "fixture.fingerprints")
    catalog_section = _require_mapping(fixture["catalog"], "fixture.catalog")
    _require_exact_keys(catalog_section, _CATALOG_FIELDS, "fixture.catalog")
    snapshot = _validate_catalog_snapshot(catalog_section["snapshot"], "fixture.catalog.snapshot")
    catalog_pin = _require_sha256(catalog_section["fingerprint"], "fixture.catalog.fingerprint")
    if catalog_pin != _sha256(snapshot):
        raise EvaluationValidationError("fixture catalog fingerprint does not match snapshot")
    if fingerprints["evaluated_catalog"] != catalog_pin:
        raise EvaluationValidationError("fixture evaluated_catalog fingerprint is inconsistent")
    baseline = _require_mapping(fixture["baseline"], "fixture.baseline")
    _require_exact_keys(baseline, _BASELINE_FIELDS, "fixture.baseline")
    _require_int(
        baseline["schema_version"],
        "fixture.baseline.schema_version",
        expected=BASELINE_SCHEMA_VERSION,
    )
    _require_opaque_id(baseline["resolver_id"], "fixture.baseline.resolver_id")
    _require_int(baseline["resolver_version"], "fixture.baseline.resolver_version", minimum=1)
    _require_opaque_id(baseline["evidence_ref"], "fixture.baseline.evidence_ref")
    thresholds = _validate_thresholds(fixture["thresholds"], "fixture.thresholds")
    cases = fixture["cases"]
    if not isinstance(cases, list) or len(cases) < 50:
        raise EvaluationValidationError("fixture must contain at least 50 cases")
    identifiers: set[str] = set()
    coverage: set[str] = set()
    for index, raw_case in enumerate(cases):
        case, _ = _validate_case(raw_case, index, snapshot)
        identifier = str(case["id"])
        if identifier in identifiers:
            raise EvaluationValidationError("fixture case ids must be unique")
        identifiers.add(identifier)
        coverage.update(case["taxonomy"])  # type: ignore[arg-type]
    if coverage != REQUIRED_TAXONOMY:
        raise EvaluationValidationError(
            f"fixture taxonomy coverage mismatch: missing {sorted(REQUIRED_TAXONOMY - coverage)!r}"
        )
    if fingerprints["canonical_corpus"] != corpus_fingerprint(cases):
        raise EvaluationValidationError("fixture canonical corpus fingerprint mismatch")
    if fingerprints["evaluation_config"] != evaluation_config_fingerprint(thresholds):
        raise EvaluationValidationError("fixture evaluation config fingerprint mismatch")
    if fingerprints["reviewed_projection_root"] != reviewed_projection_root(cases):
        raise EvaluationValidationError("fixture reviewed projection root mismatch")
    expected_pins = {
        "policy_rules": policy_rules_fingerprint(),
        "policy_config": policy_config_fingerprint(),
        "evaluator": evaluator_fingerprint(),
    }
    for key, expected in expected_pins.items():
        if fingerprints[key] != expected:
            raise EvaluationValidationError(f"fixture {key} fingerprint drifted")
    quality_threshold = _require_mapping(thresholds["quality_parity"], "quality threshold")
    taxonomy_threshold = _require_mapping(
        thresholds["taxonomy_coverage"], "taxonomy threshold"
    )
    if quality_threshold["minimum_count"] > len(cases):
        raise EvaluationValidationError("quality minimum_count exceeds corpus size")
    if taxonomy_threshold["minimum_count"] > len(REQUIRED_TAXONOMY):
        raise EvaluationValidationError("taxonomy minimum_count exceeds taxonomy size")


def _owner_candidate(value: object) -> OwnerCandidate | None:
    if value is None:
        return None
    owner = _require_mapping(value, "discovered_owner")
    return OwnerCandidate(
        identifier=str(owner["identifier"]),
        kind=str(owner["kind"]),
        priority=int(owner["priority"]),
        minimum_tier=owner["minimum_tier"],  # type: ignore[arg-type]
        required_reasoning_effort=owner["required_reasoning_effort"],  # type: ignore[arg-type]
    )


def _owner_dict(owner: OwnerCandidate | None) -> dict[str, object] | None:
    if owner is None:
        return None
    return {"identifier": owner.identifier, "kind": owner.kind.value}


def _evaluation_policy(catalog: ModelCatalog) -> RuntimePolicyDocument:
    policy = AdaptivePolicy(mode=PolicyMode.OBSERVE, default_tier=ModelTier.ECONOMY)
    return RuntimePolicyDocument(
        schema_version=POLICY_SCHEMA_VERSION,
        policy_version=POLICY_VERSION,
        layers=PolicyLayers(),
        policy=policy,
        catalog=catalog,
        tier_routes=TIER_ROUTES,
        static_fallback=FEATURE_62_STATIC_FALLBACK,
    )


def _reviewed_catalog_cost_for_tier(
    tier: ModelTier, snapshot: Mapping[str, object]
) -> CostClass:
    route = TIER_ROUTES[tier]
    for candidate in route.candidates:
        model = _snapshot_model(snapshot, candidate.model_id)
        if model is not None:
            return CostClass(str(model["cost_class"]))
    raise EvaluationValidationError(f"reviewed catalog cannot price class for tier {tier.value}")


def _movement(selected: CostClass | None, static: CostClass | None) -> CostMovement:
    if selected is None or static is None:
        return CostMovement.INELIGIBLE
    delta = _COST_ORDER[selected] - _COST_ORDER[static]
    if delta < 0:
        return CostMovement.CHEAPER
    if delta > 0:
        return CostMovement.MORE_EXPENSIVE
    return CostMovement.SAME


def _status_contract_valid(status: PlanStatus, tier: ModelTier) -> bool:
    if tier is ModelTier.HUMAN_GATE:
        return status is PlanStatus.HUMAN_APPROVAL_REQUIRED
    return status is PlanStatus.READY


def _evaluate_case(
    case: Mapping[str, object],
    *,
    policy: RuntimePolicyDocument,
    catalog: ModelCatalog,
    reviewed_catalog: Mapping[str, object],
    baseline_resolver: BaselineResolver,
) -> dict[str, object]:
    discovered = _owner_candidate(case["discovered_owner"])
    plan = resolve_execution_plan(
        str(case["task"]),
        policy,
        owner_candidates=() if discovered is None else (discovered,),
    )
    topology = build_topology(plan)
    required_gates = sorted(set(plan.required_verification) | set(plan.required_approvals))
    actual_owner = _owner_dict(plan.selected_owner)
    expected_owner = case["expected_owner"]
    reviewed_static = _validate_baseline_route(
        case["observed_static_route"], "case.observed_static_route", reviewed_catalog
    )
    resolved_static = baseline_resolver.resolve(
        case_id=str(case["id"]),
        reviewed_observation=reviewed_static,
        catalog=catalog,
    )
    if not isinstance(resolved_static, BaselineRoute):
        raise EvaluationValidationError("baseline resolver must return BaselineRoute")
    minimum = ModelTier(str(case["minimum_safe_tier"]))
    maximum = ModelTier(str(case["maximum_justified_tier"]))
    selected_record = catalog.get(plan.model_id) if plan.model_id else None
    selected_cost = selected_record.cost_class if selected_record else None
    minimum_cost = _reviewed_catalog_cost_for_tier(minimum, reviewed_catalog)
    maximum_cost = _reviewed_catalog_cost_for_tier(maximum, reviewed_catalog)
    static_cost = reviewed_static.cost_class
    cost_eligible = selected_cost is not None and static_cost is not None
    owner_match = actual_owner == expected_owner
    topology_match = topology.kind.value == case["expected_topology"]
    gates_match = set(case["required_gates"]).issubset(required_gates)  # type: ignore[arg-type]
    baseline_match = resolved_static == reviewed_static
    status_valid = _status_contract_valid(plan.status, plan.model_tier)
    within_minimum = TIER_ORDER[plan.model_tier] >= TIER_ORDER[minimum]
    within_maximum = TIER_ORDER[plan.model_tier] <= TIER_ORDER[maximum]
    false_cheap = bool(
        selected_cost is not None
        and _COST_ORDER[selected_cost] < _COST_ORDER[minimum_cost]
    )
    more_expensive_max = bool(
        selected_cost is not None
        and _COST_ORDER[selected_cost] > _COST_ORDER[maximum_cost]
    )
    more_expensive_static = bool(
        selected_cost is not None
        and static_cost is not None
        and _COST_ORDER[selected_cost] > _COST_ORDER[static_cost]
    )
    false_expensive = more_expensive_max or more_expensive_static
    safety_reasons: list[str] = []
    if not baseline_match:
        safety_reasons.append("baseline_observation_mismatch")
    if not within_minimum:
        safety_reasons.append("below_minimum_safe_tier")
    if false_cheap:
        safety_reasons.append("false_cheap_cost_class")
    if not gates_match:
        safety_reasons.append("missing_required_gate")
    if plan.model_tier is ModelTier.HUMAN_GATE and "human_approval" not in required_gates:
        safety_reasons.append("missing_human_approval_gate")
    if not cost_eligible:
        safety_reasons.append("no_selected_model_cost_class")
    if not owner_match:
        safety_reasons.append("owner_mismatch")
    if not status_valid:
        safety_reasons.append("route_status_invalid")
    core_safe = not safety_reasons
    reviewed_outcome = _require_mapping(case["reviewed_outcome"], "reviewed_outcome")
    reviewed_safety_pass = reviewed_outcome["safety"] == OutcomeState.PASS.value
    reviewed_safety_match = core_safe == reviewed_safety_pass
    if not reviewed_safety_match:
        safety_reasons.append("reviewed_safety_mismatch")
    derived_quality_pass = bool(
        core_safe
        and topology_match
        and within_maximum
        and not false_expensive
    )
    reviewed_quality_pass = reviewed_outcome["quality"] == OutcomeState.PASS.value
    quality_match = derived_quality_pass == reviewed_quality_pass
    assessment = plan.assessment.as_dict()
    result: dict[str, object] = {
        "id": case["id"],
        "corpus_case_fingerprint": case_fingerprint(case),
        "reviewed_case_fingerprint": "",
        "facts_fingerprint": "",
        "taxonomy": sorted(case["taxonomy"]),
        "provenance": dict(_require_mapping(case["provenance"], "provenance")),
        "assessment": assessment,
        "discovered_owner": case["discovered_owner"],
        "expected_owner": expected_owner,
        "observed_static_route": reviewed_static.as_dict(),
        "resolved_static_route": resolved_static.as_dict(),
        "recommended_route": {
            "outcome_category": plan.status.value,
            "tier": plan.model_tier.value,
            "model_id": plan.model_id,
            "reasoning_effort": (
                plan.reasoning_effort.value if plan.reasoning_effort else None
            ),
            "selected_owner": actual_owner,
            "required_gates": required_gates,
            "topology": topology.kind.value,
        },
        "expected_bounds": {
            "minimum_safe_tier": minimum.value,
            "maximum_justified_tier": maximum.value,
            "required_gates": sorted(case["required_gates"]),
            "expected_topology": case["expected_topology"],
            "escalation_triggers": sorted(case["escalation_triggers"]),
        },
        "reviewed_outcome": dict(reviewed_outcome),
        "derived": {
            "owner_match": owner_match,
            "topology_match": topology_match,
            "required_gates_match": gates_match,
            "baseline_match": baseline_match,
            "route_status_valid": status_valid,
            "within_minimum_safe_tier": within_minimum,
            "within_maximum_justified_tier": within_maximum,
            "selected_cost_class": selected_cost.value if selected_cost else None,
            "minimum_safe_cost_class": minimum_cost.value,
            "maximum_justified_cost_class": maximum_cost.value,
            "static_cost_class": static_cost.value if static_cost else None,
            "cost_eligible": cost_eligible,
            "false_cheap": false_cheap,
            "more_expensive_than_maximum_justified": more_expensive_max,
            "more_expensive_than_static": more_expensive_static,
            "false_expensive": false_expensive,
            "cost_class_movement": _movement(selected_cost, static_cost).value,
            "derived_quality_pass": derived_quality_pass,
            "quality_parity_match": quality_match,
            "reviewed_safety_match": reviewed_safety_match,
        },
        "safety_reasons": sorted(safety_reasons),
    }
    result["reviewed_case_fingerprint"] = _reviewed_projection_fingerprint(result)
    result["facts_fingerprint"] = _facts_fingerprint(result)
    return result


def _count_rate_metric(cases: list[Mapping[str, object]], fact: str) -> dict[str, object]:
    eligible = [case for case in cases if bool(_require_mapping(case["derived"], "derived")["cost_eligible"])]
    case_ids = [
        str(case["id"])
        for case in eligible
        if bool(_require_mapping(case["derived"], "derived")[fact])
    ]
    denominator = len(eligible)
    return {
        "count": len(case_ids),
        "eligible_count": denominator,
        "rate": len(case_ids) / denominator if denominator else 0.0,
        "case_ids": case_ids,
    }


def _compute_metrics(cases: list[Mapping[str, object]]) -> dict[str, object]:
    safety_ids = [str(case["id"]) for case in cases if case["safety_reasons"]]
    safety = {
        "count": len(safety_ids),
        "eligible_count": len(cases),
        "rate": len(safety_ids) / len(cases) if cases else 0.0,
        "case_ids": safety_ids,
    }
    false_cheap = _count_rate_metric(cases, "false_cheap")
    false_expensive = _count_rate_metric(cases, "false_expensive")
    quality_mismatches = [
        str(case["id"])
        for case in cases
        if not bool(_require_mapping(case["derived"], "derived")["quality_parity_match"])
    ]
    quality_matched = len(cases) - len(quality_mismatches)
    quality = {
        "matched_count": quality_matched,
        "eligible_count": len(cases),
        "rate": quality_matched / len(cases) if cases else 0.0,
        "mismatched_case_ids": quality_mismatches,
    }
    taxonomy_counts = Counter(item for case in cases for item in case["taxonomy"])
    covered = set(taxonomy_counts)
    taxonomy = {
        "covered_count": len(covered),
        "eligible_count": len(REQUIRED_TAXONOMY),
        "rate": len(covered) / len(REQUIRED_TAXONOMY),
        "counts": dict(sorted(taxonomy_counts.items())),
        "missing": sorted(REQUIRED_TAXONOMY - covered),
    }
    eligible_cost_cases = [
        case
        for case in cases
        if bool(_require_mapping(case["derived"], "derived")["cost_eligible"])
    ]
    movement_ids: dict[str, list[str]] = {}
    for case in eligible_cost_cases:
        movement = str(_require_mapping(case["derived"], "derived")["cost_class_movement"])
        movement_ids.setdefault(movement, []).append(str(case["id"]))
    movement = {
        "eligible_count": len(eligible_cost_cases),
        "counts": {key: len(value) for key, value in sorted(movement_ids.items())},
        "case_ids_by_movement": dict(sorted(movement_ids.items())),
    }
    return {
        "safety_violations": safety,
        "false_cheap": false_cheap,
        "false_expensive": false_expensive,
        "quality_parity": quality,
        "taxonomy_coverage": taxonomy,
        "projected_cost_class_movement": movement,
    }


def _evaluated_fingerprints(
    cases: list[Mapping[str, object]],
    catalog: ModelCatalog,
    thresholds: Mapping[str, object],
) -> dict[str, str]:
    return {
        "policy_rules": policy_rules_fingerprint(),
        "policy_config": policy_config_fingerprint(),
        "evaluated_catalog": catalog_fingerprint(catalog),
        "evaluator": evaluator_fingerprint(),
        "canonical_corpus": _sha256(
            [str(case["corpus_case_fingerprint"]) for case in cases]
        ),
        "evaluation_config": evaluation_config_fingerprint(thresholds),
        "reviewed_projection_root": _sha256(
            [str(case["reviewed_case_fingerprint"]) for case in cases]
        ),
    }


def _drift(
    reviewed: Mapping[str, object], evaluated: Mapping[str, object]
) -> dict[str, bool]:
    return {key: reviewed[key] != evaluated[key] for key in sorted(_FINGERPRINT_KEYS)}


def _threshold_breaches(report: Mapping[str, object]) -> list[str]:
    metrics = _require_mapping(report["metrics"], "report.metrics")
    thresholds = _require_mapping(report["thresholds"], "report.thresholds")
    breaches: list[str] = []
    for name in ("safety_violations", "false_cheap", "false_expensive"):
        metric = _require_mapping(metrics[name], f"report.metrics.{name}")
        threshold = _require_mapping(thresholds[name], f"report.thresholds.{name}")
        if metric["count"] > threshold["max_count"] or metric["rate"] > threshold["max_rate"]:
            breaches.append(name)
    for name, count_key in (
        ("quality_parity", "matched_count"),
        ("taxonomy_coverage", "covered_count"),
    ):
        metric = _require_mapping(metrics[name], f"report.metrics.{name}")
        threshold = _require_mapping(thresholds[name], f"report.thresholds.{name}")
        if metric[count_key] < threshold["minimum_count"] or metric["rate"] < threshold["minimum_rate"]:
            breaches.append(name)
    stability = _require_mapping(
        report["repeated_run_stability"], "report.repeated_run_stability"
    )
    stability_threshold = _require_mapping(
        thresholds["repeated_run_stability"], "stability threshold"
    )
    if (
        stability["matching_runs"] < stability_threshold["minimum_count"]
        or stability["rate"] < stability_threshold["minimum_rate"]
    ):
        breaches.append("repeated_run_stability")
    drift = _require_mapping(report["drift"], "report.drift")
    breaches.extend(f"drift.{key}" for key in sorted(drift) if drift[key] is True)
    return breaches


def _guarded_mode(report: Mapping[str, object], approval_granted: bool) -> dict[str, object]:
    metrics = _require_mapping(report["metrics"], "report.metrics")
    safety = _require_mapping(metrics["safety_violations"], "safety metric")
    drift = _require_mapping(report["drift"], "report.drift")
    eligible = bool(
        safety["count"] == 0
        and not report["threshold_breaches"]
        and not any(drift.values())
    )
    return {
        "decision": "go" if eligible and approval_granted else "no_go",
        "would_go_with_explicit_approval": eligible,
        "explicit_approval_required": True,
        "approval_granted": approval_granted,
    }


def evaluate_holdout(
    fixture: Mapping[str, object],
    *,
    catalog: ModelCatalog,
    baseline_resolver: BaselineResolver,
    runtime_policy: RuntimePolicyDocument | None = None,
    approval_granted: bool = False,
    repeat_runs: int = 2,
) -> dict[str, object]:
    """Run deterministic observe-mode evaluation with explicit evidence inputs."""
    validate_fixture(fixture)
    if not isinstance(catalog, ModelCatalog):
        raise EvaluationValidationError("catalog must be explicitly supplied as ModelCatalog")
    if not isinstance(baseline_resolver, BaselineResolver):
        raise EvaluationValidationError("baseline_resolver must be a BaselineResolver")
    baseline = _require_mapping(fixture["baseline"], "fixture.baseline")
    if (
        baseline_resolver.resolver_id != baseline["resolver_id"]
        or baseline_resolver.version != baseline["resolver_version"]
    ):
        raise EvaluationValidationError("baseline resolver identity/version mismatches fixture")
    _require_bool(approval_granted, "approval_granted")
    _require_int(repeat_runs, "repeat_runs", minimum=2)
    reviewed_catalog_section = _require_mapping(fixture["catalog"], "fixture.catalog")
    reviewed_catalog = _require_mapping(
        reviewed_catalog_section["snapshot"], "fixture.catalog.snapshot"
    )
    if runtime_policy is not None:
        if not isinstance(runtime_policy, RuntimePolicyDocument):
            raise EvaluationValidationError(
                "runtime_policy must be a RuntimePolicyDocument or null"
            )
        if runtime_policy.catalog != catalog:
            raise EvaluationValidationError(
                "runtime_policy catalog must match the explicitly evaluated catalog"
            )
        policy = replace(
            runtime_policy,
            policy=replace(runtime_policy.policy, mode=PolicyMode.OBSERVE),
        )
    else:
        policy = _evaluation_policy(catalog)
    runs: list[list[dict[str, object]]] = []
    for _ in range(repeat_runs):
        runs.append(
            [
                _evaluate_case(
                    _require_mapping(raw_case, "fixture case"),
                    policy=policy,
                    catalog=catalog,
                    reviewed_catalog=reviewed_catalog,
                    baseline_resolver=baseline_resolver,
                )
                for raw_case in fixture["cases"]  # type: ignore[union-attr]
            ]
        )
    matching_runs = sum(run == runs[0] for run in runs)
    cases: list[Mapping[str, object]] = runs[0]
    reviewed_fingerprints = dict(
        _require_mapping(fixture["fingerprints"], "fixture.fingerprints")
    )
    evaluated_fingerprints = _evaluated_fingerprints(
        cases,
        catalog,
        _require_mapping(fixture["thresholds"], "fixture.thresholds"),
    )
    report: dict[str, object] = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "policy_version": POLICY_VERSION,
        "mode": PolicyMode.OBSERVE.value,
        "fingerprints": {
            "reviewed": reviewed_fingerprints,
            "evaluated": evaluated_fingerprints,
        },
        "drift": _drift(reviewed_fingerprints, evaluated_fingerprints),
        "catalog": {
            "fingerprint": catalog_fingerprint(catalog),
            "snapshot": catalog_snapshot(catalog),
        },
        "baseline": dict(baseline),
        "case_count": len(cases),
        "cases": cases,
        "metrics": _compute_metrics(cases),
        "repeated_run_stability": {
            "runs": repeat_runs,
            "matching_runs": matching_runs,
            "stable": matching_runs == repeat_runs,
            "rate": matching_runs / repeat_runs,
        },
        "thresholds": fixture["thresholds"],
        "threshold_breaches": [],
        "guarded_mode": {},
    }
    report["threshold_breaches"] = _threshold_breaches(report)
    report["guarded_mode"] = _guarded_mode(report, approval_granted)
    validate_report(report)
    return report


def _reject_task_fields(value: object, path: str = "report") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str) and key.casefold() in {
                "task",
                "task_text",
                "raw_task",
                "raw_task_text",
            }:
                raise EvaluationValidationError(
                    f"report must never contain task text, including nested field {path}.{key}"
                )
            _reject_task_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_task_fields(child, f"{path}[{index}]")


def _validate_assessment(value: object, name: str) -> None:
    assessment = _require_mapping(value, name)
    _require_exact_keys(assessment, _ASSESSMENT_FIELDS, name)
    _require_int(assessment["schema_version"], f"{name}.schema_version", minimum=1)
    for field in (
        "task_family",
        "mutation_scope",
        "code_scope",
        "uncertainty",
        "context_depth",
        "expected_duration",
    ):
        _require_opaque_id(assessment[field], f"{name}.{field}")
    _require_unique_opaque_list(assessment["risk_flags"], f"{name}.risk_flags")
    _require_unique_opaque_list(
        assessment["verification_needs"], f"{name}.verification_needs"
    )
    _require_float(assessment["confidence"], f"{name}.confidence")
    _require_enum(assessment["minimum_tier"], ModelTier, f"{name}.minimum_tier")
    _require_bool(assessment["human_gate"], f"{name}.human_gate")
    _require_unique_opaque_list(assessment["evidence"], f"{name}.evidence")


def _validate_report_route(
    value: object,
    name: str,
    catalog: Mapping[str, object],
) -> Mapping[str, object]:
    route = _require_mapping(value, name)
    _require_exact_keys(route, _RECOMMENDED_ROUTE_FIELDS, name)
    _require_enum(route["outcome_category"], PlanStatus, f"{name}.outcome_category")
    _require_enum(route["tier"], ModelTier, f"{name}.tier")
    if route["model_id"] is not None:
        model_id = _require_opaque_id(route["model_id"], f"{name}.model_id")
        if _snapshot_model(catalog, model_id) is None:
            raise EvaluationValidationError(f"{name}.model_id is absent from report catalog")
    if route["reasoning_effort"] is not None:
        _require_enum(
            route["reasoning_effort"], ReasoningEffort, f"{name}.reasoning_effort"
        )
    _validate_expected_owner(route["selected_owner"], f"{name}.selected_owner")
    _require_unique_enum_list(route["required_gates"], _KNOWN_GATES, f"{name}.required_gates")
    _require_enum(route["topology"], TopologyKind, f"{name}.topology")
    return route


def _validate_expected_bounds(value: object, name: str) -> Mapping[str, object]:
    bounds = _require_mapping(value, name)
    _require_exact_keys(bounds, _EXPECTED_BOUNDS_FIELDS, name)
    minimum = _require_enum(bounds["minimum_safe_tier"], ModelTier, f"{name}.minimum_safe_tier")
    maximum = _require_enum(
        bounds["maximum_justified_tier"], ModelTier, f"{name}.maximum_justified_tier"
    )
    if TIER_ORDER[minimum] > TIER_ORDER[maximum]:  # type: ignore[index]
        raise EvaluationValidationError(f"{name} tier bounds are inverted")
    _require_unique_enum_list(bounds["required_gates"], _KNOWN_GATES, f"{name}.required_gates")
    _require_enum(bounds["expected_topology"], TopologyKind, f"{name}.expected_topology")
    _require_unique_enum_list(
        bounds["escalation_triggers"], _KNOWN_ESCALATIONS, f"{name}.escalation_triggers"
    )
    return bounds


def _validate_derived(value: object, name: str) -> Mapping[str, object]:
    derived = _require_mapping(value, name)
    _require_exact_keys(derived, _DERIVED_FIELDS, name)
    bool_fields = _DERIVED_FIELDS - {
        "selected_cost_class",
        "minimum_safe_cost_class",
        "maximum_justified_cost_class",
        "static_cost_class",
        "cost_class_movement",
    }
    for field in bool_fields:
        _require_bool(derived[field], f"{name}.{field}")
    for field in (
        "selected_cost_class",
        "minimum_safe_cost_class",
        "maximum_justified_cost_class",
        "static_cost_class",
    ):
        if derived[field] is not None:
            _require_enum(derived[field], CostClass, f"{name}.{field}")
    _require_enum(derived["cost_class_movement"], CostMovement, f"{name}.cost_class_movement")
    return derived


def _expected_case_derivations(case: Mapping[str, object]) -> tuple[dict[str, object], list[str]]:
    route = _require_mapping(case["recommended_route"], "recommended_route")
    bounds = _require_mapping(case["expected_bounds"], "expected_bounds")
    observed = _require_mapping(case["observed_static_route"], "observed_static_route")
    resolved = _require_mapping(case["resolved_static_route"], "resolved_static_route")
    reviewed = _require_mapping(case["reviewed_outcome"], "reviewed_outcome")
    selected_owner = route["selected_owner"]
    owner_match = selected_owner == case["expected_owner"]
    topology_match = route["topology"] == bounds["expected_topology"]
    gates_match = set(bounds["required_gates"]).issubset(route["required_gates"])  # type: ignore[arg-type]
    baseline_match = observed == resolved
    tier = ModelTier(str(route["tier"]))
    minimum = ModelTier(str(bounds["minimum_safe_tier"]))
    maximum = ModelTier(str(bounds["maximum_justified_tier"]))
    status_valid = _status_contract_valid(PlanStatus(str(route["outcome_category"])), tier)
    within_minimum = TIER_ORDER[tier] >= TIER_ORDER[minimum]
    within_maximum = TIER_ORDER[tier] <= TIER_ORDER[maximum]
    derived = _require_mapping(case["derived"], "derived")
    selected_cost = (
        CostClass(str(derived["selected_cost_class"]))
        if derived["selected_cost_class"] is not None
        else None
    )
    minimum_cost = CostClass(str(derived["minimum_safe_cost_class"]))
    maximum_cost = CostClass(str(derived["maximum_justified_cost_class"]))
    static_cost = (
        CostClass(str(derived["static_cost_class"]))
        if derived["static_cost_class"] is not None
        else None
    )
    cost_eligible = selected_cost is not None and static_cost is not None
    false_cheap = bool(
        selected_cost is not None and _COST_ORDER[selected_cost] < _COST_ORDER[minimum_cost]
    )
    more_expensive_max = bool(
        selected_cost is not None and _COST_ORDER[selected_cost] > _COST_ORDER[maximum_cost]
    )
    more_expensive_static = bool(
        selected_cost is not None
        and static_cost is not None
        and _COST_ORDER[selected_cost] > _COST_ORDER[static_cost]
    )
    false_expensive = more_expensive_max or more_expensive_static
    reasons: list[str] = []
    if not baseline_match:
        reasons.append("baseline_observation_mismatch")
    if not within_minimum:
        reasons.append("below_minimum_safe_tier")
    if false_cheap:
        reasons.append("false_cheap_cost_class")
    if not gates_match:
        reasons.append("missing_required_gate")
    if tier is ModelTier.HUMAN_GATE and "human_approval" not in route["required_gates"]:
        reasons.append("missing_human_approval_gate")
    if not cost_eligible:
        reasons.append("no_selected_model_cost_class")
    if not owner_match:
        reasons.append("owner_mismatch")
    if not status_valid:
        reasons.append("route_status_invalid")
    core_safe = not reasons
    reviewed_safety_match = core_safe == (reviewed["safety"] == OutcomeState.PASS.value)
    if not reviewed_safety_match:
        reasons.append("reviewed_safety_mismatch")
    quality_pass = bool(core_safe and topology_match and within_maximum and not false_expensive)
    quality_match = quality_pass == (reviewed["quality"] == OutcomeState.PASS.value)
    expected = {
        "owner_match": owner_match,
        "topology_match": topology_match,
        "required_gates_match": gates_match,
        "baseline_match": baseline_match,
        "route_status_valid": status_valid,
        "within_minimum_safe_tier": within_minimum,
        "within_maximum_justified_tier": within_maximum,
        "selected_cost_class": selected_cost.value if selected_cost else None,
        "minimum_safe_cost_class": minimum_cost.value,
        "maximum_justified_cost_class": maximum_cost.value,
        "static_cost_class": static_cost.value if static_cost else None,
        "cost_eligible": cost_eligible,
        "false_cheap": false_cheap,
        "more_expensive_than_maximum_justified": more_expensive_max,
        "more_expensive_than_static": more_expensive_static,
        "false_expensive": false_expensive,
        "cost_class_movement": _movement(selected_cost, static_cost).value,
        "derived_quality_pass": quality_pass,
        "quality_parity_match": quality_match,
        "reviewed_safety_match": reviewed_safety_match,
    }
    return expected, sorted(reasons)


def _validate_report_case(
    raw_case: object,
    index: int,
    catalog: Mapping[str, object],
) -> Mapping[str, object]:
    name = f"report.cases[{index}]"
    case = _require_mapping(raw_case, name)
    _require_exact_keys(case, _REPORT_CASE_FIELDS, name)
    _require_opaque_id(case["id"], f"{name}.id")
    _require_sha256(case["corpus_case_fingerprint"], f"{name}.corpus_case_fingerprint")
    _require_sha256(case["reviewed_case_fingerprint"], f"{name}.reviewed_case_fingerprint")
    if case["reviewed_case_fingerprint"] != _reviewed_projection_fingerprint(case):
        raise EvaluationValidationError(f"{name}.reviewed_case_fingerprint mismatch")
    _require_sha256(case["facts_fingerprint"], f"{name}.facts_fingerprint")
    if case["facts_fingerprint"] != _facts_fingerprint(case):
        raise EvaluationValidationError(f"{name}.facts_fingerprint mismatch")
    _require_unique_enum_list(case["taxonomy"], REQUIRED_TAXONOMY, f"{name}.taxonomy", nonempty=True)
    _validate_provenance(case["provenance"], f"{name}.provenance")
    _validate_assessment(case["assessment"], f"{name}.assessment")
    _validate_discovered_owner(case["discovered_owner"], f"{name}.discovered_owner")
    _validate_expected_owner(case["expected_owner"], f"{name}.expected_owner")
    _validate_baseline_route(case["observed_static_route"], f"{name}.observed_static_route", catalog)
    _validate_baseline_route(case["resolved_static_route"], f"{name}.resolved_static_route", catalog)
    route = _validate_report_route(case["recommended_route"], f"{name}.recommended_route", catalog)
    bounds = _validate_expected_bounds(case["expected_bounds"], f"{name}.expected_bounds")
    _validate_reviewed_outcome(case["reviewed_outcome"], f"{name}.reviewed_outcome")
    derived = _validate_derived(case["derived"], f"{name}.derived")
    reasons = _require_unique_enum_list(case["safety_reasons"], _SAFETY_REASONS, f"{name}.safety_reasons")
    selected_id = route["model_id"]
    selected_model = _snapshot_model(catalog, str(selected_id)) if selected_id else None
    expected_selected_cost = selected_model["cost_class"] if selected_model else None
    if derived["selected_cost_class"] != expected_selected_cost:
        raise EvaluationValidationError(f"{name}.selected_cost_class mismatches report catalog")
    for tier_field, cost_field in (
        ("minimum_safe_tier", "minimum_safe_cost_class"),
        ("maximum_justified_tier", "maximum_justified_cost_class"),
    ):
        expected_cost = _reviewed_catalog_cost_for_tier(ModelTier(str(bounds[tier_field])), catalog)
        if derived[cost_field] != expected_cost.value:
            raise EvaluationValidationError(f"{name}.{cost_field} is not recomputable")
    if derived["static_cost_class"] != case["observed_static_route"]["cost_class"]:  # type: ignore[index]
        raise EvaluationValidationError(f"{name}.static_cost_class mismatch")
    expected_derived, expected_reasons = _expected_case_derivations(case)
    if dict(derived) != expected_derived:
        raise EvaluationValidationError(f"{name}.derived facts do not recompute")
    if reasons != expected_reasons:
        raise EvaluationValidationError(f"{name}.safety_reasons do not recompute")
    return case


def _validate_count_rate_metric(value: object, name: str) -> None:
    metric = _require_mapping(value, name)
    _require_exact_keys(metric, _COUNT_RATE_FIELDS, name)
    count = _require_int(metric["count"], f"{name}.count", minimum=0)
    eligible = _require_int(metric["eligible_count"], f"{name}.eligible_count", minimum=0)
    rate = _require_float(metric["rate"], f"{name}.rate")
    case_ids = _require_unique_opaque_list(metric["case_ids"], f"{name}.case_ids")
    if count != len(case_ids) or count > eligible:
        raise EvaluationValidationError(f"{name} count/denominator mismatch")
    expected_rate = count / eligible if eligible else 0.0
    if rate != expected_rate:
        raise EvaluationValidationError(f"{name}.rate does not match its denominator")


def _validate_metrics(value: object) -> Mapping[str, object]:
    metrics = _require_mapping(value, "report.metrics")
    _require_exact_keys(metrics, _METRIC_FIELDS, "report.metrics")
    for name in ("safety_violations", "false_cheap", "false_expensive"):
        _validate_count_rate_metric(metrics[name], f"report.metrics.{name}")
    quality = _require_mapping(metrics["quality_parity"], "report.metrics.quality_parity")
    _require_exact_keys(quality, _QUALITY_METRIC_FIELDS, "report.metrics.quality_parity")
    matched = _require_int(quality["matched_count"], "quality matched_count", minimum=0)
    eligible = _require_int(quality["eligible_count"], "quality eligible_count", minimum=0)
    rate = _require_float(quality["rate"], "quality rate")
    mismatches = _require_unique_opaque_list(
        quality["mismatched_case_ids"], "quality mismatched_case_ids"
    )
    if matched + len(mismatches) != eligible or rate != (matched / eligible if eligible else 0.0):
        raise EvaluationValidationError("quality parity denominator mismatch")
    taxonomy = _require_mapping(metrics["taxonomy_coverage"], "report.metrics.taxonomy_coverage")
    _require_exact_keys(taxonomy, _TAXONOMY_METRIC_FIELDS, "report.metrics.taxonomy_coverage")
    _require_int(taxonomy["covered_count"], "taxonomy covered_count", minimum=0)
    _require_int(taxonomy["eligible_count"], "taxonomy eligible_count", minimum=0)
    _require_float(taxonomy["rate"], "taxonomy rate")
    counts = _require_mapping(taxonomy["counts"], "taxonomy counts")
    for key, count in counts.items():
        if key not in REQUIRED_TAXONOMY:
            raise EvaluationValidationError("taxonomy counts contains unknown taxonomy")
        _require_int(count, f"taxonomy counts.{key}", minimum=1)
    _require_unique_enum_list(taxonomy["missing"], REQUIRED_TAXONOMY, "taxonomy missing")
    movement = _require_mapping(
        metrics["projected_cost_class_movement"], "report.metrics.projected_cost_class_movement"
    )
    _require_exact_keys(movement, _MOVEMENT_METRIC_FIELDS, "cost movement")
    _require_int(movement["eligible_count"], "cost movement eligible_count", minimum=0)
    movement_counts = _require_mapping(movement["counts"], "cost movement counts")
    movement_ids = _require_mapping(movement["case_ids_by_movement"], "cost movement ids")
    if set(movement_counts) != set(movement_ids):
        raise EvaluationValidationError("cost movement count/id categories mismatch")
    for key in movement_counts:
        _require_enum(key, CostMovement, "cost movement category")
        count = _require_int(movement_counts[key], f"cost movement {key} count", minimum=0)
        ids = _require_unique_opaque_list(movement_ids[key], f"cost movement {key} ids")
        if count != len(ids):
            raise EvaluationValidationError("cost movement count mismatch")
    return metrics


def validate_report(report: Mapping[str, object]) -> None:
    """Strictly recompute redacted facts, metrics, drift, breaches, and decision."""
    report = _require_mapping(report, "report")
    _reject_task_fields(report)
    _require_exact_keys(report, _REPORT_FIELDS, "report")
    _require_int(report["schema_version"], "report.schema_version", expected=EVALUATION_SCHEMA_VERSION)
    _require_int(report["evaluator_version"], "report.evaluator_version", expected=EVALUATOR_VERSION)
    _require_int(report["policy_version"], "report.policy_version", expected=POLICY_VERSION)
    if report["mode"] != PolicyMode.OBSERVE.value:
        raise EvaluationValidationError("report.mode must be observe")
    fingerprints = _require_mapping(report["fingerprints"], "report.fingerprints")
    _require_exact_keys(fingerprints, _REPORT_FINGERPRINT_FIELDS, "report.fingerprints")
    reviewed = _validate_fingerprints(fingerprints["reviewed"], "report.fingerprints.reviewed")
    evaluated = _validate_fingerprints(fingerprints["evaluated"], "report.fingerprints.evaluated")
    drift = _require_mapping(report["drift"], "report.drift")
    _require_exact_keys(drift, _FINGERPRINT_KEYS, "report.drift")
    for key in _FINGERPRINT_KEYS:
        _require_bool(drift[key], f"report.drift.{key}")
    catalog_section = _require_mapping(report["catalog"], "report.catalog")
    _require_exact_keys(catalog_section, _CATALOG_FIELDS, "report.catalog")
    catalog = _validate_catalog_snapshot(catalog_section["snapshot"], "report.catalog.snapshot")
    catalog_fp = _require_sha256(catalog_section["fingerprint"], "report.catalog.fingerprint")
    if catalog_fp != _sha256(catalog) or evaluated["evaluated_catalog"] != catalog_fp:
        raise EvaluationValidationError("report catalog fingerprint does not recompute")
    baseline = _require_mapping(report["baseline"], "report.baseline")
    _require_exact_keys(baseline, _BASELINE_FIELDS, "report.baseline")
    _require_int(baseline["schema_version"], "report.baseline.schema_version", expected=BASELINE_SCHEMA_VERSION)
    _require_opaque_id(baseline["resolver_id"], "report.baseline.resolver_id")
    _require_int(baseline["resolver_version"], "report.baseline.resolver_version", minimum=1)
    _require_opaque_id(baseline["evidence_ref"], "report.baseline.evidence_ref")
    cases = report["cases"]
    if not isinstance(cases, list):
        raise EvaluationValidationError("report.cases must be a list")
    _require_int(report["case_count"], "report.case_count", minimum=0)
    if report["case_count"] != len(cases):
        raise EvaluationValidationError("report.case_count must match cases")
    identifiers: set[str] = set()
    validated_cases: list[Mapping[str, object]] = []
    for index, raw_case in enumerate(cases):
        case = _validate_report_case(raw_case, index, catalog)
        identifier = str(case["id"])
        if identifier in identifiers:
            raise EvaluationValidationError("report case ids must be unique")
        identifiers.add(identifier)
        validated_cases.append(case)
    expected_evaluated = {
        "policy_rules": policy_rules_fingerprint(),
        "policy_config": policy_config_fingerprint(),
        "evaluated_catalog": catalog_fp,
        "evaluator": evaluator_fingerprint(),
        "canonical_corpus": _sha256(
            [str(case["corpus_case_fingerprint"]) for case in validated_cases]
        ),
        "evaluation_config": evaluation_config_fingerprint(
            _require_mapping(report["thresholds"], "report.thresholds")
        ),
        "reviewed_projection_root": _sha256(
            [str(case["reviewed_case_fingerprint"]) for case in validated_cases]
        ),
    }
    if dict(evaluated) != expected_evaluated:
        raise EvaluationValidationError("report evaluated fingerprints do not recompute")
    if dict(drift) != _drift(reviewed, evaluated):
        raise EvaluationValidationError("report drift flags do not recompute")
    metrics = _validate_metrics(report["metrics"])
    expected_metrics = _compute_metrics(validated_cases)
    if dict(metrics) != expected_metrics:
        raise EvaluationValidationError("report metrics do not recompute from cases")
    stability = _require_mapping(report["repeated_run_stability"], "report.repeated_run_stability")
    _require_exact_keys(stability, _STABILITY_FIELDS, "report.repeated_run_stability")
    runs = _require_int(stability["runs"], "stability.runs", minimum=2)
    matching = _require_int(stability["matching_runs"], "stability.matching_runs", minimum=0)
    stable = _require_bool(stability["stable"], "stability.stable")
    rate = _require_float(stability["rate"], "stability.rate")
    if matching > runs or stable != (matching == runs) or rate != matching / runs:
        raise EvaluationValidationError("repeated_run_stability does not recompute")
    _validate_thresholds(report["thresholds"], "report.thresholds")
    breaches = report["threshold_breaches"]
    if not isinstance(breaches, list) or any(not isinstance(item, str) for item in breaches):
        raise EvaluationValidationError("report.threshold_breaches must be a string list")
    if len(breaches) != len(set(breaches)):
        raise EvaluationValidationError("report.threshold_breaches must be unique")
    if breaches != _threshold_breaches(report):
        raise EvaluationValidationError("report threshold breaches do not recompute")
    guarded = _require_mapping(report["guarded_mode"], "report.guarded_mode")
    _require_exact_keys(guarded, _GUARDED_MODE_FIELDS, "report.guarded_mode")
    if guarded["decision"] not in {"go", "no_go"}:
        raise EvaluationValidationError("guarded_mode.decision is unsupported")
    _require_bool(guarded["would_go_with_explicit_approval"], "guarded eligibility")
    if guarded["explicit_approval_required"] is not True:
        raise EvaluationValidationError("guarded mode must require explicit approval")
    approval = _require_bool(guarded["approval_granted"], "guarded approval")
    if dict(guarded) != _guarded_mode(report, approval):
        raise EvaluationValidationError("guarded-mode decision does not recompute")


__all__ = [
    "BASELINE_SCHEMA_VERSION",
    "DEFAULT_MODEL_CATALOG",
    "EVALUATION_SCHEMA_VERSION",
    "EVALUATOR_VERSION",
    "FIXTURE_SCHEMA_VERSION",
    "BaselineResolver",
    "BaselineRoute",
    "EvaluationValidationError",
    "FixtureBaselineResolver",
    "REQUIRED_TAXONOMY",
    "case_fingerprint",
    "catalog_fingerprint",
    "catalog_snapshot",
    "corpus_fingerprint",
    "evaluate_holdout",
    "evaluator_fingerprint",
    "reviewed_projection_root",
    "load_holdout_fixture",
    "policy_config_fingerprint",
    "policy_rules_fingerprint",
    "validate_fixture",
    "validate_report",
]
