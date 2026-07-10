"""Adversarial contract coverage for CC-215 Gate 3A evaluation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

import genomes_agentic_os.adaptive_evaluation as evaluation_module

from genomes_agentic_os.adaptive_evaluation import (
    DEFAULT_MODEL_CATALOG,
    BaselineResolver,
    BaselineRoute,
    EvaluationValidationError,
    FixtureBaselineResolver,
    REQUIRED_TAXONOMY,
    corpus_fingerprint,
    evaluate_holdout,
    load_holdout_fixture,
    reviewed_projection_root,
    validate_fixture,
    validate_report,
)
from genomes_agentic_os.adaptive_policy import ModelCatalog, ModelTier


FIXTURE = Path(__file__).parent / "fixtures" / "adaptive_routing_holdout.yml"


def _fixture() -> dict[str, object]:
    return load_holdout_fixture(FIXTURE)


def _repin(fixture: dict[str, object]) -> None:
    fixture["fingerprints"]["canonical_corpus"] = corpus_fingerprint(  # type: ignore[index]
        fixture["cases"]  # type: ignore[arg-type]
    )
    fixture["fingerprints"]["reviewed_projection_root"] = reviewed_projection_root(  # type: ignore[index]
        fixture["cases"]  # type: ignore[arg-type]
    )


def _facts_fingerprint(case: dict[str, object]) -> str:
    redacted = {key: value for key, value in case.items() if key != "facts_fingerprint"}
    payload = json.dumps(
        redacted, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _evaluate(
    fixture: dict[str, object] | None = None,
    *,
    catalog: ModelCatalog = DEFAULT_MODEL_CATALOG,
    approval_granted: bool = False,
    baseline_resolver: BaselineResolver | None = None,
) -> dict[str, object]:
    reviewed = fixture or _fixture()
    resolver = baseline_resolver or FixtureBaselineResolver.from_fixture(reviewed)
    return evaluate_holdout(
        reviewed,
        catalog=catalog,
        baseline_resolver=resolver,
        approval_granted=approval_granted,
    )


def test_reviewed_fixture_covers_full_taxonomy_frontier_max_and_real_variation() -> None:
    fixture = _fixture()
    cases = fixture["cases"]
    coverage = {item for case in cases for item in case["taxonomy"]}  # type: ignore[index]

    assert len(cases) == 54  # type: ignore[arg-type]
    assert coverage == REQUIRED_TAXONOMY
    assert all(case["provenance"]["review_status"] == "reviewed" for case in cases)  # type: ignore[index]
    assert all(case["provenance"]["evidence_ref"] for case in cases)  # type: ignore[index]
    assert all(case["reviewed_outcome"]["evidence_ref"] for case in cases)  # type: ignore[index]
    assert any(
        case["minimum_safe_tier"] != case["maximum_justified_tier"]
        for case in cases  # type: ignore[union-attr]
    )
    assert sum(
        bool(case["discovered_owner"])
        and case["discovered_owner"]["minimum_tier"] == "frontier_max"
        for case in cases  # type: ignore[index]
    ) >= 2

    report = _evaluate(fixture, approval_granted=True)
    assert {case["recommended_route"]["tier"] for case in report["cases"]} == {  # type: ignore[index]
        "economy",
        "balanced",
        "frontier",
        "frontier_max",
        "human_gate",
    }
    assert report["metrics"]["projected_cost_class_movement"]["counts"] == {  # type: ignore[index]
        "cheaper": 21,
        "same": 33,
    }
    assert report["guarded_mode"]["decision"] == "go"  # type: ignore[index]


def test_clean_report_has_explicit_denominators_fingerprints_and_no_task_text() -> None:
    fixture = _fixture()
    report = _evaluate(fixture)

    assert report["metrics"]["safety_violations"] == {  # type: ignore[index]
        "count": 0,
        "eligible_count": 54,
        "rate": 0.0,
        "case_ids": [],
    }
    assert report["metrics"]["false_cheap"]["eligible_count"] == 54  # type: ignore[index]
    assert report["metrics"]["false_expensive"]["eligible_count"] == 54  # type: ignore[index]
    assert report["metrics"]["quality_parity"] == {  # type: ignore[index]
        "matched_count": 54,
        "eligible_count": 54,
        "rate": 1.0,
        "mismatched_case_ids": [],
    }
    assert report["repeated_run_stability"] == {
        "runs": 2,
        "matching_runs": 2,
        "stable": True,
        "rate": 1.0,
    }
    assert not any(report["drift"].values())  # type: ignore[union-attr]
    assert set(report["fingerprints"]["reviewed"]) == {  # type: ignore[index]
        "policy_rules",
        "policy_config",
        "evaluated_catalog",
        "evaluator",
            "canonical_corpus",
            "evaluation_config",
            "reviewed_projection_root",
    }
    serialized = json.dumps(report, sort_keys=True)
    assert all(case["task"] not in serialized for case in fixture["cases"])  # type: ignore[index]
    assert all(token not in serialized.casefold() for token in ("provider_price", "currency_cost", "usd"))
    validate_report(report)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schema_version",), True),
        (("evaluator_version",), True),
        (("policy_version",), True),
        (("thresholds", "safety_violations", "max_count"), True),
        (("thresholds", "safety_violations", "max_rate"), True),
        (("thresholds", "quality_parity", "minimum_count"), True),
        (("thresholds", "quality_parity", "minimum_rate"), True),
    ],
)
def test_fixture_rejects_bool_versions_counts_and_rates(
    path: tuple[str, ...], value: object
) -> None:
    fixture = deepcopy(_fixture())
    target: dict[str, object] = fixture
    for part in path[:-1]:
        target = target[part]  # type: ignore[assignment]
    target[path[-1]] = value

    with pytest.raises(EvaluationValidationError, match="exact integer|exact float"):
        validate_fixture(fixture)


def test_repeat_count_rejects_bool() -> None:
    fixture = _fixture()
    with pytest.raises(EvaluationValidationError, match="exact integer"):
        evaluate_holdout(
            fixture,
            catalog=DEFAULT_MODEL_CATALOG,
            baseline_resolver=FixtureBaselineResolver.from_fixture(fixture),
            repeat_runs=True,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "yaml_text",
    [
        "schema_version: 2\nschema_version: 2\n",
        "root:\n  id: one\n  id: two\n",
    ],
)
def test_yaml_loader_rejects_duplicate_keys_at_any_depth(
    tmp_path: Path, yaml_text: str
) -> None:
    duplicate = tmp_path / "duplicate.yml"
    duplicate.write_text(yaml_text, encoding="utf-8")

    with pytest.raises(EvaluationValidationError, match="duplicate key"):
        load_holdout_fixture(duplicate)


def test_fixture_rejects_duplicate_taxonomies_and_case_ids() -> None:
    duplicated_taxonomy = deepcopy(_fixture())
    duplicated_taxonomy["cases"][0]["taxonomy"].append(  # type: ignore[index]
        duplicated_taxonomy["cases"][0]["taxonomy"][0]  # type: ignore[index]
    )
    with pytest.raises(EvaluationValidationError, match="unique values"):
        validate_fixture(duplicated_taxonomy)

    duplicated_id = deepcopy(_fixture())
    duplicated_id["cases"][1]["id"] = duplicated_id["cases"][0]["id"]  # type: ignore[index]
    _repin(duplicated_id)
    with pytest.raises(EvaluationValidationError, match="case ids must be unique"):
        validate_fixture(duplicated_id)


def test_task_or_corpus_tamper_without_reviewed_repin_fails() -> None:
    task_tamper = deepcopy(_fixture())
    task_tamper["cases"][0]["task"] += " Carefully."  # type: ignore[index,operator]
    with pytest.raises(EvaluationValidationError, match="canonical corpus fingerprint"):
        validate_fixture(task_tamper)

    reordered = deepcopy(_fixture())
    reordered["cases"][0], reordered["cases"][1] = (  # type: ignore[index]
        reordered["cases"][1],
        reordered["cases"][0],
    )
    with pytest.raises(EvaluationValidationError, match="canonical corpus fingerprint"):
        validate_fixture(reordered)


def test_taxonomy_is_semantic_and_benign_security_label_tamper_fails() -> None:
    fixture = deepcopy(_fixture())
    fixture["cases"][0]["taxonomy"].append("security")  # type: ignore[index]
    _repin(fixture)

    with pytest.raises(EvaluationValidationError, match="does not match assessed task semantics"):
        validate_fixture(fixture)


@pytest.mark.parametrize("missing", ["provenance", "reviewed_outcome"])
def test_each_case_requires_reviewed_provenance_and_outcome(missing: str) -> None:
    fixture = deepcopy(_fixture())
    del fixture["cases"][0][missing]  # type: ignore[index]

    with pytest.raises(EvaluationValidationError, match="schema mismatch"):
        validate_fixture(fixture)


def test_nonblank_opaque_owner_and_evidence_ids_are_enforced() -> None:
    fixture = deepcopy(_fixture())
    fixture["cases"][0]["discovered_owner"]["identifier"] = "   "  # type: ignore[index]
    _repin(fixture)
    with pytest.raises(EvaluationValidationError, match="nonblank opaque identifier"):
        validate_fixture(fixture)

    evidence = deepcopy(_fixture())
    evidence["cases"][0]["provenance"]["evidence_ref"] = ""  # type: ignore[index]
    _repin(evidence)
    with pytest.raises(EvaluationValidationError, match="nonblank opaque identifier"):
        validate_fixture(evidence)


def test_router_receives_discovered_owner_not_expected_owner() -> None:
    fixture = deepcopy(_fixture())
    fixture["cases"][0]["discovered_owner"]["identifier"] = "wrong-discovery"  # type: ignore[index]
    _repin(fixture)

    report = _evaluate(fixture, approval_granted=True)
    case = report["cases"][0]  # type: ignore[index]
    assert case["recommended_route"]["selected_owner"]["identifier"] == "wrong-discovery"
    assert case["expected_owner"]["identifier"] == "jira-workflow"
    assert case["derived"]["owner_match"] is False
    assert "owner_mismatch" in case["safety_reasons"]
    assert report["guarded_mode"]["decision"] == "no_go"  # type: ignore[index]


class _MismatchingBaselineResolver(BaselineResolver):
    def __init__(self, resolver_id: str, version: int) -> None:
        self.resolver_id = resolver_id
        self.version = version

    def resolve(
        self,
        *,
        case_id: str,
        reviewed_observation: BaselineRoute,
        catalog: ModelCatalog,
    ) -> BaselineRoute:
        del case_id, catalog
        replacement = (
            ModelTier.BALANCED
            if reviewed_observation.tier is ModelTier.ECONOMY
            else ModelTier.ECONOMY
        )
        return replace(reviewed_observation, tier=replacement)


def test_typed_baseline_resolution_mismatch_is_a_safety_failure() -> None:
    fixture = _fixture()
    baseline = fixture["baseline"]
    resolver = _MismatchingBaselineResolver(
        baseline["resolver_id"], baseline["resolver_version"]  # type: ignore[index,arg-type]
    )

    report = _evaluate(fixture, approval_granted=True, baseline_resolver=resolver)
    assert report["metrics"]["safety_violations"]["count"] == 54  # type: ignore[index]
    assert "baseline_observation_mismatch" in report["cases"][0]["safety_reasons"]  # type: ignore[index]
    assert report["guarded_mode"]["decision"] == "no_go"  # type: ignore[index]


def test_baseline_resolver_identity_and_observed_cost_mismatch_fail_closed() -> None:
    fixture = _fixture()
    with pytest.raises(EvaluationValidationError, match="identity/version"):
        evaluate_holdout(
            fixture,
            catalog=DEFAULT_MODEL_CATALOG,
            baseline_resolver=FixtureBaselineResolver("different-resolver", 1),
        )

    bad_observation = deepcopy(fixture)
    bad_observation["cases"][0]["observed_static_route"]["cost_class"] = "premium"  # type: ignore[index]
    _repin(bad_observation)
    with pytest.raises(EvaluationValidationError, match="cost_class mismatches catalog"):
        validate_fixture(bad_observation)


def test_explicit_catalog_availability_drift_and_expensive_fallback_breach() -> None:
    records = tuple(
        replace(record, available=False)
        if record.model_id == "gpt-5.6-luna"
        else record
        for record in DEFAULT_MODEL_CATALOG.records
    )
    drifted_catalog = ModelCatalog(records, version=DEFAULT_MODEL_CATALOG.version)

    report = _evaluate(
        catalog=drifted_catalog,
        approval_granted=True,
    )

    assert report["drift"]["evaluated_catalog"] is True  # type: ignore[index]
    assert report["cases"][0]["recommended_route"]["model_id"] == "gpt-5.6-terra"  # type: ignore[index]
    assert report["cases"][0]["derived"]["selected_cost_class"] == "standard"  # type: ignore[index]
    assert report["cases"][0]["derived"]["false_expensive"] is True  # type: ignore[index]
    assert "false_expensive" in report["threshold_breaches"]  # type: ignore[operator]
    assert "drift.evaluated_catalog" in report["threshold_breaches"]  # type: ignore[operator]
    assert report["guarded_mode"]["decision"] == "no_go"  # type: ignore[index]


def test_reviewed_quality_outcome_is_independent_evidence() -> None:
    fixture = deepcopy(_fixture())
    fixture["cases"][0]["reviewed_outcome"]["quality"] = "fail"  # type: ignore[index]
    _repin(fixture)

    report = _evaluate(fixture, approval_granted=True)
    assert report["cases"][0]["derived"]["derived_quality_pass"] is True  # type: ignore[index]
    assert report["cases"][0]["derived"]["quality_parity_match"] is False  # type: ignore[index]
    assert report["metrics"]["quality_parity"]["matched_count"] == 53  # type: ignore[index]
    assert "quality_parity" in report["threshold_breaches"]  # type: ignore[operator]
    assert report["guarded_mode"]["decision"] == "no_go"  # type: ignore[index]


def test_report_rejects_nested_raw_task_and_duplicate_case_ids() -> None:
    report = _evaluate()
    nested_task = deepcopy(report)
    nested_task["cases"][0]["assessment"]["audit"] = {"raw_task": "secret"}  # type: ignore[index]
    with pytest.raises(EvaluationValidationError, match="never contain task text"):
        validate_report(nested_task)

    duplicate = deepcopy(report)
    duplicate["cases"][1]["id"] = duplicate["cases"][0]["id"]  # type: ignore[index]
    duplicate["cases"][1]["facts_fingerprint"] = _facts_fingerprint(duplicate["cases"][1])  # type: ignore[index,arg-type]
    with pytest.raises(EvaluationValidationError, match="reviewed_case_fingerprint mismatch"):
        validate_report(duplicate)


@pytest.mark.parametrize(
    ("mutator", "match"),
    [
        (
            lambda report: report["metrics"]["safety_violations"].__setitem__("count", True),
            "exact integer",
        ),
        (
            lambda report: report.__setitem__("schema_version", True),
            "exact integer",
        ),
        (
            lambda report: report["metrics"]["quality_parity"].__setitem__("matched_count", 53),
            "denominator mismatch|metrics do not recompute",
        ),
        (
            lambda report: report["fingerprints"]["evaluated"].__setitem__(
                "policy_config", "0" * 64
            ),
            "evaluated fingerprints do not recompute",
        ),
    ],
)
def test_report_strictly_recomputes_types_metrics_and_fingerprints(
    mutator: object, match: str
) -> None:
    report = deepcopy(_evaluate())
    mutator(report)  # type: ignore[operator]
    with pytest.raises(EvaluationValidationError, match=match):
        validate_report(report)


def test_decision_forgery_and_approval_forgery_are_rejected() -> None:
    pending = _evaluate()
    forged_decision = deepcopy(pending)
    forged_decision["guarded_mode"]["decision"] = "go"  # type: ignore[index]
    with pytest.raises(EvaluationValidationError, match="decision does not recompute"):
        validate_report(forged_decision)

    approved = _evaluate(approval_granted=True)
    forged_approval = deepcopy(approved)
    forged_approval["guarded_mode"]["approval_granted"] = False  # type: ignore[index]
    with pytest.raises(EvaluationValidationError, match="decision does not recompute"):
        validate_report(forged_approval)


def test_thresholds_are_bound_to_reviewed_evaluation_config() -> None:
    report = deepcopy(_evaluate(approval_granted=True))
    report["thresholds"]["quality_parity"]["minimum_count"] = 0  # type: ignore[index]
    report["thresholds"]["quality_parity"]["minimum_rate"] = 0.0  # type: ignore[index]

    with pytest.raises(EvaluationValidationError, match="evaluated fingerprints"):
        validate_report(report)


def test_reviewed_projection_cannot_be_coordinately_rewritten() -> None:
    report = deepcopy(_evaluate(approval_granted=True))
    case = report["cases"][0]  # type: ignore[index]
    case["expected_owner"] = None  # type: ignore[index]
    case["reviewed_case_fingerprint"] = (  # type: ignore[index]
        evaluation_module._reviewed_projection_fingerprint(case)  # type: ignore[arg-type]
    )
    derived, reasons = evaluation_module._expected_case_derivations(case)  # type: ignore[arg-type]
    case["derived"] = derived  # type: ignore[index]
    case["safety_reasons"] = reasons  # type: ignore[index]
    case["facts_fingerprint"] = _facts_fingerprint(case)  # type: ignore[arg-type,index]

    with pytest.raises(EvaluationValidationError, match="evaluated fingerprints"):
        validate_report(report)


def test_any_breach_drift_safety_or_missing_approval_is_no_go() -> None:
    pending = _evaluate()
    assert pending["guarded_mode"] == {
        "decision": "no_go",
        "would_go_with_explicit_approval": True,
        "explicit_approval_required": True,
        "approval_granted": False,
    }

    unsafe = deepcopy(_fixture())
    unsafe["cases"][0]["minimum_safe_tier"] = "frontier"  # type: ignore[index]
    unsafe["cases"][0]["maximum_justified_tier"] = "frontier"  # type: ignore[index]
    _repin(unsafe)
    unsafe_report = _evaluate(unsafe, approval_granted=True)
    assert unsafe_report["metrics"]["safety_violations"]["count"] >= 1  # type: ignore[index]
    assert unsafe_report["guarded_mode"]["decision"] == "no_go"  # type: ignore[index]


def test_catalog_and_baseline_are_required_explicit_inputs() -> None:
    fixture = _fixture()
    with pytest.raises(TypeError):
        evaluate_holdout(fixture)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        evaluate_holdout(fixture, catalog=DEFAULT_MODEL_CATALOG)  # type: ignore[call-arg]
