from __future__ import annotations

import pytest

from genomes_agentic_os.release_rollout import rollout_gate


RELEASE = {"published": True, "draft": False, "version": "1.2.4", "tag": "v1.2.4"}


def _receipt(status: str) -> dict[str, object]:
    return {"status": status, "release": {"version": "1.2.4", "tag": "v1.2.4"}}


def test_rollout_starts_with_first_host_and_only_releases_second_host_after_health() -> None:
    initial = rollout_gate(RELEASE)
    assert initial["status"] == "ready"
    assert initial["next_host"] == "first_host"

    waiting = rollout_gate(RELEASE, {"first_host": {"reinstall": _receipt("reinstalled")}})
    assert waiting["status"] == "awaiting_health"
    assert waiting["next_host"] == "first_host"

    second = rollout_gate(
        RELEASE,
        {"first_host": {"reinstall": _receipt("reinstalled"), "health": _receipt("healthy")}},
    )
    assert second["status"] == "ready"
    assert second["next_host"] == "second_host"
    assert second["remote_execution"] == "not_implemented_by_design"


@pytest.mark.parametrize("health", ("failed", "stale", "unhealthy"))
def test_bad_first_host_health_blocks_second_host(health: str) -> None:
    result = rollout_gate(
        RELEASE,
        {"first_host": {"reinstall": _receipt("reinstalled"), "health": _receipt(health)}},
    )
    assert result["status"] == "blocked"
    assert result["next_host"] is None
    assert "first-host health gate failed" in result["reason"]


def test_second_host_evidence_before_first_host_health_is_an_order_violation() -> None:
    result = rollout_gate(RELEASE, {"second_host": {"reinstall": _receipt("reinstalled")}})

    assert result["status"] == "blocked"
    assert "before first-host health gate" in result["reason"]


def test_completed_requires_final_host_health_receipt_for_the_same_release() -> None:
    evidence = {
        host: {"reinstall": _receipt("reinstalled"), "health": _receipt("healthy")}
        for host in ("first_host", "second_host")
    }

    result = rollout_gate(RELEASE, evidence)

    assert result["status"] == "completed"
    assert result["host_phases"] == {"first_host": "healthy", "second_host": "healthy"}
