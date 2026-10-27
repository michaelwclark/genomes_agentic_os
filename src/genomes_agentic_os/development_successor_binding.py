"""Native same-task successor admission; request files are assertions, never proof.

This owner never provisions, fetches, changes a branch, renews a lease or calls a
reviewer. All observations are read again under the task admission lock at CAS.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any, Iterator, Mapping

from jsonschema import Draft202012Validator

from .development_delivery import (
    DEVELOPMENT_POLICY_PLANES, DevelopmentDeliveryError, _configured_authorship,
    _file_lock, _resolve_development_context_selection, _runtime_registration, _validate_effective_policy_snapshot,
    load_development_profile, project_root, resolve_development_policies,
    select_development_repository, worktree_entries_for_project,
)
from .development_validation_refresh import _clean_worktree
from .review_coordination import ReviewSubject, review_family_key, shared_review_coordination_root
from .state import work_items
from .state.db import connect_readonly, default_db_path

SCHEMA = "development-successor-binding-request/v1"
EFFECTS = ("task-event", "rollup-event", "portfolio-active-binding",
           "autodev-projection", "same-canonical-work-row", "active-now-projection")


def digest(value: Any) -> str:
    """Return the stable semantic digest used by native observation contracts."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _reject(message: str) -> None:
    """Refuse without exposing raw subprocess output or credential-bearing data."""
    raise DevelopmentDeliveryError("successor binding: " + message)


def read_json(path: Path) -> tuple[dict[str, Any], str]:
    """Read duplicate-free ordinary JSON and retain its exact raw digest."""
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                _reject("duplicate JSON key")
            result[key] = value
        return result
    try:
        if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
            _reject("proof must be an ordinary regular file")
        raw = path.read_bytes()
        if len(raw) > 32 * 1024 * 1024:
            _reject("proof exceeds the bounded JSON size")
        value = json.loads(raw, object_pairs_hook=unique)
    except DevelopmentDeliveryError:
        raise
    except (OSError, ValueError) as exc:
        _reject("unreadable JSON proof: " + type(exc).__name__)
    if not isinstance(value, dict):
        _reject("proof must be a JSON object")
    return value, hashlib.sha256(raw).hexdigest()


def contained(packet: Path, relative: str) -> Path:
    """Reject traversal and every symlink component before proof access."""
    item = Path(relative)
    if item.is_absolute() or item.parts[:1] != ("artifacts",) or ".." in item.parts:
        _reject("proof must be packet-relative beneath artifacts")
    path = packet / item
    for parent in (path, *path.parents):
        if parent == packet:
            break
        if parent.is_symlink():
            _reject("proof cannot traverse symlinks")
    if not path.resolve().is_relative_to(packet.resolve()):
        _reject("proof escapes the original packet")
    return path


def proof(packet: Path, ref: Mapping[str, Any]) -> tuple[Path, dict[str, Any], str]:
    """Bind one strictly typed packet proof to its bytes and declared schema."""
    if not isinstance(ref, Mapping) or set(ref) != {"packet_ref", "sha256", "schema"}:
        _reject("proof reference must contain packet_ref, sha256 and schema only")
    path = contained(packet, str(ref["packet_ref"]))
    value, sha = read_json(path)
    if sha != ref["sha256"] or value.get("schema") != ref["schema"]:
        _reject("proof digest or schema changed")
    return path, value, sha


def validate_schema(value: Mapping[str, Any], name: str) -> None:
    """Validate the package-owned closed schema, never an installed override."""
    base = Path(__file__).resolve()
    candidates = (base.parent / "_resources/schemas" / name, base.parents[2] / "schemas" / name)
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        _reject("package schema is unavailable")
    schema, _ = read_json(path)
    errors = sorted(Draft202012Validator(schema).iter_errors(dict(value)),
                    key=lambda error: str(list(error.absolute_path)))
    if errors:
        _reject("closed schema rejected " + ".".join(map(str, errors[0].absolute_path)))


def native(command: list[str], *, cwd: Path | None = None) -> str:
    """Execute one bounded read-only native observation without leaking stderr."""
    environment = dict(os.environ)
    if command[0] == "git":
        environment = {key: value for key, value in environment.items() if not key.startswith("GIT_")}
        environment.update({"GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"})
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=30,
                                env=environment)
    except (OSError, subprocess.TimeoutExpired) as exc:
        _reject("native observation unavailable: " + type(exc).__name__)
    if result.returncode:
        _reject("native observation failed: " + command[0])
    if len(result.stdout) > 32 * 1024 * 1024:
        _reject("native observation exceeds its output bound")
    return result.stdout.strip()


def git(path: Path, *args: str) -> str:
    """Read real Git objects with replacement objects and lazy fetching disabled."""
    return native(["git", "--no-replace-objects", "-c", "core.fsmonitor=false",
                   "-c", "core.hooksPath=/dev/null", "-c", "diff.external=", "-C", str(path), *args])


def _repository_url(url: str) -> str:
    """Normalize only credential-free GitHub remotes to provider repository identity."""
    match = re.fullmatch(r"(?:git@github[.]com:|https://github[.]com/)([^/\s:]+/[^/\s]+?)(?:[.]git)?", url)
    if match is None:
        _reject("origin must be a credential-free GitHub remote")
    return match.group(1)


def _common(path: Path) -> Path:
    """Resolve the actual common Git directory for an exact worktree root."""
    if Path(git(path, "rev-parse", "--show-toplevel")).resolve() != path.resolve():
        _reject("selection is not the exact Git worktree root")
    value = Path(git(path, "rev-parse", "--git-common-dir"))
    return (value if value.is_absolute() else path / value).resolve()


def predecessor_boundary(current: Mapping[str, Any]) -> dict[str, Any]:
    """Capture protected source/index identity without reading secret env files."""
    record = current["worktree"]
    path = Path(record["path"]).resolve()
    branch = git(path, "branch", "--show-current")
    if branch != record["branch"]:
        _reject("protected predecessor local branch changed")
    head = git(path, "rev-parse", "HEAD")
    index = Path(git(path, "rev-parse", "--git-path", "index"))
    index = index if index.is_absolute() else path / index
    entries = git(path, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    files: dict[str, Any] = {}
    # Hash the changed ordinary files; credentials/env values are never read.
    for name in filter(None, git(path, "ls-files", "-m", "-o", "--exclude-standard", "-z").split("\0")):
        item = Path(name)
        if (item.name.startswith(".env") or any(part in {".venv", "node_modules"} for part in item.parts)):
            files[name] = {"excluded": "secret-or-dependency-boundary"}
            continue
        source = path / item
        if source.is_symlink():
            files[name] = {"symlink_sha256": hashlib.sha256(os.readlink(source).encode()).hexdigest()}
        elif source.is_file():
            files[name] = {"sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                           "mode": stat.S_IMODE(source.stat().st_mode)}
        else:
            files[name] = {"absent": True}
    return {"schema": "development-protected-worktree/v1", "path": str(path),
            "branch": branch, "head": head, "index_sha256": hashlib.sha256(index.read_bytes()).hexdigest(),
            "status_sha256": hashlib.sha256(entries.encode()).hexdigest(), "changed_files": files}


def historical_inventory(current: Mapping[str, Any]) -> dict[str, Any]:
    """Verify all existing file-backed receipts and preserve remote/string references."""
    values: list[dict[str, Any]] = []
    refs = [dict(row) for row in current.get("receipts", []) if isinstance(row, Mapping)]
    for row in refs:
        raw = str(row.get("ref") or "")
        path = Path(raw)
        if path.is_file():
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            if row.get("sha256") and row["sha256"] != sha:
                _reject("historical receipt bytes changed")
            values.append({"ref": raw, "sha256": sha})
        else:
            if row.get("sha256"):
                _reject("hash-bound historical receipt is missing")
            values.append({"ref": raw})
    for row in current.get("stage_receipts", {}).values():
        if not isinstance(row, Mapping) or not row.get("ref") or not row.get("sha256"):
            _reject("historical stage wrapper has no immutable hash")
        path = Path(row["ref"])
        _, sha = read_json(path)
        if sha != row["sha256"]:
            _reject("historical stage wrapper changed")
        values.append({"ref": str(path), "sha256": sha})
    return {"schema": "development-historical-receipt-inventory/v1", "receipts": refs,
            "files": values, "stage_receipts": deepcopy(current.get("stage_receipts", {}))}


def coordinator_inventory(root: Path, subject: ReviewSubject) -> dict[str, Any]:
    """Hash existing shared coordination bytes without repair, quarantine or review calls."""
    shared = shared_review_coordination_root(root)
    inventory: dict[str, str] = {}
    total = 0
    for folder in ("receipts", "index", "attempts", "quarantine"):
        for path in sorted((shared / folder).rglob("*")):
            if path.is_symlink():
                _reject("shared review inventory contains a symlink")
            if not path.is_file():
                continue
            total += path.stat().st_size
            if total > 256 * 1024 * 1024 or len(inventory) >= 20000:
                _reject("shared review inventory exceeds its bounded admission size")
            inventory[str(path.relative_to(shared))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"schema": "development-shared-review-inventory/v1", "root": str(shared),
            "family_key": review_family_key(subject), "files": inventory}


def _native_runtime(current: Mapping[str, Any], profile: Mapping[str, Any],
                    record: Mapping[str, Any]) -> dict[str, Any]:
    """Prove registration with a dedicated read-only provider observation.

    Cleanup readback commands intentionally are not executed here. They prove
    absence and cannot establish a live successor's registration.
    """
    runtime = _runtime_registration(profile, record, domain=current["domain"],
                                    project=current["project"], ticket=current["ticket"])
    original = _runtime_registration(profile, current["worktree"], domain=current["domain"],
                                     project=current["project"], ticket=current["ticket"])
    if original != current["runtime"]:
        _reject("runtime provider or command semantics changed from the original registration")
    if runtime["ownership"] == "not_managed":
        return {"schema": "development-successor-runtime/v1", **runtime, "namespace": "not-managed"}
    if (runtime["provider"] != "los_fast_worktree" or current["domain"] != "los"
            or current["project"] != "los_app_los_django"):
        _reject("runtime provider has no supported successor ownership observer")
    state = Path.home() / ".los-fast-worktree"
    registry = state / "registry.tsv"
    if registry.is_symlink() or not registry.is_file() or registry.stat().st_uid != os.getuid():
        _reject("native fast-worktree registry is unavailable")
    slug = re.sub(r"-+", "-", re.sub(r"[^a-z0-9-]", "-", record["name"].lower())).strip("-")[:40]
    rows = [line.split("\t") for line in registry.read_text().splitlines()
            if len(line.split("\t")) >= 3 and line.split("\t")[1] == slug]
    if len(rows) != 1 or Path(rows[0][2]).resolve() != Path(record["path"]).resolve():
        _reject("native runtime registration is missing, duplicated or foreign")
    namespace = rows[0][0]
    if not re.fullmatch(r"[0-9]+", namespace):
        _reject("native runtime namespace is malformed")
    # Inspect only configured ownership keys. Do not copy or emit any env value.
    path = Path(record["path"]) / ".env.worktree"
    if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid():
        _reject("native runtime worktree identity is missing")
    allowed = {"FWT_SLUG", "LOS_STACK_NAME", "FWT_INDEX", "FWT_ID", "FWT_NAMESPACE"}
    identity: dict[str, str] = {}
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        if key.strip() in allowed:
            if key.strip() in identity:
                _reject("duplicate runtime identity key")
            identity[key.strip()] = value.strip()
    if (identity.get("FWT_SLUG") != slug or identity.get("LOS_STACK_NAME") != "los-" + slug
            or identity.get("FWT_INDEX") != namespace):
        _reject("native runtime ownership identity disagrees with its registry")
    for key in ("FWT_ID", "FWT_NAMESPACE"):
        if key in identity and identity[key] != namespace:
            _reject("native runtime namespace disagrees with its registry")
    # Read only whitelisted Docker fields, never Config.Env, logs or exec.
    stack = "los-" + slug
    daemon = native(["docker", "info", "--format", "{{.ID}}"])
    ids = native(["docker", "ps", "--all", "--quiet", "--no-trunc", "--filter",
                  "label=com.docker.compose.project=" + stack]).splitlines()
    if not daemon or len(daemon) > 256 or not ids or len(ids) > 32 or len(ids) != len(set(ids)):
        _reject("native runtime has no bounded unique owned container inventory")
    template = ('{"id":{{json .Id}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},'
                '"mounts":{{json .Mounts}}}')
    containers: list[dict[str, str]] = []
    for container in sorted(ids):
        if not re.fullmatch(r"[0-9a-f]{64}", container):
            _reject("native runtime returned a malformed container identity")
        try:
            observed = json.loads(native(["docker", "inspect", "--format", template, container]))
            mounts = [mount for mount in observed["mounts"]
                      if mount.get("Destination") == "/app"]
            if (observed["id"] != container or observed["project"] != stack or len(mounts) != 1
                    or mounts[0].get("Type") != "bind"
                    or Path(mounts[0]["Source"]).resolve() != Path(record["path"]).resolve()):
                _reject("native runtime container source mount or compose ownership is foreign")
        except (ValueError, KeyError, TypeError):
            _reject("native runtime container identity is malformed")
        containers.append({"id": container, "compose_project": stack,
                           "source": str(Path(record["path"]).resolve()), "destination": "/app"})
    connection = connect_readonly(default_db_path(current["os_root"]))
    try:
        claims = connection.execute("SELECT id, worktree_path FROM work_items WHERE worktree_path IS NOT NULL").fetchall()
        if any(row["id"] != current["canonical_work_id"]
               and Path(row["worktree_path"]).resolve() == Path(record["path"]).resolve() for row in claims):
            _reject("successor runtime source is claimed by another canonical work item")
    finally:
        connection.close()
    return {"schema": "development-successor-runtime/v1", **runtime, "namespace": namespace,
            "worktree": str(Path(record["path"]).resolve()), "registry_row_sha256": digest(rows[0]),
            "daemon": daemon, "containers": containers,
            "work_item_claim": {"canonical_work_id": current["canonical_work_id"],
                                "packet": current["work_item"], "foreign_claims": []}}


def _provider(path: Path, repository: str, number: int) -> dict[str, Any]:
    """Read the exact GitHub PR through the authenticated native read-only adapter."""
    raw = native(["gh", "api", "repos/" + repository + "/pulls/" + str(number)], cwd=path)
    try:
        value = json.loads(raw)
        return {"schema": "development-successor-provider/v1", "number": value["number"],
                "url": value["html_url"], "state": value["state"], "merged": bool(value["merged"]),
                "repository": value["base"]["repo"]["full_name"],
                "source_repository": value["head"]["repo"]["full_name"],
                "source_branch": value["head"]["ref"], "head": value["head"]["sha"],
                "base_branch": value["base"]["ref"], "base_sha": value["base"]["sha"],
                "author_identity": "github:" + value["user"]["login"].lower()}
    except (ValueError, KeyError, TypeError):
        _reject("provider PR readback is malformed")


def source_rule_inventory(tree: Path, revision: str) -> dict[str, dict[str, str]]:
    """Bind every tracked source rule blob/mode to its actual commit, without executing it."""
    result: dict[str, dict[str, str]] = {}
    for item in filter(None, git(tree, "ls-tree", "-r", "-z", revision).split("\0")):
        metadata, name = item.split("\t", 1)
        if (Path(name).name not in {"AGENTS.md", "CLAUDE.md"}
                and not (name.startswith((".claude/rules/", ".codex/rules/")) and name.endswith(".md"))):
            continue
        mode, kind, oid = metadata.split()
        if kind != "blob" or mode not in {"100644", "100755"}:
            _reject("source rules must be ordinary tracked files")
        result[name] = {"mode": mode, "git_blob": oid}
    return result


def _profile(current: Mapping[str, Any]) -> tuple[dict[str, Any], Path]:
    """Resolve the actual selected profile, retaining this task's configured base family."""
    profile, source = load_development_profile(current["os_root"], current["domain"], current["project"])
    catalog = profile.get("repository", {}).get("catalog")
    profile = select_development_repository(profile, current["repository"]["id"] if catalog else None)
    if (profile["repository"].get("id") != current["repository"]["id"]
            or Path(profile["repository"]["root"]).resolve() != Path(current["repository"]["root"]).resolve()
            or _configured_authorship(profile) != current["authorship"]):
        _reject("selected repository or authorship changed")
    profile["repository"]["base_branch"] = current["repository"]["base_branch"]
    return profile, Path(source)


def policy_delta(old: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, Any]:
    """Compute exact source/profile changes; non-comparable prose needs real review."""
    _validate_effective_policy_snapshot(old, require_selected_profile=True)
    _validate_effective_policy_snapshot(new, require_selected_profile=True)
    sources: list[dict[str, Any]] = []
    for plane in DEVELOPMENT_POLICY_PLANES:
        left = old["planes"][plane]["sources"]
        right = new["planes"][plane]["sources"]
        if [(s["scope"], s["rank"], s["source_ref"]) for s in left] != [
                (s["scope"], s["rank"], s["source_ref"]) for s in right]:
            _reject("policy source selector, ordering or applicability changed")
        for previous, successor in zip(left, right):
            if previous != successor:
                sources.append({"plane": plane, "source_ref": previous["source_ref"],
                                "before": deepcopy(previous), "after": deepcopy(successor)})
    before = old["selected_profile"]["validation"]
    after = new["selected_profile"]["validation"]
    # Arbitrary command replacement is not a safe inequality exception.
    if before != after:
        _reject("validation semantics changed; a separately qualified equivalence contract is required")
    before_context = old.get("context_selection") or {}
    after_context = new.get("context_selection") or {}
    before_selection = before_context.get("selection", {})
    after_selection = after_context.get("selection", {})
    if (before_selection.get("subjects") != after_selection.get("subjects")
            or before_selection.get("rulebook_ids") != after_selection.get("rulebook_ids")
            or not set(before_selection.get("touched_paths", [])).issubset(after_selection.get("touched_paths", []))):
        _reject("policy context dropped original subjects, rulebooks or source paths")
    old_docs = {row["source_ref"]: row for row in before_selection.get("selected_documents", [])}
    new_docs = {row["source_ref"]: row for row in after_selection.get("selected_documents", [])}
    if not old_docs.keys() <= new_docs.keys():
        _reject("policy context dropped an inherited selected document")
    context_changed = before_context.get("context_documents") != after_context.get("context_documents") or old_docs != new_docs
    for change in sources:
        old_lines = change["before"].get("body_markdown", "").splitlines()
        new_lines = change["after"].get("body_markdown", "").splitlines()
        safety = re.compile(r"coverage|\b95\b|budget|quorum|identity|security|secret|readback|required|ownership|lease", re.I)
        controls = [line for line in old_lines if safety.search(line)]
        if any(line not in new_lines for line in controls):
            _reject("policy delta removes or changes inherited safety/coverage/review controls")
    return {"schema": "development-successor-policy-delta/v1",
            "old_fingerprint": old["fingerprint"], "new_fingerprint": new["fingerprint"],
            "source_changes": sources, "context_changed": context_changed,
            "selected_profile_unchanged": True,
            "context_before": old.get("context_selection"), "context_after": new.get("context_selection")}


def _review_policy_delta(packet: Path, review: Mapping[str, Any], delta: Mapping[str, Any],
                         shared: Path, subject: ReviewSubject) -> None:
    """Require canonical exact-subject review for changed prose; booleans are not evidence."""
    from .review_coordination import ReviewCoordinationError, load_review_receipt, stable_review_key
    expected = {"schema": "development-successor-policy-admission/v1", "delta_sha256": digest(delta)}
    if (not delta["source_changes"] and not delta.get("context_changed")
            and not delta.get("context_policy_changed") and not delta.get("source_rule_changes")):
        if review != expected:
            _reject("policy delta admission does not match the actual unchanged controls")
        return
    if set(review) != {*expected, "canonical_review_sha256"} or any(review.get(k) != v for k, v in expected.items()):
        _reject("changed policy prose lacks exact canonical review authority")
    canonical = shared / "receipts" / (stable_review_key(subject) + ".json")
    try:
        receipt = load_review_receipt(canonical)
    except ReviewCoordinationError:
        _reject("canonical policy review does not cover the actual delta or is unavailable")
    if (hashlib.sha256(canonical.read_bytes()).hexdigest() != review["canonical_review_sha256"]
            or receipt.get("subject") != asdict(subject) or receipt.get("outcome") != "clean"
            or receipt.get("review", {}).get("policy_delta_sha256") != digest(delta)
            or any(row.get("status") == "open" for row in receipt.get("finding_ledger", []))):
        _reject("canonical policy review does not cover the actual delta or has findings")


def _canonical(current: Mapping[str, Any]) -> dict[str, Any]:
    """Read the existing canonical row without creating or migrating its database."""
    root = Path(current["os_root"])
    connection = connect_readonly(default_db_path(root))
    try:
        row = work_items.get(connection, current["canonical_work_id"])
    finally:
        connection.close()
    if (not row or row["domain"] != current["domain"] or row["project"] != current["project"]
            or row["source_key"].lower() != current["ticket"].lower()
            or Path(row["packet_path"]).resolve() != Path(current["work_item"]).resolve()
            or row["state"] in work_items.TERMINAL_STATES or row["attention"] == "closed"):
        _reject("canonical work identity is missing, foreign or terminal")
    return row


def recheck_pending_sources(current: Mapping[str, Any], receipt: Mapping[str, Any]) -> None:
    """Repeat exact source/runtime/provider proofs before completing a crashed outbox."""
    packet = Path(current["work_item"])
    before = proof(packet, receipt["predecessor"]["full_state_snapshot"])[1]["task"]
    if predecessor_boundary(before) != proof(packet, receipt["predecessor"]["protected_boundary"])[1]:
        _reject("protected predecessor changed while projections were pending")
    record = current["worktree"]
    tree = Path(record["path"])
    project = project_root(current["os_root"], current["domain"], current["project"])
    if (git(tree, "branch", "--show-current") != record["branch"]
            or git(tree, "rev-parse", "HEAD") != receipt["successor"]["head_sha"]
            or not _clean_worktree(current, project, tree)):
        _reject("successor changed while projections were pending")
    registry = proof(packet, receipt["successor"]["worktree_record"])[1]["row"]
    rows = [{key: value for key, value in row.items() if key != "_source"}
            for row in worktree_entries_for_project(project)
            if (row.get("id") or row.get("name")) == record["name"]]
    if not rows or any(row != registry for row in rows):
        _reject("successor registration changed while projections were pending")
    profile, _ = _profile(current)
    if _native_runtime(current, profile, record) != proof(packet, receipt["successor"]["runtime_native_identity"])[1]:
        _reject("runtime registration changed while projections were pending")
    expected = proof(packet, receipt["proofs"]["provider_and_remote_equality"])[1]
    provider = expected["provider"]
    if _provider(tree, provider["repository"], provider["number"]) != provider:
        _reject("provider identity changed while projections were pending")
    for ref, sha in expected["remote"]["refs"].items():
        if git(tree, "ls-remote", "--exit-code", "origin", ref).split() != [sha, ref]:
            _reject("remote identity changed while projections were pending")


def observe_successor(state_file: str | Path, *, registry_id: str,
                      pull_request: int) -> dict[str, Any]:
    """Produce read-only native source/policy/runtime observations for a request capsule."""
    path = Path(state_file).resolve()
    current, state_sha = read_json(path)
    if (current.get("schema") != "development-task/v1" or current.get("state") != "local_validation"
            or not current.get("canonical_work_id") or current.get("auto_dev_start_stage") not in {"groom", "readiness"}
            or current.get("terminal_revision") or current.get("deployed_revision")
            or any(current.get(k) for k in ("historical_delivery_reconciliations",
                "active_pr_create_delivery_escalations", "worktree_ready_delivery_recoveries"))):
        _reject("requires a modern nonterminal early-window local_validation task")
    packet = Path(current["work_item"]).resolve()
    project = project_root(current["os_root"], current["domain"], current["project"])
    if (not packet.is_relative_to((project / "work-items").resolve())
            or packet.parent.name in {"03-complete", "99-archived"}):
        _reject("original live project packet is required")
    portfolio_path = path.parents[2] / "portfolio.json"
    portfolio, portfolio_sha = read_json(portfolio_path)
    manifest, manifest_sha = read_json(packet / "autodev.json")
    task_rows = [row for row in portfolio.get("tasks", []) if row.get("ticket") == current["ticket"]]
    if (not path.is_relative_to(project / "state/development-runs")
            or path.parents[2].name != current["run_id"] or len(task_rows) != 1
            or Path(task_rows[0].get("state_ref", "")).resolve() != path):
        _reject("task is not the original portfolio's exact registered state path")
    if (manifest.get("delivery", {}).get("task_state_ref") != str(path)
            or manifest.get("canonical_work_id") != current["canonical_work_id"]
            or manifest.get("delivery", {}).get("worktree") != current["worktree"]
            or manifest.get("delivery", {}).get("policy_fingerprint") != current["policy_fingerprint"]
            or portfolio.get("run_id") != current["run_id"]
            or portfolio.get("repository") != current["repository"]):
        _reject("linked portfolio or Auto-Dev identity does not match")
    rows = [dict(row) for row in worktree_entries_for_project(project)
            if (row.get("id") or row.get("name")) == registry_id]
    sources = [str(row.get("_source") or "") for row in rows]
    variants = {digest({key: value for key, value in row.items() if key != "_source"}) for row in rows}
    if (not rows or len(variants) != 1 or len(sources) != len(set(sources))
            or rows[0].get("status", "active") != "active"):
        _reject("successor must be one unique active registered worktree")
    row = {key: value for key, value in rows[0].items() if key != "_source"}
    tree = Path(row["path"])
    tree = (tree if tree.is_absolute() else project / tree).resolve()
    repository = Path(current["repository"]["root"]).resolve()
    if tree == repository or _common(tree) != _common(repository):
        _reject("successor is not an isolated worktree of the selected repository")
    branch = git(tree, "branch", "--show-current")
    if not branch or branch != row.get("branch") or not _clean_worktree(current, project, tree):
        _reject("successor must be clean on its actual registered local branch")
    for marker in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
        marker_path = Path(git(tree, "rev-parse", "--git-path", marker))
        if (marker_path if marker_path.is_absolute() else tree / marker_path).exists():
            _reject("successor has an in-progress Git operation")
    name = row.get("id") or row.get("name")
    record = {"name": name, "path": str(tree), "branch": branch,
              "repository_id": current["repository"]["id"], "base_branch": current["repository"]["base_branch"]}
    expected_repo = current["repository"]["id"].removeprefix("git:github.com/")
    if _repository_url(git(tree, "remote", "get-url", "origin")) != expected_repo:
        _reject("successor origin differs from the selected provider repository")
    provider = _provider(tree, expected_repo, pull_request)
    head = git(tree, "rev-parse", "HEAD")
    base = provider["base_sha"]
    expected_url = "https://github.com/" + expected_repo + "/pull/" + str(pull_request)
    if (provider["repository"] != expected_repo or provider["source_repository"] != expected_repo
            or provider["state"] != "open" or provider["merged"] or provider["url"] != expected_url
            or provider["number"] != pull_request or provider["head"] != head
            or provider["base_branch"] != current["repository"]["base_branch"]
            or provider["author_identity"] not in current["authorship"]["ours"]):
        _reject("fresh provider subject is foreign, stale, closed or not ours")
    refs: dict[str, str] = {}
    for ref, sha in (("refs/heads/" + provider["source_branch"], head),
                     ("refs/heads/" + provider["base_branch"], base)):
        actual = git(tree, "ls-remote", "--exit-code", "origin", ref).split()
        if actual != [sha, ref]:
            _reject("exact remote source/base ref differs from provider/local identity")
        refs[ref] = sha
    boundary = predecessor_boundary(current)
    for ancestor in (boundary["head"], base):
        if not re.fullmatch(r"[0-9a-f]{40}", ancestor) or git(tree, "cat-file", "-t", ancestor) != "commit":
            _reject("exact predecessor/base commit objects are unavailable")
        git(tree, "merge-base", "--is-ancestor", ancestor, head)
        if git(tree, "merge-base", "--all", ancestor, head).splitlines() != [ancestor]:
            _reject("source/base ancestry is ambiguous")
    changed = sorted(filter(None, git(tree, "diff", "--no-ext-diff", "--no-textconv", "--name-only", "--no-renames", base, head, "--").splitlines()))
    profile, source = _profile(current)
    old, old_sha = read_json(Path(current["policy_receipt"]))
    selection = current.get("context_selection", {}).get("selection", {})
    new = resolve_development_policies(current["os_root"], current["domain"], current["project"],
        selected_profile=profile, profile_source=source, include_body=True,
        touched_paths=sorted(set(changed) | set(selection.get("touched_paths", []))),
        subjects=selection.get("subjects", []),
        rulebook_ids=selection.get("rulebook_ids", []))
    delta = policy_delta(old, new)
    old_selection_current = _resolve_development_context_selection(
        current["os_root"], current["domain"], current["project"],
        touched_paths=selection.get("touched_paths", []), subjects=selection.get("subjects", []),
        rulebook_ids=selection.get("rulebook_ids", []))
    delta["context_policy_changed"] = old.get("context_selection") != old_selection_current
    old_rules = source_rule_inventory(tree, boundary["head"])
    new_rules = source_rule_inventory(tree, head)
    if not old_rules.keys() <= new_rules.keys():
        _reject("successor removed an inherited source rule file")
    delta["source_rule_changes"] = [{"path": name, "before": old_rules.get(name), "after": new_rules[name]}
        for name in sorted(new_rules) if old_rules.get(name) != new_rules[name]]
    subject = ReviewSubject(expected_repo, "github:" + expected_repo + "#" + str(pull_request),
                            provider["base_branch"], base, head, new["fingerprint"])
    coordinator = coordinator_inventory(Path(current["os_root"]), subject)
    canonical = _canonical(current)
    runtime = _native_runtime(current, profile, record)
    return {"schema": "development-successor-observation/v1", "task": current,
            "expected": {"task_sha256": state_sha, "portfolio_sha256": portfolio_sha,
                "autodev_sha256": manifest_sha, "canonical_work_row_revision": digest(canonical)},
            "protected_boundary": boundary, "historical_receipts": historical_inventory(current),
            "original_runtime": {"schema": "development-original-runtime/v1", "runtime": current["runtime"]},
            "registry": {"schema": "development-successor-registry/v1", "row": row, "worktree": record},
            "runtime": runtime, "provider": provider,
            "remote": {"schema": "development-successor-remote/v1", "refs": refs},
            "ancestry": {"schema": "development-successor-ancestry/v1", "predecessor": boundary["head"],
                "base": base, "head": head, "changed_paths": changed,
                "diff_sha256": hashlib.sha256(git(tree, "diff", "--no-ext-diff", "--no-textconv", "--binary", base, head, "--").encode()).hexdigest()},
            "policy": new, "old_policy_sha256": old_sha, "policy_delta": delta,
            "coordinator": coordinator, "canonical_row": canonical}


@contextmanager
def family_admission_lock(root: Path, family_key: str) -> Iterator[None]:
    """Refuse an in-flight review instead of waiting behind a paid model call."""
    path = shared_review_coordination_root(root) / ".locks" / (family_key + ".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _reject("a shared family review is active; retry after its terminal receipt")
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
