"""Durable, local-only merged-pull-request events for host workflows.

This is deliberately a pull/readback contract, not a webhook server.  A
provider reader supplies a verified merged-PR payload, then this module writes
an idempotent envelope plus a delivery record under the installed OS root.
Consumers claim a short lease and must either acknowledge their durable
proposal receipt or release the event for retry.  None of these operations can
execute a host cleanup.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


API_VERSION = "host-events/v1"
MERGED_PR_EVENT_TYPE = "github.pull_request.merged"
STORE_DIRECTORY = Path("harness/shared_factory/00-control-plane/host-events")
EVENTS_DIRECTORY = STORE_DIRECTORY / "events"
DELIVERIES_DIRECTORY = STORE_DIRECTORY / "deliveries"
DEAD_LETTERS_DIRECTORY = STORE_DIRECTORY / "dead-letter"
PROPOSALS_DIRECTORY = STORE_DIRECTORY / "cleanup-proposals"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_time(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _required_text(value: Any, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{label} is required")
    return normalized


def merged_pr_idempotency_key(repository: str, pr_number: int, merge_sha: str) -> str:
    """Return the stable merge identity shared by every host consumer."""
    try:
        normalized_pr_number = int(pr_number)
    except (TypeError, ValueError) as exc:
        raise ValueError("pr_number must be a positive integer") from exc
    if normalized_pr_number <= 0:
        raise ValueError("pr_number must be a positive integer")
    return f"{_required_text(repository, 'repository')}:{normalized_pr_number}:{_required_text(merge_sha, 'merge_sha')}"


def _event_id(idempotency_key: str) -> str:
    return f"hostevt_{hashlib.sha256(idempotency_key.encode('utf-8')).hexdigest()[:20]}"


def _json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def normalize_merged_pr(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the provider-read merge shape without accepting host actions."""
    repository = _required_text(payload.get("repository"), "repository")
    try:
        pr_number = int(payload.get("pr_number"))
    except (TypeError, ValueError) as exc:
        raise ValueError("pr_number must be a positive integer") from exc
    if pr_number <= 0:
        raise ValueError("pr_number must be a positive integer")
    merge_sha = _required_text(payload.get("merge_sha"), "merge_sha")
    source_head_sha = _required_text(payload.get("source_head_sha"), "source_head_sha")
    merged_at = _required_text(payload.get("merged_at"), "merged_at")
    _parse_time(merged_at, "merged_at")
    provider_readback = payload.get("provider_readback")
    if not isinstance(provider_readback, Mapping) or provider_readback.get("verified") is not True:
        raise ValueError("provider_readback.verified must be true")
    return {
        "repository": repository,
        "pr_number": pr_number,
        "merge_sha": merge_sha,
        "source_head_sha": source_head_sha,
        "merged_at": merged_at,
        "provider_readback": deepcopy(dict(provider_readback)),
    }


class HostEventStore:
    """File-backed event/delivery state with explicit lease and retry semantics."""

    def __init__(self, root: str | Path, *, clock: callable = utc_now) -> None:
        self.root = Path(root).expanduser().resolve()
        self.clock = clock

    def _event_path(self, key: str) -> Path:
        return self.root / EVENTS_DIRECTORY / f"{_event_id(key)}.json"

    def _delivery_path(self, key: str) -> Path:
        return self.root / DELIVERIES_DIRECTORY / f"{_event_id(key)}.json"

    def _dead_letter_path(self, key: str) -> Path:
        return self.root / DEAD_LETTERS_DIRECTORY / f"{_event_id(key)}.json"

    def append_merged_pr(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Persist one verified provider readback. Duplicate deliveries are a no-op."""
        merged = normalize_merged_pr(payload)
        key = merged_pr_idempotency_key(merged["repository"], merged["pr_number"], merged["merge_sha"])
        event_path = self._event_path(key)
        if event_path.exists():
            return _json_object(event_path, "host event")
        observed_at = self.clock()
        event = {
            "api_version": API_VERSION,
            "id": _event_id(key),
            "type": MERGED_PR_EVENT_TYPE,
            "idempotency_key": key,
            "observed_at": observed_at,
            "delivery_mode": "proposal_only",
            "host_mutation_permitted": False,
            "payload": merged,
        }
        delivery = {
            "api_version": API_VERSION,
            "event_id": event["id"],
            "idempotency_key": key,
            "status": "pending",
            "attempts": 0,
            "max_attempts": 3,
            "lease": None,
            "acknowledgement": None,
            "last_error": None,
            "created_at": observed_at,
            "updated_at": observed_at,
        }
        _write_json(event_path, event)
        _write_json(self._delivery_path(key), delivery)
        return event

    def readback(self, idempotency_key: str) -> dict[str, Any] | None:
        event_path = self._event_path(idempotency_key)
        if not event_path.exists():
            return None
        event = _json_object(event_path, "host event")
        delivery = _json_object(self._delivery_path(idempotency_key), "host event delivery")
        return {"event": event, "delivery": delivery}

    def claim(self, idempotency_key: str, *, consumer: str, lease_seconds: int = 300) -> dict[str, Any] | None:
        """Claim a replay-safe lease. A live lease is never stolen early."""
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        readback = self.readback(idempotency_key)
        if readback is None:
            raise ValueError("host event is not present")
        delivery = readback["delivery"]
        if delivery["status"] in {"acknowledged", "dead-letter"}:
            return None
        now = _parse_time(self.clock(), "clock")
        lease = delivery.get("lease")
        if isinstance(lease, Mapping) and lease.get("expires_at"):
            if _parse_time(str(lease["expires_at"]), "lease.expires_at") > now:
                return None
        if int(delivery["attempts"]) >= int(delivery["max_attempts"]):
            self._dead_letter(idempotency_key, delivery, "retry budget exhausted")
            return None
        expires_at = (now + timedelta(seconds=lease_seconds)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        lease_id = hashlib.sha256(f"{idempotency_key}:{consumer}:{now.isoformat()}".encode()).hexdigest()[:20]
        delivery.update(
            {
                "status": "leased",
                "attempts": int(delivery["attempts"]) + 1,
                "lease": {"id": lease_id, "consumer": _required_text(consumer, "consumer"), "expires_at": expires_at},
                "updated_at": self.clock(),
            }
        )
        _write_json(self._delivery_path(idempotency_key), delivery)
        return {"event": readback["event"], "lease": deepcopy(delivery["lease"]), "attempt": delivery["attempts"]}

    def acknowledge(self, idempotency_key: str, *, lease_id: str, receipt: Mapping[str, Any]) -> dict[str, Any]:
        """Acknowledge only a current lease with a durable proposal receipt."""
        if not isinstance(receipt, Mapping) or not _required_text(receipt.get("receipt_ref"), "receipt.receipt_ref"):
            raise ValueError("receipt.receipt_ref is required")
        readback = self.readback(idempotency_key)
        if readback is None:
            raise ValueError("host event is not present")
        delivery = readback["delivery"]
        lease = delivery.get("lease") if isinstance(delivery.get("lease"), Mapping) else {}
        if delivery.get("status") != "leased" or lease.get("id") != lease_id:
            raise ValueError("acknowledgement requires the current delivery lease")
        delivery.update(
            {
                "status": "acknowledged",
                "lease": None,
                "acknowledgement": deepcopy(dict(receipt)),
                "updated_at": self.clock(),
            }
        )
        _write_json(self._delivery_path(idempotency_key), delivery)
        return delivery

    def release(self, idempotency_key: str, *, lease_id: str, error: str) -> dict[str, Any]:
        """Release a failed lease for retry, or durably dead-letter it at the budget."""
        readback = self.readback(idempotency_key)
        if readback is None:
            raise ValueError("host event is not present")
        delivery = readback["delivery"]
        lease = delivery.get("lease") if isinstance(delivery.get("lease"), Mapping) else {}
        if delivery.get("status") != "leased" or lease.get("id") != lease_id:
            raise ValueError("release requires the current delivery lease")
        delivery["last_error"] = _required_text(error, "error")
        delivery["lease"] = None
        delivery["updated_at"] = self.clock()
        if int(delivery["attempts"]) >= int(delivery["max_attempts"]):
            return self._dead_letter(idempotency_key, delivery, delivery["last_error"])
        delivery["status"] = "pending"
        _write_json(self._delivery_path(idempotency_key), delivery)
        return delivery

    def replay(self, idempotency_key: str) -> dict[str, Any]:
        """Explicitly requeue a dead letter; automatic retries remain bounded."""
        readback = self.readback(idempotency_key)
        if readback is None:
            raise ValueError("host event is not present")
        delivery = readback["delivery"]
        if delivery.get("status") != "dead-letter":
            raise ValueError("only dead-letter events may be replayed")
        delivery.update(
            {
                "status": "pending",
                "attempts": 0,
                "lease": None,
                "replayed_at": self.clock(),
                "updated_at": self.clock(),
            }
        )
        _write_json(self._delivery_path(idempotency_key), delivery)
        return delivery

    def _dead_letter(self, idempotency_key: str, delivery: dict[str, Any], reason: str) -> dict[str, Any]:
        delivery.update({"status": "dead-letter", "lease": None, "last_error": reason, "updated_at": self.clock()})
        _write_json(self._delivery_path(idempotency_key), delivery)
        _write_json(self._dead_letter_path(idempotency_key), delivery)
        return delivery


def default_retention_policy() -> dict[str, Any]:
    """Explicit policy boundary for AGE-144; it deliberately performs nothing."""
    return {
        "api_version": "host-cleanup-retention-policy/v1",
        "container_removal": {"mode": "exact_reviewed_resources_only"},
        "named_volume_deletion": {"mode": "exact_reviewed_resources_only"},
        "shared_images": {"mode": "retain", "protected_names": ["los-django-local:shared"]},
        "dangling_images": {"mode": "review_only", "requires": ["ownership", "age", "size", "receipt"]},
        "build_cache": {"mode": "review_only", "requires": ["ownership", "age", "size", "receipt"]},
        "merged_pr_automation": {"image_or_cache_prune": "prohibited"},
    }


def _one_matching_worktree(event: Mapping[str, Any], worktrees: Iterable[Mapping[str, Any]]) -> Mapping[str, Any]:
    payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
    matches = [
        candidate
        for candidate in worktrees
        if candidate.get("repository") == payload.get("repository")
        and int(candidate.get("pr_number") or 0) == payload.get("pr_number")
        and candidate.get("source_head_sha") == payload.get("source_head_sha")
    ]
    if len(matches) != 1:
        raise ValueError(f"merged PR must resolve exactly one managed worktree; found {len(matches)}")
    return matches[0]


def build_cleanup_proposal(event: Mapping[str, Any], worktrees: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Build a review receipt only. It has no host-command execution path."""
    if event.get("type") != MERGED_PR_EVENT_TYPE or event.get("host_mutation_permitted") is not False:
        raise ValueError("cleanup proposals require a proposal-only merged-PR host event")
    worktree = _one_matching_worktree(event, worktrees)
    runtime = worktree.get("runtime") if isinstance(worktree.get("runtime"), Mapping) else {}
    resources = worktree.get("reviewed_resources") if isinstance(worktree.get("reviewed_resources"), list) else []
    exact_resources = [str(name) for name in resources if str(name).strip()]
    evidence = worktree.get("evidence") if isinstance(worktree.get("evidence"), Mapping) else {}
    required_gates = {
        "provider_merge_readback": bool((event.get("payload") or {}).get("provider_readback", {}).get("verified")),
        "fast_worktree_runtime": runtime.get("fast_worktree") is True,
        "clean_git_status": evidence.get("clean_git_status") is True,
        "no_unpushed_commits": evidence.get("no_unpushed_commits") is True,
        "reopen_hold_absent": evidence.get("reopen_hold_absent") is True,
        "runtime_teardown_receipt": bool(evidence.get("runtime_teardown_receipt")),
        "worktree_finalization_receipt": bool(evidence.get("worktree_finalization_receipt")),
        "exact_reviewed_resources": bool(exact_resources),
    }
    eligible_for_approval = all(required_gates.values())
    return {
        "api_version": "host-cleanup-proposal/v1",
        "event_id": event.get("id"),
        "idempotency_key": event.get("idempotency_key"),
        "mode": "proposal_only",
        "approval_required": True,
        "apply_allowed": False,
        "eligible_for_approval": eligible_for_approval,
        "required_gates": required_gates,
        "worktree": {
            "identity": worktree.get("identity"),
            "path": worktree.get("path"),
            "runtime": deepcopy(dict(runtime)),
        },
        "reclaim": {
            "command": "agentic-os-docker-reclaim",
            "only": exact_resources,
            "protected": ["los_gold", "los-django-local:shared"],
            "host_wide_apply": False,
        },
        "retention_policy": default_retention_policy(),
    }


def write_cleanup_proposal(root: str | Path, proposal: Mapping[str, Any]) -> Path:
    """Persist the review artifact. Writing a proposal never invokes teardown."""
    if proposal.get("mode") != "proposal_only" or proposal.get("apply_allowed") is not False:
        raise ValueError("only non-executing cleanup proposals may be persisted")
    key = _required_text(proposal.get("idempotency_key"), "proposal.idempotency_key")
    path = Path(root).expanduser().resolve() / PROPOSALS_DIRECTORY / f"{_event_id(key)}.json"
    _write_json(path, proposal)
    return path
