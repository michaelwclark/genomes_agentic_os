"""Report-only Compose pressure proposals and an explicit teardown executor.

Inventory and proposal construction are observational.  The executor is a
separate API that requires the proposal to be rebuilt from current evidence;
scheduled host-health reporting never invokes it.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


THRESHOLD_KEYS = frozenset(
    {
        "orbstack_vmgr_rss_bytes",
        "orbstack_vmgr_cpu_percent",
        "load1_per_cpu",
        "container_memory_bytes",
        "container_cpu_percent",
    }
)
TERMINAL_LIFECYCLES = frozenset({"finished", "documented", "archived", "closed"})


def _token(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def compose_project_matches_worktree(project: str, worktree_path: str) -> bool:
    """Conservatively compare a Compose project and worktree directory name."""
    project_token = _token(project)
    worktree_token = _token(Path(worktree_path).name)
    if len(project_token) < 6 or len(worktree_token) < 6:
        return False
    return project_token in worktree_token or worktree_token in project_token


@dataclass(frozen=True)
class ComposeContainer:
    name: str
    project: str
    state: str
    cpu_percent: float = 0.0
    memory_bytes: int = 0
    bind_mounts: tuple[str, ...] = ()
    named_volumes: tuple[str, ...] = ()

    @classmethod
    def from_inventory(cls, item: Mapping[str, Any]) -> ComposeContainer | None:
        name = str(item.get("name") or "").strip()
        project = str(item.get("compose_project") or "").strip()
        if not name or not project:
            return None
        return cls(
            name=name,
            project=project,
            state=str(item.get("state") or "unknown"),
            cpu_percent=float(item.get("cpu_percent") or 0),
            memory_bytes=int(item.get("memory_bytes") or 0),
            bind_mounts=tuple(sorted({str(value) for value in item.get("bind_mounts") or [] if value})),
            named_volumes=tuple(sorted({str(value) for value in item.get("named_volumes") or [] if value})),
        )

    @classmethod
    def from_dict(cls, item: Mapping[str, Any]) -> ComposeContainer:
        return cls(
            name=str(item["name"]), project=str(item["project"]),
            state=str(item.get("state") or "unknown"),
            cpu_percent=float(item.get("cpu_percent") or 0),
            memory_bytes=int(item.get("memory_bytes") or 0),
            bind_mounts=tuple(str(value) for value in item.get("bind_mounts") or []),
            named_volumes=tuple(str(value) for value in item.get("named_volumes") or []),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "project": self.project, "state": self.state,
            "cpu_percent": self.cpu_percent, "memory_bytes": self.memory_bytes,
            "bind_mounts": list(self.bind_mounts), "named_volumes": list(self.named_volumes),
        }


@dataclass(frozen=True)
class WorktreeLifecycleEvidence:
    worktree_id: str
    path: str
    lifecycle: str
    lifecycle_source: str
    lifecycle_stale: bool = False
    provider_pull_request: str | None = None
    provider_merged: bool = False
    dirty: bool | None = None
    reopen_marker: bool = False
    runtime_owner: str | None = None
    runtime_identity: str | None = None

    @classmethod
    def from_dict(cls, item: Mapping[str, Any]) -> WorktreeLifecycleEvidence:
        return cls(
            worktree_id=str(item["worktree_id"]), path=str(item["path"]),
            lifecycle=str(item.get("lifecycle") or "unknown"),
            lifecycle_source=str(item.get("lifecycle_source") or "unknown"),
            lifecycle_stale=bool(item.get("lifecycle_stale")),
            provider_pull_request=str(item["provider_pull_request"]) if item.get("provider_pull_request") else None,
            provider_merged=bool(item.get("provider_merged")), dirty=item.get("dirty"),
            reopen_marker=bool(item.get("reopen_marker")),
            runtime_owner=str(item["runtime_owner"]) if item.get("runtime_owner") else None,
            runtime_identity=str(item["runtime_identity"]) if item.get("runtime_identity") else None,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "worktree_id": self.worktree_id, "path": self.path,
            "lifecycle": self.lifecycle, "lifecycle_source": self.lifecycle_source,
            "lifecycle_stale": self.lifecycle_stale,
            "provider_pull_request": self.provider_pull_request,
            "provider_merged": self.provider_merged, "dirty": self.dirty,
            "reopen_marker": self.reopen_marker, "runtime_owner": self.runtime_owner,
            "runtime_identity": self.runtime_identity,
        }


@dataclass(frozen=True)
class ComposePressureThresholds:
    values: tuple[tuple[str, float], ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def configured(self) -> bool:
        return len(self.values) == len(THRESHOLD_KEYS) and not self.errors

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | None) -> ComposePressureThresholds:
        config = config or {}
        errors = [f"missing threshold: {key}" for key in sorted(THRESHOLD_KEYS - set(config))]
        errors.extend(f"unsupported threshold: {key}" for key in sorted(set(config) - THRESHOLD_KEYS))
        values: list[tuple[str, float]] = []
        for key in sorted(THRESHOLD_KEYS & set(config)):
            try:
                value = float(config[key])
            except (TypeError, ValueError):
                errors.append(f"threshold is not numeric: {key}")
                continue
            if value <= 0:
                errors.append(f"threshold must be positive: {key}")
                continue
            values.append((key, value))
        return cls(tuple(values), tuple(errors))

    @classmethod
    def from_dict(cls, item: Mapping[str, Any]) -> ComposePressureThresholds:
        values = item.get("values") or {}
        return cls(tuple(sorted((str(key), float(value)) for key, value in values.items())), tuple(item.get("errors") or ()))

    def as_dict(self) -> dict[str, Any]:
        return {"configured": self.configured, "values": dict(self.values), "errors": list(self.errors)}


@dataclass(frozen=True)
class ComposeTeardownProposal:
    project: str
    recommendation: str
    reasons: tuple[str, ...]
    containers: tuple[ComposeContainer, ...]
    owners: tuple[WorktreeLifecycleEvidence, ...]
    pressure_breaches: tuple[str, ...]
    thresholds: ComposePressureThresholds
    before_metrics: tuple[tuple[str, float], ...]
    named_volumes: tuple[str, ...]

    def _payload(self) -> dict[str, Any]:
        return {
            "schema": "compose-teardown-proposal/v1", "project": self.project,
            "recommendation": self.recommendation, "automatic_action": False,
            "reasons": list(self.reasons), "containers": [item.as_dict() for item in self.containers],
            "bind_mounts": sorted({value for item in self.containers for value in item.bind_mounts}),
            "ownership": [item.as_dict() for item in self.owners],
            "pressure_breaches": list(self.pressure_breaches), "thresholds": self.thresholds.as_dict(),
            "named_volume_disposition": {"decision": "retain", "volumes": list(self.named_volumes)},
            "metrics": {"before": dict(self.before_metrics), "after": None},
        }

    @property
    def fingerprint(self) -> str:
        data = json.dumps(self._payload(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(data).hexdigest()

    @classmethod
    def from_dict(cls, item: Mapping[str, Any]) -> ComposeTeardownProposal:
        proposal = cls(
            project=str(item["project"]), recommendation=str(item["recommendation"]),
            reasons=tuple(item.get("reasons") or ()),
            containers=tuple(ComposeContainer.from_dict(value) for value in item.get("containers") or []),
            owners=tuple(WorktreeLifecycleEvidence.from_dict(value) for value in item.get("ownership") or []),
            pressure_breaches=tuple(item.get("pressure_breaches") or ()),
            thresholds=ComposePressureThresholds.from_dict(item.get("thresholds") or {}),
            before_metrics=tuple(sorted((str(key), float(value)) for key, value in (item.get("metrics") or {}).get("before", {}).items())),
            named_volumes=tuple((item.get("named_volume_disposition") or {}).get("volumes") or ()),
        )
        if item.get("proposal_fingerprint") != proposal.fingerprint:
            raise ValueError("proposal fingerprint is invalid")
        return proposal

    def as_dict(self) -> dict[str, Any]:
        return {**self._payload(), "proposal_fingerprint": self.fingerprint}


@dataclass(frozen=True)
class ComposePressureReport:
    thresholds: ComposePressureThresholds
    proposals: tuple[ComposeTeardownProposal, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "api_version": "host-health-compose-pressure/v1", "mode": "report_only",
            "automatic_teardown": False, "thresholds": self.thresholds.as_dict(),
            "summary": {
                "projects": len(self.proposals),
                "eligible_for_explicit_teardown": sum(p.recommendation == "eligible_for_explicit_teardown" for p in self.proposals),
                "retained": sum(p.recommendation == "retain" for p in self.proposals),
                "unconfigured": sum(p.recommendation == "unconfigured" for p in self.proposals),
            },
            "proposals": [proposal.as_dict() for proposal in self.proposals],
        }


def _owners(project: str, containers: Sequence[ComposeContainer], worktrees: Sequence[WorktreeLifecycleEvidence]) -> tuple[WorktreeLifecycleEvidence, ...]:
    mounts = {Path(value).expanduser().resolve() for container in containers for value in container.bind_mounts}
    exact = [w for w in worktrees if any(mount == Path(w.path).expanduser().resolve() or Path(w.path).expanduser().resolve() in mount.parents for mount in mounts)]
    selected = exact or [w for w in worktrees if compose_project_matches_worktree(project, w.path)]
    return tuple(sorted(selected, key=lambda item: (item.worktree_id, item.path)))


def _refusals(owners: Sequence[WorktreeLifecycleEvidence]) -> tuple[str, ...]:
    if not owners:
        return ("registered_worktree_missing",)
    if len(owners) != 1:
        return ("registered_worktree_ambiguous",)
    owner = owners[0]
    reasons: list[str] = []
    if owner.lifecycle_stale:
        reasons.append("lifecycle_evidence_stale")
    if owner.lifecycle not in TERMINAL_LIFECYCLES:
        reasons.append("lifecycle_not_terminal")
    if not owner.provider_pull_request or not owner.provider_merged:
        reasons.append("provider_merge_unverified")
    if owner.dirty is None:
        reasons.append("dirty_worktree_unknown")
    elif owner.dirty:
        reasons.append("worktree_dirty")
    if owner.reopen_marker:
        reasons.append("reopen_marker_present")
    if not owner.runtime_owner or not owner.runtime_identity or owner.runtime_identity == "not-managed":
        reasons.append("runtime_identity_missing")
    return tuple(reasons)


def build_compose_pressure_report(containers: Sequence[ComposeContainer], worktrees: Sequence[WorktreeLifecycleEvidence], host_metrics: Mapping[str, Any], threshold_config: Mapping[str, Any] | None) -> ComposePressureReport:
    """Build immutable observations; this function cannot execute Docker."""
    thresholds = ComposePressureThresholds.from_config(threshold_config)
    grouped: dict[str, list[ComposeContainer]] = {}
    for container in containers:
        grouped.setdefault(container.project, []).append(container)
    proposals: list[ComposeTeardownProposal] = []
    for project, group in sorted(grouped.items()):
        ordered = tuple(sorted(group, key=lambda item: item.name))
        observations = {key: float(host_metrics.get(key) or 0) for key in ("orbstack_vmgr_rss_bytes", "orbstack_vmgr_cpu_percent", "fseventsd_rss_bytes", "fseventsd_cpu_percent", "load1", "load5", "load15", "load1_per_cpu")}
        observations["container_memory_bytes"] = float(sum(item.memory_bytes for item in ordered))
        observations["container_cpu_percent"] = float(sum(item.cpu_percent for item in ordered))
        ownership = _owners(project, ordered, worktrees)
        refusals = _refusals(ownership)
        breaches = tuple(key for key, boundary in thresholds.values if observations.get(key, 0) >= boundary)
        if not thresholds.configured:
            recommendation, reasons = "unconfigured", thresholds.errors + refusals
        elif not breaches:
            recommendation, reasons = "retain", ("pressure_below_thresholds",) + refusals
        elif refusals:
            recommendation, reasons = "retain", refusals
        else:
            recommendation, reasons = "eligible_for_explicit_teardown", ("all_explicit_teardown_gates_passed",)
        proposals.append(ComposeTeardownProposal(project, recommendation, reasons, ordered, ownership, breaches, thresholds, tuple(sorted(observations.items())), tuple(sorted({v for c in ordered for v in c.named_volumes}))))
    return ComposePressureReport(thresholds, tuple(proposals))


Runner = Callable[..., subprocess.CompletedProcess[str]]


def execute_compose_teardown(proposal: ComposeTeardownProposal, current_proposal: ComposeTeardownProposal, *, runner: Runner, metric_reader: Callable[[], Mapping[str, Any]], volume_reader: Callable[[Sequence[str]], Sequence[str]]) -> dict[str, Any]:
    """Apply an explicitly authorized teardown after exact revalidation."""
    if proposal.fingerprint != current_proposal.fingerprint:
        raise ValueError("proposal fingerprint no longer matches current evidence")
    if current_proposal.recommendation != "eligible_for_explicit_teardown" or len(current_proposal.owners) != 1:
        raise ValueError("proposal is not eligible for explicit teardown")
    owner = current_proposal.owners[0]
    if not owner.runtime_owner or not owner.runtime_identity or owner.runtime_identity == "not-managed":
        raise ValueError("proposal has no exact runtime identity")
    command = ["docker", "compose", "--project-name", proposal.project, "--project-directory", owner.path, "down"]
    result = runner(command, check=False, capture_output=True, text=True, timeout=120)
    retained = tuple(sorted(volume_reader(proposal.named_volumes)))
    expected = tuple(sorted(proposal.named_volumes))
    return {
        "api_version": "host-health-compose-teardown/v1", "proposal_fingerprint": proposal.fingerprint,
        "runtime_identity": owner.runtime_identity, "runtime_owner": owner.runtime_owner,
        "command": command, "exit_code": result.returncode,
        "applied": result.returncode == 0 and retained == expected,
        "named_volume_disposition": {"decision": "retained", "expected": list(expected), "observed": list(retained), "verified": retained == expected},
        "metrics": {"before": dict(proposal.before_metrics), "after": dict(metric_reader())},
        "detail": (result.stderr or result.stdout).strip()[:300],
    }
