"""Installed-root orchestration for adaptive-routing observe reports."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo

import yaml

from .adaptive_observation_projection import append_report_entry
from .adaptive_observation_reports import (
    append_observation_event,
    build_observation_report,
    load_pricing_catalog,
    parse_codex_rollout,
    read_observation_events,
    write_observation_report,
)


CONFIG_RELATIVE = Path("harness/shared_factory/00-control-plane/adaptive-routing-observation-report.yml")
DEFAULT_POLICY_RELATIVE = Path("harness/shared_factory/00-control-plane/adaptive-router.yml")


class ObservationRunnerError(RuntimeError):
    """Raised for invalid installed observe-report configuration."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _resolve(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ObservationRunnerError("configured path must be a non-empty string")
    path = Path(value).expanduser()
    return path if path.is_absolute() else root / path


def load_observation_config(root: str | Path, config_file: str | Path | None = None) -> dict[str, object]:
    os_root = Path(root).expanduser().resolve()
    path = Path(config_file).expanduser() if config_file else os_root / CONFIG_RELATIVE
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ObservationRunnerError("unable to load adaptive observation config") from exc
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ObservationRunnerError("adaptive observation config version must be 1")
    privacy = data.get("privacy")
    if not isinstance(privacy, Mapping) or any(
        privacy.get(field) is not False
        for field in ("persist_task_text", "persist_conversation_text", "persist_tool_arguments")
    ):
        raise ObservationRunnerError("adaptive observation privacy flags must remain false")
    return data


def observation_paths(root: str | Path, config: Mapping[str, object]) -> dict[str, Path]:
    os_root = Path(root).expanduser().resolve()
    return {
        "ledger": _resolve(os_root, config.get("observation_ledger")),
        "report_root": _resolve(os_root, config.get("report_root")),
        "pricing": _resolve(os_root, config.get("pricing_catalog")),
        "policy": os_root / DEFAULT_POLICY_RELATIVE,
    }


def record_plan_observation(
    root: str | Path,
    operation: Mapping[str, object],
    *,
    policy_fingerprint: str,
    correlation_id: str | None = None,
    timestamp: str | None = None,
    config_file: str | Path | None = None,
) -> dict[str, object]:
    config = load_observation_config(root, config_file)
    if config.get("enabled") is not True or config.get("mode") != "observe":
        return {"status": "disabled", "written": False}
    session_id = correlation_id or os.environ.get("CODEX_THREAD_ID")
    if not session_id:
        raise ObservationRunnerError("correlation ID is required; CODEX_THREAD_ID is unavailable")
    paths = observation_paths(root, config)
    turn_id = None
    roots = config.get("session_roots")
    if isinstance(roots, list):
        candidates = []
        for raw in roots:
            if not isinstance(raw, str):
                continue
            session_root = Path(raw).expanduser()
            if session_root.exists():
                candidates.extend(session_root.rglob(f"rollout-*{session_id}.jsonl"))
        if candidates:
            latest = max(candidates, key=lambda item: item.stat().st_mtime)
            parsed = parse_codex_rollout(latest)
            turns = parsed.get("turns")
            if isinstance(turns, list) and turns and isinstance(turns[-1], Mapping):
                candidate = turns[-1].get("turn_id")
                if isinstance(candidate, str):
                    turn_id = candidate
    correlation = f"{session_id}:{turn_id}" if turn_id else session_id
    event = append_observation_event(
        paths["ledger"],
        operation,
        correlation_id=correlation,
        session_id=session_id,
        turn_id=turn_id,
        policy_fingerprint=policy_fingerprint,
        timestamp=timestamp or iso(utc_now()),
    )
    return {"status": "observed", "written": True, "event": event}


def _event_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc)


def _rollout_paths(config: Mapping[str, object], start: datetime) -> list[Path]:
    roots = config.get("session_roots")
    if not isinstance(roots, list):
        raise ObservationRunnerError("session_roots must be a list")
    paths: list[Path] = []
    threshold = start.timestamp() - 3600
    for raw in roots:
        if not isinstance(raw, str):
            continue
        root = Path(raw).expanduser()
        if not root.exists():
            continue
        for candidate in root.rglob("rollout-*.jsonl"):
            try:
                if candidate.stat().st_mtime >= threshold:
                    paths.append(candidate)
            except OSError:
                continue
    return sorted(set(paths))


def _merge_usage(target: dict[str, object], source: Mapping[str, object]) -> None:
    for field in (
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
    ):
        left = target.get(field)
        right = source.get(field)
        target[field] = left + right if isinstance(left, int) and isinstance(right, int) else None


def attach_subagent_usage(sessions: list[dict[str, object]]) -> None:
    """Attribute child rollout usage to the parent turn that spawned it."""
    primaries = {
        session.get("session_id"): session
        for session in sessions
        if session.get("is_primary") is True and isinstance(session.get("session_id"), str)
    }
    for child in sessions:
        if child.get("is_primary") is not False:
            continue
        parent = primaries.get(child.get("session_id"))
        child_started = _event_time(child.get("started_at"))
        child_usage = child.get("usage")
        if parent is None or child_started is None or not isinstance(child_usage, Mapping):
            continue
        turns = parent.get("turns")
        if not isinstance(turns, list):
            continue
        candidates = []
        for turn in turns:
            if not isinstance(turn, dict):
                continue
            start = _event_time(turn.get("started_at"))
            end = _event_time(turn.get("ended_at"))
            if start is not None and start <= child_started and (end is None or child_started <= end):
                candidates.append(turn)
        if len(candidates) != 1:
            continue
        turn = candidates[0]
        turn_usage = turn.get("usage")
        model_usage = turn.get("model_usage")
        if not isinstance(turn_usage, dict) or not isinstance(model_usage, list):
            continue
        _merge_usage(turn_usage, child_usage)
        model_usage.append(
            {
                "model": child.get("model"),
                "reasoning_effort": child.get("reasoning_effort"),
                "usage": dict(child_usage),
                "source": "subagent_rollout",
            }
        )


def run_observation_report(
    root: str | Path,
    *,
    hours: int = 12,
    apply_notion: bool = False,
    config_file: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    if type(hours) is not int or hours < 1 or hours > 168:
        raise ObservationRunnerError("hours must be an integer from 1 through 168")
    os_root = Path(root).expanduser().resolve()
    config = load_observation_config(os_root, config_file)
    paths = observation_paths(os_root, config)
    end = (now or utc_now()).astimezone(timezone.utc)
    if config.get("completed_windows_only", True) is True:
        zone = ZoneInfo(str(config.get("timezone") or "UTC"))
        local = end.astimezone(zone)
        bucket_hour = (local.hour // hours) * hours if hours <= 24 and 24 % hours == 0 else local.hour
        end = local.replace(hour=bucket_hour, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    start = end - timedelta(hours=hours)
    all_observations = read_observation_events(paths["ledger"]) if paths["ledger"].is_file() else []
    observations = [
        event
        for event in all_observations
        if (stamp := _event_time(event.get("timestamp"))) is not None and start <= stamp <= end
    ]
    sessions = []
    parse_failures = 0
    for rollout in _rollout_paths(config, start):
        try:
            parsed = parse_codex_rollout(rollout)
        except (OSError, ValueError):
            parse_failures += 1
            continue
        ended = _event_time(parsed.get("ended_at"))
        if ended is None or not start <= ended <= end:
            continue
        sessions.append(parsed)
    attach_subagent_usage(sessions)
    pricing = load_pricing_catalog(paths["pricing"])
    report = build_observation_report(observations, sessions, pricing, generated_at=iso(end))
    report["window"] = {"start": iso(start), "end": iso(end), "hours": hours}
    report["collection"] = {
        "rollouts_considered": len(sessions),
        "parse_failures": parse_failures,
        "task_or_conversation_text_persisted": False,
    }
    identity = json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False)
    run_id = end.strftime("%Y%m%dT%H%M%SZ") + "-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    report["run_id"] = run_id
    artifacts = write_observation_report(paths["report_root"], report)
    projection: dict[str, object] = {"status": "not_requested"}
    if apply_notion:
        notion = config.get("notion")
        if not isinstance(notion, Mapping) or notion.get("apply") is not True:
            raise ObservationRunnerError("Notion apply is not enabled in reviewed config")
        try:
            projection = append_report_entry(
                report,
                notion=notion,
                run_id=run_id,
                window_start=iso(start),
                window_end=iso(end),
                receipt_path=artifacts["run_dir"] / "notion-projection.json",
            )
        except Exception as exc:  # Projection failure must not erase the canonical local report.
            projection = {
                "status": "blocked",
                "run_id": run_id,
                "reason": type(exc).__name__,
            }
            (artifacts["run_dir"] / "notion-projection.json").write_text(
                json.dumps(projection, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    return {
        "status": "complete_with_projection_blocked" if projection.get("status") == "blocked" else "complete",
        "run_id": run_id,
        "window": report["window"],
        "coverage": report["coverage"],
        "routing_health": report["routing_health"],
        "classification_field_agreement": report["classification_field_agreement"],
        "cost_totals": report["cost_totals"],
        "artifacts": {key: str(value) for key, value in artifacts.items()},
        "notion": projection,
    }
