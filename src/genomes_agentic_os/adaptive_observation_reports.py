"""Privacy-safe observation and cost reports for adaptive routing.

The module deliberately has no command-line or runtime hooks.  Observation
events contain only opaque identifiers and values already derived by the
adaptive router.  Codex transcript text is held only long enough to call
``assess_task`` and is never returned or written to an artifact.
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Iterable, Iterator, Mapping, Sequence

import yaml

from .task_assessment import assess_task


OBSERVATION_SCHEMA_VERSION = 1
REPORT_SCHEMA_VERSION = 1
PRICING_SCHEMA_VERSION = 1

_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_FINGERPRINT = re.compile(r"^[a-f0-9]{64}$")
_PRIVATE_KEYS = frozenset(
    {"task", "task_text", "prompt", "transcript", "message", "content", "text"}
)
_ASSESSMENT_FIELDS = (
    "task_family",
    "mutation_scope",
    "code_scope",
    "risk_flags",
    "uncertainty",
    "verification_needs",
    "context_depth",
    "expected_duration",
    "minimum_tier",
    "human_gate",
)
_USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)


class ObservationError(ValueError):
    """Base class for invalid or unsafe observation data."""


class DuplicateCorrelationError(ObservationError):
    """Raised when an event already exists for a correlation identifier."""


def _timestamp(value: str, field: str = "timestamp") -> str:
    if not isinstance(value, str):
        raise ObservationError(f"{field} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ObservationError(f"{field} must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ObservationError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _opaque_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not _OPAQUE_ID.fullmatch(value):
        raise ObservationError(
            f"{field} must be an opaque 8-128 character identifier"
        )
    if ".." in value:
        raise ObservationError(f"{field} must not contain path traversal")
    return value


def _privacy_check(value: object, path: str = "value") -> None:
    """Reject task-like keys before any object crosses a persistence boundary."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ObservationError(f"{path} keys must be strings")
            if key.casefold() in _PRIVATE_KEYS:
                raise ObservationError(f"privacy-sensitive field is forbidden: {path}.{key}")
            _privacy_check(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _privacy_check(child, f"{path}[{index}]")


def _json_copy(value: object) -> object:
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ObservationError("observation values must be finite JSON data") from exc


def _execution_plan(operation: Mapping[str, object]) -> Mapping[str, object]:
    plan = operation.get("execution_plan", operation)
    if not isinstance(plan, Mapping):
        raise ObservationError("operation.execution_plan must be an object")
    return plan


def make_observation_event(
    operation: Mapping[str, object],
    *,
    correlation_id: str,
    policy_fingerprint: str,
    timestamp: str,
    session_id: str | None = None,
    turn_id: str | None = None,
) -> dict[str, object]:
    """Create the minimal durable event from an adaptive plan operation."""
    if not isinstance(operation, Mapping):
        raise ObservationError("operation must be an object")
    _privacy_check(operation, "operation")
    correlation = _opaque_id(correlation_id, "correlation_id")
    if not isinstance(policy_fingerprint, str) or not _FINGERPRINT.fullmatch(
        policy_fingerprint
    ):
        raise ObservationError("policy_fingerprint must be 64 lowercase hex characters")

    plan = _execution_plan(operation)
    assessment = plan.get("assessment")
    if assessment is not None and not isinstance(assessment, Mapping):
        raise ObservationError("execution_plan.assessment must be an object or null")
    route = {
        "status": plan.get("status"),
        "model_tier": plan.get("model_tier"),
        "model_id": plan.get("model_id"),
        "reasoning_effort": plan.get("reasoning_effort"),
    }
    event: dict[str, object] = {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "event_type": "adaptive_route_observed",
        "timestamp": _timestamp(timestamp),
        "correlation_id": correlation,
        "session_id": _opaque_id(session_id, "session_id") if session_id else correlation,
        "turn_id": _opaque_id(turn_id, "turn_id") if turn_id else None,
        "policy_fingerprint": policy_fingerprint,
        "policy_version": plan.get("policy_version"),
        "operation_status": operation.get("operation_status"),
        "route": route,
        "assessment": dict(assessment) if assessment is not None else None,
    }
    copied = _json_copy(event)
    assert isinstance(copied, dict)
    _privacy_check(copied, "event")
    return copied


@contextmanager
def _locked_file(path: Path, *, exclusive: bool) -> Iterator[object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a+b" if exclusive else "rb"
    with path.open(mode) as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield handle
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_jsonl_handle(handle: object, *, strict: bool) -> tuple[list[dict[str, object]], int]:
    handle.seek(0)  # type: ignore[attr-defined]
    records: list[dict[str, object]] = []
    malformed = 0
    for line_number, raw in enumerate(handle, 1):  # type: ignore[union-attr]
        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8")
            except UnicodeDecodeError:
                malformed += 1
                if strict:
                    raise ObservationError(f"invalid UTF-8 at JSONL line {line_number}")
                continue
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError as exc:
            malformed += 1
            if strict:
                raise ObservationError(f"malformed JSONL line {line_number}") from exc
            continue
        if not isinstance(item, dict):
            malformed += 1
            if strict:
                raise ObservationError(f"JSONL line {line_number} is not an object")
            continue
        records.append(item)
    return records, malformed


def append_observation_event(
    path: str | Path,
    operation: Mapping[str, object],
    *,
    correlation_id: str,
    policy_fingerprint: str,
    timestamp: str,
    session_id: str | None = None,
    turn_id: str | None = None,
) -> dict[str, object]:
    """Append one event under an exclusive lock and fsync it before returning."""
    event = make_observation_event(
        operation,
        correlation_id=correlation_id,
        policy_fingerprint=policy_fingerprint,
        timestamp=timestamp,
        session_id=session_id,
        turn_id=turn_id,
    )
    target = Path(path)
    with _locked_file(target, exclusive=True) as handle:
        existing, _ = _read_jsonl_handle(handle, strict=False)
        if any(item.get("correlation_id") == correlation_id for item in existing):
            raise DuplicateCorrelationError(
                f"correlation_id already observed: {correlation_id}"
            )
        encoded = (
            json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n"
        ).encode("utf-8")
        handle.seek(0, os.SEEK_END)  # type: ignore[attr-defined]
        written = os.write(handle.fileno(), encoded)  # type: ignore[attr-defined]
        if written != len(encoded):
            raise OSError("short atomic JSONL append")
        os.fsync(handle.fileno())  # type: ignore[attr-defined]
    return event


def read_observation_events(
    path: str | Path, *, strict: bool = False
) -> list[dict[str, object]]:
    """Read valid, supported events; malformed/duplicate records are ignored by default."""
    target = Path(path)
    if not target.exists():
        return []
    with _locked_file(target, exclusive=False) as handle:
        records, _ = _read_jsonl_handle(handle, strict=strict)
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, item in enumerate(records, 1):
        try:
            if item.get("schema_version") != OBSERVATION_SCHEMA_VERSION:
                raise ObservationError("unsupported observation schema_version")
            correlation = _opaque_id(item.get("correlation_id"), "correlation_id")
            _privacy_check(item, f"event[{index}]")
            if correlation in seen:
                raise DuplicateCorrelationError(f"duplicate correlation_id: {correlation}")
            seen.add(correlation)
            result.append(item)
        except ObservationError:
            if strict:
                raise
    return result


def _content_text(payload: Mapping[str, object]) -> str | None:
    content = payload.get("content")
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for part in content:
        if not isinstance(part, Mapping) or part.get("type") not in {"input_text", "text"}:
            continue
        text = part.get("text")
        if isinstance(text, str) and text.strip() and not text.lstrip().startswith("<"):
            parts.append(text)
    return "\n".join(parts) or None


def _usage(payload: Mapping[str, object]) -> dict[str, int | None] | None:
    if payload.get("type") != "token_count":
        return None
    info = payload.get("info")
    usage = info.get("last_token_usage") if isinstance(info, Mapping) else None
    if not isinstance(usage, Mapping) and isinstance(info, Mapping):
        usage = info.get("total_token_usage")
    if not isinstance(usage, Mapping):
        return None
    result: dict[str, int | None] = {}
    for field in _USAGE_FIELDS:
        value = usage.get(field)
        result[field] = value if isinstance(value, int) and value >= 0 else None
    return result


def _add_usage(
    target: dict[str, int | None], source: Mapping[str, object]
) -> None:
    for field in _USAGE_FIELDS:
        value = source.get(field)
        if not isinstance(value, int) or value < 0:
            target[field] = None
        elif target.get(field) is not None:
            target[field] = int(target[field]) + value


def parse_codex_rollout(path: str | Path) -> dict[str, object]:
    """Parse a Codex rollout without modifying it or exposing transcript text."""
    target = Path(path)
    session_id: str | None = None
    model: str | None = None
    effort: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    usage: dict[str, int | None] = {field: 0 for field in _USAGE_FIELDS}
    correlation_ids: set[str] = set()
    turns: list[dict[str, object]] = []
    current_turn: dict[str, object] | None = None
    malformed = 0
    filename_match = re.search(r"([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\.jsonl$", target.name)
    rollout_id = filename_match.group(1) if filename_match else None

    with target.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                malformed += 1
                continue
            if not isinstance(record, Mapping):
                malformed += 1
                continue
            raw_timestamp = record.get("timestamp")
            if isinstance(raw_timestamp, str):
                try:
                    normalized = _timestamp(raw_timestamp)
                except ObservationError:
                    normalized = None
                if normalized is not None:
                    started_at = min(started_at, normalized) if started_at else normalized
                    ended_at = max(ended_at, normalized) if ended_at else normalized
            payload = record.get("payload")
            if not isinstance(payload, Mapping):
                continue
            record_type = record.get("type")
            if record_type == "session_meta":
                raw_id = payload.get("session_id", payload.get("id"))
                if isinstance(raw_id, str) and _OPAQUE_ID.fullmatch(raw_id):
                    session_id = raw_id
                    correlation_ids.add(raw_id)
            elif record_type == "turn_context":
                if isinstance(payload.get("model"), str):
                    model = payload["model"]  # type: ignore[assignment]
                raw_effort = payload.get("effort", payload.get("reasoning_effort"))
                collaboration = payload.get("collaboration_mode")
                settings = collaboration.get("settings") if isinstance(collaboration, Mapping) else None
                if isinstance(settings, Mapping):
                    if model is None and isinstance(settings.get("model"), str):
                        model = settings["model"]  # type: ignore[assignment]
                    if raw_effort is None:
                        raw_effort = settings.get("reasoning_effort")
                if isinstance(raw_effort, str):
                    effort = raw_effort
                if current_turn is not None:
                    current_turn["model"] = model
                    current_turn["reasoning_effort"] = effort
            elif record_type == "event_msg":
                candidate_usage = _usage(payload)
                if candidate_usage is not None:
                    _add_usage(usage, candidate_usage)
                    if current_turn is not None:
                        turn_usage = current_turn["usage"]
                        assert isinstance(turn_usage, dict)
                        _add_usage(turn_usage, candidate_usage)
            elif (
                record_type == "response_item"
                and payload.get("type") == "message"
                and payload.get("role") == "user"
            ):
                metadata = payload.get("internal_chat_message_metadata_passthrough")
                if isinstance(metadata, Mapping):
                    turn_id = metadata.get("turn_id")
                    if isinstance(turn_id, str) and _OPAQUE_ID.fullmatch(turn_id):
                        correlation_ids.add(turn_id)
                fragment = _content_text(payload)
                if fragment is not None and isinstance(raw_timestamp, str):
                    if current_turn is not None:
                        turns.append(current_turn)
                    current_turn = {
                        "turn_id": (
                            turn_id
                            if isinstance(metadata, Mapping)
                            and isinstance((turn_id := metadata.get("turn_id")), str)
                            else None
                        ),
                        "started_at": _timestamp(raw_timestamp),
                        "model": model,
                        "reasoning_effort": effort,
                        "usage": {field: 0 for field in _USAGE_FIELDS},
                        "model_usage": [],
                        "retrospective_assessment": assess_task(fragment).as_dict(),
                    }
    if current_turn is not None:
        turns.append(current_turn)
    for index, turn in enumerate(turns):
        turn["ended_at"] = (
            turns[index + 1]["started_at"] if index + 1 < len(turns) else ended_at
        )
        model_usage = turn["model_usage"]
        assert isinstance(model_usage, list)
        if turn.get("model") is not None:
            model_usage.append(
                {
                    "model": turn.get("model"),
                    "reasoning_effort": turn.get("reasoning_effort"),
                    "usage": turn.get("usage"),
                    "source": "primary_turn",
                }
            )
    assessment = turns[-1]["retrospective_assessment"] if turns else None
    is_primary = rollout_id is None or session_id is None or rollout_id == session_id
    if not is_primary and session_id is not None:
        correlation_ids.discard(session_id)
    if rollout_id is not None:
        correlation_ids.add(rollout_id)
    result: dict[str, object] = {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "source_type": "codex_rollout",
        "session_id": session_id,
        "thread_id": session_id,
        "rollout_id": rollout_id,
        "is_primary": is_primary,
        "correlation_ids": sorted(correlation_ids),
        "model": model,
        "reasoning_effort": effort,
        "usage": usage if turns else None,
        "started_at": started_at,
        "ended_at": ended_at,
        "retrospective_assessment": assessment,
        "turns": turns,
        "diagnostics": {"malformed_lines": malformed},
    }
    _privacy_check(result, "rollout_result")
    return result


extract_codex_rollout = parse_codex_rollout


def parse_codex_rollouts(paths: Iterable[str | Path]) -> list[dict[str, object]]:
    return [parse_codex_rollout(path) for path in paths]


def join_observations_to_sessions(
    observations: Sequence[Mapping[str, object]],
    sessions: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Left-join observations to sessions, rejecting ambiguous correlations."""
    index: dict[str, Mapping[str, object] | None] = {}
    for session in sessions:
        identifiers = set()
        identity_keys = ("session_id", "thread_id") if session.get("is_primary", True) else ("rollout_id",)
        for key in identity_keys:
            value = session.get(key)
            if isinstance(value, str):
                identifiers.add(value)
        values = session.get("correlation_ids")
        if isinstance(values, list):
            identifiers.update(value for value in values if isinstance(value, str))
        for identifier in identifiers:
            if identifier in index and index[identifier] is not session:
                index[identifier] = None
            else:
                index[identifier] = session

    joined: list[dict[str, object]] = []
    seen: set[str] = set()
    for observation in sorted(observations, key=lambda item: str(item.get("correlation_id"))):
        correlation = _opaque_id(observation.get("correlation_id"), "correlation_id")
        if correlation in seen:
            continue
        seen.add(correlation)
        session_key = observation.get("session_id", correlation)
        session = index.get(str(session_key))
        matched_turn = None
        if session is not None:
            observed_at = _timestamp(str(observation.get("timestamp")))
            observed_time = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
            turns = session.get("turns")
            if isinstance(turns, list):
                candidates = []
                expected_turn = observation.get("turn_id")
                for turn in turns:
                    if not isinstance(turn, Mapping):
                        continue
                    start = turn.get("started_at")
                    end = turn.get("ended_at")
                    if not isinstance(start, str):
                        continue
                    start_time = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    end_time = (
                        datetime.fromisoformat(end.replace("Z", "+00:00"))
                        if isinstance(end, str)
                        else None
                    )
                    exact_turn = expected_turn is not None and turn.get("turn_id") == expected_turn
                    timestamp_turn = expected_turn is None and start_time <= observed_time and (end_time is None or observed_time <= end_time)
                    if exact_turn or timestamp_turn:
                        candidates.append(turn)
                if len(candidates) == 1:
                    matched_turn = dict(candidates[0])
            elif isinstance(session.get("usage"), Mapping):
                # Backward-compatible normalized session fixtures are treated as
                # one already-bounded turn; real Codex rollouts always emit turns.
                matched_turn = dict(session)
        joined.append(
            {
                "correlation_id": correlation,
                "observation": dict(observation),
                "session": dict(session) if session is not None else None,
                "turn": matched_turn,
                "join_status": (
                    "matched"
                    if session is not None and matched_turn is not None
                    else "turn_unmatched"
                    if session is not None
                    else "ambiguous"
                    if correlation in index
                    else "unmatched"
                ),
            }
        )
    return joined


def _price(value: object, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ObservationError(f"{field} must be a non-negative number") from exc
    if not result.is_finite() or result < 0:
        raise ObservationError(f"{field} must be a non-negative finite number")
    return result


def load_pricing_catalog(path: str | Path) -> dict[str, object]:
    """Load the versioned per-million-token YAML pricing catalog."""
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ObservationError("unable to load pricing catalog") from exc
    if not isinstance(raw, Mapping):
        raise ObservationError("pricing catalog must be an object")
    version = raw.get("schema_version", raw.get("version"))
    if version != PRICING_SCHEMA_VERSION:
        raise ObservationError("unsupported pricing catalog schema_version")
    models = raw.get("models")
    if not isinstance(models, Mapping):
        raise ObservationError("pricing catalog models must be an object")
    normalized: dict[str, object] = {}
    for model_id, entry in sorted(models.items(), key=lambda item: str(item[0])):
        if not isinstance(model_id, str) or not _MODEL_ID.fullmatch(model_id):
            raise ObservationError("model_id must be a safe 3-128 character identifier")
        model = model_id
        if not isinstance(entry, Mapping):
            raise ObservationError(f"pricing model {model} must be an object")
        prices = entry.get("per_million", entry)
        if not isinstance(prices, Mapping):
            raise ObservationError(f"pricing model {model} prices must be an object")
        aliases = {
            "input": ("input", "input_per_million"),
            "cached_input": ("cached_input", "cached", "cached_input_per_million"),
            "output": ("output", "output_per_million"),
        }
        model_prices: dict[str, float | None] = {}
        for canonical, keys in aliases.items():
            found = next((prices[key] for key in keys if key in prices), None)
            if found is None:
                # Explicitly missing/null operator rates are valid unknown data.
                model_prices[canonical] = None
            else:
                model_prices[canonical] = float(_price(found, f"{model}.{canonical}"))
        relative = entry.get("relative_cost_index")
        model_prices["relative_cost_index"] = (
            float(_price(relative, f"{model}.relative_cost_index"))
            if relative is not None
            else None
        )
        normalized[model] = model_prices
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), default=str)
    return {
        "schema_version": PRICING_SCHEMA_VERSION,
        "catalog_version": raw.get("catalog_version", f"schema-{version}"),
        "effective_at": raw.get("effective_at"),
        "source": raw.get("source", "operator_config"),
        "fingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "currency": raw.get("currency", "USD"),
        "unit": "per_million_tokens",
        "models": normalized,
    }


def estimate_cost(
    usage: Mapping[str, object] | None,
    model_id: object,
    pricing_catalog: Mapping[str, object],
) -> float | None:
    """Estimate cost; return null whenever required usage or pricing is unknown."""
    if not isinstance(usage, Mapping) or not isinstance(model_id, str):
        return None
    models = pricing_catalog.get("models")
    prices = models.get(model_id) if isinstance(models, Mapping) else None
    if not isinstance(prices, Mapping):
        return None
    values: dict[str, int] = {}
    for field in ("input_tokens", "cached_input_tokens", "output_tokens"):
        value = usage.get(field)
        if not isinstance(value, int) or value < 0:
            return None
        values[field] = value
    if values["cached_input_tokens"] > values["input_tokens"]:
        return None
    try:
        cost = (
            Decimal(values["input_tokens"] - values["cached_input_tokens"])
            * _price(prices.get("input"), "input price")
            + Decimal(values["cached_input_tokens"])
            * _price(prices.get("cached_input"), "cached input price")
            + Decimal(values["output_tokens"])
            * _price(prices.get("output"), "output price")
        ) / Decimal(1_000_000)
    except ObservationError:
        return None
    return float(cost.quantize(Decimal("0.00000001")))


def estimate_model_usage_cost(
    model_usage: object, pricing_catalog: Mapping[str, object]
) -> float | None:
    if not isinstance(model_usage, list) or not model_usage:
        return None
    total = Decimal(0)
    for item in model_usage:
        if not isinstance(item, Mapping):
            return None
        cost = estimate_cost(
            item.get("usage") if isinstance(item.get("usage"), Mapping) else None,
            item.get("model"),
            pricing_catalog,
        )
        if cost is None:
            return None
        total += Decimal(str(cost))
    return float(total.quantize(Decimal("0.00000001")))


def estimate_relative_cost(
    model_usage: object, pricing_catalog: Mapping[str, object]
) -> float | None:
    if not isinstance(model_usage, list) or not model_usage:
        return None
    models = pricing_catalog.get("models")
    if not isinstance(models, Mapping):
        return None
    total = Decimal(0)
    for item in model_usage:
        if not isinstance(item, Mapping) or not isinstance(item.get("usage"), Mapping):
            return None
        model = models.get(item.get("model"))
        tokens = item["usage"].get("total_tokens")
        if not isinstance(model, Mapping) or not isinstance(tokens, int):
            return None
        index = model.get("relative_cost_index")
        if index is None:
            return None
        total += Decimal(tokens) * _price(index, "relative_cost_index") / Decimal(1_000_000)
    return float(total.quantize(Decimal("0.00000001")))


def _agreement(
    planned: object, retrospective: object
) -> tuple[dict[str, bool | None], int, int]:
    fields: dict[str, bool | None] = {}
    compared = agreed = 0
    for field in _ASSESSMENT_FIELDS:
        left = planned.get(field) if isinstance(planned, Mapping) else None
        right = retrospective.get(field) if isinstance(retrospective, Mapping) else None
        if left is None or right is None:
            fields[field] = None
            continue
        if isinstance(left, list):
            left = sorted(left)
        if isinstance(right, list):
            right = sorted(right)
        fields[field] = left == right
        compared += 1
        agreed += int(left == right)
    return fields, compared, agreed


def build_observation_report(
    observations: Sequence[Mapping[str, object]],
    sessions: Sequence[Mapping[str, object]],
    pricing_catalog: Mapping[str, object],
    *,
    generated_at: str,
) -> dict[str, object]:
    """Build a deterministic, privacy-checked actual-vs-routed report."""
    joined = join_observations_to_sessions(observations, sessions)
    records: list[dict[str, object]] = []
    health = Counter()
    compared_total = agreed_total = 0
    actual_cost_total = Decimal(0)
    projected_cost_total = Decimal(0)
    paired_costs = 0
    relative_actual_total = Decimal(0)
    relative_projected_total = Decimal(0)
    paired_relative_costs = 0
    matched = 0
    matched_turns = 0
    usage_records = 0
    token_totals = {field: 0 for field in _USAGE_FIELDS}
    for item in joined:
        observation = item["observation"]
        session = item["session"]
        turn = item.get("turn")
        assert isinstance(observation, Mapping)
        route = observation.get("route")
        planned_model = route.get("model_id") if isinstance(route, Mapping) else None
        planned_effort = route.get("reasoning_effort") if isinstance(route, Mapping) else None
        actual_model = turn.get("model") if isinstance(turn, Mapping) else None
        actual_effort = turn.get("reasoning_effort") if isinstance(turn, Mapping) else None
        usage = turn.get("usage") if isinstance(turn, Mapping) else None
        model_usage = turn.get("model_usage") if isinstance(turn, Mapping) else None
        if not isinstance(model_usage, list) and actual_model is not None and isinstance(usage, Mapping):
            model_usage = [
                {
                    "model": actual_model,
                    "reasoning_effort": actual_effort,
                    "usage": usage,
                    "source": "normalized_turn",
                }
            ]
        if isinstance(usage, Mapping) and all(
            isinstance(usage.get(field), int) and usage.get(field) >= 0
            for field in _USAGE_FIELDS
        ):
            usage_records += 1
            for field in _USAGE_FIELDS:
                token_totals[field] += int(usage[field])
        if isinstance(session, Mapping):
            matched += 1
        if item["join_status"] == "matched":
            matched_turns += 1
        actual_cost = estimate_model_usage_cost(model_usage, pricing_catalog)
        projected_cost = estimate_cost(usage if isinstance(usage, Mapping) else None, planned_model, pricing_catalog)
        relative_actual = estimate_relative_cost(model_usage, pricing_catalog)
        projected_usage_entry = (
            [{"model": planned_model, "usage": usage}]
            if planned_model is not None and isinstance(usage, Mapping)
            else None
        )
        relative_projected = estimate_relative_cost(projected_usage_entry, pricing_catalog)
        relative_delta = (
            round(relative_actual - relative_projected, 8)
            if relative_actual is not None and relative_projected is not None
            else None
        )
        delta = (
            round(actual_cost - projected_cost, 8)
            if actual_cost is not None and projected_cost is not None
            else None
        )
        if actual_cost is not None and projected_cost is not None:
            paired_costs += 1
            actual_cost_total += Decimal(str(actual_cost))
            projected_cost_total += Decimal(str(projected_cost))
        if relative_actual is not None and relative_projected is not None:
            paired_relative_costs += 1
            relative_actual_total += Decimal(str(relative_actual))
            relative_projected_total += Decimal(str(relative_projected))
        agreement, compared, agreed = _agreement(
            observation.get("assessment"),
            turn.get("retrospective_assessment") if isinstance(turn, Mapping) else None,
        )
        compared_total += compared
        agreed_total += agreed
        actual_models = sorted(
            {
                str(entry.get("model"))
                for entry in model_usage
                if isinstance(entry, Mapping) and entry.get("model") is not None
            }
        ) if isinstance(model_usage, list) else []
        model_agreement = (
            all(model == planned_model for model in actual_models)
            if actual_models and planned_model is not None
            else None
        )
        effort_agreement = (
            actual_effort == planned_effort
            if actual_effort is not None and planned_effort is not None
            else None
        )
        status = (
            "unknown"
            if item["join_status"] != "matched" or model_agreement is None
            else "healthy"
            if model_agreement and (effort_agreement is not False)
            else "route_mismatch"
        )
        health[status] += 1
        records.append(
            {
                "correlation_id": item["correlation_id"],
                "policy_fingerprint": observation.get("policy_fingerprint"),
                "join_status": item["join_status"],
                "planned": {
                    "model": planned_model,
                    "reasoning_effort": planned_effort,
                },
                "actual": {
                    "session_id": session.get("session_id") if isinstance(session, Mapping) else None,
                    "model": actual_model,
                    "models": actual_models,
                    "reasoning_effort": actual_effort,
                    "usage": usage,
                    "model_usage": model_usage,
                },
                "cost": {
                    "actual_estimated": actual_cost,
                    "projected_routed_model": projected_cost,
                    "delta_actual_minus_projected": delta,
                    "estimated_savings": delta,
                    "relative_actual_units": relative_actual,
                    "relative_projected_units": relative_projected,
                    "relative_delta_actual_minus_projected": relative_delta,
                    "relative_direction": (
                        "premium" if relative_delta is not None and relative_delta > 0
                        else "savings" if relative_delta is not None and relative_delta < 0
                        else "equal" if relative_delta == 0
                        else "unknown"
                    ),
                },
                "routing_health": status,
                "model_agreement": model_agreement,
                "reasoning_effort_agreement": effort_agreement,
                "classification_field_agreement": agreement,
            }
        )

    total = len(joined)
    fingerprints = sorted(
        {str(item.get("policy_fingerprint")) for item in observations if item.get("policy_fingerprint") is not None}
    )
    actual_total = float(actual_cost_total.quantize(Decimal("0.00000001"))) if paired_costs else None
    projected_total = float(projected_cost_total.quantize(Decimal("0.00000001"))) if paired_costs else None
    savings_total = (
        round(actual_total - projected_total, 8)
        if actual_total is not None and projected_total is not None
        else None
    )
    relative_actual_value = float(relative_actual_total.quantize(Decimal("0.00000001"))) if paired_relative_costs else None
    relative_projected_value = float(relative_projected_total.quantize(Decimal("0.00000001"))) if paired_relative_costs else None
    relative_delta_value = (
        round(relative_actual_value - relative_projected_value, 8)
        if relative_actual_value is not None and relative_projected_value is not None
        else None
    )
    report: dict[str, object] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": _timestamp(generated_at, "generated_at"),
        "policy": {
            "fingerprints": fingerprints,
            "mixed_policy": len(fingerprints) > 1,
        },
        "pricing": {
            "schema_version": pricing_catalog.get("schema_version"),
            "catalog_version": pricing_catalog.get("catalog_version"),
            "effective_at": pricing_catalog.get("effective_at"),
            "source": pricing_catalog.get("source"),
            "fingerprint": pricing_catalog.get("fingerprint"),
            "currency": pricing_catalog.get("currency"),
            "unit": pricing_catalog.get("unit"),
        },
        "assumptions": [
            "All prices are catalog rates per one million tokens.",
            "Cached input is subtracted from input before applying the uncached input rate.",
            "Reasoning tokens are reported for transparency and are not charged again beyond output tokens.",
            "Projected routed-model cost reuses the actual session token counts.",
            "Missing tokens, models, prices, or unambiguous correlations remain null.",
        ],
        "coverage": {
            "observations": total,
            "matched_sessions": matched,
            "session_ratio": round(matched / total, 6) if total else None,
            "matched_turns": matched_turns,
            "turn_ratio": round(matched_turns / total, 6) if total else None,
            "usage_records": usage_records,
            "usage_ratio": round(usage_records / total, 6) if total else None,
            "paired_cost_records": paired_costs,
            "cost_ratio": round(paired_costs / total, 6) if total else None,
        },
        "routing_health": {
            "healthy": health["healthy"],
            "route_mismatch": health["route_mismatch"],
            "unknown": health["unknown"],
        },
        "classification_field_agreement": {
            "agreed": agreed_total,
            "compared": compared_total,
            "ratio": round(agreed_total / compared_total, 6) if compared_total else None,
        },
        "cost_totals": {
            "actual_estimated": actual_total,
            "projected_routed_model": projected_total,
            "delta_actual_minus_projected": savings_total,
            "estimated_savings": savings_total,
            "relative_actual_units": relative_actual_value,
            "relative_projected_units": relative_projected_value,
            "relative_delta_actual_minus_projected": relative_delta_value,
            "relative_direction": (
                "premium" if relative_delta_value is not None and relative_delta_value > 0
                else "savings" if relative_delta_value is not None and relative_delta_value < 0
                else "equal" if relative_delta_value == 0
                else "unknown"
            ),
        },
        "usage_totals": {
            "records_with_usage": usage_records,
            "actual": token_totals if usage_records else None,
            "projected_routed_model": token_totals if usage_records else None,
            "estimated_token_delta": 0 if usage_records else None,
            "assumption": "Projected usage holds the measured token mix constant so model-price effects can be isolated; actual routed token behavior remains unknown until guarded execution.",
        },
        "records": records,
    }
    _privacy_check(report, "report")
    return report


def _markdown(report: Mapping[str, object]) -> str:
    coverage = report["coverage"]
    health = report["routing_health"]
    costs = report["cost_totals"]
    usage = report["usage_totals"]
    agreement = report["classification_field_agreement"]
    policy = report["policy"]
    assert all(isinstance(item, Mapping) for item in (coverage, health, costs, usage, agreement, policy))

    def display(value: object) -> str:
        return "unknown" if value is None else str(value)

    lines = [
        "# Adaptive Routing Observation Report",
        "",
        f"Generated: {report['generated_at']}",
        f"Mixed policy: {str(policy['mixed_policy']).lower()}",
        "",
        "## Coverage",
        "",
        f"- Observations: {coverage['observations']}",
        f"- Matched sessions: {coverage['matched_sessions']}",
        f"- Session coverage: {display(coverage['session_ratio'])}",
        f"- Matched turns: {coverage['matched_turns']}",
        f"- Turn coverage: {display(coverage['turn_ratio'])}",
        f"- Usage coverage: {display(coverage['usage_ratio'])}",
        f"- Cost coverage: {display(coverage['cost_ratio'])}",
        "",
        "## Routing health",
        "",
        f"- Healthy: {health['healthy']}",
        f"- Route mismatch: {health['route_mismatch']}",
        f"- Unknown: {health['unknown']}",
        "",
        "## Estimated cost",
        "",
        f"- Actual: {display(costs['actual_estimated'])}",
        f"- Projected routed model: {display(costs['projected_routed_model'])}",
        f"- Estimated savings: {display(costs['estimated_savings'])}",
        "",
        "## Measured and projected usage",
        "",
        f"- Actual measured tokens: {display(usage['actual'])}",
        f"- Projected routed-model tokens: {display(usage['projected_routed_model'])}",
        f"- Estimated token delta: {display(usage['estimated_token_delta'])}",
        f"- Assumption: {usage['assumption']}",
        "",
        "## Classification agreement",
        "",
        f"- Agreed fields: {agreement['agreed']}",
        f"- Compared fields: {agreement['compared']}",
        f"- Agreement ratio: {display(agreement['ratio'])}",
        "",
        "## Estimation assumptions",
        "",
    ]
    lines.extend(f"- {assumption}" for assumption in report["assumptions"])
    lines.extend(
        [
            "",
            "## Records",
            "",
            "| Correlation | Join | Planned | Actual | Health | Actual cost | Projected cost | Savings |",
            "| --- | --- | --- | --- | --- | ---: | ---: | ---: |",
        ]
    )
    for record in report["records"]:
        assert isinstance(record, Mapping)
        planned = record["planned"]
        actual = record["actual"]
        cost = record["cost"]
        assert isinstance(planned, Mapping) and isinstance(actual, Mapping) and isinstance(cost, Mapping)
        lines.append(
            "| {correlation} | {join} | {planned} | {actual} | {health} | {actual_cost} | {projected} | {savings} |".format(
                correlation=record["correlation_id"],
                join=record["join_status"],
                planned=display(planned["model"]),
                actual=display(actual["model"]),
                health=record["routing_health"],
                actual_cost=display(cost["actual_estimated"]),
                projected=display(cost["projected_routed_model"]),
                savings=display(cost["estimated_savings"]),
            )
        )
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_observation_report(
    output_root: str | Path,
    report: Mapping[str, object],
) -> dict[str, Path]:
    """Write deterministic JSON and Markdown into a UTC timestamped run directory."""
    _privacy_check(report, "report")
    generated = _timestamp(str(report.get("generated_at")), "generated_at")
    run_name = str(report.get("run_id") or "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{7,127}", run_name):
        run_name = datetime.fromisoformat(generated.replace("Z", "+00:00")).strftime(
            "%Y%m%dT%H%M%SZ"
        )
    run_dir = Path(output_root) / run_name
    json_path = run_dir / "report.json"
    markdown_path = run_dir / "report.md"
    _atomic_write(
        json_path,
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
    )
    _atomic_write(markdown_path, _markdown(report))
    return {"run_dir": run_dir, "json": json_path, "markdown": markdown_path}


# Friendly aliases for callers that use report-oriented naming.
generate_observation_report = build_observation_report
write_report_artifacts = write_observation_report
