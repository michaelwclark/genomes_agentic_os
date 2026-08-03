"""Bounded inventory for a run-evidence filesystem root.

The scanner is read-only, does not follow symlinks, and emits compact aggregate
counts for migration sizing. It is intentionally reusable by the later import
preflight instead of leaving an ad-hoc one-off scan behind.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def inventory_run_evidence(
    evidence_root: Path,
    *,
    progress_path: Path | None = None,
    progress_every: int = 1000,
) -> dict[str, Any]:
    """Return file, byte, extension, and top-family aggregates for *evidence_root*."""
    root = evidence_root.resolve()
    if not root.is_dir():
        raise ValueError(f"run evidence root is not a directory: {root}")
    if progress_every < 1:
        raise ValueError("progress_every must be positive")

    started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    pending = [root]
    files = directories = bytes_total = errors = 0
    extensions: Counter[str] = Counter()
    families: dict[str, dict[str, Any]] = {}

    def emit_progress() -> None:
        if progress_path is None:
            return
        _atomic_json(
            progress_path,
            {
                "schema": "agentic-os-long-running-progress/v1",
                "operation": "run-evidence-inventory",
                "root": str(root),
                "status": "running",
                "phase": "scan",
                "items_total": 0,
                "items_completed": files + directories,
                "files_total": 0,
                "files_completed": files,
                "bytes_total": 0,
                "bytes_completed": bytes_total,
                "current_path": None,
                "errors": errors,
                "pending_directories": len(pending),
                "updated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "last_semantic_progress_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            },
        )

    while pending:
        directory = pending.pop()
        try:
            entries = os.scandir(directory)
        except OSError:
            errors += 1
            continue
        with entries:
            for entry in entries:
                try:
                    relative = Path(entry.path).relative_to(root)
                    family = relative.parts[0] if len(relative.parts) > 1 else "<root>"
                    aggregate = families.setdefault(
                        family,
                        {"files": 0, "directories": 0, "bytes": 0, "extensions": Counter()},
                    )
                    if entry.is_dir(follow_symlinks=False):
                        directories += 1
                        aggregate["directories"] += 1
                        pending.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        size = entry.stat(follow_symlinks=False).st_size
                        suffix = Path(entry.name).suffix.lower() or "<none>"
                        files += 1
                        bytes_total += size
                        extensions[suffix] += 1
                        aggregate["files"] += 1
                        aggregate["bytes"] += size
                        aggregate["extensions"][suffix] += 1
                except OSError:
                    errors += 1
                if (files + directories) % progress_every == 0:
                    emit_progress()

    completed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    result = {
        "schema": "run-evidence-inventory/v1",
        "root": str(root),
        "host_id": os.environ.get("AGENTIC_OS_HOST_ID", "bigmac"),
        "started_at": started_at,
        "completed_at": completed_at,
        "files": files,
        "directories": directories,
        "bytes": bytes_total,
        "errors": errors,
        "extensions": dict(sorted(extensions.items(), key=lambda item: (-item[1], item[0]))),
        "families": {
            key: {
                "files": value["files"],
                "directories": value["directories"],
                "bytes": value["bytes"],
                "extensions": dict(
                    sorted(value["extensions"].items(), key=lambda item: (-item[1], item[0]))
                ),
            }
            for key, value in sorted(families.items())
        },
    }
    emit_progress()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inventory one Agentic OS run-evidence filesystem root.")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--progress", type=Path)
    args = parser.parse_args(argv)
    result = inventory_run_evidence(args.root, progress_path=args.progress)
    _atomic_json(args.output, result)
    print(json.dumps({key: result[key] for key in ("files", "directories", "bytes", "errors")}))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the function contract
    raise SystemExit(main())
