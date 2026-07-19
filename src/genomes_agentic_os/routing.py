"""Deterministic routing and context packet assembly."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import yaml

from .context_contracts import resolve_context_contract
from .lifecycle import WorkItemRecord, record_matches_request, select_project_work_item
from .scaffold import (
    SHARED_FACTORY_DOMAIN,
    domain_path,
    expand_path,
    harness_path,
    installed_domain_names,
    normalize_domain,
    shared_factory_path,
    validate_name,
)


RISK_KEYWORDS = {
    "external": "external write",
    "send": "external write",
    "customer": "customer-visible output",
    "production": "production change",
    "deploy": "production change",
    "delete": "destructive action",
    "destroy": "destructive action",
    "secret": "secret handling",
    "billing": "billing or legal record",
    "legal": "billing or legal record",
    "merge": "production change",
}

IDEA_CAPTURE_PHRASES = (
    "add an idea",
    "capture an idea",
    "idea for",
    "rough idea",
    "new idea",
    "add idea",
)

ESCALATION_PHRASES = (
    "create a project",
    "create project",
    "create workflow",
    "create automation",
    "implementation branch",
    "open a pr",
    "make a pr",
    "jira",
)

ROUTING_MATCH_STOPWORDS = {
    "a",
    "add",
    "an",
    "and",
    "build",
    "create",
    "feature",
    "for",
    "from",
    "have",
    "i",
    "idea",
    "in",
    "into",
    "new",
    "of",
    "on",
    "the",
    "to",
    "want",
    "with",
}


class RoutingSuggestion(ValueError):
    """Raised when confidence is below threshold but a best candidate exists.

    Callers that want to honour the suggestion should catch this exception
    and use ``suggestion`` as advisory context rather than treating the result
    as a confirmed route.  Callers that want hard-refusal behaviour should
    treat it identically to ``ValueError``.

    The ``reason`` attribute carries the human-readable explanation of why
    confidence was low.  Approval-risk checks are not bypassed — the caller
    still runs ``approval_risks()`` as normal.
    """

    def __init__(self, suggestion: dict[str, str], reason: str) -> None:
        super().__init__(reason)
        self.suggestion = suggestion
        self.reason = reason


@dataclass
class ContextPacket:
    domain: str
    lane: str
    object_type: str
    target_path: Path
    sources_to_load: list[Path]
    approval_risks: list[str]
    known_gaps: list[str]
    handoff_prompt: str
    lifecycle: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        packet = {
            "domain": self.domain,
            "lane": self.lane,
            "object_type": self.object_type,
            "target_path": str(self.target_path),
            "sources_to_load": [str(path) for path in self.sources_to_load],
            "approval_risks": self.approval_risks,
            "known_gaps": self.known_gaps,
            "handoff_prompt": self.handoff_prompt,
        }
        if self.lifecycle is not None:
            packet["lifecycle"] = self.lifecycle
        return packet


def format_packet(packet: ContextPacket) -> str:
    return yaml.safe_dump(packet.as_dict(), sort_keys=False).strip()


def safe_relative(path: Path, root: Path) -> Path | None:
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError:
        return None


def read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def existing_domains(root: Path) -> list[str]:
    """Domains present on disk (any top-level dir with a domain.yml marker).

    Derived purely from the tree so routing works for installs with any
    operator-chosen domain names; no built-in name list is consulted.
    """
    domains = installed_domain_names(root)
    if shared_factory_path(root).is_dir():
        domains.append(SHARED_FACTORY_DOMAIN)
    return domains


def project_records(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for domain in existing_domains(root):
        projects_root = domain_path(root, domain) / "02-projects"
        for config in sorted(projects_root.glob("*/project.yml")):
            data = read_yaml(config)
            project = str(data.get("id") or config.parent.name)
            sources = data.get("sources") if isinstance(data.get("sources"), dict) else {}
            worktree_index = read_yaml(config.parent / "worktrees" / "index.yml")
            worktrees = worktree_index.get("worktrees") if isinstance(worktree_index.get("worktrees"), list) else []
            records.append(
                {
                    "domain": domain,
                    "project": project,
                    "lane": str(data.get("lane") or ""),
                    "path": config.parent,
                    "repo": str(sources.get("repo") or ""),
                    "worktrees": [entry for entry in worktrees if isinstance(entry, dict)],
                }
            )
    return records


def is_idea_capture_request(request: str) -> bool:
    text = request.lower()
    return any(phrase in text for phrase in IDEA_CAPTURE_PHRASES) and not any(
        phrase in text for phrase in ESCALATION_PHRASES
    )


def approval_risks(request: str) -> list[str]:
    text = request.lower()
    risks = sorted({risk for keyword, risk in RISK_KEYWORDS.items() if keyword in text})
    return risks


def detect_from_cwd(root: Path, cwd: Path) -> dict[str, str]:
    relative = safe_relative(cwd, root)
    if relative is not None and relative.parts:
        if len(relative.parts) >= 2 and relative.parts[0] == "harness" and relative.parts[1] == SHARED_FACTORY_DOMAIN:
            context = {"domain": SHARED_FACTORY_DOMAIN}
            if len(relative.parts) >= 4 and relative.parts[2] == "02-projects":
                context["project"] = relative.parts[3]
            if len(relative.parts) >= 5 and relative.parts[2] == "03-workflows":
                context["lane"] = relative.parts[3]
                context["workflow"] = relative.parts[4]
            return context
        parts = relative.parts
        if len(parts) >= 2 and parts[0] == "domains":
            parts = parts[1:]
        domain = parts[0]
        if domain in existing_domains(root):
            context = {"domain": domain}
            if len(parts) >= 3 and parts[1] == "02-projects":
                context["project"] = parts[2]
            if len(parts) >= 4 and parts[1] == "03-workflows":
                context["lane"] = parts[2]
                context["workflow"] = parts[3]
            return context

    for record in project_records(root):
        repo = record["repo"]
        repo_path = Path(repo).expanduser() if repo else None
        if repo_path and safe_relative(cwd, repo_path) is not None:
            return {
                "domain": record["domain"],
                "project": record["project"],
                "lane": record["lane"],
            }
        for worktree in record.get("worktrees", []):
            path_value = str(worktree.get("path") or "")
            if not path_value:
                continue
            if safe_relative(cwd, Path(path_value).expanduser()) is not None:
                return {
                    "domain": record["domain"],
                    "project": record["project"],
                    "lane": record["lane"],
                }
    return {}


def detect_from_request(root: Path, request: str) -> dict[str, str]:
    text = request.lower()
    domain_hits = []
    for domain in existing_domains(root):
        labels = {domain, domain.replace("_", " "), domain.replace("_", "-")}
        if domain == SHARED_FACTORY_DOMAIN:
            labels.update({"shared factory", "harness", "agentic os"})
        if any(label.lower() in text for label in labels):
            domain_hits.append(domain)

    project_hits = []
    for record in project_records(root):
        project = record["project"]
        labels = {project, project.replace("_", " "), project.replace("_", "-")}
        if any(label.lower() in text or token_label_matches(label, text) for label in labels):
            project_hits.append(record)

    work_item_hits: list[tuple[dict[str, Any], WorkItemRecord]] = []
    for record in project_records(root):
        try:
            work_item = select_project_work_item(record["path"], request=request)
        except ValueError:
            raise
        if work_item and work_item_matches_request(work_item, request):
            work_item_hits.append((record, work_item))

    if len(work_item_hits) == 1:
        record, work_item = work_item_hits[0]
        return {
            "domain": record["domain"],
            "project": record["project"],
            "lane": record["lane"],
            "work_item": work_item.path.name,
        }
    if len(work_item_hits) > 1:
        # Multiple work item matches — return the first as a suggestion
        record, work_item = work_item_hits[0]
        raise RoutingSuggestion(
            {
                "domain": record["domain"],
                "project": record["project"],
                "lane": record["lane"],
                "work_item": work_item.path.name,
            },
            "routing confidence is low: request matches multiple work items",
        )
    if len(project_hits) == 1:
        record = project_hits[0]
        return {"domain": record["domain"], "project": record["project"], "lane": record["lane"]}
    if len(domain_hits) == 1:
        return {"domain": domain_hits[0]}
    if len(domain_hits) > 1:
        # Multiple domain matches — suggest the first
        raise RoutingSuggestion(
            {"domain": domain_hits[0]},
            "routing confidence is low: request matches multiple domains",
        )
    if len(project_hits) > 1:
        # Multiple project matches — suggest the first
        record = project_hits[0]
        raise RoutingSuggestion(
            {"domain": record["domain"], "project": record["project"], "lane": record["lane"]},
            "routing confidence is low: request matches multiple projects",
        )
    raise ValueError("routing confidence is low: no domain or project matched")


def token_label_matches(label: str, text: str) -> bool:
    label_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", label.lower())
        if token not in ROUTING_MATCH_STOPWORDS and (len(token) >= 2 or token.isdigit())
    }
    request_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if token not in ROUTING_MATCH_STOPWORDS and (len(token) >= 2 or token.isdigit())
    }
    return len(label_tokens & request_tokens) >= 2


def work_item_matches_request(record: WorkItemRecord, request: str) -> bool:
    return record_matches_request(record, request)


def find_workflow(root: Path, domain: str, workflow: str, lane: str | None = None) -> tuple[str, Path]:
    workflow = validate_name(workflow, "workflow")
    domain_root = domain_path(root, domain) / "03-workflows"
    if lane:
        lane = validate_name(lane, "lane")
        candidate = domain_root / lane / workflow
        if not candidate.is_dir():
            raise ValueError(f"workflow not found: {domain}/{lane}/{workflow}")
        return lane, candidate
    matches = [(path.parent.name, path) for path in sorted(domain_root.glob(f"*/{workflow}")) if path.is_dir()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"workflow is ambiguous; specify lane: {workflow}")
    raise ValueError(f"workflow not found: {domain}/{workflow}")


def build_context(
    root: str | Path,
    *,
    domain: str,
    project: str | None = None,
    workflow: str | None = None,
    lane: str | None = None,
    inbox: bool = False,
    risks: list[str] | None = None,
    work_item: str | None = None,
    request: str | None = None,
    cwd: str | Path | None = None,
) -> ContextPacket:
    os_root = expand_path(root)
    domain = normalize_domain(domain)
    domain_root = domain_path(os_root, domain)
    if not domain_root.is_dir():
        raise ValueError(f"domain not found: {domain}")

    sources = [
        harness_path(os_root, "ROUTER.md"),
        shared_factory_path(os_root, "05-knowledge", "references", "naming-conventions.md"),
        shared_factory_path(os_root, "05-knowledge", "references", "tool-index.md"),
        shared_factory_path(os_root, "05-knowledge", "references", "source-priority.md"),
        shared_factory_path(os_root, "05-knowledge", "references", "style-and-output-rules.md"),
        domain_root / "ROUTER.md",
        domain_root / "CONTEXT.md",
        domain_root / "REFERENCES.md",
        domain_root / "MEMORY.md",
    ]
    for optional_source in (
        shared_factory_path(os_root, "00-control-plane", "active-now.json"),
        os_root / "lib" / "registry" / "objects.json",
    ):
        if optional_source.is_file():
            sources.append(optional_source)
    target = domain_root
    object_type = "domain"
    known_gaps: list[str] = []
    detected_lane = lane or ""
    lifecycle: dict[str, Any] | None = None

    if inbox:
        target = domain_root / "01-inbox"
        object_type = "inbox"
        sources.extend(
            [
                domain_root / "01-inbox" / "raw-ideas.md",
                domain_root / "01-inbox" / "triage.md",
                domain_root / "00-control-plane" / "routing-rules.md",
                domain_root / "00-control-plane" / "state-index.md",
                domain_root / "MEMORY.md",
            ]
        )

    if project and not inbox:
        project = validate_name(project, "project")
        project_root = domain_root / "02-projects" / project
        if not project_root.is_dir():
            raise ValueError(f"project not found: {domain}/{project}")
        target = project_root
        object_type = "project"
        project_config = read_yaml(project_root / "project.yml")
        detected_lane = detected_lane or str(project_config.get("lane") or "")
        sources.extend(
            [
                project_root / "AGENTS.md",
                project_root / "ROUTER.md",
                project_root / "CONTEXT.md",
                project_root / "RULES.md",
                project_root / "TOOLS.md",
                project_root / "project.yml",
                project_root / "status.md",
                project_root / "source-map.md",
                project_root / "decisions.md",
                project_root / "config" / "project-profile.yml",
                project_root / "config" / "development.yml",
                project_root / "config" / "workflows.yml",
                project_root / "config" / "work-lifecycle.yml",
                project_root / "config" / "output-artifacts.yml",
                project_root / "config" / "validation.yml",
                project_root / "config" / "worktrees.yml",
                project_root / "config" / "memory.yml",
                project_root / "config" / "mcps.yml",
                project_root / "config" / "tools.yml",
                project_root / "worktrees" / "index.yml",
            ]
        )
        project_context = resolve_context_contract(project_root, root=os_root)
        if not project_context.legacy_fallback:
            sources.extend(source.path for source in project_context.read_first)
            known_gaps.extend(
                item.message for item in project_context.diagnostics if item.severity in {"warning", "error"}
            )
        selected_work_item = select_project_work_item(
            project_root,
            request=request,
            cwd=Path(cwd).expanduser().resolve() if cwd else None,
            work_item=work_item,
        )
        if selected_work_item:
            target = selected_work_item.path
            object_type = "work_item"
            lifecycle = selected_work_item.as_lifecycle_dict()
            sources.append(selected_work_item.metadata_path)
            sources.extend(selected_work_item.required_files)

    if workflow and not inbox:
        detected_lane, workflow_root = find_workflow(os_root, domain, workflow, detected_lane or None)
        target = workflow_root
        object_type = "workflow"
        legacy_workflow_sources = (
            workflow_root / "quick-reference.md",
            workflow_root / "context-pack.md",
            workflow_root / "runbook.md",
        )
        resolved = resolve_context_contract(
            workflow_root,
            root=os_root,
            legacy_sources=legacy_workflow_sources,
        )
        sources.extend(source.path for source in resolved.read_first)
        known_gaps.extend(item.message for item in resolved.diagnostics if item.severity in {"warning", "error"})

    # Keep source ordering deterministic while avoiding the same file being
    # loaded twice through legacy and inherited paths.
    deduplicated_sources: list[Path] = []
    seen_sources: set[Path] = set()
    for source in sources:
        resolved_source = source.resolve()
        if resolved_source in seen_sources:
            continue
        seen_sources.add(resolved_source)
        deduplicated_sources.append(source)
    sources = deduplicated_sources

    for source in sources:
        if not source.is_file():
            known_gaps.append(f"missing source: {source}")

    # F-022: surface run-log create discoverability — it is required before
    # run-log close but easy to miss.  Add it to the handoff prompt so agents
    # routing to a workflow or automation always see the reminder.
    runlog_hint = ""
    if object_type in ("workflow", "automation", "work_item"):
        runlog_hint = (
            "  Before closing work: run `agentic-os run-log create <domain> <workflow_or_automation> --root <root>`"
            " first, then `run-log close` with the run_id it returns."
        )

    return ContextPacket(
        domain=domain,
        lane=detected_lane,
        object_type=object_type,
        target_path=target,
        sources_to_load=sources,
        approval_risks=risks or [],
        known_gaps=known_gaps,
        handoff_prompt=(
            f"Load the listed sources, work in {target}, follow approval rules, and record validation before closeout."
            + (f"\n{runlog_hint}" if runlog_hint else "")
        ),
        lifecycle=lifecycle,
    )


def route_request(root: str | Path, request: str, *, cwd: str | Path | None = None) -> ContextPacket:
    os_root = expand_path(root)
    cwd_path = Path(cwd).expanduser().resolve() if cwd else Path.cwd()
    inbox_request = is_idea_capture_request(request)
    inbox = False
    context: dict[str, str] = {}
    suggestion_reason: str | None = None

    if inbox_request:
        try:
            context = detect_from_request(os_root, request)
            if "project" not in context and "work_item" not in context:
                context = {"domain": context["domain"]}
                inbox = True
        except RoutingSuggestion as exc:
            # Low confidence on an inbox request: use the suggestion domain
            context = {"domain": exc.suggestion.get("domain", "")}
            suggestion_reason = exc.reason
            inbox = bool(context.get("domain"))
        except ValueError:
            cwd_context = detect_from_cwd(os_root, cwd_path)
            if cwd_context:
                context = {"domain": cwd_context["domain"]}
                inbox = True

    if not context:
        context = detect_from_cwd(os_root, cwd_path)
    if not context:
        try:
            context = detect_from_request(os_root, request)
        except RoutingSuggestion as exc:
            # Surface the suggestion: build context from the best candidate and
            # mark it advisory via known_gaps so callers can see it was a guess.
            context = exc.suggestion
            suggestion_reason = exc.reason

    packet = build_context(
        os_root,
        domain=context["domain"],
        project=context.get("project"),
        workflow=context.get("workflow"),
        lane=context.get("lane"),
        work_item=context.get("work_item"),
        request=request,
        cwd=cwd_path,
        inbox=inbox,
        risks=approval_risks(request),
    )
    if suggestion_reason:
        packet.known_gaps.insert(
            0,
            f"SUGGESTION (low confidence): {suggestion_reason} — verify before acting",
        )
    return packet


def context_from_here(root: str | Path, *, cwd: str | Path | None = None) -> ContextPacket:
    os_root = expand_path(root)
    cwd_path = Path(cwd).expanduser().resolve() if cwd else Path.cwd()
    context = detect_from_cwd(os_root, cwd_path)
    if not context:
        raise ValueError("routing confidence is low: current directory is not inside the OS or a linked project repo")
    return build_context(
        os_root,
        domain=context["domain"],
        project=context.get("project"),
        workflow=context.get("workflow"),
        lane=context.get("lane"),
        cwd=cwd_path,
    )
