"""Version-aware, evidence-first contracts and receipts for Auto-Dev Detective."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence
import uuid

import yaml

from .artifact_contracts import render_artifact, resolve_artifact_contract
from .policy_plane import MarkdownPolicyDocument, PolicyLayer, PolicyPlaneError, parse_markdown_policy, resolve_markdown_plane
from .scaffold import domain_path, expand_path, normalize_domain, validate_name


INVESTIGATION_SCHEMA_VERSION = 1
INVESTIGATION_KINDS = frozenset({"standard", "safety", "phase", "trigger", "source", "environment", "output"})
KNOWN_TRIGGER_TYPES = frozenset({"bug", "qa-failure", "ticket-comment", "log-entry", "alert", "incident", "question"})
KNOWN_OUTPUT_TYPES = frozenset({"investigation-report", "root-cause-analysis", "ticket-comment", "planning-evidence"})
ALLOWED_FRONTMATTER = frozenset(
    {
        "schema_version",
        "id",
        "kind",
        "title",
        "enabled",
        "priority",
        "applies_to",
        "authority",
        "freshness",
        "prerequisites",
        "tools",
        "queries",
        "evidence",
        "failure",
        "safety",
        "requirements",
        "outputs",
        "tags",
    }
)
TERMINAL_STATES = frozenset({"complete", "blocked", "cancelled"})
ACTIVE_STATES = frozenset(
    {
        "version_pending",
        "evidence_planned",
        "gathering",
        "analyzing",
        "conclusion_ready",
        "complete",
        "paused",
        "blocked",
        "cancelled",
    }
)
RESUMABLE_PAUSE_REASONS = frozenset(
    {
        "vpn-unavailable",
        "environment-unavailable",
        "provider-unavailable",
        "authentication-unavailable",
        "rate-limited",
        "decision-required",
    }
)


class InvestigationContractError(ValueError):
    """Raised when an investigation cannot proceed without compromising evidence."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slug(value: str, label: str) -> str:
    normalized = value.strip().lower().replace("_", "-").replace(" ", "-")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", normalized):
        raise InvestigationContractError(f"{label} must use lowercase letters, numbers, and hyphens")
    return normalized


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise InvestigationContractError(f"path is outside the Agentic OS root: {path}") from exc


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    _atomic_text(path, json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")


@contextmanager
def _run_lock(run_dir: Path):
    """Serialize mutation of one investigation packet across harnesses."""

    path = run_dir / ".run.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise InvestigationContractError(f"receipt not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InvestigationContractError(f"invalid JSON receipt: {path}") from exc
    if not isinstance(value, dict):
        raise InvestigationContractError(f"receipt must be a mapping: {path}")
    return value


def _read_receipt(root: Path, raw: str | Path, *, schema: str, label: str) -> tuple[Path, dict[str, Any]]:
    path = Path(raw).expanduser().resolve()
    _relative(root, path)
    value = _read_json(path)
    if value.get("schema") != schema:
        raise InvestigationContractError(f"{label} receipt must use {schema}")
    return path, value


def _parse_timestamp(value: str, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvestigationContractError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise InvestigationContractError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _load_mapping(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise InvestigationContractError(f"input not found: {source}")
    text = source.read_text(encoding="utf-8")
    if source.suffix.casefold() == ".json":
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise InvestigationContractError(f"invalid JSON input: {source}") from exc
    elif source.suffix.casefold() in {".yml", ".yaml"}:
        try:
            value = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            raise InvestigationContractError(f"invalid YAML input: {source}") from exc
    else:
        value = {"summary": text.strip(), "title": source.stem.replace("-", " ").title()}
    if not isinstance(value, dict):
        raise InvestigationContractError("input must contain a mapping or Markdown text")
    return dict(value)


def investigation_policy_roots(
    os_root: str | Path,
    *,
    domain: str | None = None,
    project: str | None = None,
) -> list[PolicyLayer]:
    """Return the conventional root -> domain -> project investigation layers."""

    root = expand_path(os_root)
    layers = [PolicyLayer("root", root / "harness" / "investigation-config", 0)]
    if project and not domain:
        raise InvestigationContractError("--project requires --domain")
    if domain:
        domain_name = normalize_domain(domain)
        local_domain = domain_path(root, domain_name)
        if not local_domain.is_dir():
            raise InvestigationContractError(f"domain not found: {domain_name}")
        layers.append(PolicyLayer("domain", local_domain / "investigation-config", 1))
        if project:
            project_name = validate_name(project, "project")
            project_root = local_domain / "02-projects" / project_name
            if not project_root.is_dir():
                raise InvestigationContractError(f"project not found: {domain_name}/{project_name}")
            layers.append(PolicyLayer("project", project_root / "investigation-config", 2))
    return layers


def _as_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [str(item) for item in value]
    return [str(value)]


def _matches(values: Any, actual: str | None) -> bool:
    expected = {_slug(item, "applies_to value") for item in _as_values(values)}
    if not expected or "any" in expected:
        return True
    return actual is not None and _slug(actual, "scope value") in expected


def _document_applies(
    document: MarkdownPolicyDocument,
    *,
    trigger: str,
    environment: str | None,
    output_type: str,
    domain: str | None,
    project: str | None,
) -> bool:
    metadata = document.frontmatter
    applies = metadata.get("applies_to")
    if applies is None:
        applies = {}
    if not isinstance(applies, Mapping):
        return False
    return all(
        (
            _matches(applies.get("triggers"), trigger),
            _matches(applies.get("environments"), environment),
            _matches(applies.get("outputs"), output_type),
            _matches(applies.get("domains"), domain),
            _matches(applies.get("projects"), project),
        )
    )


def _validate_document(document: MarkdownPolicyDocument) -> list[dict[str, Any]]:
    metadata = document.frontmatter
    findings: list[dict[str, Any]] = []

    def add(code: str, message: str, *, field: str | None = None, severity: str = "error") -> None:
        row: dict[str, Any] = {
            "severity": severity,
            "code": code,
            "message": message,
            "source_ref": document.source_ref,
        }
        if field:
            row["field"] = field
        findings.append(row)

    if metadata.get("schema_version") != INVESTIGATION_SCHEMA_VERSION:
        add("invalid_schema_version", f"schema_version must be {INVESTIGATION_SCHEMA_VERSION}", field="schema_version")
    kind = metadata.get("kind")
    if kind not in INVESTIGATION_KINDS:
        add("invalid_kind", f"kind must be one of {', '.join(sorted(INVESTIGATION_KINDS))}", field="kind")
    identity = metadata.get("id")
    if not isinstance(identity, str) or not identity.strip():
        add("missing_identity", "id is required", field="id")
    else:
        try:
            _slug(identity, "id")
        except InvestigationContractError as exc:
            add("invalid_identity", str(exc), field="id")
    for field in ("prerequisites", "tools", "queries", "evidence", "outputs", "tags"):
        if field in metadata and not isinstance(metadata[field], list):
            add("invalid_field_type", f"{field} must be a list", field=field)
    for field in ("applies_to", "authority", "freshness", "failure", "safety", "requirements"):
        if field in metadata and not isinstance(metadata[field], dict):
            add("invalid_field_type", f"{field} must be a mapping", field=field)
    if "priority" in metadata and not isinstance(metadata["priority"], int):
        add("invalid_field_type", "priority must be an integer", field="priority")
    for field in sorted(set(metadata) - ALLOWED_FRONTMATTER):
        add(
            "unregistered_field",
            f"unknown field is preserved for forward compatibility: {field}",
            field=field,
            severity="warning",
        )
    return findings


def _list_union(left: Sequence[Any], right: Sequence[Any]) -> list[Any]:
    result = deepcopy(list(left))
    signatures = {json.dumps(item, sort_keys=True, default=str) for item in result}
    for item in right:
        signature = json.dumps(item, sort_keys=True, default=str)
        if signature not in signatures:
            signatures.add(signature)
            result.append(deepcopy(item))
    return result


def _merge(current: Any, incoming: Any, *, path: tuple[str, ...], diagnostics: list[dict[str, Any]], source_ref: str) -> Any:
    dotted = ".".join(path)
    if isinstance(current, dict) and isinstance(incoming, Mapping):
        result = deepcopy(current)
        for key, value in incoming.items():
            if key in result:
                result[key] = _merge(
                    result[key], value, path=(*path, str(key)), diagnostics=diagnostics, source_ref=source_ref
                )
            else:
                result[key] = deepcopy(value)
        return result
    if isinstance(current, list) and isinstance(incoming, list):
        return _list_union(current, incoming)
    if dotted.startswith("safety.") and current is True and incoming is False:
        diagnostics.append(
            {
                "severity": "warning",
                "code": "blocked_safety_override",
                "field": dotted,
                "source_ref": source_ref,
                "message": "ignored false because inherited investigation safety is monotonic",
            }
        )
        return True
    if current != incoming and path and path[-1] not in {"schema_version", "id", "kind"}:
        diagnostics.append(
            {
                "severity": "observation",
                "code": "field_overridden",
                "field": dotted,
                "source_ref": source_ref,
                "message": "narrower investigation value selected",
            }
        )
    return deepcopy(incoming)


def resolve_investigation_contract(
    os_root: str | Path,
    *,
    trigger: str,
    environment: str | None = None,
    output_type: str = "investigation-report",
    domain: str | None = None,
    project: str | None = None,
    overlays: Iterable[str | Path] = (),
) -> dict[str, Any]:
    """Compose the exact evidence plan for one investigation request."""

    root = expand_path(os_root)
    trigger_name = _slug(trigger, "trigger")
    output_name = _slug(output_type, "output type")
    environment_name = _slug(environment, "environment") if environment else None
    domain_name = normalize_domain(domain) if domain else None
    project_name = validate_name(project, "project") if project else None
    layers = investigation_policy_roots(root, domain=domain_name, project=project_name)
    try:
        plane = resolve_markdown_plane(root, layers, explicit_files=overlays)
    except PolicyPlaneError as exc:
        raise InvestigationContractError(str(exc)) from exc
    diagnostics: list[dict[str, Any]] = []
    documents: list[MarkdownPolicyDocument] = []
    for document in plane["documents"]:
        diagnostics.extend(_validate_document(document))
        if _document_applies(
            document,
            trigger=trigger_name,
            environment=environment_name,
            output_type=output_name,
            domain=domain_name,
            project=project_name,
        ):
            documents.append(document)
    if any(item["severity"] == "error" for item in diagnostics):
        raise InvestigationContractError("investigation policy contains validation errors; run detective doctor")

    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for document in documents:
        kind = str(document.frontmatter.get("kind") or "standard")
        identity = _slug(str(document.frontmatter.get("id") or document.path.stem), "id")
        key = (kind, identity)
        if key not in groups:
            groups[key] = {
                "schema_version": INVESTIGATION_SCHEMA_VERSION,
                "kind": kind,
                "id": identity,
                "source_refs": [],
                "instructions_markdown": [],
            }
        current = groups[key]
        merged = _merge(current, document.frontmatter, path=(), diagnostics=diagnostics, source_ref=document.source_ref)
        merged["source_refs"] = _list_union(current.get("source_refs") or [], [document.source_ref])
        if document.body.strip():
            merged["instructions_markdown"] = _list_union(
                current.get("instructions_markdown") or [], [document.body.strip()]
            )
        groups[key] = merged

    selected = sorted(
        groups.values(),
        key=lambda item: (int(item.get("priority") or 100), str(item.get("kind")), str(item.get("id"))),
    )
    selected_sources = [item for item in selected if item.get("kind") == "source" and item.get("enabled", True)]
    digest = [
        {"source_ref": document.source_ref, "sha256": document.sha256, "scope": document.scope}
        for document in documents
    ]
    fingerprint = hashlib.sha256(
        json.dumps(digest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema": "investigation-policy-resolution/v1",
        "trigger": trigger_name,
        "environment": environment_name,
        "output_type": output_name,
        "domain": domain_name,
        "project": project_name,
        "version_gate": "required_before_evidence" if environment_name else "environment_not_specified",
        "fingerprint": fingerprint,
        "layers": plane["layers"],
        "sources": [document.as_dict() for document in documents],
        "effective": {
            "documents": selected,
            "source_catalog": selected_sources,
            "source_ids": [str(item["id"]) for item in selected_sources],
        },
        "diagnostics": diagnostics,
        "counts": {
            "available_documents": len(plane["documents"]),
            "selected_documents": len(documents),
            "effective_groups": len(selected),
            "sources": len(selected_sources),
        },
    }


def _default_run_dir(root: Path, run_id: str, *, domain: str | None, project: str | None) -> Path:
    if domain and project:
        return root / "domains" / domain / "02-projects" / project / "state" / "investigation-runs" / run_id
    if domain:
        return root / "domains" / domain / "06-runs-and-logs" / "investigations" / run_id
    return root / "harness" / "shared_factory" / "06-runs-and-logs" / "investigations" / run_id


def _run_directory(root: Path, raw: str | Path) -> Path:
    path = Path(raw).expanduser().resolve()
    _relative(root, path)
    return path


def _append_event(run_dir: Path, event_type: str, payload: Mapping[str, Any]) -> None:
    event = {
        "schema": "investigation-event/v1",
        "event_id": uuid.uuid4().hex,
        "type": event_type,
        "occurred_at": utc_now(),
        "payload": dict(payload),
    }
    path = run_dir / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True, default=str) + "\n")


def _run_state(root: Path, run_dir_raw: str | Path) -> tuple[Path, dict[str, Any]]:
    run_dir = _run_directory(root, run_dir_raw)
    state = _read_json(run_dir / "run.json")
    if state.get("schema") != "investigation-run/v1" or state.get("state") not in ACTIVE_STATES:
        raise InvestigationContractError(f"invalid investigation run: {run_dir}")
    return run_dir, state


def _save_state(run_dir: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = utc_now()
    _atomic_json(run_dir / "run.json", state)


def start_investigation(
    os_root: str | Path,
    request_path: str | Path,
    *,
    trigger: str,
    environment: str | None = None,
    tenant: str | None = None,
    output_type: str = "investigation-report",
    domain: str | None = None,
    project: str | None = None,
    overlays: Iterable[str | Path] = (),
    run_id: str | None = None,
    run_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Create an idempotent investigation packet without contacting providers."""

    root = expand_path(os_root)
    request = _load_mapping(request_path)
    resolution = resolve_investigation_contract(
        root,
        trigger=trigger,
        environment=environment,
        output_type=output_type,
        domain=domain,
        project=project,
        overlays=overlays,
    )
    now = datetime.now(timezone.utc).replace(microsecond=0)
    run_name = run_id or f"{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    run_name = _slug(run_name, "run id")
    destination = _run_directory(root, run_dir) if run_dir else _default_run_dir(
        root, run_name, domain=resolution["domain"], project=resolution["project"]
    )
    stable_request = {
        "schema": "investigation-request/v1",
        "run_id": run_name,
        "trigger": resolution["trigger"],
        "environment": resolution["environment"],
        "tenant": tenant,
        "output_type": resolution["output_type"],
        "domain": resolution["domain"],
        "project": resolution["project"],
        "title": request.get("title") or request.get("summary") or "Investigation",
        "question": request.get("question") or request.get("summary"),
        "signal": request,
    }
    request_hash = hashlib.sha256(
        json.dumps(stable_request, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    request_payload = {**stable_request, "captured_at": utc_now()}
    request_payload["sha256"] = request_hash
    if destination.exists():
        existing = _read_json(destination / "request.json")
        if existing.get("sha256") != request_hash:
            raise InvestigationContractError(f"run id already belongs to a different request: {run_name}")
        return investigation_status(root, destination)
    destination.mkdir(parents=True)
    _atomic_json(destination / "request.json", request_payload)
    _atomic_json(destination / "policy-resolution.json", resolution)
    source_manifest = {
        "schema": "investigation-source-manifest/v1",
        "policy_fingerprint": resolution["fingerprint"],
        "sources": [
            {
                "id": source["id"],
                "status": "pending",
                "priority": source.get("priority", 100),
                "authority": source.get("authority") or {},
                "freshness": source.get("freshness") or {},
                "prerequisites": source.get("prerequisites") or [],
                "tools": source.get("tools") or [],
                "queries": source.get("queries") or [],
                "evidence_requirements": source.get("evidence") or [],
                "requirements": source.get("requirements") or {},
                "failure": source.get("failure") or {},
                "source_refs": source.get("source_refs") or [],
            }
            for source in resolution["effective"]["source_catalog"]
        ],
        "updated_at": utc_now(),
    }
    _atomic_json(destination / "source-manifest.json", source_manifest)
    version = {
        "schema": "investigation-deployed-version/v1",
        "status": "pending" if environment else "environment_not_specified",
        "environment": resolution["environment"],
        "tenant": tenant,
        "requirement": resolution["version_gate"],
        "updated_at": utc_now(),
    }
    _atomic_json(destination / "deployed-version.json", version)
    _atomic_json(destination / "hypotheses.json", {"schema": "investigation-analysis/v1", "status": "not_started"})
    state = {
        "schema": "investigation-run/v1",
        "run_id": run_name,
        "state": "version_pending" if environment else "evidence_planned",
        "domain": resolution["domain"],
        "project": resolution["project"],
        "environment": resolution["environment"],
        "tenant": tenant,
        "trigger": resolution["trigger"],
        "output_type": resolution["output_type"],
        "request_sha256": request_hash,
        "policy_fingerprint": resolution["fingerprint"],
        "pause": None,
        "outputs": [],
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    _atomic_json(destination / "run.json", state)
    _append_event(destination, "investigation.started", {"state": state["state"], "request_sha256": request_hash})
    return investigation_status(root, destination)


def investigation_status(os_root: str | Path, run_dir_raw: str | Path) -> dict[str, Any]:
    root = expand_path(os_root)
    run_dir, state = _run_state(root, run_dir_raw)
    manifest = _read_json(run_dir / "source-manifest.json")
    version = _read_json(run_dir / "deployed-version.json")
    counts: dict[str, int] = {}
    for source in manifest.get("sources") or []:
        status = str(source.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    evidence_path = run_dir / "evidence.jsonl"
    evidence_count = sum(1 for line in evidence_path.read_text(encoding="utf-8").splitlines() if line.strip()) if evidence_path.is_file() else 0
    return {
        **state,
        "run_ref": _relative(root, run_dir),
        "version": version,
        "source_status_counts": counts,
        "evidence_count": evidence_count,
        "receipts": sorted(path.name for path in run_dir.iterdir() if path.is_file()),
    }


def record_deployed_version(
    os_root: str | Path,
    run_dir_raw: str | Path,
    *,
    authority_receipt: str | Path,
) -> dict[str, Any]:
    """Satisfy the version gate from a typed domain-authority readback."""

    root = expand_path(os_root)
    run_dir, state = _run_state(root, run_dir_raw)
    authority_path, authority = _read_receipt(
        root,
        authority_receipt,
        schema="investigation-version-authority/v1",
        label="deployed-version authority",
    )
    if authority.get("status") != "verified" or authority.get("source_id") != "deployed-version":
        raise InvestigationContractError("version authority receipt must be verified for source_id deployed-version")
    if authority.get("environment") != state.get("environment") or authority.get("tenant") not in {None, state.get("tenant")}:
        raise InvestigationContractError("version authority receipt does not match the run environment/tenant")
    manifest = _read_json(run_dir / "source-manifest.json")
    version_source = next((item for item in manifest.get("sources") or [] if item.get("id") == "deployed-version"), None)
    expected_authority = (
        str((version_source.get("authority") or {}).get("class") or "").strip()
        if isinstance(version_source, Mapping)
        else ""
    )
    if expected_authority and authority.get("authority_class") != expected_authority:
        raise InvestigationContractError(
            f"version authority receipt requires policy authority_class {expected_authority!r}"
        )
    version = str(authority.get("version") or "").strip()
    source = str(authority.get("source") or "").strip()
    git_ref = str(authority.get("git_ref") or "").strip() or None
    commit_sha = str(authority.get("commit_sha") or "").strip() or None
    evidence_ref = str(authority.get("evidence_ref") or "").strip()
    captured_at = str(authority.get("captured_at") or "").strip()
    if not version or not source or not evidence_ref or not captured_at:
        raise InvestigationContractError(
            "version authority receipt requires version, source, evidence_ref, and captured_at"
        )
    _parse_timestamp(captured_at, label="captured_at")
    if commit_sha and not re.fullmatch(r"[a-fA-F0-9]{7,64}", commit_sha):
        raise InvestigationContractError("commit SHA must be 7-64 hexadecimal characters")
    with _run_lock(run_dir):
        state = _read_json(run_dir / "run.json")
        if state["state"] == "paused":
            raise InvestigationContractError("run is paused; resume it before recording version evidence")
        if state["state"] in TERMINAL_STATES:
            raise InvestigationContractError(f"cannot change deployed version in terminal state {state['state']}")
        receipt = {
            "schema": "investigation-deployed-version/v1",
            "status": "resolved",
            "environment": state.get("environment"),
            "tenant": state.get("tenant"),
            "version": version,
            "git_ref": git_ref,
            "commit_sha": commit_sha.lower() if commit_sha else None,
            "source": source,
            "evidence_ref": evidence_ref,
            "captured_at": captured_at,
            "authority_receipt_ref": _relative(root, authority_path),
            "authority_receipt_sha256": hashlib.sha256(authority_path.read_bytes()).hexdigest(),
            "resolved_at": utc_now(),
            "updated_at": utc_now(),
        }
        _atomic_json(run_dir / "deployed-version.json", receipt)
        manifest = _read_json(run_dir / "source-manifest.json")
        for item in manifest.get("sources") or []:
            if item.get("id") == "deployed-version":
                item.update({"status": "completed", "last_evidence_at": utc_now(), "receipt_ref": _relative(root, authority_path)})
        manifest["updated_at"] = utc_now()
        _atomic_json(run_dir / "source-manifest.json", manifest)
        if state["state"] == "version_pending":
            state["state"] = "evidence_planned"
        _save_state(run_dir, state)
        _append_event(run_dir, "investigation.version_resolved", {"version": version, "source": source})
    return investigation_status(root, run_dir)


def record_investigation_evidence(
    os_root: str | Path,
    run_dir_raw: str | Path,
    *,
    source_id: str,
    summary: str,
    facts: Sequence[str] = (),
    limitations: Sequence[str] = (),
    authority: str | None = None,
    evidence_ref: str | None = None,
    evidence_file: str | Path | None = None,
    captured_at: str | None = None,
    fresh_until: str | None = None,
    prerequisites_satisfied: Sequence[str] = (),
) -> dict[str, Any]:
    """Append one bounded evidence receipt and update source coverage."""

    root = expand_path(os_root)
    run_dir, initial_state = _run_state(root, run_dir_raw)
    if initial_state["state"] == "version_pending":
        raise InvestigationContractError("resolve the deployed environment version before gathering other evidence")
    if initial_state["state"] == "paused":
        raise InvestigationContractError("run is paused; resume it before recording evidence")
    if initial_state["state"] in TERMINAL_STATES:
        raise InvestigationContractError(f"cannot record evidence in terminal state {initial_state['state']}")
    source_name = _slug(source_id, "source id")
    if not summary.strip():
        raise InvestigationContractError("evidence summary is required")
    manifest = _read_json(run_dir / "source-manifest.json")
    match = next((item for item in manifest.get("sources") or [] if item.get("id") == source_name), None)
    if match is None:
        raise InvestigationContractError(
            f"source {source_name!r} is not declared by the resolved policy; use an invocation overlay before starting the run"
        )
    expected_authority = match.get("authority") if isinstance(match.get("authority"), Mapping) else {}
    authority_class = str(expected_authority.get("class") or "").strip()
    if authority_class and str(authority or "").strip() != authority_class:
        raise InvestigationContractError(
            f"source {source_name} requires authority {authority_class!r}"
        )
    if not evidence_ref and not evidence_file:
        raise InvestigationContractError("evidence requires evidence_ref or an evidence file receipt")
    captured = captured_at or utc_now()
    captured_time = _parse_timestamp(captured, label="captured_at")
    if captured_time > datetime.now(timezone.utc).replace(microsecond=0):
        raise InvestigationContractError("captured_at cannot be in the future")
    if fresh_until and _parse_timestamp(fresh_until, label="fresh_until") < captured_time:
        raise InvestigationContractError("fresh_until cannot precede captured_at")
    file_receipt: dict[str, Any] | None = None
    if evidence_file:
        path = Path(evidence_file).expanduser().resolve()
        if not path.is_file():
            raise InvestigationContractError(f"evidence file not found: {path}")
        file_receipt = {
            "name": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size_bytes": path.stat().st_size,
        }
    with _run_lock(run_dir):
        state = _read_json(run_dir / "run.json")
        if state["state"] == "version_pending":
            raise InvestigationContractError("resolve the deployed environment version before gathering other evidence")
        if state["state"] == "paused":
            raise InvestigationContractError("run is paused; resume it before recording evidence")
        if state["state"] in TERMINAL_STATES:
            raise InvestigationContractError(f"cannot record evidence in terminal state {state['state']}")
        manifest = _read_json(run_dir / "source-manifest.json")
        match = next((item for item in manifest.get("sources") or [] if item.get("id") == source_name), None)
        if match is None:
            raise InvestigationContractError(f"declared source disappeared from the run manifest: {source_name}")
        asserted = {str(item).strip().casefold() for item in prerequisites_satisfied if str(item).strip()}
        missing_prerequisites: list[str] = []
        version = _read_json(run_dir / "deployed-version.json")
        version_source = next(
            (item for item in manifest.get("sources") or [] if item.get("id") == "deployed-version"),
            {},
        )
        for prerequisite in match.get("prerequisites") or []:
            text = str(prerequisite).strip()
            normalized = text.casefold()
            automatic = False
            if "deployed" in normalized and "version" in normalized:
                # The source policy is conditional: environment-scoped runs
                # require the exact resolved deployed-version receipt, while
                # non-environment runs must explicitly disposition that
                # conditional source as not applicable before source-code can
                # be recorded.
                automatic = version.get("status") == "resolved" or (
                    not state.get("environment") and version_source.get("status") == "not_applicable"
                )
            elif normalized in {"environment identity", "environment"}:
                automatic = bool(state.get("environment"))
            elif normalized in {"tenant identity", "tenant/schema resolution"}:
                automatic = bool(state.get("tenant"))
            if not automatic and normalized not in asserted:
                missing_prerequisites.append(text)
        if missing_prerequisites:
            raise InvestigationContractError(
                f"source {source_name} has unsatisfied prerequisites: " + ", ".join(missing_prerequisites)
            )
        evidence = {
            "schema": "investigation-evidence/v1",
            "evidence_id": uuid.uuid4().hex,
            "source_id": source_name,
            "summary": summary.strip(),
            "facts": [str(item).strip() for item in facts if str(item).strip()],
            "limitations": [str(item).strip() for item in limitations if str(item).strip()],
            "authority": authority_class or authority,
            "policy_authority": dict(expected_authority),
            "policy_freshness": dict(match.get("freshness") or {}),
            "evidence_ref": evidence_ref,
            "file": file_receipt,
            "prerequisites_satisfied": sorted(asserted),
            "captured_at": captured,
            "fresh_until": fresh_until,
            "recorded_at": utc_now(),
        }
        evidence_path = run_dir / "evidence.jsonl"
        with evidence_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(evidence, sort_keys=True, default=str) + "\n")
        match.update({"status": "completed", "last_evidence_at": evidence["recorded_at"], "evidence_id": evidence["evidence_id"]})
        manifest["updated_at"] = utc_now()
        _atomic_json(run_dir / "source-manifest.json", manifest)
        state["state"] = "gathering"
        _save_state(run_dir, state)
        _append_event(run_dir, "investigation.evidence_recorded", {"source_id": source_name, "evidence_id": evidence["evidence_id"]})
    return investigation_status(root, run_dir)


def record_source_disposition(
    os_root: str | Path,
    run_dir_raw: str | Path,
    *,
    source_id: str,
    status: str,
    reason: str,
    evidence_ref: str,
) -> dict[str, Any]:
    """Resolve a planned source that is unavailable or not applicable."""

    root = expand_path(os_root)
    run_dir, _ = _run_state(root, run_dir_raw)
    source_name = _slug(source_id, "source id")
    status_name = _slug(status, "source status")
    if status_name not in {"not-applicable", "unavailable", "deferred"}:
        raise InvestigationContractError("source status must be not-applicable, unavailable, or deferred")
    if not reason.strip() or not evidence_ref.strip():
        raise InvestigationContractError("source disposition requires reason and evidence_ref")
    with _run_lock(run_dir):
        state = _read_json(run_dir / "run.json")
        if state["state"] in TERMINAL_STATES:
            raise InvestigationContractError(f"cannot change source coverage in terminal state {state['state']}")
        manifest = _read_json(run_dir / "source-manifest.json")
        match = next((item for item in manifest.get("sources") or [] if item.get("id") == source_name), None)
        if match is None:
            raise InvestigationContractError(f"source is not declared by the resolved policy: {source_name}")
        if source_name == "deployed-version" and state.get("environment"):
            raise InvestigationContractError("environment-scoped deployed-version cannot be skipped or unavailable")
        manifest_status = status_name.replace("-", "_")
        match.update(
            {
                "status": manifest_status,
                "disposition": {
                    "reason": reason.strip(),
                    "evidence_ref": evidence_ref.strip(),
                    "recorded_at": utc_now(),
                },
            }
        )
        manifest["updated_at"] = utc_now()
        _atomic_json(run_dir / "source-manifest.json", manifest)
        _append_event(
            run_dir,
            "investigation.source_dispositioned",
            {"source_id": source_name, "status": manifest_status, "evidence_ref": evidence_ref.strip()},
        )
    return investigation_status(root, run_dir)


def pause_investigation(
    os_root: str | Path,
    run_dir_raw: str | Path,
    *,
    reason: str,
    resume_when: str,
    detail: str | None = None,
) -> dict[str, Any]:
    """Pause once on an unavailable dependency instead of failure-loop retrying."""

    root = expand_path(os_root)
    run_dir, state = _run_state(root, run_dir_raw)
    reason_name = _slug(reason, "pause reason")
    if reason_name not in RESUMABLE_PAUSE_REASONS:
        raise InvestigationContractError(f"pause reason must be one of {', '.join(sorted(RESUMABLE_PAUSE_REASONS))}")
    if not resume_when.strip():
        raise InvestigationContractError("resume condition is required")
    with _run_lock(run_dir):
        state = _read_json(run_dir / "run.json")
        if state["state"] in TERMINAL_STATES:
            raise InvestigationContractError(f"cannot pause terminal state {state['state']}")
        if state["state"] == "paused":
            return investigation_status(root, run_dir)
        state["pause"] = {
            "reason": reason_name,
            "detail": detail,
            "resume_when": resume_when.strip(),
            "previous_state": state["state"],
            "paused_at": utc_now(),
            "attempts_while_paused": 0,
        }
        state["state"] = "paused"
        _save_state(run_dir, state)
        _append_event(run_dir, "investigation.paused", state["pause"])
    return investigation_status(root, run_dir)


def resume_investigation(
    os_root: str | Path,
    run_dir_raw: str | Path,
    *,
    availability_receipt: str | Path,
) -> dict[str, Any]:
    root = expand_path(os_root)
    run_dir, _ = _run_state(root, run_dir_raw)
    receipt_path, availability = _read_receipt(
        root,
        availability_receipt,
        schema="investigation-availability/v1",
        label="availability",
    )
    if availability.get("status") not in {"available", "resolved"}:
        raise InvestigationContractError("availability receipt must have status available or resolved")
    if not availability.get("checked_at") or not availability.get("evidence_ref"):
        raise InvestigationContractError("availability receipt requires checked_at and evidence_ref")
    _parse_timestamp(str(availability["checked_at"]), label="checked_at")
    with _run_lock(run_dir):
        state = _read_json(run_dir / "run.json")
        if state["state"] != "paused" or not isinstance(state.get("pause"), Mapping):
            raise InvestigationContractError("run is not paused")
        pause = dict(state["pause"])
        if availability.get("reason") != pause.get("reason"):
            raise InvestigationContractError("availability receipt reason does not match the paused dependency")
        previous = str(pause.get("previous_state") or "evidence_planned")
        if previous not in ACTIVE_STATES or previous in TERMINAL_STATES or previous == "paused":
            previous = "evidence_planned"
        state["state"] = previous
        state["pause"] = None
        state["last_resume"] = {
            "availability_receipt_ref": _relative(root, receipt_path),
            "availability_receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            "resumed_at": utc_now(),
            "prior_pause": pause,
        }
        _save_state(run_dir, state)
        _append_event(
            run_dir,
            "investigation.resumed",
            {"availability_receipt_ref": _relative(root, receipt_path), "restored_state": previous},
        )
    return investigation_status(root, run_dir)


def _evidence_count(run_dir: Path) -> int:
    path = run_dir / "evidence.jsonl"
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip()) if path.is_file() else 0


def _evidence_records(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "evidence.jsonl"
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict) and value.get("schema") == "investigation-evidence/v1":
            records.append(value)
    return records


def _evidence_backed_claims(
    raw: Any,
    *,
    label: str,
    valid_ids: set[str],
    required: bool,
) -> list[dict[str, Any]]:
    if raw is None:
        values: list[Any] = []
    elif isinstance(raw, list):
        values = raw
    else:
        raise InvestigationContractError(f"{label} must be a list of evidence-backed mappings")
    result: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        if not isinstance(value, Mapping):
            raise InvestigationContractError(f"{label}[{index}] must be a mapping with claim and evidence_ids")
        claim = str(value.get("claim") or "").strip()
        evidence_ids = [str(item).strip() for item in value.get("evidence_ids") or [] if str(item).strip()]
        if not claim or not evidence_ids:
            raise InvestigationContractError(f"{label}[{index}] requires claim and evidence_ids")
        unknown = sorted(set(evidence_ids) - valid_ids)
        if unknown:
            raise InvestigationContractError(f"{label}[{index}] cites unknown evidence ids: {', '.join(unknown)}")
        result.append({**dict(value), "claim": claim, "evidence_ids": evidence_ids})
    if required and not result:
        raise InvestigationContractError(f"at least one evidence-backed {label} entry is required")
    return result


def analyze_investigation(
    os_root: str | Path,
    run_dir_raw: str | Path,
    analysis_path: str | Path,
    *,
    conclude: bool = False,
) -> dict[str, Any]:
    """Record analysis under the same per-run mutation lock as evidence."""

    root = expand_path(os_root)
    run_dir, _ = _run_state(root, run_dir_raw)
    with _run_lock(run_dir):
        return _analyze_investigation_unlocked(
            root,
            run_dir,
            analysis_path,
            conclude=conclude,
        )


def _analyze_investigation_unlocked(
    os_root: str | Path,
    run_dir_raw: str | Path,
    analysis_path: str | Path,
    *,
    conclude: bool = False,
) -> dict[str, Any]:
    """Record facts, hypotheses, contradictions, and an optional conclusion."""

    root = expand_path(os_root)
    run_dir, state = _run_state(root, run_dir_raw)
    if state["state"] == "paused":
        raise InvestigationContractError("run is paused")
    if state["state"] == "version_pending":
        raise InvestigationContractError("resolve the deployed version before analysis")
    if state["state"] in TERMINAL_STATES and state["state"] != "complete":
        raise InvestigationContractError(f"cannot analyze terminal state {state['state']}")
    analysis = _load_mapping(analysis_path)
    facts = analysis.get("facts") or []
    hypotheses = analysis.get("hypotheses") or []
    if not isinstance(hypotheses, list):
        raise InvestigationContractError("hypotheses must be a list")
    normalized = {
        "schema": "investigation-analysis/v1",
        "status": "concluded" if conclude else "in_progress",
        "facts": facts,
        "hypotheses": hypotheses,
        "contradictions": _as_values(analysis.get("contradictions")),
        "disconfirming_evidence": _as_values(analysis.get("disconfirming_evidence")),
        "unknowns": _as_values(analysis.get("unknowns") or analysis.get("gaps")),
        "causes": _as_values(analysis.get("causes")),
        "conclusion": str(analysis.get("conclusion") or "").strip() or None,
        "confidence": str(analysis.get("confidence") or "unknown").strip().lower(),
        "scope": analysis.get("scope"),
        "recommendations": _as_values(analysis.get("recommendations")),
        "next_owner": str(analysis.get("next_owner") or "").strip() or None,
        "conclusion_evidence_ids": _as_values(analysis.get("conclusion_evidence_ids")),
        "impact": analysis.get("impact"),
        "timeline": analysis.get("timeline"),
        "contributing_factors": _as_values(analysis.get("contributing_factors")),
        "prevention": _as_values(analysis.get("prevention")),
        "detection": _as_values(analysis.get("detection")),
        "updated_at": utc_now(),
    }
    if normalized["confidence"] not in {"unknown", "low", "medium", "high"}:
        raise InvestigationContractError("confidence must be unknown, low, medium, or high")
    if conclude:
        records = _evidence_records(run_dir)
        valid_ids = {str(item["evidence_id"]) for item in records}
        if not valid_ids:
            raise InvestigationContractError("at least one evidence receipt is required before conclusion")
        normalized["facts"] = _evidence_backed_claims(
            facts,
            label="facts",
            valid_ids=valid_ids,
            required=True,
        )
        normalized["contradictions"] = _evidence_backed_claims(
            analysis.get("contradictions"),
            label="contradictions",
            valid_ids=valid_ids,
            required=False,
        )
        normalized["disconfirming_evidence"] = _evidence_backed_claims(
            analysis.get("disconfirming_evidence"),
            label="disconfirming_evidence",
            valid_ids=valid_ids,
            required=True,
        )
        normalized_hypotheses: list[dict[str, Any]] = []
        for index, hypothesis in enumerate(hypotheses):
            if not isinstance(hypothesis, Mapping):
                raise InvestigationContractError(f"hypotheses[{index}] must be a mapping")
            claim = str(hypothesis.get("claim") or "").strip()
            support_ids = [str(item).strip() for item in hypothesis.get("support_evidence_ids") or [] if str(item).strip()]
            falsifier = str(hypothesis.get("falsifier") or "").strip()
            if not claim or not support_ids or not falsifier:
                raise InvestigationContractError(
                    f"hypotheses[{index}] requires claim, support_evidence_ids, and falsifier"
                )
            unknown = sorted(set(support_ids) - valid_ids)
            if unknown:
                raise InvestigationContractError(
                    f"hypotheses[{index}] cites unknown evidence ids: {', '.join(unknown)}"
                )
            normalized_hypotheses.append(
                {**dict(hypothesis), "claim": claim, "support_evidence_ids": support_ids, "falsifier": falsifier}
            )
        if not normalized_hypotheses:
            raise InvestigationContractError("at least one falsifiable hypothesis is required")
        normalized["hypotheses"] = normalized_hypotheses
        if not normalized["conclusion"]:
            raise InvestigationContractError("conclusion is required")
        conclusion_ids = normalized["conclusion_evidence_ids"]
        if not conclusion_ids or set(conclusion_ids) - valid_ids:
            raise InvestigationContractError("conclusion_evidence_ids must cite valid investigation evidence")
        if normalized["confidence"] == "unknown":
            raise InvestigationContractError("conclusion confidence cannot be unknown")
        if not normalized.get("scope") or not normalized.get("next_owner"):
            raise InvestigationContractError("conclusion requires bounded scope and next_owner")
        if "unknowns" not in analysis and "gaps" not in analysis:
            raise InvestigationContractError("conclusion must explicitly record unknowns, even when empty")
        manifest = _read_json(run_dir / "source-manifest.json")
        unresolved = [
            str(item.get("id"))
            for item in manifest.get("sources") or []
            if item.get("status") in {"pending", "deferred", None}
        ]
        if unresolved:
            raise InvestigationContractError(
                "all planned sources need evidence or an explicit disposition before conclusion: "
                + ", ".join(unresolved)
            )
        unavailable = [
            str(item.get("id")) for item in manifest.get("sources") or [] if item.get("status") == "unavailable"
        ]
        if unavailable and normalized["confidence"] == "high":
            raise InvestigationContractError("high confidence is not allowed while planned sources are unavailable")
        normalized["source_coverage"] = {
            "completed": [str(item.get("id")) for item in manifest.get("sources") or [] if item.get("status") == "completed"],
            "not_applicable": [str(item.get("id")) for item in manifest.get("sources") or [] if item.get("status") == "not_applicable"],
            "unavailable": unavailable,
        }
        normalized["status"] = "concluded"
    _atomic_json(run_dir / "hypotheses.json", normalized)
    state["state"] = "complete" if conclude else ("conclusion_ready" if normalized["conclusion"] else "analyzing")
    if conclude:
        result = {
            "schema": "investigation-result/v1",
            "run_id": state["run_id"],
            "title": _read_json(run_dir / "request.json").get("title"),
            "environment": state.get("environment"),
            "tenant": state.get("tenant"),
            "deployed_version": _read_json(run_dir / "deployed-version.json"),
            **normalized,
            "policy_fingerprint": state["policy_fingerprint"],
            "evidence_count": _evidence_count(run_dir),
            "completed_at": utc_now(),
        }
        _atomic_json(run_dir / "result.json", result)
        _atomic_text(run_dir / "result.md", _render_result_markdown(result))
        state["result_ref"] = _relative(root, run_dir / "result.json")
    _save_state(run_dir, state)
    _append_event(run_dir, "investigation.concluded" if conclude else "investigation.analysis_updated", {"state": state["state"]})
    return investigation_status(root, run_dir)


def _markdown_items(values: Any) -> str:
    raw_items = values if isinstance(values, list) else ([] if values is None else [values])
    items: list[str] = []
    for item in raw_items:
        if isinstance(item, Mapping):
            claim = str(item.get("claim") or item.get("reason") or json.dumps(item, sort_keys=True))
            evidence_ids = item.get("evidence_ids") or item.get("support_evidence_ids") or []
            suffix = f" (evidence: {', '.join(str(value) for value in evidence_ids)})" if evidence_ids else ""
            items.append(claim + suffix)
        else:
            items.append(str(item))
    return "\n".join(f"- {item}" for item in items) if items else "- None recorded"


def _render_result_markdown(result: Mapping[str, Any]) -> str:
    version = result.get("deployed_version") if isinstance(result.get("deployed_version"), Mapping) else {}
    scope = result.get("scope")
    scope_text = json.dumps(scope, sort_keys=True) if isinstance(scope, (dict, list)) else str(scope or "Not bounded")
    return f"""# {result.get('title') or 'Investigation Result'}

## Conclusion

{result.get('conclusion')}

## Confidence

{result.get('confidence')}

## Environment and deployed version

- Environment: {result.get('environment') or 'not specified'}
- Tenant: {result.get('tenant') or 'not specified'}
- Version: {version.get('version') or version.get('status') or 'unresolved'}
- Commit: {version.get('commit_sha') or 'not recorded'}

## Facts

{_markdown_items(result.get('facts'))}

## Causes

{_markdown_items(result.get('causes'))}

## Scope

{scope_text}

## Contradictions and disconfirming evidence

{_markdown_items([*(result.get('contradictions') or []), *(result.get('disconfirming_evidence') or [])])}

## Unknowns

{_markdown_items(result.get('unknowns'))}

## Recommendations

{_markdown_items(result.get('recommendations'))}

## Next owner

{result.get('next_owner') or 'Not assigned'}

## Evidence receipt

- Evidence records: {result.get('evidence_count')}
- Policy fingerprint: `{result.get('policy_fingerprint')}`
"""


def render_investigation_artifact(
    os_root: str | Path,
    run_dir_raw: str | Path,
    *,
    provider: str,
    artifact_type: str,
    output_path: str | Path | None = None,
    overlays: Iterable[str | Path] = (),
) -> dict[str, Any]:
    """Render a concluded result through the common artifact policy plane."""

    root = expand_path(os_root)
    run_dir, state = _run_state(root, run_dir_raw)
    result_path = run_dir / "result.json"
    if state["state"] != "complete" or not result_path.is_file():
        raise InvestigationContractError("conclude the investigation before rendering an artifact")
    result = _read_json(result_path)
    request = _read_json(run_dir / "request.json")
    version = result.get("deployed_version") if isinstance(result.get("deployed_version"), Mapping) else {}
    artifact_contract = resolve_artifact_contract(
        root,
        provider,
        artifact_type,
        domain=state.get("domain"),
        project=state.get("project"),
        overlays=overlays,
    )
    result_ref = _relative(root, result_path)
    evidence_receipts = {
        str(requirement): {
            "status": "verified",
            "value": f"Concluded investigation {state['run_id']}",
            "evidence_ref": result_ref,
            "captured_at": result.get("completed_at") or utc_now(),
        }
        for requirement in artifact_contract["effective"].get("required_evidence") or []
    }
    validation_assertions = {
        str(rule): {
            "status": "passed",
            "evidence_ref": result_ref,
            "checked_at": result.get("completed_at") or utc_now(),
        }
        for rule in artifact_contract["effective"].get("validation") or []
    }
    evidence_payload = {
        **result,
        "title": result.get("title") or request.get("title"),
        "summary": result.get("conclusion"),
        "signal": request.get("signal") or request.get("question"),
        "evidence": result.get("facts"),
        "evidence_gaps": result.get("unknowns"),
        "root_cause": result.get("conclusion"),
        "corrective_actions": result.get("recommendations"),
        "code_version": version.get("version"),
        "evidence_receipts": evidence_receipts,
        "validation_assertions": validation_assertions,
    }
    evidence_input = run_dir / "artifacts" / "artifact-evidence.json"
    _atomic_json(evidence_input, evidence_payload)
    artifact = render_artifact(
        root,
        provider,
        artifact_type,
        evidence_input,
        domain=state.get("domain"),
        project=state.get("project"),
        overlays=overlays,
    )
    output = _run_directory(root, output_path) if output_path else run_dir / "artifacts" / f"{provider}-{artifact_type}.json"
    _atomic_json(output, artifact)
    receipt = {
        "schema": "investigation-artifact-render/v1",
        "provider": artifact["provider"],
        "artifact_type": artifact["artifact_type"],
        "artifact_ref": _relative(root, output),
        "contract_fingerprint": artifact["contract_fingerprint"],
        "rendered_at": artifact["rendered_at"],
    }
    receipt_path = output.with_suffix(output.suffix + ".receipt.json")
    _atomic_json(receipt_path, receipt)
    output_row = {**receipt, "receipt_ref": _relative(root, receipt_path)}
    existing_outputs = [
        item
        for item in state.setdefault("outputs", [])
        if isinstance(item, Mapping) and item.get("artifact_ref") != receipt["artifact_ref"]
    ]
    state["outputs"] = [*existing_outputs, output_row]
    _save_state(run_dir, state)
    _append_event(run_dir, "investigation.artifact_rendered", receipt)
    return {**receipt, "receipt_ref": _relative(root, receipt_path)}


def investigation_contract_doctor(os_root: str | Path) -> dict[str, Any]:
    """Validate every installed investigation policy pack and representative routes."""

    root = expand_path(os_root)
    roots: list[tuple[str, Path]] = [("root", root / "harness" / "investigation-config")]
    domains_root = root / "domains"
    if domains_root.is_dir():
        for candidate in sorted(domains_root.glob("*/investigation-config")):
            roots.append(("domain", candidate))
        for candidate in sorted(domains_root.glob("*/02-projects/*/investigation-config")):
            roots.append(("project", candidate))
    findings: list[dict[str, Any]] = []
    counts = {"files": 0, "roots": len(roots), "representative_resolutions": 0}
    source_ids: set[str] = set()
    for scope, policy_root in roots:
        if scope == "root" and not policy_root.is_dir():
            findings.append(
                {
                    "severity": "error",
                    "code": "missing_root_library",
                    "source_ref": "harness/investigation-config",
                    "message": "root investigation contract library is missing",
                }
            )
            continue
        if not policy_root.is_dir():
            continue
        rank = {"root": 0, "domain": 1, "project": 2}[scope]
        for path in sorted(policy_root.rglob("*.md")):
            if path.name.casefold() == "readme.md":
                continue
            counts["files"] += 1
            try:
                document = parse_markdown_policy(root, path, scope=scope, rank=rank)
                rows = _validate_document(document)
                findings.extend(rows)
                if document.frontmatter.get("kind") == "source" and isinstance(document.frontmatter.get("id"), str):
                    source_ids.add(str(document.frontmatter["id"]))
            except (PolicyPlaneError, InvestigationContractError) as exc:
                findings.append(
                    {
                        "severity": "error",
                        "code": "unreadable_policy",
                        "source_ref": _relative(root, path),
                        "message": str(exc),
                    }
                )
    version_source = root / "harness/investigation-config/sources/deployed-version.md"
    if not version_source.is_file():
        findings.append(
            {
                "severity": "error",
                "code": "missing_version_source",
                "source_ref": "harness/investigation-config/sources/deployed-version.md",
                "message": "deployed-version evidence source is required",
            }
        )
    if (root / "harness/investigation-config").is_dir():
        for trigger in sorted(KNOWN_TRIGGER_TYPES):
            for output in sorted({"investigation-report", "root-cause-analysis"}):
                try:
                    resolve_investigation_contract(root, trigger=trigger, output_type=output)
                    counts["representative_resolutions"] += 1
                except InvestigationContractError as exc:
                    findings.append(
                        {
                            "severity": "error",
                            "code": "resolution_failed",
                            "source_ref": f"{trigger}/{output}",
                            "message": str(exc),
                        }
                    )
    severities = {"errors": 0, "warnings": 0, "observations": 0}
    for finding in findings:
        key = {"error": "errors", "warning": "warnings"}.get(finding["severity"], "observations")
        severities[key] += 1
    return {
        "schema": "investigation-contract-doctor/v1",
        "ok": severities["errors"] == 0,
        "counts": {**counts, "source_ids": len(source_ids), **severities},
        "source_ids": sorted(source_ids),
        "findings": findings,
        "checked_at": utc_now(),
    }
