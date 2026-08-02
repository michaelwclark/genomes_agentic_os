"""Read-only, evidence-gated rollout ordering for Agentic OS releases.

This module deliberately orchestrates receipts, not remote hosts.  A host-local
reinstall agent must produce its own release and health evidence; this contract
only decides whether the next host may be released.  It therefore cannot turn a
planning command into an SSH, deployment, or release side effect.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Mapping

from .scaffold import expand_path
from .update_ops import read_structured


API_VERSION = "agentic-os-release-rollout/v1"
HOST_ORDER = ("bigmac", "genomesbox")
_SEMVER = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def load_published_release(path: str | Path) -> dict[str, Any]:
    """Load the compact release receipt consumed by a host-local watcher."""

    receipt_path = expand_path(path)
    release = read_structured(receipt_path)
    if not isinstance(release, dict):
        raise ValueError(f"release receipt is missing or invalid: {receipt_path}")
    version = str(release.get("version") or "").removeprefix("v")
    if not _SEMVER.fullmatch(version):
        raise ValueError("release receipt version must be stable SemVer")
    if release.get("published") is not True or release.get("draft") is True:
        raise ValueError("release receipt must prove a published, non-draft release")
    if release.get("tag") != f"v{version}":
        raise ValueError("release receipt tag must equal v<version>")
    return {**release, "version": version, "tag": f"v{version}"}


def load_rollout_evidence(path: str | Path) -> dict[str, Any]:
    """Load locally collected receipts without reaching either rollout host."""

    evidence_path = expand_path(path)
    evidence = read_structured(evidence_path)
    if not isinstance(evidence, dict):
        raise ValueError(f"rollout evidence is missing or invalid: {evidence_path}")
    hosts = evidence.get("hosts", evidence)
    if not isinstance(hosts, dict):
        raise ValueError("rollout evidence hosts must be a mapping")
    return {host: value for host, value in hosts.items() if isinstance(value, dict)}


def _matches_release(receipt: Mapping[str, Any], release: Mapping[str, Any]) -> bool:
    value = receipt.get("release")
    if not isinstance(value, Mapping):
        return False
    return value.get("tag") == release["tag"] and value.get("version") == release["version"]


def _host_phase(host: str, release: Mapping[str, Any], evidence: Mapping[str, Any]) -> str:
    current = evidence.get(host)
    if not isinstance(current, Mapping):
        return "pending_reinstall"
    reinstall = current.get("reinstall")
    if not isinstance(reinstall, Mapping):
        return "pending_reinstall"
    if reinstall.get("status") != "reinstalled" or not _matches_release(reinstall, release):
        return "reinstall_failed"
    health = current.get("health")
    if not isinstance(health, Mapping):
        return "awaiting_health"
    if health.get("status") != "healthy" or not _matches_release(health, release):
        return "health_failed"
    return "healthy"


def rollout_gate(
    release: Mapping[str, Any],
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the only permitted next step for the fixed two-host rollout."""

    version = str(release.get("version") or "").removeprefix("v")
    if not _SEMVER.fullmatch(version) or release.get("tag") != f"v{version}":
        raise ValueError("release must be normalized by load_published_release")
    if release.get("published") is not True or release.get("draft") is True:
        raise ValueError("release must be published and non-draft")
    host_evidence = evidence or {}
    bigmac = _host_phase("bigmac", release, host_evidence)
    genomesbox = _host_phase("genomesbox", release, host_evidence)
    phases = {"bigmac": bigmac, "genomesbox": genomesbox}

    if bigmac != "healthy" and "genomesbox" in host_evidence:
        return _result(
            release,
            phases,
            "blocked",
            None,
            "genomesbox evidence arrived before bigmac health gate",
        )
    if bigmac == "pending_reinstall":
        return _result(release, phases, "ready", "bigmac", "reinstall bigmac locally")
    if bigmac == "reinstall_failed":
        return _result(release, phases, "blocked", None, "bigmac reinstall receipt is missing, failed, or for a different release")
    if bigmac == "awaiting_health":
        return _result(release, phases, "awaiting_health", "bigmac", "collect a current healthy bigmac receipt before genomesbox")
    if bigmac == "health_failed":
        return _result(release, phases, "blocked", None, "bigmac health gate failed; genomesbox is not permitted")

    if genomesbox == "pending_reinstall":
        return _result(release, phases, "ready", "genomesbox", "bigmac is healthy; reinstall genomesbox locally")
    if genomesbox == "reinstall_failed":
        return _result(release, phases, "blocked", None, "genomesbox reinstall receipt is missing, failed, or for a different release")
    if genomesbox == "awaiting_health":
        return _result(release, phases, "awaiting_health", "genomesbox", "collect a current healthy genomesbox receipt")
    if genomesbox == "health_failed":
        return _result(release, phases, "failed", None, "genomesbox health receipt failed")
    return _result(release, phases, "completed", None, "both hosts passed reinstall and health verification")


def _result(
    release: Mapping[str, Any],
    phases: Mapping[str, str],
    status: str,
    next_host: str | None,
    reason: str,
) -> dict[str, Any]:
    return {
        "api_version": API_VERSION,
        "action": "release-rollout.gate",
        "status": status,
        "release": {"version": release["version"], "tag": release["tag"]},
        "host_order": list(HOST_ORDER),
        "host_phases": dict(phases),
        "next_host": next_host,
        "reason": reason,
        "remote_execution": "not_implemented_by_design",
        "mutated": False,
    }
