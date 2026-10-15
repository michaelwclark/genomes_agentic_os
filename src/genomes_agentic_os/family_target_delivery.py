"""Exact sibling authority without retargeting a canonical delivery task.

This module records evidence; it never calls a provider or a review model.
The existing single-PR stage and lifecycle recorders remain authoritative for
the primary. A required sibling has its own immutable Finalize and merge entry.
"""

from __future__ import annotations

from contextlib import contextmanager
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

import yaml

from .auto_dev_orchestration import (
    AutoDevStateError,
    _atomic_json,
    _file_lock,
    _health_task_receipt,
    _read_json,
    _readiness_stage_authority,
    _pending_subject_supersession,
    _utc_now,
    _validate_auto_dev_stage_receipt,
    read_auto_dev_state,
    require_auto_dev_predecessors,
    validate_pull_request_authority,
)
from .review_coordination import ReviewCoordinationError, assert_exact_head_review_receipt


AUTHORITY_FIELDS = (
    "provider", "pull_request", "repository", "base_branch", "subject_revision",
    "author_identity", "author_kind",
)
MAX_PROVIDER_AGE_SECONDS = 600


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _bound(root: Path, descriptor: Any, label: str) -> tuple[dict[str, str], Path]:
    if not isinstance(descriptor, Mapping) or set(descriptor) != {"ref", "sha256"}:
        raise AutoDevStateError(f"{label} requires an exact ref/sha256 descriptor")
    raw = str(descriptor["ref"]).strip()
    path = Path(raw).expanduser()
    path = (path if path.is_absolute() else root / path).resolve()
    if not raw or not path.is_file() or str(descriptor["sha256"]) != _digest(path.read_bytes()):
        raise AutoDevStateError(f"{label} is missing or its immutable hash changed")
    return {"ref": str(path), "sha256": str(descriptor["sha256"])}, path


def _context(state_file: str | Path) -> dict[str, Any]:
    state = Path(state_file).expanduser().resolve()
    if state.is_dir():
        state /= "autodev.json"
    current = read_auto_dev_state(state)
    root = state.parent
    task_ref = current.get("delivery", {}).get("task_state_ref")
    if not task_ref:
        raise AutoDevStateError("family target requires the canonical linked delivery task")
    task_path = Path(task_ref).expanduser().resolve()
    task = _read_json(task_path)
    if (
        task.get("state") not in {"ready_for_merge", "merged"}
        or _pending_subject_supersession(task)
        or Path(str(task.get("autodev_path") or "")).resolve() != state
        or Path(str(task.get("work_item") or "")).resolve() != root
        or task.get("canonical_work_id") != current.get("canonical_work_id")
    ):
        raise AutoDevStateError("family target requires the unchanged ready canonical task")
    from .development_delivery import DevelopmentDeliveryError, _validate_effective_policy_snapshot

    policy_path = Path(str(task.get("policy_receipt") or "")).expanduser()
    if not policy_path.is_file():
        raise AutoDevStateError("family target requires the original frozen effective policy receipt")
    policy = _read_json(policy_path)
    try:
        selected_profile = _validate_effective_policy_snapshot(policy, require_selected_profile=True)
    except DevelopmentDeliveryError as exc:
        raise AutoDevStateError(str(exc)) from exc
    if not isinstance(selected_profile, Mapping) or selected_profile.get("repository_id") != task.get("repository", {}).get("id") or policy.get("fingerprint") != task.get("policy_fingerprint"):
        raise AutoDevStateError("family target frozen policy does not select the canonical repository")
    ready_path, ready = _health_task_receipt(task, "ready_for_merge", root, task_path=task_path)
    ready_evidence = ready.get("evidence", {})
    primary = validate_pull_request_authority(task, ready_evidence, "family primary readiness")
    primary["subject_revision"] = str(ready_evidence.get("subject_revision") or "")
    if not primary["subject_revision"] or any(
        value != primary["subject_revision"]
        for value in (task.get("subject_revision"), current.get("subject_revision"))
    ):
        raise AutoDevStateError("canonical reviewed subject drifted before family selection")
    identity = ready_evidence.get("review_identity_normalization")
    if isinstance(identity, Mapping):
        if identity.get("authority_kind") != "current_catalog" or identity.get("identity_shape") != "selected_catalog_alias_github" or identity.get("verified_by") != "frozen_task_catalog_origin_and_exact_provider_readback" or identity.get("selected_identity") != {"repository": primary["repository"], "pull_request": primary["pull_request"]}:
            raise AutoDevStateError("family target cannot reuse an unqualified primary catalog alias")
        alias_authority = ready_evidence.get("repository_alias_authority")
        if not isinstance(alias_authority, Mapping) or alias_authority.get("kind") != "current_catalog" or alias_authority.get("repository_id") != primary["repository"] or Path(str(alias_authority.get("root") or "")).expanduser().resolve() != Path(str(task["repository"].get("root") or "")).expanduser().resolve() or alias_authority.get("canonical_origin") != identity.get("canonical_origin"):
            raise AutoDevStateError("family target catalog alias must retain its accepted repository root and origin")
        canonical_origin = str(identity.get("canonical_origin") or "")
    else:
        canonical_origin = primary["repository"]
    canonical_origin = re.sub(r"^(?:git:github\.com/|github:|https://github\.com/)", "", canonical_origin).removesuffix(".git")
    if not re.fullmatch(r"[^/]+/[^/]+", canonical_origin):
        raise AutoDevStateError("family target requires accepted canonical repository identity or current-catalog alias proof")
    descriptor = task.get("stage_receipts", {}).get("release_propagation")
    family_binding, family_path = _bound(root, descriptor, "active release-propagation wrapper")
    wrapper = _read_json(family_path)
    ref = Path(str(wrapper.get("receipt") or ""))
    evidence_path = (ref if ref.is_absolute() else root / ref).resolve()
    if not evidence_path.is_relative_to(root) or not evidence_path.is_file():
        raise AutoDevStateError("release-propagation evidence must be packet-local")
    family_evidence = _read_json(evidence_path)
    if not (
        wrapper.get("schema") == "development-stage-receipt/v1"
        and wrapper.get("stage") == "release_propagation"
        and wrapper.get("evidence_sha256") == _digest(_canonical(family_evidence))
        and family_evidence.get("schema") == "development-stage-evidence/v1"
        and family_evidence.get("state") == "release_propagation"
        and family_evidence.get("status") in {"completed", "passed", "verified"}
    ):
        raise AutoDevStateError("active typed release-propagation evidence changed or is incomplete")
    details = family_evidence.get("evidence", {})
    if not isinstance(details, Mapping) or any(
        str(details.get(key) or "") != primary[key]
        for key in ("provider", "repository", "pull_request", "base_branch")
    ) or details.get("subject_revision") != primary["subject_revision"]:
        raise AutoDevStateError("typed family must retain its canonical primary identity")
    family = details.get("family")
    if not isinstance(family, list) or len(family) < 2:
        raise AutoDevStateError("family target requires an existing multi-target typed family")
    required: dict[str, dict[str, Any]] = {}
    for row in family:
        if not isinstance(row, Mapping):
            raise AutoDevStateError("typed family members must be objects")
        if row.get("classification") != "pr_required":
            continue
        identity = {
            "provider": str(row.get("provider") or primary["provider"]),
            "repository": str(row.get("repository") or primary["repository"]),
            "pull_request": str(row.get("pull_request") or ""),
            "base_branch": str(row.get("base_branch") or ""),
            "subject_revision": str(row.get("source_head") or ""),
            "base_sha": str(row.get("base_sha") or ""),
            "source_branch": str(row.get("source_branch") or ""),
        }
        if (
            not all(identity.values())
            or not all(re.fullmatch(r"[0-9a-f]{40}", identity[k]) for k in ("base_sha", "subject_revision"))
            or row.get("readback_verified") is not True
            or identity["repository"] != primary["repository"]
            or identity["provider"] != primary["provider"]
        ):
            raise AutoDevStateError("required family member lacks exact provider/base/source identity")
        key = _digest(_canonical(identity))
        if key in required or any(r["pull_request"] == identity["pull_request"] for r in required.values()):
            raise AutoDevStateError("typed family has duplicate or ambiguous required targets")
        required[key] = identity
    primaries = [r for r in required.values() if all(r[k] == primary[k] for k in ("provider", "repository", "pull_request", "base_branch", "subject_revision"))]
    if len(primaries) != 1 or len(required) < 2:
        raise AutoDevStateError("typed family must contain its exact primary and a required sibling")
    return {"state": state, "current": current, "root": root, "task_path": task_path,
            "task": task, "primary": primary, "family": required, "family_binding": family_binding,
            "review_policy_fingerprints": {
                str(task.get("policy_fingerprint") or ""),
                str(ready_evidence.get("review_policy_fingerprint") or task.get("policy_fingerprint") or ""),
            },
            "primary_ready_binding": {"ref": str(ready_path), "sha256": _digest(ready_path.read_bytes())},
            "canonical_origin": canonical_origin, "policy_binding": {"ref": str(policy_path.resolve()), "sha256": _digest(policy_path.read_bytes())}}


def _target(context: Mapping[str, Any], evidence: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    matches = [(key, row) for key, row in context["family"].items() if all(
        str(evidence.get(field) or "") == str(row[field])
        for field in ("provider", "repository", "pull_request", "base_branch", "subject_revision", "base_sha", "source_branch")
    )]
    if len(matches) != 1:
        raise AutoDevStateError("selected target does not equal one required typed family member")
    key, selected = matches[0]
    if selected["pull_request"] == context["primary"]["pull_request"]:
        raise AutoDevStateError("primary Finalize and Merge remain owned by the ordinary stage recorders")
    return key, selected


def _git(worktree: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(worktree), *args], capture_output=True, check=False)
    if result.returncode:
        raise AutoDevStateError("family target source checkout cannot prove its exact git scope")
    return result.stdout


def _source(context: Mapping[str, Any], target: Mapping[str, str], data: Mapping[str, Any]) -> str:
    path = Path(str(data.get("worktree") or "")).expanduser().resolve()
    repository_root = Path(context["task"]["repository"]["root"]).expanduser().resolve()
    registered = _git(repository_root, "worktree", "list", "--porcelain").decode().splitlines()
    if f"worktree {path}" not in registered:
        raise AutoDevStateError("family target source must use a registered checkout of the selected repository")
    if _git(path, "rev-parse", "HEAD").decode().strip() != target["subject_revision"]:
        raise AutoDevStateError("family target checkout head drifted")
    if _git(path, "diff", "--name-only", "HEAD"):
        raise AutoDevStateError("family target tracked source must be clean")
    branch = _git(path, "branch", "--show-current").decode().strip()
    if branch != target["source_branch"]:
        # A configured release ref may share the exact accepted primary source.
        # Keep its provider ref identity separate from this registered checkout.
        primary_worktree = context["task"].get("worktree", {})
        if (path != Path(str(primary_worktree.get("path") or "")).expanduser().resolve()
            or branch != primary_worktree.get("branch")
            or target["subject_revision"] != context["primary"]["subject_revision"]):
            raise AutoDevStateError("family target source branch drifted")
    if _git(path, "rev-parse", "HEAD^{tree}").decode().strip() != data.get("tree_sha"):
        raise AutoDevStateError("family target source tree drifted")
    if _git(path, "rev-parse", f"{target['base_sha']}^{{commit}}").decode().strip() != target["base_sha"]:
        raise AutoDevStateError("family target direct base is unavailable")
    diff = _git(path, "diff", "--binary", target["base_sha"], target["subject_revision"], "--")
    if not diff or data.get("full_diff_sha256") != _digest(diff):
        raise AutoDevStateError("family target proof must bind the complete direct-base binary diff")
    origin = _git(path, "remote", "get-url", "origin").decode().strip()
    match = re.fullmatch(r"(?:git@github\.com:|https://github\.com/)([^/]+/[^/]+?)(?:\.git)?", origin)
    if not match:
        raise AutoDevStateError("family target requires a qualified GitHub origin")
    if match.group(1).lower() != context["canonical_origin"].lower():
        raise AutoDevStateError("family target origin differs from the accepted selected repository authority")
    return match.group(1)


def _fresh(raw: Any) -> None:
    try:
        timestamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - timestamp).total_seconds()
    except (TypeError, ValueError) as exc:
        raise AutoDevStateError("family target provider observation requires a UTC timestamp") from exc
    if age < -30 or age > MAX_PROVIDER_AGE_SECONDS:
        raise AutoDevStateError("family target provider observation is stale")


def _ci_skip(root: Path, skip: Mapping[str, Any], target: Mapping[str, str], worktree: Path) -> str:
    """Prove the supported main-only Conventional Commits exclusion from source."""
    _, path = _bound(root, skip.get("proof"), "CI skip applicability")
    evidence = _read_json(path)
    workflow_path = Path(str(evidence.get("workflow_path") or ""))
    if workflow_path.is_absolute() or ".." in workflow_path.parts or not workflow_path.parts:
        raise AutoDevStateError("CI skip applicability requires a repository-relative workflow")
    workflow = yaml.safe_load(_git(worktree, "show", f"{target['subject_revision']}:{workflow_path.as_posix()}"))
    jobs = workflow.get("jobs") if isinstance(workflow, Mapping) else None
    job = jobs.get(str(evidence.get("job_id") or "")) if isinstance(jobs, Mapping) else None
    condition = str(job.get("if") or "").strip() if isinstance(job, Mapping) else ""
    expected_condition = "github.event_name == 'pull_request' && github.base_ref != 'main'"
    if not (
        evidence.get("schema") == "auto-dev-ci-applicability/v1"
        and evidence.get("event_name") == "pull_request"
        and evidence.get("base_branch") == target["base_branch"] == "main"
        and evidence.get("subject_revision") == target["subject_revision"]
        and evidence.get("status") == "not_applicable"
        and condition == evidence.get("condition") == expected_condition
        and isinstance(job, Mapping) and job.get("name") == skip.get("name")
        and skip.get("reason")
    ):
        raise AutoDevStateError("CI skip is not justified by this exact PR event, target and workflow condition")
    return str(skip["name"])


def _ci_workflows(worktree: Path, target: Mapping[str, str]) -> dict[str, Counter[str]]:
    """Derive the required static PR jobs from the exact source, not current results."""
    expected: dict[str, Counter[str]] = {}
    paths = _git(worktree, "ls-tree", "-r", "--name-only", target["subject_revision"], ".github/workflows/").decode().splitlines()
    for path in paths:
        if not path.endswith((".yml", ".yaml")):
            continue
        workflow = yaml.safe_load(_git(worktree, "show", f"{target['subject_revision']}:{path}"))
        if not isinstance(workflow, Mapping):
            raise AutoDevStateError("target workflow cannot prove the required CI inventory")
        triggers = workflow.get("on", workflow.get(True))
        if isinstance(triggers, str):
            triggers = {triggers: None}
        if isinstance(triggers, list):
            triggers = dict.fromkeys(triggers)
        if not isinstance(triggers, Mapping):
            continue
        if "pull_request_target" in triggers:
            raise AutoDevStateError("pull_request_target CI inventory requires a dedicated source adapter")
        if "pull_request" not in triggers:
            continue
        event = triggers["pull_request"] or {}
        if not isinstance(event, Mapping) or any(key in event for key in ("paths", "paths-ignore")):
            raise AutoDevStateError("path-filtered PR CI inventory requires a dedicated source adapter")
        for field in ("branches", "branches-ignore"):
            values = event.get(field, [])
            if not isinstance(values, list) or any(not isinstance(value, str) or re.search(r"[*?!\[${]", value) for value in values):
                raise AutoDevStateError("dynamic PR branch filters require a dedicated CI inventory adapter")
        if event.get("branches") and target["base_branch"] not in event["branches"]:
            continue
        if target["base_branch"] in event.get("branches-ignore", []):
            continue
        jobs = workflow.get("jobs")
        if not isinstance(jobs, Mapping) or not jobs:
            raise AutoDevStateError("applicable PR workflow has no verifiable CI jobs")
        names: Counter[str] = Counter()
        for key, job in jobs.items():
            if not isinstance(job, Mapping) or job.get("strategy") or "${{" in str(job.get("name") or ""):
                raise AutoDevStateError("dynamic PR jobs require a dedicated CI inventory adapter")
            names[str(job.get("name") or key)] += 1
        expected[path] = names
    if not expected:
        raise AutoDevStateError("family target has no source-bound required PR check inventory")
    return expected


def _ci_inventory(worktree: Path, target: Mapping[str, str]) -> Counter[str]:
    return sum(_ci_workflows(worktree, target).values(), Counter())


def _ci_events(payload: Mapping[str, Any], worktree: Path, target: Mapping[str, str], checks: list[Any], github_repository: str) -> None:
    """Bind each required job to the latest actual PR-event run, not a push namesake."""
    response = payload.get("workflow_runs")
    if not isinstance(response, Mapping) or response.get("complete") is not True:
        raise AutoDevStateError("family target requires complete provider PR workflow-run inventory")
    runs = response.get("workflow_runs")
    if not isinstance(runs, list) or not runs or response.get("total_count") != len(runs):
        raise AutoDevStateError("provider PR workflow-run inventory is incomplete")
    jobs_by_run = payload.get("workflow_jobs")
    if not isinstance(jobs_by_run, Mapping):
        raise AutoDevStateError("family target requires actual provider jobs for each PR workflow run")
    for path, required in _ci_workflows(worktree, target).items():
        applicable = []
        for run in runs:
            if not isinstance(run, Mapping) or run.get("path") != path or run.get("event") != "pull_request":
                continue
            if run.get("head_sha") != target["subject_revision"] or run.get("head_branch") != target["source_branch"]:
                continue
            prs = run.get("pull_requests")
            if not isinstance(prs, list) or not any(isinstance(pr, Mapping) and str(pr.get("number")) == target["pull_request"].rsplit("#", 1)[-1]
                and pr.get("head", {}).get("sha") == target["subject_revision"]
                and pr.get("base", {}).get("sha") == target["base_sha"]
                and pr.get("base", {}).get("ref") == target["base_branch"] for pr in prs):
                continue
            applicable.append(run)
        if not applicable:
            raise AutoDevStateError("required source CI has no exact PR-event run; push checks cannot substitute")
        if any(not run.get("created_at") or not str(run.get("id") or "").isdecimal() for run in applicable):
            raise AutoDevStateError("PR-event workflow run lacks provider identity and creation time")
        latest = max(applicable, key=lambda run: (str(run["created_at"]), int(run["id"])))
        if latest.get("head_repository", {}).get("full_name") != github_repository or latest.get("html_url") != f"https://github.com/{github_repository}/actions/runs/{latest['id']}":
            raise AutoDevStateError("required PR-event run is not owned by the selected source repository")
        if latest.get("status") != "completed" or latest.get("conclusion") != "success":
            raise AutoDevStateError("latest exact PR-event CI run is pending or failed")
        result = jobs_by_run.get(str(latest["id"]))
        jobs = result.get("jobs") if isinstance(result, Mapping) else None
        if not isinstance(jobs, list) or not jobs or result.get("total_count") != len(jobs):
            raise AutoDevStateError("required PR-event jobs response is incomplete")
        if any(not isinstance(job, Mapping) or not str(job.get("id") or "").isdecimal() for job in jobs) or len({str(job["id"]) for job in jobs}) != len(jobs):
            raise AutoDevStateError("required PR-event jobs lack unique provider job identities")
        observed: Counter[str] = Counter()
        for job in jobs:
            if not isinstance(job, Mapping) or str(job.get("run_id")) != str(latest["id"]) or job.get("head_sha") != target["subject_revision"] or job.get("status") != "completed":
                raise AutoDevStateError("provider CI job differs from the exact completed PR-event run")
            if job.get("html_url") != f"https://github.com/{github_repository}/actions/runs/{latest['id']}/job/{job['id']}":
                raise AutoDevStateError("provider CI job URL differs from its exact PR-event workflow identity")
            matches = [check for check in checks if isinstance(check, Mapping) and check.get("name") == job.get("name")
                       and check.get("detailsUrl") == job.get("html_url") and job.get("html_url")]
            if not matches or any(str(check.get("conclusion") or "").lower() != job.get("conclusion") for check in matches):
                raise AutoDevStateError("current PR checks do not bind the actual PR-event job identity/result")
            observed[str(job.get("name") or "")] += 1
        if observed != required:
            raise AutoDevStateError("actual PR-event run omits required source workflow jobs")


def _provider(root: Path, descriptor: Any, target: Mapping[str, str], *, github_repository: str,
              author_identity: str, fresh: bool, worktree: Path, merged: bool = False) -> tuple[dict[str, str], dict[str, Any]]:
    bound, path = _bound(root, descriptor, "target provider readback")
    payload = _read_json(path)
    if fresh:
        _fresh(payload.get("observed_at"))
    pr = payload.get("pr")
    if not isinstance(pr, Mapping) or payload.get("readback_verified") is not True:
        raise AutoDevStateError("family target requires actual provider PR readback")
    number = str(pr.get("number") or "")
    expected_number = target["pull_request"].rsplit("#", 1)[-1]
    if not number.isdecimal() or number != expected_number or any(
        str(pr.get(field) or "") != value for field, value in {
            "url": f"https://github.com/{github_repository}/pull/{number}",
            "baseRefName": target["base_branch"],
            **({} if merged else {"baseRefOid": target["base_sha"]}),
            "headRefName": target["source_branch"], "headRefOid": target["subject_revision"],
            "state": "MERGED" if merged else "OPEN",
        }.items()
    ) or "github:" + str(pr.get("author", {}).get("login") or "").lower() != author_identity:
        raise AutoDevStateError("family target provider PR/base/head/authorship differs from selected authority")
    if merged:
        sha = pr.get("mergeCommit", {}).get("oid")
        if not re.fullmatch(r"[0-9a-f]{40}", str(sha)) or not pr.get("mergedAt"):
            raise AutoDevStateError("family merge readback requires a provider merge commit and mergedAt")
        return bound, payload
    if pr.get("isDraft") is not False or pr.get("mergeable") != "MERGEABLE":
        raise AutoDevStateError("family target PR is draft, conflicted, or mergeability is unknown")
    checks = pr.get("statusCheckRollup")
    skips = payload.get("allowed_skips", [])
    if not isinstance(skips, list):
        raise AutoDevStateError("CI skip applicability must be a list")
    allowed: set[str] = set()
    for skip in skips:
        if not isinstance(skip, Mapping) or not skip.get("reason") or not skip.get("name"):
            raise AutoDevStateError("intentional CI skips require named applicability evidence")
        allowed.add(_ci_skip(root, skip, target, worktree))
    if not isinstance(checks, list) or not checks:
        raise AutoDevStateError("family target requires nonempty current provider checks")
    names = Counter(str(check.get("name") or check.get("context") or "") for check in checks if isinstance(check, Mapping))
    if any(count > names[name] for name, count in _ci_inventory(worktree, target).items()):
        raise AutoDevStateError("family target provider readback omits required source CI jobs")
    _ci_events(payload, worktree, target, checks, github_repository)
    for check in checks:
        if not isinstance(check, Mapping):
            raise AutoDevStateError("family target provider check is malformed")
        conclusion = str(check.get("conclusion") or "").upper()
        if check.get("__typename") == "StatusContext":
            valid = check.get("state") == "SUCCESS"
        else:
            valid = check.get("status") == "COMPLETED" and (
                conclusion == "SUCCESS" or conclusion == "SKIPPED" and check.get("name") in allowed
            )
        if not valid:
            raise AutoDevStateError("family target CI has failed, pending, or inapplicable checks")
    threads = payload.get("review_threads")
    if not isinstance(threads, Mapping) or threads.get("pageInfo", {}).get("hasNextPage") is not False or not isinstance(threads.get("nodes"), list):
        raise AutoDevStateError("family target requires complete provider review-thread pagination")
    if any(not isinstance(row, Mapping) or not (row.get("isResolved") is True or row.get("isOutdated") is True) for row in threads["nodes"]):
        raise AutoDevStateError("family target has unresolved current review threads")
    return bound, payload


def _proof(root: Path, descriptor: Any, target: Mapping[str, str], label: str) -> dict[str, str]:
    bound, path = _bound(root, descriptor, label)
    payload = _read_json(path)
    if payload.get("schema") != "auto-dev-stage-evidence/v1" or not payload.get("summary") or not payload.get("verified_at") or payload.get("subject_revision") != target["subject_revision"] or payload.get("status") not in {"passed", "completed", "satisfactory"}:
        raise AutoDevStateError(f"{label} must pass for the exact sibling source")
    details = payload.get("evidence")
    if not isinstance(details, Mapping) or any(str(details.get(k) or "") != target[k] for k in ("repository", "pull_request", "base_branch", "base_sha")):
        raise AutoDevStateError(f"{label} lacks exact sibling repository/PR/base scope")
    expected_stage = {"target acceptance": "document", "target qa": "qa", "target secondary_review": "review_self",
                      "target release validation": "validate_production_release"}.get(label)
    if expected_stage is None or payload.get("stage") != expected_stage:
        raise AutoDevStateError(f"{label} has the wrong proof kind/stage")
    refs = details.get("receipt_refs")
    if not isinstance(refs, list) or not refs:
        raise AutoDevStateError(f"{label} requires hashed actual proof receipts")
    for ref in refs:
        _bound(root, ref, label + " proof")
    return bound


def _release_proofs(root: Path, details: Mapping[str, Any], target: Mapping[str, str]) -> None:
    known: dict[str, str] = {}
    for field in ("receipt_refs", "qa_runs", "contract_test_runs", "runtime_readbacks", "provider_readbacks"):
        refs = details.get(field)
        if not isinstance(refs, list) or not refs:
            raise AutoDevStateError(f"target release validation requires hashed {field}")
        for ref in refs:
            descriptor, _ = _bound(root, ref, "target release " + field)
            known[descriptor["ref"]] = descriptor["sha256"]
            if field == "qa_runs":
                _proof(root, ref, target, "target qa")
    for field in ("consumer_contract_matrix", "tenant_impact_matrix", "check_matrix"):
        for row in details[field]:
            if not isinstance(row, Mapping):
                raise AutoDevStateError("target release matrix row must be structured evidence")
            ref = row.get("evidence_ref")
            if not ref:
                raise AutoDevStateError("target release matrix row requires a hashed evidence_ref")
            path = Path(str(ref)).expanduser()
            path = (path if path.is_absolute() else root / path).resolve()
            sha = row.get("evidence_sha256") or known.get(str(path))
            _bound(root, {"ref": str(path), "sha256": sha}, "target release matrix proof")


def _validate_finalize(context: Mapping[str, Any], payload: Mapping[str, Any], *, fresh: bool) -> tuple[str, dict[str, Any], list[dict[str, str]]]:
    if not (
        payload.get("schema") == "auto-dev-stage-evidence/v1"
        and payload.get("stage") == "finalize" and payload.get("status") == "completed"
        and payload.get("summary") and payload.get("verified_at")
    ):
        raise AutoDevStateError("family target Finalize requires completed typed stage evidence")
    details = payload.get("evidence")
    if not isinstance(details, Mapping):
        raise AutoDevStateError("family target Finalize requires structured evidence")
    details = {**details, "subject_revision": payload.get("subject_revision")}
    if details.get("readiness_scope") != "source":
        raise AutoDevStateError("family target authority must explicitly qualify source readiness only")
    key, target = _target(context, details)
    authority = _readiness_stage_authority("finalize", payload, target["subject_revision"])
    if authority["author_identity"] not in {str(x).lower() for x in context["task"].get("authorship", {}).get("ours", [])}:
        raise AutoDevStateError("family target Finalize can authorize only configured own authors")
    source = details.get("source_scope")
    if not isinstance(source, Mapping):
        raise AutoDevStateError("family target requires its own complete source scope")
    github_repository = _source(context, target, source)
    provider, _ = _provider(context["root"], details.get("provider_readback"), target,
                            github_repository=github_repository, author_identity=authority["author_identity"], fresh=fresh,
                            worktree=Path(source["worktree"]))
    proofs = [provider]
    review, path = _bound(context["root"], details.get("canonical_review"), "canonical target review")
    policy = str(details.get("review_policy_fingerprint") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", policy) or policy not in context["review_policy_fingerprints"]:
        raise AutoDevStateError("target canonical review requires its explicit frozen policy fingerprint")
    try:
        receipt = assert_exact_head_review_receipt(path, head_sha=target["subject_revision"], repository=github_repository,
                    policy_fingerprint=policy)
    except ReviewCoordinationError as exc:
        raise AutoDevStateError(str(exc)) from exc
    subject = receipt["subject"]
    canonical_pr = f"{github_repository}#{target['pull_request'].rsplit('#', 1)[-1]}".lower()
    if str(subject.get("pull_request") or "").lower() not in {canonical_pr, "github:" + canonical_pr} or subject.get("base_branch") != target["base_branch"] or subject.get("base_sha") != target["base_sha"] or subject.get("purpose") != "review_self":
        raise AutoDevStateError("canonical target review must bind the full exact direct-base subject")
    proofs.append(review)
    for label in ("acceptance", "qa", "secondary_review"):
        proofs.append(_proof(context["root"], details.get(label), target, "target " + label))
    release, release_path = _bound(context["root"], details.get("release_validation"), "target release validation")
    release_evidence = _read_json(release_path)
    if release_evidence.get("schema") != "auto-dev-stage-evidence/v1" or release_evidence.get("stage") != "validate_production_release" or release_evidence.get("status") != "completed":
        raise AutoDevStateError("target requires its own typed production-release validation")
    release_authority = _readiness_stage_authority("validate_production_release", release_evidence, str(release_evidence.get("subject_revision") or ""))
    if release_authority != authority:
        raise AutoDevStateError("target release validation must authorize this exact sibling")
    if any(not isinstance(row, Mapping) or row.get("status") != "pass" for row in release_evidence["evidence"]["check_matrix"]):
        raise AutoDevStateError("target release validation has a failing or pending check")
    _proof(context["root"], details.get("release_validation"), target, "target release validation")
    _release_proofs(context["root"], release_evidence["evidence"], target)
    proofs.append(release)
    return key, {**target, **authority}, proofs


@contextmanager
def _family_lock(state: Path):
    """Use the delivery recorder's task-before-projection lock order."""
    current = read_auto_dev_state(state)
    task_ref = current.get("delivery", {}).get("task_state_ref")
    if not task_ref:
        raise AutoDevStateError("family target requires a linked canonical task")
    task_path = Path(task_ref).expanduser().resolve()
    with _file_lock(task_path.with_suffix(task_path.suffix + ".lock")):
        with _file_lock(state.with_suffix(state.suffix + ".lock")):
            yield


def record_family_target_finalize(state_file: str | Path, *, evidence_file: str | Path, idempotency_key: str) -> dict[str, Any]:
    """Record a sibling's immutable decision, without changing the primary stage."""
    state = Path(state_file).expanduser().resolve()
    if state.is_dir():
        state /= "autodev.json"
    with _family_lock(state):
        context = _context(state)
        require_auto_dev_predecessors(state, "finalize")
        payload = _read_json(Path(evidence_file).expanduser().resolve())
        key, authority, proofs = _validate_finalize(context, payload, fresh=True)
        if not str(idempotency_key).strip():
            raise AutoDevStateError("family target Finalize requires an idempotency key")
        wrapper = {"schema": "auto-dev-family-target-finalize/v1", "target_key": key,
                   "canonical_work_id": context["task"]["canonical_work_id"],
                   "family_binding": context["family_binding"], "policy_binding": context["policy_binding"],
                   "primary_ready_binding": context["primary_ready_binding"], "authority": authority,
                   "evidence_snapshot": payload, "evidence_sha256": _digest(_canonical(payload)),
                   "proofs": proofs, "idempotency_key": idempotency_key}
        token = _digest(_canonical([idempotency_key, key]))[:24]
        output = context["root"] / "artifacts/auto-dev-orchestration/family-targets" / key / "finalize" / f"{token}.json"
        if output.exists():
            if _read_json(output) != wrapper:
                raise AutoDevStateError("family target Finalize idempotency key already has different evidence")
        else:
            _atomic_json(output, wrapper)
        descriptor = {"owner": "family_target_finalize", "target_key": key,
                      "ref": str(output), "sha256": _digest(output.read_bytes()), **{k: authority[k] for k in AUTHORITY_FIELDS}}
        current = read_auto_dev_state(state)
        rows = current.setdefault("family_targets", {})
        rows[key] = {"finalize": descriptor}
        _atomic_json(state, current)
        return descriptor


def _load_target(context: Mapping[str, Any], descriptor: Mapping[str, Any], *, fresh: bool) -> dict[str, Any]:
    required = {"owner", "target_key", "ref", "sha256", *AUTHORITY_FIELDS}
    if set(descriptor) != required or descriptor.get("owner") != "family_target_finalize":
        raise AutoDevStateError("family readiness requires an exact immutable target Finalize descriptor")
    key = str(descriptor["target_key"])
    if context["current"].get("family_targets", {}).get(key, {}).get("finalize") != descriptor:
        raise AutoDevStateError("family target Finalize is not the current recorded immutable decision")
    _, path = _bound(context["root"], {k: descriptor[k] for k in ("ref", "sha256")}, "target Finalize")
    wrapper = _read_json(path)
    payload = wrapper.get("evidence_snapshot")
    if not isinstance(payload, Mapping) or not (
        wrapper.get("schema") == "auto-dev-family-target-finalize/v1"
        and wrapper.get("canonical_work_id") == context["task"]["canonical_work_id"]
        and wrapper.get("family_binding") == context["family_binding"]
        and wrapper.get("policy_binding") == context["policy_binding"]
        and wrapper.get("primary_ready_binding") == context["primary_ready_binding"]
        and wrapper.get("evidence_sha256") == _digest(_canonical(payload))
    ):
        raise AutoDevStateError("family target immutable decision or active family binding drifted")
    expected_path = context["root"] / "artifacts/auto-dev-orchestration/family-targets" / key / "finalize" / f"{_digest(_canonical([wrapper.get('idempotency_key'), key]))[:24]}.json"
    if path != expected_path:
        raise AutoDevStateError("family target authority must reference its actual immutable recorder output")
    actual_key, authority, proofs = _validate_finalize(context, payload, fresh=fresh)
    if actual_key != key or wrapper.get("target_key") != key or wrapper.get("authority") != authority or wrapper.get("proofs") != proofs or any(descriptor[k] != authority[k] for k in AUTHORITY_FIELDS):
        raise AutoDevStateError("family target decision does not equal its described authority")
    return wrapper


def require_family_readiness(state_file: str | Path, *, fresh: bool = True) -> None:
    """Require the primary decision and every required sibling before a merge."""
    context = _context(state_file)
    row = context["current"].get("stages", {}).get("finalize", {})
    if row.get("status") != "completed":
        raise AutoDevStateError("family merge requires the ordinary primary Finalize decision")
    candidates = [row.get("run_ref"), *(row.get("receipt_refs") or [])]
    primary_valid = False
    primary_evidence: Mapping[str, Any] = {}
    for raw in candidates:
        path = Path(str(raw or ""))
        path = (path if path.is_absolute() else context["root"] / path).resolve()
        if not path.is_file():
            continue
        wrapper = _validate_auto_dev_stage_receipt(context["root"], "finalize", "completed", path)
        actual = _readiness_stage_authority("finalize", wrapper["evidence_snapshot"], str(wrapper.get("subject_revision") or ""))
        if actual == context["primary"]:
            primary_valid = True
            primary_evidence = wrapper["evidence_snapshot"]
            break
    if not primary_valid:
        raise AutoDevStateError("ordinary primary Finalize no longer matches the typed family")
    if context["task"].get("state") == "merged":
        _, merged = _health_task_receipt(context["task"], "merged", context["root"], task_path=context["task_path"])
        merged_evidence = merged.get("evidence", {})
        if not isinstance(merged_evidence, Mapping) or merged.get("status") != "completed" or merged_evidence.get("readback_verified") is not True or merged_evidence.get("source_head_sha") != context["primary"]["subject_revision"] or not re.fullmatch(r"[0-9a-f]{40}", str(merged_evidence.get("merge_sha") or "")) or any(merged_evidence.get(key) != context["primary"][key] for key in ("provider", "repository", "pull_request", "base_branch", "author_identity", "author_kind")):
            raise AutoDevStateError("merged primary counterpart lacks exact immutable provider merge evidence")
    elif fresh:
        _fresh(primary_evidence.get("verified_at"))
    for key, target in context["family"].items():
        if target["pull_request"] == context["primary"]["pull_request"]:
            continue
        descriptor = context["current"].get("family_targets", {}).get(key, {}).get("finalize")
        if not isinstance(descriptor, Mapping):
            raise AutoDevStateError("family merge lacks a required sibling's own Finalize decision")
        merged_binding = context["task"].get("family_merges", {}).get(key)
        if merged_binding:
            _, path = _bound(context["root"], merged_binding, "merged sibling counterpart")
            merged = _read_json(path)
            if merged.get("schema") != "auto-dev-family-target-merge/v1" or merged.get("target_key") != key or merged.get("canonical_work_id") != context["task"]["canonical_work_id"] or merged.get("family_binding") != context["family_binding"] or merged.get("readiness_authority") != descriptor or merged.get("source_head_sha") != target["subject_revision"]:
                raise AutoDevStateError("merged sibling counterpart differs from its immutable selected authority")
            wrapper = _load_target(context, descriptor, fresh=False)
            source = wrapper["evidence_snapshot"]["evidence"]["source_scope"]
            github_repository = _source(context, target, source)
            _, readback = _provider(context["root"], merged.get("provider_readback"), target, github_repository=github_repository,
                       author_identity=descriptor["author_identity"], fresh=False, worktree=Path(source["worktree"]), merged=True)
            if merged.get("merge_sha") != readback["pr"]["mergeCommit"]["oid"]:
                raise AutoDevStateError("merged sibling counterpart SHA differs from the actual provider result")
        else:
            _load_target(context, descriptor, fresh=fresh)


def validate_family_target_readiness(state_file: str | Path, descriptor: Mapping[str, Any], *, expected_subject: str,
                                     expected_pull_request: Mapping[str, str], fresh: bool = True) -> dict[str, Any]:
    context = _context(state_file)
    wrapper = _load_target(context, descriptor, fresh=fresh)
    expected = {k: str(expected_subject if k == "subject_revision" else expected_pull_request.get(k) or "") for k in AUTHORITY_FIELDS}
    if any(wrapper["authority"][k] != expected[k] for k in AUTHORITY_FIELDS):
        raise AutoDevStateError("immutable sibling Finalize cannot authorize a different PR/base/head/author")
    require_family_readiness(state_file, fresh=fresh)
    return dict(descriptor)


def require_family_readiness_if_applicable(state_file: str | Path) -> None:
    """Extend the ordinary primary merge guard only for recorded PR families."""
    state = Path(state_file).expanduser().resolve()
    if state.is_dir():
        state /= "autodev.json"
    current = read_auto_dev_state(state)
    task_ref = current.get("delivery", {}).get("task_state_ref")
    if not task_ref:
        return
    task = _read_json(Path(task_ref))
    descriptor = task.get("stage_receipts", {}).get("release_propagation")
    if descriptor is None:
        return
    _, wrapper_path = _bound(state.parent, descriptor, "active release-propagation wrapper")
    wrapper = _read_json(wrapper_path)
    raw = Path(str(wrapper.get("receipt") or ""))
    path = raw if raw.is_absolute() else state.parent / raw
    evidence = _read_json(path)
    if wrapper.get("evidence_sha256") != _digest(_canonical(evidence)):
        raise AutoDevStateError("active typed family evidence changed before primary readiness validation")
    family = evidence.get("evidence", {}).get("family")
    if isinstance(family, list) and sum(isinstance(row, Mapping) and row.get("classification") == "pr_required" for row in family) > 1:
        require_family_readiness(state)


def record_family_target_merge(state_file: str | Path, *, evidence_file: str | Path, idempotency_key: str) -> dict[str, Any]:
    """Record a provider-confirmed sibling merge; leave the primary lifecycle intact."""
    state = Path(state_file).expanduser().resolve()
    if state.is_dir():
        state /= "autodev.json"
    with _family_lock(state):
        context = _context(state)
        payload = _read_json(Path(evidence_file).expanduser().resolve())
        if payload.get("schema") != "development-stage-evidence/v1" or payload.get("state") != "merged" or payload.get("status") != "completed" or not payload.get("summary") or not payload.get("verified_at"):
            raise AutoDevStateError("family merge requires a completed typed provider merge receipt")
        details = payload.get("evidence", {})
        if not isinstance(details, Mapping):
            raise AutoDevStateError("family merge requires structured provider evidence")
        key, target = _target(context, details)
        descriptor = details.get("readiness_authority")
        if not isinstance(descriptor, Mapping):
            raise AutoDevStateError("family merge requires its exact immutable target readiness authority")
        validate_family_target_readiness(state, descriptor, expected_subject=target["subject_revision"], expected_pull_request=details, fresh=False)
        wrapper = _load_target(context, descriptor, fresh=False)
        github_repository = _source(context, target, wrapper["evidence_snapshot"]["evidence"]["source_scope"])
        provider, readback = _provider(context["root"], details.get("provider_readback"), target,
                       github_repository=github_repository, author_identity=descriptor["author_identity"], fresh=True,
                       worktree=Path(wrapper["evidence_snapshot"]["evidence"]["source_scope"]["worktree"]), merged=True)
        merge_sha = readback["pr"]["mergeCommit"]["oid"]
        if details.get("source_head_sha") != target["subject_revision"] or details.get("merge_sha") != merge_sha or details.get("readback_verified") is not True or not idempotency_key.strip():
            raise AutoDevStateError("family merged evidence differs from the provider's actual source and merge SHA")
        record = {"schema": "auto-dev-family-target-merge/v1", "canonical_work_id": context["task"]["canonical_work_id"],
                  "target_key": key, "family_binding": context["family_binding"], "readiness_authority": descriptor,
                  "provider_readback": provider, "source_head_sha": target["subject_revision"], "merge_sha": merge_sha,
                  "evidence_snapshot": payload, "idempotency_key": idempotency_key}
        output = context["root"] / "artifacts/auto-dev-orchestration/family-targets" / key / "merge" / f"{_digest(_canonical(idempotency_key))[:24]}.json"
        task = _read_json(context["task_path"])
        existing = task.get("family_merges", {}).get(key)
        if existing:
            _, prior_path = _bound(context["root"], existing, "recorded sibling merge")
            if _read_json(prior_path) != record:
                raise AutoDevStateError("family target already has a different recorded provider merge")
            return dict(existing)
        if output.exists() and _read_json(output) != record:
            raise AutoDevStateError("family merge idempotency key already has different evidence")
        _atomic_json(output, record)
        result = {"ref": str(output), "sha256": _digest(output.read_bytes())}
        task = _read_json(context["task_path"])
        task.setdefault("family_merges", {})[key] = result
        _atomic_json(context["task_path"], task)
        return result
