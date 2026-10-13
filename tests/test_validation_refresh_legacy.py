"""Legacy task-bound validation identity and item-owned artifact regressions."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from genomes_agentic_os import development_delivery as delivery
from genomes_agentic_os import development_validation_refresh as refresh
from test_development_validation_refresh import _bound, _document, _family, _fixture, _refresh, _write


def test_genuinely_recorded_legacy_shape_refreshes_without_rewriting_history(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, legacy=True)
    before = fixture["task"].read()
    original = fixture["predecessor"].read_bytes()

    result = _refresh(fixture)
    after = result["task"]

    assert fixture["predecessor"].read_bytes() == original
    assert after["receipts"][:-1] == before["receipts"]
    assert after["state"] == before["state"]
    assert after.get("subject_revision") is None
    assert after["validation_head_sha"] == fixture["head"]
    authority = after["validation_refreshes"][-1]["predecessor_identity_attestation"]
    assert authority["schema"] == "development-validation-predecessor-attestation/v1"
    assert authority["kind"] == "task_bound_legacy_identity"
    assert authority["predecessor_sha256"] == before["receipts"][-1]["sha256"]
    assert _refresh(fixture)["replayed"] is True


def test_only_configured_registered_item_artifacts_are_admitted(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    ticket = fixture["task"].read()["ticket"]
    artifact = fixture["worktree"] / ".features" / ticket / "checks" / "watch-state.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text('{"status":"success"}\n')
    original = artifact.read_bytes()

    assert _refresh(fixture)["task"]["validation_head_sha"] == fixture["head"]
    assert artifact.read_bytes() == original


@pytest.mark.parametrize("corruption", [
    "ticket", "repository", "policy_fingerprint", "explicit_null", "foreign_row",
    "missing_row", "wrong_stage", "future_verification", "pre_task_verification",
    "foreign_head", "manifest_ticket", "manifest_repository", "manifest_policy",
])
def test_legacy_attestation_rejects_contradictions_before_mutation(tmp_path: Path, corruption: str) -> None:
    fixture = _fixture(tmp_path, legacy=True)
    current = fixture["task"].read()
    old = json.loads(fixture["predecessor"].read_text())
    request = json.loads(fixture["request"].read_text())
    if corruption in {"ticket", "repository", "policy_fingerprint"}:
        old["evidence"][corruption] = "foreign"
    elif corruption == "explicit_null":
        old["evidence"]["ticket"] = None
    elif corruption == "foreign_row":
        current["receipts"][-1]["ref"] = str(fixture["packet"] / "foreign.json")
    elif corruption == "missing_row":
        current["receipts"].pop()
    elif corruption == "wrong_stage":
        old["stage"] = "review"
    elif corruption == "future_verification":
        old["verified_at"] = "2099-01-01T00:00:00Z"
    elif corruption == "pre_task_verification":
        old["verified_at"] = "2000-01-01T00:00:00Z"
    elif corruption == "foreign_head":
        old["evidence"]["subject_revision"] = "0" * 40
        request["evidence"]["repair_lineage"]["from_head_sha"] = "0" * 40
    else:
        manifest_path = Path(current["autodev_path"])
        manifest = json.loads(manifest_path.read_text())
        if corruption == "manifest_ticket":
            manifest["source"]["key"] = "FOREIGN-1"
        elif corruption == "manifest_repository":
            manifest["delivery"]["repository"]["id"] = "git:github.com/other/app"
        else:
            manifest["delivery"]["policy_fingerprint"] = "0" * 64
        _write(manifest_path, manifest)
    _write(fixture["predecessor"], old)
    if corruption not in {"foreign_row", "missing_row"}:
        current["receipts"][-1]["sha256"] = _bound(fixture["predecessor"])["sha256"]
    _write(fixture["task"].path, current)
    request["evidence"]["repair_lineage"]["predecessor"] = _bound(fixture["predecessor"])
    _write(fixture["request"], request)
    before = fixture["task"].path.read_bytes()

    with pytest.raises(delivery.DevelopmentDeliveryError):
        _refresh(fixture)

    assert fixture["task"].path.read_bytes() == before
    assert not list((fixture["packet"] / "artifacts/development-delivery/evidence").glob("validation-refresh-*"))

def test_disabled_frozen_fallback_refuses_genuine_environment_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("VALIDATION_REFRESH_FIXTURE_ENDPOINT", raising=False)
    fixture = _fixture(tmp_path, fallback=False, deferred_successor=True)
    before = fixture["task"].path.read_bytes()

    with pytest.raises(delivery.DevelopmentDeliveryError, match="fallback"):
        _refresh(fixture)

    assert fixture["task"].path.read_bytes() == before
    assert not list((fixture["packet"] / "artifacts/development-delivery/evidence").glob("validation-refresh-*"))


@pytest.mark.parametrize("corruption", [
    "foreign_item", "source_file", "executable", "symlink_file", "symlink_namespace", "wrong_config",
])
def test_artifact_admission_cannot_hide_foreign_or_executable_source(tmp_path: Path, corruption: str) -> None:
    fixture = _fixture(tmp_path)
    ticket = fixture["task"].read()["ticket"]
    owned = fixture["worktree"] / ".features" / ticket
    owned.mkdir(parents=True)
    artifact = owned / "watch-state.json"
    if corruption == "foreign_item":
        foreign = owned.parent / "FOREIGN-1"
        foreign.mkdir()
        (foreign / "watch-state.json").write_text("{}")
    elif corruption == "source_file":
        (owned / "helper.py").write_text("raise RuntimeError('untracked source')")
    elif corruption == "executable":
        artifact.write_text("{}")
        artifact.chmod(0o755)
    elif corruption == "symlink_file":
        outside = tmp_path / "outside.json"
        outside.write_text("{}")
        artifact.symlink_to(outside)
    elif corruption == "symlink_namespace":
        owned.rmdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "watch-state.json").write_text("{}")
        owned.symlink_to(outside, target_is_directory=True)
    else:
        import yaml
        project = fixture["packet"].parent.parent
        config = project / "config/output-artifacts.yml"
        contents = yaml.safe_load(config.read_text())
        contents["output_artifacts"]["legacy_source_feature_root"] = "src/tests/{ticket_or_slug}"
        config.write_text(yaml.safe_dump(contents))
        artifact.write_text("{}")
    before = fixture["task"].path.read_bytes()

    with pytest.raises(delivery.DevelopmentDeliveryError):
        _refresh(fixture)

    assert fixture["task"].path.read_bytes() == before


def test_actual_unavailable_frozen_command_preserves_ci_pending_authority(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("VALIDATION_REFRESH_FIXTURE_ENDPOINT", raising=False)
    fixture = _fixture(tmp_path, legacy=True, deferred_successor=True)
    original = fixture["predecessor"].read_bytes()

    result = _refresh(fixture)
    row = result["task"]["receipts"][-1]
    payload = json.loads(Path(row["ref"]).read_text())

    assert payload["status"] == "deferred_to_ci"
    assert payload["evidence"]["unavailable_check"]["exit_code"] == 17
    assert fixture["predecessor"].read_bytes() == original
    assert result["task"].get("subject_revision") is None
    assert result["readiness_projection"]["status"] == "unknown"
    assert _refresh(fixture)["replayed"] is True
    _document(fixture)
    delivery.run_development_stage(fixture["task"].path, stage="release_propagation",
        receipts={"release_propagation": _family(fixture)}, idempotency_prefix="deferred-family")
    wrapper = json.loads((fixture["task"].path.parent / "stages/release-propagation.json").read_text())
    assert wrapper["validation_authority"]["status"] == "deferred_to_ci"
    assert wrapper["validation_authority"]["ci_authority"] == "pending"
    from genomes_agentic_os.auto_dev_orchestration import _validate_health_stage_source
    admitted = _validate_health_stage_source(fixture["packet"], "develop", "completed", Path(row["ref"]))
    assert admitted["status"] == "deferred_to_ci"
    assert not any(row["state"] == "ready_for_merge" for row in fixture["task"].read()["receipts"])


@pytest.mark.parametrize("corruption", [
    "mark_passed", "code_failure", "wrong_exit", "boolean_exit", "wrong_terminal",
    "unexecuted_failure", "partial_commands", "scoped_command",
])
def test_ci_deferral_cannot_promote_failed_or_unexecuted_validation(tmp_path: Path, monkeypatch, corruption: str) -> None:
    monkeypatch.delenv("VALIDATION_REFRESH_FIXTURE_ENDPOINT", raising=False)
    fixture = _fixture(tmp_path, deferred_successor=True)
    payload = json.loads(fixture["request"].read_text())
    unavailable = payload["evidence"]["unavailable_check"]
    runs = payload["evidence"]["validation_runs"]
    if corruption == "mark_passed":
        payload["status"] = "passed"
        payload["evidence"].pop("unavailable_check")
    elif corruption == "code_failure":
        unavailable["classification"] = "code_failure"
    elif corruption == "wrong_exit":
        unavailable["exit_code"] = 1
    elif corruption == "boolean_exit":
        unavailable["exit_code"] = True
    elif corruption == "wrong_terminal":
        unavailable["receipt_ref"] = runs[0]["terminal"]["path"]
    elif corruption == "unexecuted_failure":
        runs[-1]["terminal"] = runs[0]["terminal"]
    elif corruption == "partial_commands":
        runs.pop()
    else:
        path = Path(runs[-1]["command_receipt"]["path"])
        command = json.loads(path.read_text())
        command["command"].append("--scoped-only")
        _write(path, command)
        runs[-1]["command_receipt"] = _bound(path)
    _write(fixture["request"], payload)
    before = fixture["task"].path.read_bytes()

    with pytest.raises(delivery.DevelopmentDeliveryError):
        _refresh(fixture)

    assert fixture["task"].path.read_bytes() == before

