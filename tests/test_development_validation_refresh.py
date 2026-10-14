"""Real canonical task/worktree and governed-command validation refresh regressions."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.machinery
import json
from pathlib import Path
import shlex
import sys
import io
import tarfile
import subprocess
import time
import types
import uuid

import pytest
import yaml

from genomes_agentic_os import development_delivery as delivery
from genomes_agentic_os import development_validation_refresh as refresh
from genomes_agentic_os.auto_dev_orchestration import (
    AutoDevStateError, read_auto_dev_state, require_auto_dev_predecessors, record_auto_dev_stage,
    sync_delivery_projection,
)
from genomes_agentic_os.cli import main
from genomes_agentic_os.long_run import start_run
from genomes_agentic_os.validation_command_authority import runtime_provenance_check
from genomes_agentic_os.validation_node_provenance import LOCK, SNAPSHOT, guard_checks
from test_development_delivery import (
    _git, _project, _record_standalone_stage, _repository, _stage_receipt,
)


def _write(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    return path


def _bound(path: Path) -> dict:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _command_proof(root: Path, packet: Path, worktree: Path, command: str, head: str, policy: str,
                   annotated: bool = False, expected_status: str = "success", verify_interpreter: bool = True,
                   node_install: Path | None = None, node_guards: bool = True) -> dict:
    identity = {"repository": _git("config", "--get", "remote.origin.url", cwd=worktree),
                "branch": _git("branch", "--show-current", cwd=worktree),
                "head": head, "clean": "false" if _git("status", "--porcelain", cwd=worktree) else "true",
                "worktree": str(worktree)}
    argv = shlex.split(command)
    if annotated:
        argv[0] = str(worktree / ".venv/bin/python")
        argv.extend(["--basetemp=" + str(packet / "artifacts/actor-tmp/tests"),
            "-o", "cache_dir=" + str(packet / "artifacts/actor-cache"),
            "--cov-report=json:" + str(packet / "artifacts/actor-coverage.json")])
    check = None
    if not annotated and verify_interpreter:
        manifest = json.loads((packet / "autodev.json").read_text())
        current = delivery.TaskState(Path(manifest["delivery"]["task_state_ref"])).read()
        check = runtime_provenance_check(command, argv, current, delivery.frozen_selected_task_profile(current))
    identifier = "node-proof-" + uuid.uuid4().hex
    run_path = packet / "artifacts/command-runs/async-runs" / identifier
    pre, post, lock = ([check] if check else []), ([check] if check else []), None
    environment = {"PYTEST_ADDOPTS": "", "COVERAGE_FILE": str(packet / "artifacts/actor-coverage-data")}
    is_node = shlex.split(command) in (["npm", "ci"], ["npx", "tsc", "--noEmit"], ["npx", "playwright", "test", "--list"])
    if is_node and node_guards:
        install = node_install or run_path
        snapshot_sha = _bound(install / SNAPSHOT)["sha256"] if node_install else None
        pre_check, post_check = guard_checks(install, run_path, worktree, snapshot_sha)
        pre, post, lock = [pre_check], [post_check], str(packet / "artifacts" / LOCK)
        if "playwright" in argv:
            environment["PWTEST_CACHE_DIR"] = str(run_path / "playwright-cache")
    state = start_run(root, command=["env", "REVIEW_POLICY_FINGERPRINT=" + policy, *argv], label="actual validation proof",
                      artifact_dir=str(packet / "artifacts/command-runs"),
                      run_id=identifier,
                      work_dir=str(worktree), expected_git_identity=identity,
                      environment_overrides=environment, mutation_lock=lock,
                      preflight_checks=pre, post_run_checks=post,
                      budgets={"wall_clock_minutes": 0.5, "no_progress_minutes": 0.33})
    run = Path(state["run_dir"])
    deadline = time.monotonic() + 15
    while not (run / "terminal-receipt.json").is_file() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert (run / "terminal-receipt.json").is_file(), (run / "state.json").read_text()
    assert json.loads((run / "terminal-receipt.json").read_text())["status"] == expected_status
    proof = {"command": command, "terminal": _bound(run / "terminal-receipt.json"),
             "command_receipt": _bound(run / "command.json")}
    if pre:
        proof["preflight"] = _bound(run / "preflight.json")
    if is_node and node_guards and ((node_install / SNAPSHOT) if node_install else run / SNAPSHOT).is_file():
        proof["node_install_closure"] = _bound((node_install / SNAPSHOT) if node_install else run / SNAPSHOT)
    return proof


def _node_repository(repo: Path, *, deferred: bool) -> None:
    """Synthetic, offline npm packages; no real account/path payloads in fixtures."""
    (repo / ".gitignore").write_text("node_modules/\n")
    dependencies = {}
    for name, binary in (("synthetic-typescript", "tsc"), ("synthetic-playwright", "playwright")):
        archive = repo / (name + ".tgz")
        data = {"name": name, "version": "1.0.0", "bin": {binary: "cli.js"}}
        code = "#!/usr/bin/env node\nconsole.log('actual synthetic " + binary + " validation');\n"
        if binary == "playwright" and deferred:
            code += "console.error('Required disposable fixture endpoint is absent'); process.exit(17);\n"
        with tarfile.open(archive, "w:gz") as tar:
            for filename, contents, mode in (("package.json", json.dumps(data), 0o644), ("cli.js", code, 0o755)):
                raw = contents.encode(); info = tarfile.TarInfo("package/" + filename)
                info.size, info.mode = len(raw), mode
                tar.addfile(info, io.BytesIO(raw))
        dependencies[name] = "file:" + archive.name
    (repo / "package.json").write_text(json.dumps({"name": "synthetic-validation", "version": "1.0.0", "dependencies": dependencies}))
    subprocess.run(["npm", "install", "--package-lock-only", "--ignore-scripts", "--offline"], cwd=repo,
                   check=True, capture_output=True, timeout=20)
    _git("add", ".", cwd=repo); _git("commit", "-m", "synthetic offline Node fixture", cwd=repo)
    _git("push", "origin", "main", cwd=repo)


def _fixture(tmp_path: Path, *, changed: bool = True, mode: str = "single_stage",
             historical_command: bool = True, multiple_commands: bool = False,
              annotated: bool = False, legacy: bool = False, deferred_successor: bool = False,
              fallback: bool = True, registered_metadata: bool = False, declare_interpreter: bool = True,
              npm_without_ci: bool = False, node_commands: bool = False) -> dict:
    repo, old_head = _repository(tmp_path)
    if node_commands:
        _node_repository(repo, deferred=deferred_successor)
        old_head = _git("rev-parse", "HEAD", cwd=repo)
    if annotated:
        (repo / ".gitignore").write_text(".venv\n.pytest_cache/\n__pycache__/\n*.pyc\n")
        (repo / "tests").mkdir()
        (repo / "tests/test_execution.py").write_text("def test_execution():\n    assert 2 + 2 == 4\n")
        _git("add", ".gitignore", "tests", cwd=repo)
        _git("commit", "-m", "real pytest command fixture", cwd=repo)
        _git("push", "origin", "main", cwd=repo)
        old_head = _git("rev-parse", "HEAD", cwd=repo)
    root = tmp_path / "os"
    project = _project(root, repo, repository_id="git:github.com/acme/app")
    config = project / "config/development.yml"
    profile = yaml.safe_load(config.read_text())
    interpreter = str(Path(sys._base_executable).resolve())
    diagnostic = [interpreter, "-I", "-S", "-c"]
    command = (".venv/bin/python -m pytest tests/ -q --cov=genomes_agentic_os --cov-branch" if annotated
               else shlex.join([*diagnostic, "print('validated')"]))
    if npm_without_ci:
        command = "npx --version"
    commands = [command]
    if multiple_commands:
        commands.append(shlex.join([*diagnostic, "print('validated second layer')"]))
    if deferred_successor and not node_commands:
        commands.append(shlex.join([*diagnostic,
            "import os,sys; missing=not os.environ.get('VALIDATION_REFRESH_FIXTURE_ENDPOINT'); "
            "print('Required disposable fixture endpoint is absent' if missing else 'configured'); "
            "sys.exit(17 if missing else 0)"]))
    if node_commands:
        commands = ["npm ci", "npx tsc --noEmit", "npx playwright test --list"]
        command = commands[0]
    profile["validation"]["commands"] = commands
    if not annotated and declare_interpreter and not npm_without_ci and not node_commands:
        profile["validation"]["isolated_python_interpreters"] = {
            configured: {"authority": "frozen_selected_profile", "dependency_mode": "isolated_stdlib_diagnostic",
                         "executable": interpreter, "sha256": hashlib.sha256(Path(interpreter).read_bytes()).hexdigest()}
            for configured in commands
        }
    profile["validation"]["ci_fallback_on_environment_failure"] = fallback
    config.write_text(yaml.safe_dump(profile))
    args = {"auto_dev_mode": mode}
    if mode == "single_stage":
        args.update(requested_stage="pr_create", goal="pr_create")
    run = delivery.start_development_run(
        root, "acme", "app", ["AGE-236"], run_id="refresh", apply=True, **args)
    task = delivery.TaskState(Path(run["tasks"][0]["state_ref"]))
    current = task.read()
    packet, worktree = Path(current["work_item"]), Path(current["worktree"]["path"])
    # All network-free provisioning is finished. Bind subsequent proof to the
    # selected provider NWO; no fixture performs a remote operation afterward.
    _git("remote", "set-url", "origin", "https://github.com/acme/app.git", cwd=worktree)
    if annotated:
        # Preserve an actual locked task venv rather than inferring that a
        # system-Python symlink has this disposable environment's packages.
        (worktree / ".venv").symlink_to(sys.prefix, target_is_directory=True)
    for stage in ("groom", "detective", "create_artifacts"):
        _record_standalone_stage(task, stage)
    delivery.run_development_stage(task.path, stage="readiness",
        receipts={"planned": _stage_receipt(packet, "planned")},
        idempotency_prefix="planned")
    old = {"ticket": current["ticket"], "repository": "acme/app",
           "policy_fingerprint": current["policy_fingerprint"], "head_sha": old_head,
           "focused_checks": "passed", "unavailable_check": {
               "command": "python -m pytest tests/ -q --cov=genomes_agentic_os --cov-branch --cov-fail-under=80" if historical_command else command,
               "classification": "environment_unavailable",
               "reason": "predecessor disposable environment was unavailable"}}
    if legacy:
        # This is the genuinely recorded old QA shape: candidate revision and
        # local checks, with no nested ticket/repository/policy identity.
        old = {"subject_revision": old_head, "typescript": "passed",
               "unit_suite": "passed", "targeted_discovery": "passed",
               "unavailable_check": old["unavailable_check"]}
    old_status = "deferred_to_ci" if fallback else "passed"
    if not fallback:
        old.pop("unavailable_check")
    local_receipt = _stage_receipt(packet, "local_validation",
                                  status=old_status, evidence=old)
    if legacy:
        local_payload = json.loads(Path(local_receipt).read_text())
        local_payload["verified_at"] = _now()
        local_payload["stage"] = "implementation"
        _write(Path(local_receipt), local_payload)
    delivery.run_development_stage(task.path, stage="implementation",
        receipts={"implementing": _stage_receipt(packet, "implementing"),
                  "local_validation": local_receipt},
        idempotency_prefix="implementation")
    _record_standalone_stage(task, "document", revision=old_head)
    current = task.read()
    predecessor = Path([r for r in current["receipts"] if r["state"] == "local_validation"][-1]["ref"])
    assert json.loads(predecessor.read_text())["status"] == old_status
    if changed:
        (worktree / "README.md").write_text("successor implementation\n")
        _git("add", "README.md", cwd=worktree)
        _git("commit", "-m", "successor implementation", cwd=worktree)
    head = _git("rev-parse", "HEAD", cwd=worktree)
    if registered_metadata:
        _write(worktree / ".features" / current["ticket"] / "checks/watch-state.json", {"status": "success"})
    proofs = []
    for i, c in enumerate(commands):
        proof = _command_proof(root, packet, worktree, c, head, current["policy_fingerprint"], annotated,
                           "failure" if deferred_successor and i == len(commands) - 1 else "success",
                           verify_interpreter=declare_interpreter and not npm_without_ci,
                           node_install=Path(proofs[0]["command_receipt"]["path"]).parent if node_commands and proofs else None)
        proofs.append(proof)
    current = task.read()
    evidence = {"ticket": current["ticket"], "canonical_work_id": current["canonical_work_id"],
        "repository_id": current["repository"]["id"], "repository": "acme/app",
        "task_state_ref": str(task.path), "worktree": str(worktree),
        "source_branch": current["worktree"]["branch"], "head_sha": head,
        "policy_fingerprint": current["policy_fingerprint"],
        "policy_sha256": _bound(Path(current["policy_receipt"]))["sha256"],
        "validation_runs": proofs, "repair_lineage": {
            "predecessor": _bound(predecessor), "from_head_sha": old_head,
            "to_head_sha": head, "reason": "repaired source requires fresh exact-head validation"}}
    request = _write(packet / "artifacts/successor.json", {
        "schema": "development-stage-evidence/v1", "state": "local_validation",
        "status": "passed", "summary": "Full frozen command passed on current head",
        "verified_at": _now(), "evidence": evidence})
    if deferred_successor:
        evidence["configured_local_checks"] = "passed"
        evidence["unavailable_check"] = {"command": commands[-1], "classification": "environment_unavailable",
            "reason": "Required disposable fixture endpoint is absent", "exit_code": 17,
            "receipt_ref": proofs[-1]["terminal"]["path"]}
        _write(request, {"schema": "development-stage-evidence/v1", "state": "local_validation",
            "status": "deferred_to_ci", "summary": "One local layer passed; actual fixture absence defers full validation to CI",
            "verified_at": _now(), "evidence": evidence})
    return dict(root=root, task=task, packet=packet, worktree=worktree, request=request,
                head=head, old_head=old_head, predecessor=predecessor, command=command)


def _refresh(f: dict, key: str = "repair") -> dict:
    return refresh.refresh_development_validation(
        f["task"].path, evidence_file=f["request"], idempotency_key=key)


def _family(f: dict, head: str | None = None) -> str:
    current = f["task"].read()
    return _stage_receipt(f["packet"], "release_propagation", status="completed", evidence={
        "ticket": current["ticket"], "repository": "acme/app",
        "policy_fingerprint": current["policy_fingerprint"],
        "provider": "github", "pull_request": "github:acme/app#236",
        "base_branch": "main", "source_branch": current["worktree"]["branch"],
        "source_head_sha": head or f["head"], "subject_revision": head or f["head"],
        "readback_verified": True, "author_kind": "ours", "author_identity": "github:michaelwclark"})


def _document(f: dict) -> None:
    proof = f["packet"] / "artifacts/new-document-proof.txt"
    proof.write_text("Current-head documentation checked\n")
    evidence = _write(f["packet"] / "artifacts/new-document.json", {
        "schema": "auto-dev-stage-evidence/v1", "stage": "document", "status": "completed",
        "summary": "Current-head documentation", "subject_revision": f["head"],
        "verified_at": _now(), "evidence": {"receipt_refs": [str(proof)]}})
    record_auto_dev_stage(f["task"].read()["autodev_path"], stage="document",
        evidence_file=evidence, idempotency_key="document:" + f["head"])


def test_real_producer_refresh_preserves_history_invalidates_old_document_and_replays(tmp_path):
    f = _fixture(tmp_path)
    task = f["task"]
    before = task.read()
    old_bytes = f["predecessor"].read_bytes()
    document = f["packet"] / "artifacts/auto-dev-orchestration/stages/document/latest.json"
    old_doc = document.read_bytes()
    result = _refresh(f)
    assert result["replayed"] is False
    readiness = result["readiness_projection"]
    if importlib.util.find_spec("genomes_agentic_os.review_readiness_evidence") is None:
        assert readiness["status"] == "unknown"
    else:
        assert readiness["validation_status"] == "passed"
        assert readiness["readiness_evidence_verified"]["validation"] is True
        envelope = json.loads(Path(readiness["envelope"]).read_text())
        assert envelope["head_sha"] == f["head"]
        assert envelope["policy_fingerprint"] == before["policy_fingerprint"]
    assert f["predecessor"].read_bytes() == old_bytes
    assert document.read_bytes() == old_doc
    after = task.read()
    assert after["state"] == "local_validation"
    assert after["failure"] == before["failure"]
    assert after["receipts"][:-1] == before["receipts"]
    assert after["validation_head_sha"] == f["head"]
    latest = after["receipts"][-1]
    assert Path(latest["ref"]).read_bytes() == f["request"].read_bytes()
    assert latest["sha256"] == _bound(f["request"])["sha256"]
    manifest = read_auto_dev_state(after["autodev_path"])
    assert manifest["stages"]["document"]["status"] == "not_started"
    assert manifest["stages"]["pr_create"]["status"] == "not_started"
    assert manifest["subject_revision"] is None
    replay = _refresh(f)
    assert replay["replayed"] is True
    assert task.read()["receipts"] == after["receipts"]
    assert task.read()["validation_refreshes"] == after["validation_refreshes"]
    _document(f)
    completed = delivery.run_development_stage(task.path, stage="release_propagation",
        receipts={"release_propagation": _family(f)}, idempotency_prefix="family")
    wrapper = json.loads((task.path.parent / "stages/release-propagation.json").read_text())
    assert wrapper["validation_authority"]["head_sha"] == f["head"]
    assert wrapper["validation_authority"]["status"] == "passed"
    assert read_auto_dev_state(task.read()["autodev_path"])["stages"]["pr_create"]["status"] == "completed"


def test_same_head_policy_defer_admits_only_pr_create(tmp_path, monkeypatch):
    monkeypatch.delenv("VALIDATION_REFRESH_FIXTURE_ENDPOINT", raising=False)
    f = _fixture(tmp_path, changed=False, mode="everything", historical_command=False,
                 deferred_successor=True)
    _refresh(f)
    _document(f)
    task = f["task"]
    require_auto_dev_predecessors(task.read()["autodev_path"], "pr_create")
    for stage in ("review_self", "review_others", "qa", "finalize", "merge"):
        with pytest.raises(AutoDevStateError):
            require_auto_dev_predecessors(task.read()["autodev_path"], stage)
    delivery.run_development_stage(task.path, stage="release_propagation",
        receipts={"release_propagation": _family(f)}, idempotency_prefix="deferred-family")
    wrapper = json.loads((task.path.parent / "stages/release-propagation.json").read_text())
    assert wrapper["validation_authority"]["status"] == "deferred_to_ci"
    assert wrapper["validation_authority"]["ci_authority"] == "pending"


def test_changed_head_defer_is_blocked_before_recording_family(tmp_path):
    f = _fixture(tmp_path, historical_command=False)
    before = f["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="changed-head"):
        refresh.validate_deferred_pr_create(f["task"].path, f["predecessor"])
    with pytest.raises(delivery.DevelopmentDeliveryError, match="develop"):
        delivery.run_development_stage(f["task"].path, stage="release_propagation",
            receipts={"release_propagation": _family(f)}, idempotency_prefix="stale")
    assert f["task"].path.read_bytes() == before
    assert not (f["task"].path.parent / "stages/release-propagation.json").exists()


@pytest.mark.parametrize("field,value", [
    ("ticket", "AGE-999"), ("canonical_work_id", "wrong"), ("repository_id", "wrong"),
    ("repository", "other/app"), ("task_state_ref", "/tmp/other-task"),
    ("worktree", "/tmp/other-worktree"), ("source_branch", "main"),
    ("head_sha", "a" * 40), ("policy_fingerprint", "b" * 64), ("policy_sha256", "c" * 64),
])
def test_successor_identity_mismatch_is_fail_closed(tmp_path, field, value):
    f = _fixture(tmp_path)
    payload = json.loads(f["request"].read_text())
    payload["evidence"][field] = value
    _write(f["request"], payload)
    before = f["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError):
        _refresh(f)
    assert f["task"].path.read_bytes() == before
    assert not list((f["packet"] / "artifacts/development-delivery/evidence").glob("validation-refresh-*"))


@pytest.mark.parametrize("corruption", [
    "missing_runs", "partial_runs", "junk_run", "missing_lineage", "wrong_predecessor_hash",
    "wrong_from_head", "wrong_to_head", "unsuccessful", "unavailable", "dirty", "terminal_revision",
    "tampered_predecessor", "unknown_command",
])
def test_refresh_rejects_partial_stale_or_nonmodern_proof(tmp_path, corruption):
    f = _fixture(tmp_path)
    payload = json.loads(f["request"].read_text())
    evidence = payload["evidence"]
    if corruption == "missing_runs":
        evidence.pop("validation_runs")
    elif corruption == "partial_runs":
        evidence["validation_runs"] = []
    elif corruption == "junk_run":
        evidence["validation_runs"].append(None)
    elif corruption == "missing_lineage":
        evidence.pop("repair_lineage")
    elif corruption == "wrong_predecessor_hash":
        evidence["repair_lineage"]["predecessor"]["sha256"] = "0" * 64
    elif corruption == "wrong_from_head":
        evidence["repair_lineage"]["from_head_sha"] = "0" * 40
    elif corruption == "wrong_to_head":
        evidence["repair_lineage"]["to_head_sha"] = f["old_head"]
    elif corruption == "unsuccessful":
        payload["status"] = "deferred_to_ci"
    elif corruption == "unavailable":
        evidence["unavailable_check"] = {"classification": "infrastructure"}
    elif corruption == "dirty":
        (f["worktree"] / "README.md").write_text("uncommitted")
    elif corruption == "terminal_revision":
        current = f["task"].read()
        current["terminal_revision"] = f["old_head"]
        _write(f["task"].path, current)
    elif corruption == "tampered_predecessor":
        f["predecessor"].write_text(f["predecessor"].read_text() + " ")
    elif corruption == "unknown_command":
        old = json.loads(f["predecessor"].read_text())
        old["evidence"]["unavailable_check"]["command"] = ""
        _write(f["predecessor"], old)
        evidence["repair_lineage"]["predecessor"] = _bound(f["predecessor"])
        current = f["task"].read()
        [r for r in current["receipts"] if r["state"] == "local_validation"][-1]["sha256"] = _bound(f["predecessor"])["sha256"]
        _write(f["task"].path, current)
    _write(f["request"], payload)
    before = f["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError):
        _refresh(f)
    assert f["task"].path.read_bytes() == before


@pytest.mark.parametrize("artifact,field,value", [
    ("terminal", "status", "failed"), ("terminal", "exit_code", 1),
    ("terminal", "post_run_invariants_ok", False),
    ("terminal", "exit_code", False),
    ("terminal", "git_identity_post", {"head": "0" * 40}),
    ("terminal", "git_identity_pre", {"clean": "false"}),
    ("terminal", "expected_git_identity", {}),
    ("terminal", "created_at", "2000-01-01T00:00:00Z"),
    ("terminal", "finished_at", "2099-01-01T00:00:00Z"),
    ("terminal", "finished_at", "2026-10-05T00:00:00"),
    ("command_receipt", "shell", True), ("command_receipt", "command", ["echo", "fake"]),
    ("command_receipt", "work_dir", "/tmp/wrong"), ("command_receipt", "id", "wrong"),
    ("command_receipt", "expected_git_identity", {}),
])
def test_hash_valid_command_receipts_still_require_exact_semantic_authority(tmp_path, artifact, field, value):
    f = _fixture(tmp_path)
    payload = json.loads(f["request"].read_text())
    proof = payload["evidence"]["validation_runs"][0]
    path = Path(proof[artifact]["path"])
    contents = json.loads(path.read_text())
    contents[field] = value
    _write(path, contents)
    proof[artifact] = _bound(path)
    _write(f["request"], payload)
    before = f["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError):
        _refresh(f)
    assert f["task"].path.read_bytes() == before


def test_refresh_cli_and_present_readiness_producer_read_current_atomic_receipt(tmp_path, monkeypatch, capsys):
    f = _fixture(tmp_path)
    calls = []
    module_name = "genomes_agentic_os.review_readiness_evidence"
    module = types.ModuleType(module_name)
    module.__spec__ = importlib.machinery.ModuleSpec(module_name, loader=None)
    def emit(task_path, *, head, policy):
        current = delivery.TaskState(task_path).read()
        latest = current["receipts"][-1]
        assert latest["kind"] == "validation_refresh"
        proof = json.loads(Path(latest["ref"]).read_text())
        assert proof["evidence"]["head_sha"] == head == f["head"]
        assert proof["evidence"]["policy_fingerprint"] == policy
        assert proof["evidence"]["validation_runs"]
        calls.append(head)
        envelope = _write(f["packet"] / "artifacts/finishing-touches/readiness-evidence.json", {
            "schema": "opposing-review-readiness-evidence/v1", "head_sha": head,
            "policy_fingerprint": policy, "verified_at": _now()})
        return {"schema": "review-readiness-projection/v1", "envelope": str(envelope),
                "validation_status": "passed", "readiness_evidence_verified": {"validation": True}}
    module.emit_readiness_evidence = emit
    monkeypatch.setitem(sys.modules, module_name, module)
    assert main(["develop", "refresh-validation", str(f["task"].path),
        "--evidence", str(f["request"]), "--idempotency-key", "cli-repair", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["readiness_projection"]["validation_status"] == "passed"
    assert json.loads(Path(result["readiness_projection"]["envelope"]).read_text())["head_sha"] == f["head"]
    assert calls == [f["head"]]


def test_replay_collision_and_stale_family_remain_blocked(tmp_path):
    f = _fixture(tmp_path)
    _refresh(f)
    before = f["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="exact-head"):
        refresh.pr_create_validation_authority(f["task"].path,
            json.loads(Path(_family(f, f["old_head"])).read_text()))
    payload = json.loads(f["request"].read_text())
    payload["summary"] = "changed input with reused key"
    _write(f["request"], payload)
    with pytest.raises(delivery.DevelopmentDeliveryError, match="idempotency"):
        _refresh(f)
    assert f["task"].path.read_bytes() == before


@pytest.mark.parametrize("corruption", ["partial", "reordered", "outside_packet"])
def test_multiple_frozen_commands_and_proof_containment_are_required(tmp_path, corruption):
    f = _fixture(tmp_path, multiple_commands=True)
    payload = json.loads(f["request"].read_text())
    runs = payload["evidence"]["validation_runs"]
    if corruption == "partial":
        runs.pop()
    elif corruption == "reordered":
        runs.reverse()
    else:
        outside = tmp_path / "uncontained-terminal.json"
        outside.write_bytes(Path(runs[0]["terminal"]["path"]).read_bytes())
        runs[0]["terminal"] = _bound(outside)
    _write(f["request"], payload)
    before = f["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError):
        _refresh(f)
    assert f["task"].path.read_bytes() == before


def test_old_replay_cannot_authorize_a_newer_source_head(tmp_path):
    f = _fixture(tmp_path)
    _refresh(f)
    before = f["task"].path.read_bytes()
    (f["worktree"] / "README.md").write_text("later repair requires new validation\n")
    _git("add", "README.md", cwd=f["worktree"])
    _git("commit", "-m", "later repair", cwd=f["worktree"])
    with pytest.raises(delivery.DevelopmentDeliveryError, match="mismatch"):
        _refresh(f)
    assert f["task"].path.read_bytes() == before


def test_historical_deferred_command_is_not_current_pr_create_authority(tmp_path):
    f = _fixture(tmp_path, changed=False)
    with pytest.raises(delivery.DevelopmentDeliveryError, match="unavailable-command"):
        refresh.validate_deferred_pr_create(f["task"].path, f["predecessor"])
    # The same historical failure remains valid lineage for independently
    # proved fresh frozen commands. It is never relabeled or reused as passed.
    assert _refresh(f)["task"]["receipts"][-1]["kind"] == "validation_refresh"


def test_dependency_pytest_execution_without_declared_provenance_is_refused(tmp_path):
    f = _fixture(tmp_path, annotated=True)
    before = f["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError):
        _refresh(f)
    assert f["task"].path.read_bytes() == before


@pytest.mark.parametrize("corruption", ["deleted_head", "deleted_lineage", "deleted_successor",
    "wrong_successor_hash", "wrong_lineage_head", "duplicate_key", "scalar_lineage",
    "deleted_both_markers", "deleted_receipt", "changed_predecessor", "changed_command_leaf"])
def test_replay_cannot_restore_corrupted_current_authority(tmp_path, corruption):
    f = _fixture(tmp_path)
    _refresh(f)
    current = f["task"].read()
    if corruption == "deleted_head":
        current.pop("validation_head_sha")
    elif corruption == "deleted_lineage":
        current.pop("validation_refreshes")
    elif corruption == "deleted_successor":
        current["validation_refreshes"][-1].pop("successor_ref")
    elif corruption == "wrong_successor_hash":
        current["validation_refreshes"][-1]["successor_sha256"] = "f" * 64
    elif corruption == "wrong_lineage_head":
        current["validation_refreshes"][-1]["head_sha"] = f["old_head"]
    elif corruption == "duplicate_key":
        current["validation_refreshes"].append(dict(current["validation_refreshes"][-1]))
    elif corruption == "deleted_both_markers":
        current.pop("validation_head_sha")
        current.pop("validation_refreshes")
    elif corruption == "deleted_receipt":
        current["receipts"].pop()
    elif corruption == "changed_predecessor":
        f["predecessor"].write_text(f["predecessor"].read_text() + " ")
    elif corruption == "changed_command_leaf":
        proof = json.loads(f["request"].read_text())["evidence"]["validation_runs"][0]["command_receipt"]["path"]
        Path(proof).write_text(Path(proof).read_text() + " ")
    else:
        current["validation_refreshes"] = "not a lineage list"
    _write(f["task"].path, current)
    before = f["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError):
        _refresh(f)
    assert f["task"].path.read_bytes() == before
    projection_before = Path(current["autodev_path"]).read_bytes()
    with pytest.raises(AutoDevStateError):
        sync_delivery_projection(f["task"].path)
    with pytest.raises(delivery.DevelopmentDeliveryError):
        refresh.pr_create_validation_authority(f["task"].path, json.loads(Path(_family(f)).read_text()))
    assert Path(current["autodev_path"]).read_bytes() == projection_before


@pytest.mark.parametrize("corruption", ["summary_bool", "reason_bool", "head_bool", "ref_bool",
    "hash_bool", "ambiguous_json", "mutated_terminal", "scalar_idempotency", "repository_list",
    "predecessor_status_list", "unavailable_classification_list", "unavailable_command_bool",
    "future_proof"])
def test_malformed_scalar_and_immutable_reference_proof_refuses_before_mutation(tmp_path, corruption):
    f = _fixture(tmp_path)
    payload = json.loads(f["request"].read_text())
    evidence = payload["evidence"]
    if corruption == "summary_bool":
        payload["summary"] = True
    elif corruption == "reason_bool":
        evidence["repair_lineage"]["reason"] = True
    elif corruption == "head_bool":
        evidence["source_head_sha"] = False
    elif corruption == "ref_bool":
        evidence["validation_runs"][0]["terminal"]["path"] = True
    elif corruption == "hash_bool":
        evidence["validation_runs"][0]["terminal"]["sha256"] = True
    elif corruption == "repository_list":
        evidence["repository"] = ["acme/app"]
    elif corruption.startswith("predecessor_") or corruption.startswith("unavailable_"):
        predecessor = json.loads(f["predecessor"].read_text())
        if corruption == "predecessor_status_list":
            predecessor["status"] = ["passed"]
        elif corruption == "unavailable_classification_list":
            predecessor["evidence"]["unavailable_check"]["classification"] = ["infrastructure"]
        else:
            predecessor["evidence"]["unavailable_check"]["command"] = True
        _write(f["predecessor"], predecessor)
        evidence["repair_lineage"]["predecessor"] = _bound(f["predecessor"])
        current = f["task"].read()
        [r for r in current["receipts"] if r["state"] == "local_validation"][-1]["sha256"] = _bound(f["predecessor"])["sha256"]
        _write(f["task"].path, current)
    elif corruption == "future_proof":
        payload["verified_at"] = "2099-01-01T00:00:00Z"
    elif corruption == "mutated_terminal":
        terminal = Path(evidence["validation_runs"][0]["terminal"]["path"])
        terminal.write_text(terminal.read_text() + " ")
    _write(f["request"], payload)
    if corruption == "ambiguous_json":
        raw = f["request"].read_text().replace('"head_sha":', '"head_sha": "wrong", "head_sha":', 1)
        f["request"].write_text(raw)
    before = f["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError):
        _refresh(f, key=True if corruption == "scalar_idempotency" else "repair")
    assert f["task"].path.read_bytes() == before


def test_successive_refreshes_preserve_bound_chain_and_last_replay(tmp_path):
    f = _fixture(tmp_path)
    first = _refresh(f)["task"]
    first_snapshot = Path(first["receipts"][-1]["ref"])
    original = first_snapshot.read_bytes()
    (f["worktree"] / "README.md").write_text("second validated repair\n")
    _git("add", "README.md", cwd=f["worktree"])
    _git("commit", "-m", "second validated repair", cwd=f["worktree"])
    head = _git("rev-parse", "HEAD", cwd=f["worktree"])
    payload = json.loads(f["request"].read_text())
    evidence = payload["evidence"]
    evidence["head_sha"] = head
    evidence["validation_runs"] = [_command_proof(f["root"], f["packet"], f["worktree"],
        f["command"], head, first["policy_fingerprint"])]
    evidence["repair_lineage"] = {"predecessor": _bound(first_snapshot),
        "from_head_sha": f["head"], "to_head_sha": head, "reason": "second independently validated repair"}
    payload["verified_at"] = _now()
    _write(f["request"], payload)
    second = _refresh(f, "second")["task"]
    assert len(second["validation_refreshes"]) == 2
    assert second["validation_head_sha"] == head
    assert first_snapshot.read_bytes() == original
    assert _refresh(f, "second")["replayed"] is True
    assert f["task"].read()["receipts"] == second["receipts"]
    second["validation_refreshes"].pop(0)
    _write(f["task"].path, second)
    with pytest.raises(delivery.DevelopmentDeliveryError):
        _refresh(f, "second")


def test_present_producer_failure_is_visible_and_replay_repairs_without_duplicate_authority(tmp_path, monkeypatch):
    f = _fixture(tmp_path)
    calls = []
    def emit(task, head, policy):
        calls.append(head)
        if len(calls) == 1:
            raise delivery.DevelopmentDeliveryError("present readiness producer failed")
        return {"validation_status": "passed", "readiness_evidence_verified": {"validation": True}}
    monkeypatch.setattr(refresh, "_emit_readiness", emit)
    with pytest.raises(delivery.DevelopmentDeliveryError, match="producer failed"):
        _refresh(f)
    recorded = f["task"].read()
    assert len(recorded["validation_refreshes"]) == 1
    result = _refresh(f)
    assert result["replayed"] is True
    assert result["readiness_projection"]["readiness_evidence_verified"]["validation"] is True
    assert result["task"]["receipts"] == recorded["receipts"]
    assert calls == [f["head"], f["head"]]


@pytest.mark.parametrize("corruption", ["outside_symlink", "inside_symlink", "loop", "collision", "directory"])
def test_successor_output_refuses_unsafe_target_before_authority_recording(tmp_path, corruption):
    f = _fixture(tmp_path)
    raw = f["request"].read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    snapshot = f["packet"] / "artifacts/development-delivery/evidence" / f"validation-refresh-{digest}.json"
    outside = tmp_path / "outside-successor.json"
    outside.write_bytes(raw)
    if corruption == "outside_symlink":
        snapshot.symlink_to(outside)
    elif corruption == "inside_symlink":
        snapshot.symlink_to(f["request"])
    elif corruption == "loop":
        snapshot.symlink_to(snapshot)
    elif corruption == "directory":
        snapshot.mkdir()
    else:
        snapshot.write_bytes(b"different immutable evidence\n")
    before = f["task"].path.read_bytes()
    predecessor = f["predecessor"].read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="snapshot"):
        _refresh(f)
    assert f["task"].path.read_bytes() == before
    assert f["predecessor"].read_bytes() == predecessor
    assert outside.read_bytes() == raw
    assert not f["task"].read().get("validation_refreshes")


@pytest.mark.parametrize("corruption", ["outside_parent", "inside_parent", "parent_loop", "dangling_parent"])
def test_snapshot_parent_admission_creates_no_directories_or_external_files(tmp_path, corruption):
    packet = tmp_path / "packet"
    packet.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    if corruption == "outside_parent":
        (packet / "artifacts").symlink_to(outside, target_is_directory=True)
    elif corruption == "inside_parent":
        (packet / "storage").mkdir()
        (packet / "artifacts").symlink_to(packet / "storage", target_is_directory=True)
    elif corruption == "parent_loop":
        (packet / "artifacts").symlink_to(packet / "artifacts", target_is_directory=True)
    else:
        (packet / "artifacts").symlink_to(outside / "missing", target_is_directory=True)
    before = list(packet.rglob("*"))
    with pytest.raises(delivery.DevelopmentDeliveryError, match="snapshot"):
        refresh._snapshot_target(packet.resolve(), "a" * 64)
    assert list(packet.rglob("*")) == before
    assert not list(outside.iterdir())
