"""Deterministic late-CI qualification; historical model authority stays immutable."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping

from .review_coordination import (
    ReviewCoordinationError,
    assert_exact_head_review_receipt,
    load_review_receipt,
    shared_review_coordination_root,
)


def _error(message: str) -> None:
    from .development_delivery import DevelopmentDeliveryError

    raise DevelopmentDeliveryError("unavailable review eligibility: " + message)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_descriptor(value: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    if not isinstance(value, Mapping):
        _error("hash-bound descriptor is missing")
    path = Path(str(value.get("ref") or "")).expanduser()
    if not (
        path.is_absolute()
        and path.is_file()
        and not path.is_symlink()
        and value.get("sha256") == _sha(path)
    ):
        _error("descriptor is missing, changed, or indirect")
    try:
        payload = json.loads(path.read_text())
    except (ValueError, OSError):
        _error("descriptor is unreadable")
    if not isinstance(payload, dict):
        _error("descriptor is not an object")
    return path.resolve(), payload


def _binding(task: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        name: task.get(name)
        for name in (
            "run_id",
            "ticket",
            "canonical_work_id",
            "work_item",
            "policy_fingerprint",
            "repository",
            "profile_source",
            "policy_receipt",
            "autodev_path",
        )
    }
    result["worktree"] = {
        key: (task.get("worktree") or {}).get(key)
        for key in ("path", "branch", "repository_id")
    }
    if not all(
        result.get(key)
        for key in (
            "run_id",
            "ticket",
            "canonical_work_id",
            "work_item",
            "policy_fingerprint",
            "profile_source",
            "policy_receipt",
            "autodev_path",
        )
    ):
        _error("canonical task identity is incomplete")
    return result


def _original(path: Path, task: Mapping[str, Any]) -> dict[str, Any]:
    root = shared_review_coordination_root(task["os_root"]).resolve()
    if not (
        path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root)
    ):
        _error("original is outside the shared review coordinator")
    try:
        receipt = load_review_receipt(path)
    except ReviewCoordinationError:
        _error("original coordinator receipt is invalid")
    review = receipt.get("review") or {}
    repository = str(task["repository"]["id"]).removeprefix("git:github.com/")
    number = review.get("pr_number")
    if not (
        receipt.get("mode") == "full"
        and receipt.get("parent_key") is None
        and (receipt.get("subject") or {}).get("purpose") == "review_self"
        and receipt.get("findings_ledger") == []
        and review.get("outcome") == "unavailable"
        and type(number) is int
        and number > 0
    ):
        _error("original is not the canonical unavailable full review")
    try:
        assert_exact_head_review_receipt(
            path,
            head_sha=receipt["subject"]["head_sha"],
            repository=task["repository"]["id"],
            pull_request=f"github:{repository}#{number}",
            policy_fingerprint=task["policy_fingerprint"],
            require_clean=False,
        )
    except ReviewCoordinationError:
        _error("original coordinator subject differs")
    return receipt


def _git(worktree: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        _error("native source read failed")
    if result.returncode:
        _error("native source read failed")
    return result.stdout


def _source(authority: Mapping[str, Any], task: Mapping[str, Any]) -> dict[str, Any]:
    request, subject = authority["request"], authority["subject"]
    worktree = Path(str(task["worktree"]["path"])).resolve()
    if not (
        worktree == Path(str(request.get("repo_path") or "")).resolve()
        and _git(worktree, "rev-parse", "HEAD").strip() == subject["head_sha"]
        and _git(worktree, "branch", "--show-current").strip()
        == request["source_worktree_branch"]
        and not _git(worktree, "status", "--porcelain")
    ):
        _error("current native source head, branch, or cleanliness differs")
    ancestor = _git(
        worktree, "merge-base", subject["base_sha"], subject["head_sha"]
    ).strip()
    diff = _git(worktree, "diff", "--binary", f"{ancestor}..{subject['head_sha']}")
    digest = hashlib.sha256(diff.encode()).hexdigest()
    if not (
        ancestor == request.get("diff_base_sha") and digest == request.get("diff_hash")
    ):
        _error("complete native source diff changed")
    files = {}
    for name in _git(
        worktree, "diff", "--name-only", "-z", f"{ancestor}..{subject['head_sha']}"
    ).split("\0"):
        if name:
            exists = _git(worktree, "ls-tree", subject["head_sha"], "--", name).strip()
            files[name] = (
                hashlib.sha256(
                    _git(worktree, "show", f"{subject['head_sha']}:{name}").encode()
                ).hexdigest()
                if exists
                else None
            )
    return {
        "head_sha": subject["head_sha"],
        "diff_base_sha": ancestor,
        "diff_sha256": digest,
        "tree_sha": _git(
            worktree, "rev-parse", subject["head_sha"] + "^{tree}"
        ).strip(),
        "changed_file_sha256": files,
    }


def _runner_artifacts(review: Mapping[str, Any]) -> dict[str, str]:
    run = Path(review["review"]["review_run_dir"])
    result = {}
    for path in sorted(run.iterdir()):
        if path.is_symlink() or not path.is_file():
            _error("runner artifacts contain an indirect or unexpected member")
        result[path.name] = _sha(path)
    if not set(review["review"]["unavailable_review_artifacts"]) <= set(result):
        _error("runner artifacts are incomplete")
    return result


def _required_checks(review: Mapping[str, Any]) -> list[str]:
    run = Path(review["review"]["review_run_dir"])
    sets = []
    for name in ("provider-readback-before.json", "provider-readback-after.json"):
        rows = json.loads((run / name).read_text()).get("statusCheckRollup")
        if not isinstance(rows, list) or not rows:
            _error("original native check inventory is missing")
        names = [
            row.get("name", row.get("context"))
            for row in rows
            if isinstance(row, Mapping)
        ]
        if (
            len(names) != len(rows)
            or any(not isinstance(n, str) or not n.strip() for n in names)
            or len(set(names)) != len(names)
        ):
            _error("original native check inventory is ambiguous")
        sets.append(set(names))
    if sets[0] != sets[1]:
        _error("original native check inventory drifted")
    return sorted(sets[0])


_QUERY = """
query($owner:String!,$name:String!,$number:Int!,$cursor:String){
 repository(owner:$owner,name:$name){id nameWithOwner url
  pullRequest(number:$number){number url state author{login} headRefOid headRefName
   baseRefName baseRef{name target{oid}} mergeable reviewDecision
   reviewThreads(first:100,after:$cursor){pageInfo{hasNextPage endCursor} nodes{id isResolved}}
   commits(last:1){nodes{commit{oid statusCheckRollup{contexts(first:100){
    pageInfo{hasNextPage endCursor} nodes{__typename
     ... on CheckRun{name status conclusion detailsUrl}
     ... on StatusContext{context state targetUrl}
   }}}}}}
  }
 }
}
"""


def _validate_capture(
    capture: Mapping[str, Any],
    authority: Mapping[str, Any],
    task: Mapping[str, Any],
    required: list[str],
) -> None:
    subject, request = authority["subject"], authority["request"]
    repository = str(task["repository"]["id"]).removeprefix("git:github.com/")
    pages = capture.get("pages")
    if not isinstance(pages, list) or not pages or len(pages) > 10:
        _error("native provider pages are missing")
    previous_cursor = None
    native_repository_id = None
    thread_ids: set[str] = set()
    for index, raw in enumerate(pages):
        try:
            repo = raw["data"]["repository"]
            pr = repo["pullRequest"]
            base = pr["baseRef"]
            contexts = pr["commits"]["nodes"][0]["commit"]
            connection = contexts["statusCheckRollup"]["contexts"]
            threads = pr["reviewThreads"]
            page = threads["pageInfo"]
        except (KeyError, TypeError, IndexError):
            _error("native provider pages are incomplete")
        if not (
            not raw.get("errors")
            and repo.get("id")
            and repo.get("nameWithOwner") == repository
            and repo.get("url") == "https://github.com/" + repository
            and pr.get("state") == "OPEN"
            and type(pr.get("number")) is int
            and pr["number"] == request["pr_number"]
            and pr.get("url")
            == f"https://github.com/{repository}/pull/{request['pr_number']}"
            and pr.get("headRefOid") == contexts.get("oid") == subject["head_sha"]
            and pr.get("headRefName") == request["source_worktree_branch"]
            and pr.get("baseRefName") == base.get("name") == subject["base_branch"]
            and (base.get("target") or {}).get("oid") == subject["base_sha"]
            and "github:" + str((pr.get("author") or {}).get("login") or "").lower()
            in [str(v).lower() for v in (task.get("authorship") or {}).get("ours", [])]
            and pr.get("mergeable") == "MERGEABLE"
            and pr.get("reviewDecision") in {"APPROVED", "REVIEW_REQUIRED", None}
            and connection["pageInfo"].get("hasNextPage") is False
        ):
            _error("native provider identity, author, or mergeability differs")
        if native_repository_id is not None and repo["id"] != native_repository_id:
            _error("native repository identity changed between pages")
        native_repository_id = repo["id"]
        checks = connection.get("nodes")
        if not isinstance(checks, list) or not checks:
            _error("current native checks are missing")
        names = []
        for check in checks:
            name = check.get("name", check.get("context"))
            if not isinstance(name, str) or not name.strip() or name in names:
                _error("current native checks are ambiguous")
            names.append(name)
            if not (
                (
                    check.get("__typename") == "CheckRun"
                    and check.get("status") == "COMPLETED"
                    and check.get("conclusion") == "SUCCESS"
                )
                or (
                    check.get("__typename") == "StatusContext"
                    and check.get("state") == "SUCCESS"
                )
            ):
                _error("current native checks are not all successful")
        if not set(required) <= set(names):
            _error("an original required native check is missing")
        if not isinstance(threads.get("nodes"), list):
            _error("native review threads are missing")
        for thread in threads["nodes"]:
            if (
                not thread.get("id")
                or thread["id"] in thread_ids
                or thread.get("isResolved") is not True
            ):
                _error("native review threads are unresolved or ambiguous")
            thread_ids.add(thread["id"])
        more = index < len(pages) - 1
        if page.get("hasNextPage") is not more:
            _error("native thread pagination is incomplete")
        if more and (not page.get("endCursor") or page["endCursor"] == previous_cursor):
            _error("native thread pagination is invalid")
        previous_cursor = page.get("endCursor")


def read_current_review_gates(
    authority: Mapping[str, Any], task: Mapping[str, Any], required: list[str]
) -> dict[str, Any]:
    """Read exact native GitHub identity, all observed checks, and every thread."""
    repository = str(task["repository"]["id"]).removeprefix("git:github.com/")
    owner, name = repository.split("/", 1)
    pages = []
    cursor = None
    for _ in range(10):
        argv = [
            "gh",
            "api",
            "graphql",
            "-f",
            "query=" + _QUERY,
            "-f",
            "owner=" + owner,
            "-f",
            "name=" + name,
            "-F",
            "number=" + str(authority["request"]["pr_number"]),
        ]
        if cursor:
            argv += ["-f", "cursor=" + cursor]
        try:
            result = subprocess.run(
                argv, capture_output=True, text=True, timeout=30, check=False
            )
            if result.returncode:
                _error("native provider read failed")
            raw = json.loads(result.stdout)
            page = raw["data"]["repository"]["pullRequest"]["reviewThreads"]["pageInfo"]
        except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
            _error("native provider read is unavailable")
        pages.append(raw)
        if page.get("hasNextPage") is False:
            break
        next_cursor = page.get("endCursor")
        if not next_cursor or next_cursor == cursor:
            _error("native thread pagination is invalid")
        cursor = next_cursor
    capture = {"read_at": datetime.now(timezone.utc).isoformat(), "pages": pages}
    _validate_capture(capture, authority, task, required)
    return capture


def produce_unavailable_review_eligibility(
    state_file: str | Path, coordination_receipt: str | Path, output_dir: str | Path
) -> dict[str, str]:
    """Create a separate immutable decision; never edit task, model, ledger or budget."""
    from .development_delivery import _validate_unavailable_review_authority

    state = Path(state_file).expanduser().resolve()
    task = json.loads(state.read_text())
    if (
        task.get("state") not in {"local_validation", "ready_for_merge"}
        or task.get("failure") is not None
    ):
        _error("canonical task is not eligible for review continuation")
    destination = Path(output_dir).expanduser().resolve()
    packet = Path(task["work_item"]).resolve()
    if not destination.is_relative_to(packet / "artifacts" / "review-eligibility"):
        _error(
            "output must belong to this task's separate review-eligibility artifacts"
        )
    binding = _binding(task)
    projection = json.loads(Path(task["autodev_path"]).read_text())
    if (
        Path(
            str((projection.get("delivery") or {}).get("task_state_ref") or "")
        ).resolve()
        != state
    ):
        _error("task is not the canonical packet delivery")
    original = Path(coordination_receipt).expanduser().absolute()
    review = _original(original, task)
    original_hash = _sha(original)
    authority = _validate_unavailable_review_authority(
        review, task, pending_checks=True, authority_only=True
    )
    source = _source(authority, task)
    runner_artifacts = _runner_artifacts(review)
    required = _required_checks(review)
    current = read_current_review_gates(authority, task, required)
    if (
        _sha(original) != original_hash
        or _binding(json.loads(state.read_text())) != binding
        or _runner_artifacts(review) != runner_artifacts
        or _source(authority, task) != source
    ):
        _error("original or canonical task changed during qualification")
    proof = {
        "schema": "unavailable-review-current-eligibility/v1",
        "decision": "eligible_with_unavailable_receipt",
        "qualified_at": current["read_at"],
        "original_review": {"ref": str(original), "sha256": original_hash},
        "task_binding": binding,
        "subject": review["subject"],
        "budget": review["budget"],
        "source": source,
        "runner_artifacts": runner_artifacts,
        "required_checks": required,
        "native_current_gates": current,
        "model_outcome": "unavailable",
        "original_decision": "pending_checks",
        "model_retry": False,
        "budget_reset": False,
        "lifecycle_write": False,
        "provider_write": False,
    }
    data = (json.dumps(proof, indent=2, sort_keys=True) + "\n").encode()
    digest = hashlib.sha256(data).hexdigest()
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f"eligibility-{digest}.json"
    try:
        with path.open("xb") as handle:
            handle.write(data)
    except FileExistsError:
        if path.read_bytes() != data:
            _error("immutable output collision")
    return {"ref": str(path), "sha256": digest}


def validate_unavailable_review_eligibility(
    descriptor: Mapping[str, Any],
    review: Mapping[str, Any],
    task: Mapping[str, Any],
    *,
    post_provider_merge: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Revalidate every authority and current gate before consuming late CI."""
    from .development_delivery import (
        _validate_unavailable_review_authority,
        read_completed_github_review_transition,
    )

    path, proof = _read_descriptor(descriptor)
    if not path.is_relative_to(
        Path(task["work_item"]).resolve() / "artifacts" / "review-eligibility"
    ):
        _error("eligibility belongs to another packet")
    original, _ = _read_descriptor(proof.get("original_review"))
    if _original(original, task) != dict(review):
        _error("original coordination authority differs")
    authority = _validate_unavailable_review_authority(
        review, task, pending_checks=True, authority_only=True
    )
    required = _required_checks(review)
    if not (
        proof.get("schema") == "unavailable-review-current-eligibility/v1"
        and proof.get("decision") == "eligible_with_unavailable_receipt"
        and proof.get("task_binding") == _binding(task)
        and proof.get("subject") == review["subject"]
        and proof.get("budget") == review["budget"]
        and proof.get("source") == _source(authority, task)
        and proof.get("runner_artifacts") == _runner_artifacts(review)
        and proof.get("required_checks") == required
        and proof.get("model_outcome") == "unavailable"
        and proof.get("original_decision") == "pending_checks"
        and all(
            proof.get(key) is False
            for key in (
                "model_retry",
                "budget_reset",
                "lifecycle_write",
                "provider_write",
            )
        )
    ):
        _error("eligibility authority or scope differs")
    current = proof.get("native_current_gates")
    if not isinstance(current, Mapping) or current.get("read_at") != proof.get(
        "qualified_at"
    ):
        _error("eligibility native timestamp is missing")
    _validate_capture(current, authority, task, required)
    try:
        timestamp = datetime.fromisoformat(
            str(proof["qualified_at"]).replace("Z", "+00:00")
        )
        age = (datetime.now(timezone.utc) - timestamp).total_seconds()
    except (ValueError, TypeError):
        _error("eligibility timestamp is invalid")
    if age < -5:
        _error("eligibility is from the future")
    if post_provider_merge is not None:
        completed = read_completed_github_review_transition(
            task,
            review["subject"],
            authority["request"]["pr_number"],
            authority["request"]["source_worktree_branch"],
            post_provider_merge,
            expected_repository_id=current["pages"][0]["data"]["repository"]["id"],
        )
        try:
            merged_at = datetime.fromisoformat(
                completed["native"]["pullRequest"]["mergedAt"].replace("Z", "+00:00")
            )
            if timestamp > merged_at:
                _error("eligibility was qualified after the completed merge")
        except (ValueError, TypeError, KeyError):
            _error("completed merge timestamp is invalid")
        return completed
    if age > 900:
        _error("eligibility is stale")
    fresh = read_current_review_gates(authority, task, required)
    if (
        fresh["pages"][0]["data"]["repository"]["id"]
        != current["pages"][0]["data"]["repository"]["id"]
        or _source(authority, task) != proof["source"]
        or _sha(original) != proof["original_review"]["sha256"]
        or _runner_artifacts(review) != proof["runner_artifacts"]
    ):
        _error("native repository, source, or original changed during consumption")
    return {
        "schema": "unavailable-review-current-eligibility-readback/v1",
        "eligibility_receipt": dict(descriptor),
        "native_current_gates": fresh,
        "original_outcome": "unavailable",
        "original_decision": "pending_checks",
    }
