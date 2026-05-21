"""Deterministic routing and context packet assembly."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .scaffold import DEFAULT_DOMAINS, STANDARD_LANES, expand_path, normalize_domain, validate_name


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

    def as_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "lane": self.lane,
            "object_type": self.object_type,
            "target_path": str(self.target_path),
            "sources_to_load": [str(path) for path in self.sources_to_load],
            "approval_risks": self.approval_risks,
            "known_gaps": self.known_gaps,
            "handoff_prompt": self.handoff_prompt,
        }


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
    domains = [domain for domain in DEFAULT_DOMAINS if (root / domain).is_dir()]
    extra = [
        path.name
        for path in sorted(root.iterdir())
        if path.is_dir() and (path / "domain.yml").is_file() and path.name not in domains
    ] if root.is_dir() else []
    return domains + extra


def project_records(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for domain in existing_domains(root):
        projects_root = root / domain / "02-projects"
        for config in sorted(projects_root.glob("*/project.yml")):
            data = read_yaml(config)
            project = str(data.get("id") or config.parent.name)
            sources = data.get("sources") if isinstance(data.get("sources"), dict) else {}
            records.append(
                {
                    "domain": domain,
                    "project": project,
                    "lane": str(data.get("lane") or ""),
                    "path": config.parent,
                    "repo": str(sources.get("repo") or ""),
                }
            )
    return records


def approval_risks(request: str) -> list[str]:
    text = request.lower()
    risks = sorted({risk for keyword, risk in RISK_KEYWORDS.items() if keyword in text})
    return risks


def detect_from_cwd(root: Path, cwd: Path) -> dict[str, str]:
    relative = safe_relative(cwd, root)
    if relative is not None and relative.parts:
        domain = relative.parts[0]
        if domain in existing_domains(root):
            context = {"domain": domain}
            parts = relative.parts
            if len(parts) >= 3 and parts[1] == "02-projects":
                context["project"] = parts[2]
            if len(parts) >= 4 and parts[1] == "03-workflows":
                context["lane"] = parts[2]
                context["workflow"] = parts[3]
            return context

    for record in project_records(root):
        repo = record["repo"]
        if not repo:
            continue
        repo_path = Path(repo).expanduser()
        if safe_relative(cwd, repo_path) is not None:
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
        if any(label.lower() in text for label in labels):
            domain_hits.append(domain)

    project_hits = []
    for record in project_records(root):
        project = record["project"]
        labels = {project, project.replace("_", " "), project.replace("_", "-")}
        if any(label.lower() in text for label in labels):
            project_hits.append(record)

    if len(project_hits) == 1:
        record = project_hits[0]
        return {"domain": record["domain"], "project": record["project"], "lane": record["lane"]}
    if len(domain_hits) == 1:
        return {"domain": domain_hits[0]}
    if len(domain_hits) > 1 or len(project_hits) > 1:
        raise ValueError("routing confidence is low: request matches multiple domains or projects")
    raise ValueError("routing confidence is low: no domain or project matched")


def find_workflow(root: Path, domain: str, workflow: str, lane: str | None = None) -> tuple[str, Path]:
    workflow = validate_name(workflow, "workflow")
    domain_root = root / domain / "03-workflows"
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
    risks: list[str] | None = None,
) -> ContextPacket:
    os_root = expand_path(root)
    domain = normalize_domain(domain)
    domain_root = os_root / domain
    if not domain_root.is_dir():
        raise ValueError(f"domain not found: {domain}")

    sources = [
        os_root / "ROUTER.md",
        domain_root / "ROUTER.md",
        domain_root / "CONTEXT.md",
        domain_root / "REFERENCES.md",
        domain_root / "00-control-plane" / "active-work.md",
        domain_root / "05-knowledge" / "memory-policy.md",
    ]
    target = domain_root
    object_type = "domain"
    known_gaps: list[str] = []
    detected_lane = lane or ""

    if project:
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
                project_root / "project.yml",
                project_root / "status.md",
                project_root / "source-map.md",
                project_root / "decisions.md",
            ]
        )

    if workflow:
        detected_lane, workflow_root = find_workflow(os_root, domain, workflow, detected_lane or None)
        target = workflow_root
        object_type = "workflow"
        sources.extend(
            [
                workflow_root / "quick-reference.md",
                workflow_root / "context-pack.md",
                workflow_root / "runbook.md",
            ]
        )

    for source in sources:
        if not source.is_file():
            known_gaps.append(f"missing source: {source}")

    return ContextPacket(
        domain=domain,
        lane=detected_lane,
        object_type=object_type,
        target_path=target,
        sources_to_load=sources,
        approval_risks=risks or [],
        known_gaps=known_gaps,
        handoff_prompt=f"Load the listed sources, work in {target}, follow approval rules, and record validation before closeout.",
    )


def route_request(root: str | Path, request: str, *, cwd: str | Path | None = None) -> ContextPacket:
    os_root = expand_path(root)
    cwd_path = Path(cwd).expanduser().resolve() if cwd else Path.cwd()
    context = detect_from_cwd(os_root, cwd_path)
    if not context:
        context = detect_from_request(os_root, request)
    return build_context(
        os_root,
        domain=context["domain"],
        project=context.get("project"),
        workflow=context.get("workflow"),
        lane=context.get("lane"),
        risks=approval_risks(request),
    )


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
    )
