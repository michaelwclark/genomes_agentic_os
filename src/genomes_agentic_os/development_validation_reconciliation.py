"""Append current validation authority without reinterpreting a legacy milestone.

The historical TaskState remains the source of identity and budget ownership.
Consumers explicitly request an action view; ordinary TaskState.read is unchanged.
Project qualification is opt-in. The command adapter below proves only configured
commands with existing execution provenance; it cannot qualify native full95.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Iterator, Mapping

from . import development_delivery as delivery
from .development_validation_refresh import _bound, _clean_worktree, _commands, _git, _read, _timestamp


SCHEMA = "development-validation-reconciliation/v1"
PLAN_SCHEMA = "development-validation-reconciliation-plan/v1"
PROOF_SCHEMA = "development-reconciliation-project-proof/v1"
COMMAND_ADAPTER = "configured-command-proof/v1"
HISTORY = "validation_reconciliations"
IMMUTABLE_FIELDS = (
    "schema", "os_root", "domain", "project", "ticket", "run_id", "canonical_work_id",
    "repository", "worktree", "policy_receipt", "policy_fingerprint", "created_at",
    "rollup_ledger", "autodev_path", "work_item", "context_selection",
    "auto_dev_stage_order", "auto_dev_start_stage", "auto_dev_completion_stage", "source",
    "auto_dev_mode", "requested_stage", "goal", "auto_dev_stage_policies",
)


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise delivery.DevelopmentDeliveryError(message)


def _bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _binding(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": _sha(path)}


def _contained(packet: Path, path: Path) -> Path:
    """Refuse escaped ancestors and leaves before any state or evidence write."""
    _require(path.is_absolute() and path.is_relative_to(packet) and path != packet, "reconciliation output must be packet-contained")
    for item in (path, *path.parents):
        if item == packet:
            break
        _require(not item.is_symlink(), "reconciliation evidence cannot use symlinks")
    _require(path.resolve().is_relative_to(packet), "reconciliation output escapes its packet")
    return path


def _snapshot(packet: Path, name: str, raw: bytes) -> Path:
    target = _contained(packet, packet / "artifacts/development-delivery/reconciliation" / name)
    if target.exists():
        _require(target.is_file() and target.read_bytes() == raw, "immutable reconciliation snapshot collision")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        _contained(packet, target)
        with target.open("xb") as stream:
            stream.write(raw)
    return target


def _task(state_file: str | Path) -> tuple[delivery.TaskState, dict[str, Any], Path]:
    task = delivery.TaskState(Path(state_file).expanduser().resolve())
    value, _ = _read(task.path)
    _require(value.get("schema") == "development-task/v1" and value.get("canonical_work_id") ==
             f"{value.get('domain')}:{value.get('project')}:{str(value.get('ticket')).lower()}", "reconciliation task identity is invalid")
    packet = Path(str(value.get("work_item") or "")).resolve()
    _require(packet.is_dir() and not packet.is_symlink(), "reconciliation requires the existing canonical packet")
    manifest, _ = _read(packet / "autodev.json")
    linked = manifest.get("delivery") or {}
    _require(manifest.get("canonical_work_id") == value["canonical_work_id"] and linked.get("run_id") == value["run_id"]
             and manifest.get("domain") == value["domain"] and manifest.get("project") == value["project"]
             and manifest.get("source", {}).get("key") == value["ticket"]
             and Path(str(value.get("autodev_path") or "")).resolve() == packet / "autodev.json"
             and Path(str(linked.get("work_item") or "")).resolve() == packet
             and linked.get("repository") == value["repository"] and linked.get("worktree") == value["worktree"]
             and linked.get("policy_fingerprint") == value["policy_fingerprint"]
             and Path(str(linked.get("task_state_ref") or "")).resolve() == task.path,
             "reconciliation requires the same linked task/run owner")
    return task, value, packet


def _historical_files(value: Mapping[str, Any]) -> dict[str, str]:
    files = {}
    for receipt in value.get("receipts", []):
        if not isinstance(receipt, Mapping):
            _require(False, "historical receipt metadata is malformed")
        path = Path(str(receipt.get("ref") or ""))
        if not receipt.get("sha256") and not path.is_file():
            _require(_historical_reference(value, receipt) is not None, "historical receipt file or canonical reference is missing")
            continue
        _require(path.is_absolute() and path.is_file() and not path.is_symlink(), "historical receipt file is missing or redirected")
        digest = _sha(path)
        _require(not receipt.get("sha256") or digest == receipt["sha256"], "historical receipt bytes changed")
        # An older unbound row gets a present-time custody binding, never a
        # retroactively inserted hash, timestamp or validation claim.
        files[str(path)] = digest
    policy = Path(str(value.get("policy_receipt") or ""))
    _require(policy.is_absolute() and policy.is_file() and not policy.is_symlink(), "original frozen policy is missing")
    frozen, _ = _read(policy)
    delivery._validate_effective_policy_snapshot(frozen, require_selected_profile=False)
    _require(frozen.get("fingerprint") == value["policy_fingerprint"], "original frozen policy no longer matches historical task identity")
    files[str(policy)] = _sha(policy)
    return files


def _historical_reference(value: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Classify canonical non-file rows without claiming directory/provider bodies."""
    reference = str(row.get("ref") or "")
    source = value.get("source") or {}
    marker = str(source.get("system") or "") + ":" + str(value["ticket"])
    if (row.get("state") in {"claimed", "groom_check"} and source.get("key") == value["ticket"]
            and source.get("system") in {"linear", "jira", "github", "bitbucket"} and reference == marker):
        return {"state": row["state"], "ref": reference, "kind": "canonical_tracker_identity", "body_verified": False}
    directory = {"work_item_ready": value["work_item"], "worktree_ready": value["worktree"]["path"]}.get(row.get("state"))
    if directory and Path(reference).is_absolute() and Path(reference).is_dir() and Path(reference).resolve() == Path(directory).resolve():
        return {"state": row["state"], "ref": reference, "kind": "canonical_directory_identity", "body_verified": False}
    return None


def _historical_reference_metadata(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [identity for row in value["receipts"] if not row.get("sha256")
            and (identity := _historical_reference(value, row)) is not None]


def _provider_repository(value: Mapping[str, Any]) -> str:
    identity = delivery._normalized_repository_identity({"root": value["repository"]["root"]})
    _require(identity.startswith("git:github.com/") and re.fullmatch(r"[^/]+/[^/]+", identity.removeprefix("git:github.com/")),
             "review reconciliation requires a supported GitHub provider repository identity")
    repository = identity.removeprefix("git:github.com/").casefold()
    configured = str(value["repository"]["id"])
    if configured.startswith(("git:github.com/", "github:")):
        _require(configured.removeprefix("git:github.com/").removeprefix("github:").casefold() == repository,
                 "task provider repository differs from the actual Git remote")
    return repository


def _provider_family(repository: str, pull_request: str) -> str:
    matched = re.fullmatch(r"github:([^#]+)#([1-9][0-9]*)", pull_request)
    _require(matched and matched[1].casefold() == repository, "review family provider/repository identity is unqualified")
    return "github:" + repository + "#" + matched[2]


def _review_owner(value: Mapping[str, Any], receipt: Mapping[str, Any], repository: str) -> tuple[dict[str, Any], dict[str, str]] | None:
    """Prove a native review's canonical packet owner, without freezing mutable task progress."""
    review = receipt.get("review") or {}
    if not isinstance(review, Mapping) or not review.get("review_run_dir") or not review.get("ticket"):
        return None
    directory = Path(str(review["review_run_dir"]))
    project = delivery.project_root(value["os_root"], value["domain"], value["project"]).resolve()
    if (not directory.is_absolute() or len(directory.parents) < 4 or directory.name != receipt["key"]
            or directory.parent.name != "review-runs" or directory.parents[1].name != "finishing-touches"
            or directory.parents[2].name != "artifacts" or not directory.resolve().is_relative_to(project / "work-items")):
        return None
    packet = directory.parents[3].resolve()
    try:
        request_path = _contained(packet, directory / "review-request.json")
        request, request_digest = _read(request_path)
        manifest, _ = _read(packet / "autodev.json")
        state_ref = Path(str((manifest.get("delivery") or {}).get("task_state_ref") or ""))
        _require(state_ref.is_absolute() and state_ref.resolve().is_relative_to(project / "state/development-runs"), "review owner task is outside its canonical project")
        task, owner, owned_packet = _task(state_ref)
        subject = receipt["subject"]
        names = {str(owner["repository"]["id"]).casefold(), repository, "git:github.com/" + repository, "github:" + repository}
        _require(owned_packet == packet and Path(owner["os_root"]).resolve() == Path(value["os_root"]).resolve()
                 and _provider_repository(owner) == repository and review["ticket"] == owner["ticket"]
                 and str(request.get("repository") or "").casefold() in names
                 and str(subject.get("repository") or "").casefold() in names
                 and request.get("work_item_id") == owner["ticket"] and request.get("review_key") == receipt["key"]
                 and request.get("run_id") == receipt["key"] and request.get("head_sha") == subject["head_sha"]
                 and request.get("base_sha") == subject["base_sha"]
                 and request.get("policy_fingerprint") == subject["policy_fingerprint"]
                 and _provider_family(repository, "github:" + repository + "#" + str(request.get("pr_number")))
                     == _provider_family(repository, subject["pull_request"]), "native review owner lineage is unqualified")
        return ({"canonical_work_id": owner["canonical_work_id"], "run_id": owner["run_id"],
                 "task_state_ref": str(task.path), "work_item": str(packet)}, {str(request_path): request_digest})
    except (delivery.DevelopmentDeliveryError, KeyError, OSError, TypeError):
        return None


def _task_family_evidence(value: Mapping[str, Any], repository: str) -> tuple[set[str], dict[str, str]]:
    """Read hash-bound canonical task PR evidence; never take a caller family list."""
    packet = Path(value["work_item"]).resolve()
    families, files = set(), {}

    def consume(payload: Mapping[str, Any]) -> None:
        details = payload.get("evidence") or {}
        if not isinstance(details, Mapping) or details.get("provider") != "github" or not details.get("pull_request"):
            return
        names = {str(value["repository"]["id"]).casefold(), repository, "git:github.com/" + repository, "github:" + repository}
        _require(str(details.get("repository") or "").casefold() in names
                 and details.get("ticket", value["ticket"]) == value["ticket"], "canonical task PR family identity differs")
        families.add(_provider_family(repository, str(details["pull_request"])))

    for row in value.get("receipts", []):
        if row.get("state") in {"pr_open", "ready_for_merge", "merged"} and row.get("sha256"):
            path, payload, digest = _bound({"path": row["ref"], "sha256": row["sha256"]}, packet)
            _require(payload.get("schema") == "development-stage-evidence/v1" and payload.get("state") == row["state"],
                     "canonical task PR receipt is unqualified")
            files[str(path)] = digest
            consume(payload)
    descriptor = (value.get("stage_receipts") or {}).get("release_propagation")
    if isinstance(descriptor, Mapping):
        wrapper_path = Path(str(descriptor.get("ref") or ""))
        state_root = delivery.project_root(value["os_root"], value["domain"], value["project"]) / "state/development-runs" / value["run_id"]
        _require(wrapper_path.is_absolute() and wrapper_path.resolve().is_relative_to(state_root.resolve())
                 and not wrapper_path.is_symlink() and _sha(wrapper_path) == descriptor.get("sha256"), "canonical PR family wrapper changed")
        wrapper, digest = _read(wrapper_path)
        _require(wrapper.get("schema") == "development-stage-receipt/v1" and wrapper.get("stage") == "release_propagation",
                 "canonical PR family wrapper is unqualified")
        path = _contained(packet, packet / str(wrapper.get("receipt") or ""))
        payload, body_digest = _read(path)
        semantic = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        _require(semantic == wrapper.get("evidence_sha256"), "canonical PR family evidence changed")
        files.update({str(wrapper_path): digest, str(path): body_digest})
        consume(payload)
    return families, files


def _budget_history(value: Mapping[str, Any]) -> dict[str, Any]:
    """Read the canonical ledger, including reservations/tombstones, without healing it."""
    from .review_coordination import (load_review_receipt, shared_review_coordination_root, ReviewSubject,
                                     review_family_key, review_chain_key, stable_review_key, REVIEW_RECEIPT_SCHEMA,
                                     ReviewCoordinationError)
    root = shared_review_coordination_root(value["os_root"])
    _require(root == root.resolve(), "canonical review history cannot use redirected directories")
    repository = _provider_repository(value)
    files, charges, owners, scope_files, subjects, limits = {}, {}, {}, {}, {}, {}
    family_subjects, alias_families, charged_families = {}, set(), set()
    candidates = []
    for name in ("receipts", "index", "attempts", "quarantine"):
        directory = root / name
        _require(not directory.is_symlink(), "canonical review history cannot use redirected directories")
        for path in directory.rglob("*.json"):
            candidates.append(path)
            _require(len(candidates) <= 4096, "review ledger inspection exceeds its bounded file budget")
    for path in sorted(candidates):
        _require(not path.is_symlink() and path.stat().st_size <= 1024 * 1024, "review ledger file is unsafe or exceeds its byte budget")
        payload, digest = _read(path)
        subject = payload.get("subject")
        _require(isinstance(subject, Mapping) and subject.get("repository"), "unidentified review history blocks reconciliation")
        raw_name = str(subject["repository"]).removeprefix("git:github.com/").removeprefix("github:").casefold()
        provider_hint = re.fullmatch(r"github:([^#]+)#([1-9][0-9]*)", str(subject.get("pull_request") or ""))
        if (raw_name != repository and str(subject["repository"]).casefold() != str(value["repository"]["id"]).casefold()
                and not (provider_hint and provider_hint[1].casefold() == repository)):
            _require(provider_hint or "/" in raw_name, "review history has ambiguous catalog/provider repository identity")
            continue
        if payload.get("schema") == "auto-dev-review-index/v1" and payload.get("budget_consumed") is True:
            receipt_path = Path(str(payload.get("receipt_ref") or ""))
            _require(receipt_path.is_absolute() and not receipt_path.is_symlink()
                     and receipt_path.resolve().is_relative_to(root / "receipts") and receipt_path.is_file(),
                     "review budget history has a missing charged receipt; separate audited recovery is required")
        if payload.get("schema") == REVIEW_RECEIPT_SCHEMA:
            try:
                payload = load_review_receipt(path)
            except ReviewCoordinationError as exc:
                raise delivery.DevelopmentDeliveryError("canonical review ledger proof is unqualified") from exc
            owner = _review_owner(value, payload, repository)
            if owner:
                identity, proof_files = owner
                owners.setdefault(payload["family_key"], {})[identity["canonical_work_id"]] = identity
                scope_files.update(proof_files)
        files[str(path)] = digest
        charged = payload.get("mode") in {"full", "delta"} and (payload.get("budget_consumed") is True or payload.get("outcome") in {"clean", "findings"})
        if charged or payload.get("schema") == REVIEW_RECEIPT_SCHEMA:
            try:
                model = ReviewSubject.from_mapping(payload["subject"])
            except ReviewCoordinationError as exc:
                raise delivery.DevelopmentDeliveryError("review history subject is unqualified") from exc
            family = str(payload.get("family_key") or "")
            _require(family == review_family_key(model), "review history has unsupported native family identity")
            identity = {"repository": model.repository, "pull_request": model.pull_request,
                        "provider_family": _provider_family(repository, model.pull_request)}
            _require(family not in family_subjects or family_subjects[family] == identity, "native review family identity changed")
            family_subjects[family] = identity
            subjects[family] = identity["provider_family"]
            if raw_name != repository:
                alias_families.add(family)
        if charged:
            key = str(payload.get("key") or "")
            _require(key and payload.get("family_key") and payload.get("chain_key"), "review charge lacks original family/chain identity")
            try:
                model = ReviewSubject.from_mapping(payload["subject"])
            except ReviewCoordinationError as exc:
                raise delivery.DevelopmentDeliveryError("review charge subject is unqualified") from exc
            _require(payload["family_key"] == review_family_key(model) and payload["chain_key"] == review_chain_key(model)
                     and payload["key"] == stable_review_key(model), "review charge has unsupported or ambiguous family lineage")
            charge = {name: payload[name] for name in ("family_key", "chain_key", "mode")}
            charge["provider_family"] = _provider_family(repository, model.pull_request)
            charge["provider_chain"] = review_chain_key(ReviewSubject(repository, charge["provider_family"], model.base_branch,
                model.base_sha, model.head_sha, model.policy_fingerprint, model.purpose))
            _require(key not in charges or charges[key] == charge, "review history charge identity changed")
            charges[key] = charge
            charged_families.add(payload["family_key"])
            if isinstance(payload.get("budget"), Mapping):
                _require(all(name in payload["budget"] for name in ("absolute_full_reviews_per_family", "delta_reviews_per_chain")),
                         "historical review budget limits are incomplete")
                limits[key] = {name: payload["budget"][name] for name in ("absolute_full_reviews_per_family", "delta_reviews_per_chain")}
    task_families, task_files = _task_family_evidence(value, repository)
    scope_files.update(task_files)
    inherited = set()
    for record in value.get(HISTORY) or []:
        path, previous, digest = _bound(record["plan"], Path(value["work_item"]).resolve())
        _require(previous["review_history"]["root"] == str(root) and previous["review_history"]["repository"] == repository,
                 "historical review scope changed repository or ledger root")
        inherited.update(previous["review_history"]["task_families"])
        scope_files[str(path)] = digest
    relevant, ambiguous = [], []
    related_providers = task_families | {provider for family, provider in subjects.items()
        if family in inherited or value["canonical_work_id"] in owners.get(family, {})}
    for family, provider_family in subjects.items():
        known = owners.get(family, {})
        if provider_family in related_providers:
            if family in alias_families and not known:
                ambiguous.append(family)
            else:
                relevant.append(family)
        elif family in charged_families and not known:
            ambiguous.append(family)
    return {"root": str(root), "repository": repository, "files": files, "charges": charges, "limits": limits,
            "scope_evidence_files": scope_files, "family_owners": owners,
            "task_families": sorted(relevant), "ambiguous_families": sorted(ambiguous), "family_subjects": family_subjects}


def _review_family_subjects(history: Mapping[str, Any]) -> dict[str, Any]:
    """Retain one proven native namespace per provider PR; never re-key charges."""
    _require(not history["ambiguous_families"], "review capacity has ambiguous canonical task/family lineage; separate audited reconciliation is required")
    selected = {family: history["family_subjects"][family] for family in history["task_families"]}
    for provider in {row["provider_family"] for row in selected.values()}:
        _require(len({(row["repository"], row["pull_request"]) for row in selected.values()
                      if row["provider_family"] == provider}) == 1,
                 "unsupported mixed native review identities require separate audited reconciliation")
    return selected


def _budget_available(history: Mapping[str, Any]) -> None:
    from .review_coordination import ReviewBudget
    budget = ReviewBudget()
    _review_family_subjects(history)
    charges = [row for row in history["charges"].values() if row["family_key"] in history["task_families"]]
    family_limits, chain_limits = {}, {}
    for key, row in history["charges"].items():
        raw = history["limits"].get(key, {})
        for name, default, target, identity in (
            ("absolute_full_reviews_per_family", budget.absolute_full_reviews_per_family, family_limits, row["provider_family"]),
            ("delta_reviews_per_chain", budget.delta_reviews_per_chain, chain_limits, row["provider_chain"]),
        ):
            amount = raw.get(name, default)
            _require(type(amount) is int and amount >= 0, "historical review budget quantity is invalid")
            target[identity] = min(target.get(identity, default), amount)
    for family in {row["provider_family"] for row in charges}:
        _require(sum(row["mode"] == "full" for row in charges if row["provider_family"] == family) < family_limits[family],
                 "original absolute review budget remains exhausted; separate audited recovery is required")
    for chain in {row["provider_chain"] for row in charges}:
        _require(sum(row["mode"] == "delta" for row in charges if row["provider_chain"] == chain) < chain_limits[chain],
                 "original review chain remains exhausted; reconciliation cannot reset charges")


def _current_policy(value: Mapping[str, Any]) -> tuple[dict[str, Any], Mapping[str, Any]]:
    profile, source = delivery.load_development_policy_profile(value["os_root"], value["domain"], value["project"])
    selected = delivery.select_development_repository(
        profile, value["repository"]["id"] if profile.get("repository", {}).get("catalog") else None
    )
    selected["repository"] = {**selected["repository"], "id": delivery._normalized_repository_identity(selected["repository"])}
    _require(selected["repository"] == value["repository"], "current policy cannot substitute the task repository/base")
    policy = delivery.resolve_development_policies(value["os_root"], value["domain"], value["project"], selected_profile=selected,
                profile_source=source, include_body=True, context_selection_override=value.get("context_selection"))
    profile = {**selected, "configuration_source": _binding(Path(source))}
    # Reuse the existing selected-profile/fingerprint primitives. This action
    # policy must distinguish review-setting changes even when all five planes
    # and source HEAD are identical. The historical snapshot stays untouched.
    authority = {name: item for name, item in policy["selected_profile"].items() if name != "sha256"}
    authority["reconciliation_action_profile_sha256"] = hashlib.sha256(_bytes(profile)).hexdigest()
    authority["sha256"] = delivery._json_sha256(authority)
    policy["selected_profile"] = authority
    policy["fingerprint"] = delivery._effective_policy_snapshot_fingerprint(policy)
    qualified = delivery._validate_effective_policy_snapshot(policy, require_selected_profile=True)
    _require(isinstance(qualified, Mapping), "current selected action policy is unqualified")
    return policy, profile


def inspect_development_reconciliation(state_file: str | Path) -> dict[str, Any]:
    """Inspect original custody and current policy without writing or declaring success."""
    task, value, _ = _task(state_file)
    accepted = _history_record(task.path)
    policy, profile = _current_policy(value)
    return {"schema": "development-validation-reconciliation-inspection/v1", "task_state": _binding(task.path),
            "state": value["state"], "canonical_work_id": value["canonical_work_id"], "run_id": value["run_id"],
            "historical_policy_fingerprint": value["policy_fingerprint"], "historical_worktree": value["worktree"],
            "historical_files": _historical_files(value), "review_history": _budget_history(value),
            "historical_reference_metadata": _historical_reference_metadata(value),
            "current_policy": policy, "current_policy_sha256": hashlib.sha256(_bytes(policy)).hexdigest(),
            "current_profile_sha256": hashlib.sha256(_bytes(profile)).hexdigest(),
            "project_adapter": profile["validation"].get("reconciliation"), "authority_adopted": accepted is not None,
            "current_evidence_readiness": "not_evaluated_by_inspect"}


def _require_source_ancestor(worktree: Path, original_head: str, head: str) -> None:
    """Git status1 is a valid lineage refusal; other failures are unavailable."""
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", original_head, head],
            cwd=worktree, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise delivery.DevelopmentDeliveryError(
            "registered validation worktree Git identity is unavailable: "
            + type(exc).__name__
        ) from exc
    _require(result.returncode in (0, 1), "registered validation worktree Git identity is unavailable")
    _require(result.returncode == 0, "current source must descend from the original historical worktree head")


def _source(value: Mapping[str, Any], record: Mapping[str, Any]) -> dict[str, Any]:
    project = delivery.project_root(value["os_root"], value["domain"], value["project"])
    _require(isinstance(record, Mapping) and record.get("path") and record.get("name") and record.get("branch"), "current registered worktree selection is incomplete")
    worktree = Path(str(record["path"]))
    _require(worktree.is_absolute() and worktree == worktree.resolve(), "current source worktree must be an exact absolute physical path")
    physical = lambda raw: (Path(raw) if Path(raw).is_absolute() else project / raw).resolve()
    mappings = {str(physical(str(row["path"]))) for row in delivery.worktree_entries_for_project(project)
                if (row.get("id") or row.get("name")) == record["name"] and row.get("status", "active") == "active" and row.get("path")}
    source = Path(value["repository"]["root"]).resolve()
    common = lambda path: (path / _git(path, "rev-parse", "--git-common-dir")).resolve()
    view = {**value, "worktree": dict(record)}
    _require(mappings == {str(worktree)} and worktree != source and common(worktree) == common(source)
             and record.get("repository_id") == value["repository"]["id"]
             and _git(worktree, "branch", "--show-current") == record["branch"]
             and _git(worktree, "config", "--get", "remote.origin.url") == _git(source, "config", "--get", "remote.origin.url")
             and _clean_worktree(view, project, worktree), "current source must be the same repository's clean registered feature worktree")
    original = Path(value["worktree"]["path"]).resolve()
    original_head = _git(original, "rev-parse", "HEAD")
    head = _git(worktree, "rev-parse", "HEAD")
    _require_source_ancestor(worktree, original_head, head)
    return {"worktree": dict(record), "head_sha": head, "tree_sha": _git(worktree, "rev-parse", "HEAD^{tree}"),
            "parents": _git(worktree, "show", "-s", "--format=%P", "HEAD").split(),
            "original_worktree_observation": {"path": str(original), "head_sha": original_head,
                "relationship": "observed ancestor of current source; not a claim about historical test execution"}}


def _qualify(value: Mapping[str, Any], source: Mapping[str, Any], policy: Mapping[str, Any], profile: Mapping[str, Any],
             proof: Mapping[str, Any], packet: Path) -> dict[str, Any]:
    _review_fallback(profile)
    adapter = profile.get("validation", {}).get("reconciliation")
    _require(isinstance(adapter, Mapping) and set(adapter) == {"adapter", "actions", "max_age_seconds", "claims"},
             "a separately configured project reconciliation proof adapter is required")
    _require(adapter["adapter"] == COMMAND_ADAPTER and adapter["claims"] == ["configured_commands_only"],
             "project qualification adapter or native/full95 claims are unsupported; no eligibility is inferred")
    _require(isinstance(adapter["actions"], list) and adapter["actions"] and set(adapter["actions"]) <= {"pr_create", "review"}
             and type(adapter["max_age_seconds"]) is int and 0 < adapter["max_age_seconds"] <= 86400, "project action/freshness authority is invalid")
    policy_sha = hashlib.sha256(_bytes(policy)).hexdigest()
    expected = {"task_state_ref": value["_task_state_ref"], "canonical_work_id": value["canonical_work_id"], "ticket": value["ticket"],
                "run_id": value["run_id"], "repository_id": value["repository"]["id"], "worktree": source["worktree"]["path"],
                "source_branch": source["worktree"]["branch"], "head_sha": source["head_sha"], "tree_sha": source["tree_sha"],
                "policy_fingerprint": policy["fingerprint"], "policy_sha256": policy_sha,
                "profile_sha256": hashlib.sha256(_bytes(profile)).hexdigest()}
    _require(proof.get("schema") == PROOF_SCHEMA and proof.get("adapter") == COMMAND_ADAPTER
             and proof.get("claims") == adapter["claims"] and all(proof.get(key) == item for key, item in expected.items()),
             "project proof task/run/repository/source/policy identity does not match current action")
    verified = _timestamp(proof.get("verified_at"))
    now = datetime.now(timezone.utc)
    _require(0 <= (now - verified).total_seconds() <= adapter["max_age_seconds"], "current project qualification is stale or future-dated")
    view = {**value, "worktree": source["worktree"], "policy_fingerprint": policy["fingerprint"]}
    # Existing Python/Node runtime provenance is retained verbatim. In particular,
    # an unsupported native launcher or unqualified Python closure fails closed.
    _commands(proof, view, packet, Path(source["worktree"]["path"]), profile, source["head_sha"])
    for run in proof["validation_runs"]:
        _, terminal, _ = _bound(run["terminal"], packet)
        _require(0 <= (now - _timestamp(terminal["finished_at"])).total_seconds() <= adapter["max_age_seconds"], "current executed command evidence is stale")
    return {"status": "passed", "adapter": COMMAND_ADAPTER, "claims": ["configured_commands_only"],
            "actions": adapter["actions"], "native_full95_qualified": False}


def _review_fallback(profile: Mapping[str, Any]) -> str:
    review = profile.get("review", {})
    _require(isinstance(review, Mapping), "current review policy is malformed")
    opposing = review.get("opposing_harness", {})
    _require(isinstance(opposing, Mapping), "current opposing review policy is malformed")
    fallback = opposing.get("unavailable_policy", "block")
    _require(fallback in {"block", "continue_with_receipt"}, "current review unavailable policy is unsupported")
    return fallback


def plan_development_reconciliation(state_file: str | Path, *, request_file: str | Path, idempotency_key: str) -> dict[str, Any]:
    """Build a deterministic fully checked plan; no task, event or projection writes."""
    task, current, packet = _task(state_file)
    original = task.path.read_bytes()
    _require(json.loads(original) == current, "reconciliation predecessor changed during inspection")
    _require(current.get("state") != "ready_for_merge", "ready_for_merge revalidation is unsupported; the historical milestone must remain intact")
    _require(current.get("state") in {"local_validation", "pr_open"} and not current.get("failure") and not current.get("terminal_revision")
             and not current.get("deployed_revision"), "reconciliation requires an active pre-merge validation task")
    accepted = _history_record(task.path)
    _require(isinstance(idempotency_key, str) and idempotency_key.strip(), "reconciliation requires an idempotency identity")
    _require(task.ledger.is_file() and not task.ledger.is_symlink(), "original task event history is missing or redirected")
    _unused_event_key(task, current, idempotency_key)
    request_path = _contained(packet, Path(request_file).resolve())
    request, request_sha = _read(request_path)
    _require(request.get("schema") == "development-validation-reconciliation-request/v1" and request.get("predecessor_sha256") == _sha(task.path), "wrong reconciliation predecessor or request schema")
    lease = current.get("lease") or {}
    _require(isinstance(lease.get("owner"), str) and lease["owner"] and request.get("owner") == lease["owner"]
             and _timestamp(lease.get("until")) > datetime.now(timezone.utc), "current reconciliation owner/lease is missing, changed or expired")
    source = _source(current, request.get("worktree"))
    if accepted:
        prior_record, prior_plan = accepted
        _require(_git(Path(source["worktree"]["path"]), "merge-base", prior_plan["current_source"]["head_sha"], source["head_sha"])
                 == prior_plan["current_source"]["head_sha"], "successor source must descend from the accepted current source")
    policy, profile = _current_policy(current)
    _require(request.get("current_policy_fingerprint") == policy["fingerprint"], "current action policy changed or was substituted")
    proof_path, proof, proof_sha = _bound(request.get("project_proof"), packet)
    qualification = _qualify({**current, "_task_state_ref": str(task.path)}, source, policy, profile, proof, packet)
    if accepted:
        _require(source != prior_plan["current_source"] or policy != prior_plan["current_policy"]
                 or profile != prior_plan["current_profile"] or proof_sha != prior_plan["project_proof"]["sha256"],
                 "current authority is already recorded; replay its exact plan")
    budget = _budget_history(current)
    historical_files = _historical_files(current)
    _require(request.get("historical_files_sha256") == hashlib.sha256(_bytes(historical_files)).hexdigest()
             and request.get("review_history_sha256") == hashlib.sha256(_bytes(budget)).hexdigest(),
             "inspected historical receipt/budget bindings changed or were substituted")
    _budget_available(budget)
    events = task.ledger.read_bytes() if task.ledger.exists() else b""
    plan = {"schema": PLAN_SCHEMA, "idempotency_key": idempotency_key, "task_state_ref": str(task.path),
            "predecessor_sha256": hashlib.sha256(original).hexdigest(), "request": {"path": str(request_path), "sha256": request_sha},
            "project_proof": {"path": str(proof_path), "sha256": proof_sha}, "current_source": source,
            "current_policy": policy, "current_profile": profile, "qualification": qualification, "historical_files": historical_files,
            "historical_reference_metadata": _historical_reference_metadata(current),
            "original_event_prefix": {"bytes": len(events), "sha256": hashlib.sha256(events).hexdigest()},
            "review_history": budget, "owner": lease["owner"], "historical_receipt_count": len(current["receipts"])}
    plan["predecessor_reconciliation"] = prior_record["plan"] if accepted else None
    _check_plan_custody(task, current, packet, plan)
    return plan


def _unused_event_key(task: delivery.TaskState, current: Mapping[str, Any], key: str) -> None:
    ledgers = [task.ledger]
    if current.get("rollup_ledger"):
        ledgers.append(Path(current["rollup_ledger"]))
    for path in set(ledgers):
        if path.is_file():
            _require(path.stat().st_size <= 64 * 1024 * 1024, "event ledger exceeds its bounded inspection budget")
            try:
                events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
            except (ValueError, TypeError) as exc:
                raise delivery.DevelopmentDeliveryError("historical event ledger is malformed") from exc
            _require(all(isinstance(row, Mapping) and row.get("idempotency_key") != key for row in events),
                     "reconciliation idempotency key already belongs to an existing event")


def _check_plan_custody(task: delivery.TaskState, current: Mapping[str, Any], packet: Path, plan: Mapping[str, Any]) -> None:
    """Recheck external inputs after proof parsing and immediately before adoption."""
    _require(_sha(task.path) == plan["predecessor_sha256"], "reconciliation predecessor changed during validation")
    _bound(plan["request"], packet)
    source = _source(current, plan["current_source"]["worktree"])
    policy, profile = _current_policy(current)
    _require(source == plan["current_source"] and policy == plan["current_policy"] and profile == plan["current_profile"],
             "current source/policy/profile changed during validation")
    _, proof, _ = _bound(plan["project_proof"], packet)
    _qualify({**current, "_task_state_ref": str(task.path)}, source, policy, profile, proof, packet)
    _require(_historical_files(current) == plan["historical_files"] and _budget_history(current) == plan["review_history"],
             "historical receipt/budget changed during validation")
    _require(_historical_reference_metadata(current) == plan["historical_reference_metadata"], "historical reference identities changed")
    events = task.ledger.read_bytes() if task.ledger.exists() else b""
    prefix = plan["original_event_prefix"]
    _require(len(events) == prefix["bytes"] and hashlib.sha256(events).hexdigest() == prefix["sha256"],
             "historical event ledger changed during validation")
    _unused_event_key(task, current, plan["idempotency_key"])
    _require(_timestamp(current["lease"]["until"]) > datetime.now(timezone.utc), "reconciliation owner lease expired during validation")
    _require(_sha(task.path) == plan["predecessor_sha256"], "reconciliation predecessor changed during final validation")


@contextmanager
def _review_locks(history: Mapping[str, Any]) -> Iterator[None]:
    with ExitStack() as stack:
        for family in history["task_families"]:
            path = Path(history["root"]) / ".locks" / (family + ".lock")
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = stack.enter_context(path.open("a+"))
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise delivery.DevelopmentDeliveryError("an original review family is active; reconciliation must wait") from exc
        yield


def _history_record(state_file: str | Path, *, require_event: bool = True) -> tuple[dict[str, Any], dict[str, Any]] | None:
    task = delivery.TaskState(Path(state_file).expanduser().resolve())
    current, _ = _read(task.path)
    history = current.get(HISTORY)
    rows = current.get("receipts") or []
    receipts = [row for row in rows if isinstance(row, Mapping) and row.get("kind") == "validation_reconciliation"]
    if history is None and not receipts:
        if task.ledger.exists():
            _require(not any(json.loads(line).get("type") == "development.validation.reconciled"
                         for line in task.ledger.read_text().splitlines() if line.strip()), "accepted reconciliation markers were removed from task history")
        return None
    task, current, packet = _task(state_file)
    _require(isinstance(rows, list) and all(isinstance(row, Mapping) for row in rows), "historical receipt list changed")
    events = task.ledger.read_bytes()
    matching = [json.loads(line) for line in events.decode().splitlines() if line.strip()
                and json.loads(line).get("type") == "development.validation.reconciled"]
    _require(isinstance(history, list) and bool(history) and len(history) == len(receipts)
             and len({row.get("idempotency_key") for row in history if isinstance(row, Mapping)}) == len(history),
             "reconciliation marker/history was removed or is ambiguous")
    allowed_event_counts = {len(history)} if require_event else {len(history), len(history) - 1}
    _require(len(matching) in allowed_event_counts, "accepted reconciliation event is missing or changed; replay the same apply to repair")
    budgets = _budget_history(current)
    prior = None
    for index, record in enumerate(history):
        _require(isinstance(record, Mapping) and record.get("schema") == SCHEMA
                 and record.get("task_state_ref") == str(task.path), "invalid reconciliation history identity")
        _, original, _ = _bound(record.get("original_task"), packet)
        _, plan, _ = _bound(record.get("plan"), packet)
        _, validation, _ = _bound(record.get("current_validation"), packet)
        _require(record["original_task"]["sha256"] == plan["predecessor_sha256"] and plan["task_state_ref"] == str(task.path)
                 and plan.get("predecessor_reconciliation") == prior, "original task snapshot does not bind the accepted predecessor chain")
        _bound(plan["request"], packet)
        _, proof, _ = _bound(plan["project_proof"], packet)
        _, policy, _ = _bound(record.get("current_policy"), packet)
        _require(policy == plan["current_policy"], "accepted current policy snapshot changed")
        raw_configuration = record.get("configuration_snapshot")
        _require(isinstance(raw_configuration, Mapping), "accepted current configuration snapshot is missing")
        config_path = _contained(packet, Path(raw_configuration["path"]))
        _require(config_path.is_file() and _sha(config_path) == raw_configuration["sha256"]
                 == plan["current_profile"]["configuration_source"]["sha256"], "accepted current configuration bytes changed")
        _require(all(current.get(key) == original.get(key) for key in IMMUTABLE_FIELDS)
                 and original.get(HISTORY, []) == history[:index]
                 and current["receipts"][:len(original["receipts"])] == original["receipts"]
                 and receipts[index].get("ref") == record["current_validation"]["path"]
                 and receipts[index].get("sha256") == record["current_validation"]["sha256"]
                 and receipts[index].get("recorded_at") == record["recorded_at"], "historical task/receipt identity changed")
        for key, count in original.get("attempts", {}).items():
            _require(type(count) is int and type(current.get("attempts", {}).get(key)) is int and current["attempts"][key] >= count, "historical retry charges were reset")
        for path, digest in plan["historical_files"].items():
            _require(_sha(Path(path)) == digest, "historical receipt or frozen policy changed after reconciliation")
        prefix = plan["original_event_prefix"]
        _require(hashlib.sha256(events[:prefix["bytes"]]).hexdigest() == prefix["sha256"], "historical event prefix changed")
        event = [item for item in matching if item.get("idempotency_key") == record["idempotency_key"]]
        if require_event or index < len(history) - 1 or event:
            _require(len(event) == 1 and event[0].get("payload", {}).get("plan_sha256") == record["plan"]["sha256"]
                     and event[0].get("payload", {}).get("recorded_at") == record["recorded_at"],
                     "accepted reconciliation event is missing or changed; replay the same apply to repair")
        _require(budgets["root"] == plan["review_history"]["root"] and all(budgets["files"].get(path) == digest
                 for path, digest in plan["review_history"]["files"].items()), "original review receipt/budget history was removed or changed")
        _require(all(_sha(Path(path)) == digest for path, digest in plan["review_history"]["scope_evidence_files"].items()),
                 "original canonical review ownership evidence changed")
        _require(validation.get("stage") == "validation_reconciliation" and validation.get("status") == "passed"
                 and validation.get("evidence") == {**proof, "qualification": plan["qualification"]}
                 and validation.get("verified_at") == proof["verified_at"], "current validation record differs from its accepted plan")
        prior = record["plan"]
    return record, plan


def current_action_validation_authority(state_file: str | Path, *, action: str | None = None) -> dict[str, Any] | None:
    """Resolve explicitly accepted current authority; never change historical TaskState."""
    accepted = _history_record(state_file)
    if accepted is None:
        return None
    record, plan = accepted
    task, current, packet = _task(state_file)
    lease = current.get("lease") or {}
    _require(lease.get("owner") == plan["owner"] and _timestamp(lease.get("until")) > datetime.now(timezone.utc), "current action owner/lease is no longer qualified")
    source = _source(current, plan["current_source"]["worktree"])
    policy, profile = _current_policy(current)
    _require(source == plan["current_source"] and policy == plan["current_policy"] and profile == plan["current_profile"],
             "accepted reconciliation source/current policy/profile is stale")
    _, proof, _ = _bound(plan["project_proof"], packet)
    qualification = _qualify({**current, "_task_state_ref": str(task.path)}, source, policy, profile, proof, packet)
    _require(action is None or action in qualification["actions"], "current reconciliation does not authorize this action")
    history = _budget_history(current)
    native_subjects = _review_family_subjects(history)
    review_fallback = _review_fallback(profile)
    return {"schema": "development-current-action-authority/v1", "path": record["current_validation"]["path"],
            "sha256": record["current_validation"]["sha256"], "status": "passed", "head_sha": source["head_sha"],
            "worktree": source["worktree"], "policy_fingerprint": policy["fingerprint"],
            "policy_receipt": record["current_policy"]["path"], "review_coordination_root": plan["review_history"]["root"],
            "historical_policy_fingerprint": current["policy_fingerprint"], "repository_id": current["repository"]["id"],
            "provider_repository": history["repository"], "review_family_subjects": native_subjects,
            "review_unavailable_policy": review_fallback,
            "profile_sha256": hashlib.sha256(_bytes(profile)).hexdigest(),
            "qualification": qualification}


def current_action_projection(state_file: str | Path) -> dict[str, Any] | None:
    """Project pending source/review honestly; this view grants no action authority."""
    accepted = _history_record(state_file)
    if accepted is None:
        return None
    record, plan = accepted
    try:
        authority = current_action_validation_authority(state_file)
    except delivery.DevelopmentDeliveryError as exc:
        return {"schema": "development-current-action-projection/v1", "status": "unqualified_current_evidence",
                "authority": None, "review_current": False, "reason": str(exc),
                "accepted_plan": record["plan"], "accepted_head_sha": plan["current_source"]["head_sha"]}
    _, current, packet = _task(state_file)
    review_current = False
    ready = [row for row in current.get("receipts", []) if row.get("state") == "ready_for_merge"]
    if ready:
        try:
            _, payload, _ = _bound({"path": ready[-1]["ref"], "sha256": ready[-1]["sha256"]}, packet)
            details = payload["evidence"]
            coordination = Path(str(details.get("review_coordination_receipt") or ""))
            if not coordination.is_absolute():
                coordination = packet / coordination
            _require(not coordination.is_symlink() and coordination.resolve().is_relative_to(Path(authority["review_coordination_root"]) / "receipts")
                     and details.get("subject_revision") == details.get("source_head_sha") == authority["head_sha"]
                     and all(details.get(key) is True for key in ("checks_verified", "reviews_verified", "readback_verified"))
                     and details.get("review_policy_fingerprint", authority["policy_fingerprint"]) == authority["policy_fingerprint"],
                     "historical ready milestone is not current review authority")
            from .review_coordination import assert_exact_head_review_receipt
            assert_exact_head_review_receipt(coordination, head_sha=authority["head_sha"], repository=current["repository"]["id"],
                pull_request=details["pull_request"], policy_fingerprint=authority["policy_fingerprint"])
            review_current = True
        except (delivery.DevelopmentDeliveryError, KeyError, OSError, RuntimeError, ValueError, TypeError):
            review_current = False
    return {"schema": "development-current-action-projection/v1", "status": "source_qualified",
            "authority": authority, "review_current": review_current,
            "review_status": "current" if review_current else "pending_or_unsupported_current_review"}


def review_reconciliation_authority(packet: str | Path, ticket: str) -> dict[str, Any] | None:
    """Resolve the canonical packet's explicit review action for executable consumers."""
    packet = Path(packet).resolve()
    manifest_path = packet / "autodev.json"
    if not manifest_path.is_file():
        return None
    manifest, _ = _read(manifest_path)
    reference = (manifest.get("delivery") or {}).get("task_state_ref")
    if not reference:
        return None
    task, current, owned_packet = _task(reference)
    _require(owned_packet == packet and current["ticket"] == ticket, "review reconciliation packet/task/ticket identity differs")
    return current_action_validation_authority(task.path, action="review")


def current_action_task_view(current: Mapping[str, Any], *, action: str) -> dict[str, Any]:
    """A read-only action projection; callers must never persist this as task state."""
    if not current.get(HISTORY):
        return dict(current)
    state_file = current[HISTORY][-1]["task_state_ref"]
    _require(dict(current) == delivery.TaskState(Path(state_file).resolve()).read(),
             "current task action view must come from the exact canonical task, not a substituted mapping")
    authority = current_action_validation_authority(state_file, action=action)
    return {**current, "worktree": authority["worktree"], "policy_fingerprint": authority["policy_fingerprint"],
            "policy_receipt": authority["policy_receipt"], "current_action_authority": authority}


def pr_create_reconciliation_authority(state_file: str | Path, family: Mapping[str, Any]) -> dict[str, Any] | None:
    """Require a new PR family to name the explicitly accepted current action."""
    authority = current_action_validation_authority(state_file, action="pr_create")
    if authority is None:
        return None
    _, current, _ = _task(state_file)
    evidence = family.get("evidence") or {}
    repository = str(current["repository"]["id"])
    names = {repository, repository.removeprefix("git:github.com/").removeprefix("github:")}
    heads = {evidence[key] for key in ("head_sha", "source_head_sha", "subject_revision") if evidence.get(key)}
    _require(heads == {authority["head_sha"]} and evidence.get("ticket") == current["ticket"]
             and evidence.get("repository") in names and evidence.get("source_branch") == authority["worktree"]["branch"]
             and evidence.get("policy_fingerprint") == authority["policy_fingerprint"], "PR family does not match accepted current reconciliation")
    return authority


def apply_development_reconciliation(state_file: str | Path, *, plan_file: str | Path, plan_sha256: str,
                                     execute: bool = False) -> dict[str, Any]:
    """CAS one append-only acceptance and repair owning projections on exact replay."""
    task, current, packet = _task(state_file)
    plan_path, plan, digest = _bound({"path": str(plan_file), "sha256": plan_sha256}, packet)
    _require(plan.get("schema") == PLAN_SCHEMA and plan.get("task_state_ref") == str(task.path), "reconciliation plan belongs to another task")
    if not execute:
        return {"applied": False, "plan": _binding(plan_path), "expected_predecessor": plan["predecessor_sha256"]}
    replay = superseded = False
    with delivery._file_lock(task.path.with_suffix(task.path.suffix + ".lock")), _review_locks(plan["review_history"]):
        current = task.read()
        accepted = _history_record(task.path, require_event=False) if current.get(HISTORY) else None
        matched = [row for row in current.get(HISTORY, []) if row["idempotency_key"] == plan["idempotency_key"]]
        if matched:
            record = matched[0]
            _, recorded_plan, _ = _bound(record["plan"], packet)
            _require(record["plan"]["sha256"] == digest and recorded_plan == plan, "reconciliation idempotency collision")
            latest_record, latest_plan = accepted
            superseded = record != latest_record
            if superseded:
                _history_record(task.path)  # An old replay cannot repair a missing successor event.
            source = _source(current, latest_plan["current_source"]["worktree"])
            policy, profile = _current_policy(current)
            _require(source == latest_plan["current_source"] and policy == latest_plan["current_policy"] and profile == latest_plan["current_profile"],
                     "accepted reconciliation source/current policy/profile is stale")
            _, proof, _ = _bound(latest_plan["project_proof"], packet)
            _qualify({**current, "_task_state_ref": str(task.path)}, source, policy, profile, proof, packet)
            replay = True
        else:
            _require(_sha(task.path) == plan["predecessor_sha256"], "stale reconciliation predecessor; no mutation")
            expected = plan_development_reconciliation(task.path, request_file=plan["request"]["path"], idempotency_key=plan["idempotency_key"])
            _require(expected == plan, "current source/policy/evidence/budget changed since planning")
            raw_task = task.path.read_bytes()
            policy_raw = _bytes(plan["current_policy"])
            proof_path, proof, _ = _bound(plan["project_proof"], packet)
            validation = {"schema": "development-stage-evidence/v1", "state": "local_validation", "stage": "validation_reconciliation",
                          "status": "passed", "summary": "Current project adapter verified the exact configured commands; historical Develop remains unchanged.",
                          "verified_at": proof["verified_at"], "evidence": {**proof, "qualification": plan["qualification"]}}
            # Validate all output containment/collisions before committing authority.
            original_path = _snapshot(packet, "original-task-" + plan["predecessor_sha256"] + ".json", raw_task)
            stored_plan = _snapshot(packet, "plan-" + digest + ".json", plan_path.read_bytes())
            policy_path = _snapshot(packet, "policy-" + hashlib.sha256(policy_raw).hexdigest() + ".json", policy_raw)
            validation_path = _snapshot(packet, "validation-" + digest + ".json", _bytes(validation))
            configuration = plan["current_profile"]["configuration_source"]
            configuration_raw = Path(configuration["path"]).read_bytes()
            _require(hashlib.sha256(configuration_raw).hexdigest() == configuration["sha256"], "current configuration bytes changed before freezing")
            configuration_path = _snapshot(packet, "configuration-" + configuration["sha256"] + ".yml", configuration_raw)
            recorded = delivery.utc_now()
            record = {"schema": SCHEMA, "task_state_ref": str(task.path), "idempotency_key": plan["idempotency_key"],
                      "original_task": _binding(original_path), "plan": _binding(stored_plan), "current_policy": _binding(policy_path),
                      "current_validation": _binding(validation_path), "configuration_snapshot": _binding(configuration_path),
                      "recorded_at": recorded}
            current.setdefault(HISTORY, []).append(record)
            current.setdefault("receipts", []).append({"state": "validation_reconciliation", "kind": "validation_reconciliation",
                         "ref": str(validation_path), "sha256": _sha(validation_path), "recorded_at": recorded})
            current["updated_at"] = recorded
            _check_plan_custody(task, task.read(), packet, plan)
            delivery._atomic_json(task.path, current)
    task.emit(event_type="development.validation.reconciled", idempotency_key=plan["idempotency_key"],
              payload={"ticket": current["ticket"], "head_sha": plan["current_source"]["head_sha"],
                       "plan_sha256": digest, "recorded_at": record["recorded_at"]})
    delivery._refresh_portfolio_state(task.path)
    _require(delivery._sync_auto_dev_projection(task.path) is not None, "current authority recorded; owning projection requires repair with the same apply")
    delivery._sync_canonical_task_progress(task.path)
    return {"applied": True, "replayed": replay, "superseded": superseded, "task": task.read(),
            "current_action_authority": current_action_validation_authority(task.path)}
