import pytest

from genomes_agentic_os.auto_dev_orchestration import (
    AUTO_DEV_STAGE_COMMANDS,
    AUTO_DEV_STAGE_ORDER,
    AutoDevStateError,
    _readiness_stage_authority,
    validate_auto_dev_stage_order,
)


def _authority(**extra):
    value = {
        "provider": "github",
        "pull_request": "26874",
        "repository": "lenderscooperative/los",
        "base_branch": "hotfix/v9.12.8",
        "author_identity": "github:michaelwclark",
        "author_kind": "ours",
        "readback_verified": True,
        "readiness_decision": "ready_for_merge",
        "check_matrix": [
            {"check_id": check_id, "status": "pass"}
            for check_id in (
                "jira_github_alignment",
                "exact_release_identity",
                "qa_per_jira",
                "whole_diff_policy",
                "risk_gates",
                "artifact_rollback_observability",
                "runtime_consumer_contracts",
            )
        ],
        "qa_runs": [{"jira": "FLYWL-3486", "status": "pass"}],
        "consumer_contract_matrix": [
            {
                "consumer_id": "applicable-documents:hanmi",
                "status": "pass",
                "evidence_ref": "tests/services/test_views.py::test_legacy_and_canonical_payloads",
            }
        ],
        "tenant_impact_matrix": [
            {
                "tenant": "hanmi",
                "status": "pass",
                "evidence_ref": "runtime:fixture:hanmi",
            }
        ],
        "compatibility_strategy": "preserve flat product_code until every rule is migrated",
        "contract_test_runs": ["tests/services/test_views.py::test_legacy_and_canonical_payloads"],
        "runtime_readbacks": ["fixture:hanmi:applicable-documents"],
        "independent_review": {"status": "pass", "reviewer": "test:independent"},
        "policy_fingerprint": "sha256:policy",
        "provider_readbacks": [{"provider": "github", "status": "pass"}],
    }
    value.update(extra)
    return value


def test_validate_production_release_is_a_required_pre_merge_stage():
    assert AUTO_DEV_STAGE_ORDER.index("finalize") < AUTO_DEV_STAGE_ORDER.index(
        "validate_production_release"
    ) < AUTO_DEV_STAGE_ORDER.index("merge")
    assert AUTO_DEV_STAGE_COMMANDS["validate_production_release"] == (
        "/auto-dev-validate-production-release"
    )
    validate_auto_dev_stage_order(AUTO_DEV_STAGE_ORDER)


def test_validate_production_release_requires_complete_receipt():
    evidence = {"evidence": _authority()}
    authority = _readiness_stage_authority(
        "validate_production_release", evidence, "abc123"
    )
    assert authority["author_kind"] == "ours"

    for field in (
        "check_matrix",
        "policy_fingerprint",
        "provider_readbacks",
        "compatibility_strategy",
        "contract_test_runs",
        "runtime_readbacks",
    ):
        missing = _authority()
        missing.pop(field)
        with pytest.raises(AutoDevStateError, match=field):
            _readiness_stage_authority(
                "validate_production_release", {"evidence": missing}, "abc123"
            )

    incomplete_matrix = _authority()
    incomplete_matrix["consumer_contract_matrix"] = [{"status": "pass"}]
    with pytest.raises(AutoDevStateError, match="consumer_contract_matrix"):
        _readiness_stage_authority(
            "validate_production_release", {"evidence": incomplete_matrix}, "abc123"
        )

    missing_runtime_contract_check = _authority()
    missing_runtime_contract_check["check_matrix"] = [
        row
        for row in missing_runtime_contract_check["check_matrix"]
        if row["check_id"] != "runtime_consumer_contracts"
    ]
    with pytest.raises(AutoDevStateError, match="runtime_consumer_contracts"):
        _readiness_stage_authority(
            "validate_production_release",
            {"evidence": missing_runtime_contract_check},
            "abc123",
        )


def test_validate_production_release_rejects_other_pr_authorship():
    with pytest.raises(AutoDevStateError, match="author_kind=ours"):
        _readiness_stage_authority(
            "validate_production_release",
            {"evidence": _authority(author_kind="others")},
            "abc123",
        )
