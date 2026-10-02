"""Prove early detection at low usage without learning a runaway as normal."""

import pytest

from genomes_agentic_os.host_disk_trends import DAY, GIB, observe_disk_trend

TOTAL = 2000 * GIB
START = 1_800_000_000


def sample(state, minute, used_pct):
    return observe_disk_trend(state, now=START + minute * 60,
                              total=TOTAL, available=round(TOTAL * (1 - used_pct / 100)))


def test_twelve_percent_with_eight_points_per_day_alerts_within_hour():
    state, first = {}, None
    for minute in range(0, 76, 5):
        state, metrics = sample(state, minute, 12 + 8 * minute / 1440)
        if metrics["active"] and first is None:
            first = minute
    assert first == 60
    assert metrics["recent_percentage_points_per_day"] == pytest.approx(8)
    assert 10 < metrics["projected_hours_to_exhaustion"] / 24 < 12
    assert "sustained_growth" in metrics["signals"]
    assert not metrics["baseline_ready"]


def test_stable_low_usage_never_alerts_and_learns_baseline():
    state = {}
    for minute in range(0, 8 * 60, 5):
        state, metrics = sample(state, minute, 12)
        assert not metrics["active"]
    assert metrics["baseline_ready"]
    assert metrics["baseline_bytes_per_day"] == 0


def test_brief_large_burst_does_not_become_sustained_growth():
    state = {}
    for minute in range(0, 241, 5):
        used = 12 if minute < 60 else 16
        state, metrics = sample(state, minute, used)
        assert not metrics["active"]


def test_baseline_deviation_below_absolute_growth_limit():
    state = {}
    for minute in range(0, 12 * 60 + 1, 5):
        used = 12 + .1 * min(minute, 600) / 1440 + max(0, minute - 600) / 1440
        state, metrics = sample(state, minute, used)
    assert metrics["active"]
    assert "above_normal_baseline" in metrics["signals"]
    assert "sustained_growth" not in metrics["signals"]
    assert metrics["baseline_bytes_per_day"] / TOTAL * 100 < .2


def test_acceleration_is_measured():
    state = {}
    for minute in range(0, 91, 5):
        # Continuous acceleration: rate rises from zero to 18 points/day.
        used = 12 + .1 * minute**2 / 1440
        state, metrics = sample(state, minute, used)
    assert metrics["acceleration_percentage_points_per_day_per_hour"] == pytest.approx(12, rel=.02)
    assert metrics["active"]


def test_large_cleanup_resets_recent_trend_and_clears_incident():
    state = {}
    for minute in range(0, 91, 5):
        state, metrics = sample(state, minute, 30 + 8 * minute / 1440)
    assert metrics["active"]
    state, metrics = sample(state, 95, 12)
    assert not metrics["active"]
    assert metrics["recent_percentage_points_per_day"] is None
    assert metrics["sample_count"] > 1


def test_long_gap_does_not_count_as_sustained_observation():
    state = {}
    for minute in range(0, 46, 5):
        state, metrics = sample(state, minute, 12 + 8 * minute / 1440)
    assert not metrics["active"]
    state, metrics = sample(state, 180, 13)
    assert not metrics["active"]
    assert metrics["status"] == "warming_up"
    assert metrics["candidate_minutes"] == 0


def test_capacity_change_resets_history_and_baseline():
    state, _ = sample({}, 0, 12)
    state, metrics = observe_disk_trend(state, now=START + 300,
                                       total=TOTAL * 2, available=TOTAL)
    assert metrics["sample_count"] == 1
    assert not metrics["active"]


def test_history_is_bounded_to_seven_days():
    # A full long-run simulation also exercises serialization-size bounds.
    state = {}
    for minute in range(0, 8 * 1440, 5):
        state, metrics = sample(state, minute, 12)
    assert metrics["sample_count"] <= 2017
    assert metrics["history_hours"] <= 168


def test_clock_rollback_does_not_produce_growth():
    state, _ = sample({}, 10, 12)
    state, metrics = sample(state, 5, 20)
    assert metrics["sample_count"] == 1
    assert not metrics["active"]


def test_cleanup_does_not_teach_a_negative_normal_baseline():
    state = {}
    for minute in range(0, 9 * 60, 5):
        used = 12 - min(minute, 60) * .001 + max(0, minute - 60) * .1 / 1440
        state, metrics = sample(state, minute, used)
        assert not metrics["active"]
        baseline = metrics["baseline_bytes_per_day"]
        assert baseline is None or baseline >= 0
