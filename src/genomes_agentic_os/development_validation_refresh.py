"""Append-only validation authority for modern, unmerged Auto-Dev tasks."""
from __future__ import annotations

from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import shlex
import subprocess
from typing import Any, Mapping

import yaml


def _error(message: str) -> None:
    from .development_delivery import DevelopmentDeliveryError
    raise DevelopmentDeliveryError(message)


def _read(path: Path) -> tuple[dict[str, Any], str]:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate validation authority key")
            value[key] = item
        return value
    try:
        raw = path.read_bytes()
        value = json.loads(raw, object_pairs_hook=unique_object)
    except (OSError, ValueError) as exc:
        _error(f"validation authority is unreadable: {path}: {exc}")
    if not isinstance(value, dict):
        _error("validation authority must be a JSON mapping")
    return value, hashlib.sha256(raw).hexdigest()


def _bound(ref: Mapping[str, Any], packet: Path) -> tuple[Path, dict[str, Any], str]:
    if (not isinstance(ref, Mapping) or not isinstance(ref.get("path"), str) or not ref["path"].strip()
            or not isinstance(ref.get("sha256"), str) or len(ref["sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in ref["sha256"])):
        _error("validation proof requires a path and SHA-256 binding")
    try:
        path = Path(str(ref["path"]))
        path = (path if path.is_absolute() else packet / path).resolve()
        physical = path
        if not path.is_relative_to(packet) and _archived_packet(packet):
            # Archive Health moves the whole packet, not its immutable receipt
            # identities. Only the same project's two former active locations
            # may be read through the new root. Keep the recorded logical path
            # so lineage never rewrites or manufactures prior evidence.
            work_items = packet.parent.parent
            for origin in (work_items / packet.name, work_items / "02-active" / packet.name):
                if path.is_relative_to(origin) and not origin.exists():
                    physical = packet / path.relative_to(origin)
                    break
        physical = physical.resolve()
    except (OSError, RuntimeError) as exc:
        _error(f"validation proof path is unreadable: {exc}")
    if not physical.is_relative_to(packet) or not physical.is_file():
        _error("validation proof must be a contained packet file")
    value, digest = _read(physical)
    if digest != ref["sha256"]:
        _error("validation proof SHA-256 binding changed")
    return path, value, digest


def _archived_packet(packet: Path) -> bool:
    return packet.parent.name in {"99-archived", "03-complete"} and packet.parent.parent.name == "work-items"


def _snapshot_target(packet: Path, digest: str) -> Path:
    """Admit the canonical output before creating directories or authority."""
    target = packet / "artifacts/development-delivery/evidence" / f"validation-refresh-{digest}.json"
    try:
        candidate = target
        while candidate != packet:
            if candidate.is_symlink():
                _error("validation snapshot target cannot use symlinks")
            candidate = candidate.parent
        resolved = target.resolve()
        if not (resolved.is_relative_to(packet) and target.parent.resolve().is_relative_to(packet)):
            _error("validation snapshot target must remain in its canonical packet")
        if target.exists() and not target.is_file():
            _error("validation snapshot target must be a regular file")
    except (OSError, RuntimeError) as exc:
        _error(f"validation snapshot target is unreadable: {exc}")
    return resolved


def _git(worktree: Path, *args: str) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=worktree, text=True,
                                capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        _error(f"registered validation worktree Git identity is unavailable: {type(exc).__name__}")
    if result.returncode:
        _error("registered validation worktree Git identity is unavailable")
    return result.stdout.strip()


def _head(evidence: Mapping[str, Any]) -> str:
    if not isinstance(evidence, Mapping):
        _error("validation head evidence is malformed")
    if any(evidence.get(key) is not None and not isinstance(evidence[key], str)
           for key in ("head_sha", "source_head_sha", "subject_revision")):
        _error("validation head evidence must use exact string SHAs")
    values = {str(evidence[key]) for key in ("head_sha", "source_head_sha", "subject_revision")
              if evidence.get(key)}
    if len(values) != 1:
        _error("validation head is missing or ambiguous")
    head = values.pop()
    if len(head) != 40 or any(c not in "0123456789abcdef" for c in head):
        _error("validation head must be an exact Git SHA")
    return head


def _repository_names(current: Mapping[str, Any]) -> set[str]:
    repository_id = str(current["repository"]["id"])
    return {repository_id, repository_id.removeprefix("git:github.com/").removeprefix("github:")}


def _repository_matches(value: Any, current: Mapping[str, Any]) -> bool:
    return isinstance(value, str) and value in _repository_names(current)


def _clean_worktree(current: Mapping[str, Any], project: Path, worktree: Path) -> bool:
    """Exclude only configured metadata in the registered task's artifact namespace."""
    ignored = _git(worktree, "ls-files", "--others", "--ignored", "--exclude-standard", "-z").split("\0")
    for item in filter(None, ignored):
        path = Path(item)
        # Node dependencies require the separately verified actual npm-ci
        # closure and native execution-time checks below; Git never attests them.
        # No Python recovery may import them or any working-tree/venv modules.
        if path.parts[0] != "node_modules" and (path.parts[0] == ".venv"
                or path.name in {".npmrc", ".coveragerc", "pyvenv.cfg"}
                or path.suffix.lower() in {".py", ".pyc", ".pyo", ".pth", ".pyd", ".so", ".dylib",
                                          ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".sh", ".exe"}):
            return False
    entries = _git(worktree, "status", "--porcelain=v1", "--untracked-files=all", "-z").split("\0")
    entries = [entry for entry in entries if entry]
    if not entries:
        return True
    if any(not entry.startswith("?? ") for entry in entries):
        return False
    try:
        config = yaml.safe_load((project / "config/output-artifacts.yml").read_text())
        template = config["output_artifacts"]["legacy_source_feature_root"]
        if template != "src/.features/{ticket_or_slug}":
            return False
        owned = worktree / ".features" / current["ticket"]
        for entry in entries:
            path = worktree / entry[3:]
            if (not path.is_relative_to(owned) or path.suffix not in {".json", ".jsonl", ".md", ".log", ".txt"}
                    or not path.is_file() or path.stat().st_mode & 0o111):
                return False
            candidate = path
            while candidate != worktree:
                if candidate.is_symlink():
                    return False
                candidate = candidate.parent
            if not path.resolve().is_relative_to(owned):
                return False
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError):
        return False
    return True


def _context(state_file: str | Path) -> tuple[Any, dict[str, Any], Path, Path, dict[str, Any]]:
    from .development_delivery import (TaskState, _validate_effective_policy_snapshot,
                                       project_root, worktree_entries_for_project)
    from .auto_dev_orchestration import (AUTO_DEV_STAGE_ORDER, auto_dev_workflow_window,
                                        read_auto_dev_state)
    task = TaskState(Path(state_file).resolve())
    current = task.read()
    if current.get("state") != "local_validation" or current.get("schema") != "development-task/v1":
        _error("validation refresh requires a modern local_validation task")
    packet = Path(str(current.get("work_item") or "")).resolve()
    if _archived_packet(packet):
        _error("validation refresh requires a live modern local_validation packet, not archived history")
    manifest = read_auto_dev_state(packet / "autodev.json")
    linked = manifest.get("delivery") or {}
    window = auto_dev_workflow_window(current.get("auto_dev_stage_order") or AUTO_DEV_STAGE_ORDER,
                                     current.get("auto_dev_start_stage") or "groom",
                                     current.get("auto_dev_completion_stage") or "health")
    if (not current.get("canonical_work_id") or window[0] != "groom" or "pr_create" not in window
            or current.get("terminal_revision") or current.get("deployed_revision")
            or manifest.get("start_stage") != window[0] or manifest.get("completion_stage") != window[-1]
            or current.get("autodev_path") != str(packet / "autodev.json")
            or manifest.get("canonical_work_id") != current["canonical_work_id"]
            or manifest.get("domain") != current["domain"] or manifest.get("project") != current["project"]
            or manifest.get("source", {}).get("key") != current["ticket"]
            or linked.get("policy_fingerprint") != current["policy_fingerprint"]
            or linked.get("repository") != current.get("repository")
            or linked.get("worktree") != current.get("worktree")
            or linked.get("work_item") != str(packet)
            or Path(str(manifest.get("delivery", {}).get("task_state_ref") or "")).resolve() != task.path
            or any(current.get(key) for key in ("historical_delivery_reconciliations",
                       "active_pr_create_delivery_escalations", "worktree_ready_delivery_recoveries"))):
        _error("validation refresh requires the linked modern groom-through-PR-Create boundary")
    repository = current.get("repository") or {}
    record = current.get("worktree") or {}
    if not isinstance(repository, dict) or not isinstance(record, dict):
        _error("validation repository/worktree selection is malformed")
    worktree = Path(str(record.get("path") or "")).resolve()
    source = Path(str(repository.get("root") or "")).resolve()
    project = project_root(current["os_root"], current["domain"], current["project"])
    mappings = set()
    for row in worktree_entries_for_project(project):
        if ((row.get("id") or row.get("name")) != record.get("name")
                or row.get("status", "active") != "active" or not row.get("path")):
            continue
        registered = Path(str(row["path"]))
        mappings.add(str((registered if registered.is_absolute() else project / registered).resolve()))
    common = (worktree / _git(worktree, "rev-parse", "--git-common-dir")).resolve()
    source_common = (source / _git(source, "rev-parse", "--git-common-dir")).resolve()
    if (mappings != {str(worktree)} or worktree == source or common != source_common
            or record.get("repository_id") != repository.get("id")
            or not record.get("branch") or _git(worktree, "branch", "--show-current") != record["branch"]
            or not _clean_worktree(current, project, worktree)):
        _error("validation selection must match one clean registered feature worktree")
    frozen, _ = _read(Path(str(current.get("policy_receipt") or "")))
    profile = _validate_effective_policy_snapshot(frozen, require_selected_profile=True)
    if (frozen.get("fingerprint") != current.get("policy_fingerprint")
            or not isinstance(profile, dict) or profile.get("repository_id") != repository.get("id")):
        _error("validation frozen policy does not match the selected repository")
    _refresh_history(current, packet)
    return task, current, packet, worktree, profile


def _refresh_history(current: Mapping[str, Any], packet: Path) -> None:
    history = current.get("validation_refreshes")
    if history is None:
        history = []
    refresh_receipts = [row for row in current.get("receipts") or []
                        if isinstance(row, Mapping) and row.get("kind") == "validation_refresh"]
    if (not isinstance(history, list) or bool(history) != bool(current.get("validation_head_sha"))
            or len(history) != len(refresh_receipts)):
        _error("validation refresh history/head binding is missing or malformed")
    keys = set()
    previous = None
    for index, row in enumerate(history):
        fields = ("idempotency_key", "request_sha256", "predecessor_ref", "predecessor_sha256",
                  "from_head_sha", "head_sha", "successor_ref", "successor_sha256",
                  "policy_fingerprint", "recorded_at")
        if (not isinstance(row, Mapping) or row.get("schema") != "development-validation-refresh/v1"
                or not all(isinstance(row.get(key), str) and row[key].strip() for key in fields)
                or row["idempotency_key"] in keys):
            _error("validation refresh lineage is missing, malformed or ambiguous")
        keys.add(row["idempotency_key"])
        predecessor_path, predecessor, predecessor_digest = _bound(
            {"path": row["predecessor_ref"], "sha256": row["predecessor_sha256"]}, packet)
        successor_path, successor, successor_digest = _bound(
            {"path": row["successor_ref"], "sha256": row["successor_sha256"]}, packet)
        evidence = successor.get("evidence") or {}
        lineage = evidence.get("repair_lineage") if isinstance(evidence, Mapping) else None
        receipt = refresh_receipts[index]
        recorded = _timestamp(row["recorded_at"])
        if not isinstance(lineage, Mapping):
            _error("validation refresh history lost its repair lineage")
        lineage_path, _, lineage_digest = _bound(lineage.get("predecessor"), packet)
        if (successor.get("schema") != "development-stage-evidence/v1"
                or successor.get("state") != "local_validation" or successor.get("status") not in {"passed", "deferred_to_ci"}
                or (lineage_path, lineage_digest) != (predecessor_path, predecessor_digest)
                or lineage.get("from_head_sha") != row["from_head_sha"]
                or lineage.get("to_head_sha") != row["head_sha"]
                or _head(predecessor.get("evidence") or {}) != row["from_head_sha"]
                or _head(evidence) != row["head_sha"]
                or row["request_sha256"] != successor_digest
                or evidence.get("policy_fingerprint") != row["policy_fingerprint"]
                or row["policy_fingerprint"] != current["policy_fingerprint"]
                or receipt.get("state") != "local_validation" or receipt.get("ref") != str(successor_path)
                or receipt.get("sha256") != successor_digest
                or recorded.timestamp() > datetime.now().astimezone().timestamp()
                or (previous is not None and previous != (predecessor_path, predecessor_digest))):
            _error("validation refresh lineage no longer matches immutable history")
        attestation = _predecessor_identity(current, packet, predecessor_path, predecessor, predecessor_digest,
                                           verify_worktree=not _archived_packet(packet))
        recorded_attestation = row.get("predecessor_identity_attestation")
        if (recorded_attestation is not None and recorded_attestation != attestation
                or attestation["kind"] == "task_bound_legacy_identity" and recorded_attestation != attestation):
            _error("validation predecessor identity attestation changed")
        runs = evidence.get("validation_runs")
        if not isinstance(runs, list) or not runs or not all(isinstance(run, Mapping) for run in runs):
            _error("validation refresh history lost its command proof")
        for run in runs:
            _bound(run.get("terminal"), packet)
            _bound(run.get("command_receipt"), packet)
        previous = (successor_path, successor_digest)
    if history:
        latest_path, latest, digest = _latest(current, packet)
        row = history[-1]
        if (Path(row["successor_ref"]).resolve() != latest_path
                or row["successor_sha256"] != digest or row["request_sha256"] != digest
                or row["head_sha"] != _head(latest.get("evidence") or {})
                or current["validation_head_sha"] != row["head_sha"]
                or row["policy_fingerprint"] != current["policy_fingerprint"]):
            _error("validation refresh lineage no longer matches immutable current authority")


def _latest(current: Mapping[str, Any], packet: Path) -> tuple[Path, dict[str, Any], str]:
    rows = [row for row in current.get("receipts") or []
            if isinstance(row, Mapping) and row.get("state") == "local_validation"]
    if not rows:
        _error("validation refresh lacks an immutable predecessor")
    row = rows[-1]
    return _bound({"path": row.get("ref"), "sha256": row.get("sha256")}, packet)


def _predecessor_identity(current: Mapping[str, Any], packet: Path, path: Path,
                          payload: Mapping[str, Any], digest: str, *, verify_worktree: bool = True) -> dict[str, Any]:
    """Attest absent legacy identity from one original hash-bound task receipt."""
    evidence = payload.get("evidence")
    if (payload.get("schema") != "development-stage-evidence/v1" or payload.get("state") != "local_validation"
            or not isinstance(evidence, Mapping)):
        _error("validation predecessor identity/policy mismatch")
    checks = {"ticket": evidence.get("ticket") == current["ticket"],
              "repository": _repository_matches(evidence.get("repository"), current),
              "policy_fingerprint": evidence.get("policy_fingerprint") == current["policy_fingerprint"]}
    if any(key in evidence and not matches for key, matches in checks.items()):
        _error("validation predecessor identity/policy mismatch")
    missing = [key for key in checks if key not in evidence]
    kind = "embedded_identity"
    if missing:
        rows = [row for row in current.get("receipts") or [] if isinstance(row, Mapping)
                and row.get("state") == "local_validation" and row.get("kind") is None
                and row.get("sha256") == digest
                and Path(str(row.get("ref") or "")).resolve() == path]
        if (len(rows) != 1 or payload.get("stage") != "implementation"
                or current.get("canonical_work_id") != f"{current['domain']}:{current['project']}:{current['ticket'].lower()}"):
            _error("legacy predecessor lacks original task-bound authority")
        created = int(_timestamp(current.get("created_at")).timestamp())
        verified = int(_timestamp(payload.get("verified_at")).timestamp())
        recorded = int(_timestamp(rows[0].get("recorded_at")).timestamp())
        if not created <= verified <= recorded <= int(datetime.now().astimezone().timestamp()):
            _error("legacy predecessor timestamps do not attest original task authority")
        if verify_worktree:
            _git(Path(current["worktree"]["path"]), "merge-base", "--is-ancestor", _head(evidence), "HEAD")
        kind = "task_bound_legacy_identity"
    return {"schema": "development-validation-predecessor-attestation/v1", "kind": kind,
            "canonical_work_id": current["canonical_work_id"], "ticket": current["ticket"],
            "repository_id": current["repository"]["id"], "policy_fingerprint": current["policy_fingerprint"],
            "predecessor_ref": str(path), "predecessor_sha256": digest, "head_sha": _head(evidence)}


def _deferred(payload: Mapping[str, Any], validation: Mapping[str, Any], *,
              require_frozen_command: bool = True) -> None:
    evidence = payload.get("evidence") or {}
    if not isinstance(evidence, Mapping):
        _error("CI deferral evidence is malformed")
    unavailable = evidence.get("unavailable_check") or {}
    if (validation.get("ci_fallback_on_environment_failure") is not True
            or payload.get("schema") != "development-stage-evidence/v1"
            or payload.get("state") != "local_validation" or payload.get("status") != "deferred_to_ci"
            or not isinstance(evidence, Mapping) or not isinstance(unavailable, Mapping)
            or unavailable.get("classification") not in ("environment_unavailable", "infrastructure")
            or not all(isinstance(unavailable.get(key), str) and unavailable[key].strip() for key in ("command", "reason"))
            or (require_frozen_command and unavailable.get("command") not in (validation.get("commands") or []))):
        _error("PR Create CI deferral requires exact pinned fallback policy and unavailable-command proof")


def _historical_deferred_handoff(state_file: str | Path, receipt: Path) -> dict[str, Any] | None:
    """Preserve an original narrower workflow's handoff, never current validation."""
    from .development_delivery import (TaskState, frozen_selected_task_profile,
                                       validate_local_validation_ci_deferral)
    from .auto_dev_orchestration import AUTO_DEV_STAGE_ORDER, auto_dev_workflow_window, read_auto_dev_state
    task_path = Path(state_file).resolve()
    current = TaskState(task_path).read()
    packet = Path(str(current.get("work_item") or "")).resolve()
    _refresh_history(current, packet)
    path, payload, digest = _latest(current, packet)
    evidence = payload.get("evidence")
    # Missing fields in a declared modern chain never downgrade its authority.
    # A new command/lineage proof or refresh marker remains on the modern gate.
    start = current.get("auto_dev_start_stage")
    if (start is None or start == "groom" or current.get("validation_refreshes") or current.get("validation_head_sha")
            or not isinstance(evidence, Mapping) or "validation_runs" in evidence or "repair_lineage" in evidence):
        return None
    profile = frozen_selected_task_profile(current)
    mode = current.get("auto_dev_mode")
    if not isinstance(start, str) or not isinstance(mode, str):
        _error("historical CI handoff workflow boundary is malformed")
    auto_dev = profile.get("auto_dev") if isinstance(profile.get("auto_dev"), Mapping) else {}
    configured = auto_dev.get(mode) if isinstance(auto_dev.get(mode), Mapping) else {}
    order = current.get("auto_dev_stage_order") or AUTO_DEV_STAGE_ORDER
    if not isinstance(order, (list, tuple)) or not order or not all(isinstance(stage, str) for stage in order):
        _error("historical CI handoff stage order is malformed")
    expected_start = configured.get("start_stage") or ("readiness" if mode == "default" else order[0])
    expected_end = configured.get("completion_stage") or ("pr_create" if mode == "default" else order[-1])
    manifest = read_auto_dev_state(packet / "autodev.json")
    linked = manifest.get("delivery") if isinstance(manifest.get("delivery"), Mapping) else {}
    source = manifest.get("source") if isinstance(manifest.get("source"), Mapping) else {}
    if (mode not in {"default", "everything"} or current.get("schema") != "development-task/v1"
            or current.get("state") != "local_validation" or _archived_packet(packet)
            or current.get("terminal_revision") or current.get("deployed_revision")
            or start != expected_start or current.get("auto_dev_completion_stage") != expected_end
            or list(order) != list(auto_dev.get("stage_order") or AUTO_DEV_STAGE_ORDER)
            or manifest.get("stage_order") != list(order)
            or manifest.get("start_stage") != start or manifest.get("completion_stage") != expected_end
            or manifest.get("mode") != mode or manifest.get("domain") != current.get("domain")
            or manifest.get("project") != current.get("project")
            or source.get("key") != current.get("ticket")
            or manifest.get("canonical_work_id") != current.get("canonical_work_id")
            or current.get("autodev_path") != str(packet / "autodev.json")
            or Path(str(linked.get("task_state_ref") or "")).resolve() != task_path
            or linked.get("work_item") != str(packet) or linked.get("repository") != current.get("repository")
            or linked.get("worktree") != current.get("worktree")
            or linked.get("policy_fingerprint") != current.get("policy_fingerprint")
            or path != receipt.resolve()):
        _error("historical CI handoff requires its original linked task and pinned workflow boundary")
    window = auto_dev_workflow_window(order, start, expected_end)
    if "develop" not in window or "pr_create" not in window:
        _error("historical CI handoff requires both Develop and PR Create in its recorded window")
    rows = [row for row in current.get("receipts") or [] if isinstance(row, Mapping)
            and row.get("state") == "local_validation" and row.get("kind") is None
            and row.get("ref") == str(path) and row.get("sha256") == digest]
    # Native receipt recording uses whole seconds; match the existing legacy
    # attestation's resolution instead of rejecting earlier subsecond proof.
    if (len(rows) != 1 or payload.get("schema") != "development-stage-evidence/v1"
            or not isinstance(payload.get("summary"), str) or not payload["summary"].strip()
            or not int(_timestamp(payload.get("verified_at")).timestamp())
                   <= int(_timestamp(rows[0].get("recorded_at")).timestamp())
                   <= int(datetime.now().astimezone().timestamp())
            or int(_timestamp(current.get("created_at")).timestamp()) > int(_timestamp(rows[0].get("recorded_at")).timestamp())):
        _error("historical CI handoff lacks one original immutable task receipt")
    for key, matches in {
        "ticket": evidence.get("ticket") == current.get("ticket"),
        "repository": _repository_matches(evidence.get("repository"), current),
        "policy_fingerprint": evidence.get("policy_fingerprint") == current.get("policy_fingerprint"),
    }.items():
        if key in evidence and not matches:
            _error("historical CI handoff receipt identity/policy mismatch")
    validate_local_validation_ci_deferral(payload, current, require_frozen=True)
    recorded_head = _head(evidence) if any(evidence.get(key) for key in ("head_sha", "source_head_sha", "subject_revision")) else None
    return {"status": "deferred_to_ci", "authority_scope": "historical_pr_create_handoff",
            "current_validation_authority": "unproved", "ci_authority": "pending",
            "path": str(path), "sha256": digest, "recorded_head_sha": recorded_head,
            "policy_fingerprint": current["policy_fingerprint"],
            "next_action": "Obtain required CI and review evidence on the PR's exact current head; historical local labels do not satisfy those gates."}


def validate_deferred_pr_create(state_file: str | Path, receipt: Path) -> None:
    """Admit same-head proof or a historical CI handoff, never review/merge authority."""
    if _historical_deferred_handoff(state_file, receipt) is not None:
        return
    _, current, packet, worktree, profile = _context(state_file)
    path, payload, _ = _latest(current, packet)
    if path != receipt.resolve():
        _error("PR Create deferral is not the latest immutable task receipt")
    _deferred(payload, profile["validation"])
    evidence = payload["evidence"]
    if (evidence.get("ticket") != current["ticket"]
            or not _repository_matches(evidence.get("repository"), current)
            or evidence.get("policy_fingerprint") != current["policy_fingerprint"]
            or _head(evidence) != _git(worktree, "rev-parse", "HEAD")):
        _error("changed-head CI deferral requires fresh successor validation")
    # Historical labels preserve lineage only. PR creation requires actual
    # current frozen-command terminals, including both a passed layer and the
    # exact unavailable command's failure. Missing old proof needs a refresh.
    _commands({**evidence, "verified_at": payload.get("verified_at")}, current, packet,
              worktree, profile, _head(evidence), evidence["unavailable_check"])


def pr_create_validation_authority(state_file: str | Path, family: Mapping[str, Any]) -> dict[str, Any] | None:
    """Fence refreshed/deferred PR families with their current validation head."""
    from .development_delivery import TaskState
    current = TaskState(Path(state_file).resolve()).read()
    packet = Path(str(current.get("work_item") or "")).resolve()
    rows = [r for r in current.get("receipts") or [] if isinstance(r, Mapping) and r.get("state") == "local_validation"]
    _refresh_history(current, packet)
    if not rows:
        return None
    if not current.get("validation_refreshes"):
        candidate = Path(str(rows[-1].get("ref") or ""))
        candidate = candidate if candidate.is_absolute() else packet / candidate
        if not candidate.is_file() or _read(candidate)[0].get("status") != "deferred_to_ci":
            return None
    path, payload, digest = _latest(current, packet)
    deferred = payload.get("status") == "deferred_to_ci"
    if not deferred and not current.get("validation_refreshes"):
        return None
    historical = _historical_deferred_handoff(state_file, path) if deferred else None
    if historical is not None:
        # The PR head is independently selected and read back. Do not label it
        # as the head validated by old local checks, including after repair.
        record = current.get("worktree") if isinstance(current.get("worktree"), Mapping) else {}
        if not record.get("path") or not record.get("branch"):
            _error("historical CI handoff PR family lacks its selected worktree/branch")
        worktree = Path(str(record["path"])).resolve()
        evidence = family.get("evidence")
        if (not isinstance(evidence, Mapping) or _head(evidence) != _git(worktree, "rev-parse", "HEAD")
                or evidence.get("ticket") != current.get("ticket")
                or not _repository_matches(evidence.get("repository"), current)
                or evidence.get("policy_fingerprint") != current.get("policy_fingerprint")
                or evidence.get("source_branch") != record["branch"]
                or _git(worktree, "branch", "--show-current") != record["branch"]):
            _error("historical CI handoff PR family must independently match the current selected head/branch/policy")
        return {**historical, "pr_head_sha": _head(evidence)}
    _, current, _, worktree, _ = _context(state_file)
    if deferred:
        validate_deferred_pr_create(state_file, path)
    head = _head(payload.get("evidence") or {})
    evidence = family.get("evidence") or {}
    if (head != _git(worktree, "rev-parse", "HEAD") or _head(evidence) != head
            or evidence.get("ticket") != current["ticket"]
            or not _repository_matches(evidence.get("repository"), current)
            or evidence.get("policy_fingerprint") != current["policy_fingerprint"]
            or evidence.get("source_branch") != current["worktree"]["branch"]):
        _error("PR Create family does not match current exact-head validation authority")
    return {"status": "deferred_to_ci" if deferred else "passed", "head_sha": head,
            "path": str(path), "sha256": digest, "ci_authority": "pending" if deferred else "unknown",
            "policy_fingerprint": current["policy_fingerprint"]}


def _commands(evidence: Mapping[str, Any], current: Mapping[str, Any], packet: Path,
              worktree: Path, profile: Mapping[str, Any], head: str,
              unavailable: Mapping[str, Any] | None = None) -> None:
    from .validation_command_authority import execution_argv, matches_command, runtime_provenance_check
    from .development_delivery import project_root
    commands = profile.get("validation", {}).get("commands")
    runs = evidence.get("validation_runs")
    if (not isinstance(commands, list) or not commands or not all(isinstance(c, str) and c for c in commands)
            or not isinstance(runs, list) or not all(isinstance(r, Mapping) for r in runs)
            or [r.get("command") for r in runs] != commands):
        _error("fresh validation requires complete ordered frozen-command proof")
    if not _clean_worktree(current, project_root(current["os_root"], current["domain"], current["project"]), worktree):
        _error("frozen execution requires the registered tracked/source cleanliness guard")
    identity = {"repository": _git(worktree, "config", "--get", "remote.origin.url"),
                "branch": current["worktree"]["branch"], "head": head,
                "clean": "false" if _git(worktree, "status", "--porcelain") else "true"}
    expected_identity = {**identity, "worktree": str(worktree)}
    verified = _timestamp(evidence.get("verified_at"))
    passed = 0
    deferred = 0
    node_install = None
    for run in runs:
        terminal_path, terminal, _ = _bound(run.get("terminal"), packet)
        command_path, command, _ = _bound(run.get("command_receipt"), packet)
        actual_argv, environment = execution_argv(command, current)
        is_unavailable = unavailable is not None and run["command"] == unavailable["command"]
        outcome_ok = terminal.get("status") == "success" and terminal.get("exit_code") == 0
        if is_unavailable:
            outcome_ok = (terminal.get("status") == "failure" and type(terminal.get("exit_code")) is int
                          and terminal["exit_code"] > 0 and type(unavailable.get("exit_code")) is int
                          and unavailable["exit_code"] == terminal["exit_code"]
                          and unavailable.get("receipt_ref") == str(terminal_path))
        if (terminal.get("schema") != "agentic-os-long-running-terminal/v1"
                or not outcome_ok or type(terminal.get("exit_code")) is not int
                or terminal.get("post_run_invariants_ok") is not True
                or command.get("schema") != "agentic-os-long-running-state/v1" or command.get("shell") is not False
                or not matches_command(run["command"], actual_argv, current, profile)
                or ("REVIEW_POLICY_FINGERPRINT" in environment
                    and environment["REVIEW_POLICY_FINGERPRINT"] != current["policy_fingerprint"])
                or Path(str(command.get("work_dir") or "")).resolve() != worktree
                or command.get("id") != terminal.get("id")
                or terminal_path.parent != command_path.parent
                or Path(str(command.get("run_dir") or "")).resolve() != command_path.parent
                or Path(str(terminal.get("run_dir") or "")).resolve() != terminal_path.parent
                or any(terminal.get(key) != identity for key in ("git_identity_pre", "git_identity_post"))
                or terminal.get("expected_git_identity") != expected_identity
                or command.get("expected_git_identity") != expected_identity):
            _error("fresh validation command/terminal identity is incomplete or unsuccessful")
        launcher = Path(actual_argv[0]).name.lower()
        npm_ci = shlex.split(run["command"]) == ["npm", "ci"]
        if launcher in {"npm", "npx", "node"}:
            if npm_ci:
                _git(worktree, "ls-files", "--error-unmatch", "package-lock.json")
                if is_unavailable:
                    _error("Node recovery requires actual passed npm ci install provenance")
                node_install = _node_proof(run, command_path, command, terminal, packet, worktree)
            elif node_install is None:
                _error("Node dependency validation requires prior actual passed frozen npm ci")
            else:
                _node_proof(run, command_path, command, terminal, packet, worktree, node_install)
        try:
            check = runtime_provenance_check(run["command"], actual_argv, current, profile)
        except ValueError as exc:
            _error(str(exc))
        if check is not None:
            preflight_path, preflight, _ = _bound(run.get("preflight"), packet)
            def checked(rows: Any, phase: str) -> bool:
                if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
                    return False
                matches = [row for row in rows if row.get("phase") == phase]
                return (len(matches) == 1 and matches[0].get("command") == check
                        and matches[0].get("ok") is True and type(matches[0].get("exit_code")) is int
                        and matches[0]["exit_code"] == 0)
            if (command.get("preflight_checks") != [check] or command.get("post_run_checks") != [check]
                    or preflight_path != command_path.parent / "preflight.json"
                    or preflight.get("ok") is not True or not isinstance(preflight.get("checks"), list)
                    or len(preflight["checks"]) != 1
                    or not checked(preflight.get("checks"), "preflight")
                    or not isinstance(terminal.get("checks"), list) or len(terminal["checks"]) != 2
                    or not checked(terminal["checks"], "preflight") or not checked(terminal["checks"], "post-run")):
                _error("declared base interpreter requires exact executed pre/post checksum proof")
        deferred += int(is_unavailable)
        passed += int(not is_unavailable)
        started = _timestamp(terminal.get("created_at"))
        finished = _timestamp(terminal.get("finished_at"))
        commit_time = int(_git(worktree, "show", "-s", "--format=%ct", head))
        if not commit_time <= started.timestamp() <= finished.timestamp() <= verified.timestamp() <= datetime.now().astimezone().timestamp():
            _error("fresh validation command timestamps are stale or contradictory")
    if unavailable is not None and (deferred != 1 or passed < 1):
        _error("fresh CI deferral requires one actual unavailable command and a passed local layer")


def _node_proof(run: Mapping[str, Any], command_path: Path, command: Mapping[str, Any],
                terminal: Mapping[str, Any], packet: Path, worktree: Path,
                install: tuple[Path, str] | None = None) -> tuple[Path, str]:
    from .validation_node_provenance import (LOCK, SCHEMA, SNAPSHOT, dependency_closure, guard_checks)
    install_run = install[0] if install else command_path.parent
    snapshot_path, snapshot, digest = _bound(run.get("node_install_closure"), packet)
    if (snapshot_path != install_run / SNAPSHOT or install is not None and digest != install[1]
            or snapshot.get("schema") != SCHEMA or snapshot.get("run_id") != install_run.name
            or snapshot.get("command_sha256") != _read(install_run / "command.json")[1]
            or snapshot.get("identity") != command.get("expected_git_identity")
            or snapshot.get("worktree") != str(worktree)
            or snapshot.get("lockfile_sha256") != hashlib.sha256((worktree / "package-lock.json").read_bytes()).hexdigest()
            or command.get("mutation_lock") != str(install_run.parents[2] / LOCK)
            or not Path(command["mutation_lock"]).is_relative_to(packet / "artifacts")):
        _error("Node install closure must bind its actual passed npm ci and item-owned lock")
    try:
        if snapshot.get("entries") != dependency_closure(worktree):
            _error("installed Node dependency closure changed after npm ci")
        pre_check, post_check = guard_checks(install_run, command_path.parent, worktree, digest if install else None)
        preflight_path, preflight, _ = _bound(run.get("preflight"), packet)
        pre_capsule = {"operation": "prepare", "run_id": install_run.name} if install is None else {
            "operation": "verify", "run_id": command_path.parent.name,
            "install_run_id": install_run.name, "snapshot_sha256": digest}
        post_capsule = {"operation": "capture" if install is None else "verify",
            "run_id": command_path.parent.name, "install_run_id": install_run.name, "snapshot_sha256": digest}
        def checked(rows: Any, phase: str, expected: str, capsule: dict) -> bool:
            matches = [row for row in rows if isinstance(row, Mapping) and row.get("phase") == phase]
            return (len(matches) == 1 and matches[0].get("command") == expected
                    and matches[0].get("ok") is True and type(matches[0].get("exit_code")) is int
                    and matches[0]["exit_code"] == 0
                    and json.loads(matches[0].get("output_tail", "")) == capsule)
        if (command.get("preflight_checks") != [pre_check] or command.get("post_run_checks") != [post_check]
                or preflight_path != command_path.parent / "preflight.json" or preflight.get("ok") is not True
                or not isinstance(preflight.get("checks"), list) or len(preflight["checks"]) != 1
                or not isinstance(terminal.get("checks"), list) or len(terminal["checks"]) != 2
                or not checked(preflight["checks"], "preflight", pre_check, pre_capsule)
                or not checked(terminal["checks"], "preflight", pre_check, pre_capsule)
                or not checked(terminal["checks"], "post-run", post_check, post_capsule)):
            _error("Node closure requires exact executed native install capture and pre/post checks")
    except (OSError, ValueError, RuntimeError, TypeError) as exc:
        _error("Node execution provenance is unavailable or contradictory: " + str(exc))
    return install_run, digest


def _timestamp(value: Any) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        _error("validation timestamps must be explicit UTC instants")
    if result.tzinfo is None:
        _error("validation timestamps must include a timezone")
    return result


def _emit_readiness(task: Any, head: str, policy: str) -> dict[str, Any]:
    if importlib.util.find_spec("genomes_agentic_os.review_readiness_evidence") is None:
        return {"status": "unknown", "head_sha": head,
                "reason": "Canonical readiness producer is absent from this legacy source boundary"}
    from .review_readiness_evidence import emit_readiness_evidence
    return emit_readiness_evidence(task.path, head=head, policy=policy)


def refresh_development_validation(state_file: str | Path, *, evidence_file: str | Path,
                                   idempotency_key: str) -> dict[str, Any]:
    """Bind passed validation or honest configured CI deferral without rewriting history."""
    from .development_delivery import (_atomic_json, _file_lock, _refresh_portfolio_state,
                                       _sync_auto_dev_projection, _sync_canonical_task_progress, utc_now)
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        _error("validation refresh requires an idempotency key")
    task, current, packet, worktree, profile = _context(state_file)
    request_path = Path(evidence_file).resolve()
    if not request_path.is_relative_to(packet):
        _error("successor validation evidence must be packet-contained")
    payload, request_digest = _read(request_path)
    evidence = payload.get("evidence") or {}
    if (payload.get("schema") != "development-stage-evidence/v1" or payload.get("state") != "local_validation"
            or payload.get("status") not in {"passed", "deferred_to_ci"} or not isinstance(payload.get("summary"), str)
            or not payload["summary"].strip() or not payload.get("verified_at")
            or not isinstance(evidence, dict)
            or payload.get("status") == "passed" and evidence.get("unavailable_check") is not None):
        _error("successor validation requires actual passed local evidence")
    unavailable = None
    if payload["status"] == "deferred_to_ci":
        _deferred(payload, profile["validation"])
        unavailable = evidence["unavailable_check"]
    head = _head(evidence)
    if (evidence.get("head_sha") != head or evidence.get("ticket") != current["ticket"]
            or evidence.get("canonical_work_id") != current["canonical_work_id"]
            or evidence.get("repository_id") != current["repository"]["id"]
            or not _repository_matches(evidence.get("repository"), current)
            or evidence.get("policy_fingerprint") != current["policy_fingerprint"]
            or evidence.get("policy_sha256") != _read(Path(current["policy_receipt"]))[1]
            or Path(str(evidence.get("task_state_ref") or "")).resolve() != task.path
            or Path(str(evidence.get("worktree") or "")).resolve() != worktree
            or evidence.get("source_branch") != current["worktree"]["branch"]
            or head != _git(worktree, "rev-parse", "HEAD")):
        _error("successor validation task/repository/worktree/branch/head/policy mismatch")
    _commands({**evidence, "verified_at": payload["verified_at"]}, current, packet,
              worktree, profile, head, unavailable)
    lineage = evidence.get("repair_lineage") or {}
    if (not isinstance(lineage, dict) or not isinstance(lineage.get("reason"), str)
            or not lineage["reason"].strip()):
        _error("successor validation requires explicit repair lineage")
    predecessor_path, predecessor, predecessor_digest = _bound(lineage.get("predecessor"), packet)
    old_head = _head(predecessor.get("evidence") or {})
    if lineage.get("from_head_sha") != old_head or lineage.get("to_head_sha") != head:
        _error("validation repair lineage head mismatch")
    if predecessor.get("status") == "deferred_to_ci":
        # Historical failed argv never serves as current passed command proof.
        # The fresh successor below must execute every exact frozen command.
        _deferred(predecessor, profile["validation"], require_frozen_command=False)
    elif predecessor.get("status") not in ("passed", "verified", "completed"):
        _error("validation predecessor is not terminal authority")
    attestation = _predecessor_identity(current, packet, predecessor_path, predecessor, predecessor_digest)
    latest_path, _, latest_digest = _latest(current, packet)
    replay = next((row for row in current.get("validation_refreshes") or []
                   if isinstance(row, Mapping) and row.get("idempotency_key") == idempotency_key), None)
    if replay:
        if (replay.get("request_sha256") != request_digest or replay.get("head_sha") != head
                or replay.get("successor_sha256") != latest_digest
                or Path(replay["successor_ref"]).resolve() != latest_path):
            _error("validation refresh idempotency collision or stale replay")
    elif latest_path != predecessor_path or latest_digest != predecessor_digest:
        _error("validation repair predecessor is not current immutable task authority")
    if not replay:
        snapshot = _snapshot_target(packet, request_digest)
        with _file_lock(task.path.with_suffix(task.path.suffix + ".lock")):
            if (task.read() != current or _git(worktree, "rev-parse", "HEAD") != head
                    or _git(worktree, "branch", "--show-current") != current["worktree"]["branch"]
                    or _context(state_file)[1] != current):
                _error("validation task/head changed during refresh preflight")
            if _read(request_path)[1] != request_digest:
                _error("successor validation changed during refresh preflight")
            if _read(predecessor_path)[1] != predecessor_digest:
                _error("validation predecessor changed during refresh preflight")
            if _read(Path(current["policy_receipt"]))[1] != evidence["policy_sha256"]:
                _error("validation frozen policy changed during refresh preflight")
            _commands({**evidence, "verified_at": payload["verified_at"]}, current, packet,
                      worktree, profile, head, unavailable)
            snapshot = _snapshot_target(packet, request_digest)
            try:
                if snapshot.exists() and snapshot.read_bytes() != request_path.read_bytes():
                    _error("immutable validation refresh snapshot collision")
                if not snapshot.exists():
                    snapshot.parent.mkdir(parents=True, exist_ok=True)
                    snapshot = _snapshot_target(packet, request_digest)
                    with snapshot.open("xb") as handle:
                        handle.write(request_path.read_bytes())
            except OSError as exc:
                _error(f"immutable validation refresh snapshot cannot be written: {exc}")
            now = utc_now()
            current.setdefault("receipts", []).append({"state": "local_validation", "kind": "validation_refresh",
                "ref": str(snapshot), "sha256": request_digest, "recorded_at": now})
            current.setdefault("validation_refreshes", []).append({"schema": "development-validation-refresh/v1",
                "idempotency_key": idempotency_key, "request_sha256": request_digest,
                "predecessor_ref": str(predecessor_path), "predecessor_sha256": predecessor_digest,
                "from_head_sha": old_head, "head_sha": head, "successor_ref": str(snapshot),
                "successor_sha256": request_digest, "policy_fingerprint": current["policy_fingerprint"], "recorded_at": now,
                "predecessor_identity_attestation": attestation})
            current["validation_head_sha"] = head
            current["updated_at"] = now
            _atomic_json(task.path, current)
        task.emit(event_type="development.validation.refreshed", idempotency_key=idempotency_key,
                  payload={"ticket": current["ticket"], "from_head_sha": old_head, "head_sha": head,
                           "receipt": str(snapshot), "sha256": request_digest})
    _refresh_portfolio_state(task.path)
    if _sync_auto_dev_projection(task.path) is None:
        _error("validation authority recorded but Auto-Dev projection sync requires repair")
    _sync_canonical_task_progress(task.path)
    readiness = _emit_readiness(task, head, current["policy_fingerprint"])
    return {"task": task.read(), "replayed": bool(replay), "readiness_projection": readiness}
