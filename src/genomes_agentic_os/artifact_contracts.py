"""Polymorphic artifact contracts, rendering, validation, and receipts."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence
import uuid

import yaml

from .policy_plane import MarkdownPolicyDocument, PolicyLayer, PolicyPlaneError, parse_markdown_policy
from .scaffold import domain_path, expand_path, normalize_domain, validate_name


ARTIFACT_SCHEMA_VERSION = 1
KNOWN_PROVIDERS = frozenset({"any", "jira", "confluence", "notion", "linear", "github", "slack", "filesystem"})
KNOWN_TYPES = frozenset(
    {
        "any",
        "bug",
        "story",
        "epic",
        "task",
        "issue",
        "initiative",
        "comment",
        "qa-failure",
        "investigation-report",
        "root-cause-analysis",
        "status",
        "release-note",
        "planning-spec",
        "pull-request",
        "program",
        "workflow-documentation",
    }
)
ALLOWED_FRONTMATTER = frozenset(
    {
        "schema_version",
        "provider",
        "artifact_type",
        "mode",
        "destination",
        "required_sections",
        "required_evidence",
        "optional_sections",
        "prohibited_content",
        "format",
        "approval",
        "validation",
        "readback",
        "safety",
        "terminology",
        "defaults",
    }
)
APPROVAL_RANK = {"none": 0, "inherited": 5, "implicit": 10, "explicit": 30, "human": 40, "two_person": 50}
MONOTONIC_LIST_KEYS = frozenset(
    {"required_sections", "required_evidence", "prohibited_content", "validation", "readback"}
)
MONOTONIC_TRUE_PATHS = frozenset(
    {
        "safety.sanitize_external_output",
        "safety.verify_target",
        "safety.readback_required",
        "safety.block_secrets",
        "safety.block_local_paths",
        "safety.block_private_links",
    }
)
LOCAL_PATH_RE = re.compile(r"(?:(?:/Users|/home|/private|/tmp)/[^\s)>\]}]+|~/(?:[^\s)>\]}]+))")
PRIVATE_NOTION_RE = re.compile(
    r"https?://(?:www\.)?(?:notion\.so|notion\.site|app\.notion\.com)/[^\s)>\]}]+", re.IGNORECASE
)
SECRET_RE = re.compile(
    r"(?i)(?:sk-[a-z0-9_-]{20,}|gh[pousr]_[a-z0-9_]{20,}|xox[baprs]-[a-z0-9-]{20,}|"
    r"(?:authorization\s*:\s*(?:bearer|basic)\s+\S+)|"
    r"(?:api[_-]?key|token|secret|password|private[_-]?key|access[_-]?key)\s*[:=]\s*[^\s]{8,})"
)


class ArtifactContractError(ValueError):
    """Raised when artifact policy or output cannot safely proceed."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slug(value: str, label: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", normalized):
        raise ArtifactContractError(f"{label} must use lowercase letters, numbers, and hyphens")
    return normalized


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ArtifactContractError(f"path is outside the Agentic OS root: {path}") from exc


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    _atomic_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def artifact_policy_roots(
    os_root: str | Path,
    *,
    domain: str | None = None,
    project: str | None = None,
) -> list[PolicyLayer]:
    """Return conventional root -> domain -> project inheritance layers."""

    root = expand_path(os_root)
    layers = [PolicyLayer("root", root / "harness" / "artifact-config", 0)]
    if project and not domain:
        raise ArtifactContractError("--project requires --domain")
    if domain:
        domain_name = normalize_domain(domain)
        local_domain = domain_path(root, domain_name)
        layers.append(PolicyLayer("domain", local_domain / "artifact-config", 1))
        if project:
            project_name = validate_name(project, "project")
            layers.append(PolicyLayer("project", local_domain / "02-projects" / project_name / "artifact-config", 2))
    return layers


def _candidate_paths(root: Path, provider: str, artifact_type: str) -> list[Path]:
    relative = [
        Path("any") / "any.md",
        Path("any") / f"{artifact_type}.md",
        Path(provider) / "any.md",
        Path(provider) / f"{artifact_type}.md",
    ]
    seen: set[Path] = set()
    result: list[Path] = []
    for item in relative:
        candidate = (root / item).resolve()
        if candidate not in seen:
            seen.add(candidate)
            result.append(candidate)
    return result


def _validate_document(document: MarkdownPolicyDocument, *, overlay: bool = False) -> list[dict[str, Any]]:
    metadata = document.frontmatter
    findings: list[dict[str, Any]] = []

    def finding(code: str, message: str, *, severity: str = "error", field: str | None = None) -> None:
        row = {"severity": severity, "code": code, "message": message, "source_ref": document.source_ref}
        if field:
            row["field"] = field
        findings.append(row)

    if metadata.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
        finding("invalid_schema_version", f"schema_version must be {ARTIFACT_SCHEMA_VERSION}", field="schema_version")
    for key in ("provider", "artifact_type"):
        value = metadata.get(key)
        if not isinstance(value, str) or not value.strip():
            finding("missing_identity", f"{key} is required", field=key)
    if not overlay:
        expected_provider = document.path.parent.name
        expected_type = document.path.stem
        if metadata.get("provider") != expected_provider:
            finding("identity_path_mismatch", f"provider must match folder {expected_provider!r}", field="provider")
        if metadata.get("artifact_type") != expected_type:
            finding("identity_path_mismatch", f"artifact_type must match filename {expected_type!r}", field="artifact_type")
    if metadata.get("mode", "compose") != "compose":
        finding("unsupported_mode", "only mode: compose is supported", field="mode")
    for key in ("required_sections", "required_evidence", "optional_sections", "prohibited_content", "validation", "readback"):
        if key in metadata and not isinstance(metadata[key], list):
            finding("invalid_field_type", f"{key} must be a list", field=key)
    for key in ("destination", "format", "approval", "safety", "terminology", "defaults"):
        if key in metadata and not isinstance(metadata[key], dict):
            finding("invalid_field_type", f"{key} must be a mapping", field=key)
    for key in sorted(set(metadata) - ALLOWED_FRONTMATTER):
        finding("unregistered_field", f"unknown field is preserved for forward compatibility: {key}", severity="warning", field=key)
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


def _merge_contract(
    current: Any,
    incoming: Any,
    *,
    path: tuple[str, ...] = (),
    source_ref: str,
    diagnostics: list[dict[str, Any]],
) -> Any:
    dotted = ".".join(path)
    if isinstance(current, dict) and isinstance(incoming, Mapping):
        result = deepcopy(current)
        for key, value in incoming.items():
            if key in {"schema_version", "provider", "artifact_type", "mode"}:
                result[key] = deepcopy(value)
                continue
            if key in result:
                result[key] = _merge_contract(
                    result[key], value, path=(*path, str(key)), source_ref=source_ref, diagnostics=diagnostics
                )
            else:
                result[key] = deepcopy(value)
        return result
    if isinstance(current, list) and isinstance(incoming, list):
        if path and path[-1] in MONOTONIC_LIST_KEYS:
            return _list_union(current, incoming)
        return _list_union(current, incoming)
    if dotted.startswith("approval.") and isinstance(current, str) and isinstance(incoming, str):
        old_rank = APPROVAL_RANK.get(current, -1)
        new_rank = APPROVAL_RANK.get(incoming, -1)
        if new_rank < old_rank:
            diagnostics.append(
                {
                    "severity": "warning",
                    "code": "blocked_safety_override",
                    "field": dotted,
                    "source_ref": source_ref,
                    "message": f"ignored weaker approval {incoming!r}; inherited {current!r} remains effective",
                }
            )
            return deepcopy(current)
    if dotted in MONOTONIC_TRUE_PATHS and current is True and incoming is False:
        diagnostics.append(
            {
                "severity": "warning",
                "code": "blocked_safety_override",
                "field": dotted,
                "source_ref": source_ref,
                "message": "ignored false because inherited safety requirements are monotonic",
            }
        )
        return True
    if current != incoming:
        diagnostics.append(
            {
                "severity": "observation",
                "code": "field_overridden",
                "field": dotted,
                "source_ref": source_ref,
                "message": "narrower contract value selected",
            }
        )
    return deepcopy(incoming)


def resolve_artifact_contract(
    os_root: str | Path,
    provider: str,
    artifact_type: str,
    *,
    domain: str | None = None,
    project: str | None = None,
    overlays: Iterable[str | Path] = (),
) -> dict[str, Any]:
    """Compose the effective artifact contract with explainable provenance."""

    root = expand_path(os_root)
    provider_name = _slug(provider, "provider")
    type_name = _slug(artifact_type, "artifact type")
    layers = artifact_policy_roots(root, domain=domain, project=project)
    documents: list[MarkdownPolicyDocument] = []
    layer_rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for layer in layers:
        candidates = _candidate_paths(layer.root, provider_name, type_name)
        found = [path for path in candidates if path.is_file()]
        layer_rows.append(
            {
                "scope": layer.scope,
                "root": _relative(root, layer.root),
                "exists": layer.root.is_dir(),
                "candidates": [_relative(root, path) for path in candidates],
                "matched": [_relative(root, path) for path in found],
            }
        )
        for path in found:
            document = parse_markdown_policy(root, path, scope=layer.scope, rank=layer.rank)
            documents.append(document)
            diagnostics.extend(_validate_document(document))
    explicit_rank = len(layers)
    for raw in overlays:
        path = Path(raw).expanduser().resolve()
        document = parse_markdown_policy(root, path, scope="invocation", rank=explicit_rank)
        documents.append(document)
        diagnostics.extend(_validate_document(document, overlay=True))
    if not documents:
        raise ArtifactContractError(
            f"no artifact contract matched provider={provider_name!r}, type={type_name!r}; run artifacts doctor"
        )
    errors = [item for item in diagnostics if item["severity"] == "error"]
    if errors:
        summary = "; ".join(f"{item['source_ref']}: {item['message']}" for item in errors)
        raise ArtifactContractError(f"invalid artifact contract: {summary}")
    effective: dict[str, Any] = {}
    body_parts: list[str] = []
    for document in documents:
        effective = _merge_contract(
            effective,
            document.frontmatter,
            source_ref=document.source_ref,
            diagnostics=diagnostics,
        )
        if document.body.strip():
            body_parts.append(f"<!-- {document.scope}: {document.source_ref} -->\n{document.body.strip()}")
    effective["provider"] = provider_name
    effective["artifact_type"] = type_name
    effective["schema_version"] = ARTIFACT_SCHEMA_VERSION
    effective["guidance_markdown"] = "\n\n".join(body_parts).strip() + "\n"
    fingerprint_payload = {
        "provider": provider_name,
        "artifact_type": type_name,
        "sources": [{"source_ref": item.source_ref, "sha256": item.sha256} for item in documents],
        "effective": effective,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema": "artifact-contract-resolution/v1",
        "provider": provider_name,
        "artifact_type": type_name,
        "domain": normalize_domain(domain) if domain else None,
        "project": validate_name(project, "project") if project else None,
        "layers": layer_rows,
        "sources": [item.as_dict(include_body=False) for item in documents],
        "effective": effective,
        "fingerprint": fingerprint,
        "diagnostics": diagnostics,
        "counts": {
            "sources": len(documents),
            "warnings": sum(item["severity"] == "warning" for item in diagnostics),
            "overrides": sum(item["code"] == "field_overridden" for item in diagnostics),
        },
    }


def _load_evidence(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ArtifactContractError(f"evidence input not found: {source}")
    text = source.read_text(encoding="utf-8")
    if source.suffix.lower() == ".json":
        value = json.loads(text)
    elif source.suffix.lower() in {".yml", ".yaml"}:
        value = yaml.safe_load(text)
    else:
        value = {"summary": text.strip()}
    if not isinstance(value, dict):
        raise ArtifactContractError("evidence input must be a JSON/YAML mapping or Markdown document")
    return dict(value)


def _items(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, Mapping):
        return [f"**{key}:** {item}" for key, item in value.items()]
    text = str(value).strip()
    return [text] if text else []


def _section(lines: list[str], title: str, value: Any, *, required: bool = False) -> None:
    items = _items(value)
    lines.extend([f"## {title}", ""])
    if not items:
        lines.extend([f"[MISSING: {title}]" if required else "_None recorded._", ""])
        return
    if len(items) == 1 and not isinstance(value, (list, Mapping)):
        lines.extend([items[0], ""])
    else:
        lines.extend([f"- {item}" for item in items] + [""])


TYPE_LAYOUTS: dict[str, list[tuple[str, tuple[str, ...]]]] = {
    "bug": [
        ("Observed Behavior", ("observed_behavior", "observed")),
        ("Expected Behavior", ("expected_behavior", "expected")),
        ("Reproduction", ("reproduction", "steps_to_reproduce")),
        ("Impact", ("impact",)),
        ("Acceptance Criteria", ("acceptance_criteria",)),
    ],
    "story": [
        ("User Outcome", ("user_outcome", "outcome")),
        ("Scope", ("scope",)),
        ("Acceptance Criteria", ("acceptance_criteria",)),
        ("Non-Goals", ("non_goals",)),
    ],
    "epic": [
        ("Outcome", ("outcome",)),
        ("Problem", ("problem",)),
        ("Scope", ("scope",)),
        ("Workstreams", ("workstreams",)),
        ("Acceptance Criteria", ("acceptance_criteria",)),
        ("Non-Goals", ("non_goals",)),
    ],
    "initiative": [
        ("Strategic Outcome", ("strategic_outcome", "outcome")),
        ("Why Now", ("why_now",)),
        ("Success Measures", ("success_measures", "metrics")),
        ("Projects", ("projects", "workstreams")),
        ("Risks", ("risks",)),
    ],
    "root-cause-analysis": [
        ("Impact", ("impact",)),
        ("Timeline", ("timeline",)),
        ("Root Cause", ("root_cause",)),
        ("Contributing Factors", ("contributing_factors",)),
        ("Corrective Actions", ("corrective_actions", "recommendations")),
        ("Prevention and Detection", ("prevention", "detection")),
    ],
    "investigation-report": [
        ("Signal", ("signal", "allegation")),
        ("Scope", ("scope",)),
        ("Timeline", ("timeline",)),
        ("Hypotheses", ("hypotheses",)),
        ("Conclusion", ("conclusion",)),
    ],
    "qa-failure": [
        ("Failed Scenario", ("failed_scenario", "scenario")),
        ("Observed Behavior", ("observed_behavior", "observed")),
        ("Expected Behavior", ("expected_behavior", "expected")),
        ("Environment", ("environment",)),
        ("Evidence", ("evidence",)),
    ],
    "pull-request": [
        ("Description of the Feature or Problem", ("problem", "summary")),
        ("Description of the Change", ("change", "implementation")),
        ("Associated Work", ("associated_work", "tickets")),
        ("Test Evidence", ("test_evidence", "tests")),
        ("Risk", ("risks", "risk")),
    ],
}


def _pick(evidence: Mapping[str, Any], names: Sequence[str]) -> Any:
    sections = evidence.get("sections") if isinstance(evidence.get("sections"), Mapping) else {}
    for name in names:
        if name in evidence and evidence[name] not in (None, "", []):
            return evidence[name]
        if name in sections and sections[name] not in (None, "", []):
            return sections[name]
    return None


def _render_markdown(resolution: Mapping[str, Any], evidence: Mapping[str, Any]) -> str:
    artifact_type = str(resolution["artifact_type"])
    contract = resolution["effective"]
    title = str(evidence.get("title") or evidence.get("summary") or artifact_type.replace("-", " ").title()).strip()
    lines = [f"# {title}", ""]
    required = {str(item).casefold() for item in contract.get("required_sections", [])}
    summary = evidence.get("summary")
    if summary and (str(summary).strip() != title or "summary" in required):
        _section(lines, "Summary", summary, required="summary" in required)
    context = {
        key.replace("_", " ").title(): evidence[key]
        for key in ("domain", "project", "environment", "tenant", "release", "code_version")
        if evidence.get(key) not in (None, "")
    }
    if context:
        _section(lines, "Context", context)
    rendered: set[str] = {"summary"} if summary and (str(summary).strip() != title or "summary" in required) else set()
    for section_title, keys in TYPE_LAYOUTS.get(artifact_type, []):
        value = _pick(evidence, keys)
        _section(lines, section_title, value, required=section_title.casefold() in required)
        rendered.add(section_title.casefold())
    universal = [
        ("Facts", ("facts",)),
        ("Evidence", ("evidence", "sources")),
        ("Inference", ("inferences", "analysis")),
        ("Recommendations", ("recommendations", "next_actions")),
        ("Evidence Gaps", ("evidence_gaps", "gaps")),
        ("Confidence", ("confidence",)),
    ]
    for section_title, keys in universal:
        value = _pick(evidence, keys)
        if value is not None or section_title.casefold() in required:
            _section(lines, section_title, value, required=section_title.casefold() in required)
            rendered.add(section_title.casefold())
    for section_title in contract.get("required_sections", []):
        normalized = str(section_title).casefold()
        if normalized not in rendered:
            key = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
            _section(lines, str(section_title), _pick(evidence, (key,)), required=True)
    return "\n".join(lines).rstrip() + "\n"


def _adf_inline(text: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": text}]


def markdown_to_adf(markdown: str) -> dict[str, Any]:
    """Convert the supported artifact Markdown subset to Jira-native ADF."""

    content: list[dict[str, Any]] = []
    bullets: list[dict[str, Any]] = []

    def flush_bullets() -> None:
        nonlocal bullets
        if bullets:
            content.append({"type": "bulletList", "content": bullets})
            bullets = []

    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            flush_bullets()
            continue
        if line.startswith("# "):
            flush_bullets()
            content.append({"type": "heading", "attrs": {"level": 1}, "content": _adf_inline(line[2:].strip())})
        elif line.startswith("## "):
            flush_bullets()
            content.append({"type": "heading", "attrs": {"level": 2}, "content": _adf_inline(line[3:].strip())})
        elif line.startswith("- "):
            bullets.append(
                {
                    "type": "listItem",
                    "content": [{"type": "paragraph", "content": _adf_inline(line[2:].strip())}],
                }
            )
        else:
            flush_bullets()
            content.append({"type": "paragraph", "content": _adf_inline(line)})
    flush_bullets()
    return {"version": 1, "type": "doc", "content": content}


def render_artifact(
    os_root: str | Path,
    provider: str,
    artifact_type: str,
    evidence_path: str | Path,
    *,
    domain: str | None = None,
    project: str | None = None,
    overlays: Iterable[str | Path] = (),
) -> dict[str, Any]:
    """Render a native provider draft without mutating an external system."""

    resolution = resolve_artifact_contract(
        os_root, provider, artifact_type, domain=domain, project=project, overlays=overlays
    )
    evidence = _load_evidence(evidence_path)
    markdown = _render_markdown(resolution, evidence)
    renderer = str((resolution["effective"].get("format") or {}).get("renderer") or "markdown")
    native: Any = markdown_to_adf(markdown) if renderer in {"jira_adf", "atlassian_adf"} else markdown
    title = str(evidence.get("title") or evidence.get("summary") or artifact_type.replace("-", " ").title()).strip()
    evidence_hash = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema": "rendered-artifact/v1",
        "provider": resolution["provider"],
        "artifact_type": resolution["artifact_type"],
        "title": title,
        "renderer": renderer,
        "body_markdown": markdown,
        "native": native,
        "contract_fingerprint": resolution["fingerprint"],
        "contract_sources": [item["source_ref"] for item in resolution["sources"]],
        "evidence_sha256": evidence_hash,
        "rendered_at": utc_now(),
        "resolution": resolution,
    }


def external_scrub_findings(text: str, *, prohibited: Iterable[Any] = ()) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for code, pattern in (
        ("local_path", LOCAL_PATH_RE),
        ("private_notion_link", PRIVATE_NOTION_RE),
        ("secret_fragment", SECRET_RE),
    ):
        if pattern.search(text):
            findings.append({"code": code, "message": f"external output contains prohibited {code.replace('_', ' ')}"})
    for raw in prohibited:
        pattern_text = str(raw).strip()
        if not pattern_text:
            continue
        try:
            matched = re.search(pattern_text, text, re.IGNORECASE)
        except re.error:
            matched = pattern_text.casefold() in text.casefold()
        if matched:
            findings.append({"code": "contract_prohibited_content", "message": f"matched prohibited rule: {pattern_text}"})
    unique = {(item["code"], item["message"]): item for item in findings}
    return [unique[key] for key in sorted(unique)]


def _artifact_payload(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ArtifactContractError(f"rendered artifact not found: {source}")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ArtifactContractError("rendered artifact must be the JSON envelope emitted by artifacts render") from exc
    if not isinstance(value, dict) or value.get("schema") != "rendered-artifact/v1":
        raise ArtifactContractError("artifact must use rendered-artifact/v1")
    return value


def validate_rendered_artifact(path: str | Path) -> dict[str, Any]:
    artifact = _artifact_payload(path)
    resolution = artifact.get("resolution") if isinstance(artifact.get("resolution"), Mapping) else {}
    effective = resolution.get("effective") if isinstance(resolution.get("effective"), Mapping) else {}
    body = str(artifact.get("body_markdown") or "")
    findings: list[dict[str, str]] = []
    if not str(artifact.get("title") or "").strip():
        findings.append({"code": "missing_title", "message": "title is required"})
    for marker in sorted(set(re.findall(r"\[MISSING:\s*([^\]]+)\]", body))):
        findings.append({"code": "missing_required_section", "message": f"required section has no evidence: {marker}"})
    if artifact.get("provider") != "filesystem":
        findings.extend(external_scrub_findings(body, prohibited=effective.get("prohibited_content") or []))
    required = [str(item) for item in effective.get("required_sections") or []]
    headings = {match.casefold() for match in re.findall(r"^##\s+(.+?)\s*$", body, re.MULTILINE)}
    for section in required:
        if section.casefold() not in headings:
            findings.append({"code": "missing_required_section", "message": f"required heading is absent: {section}"})
    return {
        "schema": "artifact-validation/v1",
        "valid": not findings,
        "provider": artifact.get("provider"),
        "artifact_type": artifact.get("artifact_type"),
        "contract_fingerprint": artifact.get("contract_fingerprint"),
        "artifact_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "validated_at": utc_now(),
        "findings": findings,
    }


def prepare_artifact_apply(
    os_root: str | Path,
    artifact_path: str | Path,
    *,
    target: str | Path | None,
    execute: bool,
    receipt_path: str | Path,
) -> dict[str, Any]:
    """Apply filesystem output or produce an explicit provider-adapter handoff."""

    if not execute:
        raise ArtifactContractError("apply requires --execute")
    root = expand_path(os_root)
    artifact = _artifact_payload(artifact_path)
    validation = validate_rendered_artifact(artifact_path)
    if not validation["valid"]:
        raise ArtifactContractError("artifact validation failed; inspect the validation receipt")
    provider = str(artifact["provider"])
    receipt = Path(receipt_path).expanduser().resolve()
    _relative(root, receipt)
    approval = ((artifact.get("resolution") or {}).get("effective") or {}).get("approval") or {}
    result: dict[str, Any] = {
        "schema": "artifact-apply/v1",
        "provider": provider,
        "artifact_type": artifact["artifact_type"],
        "artifact_sha256": validation["artifact_sha256"],
        "contract_fingerprint": artifact["contract_fingerprint"],
        "approval": approval,
        "requested_at": utc_now(),
        "validation": validation,
    }
    if provider == "filesystem":
        if target is None:
            raise ArtifactContractError("filesystem apply requires --target")
        destination = Path(target).expanduser().resolve()
        target_ref = _relative(root, destination)
        _atomic_text(destination, str(artifact["body_markdown"]))
        readback = destination.read_text(encoding="utf-8")
        result.update(
            {
                "status": "completed",
                "target_ref": target_ref,
                "readback": {
                    "verified": readback == artifact["body_markdown"],
                    "sha256": hashlib.sha256(readback.encode("utf-8")).hexdigest(),
                    "verified_at": utc_now(),
                },
            }
        )
    else:
        result.update(
            {
                "status": "awaiting_provider_adapter",
                "target": str(target) if target else None,
                "adapter_handoff": {
                    "provider": provider,
                    "title": artifact["title"],
                    "renderer": artifact["renderer"],
                    "native": artifact["native"],
                    "required_action": "Use the registered provider tool, verify target identity, read back the result, then record readback.",
                },
            }
        )
    _atomic_json(receipt, result)
    return {**result, "receipt_ref": _relative(root, receipt)}


def record_artifact_readback(
    os_root: str | Path,
    apply_receipt: str | Path,
    *,
    external_id: str,
    external_url: str | None,
    readback_sha256: str,
) -> dict[str, Any]:
    """Close an external-provider handoff after an agent performs live readback."""

    root = expand_path(os_root)
    path = Path(apply_receipt).expanduser().resolve()
    _relative(root, path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema") != "artifact-apply/v1" or value.get("status") != "awaiting_provider_adapter":
        raise ArtifactContractError("apply receipt is not awaiting provider readback")
    if not external_id.strip() or not re.fullmatch(r"[a-fA-F0-9]{64}", readback_sha256):
        raise ArtifactContractError("external id and 64-character readback SHA-256 are required")
    value["status"] = "completed"
    value["readback"] = {
        "verified": True,
        "external_id": external_id,
        "external_url": external_url,
        "sha256": readback_sha256.lower(),
        "verified_at": utc_now(),
    }
    value.pop("adapter_handoff", None)
    _atomic_json(path, value)
    return {**value, "receipt_ref": _relative(root, path)}


def artifact_contract_doctor(
    os_root: str | Path,
    *,
    domain: str | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    """Validate every contract file and representative effective combinations."""

    root = expand_path(os_root)
    layers = artifact_policy_roots(root, domain=domain, project=project)
    scan_layers = list(layers)
    if domain and not project:
        domain_root = domain_path(root, normalize_domain(domain))
        scan_layers.extend(
            PolicyLayer("project", path, 2)
            for path in sorted((domain_root / "02-projects").glob("*/artifact-config"))
            if path.is_dir()
        )
    elif not domain:
        scan_layers.extend(
            PolicyLayer("domain", path, 1)
            for path in sorted((root / "domains").glob("*/artifact-config"))
            if path.is_dir()
        )
        scan_layers.extend(
            PolicyLayer("project", path, 2)
            for path in sorted((root / "domains").glob("*/02-projects/*/artifact-config"))
            if path.is_dir()
        )
    diagnostics: list[dict[str, Any]] = []
    identities: set[tuple[str, str]] = set()
    files = 0
    seen_roots: set[Path] = set()
    for layer in scan_layers:
        if layer.root.resolve() in seen_roots:
            continue
        seen_roots.add(layer.root.resolve())
        if not layer.root.is_dir():
            continue
        for path in sorted(layer.root.rglob("*.md")):
            if path.name.casefold() == "readme.md":
                continue
            files += 1
            try:
                document = parse_markdown_policy(root, path, scope=layer.scope, rank=layer.rank)
                diagnostics.extend(_validate_document(document))
                provider = str(document.frontmatter.get("provider") or path.parent.name)
                artifact_type = str(document.frontmatter.get("artifact_type") or path.stem)
                identities.add((provider, artifact_type))
            except (PolicyPlaneError, OSError) as exc:
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "contract_parse_failed",
                        "source_ref": _relative(root, path),
                        "message": str(exc),
                    }
                )
    providers = sorted({provider for provider, _ in identities if provider != "any"} | set(KNOWN_PROVIDERS - {"any"}))
    types = sorted({kind for _, kind in identities if kind != "any"} | set(KNOWN_TYPES - {"any"}))
    representative = 0
    for provider in providers:
        for artifact_type in types:
            try:
                resolve_artifact_contract(root, provider, artifact_type, domain=domain, project=project)
                representative += 1
            except ArtifactContractError as exc:
                diagnostics.append(
                    {
                        "severity": "error",
                        "code": "resolution_failed",
                        "provider": provider,
                        "artifact_type": artifact_type,
                        "message": str(exc),
                    }
                )
    return {
        "schema": "artifact-contract-doctor/v1",
        "ok": not any(item["severity"] == "error" for item in diagnostics),
        "checked_at": utc_now(),
        "scope": {"domain": domain, "project": project},
        "counts": {
            "files": files,
            "providers": len(providers),
            "artifact_types": len(types),
            "representative_resolutions": representative,
            "errors": sum(item["severity"] == "error" for item in diagnostics),
            "warnings": sum(item["severity"] == "warning" for item in diagnostics),
        },
        "diagnostics": diagnostics,
    }
