"""Guarded append-only Notion projection for adaptive observation reports."""

from __future__ import annotations

import json
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Mapping
import urllib.error
import urllib.request


NOTION_VERSION = "2022-06-28"
TOKEN_ENV_NAMES = ("GENOMES_NOTION_PAT", "GENOMES_NOTION_CONNECTOR")


class ObservationProjectionError(RuntimeError):
    """Raised when a guarded projection cannot be proven safe."""


def _compact(value: object) -> str:
    return str(value or "").replace("-", "").strip()


def _token() -> str:
    for name in TOKEN_ENV_NAMES:
        value = os.environ.get(name)
        if value:
            return value
    shell = os.environ.get("SHELL") or "/bin/zsh"
    code = (
        "import json, os\n"
        f"print(json.dumps({{name: os.environ.get(name, '') for name in {TOKEN_ENV_NAMES!r}}}))\n"
    )
    process = subprocess.run(
        [shell, "-lc", f"{sys.executable} - <<'PY'\n{code}PY"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if process.returncode == 0:
        try:
            values = json.loads(process.stdout)
        except json.JSONDecodeError:
            values = {}
        for name in TOKEN_ENV_NAMES:
            if values.get(name):
                return str(values[name])
    raise ObservationProjectionError("Genome's Notion credential is unavailable")


class NotionClient:
    def __init__(self, token: str, *, retries: int = 3, timeout: float = 30.0) -> None:
        self.token = token
        self.retries = retries
        self.timeout = timeout

    def request(self, method: str, path: str, body: Mapping[str, object] | None = None) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            f"https://api.notion.com/v1{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            },
        )
        last_error = ""
        attempts = 1 if method == "POST" and path == "/pages" else self.retries
        for attempt in range(1, attempts + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode("utf-8")
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode("utf-8", errors="replace")
                if exc.code != 429 and not 500 <= exc.code < 600:
                    raise ObservationProjectionError(
                        f"Notion request failed with HTTP {exc.code}"
                    ) from exc
                last_error = f"HTTP {exc.code}"
            except urllib.error.URLError as exc:
                last_error = type(exc.reason).__name__
            time.sleep(min(2**attempt, 8))
        raise ObservationProjectionError(f"Notion request exhausted retries: {last_error}")


def _title(page: Mapping[str, object]) -> str:
    properties = page.get("properties")
    if not isinstance(properties, Mapping):
        return ""
    for raw in properties.values():
        if not isinstance(raw, Mapping) or raw.get("type") != "title":
            continue
        title = raw.get("title")
        if isinstance(title, list):
            return "".join(
                str(part.get("plain_text") or "")
                for part in title
                if isinstance(part, Mapping)
            )
    return ""


def _workspace_name(me: Mapping[str, object]) -> str:
    bot = me.get("bot")
    if isinstance(bot, Mapping):
        for key in ("workspace_name", "workspace"):
            value = bot.get(key)
            if isinstance(value, str):
                return value
    return ""


def verify_destination(client: NotionClient, notion: Mapping[str, object]) -> dict[str, str]:
    expected = str(notion.get("workspace_expected") or "")
    if expected != "Genome's Notion":
        raise ObservationProjectionError("configured workspace must be Genome's Notion")
    parent_id = _compact(notion.get("parent_page_id"))
    database_id = _compact(notion.get("database_id"))
    if not parent_id or not database_id:
        raise ObservationProjectionError("Notion parent and database IDs are required")
    me = client.request("GET", "/users/me")
    actual = _workspace_name(me)
    if actual != expected:
        raise ObservationProjectionError("Notion workspace verification failed")
    database = client.request("GET", f"/databases/{database_id}")
    parent = database.get("parent")
    if not isinstance(parent, Mapping) or parent.get("type") != "page_id":
        raise ObservationProjectionError("report database has an unexpected parent type")
    if _compact(parent.get("page_id")) != parent_id:
        raise ObservationProjectionError("report database is not under the configured router page")
    parent_page = client.request("GET", f"/pages/{parent_id}")
    if "Adaptive Model" not in _title(parent_page):
        raise ObservationProjectionError("configured parent is not the adaptive router page")
    return {"workspace": actual or expected, "database_id": database_id, "parent_id": parent_id}


def _rich(text: str) -> list[dict[str, object]]:
    return [{"type": "text", "text": {"content": text[:2000]}}]


def _paragraph(text: str) -> dict[str, object]:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rich(text)}}


def _heading(text: str) -> dict[str, object]:
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": _rich(text), "color": "blue"}}


def _number(value: object) -> dict[str, object] | None:
    return {"number": float(value)} if isinstance(value, (int, float)) else None


def routing_health(report: Mapping[str, object]) -> str:
    coverage = report.get("coverage")
    if not isinstance(coverage, Mapping):
        return "no_data"
    observations = int(coverage.get("observations") or 0)
    matched = int(coverage.get("matched_turns") or 0)
    if observations == 0:
        return "no_data"
    if matched == 0:
        return "not_working"
    return "working" if matched == observations else "degraded"


def _append_report_entry_unlocked(
    report: Mapping[str, object],
    *,
    notion: Mapping[str, object],
    run_id: str,
    window_start: str,
    window_end: str,
    receipt_path: str | Path | None = None,
    client: NotionClient | None = None,
) -> dict[str, object]:
    """Idempotently append one aggregate report page and verify readback."""
    if notion.get("append_only") is not True:
        raise ObservationProjectionError("Notion projection must be append-only")
    client = client or NotionClient(_token())
    verified = verify_destination(client, notion)
    database_id = verified["database_id"]
    existing = client.request(
        "POST",
        f"/databases/{database_id}/query",
        {"filter": {"property": "Run ID", "rich_text": {"equals": run_id}}, "page_size": 2},
    )
    results = existing.get("results")
    if isinstance(results, list) and results:
        page_id = str(results[0].get("id") or "")
        result: dict[str, object] = {
            "status": "already_projected",
            "run_id": run_id,
            "page_id": page_id,
            "workspace": verified["workspace"],
        }
    else:
        coverage = report.get("coverage") if isinstance(report.get("coverage"), Mapping) else {}
        agreement = report.get("classification_field_agreement") if isinstance(report.get("classification_field_agreement"), Mapping) else {}
        costs = report.get("cost_totals") if isinstance(report.get("cost_totals"), Mapping) else {}
        usage = report.get("usage_totals") if isinstance(report.get("usage_totals"), Mapping) else {}
        actual_usage = usage.get("actual") if isinstance(usage.get("actual"), Mapping) else {}
        projected_usage = usage.get("projected_routed_model") if isinstance(usage.get("projected_routed_model"), Mapping) else {}
        policy = report.get("policy") if isinstance(report.get("policy"), Mapping) else {}
        health = routing_health(report)
        properties: dict[str, object] = {
            "Report": {"title": _rich(f"Adaptive routing observation — {window_end}")},
            "Window": {"date": {"start": window_start, "end": window_end}},
            "Routing Health": {"select": {"name": health}},
            "Run ID": {"rich_text": _rich(run_id)},
            "Policy Fingerprints": {"rich_text": _rich(", ".join(str(x) for x in policy.get("fingerprints", [])))},
            "Generated": {"date": {"start": str(report.get("generated_at") or window_end)}},
            "Observations": _number(coverage.get("observations")),
            "Matched Sessions": _number(coverage.get("matched_sessions")),
            "Classification Accuracy": _number(agreement.get("ratio")),
            "Usage Coverage": _number(coverage.get("usage_ratio")),
            "Actual Cost": _number(costs.get("actual_estimated")),
            "Projected Routed Cost": _number(costs.get("projected_routed_model")),
            "Estimated Savings": _number(costs.get("estimated_savings")),
            "Relative Direction": {"select": {"name": str(costs.get("relative_direction") or "unknown")}},
            "Actual Tokens": _number(actual_usage.get("total_tokens")),
            "Projected Tokens": _number(projected_usage.get("total_tokens")),
        }
        properties = {key: value for key, value in properties.items() if value is not None}
        assumptions = report.get("assumptions") if isinstance(report.get("assumptions"), list) else []
        children = [
            _heading("Is routing working?"),
            _paragraph(
                f"{health}. {coverage.get('matched_turns', 0)} of {coverage.get('observations', 0)} observed routes matched an exact Codex turn; {coverage.get('matched_sessions', 0)} matched a session."
            ),
            _heading("Is classification acceptable?"),
            _paragraph(
                "Classification agreement is "
                + ("unknown because comparable evidence is incomplete." if agreement.get("ratio") is None else f"{float(agreement['ratio']):.1%} across {agreement.get('compared', 0)} compared fields.")
            ),
            _heading("What would usage and cost have been?"),
            _paragraph(
                "Actual estimated cost: {actual}; projected routed-model cost: {projected}; estimated savings: {savings}. Unknown means required token or trusted pricing evidence was unavailable.".format(
                    actual=costs.get("actual_estimated"),
                    projected=costs.get("projected_routed_model"),
                    savings=costs.get("estimated_savings"),
                )
            ),
            _paragraph(
                "Measured tokens: {actual}; projected routed-model tokens: {projected}; estimated token delta: {delta}. {assumption}".format(
                    actual=actual_usage.get("total_tokens"),
                    projected=projected_usage.get("total_tokens"),
                    delta=usage.get("estimated_token_delta"),
                    assumption=usage.get("assumption"),
                )
            ),
            _paragraph(
                "Normalized relative-cost direction: {direction}; actual units: {actual}; projected units: {projected}; delta actual minus projected: {delta}. These are catalog index units, not dollars.".format(
                    direction=costs.get("relative_direction"),
                    actual=costs.get("relative_actual_units"),
                    projected=costs.get("relative_projected_units"),
                    delta=costs.get("relative_delta_actual_minus_projected"),
                )
            ),
            _heading("Evidence and assumptions"),
            *[_paragraph(str(item)) for item in assumptions[:20]],
        ]
        created = client.request(
            "POST",
            "/pages",
            {"parent": {"database_id": database_id}, "properties": properties, "children": children},
        )
        page_id = str(created.get("id") or "")
        if not page_id:
            raise ObservationProjectionError("Notion create returned no page ID")
        readback = client.request("GET", f"/pages/{_compact(page_id)}")
        if _compact(readback.get("id")) != _compact(page_id):
            raise ObservationProjectionError("Notion report readback failed")
        result = {
            "status": "projected",
            "run_id": run_id,
            "page_id": page_id,
            "url": created.get("url"),
            "workspace": verified["workspace"],
        }
    if receipt_path is not None:
        target = Path(receipt_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def append_report_entry(
    report: Mapping[str, object],
    *,
    notion: Mapping[str, object],
    run_id: str,
    window_start: str,
    window_end: str,
    receipt_path: str | Path | None = None,
    client: NotionClient | None = None,
) -> dict[str, object]:
    """Serialize local query/create operations so one host cannot race itself."""
    receipt = Path(receipt_path) if receipt_path is not None else Path.home() / ".local/state/agentic-os/adaptive-routing/notion-projection.json"
    lock_path = receipt.parent / ".notion-projection.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            return _append_report_entry_unlocked(
                report,
                notion=notion,
                run_id=run_id,
                window_start=window_start,
                window_end=window_end,
                receipt_path=receipt_path,
                client=client,
            )
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
