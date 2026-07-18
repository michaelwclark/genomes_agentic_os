"""Health checks and additive repairs for installed Agentic OS roots."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .automation_ops import check_automation
from .config_ops import discover_config_tree_targets, doctor_config
from .customer import customer_update
from .event_graph import append_event, chain_doctor, utc_now, write_yaml
from .runtime_ops import runtime_doctor
from .scaffold import expand_path, init_os, install_docs, installed_domain_names
from .validate import lifecycle_staleness_findings, validate_root
from .workflow_ops import check_workflow

# Snapshot persisted to the shared-factory control plane alongside other
# runtime-state YAML files (event-graph.yml, chain-rules.yml, run-queue.yml).
# 50/50 decision: used shared_factory/00-control-plane/ rather than a new
# logs/doctor/ path because this is a small, single-file state record
# (not a log stream), and it co-locates with the other runtime control-plane
# state that event_graph.py already owns.
_DOCTOR_SNAPSHOT_FILE = Path("harness/shared_factory/00-control-plane/doctor-snapshot.yml")


@dataclass
class DoctorFinding:
    severity: str
    path: Path
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "path": str(self.path), "message": self.message}


def table_field(content: str, field: str) -> str:
    prefix = f"| {field} |"
    for line in content.splitlines():
        if line.startswith(prefix):
            cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
            if len(cells) >= 2:
                return cells[1]
    return ""


def managed_repair(root: Path) -> list[str]:
    if (root / "customer.yml").is_file():
        data = yaml.safe_load((root / "customer.yml").read_text(encoding="utf-8")) or {}
        slug = (data.get("customer") or {}).get("slug")
        if not slug:
            raise ValueError("customer.yml is missing customer.slug")
        customer_update(str(slug), root)
        return ["customer update"]
    # Repair additively against the operator's installed domain set; only a
    # tree with no domains at all falls back to the neutral defaults.
    init_os(root, domains=installed_domain_names(root) or None)
    install_docs(root)
    return ["init os", "install docs"]


def workflow_findings(root: Path) -> list[DoctorFinding]:
    findings = []
    workflows = {
        *root.glob("*/03-workflows/*/*/workflow.md"),
        *root.glob("domains/*/03-workflows/*/*/workflow.md"),
    }
    for workflow in sorted(workflows):
        domain = workflow.parents[3].name
        lane = workflow.parent.parent.name
        name = workflow.parent.name
        for finding in check_workflow(root, domain, lane, name):
            if finding.severity != "observation":
                findings.append(DoctorFinding(finding.severity, finding.path, f"workflow `{name}`: {finding.message}"))
    return findings


def automation_findings(root: Path) -> list[DoctorFinding]:
    findings = []
    automations = {
        *root.glob("*/04-automations/*/*/automation.md"),
        *root.glob("domains/*/04-automations/*/*/automation.md"),
    }
    for automation in sorted(automations):
        domain = automation.parents[3].name
        lane = automation.parent.parent.name
        name = automation.parent.name
        result = check_automation(root, domain, lane, name)
        for item in result["findings"]:
            if item["severity"] != "observation":
                findings.append(DoctorFinding(item["severity"], Path(item["path"]), f"automation `{name}`: {item['message']}"))
    return findings


def active_work_findings(root: Path) -> list[DoctorFinding]:
    findings = []
    active_work_files = {
        *root.glob("*/00-control-plane/active-work.md"),
        *root.glob("domains/*/00-control-plane/active-work.md"),
    }
    for active_work in sorted(active_work_files):
        for line in active_work.read_text(encoding="utf-8").splitlines():
            if line.startswith("| `") and ("Define next action" in line or "|  |" in line):
                findings.append(DoctorFinding("fix-soon", active_work, "active work row is missing a concrete next action"))
    return findings


def project_findings(root: Path) -> list[DoctorFinding]:
    findings = []
    project_dirs = {
        *root.glob("*/02-projects/*"),
        *root.glob("domains/*/02-projects/*"),
        *root.glob("domains/*/projects/*"),
    }
    for project_dir in sorted(project_dirs):
        if not project_dir.is_dir():
            continue
        for filename in ("project.yml", "status.md", "source-map.md"):
            path = project_dir / filename
            if not path.is_file():
                findings.append(DoctorFinding("blocker", path, f"project `{project_dir.name}` is missing {filename}"))
    return findings


def run_log_findings(root: Path) -> list[DoctorFinding]:
    findings = []
    run_logs = {
        *root.glob("*/06-runs-and-logs/runs/*/run-log.md"),
        *root.glob("domains/*/06-runs-and-logs/runs/*/run-log.md"),
    }
    for run_log in sorted(run_logs):
        content = run_log.read_text(encoding="utf-8")
        status = table_field(content, "Status")
        if status in {"", "running", "draft"} and "## Closeout" not in content:
            findings.append(DoctorFinding("fix-soon", run_log, "run log has no final status or closeout"))
    return findings


def lifecycle_findings(root: Path) -> list[DoctorFinding]:
    """Return DoctorFindings for plan-22 lifecycle staleness conditions."""
    return [
        DoctorFinding(f["severity"], Path(f["path"]), f["message"])
        for f in lifecycle_staleness_findings(root)
    ]


def doctor(root: str | Path, *, fix_missing: bool = False) -> dict[str, Any]:
    os_root = expand_path(root)
    repairs = managed_repair(os_root) if fix_missing else []
    validation = validate_root(os_root)
    findings: list[DoctorFinding] = []
    findings.extend(DoctorFinding("blocker", os_root, message) for message in validation.errors)
    findings.extend(DoctorFinding("cleanup", os_root, message) for message in validation.warnings)
    if validation.ok:
        findings.append(DoctorFinding("observation", os_root, "required files and folders are present"))
    findings.extend(active_work_findings(os_root))
    findings.extend(project_findings(os_root))
    findings.extend(workflow_findings(os_root))
    findings.extend(automation_findings(os_root))
    findings.extend(run_log_findings(os_root))
    findings.extend(lifecycle_findings(os_root))
    if repairs:
        findings.append(DoctorFinding("observation", os_root, f"additive repair executed: {', '.join(repairs)}"))
    return {"root": str(os_root), "ok": not any(f.severity == "blocker" for f in findings), "repairs": repairs, "findings": [f.as_dict() for f in findings]}


def _snapshot_path(os_root: Path) -> Path:
    """Absolute path to the doctor snapshot file for this install root."""
    return os_root / _DOCTOR_SNAPSHOT_FILE


def _build_snapshot(subsystems: dict[str, Any], timestamp: str) -> dict[str, Any]:
    """Compact summary of each subsystem's health state."""
    return {
        "schema_version": 1,
        "captured_at": timestamp,
        "subsystems": {
            name: {
                "ok": bool(result.get("ok", True)),
                "blocker_count": sum(
                    1 for f in (result.get("findings") or []) if f.get("severity") == "blocker"
                ),
            }
            for name, result in subsystems.items()
        },
    }


def _load_snapshot(os_root: Path) -> dict[str, Any] | None:
    """Return the previous snapshot dict, or None if none exists yet."""
    path = _snapshot_path(os_root)
    if not path.is_file():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else None


def _save_snapshot(os_root: Path, snapshot: dict[str, Any]) -> None:
    """Persist snapshot, overwriting any prior snapshot."""
    path = _snapshot_path(os_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml(path, snapshot)


def _detect_regressions(
    previous: dict[str, Any],
    current: dict[str, Any],
) -> list[dict[str, Any]]:
    """Compare previous and current snapshots; return per-subsystem regression dicts.

    A regression is either:
    - a subsystem that was ok=True and is now ok=False, OR
    - a subsystem whose blocker_count increased.
    """
    regressed: list[dict[str, Any]] = []
    prev_subs = previous.get("subsystems") or {}
    curr_subs = current.get("subsystems") or {}
    for name, curr_state in curr_subs.items():
        prev_state = prev_subs.get(name)
        if prev_state is None:
            # New subsystem, not seen before — not a regression
            continue
        was_ok = bool(prev_state.get("ok", True))
        is_ok = bool(curr_state.get("ok", True))
        prev_blockers = int(prev_state.get("blocker_count", 0))
        curr_blockers = int(curr_state.get("blocker_count", 0))
        if (was_ok and not is_ok) or curr_blockers > prev_blockers:
            regressed.append(
                {
                    "subsystem": name,
                    "was_ok": was_ok,
                    "is_ok": is_ok,
                    "prev_blocker_count": prev_blockers,
                    "curr_blocker_count": curr_blockers,
                }
            )
    return regressed


def _emit_regression_event(os_root: Path, regressions: list[dict[str, Any]]) -> dict[str, Any]:
    """Append one os.doctor.regression event to the event ledger.

    Payload carries regressed subsystems with old→new blocker counts.
    No secrets, no full findings dump.
    """
    subsystem_names = ", ".join(r["subsystem"] for r in regressions)
    return append_event(
        os_root,
        event_type="os.doctor.regression",
        source_ref=str(_snapshot_path(os_root)),
        summary=f"doctor --all detected regression in: {subsystem_names}.",
        payload_ref={
            "type": "inline",
            "regressions": regressions,
        },
    )


def doctor_all(root: str | Path) -> dict[str, Any]:
    """Aggregate every subsystem doctor into one health report (F-003).

    Subsystems checked:
      - core: structural + lifecycle (doctor())
      - runtime: execution targets, heartbeats, schedules, integrations
      - event_graph: chain rules
      - config: OTEL/MCP contracts per discovered config-tree target

    After each run:
      - A compact snapshot (per-subsystem ok + blocker_count) is persisted to
        harness/shared_factory/00-control-plane/doctor-snapshot.yml.
      - If a prior snapshot exists and this run shows a regression, exactly one
        os.doctor.regression event is appended to the event ledger.  No event is
        emitted on the first run (no baseline to compare against), on improvement,
        or when health is unchanged.

    Returns a dict with:
      ok              -- True only if every subsystem reports ok
      subsystems      -- per-subsystem result dicts (keyed by subsystem name)
      findings        -- flattened list of all findings across subsystems
      regression_event -- the emitted event dict, or None if no regression
    """
    os_root = expand_path(root)
    subsystems: dict[str, Any] = {}

    # Core doctor (structural + lifecycle)
    subsystems["core"] = doctor(os_root)

    # Runtime doctor
    try:
        subsystems["runtime"] = runtime_doctor(os_root)
    except Exception as exc:  # noqa: BLE001
        subsystems["runtime"] = {
            "ok": False,
            "findings": [{"severity": "blocker", "path": str(os_root), "message": f"runtime doctor error: {exc}"}],
        }

    # Event-graph chain doctor
    try:
        chain_result = chain_doctor(os_root)
        subsystems["event_graph"] = {"root": str(os_root), **chain_result}
    except Exception as exc:  # noqa: BLE001
        subsystems["event_graph"] = {
            "ok": False,
            "findings": [{"severity": "blocker", "path": str(os_root), "message": f"event_graph doctor error: {exc}"}],
        }

    # Config doctor — check each discovered config-tree target against its own
    # layer contract (same join as `config install-tree`); checking every known
    # layer against the root path would demand layer keys the root never holds.
    config_findings: list[dict[str, str]] = []
    config_ok = True
    try:
        config_targets = discover_config_tree_targets(os_root)
    except ValueError as exc:
        config_targets = []
        config_findings.append(
            {"severity": "blocker", "path": str(os_root), "message": f"config tree discovery failed: {exc}", "layer": "agentic_os_root"}
        )
        config_ok = False
    for target in config_targets:
        try:
            layer_result = doctor_config(target.root, layer=target.layer)
            for finding in layer_result.get("findings") or []:
                config_findings.append({**finding, "layer": target.layer})
            if not layer_result.get("ok", True):
                config_ok = False
        except Exception as exc:  # noqa: BLE001
            config_findings.append(
                {"severity": "blocker", "path": str(target.root), "message": f"config doctor error ({target.layer}): {exc}", "layer": target.layer}
            )
            config_ok = False
    subsystems["config"] = {"root": str(os_root), "ok": config_ok, "findings": config_findings}

    # Flatten findings for the top-level summary
    all_findings: list[dict[str, str]] = []
    for subsystem_name, result in subsystems.items():
        for finding in result.get("findings") or []:
            all_findings.append({**finding, "subsystem": subsystem_name})

    overall_ok = all(result.get("ok", True) for result in subsystems.values())

    # Snapshot persistence and regression detection
    previous_snapshot = _load_snapshot(os_root)
    timestamp = utc_now()
    current_snapshot = _build_snapshot(subsystems, timestamp)
    _save_snapshot(os_root, current_snapshot)

    regression_event: dict[str, Any] | None = None
    if previous_snapshot is not None:
        regressions = _detect_regressions(previous_snapshot, current_snapshot)
        if regressions:
            regression_event = _emit_regression_event(os_root, regressions)

    return {
        "root": str(os_root),
        "ok": overall_ok,
        "subsystems": subsystems,
        "findings": all_findings,
        "regression_event": regression_event,
    }


def format_doctor_result(result: dict[str, Any]) -> str:
    return yaml.safe_dump(result, sort_keys=False).strip()
