"""Native scratch-Git and SQLite successor controls with an explicit provider boundary."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest
import yaml

from genomes_agentic_os import development_delivery as delivery
from genomes_agentic_os import development_successor_binding as admission
from genomes_agentic_os import development_successor_state as binding
from genomes_agentic_os.development_validation_refresh import refresh_development_validation
from genomes_agentic_os.auto_dev_orchestration import require_auto_dev_predecessors
from genomes_agentic_os.cli import main
from genomes_agentic_os.state import work_items
from genomes_agentic_os.state.db import connect, default_db_path
from test_development_delivery import _git
from test_development_validation_refresh import _fixture, _family, _write
import test_development_validation_refresh as refresh_fixtures


def _save(packet: Path, name: str, value: dict[str, Any]) -> dict[str, str]:
    """Write a request assertion in the scratch packet; admission still rederives it."""
    path = _write(packet / "artifacts/binding-input" / (name + ".json"), value)
    return {"packet_ref": str(path.relative_to(packet)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "schema": value["schema"]}


@pytest.fixture
def candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> dict[str, Any]:
    """Build actual task/registered worktrees/commits/remote refs and immutable family."""
    monkeypatch.delenv("AGENTIC_OS_ROOT", raising=False)
    original_project = refresh_fixtures._project
    def project_with_explicit_policy(root: Path, repository: Path, **kwargs: Any) -> Path:
        """Declare the real policy selectors before the initial task freezes them."""
        project = original_project(root, repository, **kwargs)
        path = project / "config/development.yml"
        profile = yaml.safe_load(path.read_text())
        profile["policies"] = {plane: {"paths": [
            "harness/shared_factory/05-knowledge/auto_dev" + ("/" + plane if plane != "auto_dev" else ""),
            "domains/acme/config/auto_dev" + ("/" + plane if plane != "auto_dev" else ""),
            "config/auto_dev" + ("/" + plane if plane != "auto_dev" else ""),
        ]} for plane in admission.DEVELOPMENT_POLICY_PLANES}
        path.write_text(yaml.safe_dump(profile))
        return project
    monkeypatch.setattr(refresh_fixtures, "_project", project_with_explicit_policy)
    start_stage = getattr(request, "param", "groom")
    f = _fixture(tmp_path, changed=False, historical_command=False,
                 mode="default" if start_stage == "readiness" else "single_stage",
                 fallback=start_stage != "readiness")
    if start_stage == "groom":
        refresh_development_validation(f["task"].path, evidence_file=f["request"],
                                       idempotency_key="original-validated-epoch")
    current = f["task"].read()
    family_path = Path(_family(f, head=f["old_head"]))
    family = json.loads(family_path.read_text())
    family["evidence"]["repository"] = current["repository"]["id"]
    family["evidence"]["family_complete"] = True
    family["evidence"]["targets"] = [{
        "repository": "acme/app", "base_branch": "main", "pr_number": 236,
        "url": "https://github.com/acme/app/pull/236",
        "head_branch": current["worktree"]["branch"], "head_sha": f["old_head"]}]
    _write(family_path, family)
    delivery.run_development_stage(f["task"].path, stage="release_propagation",
        receipts={"release_propagation": str(family_path)}, idempotency_prefix="original-family")
    current = f["task"].read()
    wrapper = json.loads(Path(current["stage_receipts"]["release_propagation"]["ref"]).read_text())
    family_path = f["packet"] / wrapper["receipt"]
    project = delivery.project_root(f["root"], "acme", "app")
    name = "successor-registered"
    successor = project / "worktrees" / name
    _git("worktree", "add", "-b", "feature/successor-local", str(successor), f["old_head"], cwd=f["worktree"])
    (successor / "README.md").write_text("independently committed successor behavior\n")
    _git("add", "README.md", cwd=successor)
    _git("commit", "-m", "fix: successor behavior", cwd=successor)
    delivery.register_project_worktree(f["root"], "acme", "app", name, path=successor)
    name = next(row["id"] for row in delivery.worktree_entries_for_project(project)
                if Path(row["path"]).resolve() == successor.resolve())
    remote = tmp_path / "remote.git"
    published = current["worktree"]["branch"]
    _git("push", str(remote), "HEAD:refs/heads/" + published, cwd=successor)
    head = _git("rev-parse", "HEAD", cwd=successor)
    provider = {"schema": "development-successor-provider/v1", "number": 236,
        "url": "https://github.com/acme/app/pull/236", "state": "open", "merged": False,
        "repository": "acme/app", "source_repository": "acme/app", "source_branch": published,
        "head": head, "base_branch": "main", "base_sha": f["old_head"],
        "author_identity": "github:michaelwclark"}
    # Only the external SaaS edge is substituted. Git ancestry, objects,
    # worktrees, index/status and actual bare-remote refs remain genuine.
    monkeypatch.setattr(admission, "_provider", lambda *_args: deepcopy(provider))
    original_native = admission.native
    def native_read(command: list[str], *, cwd: Path | None = None) -> str:
        """Route the fixture's provider origin transport to its real disposable bare remote."""
        if "ls-remote" in command:
            command = [str(remote) if arg == "origin" else arg for arg in command]
        return original_native(command, cwd=cwd)
    monkeypatch.setattr(admission, "native", native_read)
    observation = admission.observe_successor(f["task"].path, registry_id=name, pull_request=236)
    def ref(name: str, value: dict[str, Any]) -> dict[str, str]:
        """Create one exact request-side snapshot from the independent observation."""
        return _save(f["packet"], name, value)
    policy_review = {"schema": "development-successor-policy-admission/v1",
                     "delta_sha256": admission.digest(observation["policy_delta"])}
    old = observation["task"]
    identity = {key: old[key] for key in ("run_id", "ticket", "canonical_work_id", "domain", "project", "work_item")}
    identity["repository_id"] = old["repository"]["id"]
    request = {"schema": admission.SCHEMA, "reason": "Continue the same published change in the registered successor",
        "expected": observation["expected"], "identity": identity,
        "predecessor": {"source_head": observation["protected_boundary"]["head"],
            "policy_fingerprint": old["policy_fingerprint"],
            "protected_boundary_snapshot": ref("protected", observation["protected_boundary"]),
            "historical_receipt_inventory": ref("history", observation["historical_receipts"]),
            "original_runtime_record": ref("original-runtime", observation["original_runtime"])},
        "successor": {"registry_id": name, "real_path": str(successor),
            "local_source_branch": "feature/successor-local", "expected_head": head,
            "expected_base_sha": f["old_head"], "registry_snapshot": ref("registry", observation["registry"]),
            "runtime": {"provider": observation["runtime"]["provider"], "identity": observation["runtime"]["identity"],
                "namespace": observation["runtime"]["namespace"], "native_readback": ref("runtime", observation["runtime"])}},
        "pull_request": {"provider": "github", "number": 236, "repository_id": old["repository"]["id"],
            "base_branch": "main", "base_sha": f["old_head"], "provider_source_branch": published,
            "source_head": head, "family_predecessor": {"packet_ref": str(family_path.relative_to(f["packet"])),
                "sha256": hashlib.sha256(family_path.read_bytes()).hexdigest(), "schema": "development-stage-evidence/v1"},
            "provider_readback": ref("provider", provider), "remote_ref_readback": ref("remote", observation["remote"])},
        "policy": {"new_effective_policy": ref("policy", observation["policy"]),
            "new_fingerprint": observation["policy"]["fingerprint"], "delta_review": ref("policy-admission", policy_review)},
        "review_lineage": {"existing_shared_coordinator_root": observation["coordinator"]["root"],
            "family_key": observation["coordinator"]["family_key"],
            "coordinator_inventory": ref("coordinator", observation["coordinator"]),
            "attempt_and_budget_inventory": ref("budgets", observation["coordinator"])}}
    request_path = _write(f["packet"] / "artifacts/binding-request.json", request)
    return {**f, "candidate": successor, "binding_request": request_path, "binding_payload": request,
            "provider": provider, "observation": observation, "family": family_path, "remote": remote}


def _bind(fixture: dict[str, Any], *, apply: bool = True, key: str = "bind-source") -> dict[str, Any]:
    """Invoke the real transition with the frozen raw predecessor digest."""
    return binding.bind_development_successor(fixture["task"].path,
        request_file=fixture["binding_request"], expect_state_sha256=fixture["binding_payload"]["expected"]["task_sha256"],
        idempotency_key=key, apply=apply)


def _renew_assertions(fixture: dict[str, Any], canonical_review: dict[str, Any] | None = None) -> dict[str, Any]:
    """Refresh request-side assertions only from independently rederived native proofs."""
    request = fixture["binding_payload"]
    observed = admission.observe_successor(fixture["task"].path,
        registry_id=request["successor"]["registry_id"], pull_request=236)
    request["expected"] = observed["expected"]
    comparisons = (
        (request["predecessor"], "protected_boundary_snapshot", "protected_boundary"),
        (request["predecessor"], "historical_receipt_inventory", "historical_receipts"),
        (request["predecessor"], "original_runtime_record", "original_runtime"),
        (request["successor"], "registry_snapshot", "registry"),
        (request["successor"]["runtime"], "native_readback", "runtime"),
        (request["pull_request"], "provider_readback", "provider"),
        (request["pull_request"], "remote_ref_readback", "remote"),
        (request["policy"], "new_effective_policy", "policy"),
        (request["review_lineage"], "coordinator_inventory", "coordinator"),
        (request["review_lineage"], "attempt_and_budget_inventory", "coordinator"))
    for container, key, observed_key in comparisons:
        container[key] = _save(fixture["packet"], "renewed-" + key, observed[observed_key])
    request["successor"]["expected_head"] = observed["provider"]["head"]
    request["pull_request"]["source_head"] = observed["provider"]["head"]
    request["policy"]["new_fingerprint"] = observed["policy"]["fingerprint"]
    delta_review = {"schema": "development-successor-policy-admission/v1",
                    "delta_sha256": admission.digest(observed["policy_delta"]), **(canonical_review or {})}
    request["policy"]["delta_review"] = _save(fixture["packet"], "renewed-policy-review", delta_review)
    _write(fixture["binding_request"], request)
    return observed


@pytest.mark.parametrize("available", [True, False])
def test_canonical_policy_review_producer_keeps_task_and_shared_budget_authority(
    candidate: dict[str, Any], monkeypatch: pytest.MonkeyPatch, available: bool,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The real runner/coordinator binds a native rule delta; only its external CLI is substituted."""
    from test_opposing_model_review_runner import _completed, _load_runner
    from genomes_agentic_os.review_coordination import ReviewSubject, load_review_receipt, stable_review_key
    tree = candidate["candidate"]
    (tree / "AGENTS.md").write_text("Preserve 95 coverage and all account identity checks.\n")
    _git("add", "AGENTS.md", cwd=tree)
    _git("commit", "-m", "docs: preserve inherited source controls", cwd=tree)
    _git("push", str(candidate["remote"]), "HEAD:refs/heads/" + candidate["provider"]["source_branch"], cwd=tree)
    candidate["provider"]["head"] = _git("rev-parse", "HEAD", cwd=tree)
    profile_path = delivery.project_root(candidate["root"], "acme", "app") / "config/development.yml"
    profile = yaml.safe_load(profile_path.read_text())
    profile.setdefault("review", {})["opposing_harness"] = {
        "model": "claude-fable-5", "transport": "claude_cli", "unavailable_policy": "continue_with_receipt"}
    profile_path.write_text(yaml.safe_dump(profile))
    observed = _renew_assertions(candidate)
    task_raw = candidate["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="canonical review"):
        _bind(candidate)
    runner = _load_runner()
    source = runner.successor_policy_request(candidate["packet"], candidate["task"].read()["ticket"], tree,
                                             candidate["binding_request"])
    assert source["local_source_branch"] != source["provider_source_branch"]
    assert source["successor_policy_source"]["identity"]["policy_delta"]["source_rule_changes"][0]["path"] == "AGENTS.md"
    actual_provider = candidate["provider"]
    monkeypatch.setattr(runner, "provider_pr", lambda *_args: {
        "number": 236, "url": actual_provider["url"], "state": "OPEN", "headRefOid": actual_provider["head"],
        "baseRefName": "main", "baseRefOid": actual_provider["base_sha"],
        "statusCheckRollup": [{"conclusion": "SUCCESS"}]})
    monkeypatch.setattr(runner, "git_repository", lambda _tree: "acme/app")
    original_run = runner.run
    calls: list[list[str]] = []
    def external_cli(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        """Stand in for the paid external model only; native helper/Git/coordinator stay real."""
        if command[0] == "/synthetic-read-only-reviewer":
            calls.append(command)
            assert command[command.index("--model") + 1] == "claude-fable-5"
            assert command[command.index("--permission-mode") + 1] == "dontAsk"
            assert command[command.index("--allowedTools") + 1] == runner.CLAUDE_TOOLS
            assert "ANTHROPIC_API_KEY" not in kwargs["env"]
            assert "ANTHROPIC_AUTH_TOKEN" not in kwargs["env"]
            assert "Native delta" in command[-1]
            assert "source_rule_changes" in command[-1]
            return _completed(0, "```json\n[]\n```\nAGENTIC_OS_REVIEW_VERDICT: CLEAN\n")
        return original_run(command, **kwargs)
    monkeypatch.setattr(runner, "run", external_cli)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-key-never-forwarded")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "synthetic-token-never-forwarded")
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/synthetic-read-only-reviewer" if available else None)
    monkeypatch.setattr(sys, "argv", ["run_opposing_model_review.py", candidate["task"].read()["ticket"],
        "--os-root", str(candidate["root"]), "--work-item", str(candidate["packet"]),
        "--worktree", str(tree), "--successor-policy-request", str(candidate["binding_request"])])
    assert runner.main() == (0 if available else 2)
    result = json.loads(capsys.readouterr().out)
    canonical_path = Path(result["coordination_receipt"])
    canonical = load_review_receipt(canonical_path)
    assert canonical["outcome"] == ("clean" if available else "unavailable")
    run_dir = Path(canonical["review"]["review_run_dir"])
    validation = json.loads((run_dir / "validation-plan.json").read_text())
    decision = json.loads((run_dir / "readiness-decision.json").read_text())
    assert validation["validation_status"] == decision["validation_status"] == "not_started"
    assert validation["pr_check_status"] == decision["pr_check_status"] == "not_applicable"
    assert decision["decision"] == "blocked_validation"
    assert not canonical["review"]["decision"].startswith("ready_")
    review_request = json.loads((run_dir / "review-request.json").read_text())
    assert review_request["selected_reviewer_model"] == "claude-fable-5"
    assert review_request["review_unavailable_policy"] == "continue_with_receipt"
    assert "- Reviewer model: `claude-fable-5`" in (run_dir / "model-receipt.md").read_text()
    assert canonical["review"]["policy_delta_sha256"] == admission.digest(observed["policy_delta"])
    subject = ReviewSubject("acme/app", "github:acme/app#236", "main", actual_provider["base_sha"],
                            actual_provider["head"], observed["policy"]["fingerprint"])
    assert canonical["key"] == stable_review_key(subject)
    assert len(calls) == int(available)
    assert candidate["task"].path.read_bytes() == task_raw
    _renew_assertions(candidate, {"canonical_review_sha256": hashlib.sha256(canonical_path.read_bytes()).hexdigest()})
    if available:
        assert _bind(candidate)["status"] == "bound_validation_pending"
    else:
        with pytest.raises(delivery.DevelopmentDeliveryError, match="actual delta"):
            _bind(candidate)
        assert candidate["task"].path.read_bytes() == task_raw


@pytest.mark.parametrize("fault", [None, "namespace", "mount", "duplicate", "foreign_claim", "missing"])
def test_managed_runtime_observer_binds_real_registry_and_sqlite_claims_with_docker_boundary(
    candidate: dict[str, Any], monkeypatch: pytest.MonkeyPatch, fault: str | None,
) -> None:
    """Exercise real owner files/claim queries with only the external Docker response substituted."""
    current = deepcopy(candidate["task"].read())
    current.update({"domain": "los", "project": "los_app_los_django"})
    profile, _ = admission._profile(candidate["task"].read())
    profile["runtime"] = {"ownership": "managed", "provider": "los_fast_worktree",
        "identity_template": "{domain}-{project}-{worktree}",
        "teardown_command": "true {runtime_identity}", "readback_command": "true {runtime_identity}"}
    current["runtime"] = delivery._runtime_registration(profile, current["worktree"],
        domain=current["domain"], project=current["project"], ticket=current["ticket"])
    record = candidate["observation"]["registry"]["worktree"]
    slug = record["name"].lower()
    home = candidate["packet"] / "artifacts/observer-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: home))
    registry = home / ".los-fast-worktree/registry.tsv"
    registry.parent.mkdir()
    row = "53\t" + slug + "\t" + record["path"] + "\tfixture-registration\n"
    registry.write_text(row * (2 if fault == "duplicate" else 1))
    env = Path(record["path"]) / ".env.worktree"
    env.write_text("FWT_SLUG=" + slug + "\nLOS_STACK_NAME=los-" + slug
                   + "\nFWT_INDEX=" + ("54" if fault == "namespace" else "53")
                   + "\nUNRELATED_SECRET=must-never-appear-in-the-proof\n")
    if fault == "foreign_claim":
        connection = connect(default_db_path(candidate["root"]))
        try:
            work_items.upsert(connection, item_id="foreign-runtime-owner", title="Foreign owner",
                worktree_path=record["path"], packet_path=str(home), domain="los", project="los_app_los_django")
        finally:
            connection.close()
    container = "c" * 64
    calls: list[list[str]] = []
    def docker_read(command: list[str], **_kwargs: Any) -> str:
        """Supply only the bounded Docker ownership edge; never execute a runtime command."""
        calls.append(command)
        assert command[0] == "docker"
        assert not any(word in command for word in ("exec", "start", "stop", "rm", "build"))
        if command[1] == "info":
            return "fixture-daemon"
        if command[1] == "ps":
            return "" if fault == "missing" else container
        assert "Config.Env" not in command[3]
        return json.dumps({"id": container, "project": "los-" + slug,
            "mounts": [{"Type": "bind", "Source": str(home) if fault == "mount" else record["path"],
                        "Destination": "/app"}]})
    monkeypatch.setattr(admission, "native", docker_read)
    if fault:
        with pytest.raises(delivery.DevelopmentDeliveryError):
            admission._native_runtime(current, profile, record)
    else:
        observed = admission._native_runtime(current, profile, record)
        assert observed["namespace"] == "53"
        assert observed["containers"] == [{"id": container, "compose_project": "los-" + slug,
            "source": record["path"], "destination": "/app"}]
        assert observed["work_item_claim"]["canonical_work_id"] == current["canonical_work_id"]
        assert "must-never-appear" not in json.dumps(observed)
        assert [row[1] for row in calls] == ["info", "ps", "inspect"]


def test_native_plan_preserves_every_task_and_source_byte(candidate: dict[str, Any]) -> None:
    """A valid plan distinguishes both branches and performs no transition write."""
    task = candidate["task"].path.read_bytes()
    portfolio = (candidate["task"].path.parents[2] / "portfolio.json").read_bytes()
    manifest = (candidate["packet"] / "autodev.json").read_bytes()
    predecessor = admission.predecessor_boundary(candidate["task"].read())
    result = _bind(candidate, apply=False)
    assert result["status"] == "read_only_plan"
    assert result["local_source_branch"] == "feature/successor-local"
    assert result["provider_source_branch"] != result["local_source_branch"]
    assert candidate["task"].path.read_bytes() == task
    assert (candidate["task"].path.parents[2] / "portfolio.json").read_bytes() == portfolio
    assert (candidate["packet"] / "autodev.json").read_bytes() == manifest
    assert admission.predecessor_boundary(candidate["task"].read()) == predecessor
    assert not (candidate["packet"] / "artifacts/development-delivery/successor-bindings").exists()


def test_native_bind_preserves_history_fences_old_gates_and_replays(candidate: dict[str, Any]) -> None:
    """Real CAS/outbox updates only the same work row and retains original receipts."""
    before = candidate["task"].read()
    before_source = admission.predecessor_boundary(before)
    before_receipt = candidate["predecessor"].read_bytes()
    first = _bind(candidate)
    after = candidate["task"].read()
    assert first["status"] == "bound_validation_pending"
    assert after["state"] == before["state"] == "local_validation"
    for key in ("run_id", "ticket", "canonical_work_id", "work_item", "receipts", "stage_receipts",
                "attempts", "failure", "lease", "max_attempts", "authorship"):
        assert after.get(key) == before.get(key)
    assert after["worktree"]["path"] == str(candidate["candidate"])
    assert after["worktree"]["branch"] == "feature/successor-local"
    assert after["pull_request_subject"]["source_branch"] == before["worktree"]["branch"]
    assert after["validation_pending_binding"] == first["binding_id"]
    assert candidate["predecessor"].read_bytes() == before_receipt
    assert admission.predecessor_boundary(before) == before_source
    projection = json.loads((candidate["packet"] / "autodev.json").read_text())
    assert projection["subject_revision"] is None
    assert projection["stages"]["develop"]["status"] == "not_started"
    assert projection["stages"]["pr_create"]["status"] == "not_started"
    with pytest.raises((delivery.DevelopmentDeliveryError, ValueError), match="fresh native validation"):
        require_auto_dev_predecessors(candidate["packet"], "finalize")
    connection = connect(default_db_path(candidate["root"]))
    try:
        row = work_items.get(connection, before["canonical_work_id"])
        count = connection.execute("SELECT COUNT(*) FROM work_items WHERE id = ?", (before["canonical_work_id"],)).fetchone()[0]
        assert count == 1
        assert row["worktree_path"] == str(candidate["candidate"])
        assert row["branch"] == "feature/successor-local"
        assert row["metadata"]["active_successor_binding"]["binding_id"] == first["binding_id"]
    finally:
        connection.close()
    saved = candidate["task"].path.read_bytes()
    assert _bind(candidate)["replayed"] is True
    assert candidate["task"].path.read_bytes() == saved
    events = [json.loads(line) for line in candidate["task"].ledger.read_text().splitlines()]
    assert sum(row["type"] == "development.successor.bound" for row in events) == 1


@pytest.mark.parametrize("mutation", ["head", "author", "base", "source_repository", "closed"])
def test_native_provider_drift_rejects_before_mutation(candidate: dict[str, Any], mutation: str) -> None:
    """A caller's previously hashed readback cannot substitute for current provider truth."""
    before = candidate["task"].path.read_bytes()
    changes = {"head": ("head", "a" * 40), "author": ("author_identity", "github:foreign"),
               "base": ("base_branch", "foreign"), "source_repository": ("source_repository", "other/app"),
               "closed": ("state", "closed")}
    key, value = changes[mutation]
    candidate["provider"][key] = value
    with pytest.raises(delivery.DevelopmentDeliveryError):
        _bind(candidate)
    assert candidate["task"].path.read_bytes() == before


@pytest.mark.parametrize("mutation", ["dirty", "index", "remote", "branch", "merge"])
def test_real_git_drift_rejects_before_mutation(candidate: dict[str, Any], mutation: str) -> None:
    """Real source/index/branch/operation changes fail without Git repair or checkout."""
    before = candidate["task"].path.read_bytes()
    tree = candidate["candidate"]
    if mutation in {"dirty", "index"}:
        (tree / "README.md").write_text("unreviewed change\n")
        if mutation == "index":
            _git("add", "README.md", cwd=tree)
    elif mutation == "remote":
        _git("push", str(candidate["remote"]), candidate["old_head"] + ":refs/heads/" + candidate["provider"]["source_branch"], "--force", cwd=tree)
    elif mutation == "branch":
        _git("checkout", "-b", "feature/foreign-local", cwd=tree)
    else:
        git_dir = Path(_git("rev-parse", "--git-dir", cwd=tree))
        (git_dir / "MERGE_HEAD").write_text(candidate["old_head"] + "\n")
    with pytest.raises(delivery.DevelopmentDeliveryError):
        _bind(candidate)
    assert candidate["task"].path.read_bytes() == before


def test_closed_duplicate_and_symlink_request_rejections(candidate: dict[str, Any]) -> None:
    """Strict JSON and ordinary packet paths reject ambiguous or substituted assertions."""
    path = candidate["binding_request"]
    before = candidate["task"].path.read_bytes()
    raw = path.read_bytes()
    value = json.loads(raw)
    value["waive_coverage"] = True
    _write(path, value)
    with pytest.raises(delivery.DevelopmentDeliveryError, match="closed schema"):
        _bind(candidate)
    path.write_text('{"schema":"first","schema":"second"}')
    with pytest.raises(delivery.DevelopmentDeliveryError, match="duplicate"):
        _bind(candidate)
    path.write_bytes(raw)
    proof_path = candidate["packet"] / candidate["binding_payload"]["predecessor"]["original_runtime_record"]["packet_ref"]
    proof_raw = proof_path.read_bytes()
    target = candidate["packet"] / "artifacts/substituted.json"
    target.write_bytes(proof_raw)
    proof_path.unlink()
    proof_path.symlink_to(target)
    with pytest.raises(delivery.DevelopmentDeliveryError, match="symlink"):
        _bind(candidate)
    assert candidate["task"].path.read_bytes() == before


def test_stale_canonical_row_and_budget_changes_reject(candidate: dict[str, Any]) -> None:
    """Unchanged task bytes do not authorize ignoring concurrent canonical/review history."""
    before = candidate["task"].path.read_bytes()
    connection = connect(default_db_path(candidate["root"]))
    try:
        work_items.update(connection, candidate["task"].read()["canonical_work_id"], context_summary="concurrent owner")
    finally:
        connection.close()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="stale"):
        _bind(candidate)
    assert candidate["task"].path.read_bytes() == before


def test_outbox_crash_is_fenced_then_native_replay_finishes(candidate: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """A real committed task survives projection failure without admitting stale consumers."""
    original = binding._sync_auto_dev_projection
    monkeypatch.setattr(binding, "_sync_auto_dev_projection", lambda *_args: None)
    with pytest.raises(delivery.DevelopmentDeliveryError, match="projection"):
        _bind(candidate)
    committed = json.loads(candidate["task"].path.read_text())
    assert committed["active_successor_binding"]["status"] == "projections_pending"
    with pytest.raises(delivery.DevelopmentDeliveryError, match="pending"):
        candidate["task"].read()
    monkeypatch.setattr(binding, "_sync_auto_dev_projection", original)
    result = _bind(candidate)
    assert result["replayed"] is True
    assert candidate["task"].read()["active_successor_binding"]["status"] == "bound_validation_pending"


def test_cli_exposes_dry_run_and_rejects_unknown_override(candidate: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
    """The real parser has no force, budget-reset or review-waiver escape hatch."""
    argv = ["develop", "bind-successor", str(candidate["task"].path), "--request", str(candidate["binding_request"]),
            "--expect-state-sha256", candidate["binding_payload"]["expected"]["task_sha256"],
            "--idempotency-key", "cli-plan", "--json"]
    assert main(argv) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "read_only_plan"
    with pytest.raises(SystemExit) as raised:
        main([*argv, "--force"])
    assert raised.value.code == 2


def _metadata(current: dict[str, Any]) -> dict[str, str]:
    """Return the four explicit branch/binding fields required by every new epoch."""
    active = current["active_successor_binding"]
    return {"binding_id": active["binding_id"], "binding_receipt_sha256": active["receipt"]["sha256"],
            "local_source_branch": current["worktree"]["branch"],
            "provider_source_branch": current["pull_request_subject"]["source_branch"]}


@pytest.mark.parametrize("candidate", ["groom", "readiness"], indirect=True)
def test_real_successor_validation_and_family_use_new_policy_and_both_branches(candidate: dict[str, Any]) -> None:
    """Execute the real frozen command in the successor, then continue its native PR family."""
    from test_development_validation_refresh import _bound, _command_proof, _now
    before = candidate["task"].read()
    prior_rows = [row for row in before["receipts"] if row["state"] == "local_validation"]
    predecessor = Path(prior_rows[-1]["ref"])
    predecessor_raw = predecessor.read_bytes()
    _bind(candidate)
    current = candidate["task"].read()
    head = _git("rev-parse", "HEAD", cwd=candidate["candidate"])
    run = _command_proof(candidate["root"], candidate["packet"], candidate["candidate"],
                         candidate["command"], head, current["policy_fingerprint"])
    evidence = {"ticket": current["ticket"], "canonical_work_id": current["canonical_work_id"],
        "repository_id": current["repository"]["id"], "repository": "acme/app",
        "task_state_ref": str(candidate["task"].path), "worktree": str(candidate["candidate"]),
        "source_branch": current["worktree"]["branch"], "head_sha": head,
        "policy_fingerprint": current["policy_fingerprint"],
        "policy_sha256": _bound(Path(current["policy_receipt"]))["sha256"], "validation_runs": [run],
        "repair_lineage": {"predecessor": _bound(predecessor), "from_head_sha": candidate["old_head"],
            "to_head_sha": head, "reason": "Genuine successor command after registered binding"},
        **_metadata(current)}
    payload = {"schema": "development-stage-evidence/v1", "state": "local_validation", "status": "passed",
               "summary": "Actual frozen native command passed in the bound successor", "verified_at": _now(),
               "evidence": evidence}
    path = _write(candidate["packet"] / "artifacts/bound-native-validation.json", payload)
    refreshed = refresh_development_validation(candidate["task"].path, evidence_file=path,
                                               idempotency_key="bound-native-validation")
    current = refreshed["task"]
    assert "validation_pending_binding" not in current
    assert current["active_successor_binding"]["status"] == "bound"
    assert current["validation_head_sha"] == head
    assert len(current["validation_refreshes"]) == len(before.get("validation_refreshes", [])) + 1
    assert current["validation_refreshes"][:-1] == before.get("validation_refreshes", [])
    assert predecessor.read_bytes() == predecessor_raw
    projection = json.loads((candidate["packet"] / "autodev.json").read_text())
    assert projection["stages"]["develop"]["status"] == "completed"
    assert projection["stages"]["pr_create"]["status"] == "not_started"
    # Same task, original published branch, new exact head/policy; the local
    # branch remains different and is never relabeled as the provider branch.
    from genomes_agentic_os.auto_dev_orchestration import record_auto_dev_stage
    actual_readme = candidate["candidate"] / "README.md"
    assert actual_readme.read_text() == "independently committed successor behavior\n"
    document_proof = candidate["packet"] / "artifacts/successor-document-readback.txt"
    document_proof.write_text("Actual successor README sha256=" + hashlib.sha256(actual_readme.read_bytes()).hexdigest())
    document = _write(candidate["packet"] / "artifacts/successor-document.json", {
        "schema": "auto-dev-stage-evidence/v1", "stage": "document", "status": "completed",
        "summary": "Read back the actual committed successor documentation", "verified_at": _now(),
        "subject_revision": head, "evidence": {"receipt_refs": [str(document_proof)], **_metadata(current)}})
    record_auto_dev_stage(candidate["packet"] / "autodev.json", stage="document", evidence_file=document,
                          idempotency_key="bound-source-document")
    family = json.loads(candidate["family"].read_text())
    family["evidence"].update({**_metadata(current), "policy_fingerprint": current["policy_fingerprint"],
        "source_branch": current["pull_request_subject"]["source_branch"],
        "source_head_sha": head, "subject_revision": head,
        "provider_observed": {"head_sha": candidate["provider"]["head"],
            "pull_request": "github:acme/app#236"},
        "supersession": {"supersedes_source_head_sha": candidate["old_head"],
            "reason": "The same provider PR now publishes the verified successor commit"}})
    family["evidence"]["targets"][0]["head_sha"] = head
    family_path = _write(candidate["packet"] / "artifacts/bound-native-family.json", family)
    delivery.run_development_stage(candidate["task"].path, stage="release_propagation",
        receipts={"release_propagation": str(family_path)}, idempotency_prefix="bound-native-family")
    after = candidate["task"].read()
    assert after["worktree"]["branch"] == "feature/successor-local"
    assert after["pull_request_subject"]["source_branch"] != after["worktree"]["branch"]
    projection = json.loads((candidate["packet"] / "autodev.json").read_text())
    assert projection["stages"]["pr_create"]["status"] == "completed"
    assert projection["stages"]["review_self"]["status"] != "completed"
    assert projection["stages"]["qa"]["status"] != "completed"
    from test_opposing_model_review_runner import _load_runner
    from genomes_agentic_os.auto_dev_orchestration import AutoDevStateError
    runner = _load_runner()
    with pytest.raises(AutoDevStateError, match="outside this Auto-Dev workflow boundary"):
        runner.successor_request(candidate["packet"], current["ticket"], candidate["candidate"])
    # Widen only through the existing native named-stage resume, retaining the
    # original task/portfolio and current binding rather than editing a window.
    original_run_policy = candidate["task"].path.parents[2] / "effective-policies.json"
    run_policy_raw = original_run_policy.read_bytes()
    resumed = delivery.start_development_run(candidate["root"], "acme", "app", [current["ticket"]],
        run_id=before["run_id"], requested_stage="review_self", provision_worktree=False, apply=True)
    resumed_task = candidate["task"].read()
    assert resumed["tasks"][0]["state_ref"] == str(candidate["task"].path)
    assert original_run_policy.read_bytes() == run_policy_raw
    for key in binding.BINDING_FIELDS:
        assert resumed_task[key] == current[key]
    source = runner.successor_request(candidate["packet"], current["ticket"], candidate["candidate"])
    assert source["mode"] == "post_pr"
    assert source["policy_fingerprint"] == current["policy_fingerprint"]
    assert source["base_sha"] == candidate["provider"]["base_sha"]
    assert source["head_sha"] == head
    assert source["local_source_branch"] != source["provider_source_branch"]
    assert _bind(candidate)["status"] == "bound"


def test_intent_only_crash_reuses_exact_immutable_receipt(candidate: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """A pre-CAS failure leaves old authority intact and reuses the inert intent on retry."""
    before = candidate["task"].path.read_bytes()
    original = binding._commit_task
    def fail_commit(*_args: Any, **_kwargs: Any) -> None:
        """Inject a storage failure at the sole authoritative commit boundary."""
        raise OSError("synthetic task-replace failure")
    monkeypatch.setattr(binding, "_commit_task", fail_commit)
    with pytest.raises(OSError, match="task-replace"):
        _bind(candidate)
    assert candidate["task"].path.read_bytes() == before
    receipts = list((candidate["packet"] / "artifacts/development-delivery/successor-bindings").glob("*/receipt.json"))
    assert len(receipts) == 1
    raw = receipts[0].read_bytes()
    monkeypatch.setattr(binding, "_commit_task", original)
    assert _bind(candidate)["status"] == "bound_validation_pending"
    assert receipts[0].read_bytes() == raw


def test_changed_shared_attempt_inventory_is_not_a_free_budget(candidate: dict[str, Any]) -> None:
    """A concurrently recorded shared attempt invalidates the original request without rewriting it."""
    before = candidate["task"].path.read_bytes()
    root = Path(candidate["observation"]["coordinator"]["root"])
    attempt = root / "attempts/new-terminal-attempt.json"
    _write(attempt, {"schema": "synthetic-native-fixture-attempt/v1", "outcome": "unavailable"})
    attempt_raw = attempt.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="lineage"):
        _bind(candidate)
    assert candidate["task"].path.read_bytes() == before
    assert attempt.read_bytes() == attempt_raw


def test_protected_dirty_predecessor_is_preserved_and_drift_rejected(candidate: dict[str, Any]) -> None:
    """The transition never cleans the original checkout or ignores newly changed tracked bytes."""
    path = candidate["worktree"] / "README.md"
    path.write_text("predecessor owner changed this file\n")
    raw = path.read_bytes()
    before = candidate["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="source/runtime/policy/lineage"):
        _bind(candidate)
    assert path.read_bytes() == raw
    assert candidate["task"].path.read_bytes() == before


def test_real_review_family_lock_is_nonblocking(candidate: dict[str, Any]) -> None:
    """An in-flight shared family claim prevents binding instead of consuming or resetting it."""
    import fcntl
    root = Path(candidate["observation"]["coordinator"]["root"])
    lock = root / ".locks" / (candidate["observation"]["coordinator"]["family_key"] + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    before = candidate["task"].path.read_bytes()
    with lock.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            with pytest.raises(delivery.DevelopmentDeliveryError, match="review is active"):
                _bind(candidate)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    assert candidate["task"].path.read_bytes() == before


@pytest.mark.parametrize("kind", ["commands", "source_scope", "source_order", "coverage_control"])
def test_real_policy_weakening_and_selector_loss_reject(candidate: dict[str, Any], kind: str) -> None:
    """Native validated snapshots cannot lose commands, source precedence or safety controls."""
    old = candidate["observation"]["policy"]
    new = deepcopy(old)
    if kind == "commands":
        new["selected_profile"]["validation"]["commands"] = []
        value = {k: v for k, v in new["selected_profile"].items() if k != "sha256"}
        new["selected_profile"]["sha256"] = admission.digest(value)
    else:
        plane = new["planes"]["dev_standards"]
        if kind == "source_scope":
            plane["sources"][0]["scope"] = "foreign"
        elif kind == "source_order":
            plane["sources"].reverse()
        else:
            source = next(row for row in plane["sources"] if "required" in row.get("body_markdown", "").lower())
            source["body_markdown"] = ""
            source["sha256"] = "a" * 64
        plane["fingerprint"] = admission.digest([{k: row[k] for k in ("scope", "rank", "source_ref", "sha256")}
                                                 for row in plane["sources"]])
        plane["content_sha256"] = admission.digest({k: v for k, v in plane.items() if k != "content_sha256"})
    new["fingerprint"] = delivery._effective_policy_snapshot_fingerprint(new)
    with pytest.raises(delivery.DevelopmentDeliveryError):
        admission.policy_delta(old, new)


def test_current_binding_rejects_attempt_reset_and_missing_policy(candidate: dict[str, Any]) -> None:
    """Native readers enforce preserved history and the immutable new policy, not caller flags."""
    _bind(candidate)
    state = json.loads(candidate["task"].path.read_text())
    state["max_attempts"] = int(state["max_attempts"]) + 1
    with pytest.raises(delivery.DevelopmentDeliveryError, match="retry authority"):
        binding.active_binding(state)
    state = json.loads(candidate["task"].path.read_text())
    policy = Path(state["policy_receipt"])
    policy.write_text("{}\n")
    with pytest.raises(delivery.DevelopmentDeliveryError, match="digest"):
        candidate["task"].read()


def test_final_projection_crash_fails_closed_until_exact_replay(candidate: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """The final cross-file status window is also fenced; a model heartbeat is unnecessary."""
    original = binding._sync_auto_dev_projection
    calls = 0
    def fail_final(path: Path) -> dict[str, Any] | None:
        """Fail only after the canonical state has its final binding status."""
        nonlocal calls
        calls += 1
        return None if calls == 2 else original(path)
    monkeypatch.setattr(binding, "_sync_auto_dev_projection", fail_final)
    with pytest.raises(delivery.DevelopmentDeliveryError, match="final Auto-Dev"):
        _bind(candidate)
    with pytest.raises(delivery.DevelopmentDeliveryError, match="projection fence"):
        candidate["task"].read()
    monkeypatch.setattr(binding, "_sync_auto_dev_projection", original)
    assert _bind(candidate)["replayed"] is True
    assert candidate["task"].read()["active_successor_binding"]["status"] == "bound_validation_pending"


def test_real_second_process_lease_change_invalidates_planned_predecessor(candidate: dict[str, Any]) -> None:
    """A separate native owner changes the locked task after planning; CAS preserves its lease."""
    _bind(candidate, apply=False)
    command = [sys.executable, "-c", (
        "from pathlib import Path; from genomes_agentic_os.development_delivery import TaskState; "
        "TaskState(Path(__import__('sys').argv[1])).heartbeat(owner='second-process-owner', "
        "lease_minutes=7, idempotency_key='real-concurrent-lease')"), str(candidate["task"].path)]
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
    actual = candidate["task"].path.read_bytes()
    assert json.loads(actual)["lease"]["owner"] == "second-process-owner"
    with pytest.raises(delivery.DevelopmentDeliveryError, match="stale"):
        _bind(candidate)
    assert candidate["task"].path.read_bytes() == actual
    events = [json.loads(line) for line in candidate["task"].ledger.read_text().splitlines()]
    assert not any(row["type"] == "development.successor.bound" for row in events)


def test_equal_tree_orphan_cannot_substitute_for_source_ancestry(candidate: dict[str, Any]) -> None:
    """Real equal-tree commit objects and remote equality cannot manufacture an ancestor."""
    tree = candidate["candidate"]
    original = _git("rev-parse", "HEAD", cwd=tree)
    orphan = _git("commit-tree", original + "^{tree}", "-m", "same tree without any source parents", cwd=tree)
    _git("reset", "--hard", orphan, cwd=tree)
    _git("push", "--force", str(candidate["remote"]), "HEAD:refs/heads/" + candidate["provider"]["source_branch"], cwd=tree)
    candidate["provider"]["head"] = orphan
    assert _git("rev-parse", original + "^{tree}", cwd=tree) == _git("rev-parse", orphan + "^{tree}", cwd=tree)
    before = candidate["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="native observation failed"):
        _renew_assertions(candidate)
    assert candidate["task"].path.read_bytes() == before


def test_native_binding_does_not_reset_an_exhausted_shared_full_review_budget(candidate: dict[str, Any]) -> None:
    """Real shared coordinator receipts survive the binding and still deny the next paid callback."""
    from genomes_agentic_os.review_coordination import (
        ReviewBudgetExceeded, ReviewCoordinator, ReviewSubject, shared_review_coordination_root,
    )
    coordinator = ReviewCoordinator(shared_review_coordination_root(candidate["root"]))
    for index in (1, 2):
        subject = ReviewSubject("acme/app", "github:acme/app#236", "main", candidate["old_head"],
                                str(index) * 40, str(index) * 64)
        coordinator.execute(subject, lambda: {"outcome": "clean", "findings": []})
    observed = _renew_assertions(candidate)
    before = observed["coordinator"]
    _bind(candidate)
    after = admission.coordinator_inventory(candidate["root"], subject)
    assert after == before
    calls: list[str] = []
    with pytest.raises(ReviewBudgetExceeded, match="full-review budget"):
        coordinator.execute(ReviewSubject("acme/app", "github:acme/app#236", "main", candidate["old_head"],
            "3" * 40, "3" * 64), lambda: calls.append("must-not-purchase") or {"outcome": "clean", "findings": []})
    assert calls == []


@pytest.mark.parametrize("effect", ["event", "portfolio", "sqlite", "active_projection"])
def test_each_committed_projection_effect_replays_without_duplicate_history(
    candidate: dict[str, Any], monkeypatch: pytest.MonkeyPatch, effect: str,
) -> None:
    """Fail after a genuine native effect; exact-key replay resumes its own fenced outbox."""
    owner, name = {"event": (binding, "append_event"), "portfolio": (binding, "_atomic_json"),
        "sqlite": (work_items, "bind_development_successor"),
        "active_projection": (work_items, "write_active_projection")}[effect]
    native_effect = getattr(owner, name)
    def fail_after_effect(*args: Any, **kwargs: Any) -> Any:
        """Commit the real collaborator first, then simulate process interruption."""
        native_effect(*args, **kwargs)
        raise RuntimeError("injected after " + effect)
    monkeypatch.setattr(owner, name, fail_after_effect)
    with pytest.raises(RuntimeError, match="injected after"):
        _bind(candidate)
    assert json.loads(candidate["task"].path.read_text())["active_successor_binding"]["status"] == "projections_pending"
    with pytest.raises(delivery.DevelopmentDeliveryError, match="pending"):
        candidate["task"].read()
    monkeypatch.setattr(owner, name, native_effect)
    assert _bind(candidate)["replayed"] is True
    events = [json.loads(line) for line in candidate["task"].ledger.read_text().splitlines()]
    assert sum(row["type"] == "development.successor.bound" for row in events) == 1
    connection = connect(default_db_path(candidate["root"]))
    try:
        count = connection.execute("SELECT count(*) FROM work_item_history WHERE work_item_id = ? "
            "AND actor = 'development-successor-binding'", (candidate["task"].read()["canonical_work_id"],)).fetchone()[0]
        assert count == 1
    finally:
        connection.close()


@pytest.mark.parametrize("proof_name", ["accepted_request", "policy_delta_admission", "shared_review_lineage"])
def test_current_reader_rejects_tampered_immutable_binding_proofs(candidate: dict[str, Any], proof_name: str) -> None:
    """Accepted request, policy admission and shared budget proof are immutable history too."""
    _bind(candidate)
    current = candidate["task"].read()
    receipt = binding.active_binding(current)
    target = candidate["packet"] / receipt["proofs"][proof_name]["packet_ref"]
    target.write_text("{}\n")
    with pytest.raises(delivery.DevelopmentDeliveryError, match="digest"):
        candidate["task"].read()


def test_policy_review_invalid_input_is_pre_admission_refusal(candidate: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
                                                             capsys: pytest.CaptureFixture[str]) -> None:
    """The real runner handles an invalid capsule before native provider/model/budget calls."""
    from test_opposing_model_review_runner import _load_runner
    runner = _load_runner()
    request = json.loads(candidate["binding_request"].read_text())
    request["waive_coverage"] = True
    _write(candidate["binding_request"], request)
    monkeypatch.setattr(sys, "argv", ["run_opposing_model_review.py", candidate["task"].read()["ticket"],
        "--os-root", str(candidate["root"]), "--work-item", str(candidate["packet"]),
        "--worktree", str(candidate["candidate"]), "--successor-policy-request", str(candidate["binding_request"])])
    assert runner.main() == 2
    assert "closed schema" in json.loads(capsys.readouterr().out)["error"]
    assert not Path(candidate["observation"]["coordinator"]["root"]).joinpath("attempts").exists()


@pytest.mark.parametrize("candidate", ["readiness"], indirect=True)
def test_native_readiness_start_keeps_the_original_window_without_invented_early_credit(candidate: dict[str, Any]) -> None:
    """A genuine native Readiness-start task keeps its original exclusions and pending fresh gates."""
    before = candidate["task"].read()
    manifest = json.loads((candidate["packet"] / "autodev.json").read_text())
    assert before["auto_dev_start_stage"] == "readiness"
    assert before["auto_dev_mode"] == "default"
    with pytest.raises(delivery.DevelopmentDeliveryError, match="modern groom-through-PR-Create boundary"):
        refresh_development_validation(candidate["task"].path, evidence_file=candidate["request"],
                                       idempotency_key="unbound-readiness-has-no-successor-exception")
    for name in ("groom", "detective", "create_artifacts"):
        assert manifest["stages"][name]["status"] == "out_of_scope"
    _bind(candidate)
    current = candidate["task"].read()
    for key in ("auto_dev_mode", "auto_dev_start_stage", "auto_dev_end_stage", "requested_stage", "goal", "receipts"):
        assert current.get(key) == before.get(key)
    projected = json.loads((candidate["packet"] / "autodev.json").read_text())
    for name in ("groom", "detective", "create_artifacts"):
        assert projected["stages"][name]["status"] == "out_of_scope"
    assert projected["stages"]["readiness"] == manifest["stages"]["readiness"]
    assert projected["stages"]["develop"]["status"] == "not_started"
    assert projected["stages"]["pr_create"]["status"] == "not_started"
    with pytest.raises(ValueError, match="fresh native validation"):
        require_auto_dev_predecessors(candidate["packet"], "finalize")
