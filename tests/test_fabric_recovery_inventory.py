"""No-follow metadata, secret suppression and authority boundary regressions."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "installers/execution-fabric/bin/recovery-inventory.py"
spec = importlib.util.spec_from_file_location("fabric_recovery_inventory", SCRIPT)
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)

@pytest.fixture
def root(tmp_path):
    path = tmp_path.resolve() / "recovery"
    path.mkdir(mode=0o700)
    return path

def run(root, depth=4, entries=2000, budget=83886080):
    return inventory.inventory(str(root), depth, entries, budget)

def test_payload_hash_fixed_header_and_authority_are_distinct(root):
    (root / "fabric").mkdir()
    data = b"SQLite format 3\x00" + b"fixture"
    (root / "fabric/state.sqlite3").write_bytes(data)
    (root / "postgres").mkdir(); (root / "postgres/PG_VERSION").write_text("17\n")
    (root / "witness").mkdir(); (root / "witness/leader.json").write_text('{"epoch":91}')
    (root / "objects").mkdir(); (root / "objects/item.enc").write_bytes(b"opaque fixture")
    receipt = run(root)
    rows = {row["relative_path"]: row for row in receipt["rows"]}
    assert rows["fabric/state.sqlite3"]["sha256"] == hashlib.sha256(data).hexdigest()
    assert rows["fabric/state.sqlite3"]["safe_header_classification"] == "sqlite_magic"
    assert "sha256" not in rows["postgres/PG_VERSION"]
    assert "sha256" not in rows["witness/leader.json"]
    assert all(receipt["candidate_roles"][role] for role in ("postgresql", "witness", "objects", "fabric_state"))
    assert receipt["authority"] == "unproven"
    assert receipt["recovery_set_complete"] is False
    assert receipt["bootstrap_allowed"] is False

@pytest.mark.parametrize("filename", ["runtime.env", ".env.backup", "credentials.bak",
    "private-key.backup", "configuration.json", "account.sqlite3", "events.log", "token.dump"])
def test_sensitive_contents_and_hashes_never_leave_metadata(root, filename):
    canary = "DO_NOT_OUTPUT_CREDENTIAL_VALUE_1234"
    (root / filename).write_text(canary)
    receipt = run(root)
    row = receipt["rows"][0]
    assert row["data_read"] == "none_protected_metadata_only"
    assert "sha256" not in row and "safe_header_classification" not in row
    assert canary not in json.dumps(receipt)

def test_protected_directory_is_not_descended(root):
    (root / ".ssh").mkdir()
    (root / ".ssh/key.backup").write_text("SECRET_CANARY")
    receipt = run(root)
    assert [row["relative_path"] for row in receipt["rows"]] == [".ssh"]
    assert receipt["counts"]["protected_directories_skipped"] == 1
    assert not receipt["bounded_inventory_complete"]

def test_symlink_and_fifo_are_metadata_only(root):
    (root / "external.sqlite3").symlink_to("/etc/passwd")
    os.mkfifo(root / "pipe.sqlite3")
    receipt = run(root)
    rows = {row["relative_path"]: row for row in receipt["rows"]}
    assert rows["external.sqlite3"]["type"] == "symlink_not_followed"
    assert rows["pipe.sqlite3"]["type"] == "special_file_not_opened"
    assert receipt["counts"]["hashed_bytes"] == 0
    assert receipt["counts"]["symlinks_skipped"] == 1
    assert receipt["counts"]["special_files_skipped"] == 1

def test_root_symlink_or_symlink_ancestor_is_refused(root):
    linked = root.parent / "link"
    linked.symlink_to(root, target_is_directory=True)
    (root / "nested").mkdir()
    for path in (linked, linked / "nested"):
        receipt = run(path)
        assert receipt["root_status"] != "observed"
        assert receipt["rows"] == []
        assert not receipt["bootstrap_allowed"]

def test_missing_and_denied_root_are_distinct(root, monkeypatch):
    missing = run(root / "absent")
    assert missing["root_status"] == "absent_or_changed_during_inventory"
    def denied(_):
        raise PermissionError("fixture")
    monkeypatch.setattr(inventory, "open_root_nofollow", denied)
    receipt = run(root)
    assert receipt["root_status"] == "inaccessible"
    assert receipt["counts"]["inaccessible"] == 1
    assert not receipt["bootstrap_allowed"]

def test_entry_depth_and_total_hash_bounds(root):
    for n in range(8):
        (root / ("payload%d.backup" % n)).write_bytes(b"x" * 32)
    limited = run(root, entries=3)
    assert limited["counts"]["listed_entries"] <= 3
    assert limited["counts"]["entry_limit_reached"]
    assert not limited["bounded_inventory_complete"]
    budget = run(root, budget=40)
    assert budget["counts"]["hashed_bytes"] <= 40
    assert budget["counts"]["hashed_files"] == 1
    assert budget["counts"]["hash_budget_skipped"] == 7
    (root / "level1").mkdir(); (root / "level1/level2").mkdir()
    (root / "level1/level2/hidden.backup").write_bytes(b"deep")
    shallow = run(root, depth=1)
    assert all("/" not in row["relative_path"] for row in shallow["rows"])
    assert shallow["counts"]["depth_truncated"] > 0

@pytest.mark.parametrize(("header", "classification"), [
    (b"SQLite format 3\x00", "sqlite_magic"), (b"\x1f\x8b", "gzip_magic"),
    (b"PK\x03\x04", "zip_magic"), (b"\xfd7zXZ\x00", "xz_magic"),
    (b"\x28\xb5\x2f\xfd", "zstd_magic"), (b"x"*257+b"ustar", "tar_magic"),
    (b"SECRET_LITERAL", "unrecognized_header"),
])
def test_header_output_is_only_fixed_classification(header, classification):
    assert inventory.safe_header_kind(header) == classification

def test_file_changed_during_read_has_no_digest(root, monkeypatch):
    path = root / "file.backup";path.write_bytes(b"stable")
    original = inventory.os.read
    fired = False
    def changing(fd, count):
        nonlocal fired
        data = original(fd, count)
        if not fired:
            fired = True
            path.write_bytes(b"changed")
        return data
    monkeypatch.setattr(inventory.os, "read", changing)
    receipt = run(root)
    row = receipt["rows"][0]
    assert row["status"] == "changed_during_read"
    assert "sha256" not in row
    assert receipt["counts"]["unavailable_or_changed"] == 1
    assert not receipt["bounded_inventory_complete"]

def test_file_permission_denial_is_preserved(root, monkeypatch):
    path = root / "file.backup";path.write_bytes(b"stable")
    original = inventory.os.open
    def denied(name, flags, *args, **kwargs):
        if name == "file.backup":
            raise PermissionError("fixture")
        return original(name, flags, *args, **kwargs)
    monkeypatch.setattr(inventory.os, "open", denied)
    receipt = run(root)
    assert receipt["rows"][0]["status"] == "inaccessible"
    assert receipt["counts"]["inaccessible"] == 1
    assert "sha256" not in receipt["rows"][0]

def test_unknown_extension_is_not_read(root):
    (root / "unrecognized").write_text("DO_NOT_OUTPUT_123")
    receipt = run(root)
    assert receipt["rows"][0]["data_read"] == "none_not_payload_allowlist"
    assert receipt["counts"]["hashed_bytes"] == 0
    assert "DO_NOT_OUTPUT_123" not in json.dumps(receipt)

def test_script_pin_is_its_actual_source():
    assert inventory.script_sha256() == hashlib.sha256(SCRIPT.read_bytes()).hexdigest()

@pytest.mark.parametrize(("depth", "entries", "budget"), [
    (0, 2, 0), (5, 2, 0), (1, 0, 0), (1, 2001, 0),
    (1, 2, -1), (1, 2, 83886081),
])
def test_library_bounds_cannot_exceed_reviewed_limits(root, depth, entries, budget):
    with pytest.raises(ValueError, match="hard_limits"):
        run(root, depth=depth, entries=entries, budget=budget)

def test_cli_requires_current_tool_pin_before_inventory(root, monkeypatch, capsys):
    monkeypatch.setattr(inventory.sys, "argv", [str(SCRIPT), "--root", str(root),
        "--expected-script-sha256", "0"*64, "--json"])
    calls = []
    monkeypatch.setattr(inventory, "inventory", lambda *args: calls.append(args))
    with pytest.raises(SystemExit) as stopped:
        inventory.main()
    assert stopped.value.code == 2
    assert calls == []
    assert "script digest differs" in capsys.readouterr().err

def test_cli_emits_only_metadata_receipt_for_explicit_root(root, monkeypatch, capsys):
    (root / "runtime.env").write_text("PRIVATE_CLI_CANARY")
    monkeypatch.setattr(inventory.sys, "argv", [str(SCRIPT), "--root", str(root),
        "--expected-script-sha256", inventory.script_sha256(), "--json"])
    assert inventory.main() == 0
    out = capsys.readouterr().out
    receipt = json.loads(out)
    assert "PRIVATE_CLI_CANARY" not in out
    assert receipt["root_path"] == str(root)
    assert receipt["script_sha256"] == hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    assert receipt["bootstrap_allowed"] is False
