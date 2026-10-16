"""Already normalized catalog aliases retain trusted provider fences."""

from copy import deepcopy
from pathlib import Path

import pytest

import genomes_agentic_os.development_delivery as delivery
from test_catalog_alias_review import _fixture
from test_development_delivery import _git, _stage_receipt


def _ready_then_repair(tmp_path, monkeypatch):
    task, repo, evidence, _ = _fixture(tmp_path, monkeypatch)
    work_item = Path(task.read()["work_item"])
    receipts = {name: _stage_receipt(work_item, name) for name in (
        "pre_pr_review", "ci_repair", "review_repair", "post_pr_review",
    )}
    for name in ("pr_open", "ready_for_merge"):
        receipts[name] = _stage_receipt(work_item, name, evidence=evidence)
    delivery.run_development_stage(task.path, stage="review", receipts=receipts,
                                   idempotency_prefix="catalog:ready")
    previous = evidence["source_head_sha"]
    (repo / "repair.txt").write_text("Substantive repair\n")
    _git("add", "repair.txt", cwd=repo)
    _git("commit", "-m", "fix: repair reviewed source", cwd=repo)
    head = _git("rev-parse", "HEAD", cwd=repo)
    updated = deepcopy(evidence)
    updated.update(source_head_sha=head, subject_revision=head,
                   supersession={"supersedes_source_head_sha": previous,
                                 "reason": "Repair source identified by review"})
    updated["provider_observed"]["head_sha"] = head
    return task, work_item, updated


def test_already_normalized_ready_catalog_alias_refreshes_without_relabeling_history(tmp_path, monkeypatch):
    task, work_item, evidence = _ready_then_repair(tmp_path, monkeypatch)
    prior = {Path(row["ref"]): Path(row["ref"]).read_bytes()
             for row in task.read()["receipts"] if Path(row["ref"]).is_file()}
    assert task.read()["repository"]["id"] == "user_app"
    assert task.read()["state"] == "ready_for_merge"
    receipt = _stage_receipt(work_item / "source-repair", "release_propagation", evidence=evidence)
    delivery.run_development_stage(
        task.path, stage="release_propagation", receipts={"release_propagation": receipt},
        idempotency_prefix="catalog:refresh",
    )
    assert task.read()["state"] == "local_validation"
    assert task.read()["repository"]["id"] == "user_app"
    assert all(path.read_bytes() == raw for path, raw in prior.items())
    assert task.read()["subject_revision"] is None
    assert task.read()["subject_supersessions"][-1]["to_source_head_sha"] == evidence["subject_revision"]


@pytest.mark.parametrize("field,value", [
    ("provider", "gitlab"), ("repository", "other_app"),
    ("author_kind", "others"), ("author_identity", "github:other"),
    ("base_branch", "develop"),
    ("source_branch", "feature/other"), ("base_sha", "f" * 40),
])
def test_ready_alias_refresh_refuses_provider_repository_author_and_source_drift(
    tmp_path, monkeypatch, field, value,
):
    task, work_item, evidence = _ready_then_repair(tmp_path, monkeypatch)
    evidence[field] = value
    receipt = _stage_receipt(work_item / "invalid-repair", "release_propagation", evidence=evidence)
    before = {p: p.read_bytes() for p in (task.path, task.ledger, Path(task.read()["autodev_path"]))}
    with pytest.raises(delivery.DevelopmentDeliveryError):
        delivery.run_development_stage(
            task.path, stage="release_propagation", receipts={"release_propagation": receipt},
            idempotency_prefix="catalog:invalid-refresh",
        )
    assert all(path.read_bytes() == raw for path, raw in before.items())


def test_trusted_provider_refuses_unknown_alias_and_changed_frozen_policy(tmp_path, monkeypatch):
    task, _, _ = _ready_then_repair(tmp_path, monkeypatch)
    value = task.read()
    value["repository"]["id"] = "unknown_app"
    with pytest.raises(delivery.DevelopmentDeliveryError):
        delivery._trusted_catalog_provider(value)
    profile = Path(task.read()["profile_source"])
    raw = profile.read_text()
    profile.write_text(raw.replace("acme/app", "acme/other"))
    with pytest.raises(delivery.DevelopmentDeliveryError):
        delivery._trusted_catalog_provider(task.read())
