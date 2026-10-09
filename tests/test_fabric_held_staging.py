"""Filesystem boundary tests for the standalone held-bundle installer utility."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tarfile

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "installers/execution-fabric/bin/held-staging.py"
spec = importlib.util.spec_from_file_location("fabric_held_staging", SCRIPT)
held = importlib.util.module_from_spec(spec)
spec.loader.exec_module(held)

def sha(data):
    return hashlib.sha256(data).hexdigest()

@pytest.fixture
def fixture(tmp_path):
    root = tmp_path.resolve()
    parent = root / "staged"
    parent.mkdir(mode=0o700)
    hold = {"schema": "rubicon-inert-staging-hold/v1", "ticket": "AGE-fixture",
            "mode": "no_start", **{key: False for key in held.HOLD_GATES}}
    payload = {name: (name + "\n").encode() for name in held.PAYLOAD_NAMES}
    payload["HOLD.json"] = json.dumps(hold).encode()
    plan = {"schema": "rubicon-held-stage-plan/v1", "operation": "inert_file_staging",
            "ticket": "AGE-fixture", "target_host": "isolated-fixture",
            "admission": "prepared_only", "target": str(parent / "fixture-held"),
            "staging_parent": str(parent), "effects": {key: False for key in held.EFFECT_NAMES},
            "activation": {"admitted": False},
            "payload_files": {name: {"sha256": sha(data), "bytes": len(data), "mode": "0600"}
                              for name, data in payload.items()}}
    members = {"held-stage-plan.json": json.dumps(plan).encode(),
               "held_staging.py": b"raise RuntimeError('ARCHIVED_HELPER_MUST_NOT_EXECUTE')\n",
               **{"payload/" + name: data for name, data in payload.items()}}
    receipt = root / "workflow-operation.json"
    receipt.write_text('{"schema":"existing-workflow-operation/v1","fixture_only":true}\n')
    return {"root": root, "parent": parent, "plan": plan, "payload": payload,
            "members": members, "receipt": receipt}

def bundle(fixture, changes=None, extra=None, mode=None, member_type=None):
    members = fixture["members"].copy()
    if changes:
        members.update(changes)
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as archive:
        for name, data in [*members.items(), *(extra or [])]:
            header = tarfile.TarInfo(name)
            header.mode = mode if mode is not None else 0o600
            header.size = len(data)
            if member_type is not None and name == "held_staging.py":
                header.type = member_type
                header.linkname = "../outside"
            archive.addfile(header, io.BytesIO(data) if header.isreg() else None)
    path = fixture["root"] / "candidate.tar.gz"
    path.write_bytes(raw.getvalue())
    return str(path), sha(raw.getvalue())

def candidate(fixture):
    path, pin = bundle(fixture)
    return held.verify_bundle(path, pin)

def apply(fixture, verified=None):
    return held.stage(verified or candidate(fixture), str(fixture["receipt"]),
                      sha(fixture["receipt"].read_bytes()), apply=True)

def changed_plan(fixture, mutate):
    plan = json.loads(json.dumps(fixture["plan"]))
    mutate(plan)
    return bundle(fixture, {"held-stage-plan.json": json.dumps(plan).encode()})

def test_verify_and_plan_are_read_only_and_never_execute_archived_helper(fixture):
    before = {str(p): p.read_bytes() for p in fixture["root"].iterdir() if p.is_file()}
    verified = candidate(fixture)
    result = held.plan_stage(verified)
    assert result["status"] == "read_only_plan"
    assert result["target_status"] == "absent"
    assert result["operational_mutations"] == 0
    assert result["activation_admitted"] is False
    assert not Path(fixture["plan"]["target"]).exists()
    assert all(Path(path).read_bytes() == contents for path, contents in before.items())

def test_digest_is_required_before_parsing(fixture):
    path = fixture["root"] / "untrusted.tar.gz"
    path.write_bytes(b"not even an archive")
    with pytest.raises(held.StageError, match="bundle_digest_mismatch"):
        held.verify_bundle(str(path), "0" * 64)

@pytest.mark.parametrize("name", ["../outside", "/outside", "payload/../outside", "./held-stage-plan.json"])
def test_traversal_or_foreign_member_refused(fixture, name):
    path, pin = bundle(fixture, extra=[(name, b"outside")])
    with pytest.raises(held.StageError, match="eight_member"):
        held.verify_bundle(path, pin)
    assert not (fixture["root"] / "outside").exists()

def test_duplicate_member_refused(fixture):
    path, pin = bundle(fixture, extra=[("held-stage-plan.json", fixture["members"]["held-stage-plan.json"])])
    with pytest.raises(held.StageError, match="eight_member"):
        held.verify_bundle(path, pin)

@pytest.mark.parametrize("member_type", [tarfile.SYMTYPE, tarfile.LNKTYPE,
                                        tarfile.DIRTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE])
def test_links_devices_directories_and_fifos_refused(fixture, member_type):
    path, pin = bundle(fixture, member_type=member_type)
    with pytest.raises(held.StageError, match="eight_member"):
        held.verify_bundle(path, pin)

def test_archive_mode_must_be_exactly_private_nonexecutable(fixture):
    path, pin = bundle(fixture, mode=0o700)
    with pytest.raises(held.StageError, match="eight_member"):
        held.verify_bundle(path, pin)

def test_payload_tamper_refused(fixture):
    path, pin = bundle(fixture, {"payload/SHA256SUMS": b"tampered"})
    with pytest.raises(held.StageError, match="payload_pin_mismatch"):
        held.verify_bundle(path, pin)

@pytest.mark.parametrize("value", [True, 0, None, "false"])
def test_false_operational_gates_require_actual_boolean_false(fixture, value):
    path, pin = changed_plan(fixture, lambda p: p["effects"].update({"queues": value}))
    with pytest.raises(held.StageError, match="operational_effects"):
        held.verify_bundle(path, pin)

@pytest.mark.parametrize("mutation", [
    lambda p: p["effects"].pop("healer"),
    lambda p: p["effects"].update({"unexpected_effect": False}),
    lambda p: p["activation"].update({"admitted": True}),
    lambda p: p.update({"admission": "admitted"}),
    lambda p: p.update({"staging_parent": str(Path(p["staging_parent"]).parent)}),
])
def test_closed_plan_and_parent_boundaries(fixture, mutation):
    path, pin = changed_plan(fixture, mutation)
    with pytest.raises(held.StageError):
        held.verify_bundle(path, pin)

def test_hold_cannot_admit_bootstrap(fixture):
    hold = json.loads(fixture["payload"]["HOLD.json"])
    hold["state_initialization"] = True
    data = json.dumps(hold).encode()
    fixture["plan"]["payload_files"]["HOLD.json"] = {"sha256": sha(data), "bytes": len(data), "mode": "0600"}
    path, pin = bundle(fixture, {"held-stage-plan.json": json.dumps(fixture["plan"]).encode(),
                               "payload/HOLD.json": data})
    with pytest.raises(held.StageError, match="hold_boundary"):
        held.verify_bundle(path, pin)

def test_duplicate_json_keys_are_refused(fixture):
    data = fixture["members"]["held-stage-plan.json"].decode()
    data = data[:-1] + ', "operation": "inert_file_staging"}'
    path, pin = bundle(fixture, {"held-stage-plan.json": data.encode()})
    with pytest.raises(held.StageError, match="duplicate_json_key"):
        held.verify_bundle(path, pin)

def test_stage_writes_only_six_payloads_and_provenance_and_rollback_preserves(fixture):
    untouched = fixture["root"] / "runtime.env"
    untouched.write_bytes(b"protected fixture")
    verified = candidate(fixture)
    receipt = apply(fixture, verified)
    target = Path(receipt["target"])
    assert set(p.name for p in target.iterdir()) == held.PAYLOAD_NAMES | {held.RECEIPT_NAME}
    assert stat.S_IMODE(target.stat().st_mode) == 0o700
    for name, data in fixture["payload"].items():
        assert (target / name).read_bytes() == data
        assert stat.S_IMODE((target / name).stat().st_mode) == 0o600
    receipt_bytes = (target / held.RECEIPT_NAME).read_bytes()
    checked = held.check_rollback(verified, receipt)
    assert checked["files_removed"] == 0
    assert not checked["data_removed"]
    assert untouched.read_bytes() == b"protected fixture"
    assert (target / held.RECEIPT_NAME).read_bytes() == receipt_bytes
    assert receipt["effects"] == {key: False for key in held.EFFECT_NAMES}

def test_stage_requires_explicit_apply_and_parent_receipt_digest(fixture):
    verified = candidate(fixture)
    with pytest.raises(held.StageError, match="explicit_apply"):
        held.stage(verified, str(fixture["receipt"]), sha(fixture["receipt"].read_bytes()))
    with pytest.raises(held.StageError, match="parent_receipt_digest_mismatch"):
        held.stage(verified, str(fixture["receipt"]), "0" * 64, True)
    assert not Path(verified["plan"]["target"]).exists()

@pytest.mark.parametrize("collision", ["directory", "file", "broken_symlink"])
def test_existing_target_always_preserved(fixture, collision):
    target = Path(fixture["plan"]["target"])
    if collision == "directory":
        target.mkdir(); (target / "foreign").write_text("preserve")
    elif collision == "file":
        target.write_text("preserve")
    else:
        target.symlink_to(fixture["root"] / "missing")
    with pytest.raises(held.StageError, match="existing_target_preserved"):
        apply(fixture)
    assert target.exists() or target.is_symlink()

def test_symlink_parent_is_refused_without_entering_destination(fixture):
    real = fixture["root"] / "other-parent";real.mkdir()
    fixture["parent"].rmdir()
    fixture["parent"].symlink_to(real, target_is_directory=True)
    with pytest.raises(OSError):
        apply(fixture)
    assert list(real.iterdir()) == []

def test_world_writable_parent_is_unqualified(fixture):
    fixture["parent"].chmod(0o777)
    with pytest.raises(held.StageError, match="owned_parent"):
        apply(fixture)
    assert not Path(fixture["plan"]["target"]).exists()

def test_missing_parent_is_never_created(fixture):
    fixture["parent"].rmdir()
    with pytest.raises(FileNotFoundError):
        apply(fixture)
    assert not fixture["parent"].exists()

def test_partial_stage_is_preserved_no_automatic_cleanup(fixture, monkeypatch):
    verified = candidate(fixture)
    original = held.create_file
    calls = 0
    def fail_after_first(directory_fd, name, data):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("fixture injected write failure")
        original(directory_fd, name, data)
    monkeypatch.setattr(held, "create_file", fail_after_first)
    with pytest.raises(OSError, match="injected"):
        apply(fixture, verified)
    target = Path(verified["plan"]["target"])
    assert target.is_dir()
    assert len(list(target.iterdir())) == 1
    assert not (target / held.RECEIPT_NAME).exists()

@pytest.mark.parametrize("tamper", ["payload", "mode", "foreign", "symlink", "receipt", "directory"])
def test_rollback_never_deletes_modified_or_foreign_state(fixture, tamper):
    verified = candidate(fixture)
    receipt = apply(fixture, verified)
    target = Path(receipt["target"])
    if tamper == "payload":
        (target / "SHA256SUMS").write_bytes(b"changed")
    elif tamper == "mode":
        (target / "SHA256SUMS").chmod(0o644)
    elif tamper == "foreign":
        (target / "foreign").write_bytes(b"preserve")
    elif tamper == "symlink":
        (target / "SHA256SUMS").unlink()
        (target / "SHA256SUMS").symlink_to(fixture["receipt"])
    elif tamper == "receipt":
        (target / held.RECEIPT_NAME).write_text("{}")
    else:
        target.chmod(0o755)
    before = {p.name for p in target.iterdir()}
    with pytest.raises((held.StageError, OSError)):
        held.check_rollback(verified, receipt)
    assert {p.name for p in target.iterdir()} == before

def test_bundle_symlink_is_not_opened(fixture):
    path, pin = bundle(fixture)
    link = fixture["root"] / "linked.tar.gz";link.symlink_to(path)
    with pytest.raises(OSError):
        held.verify_bundle(str(link), pin)

def test_expansion_is_bounded_before_tar_parsing(fixture):
    import gzip
    path = fixture["root"] / "candidate.tar.gz"
    raw = gzip.compress(b"x" * (held.MAX_EXPANDED_BYTES + 1))
    path.write_bytes(raw)
    with pytest.raises(held.StageError, match="expanded_archive_limit"):
        held.verify_bundle(str(path), sha(raw))

def test_shared_payload_is_preserved_during_rollback(fixture):
    verified = candidate(fixture)
    receipt = apply(fixture, verified)
    target = Path(receipt["target"])
    outside = fixture["root"] / "outside-link"
    os.link(target / "SHA256SUMS", outside)
    with pytest.raises(held.StageError, match="shared_file_preserved"):
        held.check_rollback(verified, receipt)
    assert outside.exists() and (target / "SHA256SUMS").exists()

def test_cli_malformed_archive_has_receipt_without_raw_content(fixture, monkeypatch, capsys):
    path = fixture["root"] / "invalid.tar.gz"
    raw = b"SENSITIVE_ARCHIVE_CANARY"
    path.write_bytes(raw)
    monkeypatch.setattr(held.sys, "argv", [str(SCRIPT), "verify", "--bundle", str(path),
        "--bundle-sha256", sha(raw)])
    assert held.main() == 2
    out = capsys.readouterr().out
    assert "SENSITIVE_ARCHIVE_CANARY" not in out
    receipt = json.loads(out)
    assert receipt["status"] == "refused"
    assert receipt["existing_state_preserved"] is True
    assert not receipt["bootstrap_allowed"]

def test_stage_parent_fsync_failure_refuses_success_and_preserves_files(fixture, monkeypatch, capsys):
    path, pin = bundle(fixture)
    parent_identity = (fixture["parent"].stat().st_dev, fixture["parent"].stat().st_ino)
    original = held.os.fsync
    def failing_parent(fd):
        st = os.fstat(fd)
        if (st.st_dev, st.st_ino) == parent_identity:
            raise OSError("fixture parent fsync failure")
        return original(fd)
    monkeypatch.setattr(held.os, "fsync", failing_parent)
    monkeypatch.setattr(held.sys, "argv", [str(SCRIPT), "stage", "--bundle", path,
        "--bundle-sha256", pin, "--parent-receipt", str(fixture["receipt"]),
        "--parent-receipt-sha256", sha(fixture["receipt"].read_bytes()), "--apply"])
    assert held.main() == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "refused"
    target = Path(fixture["plan"]["target"])
    assert set(p.name for p in target.iterdir()) == held.PAYLOAD_NAMES | {held.RECEIPT_NAME}
    assert all((target / name).read_bytes() == data for name, data in fixture["payload"].items())

def test_stage_synchronizes_target_and_parent_before_success(fixture, monkeypatch):
    parent_identity = (fixture["parent"].stat().st_dev, fixture["parent"].stat().st_ino)
    synced = []
    original = held.os.fsync
    def recording_fsync(fd):
        st = os.fstat(fd)
        synced.append((st.st_dev, st.st_ino))
        return original(fd)
    monkeypatch.setattr(held.os, "fsync", recording_fsync)
    receipt = apply(fixture)
    target = Path(receipt["target"])
    target_identity = (target.stat().st_dev, target.stat().st_ino)
    assert synced[-2:] == [target_identity, parent_identity]
    assert receipt["status"] == "staged_inert"

def test_rollback_same_target_inode_in_replaced_parent_is_refused(fixture):
    verified = candidate(fixture)
    receipt = apply(fixture, verified)
    parent = fixture["parent"]
    old = parent.with_name("retained-original-staged")
    target_name = Path(receipt["target"]).name
    parent.rename(old)
    parent.mkdir(mode=0o700)
    (old / target_name).rename(parent / target_name)
    target = parent / target_name
    assert target.stat().st_ino == receipt["target_inode"]
    before = set(p.name for p in target.iterdir())
    with pytest.raises(held.StageError, match="changed_parent_custody"):
        held.check_rollback(verified, receipt)
    assert set(p.name for p in target.iterdir()) == before

@pytest.mark.parametrize("mode", [0o755, 0o777])
def test_rollback_parent_mode_change_is_refused_and_preserved(fixture, mode):
    verified = candidate(fixture)
    receipt = apply(fixture, verified)
    fixture["parent"].chmod(mode)
    target = Path(receipt["target"])
    before = set(p.name for p in target.iterdir())
    with pytest.raises(held.StageError, match="parent"):
        held.check_rollback(verified, receipt)
    assert set(p.name for p in target.iterdir()) == before

def test_rollback_detects_foreign_file_added_during_file_reads(fixture, monkeypatch):
    verified = candidate(fixture)
    receipt = apply(fixture, verified)
    target = Path(receipt["target"])
    foreign = target / "foreign-during-read"
    original = held.bounded_regular_read
    injected = False
    def injecting_read(fd, *args, **kwargs):
        nonlocal injected
        data = original(fd, *args, **kwargs)
        if not injected:
            injected = True
            foreign.write_bytes(b"preserve concurrent foreign data")
        return data
    monkeypatch.setattr(held, "bounded_regular_read", injecting_read)
    with pytest.raises(held.StageError, match="foreign|directory"):
        held.check_rollback(verified, receipt)
    assert foreign.read_bytes() == b"preserve concurrent foreign data"
    assert len(list(target.iterdir())) == 8

def test_rollback_detects_changes_to_an_already_read_file(fixture, monkeypatch):
    verified = candidate(fixture)
    receipt = apply(fixture, verified)
    target = Path(receipt["target"])
    paths_by_inode = {p.stat().st_ino: p for p in target.iterdir()}
    original = held.bounded_regular_read
    first = None
    calls = 0
    def injecting_read(fd, *args, **kwargs):
        nonlocal first, calls
        data = original(fd, *args, **kwargs)
        calls += 1
        if calls == 1:
            first = paths_by_inode[os.fstat(fd).st_ino]
        elif calls == 2:
            first.write_bytes(b"preserve concurrently modified previously verified file")
        return data
    monkeypatch.setattr(held, "bounded_regular_read", injecting_read)
    with pytest.raises(held.StageError, match="files_changed_during_inspection"):
        held.check_rollback(verified, receipt)
    assert first.read_bytes() == b"preserve concurrently modified previously verified file"
    assert len(list(target.iterdir())) == 7

def test_rollback_rebinds_parent_namespace_after_reads(fixture, monkeypatch):
    verified = candidate(fixture)
    receipt = apply(fixture, verified)
    parent = fixture["parent"]
    retained = parent.with_name("retained-during-inspection")
    target_name = Path(receipt["target"]).name
    original = held.bounded_regular_read
    injected = False
    def injecting_read(fd, *args, **kwargs):
        nonlocal injected
        data = original(fd, *args, **kwargs)
        if not injected:
            injected = True
            parent.rename(retained)
            parent.mkdir(mode=0o700)
        return data
    monkeypatch.setattr(held, "bounded_regular_read", injecting_read)
    with pytest.raises(held.StageError, match="changed_parent_custody"):
        held.check_rollback(verified, receipt)
    assert len(list((retained / target_name).iterdir())) == 7
    assert list(parent.iterdir()) == []

def test_rollback_detects_target_directory_renamed_during_reads(fixture, monkeypatch):
    verified = candidate(fixture)
    receipt = apply(fixture, verified)
    target = Path(receipt["target"])
    moved = target.with_name("retained-moved-target")
    original = held.bounded_regular_read
    injected = False
    def injecting_read(fd, *args, **kwargs):
        nonlocal injected
        data = original(fd, *args, **kwargs)
        if not injected:
            injected = True
            target.rename(moved)
        return data
    monkeypatch.setattr(held, "bounded_regular_read", injecting_read)
    with pytest.raises((held.StageError, FileNotFoundError)):
        held.check_rollback(verified, receipt)
    assert len(list(moved.iterdir())) == 7
    assert not target.exists()
