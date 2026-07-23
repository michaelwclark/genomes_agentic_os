"""Composable Markdown policy planes for Agentic OS workflows.

The policy plane is deliberately small.  It discovers ordered Markdown files,
parses optional YAML frontmatter, preserves provenance, and produces a stable
fingerprint.  Workflow-specific modules own semantic merging so artifact,
investigation, development, and QA policies can share inheritance without
sharing unsafe assumptions.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml


class PolicyPlaneError(ValueError):
    """Raised when a Markdown policy source is malformed or unsafe."""


@dataclass(frozen=True)
class PolicyLayer:
    """One ordered inheritance layer."""

    scope: str
    root: Path
    rank: int


@dataclass(frozen=True)
class MarkdownPolicyDocument:
    """Parsed Markdown policy with stable source evidence."""

    scope: str
    rank: int
    path: Path
    source_ref: str
    frontmatter: dict[str, Any]
    body: str
    sha256: str

    def as_dict(self, *, include_body: bool = False) -> dict[str, Any]:
        value: dict[str, Any] = {
            "scope": self.scope,
            "rank": self.rank,
            "source_ref": self.source_ref,
            "sha256": self.sha256,
            "frontmatter": self.frontmatter,
        }
        if include_body:
            value["body_markdown"] = self.body
        return value


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise PolicyPlaneError(f"policy source is outside the Agentic OS root: {path}") from exc


def _split_frontmatter(text: str, *, source: Path) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text.strip() + ("\n" if text.strip() else "")
    end = next((index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"), None)
    if end is None:
        raise PolicyPlaneError(f"unterminated YAML frontmatter: {source}")
    try:
        metadata = yaml.safe_load("\n".join(lines[1:end])) or {}
    except yaml.YAMLError as exc:
        raise PolicyPlaneError(f"invalid YAML frontmatter in {source}: {exc}") from exc
    if not isinstance(metadata, dict):
        raise PolicyPlaneError(f"YAML frontmatter must be a mapping: {source}")
    body = "\n".join(lines[end + 1 :]).strip()
    return dict(metadata), body + ("\n" if body else "")


def parse_markdown_policy(
    os_root: str | Path,
    path: str | Path,
    *,
    scope: str,
    rank: int,
) -> MarkdownPolicyDocument:
    """Parse one policy document without leaking absolute paths."""

    root = Path(os_root).expanduser().resolve()
    source = Path(path).expanduser().resolve()
    source_ref = _relative(root, source)
    if not source.is_file():
        raise PolicyPlaneError(f"policy source is not a file: {source_ref}")
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PolicyPlaneError(f"cannot read policy source {source_ref}: {type(exc).__name__}") from exc
    frontmatter, body = _split_frontmatter(text, source=Path(source_ref))
    return MarkdownPolicyDocument(
        scope=scope,
        rank=rank,
        path=source,
        source_ref=source_ref,
        frontmatter=frontmatter,
        body=body,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def markdown_files(
    path: str | Path,
    *,
    recursive: bool = True,
    excluded_subdirectories: Sequence[str | Path] = (),
) -> list[Path]:
    """Return deterministic 1-N Markdown files, excluding explanatory READMEs."""

    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        return []
    iterator = root.rglob("*.md") if recursive else root.glob("*.md")
    excluded_parts = tuple(Path(item).parts for item in excluded_subdirectories)

    def included(item: Path) -> bool:
        relative_parts = item.relative_to(root).parts
        return not any(
            relative_parts[: len(prefix)] == prefix
            for prefix in excluded_parts
            if prefix
        )

    return sorted(
        (
            item
            for item in iterator
            if item.is_file()
            and item.name.casefold() != "readme.md"
            and included(item)
        ),
        key=lambda item: item.relative_to(root).as_posix(),
    )


def resolve_markdown_plane(
    os_root: str | Path,
    layers: Sequence[PolicyLayer],
    *,
    explicit_files: Iterable[str | Path] = (),
    recursive: bool = True,
    excluded_subdirectories: Sequence[str | Path] = (),
) -> dict[str, Any]:
    """Resolve ordered Markdown sources and return provenance plus fingerprint."""

    root = Path(os_root).expanduser().resolve()
    documents: list[MarkdownPolicyDocument] = []
    seen: set[Path] = set()
    layer_rows: list[dict[str, Any]] = []
    for layer in sorted(layers, key=lambda item: (item.rank, item.scope, str(item.root))):
        files = markdown_files(
            layer.root,
            recursive=recursive,
            excluded_subdirectories=excluded_subdirectories,
        )
        layer_rows.append(
            {
                "scope": layer.scope,
                "rank": layer.rank,
                "root": _relative(root, layer.root) if layer.root.resolve().is_relative_to(root) else str(layer.root),
                "exists": layer.root.is_dir(),
                "count": len(files),
            }
        )
        for path in files:
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            documents.append(parse_markdown_policy(root, path, scope=layer.scope, rank=layer.rank))
    explicit_rank = max((layer.rank for layer in layers), default=0) + 1
    for raw in explicit_files:
        path = Path(raw).expanduser().resolve()
        if path in seen:
            continue
        seen.add(path)
        documents.append(parse_markdown_policy(root, path, scope="invocation", rank=explicit_rank))
    documents.sort(key=lambda item: (item.rank, item.source_ref))
    digest_input = [
        {"scope": item.scope, "rank": item.rank, "source_ref": item.source_ref, "sha256": item.sha256}
        for item in documents
    ]
    fingerprint = hashlib.sha256(
        json.dumps(digest_input, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema": "markdown-policy-plane/v1",
        "layers": layer_rows,
        "sources": [item.as_dict() for item in documents],
        "documents": documents,
        "fingerprint": fingerprint,
        "counts": {"layers": len(layer_rows), "sources": len(documents)},
    }


def public_policy_plane(value: Mapping[str, Any], *, include_body: bool = False) -> dict[str, Any]:
    """Remove Python objects from a resolver result for JSON/YAML receipts."""

    result = {key: item for key, item in value.items() if key != "documents"}
    documents = value.get("documents") or []
    result["sources"] = [document.as_dict(include_body=include_body) for document in documents]
    return result
