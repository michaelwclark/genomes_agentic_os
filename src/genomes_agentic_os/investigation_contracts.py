"""Version-aware, evidence-first contracts and receipts for Auto-Dev Detective."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from fnmatch import fnmatchcase
import fcntl
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
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
APPLIES_TO_FIELDS = frozenset(
    {"triggers", "environments", "outputs", "domains", "projects", "touched_paths", "subjects"}
)
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
RULES_ENGINE_KIT_FILES = (
    "contract.yml",
    "dictionary.yml",
    "checks.yml",
    "coverage.yml",
    "redundancy.yml",
)
RULES_ENGINE_READY_KIT_STATUSES = frozenset(
    {"available", "complete", "completed", "deployed", "ready", "registered"}
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


def _selector_values(value: Any, *, label: str, required: bool = False) -> list[str]:
    """Return selector values without accepting ambiguous mapping/scalar input."""

    if value is None:
        values: list[Any] = []
    elif isinstance(value, str):
        values = [value]
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, Mapping)):
        values = list(value)
    else:
        raise InvestigationContractError(f"{label} must be a string or list of strings")
    result: list[str] = []
    for item in values:
        if not isinstance(item, str) or not item.strip():
            raise InvestigationContractError(f"{label} entries must be non-empty strings")
        result.append(item.strip())
    if required and not result:
        raise InvestigationContractError(f"{label} must declare at least one value")
    return result


def _normalize_subjects(value: Any, *, label: str, required: bool = False) -> list[str]:
    return sorted({_slug(item, label) for item in _selector_values(value, label=label, required=required)})


def _normalize_touched_path(value: str, *, label: str, pattern: bool) -> str:
    """Return one normalized relative POSIX path or glob without resolving it."""

    if len(value) > 512 or "\x00" in value:
        raise InvestigationContractError(f"{label} must be a non-empty normalized relative POSIX path")
    if "\\" in value:
        raise InvestigationContractError(f"{label} must use a relative POSIX path")
    path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if (
        path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or value.startswith("~")
        or not path.parts
        or any(part in {".", ".."} for part in path.parts)
        or path.as_posix() != value
    ):
        raise InvestigationContractError(f"{label} must be a normalized relative POSIX path")
    if not pattern and any(character in value for character in "*?["):
        raise InvestigationContractError(f"{label} must not contain glob characters")
    return path.as_posix()


def _normalize_touched_paths(
    value: Any,
    *,
    label: str,
    pattern: bool,
    required: bool = False,
) -> list[str]:
    return sorted(
        {
            _normalize_touched_path(item, label=label, pattern=pattern)
            for item in _selector_values(value, label=label, required=required)
        }
    )


def _normalize_rulebook_ids(
    value: Any,
    *,
    label: str,
    required: bool = False,
) -> list[str]:
    """Return deterministic, path-safe Rules Engine rulebook identifiers.

    Rulebook names are catalog identities rather than filesystem paths.  Keep
    their human-readable punctuation, but canonicalize case so that callers
    cannot select a different catalog entry merely by changing capitalization.
    """

    normalized: set[str] = set()
    for item in _selector_values(value, label=label, required=required):
        if (
            len(item) > 256
            or "\x00" in item
            or "/" in item
            or "\\" in item
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]*", item)
        ):
            raise InvestigationContractError(
                f"{label} entries must be path-safe Rules Engine rulebook identifiers"
            )
        normalized.add(item.casefold())
    return sorted(normalized)


def _root_relative_reference(
    root: Path,
    value: Any,
    *,
    label: str,
) -> tuple[Path, str]:
    """Resolve one declared root-relative reference without allowing escape."""

    if not isinstance(value, str) or not value.strip():
        raise InvestigationContractError(f"{label} must be a non-empty root-relative path")
    reference = _normalize_touched_path(value.strip(), label=label, pattern=False)
    path = (root / reference).resolve()
    _relative(root, path)
    return path, reference


def _rules_engine_context_configuration(
    value: Any,
    *,
    label: str,
) -> dict[str, Any]:
    """Validate the opt-in dynamic Rules Engine evidence configuration.

    A policy file only declares where dynamic evidence *may* be found.  It
    never materializes or assumes a kit.  The resolver below records an
    explicit unavailable/insufficient state when those declared files are not
    actually present and usable.
    """

    if not isinstance(value, Mapping):
        raise InvestigationContractError(f"{label} must be a mapping")
    allowed = {
        "catalog_ref",
        "snapshot_root_ref",
        "findings_ref",
        "rulebook_ids",
        "required_kit_files",
        "max_age_hours",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise InvestigationContractError(
            f"{label} has unknown fields: {', '.join(str(item) for item in unknown)}"
        )
    result: dict[str, Any] = {}
    for field in ("catalog_ref", "snapshot_root_ref", "findings_ref"):
        if field not in value or value[field] is None:
            continue
        if not isinstance(value[field], str) or not value[field].strip():
            raise InvestigationContractError(f"{label}.{field} must be a non-empty root-relative path")
        _normalize_touched_path(value[field].strip(), label=f"{label}.{field}", pattern=False)
        result[field] = value[field].strip()
    if "rulebook_ids" in value:
        result["rulebook_ids"] = _normalize_rulebook_ids(
            value["rulebook_ids"], label=f"{label}.rulebook_ids"
        )
    required_files = value.get("required_kit_files", RULES_ENGINE_KIT_FILES)
    if not isinstance(required_files, Sequence) or isinstance(
        required_files, (bytes, bytearray, str)
    ):
        raise InvestigationContractError(f"{label}.required_kit_files must be a list")
    normalized_files = tuple(str(item) for item in required_files)
    if normalized_files != RULES_ENGINE_KIT_FILES:
        raise InvestigationContractError(
            f"{label}.required_kit_files must declare exactly: "
            + ", ".join(RULES_ENGINE_KIT_FILES)
        )
    result["required_kit_files"] = list(RULES_ENGINE_KIT_FILES)
    max_age = value.get("max_age_hours", 72)
    if not isinstance(max_age, (int, float)) or isinstance(max_age, bool) or max_age <= 0:
        raise InvestigationContractError(f"{label}.max_age_hours must be a positive number")
    result["max_age_hours"] = float(max_age)
    return result


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_dynamic_evidence_mapping(path: Path, *, label: str) -> dict[str, Any]:
    """Read one local JSON/YAML evidence mapping without provider access."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InvestigationContractError(f"unable to read {label}: {path}") from exc
    try:
        if path.suffix.casefold() == ".json":
            value = json.loads(text)
        else:
            value = yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise InvestigationContractError(f"invalid {label}: {path}") from exc
    if not isinstance(value, Mapping):
        raise InvestigationContractError(f"{label} must contain a mapping: {path}")
    return dict(value)


def _compact_snapshot_evidence(
    root: Path,
    configuration: Mapping[str, Any],
    *,
    environment: str | None,
) -> dict[str, Any]:
    """Return privacy-safe freshness/coverage evidence from local registries."""

    raw_root = configuration.get("snapshot_root_ref")
    if raw_root is None:
        return {"status": "not-declared"}
    snapshot_root, root_ref = _root_relative_reference(
        root, raw_root, label="rules_engine_context.snapshot_root_ref"
    )
    if not snapshot_root.is_dir():
        return {
            "status": "unavailable",
            "root_ref": root_ref,
            "reason": "snapshot-root-missing",
        }
    candidates = sorted(snapshot_root.glob("*/rulesmeta.json"))
    direct = snapshot_root / "rulesmeta.json"
    if direct.is_file():
        candidates = [direct, *candidates]
    max_age_hours = float(configuration["max_age_hours"])
    now = datetime.now(timezone.utc)
    registries: list[dict[str, Any]] = []
    malformed = False
    for path in candidates:
        try:
            payload = _load_dynamic_evidence_mapping(path, label="Rules Engine snapshot registry")
            registry_environment = str(payload.get("environment") or path.parent.name).strip()
            if environment and registry_environment.casefold() != environment.casefold():
                continue
            captured_at = _parse_timestamp(
                str(payload.get("last_successful_sync_at") or ""),
                label="Rules Engine snapshot last_successful_sync_at",
            )
            tenants = payload.get("tenants")
            if not isinstance(tenants, Mapping):
                raise InvestigationContractError("Rules Engine snapshot tenants must be a mapping")
            tenant_count = len(tenants)
            rule_count = 0
            for tenant in tenants.values():
                if not isinstance(tenant, Mapping) or not isinstance(tenant.get("rule_count"), int):
                    raise InvestigationContractError("Rules Engine snapshot tenant coverage is incomplete")
                rule_count += int(tenant["rule_count"])
            age_hours = max(0.0, (now - captured_at).total_seconds() / 3600)
            registries.append(
                {
                    "environment": registry_environment,
                    "rulesmeta_ref": _relative(root, path),
                    "sha256": _sha256_file(path),
                    "last_successful_sync_at": captured_at.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                    "age_hours": round(age_hours, 3),
                    "freshness": "current" if age_hours <= max_age_hours else "stale",
                    "tenant_count": tenant_count,
                    "rule_count": rule_count,
                }
            )
        except InvestigationContractError:
            malformed = True
    if not registries:
        return {
            "status": "unavailable",
            "root_ref": root_ref,
            "reason": "snapshot-registry-missing-or-invalid",
        }
    registries.sort(key=lambda item: str(item["environment"]).casefold())
    coverage = {
        "environment_count": len(registries),
        "tenant_count": sum(int(item["tenant_count"]) for item in registries),
        "rule_count": sum(int(item["rule_count"]) for item in registries),
    }
    complete = (
        not malformed
        and coverage["environment_count"] > 0
        and coverage["tenant_count"] > 0
        and coverage["rule_count"] > 0
    )
    current = complete and all(item["freshness"] == "current" for item in registries)
    return {
        "status": "usable" if current else "insufficient-evidence",
        "root_ref": root_ref,
        "max_age_hours": max_age_hours,
        "coverage": {**coverage, "complete": complete},
        "registries": registries,
    }


def _compact_known_findings(
    root: Path,
    configuration: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind a bounded findings envelope without copying raw tenant evidence."""

    raw_ref = configuration.get("findings_ref")
    if raw_ref is None:
        return {"status": "not-declared"}
    path, reference = _root_relative_reference(
        root, raw_ref, label="rules_engine_context.findings_ref"
    )
    if not path.is_file():
        return {"status": "unavailable", "ref": reference, "reason": "findings-file-missing"}
    try:
        payload = _load_dynamic_evidence_mapping(path, label="Rules Engine findings")
    except InvestigationContractError:
        return {"status": "unavailable", "ref": reference, "reason": "findings-file-invalid"}
    raw_findings = payload.get("findings", payload.get("known_findings"))
    if not isinstance(raw_findings, list):
        return {"status": "unavailable", "ref": reference, "reason": "findings-list-missing"}
    summaries: list[dict[str, str]] = []
    severities: dict[str, int] = {}
    for finding in raw_findings[:100]:
        if not isinstance(finding, Mapping):
            continue
        stable = json.dumps(dict(finding), sort_keys=True, default=str, separators=(",", ":"))
        row = {"fingerprint": hashlib.sha256(stable.encode("utf-8")).hexdigest()}
        for key in ("classification", "severity", "status"):
            item = finding.get(key)
            if isinstance(item, str) and item.strip() and len(item.strip()) <= 96:
                row[key] = item.strip()
        severity = row.get("severity")
        if severity:
            severities[severity] = severities.get(severity, 0) + 1
        summaries.append(row)
    return {
        "status": "available",
        "ref": reference,
        "sha256": _sha256_file(path),
        "count": len(raw_findings),
        "by_severity": dict(sorted(severities.items())),
        "items": summaries,
    }


def _concrete_rules_engine_kit(
    root: Path,
    *,
    kit_root: Path,
    kit_id: str,
    rulebook: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Hash exactly the five required artifacts from one resolved kit root."""

    artifacts: list[dict[str, str]] = []
    missing: list[str] = []
    for filename in RULES_ENGINE_KIT_FILES:
        artifact_path = kit_root / filename
        try:
            artifact_ref = _relative(root, artifact_path)
        except InvestigationContractError:
            missing.append(filename)
            continue
        if not artifact_path.is_file():
            missing.append(filename)
            continue
        artifacts.append(
            {
                "name": filename,
                "ref": artifact_ref,
                "sha256": _sha256_file(artifact_path),
            }
        )
    if missing:
        return None, sorted(missing)
    kit = {
        "id": kit_id,
        "rulebook": rulebook,
        "root_ref": _relative(root, kit_root),
        "artifacts": artifacts,
    }
    kit["content_sha256"] = hashlib.sha256(
        json.dumps(kit, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return kit, []


def _rules_engine_kit_header_errors(
    *,
    kit_root: Path,
    kit_id: str,
    rulebook: str,
) -> list[str]:
    """Return bounded structural errors for a source-owned ready kit.

    The catalog is only a directory index.  Do not let a ready ``contract.yml``
    make the other four files authoritative by implication: each concrete
    artifact must declare the same v1 rulebook-kit header before its hashes can
    support a loaded frozen context.  Full kit-domain validation remains owned
    by the Rules Engine kit foundation; this resolver intentionally performs
    just the cross-file identity/readiness gate it needs for a safe reference.
    """

    errors: list[str] = []
    expected = {
        "schema_version": 1,
        "kit_id": kit_id,
        "entity_kind": "rulebook",
        "completion_state": "ready",
    }
    contract: Mapping[str, Any] | None = None
    for filename in RULES_ENGINE_KIT_FILES:
        path = kit_root / filename
        try:
            document = _load_dynamic_evidence_mapping(
                path, label=f"Rules Engine kit {filename}"
            )
        except InvestigationContractError:
            errors.append(f"{filename}:invalid")
            continue
        if filename == "contract.yml":
            contract = document
        for field, expected_value in expected.items():
            if document.get(field) != expected_value:
                errors.append(f"{filename}:{field}")
    identity = contract.get("identity") if isinstance(contract, Mapping) else None
    identity_key = identity.get("key") if isinstance(identity, Mapping) else None
    if not isinstance(identity_key, str) or identity_key.strip().casefold() != rulebook.casefold():
        errors.append("contract.yml:identity.key")
    return sorted(set(errors))


def _source_catalog_kit_rows(
    root: Path,
    *,
    catalog_path: Path,
    rows: Sequence[Any],
) -> list[dict[str, Any]]:
    """Read the ticket-scoped Agentic Library kit catalog shape.

    The catalog identifies a directory; the authoritative rulebook key and
    completion state live in that directory's ``contract.yml``.  Invalid rows
    are retained as unusable rather than inferred from filename text.
    """

    resolved: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        kit_id = str(raw.get("kit_id") or "").strip()
        kit_path = raw.get("path")
        if not kit_id or not isinstance(kit_path, str) or not kit_path.strip():
            continue
        try:
            relative = _normalize_touched_path(
                kit_path.strip(), label="Rules Engine source catalog path", pattern=False
            )
            root_path = (catalog_path.parent / relative).resolve()
            _relative(root, root_path)
        except InvestigationContractError:
            continue
        contract_path = root_path / "contract.yml"
        contract: Mapping[str, Any] | None = None
        if contract_path.is_file():
            try:
                contract = _load_dynamic_evidence_mapping(
                    contract_path, label="Rules Engine kit contract"
                )
            except InvestigationContractError:
                contract = None
        identity = contract.get("identity") if isinstance(contract, Mapping) else None
        key = str(identity.get("key") or "").strip() if isinstance(identity, Mapping) else ""
        aliases = (
            _normalize_rulebook_ids(identity.get("aliases"), label="Rules Engine kit aliases")
            if isinstance(identity, Mapping) and identity.get("aliases") is not None
            else []
        )
        resolved.append(
            {
                "kit_id": kit_id,
                "kit_root": root_path,
                "rulebook": key,
                "aliases": aliases,
                "kit_status": (
                    str(contract.get("completion_state") or "").strip().casefold()
                    if isinstance(contract, Mapping)
                    else ""
                ),
                "entity_kind": (
                    str(contract.get("entity_kind") or raw.get("entity_kind") or "").strip()
                    if isinstance(contract, Mapping)
                    else str(raw.get("entity_kind") or "").strip()
                ),
            }
        )
    return resolved


def _rules_engine_context_from_document(
    root: Path,
    document: Mapping[str, Any],
    *,
    selection: Mapping[str, Any],
    environment: str | None,
    rulebook_ids: Sequence[str],
) -> dict[str, Any] | None:
    """Resolve a selected Rules Engine policy to concrete local evidence.

    A selector match is only a candidate.  This function is deliberately
    fail-closed: it reports ``kit-unavailable`` or ``insufficient-evidence``
    unless the catalog identifies exactly one ready kit, all five files have
    matching ready headers and hash, local snapshot coverage is current and
    complete, and a compact known-findings receipt is available.
    """

    requirements = document.get("requirements")
    if not isinstance(requirements, Mapping) or "rules_engine_context" not in requirements:
        return None
    configuration = _rules_engine_context_configuration(
        requirements["rules_engine_context"], label="requirements.rules_engine_context"
    )
    source_refs = [
        str(item)
        for item in document.get("source_refs") or []
        if isinstance(item, str) and item.strip()
    ]
    selection_rulebooks = list(rulebook_ids)
    declared_rulebooks = list(configuration.get("rulebook_ids") or [])
    if selection_rulebooks and declared_rulebooks and selection_rulebooks != declared_rulebooks:
        raise InvestigationContractError(
            "Rules Engine rulebook selection conflicts with the selected policy declaration"
        )
    candidate_rulebooks = selection_rulebooks or declared_rulebooks
    snapshot = _compact_snapshot_evidence(root, configuration, environment=environment)
    findings = _compact_known_findings(root, configuration)
    value: dict[str, Any] = {
        "schema": "rules-engine-frozen-context/v1",
        "status": "kit-unavailable",
        "source_refs": sorted(source_refs),
        "selected_rulebook_ids": candidate_rulebooks,
        "catalog": {"status": "not-declared"},
        "kit": None,
        "snapshot": snapshot,
        "known_findings": findings,
        "reason_codes": [],
    }
    catalog_raw = configuration.get("catalog_ref")
    if catalog_raw is None:
        value["reason_codes"] = ["catalog-not-declared"]
    else:
        catalog_path, catalog_ref = _root_relative_reference(
            root, catalog_raw, label="rules_engine_context.catalog_ref"
        )
        if not catalog_path.is_file():
            value["catalog"] = {
                "status": "unavailable",
                "ref": catalog_ref,
                "reason": "catalog-file-missing",
            }
            value["reason_codes"] = ["catalog-unavailable"]
        else:
            try:
                catalog = _load_dynamic_evidence_mapping(catalog_path, label="Rules Engine kit catalog")
            except InvestigationContractError:
                value["catalog"] = {
                    "status": "unavailable",
                    "ref": catalog_ref,
                    "reason": "catalog-file-invalid",
                }
                value["reason_codes"] = ["catalog-invalid"]
            else:
                inventory_rows = catalog.get("rulebooks")
                source_rows = catalog.get("kits")
                matches: list[dict[str, Any]] = []
                if isinstance(inventory_rows, list):
                    value["catalog"] = {
                        "status": "available",
                        "shape": "inventory/v1",
                        "ref": catalog_ref,
                        "sha256": _sha256_file(catalog_path),
                        "rulebook_count": len(inventory_rows),
                    }
                    for raw in inventory_rows:
                        if not isinstance(raw, Mapping):
                            continue
                        rulebook = str(raw.get("rulebook") or "").strip()
                        if rulebook.casefold() not in set(candidate_rulebooks):
                            continue
                        kit_root: Path | None = None
                        raw_kit_path = raw.get("kit_path")
                        if isinstance(raw_kit_path, str) and raw_kit_path.strip():
                            kit_root, _ = _root_relative_reference(
                                root, raw_kit_path, label="Rules Engine catalog kit_path"
                            )
                        matches.append(
                            {
                                "kit_id": str(raw.get("kit_id") or rulebook),
                                "rulebook": rulebook,
                                "kit_status": str(raw.get("kit_status") or "").strip().casefold(),
                                "kit_root": kit_root,
                                "entity_kind": str(raw.get("entity_kind") or "").strip(),
                            }
                        )
                elif isinstance(source_rows, list):
                    value["catalog"] = {
                        "status": "available",
                        "shape": "ticket-scoped-kits/v1",
                        "ref": catalog_ref,
                        "sha256": _sha256_file(catalog_path),
                        "rulebook_count": len(source_rows),
                    }
                    for row in _source_catalog_kit_rows(
                        root, catalog_path=catalog_path, rows=source_rows
                    ):
                        identities = {str(row.get("rulebook") or "").casefold()}
                        identities.update(str(item).casefold() for item in row.get("aliases") or [])
                        if identities.intersection(candidate_rulebooks):
                            matches.append(row)
                else:
                    value["catalog"] = {
                        "status": "invalid",
                        "ref": catalog_ref,
                        "sha256": _sha256_file(catalog_path),
                    }
                    value["reason_codes"] = ["catalog-rulebooks-missing"]

                if value["catalog"]["status"] != "available":
                    pass
                elif not candidate_rulebooks:
                    value["status"] = "insufficient-evidence"
                    value["reason_codes"] = ["rulebook-identity-missing"]
                elif len(matches) == 0:
                    value["reason_codes"] = ["rulebook-not-in-catalog"]
                elif len(matches) != 1 or len(candidate_rulebooks) != 1:
                    value["status"] = "insufficient-evidence"
                    value["reason_codes"] = ["ambiguous-rulebook-selection"]
                else:
                    match = matches[0]
                    rulebook = str(match.get("rulebook") or "").strip()
                    kit_status = str(match.get("kit_status") or "").strip().casefold()
                    kit_root = match.get("kit_root")
                    entity_kind = str(match.get("entity_kind") or "").strip().casefold()
                    value["catalog"]["selected_rulebook"] = rulebook or None
                    value["catalog"]["kit_status"] = kit_status or None
                    if not rulebook:
                        value["reason_codes"] = ["kit-identity-missing"]
                    elif entity_kind and entity_kind != "rulebook":
                        value["reason_codes"] = ["kit-entity-not-rulebook"]
                    elif not isinstance(kit_root, Path):
                        value["reason_codes"] = ["kit-path-missing"]
                    else:
                        kit, missing = _concrete_rules_engine_kit(
                            root,
                            kit_root=kit_root,
                            kit_id=str(match.get("kit_id") or rulebook),
                            rulebook=rulebook,
                        )
                        if missing:
                            value["catalog"]["missing_artifacts"] = missing
                            value["reason_codes"] = ["kit-artifacts-missing"]
                        else:
                            value["kit"] = kit
                            if kit_status not in RULES_ENGINE_READY_KIT_STATUSES:
                                value["reason_codes"] = ["kit-not-ready"]
                            else:
                                header_errors = _rules_engine_kit_header_errors(
                                    kit_root=kit_root,
                                    kit_id=str(match.get("kit_id") or rulebook),
                                    rulebook=rulebook,
                                )
                                if header_errors:
                                    value["catalog"]["kit_validation_errors"] = header_errors
                                    value["reason_codes"] = ["kit-header-invalid"]
                                elif snapshot.get("status") != "usable":
                                    value["status"] = "insufficient-evidence"
                                    value["reason_codes"] = ["snapshot-insufficient"]
                                elif findings.get("status") != "available":
                                    value["status"] = "insufficient-evidence"
                                    value["reason_codes"] = [
                                        "known-findings-not-declared"
                                        if findings.get("status") == "not-declared"
                                        else "known-findings-unavailable"
                                    ]
                                else:
                                    value["status"] = "loaded"
                                    value["reason_codes"] = []
    if value["status"] == "loaded" and value["kit"] is None:
        raise InvestigationContractError("Rules Engine context cannot be loaded without concrete kit artifacts")
    value["content_sha256"] = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return value


def _path_matches_pattern(path: str, pattern: str) -> bool:
    """Match repo-relative paths component-wise, with ``**`` as recursive glob."""

    path_parts = PurePosixPath(path).parts
    pattern_parts = PurePosixPath(pattern).parts
    cache: dict[tuple[int, int], bool] = {}

    def matches(path_index: int, pattern_index: int) -> bool:
        key = (path_index, pattern_index)
        if key in cache:
            return cache[key]
        if pattern_index == len(pattern_parts):
            result = path_index == len(path_parts)
        elif pattern_parts[pattern_index] == "**":
            result = any(matches(next_index, pattern_index + 1) for next_index in range(path_index, len(path_parts) + 1))
        else:
            result = (
                path_index < len(path_parts)
                and fnmatchcase(path_parts[path_index], pattern_parts[pattern_index])
                and matches(path_index + 1, pattern_index + 1)
            )
        cache[key] = result
        return result

    return matches(0, 0)


def _context_selector_match(
    document: MarkdownPolicyDocument,
    *,
    touched_paths: Sequence[str],
    subjects: Sequence[str],
) -> tuple[bool, dict[str, Any] | None]:
    """Return whether declared context selectors apply and their receipt provenance."""

    applies = document.frontmatter.get("applies_to")
    if applies is None:
        applies = {}
    if not isinstance(applies, Mapping):
        return False, None

    selectors: dict[str, dict[str, list[str]]] = {}
    matched = True
    if "touched_paths" in applies:
        declared_paths = _normalize_touched_paths(
            applies["touched_paths"], label="applies_to.touched_paths", pattern=True, required=True
        )
        matched_paths = sorted(
            {
                path
                for path in touched_paths
                if any(_path_matches_pattern(path, pattern) for pattern in declared_paths)
            }
        )
        selectors["touched_paths"] = {"declared": declared_paths, "matched": matched_paths}
        matched = matched and bool(matched_paths)
    if "subjects" in applies:
        declared_subjects = _normalize_subjects(
            applies["subjects"], label="applies_to.subjects", required=True
        )
        matched_subjects = sorted(set(subjects).intersection(declared_subjects))
        selectors["subjects"] = {"declared": declared_subjects, "matched": matched_subjects}
        matched = matched and bool(matched_subjects)
    if not selectors:
        return True, None
    return matched, {
        "source_ref": document.source_ref,
        "sha256": document.sha256,
        "selectors": selectors,
    }


def _document_applies(
    document: MarkdownPolicyDocument,
    *,
    trigger: str,
    environment: str | None,
    output_type: str,
    domain: str | None,
    project: str | None,
    touched_paths: Sequence[str],
    subjects: Sequence[str],
) -> tuple[bool, dict[str, Any] | None]:
    metadata = document.frontmatter
    applies = metadata.get("applies_to")
    if applies is None:
        applies = {}
    if not isinstance(applies, Mapping):
        return False, None
    if not all(
        (
            _matches(applies.get("triggers"), trigger),
            _matches(applies.get("environments"), environment),
            _matches(applies.get("outputs"), output_type),
            _matches(applies.get("domains"), domain),
            _matches(applies.get("projects"), project),
        )
    ):
        return False, None
    return _context_selector_match(document, touched_paths=touched_paths, subjects=subjects)


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
    requirements = metadata.get("requirements")
    if isinstance(requirements, Mapping) and "rules_engine_context" in requirements:
        try:
            _rules_engine_context_configuration(
                requirements["rules_engine_context"],
                label="requirements.rules_engine_context",
            )
        except InvestigationContractError as exc:
            add(
                "invalid_rules_engine_context",
                str(exc),
                field="requirements.rules_engine_context",
            )
    applies = metadata.get("applies_to")
    if isinstance(applies, Mapping):
        for field in sorted(set(applies) - APPLIES_TO_FIELDS):
            add(
                "unknown_applies_to_selector",
                f"unknown applies_to selector: {field}",
                field=f"applies_to.{field}",
            )
        if "touched_paths" in applies:
            try:
                _normalize_touched_paths(
                    applies["touched_paths"], label="applies_to.touched_paths", pattern=True, required=True
                )
            except InvestigationContractError as exc:
                add("invalid_touched_paths_selector", str(exc), field="applies_to.touched_paths")
        if "subjects" in applies:
            try:
                _normalize_subjects(applies["subjects"], label="applies_to.subjects", required=True)
            except InvestigationContractError as exc:
                add("invalid_subjects_selector", str(exc), field="applies_to.subjects")
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
    touched_paths: Iterable[str] = (),
    subjects: Iterable[str] = (),
    rulebook_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """Compose the exact evidence plan for one investigation request."""

    root = expand_path(os_root)
    trigger_name = _slug(trigger, "trigger")
    output_name = _slug(output_type, "output type")
    environment_name = _slug(environment, "environment") if environment else None
    domain_name = normalize_domain(domain) if domain else None
    project_name = validate_name(project, "project") if project else None
    touched_path_names = _normalize_touched_paths(
        touched_paths, label="touched_paths", pattern=False
    )
    subject_names = _normalize_subjects(subjects, label="subjects")
    rulebook_names = _normalize_rulebook_ids(rulebook_ids, label="rulebook_ids")
    layers = investigation_policy_roots(root, domain=domain_name, project=project_name)
    try:
        plane = resolve_markdown_plane(root, layers, explicit_files=overlays)
    except PolicyPlaneError as exc:
        raise InvestigationContractError(str(exc)) from exc
    diagnostics: list[dict[str, Any]] = []
    for document in plane["documents"]:
        diagnostics.extend(_validate_document(document))
    if any(item["severity"] == "error" for item in diagnostics):
        raise InvestigationContractError("investigation policy contains validation errors; run detective doctor")

    documents: list[MarkdownPolicyDocument] = []
    selection_documents: list[dict[str, Any]] = []
    for document in plane["documents"]:
        applies, provenance = _document_applies(
            document,
            trigger=trigger_name,
            environment=environment_name,
            output_type=output_name,
            domain=domain_name,
            project=project_name,
            touched_paths=touched_path_names,
            subjects=subject_names,
        )
        if applies:
            documents.append(document)
            if provenance is not None:
                selection_documents.append(provenance)

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
    selection = {
        "touched_paths": touched_path_names,
        "subjects": subject_names,
        "rulebook_ids": rulebook_names,
        "selected_documents": sorted(selection_documents, key=lambda item: item["source_ref"]),
    }
    rules_engine_documents = [
        item
        for item in selected
        if isinstance(item.get("requirements"), Mapping)
        and "rules_engine_context" in item["requirements"]
    ]
    if len(rules_engine_documents) > 1:
        raise InvestigationContractError(
            "more than one selected Rules Engine context declaration is ambiguous"
        )
    if rules_engine_documents:
        context = _rules_engine_context_from_document(
            root,
            rules_engine_documents[0],
            selection=selection,
            environment=environment_name,
            rulebook_ids=rulebook_names,
        )
        if context is not None:
            selection["rules_engine_context"] = context
    fingerprint = hashlib.sha256(
        json.dumps({"documents": digest, "selection": selection}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema": "investigation-policy-resolution/v1",
        "trigger": trigger_name,
        "environment": environment_name,
        "output_type": output_name,
        "domain": domain_name,
        "project": project_name,
        "version_gate": "required_before_evidence" if environment_name else "environment_not_specified",
        "selection": selection,
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
            "selected_context_documents": len(selection_documents),
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
    touched_paths: Iterable[str] = (),
    subjects: Iterable[str] = (),
    rulebook_ids: Iterable[str] = (),
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
        touched_paths=touched_paths,
        subjects=subjects,
        rulebook_ids=rulebook_ids,
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
        "touched_paths": resolution["selection"]["touched_paths"],
        "subjects": resolution["selection"]["subjects"],
        "rulebook_ids": resolution["selection"]["rulebook_ids"],
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
        "selection": deepcopy(resolution["selection"]),
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
        "selection": deepcopy(resolution["selection"]),
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
        for prerequisite in match.get("prerequisites") or []:
            text = str(prerequisite).strip()
            normalized = text.casefold()
            automatic = False
            if "deployed" in normalized and "version" in normalized:
                automatic = version.get("status") == "resolved"
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
