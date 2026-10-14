"""Archive portability and historical CI handoff boundaries."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from genomes_agentic_os import development_delivery as delivery
from genomes_agentic_os import development_validation_refresh as refresh
from genomes_agentic_os.auto_dev_orchestration import (
    AutoDevStateError,
    _relink_moved_work_item,
    read_auto_dev_state,
    require_auto_dev_predecessors,
    sync_delivery_projection,
)
from test_development_validation_refresh import _bound, _family, _fixture, _refresh, _write


def _offline_pytest_repository(repo: Path, *, unavailable: bool = False) -> None:
    """Real installed pytest wheels, locked locally; no network or fake launcher."""
    import base64
    import csv
    import io
    from importlib.metadata import distribution
    import subprocess
    import sys
    import zipfile

    wheels = repo / "validation-wheels"
    wheels.mkdir()
    requirements, sources = [], []
    for name in ("pytest", "iniconfig", "packaging", "pluggy", "pygments"):
        dist = distribution(name)
        tag = next(line.split(": ", 1)[1] for line in dist.read_text("WHEEL").splitlines() if line.startswith("Tag: "))
        filename = name + "-" + dist.version + "-" + tag + ".whl"
        contents = {}
        for relative in dist.files:
            if ".." in relative.parts or "__pycache__" in relative.parts or relative.suffix == ".pyc":
                continue
            if relative.name in {"RECORD", "INSTALLER", "REQUESTED", "direct_url.json"}:
                continue
            path = dist.locate_file(relative)
            if path.is_file():
                contents[str(relative)] = path.read_bytes()
        metadata = next(value for value in contents if value.endswith(".dist-info/METADATA"))
        record = metadata.rsplit("/", 1)[0] + "/RECORD"
        rows = [[name, "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("="), str(len(data))]
                for name, data in sorted(contents.items())]
        stream = io.StringIO(); csv.writer(stream, lineterminator="\n").writerows([*rows, [record, "", ""]])
        contents[record] = stream.getvalue().encode()
        with zipfile.ZipFile(wheels / filename, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, data in contents.items():
                archive.writestr(path, data)
        requirements.append(name + "==" + dist.version)
        sources.append(name + ' = {path = "validation-wheels/' + filename + '"}')
    (repo / "pyproject.toml").write_text('[project]\nname = "validation-fixture"\nversion = "0.1.0"\nrequires-python = ">=3.11"\n'
        + "dependencies = " + json.dumps(requirements) + '\n[tool.uv]\npackage = false\nenvironments = ['
        + json.dumps("sys_platform == '" + sys.platform + "'") + ']\n[tool.uv.sources]\n' + "\n".join(sources) + "\n")
    (repo / ".gitignore").write_text(".venv/\n__pycache__/\n*.pyc\n.pytest_cache/\n")
    (repo / "tests").mkdir()
    body = ("import os,pytest\ndef test_execution():\n    if not os.environ.get('VALIDATION_REFRESH_FIXTURE_ENDPOINT'):\n"
            "        pytest.fail('Required disposable fixture endpoint is absent')\n" if unavailable
            else "def test_execution():\n    assert 2 + 2 == 4\n")
    (repo / "tests/test_execution.py").write_text(body)
    subprocess.run(["uv", "lock", "--offline", "--no-cache", "--project", str(repo)], check=True, capture_output=True, timeout=15)
    for args in (["add", "."], ["commit", "-m", "real offline locked pytest fixture"], ["push", "origin", "main"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.mark.parametrize("start_field", ["groom", None])
def test_modern_recorded_groom_or_missing_start_has_real_qualified_pytest_recovery(tmp_path, start_field):
    fixture = _fixture(tmp_path, mode="everything", python_runtime=True, repository_setup=_offline_pytest_repository)
    if start_field is None:
        current = fixture["task"].read()
        current.pop("auto_dev_start_stage")
        _write(fixture["task"].path, current)
    before = fixture["predecessor"].read_bytes()
    policy = Path(fixture["task"].read()["policy_receipt"])
    frozen = policy.read_bytes()
    result = _refresh(fixture)
    assert json.loads(Path(result["task"]["validation_refreshes"][-1]["successor_ref"]).read_text())["status"] == "passed"
    assert fixture["predecessor"].read_bytes() == before and policy.read_bytes() == frozen
    authority = refresh.pr_create_validation_authority(fixture["task"].path, json.loads(Path(_family(fixture)).read_text()))
    assert authority["head_sha"] == fixture["head"] and authority["status"] == "passed"
    assert authority.get("authority_scope") != "historical_pr_create_handoff"


def test_single_frozen_unavailable_command_has_actual_guarded_local_provenance(tmp_path):
    fixture = _fixture(tmp_path, mode="everything", deferred_successor=True, single_command_deferred=True)
    frozen = Path(fixture["task"].read()["policy_receipt"]).read_bytes()
    result = _refresh(fixture)
    assert json.loads(Path(result["task"]["validation_refreshes"][-1]["successor_ref"]).read_text())["status"] == "deferred_to_ci"
    assert Path(fixture["task"].read()["policy_receipt"]).read_bytes() == frozen
    authority = refresh.pr_create_validation_authority(fixture["task"].path, json.loads(Path(_family(fixture)).read_text()))
    assert authority["status"] == "deferred_to_ci" and authority["ci_authority"] == "pending"


def test_single_frozen_pytest_environment_failure_keeps_ci_pending(tmp_path):
    fixture = _fixture(tmp_path, mode="everything", python_runtime=True,
        repository_setup=lambda repo: _offline_pytest_repository(repo, unavailable=True),
        deferred_successor=True, single_command_deferred=True)
    predecessor = fixture["predecessor"].read_bytes()
    result = _refresh(fixture)
    assert json.loads(Path(result["task"]["validation_refreshes"][-1]["successor_ref"]).read_text())["status"] == "deferred_to_ci"
    assert fixture["predecessor"].read_bytes() == predecessor
    current = fixture["task"].read()
    assert not any(row["state"] == "ready_for_merge" for row in current["receipts"])
    authority = refresh.pr_create_validation_authority(fixture["task"].path, json.loads(Path(_family(fixture)).read_text()))
    assert authority["status"] == "deferred_to_ci" and authority["head_sha"] == fixture["head"] and authority["ci_authority"] == "pending"


@pytest.mark.parametrize("corruption", [
    "dependency_bytes", "runtime_redirect", "unbound_runtime", "foreign_task", "install_failed",
    "install_actor", "forged_install_check", "missing_validation_check", "selector", "policy", "source_lock",
])
def test_real_qualified_python_recovery_refuses_tamper_without_mutating_authority(tmp_path, corruption):
    fixture = _fixture(tmp_path, mode="everything", python_runtime=True, repository_setup=_offline_pytest_repository)
    request = json.loads(fixture["request"].read_text())
    proof = request["evidence"]["validation_runs"][0]
    closure_path = Path(proof["python_install_closure"]["path"])
    closure = json.loads(closure_path.read_text())
    runtime = Path(closure["runtime"])
    if corruption == "dependency_bytes":
        module = next(runtime.glob("lib/python*/site-packages/pytest/__init__.py"))
        module.write_text(module.read_text() + "\n# changed after the actual qualified install and pytest run\n")
    elif corruption == "runtime_redirect":
        module = next(runtime.glob("lib/python*/site-packages/pytest/__init__.py"))
        outside = tmp_path / "foreign.py"; outside.write_bytes(module.read_bytes())
        module.unlink(); module.symlink_to(outside)
    elif corruption == "unbound_runtime":
        for key in list(proof):
            if key.startswith("python_install_"):
                proof.pop(key)
        request["evidence"]["qualified_runtime"] = {"runtime": str(runtime), "trusted": True}
    elif corruption == "foreign_task":
        closure["binding"]["canonical_work_id"] = "foreign-task"
        _write(closure_path, closure); proof["python_install_closure"] = _bound(closure_path)
    elif corruption in {"install_failed", "forged_install_check"}:
        path = Path(proof["python_install_terminal"]["path"])
        payload = json.loads(path.read_text())
        if corruption == "install_failed":
            payload.update(status="failure", exit_code=1)
        else:
            payload["checks"][-1]["command"] = "echo 'caller supplied matching checksum'"
        _write(path, payload); proof["python_install_terminal"] = _bound(path)
    elif corruption == "install_actor":
        path = Path(proof["python_install_command"]["path"])
        payload = json.loads(path.read_text()); payload["mutation_lock"] = str(tmp_path / "foreign.lock")
        _write(path, payload); proof["python_install_command"] = _bound(path)
    elif corruption == "missing_validation_check":
        path = Path(proof["terminal"]["path"])
        payload = json.loads(path.read_text()); payload["checks"] = payload["checks"][:-1]
        _write(path, payload); proof["terminal"] = _bound(path)
    elif corruption == "selector":
        path = Path(proof["command_receipt"]["path"])
        payload = json.loads(path.read_text()); payload["command"].extend(["-k", "small"])
        _write(path, payload); proof["command_receipt"] = _bound(path)
    elif corruption == "policy":
        request["evidence"]["policy_fingerprint"] = "f" * 64
    else:
        lock = fixture["worktree"] / "uv.lock"; lock.write_text(lock.read_text() + "\n# modified source input\n")
    _write(fixture["request"], request)
    before = fixture["task"].path.read_bytes()
    policy = Path(fixture["task"].read()["policy_receipt"]).read_bytes()
    predecessor = fixture["predecessor"].read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError):
        _refresh(fixture)
    assert fixture["task"].path.read_bytes() == before
    assert Path(fixture["task"].read()["policy_receipt"]).read_bytes() == policy
    assert fixture["predecessor"].read_bytes() == predecessor


def test_python_runtime_qualification_cannot_override_disabled_ci_fallback(tmp_path):
    fixture = _fixture(tmp_path, mode="everything", python_runtime=True, fallback=False,
        repository_setup=lambda repo: _offline_pytest_repository(repo, unavailable=True),
        deferred_successor=True, single_command_deferred=True)
    before = fixture["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="pinned fallback policy"):
        _refresh(fixture)
    assert fixture["task"].path.read_bytes() == before


def _archived_fixture(tmp_path: Path, lane: str, *, legacy: bool = False) -> dict:
    fixture = _fixture(tmp_path, mode="everything", legacy=legacy)
    _refresh(fixture)
    current = fixture["task"].read()
    # The lifecycle may move a finished packet after delivery has completed.
    # Preserve the genuine refresh's receipts and lineage as recorded.
    current.update(state="delivery_complete", subject_revision=fixture["head"],
                   terminal_revision=fixture["head"])
    _write(fixture["task"].path, current)
    packet = fixture["packet"]
    archived = packet.parent / lane / packet.name
    archived.parent.mkdir(exist_ok=True)
    immutable = {
        path.relative_to(packet): path.read_bytes()
        for path in (packet / "artifacts/development-delivery/evidence").glob("*.json")
    }
    packet.rename(archived)
    _relink_moved_work_item(fixture["task"].path, archived / "autodev.json",
                           read_auto_dev_state(archived / "autodev.json"))
    return {**fixture, "archive": archived, "immutable": immutable, "original_task": current}


@pytest.mark.parametrize("lane", ["99-archived", "03-complete"])
@pytest.mark.parametrize("legacy", [False, True])
def test_archived_refresh_projects_without_rewriting_immutable_lineage(tmp_path, lane, legacy):
    fixture = _archived_fixture(tmp_path, lane, legacy=legacy)
    if legacy:
        # Archive inspection must not need a feature worktree already cleaned
        # by the owning lifecycle. Its prior attestation remains hash-bound.
        fixture["worktree"].rename(tmp_path / "removed-feature-worktree")
    projection = sync_delivery_projection(fixture["task"].path)

    assert projection["delivery"]["work_item"] == str(fixture["archive"])
    assert projection["delivery"]["state"] == "delivery_complete"
    after = fixture["task"].read()
    for key in ("receipts", "validation_refreshes", "validation_head_sha"):
        assert after[key] == fixture["original_task"][key]
    for relative, original in fixture["immutable"].items():
        assert (fixture["archive"] / relative).read_bytes() == original
    with pytest.raises(delivery.DevelopmentDeliveryError, match="modern local_validation"):
        refresh.pr_create_validation_authority(fixture["task"].path, {})


def test_corrupt_refresh_degrades_projection_to_its_failure_event(tmp_path):
    fixture = _fixture(tmp_path)
    _refresh(fixture)
    current = fixture["task"].read()
    current["validation_refreshes"][-1]["successor_sha256"] = "f" * 64
    _write(fixture["task"].path, current)
    projection = Path(current["autodev_path"])
    before = projection.read_bytes()

    assert delivery._sync_auto_dev_projection(fixture["task"].path) is None
    assert projection.read_bytes() == before
    events = (fixture["task"].path.parent / "events.jsonl").read_text()
    assert "development.autodev_projection.sync_failed" in events
    assert "SHA-256 binding changed" in events


@pytest.mark.parametrize("corruption", ["tampered_leaf", "foreign_packet", "symlink_leaf"])
def test_archive_rebase_never_admits_changed_or_out_of_packet_proof(tmp_path, corruption):
    fixture = _archived_fixture(tmp_path, "99-archived")
    row = fixture["original_task"]["validation_refreshes"][-1]
    original = Path(row["predecessor_ref"])
    moved = fixture["archive"] / original.relative_to(fixture["packet"])
    if corruption == "tampered_leaf":
        moved.write_bytes(moved.read_bytes() + b" ")
        with pytest.raises(AutoDevStateError, match="SHA-256 binding changed"):
            sync_delivery_projection(fixture["task"].path)
    else:
        foreign = tmp_path / "foreign/work-items" / fixture["packet"].name / original.relative_to(fixture["packet"])
        foreign.parent.mkdir(parents=True)
        foreign.write_bytes(moved.read_bytes())
        reference = {"path": str(original if corruption == "symlink_leaf" else foreign),
                     "sha256": hashlib.sha256(foreign.read_bytes()).hexdigest()}
        if corruption == "symlink_leaf":
            moved.unlink()
            moved.symlink_to(foreign)
        with pytest.raises(delivery.DevelopmentDeliveryError, match="contained packet file"):
            refresh._bound(reference, fixture["archive"])


@pytest.mark.parametrize("legacy", [False, True])
def test_recorded_default_defer_keeps_historical_pr_create_handoff(tmp_path, legacy):
    fixture = _fixture(tmp_path, changed=False, mode="default", annotated=True, legacy=legacy)
    original = fixture["predecessor"].read_bytes()
    before = fixture["task"].read()
    require_auto_dev_predecessors(before["autodev_path"], "pr_create")
    delivery.run_development_stage(fixture["task"].path, stage="release_propagation",
        receipts={"release_propagation": _family(fixture)}, idempotency_prefix="historical-handoff")
    wrapper = json.loads((fixture["task"].path.parent / "stages/release-propagation.json").read_text())
    authority = wrapper["validation_authority"]

    assert authority["status"] == "deferred_to_ci"
    assert authority["authority_scope"] == "historical_pr_create_handoff"
    assert authority["ci_authority"] == "pending"
    assert authority["current_validation_authority"] == "unproved"
    assert "head_sha" not in authority
    assert fixture["predecessor"].read_bytes() == original
    after = fixture["task"].read()
    assert after["receipts"] == before["receipts"]
    assert not after.get("validation_refreshes") and not after.get("validation_head_sha")
    assert not any(row["state"] == "ready_for_merge" for row in after["receipts"])


@pytest.mark.parametrize("delivery_link", [None, "not-a-mapping", {}])
def test_deferred_predecessor_reports_missing_task_link_without_traceback(tmp_path, delivery_link):
    fixture = _fixture(tmp_path, changed=False)
    path = Path(fixture["task"].read()["autodev_path"])
    manifest = read_auto_dev_state(path)
    manifest["delivery"] = delivery_link
    _write(path, manifest)
    with pytest.raises(AutoDevStateError, match="develop.*linked delivery task"):
        require_auto_dev_predecessors(path, "pr_create")


def test_modern_deferred_predecessor_keeps_concrete_refusal_reason(tmp_path):
    fixture = _fixture(tmp_path, changed=False)
    with pytest.raises(AutoDevStateError, match="unavailable-command proof"):
        require_auto_dev_predecessors(fixture["task"].read()["autodev_path"], "pr_create")


@pytest.mark.parametrize("marker", ["validation_runs", "repair_lineage"])
def test_narrower_window_cannot_downgrade_modern_evidence_to_historical_handoff(tmp_path, marker):
    fixture = _fixture(tmp_path, changed=False, mode="default")
    payload = json.loads(fixture["predecessor"].read_text())
    payload["evidence"][marker] = [] if marker == "validation_runs" else {}
    _write(fixture["predecessor"], payload)
    current = fixture["task"].read()
    current["receipts"][-1]["sha256"] = _bound(fixture["predecessor"])["sha256"]
    _write(fixture["task"].path, current)
    before = fixture["task"].path.read_bytes()
    with pytest.raises(AutoDevStateError, match="modern groom-through-PR-Create"):
        require_auto_dev_predecessors(current["autodev_path"], "pr_create")
    with pytest.raises(delivery.DevelopmentDeliveryError, match="modern groom-through-PR-Create"):
        refresh.pr_create_validation_authority(fixture["task"].path, json.loads(Path(_family(fixture)).read_text()))
    assert fixture["task"].path.read_bytes() == before


def test_forged_narrower_window_cannot_escape_frozen_modern_boundary(tmp_path):
    fixture = _fixture(tmp_path, changed=False, mode="everything")
    current = fixture["task"].read()
    current["auto_dev_start_stage"] = "readiness"
    _write(fixture["task"].path, current)
    manifest_path = Path(current["autodev_path"])
    manifest = read_auto_dev_state(manifest_path)
    manifest["start_stage"] = "readiness"
    _write(manifest_path, manifest)
    with pytest.raises(AutoDevStateError, match="pinned workflow boundary"):
        require_auto_dev_predecessors(manifest_path, "pr_create")


def test_historical_handoff_does_not_claim_old_checks_validated_a_repaired_head(tmp_path):
    fixture = _fixture(tmp_path, mode="default", legacy=True)
    authority = refresh.pr_create_validation_authority(
        fixture["task"].path, json.loads(Path(_family(fixture)).read_text()))
    assert authority["recorded_head_sha"] == fixture["old_head"]
    assert authority["pr_head_sha"] == fixture["head"]
    assert authority["current_validation_authority"] == "unproved"
    assert authority["ci_authority"] == "pending" and "head_sha" not in authority
    with pytest.raises(delivery.DevelopmentDeliveryError, match="current selected head"):
        refresh.pr_create_validation_authority(
            fixture["task"].path, json.loads(Path(_family(fixture, fixture["old_head"])).read_text()))


@pytest.mark.parametrize("origin_lane", ["", "02-active"])
def test_archive_reader_rebases_only_the_same_project_packet_origin(tmp_path, origin_lane):
    work_items = tmp_path / "project/work-items"
    origin = work_items / origin_lane / "same-item"
    archived = work_items / "99-archived/same-item"
    path = _write(origin / "artifacts/proof.json", {"schema": "historical-proof/v1"})
    ref = _bound(path)
    archived.parent.mkdir(parents=True)
    origin.rename(archived)
    logical, payload, digest = refresh._bound(ref, archived)
    assert logical == path and digest == ref["sha256"]
    assert payload["schema"] == "historical-proof/v1"
    # A duplicate original location is ambiguous, even with identical bytes.
    _write(path, payload)
    with pytest.raises(delivery.DevelopmentDeliveryError, match="contained packet file"):
        refresh._bound(ref, archived)


def test_archive_symlink_loop_is_a_typed_proof_failure(tmp_path):
    packet = tmp_path / "work-items/99-archived/item"
    path = packet / "artifacts/proof.json"
    path.parent.mkdir(parents=True)
    path.symlink_to(path.name)
    with pytest.raises(delivery.DevelopmentDeliveryError,
                       match="validation proof (path is unreadable|must be a contained packet file)"):
        refresh._bound({"path": str(path), "sha256": "0" * 64}, packet)


@pytest.mark.parametrize("origin", ["foreign_project", "duplicate_original"])
def test_archive_relink_refuses_foreign_or_duplicate_packet_identity(tmp_path, origin):
    fixture = _archived_fixture(tmp_path, "99-archived")
    current = fixture["task"].read()
    old_packet = fixture["packet"] if origin == "duplicate_original" else tmp_path / "foreign/work-items" / fixture["packet"].name
    old_packet.mkdir(parents=True)
    current["work_item"] = str(old_packet)
    _write(fixture["task"].path, current)
    before = fixture["task"].path.read_bytes()
    state_path = fixture["archive"] / "autodev.json"
    with pytest.raises(AutoDevStateError, match="ambiguous or cross-project"):
        _relink_moved_work_item(fixture["task"].path, state_path, read_auto_dev_state(state_path))
    assert fixture["task"].path.read_bytes() == before


@pytest.mark.parametrize("corruption", ["future_verified", "future_recorded", "mode_type", "start_type", "source_type", "worktree_type"])
def test_historical_handoff_refuses_malformed_or_future_identity_with_a_reason(tmp_path, corruption):
    fixture = _fixture(tmp_path, changed=False, mode="default", legacy=True)
    family = json.loads(Path(_family(fixture)).read_text())
    current = fixture["task"].read()
    manifest_path = Path(current["autodev_path"])
    manifest = read_auto_dev_state(manifest_path)
    if corruption == "future_verified":
        payload = json.loads(fixture["predecessor"].read_text())
        payload["verified_at"] = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
        _write(fixture["predecessor"], payload)
        current["receipts"][-1]["sha256"] = _bound(fixture["predecessor"])["sha256"]
    elif corruption == "future_recorded":
        current["receipts"][-1]["recorded_at"] = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    elif corruption == "mode_type":
        current["auto_dev_mode"] = ["default"]
    elif corruption == "start_type":
        current["auto_dev_start_stage"] = ["readiness"]
    elif corruption == "source_type":
        manifest["source"] = "not-a-mapping"
    else:
        current["worktree"] = manifest["delivery"]["worktree"] = None
    _write(fixture["task"].path, current)
    _write(manifest_path, manifest)
    before = fixture["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="historical CI handoff"):
        refresh.pr_create_validation_authority(fixture["task"].path, family)
    assert fixture["task"].path.read_bytes() == before
