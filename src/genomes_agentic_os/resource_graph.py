"""Bounded, read-only GraphQL projection over local Agentic OS state.

This module is deliberately an API over materialized local state, not an
integration gateway.  Resolvers read only the allowlisted Agentic OS root and
read-only SQLite projections.  Provider authentication, polling, webhooks, and
mutations remain outside this boundary.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Callable, Iterable, Mapping

from graphql import GraphQLError, build_schema, get_operation_ast, graphql_sync, parse, print_schema
from graphql.language import OperationType
import yaml


MAX_QUERY_BYTES = 32_768
MAX_RESULT_LIMIT = 100
DEFAULT_RESULT_LIMIT = 50
MAX_SPEC_SCAN = 5_000
MAX_STATE_DBS = 32
MAX_SPEC_BODY_BYTES = 65_536
MAX_METADATA_BYTES = 262_144

RESOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
JIRA_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,15}-\d+)\b")
GITHUB_PR_RE = re.compile(r"https://github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)", re.IGNORECASE)

SCHEMA_SDL = """
enum ResourceKind { SPEC EVENT }
enum SourceKind { AGENTIC_OS_FILESYSTEM AGENTIC_OS_STATE }
enum FreshnessState { CURRENT UNKNOWN }
enum PrivacyFlag { CONTAINS_SECRET CONTAINS_CUSTOMER_DATA }
enum SpecType { BUG FEATURE CONFIG }

type Scope {
  domain: String!
  project: String!
}

type Provenance {
  sourceId: String!
  sourceKind: SourceKind!
  nativeId: String!
  relativePath: String
}

type Freshness {
  observedAt: String!
  sourceUpdatedAt: String
  state: FreshnessState!
}

type ExternalRef {
  provider: String!
  nativeId: String!
  url: String
}

type ResourceLink {
  kind: String!
  label: String!
  href: String!
}

type Resource {
  id: ID!
  kind: ResourceKind!
  title: String!
  summary: String!
  scope: Scope!
  provenance: Provenance!
  freshness: Freshness!
  externalRefs: [ExternalRef!]!
  links: [ResourceLink!]!
  privacyFlags: [PrivacyFlag!]!
}

type Spec {
  id: ID!
  nativeId: String!
  title: String!
  summary: String!
  status: String!
  disposition: String!
  blockedFrom: String
  type: SpecType!
  body: String!
  resource: Resource!
}

type Query {
  resource(id: ID!): Resource
  resources(
    kind: ResourceKind
    domain: String
    project: String
    limit: Int = 50
  ): [Resource!]!
  spec(id: ID!): Spec
  specs(
    domain: String
    project: String
    status: String
    type: SpecType
    limit: Int = 50
  ): [Spec!]!
}
"""


class ResourceGraphError(RuntimeError):
    """Deterministic, operator-safe resource graph failure."""

    def __init__(self, message: str, *, code: str = "RESOURCE_GRAPH_ERROR") -> None:
        super().__init__(message)
        self.code = code


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _within(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root)
        return True
    except (OSError, ValueError):
        return False


def _relative(root: Path, path: Path) -> str:
    return str(path.resolve(strict=False).relative_to(root))


def _read_bytes(root: Path, path: Path, limit: int) -> bytes:
    if not _within(root, path):
        raise ResourceGraphError("source path escapes the allowlisted Agentic OS root", code="ROOT_BOUNDARY_VIOLATION")
    try:
        with path.open("rb") as handle:
            return handle.read(limit)
    except OSError:
        return b""


def _read_text(root: Path, path: Path, limit: int) -> str:
    return _read_bytes(root, path, limit).decode("utf-8", errors="replace")


def _read_yaml(root: Path, path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(_read_text(root, path, MAX_METADATA_BYTES)) or {}
    except yaml.YAMLError:
        return {}
    return value if isinstance(value, dict) else {}


def _mtime(path: Path) -> str | None:
    try:
        value = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _scope_from_path(root: Path, path: Path) -> tuple[str, str, str]:
    parts = path.resolve(strict=False).relative_to(root).parts
    try:
        project_index = parts.index("02-projects")
        work_index = parts.index("work-items")
    except ValueError:
        return "", "", path.parent.name
    domain = parts[project_index - 1] if project_index else ""
    project = parts[project_index + 1] if len(parts) > project_index + 1 else ""
    native_id = parts[work_index + 2] if len(parts) > work_index + 2 else path.parent.name
    return domain, project, native_id


def _normalize_status(value: object) -> str:
    status = re.sub(r"[-_]+", " ", str(value or "idea").strip().lower())
    aliases = {
        "intake": "idea",
        "proposed": "idea",
        "shaping": "grooming",
        "refinement": "grooming",
        "building": "in_progress",
        "validating": "in_progress",
        "active": "in_progress",
        "inprogress": "in_progress",
        "done": "built",
        "complete": "built",
        "completed": "built",
        "finished": "built",
        "documented": "built",
    }
    return aliases.get(status, status.replace(" ", "_"))


def _normalize_disposition(value: object) -> str:
    normalized = str(value or "active").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {"canceled": "cancelled", "dropped": "cancelled", "won't_do": "wont_do"}
    return aliases.get(normalized, normalized)


def _normalize_spec_type(value: object) -> str:
    normalized = str(value or "feature").strip().lower().replace("_", "-")
    if normalized in {"bug", "defect", "incident"}:
        return "BUG"
    if normalized in {"config", "configuration"}:
        return "CONFIG"
    return "FEATURE"


def _privacy_flags(*values: object) -> list[str]:
    flags: set[str] = set()
    for value in values:
        if isinstance(value, list):
            for item in value:
                normalized = str(item).upper().replace("-", "_").replace(" ", "_")
                if normalized in {"CONTAINS_SECRET", "CONTAINS_CUSTOMER_DATA"}:
                    flags.add(normalized)
        elif isinstance(value, Mapping):
            if value.get("contains_secret"):
                flags.add("CONTAINS_SECRET")
            if value.get("contains_customer_data"):
                flags.add("CONTAINS_CUSTOMER_DATA")
    return sorted(flags)


def _external_refs(metadata: Mapping[str, Any], node: Mapping[str, Any], body: str) -> list[dict[str, str | None]]:
    refs: dict[tuple[str, str], dict[str, str | None]] = {}
    raw_refs: list[object] = []
    for source in (metadata, node):
        value = source.get("external_refs") or source.get("externalRefs")
        if isinstance(value, list):
            raw_refs.extend(value)
    tracking = metadata.get("tracking")
    if isinstance(tracking, Mapping):
        raw_refs.append(tracking)
    for raw in raw_refs:
        if not isinstance(raw, Mapping):
            continue
        provider = str(raw.get("provider") or raw.get("system") or "external").lower()
        native_id = str(raw.get("native_id") or raw.get("nativeId") or raw.get("id") or raw.get("key") or "")
        if native_id:
            refs[(provider, native_id)] = {
                "provider": provider,
                "nativeId": native_id,
                "url": str(raw.get("url")) if raw.get("url") else None,
            }
    combined = "\n".join((body, json.dumps(metadata, sort_keys=True, default=str)))
    for key in JIRA_RE.findall(combined):
        refs.setdefault(("jira", key), {"provider": "jira", "nativeId": key, "url": None})
    for owner, repo, number in GITHUB_PR_RE.findall(combined):
        url = f"https://github.com/{owner}/{repo}/pull/{number}"
        native_id = f"{owner}/{repo}#{number}"
        refs[("github", native_id)] = {"provider": "github", "nativeId": native_id, "url": url}
    return [refs[key] for key in sorted(refs)]


def _validate_id(resource_id: str) -> None:
    if (
        not RESOURCE_ID_RE.fullmatch(resource_id)
        or ".." in resource_id.split("/")
        or "\\" in resource_id
        or "\x00" in resource_id
    ):
        raise ResourceGraphError("invalid resource id", code="INVALID_RESOURCE_ID")


def _validate_limit(limit: int | None) -> int:
    value = DEFAULT_RESULT_LIMIT if limit is None else limit
    if value < 1 or value > MAX_RESULT_LIMIT:
        raise ResourceGraphError(
            f"limit must be between 1 and {MAX_RESULT_LIMIT}",
            code="LIMIT_EXCEEDED",
        )
    return value


class LocalResourceStore:
    """Read-only resource projection constrained to one resolved OS root."""

    def __init__(self, root: str | Path, *, clock: Callable[[], str] = _utc_now) -> None:
        resolved = Path(root).expanduser().resolve(strict=False)
        if not resolved.is_dir():
            raise ResourceGraphError("allowlisted Agentic OS root is not a directory", code="INVALID_ROOT")
        if not (resolved / ".agentic_root").is_file():
            raise ResourceGraphError("allowlisted Agentic OS root marker is missing", code="INVALID_ROOT")
        self.root = resolved
        self._clock = clock

    def _spec_paths(self) -> list[Path]:
        patterns = (
            "*/02-projects/*/work-items/*/*/work.yml",
            "harness/*/02-projects/*/work-items/*/*/work.yml",
        )
        unique: dict[str, Path] = {}
        for pattern in patterns:
            for path in self.root.glob(pattern):
                if _within(self.root, path):
                    unique[str(path.resolve(strict=False))] = path
        return sorted(unique.values(), key=lambda path: _relative(self.root, path))[:MAX_SPEC_SCAN]

    def _spec_from_path(self, metadata_path: Path) -> dict[str, Any]:
        metadata = _read_yaml(self.root, metadata_path)
        node = metadata.get("spec")
        if not isinstance(node, Mapping):
            node = metadata.get("work")
        if not isinstance(node, Mapping):
            node = metadata
        scope_node = metadata.get("scope") if isinstance(metadata.get("scope"), Mapping) else {}
        path_domain, path_project, path_id = _scope_from_path(self.root, metadata_path)
        native_id = str(node.get("id") or metadata.get("id") or path_id)
        domain = str(scope_node.get("domain") or node.get("domain") or metadata.get("domain") or path_domain)
        project = str(scope_node.get("project") or node.get("project") or metadata.get("project") or path_project)
        title = str(node.get("title") or metadata.get("title") or native_id.replace("_", " ").title())
        summary = str(node.get("summary") or metadata.get("summary") or "")
        status = _normalize_status(node.get("status") or metadata.get("status") or metadata.get("state"))
        disposition = _normalize_disposition(node.get("disposition") or metadata.get("disposition"))
        blocked_from = node.get("blocked_from") or metadata.get("blocked_from")
        spec_type = _normalize_spec_type(node.get("type") or metadata.get("type") or node.get("kind"))
        body_path = metadata_path.parent / "SPEC.md"
        body = _read_text(self.root, body_path, MAX_SPEC_BODY_BYTES)
        resource_id = f"spec:{domain}:{project}:{native_id}"
        source_updated = str(node.get("updated_at") or metadata.get("updated_at") or _mtime(metadata_path) or "") or None
        relative_path = _relative(self.root, metadata_path)
        external_refs = _external_refs(metadata, node, body)
        links = [{"kind": "filesystem", "label": "Spec packet", "href": relative_path}]
        resource = {
            "id": resource_id,
            "kind": "SPEC",
            "title": title,
            "summary": summary,
            "scope": {"domain": domain, "project": project},
            "provenance": {
                "sourceId": "agentic-os-filesystem",
                "sourceKind": "AGENTIC_OS_FILESYSTEM",
                "nativeId": native_id,
                "relativePath": relative_path,
            },
            "freshness": {
                "observedAt": self._clock(),
                "sourceUpdatedAt": source_updated,
                "state": "CURRENT" if source_updated else "UNKNOWN",
            },
            "externalRefs": external_refs,
            "links": links,
            "privacyFlags": _privacy_flags(metadata.get("privacy_flags"), metadata.get("privacy"), node.get("privacy")),
        }
        return {
            "id": resource_id,
            "nativeId": native_id,
            "title": title,
            "summary": summary,
            "status": status,
            "disposition": disposition,
            "blockedFrom": _normalize_status(blocked_from) if blocked_from else None,
            "type": spec_type,
            "body": body,
            "resource": resource,
        }

    def specs(
        self,
        *,
        domain: str | None = None,
        project: str | None = None,
        status: str | None = None,
        spec_type: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        max_results = _validate_limit(limit)
        normalized_status = _normalize_status(status) if status else None
        normalized_type = _normalize_spec_type(spec_type) if spec_type else None
        result: list[dict[str, Any]] = []
        for path in self._spec_paths():
            spec = self._spec_from_path(path)
            scope = spec["resource"]["scope"]
            if domain is not None and scope["domain"] != domain:
                continue
            if project is not None and scope["project"] != project:
                continue
            if normalized_status is not None and spec["status"] != normalized_status:
                continue
            if normalized_type is not None and spec["type"] != normalized_type:
                continue
            result.append(spec)
            if len(result) >= max_results:
                break
        return result

    def spec(self, resource_id: str) -> dict[str, Any] | None:
        _validate_id(resource_id)
        for path in self._spec_paths():
            spec = self._spec_from_path(path)
            if spec["id"] == resource_id:
                return spec
        return None

    def _state_db_paths(self) -> list[Path]:
        paths: set[Path] = set()
        for pattern in ("*/00-control-plane/state.db", "harness/*/00-control-plane/state.db"):
            for path in self.root.glob(pattern):
                if path.is_file() and _within(self.root, path):
                    paths.add(path)
        return sorted(paths, key=lambda path: _relative(self.root, path))[:MAX_STATE_DBS]

    def _event_resources(self) -> Iterable[dict[str, Any]]:
        emitted = 0
        for db_path in self._state_db_paths():
            try:
                connection = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    """
                    SELECT id, type, observed_at, source_ref, summary, payload_json,
                           contains_secret, contains_customer_data, run_log_link,
                           source_url, domain
                      FROM events
                     ORDER BY id
                     LIMIT ?
                    """,
                    (MAX_SPEC_SCAN,),
                ).fetchall()
            except sqlite3.Error:
                continue
            finally:
                if "connection" in locals():
                    connection.close()
                    del connection
            for row in rows:
                if emitted >= MAX_SPEC_SCAN:
                    return
                emitted += 1
                try:
                    payload = json.loads(row["payload_json"] or "{}")
                except (TypeError, json.JSONDecodeError):
                    payload = {}
                project = ""
                if isinstance(payload, Mapping):
                    scope = payload.get("scope")
                    if isinstance(scope, Mapping):
                        project = str(scope.get("project") or "")
                    project = str(payload.get("project") or project)
                native_id = str(row["id"])
                external_refs = []
                if row["source_url"]:
                    external_refs.append({"provider": "source", "nativeId": native_id, "url": str(row["source_url"])})
                links = []
                if row["run_log_link"]:
                    links.append({"kind": "run-log", "label": "Run log", "href": str(row["run_log_link"])})
                yield {
                    "id": f"event:{native_id}",
                    "kind": "EVENT",
                    "title": str(row["summary"] or row["type"] or native_id),
                    "summary": str(row["summary"] or ""),
                    "scope": {"domain": str(row["domain"] or ""), "project": project},
                    "provenance": {
                        "sourceId": str(row["source_ref"] or "agentic-os-state"),
                        "sourceKind": "AGENTIC_OS_STATE",
                        "nativeId": native_id,
                        "relativePath": _relative(self.root, db_path),
                    },
                    "freshness": {
                        "observedAt": self._clock(),
                        "sourceUpdatedAt": str(row["observed_at"] or "") or None,
                        "state": "CURRENT" if row["observed_at"] else "UNKNOWN",
                    },
                    "externalRefs": external_refs,
                    "links": links,
                    "privacyFlags": _privacy_flags(
                        {
                            "contains_secret": bool(row["contains_secret"]),
                            "contains_customer_data": bool(row["contains_customer_data"]),
                        }
                    ),
                }

    def resources(
        self,
        *,
        kind: str | None = None,
        domain: str | None = None,
        project: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        max_results = _validate_limit(limit)
        candidates: list[dict[str, Any]] = []
        if kind in (None, "SPEC"):
            candidates.extend(
                spec["resource"]
                for spec in self.specs(domain=domain, project=project, limit=max_results)
            )
        if kind in (None, "EVENT"):
            candidates.extend(self._event_resources())
        candidates.sort(key=lambda item: item["id"])
        result = []
        for resource in candidates:
            scope = resource["scope"]
            if domain is not None and scope["domain"] != domain:
                continue
            if project is not None and scope["project"] != project:
                continue
            result.append(resource)
            if len(result) >= max_results:
                break
        return result

    def resource(self, resource_id: str) -> dict[str, Any] | None:
        _validate_id(resource_id)
        if resource_id.startswith("spec:"):
            spec = self.spec(resource_id)
            return spec["resource"] if spec else None
        resources: Iterable[dict[str, Any]]
        if resource_id.startswith("event:"):
            resources = self._event_resources()
        else:
            resources = self.resources(limit=MAX_RESULT_LIMIT)
        for resource in resources:
            if resource["id"] == resource_id:
                return resource
        return None


def _as_graphql_error(error: ResourceGraphError) -> GraphQLError:
    return GraphQLError(str(error), extensions={"code": error.code})


class ResourceGraphService:
    """Embeddable GraphQL query service for Command Center and local tools."""

    def __init__(self, root: str | Path, *, clock: Callable[[], str] = _utc_now) -> None:
        self.store = LocalResourceStore(root, clock=clock)
        self.schema = build_schema(SCHEMA_SDL)
        query = self.schema.get_type("Query")
        assert query is not None
        query.fields["resource"].resolve = self._resource
        query.fields["resources"].resolve = self._resources
        query.fields["spec"].resolve = self._spec
        query.fields["specs"].resolve = self._specs

    @staticmethod
    def schema_sdl() -> str:
        return print_schema(build_schema(SCHEMA_SDL))

    def _resource(self, _source: object, _info: object, *, id: str) -> dict[str, Any] | None:
        try:
            return self.store.resource(id)
        except ResourceGraphError as error:
            raise _as_graphql_error(error) from error

    def _resources(
        self,
        _source: object,
        _info: object,
        *,
        kind: str | None = None,
        domain: str | None = None,
        project: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        try:
            return self.store.resources(kind=kind, domain=domain, project=project, limit=limit)
        except ResourceGraphError as error:
            raise _as_graphql_error(error) from error

    def _spec(self, _source: object, _info: object, *, id: str) -> dict[str, Any] | None:
        try:
            return self.store.spec(id)
        except ResourceGraphError as error:
            raise _as_graphql_error(error) from error

    def _specs(
        self,
        _source: object,
        _info: object,
        *,
        domain: str | None = None,
        project: str | None = None,
        status: str | None = None,
        type: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        try:
            return self.store.specs(
                domain=domain,
                project=project,
                status=status,
                spec_type=type,
                limit=limit,
            )
        except ResourceGraphError as error:
            raise _as_graphql_error(error) from error

    def execute(
        self,
        query: str,
        *,
        variables: Mapping[str, Any] | None = None,
        operation_name: str | None = None,
    ) -> dict[str, Any]:
        if len(query.encode("utf-8")) > MAX_QUERY_BYTES:
            return {"data": None, "errors": [{"message": "query exceeds maximum size", "extensions": {"code": "QUERY_TOO_LARGE"}}]}
        try:
            document = parse(query)
            operation = get_operation_ast(document, operation_name)
        except GraphQLError as error:
            return {"data": None, "errors": [_format_error(error)]}
        if operation is not None and operation.operation == OperationType.MUTATION:
            return {"data": None, "errors": [{"message": "mutations are disabled", "extensions": {"code": "MUTATIONS_DISABLED"}}]}
        result = graphql_sync(
            self.schema,
            query,
            variable_values=dict(variables or {}),
            operation_name=operation_name,
        )
        payload: dict[str, Any] = {"data": result.data}
        if result.errors:
            payload["errors"] = [_format_error(error) for error in result.errors]
        return payload


def _format_error(error: GraphQLError) -> dict[str, Any]:
    payload: dict[str, Any] = {"message": error.message}
    if error.locations:
        payload["locations"] = [{"line": item.line, "column": item.column} for item in error.locations]
    if error.path:
        payload["path"] = list(error.path)
    if error.extensions:
        payload["extensions"] = dict(sorted(error.extensions.items()))
    return payload


def execute_resource_query(
    root: str | Path,
    query: str,
    *,
    variables: Mapping[str, Any] | None = None,
    operation_name: str | None = None,
) -> dict[str, Any]:
    """Convenience entry point for callers that do not need a long-lived service."""
    return ResourceGraphService(root).execute(query, variables=variables, operation_name=operation_name)


__all__ = [
    "DEFAULT_RESULT_LIMIT",
    "MAX_QUERY_BYTES",
    "MAX_RESULT_LIMIT",
    "LocalResourceStore",
    "ResourceGraphError",
    "ResourceGraphService",
    "SCHEMA_SDL",
    "execute_resource_query",
]
