"""Actual writer/CLI/projection conformance with test-owned governed execution."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import uuid

import pytest
import yaml

from genomes_agentic_os import development_delivery as delivery
from genomes_agentic_os import development_validation_reconciliation as reconciliation
from genomes_agentic_os import development_validation_refresh as refresh
from genomes_agentic_os.auto_dev_orchestration import require_auto_dev_predecessors
from genomes_agentic_os.cli import main
from test_development_delivery import _canonical_delivery_row, _git, _stage_receipt, _record_standalone_stage
from test_development_validation_refresh import _bound, _command_proof, _document, _family, _fixture, _now, _write


def _digest(value):
    return hashlib.sha256(reconciliation._bytes(value)).hexdigest()


@pytest.mark.parametrize("stale_kind", ["lease", "proof", "owner", "head", "profile"])
def test_stale_authority_does_not_break_lifecycle_audit_or_grant_actions(
    tmp_path, monkeypatch, stale_kind
):
    from datetime import datetime, timedelta
    from genomes_agentic_os.auto_dev_orchestration import sync_delivery_projection

    case = _case(tmp_path)
    plan_path, _ = _plan(case)
    _apply(case, plan_path)
    task = case["task"]
    original = task.read()
    historical_files = {
        name: Path(name).read_bytes() for name in case["inspected"]["historical_files"]
    }
    budget = reconciliation._budget_history(original)
    if stale_kind in {"lease", "owner"}:
        stale = task.read()
        if stale_kind == "lease":
            stale["lease"]["until"] = "2000-01-01T00:00:00Z"
        else:
            stale["lease"]["owner"] = "test-successor-owner"
        _write(task.path, stale)
    elif stale_kind == "proof":
        class ExpiredProofClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.now(tz) + timedelta(hours=2)

        monkeypatch.setattr(reconciliation, "datetime", ExpiredProofClock)
    elif stale_kind == "head":
        (case["receiving"] / "README.md").write_text("unqualified source repair\n")
        _git("add", "README.md", cwd=case["receiving"])
        _git("commit", "-m", "unqualified source repair", cwd=case["receiving"])
    else:
        configuration = (
            delivery.project_root(case["root"], "acme", "app")
            / "config/development.yml"
        )
        configuration.write_text(configuration.read_text() + "\n# current policy changed\n")

    for action in ("pr_create", "review"):
        with pytest.raises(delivery.DevelopmentDeliveryError):
            reconciliation.current_action_validation_authority(task.path, action=action)

    if stale_kind == "lease":
        assert task.recover_stale_lease() == {
            "recovered": True, "reason": "lease_expired"
        }
        failure_detail = "worker heartbeat lease expired"
    else:
        failure_detail = "test-owned failure while current authority is stale"
        task.fail(
            kind="test_failed", detail=failure_detail,
            receipt="test-owned lifecycle failure", idempotency_key="stale-failure",
        )
    failed = task.read()
    assert failed["failure"]["recoverable"] is True
    assert failed["state"] == "local_validation"
    projected_failure = _canonical_delivery_row(case["root"], task)
    assert projected_failure["state"] == "validating"
    assert projected_failure["attention"] == "active"
    assert projected_failure["blocked_reason"] == failure_detail
    assert projected_failure["worktree_path"] == original["worktree"]["path"]
    task.recover(receipt="test-owned recovery", idempotency_key="stale-recovery")
    assert task.read()["state"] == "local_validation"
    assert task.read()["failure"] is None
    recovered = _canonical_delivery_row(case["root"], task)
    assert recovered["attention"] == "active"
    assert recovered["state"] == "validating"
    assert recovered["blocked_reason"] is None
    task.transition(
        "pre_pr_review", receipt=_stage_receipt(case["packet"], "pre_pr_review"),
        idempotency_key="stale-lifecycle-transition",
    )
    assert task.read()["state"] == "pre_pr_review"
    current = sync_delivery_projection(task.path)
    assert current["delivery"]["current_action_status"]["status"] == "unqualified_current_evidence"
    assert "current_action_authority" not in current["delivery"]
    for action in ("pr_create", "review"):
        with pytest.raises(delivery.DevelopmentDeliveryError):
            reconciliation.current_action_validation_authority(task.path, action=action)
    assert task.read()["receipts"][:len(original["receipts"])] == original["receipts"]
    assert task.read()[reconciliation.HISTORY] == original[reconciliation.HISTORY]
    assert reconciliation._budget_history(task.read()) == budget
    assert all(Path(name).read_bytes() == content for name, content in historical_files.items())
    events = [json.loads(line) for line in task.ledger.read_text().splitlines()]
    assert any(row["type"] == "development.task.failed" for row in events)
    assert any(row["type"] == "development.task.recovered" for row in events)


@pytest.mark.parametrize("consumer", ["pull_request", "develop_binding"])
def test_stale_reconciliation_consumers_preserve_orchestration_error_contract(
    tmp_path, consumer
):
    from genomes_agentic_os.auto_dev_orchestration import (
        AutoDevStateError,
        validate_pull_request_authority,
    )

    case = _case(tmp_path)
    plan_path, _ = _plan(case)
    _apply(case, plan_path)
    _document(case)
    require_auto_dev_predecessors(case["packet"] / "autodev.json", "pr_create")
    stale = case["task"].read()
    stale["lease"]["until"] = "2000-01-01T00:00:00Z"
    _write(case["task"].path, stale)
    before = case["task"].path.read_bytes()
    events = case["task"].ledger.read_bytes()
    with pytest.raises(AutoDevStateError, match="owner/lease"):
        if consumer == "pull_request":
            validate_pull_request_authority(stale, {}, "pre_pr_review")
        else:
            require_auto_dev_predecessors(
                case["packet"] / "autodev.json", "pr_create"
            )
    assert case["task"].path.read_bytes() == before
    assert case["task"].ledger.read_bytes() == events


@pytest.mark.parametrize("lineage", ["rewound", "unrelated"])
def test_nonancestor_source_has_governance_diagnostic_without_task_writes(
    tmp_path, lineage
):
    case = _case(tmp_path)
    if lineage == "rewound":
        (case["worktree"] / "README.md").write_text("historical checkout advanced\n")
        _git("add", "README.md", cwd=case["worktree"])
        _git("commit", "-m", "advance original checkout", cwd=case["worktree"])
    else:
        branch = "feature/test-unrelated-source"
        _git("checkout", "--orphan", branch, cwd=case["receiving"])
        _git("commit", "-m", "independent source history", cwd=case["receiving"])
        request = json.loads(case["reconciliation_request"].read_text())
        request["worktree"]["branch"] = branch
        _write(case["reconciliation_request"], request)
    before = case["task"].path.read_bytes()
    events = case["task"].ledger.read_bytes()
    with pytest.raises(
        delivery.DevelopmentDeliveryError,
        match="current source must descend from the original historical worktree head",
    ):
        _plan(case, "nonancestor")
    assert case["task"].path.read_bytes() == before
    assert case["task"].ledger.read_bytes() == events


@pytest.mark.parametrize("unavailable", ["missing_commit", "missing_worktree"])
def test_ancestry_git_failure_retains_availability_diagnostic(tmp_path, unavailable):
    case = _case(tmp_path)
    with pytest.raises(
        delivery.DevelopmentDeliveryError, match="Git identity is unavailable"
    ):
        reconciliation._require_source_ancestor(
            case["receiving"] if unavailable == "missing_commit" else tmp_path / "absent",
            "0" * 40 if unavailable == "missing_commit" else case["head"],
            case["head"],
        )



@pytest.fixture(autouse=True)
def isolated_controller_environment(monkeypatch):
    # No inherited live Fabric file or canonical-root redirect may reach a
    # temporary fixture's real controller/owning projection writers.
    monkeypatch.delenv("FABRIC_RUNTIME_ENV_FILE", raising=False)
    monkeypatch.delenv("AGENTIC_OS_ROOT", raising=False)


def _case(tmp_path, *, adapter=True, implicit_repository=False, mode="single_stage", actions=("pr_create", "review")):
    case = _fixture(tmp_path, legacy=True, mode=mode)
    task = case["task"]
    current = task.read()
    predecessor = json.loads(case["predecessor"].read_text())
    predecessor.pop("stage", None)  # Retain the actual pre-modern schema gap.
    _write(case["predecessor"], predecessor)
    for row in current["receipts"]:
        if row.get("ref") == str(case["predecessor"]):
            row["sha256"] = _bound(case["predecessor"])["sha256"]
    # Build a deterministic ten-receipt historical fixture before freezing it.
    while len(current["receipts"]) < 10:
        receipt = Path(_stage_receipt(case["packet"], "context_ready", evidence={"historical_fixture": len(current["receipts"])}))
        # The helper uses one filename; give each original receipt its own body.
        owned = case["packet"] / "artifacts" / ("historical-" + str(len(current["receipts"])) + ".json")
        owned.write_bytes(receipt.read_bytes())
        current["receipts"].append({"state": "context_ready", "ref": str(owned), "sha256": _bound(owned)["sha256"], "recorded_at": _now()})
    current["lease"] = {"owner": "test-reconciliation-owner", "until": "2099-01-01T00:00:00Z"}
    _write(task.path, current)
    project = delivery.project_root(current["os_root"], current["domain"], current["project"])
    config = project / "config/development.yml"
    profile = yaml.safe_load(config.read_text())
    if implicit_repository:
        profile["repository"].pop("id")
    if adapter:
        profile["validation"]["reconciliation"] = {"adapter": reconciliation.COMMAND_ADAPTER,
            "actions": list(actions), "max_age_seconds": 3600, "claims": ["configured_commands_only"]}
    config.write_text(yaml.safe_dump(profile))
    receiving = tmp_path / "receiving"
    branch = "feature/test-current-validation-" + uuid.uuid4().hex[:8]
    _git("worktree", "add", "-b", branch, str(receiving), case["head"], cwd=case["worktree"])
    (receiving / "README.md").write_text("current independently selected source\n")
    _git("add", "README.md", cwd=receiving)
    _git("commit", "-m", "current source", cwd=receiving)
    delivery.register_project_worktree(case["root"], "acme", "app", "current-validation", path=receiving)
    registered_names = {row.get("id") or row.get("name") for row in delivery.worktree_entries_for_project(project)
                        if Path(row["path"]).resolve() == receiving.resolve()}
    assert len(registered_names) == 1
    record = {"name": registered_names.pop(), "path": str(receiving), "branch": branch, "repository_id": current["repository"]["id"]}
    inspected = reconciliation.inspect_development_reconciliation(task.path)
    policy = inspected["current_policy"]
    head = _git("rev-parse", "HEAD", cwd=receiving)
    proof = {"schema": reconciliation.PROOF_SCHEMA, "adapter": reconciliation.COMMAND_ADAPTER,
        "claims": ["configured_commands_only"], "task_state_ref": str(task.path),
        "canonical_work_id": current["canonical_work_id"], "ticket": current["ticket"], "run_id": current["run_id"],
        "repository_id": current["repository"]["id"], "worktree": str(receiving), "source_branch": branch,
        "head_sha": head, "tree_sha": _git("rev-parse", "HEAD^{tree}", cwd=receiving),
        "policy_fingerprint": policy["fingerprint"], "policy_sha256": inspected["current_policy_sha256"],
        "profile_sha256": inspected["current_profile_sha256"],
        "validation_runs": [_command_proof(case["root"], case["packet"], receiving, case["command"], head, policy["fingerprint"])],
        "verified_at": _now()}
    proof_path = _write(case["packet"] / "artifacts/current-project-proof.json", proof)
    request = {"schema": "development-validation-reconciliation-request/v1", "predecessor_sha256": _bound(task.path)["sha256"],
        "owner": current["lease"]["owner"], "worktree": record, "current_policy_fingerprint": policy["fingerprint"],
        "project_proof": _bound(proof_path), "historical_files_sha256": _digest(inspected["historical_files"]),
        "review_history_sha256": _digest(inspected["review_history"])}
    case.update(current=current, receiving=receiving, current_record=record, policy=policy, head=head,
        proof=proof, proof_path=proof_path, reconciliation_request=_write(case["packet"] / "artifacts/reconciliation-request.json", request),
        original_task=task.path.read_bytes(), original_events=task.ledger.read_bytes(), inspected=inspected)
    return case


def _plan(case, key="current-validation"):
    plan = reconciliation.plan_development_reconciliation(case["task"].path,
        request_file=case["reconciliation_request"], idempotency_key=key)
    path = _write(case["packet"] / "artifacts" / (key + "-plan.json"), plan)
    return path, plan


def _apply(case, path, *, execute=True):
    return reconciliation.apply_development_reconciliation(case["task"].path, plan_file=path,
        plan_sha256=_bound(path)["sha256"], execute=execute)


def test_real_cli_apply_and_consumers_preserve_ten_receipts_and_policy(tmp_path, capsys):
    case = _case(tmp_path)
    before = case["task"].read()
    original_receipts = {path: Path(path).read_bytes() for path in case["inspected"]["historical_files"]}
    assert len(before["receipts"]) == 10
    path, plan = _plan(case)
    assert case["task"].path.read_bytes() == case["original_task"]
    assert _apply(case, path, execute=False)["applied"] is False
    assert main(["develop", "reconcile-validation", "inspect", str(case["task"].path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["authority_adopted"] is False
    assert main(["develop", "reconcile-validation", "apply", str(case["task"].path), "--plan", str(path),
                 "--plan-sha256", _bound(path)["sha256"], "--execute", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    after = case["task"].read()
    assert result["applied"] and not result["replayed"]
    assert after["state"] == before["state"] == "local_validation"
    assert after["receipts"][:10] == before["receipts"]
    assert all(after.get(key) == before.get(key) for key in reconciliation.IMMUTABLE_FIELDS)
    assert all(Path(path).read_bytes() == raw for path, raw in original_receipts.items())
    assert case["task"].ledger.read_bytes().startswith(case["original_events"])
    assert "stage" not in json.loads(case["predecessor"].read_text())
    projection = json.loads((case["packet"] / "autodev.json").read_text())
    authority = result["current_action_authority"]
    assert projection["delivery"]["policy_fingerprint"] == before["policy_fingerprint"]
    assert projection["delivery"]["worktree"] == before["worktree"]
    assert projection["delivery"]["current_action_authority"] == authority
    assert authority["head_sha"] == case["head"] and authority["worktree"] == case["current_record"]
    assert authority["policy_fingerprint"] != before["policy_fingerprint"]
    assert authority["qualification"]["native_full95_qualified"] is False
    assert projection["stages"]["develop"]["receipt_refs"] == [authority["path"]]
    view = reconciliation.current_action_task_view(after, action="review")
    assert view["worktree"] == case["current_record"] and case["task"].read()["worktree"] == before["worktree"]
    substituted = deepcopy(after)
    substituted["repository"]["id"] = "git:github.com/acme/unrelated"
    with pytest.raises(delivery.DevelopmentDeliveryError, match="substituted mapping"):
        reconciliation.current_action_task_view(substituted, action="review")
    _document(case)
    require_auto_dev_predecessors(case["packet"] / "autodev.json", "pr_create")
    family = {"evidence": {"ticket": before["ticket"], "repository": "acme/app", "source_head_sha": case["head"],
             "source_branch": case["current_record"]["branch"], "policy_fingerprint": case["policy"]["fingerprint"]}}
    assert refresh.pr_create_validation_authority(case["task"].path, family)["head_sha"] == case["head"]
    family["evidence"]["policy_fingerprint"] = before["policy_fingerprint"]
    with pytest.raises(delivery.DevelopmentDeliveryError, match="PR family"):
        refresh.pr_create_validation_authority(case["task"].path, family)
    events = case["task"].ledger.read_bytes()
    budget = reconciliation._budget_history(after)
    assert _apply(case, path)["replayed"] is True
    assert case["task"].ledger.read_bytes() == events
    assert reconciliation._budget_history(after) == budget


def test_review_only_cli_apply_and_replay_project_source_without_granting_pr_create(tmp_path, capsys):
    case = _case(tmp_path, actions=("review",))
    before = case["task"].read()
    original = {path: Path(path).read_bytes() for path in case["inspected"]["historical_files"]}
    path, _ = _plan(case, "review-only")
    arguments = ["develop", "reconcile-validation", "apply", str(case["task"].path), "--plan", str(path),
        "--plan-sha256", _bound(path)["sha256"], "--execute", "--json"]
    assert main(arguments) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["applied"] and not first["replayed"]
    assert first["current_action_authority"]["qualification"]["actions"] == ["review"]
    canonical = _canonical_delivery_row(case["root"], case["task"])
    assert Path(canonical["worktree_path"]) == case["receiving"]
    assert canonical["branch"] == case["current_record"]["branch"]
    assert reconciliation.current_action_task_view(case["task"].read(), action="review")["worktree"] == case["current_record"]
    events = case["task"].ledger.read_bytes()
    budget = reconciliation._budget_history(case["task"].read())
    with pytest.raises(delivery.DevelopmentDeliveryError, match="does not authorize this action"):
        refresh.pr_create_validation_authority(case["task"].path, {"evidence": {}})
    assert main(arguments) == 0
    assert json.loads(capsys.readouterr().out)["replayed"]
    assert case["task"].ledger.read_bytes() == events
    assert reconciliation._budget_history(case["task"].read()) == budget
    assert case["task"].read()["state"] == before["state"] == "local_validation"
    assert case["task"].read()["receipts"][:10] == before["receipts"]
    assert all(Path(path).read_bytes() == raw for path, raw in original.items())


@pytest.mark.parametrize("field", ["ticket", "run_id", "canonical_work_id", "repository_id", "task_state_ref", "worktree", "source_branch", "head_sha", "tree_sha", "policy_fingerprint", "policy_sha256", "profile_sha256"])
def test_substituted_current_proof_refuses_without_state_or_event_write(tmp_path, field):
    case = _case(tmp_path)
    proof = deepcopy(case["proof"])
    proof[field] = "substituted"
    _write(case["proof_path"], proof)
    request = json.loads(case["reconciliation_request"].read_text())
    request["project_proof"] = _bound(case["proof_path"])
    _write(case["reconciliation_request"], request)
    with pytest.raises(delivery.DevelopmentDeliveryError, match="identity"):
        _plan(case)
    assert case["task"].path.read_bytes() == case["original_task"]
    assert case["task"].ledger.read_bytes() == case["original_events"]


@pytest.mark.parametrize("change", ["predecessor", "owner", "policy", "receipt_hash", "future", "stale", "unqualified_native", "passed_flag", "missing_commands"])
def test_unqualified_request_and_execution_cannot_confer_authority(tmp_path, change):
    case = _case(tmp_path)
    request = json.loads(case["reconciliation_request"].read_text())
    proof = deepcopy(case["proof"])
    if change in {"predecessor", "owner", "policy"}:
        request[{"predecessor": "predecessor_sha256", "owner": "owner", "policy": "current_policy_fingerprint"}[change]] = "wrong"
    elif change == "receipt_hash":
        proof["validation_runs"][0]["terminal"]["sha256"] = "0" * 64
    elif change in {"future", "stale"}:
        proof["verified_at"] = "2099-01-01T00:00:00Z" if change == "future" else "2000-01-01T00:00:00Z"
    elif change == "unqualified_native":
        proof["claims"] = ["native_full95"]
    elif change == "passed_flag":
        proof = {"status": "passed", "full95": True}
    else:
        proof["validation_runs"] = []
    _write(case["proof_path"], proof)
    request["project_proof"] = _bound(case["proof_path"])
    _write(case["reconciliation_request"], request)
    with pytest.raises(delivery.DevelopmentDeliveryError):
        _plan(case)
    assert case["task"].path.read_bytes() == case["original_task"]
    assert case["task"].ledger.read_bytes() == case["original_events"]


@pytest.mark.parametrize("adapter", [None, "native-python-full95/v1"])
def test_separately_required_project_adapter_is_not_inferred(tmp_path, adapter):
    case = _case(tmp_path, adapter=adapter is not None)
    if adapter:
        config = delivery.project_root(case["root"], "acme", "app") / "config/development.yml"
        profile = yaml.safe_load(config.read_text())
        profile["validation"]["reconciliation"]["adapter"] = adapter
        config.write_text(yaml.safe_dump(profile))
        inspected = reconciliation.inspect_development_reconciliation(case["task"].path)
        request = json.loads(case["reconciliation_request"].read_text())
        request["current_policy_fingerprint"] = inspected["current_policy"]["fingerprint"]
        _write(case["reconciliation_request"], request)
    with pytest.raises(delivery.DevelopmentDeliveryError, match="adapter"):
        _plan(case)


def test_stale_apply_and_altered_historical_receipt_refuse(tmp_path):
    case = _case(tmp_path)
    path, _ = _plan(case)
    current = case["task"].read()
    current["lease"]["until"] = "2098-01-01T00:00:00Z"
    _write(case["task"].path, current)
    changed = case["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="stale"):
        _apply(case, path)
    assert case["task"].path.read_bytes() == changed
    case["task"].path.write_bytes(case["original_task"])
    case["predecessor"].write_bytes(case["predecessor"].read_bytes() + b" ")
    with pytest.raises(delivery.DevelopmentDeliveryError, match="historical"):
        _apply(case, path)
    assert case["task"].ledger.read_bytes() == case["original_events"]


def test_exact_concurrent_apply_emits_once_and_repairs_projection_failure(tmp_path, monkeypatch):
    case = _case(tmp_path)
    path, _ = _plan(case)
    real = delivery._sync_auto_dev_projection
    monkeypatch.setattr(delivery, "_sync_auto_dev_projection", lambda path: None)
    with pytest.raises(delivery.DevelopmentDeliveryError, match="projection"):
        _apply(case, path)
    monkeypatch.setattr(delivery, "_sync_auto_dev_projection", real)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: _apply(case, path), range(2)))
    assert all(result["replayed"] for result in results)
    events = [json.loads(line) for line in case["task"].ledger.read_text().splitlines()]
    assert sum(row["type"] == "development.validation.reconciled" for row in events) == 1
    assert len(case["task"].read()[reconciliation.HISTORY]) == 1
    assert json.loads((case["packet"] / "autodev.json").read_text())["delivery"]["current_action_authority"]["head_sha"] == case["head"]


def test_escaped_output_and_mutated_accepted_history_fail_closed(tmp_path):
    case = _case(tmp_path)
    path, plan = _plan(case)
    outside = tmp_path / "outside.json"
    outside.write_bytes(case["original_task"])
    target = case["packet"] / "artifacts/development-delivery/reconciliation" / ("original-task-" + plan["predecessor_sha256"] + ".json")
    target.parent.mkdir(parents=True)
    target.symlink_to(outside)
    with pytest.raises(delivery.DevelopmentDeliveryError, match="symlink"):
        _apply(case, path)
    assert case["task"].path.read_bytes() == case["original_task"]
    assert outside.read_bytes() == case["original_task"]
    target.unlink()  # Remove only the test-owned adversarial link.
    _apply(case, path)
    state = case["task"].read()
    state["receipts"][0]["recorded_at"] = "altered historical timestamp"
    _write(case["task"].path, state)
    with pytest.raises(delivery.DevelopmentDeliveryError, match="historical"):
        reconciliation.current_action_validation_authority(case["task"].path)


def _original_review(case, *, second=False, owner=None, pull_request=42, repository="acme/app"):
    from genomes_agentic_os.review_coordination import ReviewCoordinator, ReviewSubject, shared_review_coordination_root, stable_review_key
    owner = owner or case
    identity = owner["task"].read()
    coordinator = ReviewCoordinator(shared_review_coordination_root(case["root"]))
    subject = ReviewSubject(repository, "github:acme/app#" + str(pull_request), "main", "a" * 40,
                            ("2" if second else "1") * 40, ("d" if second else "c") * 64)
    key = stable_review_key(subject)
    directory = owner["packet"] / "artifacts/finishing-touches/review-runs" / key
    _write(directory / "review-request.json", {"run_id": key, "review_key": key,
        "work_item_id": identity["ticket"], "repository": repository, "pr_number": pull_request,
        "head_sha": subject.head_sha, "base_sha": subject.base_sha, "policy_fingerprint": subject.policy_fingerprint})
    # The real coordinator writes/charges a synthetic test-owned terminal
    # callback. This invokes no harness, model, provider or application reviewer.
    return coordinator.execute(subject, lambda: {"outcome": "clean", "response": "Synthetic fixture review",
        "ticket": identity["ticket"], "review_run_dir": str(directory)})


def _assert_budget_conserved(before, after):
    for key in ("root", "repository", "files", "charges", "limits", "family_owners", "task_families", "ambiguous_families", "family_subjects"):
        assert after[key] == before[key]
    assert all(after["scope_evidence_files"][path] == digest for path, digest in before["scope_evidence_files"].items())


def _rebind_inspected_budget(case):
    history = reconciliation.inspect_development_reconciliation(case["task"].path)["review_history"]
    request = json.loads(case["reconciliation_request"].read_text())
    request["review_history_sha256"] = _digest(history)
    _write(case["reconciliation_request"], request)
    return history


def test_original_review_charges_and_root_survive_adoption_and_replay(tmp_path):
    case = _case(tmp_path)
    receipt = _original_review(case)
    original_bytes = receipt.receipt_path.read_bytes()
    history = _rebind_inspected_budget(case)
    assert len(history["charges"]) == 1
    path, _ = _plan(case)
    result = _apply(case, path)
    assert result["current_action_authority"]["review_coordination_root"] == history["root"]
    _assert_budget_conserved(history, reconciliation._budget_history(case["task"].read()))
    assert _apply(case, path)["replayed"]
    assert receipt.receipt_path.read_bytes() == original_bytes
    _assert_budget_conserved(history, reconciliation._budget_history(case["task"].read()))
    receipt.receipt_path.unlink()  # Adversarial deletion in the temporary fixture only.
    with pytest.raises(delivery.DevelopmentDeliveryError, match="budget history"):
        reconciliation.current_action_validation_authority(case["task"].path)


def test_exhausted_budget_and_changed_original_review_refuse(tmp_path):
    case = _case(tmp_path)
    receipt = _original_review(case)
    _rebind_inspected_budget(case)
    path, _ = _plan(case)
    receipt.receipt_path.write_bytes(receipt.receipt_path.read_bytes() + b" ")
    with pytest.raises(delivery.DevelopmentDeliveryError, match="budget"):
        _apply(case, path)
    assert case["task"].path.read_bytes() == case["original_task"]
    _original_review(case, second=True)
    _rebind_inspected_budget(case)
    with pytest.raises(delivery.DevelopmentDeliveryError, match="budget.*exhausted"):
        _plan(case, "must-not-reset-budget")


def test_missing_event_is_repaired_once_and_removed_markers_cannot_restore_old_authority(tmp_path, monkeypatch):
    case = _case(tmp_path)
    path, _ = _plan(case)
    real = delivery.TaskState.emit
    def interrupted(self, **kwargs):
        raise OSError("test-owned event-write interruption")
    monkeypatch.setattr(delivery.TaskState, "emit", interrupted)
    with pytest.raises(OSError, match="interruption"):
        _apply(case, path)
    monkeypatch.setattr(delivery.TaskState, "emit", real)
    with pytest.raises(delivery.DevelopmentDeliveryError, match="event"):
        reconciliation.current_action_validation_authority(case["task"].path)
    assert _apply(case, path)["replayed"]
    accepted = case["task"].read()
    accepted.pop(reconciliation.HISTORY)
    accepted["receipts"] = [row for row in accepted["receipts"] if row.get("kind") != "validation_reconciliation"]
    _write(case["task"].path, accepted)
    with pytest.raises(delivery.DevelopmentDeliveryError, match="markers"):
        reconciliation.current_action_validation_authority(case["task"].path)


def test_cli_plan_output_is_new_artifact_and_wrong_plan_hash_refuses(tmp_path, capsys):
    case = _case(tmp_path)
    output = case["packet"] / "artifacts/cli-plan.json"
    assert main(["develop", "reconcile-validation", "plan", str(case["task"].path), "--request", str(case["reconciliation_request"]),
                 "--idempotency-key", "cli-current", "--output", str(output), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["schema"] == reconciliation.PLAN_SCHEMA
    assert case["task"].path.read_bytes() == case["original_task"]
    with pytest.raises(delivery.DevelopmentDeliveryError, match="SHA-256"):
        reconciliation.apply_development_reconciliation(case["task"].path, plan_file=output, plan_sha256="0" * 64, execute=True)
    outside = tmp_path / "outside-plan.json"
    assert main(["develop", "reconcile-validation", "plan", str(case["task"].path), "--request", str(case["reconciliation_request"]),
                 "--idempotency-key", "escape", "--output", str(outside), "--json"]) == 2
    assert not outside.exists()
    link = case["packet"] / "artifacts/symlink-plan.json"
    link.symlink_to(outside)
    assert main(["develop", "reconcile-validation", "plan", str(case["task"].path), "--request", str(case["reconciliation_request"]),
                 "--idempotency-key", "escape", "--output", str(link), "--json"]) == 2
    assert not outside.exists() and case["task"].path.read_bytes() == case["original_task"]


def test_implicit_repository_identity_uses_the_canonical_remote_normalization(tmp_path):
    case = _case(tmp_path, implicit_repository=True)
    assert case["policy"]["selected_profile"]["repository_id"] == case["current"]["repository"]["id"]
    path, _ = _plan(case)
    assert _apply(case, path)["current_action_authority"]["repository_id"] == case["current"]["repository"]["id"]


def test_historical_refresh_cannot_replace_accepted_current_authority(tmp_path):
    case = _case(tmp_path)
    path, _ = _plan(case)
    _apply(case, path)
    before = case["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="historical validation subject"):
        refresh.refresh_development_validation(case["task"].path, evidence_file=case["request"], idempotency_key="old-writer")
    assert case["task"].path.read_bytes() == before


@pytest.mark.parametrize("ledger", ["task", "rollup"])
def test_an_existing_event_key_cannot_be_adopted_for_reconciliation(tmp_path, ledger):
    case = _case(tmp_path)
    path = case["task"].ledger if ledger == "task" else Path(case["current"]["rollup_ledger"])
    delivery.append_event(path, event_type="historical.fixture", idempotency_key="already-used", payload={"synthetic": True})
    events = path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="existing event"):
        _plan(case, "already-used")
    assert case["task"].path.read_bytes() == case["original_task"] and path.read_bytes() == events


@pytest.mark.parametrize("drift", ["source", "policy", "proof", "predecessor"])
def test_final_apply_check_refuses_real_drift_during_snapshot_storage(tmp_path, monkeypatch, drift):
    case = _case(tmp_path)
    path, _ = _plan(case)
    real_snapshot = reconciliation._snapshot
    def store_then_change(packet, name, raw):
        stored = real_snapshot(packet, name, raw)
        if name.startswith("validation-"):
            if drift == "source":
                (case["receiving"] / "README.md").write_text("concurrent source change\n")
                _git("add", "README.md", cwd=case["receiving"])
                _git("commit", "-m", "concurrent source", cwd=case["receiving"])
            elif drift == "policy":
                config = delivery.project_root(case["root"], "acme", "app") / "config/development.yml"
                config.write_text(config.read_text() + "\n# independently changed policy\n")
            elif drift == "proof":
                case["proof_path"].write_bytes(case["proof_path"].read_bytes() + b" ")
            else:
                changed = case["task"].read()
                changed["lease"]["owner"] = "concurrent-owner"
                _write(case["task"].path, changed)
        return stored
    # Interleave an actual test-owned writer at the storage collaborator, not
    # a fabricated passing validator or substituted command/terminal result.
    monkeypatch.setattr(reconciliation, "_snapshot", store_then_change)
    with pytest.raises(delivery.DevelopmentDeliveryError):
        _apply(case, path)
    assert not case["task"].read().get(reconciliation.HISTORY)
    assert case["task"].ledger.read_bytes() == case["original_events"]


def test_plan_refuses_source_that_changes_after_real_command_verification(tmp_path, monkeypatch):
    case = _case(tmp_path)
    real_commands = reconciliation._commands
    changed = False
    def verify_then_change(*args):
        nonlocal changed
        real_commands(*args)
        if not changed:
            changed = True
            (case["receiving"] / "README.md").write_text("concurrent planned source\n")
            _git("add", "README.md", cwd=case["receiving"])
            _git("commit", "-m", "concurrent planned source", cwd=case["receiving"])
    monkeypatch.setattr(reconciliation, "_commands", verify_then_change)
    with pytest.raises(delivery.DevelopmentDeliveryError, match="source/policy/profile changed"):
        _plan(case)
    assert case["task"].path.read_bytes() == case["original_task"]


def test_real_pr_create_writer_records_explicit_reconciliation_authority(tmp_path):
    case = _case(tmp_path)
    path, _ = _plan(case)
    _apply(case, path)
    _document(case)
    receipt = Path(_family(case))
    family = json.loads(receipt.read_text())
    family["evidence"].update(policy_fingerprint=case["policy"]["fingerprint"], source_branch=case["current_record"]["branch"])
    _write(receipt, family)
    delivery.run_development_stage(case["task"].path, stage="release_propagation",
        receipts={"release_propagation": str(receipt)}, idempotency_prefix="current-family")
    wrapper = json.loads((case["task"].path.parent / "stages/release-propagation.json").read_text())
    assert wrapper["validation_authority"]["head_sha"] == case["head"]
    assert wrapper["validation_authority"]["policy_fingerprint"] == case["policy"]["fingerprint"]
    current = case["task"].read()
    assert current["policy_fingerprint"] == case["current"]["policy_fingerprint"]
    assert current["receipts"][:10] == case["current"]["receipts"]


def test_real_review_entrypoint_consumes_current_policy_and_preserves_prior_request(tmp_path, monkeypatch, capsys):
    from test_opposing_model_review_runner import _load_runner
    case = _case(tmp_path)
    path, _ = _plan(case)
    _apply(case, path)
    (case["root"] / ".agentic_root").write_text("isolated test-owned OS root\n")
    (case["root"] / "harness").mkdir(exist_ok=True)
    runner = _load_runner()
    readback = {"number": 236, "url": "https://example.test/acme/app/pull/236", "state": "OPEN",
        "base_branch": "main", "base_sha": case["old_head"], "head_sha": case["head"], "repository": "acme/app"}
    _write(case["packet"] / "artifacts/auto-dev-pr-create/pull-request-provider-readback.json", readback)
    prior = _write(case["packet"] / "artifacts/finishing-touches/prior/review-request.json",
        {"work_item_id": case["current"]["ticket"], "policy_fingerprint": case["current"]["policy_fingerprint"],
         "head_sha": case["old_head"]})
    prior_bytes = prior.read_bytes()
    provider = {"number": 236, "url": readback["url"], "state": "OPEN", "headRefOid": case["head"],
                "baseRefName": "main", "baseRefOid": case["old_head"], "statusCheckRollup": []}
    monkeypatch.setattr(runner, "provider_pr", lambda *_args: provider)
    monkeypatch.setattr(runner, "git_repository", lambda *_args: "acme/app")
    monkeypatch.setattr(runner.shutil, "which", lambda *_args: None)
    monkeypatch.setattr(runner.sys, "argv", ["run_opposing_model_review.py", case["current"]["ticket"],
        "--os-root", str(case["root"]), "--work-item", str(case["packet"])])
    # Real main, Git diff, request writer, helper decision and canonical review
    # coordinator execute. Only external provider/model transports are absent.
    assert runner.main() == 2  # Actual unavailable reviewer is never a clean review.
    result = json.loads(capsys.readouterr().out)
    coordinated = json.loads(Path(result["coordination_receipt"]).read_text())
    assert coordinated["subject"]["policy_fingerprint"] == case["policy"]["fingerprint"]
    assert coordinated["subject"]["head_sha"] == case["head"] and coordinated["outcome"] == "unavailable"
    request = json.loads((Path(result["review_run_dir"]) / "review-request.json").read_text())
    assert request["validation_reconciliation"]["historical_policy_fingerprint"] == case["current"]["policy_fingerprint"]
    assert request["review_unavailable_policy"] == "block"
    assert request["repo_path"] == str(case["receiving"]) and prior.read_bytes() == prior_bytes


def test_current_review_configuration_changes_action_policy_when_planes_are_unchanged(tmp_path):
    case = _case(tmp_path)
    path, plan = _plan(case)
    _apply(case, path)
    config = delivery.project_root(case["root"], "acme", "app") / "config/development.yml"
    profile = yaml.safe_load(config.read_text())
    profile["review"]["opposing_harness"]["unavailable_policy"] = "continue_with_receipt"
    config.write_text(yaml.safe_dump(profile))
    policy, changed_profile = reconciliation._current_policy(case["task"].read())
    assert policy["planes"] == plan["current_policy"]["planes"]
    assert policy["fingerprint"] != plan["current_policy"]["fingerprint"]
    assert changed_profile != plan["current_profile"]
    with pytest.raises(delivery.DevelopmentDeliveryError, match="profile is stale"):
        reconciliation.current_action_validation_authority(case["task"].path, action="review")


def test_unbound_legacy_row_is_preserved_and_its_present_bytes_are_bound(tmp_path):
    case = _case(tmp_path)
    state = case["task"].read()
    index, row = next((index, row) for index, row in enumerate(state["receipts"]) if row.get("sha256"))
    row.pop("sha256")
    _write(case["task"].path, state)
    request = json.loads(case["reconciliation_request"].read_text())
    request["predecessor_sha256"] = _bound(case["task"].path)["sha256"]
    _write(case["reconciliation_request"], request)
    original = Path(row["ref"]).read_bytes()
    path, plan = _plan(case)
    assert plan["historical_files"][row["ref"]] == hashlib.sha256(original).hexdigest()
    _apply(case, path)
    assert "sha256" not in case["task"].read()["receipts"][index]
    assert Path(row["ref"]).read_bytes() == original
    Path(row["ref"]).write_bytes(original + b" ")
    with pytest.raises(delivery.DevelopmentDeliveryError, match="historical receipt"):
        reconciliation.current_action_validation_authority(case["task"].path)


def test_missing_original_event_history_cannot_be_reconciled(tmp_path):
    case = _case(tmp_path)
    case["task"].ledger.unlink()  # Test-owned adversarial loss, never live history.
    with pytest.raises(delivery.DevelopmentDeliveryError, match="event history is missing"):
        _plan(case)
    assert case["task"].path.read_bytes() == case["original_task"]


def test_review_entrypoint_refuses_stale_current_profile_before_provider_or_model(tmp_path, monkeypatch, capsys):
    from test_opposing_model_review_runner import _load_runner
    case = _case(tmp_path)
    path, _ = _plan(case)
    _apply(case, path)
    (case["root"] / ".agentic_root").write_text("isolated test-owned OS root\n")
    (case["root"] / "harness").mkdir(exist_ok=True)
    config = delivery.project_root(case["root"], "acme", "app") / "config/development.yml"
    config.write_text(config.read_text() + "\n# concurrent configuration change\n")
    runner = _load_runner()
    def external_must_not_run(*_args):
        pytest.fail("stale current authority reached an external review transport")
    monkeypatch.setattr(runner, "provider_pr", external_must_not_run)
    monkeypatch.setattr(runner.shutil, "which", external_must_not_run)
    monkeypatch.setattr(runner.sys, "argv", ["run_opposing_model_review.py", case["current"]["ticket"],
        "--os-root", str(case["root"]), "--work-item", str(case["packet"])])
    assert runner.main() == 2
    assert "profile is stale" in json.loads(capsys.readouterr().out)["error"]


def _next_case(case, name, *, repair=True):
    if repair:
        (case["receiving"] / "README.md").write_text("actual source repair " + name + "\n")
        _git("add", "README.md", cwd=case["receiving"])
        _git("commit", "-m", "source repair " + name, cwd=case["receiving"])
    current = case["task"].read()
    inspected = reconciliation.inspect_development_reconciliation(case["task"].path)
    head = _git("rev-parse", "HEAD", cwd=case["receiving"])
    proof = {**case["proof"], "head_sha": head, "tree_sha": _git("rev-parse", "HEAD^{tree}", cwd=case["receiving"]),
        "policy_fingerprint": inspected["current_policy"]["fingerprint"], "policy_sha256": inspected["current_policy_sha256"],
        "profile_sha256": inspected["current_profile_sha256"],
        "validation_runs": [_command_proof(case["root"], case["packet"], case["receiving"], case["command"], head, inspected["current_policy"]["fingerprint"])]}
    proof["verified_at"] = _now()  # Stamp after actual execution and terminal verification.
    proof_path = _write(case["packet"] / "artifacts" / (name + "-proof.json"), proof)
    request = {"schema": "development-validation-reconciliation-request/v1", "predecessor_sha256": _bound(case["task"].path)["sha256"],
        "owner": current["lease"]["owner"], "worktree": case["current_record"], "current_policy_fingerprint": inspected["current_policy"]["fingerprint"],
        "project_proof": _bound(proof_path), "historical_files_sha256": _digest(inspected["historical_files"]),
        "review_history_sha256": _digest(inspected["review_history"])}
    return {**case, "head": head, "policy": inspected["current_policy"], "proof": proof, "proof_path": proof_path,
        "reconciliation_request": _write(case["packet"] / "artifacts" / (name + "-request.json"), request)}


def _record_current_family(case, name, *, document=True, pr_number=236):
    if document:
        _document(case)
    current = case["task"].read()
    identity = {"repository": current["repository"]["id"], "provider": "github",
        "pull_request": "github:acme/app#" + str(pr_number), "base_branch": "main",
        "source_branch": case["current_record"]["branch"]}
    details = {"ticket": current["ticket"], **identity,
        "policy_fingerprint": case["policy"]["fingerprint"], "source_head_sha": case["head"],
        "subject_revision": case["head"], "readback_verified": True,
        "author_kind": "ours", "author_identity": "github:michaelwclark"}
    prior = current.get("stage_receipts", {}).get("release_propagation")
    if prior:
        wrapper_path = Path(prior["ref"])
        assert _bound(wrapper_path)["sha256"] == prior["sha256"]
        wrapper = json.loads(wrapper_path.read_text())
        previous_path = Path(wrapper["receipt"])
        if not previous_path.is_absolute():
            previous_path = case["packet"] / previous_path
        previous = json.loads(previous_path.read_text())
        assert hashlib.sha256(json.dumps(previous, sort_keys=True, separators=(",", ":")).encode()).hexdigest() == wrapper["evidence_sha256"]
        details["provider_observed"] = {**identity, "head_sha": case["head"]}
        details["supersession"] = {"supersedes_source_head_sha": previous["evidence"]["source_head_sha"],
            "reason": "Actual test-owned source repair observed on the same provider PR"}
    receipt = _write(case["packet"] / "artifacts" / (name + "-family.json"), {
        "schema": "development-stage-evidence/v1", "state": "release_propagation", "status": "completed",
        "summary": "Synthetic provider-read fixture for the current qualified source", "verified_at": _now(),
        "evidence": details})
    return delivery.run_development_stage(case["task"].path, stage="release_propagation",
        receipts={"release_propagation": str(receipt)}, idempotency_prefix=name + ":family")


def _review_current(case, monkeypatch, capsys, *, pr_number=236, selector=None, budget_exhausted=False,
                    provider_repository="acme/app", error_contains=None):
    from test_opposing_model_review_runner import _load_runner
    runner = _load_runner()
    (case["root"] / ".agentic_root").write_text("isolated test-owned OS root\n")
    (case["root"] / "harness").mkdir(exist_ok=True)
    readback = {"number": pr_number, "url": "https://example.test/acme/app/pull/" + str(pr_number), "state": "OPEN",
        "base_branch": "main", "base_sha": case["old_head"], "head_sha": case["head"], "repository": "acme/app"}
    # Canonical PR Create readback is current mutable provider observation;
    # every immutable old family/review artifact remains at its original path.
    _write(case["packet"] / "artifacts/auto-dev-pr-create/pull-request-provider-readback.json", readback)
    provider = {"number": pr_number, "url": readback["url"], "state": "OPEN", "headRefOid": case["head"],
        "baseRefName": "main", "baseRefOid": case["old_head"], "statusCheckRollup": []}
    with monkeypatch.context() as patch:
        patch.setattr(runner, "provider_pr", lambda *_args: provider)
        patch.setattr(runner, "git_repository", lambda *_args: provider_repository)
        patch.setattr(runner.shutil, "which", lambda *_args: None)
        patch.setattr(runner.sys, "argv", ["run_opposing_model_review.py", case["current"]["ticket"],
            "--os-root", str(case["root"]), "--work-item", str(case["packet"]),
            *(["--repository", selector] if selector else [])])
        assert runner.main() == 2  # Actual absent model remains unavailable.
        result = json.loads(capsys.readouterr().out)
    if budget_exhausted:
        assert "budget" in result["error"] and "coordination_receipt" not in result
        return result
    if error_contains:
        assert error_contains in result["error"] and "coordination_receipt" not in result
        return result
    return json.loads(Path(result["coordination_receipt"]).read_text())


def test_successor_writer_preserves_history_and_old_replay_resolves_only_latest(tmp_path, monkeypatch, capsys):
    case = _case(tmp_path)
    review = _original_review(case)
    original_review_bytes = review.receipt_path.read_bytes()
    _rebind_inspected_budget(case)
    initial_path, initial_plan = _plan(case)
    _apply(case, initial_path)
    _record_current_family(case, "initial")
    initial_review = _review_current(case, monkeypatch, capsys)
    assert initial_review["subject"]["head_sha"] == case["head"]
    old_task = case["task"].read()
    old_record = deepcopy(old_task[reconciliation.HISTORY][0])
    original_rows = deepcopy(old_task["receipts"])
    original_files = {path: Path(path).read_bytes() for path in initial_plan["historical_files"]}
    config_snapshot = Path(old_record["configuration_snapshot"]["path"])
    raw_config = config_snapshot.read_bytes()
    config = delivery.project_root(case["root"], "acme", "app") / "config/development.yml"
    profile = yaml.safe_load(config.read_text())
    profile["review"]["opposing_harness"]["unavailable_policy"] = "continue_with_receipt"
    config.write_text(yaml.safe_dump(profile))
    successor = _next_case(case, "review-repair")
    with pytest.raises(delivery.DevelopmentDeliveryError, match="stale"):
        _apply(case, initial_path)
    path, plan = _plan(successor, "review-repair")
    assert plan["predecessor_reconciliation"] == old_record["plan"]
    assert main(["develop", "reconcile-validation", "apply", str(case["task"].path), "--plan", str(path),
        "--plan-sha256", _bound(path)["sha256"], "--execute", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["current_action_authority"]["head_sha"] == successor["head"]
    after = case["task"].read()
    assert len(after[reconciliation.HISTORY]) == 2 and after[reconciliation.HISTORY][0] == old_record
    assert after["receipts"][:len(original_rows)] == original_rows
    projection = json.loads((case["packet"] / "autodev.json").read_text())
    assert not projection["delivery"]["current_action_status"]["review_current"]
    assert projection["stages"]["review_self"]["status"] != "completed"
    assert all(Path(path).read_bytes() == raw for path, raw in original_files.items())
    assert config_snapshot.read_bytes() == raw_config and review.receipt_path.read_bytes() == original_review_bytes
    with pytest.raises(delivery.DevelopmentDeliveryError, match="substituted mapping"):
        reconciliation.current_action_task_view(old_task, action="review")
    events = case["task"].ledger.read_bytes()
    replay = _apply(case, initial_path)
    assert replay["replayed"] and replay["superseded"] and replay["current_action_authority"]["head_sha"] == successor["head"]
    assert _apply(successor, path)["replayed"]
    assert case["task"].ledger.read_bytes() == events
    _record_current_family(successor, "repaired")
    repaired_review = _review_current(successor, monkeypatch, capsys)
    assert repaired_review["subject"]["head_sha"] == successor["head"] and repaired_review["outcome"] == "unavailable"
    assert review.receipt_path.read_bytes() == original_review_bytes


def test_stale_old_proof_and_two_successors_cannot_replace_one_predecessor_twice(tmp_path):
    case = _case(tmp_path)
    initial_path, _ = _plan(case)
    _apply(case, initial_path)
    successor = _next_case(case, "concurrent-repair")
    wrong = json.loads(successor["reconciliation_request"].read_text())
    wrong["project_proof"] = _bound(case["proof_path"])
    wrong_path = _write(case["packet"] / "artifacts/wrong-old-proof-request.json", wrong)
    before = case["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="identity"):
        reconciliation.plan_development_reconciliation(case["task"].path, request_file=wrong_path, idempotency_key="old-proof")
    assert case["task"].path.read_bytes() == before
    first, _ = _plan(successor, "candidate-one")
    second, _ = _plan(successor, "candidate-two")
    def attempt(path):
        try:
            return _apply(successor, path)
        except delivery.DevelopmentDeliveryError as error:
            return error
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [first, second]))
    assert sum(isinstance(result, dict) and result["applied"] for result in results) == 1
    assert sum(isinstance(result, delivery.DevelopmentDeliveryError) for result in results) == 1
    assert len(case["task"].read()[reconciliation.HISTORY]) == 2
    events = [json.loads(line) for line in case["task"].ledger.read_text().splitlines()]
    assert sum(row["type"] == "development.validation.reconciled" for row in events) == 2


def test_later_canonical_pr_receipt_append_and_premerge_milestone_survive_successor(tmp_path):
    case = _case(tmp_path)
    path, _ = _plan(case)
    _apply(case, path)
    receipt = _stage_receipt(case["packet"], "pr_open", evidence={"provider": "github", "pull_request": "github:acme/app#236",
        "repository": case["current"]["repository"]["id"], "source_head_sha": case["head"], "subject_revision": case["head"],
        "base_branch": "main", "source_branch": case["current_record"]["branch"], "readback_verified": True, "author_kind": "ours"})
    case["task"].transition("pre_pr_review", receipt=_stage_receipt(case["packet"], "pre_pr_review"),
        idempotency_key="canonical-pre-pr-review")
    case["task"].transition("pr_open", receipt=receipt, idempotency_key="canonical-pr-open")
    appended = deepcopy(case["task"].read()["receipts"])
    assert reconciliation.current_action_validation_authority(case["task"].path)["head_sha"] == case["head"]
    successor = _next_case(case, "post-pr-repair")
    next_path, _ = _plan(successor, "post-pr-repair")
    _apply(successor, next_path)
    after = case["task"].read()
    assert after["state"] == "pr_open" and after["receipts"][:len(appended)] == appended
    _record_current_family(successor, "post-pr")
    assert case["task"].read()["state"] == "pr_open"


def _ready_current_case(tmp_path):
    from genomes_agentic_os.review_coordination import ReviewCoordinator, ReviewSubject, shared_review_coordination_root, stable_review_key
    case = _case(tmp_path, mode="everything")
    path, _ = _plan(case)
    _apply(case, path)
    _record_current_family(case, "initial-ready")
    current = case["task"].read()
    subject = ReviewSubject("acme/app", "github:acme/app#236", "main", case["old_head"],
        case["head"], case["policy"]["fingerprint"])
    key = stable_review_key(subject)
    directory = case["packet"] / "artifacts/finishing-touches/review-runs" / key
    _write(directory / "review-request.json", {"run_id": key, "review_key": key,
        "work_item_id": current["ticket"], "repository": "acme/app", "pr_number": 236,
        "head_sha": subject.head_sha, "base_sha": subject.base_sha, "policy_fingerprint": subject.policy_fingerprint})
    # Exercise the real ledger/ready writer with a test-owned clean result;
    # no external reviewer, provider or installed task is called.
    review = ReviewCoordinator(shared_review_coordination_root(case["root"])).execute(subject,
        lambda: {"outcome": "clean", "ticket": current["ticket"], "review_run_dir": str(directory),
                 "response": "Synthetic current-head conformance fixture"})
    identity = {"provider": "github", "pull_request": "github:acme/app#236",
        "repository": current["repository"]["id"], "base_branch": "main",
        "source_branch": case["current_record"]["branch"], "readback_verified": True,
        "source_head_sha": case["head"], "subject_revision": case["head"], "author_kind": "ours",
        "author_identity": "github:michaelwclark"}
    receipts = {stage: _stage_receipt(case["packet"] / "artifacts/ready-admission", stage)
        for stage in ("pre_pr_review", "ci_repair", "review_repair", "post_pr_review")}
    receipts["pr_open"] = _stage_receipt(case["packet"] / "artifacts/ready-admission", "pr_open", evidence=identity)
    receipts["ready_for_merge"] = _stage_receipt(case["packet"] / "artifacts/ready-admission", "ready_for_merge",
        evidence={**identity, "checks_verified": True, "reviews_verified": True,
            "review_policy_fingerprint": subject.policy_fingerprint, "review_coordination_receipt": str(review.receipt_path)})
    delivery.run_development_stage(case["task"].path, stage="review", receipts=receipts, idempotency_prefix="real-current-ready")
    return case


@pytest.mark.parametrize("change", ["head", "profile"])
def test_later_ready_head_replacement_refuses_and_historical_review_projects_pending(tmp_path, change):
    from genomes_agentic_os.auto_dev_orchestration import sync_delivery_projection
    case = _ready_current_case(tmp_path)
    assert reconciliation.current_action_projection(case["task"].path)["review_current"] is True
    before = case["task"].path.read_bytes()
    rows = deepcopy(case["task"].read()["receipts"])
    receipt_bytes = {row["ref"]: Path(row["ref"]).read_bytes() for row in rows if Path(row["ref"]).is_file()}
    if change == "profile":
        config = delivery.project_root(case["root"], "acme", "app") / "config/development.yml"
        config.write_text(config.read_text() + "\n# current source policy bytes changed\n")
    successor = _next_case(case, "unsupported-ready-" + change, repair=change == "head")
    with pytest.raises(delivery.DevelopmentDeliveryError, match="ready_for_merge revalidation is unsupported"):
        _plan(successor, "must-not-replace-ready-head")
    projection = sync_delivery_projection(case["task"].path)
    assert projection["delivery"]["state"] == "ready_for_merge"
    assert projection["delivery"]["current_action_status"]["status"] == "unqualified_current_evidence"
    assert not projection["delivery"]["current_action_status"]["review_current"]
    assert "current_action_authority" not in projection["delivery"]
    assert projection["stages"]["review_self"]["status"] == "not_started"
    assert projection["status"] != "completed"
    with pytest.raises(delivery.DevelopmentDeliveryError):
        delivery.run_development_stage(case["task"].path, stage="review", receipts={}, idempotency_prefix="no-historical-review-noop")
    assert case["task"].path.read_bytes() == before and case["task"].read()["receipts"] == rows
    assert all(Path(path).read_bytes() == raw for path, raw in receipt_bytes.items())


def test_same_head_policy_successor_does_not_reuse_prior_pr_or_review_authority(tmp_path):
    from genomes_agentic_os.auto_dev_orchestration import sync_delivery_projection
    case = _case(tmp_path, mode="everything")
    path, _ = _plan(case)
    _apply(case, path)
    _record_current_family(case, "same-head-initial")
    original = case["task"].read()
    wrapper = original["stage_receipts"]["release_propagation"]
    wrapper_bytes = Path(wrapper["ref"]).read_bytes()
    config = delivery.project_root(case["root"], "acme", "app") / "config/development.yml"
    profile = yaml.safe_load(config.read_text())
    profile["review"]["opposing_harness"]["unavailable_policy"] = "continue_with_receipt"
    config.write_text(yaml.safe_dump(profile))
    successor = _next_case(case, "same-head-current-policy", repair=False)
    assert successor["head"] == case["head"] and successor["policy"]["fingerprint"] != case["policy"]["fingerprint"]
    next_path, _ = _plan(successor, "same-head-current-policy")
    _apply(successor, next_path)
    projection = sync_delivery_projection(case["task"].path)
    assert projection["delivery"]["current_action_status"]["status"] == "source_qualified"
    assert not projection["delivery"]["current_action_status"]["review_current"]
    assert projection["stages"]["pr_create"]["status"] == "not_started"
    assert projection["stages"]["review_self"]["status"] == "not_started"
    before = case["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="provider-read new head and explicit prior-head supersession"):
        _record_current_family(successor, "unsupported-same-head-policy-refresh", document=False)
    assert case["task"].path.read_bytes() == before
    assert Path(wrapper["ref"]).read_bytes() == wrapper_bytes
    assert case["task"].read()["receipts"][:len(original["receipts"])] == original["receipts"]
    with pytest.raises(delivery.DevelopmentDeliveryError):
        delivery.run_development_stage(case["task"].path, stage="review", receipts={}, idempotency_prefix="no-policy-only-review-noop")


def _other_canonical_task(case, tmp_path):
    root = Path(case["current"]["repository"]["root"])
    original_remote = _git("config", "--get", "remote.origin.url", cwd=root)
    # Normal factory provisioning fetches only the disposable local bare repo.
    _git("remote", "set-url", "origin", str(tmp_path / "remote.git"), cwd=root)
    try:
        profile, _ = delivery.load_development_profile(case["root"], "acme", "app")
        selection = {"repository_id": case["current"]["repository"]["id"]} if profile["repository"].get("catalog") else {}
        result = delivery.start_development_run(case["root"], "acme", "app", ["AGE-237"], run_id="unrelated-task", apply=True,
            auto_dev_mode="single_stage", requested_stage="pr_create", goal="pr_create", **selection)
    finally:
        _git("remote", "set-url", "origin", original_remote, cwd=root)
    task = delivery.TaskState(Path(result["tasks"][0]["state_ref"]))
    state = task.read()
    packet = Path(state["work_item"])
    for stage in ("groom", "detective", "create_artifacts"):
        _record_standalone_stage(task, stage)
    delivery.run_development_stage(task.path, stage="readiness", receipts={"planned": _stage_receipt(packet, "planned")}, idempotency_prefix="other-planned")
    worktree = Path(state["worktree"]["path"])
    head = _git("rev-parse", "HEAD", cwd=worktree)
    proof = _command_proof(case["root"], packet, worktree, case["command"], head, state["policy_fingerprint"])
    receipt = _stage_receipt(packet, "local_validation", status="passed", evidence={"ticket": state["ticket"], "repository": "acme/app",
        "head_sha": head, "policy_fingerprint": state["policy_fingerprint"], "validation_runs": [proof]})
    delivery.run_development_stage(task.path, stage="implementation", receipts={"implementing": _stage_receipt(packet, "implementing"),
        "local_validation": receipt}, idempotency_prefix="other-implementation")
    return {"task": task, "packet": packet, "root": case["root"]}


@pytest.mark.parametrize("catalog", [False, True])
def test_unrelated_valid_task_exhaustion_does_not_consume_this_task_capacity(tmp_path, monkeypatch, catalog):
    case = _catalog_case(tmp_path, monkeypatch) if catalog else _case(tmp_path)
    subject_repository = "api" if catalog else "acme/app"
    own = _original_review(case, repository=subject_repository)
    other = _other_canonical_task(case, tmp_path)
    unrelated = [_original_review(case, owner=other, pull_request=99, repository=subject_repository),
        _original_review(case, owner=other, pull_request=99, second=True, repository=subject_repository)]
    bytes_before = {str(result.receipt_path): result.receipt_path.read_bytes() for result in [own, *unrelated]}
    history = _rebind_inspected_budget(case)
    assert len(history["charges"]) == 3 and len(history["task_families"]) == 1 and not history["ambiguous_families"]
    path, _ = _plan(case)
    _apply(case, path)
    assert all(Path(path).read_bytes() == raw for path, raw in bytes_before.items())
    assert reconciliation._budget_history(case["task"].read())["charges"] == history["charges"]
    from genomes_agentic_os.review_coordination import ReviewBudgetExceeded, ReviewCoordinator, ReviewSubject, shared_review_coordination_root
    with pytest.raises(ReviewBudgetExceeded):
        ReviewCoordinator(shared_review_coordination_root(case["root"])).execute(
            ReviewSubject(subject_repository, "github:acme/app#99", "main", "a" * 40, "3" * 40, "e" * 64),
            lambda: {"outcome": "clean", "response": "Must not receive another paid allowance"})


def test_unattributed_paid_history_refuses_instead_of_assuming_an_unrelated_task(tmp_path):
    case = _case(tmp_path)
    from genomes_agentic_os.review_coordination import ReviewCoordinator, ReviewSubject, shared_review_coordination_root
    receipt = ReviewCoordinator(shared_review_coordination_root(case["root"])).execute(
        ReviewSubject("acme/app", "github:acme/app#88", "main", "a" * 40, "b" * 40, "c" * 64),
        lambda: {"outcome": "clean", "response": "Historical unqualified ownership fixture"})
    original = receipt.receipt_path.read_bytes()
    history = _rebind_inspected_budget(case)
    assert history["ambiguous_families"]
    with pytest.raises(delivery.DevelopmentDeliveryError, match="ambiguous canonical task/family"):
        _plan(case)
    assert receipt.receipt_path.read_bytes() == original and case["task"].path.read_bytes() == case["original_task"]


def test_catalog_alias_cannot_hide_provider_review_charges(tmp_path, monkeypatch):
    import test_development_validation_refresh as fixtures
    original_project = fixtures._project
    def aliased_project(root, repository, **kwargs):
        return original_project(root, repository, **{**kwargs, "repository_id": "api"})
    monkeypatch.setattr(fixtures, "_project", aliased_project)
    case = _case(tmp_path)
    assert case["current"]["repository"]["id"] == "api"
    _original_review(case)
    _original_review(case, second=True)
    history = _rebind_inspected_budget(case)
    assert history["repository"] == "acme/app" and len(history["charges"]) == 2
    with pytest.raises(delivery.DevelopmentDeliveryError, match="budget.*exhausted"):
        _plan(case)


def _catalog_case(tmp_path, monkeypatch):
    import test_development_validation_refresh as fixtures
    original_project = fixtures._project
    def aliased_project(root, repository, **kwargs):
        return original_project(root, repository, **{**kwargs, "repository_id": "api"})
    monkeypatch.setattr(fixtures, "_project", aliased_project)
    case = _case(tmp_path)
    config = delivery.project_root(case["root"], "acme", "app") / "config/development.yml"
    profile = yaml.safe_load(config.read_text())
    profile["repository"] = {"root": profile["repository"]["root"], "base_branch": "main",
        "selection_required": True, "catalog": [profile["repository"],
        {**profile["repository"], "id": "web"}]}
    config.write_text(yaml.safe_dump(profile))
    return _next_case(case, "selected-catalog-policy", repair=False)


@pytest.mark.parametrize("native_repository", ["api", "acme/app"])
def test_catalog_review_preserves_paid_subject_family_lock_and_budget(tmp_path, monkeypatch, capsys, native_repository):
    case = _catalog_case(tmp_path, monkeypatch)
    original = _original_review(case, repository=native_repository)
    original_bytes = original.receipt_path.read_bytes()
    history = _rebind_inspected_budget(case)
    assert len(history["charges"]) == len(history["task_families"]) == 1
    assert not history["ambiguous_families"] and str(original.receipt_path) in history["files"]
    family = original.receipt["family_key"]
    assert history["task_families"] == [family]
    assert history["family_subjects"][family] == {"repository": native_repository,
        "pull_request": "github:acme/app#42", "provider_family": "github:acme/app#42"}
    path, _ = _plan(case, "catalog-current")
    with reconciliation._review_locks(history):
        with pytest.raises(delivery.DevelopmentDeliveryError, match="original review family is active"):
            _apply(case, path)
    assert case["task"].path.read_bytes() == case["original_task"]
    _apply(case, path)
    authority = reconciliation.current_action_validation_authority(case["task"].path, action="review")
    assert authority["repository_id"] == "api" and authority["provider_repository"] == "acme/app"
    _record_current_family(case, "catalog-pr", pr_number=42)
    before_provider_refusal = reconciliation._budget_history(case["task"].read())
    _review_current(case, monkeypatch, capsys, pr_number=42, selector="api", provider_repository="wrong/repository",
        error_contains="provider repository differs")
    assert reconciliation._budget_history(case["task"].read()) == before_provider_refusal
    reviewed = _review_current(case, monkeypatch, capsys, pr_number=42, selector="api")
    assert reviewed["family_key"] == family and reviewed["subject"]["repository"] == native_repository
    request = json.loads((Path(reviewed["review"]["review_run_dir"]) / "review-request.json").read_text())
    assert request["repository"] == request["provider_repository"] == "acme/app"
    assert request["review_subject_repository"] == native_repository
    assert original.receipt_path.read_bytes() == original_bytes
    second = _original_review(case, repository=native_repository, second=True)
    second_bytes = second.receipt_path.read_bytes()
    _review_current(case, monkeypatch, capsys, pr_number=42, selector="api", budget_exhausted=True)
    assert original.receipt_path.read_bytes() == original_bytes and second.receipt_path.read_bytes() == second_bytes
    after = reconciliation._budget_history(case["task"].read())
    assert sum(row["mode"] == "full" for row in after["charges"].values()) == 2
    assert {row["family_key"] for row in after["charges"].values()} == {family}


def test_unproven_alias_paid_history_is_preserved_and_refuses_ambiguity(tmp_path, monkeypatch):
    case = _catalog_case(tmp_path, monkeypatch)
    original = _original_review(case, repository="unknown-old-alias")
    original_bytes = original.receipt_path.read_bytes()
    history = _rebind_inspected_budget(case)
    assert len(history["charges"]) == 1 and str(original.receipt_path) in history["files"]
    assert history["ambiguous_families"] == [original.receipt["family_key"]]
    with pytest.raises(delivery.DevelopmentDeliveryError, match="ambiguous canonical task/family"):
        _plan(case)
    assert case["task"].path.read_bytes() == case["original_task"] and original.receipt_path.read_bytes() == original_bytes


def test_mixed_native_alias_and_provider_namespaces_refuse_without_rekeying(tmp_path, monkeypatch):
    case = _catalog_case(tmp_path, monkeypatch)
    reviews = [_original_review(case, repository=name) for name in ("api", "acme/app")]
    original_bytes = {str(row.receipt_path): row.receipt_path.read_bytes() for row in reviews}
    history = _rebind_inspected_budget(case)
    assert len(history["charges"]) == len(history["task_families"]) == 2 and not history["ambiguous_families"]
    assert {row["provider_family"] for row in history["charges"].values()} == {"github:acme/app#42"}
    with pytest.raises(delivery.DevelopmentDeliveryError, match="mixed native review identities"):
        _plan(case)
    assert case["task"].path.read_bytes() == case["original_task"]
    assert all(Path(path).read_bytes() == raw for path, raw in original_bytes.items())


def test_successor_source_cannot_regress_to_an_older_committed_head(tmp_path):
    case = _case(tmp_path)
    initial_path, _ = _plan(case)
    _apply(case, initial_path)
    successor = _next_case(case, "forward-only")
    next_path, _ = _plan(successor, "forward-only")
    _apply(successor, next_path)
    rollback = tmp_path / "rollback"
    branch = "feature/test-rollback-" + uuid.uuid4().hex[:8]
    _git("worktree", "add", "-b", branch, str(rollback), case["head"], cwd=case["receiving"])
    delivery.register_project_worktree(case["root"], "acme", "app", "rollback", path=rollback)
    project = delivery.project_root(case["root"], "acme", "app")
    registered = next(row.get("id") or row.get("name") for row in delivery.worktree_entries_for_project(project)
                      if Path(row["path"]).resolve() == rollback.resolve())
    inspected = reconciliation.inspect_development_reconciliation(case["task"].path)
    request = json.loads(successor["reconciliation_request"].read_text())
    request.update(predecessor_sha256=_bound(case["task"].path)["sha256"],
        worktree={"name": registered, "path": str(rollback), "branch": branch, "repository_id": case["current"]["repository"]["id"]},
        historical_files_sha256=_digest(inspected["historical_files"]), review_history_sha256=_digest(inspected["review_history"]))
    request_path = _write(case["packet"] / "artifacts/rollback-request.json", request)
    before = case["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="descend from the accepted"):
        reconciliation.plan_development_reconciliation(case["task"].path, request_file=request_path, idempotency_key="no-backwards-head")
    assert case["task"].path.read_bytes() == before


def test_duplicate_task_identity_keys_refuse_before_adoption(tmp_path):
    case = _case(tmp_path)
    raw = case["task"].path.read_text().replace("{", '{"project": "app",', 1)
    case["task"].path.write_text(raw)
    before = case["task"].path.read_bytes()
    with pytest.raises(delivery.DevelopmentDeliveryError, match="duplicate"):
        reconciliation.inspect_development_reconciliation(case["task"].path)
    assert case["task"].path.read_bytes() == before and case["task"].ledger.read_bytes() == case["original_events"]


@pytest.mark.parametrize("field,value", [
    ("auto_dev_mode", "everything"), ("requested_stage", "review_self"),
    ("goal", "ready_for_merge"), ("auto_dev_stage_policies", {"develop": {"applicability": "disabled"}}),
])
def test_original_workflow_window_and_applicability_cannot_be_reinterpreted(tmp_path, field, value):
    case = _case(tmp_path)
    path, _ = _plan(case)
    _apply(case, path)
    state = case["task"].read()
    original = Path(state[reconciliation.HISTORY][0]["original_task"]["path"])
    original_bytes = original.read_bytes()
    event_bytes = case["task"].ledger.read_bytes()
    state[field] = value  # Adversarial edit to this disposable fixture only.
    _write(case["task"].path, state)
    with pytest.raises(delivery.DevelopmentDeliveryError, match="historical task/receipt identity"):
        reconciliation.current_action_validation_authority(case["task"].path)
    assert original.read_bytes() == original_bytes and case["task"].ledger.read_bytes() == event_bytes


def test_missing_paid_receipt_is_not_replaced_by_its_reservation_sidecar(tmp_path):
    case = _case(tmp_path)
    receipt = _original_review(case)
    receipt.receipt_path.unlink()  # Test-owned adversarial historical body loss.
    with pytest.raises(delivery.DevelopmentDeliveryError, match="missing charged receipt"):
        reconciliation.inspect_development_reconciliation(case["task"].path)
    assert case["task"].path.read_bytes() == case["original_task"]
