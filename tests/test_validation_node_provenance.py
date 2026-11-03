"""Actual npm install/substitution and native locked-execution regressions."""
from __future__ import annotations

import json
from pathlib import Path
import os
import shlex
import sys
from contextlib import contextmanager

import pytest

from genomes_agentic_os import development_delivery as delivery
from genomes_agentic_os.long_run import start_run, control_run
from genomes_agentic_os.validation_node_provenance import dependency_closure, run_guard, LOCK, SNAPSHOT, _json
from test_development_validation_refresh import _fixture, _refresh, _bound, _write, _command_proof, _now
from test_development_delivery import _git
from test_long_run import _wait_for


def _app_contract(subdir=".", *, typescript=True):
    """Explicit selected-profile input, not a missing-binary inference."""
    required = {"eslint": "eslint", "prettier": "prettier"}
    if typescript:
        required["tsc"] = "typescript"
    return {"schema": "development-node-tool-contract/v1", "profile": "application_static",
            "project_subdir": subdir, "required_executables": required}


def _app_guard_context(tmp_path, *, typescript=True, source=True):
    """Helper-unit fixture only; it never claims actual npm/native admission."""
    worktree = tmp_path / "app"
    worktree.mkdir()
    selection = _app_contract(typescript=typescript)
    manifest = {"name": "locked-app", "version": "1.0.0", "devDependencies": {
        package: "1.2.3" for package in selection["required_executables"].values()}}
    packages = {"": manifest}
    root = worktree / "node_modules"
    (root / ".bin").mkdir(parents=True)
    for executable, package in selection["required_executables"].items():
        metadata = {"name": package, "version": "1.2.3", "bin": {executable: "cli.js"}}
        _write(root / package / "package.json", metadata)
        binary = root / package / "cli.js"
        binary.write_text("#!/usr/bin/env node\nconsole.log('1.2.3');\n")
        binary.chmod(0o755)
        (root / ".bin" / executable).symlink_to("../" + package + "/cli.js")
        packages["node_modules/" + package] = {"version": "1.2.3", "bin": metadata["bin"]}
    _write(worktree / "package.json", manifest)
    _write(worktree / "package-lock.json", {"lockfileVersion": 3, "packages": packages})
    head = "1" * 40
    if source:
        _git("init", "-b", "main", cwd=worktree)
        _git("config", "user.email", "synthetic@example.invalid", cwd=worktree)
        _git("config", "user.name", "Synthetic Node authority fixture", cwd=worktree)
        (worktree / ".gitignore").write_text("node_modules/\n")
        _git("add", ".gitignore", "package.json", "package-lock.json", cwd=worktree)
        _git("commit", "-m", "synthetic committed Node inputs", cwd=worktree)
        head = _git("rev-parse", "HEAD", cwd=worktree)
    base = tmp_path / "packet/artifacts/command-runs/async-runs"
    install, dependent = base / "install", base / "dependent"
    lock = install.parents[2] / LOCK
    for run, command in ((install, ["npm", "ci"]), (dependent, ["npx", "--no-install", "eslint", "--version"])):
        _write(run / "command.json", {"id": run.name, "run_dir": str(run), "work_dir": str(worktree),
            "expected_git_identity": {"head": head, "clean": "false"}, "mutation_lock": str(lock),
            "command": command, "environment_overrides": {}})
    _write(lock, {"run_id": install.name, "pid": os.getpid()})
    return install, dependent, worktree, lock, selection


@pytest.mark.parametrize("typescript", [False, True])
def test_explicit_app_static_capture_binds_declared_tools_without_playwright(tmp_path, typescript):
    from genomes_agentic_os.validation_node_provenance import APPLICATION_SCHEMA, contract_binding
    install, dependent, worktree, lock, selection = _app_guard_context(tmp_path, typescript=typescript)
    # Equivalent reported failure: the unchanged generic QA contract cannot
    # capture this app installation, and no successful capture is left behind.
    with pytest.raises(FileNotFoundError):
        run_guard("capture", install, install, worktree, "post-run", "-")
    assert not (install / SNAPSHOT).exists()
    binding = contract_binding(worktree, selection)
    prepared = run_guard("prepare", install, install, worktree, "preflight", "-", binding)
    capture = run_guard("capture", install, install, worktree, "post-run", "-", binding)
    snapshot = _json(install / SNAPSHOT)
    assert snapshot["schema"] == APPLICATION_SCHEMA
    assert prepared["tool_contract_fingerprint"] == capture["tool_contract_fingerprint"] == binding["fingerprint"]
    assert {row["executable"]: row["package"] for row in snapshot["tool_contract"]["installed_tools"]} == selection["required_executables"]
    assert all(row["version"] == "1.2.3" and len(row["sha256"]) == 64 for row in snapshot["tool_contract"]["installed_tools"])
    assert not (worktree / "node_modules/.bin/playwright").exists()
    _write(lock, {"run_id": dependent.name, "pid": os.getpid()})
    run_guard("verify", install, dependent, worktree, "preflight", capture["snapshot_sha256"], binding)
    run_guard("verify", install, dependent, worktree, "post-run", capture["snapshot_sha256"], binding)


@pytest.mark.parametrize("change", ["missing-eslint", "missing-tsc", "wrong-version", "wrong-owner", "wrong-bin",
    "contents", "mode", "manifest", "lock", "profile", "redirected-package", "redirected-manifest"])
def test_app_static_required_tool_and_frozen_contract_drift_is_refused(tmp_path, change):
    from genomes_agentic_os.validation_node_provenance import contract_binding
    install, dependent, worktree, lock, selection = _app_guard_context(tmp_path)
    binding = contract_binding(worktree, selection)
    capture = run_guard("capture", install, install, worktree, "post-run", "-", binding)
    root = worktree / "node_modules"
    if change.startswith("missing-"):
        (root / ".bin" / change.removeprefix("missing-")).unlink()
    elif change in {"wrong-version", "wrong-owner", "wrong-bin"}:
        path = root / "eslint/package.json"
        metadata = _json(path)
        if change == "wrong-version": metadata["version"] = "9.9.9"
        elif change == "wrong-owner": metadata["name"] = "another-package"
        else: metadata["bin"] = {"another-command": "cli.js"}
        _write(path, metadata)
    elif change == "contents": (root / "eslint/cli.js").write_text("unqualified new bytes")
    elif change == "mode": (root / "eslint/cli.js").chmod(0o644)
    elif change == "manifest":
        value = _json(worktree / "package.json"); value["devDependencies"].pop("eslint"); _write(worktree / "package.json", value)
    elif change == "lock":
        value = _json(worktree / "package-lock.json"); value["packages"]["node_modules/eslint"]["version"] = "9.9.9"; _write(worktree / "package-lock.json", value)
    elif change == "profile":
        reduced = {**selection, "required_executables": {"eslint": "eslint"}}
        binding = contract_binding(worktree, reduced)
    elif change == "redirected-package":
        # A symlinked package manifest must not be used as authority, even
        # when its destination happens to be another contained package.
        path = root / "eslint/package.json"; path.unlink(); path.symlink_to("../prettier/package.json")
    else:
        path = worktree / "package.json"; outside = tmp_path / "outside.json"; outside.write_bytes(path.read_bytes()); path.unlink(); path.symlink_to(outside)
    _write(lock, {"run_id": dependent.name, "pid": os.getpid()})
    with pytest.raises((ValueError, OSError)):
        run_guard("verify", install, dependent, worktree, "preflight", capture["snapshot_sha256"], binding)


@pytest.mark.parametrize("mutation", ["selector", "schema", "empty", "unsafe-bin", "unsafe-package", "undeclared", "unknown-field", "parent", "absolute", "noncanonical"])
def test_app_static_selection_cannot_remove_or_guess_requirements(tmp_path, mutation):
    from genomes_agentic_os.validation_node_provenance import contract_binding, node_project
    _, _, worktree, _, selection = _app_guard_context(tmp_path)
    if mutation == "selector": selection["profile"] = "skip_missing"
    elif mutation == "schema": selection["schema"] = "unknown/v1"
    elif mutation == "empty": selection["required_executables"] = {}
    elif mutation == "unsafe-bin": selection["required_executables"] = {"../eslint": "eslint"}
    elif mutation == "unsafe-package": selection["required_executables"] = {"eslint": "../eslint"}
    elif mutation == "undeclared": selection["required_executables"] = {"missing": "undeclared"}
    elif mutation == "unknown-field": selection["skip_missing"] = True
    elif mutation == "parent": selection["project_subdir"] = "../outside"
    elif mutation == "absolute": selection["project_subdir"] = str(tmp_path)
    else: selection["project_subdir"] = "./"
    with pytest.raises((ValueError, OSError)):
        node_project({"validation": {"node_tool_contract": selection}}, worktree)
        contract_binding(worktree, selection)


@pytest.mark.parametrize("location,explicit,allowed", [
    ("ui/node_modules/tool/cli.js", True, True),
    ("ui/node_modules/tool/cli.js", False, False),
    ("node_modules/tool/cli.js", True, False),
    ("node_modules/tool/cli.js", False, True),
    ("sibling/node_modules/tool/cli.js", True, False),
    ("ui/node_modules-other/cli.js", True, False),
    ("ui/scratch.js", True, False),
    ("ui/.npmrc", True, False),
])
def test_cleanliness_defers_only_the_exact_frozen_node_closure(tmp_path, location, explicit, allowed):
    from genomes_agentic_os.development_validation_refresh import _clean_worktree
    from test_development_delivery import _repository
    repo, _ = _repository(tmp_path)
    (repo / ".gitignore").write_text("node_modules/\nnode_modules-other/\nscratch.js\n.npmrc\n")
    _git("add", ".gitignore", cwd=repo); _git("commit", "-m", "fixture ignore rules", cwd=repo)
    (repo / "ui").mkdir()
    manifest = {"name": "cleanliness-fixture", "devDependencies": {
        name: "1.2.3" for name in _app_contract("ui")["required_executables"].values()}}
    _write(repo / "ui/package.json", manifest)
    _write(repo / "ui/package-lock.json", {"lockfileVersion": 3, "packages": {
        "": manifest, **{"node_modules/" + name: {"version": "1.2.3"} for name in manifest["devDependencies"]}}})
    _git("add", "ui/package.json", "ui/package-lock.json", cwd=repo)
    _git("commit", "-m", "committed selected Node input fixture", cwd=repo)
    path = repo / location
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text("ignored executable or config")
    profile = {"validation": {"node_tool_contract": _app_contract("ui")}} if explicit else {"validation": {}}
    assert _clean_worktree({"ticket": "TEST-1"}, tmp_path, repo, profile) is allowed


@pytest.mark.parametrize("selection", [None, {"schema": "unknown"}])
def test_cleanliness_never_uses_invalid_explicit_node_selection(tmp_path, selection):
    from genomes_agentic_os.development_validation_refresh import _clean_worktree
    from test_development_delivery import _repository
    repo, _ = _repository(tmp_path)
    assert not _clean_worktree({}, tmp_path, repo, {"validation": {"node_tool_contract": selection}})


def test_cleanliness_rejects_redirected_project_before_any_node_exemption(tmp_path):
    from genomes_agentic_os.development_validation_refresh import _clean_worktree
    from test_development_delivery import _repository
    repo, _ = _repository(tmp_path)
    outside = tmp_path / "outside"; outside.mkdir()
    (repo / "ui").symlink_to(outside, target_is_directory=True)
    assert not _clean_worktree({}, tmp_path, repo, {"validation": {"node_tool_contract": _app_contract("ui")}})


@pytest.mark.parametrize("filename", ["package.json", "package-lock.json"])
@pytest.mark.parametrize("boundary", ["producer", "consumer", "command-authority"])
def test_ignored_app_manifest_cannot_supply_untracked_npm_lifecycle_authority(tmp_path, boundary, filename):
    """No npm or scripts execute: an ignored manifest must fail before admission."""
    from genomes_agentic_os.development_validation_refresh import _clean_worktree
    from genomes_agentic_os.validation_command_authority import runtime_provenance_check
    from genomes_agentic_os.validation_node_provenance import guard_checks
    install, _, worktree, _, selection = _app_guard_context(tmp_path, source=False)
    manifest = _json(worktree / "package.json")
    manifest["scripts"] = {"preinstall": "UNTRUSTED_LIFECYCLE_MUST_NOT_EXECUTE"}
    _write(worktree / "package.json", manifest)
    _git("init", "-b", "main", cwd=worktree)
    _git("config", "user.email", "synthetic@example.invalid", cwd=worktree)
    _git("config", "user.name", "Synthetic Node authority fixture", cwd=worktree)
    (worktree / ".gitignore").write_text(filename + "\nnode_modules/\n")
    _git("add", ".gitignore", "package-lock.json" if filename == "package.json" else "package.json", cwd=worktree)
    _git("commit", "-m", "tracked lock with deliberately ignored manifest", cwd=worktree)
    assert _git("status", "--porcelain", cwd=worktree) == ""
    assert _git("ls-files", filename, cwd=worktree) == ""
    profile = {"validation": {"commands": ["npm ci"], "node_tool_contract": selection}}
    if boundary == "producer":
        with pytest.raises(ValueError, match="source"):
            guard_checks(install, install, worktree, tool_contract=selection)
    elif boundary == "consumer":
        assert not _clean_worktree({"ticket": "TEST-1"}, tmp_path, worktree, profile)
    else:
        task = {"work_item": str(tmp_path / "packet"), "worktree": {"path": str(worktree)}}
        with pytest.raises(ValueError, match="source"):
            runtime_provenance_check("npm ci", ["npm", "ci"], task, profile)


@pytest.mark.parametrize("filename", ["package.json", "package-lock.json"])
@pytest.mark.parametrize("staged", [False, True])
def test_app_source_binding_rejects_uncommitted_input_even_if_git_status_is_suppressed(tmp_path, filename, staged):
    from genomes_agentic_os.validation_node_provenance import guard_checks, source_binding
    install, _, worktree, _, selection = _app_guard_context(tmp_path)
    path = worktree / filename
    value = _json(path); value["uncommitted_input"] = "must never supply npm source authority"
    _write(path, value)
    if staged:
        _git("add", filename, cwd=worktree)
    else:
        _git("update-index", "--assume-unchanged", filename, cwd=worktree)
        assert _git("status", "--porcelain", cwd=worktree) == ""
    with pytest.raises(ValueError, match="source"):
        source_binding(worktree, selection)
    with pytest.raises(ValueError, match="source"):
        guard_checks(install, install, worktree, tool_contract=selection)


def test_native_app_prepare_rechecks_source_and_requires_its_frozen_head(tmp_path):
    from genomes_agentic_os.validation_node_provenance import contract_binding, guard_checks
    install, _, worktree, _, selection = _app_guard_context(tmp_path)
    guard_checks(install, install, worktree, tool_contract=selection)
    binding = contract_binding(worktree, selection)
    command = _json(install / "command.json")
    command["expected_git_identity"]["head"] = "2" * 40
    _write(install / "command.json", command)
    with pytest.raises(ValueError, match="source"):
        run_guard("prepare", install, install, worktree, "preflight", "-", binding)
    command["expected_git_identity"]["head"] = _git("rev-parse", "HEAD", cwd=worktree)
    _write(install / "command.json", command)
    # Drift after check construction must still refuse before npm executes.
    manifest = _json(worktree / "package.json"); manifest["scripts"] = {"preinstall": "MUST_NOT_EXECUTE"}
    _write(worktree / "package.json", manifest)
    with pytest.raises(ValueError, match="source"):
        run_guard("prepare", install, install, worktree, "preflight", "-", contract_binding(worktree, selection))


def test_app_source_binding_cannot_replace_the_frozen_original_commit(tmp_path):
    """Fixture-only Git replacements must not substitute new lifecycle bytes."""
    from genomes_agentic_os.validation_node_provenance import source_binding
    _, _, worktree, _, selection = _app_guard_context(tmp_path)
    original = _git("rev-parse", "HEAD", cwd=worktree)
    manifest = _json(worktree / "package.json")
    manifest["scripts"] = {"preinstall": "REPLACEMENT_LIFECYCLE_MUST_NOT_EXECUTE"}
    _write(worktree / "package.json", manifest)
    _git("add", "package.json", cwd=worktree)
    _git("commit", "-m", "alternate fixture manifest", cwd=worktree)
    alternate = _git("rev-parse", "HEAD", cwd=worktree)
    _git("reset", "--soft", original, cwd=worktree)
    _git("replace", original, alternate, cwd=worktree)
    assert _git("rev-parse", "HEAD", cwd=worktree) == original
    assert _git("status", "--porcelain", cwd=worktree) == ""
    with pytest.raises(ValueError, match="source"):
        source_binding(worktree, selection, head=original)


def test_app_source_query_cannot_adopt_an_ambient_foreign_git_directory(tmp_path, monkeypatch):
    from genomes_agentic_os.validation_node_provenance import source_binding
    owned = tmp_path / "owned"; owned.mkdir()
    foreign = tmp_path / "foreign"; foreign.mkdir()
    _, _, worktree, _, selection = _app_guard_context(owned)
    _, _, other, _, _ = _app_guard_context(foreign)
    original = _git("rev-parse", "HEAD", cwd=worktree)
    _git("commit", "--allow-empty", "-m", "distinct foreign fixture head", cwd=other)
    assert _git("rev-parse", "HEAD", cwd=other) != original
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(worktree))
    assert source_binding(worktree, selection)["head_sha"] == original


@pytest.mark.parametrize("override", ["GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_INDEX_FILE", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"])
def test_app_source_query_ignores_ambient_git_metadata_without_mutating_it(tmp_path, monkeypatch, override):
    from genomes_agentic_os.validation_node_provenance import source_binding
    _, _, worktree, _, selection = _app_guard_context(tmp_path)
    expected = source_binding(worktree, selection)
    outside = tmp_path / "foreign-metadata"; outside.mkdir()
    if override == "GIT_CONFIG_COUNT":
        monkeypatch.setenv(override, "1")
        monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.worktree")
        monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(outside))
    elif override == "GIT_CONFIG_PARAMETERS":
        monkeypatch.setenv(override, "'core.worktree'='" + str(outside) + "'")
    else:
        monkeypatch.setenv(override, str(outside / "index") if override == "GIT_INDEX_FILE" else str(outside))
    assert source_binding(worktree, selection) == expected
    assert expected["object_resolution"] == "raw_no_replace"
    assert list(outside.iterdir()) == []
    assert override in os.environ  # Only the read-only child's environment is controlled.


@pytest.mark.parametrize("subdir", [".", "ui"])
def test_actual_offline_app_static_native_consumer_uses_the_same_frozen_contract(tmp_path, subdir):
    selection = _app_contract(subdir)
    f = _fixture(tmp_path, node_tool_contract=selection)
    before = f["task"].read()
    result = _refresh(f)
    assert result["task"]["validation_head_sha"] == f["head"]
    assert result["task"]["receipts"][:len(before["receipts"])] == before["receipts"]
    request = _json(f["request"])
    rows = request["evidence"]["validation_runs"]
    assert [r["command"] for r in rows] == ["npm ci", "npx --no-install eslint --version", "npx --no-install prettier --version", "npx --no-install tsc --version"]
    for row in rows:
        command = _json(Path(row["command_receipt"]["path"]))
        terminal = _json(Path(row["terminal"]["path"]))
        assert command["work_dir"] == str(f["worktree"] / subdir)
        assert len(command["preflight_checks"]) == len(command["post_run_checks"]) == 1
        assert [c["phase"] for c in terminal["checks"]] == ["preflight", "post-run"]
    assert not (f["worktree"] / subdir / "node_modules/.bin/playwright").exists()


def test_real_npm_ci_binds_full_closure_and_honest_frozen_deferral(tmp_path):
    f = _fixture(tmp_path, node_commands=True, legacy=True, deferred_successor=True, registered_metadata=True)
    old, before = f["predecessor"].read_bytes(), f["task"].read()
    result = _refresh(f)
    assert result["task"]["validation_head_sha"] == f["head"]
    assert result["task"]["receipts"][:len(before["receipts"])] == before["receipts"]
    assert f["predecessor"].read_bytes() == old
    request = json.loads(f["request"].read_text())
    assert request["status"] == "deferred_to_ci"
    rows = request["evidence"]["validation_runs"]
    assert [row["command"] for row in rows] == ["npm ci", "npx tsc --noEmit", "npx playwright test --list"]
    for row in rows:
        terminal = json.loads(Path(row["terminal"]["path"]).read_text())
        assert terminal["git_identity_pre"]["clean"] == terminal["git_identity_post"]["clean"] == "false"
        assert terminal["post_run_invariants_ok"] is True
        assert [check["phase"] for check in terminal["checks"]] == ["preflight", "post-run"]
    assert not (f["packet"] / "artifacts" / LOCK).exists()
    assert _refresh(f)["replayed"] is True


def test_real_post_install_green_noop_cannot_be_admitted(tmp_path):
    f = _fixture(tmp_path, node_commands=True)
    request = json.loads(f["request"].read_text()); rows = request["evidence"]["validation_runs"]
    binary = f["worktree"] / "node_modules/.bin/tsc"
    binary.unlink(); binary.write_text("#!/bin/sh\nexit 0\n"); binary.chmod(0o755)
    assert _git("status", "--porcelain", cwd=f["worktree"]) == ""
    # This is the actual reported bypass: genuine native execution of the
    # unchanged frozen argv returns green against a replaced ignored binary.
    green = _command_proof(f["root"], f["packet"], f["worktree"], "npx tsc --noEmit", f["head"],
        f["task"].read()["policy_fingerprint"], node_guards=False)
    green["node_install_closure"] = rows[0]["node_install_closure"]
    rows[1] = green; request["verified_at"] = _now(); _write(f["request"], request)
    before = f["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="closure changed"):
        _refresh(f)
    assert f["task"].path.read_bytes() == before
    # With the approved hooks the substituted command is stopped before launch.
    blocked = _command_proof(f["root"], f["packet"], f["worktree"], "npx tsc --noEmit", f["head"],
        f["task"].read()["policy_fingerprint"], expected_status="failure",
        node_install=Path(rows[0]["command_receipt"]["path"]).parent)
    terminal = json.loads(Path(blocked["terminal"]["path"]).read_text())
    assert terminal["exit_code"] is None and terminal["reason"] == "preflight-check-failed"
    assert not (f["packet"] / "artifacts" / LOCK).exists()


@pytest.mark.parametrize("change", ["contents", "mode", "added", "deleted", "outside", "dangling", "directory-link"])
def test_full_installed_dependency_closure_rejects_each_mutation(tmp_path, change):
    f = _fixture(tmp_path, node_commands=True)
    root = f["worktree"] / "node_modules"
    target = root / "synthetic-typescript/cli.js"
    if change == "contents": target.write_text("#!/usr/bin/env node\nprocess.exit(0)\n")
    elif change == "mode": target.chmod(0o644)
    elif change == "added": (root / "added.js").write_text("module.exports = 1\n")
    elif change == "deleted": target.unlink()
    else:
        binary = root / ".bin/tsc"; binary.unlink()
        destination = (tmp_path / "outside.js") if change == "outside" else root / "missing.js" if change == "dangling" else root
        if change == "outside": destination.write_text("#!/bin/sh\nexit 0\n"); destination.chmod(0o755)
        binary.symlink_to(destination)
    before = f["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="Node.*(closure|provenance)|installed Node"):
        _refresh(f)
    assert f["task"].path.read_bytes() == before


@pytest.mark.parametrize("change", ["self-asserted", "missing-preflight", "wrong-check", "no-capture",
    "capture-output", "install-command-sha", "lockfile-sha", "wrong-lock", "foreign-snapshot"])
def test_native_install_capture_authority_cannot_be_substituted(tmp_path, change):
    f = _fixture(tmp_path, node_commands=True)
    request = json.loads(f["request"].read_text()); rows = request["evidence"]["validation_runs"]
    row = rows[0]; terminal_path = Path(row["terminal"]["path"]); terminal = json.loads(terminal_path.read_text())
    command_path = Path(row["command_receipt"]["path"]); command = json.loads(command_path.read_text())
    snapshot_path = Path(row["node_install_closure"]["path"]); snapshot = json.loads(snapshot_path.read_text())
    if change == "missing-preflight": row.pop("preflight")
    elif change == "wrong-check": command["preflight_checks"] = ["true"]
    elif change == "no-capture": terminal["checks"] = terminal["checks"][:1]
    elif change == "capture-output": terminal["checks"][1]["output_tail"] = '{"operation":"capture"}\n'
    elif change == "install-command-sha": snapshot["command_sha256"] = "0" * 64
    elif change == "lockfile-sha": snapshot["lockfile_sha256"] = "0" * 64
    elif change == "wrong-lock": command["mutation_lock"] = str(f["packet"] / "artifacts/other.lock")
    elif change == "foreign-snapshot":
        snapshot_path = _write(f["packet"] / "artifacts/self-asserted.json", snapshot)
    elif change == "self-asserted": snapshot["entries"] = []
    _write(command_path, command); _write(terminal_path, terminal); _write(snapshot_path, snapshot)
    row["command_receipt"], row["terminal"], row["node_install_closure"] = _bound(command_path), _bound(terminal_path), _bound(snapshot_path)
    _write(f["request"], request)
    before = f["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="Node|validation proof"):
        _refresh(f)
    assert f["task"].path.read_bytes() == before


def test_dependency_closure_is_rechecked_under_task_lock_before_authority(tmp_path, monkeypatch):
    f = _fixture(tmp_path, node_commands=True)
    original = delivery._file_lock
    @contextmanager
    def mutate_after_admission(path):
        with original(path):
            (f["worktree"] / "node_modules/added-after-preflight.js").write_text("module.exports = 0\n")
            yield
    monkeypatch.setattr(delivery, "_file_lock", mutate_after_admission)
    before = f["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="closure changed"):
        _refresh(f)
    assert f["task"].path.read_bytes() == before


def test_real_native_post_check_rejects_dependency_change_during_command(tmp_path):
    f = _fixture(tmp_path, node_commands=True)
    rows = json.loads(f["request"].read_text())["evidence"]["validation_runs"]
    install_run = Path(rows[0]["command_receipt"]["path"]).parent
    from genomes_agentic_os.validation_node_provenance import guard_checks
    identifier = "actual-post-mutation"
    run = f["packet"] / "artifacts/command-runs/async-runs" / identifier
    pre, post = guard_checks(install_run, run, f["worktree"], rows[0]["node_install_closure"]["sha256"])
    target = f["worktree"] / "node_modules/synthetic-typescript/cli.js"
    state = start_run(f["root"], command=[sys.executable, "-I", "-S", "-c",
            "from pathlib import Path;Path(" + repr(str(target)) + ").write_text('green no-op');print('command returned zero')"],
        label="actual change while governed command runs", run_id=identifier,
        artifact_dir=str(f["packet"] / "artifacts/command-runs"), work_dir=str(f["worktree"]),
        expected_git_identity=json.loads(Path(rows[0]["command_receipt"]["path"]).read_text())["expected_git_identity"],
        mutation_lock=str(f["packet"] / "artifacts" / LOCK), preflight_checks=[pre], post_run_checks=[post],
        budgets={"wall_clock_minutes": 1, "no_progress_minutes": 1})
    result = _wait_for(Path(state["run_dir"]), {"success", "failure", "error"})
    receipt = json.loads((run / "terminal-receipt.json").read_text())
    assert result["status"] == "failure" and receipt["exit_code"] == 0
    assert receipt["reason"] == "post-run-invariant-failed" and receipt["post_run_invariants_ok"] is False
    assert receipt["checks"][0]["ok"] is True and receipt["checks"][1]["ok"] is False
    assert not (f["packet"] / "artifacts" / LOCK).exists()


@pytest.mark.parametrize("operation", ["preflight-fails", "all-pass"])
def test_native_lock_covers_preflight_command_postflight_and_releases(tmp_path, operation):
    lock = tmp_path / "execution.lock"; trace = tmp_path / "ordered.jsonl"
    def code(phase, exit_code=0):
        return ("import json;from pathlib import Path; "
            f"lock=Path({str(lock)!r});trace=Path({str(trace)!r}); "
            "assert lock.is_file(); owner=json.loads(lock.read_text()); assert owner['run_id']=='locked-order'; "
            f"f=trace.open('a');f.write({phase!r}+'\\n');f.close();raise SystemExit({exit_code})")
    pre = shlex.join([sys.executable, "-c", code("preflight", 1 if operation == "preflight-fails" else 0)])
    post = shlex.join([sys.executable, "-c", code("post-run")])
    state = start_run(tmp_path / "os", command=[sys.executable, "-c", code("command")], label="locked actual ordering",
        run_id="locked-order", artifact_dir=str(tmp_path / "artifacts"), work_dir=str(tmp_path),
        mutation_lock=str(lock), preflight_checks=[pre], post_run_checks=[post],
        budgets={"wall_clock_minutes": 1, "no_progress_minutes": 1})
    result = _wait_for(Path(state["run_dir"]), {"success", "failure", "error"})
    assert result["status"] == ("failure" if operation == "preflight-fails" else "success")
    assert trace.read_text().splitlines() == (["preflight"] if operation == "preflight-fails" else ["preflight", "command", "post-run"])
    assert not lock.exists()


@pytest.mark.parametrize("failure", ["preflight-file", "output-log", "foreign-lock", "cancel-preflight"])
def test_actual_native_lock_cleanup_on_error_conflict_and_cancellation(tmp_path, failure):
    lock, ready = tmp_path / "execution.lock", tmp_path / "ready"
    identifier = "actual-lock-cleanup"
    run = tmp_path / "artifacts/async-runs" / identifier
    code = "from pathlib import Path;import time;Path(" + repr(str(ready)) + ").write_text('ready');"
    if failure == "preflight-file": code += "Path(" + repr(str(run / "preflight.json")) + ").mkdir()"
    elif failure == "output-log": code += "Path(" + repr(str(run / "output.log")) + ").mkdir()"
    elif failure == "cancel-preflight": code += "time.sleep(5)"
    else: code += "print('preflight')"
    if failure == "foreign-lock":
        _write(lock, {"run_id": "other-live-run", "pid": os.getpid()}); original = lock.read_bytes()
    start_run(tmp_path / "os", command=[sys.executable, "-c", "print('actual command')"],
        label="actual error and cancellation cleanup", run_id=identifier,
        artifact_dir=str(tmp_path / "artifacts"), work_dir=str(tmp_path), mutation_lock=str(lock),
        preflight_checks=[shlex.join([sys.executable, "-c", code])],
        budgets={"wall_clock_minutes": 1, "no_progress_minutes": 1})
    if failure == "cancel-preflight":
        import time
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline: time.sleep(0.02)
        assert ready.exists() and lock.exists()
        try: control_run(run, "cancel", grace_seconds=5)
        except ProcessLookupError: pass  # Honest published cancellation can win this existing transport race.
    result = _wait_for(run, {"success", "failure", "error", "cancelled"})
    assert result["status"] == ("cancelled" if failure == "cancel-preflight" else "error")
    if failure == "foreign-lock":
        assert lock.read_bytes() == original and not ready.exists()
    else:
        assert not lock.exists()


def test_actual_native_same_run_id_different_live_pid_conflict_preserves_owner(tmp_path):
    import time
    lock, ready, finish = tmp_path / "shared.lock", tmp_path / "owner-ready", tmp_path / "finish-owner"
    code = ("from pathlib import Path;import time;Path(" + repr(str(ready)) + ").write_text('ready');"
            "deadline=time.monotonic()+15;\n"
            "while not Path(" + repr(str(finish)) + ").exists() and time.monotonic()<deadline: time.sleep(.02)\n"
            "assert Path(" + repr(str(finish)) + ").exists();print('owner finished')")
    first = start_run(tmp_path / "owner-os", command=[sys.executable, "-c", code],
        label="first actual monitor holds lock", run_id="same-run-id",
        artifact_dir=str(tmp_path / "owner-artifacts"), work_dir=str(tmp_path), mutation_lock=str(lock),
        budgets={"wall_clock_minutes": 1, "no_progress_minutes": 1})
    deadline = time.monotonic() + 10
    while not ready.exists() and time.monotonic() < deadline: time.sleep(.02)
    assert ready.exists() and lock.exists()
    original = lock.read_bytes(); owner = json.loads(original)
    assert owner["run_id"] == "same-run-id" and owner["pid"] == first["monitor_pid"]
    try:
        second = start_run(tmp_path / "contender-os", command=[sys.executable, "-c", "print('must not execute')"],
            label="second actual monitor same ID different PID", run_id="same-run-id",
            artifact_dir=str(tmp_path / "contender-artifacts"), work_dir=str(tmp_path), mutation_lock=str(lock),
            budgets={"wall_clock_minutes": 1, "no_progress_minutes": 1})
        assert second["monitor_pid"] != owner["pid"]
        outcome = _wait_for(Path(second["run_dir"]), {"success", "failure", "error"})
        assert outcome["status"] == "error" and "mutation-lock-acquire-failed" in outcome["terminal_reason"]
        os.kill(owner["pid"], 0)
        assert lock.is_file() and lock.read_bytes() == original
        assert not (Path(second["run_dir"]) / "output.log").exists()
        # Actual continued exclusivity: a third native monitor still cannot
        # enter the first monitor's preflight/command/post-check window.
        third = start_run(tmp_path / "third-os", command=[sys.executable, "-c", "print('must not execute')"],
            label="third actual monitor cannot enter", run_id="other-run-id",
            artifact_dir=str(tmp_path / "third-artifacts"), work_dir=str(tmp_path), mutation_lock=str(lock),
            budgets={"wall_clock_minutes": 1, "no_progress_minutes": 1})
        assert _wait_for(Path(third["run_dir"]), {"success", "failure", "error"})["status"] == "error"
        assert lock.read_bytes() == original
    finally:
        finish.write_text("finish")
        assert _wait_for(Path(first["run_dir"]), {"success", "failure", "error"})["status"] == "success"
    deadline = time.monotonic() + 2
    while lock.exists() and time.monotonic() < deadline: time.sleep(.02)
    assert not lock.exists()


@pytest.mark.parametrize("change", ["missing", "redirected-root", "fifo", "group-write", "symlink-directory"])
def test_unqualified_closure_is_refused(tmp_path, change):
    root = tmp_path / "node_modules"; root.mkdir()
    if change == "missing": root.rmdir()
    elif change == "redirected-root":
        root.rmdir(); other = tmp_path / "other"; other.mkdir(); root.symlink_to(other, target_is_directory=True)
    elif change == "fifo": os.mkfifo(root / "pipe")
    elif change == "group-write": (root / "package.js").write_text("1"); (root / "package.js").chmod(0o666)
    else: (root / "recursive").symlink_to(root, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        dependency_closure(tmp_path)


def _guard_context(tmp_path):
    """Synthetic helper-unit context only; never offered as native admission proof."""
    worktree = tmp_path / "worktree"; worktree.mkdir()
    (worktree / "package-lock.json").write_text('{}\n')
    root = worktree / "node_modules"; (root / ".bin").mkdir(parents=True)
    for name in ("tsc", "playwright"):
        path = root / (name + ".js"); path.write_text("#!/usr/bin/env node\nprocess.exit(0)\n"); path.chmod(0o755)
        (root / ".bin" / name).symlink_to("../" + path.name)
    base = tmp_path / "packet/artifacts/command-runs/async-runs"
    install, dependent = base / "install", base / "dependent"
    identity = {"head": "1" * 40, "clean": "false"}
    lock = install.parents[2] / LOCK
    for run, command in ((install, ["npm", "ci"]), (dependent, ["npx", "playwright", "test", "--list"])):
        _write(run / "command.json", {"id": run.name, "run_dir": str(run), "work_dir": str(worktree),
            "expected_git_identity": identity, "mutation_lock": str(lock), "command": command,
            "environment_overrides": {"PWTEST_CACHE_DIR": str(run / "playwright-cache")}})
    _write(lock, {"run_id": install.name, "pid": os.getpid()})
    return install, dependent, worktree, lock


def test_helper_library_refuses_replay_stale_capture_and_cached_generated_code(tmp_path):
    install, dependent, worktree, lock = _guard_context(tmp_path)
    run_guard("prepare", install, install, worktree, "preflight", "-")
    capture = run_guard("capture", install, install, worktree, "post-run", "-")
    with pytest.raises(ValueError, match="existing snapshot"):
        run_guard("prepare", install, install, worktree, "preflight", "-")
    with pytest.raises(FileExistsError):
        run_guard("capture", install, install, worktree, "post-run", "-")
    _write(lock, {"run_id": dependent.name, "pid": os.getpid()})
    digest = capture["snapshot_sha256"]
    run_guard("verify", install, dependent, worktree, "preflight", digest)
    cache = dependent / "playwright-cache"; (cache / "generated.js").write_text("module.exports=0\n")
    run_guard("verify", install, dependent, worktree, "post-run", digest)
    with pytest.raises(FileExistsError):
        run_guard("verify", install, dependent, worktree, "preflight", digest)
    with pytest.raises(ValueError, match="SHA changed"):
        run_guard("verify", install, dependent, worktree, "post-run", "0" * 64)


@pytest.mark.parametrize("change", ["redirected-run", "identity", "wrong-lock", "lock-owner", "dead-owner",
    "capture-phase", "verify-install", "unsupported", "stale-identity", "cache-outside"])
def test_helper_refuses_unqualified_context_or_cache(tmp_path, change):
    install, dependent, worktree, lock = _guard_context(tmp_path)
    capsule = run_guard("capture", install, install, worktree, "post-run", "-")
    _write(lock, {"run_id": dependent.name, "pid": os.getpid()})
    command_path = dependent / "command.json"; command = json.loads(command_path.read_text())
    operation, phase, actual_run = "verify", "preflight", dependent
    if change == "redirected-run":
        linked = tmp_path / "link"; linked.symlink_to(dependent, target_is_directory=True); actual_run = linked
    elif change == "identity": command["expected_git_identity"]["head"] = "2" * 40
    elif change == "wrong-lock": command["mutation_lock"] = str(tmp_path / "foreign.lock")
    elif change == "lock-owner": _write(lock, {"run_id": "foreign", "pid": os.getpid()})
    elif change == "dead-owner": _write(lock, {"run_id": dependent.name, "pid": -1})
    elif change == "capture-phase": operation, phase = "capture", "preflight"
    elif change == "verify-install":
        actual_run = install; _write(lock, {"run_id": install.name, "pid": os.getpid()})
    elif change == "unsupported": operation = "unsupported"
    elif change == "stale-identity":
        snapshot = json.loads((install / SNAPSHOT).read_text()); snapshot["identity"]["head"] = "2" * 40
        _write(install / SNAPSHOT, snapshot); capsule["snapshot_sha256"] = _bound(install / SNAPSHOT)["sha256"]
    elif change == "cache-outside": command["environment_overrides"]["PWTEST_CACHE_DIR"] = str(tmp_path / "shared-cache")
    _write(command_path, command)
    with pytest.raises(ValueError):
        run_guard(operation, install, actual_run, worktree, phase, capsule["snapshot_sha256"])


@pytest.mark.parametrize("payload", ['{"id":1,"id":2}', '[]'])
def test_helper_json_rejects_ambiguous_authority(tmp_path, payload):
    path = tmp_path / "invalid.json"; path.write_text(payload)
    with pytest.raises(ValueError): _json(path)
