"""Bounded disk history and sustained-growth decisions, independent of fullness.

Rates are bytes/day; percentage rates are capacity percentage points/day, not
relative percentage changes. The normal EWMA freezes during candidate incidents
so a runaway writer cannot teach the monitor that its own growth is normal.
"""

from __future__ import annotations

import math
from typing import Any

DAY = 86400
GIB = 1024**3


def _slope(samples: list[list[float]], start: float, end: float, minimum: float) -> float | None:
    rows = [r for r in samples if start <= r[0] <= end]
    if len(rows) < 3 or rows[-1][0] - rows[0][0] < minimum:
        return None
    if any(b[0] - a[0] > 900 for a, b in zip(rows, rows[1:])):
        return None
    times = [r[0] - rows[0][0] for r in rows]
    # Subtract the first reading to preserve precision with large volumes.
    used = [rows[0][1] - r[1] for r in rows]
    tx, uy = sum(times) / len(times), sum(used) / len(used)
    variance = sum((t - tx) ** 2 for t in times)
    return DAY * sum((t - tx) * (u - uy) for t, u in zip(times, used)) / variance if variance else None


def observe_disk_trend(
    previous: dict[str, Any], *, now: float, total: int, available: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return persisted history and a compact, auditable trend receipt.

    Five-minute samples: 7 days, at most 2017 rows. A recent 60-minute regression
    needs 30 minutes of observations; a candidate must then persist 30 minutes.
    A 15-minute slope rejects bursts that have stopped. Missing observations
    reset persistence. Capacity changes reset incompatible history/baselines.
    """
    state = dict(previous)
    rows = [list(r) for r in state.get("samples", []) if len(r) == 2 and now - 7 * DAY <= r[0] < now]
    if state.get("total_bytes") != total or (state.get("last_at") is not None and now <= state["last_at"]):
        state, rows = {}, []
    last_at = state.get("last_at")
    gap = now - last_at if last_at is not None else 0
    if gap > 900:
        state["candidate_since"] = None
    # A cleanup drop starts a new recent segment. Keep older history for audit.
    if rows and available - rows[-1][1] > max(GIB, total * .005):
        state["segment_since"] = now
        state["candidate_since"] = None
        state["active"] = False
    rows.append([now, available])
    rows = rows[-2017:]
    segment = max(state.get("segment_since", 0), now - 3600)
    recent = _slope(rows, segment, now, 1800)
    fast = _slope(rows, max(segment, now - 900), now, 600)
    short = _slope(rows, max(segment, now - 1800), now, 1500)
    prior = _slope(rows, max(segment, now - 3600), now - 1800, 1500)
    baseline = float(state.get("baseline_bpd", 0))
    baseline_ready = state.get("baseline_seconds", 0) >= 6 * 3600
    acceleration = (short - prior) * 2 if short is not None and prior is not None else None
    growth_floor = max(total * .02, 4 * GIB)
    deviation_floor = max(total * .005, 2 * GIB)
    hours_left = available / recent * 24 if recent is not None and recent > 0 else None
    signals = []
    continuing = recent is not None and recent > 0 and fast is not None and fast >= recent * .25
    if continuing:
        if recent >= growth_floor:
            signals.append("sustained_growth")
        if baseline_ready and recent >= max(max(0, baseline) * 3, baseline + deviation_floor):
            signals.append("above_normal_baseline")
        if short is not None and prior is not None and short >= max(max(0, prior) * 2, prior + deviation_floor):
            signals.append("accelerating_growth")
        if hours_left is not None and hours_left <= 14 * 24:
            signals.append("projected_exhaustion")
    if signals:
        if state.get("candidate_since") is None:
            state["candidate_since"] = now
        if now - state["candidate_since"] >= 1800:
            state["active"] = True
    elif recent is not None:
        state["candidate_since"] = None
        state["active"] = False
    # Learn only observed, quiet periods. Freeze on candidate/active anomalies.
    if recent is not None and not signals and not state.get("active") and 0 < gap <= 900:
        dt = min(gap, 300)
        normal_rate = max(0, recent)
        if "baseline_bpd" not in state:
            baseline = normal_rate
        else:
            alpha = 1 - math.exp(-math.log(2) * dt / DAY)
            baseline = max(0, baseline + alpha * (normal_rate - baseline))
        state["baseline_bpd"] = baseline
        state["baseline_seconds"] = min(7 * DAY, state.get("baseline_seconds", 0) + dt)
    state.update(samples=rows, total_bytes=total, last_at=now)
    active = bool(state.get("active"))
    metrics = {
        "sampled_at_epoch": now,
        "status": "warming_up" if recent is None else ("anomaly" if active else "candidate" if signals else "normal"),
        "sample_count": len(rows),
        "history_hours": (rows[-1][0] - rows[0][0]) / 3600,
        "recent_bytes_per_day": recent,
        "recent_percentage_points_per_day": recent / total * 100 if recent is not None else None,
        "six_hour_bytes_per_day": _slope(rows, now - 6 * 3600, now, 3 * 3600),
        "day_bytes_per_day": _slope(rows, now - DAY, now, 12 * 3600),
        "baseline_bytes_per_day": state.get("baseline_bpd"),
        "baseline_ready": state.get("baseline_seconds", 0) >= 6 * 3600,
        "acceleration_percentage_points_per_day_per_hour": acceleration / total * 100 if acceleration is not None else None,
        "projected_hours_to_exhaustion": hours_left,
        "candidate_minutes": (now - state["candidate_since"]) / 60 if state.get("candidate_since") is not None else 0,
        "signals": signals,
        "active": active,
        "level": "critical" if active and hours_left is not None and hours_left <= 24 else "warning",
    }
    return state, metrics
