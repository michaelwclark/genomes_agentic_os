"""Durable single-flight coordination for Auto-Dev review calls.

The review subject, rather than the selected reviewer identity, owns the stable
key.  This prevents switching models or stages from silently purchasing the
same full review again.  Receipts are immutable review results with one
optional provider-post readback layered on top.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Iterator, Mapping
import uuid


REVIEW_RECEIPT_SCHEMA = "auto-dev-review-receipt/v1"
TERMINAL_REVIEW_OUTCOMES = {"clean", "findings", "unavailable"}
SUCCESSFUL_REVIEW_OUTCOMES = {"clean", "findings"}
FINDING_STATUSES = {"open", "resolved"}
FINDING_SEVERITIES = {"blocking", "high", "medium", "low", "info"}
STRUCTURED_REVIEW_FINDINGS_PATTERN = re.compile(
    r"```json\s*(\[.*?\])\s*```", re.IGNORECASE | re.DOTALL
)
STRUCTURED_REVIEW_FINDING_FIELDS = {
    "id",
    "severity",
    "category",
    "file",
    "line",
    "title",
    "detail",
    "suggested_fix",
    "blocking",
}


class ReviewCoordinationError(RuntimeError):
    """Raised when review coordination evidence is invalid or unavailable."""


class ReviewBudgetExceeded(ReviewCoordinationError):
    """Raised before an external call would exceed the review budget."""


@dataclass(frozen=True)
class ReviewBudget:
    """Default circuit breakers for one PR review family."""

    full_reviews_per_chain: int = 1
    delta_reviews_per_chain: int = 3
    absolute_full_reviews_per_family: int = 2
    provider_posts_per_family: int = 1


@dataclass(frozen=True)
class ReviewSubject:
    """The exact review authority that determines reuse eligibility."""

    repository: str
    pull_request: str
    base_branch: str
    base_sha: str
    head_sha: str
    policy_fingerprint: str
    purpose: str = "review_self"

    def __post_init__(self) -> None:
        # Git/provider SHAs and sha256 fingerprints are case-insensitive hex.
        # Canonicalize them before any key is computed so uppercase provider
        # output cannot purchase a second review for the same revisions.
        object.__setattr__(self, "base_sha", str(self.base_sha).strip().lower())
        object.__setattr__(self, "head_sha", str(self.head_sha).strip().lower())
        object.__setattr__(
            self,
            "policy_fingerprint",
            str(self.policy_fingerprint).strip().lower(),
        )
        required = {
            "repository": self.repository,
            "pull_request": self.pull_request,
            "base_branch": self.base_branch,
            "base_sha": self.base_sha,
            "head_sha": self.head_sha,
            "policy_fingerprint": self.policy_fingerprint,
            "purpose": self.purpose,
        }
        missing = [name for name, value in required.items() if not str(value).strip()]
        if missing:
            raise ReviewCoordinationError(
                "review subject requires non-empty " + ", ".join(sorted(missing))
            )
        for name, value in (("base_sha", self.base_sha), ("head_sha", self.head_sha)):
            if not re.fullmatch(r"[0-9a-f]{40}", str(value)):
                raise ReviewCoordinationError(
                    f"review subject {name} must be a full 40-hex commit SHA"
                )
        if not re.fullmatch(r"[0-9a-f]{64}", self.policy_fingerprint):
            raise ReviewCoordinationError(
                "review subject policy_fingerprint must be a sha256 digest"
            )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ReviewSubject":
        return cls(
            repository=str(value.get("repository") or ""),
            pull_request=str(value.get("pull_request") or ""),
            base_branch=str(value.get("base_branch") or ""),
            base_sha=str(value.get("base_sha") or ""),
            head_sha=str(value.get("head_sha") or ""),
            policy_fingerprint=str(value.get("policy_fingerprint") or ""),
            purpose=str(value.get("purpose") or "review_self"),
        )


@dataclass(frozen=True)
class ReviewRunResult:
    key: str
    receipt_path: Path
    receipt: dict[str, Any]
    reused: bool


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _canonical_hash(value: Any) -> str:
    encoded = _canonical_json(value)
    return hashlib.sha256(encoded).hexdigest()


def stable_review_key(subject: ReviewSubject) -> str:
    """Return the reviewer-independent key for one exact review subject."""

    return _canonical_hash(asdict(subject))


def advisory_recovery_key(
    parent_key: str, evidence_sha256: str, findings_sha256: str
) -> str:
    """Return a deterministic immutable child key for advisory-only recovery."""

    if not re.fullmatch(r"[0-9a-f]{64}", str(parent_key)):
        raise ReviewCoordinationError("advisory recovery requires a canonical parent key")
    if not re.fullmatch(r"[0-9a-f]{64}", str(evidence_sha256)):
        raise ReviewCoordinationError("advisory recovery requires an evidence sha256")
    if not re.fullmatch(r"[0-9a-f]{64}", str(findings_sha256)):
        raise ReviewCoordinationError("advisory recovery requires a findings sha256")
    return _canonical_hash(
        {
            "kind": "advisory-recovery/v1",
            "parent_key": parent_key,
            "evidence_sha256": evidence_sha256,
            "findings_sha256": findings_sha256,
        }
    )


def _immutable_structured_findings(response: str) -> list[dict[str, Any]]:
    """Parse the one reviewer-owned findings array used for advisory recovery."""

    blocks = STRUCTURED_REVIEW_FINDINGS_PATTERN.findall(response)
    if len(blocks) != 1:
        raise ReviewCoordinationError(
            "advisory recovery response must contain exactly one fenced JSON findings array"
        )
    try:
        raw_findings = json.loads(blocks[0])
    except json.JSONDecodeError as exc:
        raise ReviewCoordinationError(
            f"advisory recovery findings JSON is invalid: {exc}"
        ) from exc
    if not isinstance(raw_findings, list) or not raw_findings:
        raise ReviewCoordinationError(
            "advisory recovery findings JSON must be a non-empty array"
        )

    parsed: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_findings, start=1):
        if not isinstance(raw, Mapping):
            raise ReviewCoordinationError(
                f"advisory recovery finding {index} must be an object"
            )
        missing = sorted(STRUCTURED_REVIEW_FINDING_FIELDS - set(raw))
        if missing:
            raise ReviewCoordinationError(
                "advisory recovery finding "
                f"{index} missing fields: {', '.join(missing)}"
            )
        finding = dict(raw)
        finding["id"] = str(finding["id"]).strip()
        finding["severity"] = str(finding["severity"]).strip().lower()
        if not finding["id"]:
            raise ReviewCoordinationError(
                f"advisory recovery finding {index} id must be non-empty"
            )
        if finding["severity"] not in {"critical", "high", "medium", "low"}:
            raise ReviewCoordinationError(
                f"advisory recovery finding {index} has invalid severity"
            )
        if not isinstance(finding["blocking"], bool):
            raise ReviewCoordinationError(
                f"advisory recovery finding {index} blocking must be boolean"
            )
        parsed.append(finding)
    return parsed


def review_chain_key(subject: ReviewSubject) -> str:
    """Return the chain shared by one full review and its changed-head deltas."""

    value = asdict(subject)
    value.pop("head_sha")
    # Stages may describe the same review as review_self, finalize, or another
    # purpose.  Purpose is provenance, not a fresh paid-review budget.
    value.pop("purpose")
    return _canonical_hash(value)


def review_family_key(subject: ReviewSubject) -> str:
    """Return the provider PR family used for absolute circuit breakers."""

    return _canonical_hash(
        {
            "repository": subject.repository,
            "pull_request": subject.pull_request,
        }
    )


def _legacy_review_chain_key(subject: ReviewSubject) -> str:
    value = asdict(subject)
    value.pop("head_sha")
    return _canonical_hash(value)


def _legacy_review_family_key(subject: ReviewSubject) -> str:
    return _canonical_hash(
        {
            "repository": subject.repository,
            "pull_request": subject.pull_request,
            "purpose": subject.purpose,
        }
    )


def _legacy_subject_hash(
    subject: Mapping[str, Any], *, drop: tuple[str, ...] = ()
) -> str:
    """Hash a pre-canonicalization subject exactly as its writer saw it."""

    value = {
        "repository": str(subject.get("repository") or ""),
        "pull_request": str(subject.get("pull_request") or ""),
        "base_branch": str(subject.get("base_branch") or ""),
        "base_sha": str(subject.get("base_sha") or ""),
        "head_sha": str(subject.get("head_sha") or ""),
        "policy_fingerprint": str(subject.get("policy_fingerprint") or ""),
        "purpose": str(subject.get("purpose") or "review_self"),
    }
    for field in drop:
        value.pop(field, None)
    return _canonical_hash(value)


def provider_review_marker(key: str) -> str:
    """Return the provider-visible deduplication marker for a terminal post."""

    return f"<!-- agentic-os-review:{key} -->"


def canonical_review_purpose(_value: str | None = None) -> str:
    """Collapse stage/scope labels onto the one paid Auto-Dev review purpose."""

    return "review_self"


def shared_review_coordination_root(os_root: str | Path) -> Path:
    """Return the OS-wide receipt store shared by every review entrypoint."""

    requested = Path(os_root).expanduser().resolve()
    configured_raw = str(os.environ.get("AGENTIC_OS_ROOT") or "").strip()
    if configured_raw:
        configured = Path(configured_raw).expanduser().resolve()
        if requested != configured:
            raise ReviewCoordinationError(
                "review coordination root disagrees with canonical AGENTIC_OS_ROOT: "
                f"requested={requested} canonical={configured}"
            )
        requested = configured
    return requested / "state" / "review-coordination"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(value)
    temporary.replace(path)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, list | tuple | set) else [value]
    normalized: list[str] = []
    for item in values:
        if isinstance(item, Mapping):
            text = json.dumps(dict(item), sort_keys=True, separators=(",", ":"))
        else:
            text = str(item).strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _finding_id(*, summary: str, severity: str, evidence: list[str]) -> str:
    digest = _canonical_hash(
        {"summary": summary.strip(), "severity": severity, "evidence": evidence}
    )
    return f"finding-{digest[:16]}"


def _redact_scrub_hits(value: Any, hits: list[str]) -> Any:
    if isinstance(value, str):
        redacted = value
        for hit in hits:
            redacted = redacted.replace(hit, "[REDACTED]")
        return redacted
    if isinstance(value, list):
        return [_redact_scrub_hits(item, hits) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): _redact_scrub_hits(item, hits) for key, item in value.items()
        }
    return value


def normalize_findings_ledger(
    review: Mapping[str, Any],
    *,
    parent_ledger: list[Mapping[str, Any]] | None = None,
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    """Normalize reviewer output and preserve unresolved findings across deltas."""

    normalized_review = dict(review)
    outcome = str(normalized_review.get("outcome") or "")
    if outcome == "clean" and normalized_review.get("scrub_passed") is False:
        outcome = "unavailable"
        normalized_review["outcome"] = outcome
        normalized_review["coordination_warning"] = (
            "review output failed the provider scrub and remains retryable"
        )
    if outcome not in TERMINAL_REVIEW_OUTCOMES:
        raise ReviewCoordinationError(
            "review_call must return terminal outcome clean, findings, or unavailable"
        )

    inherited = [dict(row) for row in (parent_ledger or [])]
    raw_findings = normalized_review.get("findings_ledger")
    if raw_findings is None:
        raw_findings = normalized_review.get("findings")
    if raw_findings is None:
        raw_findings = []
    if not isinstance(raw_findings, list):
        raw_findings = [raw_findings]

    ledger: list[dict[str, Any]] = []
    for raw in raw_findings:
        item = dict(raw) if isinstance(raw, Mapping) else {"summary": str(raw)}
        summary = str(
            item.get("summary")
            or item.get("title")
            or item.get("message")
            or item.get("body")
            or "Reviewer finding"
        ).strip()
        severity = str(item.get("severity") or "medium").strip().lower()
        if severity not in FINDING_SEVERITIES:
            severity = "medium"
        evidence = _string_list(
            item.get("evidence")
            or item.get("locations")
            or item.get("location")
            or summary
        )
        raw_id = str(item.get("id") or item.get("finding_id") or "").strip()
        finding_id = (
            raw_id
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}", raw_id)
            else _finding_id(summary=summary, severity=severity, evidence=evidence)
        )
        resolution_value = item.get("resolution")
        resolution_refs = _string_list(item.get("resolution_refs"))
        resolution_summary = ""
        if isinstance(resolution_value, Mapping):
            resolution_refs.extend(
                ref
                for ref in _string_list(resolution_value.get("refs"))
                if ref not in resolution_refs
            )
            resolution_summary = str(resolution_value.get("summary") or "").strip()
        elif resolution_value:
            resolution_summary = str(resolution_value).strip()
        status = str(item.get("status") or "open").strip().lower()
        if status not in FINDING_STATUSES:
            status = "open"
        if status == "resolved" and not resolution_refs:
            status = "open"
        ledger.append(
            {
                "id": finding_id,
                "status": status,
                "severity": severity,
                "summary": summary,
                "evidence": evidence,
                "resolution": (
                    {"refs": resolution_refs, "summary": resolution_summary}
                    if resolution_refs
                    else None
                ),
            }
        )

    explicit_resolution_refs = set(_string_list(normalized_review.get("resolution_refs")))
    by_id = {str(row.get("id")): row for row in ledger}
    inherited_open: list[dict[str, Any]] = []
    for parent in inherited:
        finding_id = str(parent.get("id") or "")
        if parent.get("status") != "open":
            continue
        replacement = by_id.get(finding_id)
        replacement_refs = (
            _string_list((replacement.get("resolution") or {}).get("refs"))
            if isinstance(replacement, Mapping)
            and isinstance(replacement.get("resolution"), Mapping)
            else []
        )
        if finding_id in explicit_resolution_refs or replacement_refs:
            resolved = dict(parent)
            resolved["status"] = "resolved"
            resolved["resolution"] = {
                "refs": replacement_refs or [finding_id],
                "summary": str(
                    (replacement.get("resolution") or {}).get("summary")
                    if isinstance(replacement, Mapping)
                    else ""
                ).strip(),
            }
            by_id[finding_id] = resolved
            continue
        inherited_open.append(dict(parent))
        by_id.setdefault(finding_id, dict(parent))

    ledger = list(by_id.values())
    if outcome == "clean" and inherited_open:
        # Preserve the paid delta as a terminal receipt but never allow an
        # unreferenced "clean" string to erase known findings or trigger a rerun.
        outcome = "findings"
        normalized_review["outcome"] = "findings"
        normalized_review["coordination_warning"] = (
            "clean delta did not explicitly resolve inherited finding IDs"
        )
    if outcome == "findings" and not ledger:
        summary = str(
            normalized_review.get("summary")
            or normalized_review.get("text")
            or "Reviewer reported findings; see the attached review artifact."
        ).strip()
        evidence = _string_list(
            normalized_review.get("artifact_file")
            or normalized_review.get("evidence")
            or summary
        )
        ledger = [
            {
                "id": _finding_id(summary=summary, severity="medium", evidence=evidence),
                "status": "open",
                "severity": "medium",
                "summary": summary,
                "evidence": evidence,
                "resolution": None,
            }
        ]
    if outcome == "findings" and normalized_review.get("scrub_passed") is False:
        hits = _string_list(normalized_review.get("scrub_hits"))
        ledger = _redact_scrub_hits(ledger, hits)
        normalized_review = _redact_scrub_hits(normalized_review, hits)
        normalized_review["text"] = (
            "[redacted: review findings failed the provider scrub; use artifact_file locally]"
        )
        normalized_review["scrub_hit_count"] = len(hits)
        normalized_review["scrub_hits"] = []
        normalized_review["consumer_safe"] = True
    normalized_review["outcome"] = outcome
    normalized_review["findings_ledger"] = ledger
    return outcome, ledger, normalized_review


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def load_review_receipt(path: str | Path) -> dict[str, Any]:
    """Load and structurally verify one terminal coordination receipt."""

    ref = Path(path).expanduser().resolve()
    if not ref.is_file():
        raise ReviewCoordinationError(f"review coordination receipt not found: {ref}")
    try:
        payload = json.loads(ref.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ReviewCoordinationError(
            f"review coordination receipt must be valid JSON: {ref}"
        ) from exc
    if not isinstance(payload, dict) or payload.get("schema") != REVIEW_RECEIPT_SCHEMA:
        raise ReviewCoordinationError(
            f"review coordination receipt must use {REVIEW_RECEIPT_SCHEMA}"
        )
    subject_raw = payload.get("subject")
    if not isinstance(subject_raw, Mapping):
        raise ReviewCoordinationError("review coordination receipt requires subject")
    raw_review = payload.get("review")
    legacy_scrub_failure = (
        payload.get("outcome") == "clean"
        and isinstance(raw_review, Mapping)
        and raw_review.get("scrub_passed") is False
    )
    subject = ReviewSubject.from_mapping(subject_raw)
    expected_key = stable_review_key(subject)
    legacy_key = _legacy_subject_hash(subject_raw)
    recovery = payload.get("recovery")
    advisory_key = ""
    if payload.get("mode") == "advisory_recovery":
        if not isinstance(recovery, Mapping):
            raise ReviewCoordinationError("advisory recovery receipt requires recovery evidence")
        structured_findings = raw_review.get("structured_findings") if isinstance(raw_review, Mapping) else None
        findings_sha256 = str(recovery.get("findings_sha256") or "")
        if not isinstance(structured_findings, list) or not re.fullmatch(
            r"[0-9a-f]{64}", findings_sha256
        ):
            raise ReviewCoordinationError(
                "advisory recovery receipt requires immutable structured findings evidence"
            )
        if _canonical_hash(structured_findings) != findings_sha256:
            raise ReviewCoordinationError(
                "advisory recovery structured findings digest does not match receipt"
            )
        immutable_findings = _immutable_structured_findings(
            str(raw_review.get("response") or "")
        )
        if immutable_findings != structured_findings or any(
            row["blocking"] is not False for row in immutable_findings
        ):
            raise ReviewCoordinationError(
                "advisory recovery receipt does not prove immutable all-advisory findings"
            )
        advisory_key = advisory_recovery_key(
            str(payload.get("parent_key") or ""),
            str(recovery.get("evidence_sha256") or ""),
            findings_sha256,
        )
    if payload.get("key") not in {expected_key, legacy_key, advisory_key}:
        raise ReviewCoordinationError("review coordination receipt key does not match subject")
    expected_chain = review_chain_key(subject)
    expected_family = review_family_key(subject)
    legacy_unavailable = (
        payload.get("outcome") == "unavailable" or legacy_scrub_failure
    )
    if payload.get("chain_key") != expected_chain:
        legacy_chains = {
            _legacy_review_chain_key(subject),
            _legacy_subject_hash(subject_raw, drop=("head_sha",)),
            _legacy_subject_hash(subject_raw, drop=("head_sha", "purpose")),
        }
        if payload.get("chain_key") in legacy_chains:
            payload["chain_key"] = expected_chain
        else:
            raise ReviewCoordinationError(
                "review coordination receipt chain_key does not match subject"
            )
    if payload.get("family_key") != expected_family:
        if payload.get("family_key") == _legacy_review_family_key(subject):
            payload["family_key"] = expected_family
        else:
            raise ReviewCoordinationError(
                "review coordination receipt family_key does not match subject"
            )
    if payload.get("status") != "completed" or payload.get("outcome") not in TERMINAL_REVIEW_OUTCOMES:
        raise ReviewCoordinationError("review coordination receipt is not terminal")
    review_payload = payload.get("review")
    if not isinstance(review_payload, Mapping):
        raise ReviewCoordinationError("review coordination receipt requires review evidence")
    if legacy_scrub_failure:
        existing_post = payload.get("provider_post")
        if isinstance(existing_post, Mapping) and existing_post.get("status") == "posted":
            raise ReviewCoordinationError(
                "scrub-failed legacy receipt claims an already-posted provider result"
            )
        # Receipts produced before scrub failures became retryable may claim
        # clean at the top level.  Downgrade only the in-memory authority; the
        # original bytes are archived by execute before the same key retries.
        payload["outcome"] = "unavailable"
        payload["review"] = {
            **dict(review_payload),
            "outcome": "unavailable",
            "coordination_warning": (
                "legacy clean receipt failed scrub and was downgraded for retry"
            ),
        }
    mode = payload.get("mode")
    if mode not in {"full", "delta", "operator_resolution", "advisory_recovery"}:
        raise ReviewCoordinationError("review coordination receipt mode is invalid")
    if mode in {"delta", "operator_resolution", "advisory_recovery"} and not re.fullmatch(
        r"[0-9a-f]{64}", str(payload.get("parent_key") or "")
    ):
        raise ReviewCoordinationError(
            f"{mode} review coordination receipt requires parent_key"
        )
    if mode == "operator_resolution" and not (
        payload.get("operator_override") is True
        and isinstance(payload.get("operator_evidence"), Mapping)
    ):
        raise ReviewCoordinationError(
            "operator_resolution receipt requires operator override evidence"
        )
    ledger = payload.get("findings_ledger")
    # v1 unavailable receipts written before CC-422's repair did not contain a
    # ledger.  They are accepted only so the successful artifact can be safely
    # recovered; they are never eligible for reuse, budget, or delta ancestry.
    if ledger is None and payload.get("outcome") == "unavailable":
        payload["findings_ledger"] = []
        ledger = []
    if not isinstance(ledger, list):
        raise ReviewCoordinationError("review coordination receipt requires findings_ledger")
    seen: set[str] = set()
    for row in ledger:
        if not isinstance(row, Mapping):
            raise ReviewCoordinationError("findings_ledger entries must be objects")
        finding_id = str(row.get("id") or "")
        if not finding_id or finding_id in seen:
            raise ReviewCoordinationError("findings_ledger IDs must be unique and non-empty")
        seen.add(finding_id)
        if row.get("status") not in FINDING_STATUSES:
            raise ReviewCoordinationError("findings_ledger status is invalid")
        if row.get("severity") not in FINDING_SEVERITIES:
            raise ReviewCoordinationError("findings_ledger severity is invalid")
        if not isinstance(row.get("evidence"), list):
            raise ReviewCoordinationError("findings_ledger evidence must be a list")
        if row.get("status") == "resolved":
            resolution = row.get("resolution")
            if not (
                isinstance(resolution, Mapping)
                and isinstance(resolution.get("refs"), list)
                and resolution.get("refs")
            ):
                raise ReviewCoordinationError(
                    "resolved findings require explicit resolution refs"
                )
    if payload.get("outcome") == "clean" and any(
        row.get("status") == "open" for row in ledger
    ):
        raise ReviewCoordinationError("clean receipt cannot contain unresolved findings")
    post = payload.get("provider_post")
    if (
        legacy_unavailable
        and isinstance(post, Mapping)
        and post.get("status") == "pending"
    ):
        payload["provider_post"] = {
            "status": "not_requested",
            "marker": provider_review_marker(str(payload["key"])),
        }
        post = payload["provider_post"]
    if not isinstance(post, Mapping) or post.get("status") not in {
        "not_requested", "failed", "posted"
    }:
        raise ReviewCoordinationError("review coordination provider_post is invalid")
    if post.get("status") == "posted" and not (
        isinstance(post.get("result"), Mapping)
        and post["result"].get("readback_verified") is True
    ):
        raise ReviewCoordinationError(
            "posted review coordination receipt requires verified provider readback"
        )
    return payload


def assert_exact_head_review_receipt(
    path: str | Path,
    *,
    head_sha: str,
    repository: str | None = None,
    pull_request: str | None = None,
    policy_fingerprint: str | None = None,
    require_clean: bool = True,
) -> dict[str, Any]:
    """Validate that a ready/finalize gate reuses the exact terminal review."""

    payload = load_review_receipt(path)
    subject = payload["subject"]
    checks = {
        "head_sha": head_sha,
        **({"pull_request": str(pull_request)} if pull_request else {}),
        **({"policy_fingerprint": policy_fingerprint} if policy_fingerprint else {}),
    }
    drift = [name for name, value in checks.items() if str(subject.get(name)) != str(value)]
    if repository:
        def canonical_repository(value: Any) -> str:
            normalized = str(value).strip().lower().removesuffix(".git")
            for prefix in ("git:github.com/", "github:", "https://github.com/"):
                if normalized.startswith(prefix):
                    return normalized.removeprefix(prefix)
            return normalized

        if canonical_repository(subject.get("repository")) != canonical_repository(repository):
            drift.append("repository")
    if drift:
        raise ReviewCoordinationError(
            "review coordination receipt drifted for " + ", ".join(sorted(drift))
        )
    if require_clean and payload.get("outcome") != "clean":
        raise ReviewCoordinationError("ready_for_merge requires a clean exact-head review")
    return payload


class ReviewCoordinator:
    """Coordinate review calls and persist reviewer-independent receipts."""

    def __init__(self, receipt_root: str | Path, *, budget: ReviewBudget | None = None) -> None:
        self.root = Path(receipt_root).expanduser().resolve()
        self.receipts = self.root / "receipts"
        self.index = self.root / "index"
        self.attempts = self.root / "attempts"
        self.quarantine = self.root / "quarantine"
        self.locks = self.root / ".locks"
        self.budget = budget or ReviewBudget()
        self._quarantine_cache: list[dict[str, Any]] | None = None
        self._quarantine_cache_token: int | None = None

    def _path(self, key: str) -> Path:
        return self.receipts / f"{key}.json"

    def _write_receipt(self, path: Path, receipt: Mapping[str, Any]) -> None:
        index_payload = {
            "schema": "auto-dev-review-index/v1",
            "key": receipt.get("key"),
            "family_key": receipt.get("family_key"),
            "chain_key": receipt.get("chain_key"),
            "mode": receipt.get("mode"),
            "outcome": receipt.get("outcome"),
            "budget_consumed": (
                receipt.get("outcome") in SUCCESSFUL_REVIEW_OUTCOMES
                and receipt.get("mode") in {"full", "delta"}
            ),
            "subject": receipt.get("subject"),
            "receipt_ref": str(path),
        }
        # The identity sidecar lands first. A crash between these writes is
        # conservative (reserved budget without a receipt), never a free retry.
        _atomic_json(self.index / f"{receipt.get('key')}.json", index_payload)
        _atomic_json(path, receipt)

    def _quarantine_entries(self) -> list[dict[str, Any]]:
        token = self.quarantine.stat().st_mtime_ns if self.quarantine.is_dir() else 0
        if (
            self._quarantine_cache is not None
            and self._quarantine_cache_token == token
        ):
            return list(self._quarantine_cache)
        entries: list[dict[str, Any]] = []
        for metadata_path in sorted(self.quarantine.glob("*.meta.json")):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                raise ReviewCoordinationError(
                    f"quarantine metadata is unreadable: {metadata_path}"
                ) from exc
            if not isinstance(metadata, Mapping):
                raise ReviewCoordinationError(
                    f"quarantine metadata is invalid: {metadata_path}"
                )
            entries.append(dict(metadata))
        self._quarantine_cache = entries
        self._quarantine_cache_token = token
        return list(entries)

    def _raise_if_quarantined(
        self, *, family_key: str, exact_key: str | None = None
    ) -> None:
        for metadata in self._quarantine_entries():
            blocked_key = str(metadata.get("key") or "")
            blocked_family = str(metadata.get("family_key") or "")
            unidentified = not blocked_family
            if (exact_key and blocked_key == exact_key) or unidentified:
                raise ReviewCoordinationError(
                    "review budget failed closed for quarantined "
                    f"key={blocked_key or 'unknown'} family={blocked_family or 'unknown'}; "
                    f"evidence={metadata.get('quarantine_ref')}"
                )

    def _quarantine_receipt(
        self, path: Path, error: ReviewCoordinationError
    ) -> dict[str, Any]:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        quarantine_path = self.quarantine / f"{path.stem}-{digest}.json"
        key = path.stem if re.fullmatch(r"[0-9a-f]{64}", path.stem) else ""
        family_key = ""
        try:
            candidate = json.loads(raw)
        except json.JSONDecodeError:
            candidate = None
        index_path = self.index / f"{path.stem}.json"
        index_candidate: Mapping[str, Any] | None = None
        if index_path.is_file():
            try:
                parsed_index = json.loads(index_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                parsed_index = None
            if isinstance(parsed_index, Mapping):
                index_candidate = parsed_index
        identity_source = candidate if isinstance(candidate, Mapping) else index_candidate
        normalized_subject: ReviewSubject | None = None
        if isinstance(identity_source, Mapping):
            candidate_key = str(identity_source.get("key") or "")
            if not key and re.fullmatch(r"[0-9a-f]{64}", candidate_key):
                key = candidate_key
            candidate_family = str(identity_source.get("family_key") or "")
            if re.fullmatch(r"[0-9a-f]{64}", candidate_family):
                family_key = candidate_family
            subject_raw = identity_source.get("subject")
            if isinstance(subject_raw, Mapping):
                try:
                    normalized_subject = ReviewSubject.from_mapping(subject_raw)
                    family_key = review_family_key(normalized_subject)
                except ReviewCoordinationError:
                    pass
        metadata_path = self.quarantine / f"{path.stem}-{digest}.meta.json"
        budget_consumed = False
        chain_key = ""
        mode = ""
        outcome = ""
        subject: dict[str, Any] | None = None
        if isinstance(identity_source, Mapping):
            chain_candidate = str(identity_source.get("chain_key") or "")
            if re.fullmatch(r"[0-9a-f]{64}", chain_candidate):
                chain_key = chain_candidate
            mode_candidate = str(identity_source.get("mode") or "")
            if mode_candidate in {"full", "delta", "operator_resolution"}:
                mode = mode_candidate
            outcome_candidate = str(identity_source.get("outcome") or "")
            if outcome_candidate in TERMINAL_REVIEW_OUTCOMES:
                outcome = outcome_candidate
                budget_consumed = outcome_candidate in SUCCESSFUL_REVIEW_OUTCOMES
            if isinstance(identity_source.get("subject"), Mapping):
                subject = dict(identity_source["subject"])
        if normalized_subject is not None:
            chain_key = review_chain_key(normalized_subject)
            subject = asdict(normalized_subject)
        metadata = {
            "schema": "auto-dev-review-quarantine/v1",
            "key": key,
            "family_key": family_key,
            "source_ref": str(path),
            "quarantine_ref": str(quarantine_path),
            "sha256": digest,
            "chain_key": chain_key,
            "mode": mode,
            "outcome": outcome,
            "budget_consumed": budget_consumed,
            "subject": subject,
            "error": str(error),
            "quarantined_at": _utc_now(),
        }
        if not metadata_path.is_file():
            _atomic_json(metadata_path, metadata)
        self._quarantine_cache = None
        self._quarantine_cache_token = None
        quarantine_path.parent.mkdir(parents=True, exist_ok=True)
        if quarantine_path.is_file():
            if quarantine_path.read_bytes() != raw:
                raise ReviewCoordinationError(
                    f"quarantine collision for corrupt receipt: {quarantine_path}"
                )
            path.unlink(missing_ok=True)
        else:
            path.replace(quarantine_path)
        return {**metadata, "ref": str(quarantine_path)}

    def _family_receipts(self, family_key: str) -> list[dict[str, Any]]:
        self._raise_if_quarantined(family_key=family_key)
        rows: list[dict[str, Any]] = []
        for metadata in self._quarantine_entries():
            if (
                metadata.get("family_key") == family_key
                and metadata.get("budget_consumed") is True
                and metadata.get("mode") in {"full", "delta"}
                and metadata.get("outcome") in SUCCESSFUL_REVIEW_OUTCOMES
                and re.fullmatch(r"[0-9a-f]{64}", str(metadata.get("chain_key") or ""))
            ):
                rows.append(
                    {
                        "key": metadata.get("key"),
                        "family_key": family_key,
                        "chain_key": metadata.get("chain_key"),
                        "mode": metadata.get("mode"),
                        "outcome": metadata.get("outcome"),
                        "subject": metadata.get("subject"),
                        "provider_post": {"status": "not_requested"},
                        "quarantined": True,
                    }
                )
        for path in sorted(self.receipts.glob("*.json")):
            try:
                payload = load_review_receipt(path)
            except ReviewCoordinationError as exc:
                quarantined = self._quarantine_receipt(path, exc)
                if not quarantined["family_key"]:
                    raise ReviewCoordinationError(
                        "unidentified corrupt review receipt was quarantined; "
                        "all review budgets fail closed until operator recovery: "
                        f"{quarantined['ref']}"
                    ) from exc
                if quarantined["family_key"] == family_key:
                    if (
                        quarantined.get("budget_consumed") is True
                        and quarantined.get("mode") in {"full", "delta"}
                        and quarantined.get("outcome") in SUCCESSFUL_REVIEW_OUTCOMES
                        and re.fullmatch(
                            r"[0-9a-f]{64}",
                            str(quarantined.get("chain_key") or ""),
                        )
                    ):
                        rows.append(
                            {
                                "key": quarantined.get("key"),
                                "family_key": family_key,
                                "chain_key": quarantined.get("chain_key"),
                                "mode": quarantined.get("mode"),
                                "outcome": quarantined.get("outcome"),
                                "subject": quarantined.get("subject"),
                                "provider_post": {"status": "not_requested"},
                                "quarantined": True,
                            }
                        )
                        continue
                    raise ReviewCoordinationError(
                        "same-family quarantine lacks enough terminal budget identity; "
                        f"budget accounting failed closed at {quarantined['ref']}"
                    ) from exc
                # An unrelated or unidentifiable receipt cannot contribute to
                # this family's counters. It is evicted from the active store;
                # its exact key (and known family, if recoverable) stays blocked
                # by quarantine metadata.
                continue
            if payload.get("family_key") == family_key:
                rows.append(payload)
        return rows

    def _archive_attempt(self, path: Path) -> Path:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        attempt = self.attempts / f"{path.stem}-{digest}.json"
        if not attempt.is_file():
            _atomic_bytes(attempt, raw)
        return attempt

    def classify_quarantine_tombstone(
        self,
        key: str,
        *,
        family_key: str,
        chain_key: str,
        mode: str,
        outcome: str,
        approval_ref: str,
    ) -> Path:
        """Classify an unknown tombstone without erasing its budget history."""

        for label, value in (
            ("key", key),
            ("family_key", family_key),
            ("chain_key", chain_key),
        ):
            if not re.fullmatch(r"[0-9a-f]{64}", str(value)):
                raise ReviewCoordinationError(
                    f"quarantine classification requires canonical {label}"
                )
        if mode not in {"full", "delta"} or outcome not in SUCCESSFUL_REVIEW_OUTCOMES:
            raise ReviewCoordinationError(
                "quarantine classification requires a budget-consuming full/delta outcome"
            )
        if not str(approval_ref).strip():
            raise ReviewCoordinationError(
                "quarantine classification requires approval_ref"
            )
        matches = [
            path
            for path in sorted(self.quarantine.glob("*.meta.json"))
            if path.name.startswith(f"{key}-")
        ]
        if len(matches) != 1:
            raise ReviewCoordinationError(
                "quarantine classification requires exactly one matching tombstone"
            )
        metadata_path = matches[0]
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            raise ReviewCoordinationError("quarantine tombstone metadata is invalid")
        metadata.update(
            {
                "family_key": family_key,
                "chain_key": chain_key,
                "mode": mode,
                "outcome": outcome,
                "budget_consumed": True,
                "classification_approval_ref": str(approval_ref),
                "classified_at": _utc_now(),
            }
        )
        _atomic_json(metadata_path, metadata)
        self._quarantine_cache = None
        self._quarantine_cache_token = None
        return metadata_path

    def _result(self, path: Path, receipt: dict[str, Any], *, reused: bool) -> ReviewRunResult:
        return ReviewRunResult(
            key=str(receipt["key"]), receipt_path=path, receipt=receipt, reused=reused
        )

    def _post_terminal(
        self,
        path: Path,
        receipt: dict[str, Any],
        provider_post: Callable[[str, Mapping[str, Any]], Mapping[str, Any] | None],
    ) -> dict[str, Any]:
        post = receipt.get("provider_post")
        if isinstance(post, Mapping) and post.get("status") == "posted":
            return receipt
        marker = provider_review_marker(str(receipt["key"]))
        try:
            result = provider_post(marker, receipt)
        except Exception as exc:
            updated = dict(receipt)
            updated["provider_post"] = {
                "status": "failed",
                "marker": marker,
                "error": f"{type(exc).__name__}: {exc}",
                "failed_at": _utc_now(),
            }
            _atomic_json(path, updated)
            raise ReviewCoordinationError(
                "provider post failed; the verified-post budget was not consumed"
            ) from exc
        if not isinstance(result, Mapping) or result.get("readback_verified") is not True:
            updated = dict(receipt)
            updated["provider_post"] = {
                "status": "failed",
                "marker": marker,
                "error": "provider post lacked readback_verified=true",
                "failed_at": _utc_now(),
                "result": dict(result) if isinstance(result, Mapping) else {},
            }
            _atomic_json(path, updated)
            raise ReviewCoordinationError(
                "provider post requires verified readback; budget was not consumed"
            )
        updated = dict(receipt)
        updated["provider_post"] = {
            "status": "posted",
            "marker": marker,
            "result": dict(result),
            "posted_at": _utc_now(),
        }
        budget = dict(updated.get("budget") or {})
        budget["provider_posts_used"] = int(budget.get("provider_posts_used") or 0) + 1
        updated["budget"] = budget
        _atomic_json(path, updated)
        return updated

    def execute(
        self,
        subject: ReviewSubject,
        review_call: Callable[[], Mapping[str, Any]],
        *,
        mode: str = "full",
        parent_key: str | None = None,
    ) -> ReviewRunResult:
        """Run or reuse one review while holding the PR-family single-flight lock."""

        if mode not in {"full", "delta"}:
            raise ReviewCoordinationError("review mode must be full or delta")
        key = stable_review_key(subject)
        chain_key = review_chain_key(subject)
        family_key = review_family_key(subject)
        path = self._path(key)
        lock_path = self.locks / f"{family_key}.lock"
        with _exclusive_lock(lock_path):
            self._raise_if_quarantined(family_key=family_key, exact_key=key)
            if path.is_file():
                try:
                    existing = load_review_receipt(path)
                except ReviewCoordinationError as exc:
                    quarantined = self._quarantine_receipt(path, exc)
                    raise ReviewCoordinationError(
                        "exact-key review receipt was quarantined; retry is blocked "
                        f"until recovery: {quarantined['ref']}"
                    ) from exc
                if existing.get("outcome") in SUCCESSFUL_REVIEW_OUTCOMES:
                    return self._result(path, existing, reused=True)
                # Unavailable is an attempt, not a terminal authority.  Preserve
                # it immutably and allow the exact same subject to retry.
                self._archive_attempt(path)
                path.unlink()

            family = self._family_receipts(family_key)
            for row in family:
                if row.get("quarantined") or not isinstance(row.get("subject"), Mapping):
                    continue
                try:
                    prior_subject = ReviewSubject.from_mapping(row["subject"])
                except ReviewCoordinationError:
                    continue
                if prior_subject == subject and row.get("outcome") in SUCCESSFUL_REVIEW_OUTCOMES:
                    legacy_path = self._path(str(row["key"]))
                    return self._result(legacy_path, row, reused=True)
            successful_family = [
                row for row in family if row.get("outcome") in SUCCESSFUL_REVIEW_OUTCOMES
            ]
            chain = [
                row for row in successful_family if row.get("chain_key") == chain_key
            ]
            full_count = sum(row.get("mode") == "full" for row in chain)
            delta_count = sum(row.get("mode") == "delta" for row in chain)
            absolute_full_count = sum(
                row.get("mode") == "full" for row in successful_family
            )
            provider_post_count = sum(
                isinstance(row.get("provider_post"), Mapping)
                and row["provider_post"].get("status") == "posted"
                for row in successful_family
            )

            if mode == "full" and full_count >= self.budget.full_reviews_per_chain:
                raise ReviewBudgetExceeded(
                    "full-review budget exhausted for this base/policy chain; use a delta review"
                )
            if (
                mode == "full"
                and absolute_full_count >= self.budget.absolute_full_reviews_per_family
            ):
                raise ReviewBudgetExceeded("absolute full-review budget exhausted for this PR")
            if mode == "delta" and delta_count >= self.budget.delta_reviews_per_chain:
                raise ReviewBudgetExceeded("delta-review budget exhausted for this review chain")
            parent: dict[str, Any] | None = None
            if mode == "delta":
                candidates = [row for row in chain if not row.get("quarantined")]
                if parent_key:
                    candidates = [
                        row for row in candidates if row.get("key") == parent_key
                    ]
                if not candidates:
                    if any(row.get("quarantined") for row in chain):
                        raise ReviewCoordinationError(
                            "delta review parent is quarantined; explicit recovery is required"
                        )
                    raise ReviewCoordinationError(
                        "delta review requires a successful parent in the same base/policy chain"
                    )
                parent = sorted(candidates, key=lambda row: str(row.get("completed_at") or ""))[-1]
                if parent.get("outcome") == "unavailable":
                    raise ReviewCoordinationError(
                        "unavailable review attempts cannot be delta parents"
                    )
                if parent["subject"]["head_sha"] == subject.head_sha:
                    raise ReviewCoordinationError("delta review requires a changed head revision")
                parent_key = str(parent["key"])

            # All budget and chain checks above happen before the paid/provider call.
            result = review_call()
            if not isinstance(result, Mapping):
                raise ReviewCoordinationError("review_call must return a mapping")
            outcome, ledger, normalized_review = normalize_findings_ledger(
                result,
                parent_ledger=(parent.get("findings_ledger") if parent else None),
            )
            now = _utc_now()
            budget_consumed = outcome in SUCCESSFUL_REVIEW_OUTCOMES
            receipt: dict[str, Any] = {
                "schema": REVIEW_RECEIPT_SCHEMA,
                "key": key,
                "chain_key": chain_key,
                "family_key": family_key,
                "status": "completed",
                "mode": mode,
                "outcome": outcome,
                "subject": asdict(subject),
                "parent_key": parent_key,
                "review": normalized_review,
                "findings_ledger": ledger,
                "budget": {
                    "full_reviews_per_chain": self.budget.full_reviews_per_chain,
                    "delta_reviews_per_chain": self.budget.delta_reviews_per_chain,
                    "absolute_full_reviews_per_family": self.budget.absolute_full_reviews_per_family,
                    "provider_posts_per_family": self.budget.provider_posts_per_family,
                    "full_reviews_used": full_count
                    + (1 if budget_consumed and mode == "full" else 0),
                    "delta_reviews_used": delta_count
                    + (1 if budget_consumed and mode == "delta" else 0),
                    "absolute_full_reviews_used": absolute_full_count
                    + (1 if budget_consumed and mode == "full" else 0),
                    "provider_posts_used": provider_post_count,
                },
                "provider_post": {
                    "status": "not_requested",
                    "marker": provider_review_marker(key),
                },
                "created_at": now,
                "completed_at": now,
            }
            if outcome == "unavailable":
                attempt_path = self.attempts / f"{key}-{uuid.uuid4().hex}.json"
                _atomic_json(attempt_path, receipt)
                return self._result(attempt_path, receipt, reused=False)
            self._write_receipt(path, receipt)
            return self._result(path, receipt, reused=False)

    def post_terminal(
        self,
        subject: ReviewSubject,
        provider_post: Callable[[str, Mapping[str, Any]], Mapping[str, Any] | None],
        *,
        scrub_passed: bool,
    ) -> ReviewRunResult:
        """Post one clean, scrubbed terminal summary with verified readback."""

        key = stable_review_key(subject)
        path = self._path(key)
        family_key = review_family_key(subject)
        with _exclusive_lock(self.locks / f"{family_key}.lock"):
            self._raise_if_quarantined(family_key=family_key, exact_key=key)
            if not path.is_file():
                raise ReviewCoordinationError(
                    "provider post requires an exact-head successful review receipt"
                )
            receipt = load_review_receipt(path)
            post = receipt.get("provider_post")
            if isinstance(post, Mapping) and post.get("status") == "posted":
                return self._result(path, receipt, reused=True)
            if receipt.get("outcome") != "clean" or scrub_passed is not True:
                raise ReviewCoordinationError(
                    "provider post requires a clean review and scrub_passed=true"
                )
            if receipt.get("operator_override") is True:
                raise ReviewCoordinationError(
                    "operator resolution receipts cannot be posted as reviewer approval"
                )
            family = self._family_receipts(family_key)
            posted_count = sum(
                isinstance(row.get("provider_post"), Mapping)
                and row["provider_post"].get("status") == "posted"
                for row in family
            )
            if posted_count >= self.budget.provider_posts_per_family:
                raise ReviewBudgetExceeded("provider-post budget exhausted for this PR")
            posted = self._post_terminal(path, receipt, provider_post)
            return self._result(path, posted, reused=False)

    def resolve_capped_findings(
        self,
        subject: ReviewSubject,
        *,
        parent_key: str,
        approval_ref: str,
        test_evidence: Mapping[str, Any],
        ci_evidence: Mapping[str, Any],
        resolutions: Mapping[str, Any],
    ) -> ReviewRunResult:
        """Resolve a capped findings chain from explicit operator evidence only."""

        if not re.fullmatch(r"[0-9a-f]{64}", str(parent_key)):
            raise ReviewCoordinationError(
                "operator resolution requires a canonical parent_key"
            )
        if not str(approval_ref).strip():
            raise ReviewCoordinationError(
                "operator resolution requires an explicit approval_ref"
            )

        def exact_head_evidence(
            label: str, evidence: Mapping[str, Any]
        ) -> dict[str, Any]:
            if not isinstance(evidence, Mapping):
                raise ReviewCoordinationError(
                    f"operator resolution requires typed {label} evidence"
                )
            refs = _string_list(evidence.get("refs"))
            if (
                str(evidence.get("head_sha") or "").strip().lower()
                != subject.head_sha
                or evidence.get("verified") is not True
                or not refs
            ):
                raise ReviewCoordinationError(
                    f"operator resolution {label} evidence must be verified, "
                    "exact-head, and contain refs"
                )
            return {"head_sha": subject.head_sha, "verified": True, "refs": refs}

        tests = exact_head_evidence("test", test_evidence)
        ci = exact_head_evidence("CI", ci_evidence)
        key = stable_review_key(subject)
        chain_key = review_chain_key(subject)
        family_key = review_family_key(subject)
        path = self._path(key)
        with _exclusive_lock(self.locks / f"{family_key}.lock"):
            self._raise_if_quarantined(family_key=family_key, exact_key=key)
            if path.is_file():
                existing = load_review_receipt(path)
                if existing.get("operator_override") is True:
                    return self._result(path, existing, reused=True)
                raise ReviewCoordinationError(
                    "operator resolution exact head already has review authority"
                )
            family = self._family_receipts(family_key)
            chain = [row for row in family if row.get("chain_key") == chain_key]
            full_count = sum(row.get("mode") == "full" for row in chain)
            delta_count = sum(row.get("mode") == "delta" for row in chain)
            absolute_full_count = sum(row.get("mode") == "full" for row in family)
            if (
                full_count < self.budget.full_reviews_per_chain
                or delta_count < self.budget.delta_reviews_per_chain
            ):
                raise ReviewCoordinationError(
                    "operator resolution requires a capped findings chain "
                    f"({self.budget.full_reviews_per_chain} full and "
                    f"{self.budget.delta_reviews_per_chain} delta reviews)"
                )
            parent_candidates = [
                row
                for row in chain
                if row.get("key") == parent_key and not row.get("quarantined")
            ]
            if not parent_candidates:
                raise ReviewCoordinationError(
                    "operator resolution requires an active capped-chain parent"
                )
            parent = parent_candidates[-1]
            if parent.get("outcome") != "findings":
                raise ReviewCoordinationError(
                    "operator resolution parent must contain canonical findings"
                )
            active_chain = [
                row
                for row in chain
                if not row.get("quarantined")
                and row.get("mode") in {"full", "delta"}
            ]
            latest = sorted(
                active_chain, key=lambda row: str(row.get("completed_at") or "")
            )[-1]
            if latest.get("key") != parent_key or parent.get("mode") != "delta":
                raise ReviewCoordinationError(
                    "operator resolution requires the latest capped delta parent"
                )
            parent_subject = ReviewSubject.from_mapping(parent["subject"])
            if parent_subject.head_sha == subject.head_sha:
                raise ReviewCoordinationError(
                    "operator resolution requires an exact new head"
                )
            ledger = parent.get("findings_ledger")
            if not isinstance(ledger, list):
                raise ReviewCoordinationError(
                    "operator resolution parent lacks a findings ledger"
                )
            open_ids = {
                str(row.get("id"))
                for row in ledger
                if isinstance(row, Mapping) and row.get("status") == "open"
            }
            if not open_ids or set(map(str, resolutions)) != open_ids:
                raise ReviewCoordinationError(
                    "operator resolution must resolve every and only open finding ID"
                )
            resolved_ledger: list[dict[str, Any]] = []
            normalized_resolutions: dict[str, dict[str, Any]] = {}
            for row in ledger:
                current = dict(row)
                finding_id = str(current.get("id"))
                if finding_id not in open_ids:
                    resolved_ledger.append(current)
                    continue
                value = resolutions[finding_id]
                if isinstance(value, Mapping):
                    refs = _string_list(value.get("refs"))
                    summary = str(value.get("summary") or "").strip()
                else:
                    refs = _string_list(value)
                    summary = ""
                if not refs:
                    raise ReviewCoordinationError(
                        f"operator resolution for {finding_id} requires refs"
                    )
                resolution = {"refs": refs, "summary": summary}
                current["status"] = "resolved"
                current["resolution"] = resolution
                resolved_ledger.append(current)
                normalized_resolutions[finding_id] = resolution
            now = _utc_now()
            receipt: dict[str, Any] = {
                "schema": REVIEW_RECEIPT_SCHEMA,
                "key": key,
                "chain_key": chain_key,
                "family_key": family_key,
                "status": "completed",
                "mode": "operator_resolution",
                "outcome": "clean",
                "subject": asdict(subject),
                "parent_key": parent_key,
                "review": {
                    "outcome": "clean",
                    "summary": "Capped findings resolved by explicit operator evidence.",
                    "scrub_passed": True,
                },
                "findings_ledger": resolved_ledger,
                "budget": {
                    "full_reviews_per_chain": self.budget.full_reviews_per_chain,
                    "delta_reviews_per_chain": self.budget.delta_reviews_per_chain,
                    "absolute_full_reviews_per_family": self.budget.absolute_full_reviews_per_family,
                    "provider_posts_per_family": self.budget.provider_posts_per_family,
                    "full_reviews_used": full_count,
                    "delta_reviews_used": delta_count,
                    "absolute_full_reviews_used": absolute_full_count,
                    "provider_posts_used": sum(
                        isinstance(row.get("provider_post"), Mapping)
                        and row["provider_post"].get("status") == "posted"
                        for row in family
                    ),
                },
                "provider_post": {
                    "status": "not_requested",
                    "marker": provider_review_marker(key),
                },
                "operator_override": True,
                "operator_evidence": {
                    "approval_ref": str(approval_ref),
                    "tests": tests,
                    "ci": ci,
                    "resolutions": normalized_resolutions,
                },
                "created_at": now,
                "completed_at": now,
            }
            self._write_receipt(path, receipt)
            return self._result(path, receipt, reused=False)

    def recover_successful_unavailable(
        self,
        receipt_path: str | Path,
        recovered_review: Mapping[str, Any],
        *,
        evidence_ref: str,
    ) -> ReviewRunResult:
        """Recover a successful reviewer artifact without purchasing another call.

        This is deliberately narrow: the original attempt must be unavailable,
        its reviewer process must have exited successfully, and the caller must
        provide explicit recovered findings plus a durable evidence reference.
        The original bytes are archived before canonical authority is written.
        """

        source = Path(receipt_path).expanduser().resolve()
        if not source.is_file():
            raise ReviewCoordinationError(f"recovery receipt not found: {source}")
        original_raw = source.read_bytes()
        try:
            original = load_review_receipt(source)
        except ReviewCoordinationError as exc:
            digest = hashlib.sha256(original_raw).hexdigest()
            quarantine_path = self.quarantine / f"{source.stem}-{digest}.json"
            if not quarantine_path.is_file():
                _atomic_bytes(quarantine_path, original_raw)
            raise ReviewCoordinationError(
                f"recovery source failed closed and was quarantined at {quarantine_path}"
            ) from exc
        if original.get("outcome") != "unavailable":
            raise ReviewCoordinationError("recovery source must be an unavailable attempt")
        original_review = original.get("review")
        if not isinstance(original_review, Mapping) or original_review.get("exit_code") != 0:
            raise ReviewCoordinationError(
                "recovery requires reviewer exit_code=0 evidence"
            )
        if not str(evidence_ref).strip():
            raise ReviewCoordinationError("recovery requires a durable evidence_ref")
        recovered = dict(recovered_review)
        recovered["outcome"] = "findings"
        outcome, ledger, normalized_review = normalize_findings_ledger(recovered)
        if outcome != "findings" or not ledger:
            raise ReviewCoordinationError("recovery requires normalized findings")

        subject = ReviewSubject.from_mapping(original["subject"])
        family_key = review_family_key(subject)
        canonical_path = self._path(str(original["key"]))
        with _exclusive_lock(self.locks / f"{family_key}.lock"):
            digest = hashlib.sha256(original_raw).hexdigest()
            archived = self.attempts / f"{source.stem}-{digest}.json"
            if not archived.is_file():
                _atomic_bytes(archived, original_raw)
            family = self._family_receipts(family_key)
            successful_family = [
                row
                for row in family
                if row.get("outcome") in SUCCESSFUL_REVIEW_OUTCOMES
                and row.get("key") != original.get("key")
            ]
            chain = [
                row
                for row in successful_family
                if row.get("chain_key") == original.get("chain_key")
            ]
            mode = str(original.get("mode"))
            full_count = sum(row.get("mode") == "full" for row in chain)
            delta_count = sum(row.get("mode") == "delta" for row in chain)
            absolute_full_count = sum(
                row.get("mode") == "full" for row in successful_family
            )
            if mode == "full" and (
                full_count >= self.budget.full_reviews_per_chain
                or absolute_full_count >= self.budget.absolute_full_reviews_per_family
            ):
                raise ReviewBudgetExceeded(
                    "recovered review would exceed the successful full-review budget"
                )
            if mode == "delta" and delta_count >= self.budget.delta_reviews_per_chain:
                raise ReviewBudgetExceeded(
                    "recovered review would exceed the successful delta-review budget"
                )
            now = _utc_now()
            canonical = {
                **original,
                "outcome": "findings",
                "review": normalized_review,
                "findings_ledger": ledger,
                "budget": {
                    **dict(original.get("budget") or {}),
                    "full_reviews_used": full_count + (1 if mode == "full" else 0),
                    "delta_reviews_used": delta_count + (1 if mode == "delta" else 0),
                    "absolute_full_reviews_used": absolute_full_count
                    + (1 if mode == "full" else 0),
                    "provider_posts_used": sum(
                        isinstance(row.get("provider_post"), Mapping)
                        and row["provider_post"].get("status") == "posted"
                        for row in successful_family
                    ),
                },
                "provider_post": {
                    "status": "not_requested",
                    "marker": provider_review_marker(str(original["key"])),
                },
                "recovery": {
                    "source_attempt_ref": str(archived),
                    "source_attempt_sha256": digest,
                    "evidence_ref": str(evidence_ref),
                    "recovered_at": now,
                },
                "completed_at": now,
            }
            self._write_receipt(canonical_path, canonical)
            return self._result(canonical_path, canonical, reused=True)

    def derive_same_head_advisory_clean(
        self,
        source_receipt_path: str | Path,
        *,
        evidence_path: str | Path,
        findings: list[Mapping[str, Any]],
    ) -> ReviewRunResult:
        """Derive immutable clean authority from one all-advisory model response.

        This is recovery, not a reviewer call or mutation of the original
        receipt.  It exists for older runner receipts that kept the raw model
        response but failed to ingest its typed non-blocking findings before
        determining the coordination outcome.
        """

        source = Path(source_receipt_path).expanduser().resolve()
        evidence = Path(evidence_path).expanduser().resolve()
        if not source.is_file() or not evidence.is_file():
            raise ReviewCoordinationError(
                "advisory recovery requires an existing source receipt and evidence file"
            )
        source_raw = source.read_bytes()
        original = load_review_receipt(source)
        if original.get("outcome") != "findings":
            raise ReviewCoordinationError(
                "advisory recovery source must be a terminal findings receipt"
            )
        if original.get("mode") not in {"full", "delta"}:
            raise ReviewCoordinationError(
                "advisory recovery source must be a full or delta reviewer receipt"
            )
        response = (original.get("review") or {}).get("response")
        if not isinstance(response, str) or not response.strip():
            raise ReviewCoordinationError(
                "advisory recovery requires the original typed reviewer response"
            )
        evidence_text = evidence.read_text(encoding="utf-8").strip()
        if hashlib.sha256(response.strip().encode()).hexdigest() != hashlib.sha256(
            evidence_text.encode()
        ).hexdigest():
            raise ReviewCoordinationError(
                "advisory recovery evidence does not match the source reviewer response"
            )
        immutable_findings = _immutable_structured_findings(response.strip())
        if any(row["blocking"] is not False for row in immutable_findings):
            raise ReviewCoordinationError(
                "advisory recovery requires one or more immutable non-blocking findings"
            )
        supplied_findings = [dict(row) for row in findings if isinstance(row, Mapping)]
        if len(supplied_findings) != len(findings) or _canonical_json(
            supplied_findings
        ) != _canonical_json(immutable_findings):
            raise ReviewCoordinationError(
                "advisory recovery findings must exactly match the immutable reviewer response"
            )

        subject = ReviewSubject.from_mapping(original["subject"])
        parent_key = str(original["key"])
        evidence_sha256 = hashlib.sha256(evidence_text.encode()).hexdigest()
        findings_sha256 = _canonical_hash(immutable_findings)
        key = advisory_recovery_key(parent_key, evidence_sha256, findings_sha256)
        family_key = review_family_key(subject)
        path = self._path(key)
        advisory_rows: list[dict[str, Any]] = []
        for row in immutable_findings:
            finding_id = str(row.get("id") or "").strip()
            if not finding_id:
                raise ReviewCoordinationError("advisory recovery findings require IDs")
            advisory_rows.append(
                {
                    **dict(row),
                    "status": "resolved",
                    "resolution_refs": [f"reviewer-nonblocking-advisory:{finding_id}"],
                    "advisory": True,
                }
            )
        outcome, ledger, normalized_review = normalize_findings_ledger(
            {
                "outcome": "clean",
                "findings": advisory_rows,
                "response": response.strip(),
                "structured_findings": immutable_findings,
                "summary": "Recovered all-nonblocking reviewer advice from immutable model evidence.",
                "scrub_passed": True,
            }
        )
        if outcome != "clean" or any(row.get("status") == "open" for row in ledger):
            raise ReviewCoordinationError(
                "advisory recovery cannot derive clean authority with unresolved findings"
            )
        with _exclusive_lock(self.locks / f"{family_key}.lock"):
            if path.is_file():
                existing = load_review_receipt(path)
                if (
                    existing.get("parent_key") == parent_key
                    and (existing.get("recovery") or {}).get("evidence_sha256")
                    == evidence_sha256
                ):
                    return self._result(path, existing, reused=True)
                raise ReviewCoordinationError("advisory recovery child key collision")
            now = _utc_now()
            receipt = {
                "schema": REVIEW_RECEIPT_SCHEMA,
                "key": key,
                "chain_key": review_chain_key(subject),
                "family_key": family_key,
                "status": "completed",
                "mode": "advisory_recovery",
                "outcome": "clean",
                "subject": asdict(subject),
                "parent_key": parent_key,
                "review": normalized_review,
                "findings_ledger": ledger,
                "budget": dict(original.get("budget") or {}),
                "provider_post": {
                    "status": "not_requested",
                    "marker": provider_review_marker(key),
                },
                "recovery": {
                    "source_receipt_ref": str(source),
                    "source_receipt_sha256": hashlib.sha256(source_raw).hexdigest(),
                    "evidence_ref": str(evidence),
                    "evidence_sha256": evidence_sha256,
                    "findings_sha256": findings_sha256,
                    "derived_at": now,
                },
                "created_at": now,
                "completed_at": now,
            }
            self._write_receipt(path, receipt)
            return self._result(path, receipt, reused=False)

    def finalize(self, subject: ReviewSubject) -> ReviewRunResult:
        """Reuse the exact-head terminal result without invoking a reviewer."""

        key = stable_review_key(subject)
        path = self._path(key)
        family_key = review_family_key(subject)
        with _exclusive_lock(self.locks / f"{family_key}.lock"):
            if not path.is_file():
                raise ReviewCoordinationError(
                    "finalize requires an exact-head terminal review receipt"
                )
            receipt = load_review_receipt(path)
            return self._result(path, receipt, reused=True)
