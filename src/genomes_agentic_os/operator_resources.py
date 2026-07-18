"""Read-only operator projection for Program and Automation resources.

The projection is deliberately conservative: identities are never joined by a
display name, runtime health is derived only from durable local evidence, and
partial or malformed sources become diagnostics instead of disappearing.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
import hashlib
import json
from pathlib import Path
import re
import tomllib
from typing import Any

import yaml

from .automation_ops import check_automation
from .runtime_backend import effective_queue_mode, runtime_queue_items
from .scaffold import expand_path, installed_domain_names, shared_factory_path
from .state import db as state_db


API_VERSION = "operator-resource-query/v1"
RUNTIME_REGISTRY = Path("harness/shared_factory/00-control-plane/runtime-registry.yml")
RUN_QUEUE = Path("harness/shared_factory/00-control-plane/run-queue.yml")
AUTOMATION_TRACKING = Path(
    "harness/shared_factory/00-control-plane/automation-run-tracking.yml"
)
AUTHORING_RULES = Path("harness/rules/os-authoring-rules.md")
STALE_AFTER_SECONDS = 24 * 60 * 60
MAX_CONFIG_BYTES = 1_048_576
MAX_RUNTIME_BYTES = 16 * 1_048_576
MAX_EVIDENCE_FILES = 8
ICON_PALETTE = ("🧭", "⚙️", "🧩", "🛠️", "📦", "🔧", "🧠", "🚦")

DIAGNOSTIC_REPAIRS = {
    "source_missing": (
        "restore_source",
        "Restore the required source at the reported path or update its canonical source reference.",
    ),
    "source_malformed": (
        "repair_source",
        "Repair the structured source so it parses as the declared JSON, TOML, or YAML format.",
    ),
    "source_shape_invalid": (
        "repair_source_shape",
        "Change the structured source to the required mapping shape.",
    ),
    "dependency_missing": (
        "repair_dependency_reference",
        "Restore the component or update/remove its declared path; mark optional state explicitly when absence is intentional.",
    ),
    "program_definition_unmatched": (
        "declare_program_relationship",
        "Set an exact definition_id or explicitly declare the instance standalone.",
    ),
    "automation_definition_unmatched": (
        "declare_automation_relationship",
        "Point the tracking row at an installed automation definition or mark it as an intentional external tracker.",
    ),
    "automation_schedule_unassociated": (
        "associate_schedule_identity",
        "Add automation_id, definition_id, automation_ref, or an exact canonical automation path; non-automation runtime jobs must set intentional_orphan: true with a non-empty orphan_reason.",
    ),
}


def _iso(value: datetime | None = None) -> str:
    return (
        (value or datetime.now(UTC))
        .astimezone(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _stable_schedule_id(schedule: dict[str, Any]) -> str:
    """Return a deterministic diagnostic identity even for malformed unnamed rows."""
    declared = str(schedule.get("id") or "").strip()
    if declared:
        return declared
    canonical = json.dumps(schedule, sort_keys=True, default=str, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
    return f"unnamed-{digest}"


def _diagnostic(
    diagnostics: list[dict[str, Any]],
    *,
    severity: str,
    code: str,
    source: str,
    message: str,
    resource_id: str | None = None,
    path: str | None = None,
) -> None:
    repair_kind, guidance = DIAGNOSTIC_REPAIRS.get(
        code,
        (
            "inspect_source",
            "Inspect the reported source and resource evidence before changing the canonical definition.",
        ),
    )
    row: dict[str, Any] = {
        "severity": severity,
        "code": code,
        "source": source,
        "message": message,
        "resource_id": resource_id,
        "path": path,
        "repair_kind": repair_kind,
        "guidance": guidance,
    }
    diagnostics.append(row)


def _health_projection(
    state: str,
    *,
    evidence_basis: str,
    summary: str,
    observed_at: str | None = None,
    liveness_observed: bool = False,
    **details: Any,
) -> dict[str, Any]:
    """Build the honest, stable health contract used by operator projections."""
    return {
        "status": state,
        "source": evidence_basis,
        "evidence_basis": evidence_basis,
        "applicable": state != "not_applicable",
        "observed_at": observed_at,
        "liveness_observed": liveness_observed,
        "reason": summary,
        **details,
    }


def _load_structured(
    root: Path,
    path: Path,
    diagnostics: list[dict[str, Any]],
    *,
    source: str,
    required: bool = False,
    max_bytes: int = MAX_CONFIG_BYTES,
) -> dict[str, Any]:
    if not path.is_file():
        if required:
            _diagnostic(
                diagnostics,
                severity="error",
                code="source_missing",
                source=source,
                message="required source is missing",
                path=_rel(root, path),
            )
        return {}
    try:
        if path.stat().st_size > max_bytes:
            raise ValueError(f"source exceeds {max_bytes} bytes")
        if path.suffix == ".json":
            loaded = json.loads(path.read_text(encoding="utf-8"))
        elif path.suffix == ".toml":
            loaded = tomllib.loads(path.read_text(encoding="utf-8"))
        else:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        tomllib.TOMLDecodeError,
        yaml.YAMLError,
    ) as exc:
        _diagnostic(
            diagnostics,
            severity="error",
            code="source_malformed",
            source=source,
            message=f"{type(exc).__name__}: {exc}",
            path=_rel(root, path),
        )
        return {}
    if not isinstance(loaded, dict):
        _diagnostic(
            diagnostics,
            severity="error",
            code="source_shape_invalid",
            source=source,
            message="expected a mapping",
            path=_rel(root, path),
        )
        return {}
    return loaded


def _items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)]


def _markdown_metadata(path: Path, fallback_id: str) -> dict[str, Any]:
    if not path.is_file():
        return {
            "display_name": fallback_id.replace("_", " ").title(),
            "summary": "",
            "status": "unknown",
        }
    content = path.read_text(encoding="utf-8", errors="replace")
    title_match = re.search(
        r"^#\s+(?:OSProgram|InstanceOSProgram|Automation):\s*(.+)$", content, re.M
    )
    purpose_match = re.search(
        r"^##\s+Purpose\s*$\n+(.+?)(?=\n##\s|\Z)", content, re.M | re.S
    )
    summary = ""
    if purpose_match:
        summary = " ".join(
            line.strip() for line in purpose_match.group(1).splitlines() if line.strip()
        )[:600]
    fields: dict[str, str] = {}
    for line in content.splitlines():
        if line.startswith("|"):
            cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
            if len(cells) >= 2 and cells[0] not in {"Field", "---"}:
                fields[cells[0].lower().replace(" ", "_")] = cells[1]
        elif line.startswith("- ") and ":" in line:
            key, value = line[2:].split(":", 1)
            fields.setdefault(
                key.strip().lower().replace(" ", "_"), value.strip().strip("`")
            )
    return _json_safe(
        {
            "display_name": title_match.group(1).strip()
            if title_match
            else fallback_id.replace("_", " ").title(),
            "summary": summary,
            "status": fields.get("status") or "unknown",
            "owner": fields.get("owner"),
            "scope": fields.get("scope") or fields.get("domain"),
            "level": fields.get("level"),
            "raw_fields": fields,
        }
    )


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(value, dict):
        for key in sorted(value, key=str):
            child = f"{prefix}.{key}" if prefix else str(key)
            result.update(_flatten(value[key], child))
    elif isinstance(value, list):
        result[prefix] = [_json_safe(item) for item in value]
    elif prefix:
        result[prefix] = _json_safe(value)
    return result


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


def _config_projection(layers: list[dict[str, Any]]) -> dict[str, Any]:
    effective: dict[str, Any] = {}
    provenance: dict[str, dict[str, Any]] = {}
    projected_layers: list[dict[str, Any]] = []
    for layer in layers:
        fields = _flatten(layer.get("fields") or {})
        status = layer.get("status") or ("present" if fields else "absent")
        projected_layers.append(
            {
                "name": layer["name"],
                "status": status,
                "source_path": layer.get("source_path"),
                "fields": fields,
                "reason": layer.get("reason"),
            }
        )
        if status == "unknown":
            continue
        for field, value in fields.items():
            effective[field] = value
            provenance[field] = {
                "layer": layer["name"],
                "source_path": layer.get("source_path"),
            }
    return {
        "effective": effective,
        "field_provenance": [
            {"field": field, "value": effective[field], **provenance[field]}
            for field in sorted(effective)
        ],
        "layers": projected_layers,
    }


def _routing_projection(configuration: dict[str, Any]) -> dict[str, Any]:
    effective = configuration.get("effective") or {}
    provenance = {
        item.get("field"): {
            "layer": item.get("layer"),
            "source_path": item.get("source_path"),
        }
        for item in configuration.get("field_provenance") or []
        if isinstance(item, dict)
    }
    execution_target = effective.get("execution_target")
    harness = effective.get("harness")
    harness_source = provenance.get("harness")
    if not harness and execution_target in {"codex_harness", "claude_harness"}:
        harness = str(execution_target).removesuffix("_harness")
        harness_source = provenance.get("execution_target")
    complexity_field = (
        "complexity" if "complexity" in effective else "model_reasoning_effort"
    )
    fields = {
        "host": (effective.get("host"), provenance.get("host")),
        "harness": (harness, harness_source),
        "model": (effective.get("model"), provenance.get("model")),
        "complexity": (
            effective.get(complexity_field),
            provenance.get(complexity_field),
        ),
        "execution_target": (execution_target, provenance.get("execution_target")),
    }
    return {
        key: {
            "value": value,
            "provenance": source,
            "status": "known" if value is not None else "unknown",
        }
        for key, (value, source) in fields.items()
    }


def _fallback_icon(resource_id: str) -> str:
    digest = hashlib.sha256(resource_id.encode("utf-8")).digest()
    return ICON_PALETTE[digest[0] % len(ICON_PALETTE)]


def _icon(resource_id: str, *sources: dict[str, Any]) -> dict[str, str]:
    for source in sources:
        value = source.get("icon")
        if isinstance(value, str) and value.strip():
            return {"value": value.strip(), "source": "metadata"}
    return {"value": _fallback_icon(resource_id), "source": "deterministic_fallback"}


def _component_projection(
    root: Path,
    owner_path: Path,
    resource_id: str,
    components: dict[str, Any],
    diagnostics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    container = (
        components.get("components")
        if isinstance(components.get("components"), dict)
        else {}
    )
    rows: list[dict[str, Any]] = []
    for component_kind in sorted(container):
        for value in container.get(component_kind) or []:
            if isinstance(value, dict):
                component_id = str(
                    value.get("id")
                    or value.get("name")
                    or value.get("path")
                    or "unknown"
                )
                path_value = value.get("path")
                role = value.get("role")
                source_package = value.get("source_package")
                required = value.get("required") is not False
            else:
                component_id = str(value)
                path_value = (
                    value
                    if isinstance(value, str) and ("/" in value or "." in value)
                    else None
                )
                role = None
                source_package = None
                required = True
            resolved: Path | None = None
            if isinstance(path_value, str) and path_value:
                candidate = Path(path_value).expanduser()
                if not candidate.is_absolute():
                    source_root = (
                        Path(str(source_package)).expanduser()
                        if source_package
                        else owner_path
                    )
                    candidate = source_root / candidate
                    if not candidate.exists() and not source_package:
                        candidate = root / path_value
                resolved = candidate
            exists = resolved.exists() if resolved else None
            row = {
                "kind": component_kind.rstrip("s"),
                "id": component_id,
                "role": role,
                "path": _rel(root, resolved) if resolved else None,
                "exists": exists,
                "required": required,
            }
            rows.append(row)
            if exists is False and required:
                _diagnostic(
                    diagnostics,
                    severity="warning",
                    code="dependency_missing",
                    source="program_components",
                    message=f"component path is missing: {component_id}",
                    resource_id=resource_id,
                    path=row["path"],
                )
    return rows


def _evidence_files(root: Path, owner: Path) -> list[dict[str, Any]]:
    candidates: list[Path] = []
    for directory in (owner / "runs", owner / "logs"):
        if directory.is_dir():
            candidates.extend(
                path
                for path in directory.rglob("*")
                if path.is_file() and not path.is_symlink()
            )
    newest = sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)[
        :MAX_EVIDENCE_FILES
    ]
    return [
        {
            "evidence_id": f"file:{_rel(root, path)}",
            "path": _rel(root, path),
            "observed_at": _iso(datetime.fromtimestamp(path.stat().st_mtime, UTC)),
            "source": "filesystem_receipt",
        }
        for path in newest
    ]


def _program_dirs(root: Path) -> tuple[list[Path], list[tuple[str, Path]]]:
    definitions_root = shared_factory_path(root, "00-programs")
    definitions = (
        sorted(
            path
            for path in definitions_root.iterdir()
            if path.is_dir() and (path / "program.md").is_file()
        )
        if definitions_root.is_dir()
        else []
    )
    instances: list[tuple[str, Path]] = []
    for domain in installed_domain_names(root):
        collection = root / domain / "00-programs"
        if not collection.is_dir():
            continue
        instances.extend(
            (domain, path)
            for path in sorted(collection.iterdir())
            if path.is_dir() and (path / "program.md").is_file()
        )
    return definitions, instances


def _program_overlay(
    root: Path, path: Path, diagnostics: list[dict[str, Any]], *, source: str
) -> dict[str, Any]:
    return _load_structured(
        root, path / ".agentic-resource.yml", diagnostics, source=source
    )


def _program_config_layers(
    root: Path,
    definition: Path | None,
    instance: Path | None,
    definition_overlay: dict[str, Any],
    instance_overlay: dict[str, Any],
    diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    layers: list[dict[str, Any]] = []
    layers.append(
        {
            "name": "definition",
            "source_path": _rel(root, definition / ".agentic-resource.yml")
            if definition
            else None,
            "fields": definition_overlay,
        }
    )
    config_fields: dict[str, Any] = {}
    config_paths: list[str] = []
    for owner in (definition, instance):
        if not owner:
            continue
        paths = [owner / "config.toml"]
        if (owner / "config").is_dir():
            paths.extend(sorted((owner / "config").glob("*.yml")))
            paths.extend(sorted((owner / "config").glob("*.yaml")))
            paths.extend(sorted((owner / "config").glob("*.toml")))
            paths.extend(sorted((owner / "config").glob("*.json")))
        for path in paths:
            loaded = _load_structured(root, path, diagnostics, source="program_config")
            if loaded:
                config_fields.update(loaded)
                config_paths.append(_rel(root, path))
    layers.append(
        {
            "name": "config",
            "source_path": ",".join(config_paths) or None,
            "fields": config_fields,
        }
    )
    layers.append(
        {
            "name": "instance_overlay",
            "source_path": _rel(root, instance / ".agentic-resource.yml")
            if instance
            else None,
            "fields": instance_overlay,
        }
    )
    layers.append(
        {
            "name": "runtime",
            "status": "unknown",
            "fields": {},
            "reason": "no source-backed runtime configuration observation",
        }
    )
    return _config_projection(layers)


def _program_resources(
    root: Path, diagnostics: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    definitions, instances = _program_dirs(root)
    definition_records: dict[str, dict[str, Any]] = {}
    for path in definitions:
        overlay = _program_overlay(
            root, path, diagnostics, source="program_definition_overlay"
        )
        definition_id = str(overlay.get("id") or path.name)
        metadata = _markdown_metadata(path / "program.md", path.name)
        components = _load_structured(
            root, path / "components.yml", diagnostics, source="program_components"
        )
        resource_id = f"program_definition:{definition_id}"
        definition_records[definition_id] = {
            "kind": "program",
            "resource_type": "definition",
            "id": resource_id,
            "definition": {
                "definition_id": definition_id,
                "name": path.name,
                "display_name": overlay.get("display_name") or metadata["display_name"],
                "summary": overlay.get("summary") or metadata["summary"],
                "status": overlay.get("status") or metadata["status"],
                "version": overlay.get("version") or components.get("schema_version"),
                "path": _rel(root, path),
                "prompt_paths": [
                    _rel(root, prompt)
                    for prompt in sorted((path / "prompts").glob("*.md"))
                ]
                if (path / "prompts").is_dir()
                else [],
            },
            "instance": None,
            "instances": [],
            "icon": _icon(definition_id or path.name, overlay, components),
            "configuration": _program_config_layers(
                root, path, None, overlay, {}, diagnostics
            ),
            "components": _component_projection(
                root, path, resource_id, components, diagnostics
            ),
            "recent_evidence": _evidence_files(root, path),
            "health": _health_projection(
                "unobserved",
                evidence_basis="no_runtime_observation",
                summary="This runnable definition has no durable runtime observation.",
            ),
            "diagnostics": [],
        }

    resources = list(definition_records.values())
    for domain, path in instances:
        overlay = _program_overlay(
            root, path, diagnostics, source="program_instance_overlay"
        )
        standalone = (
            overlay.get("standalone") is True
            or overlay.get("definition_required") is False
        )
        declared_definition_id = overlay.get("definition_id")
        definition_id = (
            str(declared_definition_id)
            if declared_definition_id
            else None
            if standalone
            else path.name
        )
        metadata = _markdown_metadata(path / "program.md", path.name)
        components = _load_structured(
            root, path / "components.yml", diagnostics, source="program_components"
        )
        instance_id = f"program_instance:{domain}:{path.name}"
        definition = definition_records.get(definition_id) if definition_id else None
        instance = {
            "instance_id": instance_id,
            "definition_id": definition_id,
            "name": path.name,
            "display_name": overlay.get("display_name") or metadata["display_name"],
            "summary": overlay.get("summary") or metadata["summary"],
            "domain": domain,
            "project": overlay.get("project"),
            "status": overlay.get("status") or metadata["status"],
            "path": _rel(root, path),
            "definition_join": (
                "exact_definition_id"
                if definition
                else "standalone_instance"
                if standalone
                else "unmatched_definition_id"
            ),
        }
        config = _program_config_layers(
            root,
            Path(root / definition["definition"]["path"]) if definition else None,
            path,
            _program_overlay(
                root,
                root / definition["definition"]["path"],
                diagnostics,
                source="program_definition_overlay",
            )
            if definition
            else {},
            overlay,
            diagnostics,
        )
        recent = _evidence_files(root, path)
        projected = {
            "kind": "program",
            "resource_type": "instance",
            "id": instance_id,
            "definition": definition["definition"] if definition else None,
            "instance": instance,
            "instances": [],
            "icon": _icon(definition_id or path.name, overlay, components),
            "configuration": config,
            "components": _component_projection(
                root, path, instance_id, components, diagnostics
            ),
            "recent_evidence": recent,
            "health": _health_projection(
                "unobserved",
                evidence_basis=(
                    "filesystem_receipts_only" if recent else "no_runtime_observation"
                ),
                summary=(
                    "Filesystem receipts exist, but they do not prove current process or host liveness."
                    if recent
                    else "This runnable instance has no durable runtime observation."
                ),
                observed_at=recent[0]["observed_at"] if recent else None,
            ),
            "orphan_disposition": (
                {
                    "intentional": True,
                    "reason": str(
                        overlay.get("standalone_reason")
                        or "declared standalone instance program"
                    ),
                }
                if standalone
                else None
            ),
            "diagnostics": [],
        }
        if definition:
            definition["instances"].append(instance)
        elif not standalone:
            message = (
                f"definition_id {definition_id!r} has no installed Program definition"
            )
            projected["diagnostics"].append(
                {
                    "severity": "warning",
                    "code": "program_definition_unmatched",
                    "source": "program_instance_overlay"
                    if overlay
                    else "implicit_legacy_identity",
                    "message": message,
                    "resource_id": instance_id,
                    "path": _rel(root, path),
                    "repair_kind": "declare_program_relationship",
                    "guidance": DIAGNOSTIC_REPAIRS["program_definition_unmatched"][1],
                }
            )
            _diagnostic(
                diagnostics,
                severity="warning",
                code="program_definition_unmatched",
                source="program_instance_overlay"
                if overlay
                else "implicit_legacy_identity",
                message=message,
                resource_id=instance_id,
                path=_rel(root, path),
            )
        resources.append(projected)
    for resource in resources:
        resource["routing"] = _routing_projection(resource["configuration"])
    return sorted(resources, key=lambda row: row["id"])


def _automation_dirs(root: Path) -> list[tuple[str, str, Path]]:
    rows: list[tuple[str, str, Path]] = []
    domain_names = installed_domain_names(root)
    if (root / "harness" / "shared_factory").is_dir():
        domain_names.append("shared_factory")
    for domain in sorted(set(domain_names)):
        domain_root = (
            shared_factory_path(root) if domain == "shared_factory" else root / domain
        )
        collection = domain_root / "04-automations"
        if not collection.is_dir():
            continue
        for lane in sorted(path for path in collection.iterdir() if path.is_dir()):
            rows.extend(
                (domain, lane.name, path)
                for path in sorted(lane.iterdir())
                if path.is_dir() and (path / "automation.md").is_file()
            )
    return rows


def _explicit_automation_identity(root: Path, schedule: dict[str, Any]) -> str | None:
    for field in ("automation_id", "definition_id", "automation_ref"):
        if isinstance(schedule.get(field), str) and schedule[field].strip():
            return schedule[field].strip()
    text = " ".join(
        str(schedule.get(field) or "") for field in ("cwd", "work_dir", "command")
    )
    match = re.search(
        r"(?:^|[ /])(?P<domain>[a-z0-9_]+)/04-automations/(?P<lane>[a-z0-9_]+)/(?P<id>[a-z0-9_]+)(?:/|\b)",
        text,
    )
    if match:
        return f"{match.group('domain')}:{match.group('lane')}:{match.group('id')}"
    root_text = re.escape(str(root))
    match = re.search(
        rf"{root_text}/(?P<domain>[a-z0-9_]+)/04-automations/(?P<lane>[a-z0-9_]+)/(?P<id>[a-z0-9_]+)(?:/|\b)",
        text,
    )
    if match:
        return f"{match.group('domain')}:{match.group('lane')}:{match.group('id')}"
    return None


def _automation_config(
    root: Path,
    domain: str,
    lane: str,
    path: Path,
    overlay: dict[str, Any],
    schedules: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    markdown = _markdown_metadata(path / "automation.md", path.name)
    layers: list[dict[str, Any]] = [
        {
            "name": "definition",
            "source_path": _rel(root, path / "automation.md"),
            "fields": markdown.get("raw_fields") or {},
        }
    ]
    config_fields: dict[str, Any] = {}
    config_paths: list[str] = []
    domain_root = (
        shared_factory_path(root) if domain == "shared_factory" else root / domain
    )
    shared = domain_root / "04-automations" / lane / "_shared"
    candidates: list[Path] = []
    for owner in (shared, path):
        if owner.is_dir():
            candidates.extend(sorted(owner.glob("*.yml")))
            candidates.extend(sorted(owner.glob("*.yaml")))
            candidates.extend(sorted(owner.glob("*.json")))
            candidates.extend(sorted(owner.glob("*.toml")))
            if (owner / "config").is_dir():
                candidates.extend(sorted((owner / "config").glob("*.yml")))
                candidates.extend(sorted((owner / "config").glob("*.yaml")))
                candidates.extend(sorted((owner / "config").glob("*.json")))
                candidates.extend(sorted((owner / "config").glob("*.toml")))
    for candidate in candidates:
        loaded = _load_structured(
            root, candidate, diagnostics, source="automation_config"
        )
        if loaded:
            config_fields.update(loaded)
            config_paths.append(_rel(root, candidate))
    layers.append(
        {
            "name": "config",
            "source_path": ",".join(config_paths) or None,
            "fields": config_fields,
        }
    )
    layers.append(
        {
            "name": "instance_overlay",
            "source_path": _rel(root, path / ".agentic-resource.yml"),
            "fields": overlay,
        }
    )
    runtime_fields: dict[str, Any] = {}
    if schedules:
        for field in ("execution_target", "host", "model", "complexity", "enabled"):
            values = [
                schedule.get(field)
                for schedule in schedules
                if schedule.get(field) is not None
            ]
            if values:
                runtime_fields[field] = (
                    values[0] if len(set(map(str, values))) == 1 else values
                )
    layers.append(
        {
            "name": "runtime",
            "status": "present" if runtime_fields else "unknown",
            "source_path": _rel(root, root / RUNTIME_REGISTRY)
            if runtime_fields
            else None,
            "fields": runtime_fields,
            "reason": None if runtime_fields else "no joined runtime schedule evidence",
        }
    )
    return _config_projection(layers)


def _run_sort_value(item: dict[str, Any]) -> datetime:
    for field in ("finished_at", "updated_at", "started_at", "created_at", "due_at"):
        if parsed := _parse_time(item.get(field)):
            return parsed
    return datetime.min.replace(tzinfo=UTC)


def _health(
    schedules: list[dict[str, Any]], runs: list[dict[str, Any]], now: datetime
) -> dict[str, Any]:
    enabled = [item for item in schedules if item.get("enabled") is not False]
    latest = max(runs, key=_run_sort_value) if runs else None
    if schedules and not enabled:
        return _health_projection(
            "disabled",
            evidence_basis="runtime_schedule",
            summary="All joined schedules are explicitly disabled.",
        )
    if not latest:
        return _health_projection(
            "unobserved",
            evidence_basis="no_run_receipt",
            summary="No joined queue or run receipt is available.",
        )
    status = str(latest.get("status") or "unobserved").lower()
    observed = _run_sort_value(latest)
    age = max(0, int((now - observed).total_seconds()))
    if status in {"failed", "blocked"}:
        projected = "unhealthy"
    elif age > STALE_AFTER_SECONDS:
        projected = "degraded"
    elif status in {"done", "skipped", "running", "queued"}:
        projected = "healthy"
    else:
        projected = "degraded"
    return _health_projection(
        projected,
        evidence_basis="run_queue_receipt",
        summary="Derived from durable queue evidence; process and host liveness were not observed.",
        observed_at=_iso(observed),
        age_seconds=age,
        last_outcome=status,
    )


def _qualification(
    root: Path,
    domain: str,
    lane: str,
    automation_id: str,
    resource_id: str,
    overlay: dict[str, Any],
    path: Path,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    try:
        checked = check_automation(root, domain, lane, automation_id)
        findings.extend(
            {
                "finding_type": "qualification",
                "source": "automation_check",
                "severity": item.get("severity") or "observation",
                "message": item.get("message") or "",
                "path": _rel(root, Path(str(item.get("path") or path))),
            }
            for item in checked.get("findings") or []
            if isinstance(item, dict)
        )
    except (OSError, ValueError) as exc:
        findings.append(
            {
                "finding_type": "qualification",
                "source": "automation_check",
                "severity": "blocker",
                "message": str(exc),
                "path": _rel(root, path),
            }
        )
    harness = str(overlay.get("harness") or "agentic_os")
    allowed = harness in {"agentic_os", "codex", "claude"}
    missing: list[str] = []
    if harness == "codex" and not (path / "config.toml").is_file():
        missing.append("config.toml")
    if harness == "claude" and not (path / "CLAUDE.md").is_file():
        missing.append("CLAUDE.md")
    if not (root / AUTHORING_RULES).is_file():
        missing.append(str(AUTHORING_RULES))
    if missing:
        allowed = False
    findings.append(
        {
            "finding_type": "placement",
            "source": "os_authoring_rules",
            "severity": "observation" if allowed else "blocker",
            "decision": "allowed" if allowed else "denied",
            "harness": harness,
            "message": (
                "canonical placement and harness adapter requirements are present"
                if allowed
                else f"placement denied; unsupported harness or missing: {', '.join(missing) or harness}"
            ),
            "policy_path": str(AUTHORING_RULES),
            "resource_id": resource_id,
        }
    )
    return findings


def _automation_resources(
    root: Path, diagnostics: list[dict[str, Any]], now: datetime
) -> list[dict[str, Any]]:
    registry = _load_structured(
        root, root / RUNTIME_REGISTRY, diagnostics, source="runtime_registry"
    )
    tracking = _load_structured(
        root, root / AUTOMATION_TRACKING, diagnostics, source="automation_tracking"
    )
    schedules = _items(registry.get("schedules"))
    runs = runtime_queue_items(root)
    run_queue_source = (
        str(state_db.default_db_path(root).relative_to(root))
        if effective_queue_mode(root) == "execution_fabric"
        else str(RUN_QUEUE)
    )
    tracking_rows = (
        tracking.get("automations")
        if isinstance(tracking.get("automations"), dict)
        else {}
    )
    excluded_tracking_rows = (
        tracking.get("excluded_automations")
        if isinstance(tracking.get("excluded_automations"), dict)
        else {}
    )

    schedules_by_identity: dict[str, list[dict[str, Any]]] = {}
    unmatched_schedules: list[dict[str, Any]] = []
    for schedule in schedules:
        identity = _explicit_automation_identity(root, schedule)
        if identity:
            schedules_by_identity.setdefault(identity, []).append(schedule)
        else:
            unmatched_schedules.append(schedule)

    resources: list[dict[str, Any]] = []
    known_identities: set[str] = set()
    for domain, lane, path in _automation_dirs(root):
        identity = f"{domain}:{lane}:{path.name}"
        known_identities.add(identity)
        resource_id = f"automation_definition:{identity}"
        overlay = _load_structured(
            root,
            path / ".agentic-resource.yml",
            diagnostics,
            source="automation_overlay",
        )
        metadata = _markdown_metadata(path / "automation.md", path.name)
        joined_schedules = schedules_by_identity.get(identity, [])
        schedule_ids = {
            str(item.get("id")) for item in joined_schedules if item.get("id")
        }
        joined_runs = [
            item for item in runs if str(item.get("ref") or "") in schedule_ids
        ]
        joined_runs.sort(key=_run_sort_value, reverse=True)
        next_times = [
            parsed
            for item in joined_schedules
            if (parsed := _parse_time(item.get("next_due_at"))) is not None
        ]
        last = joined_runs[0] if joined_runs else None
        projected_health = (
            _health_projection(
                "disabled",
                evidence_basis="automation_definition",
                summary="The automation definition is explicitly disabled.",
            )
            if overlay.get("enabled") is False
            else _health(joined_schedules, joined_runs, now)
        )
        tracking_match = None
        expected_path = _rel(root, path)
        for key, value in tracking_rows.items():
            if not isinstance(value, dict):
                continue
            cwd = str(value.get("cwd") or "").rstrip("/")
            if cwd in {str(path), expected_path}:
                tracking_match = {"tracking_id": key, **value}
                break
        prompt_paths = [
            _rel(root, candidate)
            for candidate in sorted(path.glob("*prompt*.md"))
            if candidate.is_file()
        ]
        resources.append(
            {
                "kind": "automation",
                "resource_type": "definition",
                "id": resource_id,
                "definition": {
                    "definition_id": resource_id,
                    "name": path.name,
                    "display_name": overlay.get("display_name")
                    or metadata["display_name"],
                    "summary": overlay.get("summary") or metadata["summary"],
                    "domain": domain,
                    "lane": lane,
                    "status": overlay.get("status") or metadata["status"],
                    "level": overlay.get("level") or metadata.get("level"),
                    "path": expected_path,
                    "prompt_paths": prompt_paths,
                },
                "instances": [
                    {
                        "instance_id": f"automation_instance:{identity}:filesystem",
                        "definition_id": resource_id,
                        "source": "installed_filesystem",
                        "path": expected_path,
                        "enabled": overlay.get("enabled", True),
                    }
                ],
                "schedules": [
                    {
                        "schedule_id": item.get("id"),
                        "definition_id": resource_id,
                        "enabled": item.get("enabled", False),
                        "cadence": item.get("cadence"),
                        "timezone": item.get("timezone"),
                        "next_due_at": item.get("next_due_at"),
                        "last_queued_at": item.get("last_queued_at"),
                        "execution_target": item.get("execution_target"),
                        "host": item.get("host"),
                        "source_path": str(RUNTIME_REGISTRY),
                    }
                    for item in joined_schedules
                ],
                "runs": [
                    {
                        "run_id": item.get("id"),
                        "schedule_id": item.get("ref"),
                        "status": item.get("status"),
                        "created_at": item.get("created_at"),
                        "started_at": item.get("started_at"),
                        "finished_at": item.get("finished_at"),
                        "updated_at": item.get("updated_at"),
                        "log": item.get("log") or item.get("dispatch_log"),
                        "error": item.get("error") or item.get("blocked_reason"),
                        "source_path": run_queue_source,
                    }
                    for item in joined_runs[:20]
                ],
                "health": projected_health,
                "last_run_at": _iso(_run_sort_value(last)) if last else None,
                "next_run_at": _iso(min(next_times)) if next_times else None,
                "tracking": tracking_match,
                "icon": _icon(path.name, overlay, tracking_match or {}),
                "configuration": _automation_config(
                    root, domain, lane, path, overlay, joined_schedules, diagnostics
                ),
                "qualification_findings": _qualification(
                    root, domain, lane, path.name, resource_id, overlay, path
                ),
                "recent_evidence": _evidence_files(root, path),
                "diagnostics": [],
            }
        )

    matched_tracking_ids = {
        str(resource.get("tracking", {}).get("tracking_id"))
        for resource in resources
        if isinstance(resource.get("tracking"), dict)
    }
    for tracking_id, tracked in sorted(
        {**excluded_tracking_rows, **tracking_rows}.items()
    ):
        if tracking_id in matched_tracking_ids or not isinstance(tracked, dict):
            continue
        tracked_cwd = str(tracked.get("cwd") or "").strip()
        tracked_path = Path(tracked_cwd).expanduser() if tracked_cwd else None
        if tracked_path and not tracked_path.is_absolute():
            tracked_path = root / tracked_path
        if tracked_path and (tracked_path / "automation.md").is_file():
            # Excluded tracking rows may intentionally alias an installed
            # definition already represented above. Do not duplicate it.
            continue
        schedule_text = str(tracked.get("schedule") or "")
        referenced_schedule_ids = {
            schedule_id
            for schedule_id in re.findall(r"[a-z0-9][a-z0-9_-]+", schedule_text)
            if any(str(item.get("id")) == schedule_id for item in schedules)
        }
        joined_schedules = [
            item for item in schedules if str(item.get("id")) in referenced_schedule_ids
        ]
        joined_runs = [
            item for item in runs if str(item.get("ref")) in referenced_schedule_ids
        ]
        joined_runs.sort(key=_run_sort_value, reverse=True)
        resource_id = f"automation_instance:tracking:{tracking_id}"
        intentional_orphan = (
            tracked.get("intentional_orphan") is True
            or tracked.get("definition_required") is False
        )
        orphan_reason = str(
            tracked.get("orphan_reason")
            or tracked.get("reason")
            or "tracking-only projection declared outside the automation definition tree"
        )
        message = "tracking instance has no exact installed automation definition path"
        if not intentional_orphan:
            _diagnostic(
                diagnostics,
                severity="warning",
                code="automation_definition_unmatched",
                source="automation_tracking",
                message=message,
                resource_id=resource_id,
                path=str(AUTOMATION_TRACKING),
            )
        tracked_status = str(tracked.get("status") or "").upper()
        projected_health = (
            _health_projection(
                "disabled",
                evidence_basis="automation_tracking",
                summary="The tracking entry is explicitly paused or disabled.",
            )
            if tracked_status in {"PAUSED", "DISABLED"}
            else _health(joined_schedules, joined_runs, now)
        )
        resources.append(
            {
                "kind": "automation",
                "resource_type": "tracking_instance",
                "id": resource_id,
                "definition": None,
                "instances": [
                    {
                        "instance_id": resource_id,
                        "definition_id": None,
                        "source": "automation_tracking",
                        "path": tracked.get("cwd"),
                        "enabled": tracked_status not in {"PAUSED", "DISABLED"},
                    }
                ],
                "schedules": [
                    {
                        "schedule_id": item.get("id"),
                        "definition_id": None,
                        "enabled": item.get("enabled", False),
                        "cadence": item.get("cadence"),
                        "timezone": item.get("timezone"),
                        "next_due_at": item.get("next_due_at"),
                        "last_queued_at": item.get("last_queued_at"),
                        "execution_target": item.get("execution_target"),
                        "host": item.get("host"),
                        "source_path": str(RUNTIME_REGISTRY),
                    }
                    for item in joined_schedules
                ],
                "runs": [
                    {
                        "run_id": item.get("id"),
                        "schedule_id": item.get("ref"),
                        "status": item.get("status"),
                        "created_at": item.get("created_at"),
                        "started_at": item.get("started_at"),
                        "finished_at": item.get("finished_at"),
                        "updated_at": item.get("updated_at"),
                        "log": item.get("log") or item.get("dispatch_log"),
                        "error": item.get("error") or item.get("blocked_reason"),
                        "source_path": run_queue_source,
                    }
                    for item in joined_runs[:20]
                ],
                "health": projected_health,
                "last_run_at": _iso(_run_sort_value(joined_runs[0]))
                if joined_runs
                else None,
                "next_run_at": min(
                    (
                        str(item.get("next_due_at"))
                        for item in joined_schedules
                        if item.get("next_due_at")
                    ),
                    default=None,
                ),
                "tracking": {"tracking_id": tracking_id, **tracked},
                "icon": _icon(tracking_id, tracked),
                "configuration": _config_projection(
                    [
                        {"name": "definition", "status": "absent", "fields": {}},
                        {"name": "config", "status": "absent", "fields": {}},
                        {"name": "instance_overlay", "status": "absent", "fields": {}},
                        {
                            "name": "runtime",
                            "status": "present",
                            "source_path": str(AUTOMATION_TRACKING),
                            "fields": tracked,
                        },
                    ]
                ),
                "qualification_findings": [
                    {
                        "finding_type": "placement",
                        "source": "os_authoring_rules",
                        "severity": "observation" if intentional_orphan else "blocker",
                        "decision": "allowed" if intentional_orphan else "denied",
                        "message": orphan_reason if intentional_orphan else message,
                        "policy_path": str(AUTHORING_RULES),
                        "resource_id": resource_id,
                    }
                ],
                "orphan_disposition": (
                    {"intentional": True, "reason": orphan_reason}
                    if intentional_orphan
                    else None
                ),
                "recent_evidence": [],
                "diagnostics": (
                    []
                    if intentional_orphan
                    else [
                        {
                            "severity": "warning",
                            "code": "automation_definition_unmatched",
                            "source": "automation_tracking",
                            "message": message,
                            "resource_id": resource_id,
                            "path": str(AUTOMATION_TRACKING),
                            "repair_kind": "declare_automation_relationship",
                            "guidance": DIAGNOSTIC_REPAIRS[
                                "automation_definition_unmatched"
                            ][1],
                        }
                    ]
                ),
            }
        )

    for identity, joined in sorted(schedules_by_identity.items()):
        if identity in known_identities:
            continue
        for item in joined:
            schedule_id = str(item.get("id") or "unknown")
            resource_id = f"automation_schedule:{schedule_id}"
            message = f"schedule references missing automation definition identity {identity!r}"
            _diagnostic(
                diagnostics,
                severity="warning",
                code="automation_definition_unmatched",
                source="runtime_registry",
                message=message,
                resource_id=resource_id,
                path=str(RUNTIME_REGISTRY),
            )
            resources.append(
                {
                    "kind": "automation",
                    "resource_type": "unmatched_schedule",
                    "id": resource_id,
                    "definition": None,
                    "instances": [],
                    "schedules": [{"schedule_id": schedule_id, **item}],
                    "runs": [],
                    "health": _health([item], [], now),
                    "last_run_at": None,
                    "next_run_at": item.get("next_due_at"),
                    "tracking": None,
                    "icon": _icon(schedule_id),
                    "configuration": _config_projection(
                        [
                            {"name": "definition", "status": "absent", "fields": {}},
                            {"name": "config", "status": "absent", "fields": {}},
                            {
                                "name": "instance_overlay",
                                "status": "absent",
                                "fields": {},
                            },
                            {
                                "name": "runtime",
                                "status": "present",
                                "source_path": str(RUNTIME_REGISTRY),
                                "fields": item,
                            },
                        ]
                    ),
                    "qualification_findings": [],
                    "recent_evidence": [],
                    "diagnostics": [
                        {
                            "severity": "warning",
                            "code": "automation_definition_unmatched",
                            "source": "runtime_registry",
                            "message": message,
                            "resource_id": resource_id,
                            "path": str(RUNTIME_REGISTRY),
                            "repair_kind": "declare_automation_relationship",
                            "guidance": DIAGNOSTIC_REPAIRS[
                                "automation_definition_unmatched"
                            ][1],
                        }
                    ],
                }
            )
    for item in unmatched_schedules:
        schedule_id = _stable_schedule_id(item)
        resource_id = f"automation_schedule:{schedule_id}"
        orphan_requested = item.get("intentional_orphan") is True
        orphan_reason = str(item.get("orphan_reason") or "").strip()
        if orphan_requested and orphan_reason:
            continue
        message = (
            "schedule declares intentional_orphan without a non-empty orphan_reason"
            if orphan_requested
            else "schedule has no explicit automation identity or canonical automation path"
        )
        _diagnostic(
            diagnostics,
            severity="warning" if orphan_requested else "info",
            code="automation_schedule_unassociated",
            source="runtime_registry",
            message=message,
            resource_id=resource_id,
            path=str(RUNTIME_REGISTRY),
        )
    for resource in resources:
        resource["routing"] = _routing_projection(resource["configuration"])
    return sorted(resources, key=lambda row: row["id"])


def query_operator_resources(
    root: str | Path,
    kind: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return the stable read-only operator resource envelope."""
    if kind not in {"program", "automation"}:
        raise ValueError("kind must be program or automation")
    os_root = expand_path(root)
    generated = (now or datetime.now(UTC)).astimezone(UTC)
    diagnostics: list[dict[str, Any]] = []
    resources = (
        _program_resources(os_root, diagnostics)
        if kind == "program"
        else _automation_resources(os_root, diagnostics, generated)
    )
    errors = sum(item["severity"] == "error" for item in diagnostics)
    warnings = sum(item["severity"] == "warning" for item in diagnostics)
    return _json_safe(
        {
            "api_version": API_VERSION,
            "generated_at": _iso(generated),
            "root": str(os_root),
            "query": {"kind": kind},
            "resources": resources,
            "diagnostics": diagnostics,
            "summary": {
                "returned": len(resources),
                "errors": errors,
                "warnings": warnings,
                "partial": bool(errors or warnings),
                "remote_probes": 0,
            },
        }
    )


def get_operator_resource(
    root: str | Path,
    kind: str,
    resource_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    envelope = query_operator_resources(root, kind, now=now)
    resource = next(
        (item for item in envelope["resources"] if item["id"] == resource_id), None
    )
    if resource is None:
        raise ValueError(f"operator resource not found: {resource_id}")
    envelope["query"]["id"] = resource_id
    envelope["resources"] = [resource]
    envelope["summary"]["returned"] = 1
    return envelope
