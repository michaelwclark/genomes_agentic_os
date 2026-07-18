"""Configurable names for durable Agentic OS entities.

The date prefix is intentionally limited to top-level durable entity names.
Stable files inside those entities (``work.yml``, ``run-log.md``, and similar)
keep their contract names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
import re
from typing import Any, Mapping

import yaml


CONFIG_RELATIVE_PATH = Path("harness") / "config" / "artifact-naming.yml"
DEFAULT_DATE_FORMAT = "%m%d%y"
DEFAULT_SEPARATOR = "-"
DEFAULT_SCOPES = {
    "work_items": True,
    "worktrees": True,
    "conversation_logs": True,
    "async_runs": True,
    "run_logs": True,
    "report_runs": True,
    "development_runs": True,
    "thread_closeouts": True,
}


@dataclass(frozen=True)
class ArtifactNamingPolicy:
    enabled: bool = True
    date_format: str = DEFAULT_DATE_FORMAT
    separator: str = DEFAULT_SEPARATOR
    scopes: Mapping[str, bool] = field(default_factory=lambda: dict(DEFAULT_SCOPES))

    def enabled_for(self, scope: str) -> bool:
        return self.enabled and bool(self.scopes.get(scope, False))

    def prefix_for(self, value: datetime | date) -> str:
        if isinstance(value, datetime):
            value = value.astimezone(timezone.utc)
        return value.strftime(self.date_format)


def default_artifact_naming_config() -> dict[str, Any]:
    return {
        "artifact_naming": {
            "date_prefix": {
                "enabled": True,
                "format": DEFAULT_DATE_FORMAT,
                "separator": DEFAULT_SEPARATOR,
                "scopes": dict(DEFAULT_SCOPES),
            }
        }
    }


def render_default_artifact_naming_config() -> str:
    return yaml.safe_dump(default_artifact_naming_config(), sort_keys=False)


def _validate_format(value: str) -> str:
    try:
        sample = datetime(2026, 7, 18, tzinfo=timezone.utc).strftime(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid artifact date format: {value!r}") from exc
    if not sample or re.search(r"[^A-Za-z0-9]", sample):
        raise ValueError("artifact date format must render only letters and digits")
    return value


def load_artifact_naming_policy(root: str | Path) -> ArtifactNamingPolicy:
    path = Path(root).expanduser().resolve() / CONFIG_RELATIVE_PATH
    data: dict[str, Any] = {}
    if path.is_file():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"artifact naming config must be a mapping: {path}")
        data = loaded
    artifact_naming = data.get("artifact_naming", {})
    if not isinstance(artifact_naming, dict):
        raise ValueError(f"artifact_naming must be a mapping: {path}")
    date_prefix = artifact_naming.get("date_prefix", {})
    if not isinstance(date_prefix, dict):
        raise ValueError(f"artifact_naming.date_prefix must be a mapping: {path}")
    scopes = dict(DEFAULT_SCOPES)
    configured_scopes = date_prefix.get("scopes", {})
    if configured_scopes:
        if not isinstance(configured_scopes, dict):
            raise ValueError(f"artifact_naming.date_prefix.scopes must be a mapping: {path}")
        unknown = sorted(set(configured_scopes) - set(DEFAULT_SCOPES))
        if unknown:
            raise ValueError(f"unknown artifact naming scopes: {', '.join(unknown)}")
        invalid = sorted(str(key) for key, value in configured_scopes.items() if not isinstance(value, bool))
        if invalid:
            raise ValueError(f"artifact naming scopes must be booleans: {', '.join(invalid)}")
        scopes.update({str(key): value for key, value in configured_scopes.items()})
    separator = str(date_prefix.get("separator", DEFAULT_SEPARATOR))
    if separator not in {"-", "_"}:
        raise ValueError("artifact date prefix separator must be '-' or '_'")
    enabled = date_prefix.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("artifact_naming.date_prefix.enabled must be a boolean")
    return ArtifactNamingPolicy(
        enabled=enabled,
        date_format=_validate_format(str(date_prefix.get("format", DEFAULT_DATE_FORMAT))),
        separator=separator,
        scopes=scopes,
    )


def parse_timestamp(value: Any, *, fallback: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, date):
        result = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    elif value:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            result = datetime.fromisoformat(text)
        except ValueError:
            result = fallback or datetime.now(timezone.utc)
    else:
        result = fallback or datetime.now(timezone.utc)
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def filesystem_timestamp(path: Path) -> datetime:
    stat = path.lstat() if path.is_symlink() else path.stat()
    epoch = getattr(stat, "st_birthtime", None)
    return datetime.fromtimestamp(epoch if epoch is not None else stat.st_ctime, timezone.utc)


def split_date_prefix(name: str, policy: ArtifactNamingPolicy) -> tuple[str | None, str]:
    sample_length = len(policy.prefix_for(datetime(2026, 7, 18, tzinfo=timezone.utc)))
    if len(name) <= sample_length or name[sample_length : sample_length + len(policy.separator)] != policy.separator:
        return None, name
    candidate = name[:sample_length]
    try:
        datetime.strptime(candidate, policy.date_format)
    except ValueError:
        return None, name
    return candidate, name[sample_length + len(policy.separator) :]


def has_date_prefix(name: str, policy: ArtifactNamingPolicy) -> bool:
    prefix, _ = split_date_prefix(name, policy)
    return prefix is not None


def dated_name(
    name: str,
    *,
    when: datetime | date | str | None,
    policy: ArtifactNamingPolicy,
    scope: str,
    force: bool = False,
) -> str:
    if not policy.enabled_for(scope) or (not force and has_date_prefix(name, policy)):
        return name
    timestamp = parse_timestamp(when)
    return f"{policy.prefix_for(timestamp)}{policy.separator}{name}"


def legacy_date_from_name(name: str) -> datetime | None:
    """Extract dates from pre-policy run and conversation names."""
    candidates = (
        (r"^(\d{4}_\d{2}_\d{2})(?:_|-)", "%Y_%m_%d"),
        (r"^(\d{8})T\d{6}", "%Y%m%d"),
        (r"^[a-z0-9_-]+[-_](\d{8})t\d{6}", "%Y%m%d"),
    )
    for pattern, date_format in candidates:
        match = re.match(pattern, name, re.IGNORECASE)
        if match:
            return datetime.strptime(match.group(1), date_format).replace(tzinfo=timezone.utc)
    return None


def strip_legacy_date(name: str) -> str:
    """Keep uniqueness information while replacing legacy leading dates."""
    value = re.sub(r"^\d{4}_\d{2}_\d{2}[_-]", "", name)
    value = re.sub(r"^\d{8}T", "", value, flags=re.IGNORECASE)
    match = re.match(r"^([a-z0-9_-]+)[-_]\d{8}t(.+)$", value, re.IGNORECASE)
    if match:
        value = f"{match.group(1)}-{match.group(2)}"
    return value.lstrip("-_") or "artifact"
