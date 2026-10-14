"""Exercise user-facing intake persistence; use synthetic definitions only."""
import copy
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

SCRIPT = Path(__file__).resolve().parents[1] / "harness/bin/agentic-os-atlas-registry"
API = runpy.run_path(str(SCRIPT), run_name="atlas_registry_test")
SCHEMA = json.loads((SCRIPT.parents[2] / "schemas/atlas-task-intake.schema.json").read_text())


def schema_validate(value):
    Draft202012Validator(SCHEMA, format_checker=FormatChecker()).validate(value)


@pytest.fixture
def root(tmp_path):
    (tmp_path / ".agentic_root").write_text("test = true\n")
    return tmp_path


@pytest.fixture
def intake():
    return {"schema": "atlas-task-intake/v1", "source": {"system": "chatgpt_cloud_automations", "observed_at": "2026-10-06T20:46:00Z", "reference": "synthetic listing", "snapshot_scope": "partial"}, "explicit_user_request": {"reference": "synthetic explicit request", "requested_at": "2026-10-06T20:00:00Z"}, "privacy": {"attested_by": "synthetic operator", "task_definitions_only": True, "excluded_sensitive_content": True}, "tasks": [{"id": "synthetic-1", "title": "Synthetic public research", "prompt": "Research public documentation.\nPreserve exact punctuation: café’s.", "is_enabled": True, "default_timezone": "America/Chicago", "timing_mode": "flexible_schedule", "schedule": "BEGIN:VEVENT\nDTSTART;TZID=America/Chicago:20261007T080000\nRRULE:FREQ=DAILY;BYHOUR=8;BYMINUTE=0;BYSECOND=0\nEND:VEVENT", "registration_status": "registered", "destinations": [{"kind": "brief", "reference": "synthetic destination", "verification": "unverified"}], "workflow": {key: ["Synthetic " + key] for key in ["inputs", "process", "outputs", "review", "handoff"]}}]}


def apply(root, intake):
    API["validate_input"](intake)
    preview = API["execute_import"](root, intake)
    return API["execute_import"](root, intake, True, preview["expected_generation"])


def locator(root, value):
    path = root / "harness/config/atlas-work-registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


def test_generic_home_and_configured_project_home_preserve_same_id(root, intake):
    assert API["home"](root) == root / "artifacts/atlas-work-registry"
    relative = "domains/example/02-projects/sample/artifacts/atlas-work-registry"
    config = locator(root, {"schema": "atlas-registry-location/v1", "relative_home": relative})
    before = config.read_bytes()
    first = apply(root, intake)
    assert API["home"](root) == root / relative
    assert API["validate_store"](root)["generation"] == first["generation"]
    assert apply(root, intake)["status"] == "unchanged"
    assert config.read_bytes() == before
    assert not (root / "artifacts").exists()


@pytest.mark.parametrize("relative", ["", None, "/tmp/artifacts/atlas-work-registry", "../artifacts/atlas-work-registry", "harness", "harness/artifacts/atlas-work-registry", "lib/artifacts/atlas-work-registry", "artifacts/atlas-work-registry\x00", "x" * 1001])
def test_locator_refuses_invalid_or_protected_home_without_fallback(root, relative):
    locator(root, {"schema": "atlas-registry-location/v1", "relative_home": relative})
    with pytest.raises(API["Refusal"]):
        API["home"](root)
    assert not (root / "artifacts").exists()


@pytest.mark.parametrize("value", [{"schema": "bad", "relative_home": "artifacts/atlas-work-registry"}, {"schema": "atlas-registry-location/v1", "relative_home": "artifacts/atlas-work-registry", "extra": True}])
def test_locator_refuses_unknown_schema_and_fields(root, value):
    locator(root, value)
    with pytest.raises(API["Refusal"]):
        API["home"](root)


@pytest.mark.parametrize("relative", ["harness", "harness/config"])
def test_locator_refuses_invalid_ancestors_without_fallback(root, relative):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not-a-directory")
    with pytest.raises(API["Refusal"]):
        API["home"](root)
    assert not (root / "artifacts").exists()


def test_locator_refuses_broken_symlink_ancestors_and_oversized_file(root):
    config = locator(root, {"schema": "atlas-registry-location/v1", "relative_home": "artifacts/atlas-work-registry"})
    config.unlink()
    config.symlink_to(root / "missing")
    with pytest.raises(API["Refusal"]):
        API["home"](root)

    config.unlink()
    config.write_text(" " * 4097)
    with pytest.raises(API["Refusal"]):
        API["home"](root)
    config.unlink()
    config.parent.rmdir()
    config.parent.symlink_to(root / "missing-parent")
    with pytest.raises(API["Refusal"]):
        API["home"](root)


def test_bad_locator_cli_refuses_store_but_pending_sync_still_stages(root, intake):
    config = locator(root, {})
    config.write_text("not-json")
    path = root / "intake.json"
    path.write_text(json.dumps(intake))
    prefix = [sys.executable, str(SCRIPT), "--root", str(root)]
    refused = subprocess.run(prefix + ["status"], capture_output=True, text=True)
    assert refused.returncode == 2
    assert json.loads(refused.stderr)["status"] == "refused"
    pending = subprocess.run(prefix + ["pending-sync", "--input", str(path), "--pending-dir", str(root / "pending")], capture_output=True, text=True)
    assert pending.returncode == 0
    assert json.loads(pending.stdout)["status"] == "pending_sync"
    assert not (root / "artifacts").exists()


def next_input(intake, status=None):
    value = copy.deepcopy(intake)
    value["source"]["observed_at"] = "2026-10-07T20:46:00Z"
    if status:
        value["tasks"][0]["registration_status"] = status
    return value


def test_dry_run_has_no_writes_and_apply_exact_prompt_history(root, intake):
    before = list(root.rglob("*"))
    preview = API["execute_import"](root, intake)
    assert preview["status"] == "preview"
    assert list(root.rglob("*")) == before
    outcome = apply(root, intake)
    store = API["home"](root)
    task = store / "current/tasks/chatgpt-synthetic-1"
    assert (task / "prompt.txt").read_bytes() == intake["tasks"][0]["prompt"].encode()
    assert len(list((task / "revisions").iterdir())) == 1
    assert API["validate_store"](root)["task_count"] == 1
    assert outcome["execution_effects"] == 0


def test_repeat_import_does_not_create_generation_or_revision(root, intake):
    first = apply(root, intake)
    second = apply(root, intake)
    assert second["status"] == "unchanged"
    assert first["generation"] == second["generation"]
    assert len(list((API["home"](root) / "generations").iterdir())) == 1


def test_upsert_same_id_preserves_history_and_deduplicates_prompt(root, intake):
    apply(root, intake)
    update = next_input(intake)
    update["tasks"][0]["title"] = "Renamed public research"
    apply(root, update)
    folder = API["home"](root) / "current/tasks/chatgpt-synthetic-1"
    assert len(list((folder / "revisions").iterdir())) == 2
    assert len(list((folder / "prompts").iterdir())) == 1
    assert API["validate_store"](root)["task_count"] == 1


def test_generation_conflict_and_same_time_conflict_refuse(root, intake):
    preview = API["execute_import"](root, intake)
    apply(root, intake)
    with pytest.raises(API["Refusal"], match="generation conflict"):
        API["execute_import"](root, intake, True, preview["expected_generation"])
    changed = copy.deepcopy(intake)
    changed["tasks"][0]["prompt"] = "Different public task"
    with pytest.raises(API["Refusal"], match="same-time"):
        API["execute_import"](root, changed)


def test_stale_snapshot_cannot_overwrite_current(root, intake):
    apply(root, next_input(intake))
    with pytest.raises(API["Refusal"], match="stale snapshot"):
        API["execute_import"](root, intake)


def test_cancellation_cannot_be_revived_or_erased_by_rollback(root, intake):
    initial = apply(root, intake)
    canceled = apply(root, next_input(intake, "canceled"))
    revival = next_input(intake)
    revival["source"]["observed_at"] = "2026-10-08T20:46:00Z"
    with pytest.raises(API["Refusal"], match="cannot be revived"):
        API["execute_import"](root, revival)
    with pytest.raises(API["Refusal"], match="erase a cancellation"):
        API["rollback"](root, initial["generation"], canceled["generation"], True)
    assert API["current"](API["home"](root))[0] == canceled["generation"]


def test_pending_approval_stays_separate_from_cloud_enabled(root, intake):
    intake["tasks"][0]["registration_status"] = "pending_approval"
    apply(root, intake)
    entry = API["current"](API["home"](root))[1]["tasks"]["chatgpt-synthetic-1"]["current"]
    assert entry["definition"]["is_enabled"] is True
    assert entry["definition"]["registration_status"] == "pending_approval"
    assert entry["execution_authority"] == "chatgpt_cloud_automations"


@pytest.mark.parametrize("change", ["duplicate", "unknown", "privacy", "secret", "id", "timestamp", "trigger"])
def test_input_rejections_before_writes(root, intake, change):
    if change == "duplicate":
        intake["tasks"].append(copy.deepcopy(intake["tasks"][0]))
    elif change == "unknown":
        intake["conversation"] = "prohibited payload"
    elif change == "privacy":
        intake["privacy"]["excluded_sensitive_content"] = False
    elif change == "secret":
        intake["tasks"][0]["prompt"] = " ".join(("-----BEGIN", "PRIVATE", "KEY-----", "synthetic"))
    elif change == "id":
        intake["tasks"][0]["id"] = "../outside"
    elif change == "timestamp":
        intake["source"]["observed_at"] = "2026-10-06T20:46:00"
    else:
        intake["tasks"][0]["schedule"] = "BEGIN:VEVENT\nX-UNSCHEDULED:1\nEND:VEVENT"
    with pytest.raises(API["Refusal"]):
        API["validate_input"](intake)
    assert not (root / API["RELATIVE_HOME"]).exists()


def test_missing_partial_snapshot_retains_records(root, intake):
    apply(root, intake)
    added = next_input(intake)
    added["tasks"][0]["id"] = "synthetic-2"
    outcome = apply(root, added)
    assert outcome["missing_from_snapshot"] == ["chatgpt-synthetic-1"]
    assert API["validate_store"](root)["task_count"] == 2


def test_rollback_preview_and_apply_with_expected_generation(root, intake):
    first = apply(root, intake)
    second = apply(root, next_input(intake))
    API["rollback"](root, first["generation"], second["generation"])
    assert API["current"](API["home"](root))[0] == second["generation"]
    API["rollback"](root, first["generation"], second["generation"], True)
    assert API["current"](API["home"](root))[0] == first["generation"]


def test_prompt_tamper_detected(root, intake):
    apply(root, intake)
    path = API["home"](root) / "current/tasks/chatgpt-synthetic-1/prompt.txt"
    path.write_text("tampered")
    with pytest.raises(API["Refusal"], match="prompt readback"):
        API["validate_store"](root)


def test_interrupted_publication_preserves_old_pointer_and_retries(root, intake):
    first = apply(root, intake)
    globals_ = API["execute_import"].__globals__
    original = globals_["publish_pointer"]
    def fail(*args):
        raise OSError("simulated publication interruption")
    globals_["publish_pointer"] = fail
    try:
        with pytest.raises(OSError):
            apply(root, next_input(intake))
    finally:
        globals_["publish_pointer"] = original
    assert API["current"](API["home"](root))[0] == first["generation"]
    assert apply(root, next_input(intake))["status"] == "applied"


def test_new_work_blocked_intake_is_not_another_cloud_schedule(root, intake):
    apply(root, intake)
    request = next_input(intake)
    request["source"]["system"] = "explicit_user_requests"
    task = request["tasks"][0]
    for key in ["is_enabled", "default_timezone", "timing_mode", "schedule"]:
        del task[key]
    task.update(prompt_capture="summary_only", registration_status="blocked", components=["Synthetic service"], dependencies=["Confirm host and authorization"])
    outcome = apply(root, request)
    assert outcome["missing_from_snapshot"] == []
    value = API["current"](API["home"](root))[1]
    assert len(value["tasks"]) == 2
    assert "schedule" not in value["tasks"]["request-synthetic-1"]["current"]["definition"]
    assert value["tasks"]["request-synthetic-1"]["current"]["definition"]["registration_status"] == "blocked"


def test_unavailable_root_cli_pending_sync_is_idempotent_and_private(tmp_path, intake):
    path = tmp_path / "input.json"
    path.write_text(json.dumps(intake))
    command = [sys.executable, str(SCRIPT), "--root", str(tmp_path / "missing"), "pending-sync", "--input", str(path), "--pending-dir", str(tmp_path / "pending")]
    first = subprocess.run(command, capture_output=True, text=True)
    second = subprocess.run(command, capture_output=True, text=True)
    assert first.returncode == second.returncode == 0
    assert json.loads(first.stdout)["status"] == "pending_sync"
    assert len(list((tmp_path / "pending").iterdir())) == 1
    assert next((tmp_path / "pending").iterdir()).stat().st_mode & 0o777 == 0o600
    assert not (tmp_path / "missing").exists()


def test_symlink_escape_refused(root, tmp_path, intake):
    target = root / API["RELATIVE_HOME"]
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "outside", target_is_directory=True)
    with pytest.raises(API["Refusal"], match="escapes|symlink"):
        API["execute_import"](root, intake)


def test_no_scheduler_service_or_queue_mutation(root, intake):
    sentinels = [root / "harness/config/execution-fabric.yml", root / "harness/shared_factory/00-control-plane/runtime-registry.yml"]
    for sentinel in sentinels:
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.write_text("operator sentinel")
    apply(root, intake)
    assert all(path.read_text() == "operator sentinel" for path in sentinels)


def test_cli_errors_do_not_echo_private_input(tmp_path, intake):
    intake["tasks"][0]["prompt"] = "-----BEGIN PRIVATE KEY----- DO-NOT-ECHO-ME"
    path = tmp_path / "input.json"
    path.write_text(json.dumps(intake))
    result = subprocess.run([sys.executable, str(SCRIPT), "import", "--input", str(path)], capture_output=True, text=True)
    assert result.returncode == 2
    assert "DO-NOT-ECHO-ME" not in result.stderr + result.stdout


@pytest.mark.parametrize("prefix", ["ghp_", "github_pat_", "AKIA", "Authorization: Bearer ", "client_secret="])
def test_common_accidental_credentials_rejected(intake, prefix):
    intake["tasks"][0]["prompt"] = prefix + ("A" * 16 if prefix == "AKIA" else "a" * 32)
    with pytest.raises(API["Refusal"], match="privacy scan"):
        API["validate_input"](intake)


@pytest.mark.parametrize("surface", ["generations", ".lock", "registry.json", "prompt_snapshot"])
def test_redirected_generation_surfaces_refused(root, tmp_path, intake, surface):
    applied = apply(root, intake)
    store = API["home"](root)
    if surface == "generations":
        target = store / "generations"
        destination = root / "saved-generations"
        target.rename(destination)
        target.symlink_to(destination)
    elif surface == ".lock":
        target = store / ".lock"
        target.unlink()
        target.symlink_to(root / "foreign-lock")
    else:
        folder = store / "current/tasks/chatgpt-synthetic-1"
        target = store / "current/registry.json" if surface == "registry.json" else next((folder / "prompts").iterdir())
        destination = root / "saved-file"
        destination.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(destination)
    with pytest.raises(API["Refusal"], match="redirect"):
        API["current"](store)
    with pytest.raises(API["Refusal"], match="redirect"):
        API["rollback"](root, applied["generation"], applied["generation"], True)


def channel_binding(verification="provider_verified"):
    return {"workspace_id": "TSYNTH001", "channel_id": "CSYNTH001", "relation": "destination", "verification": verification, "evidence_ref": "Synthetic provider identity readback"}


def component_binding():
    return {"kind": "workflow", "reference": "workflow:domain:example:public_research", "repository": "https://github.com/example/workflows", "path": "lib/workflows/domains/example/public_research/object.yml", "revision": "a" * 40, "sha256": hashlib.sha256(b"synthetic source definition\n").hexdigest(), "ownership": {"scope": "domain", "domain": "example"}, "verification": "source_verified"}


def test_channel_inventory_groups_verified_pairs_without_content_or_writes(root, intake):
    task = intake["tasks"][0]
    task["title"] = "PRIVATE TITLE SENTINEL"
    task["prompt"] = "PRIVATE PROMPT SENTINEL"
    task["workflow"]["inputs"] = ["PRIVATE WORKFLOW SENTINEL"]
    intake["source"]["reference"] = "PRIVATE SOURCE SENTINEL"
    task["destinations"] = [{"kind": "slack", "reference": "TSYNTH001/CSYNTH001 (#PRIVATE_NAME_SENTINEL)", "verification": "provider_verified"}]
    task["ownership"] = {"scope": "domain", "domain": "example"}
    task["component_bindings"] = [component_binding()]
    first = apply(root, intake)
    store = API["home"](root)
    before = {p.relative_to(store).as_posix(): p.read_bytes() for p in store.rglob("*") if p.is_file()}
    result = API["channels"](root)
    row = result["channels"][0]["tasks"][0]
    assert result["channels"][0]["workspace_id"] == "TSYNTH001"
    assert result["candidates"] == result["ungrouped"] == []
    assert row["source_id"] == "synthetic-1" and row["revision"] == 1
    assert row["prompt_sha256"] == hashlib.sha256(task["prompt"].encode()).hexdigest()
    assert row["cadence"]["schedule_sha256"] == hashlib.sha256(task["schedule"].encode()).hexdigest()
    assert row["ownership"] == task["ownership"]
    assert row["component_bindings"] == task["component_bindings"]
    assert row["source_observed_at"] == intake["source"]["observed_at"]
    assert row["requested_at"] == intake["explicit_user_request"]["requested_at"]
    assert "PRIVATE" not in json.dumps(result)
    assert result["execution_effects"] == 0 and result["generation"] == first["generation"]
    assert result["coverage"]["historical_source_coverage"] == "not_verified"
    assert result["audience_authorization"] == "not_established_by_inventory"
    assert {p.relative_to(store).as_posix(): p.read_bytes() for p in store.rglob("*") if p.is_file()} == before


def test_channel_inventory_retains_distinct_source_ids_and_verification(root, intake):
    task = intake["tasks"][0]
    task["channel_bindings"] = [channel_binding()]
    second = copy.deepcopy(task)
    second["id"] = "synthetic-2"
    second["channel_bindings"][0]["verification"] = "user_defined"
    intake["tasks"].append(second)
    intake["explicit_user_request"]["reference"] = "slack:TSYNTH002/CSYNTH002/thread1790000000.000001"
    apply(root, intake)
    result = API["channels"](root)
    assert [r["source_id"] for r in result["channels"][0]["tasks"]] == ["synthetic-1"]
    candidates = {(g["workspace_id"], g["channel_id"]): g for g in result["candidates"]}
    assert len(candidates[("TSYNTH002", "CSYNTH002")]["tasks"]) == 2
    assert candidates[("TSYNTH001", "CSYNTH001")]["tasks"][0]["source_id"] == "synthetic-2"
    assert "channel_identity_unverified" in candidates[("TSYNTH001", "CSYNTH001")]["tasks"][0]["gaps"]
    assert candidates[("TSYNTH002", "CSYNTH002")]["tasks"][0]["channel_evidence"][0]["relation"] == "origin"


def test_channel_inventory_does_not_infer_workspace_from_channel_or_prompt(root, intake):
    task = intake["tasks"][0]
    task["prompt"] = "Use TSYNTH001/CSYNTH001; never infer metadata from this instruction."
    task["destinations"] = [{"kind": "slack_thread", "reference": "https://example.slack.com/archives/CSYNTH001/p1790000000000001", "verification": "provider_verified"}]
    apply(root, intake)
    result = API["channels"](root)
    assert result["channels"] == result["candidates"] == []
    assert "channel_workspace_unknown" in result["ungrouped"][0]["gaps"]
    assert "ownership_unknown" in result["ungrouped"][0]["gaps"]


def test_inventory_limit_and_empty_history_are_honest(root, intake):
    empty = API["channels"](root)
    assert empty["status"] == "empty" and empty["coverage"]["historical_source_coverage"] == "not_verified"
    apply(root, intake)
    update = next_input(intake)
    update["tasks"][0]["id"] = "synthetic-2"
    apply(root, update)
    limited = API["channels"](root, 1)
    assert limited["coverage"]["omitted_task_count"] == 1
    assert limited["coverage"]["task_count"] == 2


@pytest.mark.parametrize("limit", [0, -1, 1001, True, "10"])
def test_inventory_invalid_limits_refuse(root, limit):
    with pytest.raises(API["Refusal"], match="inventory limit"):
        API["channels"](root, limit)


def test_optional_metadata_preserves_prior_generation_prompt_schedule_and_identity(root, intake):
    original = apply(root, intake)
    prior = API["home"](root) / "generations" / original["generation"]
    before = {p.relative_to(prior).as_posix(): p.read_bytes() for p in prior.rglob("*") if p.is_file()}
    update = next_input(intake)
    update["tasks"][0].update(ownership={"scope": "root"}, component_bindings=[component_binding()], channel_bindings=[channel_binding()])
    schema_validate(update)
    apply(root, update)
    row = API["channels"](root)["channels"][0]["tasks"][0]
    assert row["revision"] == 2 and row["source_id"] == "synthetic-1"
    assert row["first_observed_at"] == intake["source"]["observed_at"]
    current_task = API["home"](root) / "current/tasks/chatgpt-synthetic-1"
    assert (current_task / "prompt.txt").read_bytes() == intake["tasks"][0]["prompt"].encode()
    assert (current_task / "schedule.ics").read_bytes() == intake["tasks"][0]["schedule"].encode()
    assert {p.relative_to(prior).as_posix(): p.read_bytes() for p in prior.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("name,value", [
    ("kind", "unknown"), ("reference", "skill:root:wrong_kind"),
    ("repository", "https://user:password@example.com/source"), ("repository", "http://example.com/source"),
    ("path", "../outside"), ("path", "/tmp/private"), ("path", "a/.git/config"), ("path", "a//file"),
    ("revision", "main"), ("revision", None), ("sha256", "bad"), ("sha256", None),
    ("ownership", {"scope": "project", "domain": "example"}), ("verification", "provider_verified"),
])
def test_component_binding_rejects_misbound_unpinned_or_unsafe_source(root, intake, name, value):
    binding = component_binding()
    binding[name] = value
    intake["tasks"][0]["component_bindings"] = [binding]
    with pytest.raises(API["Refusal"]):
        API["validate_input"](intake)
    with pytest.raises(ValidationError):
        schema_validate(intake)
    assert not (root / API["RELATIVE_HOME"]).exists()


def test_binding_duplicate_and_channel_identity_mismatch_refuse(intake):
    intake["tasks"][0]["component_bindings"] = [component_binding(), component_binding()]
    with pytest.raises(API["Refusal"], match="duplicate"):
        API["validate_input"](intake)
    del intake["tasks"][0]["component_bindings"]
    bad = channel_binding()
    bad["workspace_id"] = "CSYNTH001"
    intake["tasks"][0]["channel_bindings"] = [bad]
    with pytest.raises(API["Refusal"], match="workspace"):
        API["validate_input"](intake)
    with pytest.raises(ValidationError):
        schema_validate(intake)


def test_local_component_readback_checks_content_and_never_executes(root, intake):
    task = intake["tasks"][0]
    task["component_bindings"] = [component_binding()]
    apply(root, intake)
    source = root / "source"
    file = source / component_binding()["path"]
    file.parent.mkdir(parents=True)
    file.write_bytes(b"synthetic source definition\n")
    result = API["validate_components"](root, component_binding()["repository"], source)
    assert result["status"] == "valid" and result["checks"][0]["status"] == "content_verified"
    assert result["checks"][0]["revision_verification"] == "not_checked"
    file.write_bytes(b"changed source\n")
    assert API["validate_components"](root, component_binding()["repository"], source)["checks"][0]["status"] == "content_mismatch"
    file.unlink()
    assert API["validate_components"](root, component_binding()["repository"], source)["checks"][0]["status"] == "file_unavailable"
    file.symlink_to(root / "outside")
    assert API["validate_components"](root, component_binding()["repository"], source)["checks"][0]["status"] == "redirect_refused"
    assert result["execution_effects"] == 0


@pytest.mark.parametrize("cycle", ["file", "ancestor"])
def test_component_cycles_produce_structured_incomplete_result_without_traceback(root, intake, cycle):
    binding = component_binding()
    intake["tasks"][0]["component_bindings"] = [binding]
    apply(root, intake)
    source = root / "source"
    source.mkdir()
    file = source / binding["path"]
    if cycle == "file":
        file.parent.mkdir(parents=True)
        file.symlink_to(file.name)
    else:
        ancestor = source / "lib"
        ancestor.symlink_to(ancestor.name, target_is_directory=True)
    before = API["current"](API["home"](root))[0]
    command = [sys.executable, str(SCRIPT), "--root", str(root), "validate-components", "--repository", binding["repository"], "--source-root", str(source)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 1
    response = json.loads(result.stdout)
    assert response["status"] == "incomplete" and response["checks"][0]["status"] == "redirect_refused"
    assert response["execution_effects"] == 0 and "Traceback" not in result.stderr
    assert API["current"](API["home"](root))[0] == before


def test_cyclic_component_source_root_is_structured_refusal_without_traceback(root, intake):
    apply(root, intake)
    source = root / "private-source-root-sentinel"
    source.symlink_to(source.name, target_is_directory=True)
    command = [sys.executable, str(SCRIPT), "--root", str(root), "validate-components", "--repository", component_binding()["repository"], "--source-root", str(source)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 2 and result.stdout == ""
    response = json.loads(result.stderr)
    assert response["status"] == "refused" and response["execution_effects"] == 0
    assert "Traceback" not in result.stderr and "private-source-root-sentinel" not in result.stderr


def test_channel_and_component_cli_contracts(root, intake):
    task = intake["tasks"][0]
    task["channel_bindings"] = [channel_binding()]
    task["component_bindings"] = [component_binding()]
    apply(root, intake)
    prefix = [sys.executable, str(SCRIPT), "--root", str(root)]
    observed = subprocess.run(prefix + ["channels", "--limit", "1"], capture_output=True, text=True)
    assert observed.returncode == 0
    assert json.loads(observed.stdout)["schema"] == "atlas-channel-inventory/v1"
    assert task["prompt"] not in observed.stdout and task["title"] not in observed.stdout
    source = root / "source"
    source.mkdir()
    incomplete = subprocess.run(prefix + ["validate-components", "--repository", component_binding()["repository"], "--source-root", str(source)], capture_output=True, text=True)
    assert incomplete.returncode == 1 and json.loads(incomplete.stdout)["status"] == "incomplete"
    refused = subprocess.run(prefix + ["channels", "--limit", "0"], capture_output=True, text=True)
    assert refused.returncode == 2 and json.loads(refused.stderr)["status"] == "refused"


def test_legacy_and_extended_examples_match_schema(intake):
    Draft202012Validator.check_schema(SCHEMA)
    schema_validate(intake)
    API["validate_input"](intake)
    sample = json.loads((SCRIPT.parents[2] / "templates/atlas-work-registry/intake-example.json").read_text())
    schema_validate(sample)
    API["validate_input"](sample)


def test_fresh_install_and_additive_reinstall_keep_private_generations_and_locator(tmp_path, intake):
    from genomes_agentic_os.scaffold import init_os, install_docs
    from genomes_agentic_os.validate import validate_root, validate_schemas_strict

    installed = tmp_path / "installed"
    init_os(installed, domains=["example"])
    helper = installed / "harness/bin/agentic-os-atlas-registry"
    assert helper.read_bytes() == SCRIPT.read_bytes()
    assert helper.stat().st_mode & 0o111
    assert "agentic-os-atlas-registry" in (installed / "harness/registries/commands.yml").read_text()
    assert (installed / "harness/schemas/atlas-task-intake.schema.json").read_bytes() == (SCRIPT.parents[2] / "schemas/atlas-task-intake.schema.json").read_bytes()
    result = subprocess.run([sys.executable, str(helper), "--root", str(installed), "channels"], capture_output=True, text=True)
    assert result.returncode == 0 and json.loads(result.stdout)["status"] == "empty"
    assert not (installed / "artifacts/atlas-work-registry").exists()
    config = locator(installed, {"schema": "atlas-registry-location/v1", "relative_home": "domains/example/02-projects/sample/artifacts/atlas-work-registry"})
    original = apply(installed, intake)
    store = API["home"](installed)
    before = {p.relative_to(store).as_posix(): p.read_bytes() for p in store.rglob("*") if p.is_file()}
    sentinels = [config, installed / "harness/config/execution-fabric.yml"]
    sentinel_bytes = {p: p.read_bytes() for p in sentinels}
    helper.write_text("#!/usr/bin/env python3\n# stale installed helper\n")
    install_docs(installed)
    install_docs(installed)
    assert helper.read_bytes() == SCRIPT.read_bytes()
    assert {p.relative_to(store).as_posix(): p.read_bytes() for p in store.rglob("*") if p.is_file()} == before
    assert all(p.read_bytes() == content for p, content in sentinel_bytes.items())
    assert API["validate_store"](installed)["generation"] == original["generation"]
    assert apply(installed, intake)["status"] == "unchanged"
    structural = validate_root(installed)
    assert structural.ok, structural.errors
    assert not validate_schemas_strict(installed)
