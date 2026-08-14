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


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def stable_review_key(subject: ReviewSubject) -> str:
    """Return the reviewer-independent key for one exact review subject."""

    return _canonical_hash(asdict(subject))


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


def normalize_findings_ledger(
    review: Mapping[str, Any],
    *,
    parent_ledger: list[Mapping[str, Any]] | None = None,
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    """Normalize reviewer output and preserve unresolved findings across deltas."""

    normalized_review = dict(review)
    outcome = str(normalized_review.get("outcome") or "")
    if normalized_review.get("scrub_passed") is False:
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
    if payload.get("key") != expected_key:
        raise ReviewCoordinationError("review coordination receipt key does not match subject")
    expected_chain = review_chain_key(subject)
    expected_family = review_family_key(subject)
    legacy_unavailable = (
        payload.get("outcome") == "unavailable" or legacy_scrub_failure
    )
    if payload.get("chain_key") != expected_chain:
        if legacy_unavailable and payload.get("chain_key") == _legacy_review_chain_key(subject):
            payload["chain_key"] = expected_chain
        else:
            raise ReviewCoordinationError(
                "review coordination receipt chain_key does not match subject"
            )
    if payload.get("family_key") != expected_family:
        if legacy_unavailable and payload.get("family_key") == _legacy_review_family_key(subject):
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
    if mode not in {"full", "delta"}:
        raise ReviewCoordinationError("review coordination receipt mode is invalid")
    if mode == "delta" and not re.fullmatch(r"[0-9a-f]{64}", str(payload.get("parent_key") or "")):
        raise ReviewCoordinationError("delta review coordination receipt requires parent_key")
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
        **({"repository": repository} if repository else {}),
        **({"pull_request": str(pull_request)} if pull_request else {}),
        **({"policy_fingerprint": policy_fingerprint} if policy_fingerprint else {}),
    }
    drift = [name for name, value in checks.items() if str(subject.get(name)) != str(value)]
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
        self.attempts = self.root / "attempts"
        self.quarantine = self.root / "quarantine"
        self.locks = self.root / ".locks"
        self.budget = budget or ReviewBudget()

    def _path(self, key: str) -> Path:
        return self.receipts / f"{key}.json"

    def _family_receipts(self, family_key: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted(self.receipts.glob("*.json")):
            try:
                payload = load_review_receipt(path)
            except ReviewCoordinationError as exc:
                raw = path.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                quarantine_path = self.quarantine / f"{path.stem}-{digest}.json"
                if not quarantine_path.is_file():
                    _atomic_bytes(quarantine_path, raw)
                raise ReviewCoordinationError(
                    f"corrupt review receipt quarantined at {quarantine_path}; "
                    "budget accounting failed closed"
                ) from exc
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
            if path.is_file():
                existing = load_review_receipt(path)
                if existing.get("outcome") in SUCCESSFUL_REVIEW_OUTCOMES:
                    return self._result(path, existing, reused=True)
                # Unavailable is an attempt, not a terminal authority.  Preserve
                # it immutably and allow the exact same subject to retry.
                self._archive_attempt(path)
                path.unlink()

            family = self._family_receipts(family_key)
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
                candidates = chain
                if parent_key:
                    candidates = [row for row in chain if row.get("key") == parent_key]
                if not candidates:
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
            _atomic_json(path, receipt)
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
            _atomic_json(canonical_path, canonical)
            return self._result(canonical_path, canonical, reused=True)

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
