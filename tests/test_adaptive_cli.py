"""CLI contract coverage for CC-216 adaptive-routing operator controls."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from genomes_agentic_os.cli import main


ROOT = Path(__file__).parents[1]
TEMPLATE = ROOT / "templates" / "runtime" / "adaptive-router.yml"
HOLDOUT = Path(__file__).parent / "fixtures" / "adaptive_routing_holdout.yml"


def _policy(
    tmp_path: Path,
    *,
    mode: str = "guarded",
    opt_out: str | None = None,
    economy_customer_safe: bool = True,
    default_tier: str | None = None,
) -> Path:
    data = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    layers = data["layers"]
    assert isinstance(layers, dict)
    host = layers["host"]
    assert isinstance(host, dict)
    host["mode"] = mode
    if default_tier is not None:
        host["default_tier"] = default_tier
    catalog = data["catalog"]
    assert isinstance(catalog, dict)
    models = catalog["models"]
    assert isinstance(models, list)
    assert isinstance(models[0], dict)
    models[0]["customer_safe"] = economy_customer_safe
    if opt_out:
        layer = layers[opt_out]
        assert isinstance(layer, dict)
        layer["mode"] = "off"
    path = tmp_path / "policy.yml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _output(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    captured = capsys.readouterr()
    assert not captured.err
    return json.loads(captured.out)


def test_plan_emits_canonical_redacted_snapshot_with_topology(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    policy = _policy(tmp_path)
    task = "Update Jira CC-216 status and add a triage label."

    assert main(["adaptive-routing", "plan", task, "--policy-file", str(policy)]) == 0
    first = _output(capsys)
    assert main(["adaptive-routing", "plan", task, "--policy-file", str(policy)]) == 0
    second = _output(capsys)

    assert first == second
    assert first["execution"] == "never"
    assert first["operation_status"] == "ready"
    assert first["topology"]["kind"] == "operator_only"  # type: ignore[index]
    serialized = json.dumps(first, sort_keys=True)
    assert task not in serialized
    assert str(policy) not in serialized


def test_observe_persists_one_text_free_idempotent_receipt(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "agentic_os"
    control = root / "harness/shared_factory/00-control-plane"
    control.mkdir(parents=True)
    config = yaml.safe_load(
        (ROOT / "templates/runtime/adaptive-routing-observation-report.yml").read_text()
    )
    config["enabled"] = True
    (control / "adaptive-routing-observation-report.yml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    policy = _policy(tmp_path, mode="observe")
    monkeypatch.setenv("CODEX_THREAD_ID", "019f49a2-e800-7253-966e-2164d765584f")
    task = "Update Jira CC-216 status and add a triage label."

    assert main([
        "adaptive-routing", "observe", task, "--root", str(root),
        "--policy-file", str(policy),
    ]) == 0
    first = _output(capsys)
    assert first["observation"]["status"] == "observed"  # type: ignore[index]
    assert main([
        "adaptive-routing", "observe", task, "--root", str(root),
        "--policy-file", str(policy),
    ]) == 0
    second = _output(capsys)
    assert second["observation"] == {"status": "already_observed", "written": False}

    ledger = root / config["observation_ledger"]
    content = ledger.read_text(encoding="utf-8")
    assert len(content.splitlines()) == 1
    assert task not in content


def test_plan_no_sub_agents_replans_complex_work_without_removing_verification(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    policy = _policy(tmp_path)

    assert main([
        "adaptive-routing", "plan", "Refactor the monolith across multiple modules.",
        "--policy-file", str(policy), "--no-sub-agents",
    ]) == 3
    result = _output(capsys)

    assert result["operation_status"] == "replan_required"
    assert result["blocker"] == "no_sub_agents_would_remove_required_verification"
    assert result["subagent_policy"]["accepted"] is False  # type: ignore[index]
    contracts = result["topology"]["contracts"]  # type: ignore[index]
    assert any(contract["role"] == "verifier" for contract in contracts)  # type: ignore[index]


@pytest.mark.parametrize("layer", ["project", "customer"])
def test_project_and_customer_opt_outs_monotonically_force_static_fallback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], layer: str
) -> None:
    policy = _policy(tmp_path, mode="enforce", opt_out=layer)

    assert main([
        "adaptive-routing", "plan", "Update Jira CC-216 status.", "--policy-file", str(policy),
    ]) == 0
    result = _output(capsys)

    assert result["operation_status"] == "static_fallback"
    assert result["rollout"]["lifecycle"] == "off"  # type: ignore[index]
    assert result["rollout"]["project_or_customer_opt_out"] == layer  # type: ignore[index]
    assert result["execution_plan"]["status"] == "static_fallback"  # type: ignore[index]


def test_evaluate_uses_explicit_approval_and_policy_bound_catalog_baseline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    policy = _policy(tmp_path, mode="enforce", default_tier="economy")
    assert main([
        "adaptive-routing", "evaluate", "--holdout-file", str(HOLDOUT),
        "--policy-file", str(policy), "--approve",
    ]) == 0
    result = _output(capsys)

    assert result["execution"] == "never"
    assert result["catalog"] == "built_in_default_model_catalog"
    assert len(result["runtime_policy_fingerprint"]) == 64
    assert result["baseline"] == "fixture_explicit_baseline"
    assert result["report"]["mode"] == "observe"  # type: ignore[index]
    assert result["report"]["guarded_mode"]["approval_granted"] is True  # type: ignore[index]


def test_enforce_requires_then_accepts_an_approved_no_breach_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    policy = _policy(tmp_path, mode="enforce", default_tier="economy")

    assert main(["adaptive-routing", "status", "--policy-file", str(policy)]) == 3
    blocked = _output(capsys)
    assert blocked["rollout"]["enforce_eligibility"]["eligible"] is False  # type: ignore[index]

    assert main([
        "adaptive-routing", "evaluate", "--holdout-file", str(HOLDOUT),
        "--policy-file", str(policy), "--approve",
    ]) == 0
    evaluation = _output(capsys)
    report_path = tmp_path / "approved-holdout.json"
    report_path.write_text(json.dumps(evaluation), encoding="utf-8")

    assert main([
        "adaptive-routing", "status", "--policy-file", str(policy),
        "--holdout-report", str(report_path),
    ]) == 0
    permitted = _output(capsys)
    assert permitted["rollout"]["enforce_eligibility"]["eligible"] is True  # type: ignore[index]


def test_enforce_rejects_holdout_bound_to_a_different_runtime_policy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first_dir = tmp_path / "first"
    first_dir.mkdir()
    second_dir = tmp_path / "second"
    second_dir.mkdir()
    evaluated_policy = _policy(first_dir, mode="enforce")
    other_policy = _policy(second_dir, mode="guarded")

    assert main([
        "adaptive-routing", "evaluate", "--holdout-file", str(HOLDOUT),
        "--policy-file", str(evaluated_policy), "--approve",
    ]) == 0
    evaluation = _output(capsys)
    report_path = tmp_path / "bound-report.json"
    report_path.write_text(json.dumps(evaluation), encoding="utf-8")

    # Change the second policy to enforce after its distinct guarded document
    # was not the policy evaluated by the holdout.
    data = yaml.safe_load(other_policy.read_text(encoding="utf-8"))
    data["layers"]["host"]["mode"] = "enforce"
    data["layers"]["host"]["default_tier"] = "frontier"
    other_policy.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    assert main([
        "adaptive-routing", "status", "--policy-file", str(other_policy),
        "--holdout-report", str(report_path),
    ]) == 3
    result = _output(capsys)
    assert result["rollout"]["enforce_eligibility"]["reason"] == (  # type: ignore[index]
        "holdout_runtime_policy_fingerprint_mismatch"
    )


def test_supplied_malformed_report_fails_in_non_enforce_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    policy = _policy(tmp_path, mode="guarded")
    report = tmp_path / "bad.json"
    report.write_text("{}", encoding="utf-8")

    assert main([
        "adaptive-routing", "status", "--policy-file", str(policy),
        "--holdout-report", str(report),
    ]) == 2
    assert "holdout report does not satisfy" in capsys.readouterr().err


def test_secret_shaped_owner_metadata_is_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    policy = _policy(tmp_path)
    assert main([
        "adaptive-routing", "plan", "Update Jira CC-216 status.",
        "--policy-file", str(policy), "--owner-id", "sk_live_supersecret",
        "--owner-kind", "workflow",
    ]) == 2
    assert "opaque, path-free" in capsys.readouterr().err


def test_customer_safe_policy_avoids_an_unsafe_candidate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    policy = _policy(tmp_path, economy_customer_safe=False)

    assert main([
        "adaptive-routing", "plan", "Update Jira CC-216 status and add a triage label.",
        "--policy-file", str(policy),
    ]) == 0
    result = _output(capsys)

    assert result["execution_plan"]["model_id"] == "gpt-5.6-terra"  # type: ignore[index]
    assert result["rollout"]["customer_safety"] == {  # type: ignore[index]
        "required": True,
        "eligible": True,
        "reason": "customer_safe_model",
    }


def test_rollback_plan_preserves_receipts_and_feature_62_without_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    policy = _policy(tmp_path, mode="guarded")
    known_directory = tmp_path / "known"
    known_directory.mkdir()
    last_known_good = _policy(known_directory, mode="observe")

    assert main([
        "adaptive-routing", "rollback-plan", "--policy-file", str(policy),
        "--last-known-good-policy-file", str(last_known_good),
    ]) == 0
    result = _output(capsys)
    rollback = result["rollback"]  # type: ignore[assignment]

    assert rollback["target_mode"] == "off"  # type: ignore[index]
    assert rollback["static_fallback"]["feature"] == "62-role-aware-codex-config-layers"  # type: ignore[index]
    assert rollback["receipt_path_semantics"] == {  # type: ignore[index]
        "historical_receipts": "preserve_unchanged", "write_path": None, "deletion": "forbidden",
    }
    assert str(policy) not in json.dumps(result)


def test_cli_rejects_partial_owner_override_with_stable_input_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    policy = _policy(tmp_path)

    assert main([
        "adaptive-routing", "plan", "Update Jira CC-216 status.", "--policy-file", str(policy),
        "--owner-id", "ticket-workflow",
    ]) == 2
    assert "owner override requires both owner identifier and owner kind" in capsys.readouterr().err
