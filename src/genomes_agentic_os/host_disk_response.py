"""Bounded, read-only investigation started by the off-box disk sentinel."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

# No log contents, process arguments, environment variables, or database reads.
# All commands are fixed; the SSH target is passed as an argv element by caller.
DISK_DIAGNOSTIC_SCRIPT = r"""
export LC_ALL=C
priv() { if sudo -n true 2>/dev/null; then sudo -n "$@"; else "$@"; fi; }
echo '[filesystem bytes and inodes]'
df -Pk /; df -Pi /
echo '[journal size]'
priv timeout 5s journalctl --disk-usage 2>/dev/null
echo '[root directory sizes: bounded 20 seconds, may be partial]'
priv timeout 20s ionice -c3 nice -n19 du -x -B1 --max-depth=1 / 2>/dev/null | sort -nr | head -20
echo '[log and docker directory sizes: bounded 15 seconds, may be partial]'
priv timeout 15s ionice -c3 nice -n19 du -x -B1 --max-depth=2 /var/log /var/lib/docker/containers 2>/dev/null | sort -nr | head -30
echo '[deleted but open files: no process arguments]'
priv timeout 5s lsof -nP +L1 -F pcsn 2>/dev/null | head -160
echo '[process names and resource usage]'
ps -eo pid=,comm=,%cpu=,%mem= --sort=-%cpu | head -20
echo '[container logging limits: only retention fields]'
ids=$(timeout 3s docker ps -aq 2>/dev/null | head -40)
if [ -n "$ids" ]; then
  timeout 5s docker inspect --format '{{.Name}} driver={{.HostConfig.LogConfig.Type}} max-size={{index .HostConfig.LogConfig.Config "max-size"}} max-file={{index .HostConfig.LogConfig.Config "max-file"}} path={{.LogPath}}' $ids 2>/dev/null
fi
echo '[no cleanup performed; requires an identified target and retention policy]'
true
""".strip()


def capture_disk_diagnostics(
    *, state_dir: Path, host: str, ssh_target: str, runner: Callable,
    connect_timeout: int, generated_at: str,
) -> dict[str, Any]:
    """Save at most 12 own reports, each bounded to 64 KiB of metadata output."""
    directory = state_dir / "diagnostics"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    outcome = runner(ssh_target, DISK_DIAGNOSTIC_SCRIPT, connect_timeout)
    receipt = {
        "generated_at": generated_at, "host": host,
        "status": "captured" if outcome.returncode == 0 and not outcome.timed_out else "capture_failed",
        "exit_code": outcome.returncode, "timed_out": outcome.timed_out,
        "cleanup_status": "requires_identified_target_and_retention_policy",
        "output": outcome.stdout[:65536], "output_truncated": len(outcome.stdout) > 65536,
        "error": outcome.stderr[:1000],
    }
    stamp = generated_at.replace(":", "").replace("-", "")
    path = directory / f"{host}-{stamp}.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(receipt, handle, indent=2)
        handle.write("\n")
    for old in sorted(directory.glob(f"{host}-*.json"), reverse=True)[12:]:
        old.unlink()
    return {k: v for k, v in {**receipt, "path": str(path)}.items() if k not in {"output", "error"}}
