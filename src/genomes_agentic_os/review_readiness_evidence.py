"""Canonical packet-local proof for review readiness; no model transport.

Development Delivery owns policy and execution receipts. This adapter projects
those receipts and complete GitHub readback without granting merge authority.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
from typing import Any

from .development_delivery import (
    DevelopmentDeliveryError, _file_lock, _validate_effective_policy_snapshot,
)

SHA = re.compile(r"[a-f0-9]{40}")
DIGEST = re.compile(r"[a-f0-9]{64}")
MAX_BYTES = 16 * 1024 * 1024
MAX_PAGES = 50
COPILOT_LOGINS = {"copilot-pull-request-reviewer[bot]", "github-copilot[bot]"}
THREAD_QUERY = """query($owner:String!,$repo:String!,$number:Int!,$cursor:String) {
 repository(owner:$owner,name:$repo) { pullRequest(number:$number) {
 reviewThreads(first:100,after:$cursor) {
 nodes { id isResolved isOutdated }
 pageInfo { hasNextPage endCursor }
 } } } }"""


def _json(path: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_BYTES:
        raise DevelopmentDeliveryError("readiness input exceeds bounded size")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DevelopmentDeliveryError("readiness input must be an object")
    return value


def _fresh(value: Any, now: datetime, maximum_age: int | None = None) -> bool:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        age = (now - stamp).total_seconds() if stamp.tzinfo else -1
        return age >= 0 and (maximum_age is None or age <= maximum_age)
    except (ValueError, TypeError, OverflowError):
        return False


def _bound(packet: Path, ref: Any) -> dict[str, Any]:
    if not isinstance(ref, Mapping) or not DIGEST.fullmatch(str(ref.get("sha256") or "")):
        raise DevelopmentDeliveryError("readiness input lacks content binding")
    path = (packet / str(ref.get("path") or ref.get("ref") or "")).resolve()
    if not path.is_relative_to(packet.resolve()) or not path.is_file():
        raise DevelopmentDeliveryError("readiness input escapes its packet")
    if path.stat().st_size > MAX_BYTES:
        raise DevelopmentDeliveryError("readiness input exceeds bounded size")
    if hashlib.sha256(path.read_bytes()).hexdigest() != ref["sha256"]:
        raise DevelopmentDeliveryError("readiness input bytes changed")
    return _json(path)


def _leaf(packet: Path, name: str, value: dict[str, Any]) -> dict[str, str]:
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    digest = hashlib.sha256(data).hexdigest()
    path = packet / "artifacts/finishing-touches/proofs" / f"{name}-{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != data:
        raise DevelopmentDeliveryError("immutable readiness proof collision")
    if not path.exists():
        path.write_bytes(data)
    return {"path": str(path.relative_to(packet)), "sha256": digest}


def _repository(value: Any) -> str:
    text = str(value or "")
    match = re.fullmatch(r"(?:git:|github:)?(?:git@github.com:|https://github.com/|github.com/)?([\w.-]+/[\w.-]+?)(?:\.git)?", text)
    return match[1] if match else ""


def _context(state_file: str | Path, head: str, policy: str) -> tuple[Path, dict, dict]:
    if not SHA.fullmatch(head) or not DIGEST.fullmatch(policy):
        raise DevelopmentDeliveryError("readiness requires exact head and policy")
    task = _json(Path(state_file))
    if task.get("schema") != "development-task/v1":
        raise DevelopmentDeliveryError("readiness task schema differs")
    packet = Path(task["work_item"]).resolve()
    manifest = _json(packet / "autodev.json")
    delivery = manifest.get("delivery") or {}
    if manifest.get("schema") != "auto-dev-work-item/v1" or not isinstance(delivery, dict):
        raise DevelopmentDeliveryError("canonical packet manifest schema differs")
    for owner in (manifest, delivery):
        for key in ("canonical_work_id", "run_id"):
            identity = owner.get(key)
            if identity is not None and (not isinstance(identity, str) or not identity or task.get(key) != identity):
                raise DevelopmentDeliveryError("canonical task work identity differs")
    if delivery.get("work_item") is not None and Path(delivery["work_item"]).resolve() != packet:
        raise DevelopmentDeliveryError("canonical delivery packet differs")
    if task.get("autodev_path") is not None and Path(task["autodev_path"]).resolve() != packet / "autodev.json":
        raise DevelopmentDeliveryError("canonical task manifest differs")
    if not (
        task.get("policy_fingerprint") == policy
        and delivery.get("policy_fingerprint") == policy
        and Path(str(delivery.get("task_state_ref") or "")).resolve() == Path(state_file).resolve()
        and Path(str(delivery.get("policy_receipt") or "")).resolve() == Path(task["policy_receipt"]).resolve()
    ):
        raise DevelopmentDeliveryError("canonical packet policy linkage differs")
    pinned = _json(Path(task["policy_receipt"]))
    selected = _validate_effective_policy_snapshot(pinned, require_selected_profile=True)
    if pinned["fingerprint"] != policy or selected["repository_id"] != task["repository"]["id"]:
        raise DevelopmentDeliveryError("selected policy belongs to another repository")
    return packet, task, dict(selected)


def _execution_argv(command: dict) -> tuple[list[str], dict[str, str]]:
    argv = command.get("command")
    if not isinstance(argv, list) or not all(isinstance(x, str) for x in argv):
        return [], {}
    environment: dict[str, str] = {}
    if argv and argv[0] == "env":
        argv = argv[1:]
        if argv and argv[0] == "-i":
            argv = argv[1:]
        while argv and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[0]):
            key, value = argv.pop(0).split("=", 1)
            environment[key] = value
    return argv, environment


def _matches_command(configured: str, actual: list[str], task: dict, selected: dict) -> bool:
    expected = shlex.split(configured)
    if not expected or len(actual) < len(expected):
        return False
    worktree = task["worktree"]["path"]
    def executable(value: str) -> str:
        return str(Path(worktree) / value) if value.startswith(".") else value
    accepted = executable(expected[0])
    mappings = selected.get("validation", {}).get("command_executables") or {}
    mapping = mappings.get(configured) if isinstance(mappings, dict) else None
    if mapping and selected.get("schema") == "development-selected-profile/v2":
        if not isinstance(mapping, dict) or mapping.get("authority") != "selected_profile":
            return False
        try:
            mapped = Path(mapping["executable"].format(work_item=task["work_item"], worktree=worktree))
            if not mapped.is_absolute():
                return False
            mapped = Path(os.path.abspath(mapped))
        except (KeyError, TypeError, ValueError, AttributeError):
            return False
        if not mapped.is_absolute() or not (mapped.is_relative_to(Path(task["work_item"])) or mapped.is_relative_to(Path(worktree))):
            return False
        accepted = str(mapped)
    if accepted != executable(actual[0]) or expected[1:] != actual[1:len(expected)]:
        return False
    extras = actual[len(expected):]
    if not extras:
        return True
    # Additional pytest selectors can reduce the required suite and are refused.
    return expected[1:3] == ["-m", "pytest"] and all(
        item == "--cov-branch" or item.startswith(("--cov=", "--cov-report=", "--cov-fail-under=", "--basetemp="))
        for item in extras
    )


def validation_proof(packet: Path, task: dict, selected: dict, head: str, policy: str, now: datetime) -> dict:
    proof = {"schema": "opposing-review-validation-evidence/v1", "head_sha": head,
             "policy_fingerprint": policy, "verified_at": now.isoformat(),
             "status": "unknown", "commands": [], "reasons": []}
    required = selected.get("validation", {}).get("commands")
    if not isinstance(required, list) or not required or not all(isinstance(c, str) and c for c in required):
        proof["reasons"].append("pinned validation commands absent")
        return proof
    rows = [r for r in task.get("receipts", []) if isinstance(r, dict) and r.get("state") == "local_validation"]
    if not rows:
        proof["reasons"].append("terminal local validation stage absent")
        return proof
    try:
        stage = _bound(packet, rows[-1])
        if not (stage.get("schema") == "development-stage-evidence/v1"
                and stage.get("state") == "local_validation"
                and stage.get("status") in {"passed", "deferred_to_ci"}
                and _fresh(stage.get("verified_at"), now)
                and stage.get("evidence", {}).get("head_sha") == head
                and stage.get("evidence", {}).get("policy_fingerprint") == policy):
            raise DevelopmentDeliveryError("stage does not establish completed validation")
        runs = stage.get("evidence", {}).get("validation_runs")
        if not isinstance(runs, list) or not runs:
            raise DevelopmentDeliveryError("actual terminal command bindings absent")
        for row in runs:
            terminal = _bound(packet, row.get("terminal"))
            command = _bound(packet, row.get("command_receipt"))
            argv, environment = _execution_argv(command)
            configured = row.get("command")
            if not (
                configured in required
                and command.get("id") == terminal.get("id")
                and command.get("work_dir") == task["worktree"]["path"]
                and environment.get("REVIEW_POLICY_FINGERPRINT") == policy
                and bool(_repository(selected["repository_id"]))
                and command.get("expected_git_identity", {}).get("worktree") == task["worktree"]["path"]
                and terminal.get("expected_git_identity", {}).get("worktree") == task["worktree"]["path"]
                and bool(task["worktree"].get("branch"))
                and _matches_command(configured, argv, task, selected)
                and terminal.get("schema") == "agentic-os-long-running-terminal/v1"
                and terminal.get("status") in {"success", "failure"}
                and type(terminal.get("exit_code")) is int
                and (terminal["status"] == "success") == (terminal["exit_code"] == 0)
                and _fresh(terminal.get("finished_at"), now)
                and all(terminal.get(field, {}).get("head") == head and terminal[field].get("clean") == "true"
                        and terminal[field].get("branch") == task["worktree"]["branch"]
                        and bool(_repository(terminal[field].get("repository")))
                        and _repository(terminal[field].get("repository")) == _repository(selected["repository_id"])
                        for field in ("git_identity_pre", "git_identity_post"))
                and terminal.get("post_run_invariants_ok") is True
            ):
                raise DevelopmentDeliveryError("terminal command subject, policy or execution differs")
            proof["commands"].append({"command": configured, "exit_code": terminal["exit_code"],
                                      "terminal": row["terminal"], "command_receipt": row["command_receipt"]})
        if any(row["exit_code"] != 0 for row in proof["commands"]):
            proof["status"] = "failed"
        elif stage["status"] == "passed" and set(required).issubset({r["command"] for r in proof["commands"]}):
            proof["status"] = "passed"
        else:
            proof["reasons"].append("validation incomplete or deferred; CI cannot invent a local pass")
    except (DevelopmentDeliveryError, OSError, ValueError, KeyError, TypeError, RuntimeError, AttributeError) as exc:
        proof["reasons"].append(str(exc))
    return proof


def _check_rows(value: Any) -> set[tuple[str, int]] | None:
    if not isinstance(value, list) or not value:
        return None
    result = set()
    for row in value:
        if not isinstance(row, dict) or not isinstance(row.get("context"), str) or not row["context"] or type(row.get("app_id")) is not int or row["app_id"] < -1 or row["app_id"] == 0:
            return None
        result.add((row["context"], row["app_id"]))
    return result if len(result) == len(value) else None


def _gate_projection(selected: dict, provider: dict, head: str, base: str, repository: str, number: int,
                    policy: str, now: datetime) -> tuple[dict, dict]:
    common = {"head_sha": head, "base_sha": base, "policy_fingerprint": policy,
              "verified_at": now.isoformat(), "provider": "github", "repository": repository, "pr_number": number}
    ci = {**common, "schema": "opposing-review-ci-evidence/v1", "status": "unknown", "readback_verified": False}
    copilot = {**common, "schema": "opposing-review-copilot-evidence/v1", "status": "unknown",
               "readback_verified": False, "review_received": False, "threads_complete": False,
               "actionable_thread_count": None}
    requirement = selected.get("review", {}).get("copilot", {}).get("required")
    explicit_review = selected.get("schema") == "development-selected-profile/v2" and type(requirement) is bool
    if explicit_review and requirement is False:
        copilot.update(status="not_applicable", policy_exempt=True)
    valid_subject = (
        provider.get("schema") == "github-review-gate-readback/v1"
        and SHA.fullmatch(head) and SHA.fullmatch(base)
        and type(number) is int and number > 0 and bool(repository)
        and provider.get("repository") == repository and provider.get("pr_number") == number
        and _fresh(provider.get("captured_at"), now, 300)
        and provider.get("before") == provider.get("after")
        and provider.get("after") == {"head_sha": head, "base_sha": base, "base_branch": selected.get("repository", {}).get("base_branch"), "state": "OPEN"}
    )
    if not valid_subject:
        ci["reason"] = copilot["reason"] = "provider readback stale, incomplete or changed subject"
        return ci, copilot
    validation = selected.get("validation") or {}
    contract = validation.get("ci_contract") or {}
    expected = _check_rows(contract.get("checks"))
    live = _check_rows(provider.get("required_checks"))
    if not (
        selected.get("schema") == "development-selected-profile/v2"
        and contract.get("schema") == "github-required-check-contract/v1"
        and contract.get("repository") == repository
        and contract.get("base_branch") == selected["repository"]["base_branch"]
        and contract.get("provider") == "github"
        and isinstance(contract.get("source"), dict)
        and contract["source"].get("url") == f"https://api.github.com/repos/{repository}/branches/{contract['base_branch']}/protection"
        and _fresh(contract["source"].get("captured_at"), now)
        and contract["source"].get("rules_complete") is True
        and contract["source"].get("route") in {"composio:GITHUB_GET_BRANCH_PROTECTION", "github_cli_api"}
        and isinstance(contract["source"].get("active_rules"), list)
        and isinstance(provider.get("active_rules"), list)
        and DIGEST.fullmatch(str(contract["source"].get("readback_sha256") or ""))
        and _check_rows(contract["source"].get("required_checks")) == expected
        and contract.get("drift_policy") == "block_until_context_refresh"
        and expected and live == expected and provider.get("rules_complete") is True
        and provider.get("active_rules") == contract["source"].get("active_rules")
        and set(validation.get("required_checks") or []) == {context for context, _ in expected}
        and provider.get("checks_complete") is True
    ):
        ci["reason"] = "pinned CI authority missing or differs from fresh provider contract"
    else:
        observed = provider.get("checks")
        states = []
        if isinstance(observed, list):
            for name, app_id in expected:
                matching = [r for r in observed if isinstance(r, dict) and r.get("name") == name
                            and type(r.get("app_id")) is int and r["app_id"] >= -1 and r["app_id"] != 0
                            and (app_id == -1 or r["app_id"] == app_id) and r.get("head_sha") == head]
                states.append([r.get("conclusion") if r.get("status") == "completed" else "PENDING" for r in matching])
        if not states or any(not state for state in states):
            ci["reason"] = "required context or application result missing"
        elif any(s in {"failure", "cancelled", "timed_out", "action_required", "error"} for row in states for s in row):
            ci.update(status="failed", readback_verified=True)
        elif any(s != "success" for row in states for s in row):
            ci.update(status="pending", readback_verified=True)
        else:
            ci.update(status="passed", readback_verified=True)
    if copilot.get("policy_exempt"):
        return ci, copilot
    if not explicit_review:
        copilot["reason"] = "explicit pinned Copilot requirement absent"
        return ci, copilot
    reviews, threads = provider.get("reviews"), provider.get("threads")
    if provider.get("reviews_complete") is not True or provider.get("threads_complete") is not True or not isinstance(reviews, list) or not isinstance(threads, list):
        copilot["reason"] = "review or thread pagination incomplete"
        return ci, copilot
    delivered = [r for r in reviews if isinstance(r, dict) and r.get("login") in COPILOT_LOGINS
                 and r.get("head_sha") == head and r.get("state") in {"APPROVED", "COMMENTED", "CHANGES_REQUESTED"}
                 and _fresh(r.get("submitted_at"), now)]
    if not delivered:
        copilot["reason"] = "no delivered Copilot review for current head"
        return ci, copilot
    if any(not isinstance(r, dict) or type(r.get("isResolved")) is not bool or type(r.get("isOutdated")) is not bool for r in threads):
        copilot["reason"] = "thread resolution evidence malformed"
        return ci, copilot
    latest = max(delivered, key=lambda r: datetime.fromisoformat(r["submitted_at"].replace("Z", "+00:00")))
    count = sum(not r["isResolved"] and not r["isOutdated"] for r in threads)
    if latest["state"] == "CHANGES_REQUESTED":
        count = max(count, 1)
    copilot.update(status="resolved" if count == 0 else "unresolved", readback_verified=True,
                   review_received=True, threads_complete=True, actionable_thread_count=count)
    return ci, copilot


def gate_projection(selected: dict, provider: dict, head: str, base: str, repository: str, number: int,
                    policy: str, now: datetime) -> tuple[dict, dict]:
    """Malformed policy or provider rows fail closed without keeping old passes."""
    try:
        return _gate_projection(selected, provider, head, base, repository, number, policy, now)
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError):
        common = {"head_sha": head, "base_sha": base, "policy_fingerprint": policy,
                  "verified_at": now.isoformat(), "status": "unknown", "readback_verified": False,
                  "reason": "policy or provider evidence malformed"}
        return ({**common, "schema": "opposing-review-ci-evidence/v1"},
                {**common, "schema": "opposing-review-copilot-evidence/v1", "review_received": False,
                 "threads_complete": False, "actionable_thread_count": None})


def emit_readiness_evidence(state_file: str | Path, *, head: str, policy: str,
                            provider: dict | None = None, now: datetime | None = None,
                            expected_packet: str | Path | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    packet, task, selected = _context(state_file, head, policy)
    if expected_packet is not None and packet != Path(os.path.abspath(expected_packet)):
        raise DevelopmentDeliveryError("emission packet differs from expected caller packet")
    repository = _repository(selected["repository_id"])
    live = provider or {}
    number = live.get("pr_number")
    before = live.get("before")
    base = before.get("base_sha") if isinstance(before, dict) else task["worktree"]["base_sha"]
    ci, copilot = gate_projection(selected, live, head, base, repository, number, policy, now)
    validation = validation_proof(packet, task, selected, head, policy, now)
    refs = {name: _leaf(packet, name, value) for name, value in
            (("validation", validation), ("ci", ci), ("copilot", copilot), ("provider", live))}
    envelope = {"schema": "opposing-review-readiness-evidence/v1", "head_sha": head,
                "policy_fingerprint": policy, "verified_at": now.isoformat(), **refs}
    path = packet / "artifacts/finishing-touches/readiness-evidence.json"
    with _file_lock(path.with_suffix(".lock")):
        temporary = path.with_suffix(".pending")
        temporary.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n")
        temporary.replace(path)
    return {"schema": "review-readiness-projection/v1", "envelope": str(path),
            "validation_status": validation["status"], "pr_check_status": ci["status"],
            "copilot_status": copilot["status"], "copilot_policy_exempt": bool(copilot.get("policy_exempt")),
            "readiness_evidence_verified": {"validation": validation["status"] == "passed",
                                          "ci": ci["status"] == "passed",
                                          "copilot": copilot["status"] in {"resolved", "not_applicable"}}}
def _github_json(arguments: list[str], worktree: str) -> Any:
    """Existing GitHub CLI transport; callers may inject a governed provider."""
    completed = subprocess.run(["gh", "api", *arguments], cwd=worktree,
                               capture_output=True, text=True, timeout=30)
    if completed.returncode:
        raise DevelopmentDeliveryError("GitHub gate readback unavailable")
    return json.loads(completed.stdout)


def collect_github_gate_readback(repository: str, number: int, worktree: str, *,
                                fetch: Callable[[list[str]], Any] | None = None,
                                now: datetime | None = None) -> dict:
    """Read every required result/page and bracket capture with exact subjects."""
    transport = fetch or (lambda args: _github_json(args, worktree))
    started = time.monotonic()
    def fetch(arguments: list[str]) -> Any:
        if time.monotonic() - started > 120:
            raise DevelopmentDeliveryError("GitHub capture exceeds bounded duration")
        return transport(arguments)
    now = now or datetime.now(timezone.utc)
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository) or type(number) is not int or number <= 0:
        raise DevelopmentDeliveryError("GitHub gate subject is invalid")
    prefix = f"repos/{repository}"
    def subject() -> dict:
        value = fetch([f"{prefix}/pulls/{number}"])
        return {"head_sha": value["head"]["sha"], "base_sha": value["base"]["sha"],
                "base_branch": value["base"]["ref"], "state": str(value["state"]).upper()}
    before = subject()
    def pages(endpoint: str, key: str | None = None) -> list:
        rows = []
        for page in range(1, MAX_PAGES + 1):
            value = fetch([f"{endpoint}{'&' if '?' in endpoint else '?'}per_page=100&page={page}"])
            chunk = value[key] if key else value
            if not isinstance(chunk, list) or len(chunk) > 100:
                raise DevelopmentDeliveryError("GitHub pagination shape differs")
            rows.extend(chunk)
            if len(chunk) < 100:
                return rows
        raise DevelopmentDeliveryError("GitHub pagination exceeds bounded capture")
    protection = fetch([f"{prefix}/branches/{before['base_branch']}/protection"])
    rules = pages(f"{prefix}/rules/branches/{before['base_branch']}")
    checks = pages(f"{prefix}/commits/{before['head_sha']}/check-runs?filter=latest", "check_runs")
    statuses = pages(f"{prefix}/commits/{before['head_sha']}/statuses")
    reviews = pages(f"{prefix}/pulls/{number}/reviews")
    owner, repo = repository.split("/")
    threads, cursor, cursors = [], None, set()
    for _ in range(MAX_PAGES):
        args = ["graphql", "-f", f"query={THREAD_QUERY}", "-F", f"owner={owner}", "-F", f"repo={repo}", "-F", f"number={number}"]
        if cursor is not None:
            args.extend(["-F", f"cursor={cursor}"])
        value = fetch(args)
        if value.get("errors"):
            raise DevelopmentDeliveryError("GitHub thread readback has GraphQL errors")
        connection = value["data"]["repository"]["pullRequest"]["reviewThreads"]
        info = connection["pageInfo"]
        if not isinstance(connection["nodes"], list) or len(connection["nodes"]) > 100 or type(info.get("hasNextPage")) is not bool:
            raise DevelopmentDeliveryError("GitHub thread pagination malformed")
        threads.extend(connection["nodes"])
        if not info["hasNextPage"]:
            break
        cursor = info.get("endCursor")
        if not isinstance(cursor, str) or not cursor or cursor in cursors:
            raise DevelopmentDeliveryError("GitHub thread pagination cannot prove completion")
        cursors.add(cursor)
    else:
        raise DevelopmentDeliveryError("GitHub thread pagination exceeds bounded capture")
    # Status contexts have no App identity. A pinned specific App cannot be
    # satisfied by one of these older status results.
    normalized_checks = [{"name": c.get("name"), "app_id": c.get("app", {}).get("id"),
                          "head_sha": c.get("head_sha"), "status": c.get("status"),
                          "conclusion": c.get("conclusion"), "id": c.get("id")} for c in checks]
    seen = set()
    for status in statuses:
        name = status.get("context")
        if name not in seen:
            normalized_checks.append({"name": name, "app_id": -1, "head_sha": before["head_sha"],
                                      "status": "completed", "conclusion": status.get("state"), "id": status.get("id")})
            seen.add(name)
    after = subject()
    return {"schema": "github-review-gate-readback/v1", "captured_at": now.isoformat(),
            "provider_route": "github_cli_api", "repository": repository, "pr_number": number,
            "before": before, "after": after, "rules_complete": True, "active_rules": rules,
            "required_checks": protection["required_status_checks"]["checks"],
            "checks_complete": True, "checks": normalized_checks, "reviews_complete": True,
            "reviews": [{"login": r.get("user", {}).get("login"), "state": r.get("state"),
                         "head_sha": r.get("commit_id"), "submitted_at": r.get("submitted_at"),
                         "id": r.get("id")} for r in reviews],
            "threads_complete": True, "threads": threads}


def refresh_packet_readiness(packet: str | Path, provider: dict, head: str, policy: str, *,
                             fetch: Callable[[list[str]], Any] | None = None,
                             now: datetime | None = None) -> dict:
    """Consumer hook: execute again for every fresh or reused model projection.

    A cached model receipt never substitutes for this new provider capture.
    Errors produce unknown CI/Copilot proof rather than retaining prior success.
    """
    packet = Path(packet).resolve()
    manifest = _json(packet / "autodev.json")
    state_file = manifest["delivery"]["task_state_ref"]
    context_packet, task, selected = _context(state_file, head, policy)
    if context_packet != packet:
        raise DevelopmentDeliveryError("caller packet differs from canonical task packet")
    repository = _repository(selected["repository_id"])
    try:
        live = collect_github_gate_readback(repository, provider.get("number"), task["worktree"]["path"],
                                           fetch=fetch, now=now)
        if live["after"]["head_sha"] != provider.get("headRefOid") or live["after"]["base_sha"] != provider.get("baseRefOid"):
            live["subject_mismatch"] = True
            live["after"]["state"] = "UNKNOWN"
    except (DevelopmentDeliveryError, OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError):
        live = {}
    return emit_readiness_evidence(state_file, head=head, policy=policy, provider=live, now=now, expected_packet=packet)
