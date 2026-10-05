"""Append-only validation authority for modern, unmerged Auto-Dev tasks."""
from __future__ import annotations

from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping


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
    path = Path(str(ref["path"]))
    path = (path if path.is_absolute() else packet / path).resolve()
    if not path.is_relative_to(packet) or not path.is_file():
        _error("validation proof must be a contained packet file")
    value, digest = _read(path)
    if digest != ref["sha256"]:
        _error("validation proof SHA-256 binding changed")
    return path, value, digest


def _git(worktree: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=worktree, text=True,
                            capture_output=True, timeout=10)
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
    manifest = read_auto_dev_state(packet / "autodev.json")
    window = auto_dev_workflow_window(current.get("auto_dev_stage_order") or AUTO_DEV_STAGE_ORDER,
                                     current.get("auto_dev_start_stage") or "groom",
                                     current.get("auto_dev_completion_stage") or "health")
    if (not current.get("canonical_work_id") or window[0] != "groom" or "pr_create" not in window
            or current.get("terminal_revision") or current.get("deployed_revision")
            or manifest.get("start_stage") != window[0] or manifest.get("completion_stage") != window[-1]
            or current.get("autodev_path") != str(packet / "autodev.json")
            or manifest.get("canonical_work_id") != current["canonical_work_id"]
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
            or _git(worktree, "status", "--porcelain")):
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
                or successor.get("state") != "local_validation" or successor.get("status") != "passed"
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
            or (require_frozen_command and unavailable.get("command") not in (validation.get("commands") or []))
            or not any(value == "passed" for key, value in evidence.items() if key != "unavailable_check")):
        _error("PR Create CI deferral requires exact pinned fallback policy and unavailable-command proof")


def validate_deferred_pr_create(state_file: str | Path, receipt: Path) -> None:
    """Admit only same-head PR creation, never review or merge authority."""
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
              worktree: Path, profile: Mapping[str, Any], head: str) -> None:
    from .validation_command_authority import execution_argv, matches_command
    commands = profile.get("validation", {}).get("commands")
    runs = evidence.get("validation_runs")
    if (not isinstance(commands, list) or not commands or not all(isinstance(c, str) and c for c in commands)
            or not isinstance(runs, list) or not all(isinstance(r, Mapping) for r in runs)
            or [r.get("command") for r in runs] != commands):
        _error("fresh validation requires complete ordered frozen-command proof")
    identity = {"repository": _git(worktree, "config", "--get", "remote.origin.url"),
                "branch": current["worktree"]["branch"], "head": head, "clean": "true"}
    expected_identity = {**identity, "worktree": str(worktree)}
    verified = _timestamp(evidence.get("verified_at"))
    for run in runs:
        terminal_path, terminal, _ = _bound(run.get("terminal"), packet)
        command_path, command, _ = _bound(run.get("command_receipt"), packet)
        actual_argv, environment = execution_argv(command)
        if (terminal.get("schema") != "agentic-os-long-running-terminal/v1"
                or terminal.get("status") != "success" or type(terminal.get("exit_code")) is not int
                or terminal.get("exit_code") != 0
                or terminal.get("post_run_invariants_ok") is not True
                or command.get("schema") != "agentic-os-long-running-state/v1" or command.get("shell") is not False
                or not matches_command(run["command"], actual_argv, current, profile)
                or (command.get("command", [None])[0] == "env"
                    and environment.get("REVIEW_POLICY_FINGERPRINT") != current["policy_fingerprint"])
                or Path(str(command.get("work_dir") or "")).resolve() != worktree
                or command.get("id") != terminal.get("id")
                or terminal_path.parent != command_path.parent
                or Path(str(command.get("run_dir") or "")).resolve() != command_path.parent
                or Path(str(terminal.get("run_dir") or "")).resolve() != terminal_path.parent
                or any(terminal.get(key) != identity for key in ("git_identity_pre", "git_identity_post"))
                or terminal.get("expected_git_identity") != expected_identity
                or command.get("expected_git_identity") != expected_identity):
            _error("fresh validation command/terminal identity is incomplete or unsuccessful")
        started = _timestamp(terminal.get("created_at"))
        finished = _timestamp(terminal.get("finished_at"))
        commit_time = int(_git(worktree, "show", "-s", "--format=%ct", head))
        if not commit_time <= started.timestamp() <= finished.timestamp() <= verified.timestamp() <= datetime.now().astimezone().timestamp():
            _error("fresh validation command timestamps are stale or contradictory")


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
    """Bind fresh passed validation without relabeling or transitioning history."""
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
            or payload.get("status") != "passed" or not isinstance(payload.get("summary"), str)
            or not payload["summary"].strip() or not payload.get("verified_at")
            or not isinstance(evidence, dict) or evidence.get("unavailable_check") is not None):
        _error("successor validation requires actual passed local evidence")
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
              worktree, profile, head)
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
    old_evidence = predecessor.get("evidence") or {}
    if (predecessor.get("schema") != "development-stage-evidence/v1" or predecessor.get("state") != "local_validation"
            or old_evidence.get("ticket") != current["ticket"]
            or not _repository_matches(old_evidence.get("repository"), current)
            or old_evidence.get("policy_fingerprint") != current["policy_fingerprint"]):
        _error("validation predecessor identity/policy mismatch")
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
        snapshot = packet / "artifacts/development-delivery/evidence" / f"validation-refresh-{request_digest}.json"
        with _file_lock(task.path.with_suffix(task.path.suffix + ".lock")):
            if (task.read() != current or _git(worktree, "rev-parse", "HEAD") != head
                    or _git(worktree, "branch", "--show-current") != current["worktree"]["branch"]
                    or _git(worktree, "status", "--porcelain")):
                _error("validation task/head changed during refresh preflight")
            if _read(request_path)[1] != request_digest:
                _error("successor validation changed during refresh preflight")
            if _read(predecessor_path)[1] != predecessor_digest:
                _error("validation predecessor changed during refresh preflight")
            if _read(Path(current["policy_receipt"]))[1] != evidence["policy_sha256"]:
                _error("validation frozen policy changed during refresh preflight")
            _commands({**evidence, "verified_at": payload["verified_at"]}, current, packet,
                      worktree, profile, head)
            if snapshot.exists() and snapshot.read_bytes() != request_path.read_bytes():
                _error("immutable validation refresh snapshot collision")
            if not snapshot.exists():
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                snapshot.write_bytes(request_path.read_bytes())
            now = utc_now()
            current.setdefault("receipts", []).append({"state": "local_validation", "kind": "validation_refresh",
                "ref": str(snapshot), "sha256": request_digest, "recorded_at": now})
            current.setdefault("validation_refreshes", []).append({"schema": "development-validation-refresh/v1",
                "idempotency_key": idempotency_key, "request_sha256": request_digest,
                "predecessor_ref": str(predecessor_path), "predecessor_sha256": predecessor_digest,
                "from_head_sha": old_head, "head_sha": head, "successor_ref": str(snapshot),
                "successor_sha256": request_digest, "policy_fingerprint": current["policy_fingerprint"], "recorded_at": now})
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
