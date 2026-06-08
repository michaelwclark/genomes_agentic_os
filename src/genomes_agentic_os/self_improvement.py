"""Dry-run self-improvement review for installed Agentic OS roots."""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

import yaml

from .lifecycle import TOKEN_SHAPED_VALUE_RE
from .scaffold import expand_path


CONFIG_PATH = "harness/shared_factory/00-control-plane/self-improvement.yml"
OUTPUT_ROOT = "harness/shared_factory/06-runs-and-logs/self-improvement"
MAX_EVIDENCE_FILES = 200
MAX_EVIDENCE_BYTES = 16_000
EVIDENCE_SUFFIXES = {".md", ".txt", ".json", ".jsonl", ".yml", ".yaml", ".log"}
APPROVED_TARGETS = {
    "feature-spec",
    "skill-draft",
    "command-draft",
    "workflow-draft",
    "tool-wrapper-draft",
    "reference-update-plan",
    "doctor-check-draft",
}
SHARED_ARTIFACT_TARGETS = {"skill-draft", "command-draft", "workflow-draft"}
MUTABLE_PROPOSAL_FIELDS = {"updated_at", "cooldown_until", "promotion_status", "approval_record_id"}
SECRET_ENV_ASSIGNMENT_RE = re.compile(
    r"(?im)\b[A-Z][A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API[_]?KEY|PRIVATE[_]?KEY)[A-Z0-9_]*\s*=\s*[^\s\"']+"
)


DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": 1,
    "enabled": False,
    "schedule_mode": "disabled",
    "evidence_roots": [
        {"path": "harness/shared_factory/06-runs-and-logs", "legacy_read_only": False},
        {"path": "harness/shared_factory/05-knowledge", "legacy_read_only": False},
        {"path": "harness/logs", "legacy_read_only": False},
        {"path": "shared_factory", "legacy_read_only": True},
    ],
    "proposal_thresholds": {"minimum_total": 18, "minimum_confidence": 3},
    "cooldowns": {
        "feature-spec": "30d",
        "skill-draft": "14d",
        "command-draft": "14d",
        "workflow-draft": "14d",
        "tool-wrapper-draft": "14d",
        "reference-update-plan": "14d",
        "doctor-check-draft": "14d",
    },
    "output_paths": {
        "runs": f"{OUTPUT_ROOT}/runs",
        "proposals": f"{OUTPUT_ROOT}/proposals",
        "approvals": f"{OUTPUT_ROOT}/approvals",
        "drafts": f"{OUTPUT_ROOT}/drafts",
    },
    "promotion_targets": sorted(APPROVED_TARGETS),
    "approval_required": True,
    "model_review": {"enabled": False},
}


@dataclass
class EvidenceRecord:
    path: Path
    text: str
    redacted_text: str
    redactions: int


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _digest(value: Any, length: int = 16) -> str:
    if isinstance(value, str):
        payload = value
    else:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def _sha256(value: Any) -> str:
    if isinstance(value, str):
        payload = value
    else:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return dict(DEFAULT_CONFIG)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"self-improvement config must be a mapping: {path}")
    merged = dict(DEFAULT_CONFIG)
    merged.update(data)
    return merged


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _duration(value: str | None, default_days: int = 14) -> timedelta:
    if not value:
        return timedelta(days=default_days)
    raw = str(value).strip().lower()
    try:
        if raw.endswith("d"):
            return timedelta(days=int(raw[:-1]))
        if raw.endswith("h"):
            return timedelta(hours=int(raw[:-1]))
        return timedelta(days=int(raw))
    except ValueError:
        return timedelta(days=default_days)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _resolve_root_relative(root: Path, value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"self-improvement path must be root-relative and non-traversing: {value}")
    resolved_root = root.resolve()
    resolved = (resolved_root / candidate).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError(f"self-improvement path escapes installed root: {value}")
    return resolved


def _output_path(root: Path, config: dict[str, Any], key: str) -> Path:
    outputs = config.get("output_paths") or {}
    if not isinstance(outputs, dict) or key not in outputs:
        raise ValueError(f"self-improvement output_paths missing {key!r}")
    value = str(outputs[key])
    if value == "shared_factory" or value.startswith("shared_factory/"):
        raise ValueError(f"self-improvement output path uses legacy top-level shared_factory: {value}")
    if value != OUTPUT_ROOT and not value.startswith(f"{OUTPUT_ROOT}/"):
        raise ValueError(f"self-improvement output path must stay under {OUTPUT_ROOT}: {value}")
    path = _resolve_root_relative(root, value)
    _reject_symlink_ancestors(root, root / value)
    return path


def _reject_symlink_ancestors(root: Path, path: Path) -> None:
    resolved_root = root.resolve()
    try:
        relative_parts = path.relative_to(root).parts
    except ValueError:
        relative_parts = path.parts
    probe = resolved_root
    for part in relative_parts:
        probe = probe / part
        if probe.exists() and probe.is_symlink():
            raise ValueError(f"self-improvement output path contains symlink ancestor: {probe}")


def _validate_output_paths(root: Path, config: dict[str, Any]) -> None:
    for key in ("runs", "proposals", "approvals", "drafts"):
        _output_path(root, config, key)


def _ensure_safe_dir(root: Path, directory: Path) -> Path:
    resolved_root = root.resolve()
    _reject_symlink_ancestors(root, directory)
    directory.mkdir(parents=True, exist_ok=True)
    current = directory.resolve()
    if current != resolved_root and resolved_root not in current.parents:
        raise ValueError(f"self-improvement output directory escapes installed root: {directory}")
    relative_parts = current.relative_to(resolved_root).parts
    probe = resolved_root
    for part in relative_parts:
        probe = probe / part
        if probe.is_symlink():
            raise ValueError(f"self-improvement output directory contains symlink ancestor: {probe}")
    return current


def _safe_child(root: Path, directory: Path, filename: str) -> Path:
    if "/" in filename or "\\" in filename or ".." in Path(filename).parts:
        raise ValueError(f"unsafe self-improvement filename: {filename}")
    real_dir = _ensure_safe_dir(root, directory)
    target = (real_dir / filename).resolve()
    if target.parent != real_dir:
        raise ValueError(f"self-improvement target escapes output directory: {filename}")
    return target


def _assert_safe_payload(content: str) -> None:
    if TOKEN_SHAPED_VALUE_RE.search(content):
        raise ValueError("self-improvement write refused: token-shaped value detected in output")
    if SECRET_ENV_ASSIGNMENT_RE.search(content):
        raise ValueError("self-improvement write refused: secret environment assignment detected in output")


def _atomic_write_text(root: Path, path: Path, content: str) -> None:
    _assert_safe_payload(content)
    real_parent = _ensure_safe_dir(root, path.parent)
    target = path.resolve()
    if target.parent != real_parent:
        raise ValueError(f"self-improvement target escapes output directory: {path}")
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=real_parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _atomic_write_yaml(root: Path, path: Path, data: dict[str, Any]) -> None:
    payload = yaml.safe_dump(data, sort_keys=False)
    _atomic_write_text(root, path, payload)


@contextmanager
def _proposal_lock(root: Path, directory: Path, lock_id: str):
    lock_path = _safe_child(root, directory, f"{lock_id}.lock")
    fd: int | None = None
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, _now().encode("utf-8"))
        yield
    except FileExistsError as exc:
        raise ValueError(f"self-improvement proposal lock is held: {lock_path}") from exc
    finally:
        if fd is not None:
            os.close(fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _configured_evidence_roots(root: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    entries = config.get("evidence_roots") or []
    if not isinstance(entries, list):
        raise ValueError("self-improvement evidence_roots must be a list")
    resolved_entries: list[dict[str, Any]] = []
    for entry in entries:
        if isinstance(entry, str):
            path_value = entry
            legacy_read_only = False
        elif isinstance(entry, dict):
            path_value = str(entry.get("path") or "")
            legacy_read_only = bool(entry.get("legacy_read_only", False))
        else:
            raise ValueError("self-improvement evidence root entries must be strings or mappings")
        if not path_value:
            raise ValueError("self-improvement evidence root missing path")
        resolved = _resolve_root_relative(root, path_value)
        if path_value == "shared_factory" and not legacy_read_only:
            raise ValueError("legacy top-level shared_factory evidence root must be marked legacy_read_only")
        resolved_entries.append(
            {
                "path": path_value,
                "resolved": resolved,
                "exists": resolved.exists(),
                "legacy_read_only": legacy_read_only,
            }
        )
    return resolved_entries


def _evidence_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    if path.is_file():
        return [path] if path.suffix.lower() in EVIDENCE_SUFFIXES else []
    files = []
    for candidate in sorted(path.rglob("*")):
        if len(files) >= MAX_EVIDENCE_FILES:
            break
        if not candidate.is_file():
            continue
        if OUTPUT_ROOT in candidate.as_posix():
            continue
        if candidate.suffix.lower() in EVIDENCE_SUFFIXES:
            files.append(candidate)
    return files


def _redact(text: str) -> tuple[str, int]:
    redacted, count = TOKEN_SHAPED_VALUE_RE.subn("[REDACTED_SECRET]", text)
    redacted, env_count = SECRET_ENV_ASSIGNMENT_RE.subn("[REDACTED_SECRET_ENV_ASSIGNMENT]", redacted)
    count += env_count
    return redacted, count


def _collect_evidence(evidence_roots: list[dict[str, Any]]) -> list[EvidenceRecord]:
    records: list[EvidenceRecord] = []
    for entry in evidence_roots:
        for path in _evidence_files(entry["resolved"]):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")[:MAX_EVIDENCE_BYTES]
            except OSError:
                continue
            redacted, redactions = _redact(text)
            records.append(EvidenceRecord(path=path, text=text, redacted_text=redacted, redactions=redactions))
            if len(records) >= MAX_EVIDENCE_FILES:
                return records
    return records


def _line_counts(records: list[EvidenceRecord]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for record in records:
        for raw_line in record.redacted_text.splitlines():
            line = " ".join(raw_line.strip().lower().split())
            if len(line) < 20:
                continue
            if line.startswith(("#", "---", "|")):
                continue
            counter[line] += 1
    return counter


def _keyword_hits(records: list[EvidenceRecord], keywords: tuple[str, ...]) -> int:
    return sum(
        record.redacted_text.lower().count(keyword)
        for record in records
        for keyword in keywords
    )


def _score(*, frequency: int, severity: int, reuse: int, confidence: int, blast_radius: int, staleness: int) -> dict[str, int]:
    return {
        "frequency": frequency,
        "severity": severity,
        "reuse": reuse,
        "confidence": confidence,
        "blast_radius": blast_radius,
        "staleness": staleness,
        "total": frequency + severity + reuse + confidence + blast_radius + staleness,
    }


def _findings(root: Path, records: list[EvidenceRecord]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    repeated = [(line, count) for line, count in _line_counts(records).most_common(5) if count >= 2]
    if repeated:
        line, count = repeated[0]
        findings.append(
            {
                "type": "repeated_evidence",
                "title": "Repeated evidence pattern",
                "summary": f"{count} matching evidence lines suggest recurring operator friction.",
                "evidence": line[:220],
                "score": _score(frequency=3, severity=2, reuse=3, confidence=3, blast_radius=5, staleness=3),
            }
        )

    failure_hits = _keyword_hits(records, ("validation failed", "test failed", "failed", "blocked", "error:"))
    if failure_hits >= 2:
        findings.append(
            {
                "type": "recurring_failure",
                "title": "Recurring failure signal",
                "summary": f"{failure_hits} failure-oriented terms appeared in local evidence.",
                "evidence": _first_locator(root, records),
                "score": _score(frequency=3, severity=3, reuse=3, confidence=3, blast_radius=5, staleness=3),
            }
        )

    manual_hits = _keyword_hits(records, ("manual command", "repeated manual", "copy/paste", "run this again", "workflow gap"))
    if manual_hits >= 1:
        findings.append(
            {
                "type": "manual_workflow",
                "title": "Manual workflow improvement candidate",
                "summary": f"{manual_hits} manual-workflow signals appeared in local evidence.",
                "evidence": _first_locator(root, records),
                "score": _score(frequency=2, severity=2, reuse=3, confidence=3, blast_radius=5, staleness=3),
            }
        )
    return findings


def _first_locator(root: Path, records: list[EvidenceRecord]) -> str:
    if not records:
        return "none"
    try:
        return records[0].path.relative_to(root).as_posix()
    except ValueError:
        return records[0].path.as_posix()


def _record_locator(root: Path, record: EvidenceRecord) -> str:
    try:
        return record.path.relative_to(root).as_posix()
    except ValueError:
        return record.path.as_posix()


def _candidate_evidence(root: Path, records: list[EvidenceRecord], finding: dict[str, Any]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    finding_text = str(finding.get("evidence") or "")
    for record in records[:10]:
        excerpt = ""
        for line in record.redacted_text.splitlines():
            normalized = " ".join(line.strip().split())
            if not normalized:
                continue
            if finding_text and finding_text[:80].lower() in normalized.lower():
                excerpt = normalized[:300]
                break
            if not excerpt:
                excerpt = normalized[:300]
        if excerpt:
            evidence.append(
                {
                    "locator": _record_locator(root, record),
                    "excerpt": excerpt,
                    "signal_type": finding.get("type") or "deterministic",
                    "redactions": record.redactions,
                }
            )
        if len(evidence) >= 3:
            break
    if not evidence and finding_text:
        evidence.append({"locator": "deterministic", "excerpt": finding_text[:300], "signal_type": finding.get("type") or "deterministic"})
    return evidence


def _recommended_artifact(finding: dict[str, Any]) -> tuple[str, str]:
    finding_type = str(finding.get("type") or "")
    if finding_type == "manual_workflow":
        return "workflow-draft", "Draft a shared workflow or automation packet for the repeated manual sequence."
    if finding_type == "recurring_failure":
        return "doctor-check-draft", "Draft a validation or doctor check for the recurring failure signal."
    return "feature-spec", "Draft a feature packet for the repeated evidence pattern."


def _canonical_proposal_content(proposal: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in proposal.items() if key not in MUTABLE_PROPOSAL_FIELDS}


def _proposal_content_hash(proposal: dict[str, Any]) -> str:
    content = _canonical_proposal_content(proposal)
    content.pop("content_hash", None)
    return _sha256(content)


def _proposal_validation_hash(proposal: dict[str, Any]) -> str:
    return _sha256(proposal.get("validation_plan") or [])


def _control_plane_hash(config: dict[str, Any]) -> str:
    return _sha256(config)


def _proposal_from_finding(root: Path, records: list[EvidenceRecord], finding: dict[str, Any]) -> dict[str, Any]:
    recommended_artifact, recommendation = _recommended_artifact(finding)
    evidence = _candidate_evidence(root, records, finding)
    title = str(finding.get("title") or "Self-improvement proposal")
    opportunity_type = str(finding.get("type") or "deterministic")
    primary_cluster = "|".join(str(item.get("locator")) for item in evidence) or title
    dedupe_key = _sha256(f"{opportunity_type}|{title.lower()}|{recommended_artifact}|{primary_cluster}")
    proposal_id = "si-" + _digest(dedupe_key, 12)
    now = _now()
    proposal = {
        "schema_version": 1,
        "proposal_id": proposal_id,
        "created_at": now,
        "updated_at": now,
        "opportunity_type": opportunity_type,
        "title": title,
        "summary": finding.get("summary") or title,
        "scope": "installed_os",
        "evidence": evidence,
        "deterministic_findings": [finding],
        "model_recommendation": None,
        "score": finding.get("score") or {},
        "dedupe_key": dedupe_key,
        "cooldown_until": None,
        "recommended_artifact": recommended_artifact,
        "approval_requirement": "operator_required",
        "validation_plan": [
            "Review cited evidence and confirm the pattern is recurring.",
            "Implement draft artifact only; do not mutate live shared surfaces.",
            "Run agentic-os validate and focused tests before promotion.",
        ],
        "reference_migration_plan": [],
        "redaction_status": "redacted" if any(item.get("redactions", 0) for item in evidence) else "clean",
        "content_hash": "",
        "promotion_status": "proposed",
        "approval_record_id": None,
    }
    proposal["content_hash"] = _proposal_content_hash(proposal)
    return proposal


def _proposal_file(root: Path, config: dict[str, Any], proposal_id: str) -> Path:
    return _safe_child(root, _output_path(root, config, "proposals"), f"{proposal_id}.yml")


def _approval_file(root: Path, config: dict[str, Any], approval_id: str) -> Path:
    return _safe_child(root, _output_path(root, config, "approvals"), f"{approval_id}.yml")


def _run_file(root: Path, config: dict[str, Any], run_id: str) -> Path:
    return _safe_child(root, _output_path(root, config, "runs"), f"{run_id}.yml")


def _safe_descendant(root: Path, directory: Path, *parts: str) -> Path:
    if not parts:
        raise ValueError("self-improvement target requires a relative child path")
    for part in parts:
        candidate = Path(part)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"unsafe self-improvement child path: {part}")
    real_dir = _ensure_safe_dir(root, directory)
    target = (real_dir / Path(*parts)).resolve()
    if target != real_dir and real_dir not in target.parents:
        raise ValueError(f"self-improvement target escapes output directory: {target}")
    _reject_symlink_ancestors(root, target.parent)
    return target


def _proposal_files(root: Path, config: dict[str, Any]) -> list[Path]:
    directory = _output_path(root, config, "proposals")
    if not directory.exists():
        return []
    return sorted(path for path in directory.glob("*.yml") if path.is_file())


def _load_proposal(root: Path, config: dict[str, Any], proposal_id: str) -> dict[str, Any]:
    path = _proposal_file(root, config, proposal_id)
    if not path.is_file():
        raise ValueError(f"unknown self-improvement proposal: {proposal_id}")
    proposal = _read_yaml(path)
    if proposal.get("proposal_id") != proposal_id:
        raise ValueError(f"proposal id mismatch: {path}")
    _validate_proposal(proposal)
    return proposal


def _load_approval(root: Path, config: dict[str, Any], approval_id: str) -> dict[str, Any]:
    path = _approval_file(root, config, approval_id)
    if not path.is_file():
        raise ValueError(f"unknown self-improvement approval: {approval_id}")
    approval = _read_yaml(path)
    if approval.get("approval_id") != approval_id:
        raise ValueError(f"approval id mismatch: {path}")
    return approval


def _validate_proposal(proposal: dict[str, Any]) -> None:
    required = {
        "proposal_id",
        "evidence",
        "recommended_artifact",
        "approval_requirement",
        "validation_plan",
        "redaction_status",
        "content_hash",
        "promotion_status",
    }
    missing = sorted(key for key in required if proposal.get(key) in (None, "", []))
    if missing:
        raise ValueError(f"self-improvement proposal missing required fields: {', '.join(missing)}")
    if _proposal_content_hash(proposal) != proposal.get("content_hash"):
        raise ValueError(f"self-improvement proposal content hash mismatch: {proposal.get('proposal_id')}")


def _validate_proposal_for_target(proposal: dict[str, Any], target: str) -> None:
    _validate_proposal(proposal)
    if target not in APPROVED_TARGETS:
        raise ValueError(f"unsupported self-improvement promotion target: {target}")
    recommended = str(proposal.get("recommended_artifact") or "")
    if recommended and recommended != target:
        raise ValueError(f"proposal recommends {recommended}, not {target}")
    if proposal.get("approval_requirement") != "operator_required":
        raise ValueError("self-improvement proposals require operator approval in v1")
    if target in SHARED_ARTIFACT_TARGETS and not proposal.get("reference_migration_plan"):
        raise ValueError(f"{target} approval requires a reference_migration_plan")


def _merge_evidence(existing: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    seen = {
        (str(item.get("locator")), str(item.get("excerpt")))
        for item in existing.get("evidence") or []
        if isinstance(item, dict)
    }
    evidence = list(existing.get("evidence") or [])
    for item in candidate.get("evidence") or []:
        key = (str(item.get("locator")), str(item.get("excerpt")))
        if key not in seen:
            evidence.append(item)
            seen.add(key)
    merged["evidence"] = evidence
    merged["deterministic_findings"] = candidate.get("deterministic_findings") or existing.get("deterministic_findings") or []
    merged["score"] = candidate.get("score") or existing.get("score") or {}
    merged["updated_at"] = _now()
    merged["promotion_status"] = "proposed"
    merged["approval_record_id"] = None
    merged["content_hash"] = _proposal_content_hash(merged)
    return merged


def _cooldown_active(proposal: dict[str, Any], now: datetime | None = None) -> bool:
    until = _parse_time(proposal.get("cooldown_until"))
    return bool(until and until > (now or datetime.now(timezone.utc)))


def _cooldown_until(config: dict[str, Any], target: str) -> str:
    cooldowns = config.get("cooldowns") or {}
    duration = _duration(str(cooldowns.get(target) or ""), default_days=14) if isinstance(cooldowns, dict) else _duration(None)
    return (datetime.now(timezone.utc) + duration).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_proposals(root: Path, config: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    proposals_dir = _output_path(root, config, "proposals")
    _ensure_safe_dir(root, proposals_dir)
    existing_by_dedupe = {}
    for path in _proposal_files(root, config):
        proposal = _read_yaml(path)
        if proposal.get("dedupe_key"):
            existing_by_dedupe[str(proposal["dedupe_key"])] = proposal

    written: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    for candidate in candidates:
        existing = existing_by_dedupe.get(str(candidate.get("dedupe_key")))
        proposal = candidate
        if existing:
            status = str(existing.get("promotion_status") or "proposed")
            if status == "rejected" and _cooldown_active(existing):
                suppressed.append(
                    {
                        "proposal_id": existing.get("proposal_id"),
                        "reason": "cooldown_active",
                        "cooldown_until": existing.get("cooldown_until"),
                    }
                )
                continue
            if status == "rejected":
                suppressed.append({"proposal_id": existing.get("proposal_id"), "reason": "existing_rejected"})
                continue
            if status in {"approved", "drafted"}:
                suppressed.append({"proposal_id": existing.get("proposal_id"), "reason": f"existing_{status}"})
                continue
            proposal = _merge_evidence(existing, candidate)

        proposal_id = str(proposal["proposal_id"])
        with _proposal_lock(root, proposals_dir, proposal_id):
            path = _proposal_file(root, config, proposal_id)
            _atomic_write_yaml(root, path, proposal)
        existing_by_dedupe[str(proposal["dedupe_key"])] = proposal
        written.append({"proposal_id": proposal_id, "path": str(_proposal_file(root, config, proposal_id).relative_to(root))})
    return {"written": written, "suppressed": suppressed}


def run_self_improvement(root: str | Path, *, dry_run: bool = True) -> dict[str, Any]:
    os_root = expand_path(root)
    config_path = os_root / CONFIG_PATH
    config = _load_yaml(config_path)
    evidence_roots = _configured_evidence_roots(os_root, config)
    records = _collect_evidence(evidence_roots)
    findings = _findings(os_root, records)
    candidates = [_proposal_from_finding(os_root, records, finding) for finding in findings]
    redactions = sum(record.redactions for record in records)
    result: dict[str, Any] = {
        "ok": True,
        "mode": "dry-run" if dry_run else "apply",
        "root": os_root,
        "config": config_path,
        "writes": [],
        "model_review": {
            "enabled": False,
            "reason": "no-tool model reviewer sandbox is not configured in P1",
        },
        "evidence_roots": evidence_roots,
        "evidence_files": len(records),
        "redactions": redactions,
        "findings": findings,
        "proposal_candidates": candidates,
        "thresholds": config.get("proposal_thresholds") or {},
    }
    if dry_run:
        return result

    _validate_output_paths(os_root, config)
    run_id = f"{_stamp()}-{_digest({'findings': [finding.get('type') for finding in findings], 'created_at': datetime.now(timezone.utc).isoformat()}, 8)}"
    proposal_result = _write_proposals(os_root, config, candidates)
    run_record = {
        "schema_version": 1,
        "run_id": run_id,
        "started_at": _now(),
        "completed_at": _now(),
        "mode": "apply",
        "config_ref": CONFIG_PATH,
        "evidence_roots": [
            {key: value for key, value in entry.items() if key != "resolved"}
            for entry in evidence_roots
        ],
        "deterministic_findings": findings,
        "model_review": result["model_review"],
        "redaction": {"replacements": redactions, "refused": False},
        "proposal_candidates": [candidate["proposal_id"] for candidate in candidates],
        "writes": proposal_result["written"],
        "suppressed": proposal_result["suppressed"],
    }
    run_path = _run_file(os_root, config, run_id)
    _atomic_write_yaml(os_root, run_path, run_record)
    result["run_id"] = run_id
    result["writes"] = [{"type": "run", "path": str(run_path.relative_to(os_root))}, *proposal_result["written"]]
    result["suppressed"] = proposal_result["suppressed"]
    return result


def self_improvement_status(root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    config = _load_yaml(os_root / CONFIG_PATH)
    proposals = [_read_yaml(path) for path in _proposal_files(os_root, config)]
    counts = Counter(str(proposal.get("promotion_status") or "unknown") for proposal in proposals)
    runs_dir = _output_path(os_root, config, "runs")
    latest_run = None
    if runs_dir.exists():
        runs = sorted(path for path in runs_dir.glob("*.yml") if path.is_file())
        latest_run = str(runs[-1].relative_to(os_root)) if runs else None
    return {
        "action": "status",
        "root": os_root,
        "enabled": bool(config.get("enabled")),
        "schedule_mode": config.get("schedule_mode"),
        "latest_run": latest_run,
        "proposal_counts": dict(sorted(counts.items())),
    }


def list_self_improvement_proposals(root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    config = _load_yaml(os_root / CONFIG_PATH)
    proposals = [_read_yaml(path) for path in _proposal_files(os_root, config)]
    rows = [
        {
            "proposal_id": proposal.get("proposal_id"),
            "status": proposal.get("promotion_status"),
            "recommended_artifact": proposal.get("recommended_artifact"),
            "title": proposal.get("title"),
            "score": (proposal.get("score") or {}).get("total"),
        }
        for proposal in proposals
    ]
    return {"action": "list", "root": os_root, "proposals": rows}


def show_self_improvement_proposal(root: str | Path, proposal_id: str) -> dict[str, Any]:
    os_root = expand_path(root)
    config = _load_yaml(os_root / CONFIG_PATH)
    proposal = _load_proposal(os_root, config, proposal_id)
    return {"action": "show", "root": os_root, "proposal": proposal}


def approve_self_improvement_proposal(root: str | Path, proposal_id: str, *, target: str, approver: str = "local_operator") -> dict[str, Any]:
    if target not in APPROVED_TARGETS:
        raise ValueError(f"unsupported self-improvement approval target: {target}")
    os_root = expand_path(root)
    config = _load_yaml(os_root / CONFIG_PATH)
    _validate_output_paths(os_root, config)
    if target not in (config.get("promotion_targets") or sorted(APPROVED_TARGETS)):
        raise ValueError(f"self-improvement target is not allowed by control plane: {target}")
    proposal = _load_proposal(os_root, config, proposal_id)
    _validate_proposal_for_target(proposal, target)
    if target in SHARED_ARTIFACT_TARGETS and not proposal.get("reference_migration_plan"):
        raise ValueError("shared-artifact proposal approval requires reference_migration_plan")
    proposals_dir = _output_path(os_root, config, "proposals")
    approvals_dir = _output_path(os_root, config, "approvals")
    content_hash = _proposal_content_hash(proposal)
    validation_hash = _proposal_validation_hash(proposal)
    control_hash = _control_plane_hash(config)
    approval = {
        "schema_version": 1,
        "approval_id": _sha256(f"{proposal_id}|{target}|{content_hash}|{validation_hash}|{control_hash}"),
        "proposal_id": proposal_id,
        "proposal_content_hash": content_hash,
        "approved_target": target,
        "approved_at": _now(),
        "approver": approver,
        "validation_hash": validation_hash,
        "control_plane_hash": control_hash,
    }
    approval_id = str(approval["approval_id"]).replace("sha256:", "approval-")[:80]
    approval["approval_id"] = approval_id
    with _proposal_lock(os_root, proposals_dir, proposal_id):
        proposal = _load_proposal(os_root, config, proposal_id)
        _validate_proposal_for_target(proposal, target)
        if _proposal_content_hash(proposal) != content_hash:
            raise ValueError("proposal changed before approval could be recorded")
        proposal["promotion_status"] = "approved"
        proposal["approval_record_id"] = approval_id
        proposal["updated_at"] = _now()
        _assert_safe_payload(yaml.safe_dump(proposal, sort_keys=False))
        _atomic_write_yaml(os_root, _approval_file(os_root, config, approval_id), approval)
        _atomic_write_yaml(os_root, _proposal_file(os_root, config, proposal_id), proposal)
    return {
        "action": "approve",
        "root": os_root,
        "proposal_id": proposal_id,
        "approval_id": approval_id,
        "approval_path": str(_approval_file(os_root, config, approval_id).relative_to(os_root)),
        "approved_target": target,
        "approvals_dir": str(approvals_dir.relative_to(os_root)),
    }


def reject_self_improvement_proposal(root: str | Path, proposal_id: str) -> dict[str, Any]:
    os_root = expand_path(root)
    config = _load_yaml(os_root / CONFIG_PATH)
    _validate_output_paths(os_root, config)
    proposal = _load_proposal(os_root, config, proposal_id)
    cooldowns = config.get("cooldowns") or {}
    cooldown = _duration(str(cooldowns.get(proposal.get("recommended_artifact")) or "14d"))
    cooldown_until = (datetime.now(timezone.utc) + cooldown).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    proposals_dir = _output_path(os_root, config, "proposals")
    with _proposal_lock(os_root, proposals_dir, proposal_id):
        proposal["promotion_status"] = "rejected"
        proposal["approval_record_id"] = None
        proposal["cooldown_until"] = cooldown_until
        proposal["updated_at"] = _now()
        proposal["content_hash"] = _proposal_content_hash(proposal)
        _atomic_write_yaml(os_root, _proposal_file(os_root, config, proposal_id), proposal)
    return {"action": "reject", "root": os_root, "proposal_id": proposal_id, "cooldown_until": cooldown_until}


def _draft_dir(root: Path, config: dict[str, Any], proposal_id: str) -> Path:
    return _safe_child(root, _output_path(root, config, "drafts"), proposal_id)


def _draft_payloads(proposal: dict[str, Any], target: str) -> dict[str, str]:
    title = str(proposal.get("title") or proposal.get("proposal_id"))
    summary = str(proposal.get("summary") or "")
    proposal_id = str(proposal.get("proposal_id"))
    if target == "feature-spec":
        return {
            "feature.yml": yaml.safe_dump(
                {
                    "id": proposal_id,
                    "title": title,
                    "status": "draft",
                    "source": "self-improvement",
                    "proposal_id": proposal_id,
                },
                sort_keys=False,
            ),
            "SPEC.md": f"# {title}\n\n{summary}\n\n## Evidence\n\n{_evidence_markdown(proposal)}\n",
            "PLAN.md": "# Plan\n\n- Review the proposal evidence.\n- Implement the draft behind normal validation gates.\n",
            "NEXT.md": "# Next\n\nReview this self-improvement draft and decide whether to promote it into active feature work.\n",
        }
    return {
        "README.md": f"# {title}\n\n{summary}\n\nTarget: `{target}`\n\n## Evidence\n\n{_evidence_markdown(proposal)}\n",
        "validation-plan.md": "\n".join(f"- {item}" for item in proposal.get("validation_plan") or []) + "\n",
    }


def _evidence_markdown(proposal: dict[str, Any]) -> str:
    rows = []
    for item in proposal.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        rows.append(f"- `{item.get('locator', 'unknown')}`: {item.get('excerpt', '')}")
    return "\n".join(rows) or "- No evidence recorded."


def promote_self_improvement_proposal(root: str | Path, proposal_id: str, *, target: str) -> dict[str, Any]:
    if target not in APPROVED_TARGETS:
        raise ValueError(f"unsupported self-improvement promotion target: {target}")
    os_root = expand_path(root)
    config = _load_yaml(os_root / CONFIG_PATH)
    _validate_output_paths(os_root, config)
    if target not in (config.get("promotion_targets") or sorted(APPROVED_TARGETS)):
        raise ValueError(f"self-improvement target is not allowed by control plane: {target}")
    proposal = _load_proposal(os_root, config, proposal_id)
    _validate_proposal_for_target(proposal, target)
    if proposal.get("promotion_status") != "approved":
        raise ValueError(f"proposal must be approved before promotion: {proposal_id}")
    approval_id = str(proposal.get("approval_record_id") or "")
    if not approval_id:
        raise ValueError(f"proposal missing approval record id: {proposal_id}")
    approval_path = _approval_file(os_root, config, approval_id)
    if not approval_path.is_file():
        raise ValueError(f"approval record is missing: {approval_id}")
    approval = _read_yaml(approval_path)
    if approval.get("approved_target") != target:
        raise ValueError("requested promotion target differs from approved target")
    if approval.get("proposal_content_hash") != _proposal_content_hash(proposal):
        raise ValueError("proposal content differs from approved hash")
    if approval.get("validation_hash") != _proposal_validation_hash(proposal):
        raise ValueError("proposal validation differs from approved hash")
    if approval.get("control_plane_hash") != _control_plane_hash(config):
        raise ValueError("self-improvement control plane differs from approval time")

    drafts_dir = _draft_dir(os_root, config, proposal_id)
    _ensure_safe_dir(os_root, drafts_dir)
    written = []
    for filename, content in _draft_payloads(proposal, target).items():
        path = _safe_child(os_root, drafts_dir, filename)
        if path.exists():
            raise ValueError(f"draft target already exists: {path}")
        _atomic_write_text(os_root, path, content)
        written.append(str(path.relative_to(os_root)))
    proposal["promotion_status"] = "drafted"
    proposal["updated_at"] = _now()
    _atomic_write_yaml(os_root, _proposal_file(os_root, config, proposal_id), proposal)
    return {"action": "promote", "root": os_root, "proposal_id": proposal_id, "target": target, "draft_paths": written}


def format_self_improvement_result(result: dict[str, Any]) -> str:
    action = result.get("action")
    if action == "status":
        lines = [
            "Self Improvement Status",
            f"root: {result['root']}",
            f"enabled: {result['enabled']}",
            f"schedule_mode: {result['schedule_mode']}",
            f"latest_run: {result['latest_run'] or 'none'}",
            "proposal_counts:",
        ]
        counts = result.get("proposal_counts") or {}
        if not counts:
            lines.append("- none")
        else:
            lines.extend(f"- {status}: {count}" for status, count in counts.items())
        return "\n".join(lines)

    if action == "list":
        lines = ["Self Improvement Proposals"]
        proposals = result.get("proposals") or []
        if not proposals:
            lines.append("- none")
        for proposal in proposals:
            lines.append(
                f"- {proposal['proposal_id']} [{proposal['status']}] "
                f"{proposal['recommended_artifact']} score={proposal['score']}: {proposal['title']}"
            )
        return "\n".join(lines)

    if action == "show":
        return yaml.safe_dump(result["proposal"], sort_keys=False)

    if action in {"approve", "reject", "promote"}:
        lines = [f"Self Improvement {str(action).title()}"]
        for key, value in result.items():
            if key in {"action", "root"}:
                continue
            lines.append(f"{key}: {value}")
        return "\n".join(lines)

    lines = [
        "Self Improvement Dry Run" if result["mode"] == "dry-run" else "Self Improvement Apply",
        f"root: {result['root']}",
        f"config: {result['config']}",
        "writes: none" if not result.get("writes") else "writes:",
        f"evidence_files: {result['evidence_files']}",
        f"redactions: {result['redactions']}",
        f"model_review: disabled ({result['model_review']['reason']})",
        "",
        "Evidence roots:",
    ]
    for entry in result["evidence_roots"]:
        status = "present" if entry["exists"] else "missing"
        legacy = " legacy_read_only" if entry["legacy_read_only"] else ""
        lines.append(f"- {entry['path']}: {status}{legacy}")

    lines.extend(["", "Deterministic findings:"])
    findings = result["findings"]
    if not findings:
        lines.append("- none above dry-run reporting threshold")
    for finding in findings:
        score = finding["score"]
        lines.append(f"- {finding['title']} [{finding['type']}]")
        lines.append(f"  summary: {finding['summary']}")
        lines.append(f"  evidence: {finding['evidence']}")
        lines.append(
            "  score: "
            f"total={score['total']} "
            f"frequency={score['frequency']} "
            f"severity={score['severity']} "
            f"reuse={score['reuse']} "
            f"confidence={score['confidence']} "
            f"blast_radius={score['blast_radius']} "
            f"staleness={score['staleness']}"
        )

    lines.append("")
    if result["mode"] == "dry-run":
        lines.extend(["Proposal writes: disabled in dry-run", "Next step: rerun with --apply to write gated proposal files."])
    else:
        lines.append("Proposal writes:")
        writes = [write for write in result.get("writes") or [] if write.get("proposal_id")]
        if not writes:
            lines.append("- none")
        else:
            lines.extend(f"- {write['proposal_id']}: {write['path']}" for write in writes)
        suppressed = result.get("suppressed") or []
        if suppressed:
            lines.append("Suppressed:")
            lines.extend(f"- {item.get('proposal_id')}: {item.get('reason')}" for item in suppressed)
    return "\n".join(lines)
