"""Native npm-install closure capture and execution-time verification.

This stdlib-only file is executed directly with the qualified base Python's
isolated flags. Native check output, rather than a caller-declared snapshot,
binds the installed bytes to the actual passed npm-ci command.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import sys
from typing import Any


SCHEMA = "development-node-install-closure/v1"
SNAPSHOT = "node-install-closure.json"
LOCK = "node-validation.lock"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate Node authority key")
            value[key] = item
        return value
    value = json.loads(path.read_text(), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("Node authority must be a mapping")
    return value


def dependency_closure(worktree: Path) -> list[dict[str, Any]]:
    """Bind every entry, including modes and contained non-dangling symlinks."""
    root = worktree / "node_modules"
    if root.is_symlink() or not root.is_dir():
        raise ValueError("installed Node closure is absent or redirected")
    entries = []
    def visit(path: Path) -> None:
        before = path.lstat()
        row = {"path": str(path.relative_to(root)), "mode": stat.S_IMODE(before.st_mode)}
        if not stat.S_ISLNK(before.st_mode) and row["mode"] & 0o7022:
            raise ValueError("installed Node entry has unsafe writable or special mode")
        if stat.S_ISLNK(before.st_mode):
            # Symlink permissions are platform-defined; target permissions are
            # bound by their own closure entry. Never follow links while walking.
            target = path.resolve(strict=True)
            if target == root or not target.is_relative_to(root):
                raise ValueError("installed Node symlink escapes its closure")
            row.update(kind="symlink", target=os.readlink(path))
        elif stat.S_ISREG(before.st_mode):
            row.update(kind="file", sha256=_digest(path))
        elif stat.S_ISDIR(before.st_mode):
            row.update(kind="directory")
            for child in sorted(path.iterdir()):
                visit(child)
        else:
            raise ValueError("installed Node closure contains a special file")
        after = path.lstat()
        if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_mode) != (
                after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_mode):
            raise ValueError("installed Node closure changed while being hashed")
        entries.append(row)
    visit(root)
    for name in ("tsc", "playwright"):
        executable = root / ".bin" / name
        target = executable.resolve(strict=True)
        if not target.is_relative_to(root) or not target.is_file() or not target.stat().st_mode & 0o111:
            raise ValueError("required local Node executable is unqualified")
    return sorted(entries, key=lambda row: row["path"])


def guard_checks(install_run: Path, run: Path, worktree: Path, snapshot_sha: str | None = None) -> tuple[str, str]:
    """Derive exact approved helper/interpreter checks, never from request hashes."""
    helper = Path(__file__).resolve()
    interpreter = Path(sys._base_executable).resolve()
    checks = []
    for phase in ("preflight", "post-run"):
        operation = ("prepare" if phase == "preflight" else "capture") if run == install_run else "verify"
        argv = [str(interpreter), "-I", "-S", str(helper), operation,
                str(install_run), str(run), str(worktree), phase, snapshot_sha or "-"]
        # Both checks execute the exact declared bytes; a hash appearing in a
        # successful unrelated command is not executable provenance.
        bindings = " && ".join(shlex.join(["/usr/bin/shasum", "-a", "256", str(path)])
            + " | /usr/bin/awk " + shlex.quote('$1 == "' + _digest(path) + '" {ok=1} END {exit !ok}')
            for path in (interpreter, helper))
        checks.append(bindings + " && " + shlex.join(argv) + " && " + bindings)
    return checks[0], checks[1]


def _context(install_run: Path, run: Path, worktree: Path) -> tuple[dict, dict]:
    if any(path != path.resolve() for path in (install_run, run, worktree)):
        raise ValueError("Node guard paths must be resolved")
    install, current = _json(install_run / "command.json"), _json(run / "command.json")
    if (install.get("id") != install_run.name or current.get("id") != run.name
            or install.get("run_dir") != str(install_run) or current.get("run_dir") != str(run)
            or install.get("work_dir") != str(worktree) or current.get("work_dir") != str(worktree)
            or current.get("expected_git_identity") != install.get("expected_git_identity")):
        raise ValueError("Node run identity changed")
    lock = Path(current.get("mutation_lock") or "")
    if lock != run.parents[2] / LOCK or not lock.is_file() or lock.is_symlink():
        raise ValueError("Node guard requires its item-owned native lock")
    owner = _json(lock)
    if owner.get("run_id") != run.name or type(owner.get("pid")) is not int or owner["pid"] <= 0:
        raise ValueError("Node guard native lock belongs to a different run")
    os.kill(owner["pid"], 0)
    return install, current


def run_guard(operation: str, install_run: Path, run: Path, worktree: Path,
              phase: str, snapshot_sha: str) -> dict[str, Any]:
    install, current = _context(install_run, run, worktree)
    snapshot = install_run / SNAPSHOT
    if operation == "prepare":
        if run != install_run or phase != "preflight" or snapshot.exists() or snapshot.is_symlink():
            raise ValueError("npm install capture must start without an existing snapshot")
        return {"operation": operation, "run_id": run.name}
    if operation == "capture":
        if run != install_run or phase != "post-run":
            raise ValueError("Node capture is only an npm install post-check")
        payload = {"schema": SCHEMA, "run_id": run.name, "command_sha256": _digest(run / "command.json"),
                   "worktree": str(worktree), "identity": current["expected_git_identity"],
                   "lockfile_sha256": _digest(worktree / "package-lock.json"),
                   "entries": dependency_closure(worktree)}
        with snapshot.open("x") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
    elif operation == "verify":
        if run == install_run or phase not in {"preflight", "post-run"}:
            raise ValueError("Node verify is only a dependent command pre/post-check")
        if snapshot.is_symlink() or _digest(snapshot) != snapshot_sha:
            raise ValueError("installed Node capture SHA changed")
        payload = _json(snapshot)
        if (payload.get("schema") != SCHEMA or payload.get("run_id") != install_run.name
                or payload.get("command_sha256") != _digest(install_run / "command.json")
                or payload.get("worktree") != str(worktree) or payload.get("identity") != install["expected_git_identity"]
                or payload.get("lockfile_sha256") != _digest(worktree / "package-lock.json")
                or payload.get("entries") != dependency_closure(worktree)):
            raise ValueError("installed Node dependency closure changed after npm ci")
        # Transform caches contain runnable generated JavaScript. Give the
        # frozen Playwright command a fresh, run-owned cache rather than trusting
        # prior cached code. It is output of this command, outside node_modules.
        cache = Path(current.get("environment_overrides", {}).get("PWTEST_CACHE_DIR") or "")
        if "playwright" in current.get("command", []):
            if cache != run / "playwright-cache" or cache.is_symlink():
                raise ValueError("Playwright requires a fresh run-contained transform cache")
            if phase == "preflight":
                cache.mkdir(exist_ok=False)
    else:
        raise ValueError("unsupported Node guard operation")
    return {"operation": operation, "run_id": run.name, "install_run_id": install_run.name,
            "snapshot_sha256": _digest(snapshot)}


if __name__ == "__main__":
    try:
        result = run_guard(sys.argv[1], *(Path(p) for p in sys.argv[2:5]), sys.argv[5], sys.argv[6])
        print(json.dumps(result, sort_keys=True))
    except (OSError, ValueError, RuntimeError, KeyError, IndexError) as exc:
        print("Node execution provenance refused: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
