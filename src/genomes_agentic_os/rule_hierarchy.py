"""Deterministic, GUI-safe projection of effective Agentic OS rules."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
from typing import Any, Iterable

import yaml

from .context_contracts import PARENT_CONTRACT_FILES, load_context_manifest, resolve_context_contract
from .scaffold import domain_path, expand_path, normalize_domain, validate_name


API_VERSION = "rules/v1"
SCOPE_RANK = {"system": 0, "os": 1, "domain": 2, "project": 3, "workflow": 4, "automation": 4}
SCOPE_PREFIX = {"system": "SYS", "os": "OS", "domain": "DOM", "project": "PRJ", "workflow": "WFL", "automation": "AUT"}
EFFECT_RANK = {"inform": 0, "allow": 10, "prefer": 20, "require": 30, "deny": 40}
ALLOWED_EFFECTS = frozenset(EFFECT_RANK)


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _safe_reference(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.startswith(("https://", "http://")):
        return text
    path = Path(text)
    if path.is_absolute() or text.startswith("~") or ".." in path.parts:
        return None
    return path.as_posix()


def _public_message(root: Path, message: str) -> str:
    """Remove the private root prefix from resolver diagnostics."""

    return message.replace(str(root), ".")


def _sha(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _freshness(path: Path, content: str) -> dict[str, str]:
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    return {"source_sha256": _sha(content), "source_modified_at": modified}


def _one_sentence(markdown: str, fallback: str) -> str:
    paragraph: list[str] = []
    for raw in [*markdown.splitlines(), ""]:
        line = raw.strip()
        if line.startswith(("#", "<!--", "```", "|")):
            continue
        if not line:
            if not paragraph:
                continue
            text = " ".join(paragraph)
            match = re.match(r"(.+?[.!?])(?:\s|$)", text)
            return (match.group(1) if match else text)[:240]
        line = re.sub(r"^[-*+]\s+", "", line)
        line = re.sub(r"^\d+[.)]\s+", "", line)
        line = re.sub(r"[`*_]", "", line).strip()
        if line:
            paragraph.append(line)
    return fallback[:240]


def _heading(markdown: str, fallback: str) -> str:
    for raw in markdown.splitlines():
        if raw.startswith("# "):
            return raw[2:].strip()[:120]
    return fallback.replace("_", " ").replace("-", " ").title()[:120]


def _target_metadata(root: Path, target: Path) -> dict[str, str | None]:
    parts = target.relative_to(root).parts
    domain: str | None = None
    project: str | None = None
    if len(parts) >= 2 and parts[:2] == ("harness", "shared_factory"):
        domain = "shared_factory"
    elif parts and parts[0] != "harness":
        domain = parts[0]
    if "02-projects" in parts:
        index = parts.index("02-projects")
        if len(parts) > index + 1:
            project = parts[index + 1]
    scope, locator = _scope_for_path(root, target)
    return {"domain": domain, "project": project, "scope": scope, "locator": locator}


def _scope_for_path(root: Path, path: Path) -> tuple[str, str]:
    relative = path.resolve().relative_to(root.resolve())
    parts = relative.parts
    if not parts:
        return "system", "root"
    if "04-automations" in parts:
        index = parts.index("04-automations")
        locator = "/".join(parts[index + 1 : index + 3]) or "automation"
        return "automation", locator
    if "03-workflows" in parts:
        index = parts.index("03-workflows")
        locator = "/".join(parts[index + 1 : index + 3]) or "workflow"
        return "workflow", locator
    if "02-projects" in parts:
        index = parts.index("02-projects")
        locator = parts[index + 1] if len(parts) > index + 1 else "projects"
        return "project", locator
    if parts[0] == "harness":
        if len(parts) == 1:
            return "os", "harness"
        if parts[:2] == ("harness", "shared_factory"):
            return "domain", "shared_factory"
        return "os", "harness"
    return "domain", parts[0]


def resolve_rule_target(
    root: str | Path,
    *,
    path: str | Path | None = None,
    domain: str | None = None,
    project: str | None = None,
    lane: str | None = None,
    workflow: str | None = None,
    automation: str | None = None,
) -> tuple[Path, Path]:
    """Resolve an allowlisted OS target without accepting paths outside the root."""

    os_root = expand_path(root)
    if path is not None:
        target = Path(path).expanduser().resolve()
    elif domain:
        target = domain_path(os_root, normalize_domain(domain))
        if project:
            target = target / "02-projects" / validate_name(project, "project")
        elif workflow or automation:
            if not lane:
                raise ValueError("--lane is required with --workflow or --automation")
            lane_name = validate_name(lane, "lane")
            if workflow:
                target = target / "03-workflows" / lane_name / validate_name(workflow, "workflow")
            else:
                target = target / "04-automations" / lane_name / validate_name(str(automation), "automation")
    elif any((project, lane, workflow, automation)):
        raise ValueError("--domain is required with project, lane, workflow, or automation selectors")
    else:
        target = os_root
    try:
        target.relative_to(os_root)
    except ValueError as exc:
        raise ValueError(f"rule target is outside root: {target}") from exc
    if not target.is_dir():
        raise ValueError(f"rule target not found: {target}")
    return os_root, target


def _legacy_sources(root: Path, target: Path) -> list[Path]:
    ancestors: list[Path] = []
    current = target
    while True:
        ancestors.append(current)
        if current == root:
            break
        current = current.parent
    sources: list[Path] = []
    for directory in reversed(ancestors):
        for filename in PARENT_CONTRACT_FILES:
            candidate = directory / filename
            if candidate.is_file():
                sources.append(candidate)
    return sources


def _context_rules(root: Path, target: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    resolved = resolve_context_contract(
        target,
        root=root,
        legacy_sources=_legacy_sources(root, target) if load_context_manifest(target) is None else (),
    )
    sources = [item for item in (*resolved.read_first, *resolved.deferred) if item.exists and item.path.name == "RULES.md"]
    rows: list[dict[str, Any]] = []
    source_refs: list[str] = []
    for source in sources:
        content = source.path.read_text(encoding="utf-8")
        source_ref = _relative(root, source.path)
        source_refs.append(source_ref)
        scope, locator = _scope_for_path(root, source.path.parent)
        stable_slug = re.sub(r"[^a-z0-9]+", "-", source_ref.lower()).strip("-")
        rule_id = f"ruleset:{stable_slug}"
        summary = _one_sentence(content, f"Rules declared by {source_ref}.")
        rows.append(
            {
                "id": rule_id,
                "rule_id": rule_id,
                "key": rule_id,
                "name": _heading(content, f"{scope} rules"),
                "summary": summary,
                "scope": scope,
                "scope_rank": SCOPE_RANK[scope],
                "scope_locator": locator,
                "source_ref": source_ref,
                "source_kind": "context_ruleset",
                "body_markdown": content,
                "references": [],
                "effect": "require",
                "strictness": EFFECT_RANK["require"],
                "local": source.path.parent == target,
                "inherited": source.path.parent != target,
                "validation": {"valid": True, "findings": []},
                **_freshness(source.path, content),
            }
        )
    diagnostics = []
    for item in resolved.diagnostics:
        diagnostic = item.as_dict()
        diagnostic["message"] = _public_message(root, diagnostic["message"])
        if "path" in diagnostic:
            try:
                diagnostic["source_ref"] = _relative(root, Path(diagnostic.pop("path")))
            except ValueError:
                diagnostic.pop("path", None)
        diagnostics.append(diagnostic)
    for duplicate in resolved.skipped_duplicates:
        if Path(duplicate["path"]).name != "RULES.md":
            continue
        try:
            source_ref = _relative(root, Path(duplicate["path"]))
            duplicate_of = _relative(root, Path(duplicate["duplicate_of"]))
        except ValueError:
            continue
        diagnostics.append(
            {
                "severity": "observation",
                "code": "context_duplicate",
                "message": f"Context resolver skipped duplicate RULES source {source_ref}.",
                "source_ref": source_ref,
                "duplicate_of": duplicate_of,
                "source_sha256": duplicate["sha256"],
            }
        )
    return rows, diagnostics, source_refs


def _registry_candidates(root: Path, target: Path) -> list[tuple[str, str, Path]]:
    metadata = _target_metadata(root, target)
    candidates = [("system", "global", root / "harness" / "registries" / "rules.yml")]
    domain = metadata["domain"]
    if domain:
        domain_root = domain_path(root, str(domain))
        candidates.append(("domain", str(domain), domain_root / "00-control-plane" / "resource-registries" / "rules.yml"))
    project = metadata["project"]
    if domain and project:
        candidates.append(
            (
                "project",
                str(project),
                domain_path(root, str(domain)) / "02-projects" / str(project) / "config" / "resource-registries" / "rules.yml",
            )
        )
    return candidates


def _registry_rules(root: Path, target: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    target_scope = str(_target_metadata(root, target)["scope"])
    for default_scope, locator, registry in _registry_candidates(root, target):
        if not registry.exists():
            continue
        source_ref = _relative(root, registry)
        try:
            content = registry.read_text(encoding="utf-8")
            data = yaml.safe_load(content) or {}
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            diagnostics.append(
                {
                    "severity": "warning",
                    "code": "partial_rule_registry",
                    "message": f"Rule registry could not be loaded: {type(exc).__name__}.",
                    "source_ref": source_ref,
                }
            )
            continue
        entries = data.get("rules") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            diagnostics.append(
                {
                    "severity": "warning",
                    "code": "partial_rule_registry",
                    "message": "Rule registry must contain a rules list.",
                    "source_ref": source_ref,
                }
            )
            continue
        freshness = _freshness(registry, content)
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                diagnostics.append(
                    {
                        "severity": "warning",
                        "code": "invalid_rule_entry",
                        "message": f"Rule entry {index} is not a mapping.",
                        "source_ref": source_ref,
                    }
                )
                continue
            raw_id = str(entry.get("id") or "").strip()
            name = str(entry.get("name") or "").strip()
            summary = str(entry.get("summary") or entry.get("description") or "").strip()
            effect = str(entry.get("effect") or "require").strip().lower()
            findings: list[str] = []
            if not raw_id:
                findings.append("id is required")
            if not name:
                findings.append("name is required")
            if not summary:
                findings.append("summary or description is required")
            if effect not in ALLOWED_EFFECTS:
                findings.append(f"unsupported effect: {effect}")
                effect = "require"
            strictness_value = entry.get("strictness", EFFECT_RANK[effect])
            if isinstance(strictness_value, bool) or not isinstance(strictness_value, int) or not 0 <= strictness_value <= 100:
                findings.append("strictness must be an integer from 0 to 100")
                strictness_value = EFFECT_RANK[effect]
            if findings:
                diagnostics.append(
                    {
                        "severity": "warning",
                        "code": "invalid_rule_entry",
                        "message": "; ".join(findings),
                        "rule_id": raw_id or f"entry-{index}",
                        "source_ref": source_ref,
                    }
                )
            if not raw_id:
                continue
            scope = str(entry.get("scope") or default_scope).strip().lower()
            if scope not in SCOPE_RANK or SCOPE_RANK[scope] > SCOPE_RANK[target_scope]:
                scope = default_scope
            qualified_id = f"{scope}:{locator}:{raw_id}"
            raw_references = entry.get("references") or []
            if not isinstance(raw_references, list):
                raw_references = [raw_references]
                findings.append("references must be a list")
            references = [safe for safe in (_safe_reference(value) for value in raw_references) if safe]
            unsafe_count = len(raw_references) - len(references)
            if unsafe_count:
                findings.append(f"ignored {unsafe_count} unsafe reference(s)")
            body = str(entry.get("body_markdown") or summary)
            rows.append(
                {
                    "id": qualified_id,
                    "rule_id": raw_id,
                    "key": str(entry.get("key") or raw_id).strip().lower(),
                    "name": name or raw_id.replace("_", " ").replace("-", " ").title(),
                    "summary": _one_sentence(summary, name or raw_id),
                    "scope": scope,
                    "scope_rank": SCOPE_RANK[scope],
                    "scope_locator": locator,
                    "source_ref": source_ref,
                    "source_kind": "rule_registry",
                    "body_markdown": body,
                    "references": references,
                    "effect": effect,
                    "strictness": strictness_value,
                    "local": scope == target_scope,
                    "inherited": scope != target_scope,
                    "validation": {"valid": not findings, "findings": findings},
                    **freshness,
                }
            )
    return rows, diagnostics


def _resolve_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row["key"]].append(row)
    for key, candidates in sorted(groups.items()):
        ordered = sorted(
            candidates,
            key=lambda item: (-item["strictness"], -EFFECT_RANK[item["effect"]], -item["scope_rank"], item["id"]),
        )
        winner = ordered[0]
        winner["effective"] = True
        winner["shadowed_by"] = None
        winner["resolution_reason"] = "only applicable definition" if len(ordered) == 1 else "strictest applicable definition"
        signatures = {(item["effect"], item["strictness"], item["summary"].casefold(), _sha(item["body_markdown"])) for item in ordered}
        for item in ordered[1:]:
            item["effective"] = False
            item["shadowed_by"] = winner["id"]
            if item["strictness"] < winner["strictness"]:
                reason = "lower strictness"
            elif EFFECT_RANK[item["effect"]] < EFFECT_RANK[winner["effect"]]:
                reason = "less restrictive effect"
            elif item["scope_rank"] < winner["scope_rank"]:
                reason = "broader scope at equal strictness"
            else:
                reason = "stable ID tie-break"
            item["resolution_reason"] = reason
        if len(ordered) > 1:
            code = "duplicate_rule" if len(signatures) == 1 else "rule_conflict"
            diagnostics.append(
                {
                    "severity": "observation" if code == "duplicate_rule" else "warning",
                    "code": code,
                    "message": f"{len(ordered)} applicable definitions share rule key {key!r}; {winner['id']} wins.",
                    "key": key,
                    "winner_id": winner["id"],
                    "definitions": [{"id": item["id"], "source_ref": item["source_ref"]} for item in ordered],
                }
            )
    return diagnostics


def _number(rows: list[dict[str, Any]]) -> None:
    by_scope: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_scope[row["scope"]].append(row)
    for scope in SCOPE_RANK:
        for index, row in enumerate(sorted(by_scope[scope], key=lambda item: item["id"]), start=1):
            row["display_number"] = f"{SCOPE_PREFIX[scope]}-{index:03d}"


def _matches_query(row: dict[str, Any], query: str) -> bool:
    needle = query.casefold()
    values: Iterable[object] = (row["id"], row["rule_id"], row["key"], row["name"], row["summary"], row["source_ref"])
    return any(needle in str(value).casefold() for value in values)


def effective_rules(
    root: str | Path,
    target: str | Path,
    *,
    query: str | None = None,
    scopes: Iterable[str] = (),
    effects: Iterable[str] = (),
    local_only: bool = False,
    conflicts_only: bool = False,
) -> dict[str, Any]:
    """Return a stable projection for rules applicable to *target*."""

    os_root = expand_path(root)
    target_path = Path(target).expanduser().resolve()
    try:
        target_path.relative_to(os_root)
    except ValueError as exc:
        raise ValueError(f"rule target is outside root: {target_path}") from exc
    if not target_path.is_dir():
        raise ValueError(f"rule target not found: {target_path}")

    context_rows, diagnostics, context_source_refs = _context_rules(os_root, target_path)
    registry_rows, registry_diagnostics = _registry_rules(os_root, target_path)
    rows = [*context_rows, *registry_rows]
    diagnostics.extend(registry_diagnostics)
    diagnostics.extend(_resolve_groups(rows))
    _number(rows)
    rows.sort(key=lambda item: (item["scope_rank"], item["display_number"], item["id"]))

    conflict_ids = {
        definition["id"]
        for diagnostic in diagnostics
        if diagnostic.get("code") == "rule_conflict"
        for definition in diagnostic.get("definitions", [])
    }
    requested_scopes = set(scopes)
    requested_effects = set(effects)
    filtered = [
        row
        for row in rows
        if (not query or _matches_query(row, query))
        and (not requested_scopes or row["scope"] in requested_scopes)
        and (not requested_effects or row["effect"] in requested_effects)
        and (not local_only or row["local"])
        and (not conflicts_only or row["id"] in conflict_ids)
    ]
    metadata = _target_metadata(os_root, target_path)
    return {
        "api_version": API_VERSION,
        "target": {
            "ref": _relative(os_root, target_path) or ".",
            "scope": metadata["scope"],
            "domain": metadata["domain"],
            "project": metadata["project"],
        },
        "query": {
            "text": query,
            "scopes": sorted(requested_scopes),
            "effects": sorted(requested_effects),
            "local_only": local_only,
            "conflicts_only": conflicts_only,
        },
        "counts": {
            "applicable": len(rows),
            "returned": len(filtered),
            "effective": sum(bool(row["effective"]) for row in rows),
            "conflicts": sum(diagnostic.get("code") == "rule_conflict" for diagnostic in diagnostics),
            "duplicates": sum(diagnostic.get("code") in {"duplicate_rule", "context_duplicate"} for diagnostic in diagnostics),
            "warnings": sum(diagnostic.get("severity") == "warning" for diagnostic in diagnostics),
        },
        "context_parity": {"rule_source_refs": context_source_refs},
        "rules": filtered,
        "diagnostics": diagnostics,
    }
