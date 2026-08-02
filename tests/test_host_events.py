from __future__ import annotations

from datetime import datetime, timezone

import pytest

from genomes_agentic_os.host_events import (
    HostEventStore,
    build_cleanup_proposal,
    default_retention_policy,
    merged_pr_idempotency_key,
    write_cleanup_proposal,
)


def _clock() -> str:
    return "2026-08-02T12:00:00Z"


def _merged_pr() -> dict[str, object]:
    return {
        "repository": "michaelwclark/genomes_agentic_os",
        "pr_number": 153,
        "merge_sha": "abc123merge",
        "source_head_sha": "def456head",
        "merged_at": "2026-08-02T11:59:00Z",
        "provider_readback": {"verified": True, "provider": "github", "url": "https://example.test/pr/153"},
    }


def _worktree() -> dict[str, object]:
    return {
        "repository": "michaelwclark/genomes_agentic_os",
        "pr_number": 153,
        "source_head_sha": "def456head",
        "identity": "080202-aos-stack-cleaner",
        "path": "/private/worktrees/aos-stack-cleaner",
        "runtime": {"identity": "aos-stack-cleaner", "ownership": "managed", "fast_worktree": True},
        "reviewed_resources": ["aos-stack-cleaner_default", "aos-stack-cleaner_postgres_data"],
        "evidence": {
            "clean_git_status": True,
            "no_unpushed_commits": True,
            "reopen_hold_absent": True,
            "runtime_teardown_receipt": "runtime-cleanup.json",
            "worktree_finalization_receipt": "worktree-finalization.json",
        },
    }


def test_merged_pr_event_uses_the_required_durable_idempotency_key(tmp_path):
    store = HostEventStore(tmp_path, clock=_clock)

    event = store.append_merged_pr(_merged_pr())
    duplicate = store.append_merged_pr(_merged_pr())

    key = "michaelwclark/genomes_agentic_os:153:abc123merge"
    assert event["idempotency_key"] == key
    assert duplicate == event
    assert event["payload"] == _merged_pr()
    assert event["delivery_mode"] == "proposal_only"
    assert event["host_mutation_permitted"] is False


def test_delivery_requires_lease_ack_and_is_readable_after_ack(tmp_path):
    store = HostEventStore(tmp_path, clock=_clock)
    event = store.append_merged_pr(_merged_pr())

    claim = store.claim(event["idempotency_key"], consumer="aos-stack-cleaner")
    assert claim is not None
    assert store.claim(event["idempotency_key"], consumer="another-consumer") is None

    acknowledged = store.acknowledge(
        event["idempotency_key"],
        lease_id=claim["lease"]["id"],
        receipt={"receipt_ref": "cleanup-proposals/hostevt.json", "mode": "proposal_only"},
    )

    assert acknowledged["status"] == "acknowledged"
    assert store.readback(event["idempotency_key"])["delivery"]["acknowledgement"]["mode"] == "proposal_only"


def test_delivery_retries_then_dead_letters_and_can_be_explicitly_replayed(tmp_path):
    store = HostEventStore(tmp_path, clock=_clock)
    event = store.append_merged_pr(_merged_pr())
    key = event["idempotency_key"]

    for _ in range(3):
        claim = store.claim(key, consumer="aos-stack-cleaner")
        assert claim is not None
        delivery = store.release(key, lease_id=claim["lease"]["id"], error="receipt unavailable")

    assert delivery["status"] == "dead-letter"
    assert store.claim(key, consumer="aos-stack-cleaner") is None
    assert store.replay(key)["status"] == "pending"


def test_cleanup_proposal_requires_one_exact_worktree_and_never_allows_apply(tmp_path):
    store = HostEventStore(tmp_path, clock=_clock)
    event = store.append_merged_pr(_merged_pr())

    proposal = build_cleanup_proposal(event, [_worktree()])
    proposal_path = write_cleanup_proposal(tmp_path, proposal)

    assert proposal["eligible_for_approval"] is True
    assert proposal["approval_required"] is True
    assert proposal["apply_allowed"] is False
    assert proposal["reclaim"] == {
        "command": "agentic-os-docker-reclaim",
        "only": ["aos-stack-cleaner_default", "aos-stack-cleaner_postgres_data"],
        "protected": ["los_gold", "los-django-local:shared"],
        "host_wide_apply": False,
    }
    assert proposal_path.is_file()
    with pytest.raises(ValueError, match="exactly one"):
        build_cleanup_proposal(event, [_worktree(), _worktree()])


def test_proposal_is_not_approval_eligible_when_any_required_evidence_is_missing(tmp_path):
    store = HostEventStore(tmp_path, clock=_clock)
    event = store.append_merged_pr(_merged_pr())
    worktree = _worktree()
    worktree["evidence"] = {"clean_git_status": True}

    proposal = build_cleanup_proposal(event, [worktree])

    assert proposal["eligible_for_approval"] is False
    assert proposal["apply_allowed"] is False
    assert proposal["required_gates"]["no_unpushed_commits"] is False
    assert proposal["required_gates"]["reopen_hold_absent"] is False


def test_retention_policy_protects_shared_images_and_forbids_automation_prune():
    policy = default_retention_policy()

    assert policy["shared_images"] == {"mode": "retain", "protected_names": ["los-django-local:shared"]}
    assert policy["dangling_images"]["mode"] == "review_only"
    assert policy["build_cache"]["mode"] == "review_only"
    assert policy["merged_pr_automation"]["image_or_cache_prune"] == "prohibited"


def test_idempotency_key_rejects_an_invalid_pr_number():
    with pytest.raises(ValueError, match="positive integer"):
        merged_pr_idempotency_key("repo", 0, "merge")
