"""Read-only, evidence-gated rollout ordering for Agentic OS releases.

This module deliberately orchestrates receipts, not remote hosts.  A host-local
reinstall agent must produce its own release and health evidence; this contract
only decides whether the next host may be released.  It therefore cannot turn a
planning command into an SSH, deployment, or release side effect.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Mapping

import yaml

from .scaffold import expand_path


API_VERSION = "agentic-os-release-rollout/v1"
# The installer ships a generic two-host rollout contract.  Site-specific host
# identifiers belong only in locally collected receipt files, never in package
# defaults or public output.
HOST_ORDER = ("first_host", "second_host")
_SEMVER = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def _load_mapping(path: str | Path, *, label: str) -> dict[str, Any]:
    structured_path = expand_path(path)
    if not structured_path.is_file():
        raise ValueError(f"{label} is missing or invalid: {structured_path}")
    try:
        text = structured_path.read_text(encoding="utf-8")
        data = json.loads(text) if structured_path.suffix == ".json" else yaml.safe_load(text)
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"{label} is missing or invalid: {structured_path}") from exc
    if not isinstance(data, Mapping):
        raise ValueError(f"{label} is missing or invalid: {structured_path}")
    return dict(data)


def load_published_release(path: str | Path) -> dict[str, Any]:
    """Load the compact release receipt consumed by a host-local watcher."""

    release = _load_mapping(path, label="release receipt")
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

    evidence = _load_mapping(path, label="rollout evidence")
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
    first_host = _host_phase("first_host", release, host_evidence)
    second_host = _host_phase("second_host", release, host_evidence)
    phases = {"first_host": first_host, "second_host": second_host}

    if first_host != "healthy" and "second_host" in host_evidence:
        return _result(
            release,
            phases,
            "blocked",
            None,
            "second-host evidence arrived before first-host health gate",
        )
    if first_host == "pending_reinstall":
        return _result(release, phases, "ready", "first_host", "reinstall the first host locally")
    if first_host == "reinstall_failed":
        return _result(release, phases, "blocked", None, "first-host reinstall receipt is missing, failed, or for a different release")
    if first_host == "awaiting_health":
        return _result(release, phases, "awaiting_health", "first_host", "collect a current healthy first-host receipt before the second host")
    if first_host == "health_failed":
        return _result(release, phases, "blocked", None, "first-host health gate failed; the second host is not permitted")

    if second_host == "pending_reinstall":
        return _result(release, phases, "ready", "second_host", "first host is healthy; reinstall the second host locally")
    if second_host == "reinstall_failed":
        return _result(release, phases, "blocked", None, "second-host reinstall receipt is missing, failed, or for a different release")
    if second_host == "awaiting_health":
        return _result(release, phases, "awaiting_health", "second_host", "collect a current healthy second-host receipt")
    if second_host == "health_failed":
        return _result(release, phases, "failed", None, "second-host health receipt failed")
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
