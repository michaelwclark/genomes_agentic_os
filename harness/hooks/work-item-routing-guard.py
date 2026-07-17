#!/usr/bin/env python3
"""Guard against misfiling Agentic OS lifecycle work-items into a code repo's `.features/`.

PostToolUse hook. When an agent writes a lifecycle/handoff packet (PROMPT-PACK,
WORKLOG, JIRA, PR, QA_HANDOFF, review packet, etc.) into a `.features/<ticket>/`
directory that lives *inside a linked code repository* (i.e. outside the OS root),
this hook nudges the agent to relocate it to the canonical OS work item at
`<domain>/02-projects/<project>/work-items/02-active/<slug>/`.

It never blocks or fails a tool call (always exits 0). It stays silent for
disposable raw evidence (watcher state, logs, screenshots) so that legitimate
in-repo `.features/` usage is left alone -- only packet-shaped filenames trigger
the advisory.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any


OS_ROOT = (Path.home() / "agentic_os").resolve()

# Tool calls that write files, across Claude and Codex harnesses.
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "apply_patch"}

# Lifecycle / handoff packet filenames whose canonical home is the OS work item.
# Kept deliberately narrow so disposable raw evidence in `.features/` is untouched.
PACKET_BASENAMES = {
    "prompt-pack.md",
    "worklog.md",
    "jira.md",
    "pr.md",
    "qa_handoff.md",
    "qa-handoff.md",
    "spec.md",
    "plan.md",
    "implementation-plan.md",
    "decisions.md",
    "next.md",
    "handoff.md",
    "review.md",
    "outcome-brief.md",
    "dispatch-handoff.md",
}
PACKET_SUFFIX_HINTS = ("-review.md", "-handoff.md", "-packet.md", "-prompt-pack.md")


def read_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def emit(context: str = "") -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": context}}))


def target_path(payload: dict[str, Any]) -> Path | None:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "path", "notebook_path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            try:
                return Path(value).expanduser()
            except (ValueError, OSError):
                return None
    return None


def is_packet(path: Path) -> bool:
    name = path.name.lower()
    if name in PACKET_BASENAMES:
        return True
    return any(name.endswith(hint) for hint in PACKET_SUFFIX_HINTS)


def features_repo_root(path: Path) -> Path | None:
    """Return the repo root holding a `.features/` segment, or None.

    Only matches when `.features` is a real path segment and the location is
    OUTSIDE the OS root (i.e. inside a linked code clone / worktree).
    """
    parts = path.parts
    if ".features" not in parts:
        return None
    idx = parts.index(".features")
    repo_root = Path(*parts[:idx]) if idx else None
    if repo_root is None:
        return None
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError):
        resolved = path
    # Leave the OS root's own trees alone; only guard external code repos.
    if str(resolved).startswith(str(OS_ROOT)):
        return None
    return repo_root


def canonical_destination(repo_root: Path) -> str | None:
    """Best-effort map a linked repo root to its OS work-items destination.

    Scans `<OS_ROOT>/*/02-projects/*/project.yml` for a `repo:` entry matching
    the code repo root. Returns the canonical `work-items/02-active/` path if a
    single project owns the repo, else None. Pure stdlib, no YAML dependency.
    """
    if not OS_ROOT.is_dir():
        return None
    needle = str(repo_root)
    try:
        candidates = list(OS_ROOT.glob("*/02-projects/*/project.yml"))
    except OSError:
        return None
    for cfg in candidates:
        try:
            text = cfg.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if needle in text:
            room = cfg.parent
            return str(room / "work-items" / "02-active")
    return None


def main() -> int:
    try:
        payload = read_payload()
        if payload.get("tool_name") not in WRITE_TOOLS:
            emit()
            return 0
        path = target_path(payload)
        if path is None or not is_packet(path):
            emit()
            return 0
        repo_root = features_repo_root(path)
        if repo_root is None:
            emit()
            return 0

        dest = canonical_destination(repo_root)
        if dest:
            where = f"`{dest}/<index>_<slug>/`"
        else:
            where = (
                "the OS work item at "
                "`<domain>/02-projects/<project>/work-items/02-active/<index>_<slug>/` "
                "(resolve it with `agentic-os doc-config plan --root ~/agentic_os "
                "--domain <domain> --project <project> --work-item <slug>`)"
            )
        context = (
            f"[work-item-routing-guard] You wrote a lifecycle/handoff packet "
            f"(`{path.name}`) into a code repo's `.features/` directory "
            f"(`{repo_root}`). In Agentic OS the code-repo `.features/` is a "
            f"disposable mirror only -- it is NOT the source of truth. The "
            f"canonical location for this packet is {where}. Relocate the packet "
            f"there (and keep only disposable raw evidence, e.g. watcher state or "
            f"logs, in `.features/`)."
        )
        emit(context)
        return 0
    except Exception:  # never break the tool call
        try:
            emit()
        except Exception:
            pass
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
