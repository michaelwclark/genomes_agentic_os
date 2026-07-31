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

from .config_ops import install_config
from . import notion_api
from .lifecycle import TOKEN_SHAPED_VALUE_RE
from .runtime_backend import patch_runtime_queue_item, runtime_queue_items
from .scaffold import expand_path
from .validate import validate_root


CONFIG_PATH = "harness/shared_factory/00-control-plane/self-improvement.yml"
OUTPUT_ROOT = "harness/shared_factory/06-runs-and-logs/self-improvement"
MORNING_REPORT_ROOT = f"{OUTPUT_ROOT}/morning-reports"
RUN_QUEUE_PATH = "harness/shared_factory/00-control-plane/run-queue.yml"
NOTION_RUNTIME_MANIFEST = ".notion-runtime-tracking/manifest.yml"
NOTION_SELF_IMPROVEMENT_DB = "Self Improvement"
NOTION_TOKEN_ENV = "GENOMES_NOTION_PAT"
NOTION_REPORT_PARENT_TITLE = "Genome's Agentic OS"
NOTION_REPORTS_PAGE_TITLE = "Self Improvement Reports"
ACTION_OUTPUT_ROOT = f"{OUTPUT_ROOT}/actions"
NIGHTLY_APPLY_ROOT = f"{OUTPUT_ROOT}/nightly-apply"
# Per-improvement feature-toggle ledger: which auto-implemented improvements are
# live, which artifact files they registered, and where disabled artifacts were
# parked so a toggle-on can restore them.
SI_TOGGLES_PATH = "harness/shared_factory/00-control-plane/self-improvement-toggles.yml"
SI_DISABLED_ROOT = f"{OUTPUT_ROOT}/disabled"
# OS-relative work-item packet that owns continuous self-improvement work.
# Lives under the shared factory so every install has a stable home for it.
SELF_IMPROVEMENT_WORK_ITEM = "harness/shared_factory/02-projects/genomes_agentic_os/work-items/017_self_improvement_v2_continuous_flywheel"
STALE_QUEUE_GRACE = timedelta(hours=24)
# 🧭 OS Work Intake Notion database that receives queued self-improvement work.
WORK_INTAKE_DB_ID = "c442dd56a24340f0880acfd195f34225"
# Notification bridge used to emit one summary alert per nightly-apply run.
NOTIFY_BIN = "harness/bin/agentic-os-notify"
NIGHTLY_APPLY_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "auto_approve": {"classes": ["doctor-check-draft"], "min_score": 20, "max_per_night": 3},
    # Per-class feature toggles for the autonomous implementation lane. `classes`
    # maps artifact class -> bool; only classes explicitly set to true are queued
    # into the auto_dev worker lane after approve+promote. Disabled by default.
    "auto_implement": {"enabled": False, "classes": {}, "max_per_night": 2},
    "queue_target": "work_intake",
    "notify_source": "automation.self_improvement",
    "stale_after_days": 7,
}
MAX_EVIDENCE_FILES = 400
MAX_EVIDENCE_FILES_PER_ROOT = 40
MAX_EVIDENCE_BYTES = 16_000
# Recency window for evidence sampling: files whose mtime is older than this many
# days are never scanned, so stale transcripts cannot regenerate old proposals
# forever. Overridable via the `evidence_max_age_days` control-plane key.
EVIDENCE_MAX_AGE_DAYS_DEFAULT = 7
# Lines carrying this marker are test-fixture noise, never operator evidence.
# Test fixtures stamp it on their synthetic failure strings so leaked fixture
# text echoed through harness-run transcripts can never score as evidence.
TEST_FIXTURE_MARKER = "test-fixture"
EVIDENCE_SUFFIXES = {".md", ".txt", ".json", ".jsonl", ".yml", ".yaml", ".log"}
ACTIONABLE_EVIDENCE_TERMS = (
    "blocked",
    "failed",
    "failure",
    "error",
    "manual",
    "missing",
    "needs",
    "unsupported",
    "duplicate",
    "stale",
    "workaround",
    "workflow gap",
    "operator friction",
    "queue",
)
LOW_VALUE_EVIDENCE_FIELDS = {
    "id",
    "run_id",
    "queue_item_id",
    "proposal_id",
    "approval_id",
    "content_hash",
    "dedupe_key",
    "created_at",
    "updated_at",
    "started_at",
    "finished_at",
    "completed_at",
    "due_at",
    "idempotency_key",
    "root",
    "path",
    "log",
    "dispatch_log",
    "evidence",
    "dry_run",
    "external_effect",
}
AGENT_LAYER_FILES = {"config.toml", "AGENTS.md", "CLAUDE.md", "ROUTER.md", "CONTEXT.md", "RULES.md", "TOOLS.md", "MEMORY.md"}
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
        {"path": "harness/logs/conversations", "legacy_read_only": False},
        {"path": "harness/skills", "legacy_read_only": False},
        {"path": "harness/commands", "legacy_read_only": False},
        {"path": "harness/rules", "legacy_read_only": False},
        {"path": "TOOLS.md", "legacy_read_only": False},
        {"path": "RULES.md", "legacy_read_only": False},
        {"path": "ROUTER.md", "legacy_read_only": False},
        {"path": "shared_factory", "legacy_read_only": True},
    ],
    "evidence_max_age_days": EVIDENCE_MAX_AGE_DAYS_DEFAULT,
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
    "nightly_apply": {
        "enabled": False,
        "auto_approve": {
            "classes": ["doctor-check-draft"],
            "min_score": 20,
            "max_per_night": 3,
        },
        "auto_implement": {
            "enabled": False,
            "classes": {},
            "max_per_night": 2,
        },
        "queue_target": "work_intake",
        "notify_source": "automation.self_improvement",
        "stale_after_days": 7,
    },
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


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def _read_yaml_if_present(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return _read_yaml(path)
    except (OSError, yaml.YAMLError):
        return {}


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


def _candidate_sort_key(path: Path) -> tuple[float, str]:
    """Newest-first ordering with a stable path tiebreak for determinism."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (-mtime, path.as_posix())


def _evidence_max_age_days(config: dict[str, Any]) -> float | None:
    """Resolve the configured evidence recency window over the safe default.

    Mirrors the ``_nightly_apply_policy`` merge pattern: a missing or invalid
    ``evidence_max_age_days`` key falls back to ``EVIDENCE_MAX_AGE_DAYS_DEFAULT``
    so control-plane files that predate the knob stay deterministic. A value of
    0 or less explicitly disables the age cutoff (scan regardless of mtime).
    """
    raw = config.get("evidence_max_age_days", EVIDENCE_MAX_AGE_DAYS_DEFAULT)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return float(EVIDENCE_MAX_AGE_DAYS_DEFAULT)
    if value <= 0:
        return None
    return value


def _evidence_files(
    path: Path,
    *,
    limit: int = MAX_EVIDENCE_FILES_PER_ROOT,
    max_age_days: float | None = None,
) -> list[Path]:
    cutoff: float | None = None
    if max_age_days is not None:
        cutoff = datetime.now(timezone.utc).timestamp() - max_age_days * 86400.0

    def _within_window(candidate: Path) -> bool:
        if cutoff is None:
            return True
        try:
            return candidate.stat().st_mtime >= cutoff
        except OSError:
            return False

    if not path.exists():
        return []
    if path.is_file():
        return [path] if path.suffix.lower() in EVIDENCE_SUFFIXES and _within_window(path) else []
    eligible = [
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file()
        and OUTPUT_ROOT not in candidate.as_posix()
        and candidate.suffix.lower() in EVIDENCE_SUFFIXES
        and _within_window(candidate)
    ]
    eligible.sort(key=_candidate_sort_key)
    return eligible[:limit]


def _redact(text: str) -> tuple[str, int]:
    redacted, count = TOKEN_SHAPED_VALUE_RE.subn("[REDACTED_SECRET]", text)
    redacted, env_count = SECRET_ENV_ASSIGNMENT_RE.subn("[REDACTED_SECRET_ENV_ASSIGNMENT]", redacted)
    count += env_count
    return redacted, count


def _collect_evidence(
    evidence_roots: list[dict[str, Any]],
    *,
    max_age_days: float | None = EVIDENCE_MAX_AGE_DAYS_DEFAULT,
) -> list[EvidenceRecord]:
    """Sample evidence from every configured root.

    A per-root cap (``MAX_EVIDENCE_FILES_PER_ROOT``) guarantees that small but
    high-signal roots (conversation logs, OS-shape files) are always represented
    even when a large root such as ``06-runs-and-logs`` could otherwise exhaust a
    single global budget. The global ceiling (``MAX_EVIDENCE_FILES``) still bounds
    total work for a daily run. ``max_age_days`` bounds recency: files last
    modified before the window are skipped so old transcripts cannot keep
    regenerating the same proposal indefinitely.
    """
    records: list[EvidenceRecord] = []
    seen: set[Path] = set()
    for entry in evidence_roots:
        for path in _evidence_files(entry["resolved"], max_age_days=max_age_days):
            if path in seen:
                continue
            seen.add(path)
            try:
                text = path.read_text(encoding="utf-8", errors="replace")[:MAX_EVIDENCE_BYTES]
            except OSError:
                continue
            redacted, redactions = _redact(text)
            records.append(EvidenceRecord(path=path, text=text, redacted_text=redacted, redactions=redactions))
            if len(records) >= MAX_EVIDENCE_FILES:
                return records
    return records


def _has_actionable_signal(line: str) -> bool:
    lower = line.lower()
    return any(term in lower for term in ACTIONABLE_EVIDENCE_TERMS)


def _is_low_value_evidence_line(line: str) -> bool:
    lower = " ".join(line.strip().lower().split())
    if TEST_FIXTURE_MARKER in lower:
        return True
    if len(lower) < 20:
        return True
    if lower.startswith(("#", "---", "|")):
        return True
    field_match = re.match(r"^-?\s*([a-z0-9_ -]{2,40})\s*:", lower)
    if field_match:
        field = field_match.group(1).strip().replace("-", "_").replace(" ", "_")
        if field in LOW_VALUE_EVIDENCE_FIELDS and not _has_actionable_signal(lower):
            return True
    volatile_markers = (
        "sha256:",
        "queue_",
        "/users/genome/",
        "harness/shared_factory/06-runs-and-logs/runs/",
    )
    if any(marker in lower for marker in volatile_markers) and not _has_actionable_signal(lower):
        return True
    if re.search(r"\b20\d\d-\d\d-\d\d[t ]\d\d:\d\d", lower) and not _has_actionable_signal(lower):
        return True
    return False


def _semantic_signature(text: str) -> str:
    normalized = text.lower()
    normalized = re.sub(r"/users/genome/\S+", " local_path ", normalized)
    normalized = re.sub(r"\bqueue_[a-f0-9]{8,}\b", " queue_id ", normalized)
    normalized = re.sub(r"\bsi-[a-f0-9]{8,}\b", " proposal_id ", normalized)
    normalized = re.sub(r"\bsha256:[a-f0-9]{16,}\b", " hash ", normalized)
    normalized = re.sub(r"\b[a-f0-9]{12,}\b", " hash ", normalized)
    normalized = re.sub(r"\b20\d\d-\d\d-\d\d[t ][0-9:.+\-z]+\b", " timestamp ", normalized)
    normalized = re.sub(r"\b\d+\b", " number ", normalized)
    tokens = re.findall(r"[a-z][a-z0-9_'-]{2,}", normalized)
    stopwords = {"the", "and", "for", "with", "this", "that", "from", "into", "under", "over"}
    kept = [token for token in tokens if token not in stopwords]
    return " ".join(kept[:32])


def _line_counts(records: list[EvidenceRecord]) -> Counter[str]:
    signature_counts: Counter[str] = Counter()
    examples: dict[str, str] = {}
    for record in records:
        for raw_line in record.redacted_text.splitlines():
            line = " ".join(raw_line.strip().lower().split())
            if _is_low_value_evidence_line(line):
                continue
            signature = _semantic_signature(line)
            if len(signature) < 20:
                continue
            signature_counts[signature] += 1
            examples.setdefault(signature, line)
    return Counter({examples[signature]: count for signature, count in signature_counts.items()})


def _keyword_hits(records: list[EvidenceRecord], keywords: tuple[str, ...]) -> int:
    total = 0
    for record in records:
        for line in record.redacted_text.lower().splitlines():
            if TEST_FIXTURE_MARKER in line:
                continue
            total += sum(line.count(keyword) for keyword in keywords)
    return total


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


def _evidence_line_score(line: str, finding_text: str) -> int:
    lower = line.lower()
    score = 0
    if finding_text and finding_text[:80].lower() in lower:
        score += 6
    if _has_actionable_signal(lower):
        score += 3
    if any(term in lower for term in ("should", "because", "needs", "cannot", "blocked")):
        score += 1
    return score


def _candidate_evidence(root: Path, records: list[EvidenceRecord], finding: dict[str, Any]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    finding_text = str(finding.get("evidence") or "")
    seen: set[tuple[str, str]] = set()
    for record in records[:10]:
        candidates: list[tuple[int, int, str]] = []
        for index, line in enumerate(record.redacted_text.splitlines()):
            normalized = " ".join(line.strip().split())
            if not normalized or _is_low_value_evidence_line(normalized):
                continue
            candidates.append((_evidence_line_score(normalized, finding_text), index, normalized[:300]))
        if not candidates:
            continue
        candidates.sort(key=lambda item: (-item[0], item[1]))
        excerpt = candidates[0][2]
        locator = _record_locator(root, record)
        key = (locator, excerpt)
        if key in seen:
            continue
        seen.add(key)
        if excerpt:
            evidence.append(
                {
                    "locator": locator,
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
    evidence_basis = str(finding.get("evidence") or "")
    if opportunity_type != "repeated_evidence" or _is_low_value_evidence_line(evidence_basis):
        evidence_basis = str(finding.get("summary") or title)
    semantic_cluster = _semantic_signature(evidence_basis) or title.lower()
    dedupe_key = _sha256(f"{opportunity_type}|{recommended_artifact}|{semantic_cluster}")
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


def _latest_run_record(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    runs_dir = _output_path(root, config, "runs")
    if not runs_dir.exists():
        return {}
    candidates: list[tuple[datetime, Path, dict[str, Any]]] = []
    for path in runs_dir.glob("*.yml"):
        if not path.is_file():
            continue
        record = _read_yaml_if_present(path)
        completed = _parse_time(record.get("completed_at")) or _parse_time(record.get("started_at"))
        if completed is None:
            completed = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        candidates.append((completed, path, record))
    if not candidates:
        return {}
    completed, path, record = max(candidates, key=lambda item: (item[0], item[1].name))
    return {
        "path": str(path.relative_to(root)),
        "run_id": record.get("run_id") or path.stem,
        "completed_at": _iso(completed),
        "status": record.get("status") or "done",
    }


def _run_queue_items(root: Path) -> list[dict[str, Any]]:
    return runtime_queue_items(root)


def _queue_item_reason(item: dict[str, Any], latest_run: dict[str, Any], now: datetime) -> str | None:
    status = str(item.get("status") or "")
    if status != "queued":
        return None
    due_at = _parse_time(item.get("due_at"))
    latest_completed = _parse_time(latest_run.get("completed_at"))
    if due_at and latest_completed and latest_completed >= due_at:
        return "covered_by_later_self_improvement_run"
    if due_at and now - due_at > STALE_QUEUE_GRACE:
        return "queued_past_24h_grace"
    created_at = _parse_time(item.get("created_at"))
    if created_at and now - created_at > STALE_QUEUE_GRACE:
        return "created_past_24h_grace"
    return None


def self_improvement_queue_health(root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    config = _load_yaml(os_root / CONFIG_PATH)
    latest_run = _latest_run_record(os_root, config)
    now = datetime.now(timezone.utc)
    items: list[dict[str, Any]] = []
    stale_items: list[dict[str, Any]] = []
    for item in _run_queue_items(os_root):
        if item.get("kind") != "schedule" or item.get("ref") != "self_improvement_review":
            continue
        row = {
            "id": item.get("id"),
            "status": item.get("status"),
            "due_at": item.get("due_at"),
            "created_at": item.get("created_at"),
            "idempotency_key": item.get("idempotency_key"),
        }
        reason = _queue_item_reason(item, latest_run, now)
        if reason:
            row["stale_reason"] = reason
            stale_items.append(row)
        items.append(row)
    current_status = "stale" if stale_items else "queued" if any(item.get("status") == "queued" for item in items) else "clear"
    return {
        "queue_path": RUN_QUEUE_PATH,
        "status": current_status,
        "latest_run": latest_run,
        "items": items,
        "stale_items": stale_items,
        "stale_count": len(stale_items),
    }


def reconcile_self_improvement_queue(
    root: str | Path,
    *,
    dry_run: bool = True,
    latest_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    os_root = expand_path(root)
    config = _load_yaml(os_root / CONFIG_PATH)
    items = runtime_queue_items(os_root)
    latest = latest_run or _latest_run_record(os_root, config)
    latest_completed = _parse_time(latest.get("completed_at"))
    result: dict[str, Any] = {
        "action": "reconcile-queue",
        "root": str(os_root),
        "mode": "dry-run" if dry_run else "apply",
        "queue_path": RUN_QUEUE_PATH,
        "latest_run": latest,
        "reconciled": [],
        "skipped": [],
    }
    if not latest_completed:
        result["skipped"].append({"reason": "no_successful_self_improvement_run"})
        result["changed"] = False
        return result

    changed = False
    for item in items:
        if item.get("kind") != "schedule" or item.get("ref") != "self_improvement_review":
            continue
        reason = _queue_item_reason(item, latest, latest_completed)
        if reason != "covered_by_later_self_improvement_run":
            result["skipped"].append(
                {
                    "id": item.get("id"),
                    "status": item.get("status"),
                    "reason": reason or "not_covered_by_latest_run",
                }
            )
            continue
        row = {
            "id": item.get("id"),
            "previous_status": item.get("status"),
            "reconcile_reason": reason,
            "covered_by_run_id": latest.get("run_id"),
        }
        result["reconciled"].append(row)
        if dry_run:
            continue
        evidence = list(item.get("evidence") or [])
        evidence.append({"type": "self_improvement_run", "run_id": latest.get("run_id"), "path": latest.get("path")})
        patch_runtime_queue_item(
            os_root,
            str(item["id"]),
            {
                "status": "done",
                "finished_at": latest.get("completed_at"),
                "updated_at": _now(),
                "reconcile_reason": reason,
                "covered_by_run_id": latest.get("run_id"),
                "evidence": evidence,
            },
        )
        changed = True

    result["changed"] = changed
    return result


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


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _cell(value: str, *, limit: int = 200) -> str:
    """Sanitize a value for a single Markdown table cell."""
    escaped = value.replace("|", "\\|").replace("\n", " ").strip()
    return escaped[:limit]


def _report_markdown(root: Path, result: dict[str, Any]) -> str:
    """Render a human-readable daily report from a persisted run result.

    Built only from already-redacted finding/proposal/evidence fields so the
    payload never carries a token-shaped value (which the atomic writer refuses).
    """
    run_id = str(result.get("run_id") or "(no run id)")
    title = f"Self-Improvement Daily Report — {_today()}"
    findings = result.get("findings") or []
    proposals = result.get("proposal_candidates") or []
    evidence_files = int(result.get("evidence_files") or 0)
    present_roots = [entry for entry in result.get("evidence_roots") or [] if entry.get("exists")]

    lines: list[str] = [f"# {title}", ""]
    if findings:
        summary = (
            f"The self-improvement heartbeat scanned {evidence_files} evidence files across "
            f"{len(present_roots)} present roots (conversations and OS shape included) and surfaced "
            f"{len(findings)} deterministic finding(s) yielding {len(proposals)} proposal candidate(s)."
        )
    else:
        summary = (
            f"The self-improvement heartbeat scanned {evidence_files} evidence files across "
            f"{len(present_roots)} present roots and found no patterns above the reporting threshold."
        )
    lines.extend([summary, ""])
    lines.append(
        f"Counts: evidence files scanned = {evidence_files} | findings = {len(findings)} | "
        f"proposals = {len(proposals)}"
    )
    lines.append(f"Run ID: `{run_id}`")
    lines.append("")

    lines.append("## Findings")
    lines.append("")
    if not findings:
        lines.append("_No findings above the reporting threshold._")
    else:
        lines.append("| Title | Type | Score | Evidence locator |")
        lines.append("| --- | --- | --- | --- |")
        for finding in findings:
            score = (finding.get("score") or {}).get("total", "")
            title_cell = _cell(str(finding.get("title") or ""))
            type_cell = _cell(str(finding.get("type") or ""))
            evidence = _cell(str(finding.get("evidence") or ""), limit=160)
            lines.append(f"| {title_cell} | {type_cell} | {score} | {evidence} |")
    lines.append("")

    lines.append("## Proposals")
    lines.append("")
    if not proposals:
        lines.append("_No proposal candidates this run._")
    else:
        lines.append("| Proposal ID | Summary | Recommended artifact | Score | Evidence path |")
        lines.append("| --- | --- | --- | --- | --- |")
        for proposal in proposals:
            score = (proposal.get("score") or {}).get("total", "")
            summary_cell = _cell(str(proposal.get("summary") or ""), limit=160)
            artifact_cell = _cell(str(proposal.get("recommended_artifact") or ""))
            evidence_items = proposal.get("evidence") or []
            locator = _cell(str((evidence_items[0] or {}).get("locator"))) if evidence_items else "none"
            lines.append(
                f"| `{proposal.get('proposal_id')}` | {summary_cell} "
                f"| {artifact_cell} | {score} | {locator} |"
            )
    lines.append("")

    lines.append("## Recommended next actions")
    lines.append("")
    if not findings:
        lines.append("- No action required; keep accumulating evidence for the next heartbeat.")
    else:
        lines.append(
            "- Review the proposals above with `agentic-os self-improvement list` and "
            "`agentic-os self-improvement show <id>`."
        )
        lines.append(
            "- Approve and promote any proposal you want drafted; promotion writes draft "
            "artifacts only and never mutates live shared surfaces."
        )
        lines.append("- Reject noise to start its cooldown and keep future reports focused.")
    lines.append("")
    return "\n".join(lines)


def _write_daily_report(root: Path, result: dict[str, Any]) -> dict[str, str]:
    """Write the stable latest report plus an archived timestamped copy.

    Returns the relative paths written. The report directory lives under
    ``OUTPUT_ROOT`` but outside the four validated output_paths, so it is
    resolved directly rather than through ``_output_path``.
    """
    content = _report_markdown(root, result)
    output_root = _resolve_root_relative(root, OUTPUT_ROOT)
    reports_dir = _safe_descendant(root, output_root, "reports")
    _ensure_safe_dir(root, reports_dir)
    latest_path = _safe_child(root, output_root, "latest-report.md")
    archive_path = _safe_child(root, reports_dir, f"{_stamp()}.md")
    _atomic_write_text(root, latest_path, content)
    _atomic_write_text(root, archive_path, content)
    return {
        "latest": str(latest_path.relative_to(root)),
        "archive": str(archive_path.relative_to(root)),
    }


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _path_under_root(root: Path, value: str) -> Path | None:
    raw = value.strip()
    if not raw:
        return None
    path = Path(raw)
    candidate = path if path.is_absolute() else root / path
    try:
        resolved = candidate.resolve(strict=False)
        resolved_root = root.resolve(strict=False)
    except OSError:
        return None
    if resolved != resolved_root and resolved_root not in resolved.parents:
        return None
    return resolved


def _validation_snapshot(root: Path) -> dict[str, Any]:
    validation = validate_root(root)
    return {
        "ok": validation.ok,
        "errors": list(validation.errors),
        "warnings": list(validation.warnings),
        "error_count": len(validation.errors),
        "warning_count": len(validation.warnings),
    }


def _missing_file_path(root: Path, message: str) -> Path | None:
    match = re.search(r"(?:missing required file|missing metadata file \([^)]+\)): (.+)$", message)
    if match:
        return _path_under_root(root, match.group(1))
    match = re.search(r"work item .+ missing required file: (.+)$", message)
    if match:
        return _path_under_root(root, match.group(1))
    return None


def _missing_folder_path(root: Path, message: str) -> Path | None:
    match = re.search(r"missing required folder: (.+)$", message)
    if not match:
        return None
    return _path_under_root(root, match.group(1))


def _invalid_json_path(root: Path, message: str) -> Path | None:
    match = re.search(r"invalid JSON: (.+?): ", message)
    if not match:
        return None
    return _path_under_root(root, match.group(1))


def _infer_agent_layer(layer_root: Path, os_root: Path) -> str | None:
    if (layer_root / "workflow.md").is_file():
        return "workflow_or_task"
    if (layer_root / "automation.md").is_file():
        return "automation"
    if (layer_root / "project.yml").is_file():
        return "project"
    if (layer_root / "domain.yml").is_file():
        return "domain_or_lane"
    if layer_root == os_root or layer_root == os_root / "harness":
        return "agentic_os_root"
    return None


def _work_item_metadata(work_item_root: Path) -> dict[str, Any]:
    metadata_path = work_item_root / "work.yml"
    if not metadata_path.is_file():
        return {}
    try:
        data = yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _generated_file_content(root: Path, path: Path, message: str) -> str:
    now = _now()
    filename = path.name
    parent = path.parent
    metadata = _work_item_metadata(parent)
    title = str(metadata.get("title") or parent.name.replace("_", " ").title())
    relative = _relative_path(root, path)
    if filename == "CLAUDE.md":
        return "@AGENTS.md\n"
    if filename == "IDEA.md":
        return (
            f"# Idea: {title}\n\n"
            f"Generated by `agentic-os self-improvement morning-report` on {now}.\n\n"
            "## Source\n\n"
            f"- Validation issue: `{message}`\n"
            f"- Generated file: `{relative}`\n\n"
            "## Current Understanding\n\n"
            f"{metadata.get('summary') or 'This work item needed a structural idea file so future agents can route it.'}\n\n"
            "## Next\n\n"
            "- Replace this generated scaffold with the operator-approved product framing when the packet is triaged.\n"
        )
    if filename == "JUDGMENT.md":
        return (
            f"# Judgment: {title}\n\n"
            f"Generated by `agentic-os self-improvement morning-report` on {now}.\n\n"
            "## Status\n\n"
            "Needs review. This file was generated to repair structure drift; it does not claim that product judgment is complete.\n\n"
            "## Known Facts\n\n"
            f"- Validation issue: `{message}`\n"
            f"- Work item status: `{metadata.get('status') or 'unknown'}`\n\n"
            "## Required Follow-Up\n\n"
            "- Confirm scope, tradeoffs, and acceptance criteria before treating this packet as ready for implementation.\n"
        )
    if filename == "WORKLOG.md":
        return f"# Worklog: {title}\n\n## {now[:10]}\n\n- Generated structural worklog placeholder from validation repair.\n"
    if filename == "NEXT.md":
        return f"# Next: {title}\n\n- Review the generated structural repair and replace placeholders with packet-specific next action.\n"
    if filename == "MEMORY.md":
        return "# Memory\n\nNo durable local memories recorded for this layer yet.\n"
    if filename == "ROUTER.md":
        return "# Router\n\nUse the nearest parent routing rules until this layer has specialized routing.\n"
    if filename == "CONTEXT.md":
        return "# Context\n\nThis layer uses local files as the source of truth. Load adjacent rules and tools before acting.\n"
    if filename == "RULES.md":
        return "# Rules\n\n- Follow the parent Agentic OS rules.\n- Keep local filesystem state as source of truth.\n"
    if filename == "TOOLS.md":
        return "# Tools\n\nUse tools declared by the nearest parent layer unless this layer adds a narrower contract.\n"
    if filename == "AGENTS.md":
        return (
            "# Agent Entry Point\n\n"
            "Read `ROUTER.md`, `CONTEXT.md`, `RULES.md`, and `TOOLS.md` before acting in this layer.\n"
        )
    if filename == "config.toml":
        layer = _infer_agent_layer(parent, root) or "workflow_or_task"
        return f'# Generated by agentic-os self-improvement morning-report on {now}.\nprofile = "{layer}"\n'
    return (
        f"# {filename}\n\n"
        f"Generated by `agentic-os self-improvement morning-report` on {now} to repair validation drift.\n\n"
        f"Validation issue: `{message}`\n"
    )


def _repair_missing_file(root: Path, path: Path, message: str, *, apply: bool) -> dict[str, Any]:
    if path.exists():
        return {"status": "skipped", "reason": "already_exists", "path": _relative_path(root, path)}
    layer = _infer_agent_layer(path.parent, root) if path.name in AGENT_LAYER_FILES else None
    if layer:
        if not apply:
            return {"status": "planned", "type": "agent_layer_config", "path": _relative_path(root, path), "layer": layer}
        result = install_config(path.parent, layer=layer, dry_run=False, confirm_conflicts=True)
        writes = [
            {"action": "created", "path": _relative_path(root, item)}
            for item in result.created
        ] + [
            {"action": "updated", "path": _relative_path(root, item)}
            for item in result.updated
        ]
        if path.exists():
            return {"status": "applied", "type": "agent_layer_config", "path": _relative_path(root, path), "layer": layer, "writes": writes}
        return {"status": "skipped", "reason": "agent_config_install_did_not_create_file", "path": _relative_path(root, path), "layer": layer}
    if not apply:
        return {"status": "planned", "type": "missing_file", "path": _relative_path(root, path)}
    content = _generated_file_content(root, path, message)
    _atomic_write_text(root, path, content)
    return {"status": "applied", "type": "missing_file", "path": _relative_path(root, path)}


def _repair_missing_folder(root: Path, path: Path, *, apply: bool) -> dict[str, Any]:
    if path.exists():
        return {"status": "skipped", "reason": "already_exists", "path": _relative_path(root, path)}
    if not apply:
        return {"status": "planned", "type": "missing_folder", "path": _relative_path(root, path)}
    _ensure_safe_dir(root, path)
    return {"status": "applied", "type": "missing_folder", "path": _relative_path(root, path)}


def _repair_invalid_json(root: Path, path: Path, message: str, *, apply: bool) -> dict[str, Any]:
    if not path.exists():
        return {"status": "skipped", "reason": "json_file_missing", "path": _relative_path(root, path)}
    if not apply:
        return {"status": "planned", "type": "invalid_json", "path": _relative_path(root, path)}
    backup = path.with_name(f"{path.name}.invalid-{_stamp()}")
    backup_content = path.read_text(encoding="utf-8", errors="replace")
    _atomic_write_text(root, backup, backup_content)
    payload = {
        "schema_version": 1,
        "status": "repaired_invalid_json_placeholder",
        "repaired_at": _now(),
        "validation_issue": message,
        "original_backup": _relative_path(root, backup),
    }
    _atomic_write_text(root, path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return {
        "status": "applied",
        "type": "invalid_json",
        "path": _relative_path(root, path),
        "backup": _relative_path(root, backup),
    }


def _repair_validation_drift(root: Path, validation: dict[str, Any], *, apply: bool) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    for message in validation.get("errors") or []:
        missing_file = _missing_file_path(root, str(message))
        if missing_file is not None:
            actions.append(_repair_missing_file(root, missing_file, str(message), apply=apply))
            continue
        missing_folder = _missing_folder_path(root, str(message))
        if missing_folder is not None:
            actions.append(_repair_missing_folder(root, missing_folder, apply=apply))
            continue
        invalid_json = _invalid_json_path(root, str(message))
        if invalid_json is not None:
            actions.append(_repair_invalid_json(root, invalid_json, str(message), apply=apply))
            continue
        actions.append({"status": "skipped", "reason": "unsupported_validation_error", "message": str(message)})
    for message in validation.get("warnings") or []:
        if "legacy root folder present" in str(message):
            actions.append({"status": "skipped", "reason": "legacy_root_folder_requires_manual_migration", "message": str(message)})
    return {
        "mode": "apply" if apply else "dry-run",
        "actions": actions,
        "applied_count": sum(1 for action in actions if action.get("status") == "applied"),
        "planned_count": sum(1 for action in actions if action.get("status") == "planned"),
        "skipped_count": sum(1 for action in actions if action.get("status") == "skipped"),
    }


def _source_inventory(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    files = {
        "connected_systems": root / "harness/shared_factory/00-control-plane/connected-systems.yml",
        "source_providers": root / "harness/shared_factory/00-control-plane/source-providers.yml",
        "watch_sources": root / "harness/shared_factory/00-control-plane/watch-sources.yml",
        "runtime_registry": root / "harness/shared_factory/00-control-plane/runtime-registry.yml",
        "tools": root / "TOOLS.md",
    }
    env_vars = {
        name: "set" if os.environ.get(name) else "missing"
        for name in ("GENOMES_NOTION_PAT", "GENOMES_NOTION_CONNECTOR", "LINEAR_TOKEN", "LINEAR_API_KEY", "COMPOSIO_API_KEY")
    }
    configured_external_sources = config.get("external_sources") if isinstance(config.get("external_sources"), list) else []
    source_files = {name: {"path": _relative_path(root, path), "exists": path.exists()} for name, path in files.items()}
    return {
        "env": env_vars,
        "source_files": source_files,
        "configured_external_sources": configured_external_sources,
        "readiness": {
            "notion": "configured" if env_vars["GENOMES_NOTION_PAT"] == "set" else "missing_token",
            "linear": "configured" if env_vars["LINEAR_TOKEN"] == "set" or env_vars["LINEAR_API_KEY"] == "set" else "missing_token",
            "composio": "configured" if env_vars["COMPOSIO_API_KEY"] == "set" else "missing_token",
        },
    }


def _notion_manifest(root: Path) -> dict[str, Any]:
    path = root / NOTION_RUNTIME_MANIFEST
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _verified_runtime_notion_anchor(
    manifest: dict[str, Any], transport: Any
) -> tuple[str | None, str | None]:
    """Return the configured root and verified cockpit mutation anchor."""
    if transport is not notion_api._default_fetcher:
        return None, None
    root_parent_id = str(
        manifest.get("parent_page_id")
        or os.environ.get("GENOMES_NOTION_PARENT_PAGE_ID")
        or ""
    ).strip()
    cockpit_page_id = str(manifest.get("cockpit_page_id") or "").strip()
    if not root_parent_id or not cockpit_page_id:
        raise RuntimeError(
            "live Notion manifest requires parent_page_id and cockpit_page_id"
        )
    children = notion_api.search_child_pages(
        root_parent_id, NOTION_TOKEN_ENV, fetcher=transport
    )
    if not any(
        str(page.get("id") or "").replace("-", "")
        == cockpit_page_id.replace("-", "")
        for page in children
    ):
        raise RuntimeError(
            "manifest cockpit page is not a child of the approved Notion parent"
        )
    return root_parent_id, cockpit_page_id


SELF_IMPROVEMENT_DB_SCHEMA: dict[str, dict[str, Any]] = {
    "Summary": {"rich_text": {}},
    "Proposed Spec": {"rich_text": {}},
    "Status": {"select": {}},
    "Score": {"number": {}},
    "Evidence Path": {"rich_text": {}},
    "Run ID": {"rich_text": {}},
    "Date": {"date": {}},
    "Updated": {"date": {}},
    "Type": {"select": {}},
    "Proposal ID": {"rich_text": {}},
    "Parent Run ID": {"rich_text": {}},
    "Recommended Artifact": {"rich_text": {}},
    "Action Status": {"select": {}},
    "Action Log": {"rich_text": {}},
    "Auto Groom": {"checkbox": {}},
    "Run Grooming": {"checkbox": {}},
    "Auto-dev Implementation": {"checkbox": {}},
}


def _ensure_self_improvement_schema(
    database_id: str,
    available: dict[str, str],
    *,
    fetcher: Any,
    approved_parent_page_id: str | None = None,
) -> dict[str, str]:
    missing = {
        name: schema
        for name, schema in SELF_IMPROVEMENT_DB_SCHEMA.items()
        if name not in available
    }
    if not missing:
        return available
    notion_api.update_database_schema(
        database_id,
        missing,
        NOTION_TOKEN_ENV,
        approved_parent_page_id=approved_parent_page_id,
        fetcher=fetcher,
    )
    return notion_api.get_database_property_types(database_id, NOTION_TOKEN_ENV, fetcher=fetcher)


def _rt(value: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": value[:2000]}}] if value else []


def _rt_bold(value: str) -> list[dict[str, Any]]:
    """Rich text with bold annotation — used for 'What to do:' opener."""
    return [{"type": "text", "text": {"content": value[:2000]}, "annotations": {"bold": True}}] if value else []


def _paragraph(text: str) -> dict[str, Any]:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rt(text)}}


def _bold_paragraph(text: str) -> dict[str, Any]:
    """Notion paragraph block whose entire text is bold."""
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rt_bold(text)}}


def _heading(level: int, text: str) -> dict[str, Any]:
    key = f"heading_{level}"
    return {"object": "block", "type": key, key: {"rich_text": _rt(text)}}


def _bullet(text: str) -> dict[str, Any]:
    return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": _rt(text)}}


# ---------------------------------------------------------------------------
# SI sequence counter — monotonic per-root, zero-padded 3-digit row number
# ---------------------------------------------------------------------------

_SI_SEQ_FILENAME = "si-seq.json"
_SI_SEQ_SEED = 3  # SI-001 and SI-002 pre-assigned to existing rows


def _si_seq_path(root: Path) -> Path:
    """Absolute path to the si-seq counter file inside *root*."""
    seq_dir = _resolve_root_relative(root, OUTPUT_ROOT)
    return _safe_child(root, seq_dir, _SI_SEQ_FILENAME)


def _next_si_seq(root: Path) -> int:
    """Read, increment, and atomically persist the SI sequence counter.

    If the counter file is absent it is created seeded at ``_SI_SEQ_SEED`` so
    SI-001/002/003 (already assigned externally) are never re-issued.
    Returns the *consumed* sequence number (the one to use for this row).
    """
    path = _si_seq_path(root)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            current = int(raw.get("next_seq") or _SI_SEQ_SEED)
        except Exception:  # noqa: BLE001
            current = _SI_SEQ_SEED
    else:
        current = _SI_SEQ_SEED
    next_val = current + 1
    _atomic_write_text(root, path, json.dumps({"next_seq": next_val}, indent=2) + "\n")
    return current


def _imperative_slug(text: str) -> str:
    """Convert *text* to an imperative phrase slug suitable for an SI row title.

    - Lowercases, strips punctuation, collapses whitespace
    - Replaces spaces with hyphens
    - Truncates to ≤60 characters at a word boundary
    """
    import re
    cleaned = re.sub(r"[^\w\s-]", " ", text.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    slug = cleaned.replace(" ", "-")
    if len(slug) <= 60:
        return slug
    # Truncate to 60 chars at the last hyphen boundary
    truncated = slug[:60]
    last_hyphen = truncated.rfind("-")
    if last_hyphen > 20:
        truncated = truncated[:last_hyphen]
    return truncated


# ---------------------------------------------------------------------------
# Durable intake projection ledger — proposal_id -> {seq, page_id, url}
# ---------------------------------------------------------------------------

_SI_INTAKE_LEDGER_FILENAME = "si-intake-ledger.json"


def _intake_ledger_path(root: Path) -> Path:
    """Absolute path to the intake projection ledger inside *root*."""
    ledger_dir = _resolve_root_relative(root, OUTPUT_ROOT)
    return _safe_child(root, ledger_dir, _SI_INTAKE_LEDGER_FILENAME)


def _read_intake_ledger(root: Path) -> dict[str, Any]:
    """Load the durable projection ledger for *root*.

    The ledger is the primary dedup guard for Notion projections: it records,
    per proposal_id, the pinned SI sequence number and the intake page created
    for it, plus (under ``actions``) which suggestion-page actions were already
    queued. A missing or corrupt file degrades to an empty ledger — the
    Notion-side guard still applies downstream.
    """
    path = _intake_ledger_path(root)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                proposals = raw.get("proposals")
                actions = raw.get("actions")
                return {
                    "schema_version": 1,
                    "proposals": proposals if isinstance(proposals, dict) else {},
                    "actions": actions if isinstance(actions, dict) else {},
                }
        except Exception:  # noqa: BLE001 - corrupt ledger degrades to empty
            pass
    return {"schema_version": 1, "proposals": {}, "actions": {}}


def _write_intake_ledger(root: Path, ledger: dict[str, Any]) -> None:
    _atomic_write_text(root, _intake_ledger_path(root), json.dumps(ledger, indent=2, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# Notion-side dedup guard
# ---------------------------------------------------------------------------

def _query_existing_intake_row(
    proposal_id: str,
    fetcher: Any,
    token_env: str = "NOTION_TOKEN",
) -> str | None:
    """Search the Work Intake DB for an existing non-dropped row for *proposal_id*.

    Returns the page_id of the first matching non-dropped row, or ``None`` if no
    such row exists. Uses a title ``contains`` filter via ``notion_api.query_database``.
    Never raises — caller treats any exception as "no duplicate found" so the run
    can proceed.
    """
    try:
        filter_body: dict[str, Any] = {
            "property": "Name",
            "title": {"contains": proposal_id},
        }
        pages = notion_api.query_database(
            WORK_INTAKE_DB_ID,
            filter_body,
            token_env,
            fetcher=fetcher,
        )
        for page in pages:
            props = page.get("properties") or {}
            status_prop = props.get("Status") or {}
            status_val = (
                (status_prop.get("select") or {}).get("name") or ""
            ).lower()
            if status_val != "dropped":
                return str(page.get("id") or "").replace("-", "")
    except Exception:  # noqa: BLE001 - guard must never break the run
        pass
    return None


def _todo(text: str, *, checked: bool = False) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "to_do",
        "to_do": {"rich_text": _rt(text), "checked": checked},
    }


def _divider() -> dict[str, Any]:
    return {"object": "block", "type": "divider", "divider": {}}


def _summary_blocks(root: Path, result: dict[str, Any], report_paths: dict[str, str]) -> list[dict[str, Any]]:
    findings = result.get("findings") or []
    proposals = result.get("proposal_candidates") or []
    evidence_files = int(result.get("evidence_files") or 0)
    report_path = report_paths.get("latest", "")
    blocks: list[dict[str, Any]] = [
        _heading(2, "Run Summary"),
        _paragraph(
            f"Scanned {evidence_files} evidence files and surfaced "
            f"{len(findings)} finding(s) with {len(proposals)} suggestion(s)."
        ),
        _bullet(f"Run ID: {result.get('run_id') or ''}"),
        _bullet(f"Filesystem report: {report_path}"),
        _bullet("Filesystem remains the source of truth; Notion is the review and action projection."),
        _divider(),
        _heading(2, "Findings"),
    ]
    if not findings:
        blocks.append(_paragraph("No findings crossed the reporting threshold."))
    else:
        for finding in findings[:10]:
            score = (finding.get("score") or {}).get("total", "")
            blocks.append(
                _bullet(
                    f"{finding.get('title') or 'Finding'}: "
                    f"{finding.get('summary') or ''} Score {score}."
                )
            )
    blocks.extend(
        [
            _divider(),
            _heading(2, "Suggestion Pages"),
            _paragraph(
                "Open the suggestion rows linked to this run. Each suggestion page has two action checkboxes: "
                "Auto Groom and Auto-dev Implementation."
            ),
        ]
    )
    return blocks


def _proposal_spec_outline(proposal: dict[str, Any]) -> str:
    title = str(proposal.get("title") or proposal.get("proposal_id") or "Self-improvement suggestion")
    summary = str(proposal.get("summary") or "")
    recommended_artifact = str(proposal.get("recommended_artifact") or "spec")
    evidence = proposal.get("evidence") or []
    validation = proposal.get("validation_plan") or []
    evidence_lines = [
        f"- {item.get('locator') or 'evidence'}: {item.get('excerpt') or ''}"
        for item in evidence[:3]
    ]
    validation_lines = [f"- {item}" for item in validation[:5]]
    lines = [
        f"Title: {title}",
        f"Problem: {summary or 'Clarify the proposed Agentic OS improvement.'}",
        f"Target artifact: {recommended_artifact}.",
        "Scope: Groom this self-improvement idea into an Agentic OS spec packet and a Linear issue under the Agentic OS project.",
        "Acceptance criteria:",
        "- Problem, scope, non-goals, implementation notes, QA, rollout, and open questions are explicit.",
        "- Linear content is sanitized: no local filesystem paths, private Notion links, secrets, or private run-log paths.",
    ]
    if evidence_lines:
        lines.append("Evidence:")
        lines.extend(evidence_lines)
    if validation_lines:
        lines.append("Validation:")
        lines.extend(validation_lines)
    return "\n".join(lines)


def _proposal_blocks(proposal: dict[str, Any], *, run_id: str) -> list[dict[str, Any]]:
    evidence = proposal.get("evidence") or []
    validation = proposal.get("validation_plan") or []
    proposed_spec = _proposal_spec_outline(proposal)
    blocks: list[dict[str, Any]] = [
        _heading(2, "Recommendation"),
        _paragraph(str(proposal.get("summary") or "")),
        _bullet(f"Proposal ID: {proposal.get('proposal_id') or ''}"),
        _bullet(f"Run ID: {run_id}"),
        _bullet(f"Recommended artifact: {proposal.get('recommended_artifact') or ''}"),
        _bullet(f"Promotion status: {proposal.get('promotion_status') or 'proposed'}"),
        _divider(),
        _heading(2, "Proposed Spec Draft"),
        _paragraph(proposed_spec),
        _divider(),
        _heading(2, "Actions"),
        _bullet("Auto Groom: check the page property to queue Agentic OS spec grooming and Linear issue creation."),
        _bullet("Auto-dev Implementation: check the page property to queue implementation."),
        _divider(),
        _heading(2, "Evidence"),
    ]
    if not evidence:
        blocks.append(_paragraph("No evidence attached."))
    else:
        for item in evidence[:8]:
            blocks.append(_bullet(f"{item.get('locator') or 'evidence'}: {item.get('excerpt') or ''}"))
    blocks.append(_heading(2, "Validation Plan"))
    if not validation:
        blocks.append(_paragraph("No validation plan recorded."))
    else:
        for item in validation:
            blocks.append(_bullet(str(item)))
    return blocks


def _notion_projection_properties(
    available: dict[str, str],
    *,
    title: str,
    summary: str,
    score: int,
    run_id: str,
    evidence_path: str,
    page_type: str = "Daily Summary",
    proposal_id: str = "",
    parent_run_id: str = "",
    recommended_artifact: str = "",
    proposed_spec: str = "",
    auto_groom: bool = False,
    run_grooming: bool = False,
    auto_dev: bool = False,
    action_status: str = "",
    action_log: str = "",
) -> dict[str, Any]:
    """Build only the properties that exist on the live database.

    The title property is mandatory and always emitted under whatever name the
    database uses for its title column. Other fields are emitted only when a
    matching, type-compatible column exists, so an out-of-band schema cannot
    cause a 400.
    """
    properties: dict[str, Any] = {}
    title_name = next((name for name, kind in available.items() if kind == "title"), "Name")
    properties[title_name] = notion_api._title_prop(title)

    candidates: dict[str, tuple[str, Any]] = {
        "Summary": ("rich_text", summary),
        "Status": ("select", "proposed"),
        "Score": ("number", score),
        "Evidence Path": ("rich_text", evidence_path),
        "Run ID": ("rich_text", run_id),
        "Date": ("date", _today()),
        "Updated": ("date", _now()),
        "Type": ("select", page_type),
        "Proposal ID": ("rich_text", proposal_id),
        "Parent Run ID": ("rich_text", parent_run_id),
        "Recommended Artifact": ("rich_text", recommended_artifact),
        "Proposed Spec": ("rich_text", proposed_spec),
        "Auto Groom": ("checkbox", auto_groom),
        "Run Grooming": ("checkbox", run_grooming),
        "Auto-dev Implementation": ("checkbox", auto_dev),
        "Action Status": ("select", action_status),
        "Action Log": ("rich_text", action_log),
    }
    for name, (expected_type, value) in candidates.items():
        actual = available.get(name)
        if actual != expected_type:
            continue
        if expected_type == "rich_text":
            properties[name] = notion_api._rich_text_prop(str(value))
        elif expected_type == "select":
            properties[name] = notion_api._select_prop(str(value))
        elif expected_type == "number":
            properties[name] = {"number": value}
        elif expected_type == "date":
            properties[name] = notion_api._date_prop(str(value))
        elif expected_type == "checkbox":
            properties[name] = notion_api._checkbox_prop(bool(value))
    return properties


def _project_run_to_notion(
    root: Path,
    result: dict[str, Any],
    report_paths: dict[str, str],
    *,
    fetcher: Any = None,
) -> dict[str, Any]:
    """Project the run summary into the "Self Improvement" Notion database.

    Degrades gracefully: any missing credential, workspace mismatch, manifest
    gap, or API error writes a projection-draft file under ``reports/`` and
    returns ``{"projected": False, ...}`` without raising. The filesystem report
    must always succeed regardless of Notion availability.

    ``fetcher`` is the injectable HTTP transport seam (mirrors ``notion_api``);
    tests pass a fake. When ``None``, the module default transport is used.
    """
    transport = fetcher or notion_api._default_fetcher
    findings = result.get("findings") or []
    proposals = result.get("proposal_candidates") or []
    run_id = str(result.get("run_id") or "")
    title = f"Self-Improvement Daily Report — {_today()}"
    summary = (
        f"{len(findings)} finding(s), {len(proposals)} proposal(s) from "
        f"{int(result.get('evidence_files') or 0)} evidence files."
    )
    score = max((int((finding.get("score") or {}).get("total") or 0) for finding in findings), default=0)
    evidence_path = report_paths.get("latest", "")

    def _degrade(reason: str) -> dict[str, Any]:
        draft = (
            f"# Notion projection draft — {_today()}\n\n"
            f"Notion projection was not performed: {reason}.\n\n"
            f"- Name: {title}\n- Date: {_today()}\n- Summary: {summary}\n"
            f"- Score: {score}\n- Status: proposed\n- Evidence Path: {evidence_path}\n- Run ID: {run_id}\n"
        )
        output_root = _resolve_root_relative(root, OUTPUT_ROOT)
        reports_dir = _safe_descendant(root, output_root, "reports")
        _ensure_safe_dir(root, reports_dir)
        draft_path = _safe_child(root, reports_dir, f"{_stamp()}-notion-draft.md")
        _atomic_write_text(root, draft_path, draft)
        return {"projected": False, "reason": reason, "draft": str(draft_path.relative_to(root))}

    manifest = _notion_manifest(root)
    if not manifest.get("live"):
        return _degrade("notion runtime tracking is not live in the manifest")
    expected_workspace = str(manifest.get("workspace") or "")
    if "michael clark" in expected_workspace.lower() or "personal" in expected_workspace.lower():
        return _degrade("manifest workspace appears to be a personal Notion")
    database_id = (manifest.get("database_ids") or {}).get(NOTION_SELF_IMPROVEMENT_DB)
    if not database_id:
        return _degrade(f"manifest has no {NOTION_SELF_IMPROVEMENT_DB!r} database id")
    if not notion_api.resolve_token(NOTION_TOKEN_ENV):
        return _degrade(f"notion token env var {NOTION_TOKEN_ENV!r} is not set")

    try:
        verification_parent, approved_anchor = _verified_runtime_notion_anchor(
            manifest, transport
        )
        bot_workspace = notion_api.get_bot_workspace(
            NOTION_TOKEN_ENV,
            parent_page_id=verification_parent,
            fetcher=transport,
        )
        if expected_workspace and bot_workspace != expected_workspace:
            return _degrade(
                f"live workspace {bot_workspace!r} does not match manifest workspace {expected_workspace!r}"
            )
        available = notion_api.get_database_property_types(database_id, NOTION_TOKEN_ENV, fetcher=transport)
        available = _ensure_self_improvement_schema(
            database_id,
            available,
            fetcher=transport,
            approved_parent_page_id=approved_anchor,
        )
        properties = _notion_projection_properties(
            available,
            title=title,
            summary=summary,
            score=score,
            run_id=run_id,
            evidence_path=evidence_path,
            page_type="Daily Summary",
            action_status="ready",
        )
        page_id = notion_api.create_database_page(
            database_id,
            properties,
            NOTION_TOKEN_ENV,
            children=_summary_blocks(root, result, report_paths),
            approved_parent_page_id=approved_anchor,
            fetcher=transport,
        )
        suggestion_pages = []
        for proposal in proposals:
            proposal_id = str(proposal.get("proposal_id") or "")
            proposal_score = int((proposal.get("score") or {}).get("total") or 0)
            proposal_title = str(proposal.get("title") or proposal_id or "Self-improvement suggestion")
            proposal_summary = str(proposal.get("summary") or "")
            evidence_items = proposal.get("evidence") or []
            proposal_evidence = str((evidence_items[0] or {}).get("locator")) if evidence_items else evidence_path
            proposed_spec = _proposal_spec_outline(proposal)
            proposal_properties = _notion_projection_properties(
                available,
                title=proposal_title,
                summary=proposal_summary,
                score=proposal_score,
                run_id=run_id,
                evidence_path=proposal_evidence,
                page_type="Suggestion",
                proposal_id=proposal_id,
                parent_run_id=run_id,
                recommended_artifact=str(proposal.get("recommended_artifact") or ""),
                proposed_spec=proposed_spec,
                auto_groom=False,
                run_grooming=False,
                auto_dev=False,
                action_status="ready",
                action_log="",
            )
            proposal_page_id = notion_api.create_database_page(
                database_id,
                proposal_properties,
                NOTION_TOKEN_ENV,
                children=_proposal_blocks(proposal, run_id=run_id),
                approved_parent_page_id=approved_anchor,
                fetcher=transport,
            )
            suggestion_pages.append({"proposal_id": proposal_id, "page_id": proposal_page_id})
    except (RuntimeError, OSError, KeyError, ValueError) as exc:
        return _degrade(f"notion projection failed: {exc}")
    return {
        "projected": True,
        "page_id": page_id,
        "database": NOTION_SELF_IMPROVEMENT_DB,
        "suggestion_pages": suggestion_pages,
        "suggestion_count": len(suggestion_pages),
    }


def _property_text(properties: dict[str, Any], name: str) -> str:
    prop = properties.get(name) or {}
    kind = prop.get("type")
    if kind in {"title", "rich_text"}:
        return "".join((item.get("plain_text") or "") for item in prop.get(kind) or [])
    if kind == "select":
        return str(((prop.get("select") or {}).get("name")) or "")
    return ""


def _property_checkbox(properties: dict[str, Any], name: str) -> bool:
    prop = properties.get(name) or {}
    return bool(prop.get("checkbox")) if prop.get("type") == "checkbox" else False


def _proposal_action_filter() -> dict[str, Any]:
    return {
        "and": [
            {"property": "Type", "select": {"equals": "Suggestion"}},
            {
                "or": [
                    {"property": "Auto Groom", "checkbox": {"equals": True}},
                    {"property": "Run Grooming", "checkbox": {"equals": True}},
                    {"property": "Auto-dev Implementation", "checkbox": {"equals": True}},
                ]
            },
        ]
    }


def _action_slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-")
    return cleaned[:80] or "self-improvement-action"


def _action_prompt(proposal: dict[str, Any], *, action_type: str, page_id: str) -> str:
    proposal_id = str(proposal.get("proposal_id") or "")
    title = str(proposal.get("title") or proposal_id or "Self-improvement suggestion")
    if action_type == "groom":
        objective = (
            "Use $aos-product-orchestrator to turn this suggestion into a proper Agentic OS spec packet "
            "and a Linear issue under the Agentic OS project. Resolve the Linear workspace, team, and project "
            "before any write. Do not mutate live shared OS surfaces except for the approved spec/Linear "
            "tracking outputs and receipt updates."
        )
    else:
        objective = (
            "Run the implementation workflow start to finish for this suggestion. "
            "Route through the Agentic OS work item, make code or documentation changes as needed, "
            "run focused validation, and leave receipt-backed status."
        )
    proposal_yaml = yaml.safe_dump(proposal, sort_keys=False)
    registration_rules = ""
    if action_type == "auto_dev":
        registration_rules = (
            "- Register every artifact file you create or modify: append its OS-root-relative path to the "
            f"`artifacts` list of this proposal's entry ({proposal_id}) in `{SI_TOGGLES_PATH}`. "
            "This registration is what lets the operator switch the improvement off later.\n"
            "- Changes must be additive and reversible: create new surfaces; never delete or rewrite "
            "unrelated existing ones.\n"
        )
    return f"""# Self-Improvement Action Worker

Action: {action_type}
Proposal: {proposal_id}
Notion page: {page_id}
Work item: {SELF_IMPROVEMENT_WORK_ITEM}

## Objective

{objective}

## Operating Rules

- Load the Agentic OS routing/context files before acting.
- Keep filesystem work items and receipts as the source of truth.
- Verify Genome's Notion before any Notion write.
- Do not publish local paths or private Notion links to Jira, GitHub, Slack, or email.
- For grooming, create or update the Linear issue in the Agentic OS project only after workspace/project/team verification.
- If implementation is unsafe or underspecified, stop with a blocker-grade receipt instead of guessing.
{registration_rules}
## Proposal

```yaml
{proposal_yaml}```
"""


def _write_action_worker(root: Path, proposal: dict[str, Any], *, action_type: str, page_id: str) -> dict[str, str]:
    proposal_id = str(proposal.get("proposal_id") or "unknown")
    action_root = _ensure_safe_dir(root, _resolve_root_relative(root, ACTION_OUTPUT_ROOT))
    prompts_dir = _safe_descendant(root, action_root, "prompts")
    _ensure_safe_dir(root, prompts_dir)
    stamp = _stamp()
    basename = _action_slug(f"{stamp}-{action_type}-{proposal_id}-{page_id[:8]}")
    prompt_path = _safe_child(root, prompts_dir, f"{basename}.md")
    instructions = _action_prompt(proposal, action_type=action_type, page_id=page_id)
    _atomic_write_text(root, prompt_path, instructions)
    return {
        "prompt": str(prompt_path.relative_to(root)),
        "action_root": str(action_root),
        "instructions": instructions,
    }


def _action_queue_item(
    root: Path,
    proposal: dict[str, Any],
    *,
    action_type: str,
    page_id: str,
    worker: dict[str, str],
) -> dict[str, Any]:
    proposal_id = str(proposal.get("proposal_id") or "unknown")
    queue_id = f"queue_self_improvement_{_digest(f'{page_id}:{proposal_id}:{action_type}', 12)}"
    return {
        "id": queue_id,
        "kind": "self_improvement_action",
        "ref": proposal_id,
        "status": "queued",
        "approval_state": "not_required",
        "dry_run": False,
        "idempotency_key": f"self-improvement-action:{page_id}:{proposal_id}:{action_type}",
        "execution_target": "codex_harness",
        "task_type": "llm.codex",
        "queue_name": "codex",
        "worker_pool": "codex_workers",
        "work_type": f"self_improvement_{action_type}",
        "route_to": SELF_IMPROVEMENT_WORK_ITEM,
        "instructions": worker["instructions"],
        "evidence": [
            {"type": "notion_page", "page_id": page_id},
            {"type": "proposal", "proposal_id": proposal_id},
            {"type": "prompt", "path": worker["prompt"]},
        ],
    }


def process_self_improvement_actions(
    root: str | Path,
    *,
    dry_run: bool = True,
    fetcher: Any = None,
) -> dict[str, Any]:
    os_root = expand_path(root)
    config = _load_yaml(os_root / CONFIG_PATH)
    transport = fetcher or notion_api._default_fetcher
    result: dict[str, Any] = {
        "action": "actions",
        "root": str(os_root),
        "mode": "dry-run" if dry_run else "apply",
        "ok": True,
        "actions": [],
        "queued": [],
        "skipped": [],
    }

    ledger = _read_intake_ledger(os_root)
    manifest = _notion_manifest(os_root)
    if not manifest.get("live"):
        result.update({"status": "blocked", "reason": "notion runtime tracking is not live in the manifest"})
        return result
    expected_workspace = str(manifest.get("workspace") or "")
    if "michael clark" in expected_workspace.lower() or "personal" in expected_workspace.lower():
        result.update({"status": "blocked", "reason": "manifest workspace appears to be a personal Notion"})
        return result
    database_id = (manifest.get("database_ids") or {}).get(NOTION_SELF_IMPROVEMENT_DB)
    if not database_id:
        result.update({"status": "blocked", "reason": f"manifest has no {NOTION_SELF_IMPROVEMENT_DB!r} database id"})
        return result
    if not notion_api.resolve_token(NOTION_TOKEN_ENV):
        result.update({"status": "blocked", "reason": f"notion token env var {NOTION_TOKEN_ENV!r} is not set"})
        return result

    try:
        verification_parent, approved_anchor = _verified_runtime_notion_anchor(
            manifest, transport
        )
        bot_workspace = notion_api.get_bot_workspace(
            NOTION_TOKEN_ENV,
            parent_page_id=verification_parent,
            fetcher=transport,
        )
        if expected_workspace and bot_workspace != expected_workspace:
            result.update(
                {
                    "status": "blocked",
                    "reason": f"live workspace {bot_workspace!r} does not match manifest workspace {expected_workspace!r}",
                }
            )
            return result
        available = notion_api.get_database_property_types(database_id, NOTION_TOKEN_ENV, fetcher=transport)
        _ensure_self_improvement_schema(
            database_id,
            available,
            fetcher=transport,
            approved_parent_page_id=approved_anchor,
        )
        pages = notion_api.query_database(database_id, _proposal_action_filter(), NOTION_TOKEN_ENV, fetcher=transport)
    except (RuntimeError, OSError, KeyError, ValueError) as exc:
        result.update({"ok": False, "status": "failed", "reason": str(exc)})
        return result

    for page in pages:
        page_id = str(page.get("id") or "").replace("-", "")
        properties = page.get("properties") or {}
        proposal_id = _property_text(properties, "Proposal ID")
        action_status = _property_text(properties, "Action Status")
        wants_auto_groom = _property_checkbox(properties, "Auto Groom")
        wants_run_grooming = _property_checkbox(properties, "Run Grooming")
        wants_grooming = wants_auto_groom or wants_run_grooming
        wants_auto_dev = _property_checkbox(properties, "Auto-dev Implementation")
        if action_status in {"queued", "running"}:
            result["skipped"].append({"page_id": page_id, "proposal_id": proposal_id, "reason": f"already_{action_status}"})
            continue
        if wants_grooming and wants_auto_dev:
            result["skipped"].append({"page_id": page_id, "proposal_id": proposal_id, "reason": "needs_single_action"})
            if not dry_run:
                notion_api.update_database_page(
                    page_id,
                    {
                        "Action Status": notion_api._select_prop("needs_choice"),
                        "Action Log": notion_api._rich_text_prop("Both action boxes were checked; clear one and the next watcher tick will queue it."),
                    },
                    NOTION_TOKEN_ENV,
                    approved_parent_page_id=approved_anchor,
                    fetcher=transport,
                )
            continue
        action_type = "groom" if wants_grooming else "auto_dev" if wants_auto_dev else ""
        if not action_type:
            continue
        if not proposal_id:
            result["skipped"].append({"page_id": page_id, "reason": "missing_proposal_id"})
            continue
        # Durable ledger guard: a proposal+action pair is queued at most once,
        # even when the daily report mints a fresh suggestion page (new page_id)
        # for the same proposal or the post-queue Notion update failed last tick.
        action_key = f"{proposal_id}:{action_type}"
        prior = (ledger.get("actions") or {}).get(action_key)
        if prior:
            result["skipped"].append(
                {
                    "page_id": page_id,
                    "proposal_id": proposal_id,
                    "reason": "already_processed_ledger",
                    "queue_item_id": prior.get("queue_id"),
                }
            )
            if not dry_run:
                # Re-clear the trigger boxes so a stale page stops re-firing the watcher.
                update_props = {
                    "Action Status": notion_api._select_prop("queued"),
                    "Action Log": notion_api._rich_text_prop(
                        f"Already queued as {prior.get('queue_id')} (durable ledger); not re-queued."
                    ),
                }
                if action_type == "groom":
                    update_props["Auto Groom"] = notion_api._checkbox_prop(False)
                    update_props["Run Grooming"] = notion_api._checkbox_prop(False)
                else:
                    update_props["Auto-dev Implementation"] = notion_api._checkbox_prop(False)
                notion_api.update_database_page(
                    page_id,
                    update_props,
                    NOTION_TOKEN_ENV,
                    approved_parent_page_id=approved_anchor,
                    fetcher=transport,
                )
            continue
        try:
            proposal = _load_proposal(os_root, config, proposal_id)
        except ValueError as exc:
            result["skipped"].append({"page_id": page_id, "proposal_id": proposal_id, "reason": str(exc)})
            if not dry_run:
                notion_api.update_database_page(
                    page_id,
                    {
                        "Action Status": notion_api._select_prop("blocked"),
                        "Action Log": notion_api._rich_text_prop(str(exc)),
                    },
                    NOTION_TOKEN_ENV,
                    approved_parent_page_id=approved_anchor,
                    fetcher=transport,
                )
            continue

        if dry_run:
            result["actions"].append({"page_id": page_id, "proposal_id": proposal_id, "action_type": action_type})
            continue
        worker = _write_action_worker(os_root, proposal, action_type=action_type, page_id=page_id)
        item = _action_queue_item(os_root, proposal, action_type=action_type, page_id=page_id, worker=worker)
        result["actions"].append({"page_id": page_id, "proposal_id": proposal_id, "action_type": action_type, "queue_item": item})
        from .runtime_ops import append_run_queue_item

        queued = append_run_queue_item(os_root, item)
        result["queued"].append(queued["queue_item"])
        # Durable record BEFORE the Notion page update: if the update below
        # fails, the next watcher tick hits the ledger instead of re-queueing.
        ledger["actions"][action_key] = {"queue_id": item["id"], "page_id": page_id, "queued_at": _now()}
        _write_intake_ledger(os_root, ledger)
        update_props = {
            "Action Status": notion_api._select_prop("queued"),
            "Action Log": notion_api._rich_text_prop(f"Queued {item['id']} at {_now()}."),
        }
        if action_type == "groom":
            update_props["Auto Groom"] = notion_api._checkbox_prop(False)
            update_props["Run Grooming"] = notion_api._checkbox_prop(False)
        else:
            update_props["Auto-dev Implementation"] = notion_api._checkbox_prop(False)
        notion_api.update_database_page(
            page_id,
            update_props,
            NOTION_TOKEN_ENV,
            approved_parent_page_id=approved_anchor,
            fetcher=transport,
        )

    result["status"] = "dry-run" if dry_run else "processed"
    return result


def _markdown_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> list[str]:
    lines = ["| " + " | ".join(label for label, _key in columns) + " |"]
    lines.append("| " + " | ".join("---" for _label, _key in columns) + " |")
    for row in rows:
        values = [_cell(str(row.get(key) or ""), limit=180) for _label, key in columns]
        lines.append("| " + " | ".join(values) + " |")
    return lines


ADDED_TO_SYSTEM_EMPTY = "Nothing was auto-applied overnight."
ADDED_TO_SYSTEM_TOGGLE_HINT = "agentic-os self-improvement toggle <proposal-id> --off --root <root>"


def _added_to_system_last_24h(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """Collect what the autonomous lanes added in the last 24 hours.

    Reads the nightly-apply receipts (approved/queued/implemented rows) and the
    per-improvement toggle ledger so the morning report can show the operator
    exactly what changed overnight and how to switch any item off.
    """
    now = now or datetime.now(timezone.utc)
    window_start = now - timedelta(hours=24)
    items: list[dict[str, Any]] = []
    receipts_dir = _resolve_root_relative(root, NIGHTLY_APPLY_ROOT)
    if receipts_dir.is_dir():
        for path in sorted(receipts_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            generated = _parse_time(str(payload.get("generated_at") or ""))
            if generated is None or generated < window_start:
                continue
            receipt_rel = _relative_path(root, path)
            for row in payload.get("approved") or []:
                if isinstance(row, dict):
                    items.append(
                        {"kind": "approved", "proposal_id": row.get("proposal_id"), "target": "", "receipt": receipt_rel}
                    )
            for row in payload.get("queued") or []:
                if isinstance(row, dict):
                    items.append(
                        {
                            "kind": "queued",
                            "proposal_id": row.get("proposal_id"),
                            "target": row.get("target"),
                            "receipt": receipt_rel,
                        }
                    )
            for row in payload.get("implemented") or []:
                if isinstance(row, dict):
                    items.append(
                        {
                            "kind": "implemented",
                            "proposal_id": row.get("proposal_id"),
                            "target": row.get("target"),
                            "receipt": receipt_rel,
                        }
                    )
    toggles: list[dict[str, Any]] = []
    for proposal_id, entry in sorted((_read_si_toggles(root).get("toggles") or {}).items()):
        if not isinstance(entry, dict):
            continue
        queued_at = _parse_time(str(entry.get("queued_at") or ""))
        if queued_at is None or queued_at < window_start:
            continue
        toggles.append(
            {
                "proposal_id": proposal_id,
                "title": entry.get("title"),
                "target": entry.get("target"),
                "enabled": bool(entry.get("enabled", True)),
                "artifacts": [str(item) for item in entry.get("artifacts") or []],
                "queued_at": entry.get("queued_at"),
            }
        )
    return {
        "window_hours": 24,
        "items": items,
        "toggles": toggles,
        "toggle_command": ADDED_TO_SYSTEM_TOGGLE_HINT,
    }


def _morning_report_markdown(root: Path, result: dict[str, Any]) -> str:
    date_value = str(result.get("date") or _today())
    validation_before = result.get("validation_before") or {}
    validation_after = result.get("validation_after") or validation_before
    repair = result.get("repair") or {}
    self_review = result.get("self_improvement") or {}
    source_inventory = result.get("source_inventory") or {}
    external_readiness = source_inventory.get("readiness") or {}

    lines = [f"# Self Improvement Morning Report - {date_value}", ""]
    lines.append(
        "Daily autonomous self-improvement run for Agentic OS. Filesystem receipts are the source of truth; "
        "Notion is the morning reading surface."
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Validation before: {validation_before.get('error_count', 0)} error(s), {validation_before.get('warning_count', 0)} warning(s).")
    lines.append(f"- Validation after: {validation_after.get('error_count', 0)} error(s), {validation_after.get('warning_count', 0)} warning(s).")
    lines.append(f"- Deterministic repair actions applied: {repair.get('applied_count', 0)}.")
    lines.append(f"- Evidence files analyzed: {self_review.get('evidence_files', 0)}.")
    lines.append(f"- Self-improvement findings: {len(self_review.get('findings') or [])}.")
    lines.append(f"- Proposal candidates: {len(self_review.get('proposal_candidates') or [])}.")
    lines.append("")

    lines.append("## What Was Analyzed")
    lines.append("")
    analyzed = []
    for entry in self_review.get("evidence_roots") or []:
        analyzed.append(
            {
                "Source": str(entry.get("path") or ""),
                "Status": "present" if entry.get("exists") else "missing",
                "Mode": "legacy_read_only" if entry.get("legacy_read_only") else "active",
            }
        )
    if analyzed:
        lines.extend(_markdown_table(analyzed, [("Source", "Source"), ("Status", "Status"), ("Mode", "Mode")]))
    else:
        lines.append("- No evidence roots were available.")
    lines.append("")

    lines.append("## External Source Readiness")
    lines.append("")
    source_rows = [{"Source": key, "Status": value} for key, value in sorted(external_readiness.items())]
    if source_rows:
        lines.extend(_markdown_table(source_rows, [("Source", "Source"), ("Status", "Status")]))
    else:
        lines.append("- No external sources configured.")
    lines.append("")

    lines.append("## What Was Found")
    lines.append("")
    findings = self_review.get("findings") or []
    if findings:
        finding_rows = []
        for finding in findings:
            finding_rows.append(
                {
                    "Title": str(finding.get("title") or ""),
                    "Type": str(finding.get("type") or ""),
                    "Score": str((finding.get("score") or {}).get("total") or ""),
                    "Evidence": str(finding.get("evidence") or ""),
                }
            )
        lines.extend(_markdown_table(finding_rows, [("Title", "Title"), ("Type", "Type"), ("Score", "Score"), ("Evidence", "Evidence")]))
    else:
        lines.append("- No self-improvement findings exceeded the deterministic threshold.")
    lines.append("")

    if validation_after.get("errors"):
        lines.append("## Remaining Validation Drift")
        lines.append("")
        for item in validation_after.get("errors") or []:
            lines.append(f"- {item}")
        lines.append("")

    lines.append("## What Was Updated")
    lines.append("")
    actions = repair.get("actions") or []
    updated_rows = [
        {
            "Status": str(action.get("status") or ""),
            "Type": str(action.get("type") or action.get("reason") or ""),
            "Path": str(action.get("path") or action.get("message") or ""),
        }
        for action in actions
    ]
    if updated_rows:
        lines.extend(_markdown_table(updated_rows, [("Status", "Status"), ("Type", "Type"), ("Path", "Path")]))
    else:
        lines.append("- No deterministic repair actions were needed.")
    lines.append("")

    lines.append("## Added To The System (Last 24h)")
    lines.append("")
    added = result.get("added_to_system") or {}
    added_items = added.get("items") or []
    added_toggles = added.get("toggles") or []
    if added_items or added_toggles:
        if added_items:
            item_rows = [
                {
                    "Kind": str(item.get("kind") or ""),
                    "Proposal": str(item.get("proposal_id") or ""),
                    "Target": str(item.get("target") or ""),
                    "Receipt": str(item.get("receipt") or ""),
                }
                for item in added_items
            ]
            lines.extend(
                _markdown_table(
                    item_rows,
                    [("Kind", "Kind"), ("Proposal", "Proposal"), ("Target", "Target"), ("Receipt", "Receipt")],
                )
            )
        for toggle in added_toggles:
            state = "on" if toggle.get("enabled") else "off"
            artifacts = ", ".join(f"`{path}`" for path in toggle.get("artifacts") or []) or "none registered yet"
            lines.append(
                f"- Toggle {toggle.get('proposal_id')} [{state}] target={toggle.get('target')} artifacts: {artifacts}"
            )
        lines.append("")
        lines.append(f"Switch any item off with: `{ADDED_TO_SYSTEM_TOGGLE_HINT}`")
    else:
        lines.append(ADDED_TO_SYSTEM_EMPTY)
    lines.append("")

    lines.append("## Filesystem Receipts")
    lines.append("")
    for write in result.get("writes") or []:
        lines.append(f"- {write.get('type')}: `{write.get('path')}`")
    lines.append("")
    return "\n".join(lines)


def _write_morning_report(root: Path, result: dict[str, Any]) -> dict[str, str]:
    date_value = str(result.get("date") or _today())
    run_id = str(result.get("run_id") or _stamp())
    report_dir = _safe_descendant(root, _resolve_root_relative(root, MORNING_REPORT_ROOT), date_value)
    _ensure_safe_dir(root, report_dir)
    report_path = _safe_child(root, report_dir, "report.md")
    log_path = _safe_child(root, report_dir, "logs.yml")
    receipt_path = _safe_child(root, report_dir, f"{run_id}.yml")
    report_content = _morning_report_markdown(root, result)
    log_data = _morning_log_payload(result)
    _atomic_write_text(root, report_path, report_content)
    _atomic_write_yaml(root, log_path, log_data)
    receipt = json.loads(json.dumps(result, default=str))
    _atomic_write_yaml(root, receipt_path, receipt)
    return {
        "report": _relative_path(root, report_path),
        "logs": _relative_path(root, log_path),
        "receipt": _relative_path(root, receipt_path),
    }


def _morning_log_payload(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": result.get("run_id"),
        "date": result.get("date"),
        "generated_at": result.get("generated_at"),
        "validation_before": result.get("validation_before"),
        "validation_after": result.get("validation_after"),
        "repair": result.get("repair"),
        "source_inventory": result.get("source_inventory"),
        "morning_report": result.get("morning_report"),
        "notion_page_projection": result.get("notion_page_projection"),
        "writes": result.get("writes"),
        "self_improvement": {
            "evidence_files": (result.get("self_improvement") or {}).get("evidence_files"),
            "findings": (result.get("self_improvement") or {}).get("findings"),
            "proposal_candidates": [
                candidate.get("proposal_id")
                for candidate in (result.get("self_improvement") or {}).get("proposal_candidates") or []
            ],
            "writes": (result.get("self_improvement") or {}).get("writes"),
            "report": (result.get("self_improvement") or {}).get("report"),
            "notion_projection": (result.get("self_improvement") or {}).get("notion_projection"),
        },
    }


def _notion_text(value: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": value[:2000]}}]


def _notion_block(block_type: str, text: str) -> dict[str, Any]:
    return {"object": "block", "type": block_type, block_type: {"rich_text": _notion_text(text)}}


def _notion_bullets(values: list[str]) -> list[dict[str, Any]]:
    return [_notion_block("bulleted_list_item", value) for value in values]


def _notion_url(page_id: str) -> str:
    return f"https://www.notion.so/{page_id.replace('-', '')}"


def _find_exact_page_by_title(pages: list[dict[str, Any]], title: str) -> dict[str, Any] | None:
    return next((page for page in pages if str(page.get("title") or "") == title), None)


def _project_morning_report_to_notion(
    root: Path,
    result: dict[str, Any],
    *,
    fetcher: Any = None,
) -> dict[str, Any]:
    transport = fetcher or notion_api._default_fetcher
    config = _load_yaml(root / CONFIG_PATH)
    notion_report_config = config.get("notion_report") if isinstance(config.get("notion_report"), dict) else {}
    parent_title = str(notion_report_config.get("parent_title") or NOTION_REPORT_PARENT_TITLE)
    reports_title = str(notion_report_config.get("reports_page_title") or NOTION_REPORTS_PAGE_TITLE)
    configured_parent_id = str(notion_report_config.get("parent_page_id") or "").strip()
    date_value = str(result.get("date") or _today())
    title = f"Self Improvement Report - {date_value}"
    logs_title = f"Self Improvement Logs - {date_value} - {_stamp()}"

    def _degrade(reason: str) -> dict[str, Any]:
        output_root = _resolve_root_relative(root, MORNING_REPORT_ROOT)
        draft_dir = _safe_descendant(root, output_root, date_value)
        _ensure_safe_dir(root, draft_dir)
        draft_path = _safe_child(root, draft_dir, f"{_stamp()}-notion-page-draft.md")
        draft = (
            f"# Notion page projection draft - {date_value}\n\n"
            f"Projection was not performed: {reason}.\n\n"
            f"Target: {parent_title} / {reports_title}\n"
        )
        _atomic_write_text(root, draft_path, draft)
        return {"projected": False, "reason": reason, "draft": _relative_path(root, draft_path)}

    if not notion_api.resolve_token(NOTION_TOKEN_ENV):
        return _degrade(f"notion token env var {NOTION_TOKEN_ENV!r} is not set")
    approved_root = configured_parent_id or (
        os.environ.get("GENOMES_NOTION_PARENT_PAGE_ID", "").strip()
        if transport is notion_api._default_fetcher
        else ""
    )
    if transport is notion_api._default_fetcher and not approved_root:
        return _degrade(
            "GENOMES_NOTION_PARENT_PAGE_ID or notion_report.parent_page_id is required"
        )
    try:
        workspace = notion_api.get_bot_workspace(
            NOTION_TOKEN_ENV,
            parent_page_id=approved_root or None,
            fetcher=transport,
        )
    except (RuntimeError, OSError, ValueError) as exc:
        return _degrade(f"workspace verification failed: {exc}")
    if workspace != "Genome's Notion":
        return _degrade(f"live workspace {workspace!r} is not Genome's Notion")

    try:
        if configured_parent_id:
            parent_id = configured_parent_id.replace("-", "")
        elif approved_root:
            parent_id = approved_root.replace("-", "")
        else:
            parent_pages = notion_api.search_pages(parent_title, NOTION_TOKEN_ENV, fetcher=transport)
            parent = _find_exact_page_by_title(parent_pages, parent_title)
            if not parent:
                return _degrade(f"could not find parent page {parent_title!r}")
            parent_id = str(parent["id"])
        child_pages = notion_api.search_child_pages(parent_id, NOTION_TOKEN_ENV, fetcher=transport)
        reports_page = _find_exact_page_by_title(child_pages, reports_title)
        if reports_page:
            reports_page_id = str(reports_page["id"])
        else:
            reports_page_id = notion_api.create_page(
                parent_id,
                reports_title,
                NOTION_TOKEN_ENV,
                approved_parent_page_id=parent_id,
                fetcher=transport,
            )
            notion_api.append_block_children(
                reports_page_id,
                [
                    _notion_block("heading_2", "Purpose"),
                    _notion_block(
                        "paragraph",
                        "Daily Agentic OS self-improvement reports. Filesystem artifacts remain the source of truth.",
                    ),
                ],
                NOTION_TOKEN_ENV,
                approved_parent_page_id=parent_id,
                fetcher=transport,
            )

        daily_pages = notion_api.search_child_pages(reports_page_id, NOTION_TOKEN_ENV, fetcher=transport)
        daily_page = _find_exact_page_by_title(daily_pages, title)
        daily_page_id = str(daily_page["id"]) if daily_page else notion_api.create_page(
            reports_page_id,
            title,
            NOTION_TOKEN_ENV,
            approved_parent_page_id=reports_page_id,
            fetcher=transport,
        )
        logs_page_id = notion_api.create_page(
            daily_page_id,
            logs_title,
            NOTION_TOKEN_ENV,
            approved_parent_page_id=daily_page_id,
            fetcher=transport,
        )
        report_blocks = _morning_report_notion_blocks(result)
        log_blocks = _morning_logs_notion_blocks(result)
        notion_api.append_block_children(
            daily_page_id,
            report_blocks,
            NOTION_TOKEN_ENV,
            approved_parent_page_id=reports_page_id,
            fetcher=transport,
        )
        notion_api.append_block_children(
            logs_page_id,
            log_blocks,
            NOTION_TOKEN_ENV,
            approved_parent_page_id=daily_page_id,
            fetcher=transport,
        )
    except (RuntimeError, OSError, KeyError, ValueError) as exc:
        return _degrade(f"notion page projection failed: {exc}")
    return {
        "projected": True,
        "workspace": workspace,
        "reports_page_id": reports_page_id,
        "report_page_id": daily_page_id,
        "logs_page_id": logs_page_id,
        "report_url": _notion_url(daily_page_id),
        "logs_url": _notion_url(logs_page_id),
    }


def _morning_report_notion_blocks(result: dict[str, Any]) -> list[dict[str, Any]]:
    validation_before = result.get("validation_before") or {}
    validation_after = result.get("validation_after") or {}
    repair = result.get("repair") or {}
    self_review = result.get("self_improvement") or {}
    source_inventory = result.get("source_inventory") or {}
    readiness = source_inventory.get("readiness") or {}
    blocks = [
        _notion_block("heading_2", "Summary"),
        *_notion_bullets(
            [
                f"Validation before: {validation_before.get('error_count', 0)} error(s), {validation_before.get('warning_count', 0)} warning(s).",
                f"Validation after: {validation_after.get('error_count', 0)} error(s), {validation_after.get('warning_count', 0)} warning(s).",
                f"Deterministic repairs applied: {repair.get('applied_count', 0)}.",
                f"Evidence files analyzed: {self_review.get('evidence_files', 0)}.",
                f"Findings: {len(self_review.get('findings') or [])}.",
            ]
        ),
        _notion_block("heading_2", "What Was Analyzed"),
    ]
    evidence_roots = self_review.get("evidence_roots") or []
    blocks.extend(
        _notion_bullets(
            [
                f"{entry.get('path')}: {'present' if entry.get('exists') else 'missing'}"
                for entry in evidence_roots[:30]
            ]
            or ["No evidence roots were available."]
        )
    )
    blocks.append(_notion_block("heading_2", "External Source Readiness"))
    blocks.extend(_notion_bullets([f"{key}: {value}" for key, value in sorted(readiness.items())] or ["No external sources configured."]))
    blocks.append(_notion_block("heading_2", "What Was Found"))
    findings = self_review.get("findings") or []
    blocks.extend(
        _notion_bullets(
            [
                f"{finding.get('title')} ({finding.get('type')}): {finding.get('summary')}"
                for finding in findings[:20]
            ]
            or ["No findings exceeded the deterministic threshold."]
        )
    )
    blocks.append(_notion_block("heading_2", "What Was Updated"))
    actions = repair.get("actions") or []
    blocks.extend(
        _notion_bullets(
            [
                f"{action.get('status')}: {action.get('type') or action.get('reason')} {action.get('path') or action.get('message') or ''}"
                for action in actions[:30]
            ]
            or ["No deterministic repair actions were needed."]
        )
    )
    blocks.append(_notion_block("heading_2", "Added To The System (Last 24h)"))
    added = result.get("added_to_system") or {}
    added_lines = [
        f"{item.get('kind')}: {item.get('proposal_id')}" + (f" ({item.get('target')})" if item.get("target") else "")
        for item in (added.get("items") or [])[:30]
    ]
    added_lines.extend(
        f"toggle {toggle.get('proposal_id')} [{'on' if toggle.get('enabled') else 'off'}] "
        f"target={toggle.get('target')} artifacts={len(toggle.get('artifacts') or [])}"
        for toggle in (added.get("toggles") or [])[:30]
    )
    if added_lines:
        added_lines.append(f"Switch any item off with: {ADDED_TO_SYSTEM_TOGGLE_HINT}")
        blocks.extend(_notion_bullets(added_lines))
    else:
        blocks.extend(_notion_bullets([ADDED_TO_SYSTEM_EMPTY]))
    paths = result.get("morning_report") or {}
    blocks.append(_notion_block("heading_2", "Filesystem Version"))
    blocks.extend(_notion_bullets([f"{key}: {value}" for key, value in sorted(paths.items())] or ["Filesystem report path not recorded."]))
    return blocks


def _morning_logs_notion_blocks(result: dict[str, Any]) -> list[dict[str, Any]]:
    repair = result.get("repair") or {}
    validation_after = result.get("validation_after") or {}
    blocks = [
        _notion_block("heading_2", "Repair Actions"),
        *_notion_bullets(
            [
                f"{action.get('status')}: {action.get('type') or action.get('reason')} {action.get('path') or action.get('message') or ''}"
                for action in (repair.get("actions") or [])[:80]
            ]
            or ["No repair actions recorded."]
        ),
        _notion_block("heading_2", "Remaining Validation Errors"),
        *_notion_bullets([str(error) for error in (validation_after.get("errors") or [])[:80]] or ["No remaining validation errors."]),
    ]
    writes = []
    for write in result.get("writes") or []:
        writes.append(f"{write.get('type')}: {write.get('path')}")
    blocks.append(_notion_block("heading_2", "Filesystem Writes"))
    blocks.extend(_notion_bullets(writes[:80] or ["No filesystem writes recorded."]))
    return blocks


def run_self_improvement(root: str | Path, *, dry_run: bool = True) -> dict[str, Any]:
    os_root = expand_path(root)
    config_path = os_root / CONFIG_PATH
    config = _load_yaml(config_path)
    evidence_roots = _configured_evidence_roots(os_root, config)
    records = _collect_evidence(evidence_roots, max_age_days=_evidence_max_age_days(config))
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
    result["queue_reconciliation"] = reconcile_self_improvement_queue(
        os_root,
        dry_run=False,
        latest_run={**run_record, "path": str(run_path.relative_to(os_root))},
    )

    report_paths = _write_daily_report(os_root, result)
    result["report"] = report_paths
    result["writes"].extend(
        [
            {"type": "report", "path": report_paths["latest"]},
            {"type": "report", "path": report_paths["archive"]},
        ]
    )
    notion_projection = _project_run_to_notion(os_root, result, report_paths)
    result["notion_projection"] = notion_projection
    if notion_projection.get("draft"):
        result["writes"].append({"type": "notion-draft", "path": notion_projection["draft"]})
    return result


def run_self_improvement_morning_report(
    root: str | Path,
    *,
    dry_run: bool = True,
    publish_notion: bool = True,
    auto_fix: bool = True,
) -> dict[str, Any]:
    os_root = expand_path(root)
    config_path = os_root / CONFIG_PATH
    config = _load_yaml(config_path)
    generated_at = _now()
    run_id = f"morning-{_stamp()}-{_digest({'root': str(os_root), 'generated_at': generated_at}, 8)}"
    validation_before = _validation_snapshot(os_root)
    repair = _repair_validation_drift(os_root, validation_before, apply=(not dry_run and auto_fix))
    validation_after = _validation_snapshot(os_root) if not dry_run and auto_fix else validation_before
    self_review = run_self_improvement(os_root, dry_run=dry_run)
    result: dict[str, Any] = {
        "action": "morning-report",
        "ok": True,
        "validation_ok": bool(validation_after.get("ok")),
        "mode": "dry-run" if dry_run else "apply",
        "run_id": run_id,
        "date": _today(),
        "generated_at": generated_at,
        "root": os_root,
        "config": config_path,
        "validation_before": validation_before,
        "validation_after": validation_after,
        "repair": repair,
        "source_inventory": _source_inventory(os_root, config),
        "self_improvement": self_review,
        "added_to_system": _added_to_system_last_24h(os_root),
        "writes": [],
    }
    if dry_run:
        return result

    morning_paths = _write_morning_report(os_root, result)
    result["morning_report"] = morning_paths
    result["writes"].extend(
        [
            {"type": "morning-report", "path": morning_paths["report"]},
            {"type": "morning-logs", "path": morning_paths["logs"]},
            {"type": "morning-receipt", "path": morning_paths["receipt"]},
        ]
    )
    if publish_notion:
        notion_projection = _project_morning_report_to_notion(os_root, result)
        result["notion_page_projection"] = notion_projection
        if notion_projection.get("draft"):
            result["writes"].append({"type": "notion-page-draft", "path": notion_projection["draft"]})
    else:
        result["notion_page_projection"] = {"projected": False, "reason": "disabled_by_flag"}
    # Refresh the visible artifacts after receipt paths and Notion projection
    # have been recorded.
    _atomic_write_text(os_root, os_root / morning_paths["report"], _morning_report_markdown(os_root, result))
    _atomic_write_yaml(os_root, os_root / morning_paths["logs"], _morning_log_payload(result))
    _atomic_write_yaml(os_root, os_root / morning_paths["receipt"], json.loads(json.dumps(result, default=str)))
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
        "queue_health": self_improvement_queue_health(os_root),
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
    validation_items = [str(item) for item in proposal.get("validation_plan") or []]
    validation_markdown = "\n".join(f"- {item}" for item in validation_items) or "- Define validation before implementation."
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
            "SPEC.md": (
                f"# {title}\n\n"
                f"Proposal: `{proposal_id}`\n\n"
                f"{summary}\n\n"
                "## Acceptance Criteria\n\n"
                f"{validation_markdown}\n\n"
                "## Evidence\n\n"
                f"{_evidence_markdown(proposal)}\n"
            ),
            "PLAN.md": "# Plan\n\n- Review the proposal evidence.\n- Implement the draft behind normal validation gates.\n",
            "VALIDATION.md": f"# Validation\n\n{validation_markdown}\n",
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


def _nightly_apply_policy(config: dict[str, Any]) -> dict[str, Any]:
    """Merge the configured nightly_apply block over safe defaults.

    Keeps the lane deterministic even when the control-plane file predates the
    nightly_apply key or leaves parts of it unset.
    """
    policy = dict(NIGHTLY_APPLY_DEFAULTS)
    configured = config.get("nightly_apply") or {}
    if isinstance(configured, dict):
        policy.update(configured)
    auto = dict(NIGHTLY_APPLY_DEFAULTS["auto_approve"])
    configured_auto = configured.get("auto_approve") if isinstance(configured, dict) else None
    if isinstance(configured_auto, dict):
        auto.update(configured_auto)
    policy["auto_approve"] = auto
    implement = dict(NIGHTLY_APPLY_DEFAULTS["auto_implement"])
    configured_implement = configured.get("auto_implement") if isinstance(configured, dict) else None
    if isinstance(configured_implement, dict):
        implement.update(configured_implement)
    classes = implement.get("classes")
    implement["classes"] = dict(classes) if isinstance(classes, dict) else {}
    policy["auto_implement"] = implement
    return policy


def _proposal_score_total(proposal: dict[str, Any]) -> int:
    score = proposal.get("score") or {}
    try:
        return int(score.get("total") or 0)
    except (TypeError, ValueError):
        return 0


def _proposal_age_days(proposal: dict[str, Any], now: datetime) -> float | None:
    created = _parse_time(proposal.get("created_at"))
    if created is None:
        return None
    return (now - created).total_seconds() / 86400.0


def _nightly_intake_properties(
    available: dict[str, str],
    proposal: dict[str, Any],
    *,
    seq: int = 0,
) -> dict[str, Any]:
    """Build 🧭 OS Work Intake row properties, sending only columns that exist.

    Auto Mode is intentionally left UNCHECKED: an operator (or the Notion watcher)
    flips it to actually dispatch the queued work.

    Title format: ``SI-NNN — imperative-slug [proposal-id]`` where NNN is the
    caller-allocated sequence number (pinned per proposal in the intake ledger)
    and the slug is derived from the proposal summary. The trailing proposal id
    is load-bearing: the Notion-side dedup guard filters on title *contains*
    proposal_id, so a title without it never matches and every re-projection
    files a fresh row (the 2026-07 SI-003 duplicate incident).
    """
    proposal_id = str(proposal.get("proposal_id") or "")
    summary = str(proposal.get("title") or proposal.get("summary") or proposal_id)
    slug = _imperative_slug(summary)
    title_str = f"SI-{seq:03d} — {slug}"
    if proposal_id:
        title_str = f"{title_str} [{proposal_id}]"
    desired: dict[str, tuple[str, Any]] = {
        "Name": ("title", title_str),
        "Type": ("select", "improvement"),
        "Project": ("select", "Agentic OS"),
        "Status": ("select", "queued"),
        "Priority": ("select", "P2"),
        "Source": ("select", "self-improvement"),
        "Harness": ("select", "either"),
        "Auto Mode": ("checkbox", False),
    }
    properties: dict[str, Any] = {}
    for name, (kind, value) in desired.items():
        if name not in available:
            continue
        if kind == "title":
            properties[name] = notion_api._title_prop(str(value))
        elif kind == "select":
            properties[name] = notion_api._select_prop(str(value))
        elif kind == "checkbox":
            properties[name] = notion_api._checkbox_prop(bool(value))
    return properties


def _nightly_intake_body(proposal: dict[str, Any], draft_paths: list[str]) -> list[dict[str, Any]]:
    """Compose the Notion page body: 'What to do' opener + provenance + drafts.

    The first block is always a bold "What to do:" paragraph so the row is
    immediately actionable when opened. The text is derived from the proposal
    summary/evidence fields; downstream operators should not need to open the
    draft artifact just to know what action is expected.
    """
    summary_text = str(proposal.get("summary") or proposal.get("title") or "")
    evidence_text = str(proposal.get("evidence") or "")
    # Build a 1-2 sentence imperative description from the proposal content.
    what_to_do_parts = [summary_text] if summary_text else []
    if evidence_text and evidence_text != summary_text:
        what_to_do_parts.append(evidence_text)
    what_to_do = " ".join(what_to_do_parts)[:400] or "Review and act on this self-improvement proposal."
    blocks: list[dict[str, Any]] = [
        _bold_paragraph(f"What to do: {what_to_do}"),
        _heading(2, "Self-improvement proposal"),
        _paragraph(summary_text),
        _heading(3, "Provenance"),
        _bullet(f"proposal_id: {proposal.get('proposal_id')}"),
        _bullet(f"recommended_artifact: {proposal.get('recommended_artifact')}"),
        _bullet(f"score.total: {_proposal_score_total(proposal)}"),
        _bullet(f"created_at: {proposal.get('created_at')}"),
        _bullet("source: nightly-apply (automation.self_improvement)"),
    ]
    if draft_paths:
        blocks.append(_heading(3, "Draft artifacts"))
        blocks.extend(_bullet(path) for path in draft_paths)
    validation = [str(item) for item in proposal.get("validation_plan") or []]
    if validation:
        blocks.append(_heading(3, "Validation plan"))
        blocks.extend(_bullet(item) for item in validation)
    return blocks


def _project_nightly_row_to_intake(
    proposal: dict[str, Any],
    draft_paths: list[str],
    *,
    root: Path | None = None,
    approved_parent_page_id: str | None = None,
    fetcher: Any | None = None,
) -> dict[str, Any]:
    """Best-effort projection of one queued item into the OS Work Intake DB.

    Never raises: Notion failures are returned as a degraded record so the caller
    can log them in the run receipt and continue (projection is best-effort per
    OS rules).

    Defense layers (in order):
    1. Durable ledger — root-local ``si-intake-ledger.json`` records
       proposal_id -> page_id on every successful create; a hit short-circuits
       before any Notion call, so re-processing stays a no-op even when Notion
       is unreachable.
    2. Token check — short-circuit if Notion token is absent.
    3. Notion-side dedup guard — query the Work Intake DB for an existing
       non-dropped row whose title contains the proposal_id. Row titles carry
       the proposal_id (``SI-NNN — slug [proposal-id]``) precisely so this
       filter can match; a hit heals the local ledger.
    4. SI sequence counter — allocated once per proposal via ``_next_si_seq``
       and pinned in the ledger, so a retry after a Notion failure reuses the
       same SI-NNN instead of consuming a new number.
    """
    transport = fetcher or notion_api._default_fetcher
    proposal_id = str(proposal.get("proposal_id") or "")
    # --- Durable ledger guard (primary) ------------------------------------
    ledger: dict[str, Any] | None = None
    entry: dict[str, Any] = {}
    if root is not None and proposal_id:
        ledger = _read_intake_ledger(root)
        entry = dict(ledger["proposals"].get(proposal_id) or {})
        if entry.get("page_id"):
            page_id = str(entry["page_id"])
            return {
                "projected": True,
                "page_id": page_id,
                "url": str(entry.get("url") or _notion_url(page_id)),
                "deduped": "ledger",
            }
    if transport is notion_api._default_fetcher and not notion_api.resolve_token(
        NOTION_TOKEN_ENV
    ):
        return {"projected": False, "reason": "notion_token_missing"}
    if transport is notion_api._default_fetcher:
        if not approved_parent_page_id:
            return {
                "projected": False,
                "reason": "approved_parent_page_id_missing",
            }
        try:
            database_parent = notion_api.get_database_parent_page_id(
                WORK_INTAKE_DB_ID, NOTION_TOKEN_ENV, fetcher=transport
            )
        except Exception as exc:  # noqa: BLE001 - projection remains best-effort
            return {
                "projected": False,
                "reason": f"notion_parent_error: {type(exc).__name__}: {exc}"[:300],
            }
        if not notion_api._same_notion_id(
            database_parent, approved_parent_page_id
        ):
            return {
                "projected": False,
                "reason": "intake_database_outside_approved_parent",
            }
    # --- Notion-side dedup guard (secondary; heals a lost ledger) -----------
    if proposal_id:
        existing_id = _query_existing_intake_row(proposal_id, transport, NOTION_TOKEN_ENV)
        if existing_id:
            if ledger is not None:
                entry.update({"page_id": existing_id, "url": _notion_url(existing_id), "projected_at": _now()})
                ledger["proposals"][proposal_id] = entry
                _write_intake_ledger(root, ledger)
            return {
                "projected": True,
                "page_id": existing_id,
                "url": _notion_url(existing_id),
                "deduped": "notion_guard",
            }
    # --- SI sequence: allocate once per proposal, pinned in the ledger ------
    seq = int(entry.get("seq") or 0)
    if seq <= 0 and root is not None:
        seq = _next_si_seq(root)
        if ledger is not None:
            entry["seq"] = seq
            ledger["proposals"][proposal_id] = entry
            _write_intake_ledger(root, ledger)
    try:
        available = notion_api.get_database_property_types(WORK_INTAKE_DB_ID, NOTION_TOKEN_ENV, fetcher=transport)
        properties = _nightly_intake_properties(available, proposal, seq=seq)
        if "Name" not in properties:
            return {"projected": False, "reason": "intake_missing_name_property"}
        page_id = notion_api.create_database_page(
            WORK_INTAKE_DB_ID,
            properties,
            NOTION_TOKEN_ENV,
            children=_nightly_intake_body(proposal, draft_paths),
            approved_parent_page_id=approved_parent_page_id,
            fetcher=transport,
        )
    except Exception as exc:  # noqa: BLE001 - projection must never fail the run
        return {"projected": False, "reason": f"notion_error: {type(exc).__name__}: {exc}"[:300]}
    if ledger is not None:
        entry.update({"seq": seq, "page_id": page_id, "url": _notion_url(page_id), "projected_at": _now()})
        ledger["proposals"][proposal_id] = entry
        _write_intake_ledger(root, ledger)
    return {"projected": True, "page_id": page_id, "url": _notion_url(page_id)}


def _send_nightly_notification(
    root: Path,
    *,
    source: str,
    approved: int,
    queued: int,
    skipped: int,
    dry_run: bool,
    implemented: int = 0,
    notifier: Any | None = None,
) -> dict[str, Any]:
    """Emit one summary notification via agentic-os-notify. Best-effort."""
    title = "Self-improvement nightly-apply" + (" (dry-run)" if dry_run else "")
    message = f"approved {approved}, queued {queued}, implemented {implemented}, skipped {skipped}"
    if notifier is not None:
        try:
            notifier(source=source, title=title, message=message, level="info", dry_run=dry_run)
            return {"sent": True, "message": message}
        except Exception as exc:  # noqa: BLE001
            return {"sent": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}
    notify_bin = root / NOTIFY_BIN
    if not notify_bin.is_file():
        return {"sent": False, "reason": "notify_bin_missing"}
    cmd = [
        str(notify_bin),
        "--source",
        source,
        "--title",
        title,
        "--message",
        message,
        "--level",
        "info",
    ]
    if dry_run:
        cmd.append("--dry-run")
    try:
        import subprocess

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    except Exception as exc:  # noqa: BLE001
        return {"sent": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}
    if result.returncode != 0:
        return {"sent": False, "reason": f"exit_{result.returncode}: {(result.stderr or '').strip()[:160]}"}
    return {"sent": True, "message": message}


def _nightly_apply_receipt_path(root: Path) -> Path:
    directory = _resolve_root_relative(root, NIGHTLY_APPLY_ROOT)
    return _safe_child(root, directory, f"{_stamp()}.json")


def nightly_apply_self_improvement(
    root: str | Path,
    *,
    dry_run: bool = True,
    limit: int | None = None,
    approved_parent_page_id: str | None = None,
    fetcher: Any | None = None,
    notifier: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Auto-triage low-risk proposals into queued, executable work.

    Selects proposals still at ``promotion_status == "proposed"`` whose
    recommended_artifact is in the configured auto_approve.classes and whose
    score.total meets auto_approve.min_score, capped at max_per_night (and
    ``limit`` when supplied). Each selected proposal is approved and promoted via
    the existing mechanics, then projected (best-effort) into the OS Work Intake
    database. Proposals that stay ``proposed`` past ``stale_after_days`` without
    matching the policy are surfaced as ``stale_triage`` for operator visibility
    (no state change). One summary notification is sent per run.
    """
    os_root = expand_path(root)
    config = _load_yaml(os_root / CONFIG_PATH)
    policy = _nightly_apply_policy(config)
    auto = policy["auto_approve"]
    implement_policy = policy["auto_implement"]
    implement_enabled = bool(implement_policy.get("enabled"))
    implement_classes = {
        str(key): bool(value) for key, value in (implement_policy.get("classes") or {}).items()
    }
    implement_max = int(implement_policy.get("max_per_night") or 0)
    now = now or datetime.now(timezone.utc)
    classes = {str(item) for item in (auto.get("classes") or [])}
    min_score = int(auto.get("min_score") or 0)
    max_per_night = int(auto.get("max_per_night") or 0)
    if limit is not None:
        max_per_night = min(max_per_night, max(0, int(limit)))
    stale_after_days = float(policy.get("stale_after_days") or 7)
    notify_source = str(policy.get("notify_source") or "automation.self_improvement")

    proposals = [_read_yaml(path) for path in _proposal_files(os_root, config)]
    eligible: list[dict[str, Any]] = []
    stale_triage: list[dict[str, Any]] = []
    for proposal in proposals:
        if str(proposal.get("promotion_status")) != "proposed":
            continue
        artifact = str(proposal.get("recommended_artifact") or "")
        matches = artifact in classes and _proposal_score_total(proposal) >= min_score
        if matches:
            eligible.append(proposal)
            continue
        age = _proposal_age_days(proposal, now)
        if age is not None and age >= stale_after_days:
            stale_triage.append(
                {
                    "proposal_id": proposal.get("proposal_id"),
                    "recommended_artifact": artifact,
                    "score": _proposal_score_total(proposal),
                    "age_days": round(age, 1),
                    "note": "proposed past stale_after_days and outside auto_approve policy",
                }
            )

    enabled = bool(policy.get("enabled"))
    eligible.sort(key=lambda item: (-_proposal_score_total(item), str(item.get("created_at") or "")))
    # A disabled lane never selects anything; eligible is still reported for visibility.
    if not enabled:
        selected: list[dict[str, Any]] = []
        deferred_over_cap: list[dict[str, Any]] = []
    elif max_per_night > 0:
        selected = eligible[:max_per_night]
        deferred_over_cap = [
            {"proposal_id": item.get("proposal_id"), "reason": "over_max_per_night"}
            for item in eligible[max_per_night:]
        ]
    else:
        selected = []
        deferred_over_cap = [
            {"proposal_id": item.get("proposal_id"), "reason": "max_per_night_is_zero"} for item in eligible
        ]

    result: dict[str, Any] = {
        "action": "nightly-apply",
        "ok": True,
        "root": os_root,
        "mode": "dry-run" if dry_run else "apply",
        "enabled": enabled,
        "policy": {
            "classes": sorted(classes),
            "min_score": min_score,
            "max_per_night": max_per_night,
            "stale_after_days": stale_after_days,
            "queue_target": policy.get("queue_target"),
            "notify_source": notify_source,
            "auto_implement": {
                "enabled": implement_enabled,
                "classes": implement_classes,
                "max_per_night": implement_max,
            },
        },
        "eligible": [item.get("proposal_id") for item in eligible],
        "selected": [item.get("proposal_id") for item in selected],
        "deferred_over_cap": deferred_over_cap,
        "stale_triage": stale_triage,
        "approved": [],
        "queued": [],
        "implemented": [],
        "implement_candidates": [],
        "skipped_implement": [],
        "notion_failures": [],
        "errors": [],
    }

    if not enabled:
        result["skipped_reason"] = "nightly_apply_disabled"

    # Preview of the auto-implement lane: which selected proposals would be
    # queued for implementation. Computed for dry-run reporting and reused as
    # the apply-mode plan (the apply lane still re-checks the durable ledger).
    if implement_enabled:
        ledger_actions = _read_intake_ledger(os_root).get("actions") or {}
        for item in selected:
            if len(result["implement_candidates"]) >= implement_max:
                break
            target = str(item.get("recommended_artifact") or "")
            if not implement_classes.get(target):
                continue
            if f"{item.get('proposal_id')}:auto_dev" in ledger_actions:
                continue
            result["implement_candidates"].append({"proposal_id": item.get("proposal_id"), "target": target})

    if dry_run or not selected:
        # No approvals happen on a dry-run or when nothing is eligible. We
        # deliberately send the notification in quiet (dry-run) mode here so an
        # enabled apply-night with zero eligible proposals does not emit an alert
        # about no-op work — this matches the quiet-by-default operator posture.
        result["notification"] = _send_nightly_notification(
            os_root,
            source=notify_source,
            approved=len(result["approved"]),
            queued=len(result["queued"]),
            skipped=len(stale_triage) + len(deferred_over_cap),
            dry_run=True,  # quiet: no delivery for a preview or a no-op apply
            implemented=len(result["implemented"]),
            notifier=notifier,
        )
        if not dry_run:
            # Even a no-op apply writes a receipt for the audit trail.
            result["receipt"] = _write_nightly_apply_receipt(os_root, result)
        return result

    _validate_output_paths(os_root, config)
    promoted_rows: list[dict[str, Any]] = []
    for proposal in selected:
        proposal_id = str(proposal.get("proposal_id"))
        target = str(proposal.get("recommended_artifact") or "")
        try:
            approval = approve_self_improvement_proposal(
                os_root, proposal_id, target=target, approver=notify_source
            )
            promotion = promote_self_improvement_proposal(os_root, proposal_id, target=target)
        except Exception as exc:  # noqa: BLE001 - record and continue with the next item
            result["errors"].append({"proposal_id": proposal_id, "error": f"{type(exc).__name__}: {exc}"[:300]})
            continue
        result["approved"].append({"proposal_id": proposal_id, "approval_id": approval.get("approval_id")})
        draft_paths = [str(path) for path in promotion.get("draft_paths") or []]
        refreshed = _load_proposal(os_root, config, proposal_id)
        projection = _project_nightly_row_to_intake(
            refreshed,
            draft_paths,
            root=os_root,
            approved_parent_page_id=approved_parent_page_id,
            fetcher=fetcher,
        )
        queued_row = {
            "proposal_id": proposal_id,
            "target": target,
            "draft_paths": draft_paths,
            "notion": projection,
        }
        result["queued"].append(queued_row)
        if not projection.get("projected"):
            result["notion_failures"].append({"proposal_id": proposal_id, "reason": projection.get("reason")})
        promoted_rows.append(
            {"proposal_id": proposal_id, "target": target, "proposal": refreshed, "projection": projection}
        )

    # Auto-implement lane: queue an auto_dev worker (reusing the Notion-action
    # mechanics) for approved+promoted proposals whose class toggle is on.
    if implement_enabled and promoted_rows:
        ledger = _read_intake_ledger(os_root)
        for row in promoted_rows:
            proposal_id = str(row["proposal_id"])
            target = str(row["target"])
            if not implement_classes.get(target):
                continue
            if len(result["implemented"]) >= implement_max:
                result["skipped_implement"].append(
                    {"proposal_id": proposal_id, "reason": "over_auto_implement_max_per_night"}
                )
                continue
            action_key = f"{proposal_id}:auto_dev"
            prior = (ledger.get("actions") or {}).get(action_key)
            if prior:
                result["skipped_implement"].append(
                    {
                        "proposal_id": proposal_id,
                        "reason": "already_processed_ledger",
                        "queue_item_id": prior.get("queue_id"),
                    }
                )
                continue
            projection = row.get("projection") or {}
            page_id = (
                str(projection.get("page_id"))
                if projection.get("projected") and projection.get("page_id")
                else f"local{_digest(proposal_id, 12)}"
            )
            try:
                worker = _write_action_worker(os_root, row["proposal"], action_type="auto_dev", page_id=page_id)
                item = _action_queue_item(
                    os_root, row["proposal"], action_type="auto_dev", page_id=page_id, worker=worker
                )
                from .runtime_ops import append_run_queue_item

                append_run_queue_item(os_root, item)
                # Durable record BEFORE any Notion write: a later tick (or the
                # Notion action watcher) hits the ledger instead of re-queueing.
                ledger["actions"][action_key] = {"queue_id": item["id"], "page_id": page_id, "queued_at": _now()}
                _write_intake_ledger(os_root, ledger)
                toggles = _read_si_toggles(os_root)
                toggles["toggles"][proposal_id] = {
                    "enabled": True,
                    "status": "queued",
                    "target": target,
                    "title": str(row["proposal"].get("title") or ""),
                    "queued_at": _now(),
                    "artifacts": [],
                    "disabled_at": None,
                }
                _write_si_toggles(os_root, toggles)
            except Exception as exc:  # noqa: BLE001 - record and continue with the next item
                result["errors"].append({"proposal_id": proposal_id, "error": f"{type(exc).__name__}: {exc}"[:300]})
                continue
            result["implemented"].append(
                {
                    "proposal_id": proposal_id,
                    "target": target,
                    "queue_id": item["id"],
                    "prompt": worker["prompt"],
                    "execution_target": item["execution_target"],
                }
            )

    result["notification"] = _send_nightly_notification(
        os_root,
        source=notify_source,
        approved=len(result["approved"]),
        queued=len(result["queued"]),
        skipped=len(stale_triage) + len(deferred_over_cap),
        dry_run=False,
        implemented=len(result["implemented"]),
        notifier=notifier,
    )
    result["receipt"] = _write_nightly_apply_receipt(os_root, result)
    return result


def _write_nightly_apply_receipt(root: Path, result: dict[str, Any]) -> str:
    path = _nightly_apply_receipt_path(root)
    payload = {
        "schema_version": 1,
        "action": "nightly-apply",
        "generated_at": _now(),
        "mode": result.get("mode"),
        "enabled": result.get("enabled"),
        "policy": result.get("policy"),
        "selected": result.get("selected"),
        "approved": result.get("approved"),
        "queued": result.get("queued"),
        "implemented": result.get("implemented"),
        "implement_candidates": result.get("implement_candidates"),
        "skipped_implement": result.get("skipped_implement"),
        "deferred_over_cap": result.get("deferred_over_cap"),
        "stale_triage": result.get("stale_triage"),
        "notion_failures": result.get("notion_failures"),
        "errors": result.get("errors"),
        "notification": result.get("notification"),
    }
    _atomic_write_text(root, path, json.dumps(payload, indent=2, default=str) + "\n")
    return str(path.relative_to(root))


# ---------------------------------------------------------------------------
# Per-improvement feature toggles
# ---------------------------------------------------------------------------


def _si_toggles_path(root: Path) -> Path:
    directory = _resolve_root_relative(root, str(Path(SI_TOGGLES_PATH).parent))
    return _safe_child(root, directory, Path(SI_TOGGLES_PATH).name)


def _read_si_toggles(root: Path) -> dict[str, Any]:
    """Load the per-improvement toggle ledger. Missing or corrupt degrades to empty."""
    path = _si_toggles_path(root)
    if path.exists():
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                toggles = raw.get("toggles")
                return {
                    "schema_version": 1,
                    "toggles": toggles if isinstance(toggles, dict) else {},
                }
        except Exception:  # noqa: BLE001 - corrupt ledger degrades to empty
            pass
    return {"schema_version": 1, "toggles": {}}


def _write_si_toggles(root: Path, data: dict[str, Any]) -> None:
    _atomic_write_yaml(root, _si_toggles_path(root), data)


def _flattened_artifact_name(index: int, artifact: str) -> str:
    flattened = re.sub(r"[^A-Za-z0-9._-]+", "-", artifact).strip("-.") or "artifact"
    return f"{index}-{flattened}"[:120]


def list_self_improvement_toggles(root: str | Path) -> dict[str, Any]:
    os_root = expand_path(root)
    ledger = _read_si_toggles(os_root)
    return {"action": "toggles", "root": os_root, "toggles": ledger["toggles"]}


def set_self_improvement_toggle(root: str | Path, proposal_id: str, *, enabled: bool) -> dict[str, Any]:
    """Switch one auto-implemented improvement on or off.

    Toggle OFF parks every registered artifact under the disabled run root
    (recording the move so toggle ON can restore it); paths that resolve outside
    the OS root are refused and left untouched. Toggling to the current state is
    a no-op that reports ``changed: false``.
    """
    os_root = expand_path(root)
    ledger = _read_si_toggles(os_root)
    entry = ledger["toggles"].get(proposal_id)
    if not isinstance(entry, dict):
        raise ValueError(f"unknown self-improvement toggle: {proposal_id}")
    result: dict[str, Any] = {
        "action": "toggle",
        "root": os_root,
        "proposal_id": proposal_id,
        "enabled": enabled,
        "changed": False,
        "moved": [],
        "restored": [],
        "refused": [],
        "skipped": [],
    }
    if bool(entry.get("enabled", True)) == enabled:
        return result
    if not enabled:
        disabled_dir = _safe_descendant(
            os_root, _resolve_root_relative(os_root, SI_DISABLED_ROOT), proposal_id
        )
        moved: list[dict[str, str]] = []
        for index, artifact in enumerate(str(item) for item in entry.get("artifacts") or []):
            source = _path_under_root(os_root, artifact)
            if source is None:
                result["refused"].append({"path": artifact, "reason": "outside_os_root"})
                continue
            if not source.exists():
                result["skipped"].append({"path": artifact, "reason": "missing"})
                continue
            destination = _safe_child(os_root, disabled_dir, _flattened_artifact_name(index, artifact))
            if destination.exists():
                result["skipped"].append({"path": artifact, "reason": "disabled_copy_exists"})
                continue
            source.rename(destination)
            moved.append({"from": _relative_path(os_root, source), "to": _relative_path(os_root, destination)})
        entry["moved"] = moved
        entry["enabled"] = False
        entry["disabled_at"] = _now()
        result["moved"] = moved
    else:
        restored: list[dict[str, str]] = []
        for move in entry.get("moved") or []:
            if not isinstance(move, dict):
                continue
            source = _path_under_root(os_root, str(move.get("to") or ""))
            destination = _path_under_root(os_root, str(move.get("from") or ""))
            if source is None or destination is None:
                result["refused"].append({"path": str(move.get("from") or ""), "reason": "outside_os_root"})
                continue
            if destination.exists():
                result["skipped"].append({"path": _relative_path(os_root, destination), "reason": "destination_exists"})
                continue
            if not source.exists():
                result["skipped"].append({"path": _relative_path(os_root, source), "reason": "disabled_copy_missing"})
                continue
            _ensure_safe_dir(os_root, destination.parent)
            source.rename(destination)
            restored.append({"from": _relative_path(os_root, source), "to": _relative_path(os_root, destination)})
        entry["moved"] = []
        entry["enabled"] = True
        entry["disabled_at"] = None
        result["restored"] = restored
    ledger["toggles"][proposal_id] = entry
    _write_si_toggles(os_root, ledger)
    result["changed"] = True
    return result


def format_self_improvement_result(result: dict[str, Any]) -> str:
    action = result.get("action")
    if action == "nightly-apply":
        lines = [
            "Self Improvement Nightly Apply" + (" (dry-run)" if result.get("mode") == "dry-run" else ""),
            f"root: {result['root']}",
            f"enabled: {result.get('enabled')}",
        ]
        if result.get("skipped_reason"):
            lines.append(f"skipped: {result['skipped_reason']}")
        policy = result.get("policy") or {}
        lines.append(
            "policy: classes="
            f"{','.join(policy.get('classes') or [])} "
            f"min_score={policy.get('min_score')} max_per_night={policy.get('max_per_night')}"
        )
        lines.append(f"eligible: {len(result.get('eligible') or [])}")
        lines.append(f"selected: {len(result.get('selected') or [])}")
        lines.append(f"approved: {len(result.get('approved') or [])}")
        lines.append(f"queued: {len(result.get('queued') or [])}")
        lines.append(f"implemented: {len(result.get('implemented') or [])}")
        lines.append(f"implement_candidates: {len(result.get('implement_candidates') or [])}")
        lines.append(f"stale_triage: {len(result.get('stale_triage') or [])}")
        for row in result.get("queued") or []:
            notion = row.get("notion") or {}
            state = notion.get("url") if notion.get("projected") else f"notion:{notion.get('reason')}"
            lines.append(f"- queued {row.get('proposal_id')} ({row.get('target')}) -> {state}")
        for row in result.get("implemented") or []:
            lines.append(f"- implemented {row.get('proposal_id')} ({row.get('target')}) -> {row.get('queue_id')}")
        for row in result.get("implement_candidates") or []:
            lines.append(f"- implement_candidate {row.get('proposal_id')} ({row.get('target')})")
        for row in result.get("skipped_implement") or []:
            lines.append(f"- skipped_implement {row.get('proposal_id')}: {row.get('reason')}")
        for item in result.get("stale_triage") or []:
            lines.append(f"- stale_triage {item.get('proposal_id')} ({item.get('age_days')}d, score={item.get('score')})")
        for item in result.get("errors") or []:
            lines.append(f"- error {item.get('proposal_id')}: {item.get('error')}")
        notification = result.get("notification") or {}
        lines.append(f"notification: {'sent' if notification.get('sent') else notification.get('reason')}")
        if result.get("receipt"):
            lines.append(f"receipt: {result['receipt']}")
        if result.get("mode") == "dry-run":
            lines.append("Next step: rerun with --apply to approve, promote, and queue eligible proposals.")
        return "\n".join(lines)

    if action == "morning-report":
        validation_before = result.get("validation_before") or {}
        validation_after = result.get("validation_after") or {}
        repair = result.get("repair") or {}
        self_review = result.get("self_improvement") or {}
        lines = [
            "Self Improvement Morning Report",
            f"root: {result['root']}",
            f"mode: {result['mode']}",
            f"run_id: {result['run_id']}",
            f"validation_before: {validation_before.get('error_count', 0)} errors / {validation_before.get('warning_count', 0)} warnings",
            f"validation_after: {validation_after.get('error_count', 0)} errors / {validation_after.get('warning_count', 0)} warnings",
            f"repair_actions_applied: {repair.get('applied_count', 0)}",
            f"evidence_files: {self_review.get('evidence_files', 0)}",
            f"findings: {len(self_review.get('findings') or [])}",
        ]
        morning_report = result.get("morning_report") or {}
        if morning_report:
            lines.append(f"Report: {morning_report.get('report')}")
            lines.append(f"Logs: {morning_report.get('logs')}")
        projection = result.get("notion_page_projection") or {}
        if projection.get("projected"):
            lines.append(f"Notion: {projection.get('report_url')}")
            lines.append(f"Notion logs: {projection.get('logs_url')}")
        elif projection.get("draft"):
            lines.append(f"Notion: degraded to draft ({projection.get('reason')}): {projection['draft']}")
        elif projection:
            lines.append(f"Notion: {projection.get('reason')}")
        if result["mode"] == "dry-run":
            lines.append("Next step: rerun with --apply to write repairs, filesystem report, and Notion page projection.")
        return "\n".join(lines)

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
        queue_health = result.get("queue_health") or {}
        lines.append("queue_health:")
        lines.append(f"- status: {queue_health.get('status') or 'unknown'}")
        lines.append(f"- stale_items: {queue_health.get('stale_count') or 0}")
        latest_run = queue_health.get("latest_run") or {}
        if latest_run:
            lines.append(f"- latest_run: {latest_run.get('run_id')} at {latest_run.get('completed_at')}")
        for item in queue_health.get("stale_items") or []:
            lines.append(f"- stale: {item.get('id')} ({item.get('stale_reason')})")
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

    if action == "toggles":
        lines = ["Self Improvement Toggles", f"root: {result['root']}"]
        toggles = result.get("toggles") or {}
        if not toggles:
            lines.append("- none")
        for proposal_id, entry in sorted(toggles.items()):
            entry = entry if isinstance(entry, dict) else {}
            state = "on" if entry.get("enabled", True) else "off"
            lines.append(
                f"- {proposal_id} [{state}] target={entry.get('target')} "
                f"artifacts={len(entry.get('artifacts') or [])} queued_at={entry.get('queued_at')}"
            )
        return "\n".join(lines)

    if action == "toggle":
        state = "on" if result.get("enabled") else "off"
        lines = [
            "Self Improvement Toggle",
            f"root: {result['root']}",
            f"proposal: {result.get('proposal_id')}",
            f"enabled: {state}",
            f"changed: {result.get('changed')}",
        ]
        for move in result.get("moved") or []:
            lines.append(f"- moved {move.get('from')} -> {move.get('to')}")
        for move in result.get("restored") or []:
            lines.append(f"- restored {move.get('from')} -> {move.get('to')}")
        for item in result.get("refused") or []:
            lines.append(f"- refused {item.get('path')}: {item.get('reason')}")
        for item in result.get("skipped") or []:
            lines.append(f"- skipped {item.get('path')}: {item.get('reason')}")
        return "\n".join(lines)

    if action == "actions":
        lines = [
            "Self Improvement Actions",
            f"root: {result['root']}",
            f"mode: {result['mode']}",
            f"status: {result.get('status') or 'unknown'}",
            f"actions: {len(result.get('actions') or [])}",
            f"queued: {len(result.get('queued') or [])}",
            f"skipped: {len(result.get('skipped') or [])}",
        ]
        if result.get("reason"):
            lines.append(f"reason: {result['reason']}")
        return "\n".join(lines)

    if action == "reconcile-queue":
        lines = [
            "Self Improvement Queue Reconciliation",
            f"root: {result['root']}",
            f"mode: {result['mode']}",
            f"queue_path: {result['queue_path']}",
            f"changed: {result.get('changed', False)}",
            f"reconciled: {len(result.get('reconciled') or [])}",
            f"skipped: {len(result.get('skipped') or [])}",
        ]
        for item in result.get("reconciled") or []:
            lines.append(f"- reconciled {item.get('id')}: {item.get('reconcile_reason')}")
        for item in result.get("skipped") or []:
            lines.append(f"- skipped {item.get('id', 'none')}: {item.get('reason')}")
        return "\n".join(lines)

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
        lines.extend(["Proposal writes: disabled in dry-run", "Next step: rerun without --dry-run to document a report and write gated proposal files."])
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
        report = result.get("report") or {}
        if report.get("latest"):
            lines.append(f"Report: {report['latest']}")
        projection = result.get("notion_projection") or {}
        if projection.get("projected"):
            lines.append(f"Notion: row created in {projection.get('database')}")
        elif projection.get("draft"):
            lines.append(f"Notion: degraded to draft ({projection.get('reason')}): {projection['draft']}")
    return "\n".join(lines)
