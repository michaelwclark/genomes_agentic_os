"""Locked successor CAS and replayable fenced projections for development tasks."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping
import uuid

from .development_delivery import (
    _atomic_json, _file_lock, _task_provisioning_admission_lock,
    _sync_auto_dev_projection, append_event, utc_now,
)
from .development_successor_binding import (
    EFFECTS, _reject, _review_policy_delta, contained, digest, family_admission_lock,
    observe_successor, proof, read_json, validate_schema,
)
from .review_coordination import (
    ReviewSubject, SUCCESSOR_POLICY_REVIEW_PURPOSE, shared_review_coordination_root,
)
from .state import work_items
from .state.db import connect, default_db_path

BINDING_FIELDS = ("worktree", "runtime", "policy_receipt", "policy_fingerprint",
                  "policy_sources", "context_selection", "pull_request_subject")
BOOKKEEPING = ("active_successor_binding", "successor_bindings", "subject_revision",
               "validation_pending_binding", "updated_at")


def _commit_task(path: Path, value: Mapping[str, Any]) -> None:
    """Durably replace the locked task after CAS, leaving a recoverable outbox."""
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write((json.dumps(dict(value), indent=2, sort_keys=True) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        with _directory_handle(path.parent) as descriptor:
            os.fsync(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def _reference(packet: Path, path: Path, value: Mapping[str, Any]) -> dict[str, str]:
    """Exclusively persist a deterministic immutable native proof and fsync it."""
    path = contained(packet, str(path.relative_to(packet)))
    raw = (json.dumps(dict(value), indent=2, sort_keys=True) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if path.read_bytes() != raw:
            _reject("immutable binding proof collision")
    with _directory_handle(path.parent) as descriptor:
        os.fsync(descriptor)
    return {"packet_ref": str(path.relative_to(packet)),
            "sha256": hashlib.sha256(raw).hexdigest(), "schema": str(value["schema"])}


class _directory_handle:
    """Close the directory descriptor used to make an immutable create durable."""
    def __init__(self, path: Path) -> None:
        self.path = path
        self.descriptor: int | None = None

    def __enter__(self) -> int:
        self.descriptor = os.open(self.path, os.O_RDONLY)
        return self.descriptor

    def __exit__(self, *_args: Any) -> None:
        if self.descriptor is not None:
            os.close(self.descriptor)


def _family(current: Mapping[str, Any], packet: Path, ref: Mapping[str, Any],
            observation: Mapping[str, Any]) -> None:
    """Anchor the real provider PR to the task's original immutable family wrapper."""
    path, family, sha = proof(packet, ref)
    descriptor = current.get("stage_receipts", {}).get("release_propagation", {})
    wrapper_path = Path(str(descriptor.get("ref") or ""))
    wrapper, wrapper_sha = read_json(wrapper_path)
    if (wrapper_sha != descriptor.get("sha256") or wrapper.get("schema") != "development-stage-receipt/v1"
            or wrapper.get("stage") != "release_propagation" or wrapper.get("evidence_sha256") != digest(family)
            or contained(packet, str(wrapper.get("receipt") or "")) != path):
        _reject("family proof is not the original task-bound PR Create authority")
    evidence = family.get("evidence", {})
    provider = observation["provider"]
    targets = evidence.get("targets", [])
    matching = [row for row in targets if isinstance(row, Mapping)
                and row.get("base_branch") == provider["base_branch"]
                and row.get("pr_number") == provider["number"]]
    if (family.get("schema") != "development-stage-evidence/v1"
            or family.get("state") != "release_propagation" or family.get("status") not in {"verified", "passed", "completed"}
            or evidence.get("ticket") not in {None, current["ticket"]}
            or evidence.get("family_complete") is not True or len(matching) != 1
            or matching[0].get("repository") != provider["repository"]
            or matching[0].get("url") != provider["url"]
            or matching[0].get("head_branch") != provider["source_branch"]):
        _reject("provider PR does not belong to the task's real original family")


def _match_inputs(current: Mapping[str, Any], packet: Path, request: Mapping[str, Any],
                  observation: Mapping[str, Any]) -> None:
    """Compare every caller assertion to independent native observations."""
    if request["expected"] != observation["expected"]:
        _reject("stale task, portfolio, projection or canonical predecessor")
    identity = {key: current[key] for key in ("run_id", "ticket", "canonical_work_id", "domain", "project", "work_item")}
    identity["repository_id"] = current["repository"]["id"]
    if request["identity"] != identity:
        _reject("same-task identity changed")
    old = request["predecessor"]
    if old["source_head"] != observation["protected_boundary"]["head"] or old["policy_fingerprint"] != current["policy_fingerprint"]:
        _reject("protected predecessor head or policy changed")
    comparisons = (
        (old["protected_boundary_snapshot"], observation["protected_boundary"]),
        (old["historical_receipt_inventory"], observation["historical_receipts"]),
        (old["original_runtime_record"], observation["original_runtime"]),
        (request["successor"]["registry_snapshot"], observation["registry"]),
        (request["successor"]["runtime"]["native_readback"], observation["runtime"]),
        (request["pull_request"]["provider_readback"], observation["provider"]),
        (request["pull_request"]["remote_ref_readback"], observation["remote"]),
        (request["policy"]["new_effective_policy"], observation["policy"]),
        (request["review_lineage"]["coordinator_inventory"], observation["coordinator"]),
        (request["review_lineage"]["attempt_and_budget_inventory"], observation["coordinator"]),
    )
    for ref, expected in comparisons:
        if proof(packet, ref)[1] != expected:
            _reject("caller proof disagrees with native source/runtime/policy/lineage")
    successor = request["successor"]
    record = observation["registry"]["worktree"]
    provider = observation["provider"]
    if not set(current["worktree"]).issubset(record):
        _reject("successor worktree record drops predecessor contract keys")
    if (successor["registry_id"] != record["name"] or successor["real_path"] != record["path"]
            or successor["local_source_branch"] != record["branch"]
            or successor["expected_head"] != provider["head"] or successor["expected_base_sha"] != provider["base_sha"]
            or any(successor["runtime"][key] != observation["runtime"][key]
                   for key in ("provider", "identity", "namespace"))):
        _reject("successor registry/local/runtime/source assertion changed")
    pr = request["pull_request"]
    if (pr["repository_id"] != current["repository"]["id"] or pr["base_branch"] != provider["base_branch"]
            or pr["base_sha"] != provider["base_sha"] or pr["source_head"] != provider["head"]
            or pr["provider_source_branch"] != provider["source_branch"]
            or request["policy"]["new_fingerprint"] != observation["policy"]["fingerprint"]):
        _reject("provider branch/head/base or effective policy assertion changed")
    lineage = request["review_lineage"]
    if (lineage["existing_shared_coordinator_root"] != observation["coordinator"]["root"]
            or lineage["family_key"] != observation["coordinator"]["family_key"]):
        _reject("shared review coordinator or family changed")
    _family(current, packet, pr["family_predecessor"], observation)


def _match(current: Mapping[str, Any], packet: Path, request: Mapping[str, Any],
           observation: Mapping[str, Any]) -> None:
    """Require both native input identity and qualified policy review before binding."""
    _match_inputs(current, packet, request, observation)
    provider = observation["provider"]
    subject = ReviewSubject(provider["repository"], "github:" + provider["repository"] + "#" + str(provider["number"]),
                            provider["base_branch"], provider["base_sha"], provider["head"],
                            observation["policy"]["fingerprint"], SUCCESSOR_POLICY_REVIEW_PURPOSE)
    review = proof(packet, request["policy"]["delta_review"])[1]
    _review_policy_delta(packet, review, observation["policy_delta"],
                         shared_review_coordination_root(current["os_root"]), subject)


def policy_review_identity(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Bind source and task evidence without counting the review's own coordinator writes."""
    return {key: deepcopy(observation[key]) for key in (
        "expected", "protected_boundary", "historical_receipts", "original_runtime",
        "registry", "runtime", "provider", "remote", "ancestry", "policy", "old_policy_sha256", "policy_delta")}


def successor_policy_review_request(state_file: str | Path, request_file: str | Path) -> dict[str, Any]:
    """Admit a read-only full review of a native policy delta before any task CAS.

    This only supplies a subject to the existing shared review coordinator. A
    model verdict is still required; this function grants no binding or gate.
    """
    state_path = Path(state_file).resolve()
    initial, _ = read_json(state_path)
    packet = Path(initial["work_item"]).resolve()
    request_path = Path(request_file).absolute()
    if not request_path.is_relative_to(packet):
        _reject("policy review request must be in the original packet")
    request_path = contained(packet, str(request_path.relative_to(packet)))
    request, request_sha = read_json(request_path)
    validate_schema(request, "development-successor-binding-request.schema.json")
    observation = observe_successor(state_path, registry_id=request["successor"]["registry_id"],
                                    pull_request=request["pull_request"]["number"])
    current = observation["task"]
    _match_inputs(current, Path(current["work_item"]), request, observation)
    return {"schema": "development-successor-policy-review-source/v1",
            "task_state_ref": str(state_path), "request_ref": str(request_path),
            "request_sha256": request_sha, "registry_id": request["successor"]["registry_id"],
            "pull_request": request["pull_request"]["number"],
            "identity": policy_review_identity(observation)}


def _receipt(state_path: Path, current: Mapping[str, Any], request: Mapping[str, Any],
             request_sha: str, key: str, observation: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Persist a self-hash-free immutable intent before the single task CAS."""
    packet = Path(current["work_item"])
    binding_id = digest({"request_sha256": request_sha, "idempotency_key": key,
                         "predecessor": observation["expected"]["task_sha256"]})
    folder = packet / "artifacts/development-delivery/successor-bindings" / binding_id
    def save(name: str, value: Mapping[str, Any]) -> dict[str, str]:
        return _reference(packet, folder / (name + ".json"), value)
    previous = save("predecessor-state", {"schema": "development-predecessor-task/v1", "task": current})
    policy = save("effective-policies", observation["policy"])
    provider = observation["provider"]
    subject = {"provider": "github", "pull_request": "github:" + provider["repository"] + "#" + str(provider["number"]),
               "url": provider["url"], "repository": current["repository"]["id"],
               "base_branch": provider["base_branch"], "base_sha": provider["base_sha"],
               "source_branch": provider["source_branch"], "source_head_sha": provider["head"],
               "author_identity": provider["author_identity"], "author_kind": "ours"}
    patch = {"worktree": observation["registry"]["worktree"],
             "runtime": {key: observation["runtime"][key] for key in current["runtime"]},
             "policy_receipt": str(packet / policy["packet_ref"]),
             "policy_fingerprint": observation["policy"]["fingerprint"],
             "policy_sources": {plane: [row["source_ref"] for row in value["sources"]]
                                for plane, value in observation["policy"]["planes"].items()},
             "context_selection": observation["policy"].get("context_selection"),
             "pull_request_subject": subject}
    patch_ref = save("task-patch", {"schema": "development-successor-task-patch/v1", "patch": patch})
    original_policy, _ = read_json(Path(current["policy_receipt"]))
    # A replay after an intent-only crash reuses the original instant.
    receipt_path = folder / "receipt.json"
    recorded = read_json(receipt_path)[0]["recorded_at"] if receipt_path.exists() else utc_now()
    receipt = {
        "schema": "development-successor-binding-receipt/v1", "binding_id": binding_id,
        "idempotency_key": key, "request_sha256": request_sha, "recorded_at": recorded,
        "task": {"state_path": str(state_path), "run_id": current["run_id"], "ticket": current["ticket"],
                 "canonical_work_id": current["canonical_work_id"], "work_item": str(packet),
                 "repository_id": current["repository"]["id"]},
        "predecessor": {"raw_state_sha256": observation["expected"]["task_sha256"],
            "raw_portfolio_sha256": observation["expected"]["portfolio_sha256"],
            "raw_autodev_sha256": observation["expected"]["autodev_sha256"],
            "canonical_work_row_revision": observation["expected"]["canonical_work_row_revision"],
            "full_state_snapshot": previous, "protected_boundary": save("protected-boundary", observation["protected_boundary"]),
            "original_policy": save("original-policy", original_policy),
            "historical_receipts": save("historical-receipts", observation["historical_receipts"])},
        "successor": {"worktree_record": save("registry", observation["registry"]),
            "runtime_native_identity": save("runtime", observation["runtime"]),
            "local_source_branch": patch["worktree"]["branch"],
            "provider_source_branch": provider["source_branch"], "head_sha": provider["head"],
            "base_sha": provider["base_sha"],
            "pull_request_subject": save("provider-subject", {"schema": "development-successor-pr-subject/v1", **subject}),
            "policy_receipt": policy, "policy_delta": save("policy-delta", observation["policy_delta"])},
        "proofs": {"native_admission": patch_ref,
            "accepted_request": save("accepted-request", {"schema": "development-successor-accepted-request/v1",
                "raw_sha256": request_sha, "request": request}),
            "policy_delta_admission": save("policy-delta-admission", proof(packet, request["policy"]["delta_review"])[1]),
            "provider_and_remote_equality": save("provider-remote", {"schema": "development-successor-provider-remote/v1",
                "provider": provider, "remote": observation["remote"]}),
            "real_git_ancestry": save("ancestry", observation["ancestry"]),
            "actual_policy_resolution": policy, "shared_review_lineage": save("review-lineage", observation["coordinator"])},
        "preserved_invariants": {
            "receipts_and_stage_history_sha256": digest({k: current.get(k) for k in ("receipts", "stage_receipts")}),
            "attempts_failures_restarts_sha256": digest({k: v for k, v in current.items()
                if any(word in k for word in ("attempt", "failure", "restart"))}),
            "lease_authorship_and_retry_limits_sha256": digest({k: current.get(k) for k in ("lease", "authorship", "max_attempts")}),
            "original_runtime_history_sha256": digest(current["runtime"]),
            "shared_coordinator_and_budget_inventory_sha256": digest(observation["coordinator"])},
        "effects": {"outbox_id": binding_id, "task_patch_payload_sha256": digest(patch),
                    "required_effects": list(EFFECTS)},
        "resulting_authority": "local_validation; new binding must complete projections, fresh native validation, provider-family continuation and all ordinary review/QA/Finalize gates"}
    validate_schema(receipt, "development-successor-binding-receipt.schema.json")
    ref = save("receipt", receipt)
    return receipt, {"ref": ref, "patch": patch}


def active_binding(current: Mapping[str, Any], *, allow_pending: bool = False) -> dict[str, Any] | None:
    """Verify the immutable chain and current subjects before a consumer uses them."""
    active = current.get("active_successor_binding")
    history = current.get("successor_bindings")
    if active is None and not history:
        return None
    if (not isinstance(active, Mapping) or set(active) != {"binding_id", "receipt", "status"}
            or not isinstance(history, list) or not history or history[-1] != active["receipt"]
            or active["status"] not in {"projections_pending", "bound_validation_pending", "bound"}):
        _reject("active binding/history fence is malformed")
    packet = Path(current["work_item"])
    previous: Mapping[str, Any] | None = None
    keys: set[str] = set()
    for ref in history:
        _, receipt, _ = proof(packet, ref)
        validate_schema(receipt, "development-successor-binding-receipt.schema.json")
        for section in ("predecessor", "successor", "proofs"):
            for value in receipt[section].values():
                if isinstance(value, Mapping) and set(value) == {"packet_ref", "sha256", "schema"}:
                    proof(packet, value)
        _, predecessor, _ = proof(packet, receipt["predecessor"]["full_state_snapshot"])
        snapshot = predecessor.get("task", {})
        identity = receipt["task"]
        if (receipt["idempotency_key"] in keys or identity["run_id"] != current["run_id"]
                or identity["canonical_work_id"] != current["canonical_work_id"]
                or identity["repository_id"] != current["repository"]["id"]
                or identity["work_item"] != str(packet)
                or previous is not None and snapshot.get("successor_bindings", [])[-1:] != [previous]):
            _reject("binding history changed task, family or predecessor")
        keys.add(receipt["idempotency_key"])
        previous = ref
    old_receipts = snapshot.get("receipts", [])
    if (any(current.get(key) != snapshot.get(key) for key in (
                "os_root", "domain", "project", "ticket", "run_id", "canonical_work_id", "work_item", "repository"))
            or current.get("receipts", [])[:len(old_receipts)] != old_receipts
            or current.get("max_attempts") != snapshot.get("max_attempts")
            or current.get("authorship") != snapshot.get("authorship")
            or any(int(current.get("attempts", {}).get(key, -1)) < int(value)
                   for key, value in snapshot.get("attempts", {}).items())):
        _reject("binding lost immutable receipts, attempt history or review/retry authority")
    if receipt["binding_id"] != active["binding_id"]:
        _reject("active binding receipt identity changed")
    _, payload, _ = proof(packet, receipt["proofs"]["native_admission"])
    patch = payload["patch"]
    if (digest(patch) != receipt["effects"]["task_patch_payload_sha256"]
            or any(current.get(key) != value for key, value in patch.items())
            or active["status"] == "projections_pending" and not allow_pending):
        _reject("binding source/policy changed or projections remain pending")
    proof(packet, receipt["successor"]["policy_receipt"])
    if not allow_pending:
        manifest, _ = read_json(packet / "autodev.json")
        delivery = manifest.get("delivery")
        if not isinstance(delivery, Mapping) or delivery.get("active_successor_binding") != active:
            _reject("binding projection fence requires native sync or exact replay")
    if current.get("validation_pending_binding") not in {None, active["binding_id"]}:
        _reject("validation fence belongs to a different binding")
    return receipt


def binding_evidence(current: Mapping[str, Any], evidence: Mapping[str, Any], *,
                     validation: bool = False, verify_provider: bool = True) -> None:
    """Require fresh binding-aware evidence without granting any ordinary gate."""
    receipt = active_binding(current)
    if receipt is None:
        return
    active = current["active_successor_binding"]
    if not validation and current.get("validation_pending_binding"):
        _reject("fresh native validation for this binding is still required")
    expected = {"binding_id": active["binding_id"],
                "binding_receipt_sha256": active["receipt"]["sha256"],
                "local_source_branch": current["worktree"]["branch"],
                "provider_source_branch": current["pull_request_subject"]["source_branch"]}
    if any(evidence.get(key) != value for key, value in expected.items()):
        _reject("stage evidence is stale or lacks the exact local/provider binding")
    if not verify_provider:
        # Post-merge provider/base/ref semantics belong to the ordinary typed
        # Merge/Release/Health gates; a deleted source branch is then legitimate.
        return
    from .development_successor_binding import _provider, git
    subject = current["pull_request_subject"]
    repository = current["repository"]["id"].removeprefix("git:github.com/")
    number = int(subject["pull_request"].rsplit("#", 1)[1])
    tree = Path(current["worktree"]["path"])
    provider = _provider(tree, repository, number)
    head = git(tree, "rev-parse", "HEAD")
    git(tree, "merge-base", "--is-ancestor", subject["source_head_sha"], head)
    if (provider["head"] != head or provider["base_sha"] != subject["base_sha"]
            or provider["source_branch"] != subject["source_branch"]
            or provider["base_branch"] != subject["base_branch"]
            or provider["repository"] != repository or provider["source_repository"] != repository
            or provider["state"] != "open" or provider["merged"]
            or provider["author_identity"] != subject["author_identity"]
            or git(tree, "ls-remote", "--exit-code", "origin", "refs/heads/" + subject["base_branch"]).split()
                != [subject["base_sha"], "refs/heads/" + subject["base_branch"]]
            or git(tree, "ls-remote", "--exit-code", "origin", "refs/heads/" + subject["source_branch"]).split()
                != [head, "refs/heads/" + subject["source_branch"]]):
        _reject("current local/provider publication or base identity changed")


def predecessor_authority(current: Mapping[str, Any], path: Path, sha: str) -> dict[str, Any]:
    """Resolve historical validation under its original immutable policy/worktree."""
    receipt = active_binding(current, allow_pending=True)
    if receipt is None:
        return dict(current)
    packet = Path(current["work_item"])
    snapshot = proof(packet, receipt["predecessor"]["full_state_snapshot"])[1]["task"]
    if any(row.get("ref") == str(path) and row.get("sha256") == sha
           for row in snapshot.get("receipts", []) if isinstance(row, Mapping)):
        return predecessor_authority(snapshot, path, sha)
    return dict(current)


def current_stage_authority(current: Mapping[str, Any], row: Mapping[str, Any]) -> bool:
    """Recognize new-epoch stage evidence while keeping predecessor wrappers immutable."""
    active = current["active_successor_binding"]
    packet = Path(current["work_item"])
    for raw in row.get("receipt_refs", []):
        path = Path(str(raw))
        if not path.is_absolute():
            if path.parts[:1] != ("artifacts",):
                continue
            path = contained(packet, str(path))
        if not path.is_file():
            continue
        payload, _ = read_json(path)
        if payload.get("schema") == "development-stage-receipt/v1":
            path = contained(packet, str(payload.get("receipt") or ""))
            child, sha = read_json(path)
            if digest(child) != payload.get("evidence_sha256"):
                _reject("stage wrapper's immutable evidence changed")
            payload = child
        if payload.get("schema") == "auto-dev-stage-receipt/v1":
            payload = payload.get("evidence_snapshot", {})
        evidence = {**payload, **(payload.get("evidence") or {})}
        if (evidence.get("binding_id") == active["binding_id"]
                and evidence.get("binding_receipt_sha256") == active["receipt"]["sha256"]):
            return True
    return False


def _finish(state_path: Path, receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Idempotently project a committed intent, preserving the original portfolio."""
    current, _ = read_json(state_path)
    if current.get("successor_abandonment", {}).get("status") == "abandoning":
        _reject("pending abandonment requires abandon-successor replay")
    active_binding(current, allow_pending=True)
    packet = Path(current["work_item"])
    binding_id = receipt["binding_id"]
    if current["active_successor_binding"]["status"] == "projections_pending":
        from .development_successor_binding import recheck_pending_sources
        recheck_pending_sources(current, receipt)
    event_key = "successor-binding:" + binding_id
    payload = {"ticket": current["ticket"], "binding_id": binding_id,
               "receipt": current["active_successor_binding"]["receipt"]}
    append_event(state_path.parent / "events.jsonl", event_type="development.successor.bound",
                 idempotency_key=event_key, payload=payload)
    if current.get("rollup_ledger"):
        append_event(Path(current["rollup_ledger"]), event_type="development.successor.bound",
                     idempotency_key=event_key, payload=payload)
    portfolio_path = state_path.parents[2] / "portfolio.json"
    with _file_lock(portfolio_path.with_suffix(".json.lock")):
        portfolio, _ = read_json(portfolio_path)
        pointers = portfolio.get("active_successor_bindings", {})
        rows = [row for row in portfolio.get("tasks", [])
                if isinstance(row, Mapping) and row.get("ticket") == current["ticket"]]
        if (not isinstance(pointers, Mapping) or len(rows) != 1
                or Path(str(rows[0].get("state_ref") or "")).resolve() != state_path.resolve()):
            _reject("portfolio no longer owns this exact task")
        previous = pointers.get(current["ticket"])
        expected = current["active_successor_binding"]["receipt"]
        if previous != expected:
            if previous is not None:
                _reject("portfolio has a foreign successor binding")
            portfolio.setdefault("active_successor_bindings", {})[current["ticket"]] = expected
            _atomic_json(portfolio_path, portfolio)
    connection = connect(default_db_path(current["os_root"]))
    try:
        row = work_items.bind_development_successor(connection, current["canonical_work_id"],
            expected_revision=receipt["predecessor"]["canonical_work_row_revision"],
            binding_id=binding_id, worktree_path=current["worktree"]["path"],
            branch=current["worktree"]["branch"],
            receipt_ref=str(packet / current["active_successor_binding"]["receipt"]["packet_ref"]))
        work_items.write_active_projection(connection, Path(current["os_root"]))
        if row["worktree_path"] != current["worktree"]["path"] or row["branch"] != current["worktree"]["branch"]:
            _reject("canonical outbox readback disagrees")
    finally:
        connection.close()
    if _sync_auto_dev_projection(state_path) is None:
        _reject("Auto-Dev outbox projection requires repair")
    manifest, _ = read_json(packet / "autodev.json")
    delivery = manifest.get("delivery")
    if (not isinstance(delivery, Mapping)
            or delivery.get("active_successor_binding") != current["active_successor_binding"]
            or delivery.get("worktree") != current["worktree"]
            or delivery.get("policy_fingerprint") != current["policy_fingerprint"]):
        _reject("Auto-Dev outbox readback disagrees")
    with _file_lock(state_path.with_suffix(".json.lock")):
        live, _ = read_json(state_path)
        if live != current:
            _reject("task changed during outbox completion")
        if live["active_successor_binding"]["status"] == "projections_pending":
            live["active_successor_binding"]["status"] = "bound_validation_pending"
            _commit_task(state_path, live)
    # Projection status must agree with the final authoritative fence as well.
    if _sync_auto_dev_projection(state_path) is None:
        _reject("final Auto-Dev fence projection requires repair")
    return {"task": read_json(state_path)[0], "status": read_json(state_path)[0]["active_successor_binding"]["status"],
            "binding_id": binding_id}


def abandonment_status(current: Mapping[str, Any], *, allow_pending: bool = False) -> dict[str, Any] | None:
    """Verify abandonment history and fence consumers until its projections agree."""
    marker = current.get("successor_abandonment")
    history = current.get("abandoned_successor_bindings")
    if marker is None and not history:
        return None
    if (not isinstance(marker, Mapping) or set(marker) != {"receipt", "status"}
            or marker["status"] not in {"abandoning", "abandoned"}
            or not isinstance(history, list) or not history or history[-1] != marker["receipt"]):
        _reject("successor abandonment history is malformed")
    packet = Path(current["work_item"])
    for index, ref in enumerate(history):
        _, receipt, _ = proof(packet, ref)
        validate_schema(receipt, "development-successor-abandonment-receipt.schema.json")
        binding = proof(packet, receipt["binding_receipt"])[1]
        predecessor = proof(packet, receipt["predecessor_snapshot"])[1]["task"]
        if (binding["binding_id"] != receipt["binding_id"]
                or binding["predecessor"]["full_state_snapshot"] != receipt["predecessor_snapshot"]
                or receipt["canonical_work_id"] != current["canonical_work_id"]
                or predecessor.get("abandoned_successor_bindings", []) != history[:index]
                or predecessor["work_item"] != current["work_item"]
                or predecessor["run_id"] != current["run_id"]
                or predecessor["canonical_work_id"] != current["canonical_work_id"]):
            _reject("abandonment belongs to another task or binding")
    if not allow_pending:
        if marker["status"] == "abandoning":
            _reject("successor abandonment projections remain pending")
        manifest, _ = read_json(packet / "autodev.json")
        delivery = manifest.get("delivery")
        if (not isinstance(delivery, Mapping)
                or delivery.get("successor_abandonment") != marker
                or delivery.get("abandoned_successor_bindings") != history):
            _reject("abandonment projection fence requires abandon-successor replay")
    return receipt


def _finish_abandonment(state_path: Path, ref: Mapping[str, Any]) -> dict[str, Any]:
    """Replay pointer-only rollback before restoring the predecessor's task authority."""
    current, _ = read_json(state_path)
    receipt = abandonment_status(current, allow_pending=True)
    if receipt is None or current["successor_abandonment"]["receipt"] != ref:
        _reject("abandonment replay does not own the current outbox")
    packet = Path(current["work_item"])
    if current["successor_abandonment"]["status"] == "abandoned":
        if _sync_auto_dev_projection(state_path) is None:
            _reject("abandonment Auto-Dev projection requires replay")
        abandonment_status(current)
        return {"status": "abandoned", "binding_id": receipt["binding_id"], "task": current}
    bound = active_binding(current, allow_pending=True)
    if (bound is None or bound["binding_id"] != receipt["binding_id"]
            or current["active_successor_binding"]["status"] != "projections_pending"):
        _reject("only an unconsumed pending binding can be abandoned")
    predecessor = proof(packet, receipt["predecessor_snapshot"])[1]["task"]
    exempt = set(BINDING_FIELDS) | set(BOOKKEEPING) | {"successor_abandonment", "abandoned_successor_bindings"}
    if {k: v for k, v in current.items() if k not in exempt} != {
            k: v for k, v in predecessor.items() if k not in exempt}:
        _reject("abandonment replay would discard changed task history, lease or attempts")
    expected_pointer = current["active_successor_binding"]["receipt"]
    portfolio_path = state_path.parents[2] / "portfolio.json"
    with _file_lock(portfolio_path.with_suffix(".json.lock")):
        portfolio, _ = read_json(portfolio_path)
        rows = [row for row in portfolio.get("tasks", [])
                if isinstance(row, Mapping) and row.get("ticket") == current["ticket"]]
        pointers = portfolio.get("active_successor_bindings", {})
        if (not isinstance(pointers, Mapping) or len(rows) != 1
                or Path(str(rows[0].get("state_ref") or "")).resolve() != state_path.resolve()
                or pointers.get(current["ticket"]) not in (None, expected_pointer)):
            _reject("abandonment portfolio pointer is foreign")
        if current["ticket"] in pointers:
            portfolio["active_successor_bindings"] = {
                key: value for key, value in pointers.items() if key != current["ticket"]}
            _atomic_json(portfolio_path, portfolio)
    connection = connect(default_db_path(current["os_root"]))
    try:
        work_items.abandon_development_successor(
            connection, current["canonical_work_id"],
            binding={"binding_id": bound["binding_id"], "worktree_path": current["worktree"]["path"],
                     "branch": current["worktree"]["branch"],
                     "receipt_ref": str(packet / expected_pointer["packet_ref"])},
            predecessor_worktree_path=predecessor["worktree"]["path"],
            predecessor_branch=predecessor["worktree"]["branch"],
            receipt_ref=str(packet / ref["packet_ref"]))
        work_items.write_active_projection(connection, Path(current["os_root"]))
    finally:
        connection.close()
    payload = {"ticket": current["ticket"], "binding_id": receipt["binding_id"], "receipt": dict(ref)}
    event_key = "successor-abandonment:" + ref["sha256"]
    append_event(state_path.parent / "events.jsonl", event_type="development.successor.abandoned",
                 idempotency_key=event_key, payload=payload)
    if current.get("rollup_ledger"):
        append_event(Path(current["rollup_ledger"]), event_type="development.successor.abandoned",
                     idempotency_key=event_key, payload=payload)
    with _file_lock(state_path.with_suffix(".json.lock")):
        live, _ = read_json(state_path)
        if live != current:
            _reject("task changed during abandonment projection")
        restored = deepcopy(predecessor)
        restored.update({"successor_abandonment": {"receipt": dict(ref), "status": "abandoned"},
                         "abandoned_successor_bindings": current["abandoned_successor_bindings"],
                         "updated_at": receipt["recorded_at"]})
        _commit_task(state_path, restored)
    if _sync_auto_dev_projection(state_path) is None:
        _reject("abandonment Auto-Dev projection requires replay")
    abandonment_status(restored)
    return {"status": "abandoned", "binding_id": receipt["binding_id"], "task": restored}


def abandon_development_successor(state_file: str | Path, *, expect_state_sha256: str,
                                  idempotency_key: str, reason: str, apply: bool = False) -> dict[str, Any]:
    """Abandon only a pending, unconsumed intent; retain its immutable receipts and budgets."""
    if (not idempotency_key.strip() or not reason.strip() or len(reason) > 2000
            or len(expect_state_sha256) != 64
            or any(char not in "0123456789abcdef" for char in expect_state_sha256)):
        _reject("abandonment needs an exact pending-state hash, stable key and bounded reason")
    state_path = Path(state_file).resolve()
    current, raw_sha = read_json(state_path)
    packet = Path(current["work_item"])
    marker = current.get("successor_abandonment")
    if marker:
        previous = abandonment_status(current, allow_pending=True)
        if previous["idempotency_key"] == idempotency_key:
            if (previous["expected_pending_state_sha256"] != expect_state_sha256
                    or previous["reason"] != reason or previous["task_state_ref"] != str(state_path)):
                _reject("abandonment idempotency key collision")
            if not apply:
                return {"status": "read_only_plan", "binding_id": previous["binding_id"], "replayed": True}
            with _task_provisioning_admission_lock(state_path):
                result = _finish_abandonment(state_path, marker["receipt"])
            return {**result, "replayed": True}
        if marker["status"] == "abandoning":
            _reject("pending abandonment requires its original exact key")
    bound = active_binding(current, allow_pending=True)
    if (raw_sha != expect_state_sha256 or bound is None
            or current["active_successor_binding"]["status"] != "projections_pending"):
        _reject("abandonment requires the exact unconsumed pending task")
    predecessor = proof(packet, bound["predecessor"]["full_state_snapshot"])[1]["task"]
    exempt = set(BINDING_FIELDS) | set(BOOKKEEPING) | {"successor_abandonment", "abandoned_successor_bindings"}
    if {k: v for k, v in current.items() if k not in exempt} != {
            k: v for k, v in predecessor.items() if k not in exempt}:
        _reject("abandonment would discard changed task history, lease or attempts")
    if not apply:
        return {"status": "read_only_plan", "binding_id": bound["binding_id"],
                "restores_worktree": predecessor["worktree"], "grants_delivery_acceptance": False}
    key = digest({"binding_id": bound["binding_id"], "key": idempotency_key, "pending_sha": raw_sha})
    folder = packet / current["active_successor_binding"]["receipt"]["packet_ref"]
    path = folder.parent / "abandonments" / key / "receipt.json"
    recorded = read_json(path)[0]["recorded_at"] if path.exists() else utc_now()
    receipt = {"schema": "development-successor-abandonment-receipt/v1",
               "binding_id": bound["binding_id"], "idempotency_key": idempotency_key,
               "expected_pending_state_sha256": raw_sha, "recorded_at": recorded, "reason": reason,
               "task_state_ref": str(state_path), "canonical_work_id": current["canonical_work_id"],
               "binding_receipt": current["active_successor_binding"]["receipt"],
               "predecessor_snapshot": bound["predecessor"]["full_state_snapshot"]}
    validate_schema(receipt, "development-successor-abandonment-receipt.schema.json")
    with _task_provisioning_admission_lock(state_path):
        with _file_lock(state_path.with_suffix(".json.lock")):
            if read_json(state_path)[1] != raw_sha:
                _reject("pending task changed before abandonment CAS")
            ref = _reference(packet, path, receipt)
            updated = deepcopy(current)
            updated["successor_abandonment"] = {"receipt": ref, "status": "abandoning"}
            updated.setdefault("abandoned_successor_bindings", []).append(ref)
            _commit_task(state_path, updated)
        return _finish_abandonment(state_path, ref)


def bind_development_successor(state_file: str | Path, *, request_file: str | Path,
                               expect_state_sha256: str, idempotency_key: str,
                               apply: bool = False) -> dict[str, Any]:
    """Admit one exact successor and CAS the same task; default is read-only."""
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        _reject("an explicit stable idempotency key is required")
    state_path = Path(state_file).resolve()
    current, raw_sha = read_json(state_path)
    packet = Path(current["work_item"]).resolve()
    request_path = Path(request_file).absolute()
    if not request_path.is_relative_to(packet):
        _reject("request must be in the original packet")
    request_path = contained(packet, str(request_path.relative_to(packet)))
    request, request_sha = read_json(request_path)
    validate_schema(request, "development-successor-binding-request.schema.json")
    if request["expected"]["task_sha256"] != expect_state_sha256:
        _reject("explicit predecessor CAS does not match the request")
    active = current.get("active_successor_binding")
    if active:
        receipt = active_binding(current, allow_pending=True)
        if receipt["idempotency_key"] == idempotency_key:
            if receipt["request_sha256"] != request_sha or receipt["predecessor"]["raw_state_sha256"] != expect_state_sha256:
                _reject("idempotency key collision")
            if not apply:
                return {"status": "read_only_plan", "binding_id": receipt["binding_id"], "replayed": True}
            with _task_provisioning_admission_lock(state_path):
                result = _finish(state_path, receipt)
            return {**result, "replayed": True}
        _reject("an existing successor binding requires its ordinary current-epoch delivery first")
    if raw_sha != expect_state_sha256:
        _reject("stale raw predecessor state")
    observation = observe_successor(state_path, registry_id=request["successor"]["registry_id"],
                                    pull_request=request["pull_request"]["number"])
    _match(current, packet, request, observation)
    if not apply:
        return {"status": "read_only_plan", "expected": observation["expected"],
                "local_source_branch": observation["registry"]["worktree"]["branch"],
                "provider_source_branch": observation["provider"]["source_branch"],
                "head_sha": observation["provider"]["head"], "fresh_validation_required": True}
    with _task_provisioning_admission_lock(state_path):
        with _file_lock(state_path.with_suffix(".json.lock")):
            with family_admission_lock(Path(current["os_root"]), observation["coordinator"]["family_key"]):
                fresh = observe_successor(state_path, registry_id=request["successor"]["registry_id"],
                                          pull_request=request["pull_request"]["number"])
                if fresh != observation or read_json(request_path)[1] != request_sha:
                    _reject("native state, source, provider, policy or review lineage changed before CAS")
                _match(current, packet, request, fresh)
                receipt, intent = _receipt(state_path, current, request, request_sha, idempotency_key, fresh)
                if observe_successor(state_path, registry_id=request["successor"]["registry_id"],
                                      pull_request=request["pull_request"]["number"]) != fresh:
                    _reject("native observations changed while the immutable intent was written")
                # This final raw comparison is the sole task-authority commit point.
                if read_json(state_path)[1] != expect_state_sha256:
                    _reject("raw predecessor changed immediately before CAS")
                updated = deepcopy(current)
                updated.update(intent["patch"])
                updated.update({"subject_revision": None, "updated_at": receipt["recorded_at"],
                    "validation_pending_binding": receipt["binding_id"],
                    "active_successor_binding": {"binding_id": receipt["binding_id"],
                        "receipt": intent["ref"], "status": "projections_pending"}})
                updated.setdefault("successor_bindings", []).append(intent["ref"])
                allowed = set(BINDING_FIELDS) | set(BOOKKEEPING)
                if {k: v for k, v in updated.items() if k not in allowed} != {
                        k: v for k, v in current.items() if k not in allowed}:
                    _reject("task mutation would change protected history, attempts, lease or authority")
                _commit_task(state_path, updated)
        return _finish(state_path, receipt)
