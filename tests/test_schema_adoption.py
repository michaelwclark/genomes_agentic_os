import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from genomes_agentic_os import schema_adoption as adoption
from genomes_agentic_os.auto_dev_orchestration import configured_auto_dev_workflow_stages, read_auto_dev_state
from genomes_agentic_os.cli import main
from genomes_agentic_os.scaffold import ScaffoldResult, ensure_schemas_dir, repo_root
from genomes_agentic_os.state import work_items
from genomes_agentic_os.state.db import connect, default_db_path
from test_auto_dev_consumer_migration import legacy_pair


def sha(data):
    return hashlib.sha256(data).hexdigest()


def root_fixture(tmp_path, *, ownership="unowned"):
    root = tmp_path / "os"
    directory = root / "harness/schemas"
    directory.mkdir(parents=True)
    bundled = (repo_root() / "schemas" / adoption.DEFAULT_SCHEMA).read_bytes()
    current = json.loads(bundled)
    current["title"] = "Preserved operator legacy schema"
    current["properties"]["stage_order"].update(minItems=16, maxItems=16)
    current["properties"]["stages"]["required"].remove("validate_production_release")
    installed = (json.dumps(current, indent=1) + "\n").encode()
    if ownership == "current": installed = bundled
    schema = directory / adoption.DEFAULT_SCHEMA
    if ownership != "absent": schema.write_bytes(installed)
    manifest = {"schema_version": 1, "managed_by": "genomes-agentic-os package", "operator_custom": {"keep": True}, "entries": []}
    if ownership != "absent":
        manifest["entries"].append({"source": f"schemas/{adoption.DEFAULT_SCHEMA}", "destination": f"harness/schemas/{adoption.DEFAULT_SCHEMA}",
                                    "source_checksum": f"sha256:{sha(bundled)}", "observed_checksum": f"sha256:{sha(installed)}",
                                    "managed_checksum": f"sha256:{sha(installed)}" if ownership in {"managed", "current"} else None,
                                    "status": "local_override" if ownership == "unowned" else "current", "operator_note": "preserve"})
    manifest["entries"].append({"destination": "harness/schemas/unrelated.schema.json", "custom": "do not alter"})
    manifest_path = directory / "package-manifest.yml"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    candidate = schema.with_suffix(schema.suffix + ".new"); candidate.write_bytes(bundled)
    return root, schema, manifest_path, candidate


def consumer_fixture(root, name="fixture", *, historical=False, unknown=False):
    packet = root / "domains/acme/02-projects/app" / ("work-items/closed" if historical else "work-items") / name
    packet.mkdir(parents=True)
    projection, task = legacy_pair(status="completed")
    canonical_id = f"acme:app:{name}"
    projection.update(work_item_id=name, canonical_work_id=canonical_id)
    task_path = root / f"domains/acme/02-projects/app/state/development-runs/{name}/tasks/{name}/state.json"
    task_path.parent.mkdir(parents=True)
    projection["delivery"].update(task_state_ref=str(task_path), portfolio_ref=str(task_path.parent.parent.parent / "portfolio.json"))
    task.update(canonical_work_id=canonical_id, work_item=str(packet), autodev_path=str(packet / "autodev.json"))
    if unknown:
        projection["custom_operator_field"] = {"preserve": "unknown"}; task["custom_operator_field"] = {"keep": True}
    path = packet / "autodev.json"; path.write_text(json.dumps(projection, indent=1) + "\n")
    task_path.write_text(json.dumps(task, indent=1) + "\n")
    (packet / "artifacts").mkdir(); (packet / "artifacts/history.json").write_bytes(b'{"historical":"immutable"}\n')
    with connect(default_db_path(root)) as connection:
        work_items.upsert(connection, item_id=canonical_id, title="Fixture", state="finished" if historical else "building",
                          domain="acme", project="app", packet_path=packet.relative_to(root).as_posix())
    return path, task_path


def apply(plan):
    return adoption.apply_schema_plan(plan, expected_plan_sha256=plan["plan_sha256"],
                                      acknowledge_installed_sha256=plan["installed"]["sha256"] or "absent")


@pytest.mark.parametrize("ownership,classification", [("absent", "absent"), ("current", "current_managed"), ("managed", "managed_upgrade"), ("unowned", "unowned_or_custom_override")])
def test_schema_ownership_plan_apply_and_exact_rollback(tmp_path, ownership, classification):
    root, schema, manifest, candidate = root_fixture(tmp_path, ownership=ownership)
    originals = {path: path.read_bytes() if path.exists() else None for path in (schema, manifest, candidate)}
    plan = adoption.plan_schema_adoption(root)
    assert plan["installed"]["ownership"] == classification
    assert {path: path.read_bytes() if path.exists() else None for path in originals} == originals
    receipt = apply(plan)
    assert receipt["status"] == "applied" and receipt["readback_verified"] and schema.read_bytes() == candidate.read_bytes()
    after_manifest = yaml.safe_load(manifest.read_bytes())
    assert after_manifest["operator_custom"] == {"keep": True}
    assert {"destination": "harness/schemas/unrelated.schema.json", "custom": "do not alter"} in after_manifest["entries"]
    assert candidate.read_bytes() == originals[candidate]
    rollback = adoption.rollback_schema_transaction(root, receipt["journal"], expected_plan_sha256=plan["plan_sha256"])
    assert rollback["readback_verified"]
    assert {path: path.read_bytes() if path.exists() else None for path in originals} == originals


def test_scaffold_still_preserves_unowned_override(tmp_path):
    root, schema, _, candidate = root_fixture(tmp_path); original = schema.read_bytes()
    ensure_schemas_dir(root, ScaffoldResult())
    assert schema.read_bytes() == original and candidate.read_bytes() != original


def test_exact_active_and_historical_validation_are_frozen_and_separate(tmp_path):
    root, _, _, _ = root_fixture(tmp_path)
    active, _ = consumer_fixture(root); historic, _ = consumer_fixture(root, "historic", historical=True)
    originals = {path: path.read_bytes() for path in (active, historic)}
    plan = adoption.plan_schema_adoption(root, consumers=[active], historical=[historic])
    assert [row["kind"] for row in plan["consumers"]] == ["active", "historical"]
    assert all(row["old_validation"]["valid"] for row in plan["consumers"])
    assert not any(row["new_validation"]["valid"] for row in plan["consumers"])
    receipt = apply(plan)
    assert len(receipt["writes"]) == 2 and {path: path.read_bytes() for path in originals} == originals
    assert not receipt["whole_root_health_claimed"]


def test_explicit_migration_crosses_real_consumer_boundary_preserving_history(tmp_path):
    root, _, _, _ = root_fixture(tmp_path, ownership="current")
    active, task = consumer_fixture(root); historic, historical_task = consumer_fixture(root, "historic", historical=True)
    historic_original = historic.read_bytes(), historical_task.read_bytes()
    before_task = json.loads(task.read_bytes()); history = (active.parent / "artifacts/history.json").read_bytes()
    plan = adoption.plan_schema_adoption(root, consumers=[active], historical=[historic], migrate_consumers=True)
    assert plan["consumers"][0]["migrated_validation"]["valid"]
    receipt = apply(plan); current = read_auto_dev_state(active)
    assert "validate_production_release" in configured_auto_dev_workflow_stages(current)
    assert current["current_stage"] == "validate_production_release" and current["status"] == "ready"
    assert current["stages"]["validate_production_release"]["receipt_refs"] == []
    after_task = json.loads(task.read_bytes())
    assert after_task["stage_receipts"] == before_task["stage_receipts"] and after_task["history"] == before_task["history"]
    assert after_task["state"] == before_task["state"] and (historic.read_bytes(), historical_task.read_bytes()) == historic_original
    assert (active.parent / "artifacts/history.json").read_bytes() == history
    assert not adoption.plan_schema_adoption(root, consumers=[active], migrate_consumers=True)["consumers"][0]["migration"]["changed"]
    adoption.rollback_schema_transaction(root, receipt["journal"], expected_plan_sha256=plan["plan_sha256"])
    assert json.loads(task.read_bytes()) == before_task


def test_unknown_consumer_fields_are_preserved_with_residual_diagnostics(tmp_path):
    root, _, _, _ = root_fixture(tmp_path, ownership="current"); active, task = consumer_fixture(root, unknown=True)
    plan = adoption.plan_schema_adoption(root, consumers=[active], migrate_consumers=True)
    assert not plan["consumers"][0]["migrated_validation"]["valid"]
    receipt = apply(plan)
    assert receipt["selected_validation_readback"][0]["valid"] is False
    assert receipt["selected_validation_readback"][0]["diagnostics_count"] > 0
    assert json.loads(active.read_bytes())["custom_operator_field"] == {"preserve": "unknown"}
    assert json.loads(task.read_bytes())["custom_operator_field"] == {"keep": True}


@pytest.mark.parametrize("change", ["schema", "manifest", "consumer", "task", "canonical"])
def test_stale_plan_refuses_before_first_target_mutation(tmp_path, change):
    root, schema, manifest, _ = root_fixture(tmp_path, ownership="current"); active, task = consumer_fixture(root)
    plan = adoption.plan_schema_adoption(root, consumers=[active], migrate_consumers=change in {"task", "canonical"})
    if change != "canonical":
        path = {"schema": schema, "manifest": manifest, "consumer": active, "task": task}[change]; path.write_bytes(path.read_bytes() + b"\n")
    else:
        with connect(default_db_path(root)) as connection:
            work_items.upsert(connection, item_id="acme:app:fixture", title="Changed owner context", state="building", domain="acme", project="app", packet_path=active.parent.relative_to(root).as_posix())
    originals = {path: path.read_bytes() for path in (schema, manifest, active, task)}
    with pytest.raises(adoption.SchemaAdoptionError): apply(plan)
    assert {path: path.read_bytes() for path in originals} == originals


def test_later_invalid_consumer_prevents_all_member_writes(tmp_path):
    root, schema, manifest, _ = root_fixture(tmp_path, ownership="current")
    good, good_task = consumer_fixture(root, "good"); bad, _ = consumer_fixture(root, "bad")
    value = json.loads(bad.read_bytes()); value["schema"] = "auto-dev-work-item/v99"; bad.write_text(json.dumps(value))
    originals = {path: path.read_bytes() for path in (schema, manifest, good, good_task)}
    with pytest.raises(adoption.SchemaAdoptionError, match="cannot be safely migrated"):
        adoption.plan_schema_adoption(root, consumers=[good, bad], migrate_consumers=True)
    assert {path: path.read_bytes() for path in originals} == originals


@pytest.mark.parametrize("target", ["schema", "manifest", "consumer", "task"])
def test_rollback_refuses_unknown_target_changes_without_partial_restoration(tmp_path, target):
    root, schema, manifest, _ = root_fixture(tmp_path, ownership="current" if target in {"consumer", "task"} else "unowned")
    active, task = consumer_fixture(root)
    plan = adoption.plan_schema_adoption(root, consumers=[active], migrate_consumers=target in {"consumer", "task"}); receipt = apply(plan)
    path = {"schema": schema, "manifest": manifest, "consumer": active, "task": task}[target]; path.write_bytes(path.read_bytes() + b"unknown concurrent edit")
    originals = {item: item.read_bytes() for item in (schema, manifest, active, task)}
    with pytest.raises(adoption.SchemaAdoptionError, match="concurrent or unknown"):
        adoption.rollback_schema_transaction(root, receipt["journal"], expected_plan_sha256=plan["plan_sha256"])
    assert {item: item.read_bytes() for item in originals} == originals


@pytest.mark.parametrize("dependency", ["schema", "manifest"])
@pytest.mark.parametrize("change", ["edit", "remove"])
def test_consumer_rollback_refuses_changed_readonly_schema_and_manifest(tmp_path, dependency, change):
    root, schema, manifest, _ = root_fixture(tmp_path, ownership="current")
    active, task = consumer_fixture(root)
    plan = adoption.plan_schema_adoption(root, consumers=[active], migrate_consumers=True)
    receipt = apply(plan)
    path = {"schema": schema, "manifest": manifest}[dependency]
    if change == "edit":
        path.write_bytes(path.read_bytes() + b"\n")
    else:
        path.unlink()
    originals = {item: item.read_bytes() if item.exists() else None for item in (schema, manifest, active, task)}
    journal_before = Path(receipt["journal"]).read_bytes()
    with pytest.raises(adoption.SchemaAdoptionError) as exc:
        adoption.rollback_schema_transaction(root, receipt["journal"], expected_plan_sha256=plan["plan_sha256"])
    assert exc.value.error_code == "rollback_dependency_divergence" and not exc.value.retryable
    assert {item: item.read_bytes() if item.exists() else None for item in originals} == originals
    assert Path(receipt["journal"]).read_bytes() == journal_before


@pytest.mark.parametrize("dependency", ["schema", "manifest"])
@pytest.mark.parametrize("change", ["edit", "remove"])
def test_apply_rechecks_readonly_dependencies_and_restores_only_known_consumers(tmp_path, monkeypatch, dependency, change):
    root, schema, manifest, _ = root_fixture(tmp_path, ownership="current")
    active, task = consumer_fixture(root)
    plan = adoption.plan_schema_adoption(root, consumers=[active], migrate_consumers=True)
    consumer_originals = active.read_bytes(), task.read_bytes()
    changed_path = {"schema": schema, "manifest": manifest}[dependency]
    original_atomic = adoption._atomic
    changed = False
    dependency_after = None
    def manual_writer(path, data):
        nonlocal changed, dependency_after
        original_atomic(path, data)
        if path == active and not changed:
            changed = True
            if change == "edit":
                changed_path.write_bytes(changed_path.read_bytes() + b"\n")
                dependency_after = changed_path.read_bytes()
            else:
                changed_path.unlink()
    monkeypatch.setattr(adoption, "_atomic", manual_writer)
    with pytest.raises(adoption.SchemaAdoptionError) as exc:
        apply(plan)
    assert exc.value.error_code == "apply_dependency_divergence" and not exc.value.retryable
    assert (active.read_bytes(), task.read_bytes()) == consumer_originals
    assert (changed_path.read_bytes() if changed_path.exists() else None) == dependency_after
    journals = list((root / adoption.TRANSACTION_RELATIVE).glob("*/journal.json"))
    assert len(journals) == 1
    assert json.loads(journals[0].read_bytes())["status"] == "rolled_back"


@pytest.mark.parametrize("target", ["schema", "manifest", "consumer", "task"])
def test_changed_identity_between_replan_and_backup_refuses_before_mutation(tmp_path, monkeypatch, target):
    root, schema, manifest, _ = root_fixture(tmp_path, ownership="current")
    active, task = consumer_fixture(root)
    plan = adoption.plan_schema_adoption(root, consumers=[active], migrate_consumers=True)
    selected = {"schema": schema, "manifest": manifest, "consumer": active, "task": task}[target]
    original_writes = adoption._writes
    expected = {}
    def late_writer(root_path, frozen):
        writes = original_writes(root_path, frozen)
        selected.write_bytes(selected.read_bytes() + b"\n")
        expected.update({path: path.read_bytes() for path in (schema, manifest, active, task)})
        return writes
    monkeypatch.setattr(adoption, "_writes", late_writer)
    with pytest.raises(adoption.SchemaAdoptionError) as exc:
        apply(plan)
    assert exc.value.error_code == "stale_plan" and not exc.value.retryable
    assert {path: path.read_bytes() for path in expected} == expected
    assert not list((root / adoption.TRANSACTION_RELATIVE).glob("*/journal.json"))


def test_write_failure_restores_exact_schema_and_manifest(tmp_path, monkeypatch):
    root, schema, manifest, _ = root_fixture(tmp_path); originals = schema.read_bytes(), manifest.read_bytes()
    plan = adoption.plan_schema_adoption(root); original_atomic = adoption._atomic; failed = False
    def fault(path, data):
        nonlocal failed
        if path == manifest and not failed: failed = True; raise OSError("fixture write failure")
        original_atomic(path, data)
    monkeypatch.setattr(adoption, "_atomic", fault)
    with pytest.raises(OSError, match="fixture write failure"): apply(plan)
    assert (schema.read_bytes(), manifest.read_bytes()) == originals
    journals = list((root / adoption.TRANSACTION_RELATIVE).glob("*/journal.json"))
    assert len(journals) == 1 and json.loads(journals[0].read_bytes())["status"] == "rolled_back"


def test_crash_journal_recovery_and_new_apply_refusal(tmp_path):
    root, schema, manifest, _ = root_fixture(tmp_path); original = schema.read_bytes(), manifest.read_bytes()
    plan = adoption.plan_schema_adoption(root); plan_file = tmp_path / "plan.json"; plan_file.write_text(json.dumps(plan))
    code = """import json, os, sys
from pathlib import Path
from genomes_agentic_os import schema_adoption as a
p=json.loads(Path(sys.argv[1]).read_text()); original=a._atomic
def crash(path,data):
    if path == Path(p['root']) / p['manifest']['path']: os._exit(73)
    original(path,data)
a._atomic=crash
a.apply_schema_plan(p,expected_plan_sha256=p['plan_sha256'],acknowledge_installed_sha256=p['installed']['sha256'])
"""
    result = subprocess.run([sys.executable, "-c", code, str(plan_file)], capture_output=True, timeout=30)
    assert result.returncode == 73
    journal = next((root / adoption.TRANSACTION_RELATIVE).glob("*/journal.json"))
    assert json.loads(journal.read_bytes())["status"] == "applying"
    with pytest.raises(adoption.SchemaAdoptionError, match="interrupted transaction"): apply(plan)
    receipt = adoption.rollback_schema_transaction(root, journal, expected_plan_sha256=plan["plan_sha256"])
    assert receipt["readback_verified"] and (schema.read_bytes(), manifest.read_bytes()) == original


@pytest.mark.parametrize("case", ["escape", "symlink", "external-ref", "bad-schema", "duplicate-json", "nan", "bad-manifest", "duplicate-entry", "missing-canonical", "historical-as-active", "too-many"])
def test_typed_permanent_refusals_preserve_targets(tmp_path, case):
    root, schema, manifest, _ = root_fixture(tmp_path); active, _ = consumer_fixture(root); kwargs = {}
    if case == "escape": kwargs["consumers"] = [tmp_path / "outside/autodev.json"]
    if case == "symlink":
        link = root / "link"; link.symlink_to(active.parent, target_is_directory=True); kwargs["consumers"] = [link / "autodev.json"]
    if case == "external-ref": schema.write_text('{"$ref":"https://example.invalid/secret"}')
    if case == "bad-schema": schema.write_text('{"type":99}')
    if case == "duplicate-json": schema.write_text('{"type":"object","type":"array"}')
    if case == "nan": schema.write_text('{"maximum":NaN}')
    if case in {"external-ref", "bad-schema", "duplicate-json", "nan"}:
        value=yaml.safe_load(manifest.read_bytes()); value["entries"][0]["observed_checksum"]=sha(schema.read_bytes()); manifest.write_text(yaml.safe_dump(value))
    if case == "bad-manifest": manifest.write_text("invalid: [")
    if case == "duplicate-entry":
        value=yaml.safe_load(manifest.read_bytes()); value["entries"].append(value["entries"][0]); manifest.write_text(yaml.safe_dump(value))
    if case == "missing-canonical":
        value=json.loads(active.read_bytes()); value["canonical_work_id"]="acme:app:missing"; active.write_text(json.dumps(value)); kwargs["consumers"]=[active]
    if case == "historical-as-active": kwargs["consumers"]=[consumer_fixture(root,"historic",historical=True)[0]]
    if case == "too-many": kwargs["consumers"]=[active] * (adoption.MAX_CONSUMERS+1)
    originals=schema.read_bytes(),manifest.read_bytes(),active.read_bytes()
    with pytest.raises(adoption.SchemaAdoptionError) as exc: adoption.plan_schema_adoption(root,**kwargs)
    assert exc.value.error_code and exc.value.retryable is False and "secret" not in str(exc.value)
    assert (schema.read_bytes(),manifest.read_bytes(),active.read_bytes()) == originals


def test_plan_hash_and_explicit_operator_acknowledgement_are_required(tmp_path):
    root, _, _, _ = root_fixture(tmp_path); plan = adoption.plan_schema_adoption(root)
    with pytest.raises(adoption.SchemaAdoptionError, match="plan hash"):
        adoption.apply_schema_plan(plan, expected_plan_sha256="wrong", acknowledge_installed_sha256=plan["installed"]["sha256"])
    with pytest.raises(adoption.SchemaAdoptionError, match="acknowledgement"):
        adoption.apply_schema_plan(plan, expected_plan_sha256=plan["plan_sha256"], acknowledge_installed_sha256="wrong")


def test_public_cli_plan_apply_and_rollback(tmp_path, capsys):
    root, schema, manifest, _ = root_fixture(tmp_path); originals = schema.read_bytes(), manifest.read_bytes()
    plan_file=tmp_path/"public-plan.json"
    assert main(["schema-adoption","plan","--root",str(root),"--output",str(plan_file)]) == 0
    plan=json.loads(capsys.readouterr().out)
    assert main(["schema-adoption","apply","--plan",str(plan_file),"--plan-sha256",plan["plan_sha256"],"--acknowledge-installed-sha256",plan["installed"]["sha256"],"--apply"]) == 0
    receipt=json.loads(capsys.readouterr().out)
    assert main(["schema-adoption","rollback","--root",str(root),"--journal",receipt["journal"],"--plan-sha256",plan["plan_sha256"],"--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["readback_verified"] and (schema.read_bytes(), manifest.read_bytes()) == originals


@pytest.mark.parametrize("migration", [False, True])
def test_concurrent_apply_serializes_and_refuses_the_stale_actor(tmp_path, migration):
    root, _, _, _ = root_fixture(tmp_path, ownership="current" if migration else "unowned")
    active, _ = consumer_fixture(root)
    plan = adoption.plan_schema_adoption(root, consumers=[active], migrate_consumers=migration)
    plan_file = tmp_path / "concurrent-plan.json"; plan_file.write_text(json.dumps(plan))
    code = """import json,sys
from pathlib import Path
from genomes_agentic_os import schema_adoption as a
p=json.loads(Path(sys.argv[1]).read_text())
try:
    r=a.apply_schema_plan(p,expected_plan_sha256=p['plan_sha256'],acknowledge_installed_sha256=p['installed']['sha256'])
    print(json.dumps({'status':r['status']}))
except a.SchemaAdoptionError as e:
    print(json.dumps({'error_code':e.error_code,'retryable':e.retryable})); sys.exit(2)
"""
    actors = [subprocess.Popen([sys.executable, "-c", code, str(plan_file)], stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
    outputs = [actor.communicate(timeout=30) for actor in actors]
    assert sorted(actor.returncode for actor in actors) == [0, 2]
    receipts = [json.loads(stdout) for stdout, _ in outputs]
    assert {row.get("status") for row in receipts} == {None, "applied"}
    assert {row.get("error_code") for row in receipts} == {None, "stale_plan"}
    assert len(list((root / adoption.TRANSACTION_RELATIVE).glob("*/journal.json"))) == 1


def test_late_member_write_failure_restores_every_selected_consumer(tmp_path, monkeypatch):
    root, _, _, _ = root_fixture(tmp_path, ownership="current")
    first, first_task = consumer_fixture(root, "first"); second, second_task = consumer_fixture(root, "second")
    plan = adoption.plan_schema_adoption(root, consumers=[first, second], migrate_consumers=True)
    originals = {path: path.read_bytes() for path in (first, first_task, second, second_task)}
    original_atomic = adoption._atomic; failed = False
    def fault(path, data):
        nonlocal failed
        if path == second and not failed: failed = True; raise OSError("late fixture write failure")
        original_atomic(path, data)
    monkeypatch.setattr(adoption, "_atomic", fault)
    with pytest.raises(OSError, match="late fixture"): apply(plan)
    assert {path: path.read_bytes() for path in originals} == originals
    journal = next((root / adoption.TRANSACTION_RELATIVE).glob("*/journal.json"))
    assert json.loads(journal.read_bytes())["status"] == "rolled_back"


def test_rollback_refuses_changed_canonical_authority(tmp_path):
    root, _, _, _ = root_fixture(tmp_path, ownership="current"); active, task = consumer_fixture(root)
    plan = adoption.plan_schema_adoption(root, consumers=[active], migrate_consumers=True); receipt = apply(plan)
    with connect(default_db_path(root)) as connection:
        work_items.upsert(connection, item_id="acme:app:fixture", title="Different canonical context", state="building",
                          domain="acme", project="app", packet_path=active.parent.relative_to(root).as_posix())
    originals = active.read_bytes(), task.read_bytes()
    with pytest.raises(adoption.SchemaAdoptionError, match="canonical consumer authority"):
        adoption.rollback_schema_transaction(root, receipt["journal"], expected_plan_sha256=plan["plan_sha256"])
    assert (active.read_bytes(), task.read_bytes()) == originals


def test_forged_journal_cannot_select_unrelated_targets(tmp_path):
    root, schema, manifest, _ = root_fixture(tmp_path); unrelated = root / "operator-custom.txt"; unrelated.write_bytes(b"keep")
    plan = adoption.plan_schema_adoption(root); receipt = apply(plan); journal = Path(receipt["journal"])
    value = json.loads(journal.read_bytes()); value["writes"][0]["path"] = "operator-custom.txt"; journal.write_text(json.dumps(value))
    originals = schema.read_bytes(), manifest.read_bytes(), unrelated.read_bytes()
    with pytest.raises(adoption.SchemaAdoptionError, match="journal target identities"):
        adoption.rollback_schema_transaction(root, journal, expected_plan_sha256=plan["plan_sha256"])
    assert (schema.read_bytes(), manifest.read_bytes(), unrelated.read_bytes()) == originals


def test_corrupt_backup_refuses_all_restoration(tmp_path):
    root, schema, manifest, _ = root_fixture(tmp_path); plan = adoption.plan_schema_adoption(root); receipt = apply(plan)
    journal = Path(receipt["journal"]); (journal.parent / "backup-0.bin").write_bytes(b"corrupt")
    originals = schema.read_bytes(), manifest.read_bytes()
    with pytest.raises(adoption.SchemaAdoptionError, match="backup identity"):
        adoption.rollback_schema_transaction(root, journal, expected_plan_sha256=plan["plan_sha256"])
    assert (schema.read_bytes(), manifest.read_bytes()) == originals


def test_consumer_migration_requires_adopted_schema(tmp_path):
    root, _, _, _ = root_fixture(tmp_path); active, task = consumer_fixture(root)
    plan = adoption.plan_schema_adoption(root, consumers=[active], migrate_consumers=True)
    originals = active.read_bytes(), task.read_bytes()
    with pytest.raises(adoption.SchemaAdoptionError, match="adopt the exact bundled"): apply(plan)
    assert (active.read_bytes(), task.read_bytes()) == originals


def test_unregistered_consumer_does_not_create_a_state_database(tmp_path):
    root, _, _, _ = root_fixture(tmp_path); packet = root / "packet"; packet.mkdir()
    projection, _ = legacy_pair(); path = packet / "autodev.json"; path.write_text(json.dumps(projection))
    with pytest.raises(adoption.SchemaAdoptionError, match="canonical work registry"):
        adoption.plan_schema_adoption(root, consumers=[path])
    assert not default_db_path(root).exists()


def test_public_cli_refusal_is_typed_permanent_json(tmp_path, capsys):
    root, _, _, _ = root_fixture(tmp_path); plan = adoption.plan_schema_adoption(root)
    path = tmp_path / "plan.json"; path.write_text(json.dumps(plan))
    assert main(["schema-adoption", "apply", "--plan", str(path), "--plan-sha256", plan["plan_sha256"],
                 "--acknowledge-installed-sha256", "wrong", "--apply"]) == 2
    refusal = json.loads(capsys.readouterr().out)
    assert refusal["schema"] == "schema-adoption-failure/v1" and refusal["retryable"] is False
    assert refusal["error_code"] == "operator_acknowledgement"


def test_migrated_materialized_packet_stays_pending_through_actual_projection_refresh(tmp_path):
    import genomes_agentic_os.development_delivery as delivery
    from genomes_agentic_os.auto_dev_orchestration import sync_delivery_projection
    from test_auto_dev_state_reconciliation import _project, _repository

    repo, _ = _repository(tmp_path)
    root = tmp_path / "os"; project = _project(root, repo)
    profile_path = project / "config/development.yml"
    profile = yaml.safe_load(profile_path.read_text()); profile["tracker"]["primary"] = "filesystem"
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False))
    run = delivery.start_development_run(root, "acme", "app", ["FIX-227"], run_id="consumer-migration",
                                         auto_dev_mode="everything", provision_worktree=False, apply=True)
    task_path = Path(run["tasks"][0]["state_ref"])
    task = json.loads(task_path.read_bytes()); projection_path = Path(task["autodev_path"])
    projection = json.loads(projection_path.read_bytes())
    legacy_order = [name for name in projection["stage_order"] if name != "validate_production_release"]
    projection["stage_order"] = legacy_order; projection["stages"].pop("validate_production_release")
    task["auto_dev_stage_order"] = legacy_order
    projection_path.write_text(json.dumps(projection)); task_path.write_text(json.dumps(task))
    plan = adoption.plan_schema_adoption(root, consumers=[projection_path], migrate_consumers=True)
    receipt = apply(plan)
    assert receipt["readback_verified"]
    refreshed = sync_delivery_projection(task_path)
    row = refreshed["stages"]["validate_production_release"]
    assert row["status"] == "not_started" and row["receipt_refs"] == [] and row["last_verified_at"] is None
    assert json.loads(task_path.read_bytes())["state"] == task["state"]
    assert plan["consumers"][0]["migrated_validation"]["valid"]


@pytest.mark.parametrize("bad_ref", ["#/$defs/missing", "#"])
def test_unresolvable_or_recursive_local_schema_failure_is_sanitized(tmp_path, bad_ref):
    root, schema, manifest, _ = root_fixture(tmp_path); active, _ = consumer_fixture(root)
    schema.write_text(json.dumps({"$ref": bad_ref}))
    value = yaml.safe_load(manifest.read_bytes()); value["entries"][0]["observed_checksum"] = sha(schema.read_bytes())
    manifest.write_text(yaml.safe_dump(value))
    with pytest.raises(adoption.SchemaAdoptionError) as exc:
        adoption.plan_schema_adoption(root, consumers=[active])
    assert exc.value.error_code == "validation_reference" and exc.value.retryable is False


@pytest.mark.parametrize("historical", [False, True])
def test_schema_rollback_refuses_changed_diagnostic_only_consumers(tmp_path, historical):
    root, schema, manifest, _ = root_fixture(tmp_path)
    selected, _ = consumer_fixture(root, historical=historical)
    selection = {"historical": [selected]} if historical else {"consumers": [selected]}
    plan = adoption.plan_schema_adoption(root, **selection); receipt = apply(plan)
    value = json.loads(selected.read_bytes()); value["next_action"] = "concurrent selected consumer edit"
    selected.write_text(json.dumps(value))
    originals = schema.read_bytes(), manifest.read_bytes(), selected.read_bytes()
    with pytest.raises(adoption.SchemaAdoptionError, match="diagnostic-only selected consumer"):
        adoption.rollback_schema_transaction(root, receipt["journal"], expected_plan_sha256=plan["plan_sha256"])
    assert (schema.read_bytes(), manifest.read_bytes(), selected.read_bytes()) == originals


@pytest.mark.parametrize("malformation", ["installed", "bundled", "manifest", "schema", "migration"])
def test_even_hash_acknowledged_malformed_plans_are_typed_refusals(tmp_path, malformation):
    root, _, _, _ = root_fixture(tmp_path, ownership="current"); selected, _ = consumer_fixture(root)
    plan = adoption.plan_schema_adoption(root, consumers=[selected], migrate_consumers=True)
    if malformation in {"installed", "bundled", "manifest"}: plan[malformation] = None
    if malformation == "schema": plan["schema_name"] = None
    if malformation == "migration": plan["consumers"][0]["migration"] = None
    plan["plan_sha256"] = adoption._identity({key: value for key, value in plan.items() if key != "plan_sha256"})
    with pytest.raises(adoption.SchemaAdoptionError) as exc:
        adoption.apply_schema_plan(plan, expected_plan_sha256=plan["plan_sha256"], acknowledge_installed_sha256="wrong")
    assert exc.value.error_code == "invalid_plan" and not exc.value.retryable


def test_canonical_current_order_missing_row_migrates_instead_of_zero_write_acceptance(tmp_path):
    from genomes_agentic_os.auto_dev_orchestration import AUTO_DEV_STAGE_ORDER
    root, _, _, _ = root_fixture(tmp_path, ownership="current"); selected, task_path = consumer_fixture(root)
    projection = json.loads(selected.read_bytes()); task = json.loads(task_path.read_bytes())
    projection["stage_order"] = list(AUTO_DEV_STAGE_ORDER); task["auto_dev_stage_order"] = list(AUTO_DEV_STAGE_ORDER)
    selected.write_text(json.dumps(projection)); task_path.write_text(json.dumps(task))
    plan = adoption.plan_schema_adoption(root, consumers=[selected], migrate_consumers=True)
    assert not plan["consumers"][0]["new_validation"]["valid"]
    assert plan["consumers"][0]["migrated_validation"]["valid"]
    receipt = apply(plan)
    assert len(receipt["writes"]) == 2
    current = read_auto_dev_state(selected)
    assert current["status"] == "ready" and current["current_stage"] == "validate_production_release"
    row = current["stages"]["validate_production_release"]
    assert row["status"] == "not_started" and row["receipt_refs"] == [] and row["last_verified_at"] is None
    assert json.loads(task_path.read_bytes())["history"] == task["history"]


def test_future_canonical_task_schema_is_refused_before_all_selected_mutations(tmp_path):
    root, schema, manifest, _ = root_fixture(tmp_path, ownership="current")
    first, first_task = consumer_fixture(root, "first"); future, future_task = consumer_fixture(root, "future")
    task = json.loads(future_task.read_bytes()); task["schema"] = "development-task/v99"; future_task.write_text(json.dumps(task))
    originals = {path: path.read_bytes() for path in (schema, manifest, first, first_task, future, future_task)}
    with pytest.raises(adoption.SchemaAdoptionError) as exc:
        adoption.plan_schema_adoption(root, consumers=[first, future], migrate_consumers=True)
    assert exc.value.error_code == "unsupported_consumer" and not exc.value.retryable
    assert {path: path.read_bytes() for path in originals} == originals


@pytest.mark.parametrize("fault", ["packet-id", "task-ref-null", "portfolio-ref-null", "task-work-item-null",
                                   "task-projection-null", "task-domain", "task-project", "unsupported-mode",
                                   "foreign-portfolio", "foreign-task-layout", "foreign-run-id"])
def test_exact_task_projection_binding_and_supported_shape_refuse_before_any_member_mutation(tmp_path, fault):
    root, schema, manifest, _ = root_fixture(tmp_path, ownership="current")
    first, first_task = consumer_fixture(root, "first"); bad, bad_task = consumer_fixture(root, "bad")
    value, task = json.loads(bad.read_bytes()), json.loads(bad_task.read_bytes())
    if fault == "packet-id": value["work_item_id"] = "different-packet"
    if fault == "task-ref-null": value["delivery"]["task_state_ref"] = None
    if fault == "portfolio-ref-null": value["delivery"]["portfolio_ref"] = None
    if fault == "task-work-item-null": task["work_item"] = None
    if fault == "task-projection-null": task["autodev_path"] = None
    if fault == "task-domain": task["domain"] = "different-domain"
    if fault == "task-project": task["project"] = "different-project"
    if fault == "unsupported-mode": value["mode"] = task["auto_dev_mode"] = "future_mode"
    if fault == "foreign-portfolio": value["delivery"]["portfolio_ref"] = str(root / "different/portfolio.json")
    if fault == "foreign-task-layout": value["delivery"]["task_state_ref"] = str(root / "foreign/state.json")
    if fault == "foreign-run-id": task["run_id"] = "different-run"
    bad.write_text(json.dumps(value)); bad_task.write_text(json.dumps(task))
    originals = {path: path.read_bytes() for path in (schema, manifest, first, first_task, bad, bad_task)}
    with pytest.raises(adoption.SchemaAdoptionError) as exc:
        adoption.plan_schema_adoption(root, consumers=[first, bad], migrate_consumers=True)
    assert exc.value.error_code in {"consumer_identity", "unsupported_consumer"} and not exc.value.retryable
    assert {path: path.read_bytes() for path in originals} == originals
    assert not (root / adoption.TRANSACTION_RELATIVE).exists()
