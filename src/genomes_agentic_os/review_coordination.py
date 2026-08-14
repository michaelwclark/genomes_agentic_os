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
from pathlib import Path
import re
from typing import Any, Callable, Iterator, Mapping
import uuid


REVIEW_RECEIPT_SCHEMA = "auto-dev-review-receipt/v1"
TERMINAL_REVIEW_OUTCOMES = {"clean", "findings", "unavailable"}


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
            if not re.fullmatch(r"[0-9a-fA-F]{7,64}", str(value)):
                raise ReviewCoordinationError(f"review subject {name} must be an exact revision")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", self.policy_fingerprint):
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
    return _canonical_hash(value)


def review_family_key(subject: ReviewSubject) -> str:
    """Return the PR/purpose family used for absolute circuit breakers."""

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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


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
    subject = ReviewSubject.from_mapping(subject_raw)
    expected_key = stable_review_key(subject)
    if payload.get("key") != expected_key:
        raise ReviewCoordinationError("review coordination receipt key does not match subject")
    if payload.get("chain_key") != review_chain_key(subject):
        raise ReviewCoordinationError("review coordination receipt chain_key does not match subject")
    if payload.get("family_key") != review_family_key(subject):
        raise ReviewCoordinationError("review coordination receipt family_key does not match subject")
    if payload.get("status") != "completed" or payload.get("outcome") not in TERMINAL_REVIEW_OUTCOMES:
        raise ReviewCoordinationError("review coordination receipt is not terminal")
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
        self.locks = self.root / ".locks"
        self.budget = budget or ReviewBudget()

    def _path(self, key: str) -> Path:
        return self.receipts / f"{key}.json"

    def _family_receipts(self, family_key: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted(self.receipts.glob("*.json")):
            try:
                payload = load_review_receipt(path)
            except ReviewCoordinationError:
                continue
            if payload.get("family_key") == family_key:
                rows.append(payload)
        return rows

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
        result = provider_post(provider_review_marker(str(receipt["key"])), receipt)
        if result is not None and not isinstance(result, Mapping):
            raise ReviewCoordinationError("provider_post must return a mapping or None")
        updated = dict(receipt)
        updated["provider_post"] = {
            "status": "posted",
            "marker": provider_review_marker(str(receipt["key"])),
            "result": dict(result or {}),
            "posted_at": _utc_now(),
        }
        _atomic_json(path, updated)
        return updated

    def execute(
        self,
        subject: ReviewSubject,
        review_call: Callable[[], Mapping[str, Any]],
        *,
        mode: str = "full",
        parent_key: str | None = None,
        provider_post: Callable[[str, Mapping[str, Any]], Mapping[str, Any] | None]
        | None = None,
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
                if provider_post is not None:
                    family = self._family_receipts(family_key)
                    posts = [
                        row
                        for row in family
                        if isinstance(row.get("provider_post"), Mapping)
                        and row["provider_post"].get("status") in {"pending", "posted"}
                    ]
                    existing_post = existing.get("provider_post")
                    if (
                        not (
                            isinstance(existing_post, Mapping)
                            and existing_post.get("status") in {"pending", "posted"}
                        )
                        and len(posts) >= self.budget.provider_posts_per_family
                    ):
                        raise ReviewBudgetExceeded(
                            "provider-post budget exhausted for this PR"
                        )
                    existing = self._post_terminal(path, existing, provider_post)
                return self._result(path, existing, reused=True)

            family = self._family_receipts(family_key)
            chain = [row for row in family if row.get("chain_key") == chain_key]
            full_count = sum(row.get("mode") == "full" for row in chain)
            delta_count = sum(row.get("mode") == "delta" for row in chain)
            absolute_full_count = sum(row.get("mode") == "full" for row in family)
            provider_post_count = sum(
                isinstance(row.get("provider_post"), Mapping)
                and row["provider_post"].get("status") in {"pending", "posted"}
                for row in family
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
            if provider_post is not None and provider_post_count >= self.budget.provider_posts_per_family:
                raise ReviewBudgetExceeded("provider-post budget exhausted for this PR")

            parent: dict[str, Any] | None = None
            if mode == "delta":
                candidates = chain
                if parent_key:
                    candidates = [row for row in chain if row.get("key") == parent_key]
                if not candidates:
                    raise ReviewCoordinationError(
                        "delta review requires a completed parent in the same base/policy chain"
                    )
                parent = sorted(candidates, key=lambda row: str(row.get("completed_at") or ""))[-1]
                if parent["subject"]["head_sha"] == subject.head_sha:
                    raise ReviewCoordinationError("delta review requires a changed head revision")
                parent_key = str(parent["key"])

            # All budget and chain checks above happen before the paid/provider call.
            result = review_call()
            if not isinstance(result, Mapping):
                raise ReviewCoordinationError("review_call must return a mapping")
            outcome = str(result.get("outcome") or "")
            if outcome not in TERMINAL_REVIEW_OUTCOMES:
                raise ReviewCoordinationError(
                    "review_call must return terminal outcome clean, findings, or unavailable"
                )
            now = _utc_now()
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
                "review": dict(result),
                "budget": {
                    "full_reviews_per_chain": self.budget.full_reviews_per_chain,
                    "delta_reviews_per_chain": self.budget.delta_reviews_per_chain,
                    "absolute_full_reviews_per_family": self.budget.absolute_full_reviews_per_family,
                    "provider_posts_per_family": self.budget.provider_posts_per_family,
                    "full_reviews_used": full_count + (1 if mode == "full" else 0),
                    "delta_reviews_used": delta_count + (1 if mode == "delta" else 0),
                    "absolute_full_reviews_used": absolute_full_count
                    + (1 if mode == "full" else 0),
                    "provider_posts_used": provider_post_count
                    + (1 if provider_post is not None else 0),
                },
                "provider_post": {
                    "status": "pending" if provider_post is not None else "not_requested",
                    "marker": provider_review_marker(key),
                },
                "created_at": now,
                "completed_at": now,
            }
            _atomic_json(path, receipt)
            if provider_post is not None:
                receipt = self._post_terminal(path, receipt, provider_post)
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
