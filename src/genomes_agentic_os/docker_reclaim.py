"""Reclaim orphaned Docker/OrbStack resources left behind by removed worktrees.

Every per-worktree dev stack creates its own compose project: a network, a set
of named volumes, and images. When a worktree is deleted after its PR merges,
those resources stay behind. They accumulate until Docker runs out of address
pools and no new stack can start at all -- observed on one dev host with 32
networks, 28 of them empty.

Deciding what is safe to delete is the whole problem. Two predicates are
tempting and both are wrong:

* "no running container" -- a worktree whose stack is merely stopped still owns
  its postgres volume. Docker reports that volume as dangling, and pruning it
  destroys a live dev database.
* "worktree registry says complete" -- the registry is advisory and drifts. On
  one dev host all 94 registered worktrees claim ``status: active`` while only
  57 directories exist and 4 stacks run.

This module uses the conjunction of two independent facts instead, and deletes
only when both agree the owner is gone:

1. no directory for the owning compose project exists under any known worktree
   root -- the worktree itself has been removed; and
2. no container is attached to the resource -- nothing is using it right now.

Ambiguity always resolves to keeping the resource.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

#: Networks Docker creates itself. Removing them is either impossible or breaks
#: default container networking.
BUILTIN_NETWORKS = frozenset({"bridge", "host", "none"})

#: Scopes that may be deleted by default. Images and build cache are excluded:
#: they hold no unique state, but re-pulling them is slow and expensive, so they
#: stay opt-in rather than surprising an operator on a scheduled run.
DEFAULT_SCOPES = ("networks", "volumes")
ALL_SCOPES = ("networks", "volumes", "images", "cache")

#: Compose derives a project name from a directory name by lowercasing and
#: dropping separators. Comparisons happen in that normalised space.
_NON_ALNUM = re.compile(r"[^a-z0-9]")

#: Compose truncates long project names when composing container names, so an
#: exact match is not reliable. Comparing a generous common prefix keeps a
#: truncated name matching its full directory. Deliberately biased toward
#: matching, because a false match only preserves a resource.
_PREFIX_MATCH_CHARS = 24

#: Below this length a token is too generic to match on containment -- "ouz"
#: would match half the daemon. Short tokens fall back to strict prefixing.
_MIN_CONTAINMENT_CHARS = 6

#: Anonymous volumes are bare hex ids with no project prefix.
_ANONYMOUS_VOLUME = re.compile(r"^[0-9a-f]{32,}$")


def normalise(name: str) -> str:
    """Reduce a directory or resource name to its compose-comparable form."""
    return _NON_ALNUM.sub("", name.lower())


@dataclass(frozen=True)
class Resource:
    """One Docker resource considered for reclamation."""

    kind: str
    name: str
    attached_containers: int = 0
    size_bytes: int = 0

    @property
    def project_token(self) -> str:
        """The compose project portion of the name, normalised.

        Volumes and networks are named ``<project>_<suffix>``; splitting on the
        last underscore is wrong for projects that contain underscores, so the
        whole name is normalised and prefix-compared instead.
        """
        return normalise(self.name)


@dataclass
class Decision:
    """Why a single resource is kept or reclaimed."""

    resource: Resource
    action: str  # "reclaim" | "keep"
    reason: str
    owner: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.resource.kind,
            "name": self.resource.name,
            "action": self.action,
            "reason": self.reason,
            "attached_containers": self.resource.attached_containers,
        }
        if self.owner:
            payload["owner_worktree"] = self.owner
        if self.resource.size_bytes:
            payload["size_bytes"] = self.resource.size_bytes
        return payload


@dataclass
class ReclaimPlan:
    """The full set of decisions for one run."""

    decisions: list[Decision] = field(default_factory=list)
    live_tokens: dict[str, str] = field(default_factory=dict)
    scopes: tuple[str, ...] = DEFAULT_SCOPES
    applied: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def reclaimable(self) -> list[Decision]:
        return [d for d in self.decisions if d.action == "reclaim"]

    @property
    def kept(self) -> list[Decision]:
        return [d for d in self.decisions if d.action == "keep"]

    def as_receipt(self, generated_at: str) -> dict[str, Any]:
        by_kind: dict[str, int] = {}
        for decision in self.reclaimable:
            by_kind[decision.resource.kind] = by_kind.get(decision.resource.kind, 0) + 1
        return {
            "api_version": "host-health-docker-reclaim/v1",
            "generated_at": generated_at,
            "mode": "apply" if self.applied else "report",
            "scopes": list(self.scopes),
            "protected_worktrees": len(self.live_tokens),
            "summary": {
                "reclaimable": len(self.reclaimable),
                "kept": len(self.kept),
                "reclaimable_by_kind": by_kind,
            },
            "decisions": [d.as_dict() for d in self.decisions],
            "errors": self.errors,
        }


def discover_worktree_dirs(roots: Iterable[Path]) -> dict[str, str]:
    """Map every on-disk worktree directory to its normalised compose token.

    A directory here means "some checkout still exists", which is the signal
    that its Docker resources may still be wanted. Roots that do not exist are
    skipped rather than raising: a project without worktrees is normal.
    """
    tokens: dict[str, str] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            token = normalise(child.name)
            if token:
                tokens[token] = child.name
    return tokens


def default_worktree_roots(os_root: Path, projects_root: Path | None = None) -> list[Path]:
    """Every directory that can hold a per-worktree dev stack.

    Covers OS-managed worktrees (``domains/*/02-projects/*/worktrees``) and
    plain source checkouts under ``~/projects/*/worktrees``, because both
    produce compose projects on the same Docker daemon.
    """
    roots: list[Path] = []
    domains = os_root / "domains"
    if domains.is_dir():
        roots.extend(sorted(domains.glob("*/02-projects/*/worktrees")))
        roots.extend(sorted(domains.glob("*/02-projects/*/*/worktrees")))
    if projects_root and projects_root.is_dir():
        roots.extend(sorted(projects_root.glob("*/worktrees")))
    return [r for r in roots if r.is_dir()]


def _match_owner(token: str, live_tokens: dict[str, str]) -> str | None:
    """Return the worktree owning ``token``, if any.

    Matching has to survive two independent manglings of the same directory
    name, which is why plain prefixing is not enough:

    * truncation -- compose shortens long project names for container names
      (``072926-git-...-sso-managed-us`` becomes ``acme-072926-git-...-acme-a``);
    * prefixing -- some stacks name their compose project ``acme-<dir>``, so the
      directory token appears in the *middle* of a network name while volumes
      keep the bare directory name.

    Containment in either direction handles both. The bias is intentional: a
    spurious match only keeps a resource, while a missed match deletes one.
    """
    if not token:
        return None
    for live, original in live_tokens.items():
        if not live:
            continue
        head = live[:_PREFIX_MATCH_CHARS]
        if len(head) < _MIN_CONTAINMENT_CHARS:
            # Too generic for containment; demand a real prefix.
            if token.startswith(head):
                return original
            continue
        if head in token or token[:_PREFIX_MATCH_CHARS] in live:
            return original
    return None


def classify(
    resources: Sequence[Resource],
    live_tokens: dict[str, str],
    protected_names: Iterable[str] = (),
) -> list[Decision]:
    """Decide each resource against both safety predicates.

    Order matters: the cheapest, most absolute reasons to keep are checked
    first so a receipt reports the strongest justification rather than an
    incidental one.
    """
    protected = set(protected_names)
    decisions: list[Decision] = []

    for resource in resources:
        if resource.kind == "network" and resource.name in BUILTIN_NETWORKS:
            decisions.append(Decision(resource, "keep", "docker builtin network"))
            continue

        if resource.name in protected:
            decisions.append(Decision(resource, "keep", "explicitly protected"))
            continue

        if resource.attached_containers > 0:
            decisions.append(
                Decision(resource, "keep", "in use by a container")
            )
            continue

        owner = _match_owner(resource.project_token, live_tokens)
        if owner:
            # The stack may simply be stopped; its volumes still hold state.
            decisions.append(
                Decision(resource, "keep", "owning worktree still on disk", owner)
            )
            continue

        decisions.append(
            Decision(resource, "reclaim", "no owning worktree on disk and unused")
        )

    return decisions


class DockerClient:
    """Thin wrapper over the docker CLI, isolated so tests can substitute it."""

    def __init__(self, binary: str = "docker") -> None:
        self.binary = binary

    def available(self) -> bool:
        if shutil.which(self.binary) is None:
            return False
        return self._run(["info", "--format", "{{.ServerVersion}}"]).returncode == 0

    def _run(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.binary, *args], capture_output=True, text=True, timeout=120
        )

    def networks(self) -> list[Resource]:
        out = self._run(["network", "ls", "--format", "{{.Name}}"]).stdout.split()
        found: list[Resource] = []
        for name in out:
            inspect = self._run(
                ["network", "inspect", name, "--format", "{{len .Containers}}"]
            )
            count = int(inspect.stdout.strip() or 0) if inspect.returncode == 0 else 1
            found.append(Resource("network", name, attached_containers=count))
        return found

    def volumes(self) -> list[Resource]:
        all_names = set(self._run(["volume", "ls", "--format", "{{.Name}}"]).stdout.split())
        dangling = set(
            self._run(
                ["volume", "ls", "-q", "--filter", "dangling=true"]
            ).stdout.split()
        )
        return [
            Resource("volume", name, attached_containers=0 if name in dangling else 1)
            for name in sorted(all_names)
        ]

    def remove(self, resource: Resource) -> tuple[bool, str]:
        verb = {"network": "network", "volume": "volume"}.get(resource.kind)
        if verb is None:
            return False, f"unsupported kind {resource.kind}"
        proc = self._run([verb, "rm", resource.name])
        if proc.returncode == 0:
            return True, "removed"
        return False, (proc.stderr or proc.stdout).strip()[:200]


def build_plan(
    client: DockerClient,
    live_tokens: dict[str, str],
    scopes: Sequence[str] = DEFAULT_SCOPES,
    protected_names: Iterable[str] = (),
) -> ReclaimPlan:
    """Collect resources for the requested scopes and classify them."""
    resources: list[Resource] = []
    if "networks" in scopes:
        resources.extend(client.networks())
    if "volumes" in scopes:
        resources.extend(client.volumes())

    plan = ReclaimPlan(scopes=tuple(scopes), live_tokens=dict(live_tokens))
    plan.decisions = classify(resources, live_tokens, protected_names)
    return plan


def apply_plan(client: DockerClient, plan: ReclaimPlan) -> ReclaimPlan:
    """Delete everything the plan marked reclaimable, recording failures.

    A removal that fails is not fatal: Docker may legitimately refuse when a
    resource became busy between planning and applying, and that is exactly the
    race the conservative predicates are meant to lose safely.
    """
    for decision in list(plan.reclaimable):
        ok, detail = client.remove(decision.resource)
        if not ok:
            decision.action = "keep"
            decision.reason = f"removal refused: {detail}"
            plan.errors.append(f"{decision.resource.kind} {decision.resource.name}: {detail}")
    plan.applied = True
    return plan


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_receipt(os_root: Path, receipt: dict[str, Any]) -> Path:
    """Persist the receipt; runs are only trustworthy if they leave evidence."""
    out_dir = os_root / "harness" / "shared_factory" / "06-runs-and-logs" / "docker-reclaim"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = receipt["generated_at"].replace(":", "").replace("-", "")
    path = out_dir / f"{stamp}-{receipt['mode']}.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    return path
