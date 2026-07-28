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
        "subtask",
        "project",
        "review",
        "release",
        "daily-handoff",
        "work-handoff",
        "dashboard",
        "closeout",
        "technical-design",
        "test-plan",
        "incident-report",
        "decision-record",
        "meeting-notes",
        "control-plane",
        "spike",
        "review-report",
        "report",
        "health-report",
        "client-automation-brief",
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
TRACKER_MARKDOWN_LINK_RE = re.compile(
    r"\[[^\]\n]+\]\(https?://[^\s)]+/(?:browse/[A-Za-z][A-Za-z0-9]+-\d+|issue/[A-Za-z][A-Za-z0-9]+-\d+(?:[^\s)]*)|issues/\d+)\)",
    re.IGNORECASE,
)
BUILTIN_VALIDATIONS = frozenset(
    {
        "required_sections_present",
        "audience_safe",
        "facts_distinct_from_inference",
        "evidence_is_sanitized",
        "adf_renders_without_markdown_artifacts",
        "jira_native_rendering",
        "linked_work_has_tracker_hyperlink",
    }
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


def _candidate_paths(
    root: Path, provider: str, artifact_type: str
) -> list[tuple[Path, str, str]]:
    """Return ordered base files plus 1-N Markdown addenda directories."""

    identities = [
        ("any", "any"),
        ("any", artifact_type),
        (provider, "any"),
        (provider, artifact_type),
    ]
    seen: set[tuple[Path, str, str]] = set()
    result: list[tuple[Path, str, str]] = []
    for expected_provider, expected_type in identities:
        base = (root / expected_provider / expected_type).resolve()
        entries = [base.with_suffix(".md")]
        if base.is_dir():
            entries.extend(sorted(path.resolve() for path in base.rglob("*.md") if path.is_file()))
        for candidate in entries:
            row = (candidate, expected_provider, expected_type)
            if row not in seen:
                seen.add(row)
                result.append(row)
    return result


def _validate_document(
    document: MarkdownPolicyDocument,
    *,
    overlay: bool = False,
    expected_provider: str | None = None,
    expected_type: str | None = None,
) -> list[dict[str, Any]]:
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
        expected_provider = expected_provider or document.path.parent.name
        expected_type = expected_type or document.path.stem
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
        found = [row for row in candidates if row[0].is_file()]
        layer_rows.append(
            {
                "scope": layer.scope,
                "root": _relative(root, layer.root),
                "exists": layer.root.is_dir(),
                "candidates": [_relative(root, path) for path, _, _ in candidates],
                "matched": [_relative(root, path) for path, _, _ in found],
            }
        )
        for path, expected_provider, expected_type in found:
            document = parse_markdown_policy(root, path, scope=layer.scope, rank=layer.rank)
            documents.append(document)
            diagnostics.extend(
                _validate_document(
                    document,
                    expected_provider=expected_provider,
                    expected_type=expected_type,
                )
            )
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
        ("Linked Work", ("linked_work", "associated_work", "tickets")),
        ("Summary", ("summary", "problem")),
        ("Change Scope", ("change_scope", "change", "implementation")),
        ("Safety, Compatibility, and Rollout", ("safety_compatibility_and_rollout", "risks", "risk")),
        ("Validation", ("validation", "test_evidence", "tests")),
        ("Reviewer Focus", ("reviewer_focus", "review")),
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


def _contract_receipt_rows(
    evidence: Mapping[str, Any], required: Sequence[Any]
) -> list[dict[str, Any]]:
    """Normalize producer-supplied evidence receipts without inventing proof."""

    raw = evidence.get("evidence_receipts")
    receipts = raw if isinstance(raw, Mapping) else {}
    rows: list[dict[str, Any]] = []
    for item in required:
        name = str(item).strip()
        value = receipts.get(name)
        if isinstance(value, Mapping):
            row = dict(value)
        elif value not in (None, ""):
            row = {"status": "verified", "value": value}
        else:
            row = {}
        rows.append(
            {
                "requirement": name,
                "status": str(row.get("status") or "missing").strip().lower(),
                "value": row.get("value"),
                "evidence_ref": row.get("evidence_ref"),
                "captured_at": row.get("captured_at"),
            }
        )
    return rows


def _validation_assertion_rows(
    evidence: Mapping[str, Any], rules: Sequence[Any]
) -> list[dict[str, Any]]:
    raw = evidence.get("validation_assertions")
    assertions = raw if isinstance(raw, Mapping) else {}
    rows: list[dict[str, Any]] = []
    for item in rules:
        rule = str(item).strip()
        if rule in BUILTIN_VALIDATIONS:
            rows.append({"rule": rule, "status": "engine_validated", "evidence_ref": None, "checked_at": None})
            continue
        value = assertions.get(rule)
        row = dict(value) if isinstance(value, Mapping) else {}
        rows.append(
            {
                "rule": rule,
                "status": str(row.get("status") or "missing").strip().lower(),
                "evidence_ref": row.get("evidence_ref"),
                "checked_at": row.get("checked_at"),
            }
        )
    return rows


def _provider_payload(renderer: str, title: str, markdown: str, contract: Mapping[str, Any]) -> Any:
    """Build the provider-adapter payload; only Jira claims a native document."""

    if renderer in {"jira_adf", "atlassian_adf"}:
        return markdown_to_adf(markdown)
    if renderer in {"github_markdown", "linear_markdown"}:
        return {"title": title, "body": markdown}
    if renderer == "slack_markdown":
        return {"text": markdown}
    if renderer in {"notion_enhanced_markdown", "confluence_markdown"}:
        return {
            "title": title,
            "enhanced_markdown": markdown,
            "layout": deepcopy(dict(contract.get("format") or {})),
        }
    return markdown


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
    title = str(evidence.get("title") or evidence.get("summary") or artifact_type.replace("-", " ").title()).strip()
    provider_payload = _provider_payload(renderer, title, markdown, resolution["effective"])
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
        "provider_payload": provider_payload,
        # Compatibility alias. Only Jira ADF is a provider-native document;
        # every other value is an explicit adapter payload.
        "native": provider_payload,
        "evidence_contract": _contract_receipt_rows(
            evidence, resolution["effective"].get("required_evidence") or []
        ),
        "validation_contract": _validation_assertion_rows(
            evidence, resolution["effective"].get("validation") or []
        ),
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
    validations = {str(item) for item in effective.get("validation") or []}
    if "linked_work_has_tracker_hyperlink" in validations:
        linked_work = re.search(r"^##\s+Linked Work\s*$([\s\S]*?)(?=^##\s|\Z)", body, re.MULTILINE)
        if not linked_work or not TRACKER_MARKDOWN_LINK_RE.search(linked_work.group(1)):
            findings.append(
                {
                    "code": "missing_tracker_hyperlink",
                    "message": "Linked Work must contain a Markdown hyperlink to a Jira, Linear, or GitHub work item",
                }
            )
    for receipt in artifact.get("evidence_contract") or []:
        if not isinstance(receipt, Mapping) or receipt.get("status") not in {"verified", "satisfied", "captured"}:
            requirement = receipt.get("requirement") if isinstance(receipt, Mapping) else "unknown"
            findings.append(
                {
                    "code": "missing_required_evidence",
                    "message": f"required evidence lacks a verified receipt: {requirement}",
                }
            )
    for assertion in artifact.get("validation_contract") or []:
        if not isinstance(assertion, Mapping):
            findings.append({"code": "missing_validation_assertion", "message": "invalid validation assertion"})
            continue
        if assertion.get("status") == "engine_validated":
            continue
        if assertion.get("status") not in {"passed", "verified"} or not assertion.get("evidence_ref") or not assertion.get("checked_at"):
            findings.append(
                {
                    "code": "missing_validation_assertion",
                    "message": f"semantic validation lacks a passed evidence receipt: {assertion.get('rule')}",
                }
            )
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


def _load_governance_receipt(
    root: Path,
    raw: str | Path | None,
    *,
    schema: str,
    label: str,
) -> dict[str, Any]:
    if raw is None:
        raise ArtifactContractError(f"external provider apply requires a {label} receipt")
    path = Path(raw).expanduser().resolve()
    _relative(root, path)
    if not path.is_file():
        raise ArtifactContractError(f"{label} receipt not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ArtifactContractError(f"{label} receipt must be valid JSON") from exc
    if not isinstance(value, dict) or value.get("schema") != schema:
        raise ArtifactContractError(f"{label} receipt must use {schema}")
    return {**value, "receipt_ref": _relative(root, path)}


def _validate_apply_governance(
    artifact: Mapping[str, Any],
    *,
    target: str,
    approval: Mapping[str, Any],
    target_verification: Mapping[str, Any],
) -> None:
    provider = artifact.get("provider")
    artifact_type = artifact.get("artifact_type")
    fingerprint = artifact.get("contract_fingerprint")
    if approval.get("status") != "approved":
        raise ArtifactContractError("approval receipt must have status: approved")
    for key, expected in (
        ("provider", provider),
        ("artifact_type", artifact_type),
        ("contract_fingerprint", fingerprint),
        ("target", target),
    ):
        if approval.get(key) != expected:
            raise ArtifactContractError(f"approval receipt {key} does not match the rendered artifact")
    if not approval.get("approved_by") or not approval.get("approved_at"):
        raise ArtifactContractError("approval receipt requires approved_by and approved_at")
    if target_verification.get("status") != "verified":
        raise ArtifactContractError("target verification receipt must have status: verified")
    if target_verification.get("provider") != provider or target_verification.get("target") != target:
        raise ArtifactContractError("target verification does not match the provider and target")
    if not target_verification.get("resolver") or not target_verification.get("verified_at") or not target_verification.get("evidence_ref"):
        raise ArtifactContractError(
            "target verification requires resolver, verified_at, and evidence_ref"
        )


def prepare_artifact_apply(
    os_root: str | Path,
    artifact_path: str | Path,
    *,
    target: str | Path | None,
    execute: bool,
    receipt_path: str | Path,
    approval_receipt: str | Path | None = None,
    target_receipt: str | Path | None = None,
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
    effective = ((artifact.get("resolution") or {}).get("effective") or {})
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
        if target is None or not str(target).strip():
            raise ArtifactContractError("external provider apply requires a verified --target")
        approval_value = _load_governance_receipt(
            root,
            approval_receipt,
            schema="artifact-approval/v1",
            label="approval",
        )
        target_value = _load_governance_receipt(
            root,
            target_receipt,
            schema="artifact-target-verification/v1",
            label="target verification",
        )
        _validate_apply_governance(
            artifact,
            target=str(target),
            approval=approval_value,
            target_verification=target_value,
        )
        payload_hash = hashlib.sha256(
            json.dumps(artifact.get("provider_payload"), sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        result.update(
            {
                "status": "awaiting_provider_adapter",
                "target": str(target),
                "approval_receipt": approval_value,
                "target_verification": target_value,
                "required_readback": list(effective.get("readback") or []),
                "expected_content_sha256": payload_hash,
                "adapter_handoff": {
                    "provider": provider,
                    "title": artifact["title"],
                    "renderer": artifact["renderer"],
                    "provider_payload": artifact["provider_payload"],
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
    readback_receipt: str | Path,
) -> dict[str, Any]:
    """Close an external-provider handoff after an agent performs live readback."""

    root = expand_path(os_root)
    path = Path(apply_receipt).expanduser().resolve()
    _relative(root, path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema") != "artifact-apply/v1" or value.get("status") != "awaiting_provider_adapter":
        raise ArtifactContractError("apply receipt is not awaiting provider readback")
    readback = _load_governance_receipt(
        root,
        readback_receipt,
        schema="artifact-provider-readback/v1",
        label="provider readback",
    )
    if readback.get("status") != "verified":
        raise ArtifactContractError("provider readback receipt must have status: verified")
    if readback.get("provider") != value.get("provider") or readback.get("target") != value.get("target"):
        raise ArtifactContractError("provider readback does not match the apply provider and target")
    if not str(readback.get("external_id") or "").strip() or not readback.get("verified_at"):
        raise ArtifactContractError("provider readback requires external_id and verified_at")
    observed = readback.get("observed") if isinstance(readback.get("observed"), Mapping) else {}
    missing = [field for field in value.get("required_readback") or [] if field not in observed]
    if missing:
        raise ArtifactContractError("provider readback is missing observed fields: " + ", ".join(missing))
    if "content" not in readback:
        raise ArtifactContractError("provider readback requires the normalized live content")
    actual_hash = hashlib.sha256(
        json.dumps(readback["content"], sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if actual_hash != value.get("expected_content_sha256"):
        raise ArtifactContractError("provider readback content does not match the rendered provider payload")
    value["status"] = "completed"
    value["readback"] = {
        "verified": True,
        "external_id": readback["external_id"],
        "external_url": readback.get("external_url"),
        "observed": dict(observed),
        "sha256": actual_hash,
        "verified_at": readback["verified_at"],
        "receipt_ref": _relative(root, Path(readback_receipt).expanduser().resolve()),
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
                relative = path.relative_to(layer.root)
                if len(relative.parts) >= 3:
                    expected_provider, expected_type = relative.parts[0], relative.parts[1]
                else:
                    expected_provider, expected_type = path.parent.name, path.stem
                diagnostics.extend(
                    _validate_document(
                        document,
                        expected_provider=expected_provider,
                        expected_type=expected_type,
                    )
                )
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
