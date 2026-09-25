#!/usr/bin/env python3
"""Reconcile the governed LOS security schedules into Execution Fabric."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


IDENTIFIER = re.compile(r"^[a-zA-Z0-9._:-]{1,128}$")


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _request(
    base: str,
    token: str,
    path: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(
        f"{base.rstrip('/')}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.load(response)
    except HTTPError as exc:
        summary = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"Execution Fabric returned HTTP {exc.code}: {summary}") from exc
    except URLError as exc:
        raise RuntimeError(f"Execution Fabric is unavailable: {exc.reason}") from exc


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schemaVersion") != "agentic-os-execution-fabric-schedule-manifest/v1":
        raise ValueError("unsupported LOS security schedule manifest")
    schedules = raw.get("schedules")
    if not isinstance(schedules, list) or not schedules:
        raise ValueError("LOS security schedule manifest must contain schedules")
    ids: set[str] = set()
    for schedule in schedules:
        schedule_id = str(schedule.get("id") or "")
        if not IDENTIFIER.fullmatch(schedule_id) or schedule_id in ids:
            raise ValueError(f"invalid or duplicate schedule id: {schedule_id}")
        ids.add(schedule_id)
        if schedule.get("queue") != "codex" or schedule.get("taskType") != "llm.codex":
            raise ValueError(f"schedule {schedule_id} must use the codex llm route")
        payload = schedule.get("payload")
        if not isinstance(payload, dict) or not payload.get("instruction_ref"):
            raise ValueError(f"schedule {schedule_id} requires an instruction_ref")
        for field in ("intervalSeconds", "initialDelaySeconds"):
            value = schedule.get(field)
            if not isinstance(value, int) or value < 1:
                raise ValueError(f"schedule {schedule_id} has invalid {field}")
    return schedules


def _plan(
    schedules: list[dict[str, Any]],
    existing: list[dict[str, Any]],
    now: datetime,
) -> list[dict[str, Any]]:
    existing_by_id = {str(item.get("id")): item for item in existing}
    planned: list[dict[str, Any]] = []
    for source in schedules:
        schedule = dict(source)
        schedule_id = str(schedule.pop("id"))
        initial_delay = int(schedule.pop("initialDelaySeconds"))
        current = existing_by_id.get(schedule_id) or {}
        next_occurrence = current.get("nextOccurrenceAt")
        if not isinstance(next_occurrence, str):
            next_occurrence = _iso(now + timedelta(seconds=initial_delay))
        schedule["nextOccurrenceAt"] = next_occurrence
        planned.append({"id": schedule_id, "body": schedule})
    return planned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--api-base", default=os.environ.get("FABRIC_API_BASE"))
    parser.add_argument(
        "--admin-token-file", default=os.environ.get("FABRIC_ADMIN_TOKEN_FILE")
    )
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args(argv)
    if not args.api_base or not args.admin_token_file:
        parser.error("--api-base and --admin-token-file are required")
    token_path = Path(args.admin_token_file).expanduser()
    token = token_path.read_text(encoding="utf-8").strip()
    if len(token) < 32 or any(char.isspace() for char in token):
        raise ValueError("admin token file must contain one scoped token")
    schedules = _load_manifest(args.manifest)
    snapshot = _request(
        args.api_base, token, "/api/v1/snapshots/schedules?limit=200"
    )
    plan = _plan(schedules, list(snapshot.get("schedules") or []), datetime.now(timezone.utc))
    if not args.apply:
        print(
            json.dumps(
                {
                    "status": "would-reconcile",
                    "schedule_ids": [item["id"] for item in plan],
                },
                indent=2,
            )
        )
        return 0
    for item in plan:
        _request(
            args.api_base,
            token,
            f"/api/v1/admin/schedules/{item['id']}",
            method="PUT",
            body=item["body"],
        )
    readback = _request(
        args.api_base, token, "/api/v1/snapshots/schedules?limit=200"
    )
    expected = {item["id"] for item in plan}
    observed = {
        str(item.get("id"))
        for item in list(readback.get("schedules") or [])
        if item.get("enabled") is True
    }
    missing = sorted(expected - observed)
    if missing:
        raise RuntimeError(f"schedule readback is missing: {', '.join(missing)}")
    print(
        json.dumps(
            {
                "status": "reconciled",
                "schedule_ids": sorted(expected),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
