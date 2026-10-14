"""Narrow frozen-command matching shared by validation and readiness proof readers."""
from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
from typing import Any, Mapping


def execution_argv(command: Mapping[str, Any], task: Mapping[str, Any] | None = None) -> tuple[list[str], dict[str, str]]:
    """Admit only receipt-bound metadata and contained output/cache controls."""
    argv = command.get("command")
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
        return [], {}
    argv = list(argv)
    environment: dict[str, str] = {}
    overrides = command.get("environment_overrides", {})
    if not isinstance(overrides, Mapping):
        return [], {}
    assignments = list(overrides.items())
    if argv[0] == "env":
        argv = argv[1:]
        if argv and argv[0].startswith("-"):
            return [], {}  # Clearing or changing inherited execution is not a frozen annotation.
        while argv and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[0]):
            assignments.append(tuple(argv.pop(0).split("=", 1)))
    for key, value in assignments:
        if not isinstance(key, str) or not isinstance(value, str) or key in environment:
            return [], {}
        if key == "REVIEW_POLICY_FINGERPRINT":
            allowed = bool(re.fullmatch(r"[0-9a-f]{64}", value))
        elif key == "PYTEST_ADDOPTS":
            allowed = value == ""  # Explicitly neutralize inherited test selection.
        elif key == "PYTHONDONTWRITEBYTECODE":
            allowed = value == "1"
        elif key in {"COVERAGE_FILE", "NPM_CONFIG_CACHE", "PWTEST_CACHE_DIR"}:
            allowed = task is not None and _contained_annotation(value, task, cache_only=True)
        else:
            allowed = False
        if not allowed:
            return [], {}
        environment[key] = value
    return argv, environment


def _contained_annotation(value: str, task: Mapping[str, Any], *, cache_only: bool = False) -> bool:
    if not value:
        return False
    worktree = Path(str(task.get("worktree", {}).get("path") or ""))
    packet = Path(str(task.get("work_item") or ""))
    if not worktree.is_absolute() or not packet.is_absolute():
        return False
    path = Path(value)
    if cache_only and not path.is_absolute():
        return False
    if not path.is_absolute():
        path = worktree / path
    lexical = Path(os.path.abspath(path))
    # Outputs may not escape through an existing symlink or replace either root.
    roots = (packet / "artifacts",) if cache_only else (packet, worktree)
    return any(lexical != root and lexical.is_relative_to(root)
               and lexical.resolve().is_relative_to(root.resolve())
               for root in roots)


def _annotations(extras: list[str], task: Mapping[str, Any]) -> bool:
    index = 0
    cache_seen = False
    while index < len(extras):
        token = extras[index]
        if token == "--cov-branch" or token.startswith(("--cov=", "--cov-fail-under=", "--cov-config=")):
            # Targets, branch mode, configuration and thresholds alter the
            # gate's denominator or acceptance. Only the frozen prefix owns them.
            return False
        elif token.startswith("--basetemp="):
            if not _contained_annotation(token.split("=", 1)[1], task):
                return False
        elif token.startswith("--cov-report="):
            report = token.split("=", 1)[1]
            kind, separator, destination = report.partition(":")
            if kind not in {"term", "term-missing", "html", "xml", "json", "lcov", "annotate"}:
                return False
            if separator and not _contained_annotation(destination, task):
                return False
        elif token == "-o":
            if cache_seen:
                return False
            cache_seen = True
            index += 1
            if index >= len(extras) or not extras[index].startswith("cache_dir="):
                return False
            if not _contained_annotation(extras[index].split("=", 1)[1], task, cache_only=True):
                return False
        else:
            return False
        index += 1
    return True


def _isolated_diagnostic(code: str) -> bool:
    """Small frozen diagnostic grammar; no path loading, site hooks or dependencies."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return False
    allowed = (ast.Module, ast.Import, ast.alias, ast.Assign, ast.Expr, ast.Call,
               ast.Name, ast.Load, ast.Store, ast.Constant, ast.Attribute,
               ast.UnaryOp, ast.Not, ast.IfExp, ast.Compare, ast.Eq, ast.NotEq)
    protected = {"os", "sys", "print"}
    attributes = {"os.environ", "os.environ.get", "sys.exit"}
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            return False
        if isinstance(node, ast.Import) and any(a.name not in {"os", "sys"} or a.asname for a in node.names):
            return False
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            return False
        if isinstance(node, ast.Assign) and any(not isinstance(t, ast.Name) or t.id in protected for t in node.targets):
            return False
        if isinstance(node, ast.Attribute) and ast.unparse(node) not in attributes:
            return False
        if isinstance(node, ast.Call):
            name = ast.unparse(node.func)
            if name not in {"print", "os.environ.get", "sys.exit"} or node.keywords:
                return False
            if name == "os.environ.get" and (len(node.args) != 1 or not isinstance(node.args[0], ast.Constant)
                                             or not isinstance(node.args[0].value, str)):
                return False
    return True


def runtime_provenance_check(configured: str, actual: list[str], task: Mapping[str, Any],
                             selected: Mapping[str, Any], *,
                             qualified_runtime: QualifiedPythonRuntime | None = None) -> str | None:
    """Require native dependency qualification or a declared isolated diagnostic."""
    if not actual:
        raise ValueError("executed command is unavailable")
    if qualified_runtime is not None:
        if qualified_runtime.command != configured or actual[0] != qualified_runtime.executable:
            raise ValueError("qualified Python runtime does not bind this frozen command")
        return None  # Its actual install and execution-time closure checks were verified separately.
    executable = Path(actual[0])
    roots = (Path(task["work_item"]).resolve(), Path(task["worktree"]["path"]).resolve())
    lexical = Path(os.path.abspath(roots[1] / executable)) if actual[0].startswith(".") else executable
    if lexical.is_absolute() and any(lexical.is_relative_to(root) for root in roots):
        raise ValueError("work-item executable requires independently declared dependency provenance")
    if shlex.split(configured) in (["npm", "ci"], ["npx", "tsc", "--noEmit"],
                                  ["npx", "playwright", "test", "--list"]):
        return None
    if not re.match(r"^(python|pypy)", executable.name, re.IGNORECASE):
        raise ValueError("command runtime/dependency provenance is unsupported for validation recovery")
    declarations = selected.get("validation", {}).get("isolated_python_interpreters") or {}
    declaration = declarations.get(configured) if isinstance(declarations, Mapping) else None
    if (not isinstance(declaration, Mapping) or declaration.get("authority") != "frozen_selected_profile"
            or declaration.get("dependency_mode") != "isolated_stdlib_diagnostic"
            or not executable.is_absolute() or executable != executable.resolve()
            or declaration.get("executable") != str(executable)
            or not re.fullmatch(r"[0-9a-f]{64}", str(declaration.get("sha256") or ""))
            or len(actual) != 5 or actual[1:4] != ["-I", "-S", "-c"]
            or not _isolated_diagnostic(actual[4])):
        raise ValueError("unsafe Python execution requires frozen interpreter/dependency provenance")
    try:
        observed = hashlib.sha256(executable.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValueError("declared base interpreter is unavailable") from exc
    if observed != declaration["sha256"]:
        raise ValueError("declared base interpreter SHA changed")
    # The real governed runner must execute this exact checksum before and
    # after the diagnostic. Caller evidence alone never declares interpreter trust.
    return (shlex.join(["/usr/bin/shasum", "-a", "256", str(executable)])
            + " | /usr/bin/awk " + shlex.quote('$1 == "' + observed + '" {ok=1} END {exit !ok}'))


def matches_command(configured: str, actual: list[str], task: Mapping[str, Any],
                    selected: Mapping[str, Any], *,
                    qualified_runtime: QualifiedPythonRuntime | None = None) -> bool:
    """Keep the frozen prefix exact; permit only contained pytest annotations."""
    try:
        expected = shlex.split(configured)
    except (TypeError, ValueError):
        return False
    if (not expected or not isinstance(actual, list) or len(actual) < len(expected)
            or not all(isinstance(x, str) for x in actual)):
        return False
    worktree = Path(str(task.get("worktree", {}).get("path") or ""))
    packet = Path(str(task.get("work_item") or ""))
    if not worktree.is_absolute() or not packet.is_absolute():
        return False

    def executable(value: str) -> str:
        # Lexical binding intentionally preserves the named task venv symlink.
        return os.path.abspath(worktree / value) if value.startswith(".") else value

    accepted = executable(expected[0])
    if qualified_runtime is not None:
        if (qualified_runtime.command != configured or expected[1:3] != ["-m", "pytest"]
                or not Path(accepted).is_absolute() or not Path(accepted).is_relative_to(worktree)
                or not Path(qualified_runtime.executable).is_relative_to(packet / "artifacts")):
            return False
        accepted = qualified_runtime.executable
    validation = selected.get("validation") or {}
    if not isinstance(validation, Mapping):
        return False
    mappings = validation.get("command_executables") or {}
    mapping = mappings.get(configured) if isinstance(mappings, Mapping) else None
    if mapping is not None and qualified_runtime is None:
        if (selected.get("schema") != "development-selected-profile/v2"
                or not isinstance(mapping, Mapping) or mapping.get("authority") != "selected_profile"):
            return False
        try:
            mapped = Path(mapping["executable"].format(work_item=str(packet), worktree=str(worktree)))
            if not mapped.is_absolute():
                return False
            mapped = Path(os.path.abspath(mapped))
        except (KeyError, TypeError, ValueError, AttributeError):
            return False
        if not any(mapped.is_relative_to(root) and mapped != root for root in (packet, worktree)):
            return False
        accepted = str(mapped)
    if accepted != executable(actual[0]) or expected[1:] != actual[1:len(expected)]:
        return False
    extras = actual[len(expected):]
    if not extras:
        return True
    # An added selector, test path, plugin, or arbitrary ini override changes
    # what ran and cannot establish the frozen full command.
    return expected[1:3] == ["-m", "pytest"] and _annotations(extras, task)


PYTHON_SNAPSHOT = "python-install-closure.json"
PYTHON_LOCK = "python-validation.lock"
PYTHON_SCHEMA = "development-python-install-closure/v1"


@dataclass(frozen=True)
class QualifiedPythonRuntime:
    """A native proof reader's execution binding; never a selected-policy rewrite."""
    command: str
    executable: str


def _json(path: Path) -> dict[str, Any]:
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate Python runtime authority key")
            value[key] = item
        return value
    value = json.loads(path.read_text(), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("Python runtime authority must be a mapping")
    return value


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def python_runtime_binding(task_path: Path, head: str) -> dict[str, Any]:
    """Bind the original task/policy and tracked dependency inputs at this head."""
    task = _json(task_path)
    packet, worktree = Path(task["work_item"]).resolve(), Path(task["worktree"]["path"]).resolve()
    policy = Path(task["policy_receipt"])
    if (task_path != task_path.resolve() or task.get("schema") != "development-task/v1"
            or task.get("state") != "local_validation" or not task.get("canonical_work_id")
            or _json(policy).get("fingerprint") != task.get("policy_fingerprint")):
        raise ValueError("Python qualification requires the original pinned local-validation task")
    inputs = {}
    for name in ("pyproject.toml", "uv.lock"):
        path = worktree / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(worktree):
            raise ValueError("Python qualification requires contained tracked pyproject.toml and uv.lock")
        subprocess.run(["git", "-C", str(worktree), "ls-files", "--error-unmatch", name],
                       check=True, capture_output=True)
        inputs[name] = _digest(path)
    return {"task_state_ref": str(task_path), "canonical_work_id": task["canonical_work_id"],
            "repository_id": task["repository"]["id"], "work_item": str(packet), "worktree": str(worktree),
            "source_branch": task["worktree"]["branch"], "head_sha": head,
            "policy_fingerprint": task["policy_fingerprint"], "policy_ref": str(policy),
            "policy_sha256": _digest(policy), "dependency_inputs": inputs}


def _python_install_command(task_path: Path, install_run: Path, runtime: Path, *, offline: bool) -> list[str]:
    task = _json(task_path)
    packet, worktree = Path(task["work_item"]).resolve(), Path(task["worktree"]["path"]).resolve()
    base = Path(sys._base_executable).resolve()
    located = shutil.which("uv")
    uv = Path(located).resolve() if located else Path()
    if (not located or not uv.is_file() or any(base.is_relative_to(p) or uv.is_relative_to(p) for p in (packet, worktree))
            or any(path != path.resolve() or not path.is_relative_to(packet / "artifacts")
                   for path in (install_run, runtime)) or runtime == packet / "artifacts"
            or runtime.is_relative_to(install_run) or install_run.is_relative_to(runtime)):
        raise ValueError("Python qualification requires independent host tools and fresh owned artifact paths")
    return ["/usr/bin/env", "UV_PROJECT_ENVIRONMENT=" + str(runtime),
            "UV_CACHE_DIR=" + str(install_run / "uv-cache"), str(uv), "sync", "--locked", "--all-groups",
            "--all-extras", "--no-editable", "--no-managed-python", "--python", str(base),
            "--project", str(worktree), *(["--offline"] if offline else [])]


def python_runtime_install_plan(task_path: Path, install_run: Path, runtime: Path, *, offline: bool = False) -> dict[str, Any]:
    """Prepare a real native locked install; it does not qualify caller-supplied bytes."""
    from .development_validation_refresh import _context
    _, current, packet, worktree, profile = _context(task_path)
    if not any(shlex.split(c)[1:3] == ["-m", "pytest"] for c in profile["validation"]["commands"]):
        raise ValueError("Python runtime qualification requires a frozen pytest command")
    head = subprocess.check_output(["git", "-C", str(worktree), "rev-parse", "HEAD"], text=True).strip()
    python_runtime_binding(task_path, head)
    command = _python_install_command(task_path, install_run, runtime, offline=offline)
    pre, post = python_runtime_guard_checks(install_run, install_run, task_path, runtime)
    return {"command": command, "mutation_lock": str(packet / "artifacts" / PYTHON_LOCK),
            "preflight_checks": [pre], "post_run_checks": [post]}


def python_dependency_closure(runtime: Path) -> list[dict[str, Any]]:
    """Hash the actual fresh locked environment, including generated and native code."""
    base = Path(sys._base_executable).resolve()
    if runtime.is_symlink() or not runtime.is_dir() or (runtime / "bin/python").resolve() != base:
        raise ValueError("qualified Python runtime or independent base interpreter changed")
    config = runtime / "pyvenv.cfg"
    if "include-system-site-packages = false" not in config.read_text().lower():
        raise ValueError("qualified Python runtime cannot load system site packages")
    if not any(runtime.glob("lib/python*/site-packages/pytest/__init__.py")):
        raise ValueError("locked Python runtime has no installed pytest")
    entries = []
    def visit(path: Path) -> None:
        before = path.lstat()
        row = {"path": str(path.relative_to(runtime)), "mode": stat.S_IMODE(before.st_mode)}
        if not stat.S_ISLNK(before.st_mode) and row["mode"] & 0o7022:
            raise ValueError("Python runtime entry has unsafe writable or special mode")
        if stat.S_ISLNK(before.st_mode):
            target = path.resolve(strict=True)
            base_link = path.parent == runtime / "bin" and re.fullmatch(r"python(?:3(?:\.\d+)?)?", path.name) and target == base
            if not base_link and (target == runtime or not target.is_relative_to(runtime)):
                raise ValueError("Python runtime symlink escapes its qualified closure")
            row.update(kind="symlink", target=os.readlink(path))
        elif stat.S_ISREG(before.st_mode):
            row.update(kind="file", sha256=_digest(path))
        elif stat.S_ISDIR(before.st_mode):
            row.update(kind="directory")
            for child in sorted(path.iterdir()):
                visit(child)
        else:
            raise ValueError("Python runtime contains a special file")
        after = path.lstat()
        if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_mode) != (
                after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_mode):
            raise ValueError("Python runtime changed while hashing its closure")
        entries.append(row)
    visit(runtime)
    return sorted(entries, key=lambda row: row["path"])


def python_runtime_guard_checks(install_run: Path, run: Path, task_path: Path, runtime: Path,
                                snapshot_sha: str | None = None) -> tuple[str, str]:
    """Derive exact SDK/base/tool checks and native closure operations."""
    helper, base = Path(__file__).resolve(), Path(sys._base_executable).resolve()
    located = shutil.which("uv")
    if not located:
        raise ValueError("locked Python runtime qualification requires uv")
    uv = Path(located).resolve()
    checks = []
    for phase in ("preflight", "post-run"):
        operation = ("prepare" if phase == "preflight" else "capture") if install_run == run else "verify"
        argv = [str(base), "-I", "-S", str(helper), "python-runtime-guard", operation,
                str(install_run), str(run), str(task_path), str(runtime), phase, snapshot_sha or "-"]
        bindings = " && ".join(shlex.join(["/usr/bin/shasum", "-a", "256", str(path)])
            + " | /usr/bin/awk " + shlex.quote('$1 == "' + _digest(path) + '" {ok=1} END {exit !ok}')
            for path in (helper, base, uv))
        checks.append(bindings + " && " + shlex.join(argv) + " && " + bindings)
    return checks[0], checks[1]


def run_python_runtime_guard(operation: str, install_run: Path, run: Path, task_path: Path,
                             runtime: Path, phase: str, snapshot_sha: str) -> dict[str, Any]:
    if any(path != path.resolve() for path in (install_run, run, task_path, runtime)):
        raise ValueError("Python guard paths must be resolved")
    task = _json(task_path)
    packet, worktree = Path(task["work_item"]).resolve(), Path(task["worktree"]["path"]).resolve()
    install, command = _json(install_run / "command.json"), _json(run / "command.json")
    identity = command.get("expected_git_identity")
    if (not isinstance(identity, dict) or identity != install.get("expected_git_identity")
            or identity.get("worktree") != str(worktree) or identity.get("branch") != task["worktree"]["branch"]
            or identity.get("clean") != "true"
            or any(row.get("shell") is not False or row.get("id") != path.name
                   or row.get("run_dir") != str(path) or row.get("work_dir") != str(worktree)
                   for row, path in ((install, install_run), (command, run)))):
        raise ValueError("Python install/validation native identity differs")
    expected_install = _python_install_command(task_path, install_run, runtime, offline="--offline" in install["command"])
    if install["command"] != expected_install or install.get("environment_overrides"):
        raise ValueError("Python qualification did not execute the exact locked install")
    lock = packet / "artifacts" / PYTHON_LOCK
    if command.get("mutation_lock") != str(lock) or lock.is_symlink() or not lock.is_file():
        raise ValueError("Python guard requires its native item lock")
    owner = _json(lock)
    if owner.get("run_id") != run.name or type(owner.get("pid")) is not int or owner["pid"] <= 0:
        raise ValueError("Python native lock belongs to a different run")
    os.kill(owner["pid"], 0)
    binding = python_runtime_binding(task_path, identity["head"])
    snapshot = install_run / PYTHON_SNAPSHOT
    if operation == "prepare":
        if run != install_run or phase != "preflight" or runtime.exists() or runtime.is_symlink() or snapshot.exists() or snapshot.is_symlink():
            raise ValueError("locked Python qualification requires a fresh runtime and snapshot")
        return {"operation": operation, "run_id": run.name}
    if operation == "capture":
        if run != install_run or phase != "post-run":
            raise ValueError("Python capture is only a locked install post-check")
        # uv creates an empty, non-executable environment lock with mode 0666.
        # Restrict only that known metadata file before capturing the fresh
        # runtime; every other writable or redirected entry still fails closed.
        uv_lock = runtime / ".lock"
        if uv_lock.exists():
            mode = uv_lock.lstat().st_mode
            if not stat.S_ISREG(mode) or uv_lock.stat().st_size != 0 or mode & 0o111:
                raise ValueError("uv environment lock metadata is redirected or executable")
            uv_lock.chmod(0o600)
        payload = {"schema": PYTHON_SCHEMA, "run_id": run.name, "command_sha256": _digest(run / "command.json"),
                   "runtime": str(runtime), "binding": binding, "identity": identity,
                   "entries": python_dependency_closure(runtime)}
        with snapshot.open("x") as stream:
            json.dump(payload, stream, sort_keys=True); stream.write("\n")
    elif operation == "verify":
        if run == install_run or phase not in {"preflight", "post-run"} or snapshot.is_symlink() or _digest(snapshot) != snapshot_sha:
            raise ValueError("Python install closure hash or verification phase changed")
        payload = _json(snapshot)
        if (payload.get("schema") != PYTHON_SCHEMA or payload.get("run_id") != install_run.name
                or payload.get("command_sha256") != _digest(install_run / "command.json")
                or payload.get("runtime") != str(runtime) or payload.get("identity") != identity
                or payload.get("binding") != binding or payload.get("entries") != python_dependency_closure(runtime)):
            raise ValueError("Python dependency closure or task/head/policy binding changed")
        actual, environment = execution_argv(command, task)
        if (not actual or actual[0] != str(runtime / "bin/python")
                or environment.get("PYTHONDONTWRITEBYTECODE") != "1" or environment.get("PYTEST_ADDOPTS") != ""):
            raise ValueError("qualified pytest requires exact runtime and neutralized selection/bytecode controls")
        if any(os.environ.get(name) for name in ("PYTHONPATH", "PYTHONHOME", "PYTEST_PLUGINS", "PYTHONSTARTUP",
                    "COVERAGE_RCFILE", "PYTHONOPTIMIZE", "LD_PRELOAD", "DYLD_INSERT_LIBRARIES")):
            raise ValueError("qualified pytest inherited execution-affecting environment")
    else:
        raise ValueError("unsupported Python runtime guard operation")
    return {"operation": operation, "run_id": run.name, "install_run_id": install_run.name,
            "snapshot_sha256": _digest(snapshot)}


if __name__ == "__main__":
    try:
        if sys.argv[1] != "python-runtime-guard":
            raise ValueError("unsupported validation command authority operation")
        result = run_python_runtime_guard(sys.argv[2], *(Path(value) for value in sys.argv[3:7]), sys.argv[7], sys.argv[8])
        print(json.dumps(result, sort_keys=True))
    except (OSError, ValueError, RuntimeError, KeyError, IndexError, subprocess.SubprocessError) as exc:
        print("Python execution provenance refused: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
