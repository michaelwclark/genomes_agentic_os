"""Actual scoped file effects in disposable roots; no live service or credentials."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import platform
import stat
from datetime import datetime, timedelta, timezone

import pytest

from genomes_agentic_os import memory_endpoint_migration as m

CONFIG = "harness/config.toml"
FACTORY = "harness/shared_factory/config.toml"
HOOK = "harness/hooks/harness-emit-trace.sh"
TOML = b'# preserve this\r\n[other]\r\ncredential = "fixture-sentinel"\r\n[mcp_servers.genomes_brain]\r\nurl = "http://127.0.0.1:3155/mcp" # managed\r\n'
EMITTER = b'#!/bin/bash\nMCP_URL="${GENOMES_BRAIN_MCP_URL:-${LOSMON_MEMORY_MCP_URL:-http://127.0.0.1:3155/mcp}}"\necho unchanged\n'


@pytest.fixture
def root(tmp_path):
    root = (tmp_path / "installed").resolve()
    root.mkdir(mode=0o700)
    (root / ".agentic_root").write_bytes(b"")
    for relative, data in ((CONFIG, TOML), (FACTORY, TOML), (HOOK, EMITTER)):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(0o700 if relative == HOOK else 0o600)
    return root


def service(**changes):
    return {"schema": "memory-endpoint-service-verification/v1", "status": "verified",
            "service": "genomes_brain", "endpoint": m.NEW_ENDPOINT, "host": "fixture",
            "machine": platform.node(), "health_status": "healthy",
            "verified_at": datetime.now(timezone.utc).isoformat(), **changes}


def plan(root, paths=None, receipt=None):
    return m.plan_memory_endpoint(root, host="fixture", paths=paths or [CONFIG, FACTORY, HOOK],
                                  service_receipt=receipt or service())


def resign(value):
    value["plan_id"] = m._sha(m._encoded({k: v for k, v in value.items() if k != "plan_id"}))
    return value


def test_apply_rollback_bytes_modes_identity_and_idempotency(root):
    before = {p: (root / p).read_bytes() for p in [CONFIG, FACTORY, HOOK]}
    p = plan(root)
    assert m.execute_memory_endpoint(root, p, operation="apply")["target_changes"] is False
    assert not (root / m.JOURNAL_DIR).exists() and not (root / m.LOCK_NAME).exists()
    result = m.execute_memory_endpoint(root, p, operation="apply", apply=True)
    assert result["status"] == "completed" and set(result["changed"]) == set(before)
    for entry in p["entries"]:
        path = root / entry["path"]
        assert path.read_bytes() == before[entry["path"]].replace(m.OLD_ENDPOINT.encode(), m.NEW_ENDPOINT.encode())
        assert stat.S_IMODE(path.stat().st_mode) == entry["identity"]["mode"]
        assert path.stat().st_uid == entry["identity"]["uid"]
    assert m.execute_memory_endpoint(root, p, operation="apply", apply=True)["status"] == "already_matches"
    journal = root / result["journal"]
    assert "fixture-sentinel" not in journal.read_text()
    assert stat.S_IMODE(journal.stat().st_mode) == 0o600
    assert not list(root.rglob(".memory-endpoint-????????????????????????"))
    assert m.execute_memory_endpoint(root, p, operation="rollback", apply=True)["status"] == "completed"
    assert {path: (root / path).read_bytes() for path in before} == before
    assert m.execute_memory_endpoint(root, p, operation="rollback", apply=True)["status"] == "already_matches"
    assert m.execute_memory_endpoint(root, p, operation="apply", apply=True)["status"] == "completed"


@pytest.mark.parametrize("body,disposition", [
    (b'[mcp_servers.genomes_brain]\ncommand = "ssh"\nargs = ["preserve-native"]\n', "stdio_preserved"),
    (b'[mcp_servers.genomes_brain]\nurl = "https://custom.invalid/mcp"\n', "custom_url_preserved"),
    (b'[mcp_servers.genomes_brain]\nurl = "http://127.0.0.1:3166/mcp"\n', "current_endpoint"),
    (b'[unrelated]\nvalue = "fixture-sentinel"\n', "managed_server_absent"),
])
def test_custom_stdio_current_absent_preserved(root, body, disposition):
    (root / CONFIG).write_bytes(body)
    p = plan(root, [CONFIG])
    assert p["entries"][0]["disposition"] == disposition
    m.execute_memory_endpoint(root, p, operation="apply", apply=True)
    assert (root / CONFIG).read_bytes() == body
    assert "custom.invalid" not in json.dumps(p)


@pytest.mark.parametrize("body", [
    b'[mcp_servers.genomes_brain]\nurl="http://127.0.0.1:3155/mcp"\nurl="duplicate"',
    b'[mcp_servers.genomes_brain]\ncommand="ssh"\nurl="http://127.0.0.1:3155/mcp"',
    b'[mcp_servers.genomes_brain]\nurl=3', b'[invalid',
    b'mcp_servers.genomes_brain.url="http://127.0.0.1:3155/mcp"',
])
def test_ambiguous_or_unsupported_toml_refused(root, body):
    (root / CONFIG).write_bytes(body)
    with pytest.raises(m.MemoryEndpointMigrationError):
        plan(root, [CONFIG])


def test_hook_custom_and_duplicate_declarations(root):
    body = b'MCP_URL="${PRIVATE_ENDPOINT:-https://custom.invalid/mcp}"\n'
    (root / HOOK).write_bytes(body)
    assert plan(root, [HOOK])["entries"][0]["disposition"] == "current_or_custom_fallback_preserved"
    (root / HOOK).write_bytes(EMITTER + b'MCP_URL="duplicate"\n')
    with pytest.raises(m.MemoryEndpointMigrationError):
        plan(root, [HOOK])


@pytest.mark.parametrize("changes", [
    {"endpoint": m.OLD_ENDPOINT}, {"host": "other"}, {"machine": "other"},
    {"status": "unverified"}, {"verified_at": "not-date"}, {"verified_at": []},
    {"verified_at": lambda: (datetime.now(timezone.utc)-timedelta(minutes=16)).isoformat()},
    {"verified_at": lambda: (datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat()},
])
def test_service_binding_and_freshness_refused(root, changes):
    with pytest.raises(m.MemoryEndpointMigrationError):
        plan(root, receipt=service(**{key: value() if callable(value) else value for key, value in changes.items()}))
    assert not (root / m.LOCK_NAME).exists()


def test_stale_receipt_still_allows_owned_rollback(root, monkeypatch):
    p = plan(root)
    m.execute_memory_endpoint(root, p, operation="apply", apply=True)
    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz)+timedelta(minutes=16)
    monkeypatch.setattr(m, "datetime", Later)
    with pytest.raises(m.MemoryEndpointMigrationError, match="stale"):
        m.execute_memory_endpoint(root, p, operation="apply", apply=True)
    m.execute_memory_endpoint(root, p, operation="rollback", apply=True)
    assert (root / CONFIG).read_bytes() == TOML


@pytest.mark.parametrize("mutation", ["content", "mode", "inode", "symlink", "hardlink"])
def test_file_drift_or_unsafe_custody_refused_before_effect(root, mutation):
    p = plan(root)
    path = root / FACTORY
    if mutation == "content": path.write_bytes(TOML+b"# concurrent\n")
    elif mutation == "mode": path.chmod(0o666)
    elif mutation == "inode":
        path.unlink(); path.write_bytes(TOML); path.chmod(0o600)
    elif mutation == "symlink":
        path.unlink(); path.symlink_to(root / CONFIG)
    else: os.link(path, root / "extra-link")
    with pytest.raises(m.MemoryEndpointMigrationError):
        m.execute_memory_endpoint(root, p, operation="apply", apply=True)
    assert (root / CONFIG).read_bytes() == TOML


def test_plan_digest_runtime_root_offset_and_output_guards(root, monkeypatch):
    base = plan(root)
    for field, value in [("machine", "other"), ("runtime", {}), ("root", "/other")]:
        p = copy.deepcopy(base); p[field] = value; resign(p)
        with pytest.raises(m.MemoryEndpointMigrationError): m.execute_memory_endpoint(root, p, operation="apply", apply=True)
    p = copy.deepcopy(base); p["entries"][0]["offset"] += 1; resign(p)
    with pytest.raises(m.MemoryEndpointMigrationError): m.execute_memory_endpoint(root, p, operation="apply", apply=True)
    p = copy.deepcopy(base); p["entries"][0]["after_sha256"] = "0"*64; resign(p)
    with pytest.raises(m.MemoryEndpointMigrationError): m.execute_memory_endpoint(root, p, operation="apply", apply=True)
    p = copy.deepcopy(base); p["host"] = "tampered"
    with pytest.raises(m.MemoryEndpointMigrationError): m.execute_memory_endpoint(root, p, operation="apply")
    assert not (root / m.LOCK_NAME).exists()


def test_lock_contention_and_rollback_without_journal(root):
    p = plan(root)
    with m._directory(root) as descriptor, m._lock(descriptor):
        with pytest.raises(m.MemoryEndpointMigrationError): m.execute_memory_endpoint(root, p, operation="apply", apply=True)
    with pytest.raises(m.MemoryEndpointMigrationError): m.execute_memory_endpoint(root, p, operation="rollback", apply=True)


def test_concurrent_replace_refusal_and_guarded_rollback(root, monkeypatch):
    p = plan(root)
    original = m._atomic
    def race(parent, name, data, mode, gid, before=None, intent=None):
        if before is not None:
            path = root / CONFIG
            path.write_bytes(TOML+b"# concurrent\n")
        return original(parent, name, data, mode, gid, before, intent)
    monkeypatch.setattr(m, "_atomic", race)
    with pytest.raises(m.MemoryEndpointMigrationError): m.execute_memory_endpoint(root, p, operation="apply", apply=True)
    assert (root / CONFIG).read_bytes().endswith(b"# concurrent\n")
    assert not list(root.rglob(".memory-endpoint-????????????????????????"))
    monkeypatch.setattr(m, "_atomic", original)
    with pytest.raises(m.MemoryEndpointMigrationError): m.execute_memory_endpoint(root, p, operation="rollback", apply=True)


def test_partial_failure_recovery_and_history(root, monkeypatch):
    p = plan(root)
    original = m._atomic
    count = 0
    def fail_second(parent, name, data, mode, gid, before=None, intent=None):
        nonlocal count
        if before is not None:
            count += 1
            if count == 2: raise OSError("fixture failure")
        return original(parent, name, data, mode, gid, before, intent)
    monkeypatch.setattr(m, "_atomic", fail_second)
    with pytest.raises(m.MemoryEndpointMigrationError): m.execute_memory_endpoint(root, p, operation="apply", apply=True)
    journal = root / m.JOURNAL_DIR / (p["plan_id"]+".json")
    assert json.loads(journal.read_text())["history"][-1]["status"] == "partial_failure"
    monkeypatch.setattr(m, "_atomic", original)
    assert m.execute_memory_endpoint(root, p, operation="apply", apply=True)["status"] == "completed"


def test_post_replace_pending_recovery(root, monkeypatch):
    p = plan(root, [CONFIG])
    original = m._atomic
    class Crash(BaseException): pass
    def crash(parent, name, data, mode, gid, before=None, intent=None):
        result = original(parent, name, data, mode, gid, before, intent)
        if before is not None: raise Crash()
        return result
    monkeypatch.setattr(m, "_atomic", crash)
    with pytest.raises(Crash): m.execute_memory_endpoint(root, p, operation="apply", apply=True)
    monkeypatch.setattr(m, "_atomic", original)
    assert m.execute_memory_endpoint(root, p, operation="apply", apply=True)["status"] == "already_matches"
    assert m.execute_memory_endpoint(root, p, operation="rollback", apply=True)["status"] == "completed"


@pytest.mark.parametrize("body", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e309}', b'[]', b'\xff'])
def test_strict_bounded_document(root, body):
    path = root / "receipt.json"; path.write_bytes(body); path.chmod(0o600)
    with pytest.raises(m.MemoryEndpointMigrationError): m.read_document(path)


def test_path_allowlist_parent_symlink_marker_and_size(root):
    for paths in [["../config.toml"], [CONFIG, CONFIG], ["harness/other.toml"]]:
        with pytest.raises(m.MemoryEndpointMigrationError): plan(root, paths)
    (root / ".agentic_root").unlink()
    with pytest.raises(m.MemoryEndpointMigrationError): plan(root)
    (root / ".agentic_root").write_bytes(b"")
    (root / CONFIG).write_bytes(b"x"*(m.MAX_FILE_BYTES+1))
    with pytest.raises(m.MemoryEndpointMigrationError): plan(root)


def test_journal_tampering_refused(root):
    p = plan(root, [CONFIG])
    result = m.execute_memory_endpoint(root, p, operation="apply", apply=True)
    path = root / result["journal"]
    original = path.read_bytes()
    for patch in [{"effects": {CONFIG: {"operation": "apply", "identity": []}}},
                  {"pending": {}}, {"pending": {"path": CONFIG, "operation": "apply",
                    "temporary": "../../outside", "identity": p["entries"][0]["identity"], "sha256": "0"*64}},
                  {"plan_id": "0"*64}]:
        value = json.loads(original); value.update(patch); path.write_text(json.dumps(value))
        with pytest.raises(m.MemoryEndpointMigrationError): m.execute_memory_endpoint(root, p, operation="rollback", apply=True)
    path.write_bytes(original)
    replacement = root / "replacement"; replacement.write_bytes((root / CONFIG).read_bytes()); replacement.chmod(0o600)
    os.replace(replacement, root / CONFIG)
    with pytest.raises(m.MemoryEndpointMigrationError): m.execute_memory_endpoint(root, p, operation="rollback", apply=True)


def test_parent_symlink_and_metadata_refusals(root, tmp_path, monkeypatch):
    alias = tmp_path / "alias"; alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(m.MemoryEndpointMigrationError): plan(alias)
    root.chmod(0o777)
    with pytest.raises(m.MemoryEndpointMigrationError): plan(root)
    root.chmod(0o700)
    monkeypatch.setattr(m, "tomllib", None)
    with pytest.raises(m.MemoryEndpointMigrationError): plan(root)


def test_missing_lock_support_and_bounded_journal(root, monkeypatch):
    p = plan(root)
    monkeypatch.setattr(m, "fcntl", None)
    with pytest.raises(m.MemoryEndpointMigrationError): m.execute_memory_endpoint(root, p, operation="apply", apply=True)
    with m._directory(root) as descriptor:
        with pytest.raises(m.MemoryEndpointMigrationError):
            m._save_journal(descriptor, {"plan_id": "0"*64, "history": ["x"*m.MAX_JSON_BYTES]})


def test_preserved_file_inode_drift_refused(root):
    path = root / CONFIG; path.write_bytes(b'[mcp_servers.genomes_brain]\ncommand="ssh"\n')
    p = plan(root)
    replacement = root / "replacement"; replacement.write_bytes(path.read_bytes()); replacement.chmod(0o600)
    os.replace(replacement, path)
    with pytest.raises(m.MemoryEndpointMigrationError): m.execute_memory_endpoint(root, p, operation="apply", apply=True)
    assert (root / FACTORY).read_bytes() == TOML


@pytest.mark.parametrize("relative,body", [
    (CONFIG, b'[custom]\nurl="http://127.0.0.1:3155/mcp"\n'+TOML),
    (HOOK, b'# http://127.0.0.1:3155/mcp is a preserved comment\n'+EMITTER),
])
def test_rehashed_plan_cannot_patch_custom_url_or_comment(root, relative, body):
    path = root/relative; path.write_bytes(body)
    p = plan(root, [relative])
    entry = p["entries"][0]
    assert entry["offset"] != body.index(m.OLD_ENDPOINT.encode())
    entry["offset"] = body.index(m.OLD_ENDPOINT.encode())
    entry["after_sha256"] = m._sha(m._patch(body, entry["offset"], m.OLD_ENDPOINT, m.NEW_ENDPOINT))
    resign(p)
    for operation in ["apply", "rollback"]:
        with pytest.raises(m.MemoryEndpointMigrationError, match="actual managed declaration"):
            m.execute_memory_endpoint(root, p, operation=operation, apply=True)
    assert path.read_bytes() == body
    assert not (root / m.LOCK_NAME).exists() and not (root / m.JOURNAL_DIR).exists()


def test_rehashed_plan_cannot_skip_actual_managed_declaration(root):
    p = plan(root, [CONFIG])
    entry = p["entries"][0]
    for key in ["offset", "before", "after", "after_sha256"]: entry.pop(key)
    entry["disposition"] = "custom_url_preserved"
    resign(p)
    with pytest.raises(m.MemoryEndpointMigrationError, match="actual managed declaration"):
        m.execute_memory_endpoint(root, p, operation="apply", apply=True)
    assert not (root / m.LOCK_NAME).exists()
