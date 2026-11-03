"""Native npm-install closure capture and execution-time verification.

This stdlib-only file is executed directly with the qualified base Python's
isolated flags. Native check output, rather than a caller-declared snapshot,
binds the installed bytes to the actual passed npm-ci command.

The default contract remains TypeScript/Playwright QA. Applications opt in
through the frozen validation.node_tool_contract mapping: schema
development-node-tool-contract/v1, profile application_static, a canonical
project_subdir, and nonempty required_executables mapping each local CLI to
its directly declared package. Producers and consumers resolve that same
selection; neither installed absence nor an unchecked optional tool list
can choose a weaker contract.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import stat
import subprocess
import sys
from typing import Any, Mapping, Sequence


SCHEMA = "development-node-install-closure/v1"
SNAPSHOT = "node-install-closure.json"
LOCK = "node-validation.lock"
APPLICATION_SCHEMA = "development-node-install-closure/app-static-v1"
TOOL_CONTRACT_SCHEMA = "development-node-tool-contract/v1"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _decode_json(text: str) -> dict[str, Any]:
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate Node authority key")
            value[key] = item
        return value
    value = json.loads(text, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("Node authority must be a mapping")
    return value


def _json(path: Path) -> dict[str, Any]:
    return _decode_json(path.read_text())


def _fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _selection(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the complete opt-in declaration, never infer missing tools."""
    if (not isinstance(value, Mapping)
            or set(value) != {"schema", "profile", "project_subdir", "required_executables"}
            or value.get("schema") != TOOL_CONTRACT_SCHEMA or value.get("profile") != "application_static"):
        raise ValueError("unsupported Node tool contract selector or fields")
    subdir = value["project_subdir"]
    if (not isinstance(subdir, str) or not subdir or "\\" in subdir
            or PurePosixPath(subdir).is_absolute() or Path(subdir).is_absolute()
            or ".." in PurePosixPath(subdir).parts or str(PurePosixPath(subdir)) != subdir):
        raise ValueError("Node project subdirectory must be canonical and contained")
    required = value["required_executables"]
    if not isinstance(required, Mapping) or not required:
        raise ValueError("Node tool contract requires declared executables")
    for executable, package in required.items():
        if (not isinstance(executable, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", executable)
                or not isinstance(package, str)
                or not re.fullmatch(r"(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*", package)):
            raise ValueError("Node executable/package declaration is unsafe")
    return {**value, "required_executables": dict(sorted(required.items()))}


def node_project(profile: Mapping[str, Any], worktree: Path) -> tuple[Path, dict[str, Any] | None]:
    """Resolve only an explicit immutable selected-profile declaration."""
    validation = profile.get("validation", {})
    if not isinstance(validation, Mapping):
        raise ValueError("Node validation profile must be a mapping")
    if "node_tool_contract" not in validation:
        return worktree, None
    selection = _selection(validation["node_tool_contract"])
    project = worktree / selection["project_subdir"]
    if (worktree != worktree.resolve() or project != project.resolve()
            or not project.is_dir() or not project.is_relative_to(worktree)):
        raise ValueError("Node project must be a contained canonical directory")
    return project, selection


def selected_node_command(command: str, selection: Mapping[str, Any],
                          actual_argv: Sequence[str] | None = None) -> str | None:
    """Accept only install or non-installing npx execution of a required CLI."""
    selected = _selection(selection)
    words = shlex.split(command)
    if actual_argv is not None and list(actual_argv) != words:
        raise ValueError("app-static Node execution argv differs from its frozen command")
    if words == ["npm", "ci"]:
        return None
    forbidden = ("--package", "--prefix", "--call", "--yes", "--install", "--global", "--registry")
    if (len(words) < 3 or words[:2] != ["npx", "--no-install"]
            or words[2] not in selected["required_executables"]
            or any(word.startswith(("-p", "-c", "-y", "-g", *forbidden)) for word in words[3:])):
        raise ValueError("app-static Node command must use a frozen required local CLI with npx --no-install")
    return words[2]


def contract_binding(worktree: Path, selection: Mapping[str, Any]) -> dict[str, Any]:
    """Bind pre-install requirements to the actual manifest and v2/v3 lock."""
    selected = _selection(selection)
    if worktree != worktree.resolve() or not worktree.is_dir():
        raise ValueError("Node manifest directory is not canonical")
    for filename in ("package.json", "package-lock.json"):
        path = worktree / filename
        if not path.is_file() or path.is_symlink():
            raise ValueError("Node manifest and lock must be ordinary contained files")
    manifest, lock = _json(worktree / "package.json"), _json(worktree / "package-lock.json")
    packages = lock.get("packages")
    if (type(lock.get("lockfileVersion")) is not int or lock["lockfileVersion"] not in {2, 3}
            or not isinstance(packages, Mapping) or not isinstance(packages.get(""), Mapping)):
        raise ValueError("app-static Node contract requires a complete package-lock v2/v3 manifest")
    tools = []
    for executable, package in selected["required_executables"].items():
        groups = [group for group in ("dependencies", "devDependencies", "optionalDependencies")
                  if isinstance(manifest.get(group), Mapping) and package in manifest[group]]
        locked_declarations = packages[""].get(groups[0]) if len(groups) == 1 else None
        if (len(groups) != 1 or not isinstance(manifest[groups[0]][package], str)
                or not manifest[groups[0]][package]
                or not isinstance(locked_declarations, Mapping)
                or locked_declarations.get(package) != manifest[groups[0]][package]):
            raise ValueError("required Node package must be directly declared and match its locked manifest")
        locked = packages.get("node_modules/" + package)
        if (not isinstance(locked, Mapping) or not isinstance(locked.get("version"), str)
                or not locked["version"] or locked.get("link") is True):
            raise ValueError("required Node package has no locked installed version")
        tools.append({"executable": executable, "package": package, "version": locked["version"],
                      "lock_entry_sha256": _fingerprint(locked)})
    bound = {"schema": "development-node-tool-contract-binding/v1", "selection": selected,
             "profile_fingerprint": _fingerprint(selected), "manifest_sha256": _digest(worktree / "package.json"),
             "lockfile_sha256": _digest(worktree / "package-lock.json"), "locked_tools": tools}
    return {**bound, "fingerprint": _fingerprint(bound)}


def source_binding(worktree: Path, selection: Mapping[str, Any], head: str | None = None) -> dict[str, Any]:
    """Require both app manifests to be ordinary committed bytes at this Git head."""
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment["GIT_OPTIONAL_LOCKS"] = "0"

    def git(*args: str, directory: Path | None = None) -> bytes:
        try:
            return subprocess.check_output(["git", "--no-replace-objects", "-C", str(directory or worktree), *args],
                                           env=environment, stderr=subprocess.PIPE, timeout=10)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError("app-static Node source authority is unavailable") from exc

    root = Path(os.fsdecode(git("rev-parse", "--show-toplevel")).strip()).resolve()
    selected_root, _ = node_project({"validation": {"node_tool_contract": selection}}, root)
    actual_head = git("rev-parse", "HEAD").decode().strip()
    if selected_root != worktree or head is not None and actual_head != head:
        raise ValueError("app-static Node source directory or frozen Git head differs")
    inputs = []
    for filename in ("package.json", "package-lock.json"):
        path = worktree / filename
        relative = str(path.relative_to(root))
        if not path.is_file() or path.is_symlink():
            raise ValueError("app-static Node source manifests must be ordinary committed files")
        entry = git("ls-tree", "-z", actual_head, "--", relative, directory=root).split(b"\0")
        if len(entry) != 2 or entry[1] or b"\t" not in entry[0]:
            raise ValueError("app-static Node source manifest is not committed")
        metadata, name = entry[0].split(b"\t", 1)
        fields = metadata.decode().split()
        contents = path.read_bytes()
        if (len(fields) != 3 or fields[0] not in {"100644", "100755"} or fields[1] != "blob"
                or os.fsdecode(name) != relative or contents != git("show", actual_head + ":" + relative, directory=root)):
            raise ValueError("app-static Node source manifest differs from its committed ordinary blob")
        inputs.append({"path": relative, "git_mode": fields[0], "git_blob": fields[2],
                       "sha256": hashlib.sha256(contents).hexdigest()})
    value = {"schema": "development-node-source-binding/v1", "worktree": str(root), "head_sha": actual_head,
             "object_resolution": "raw_no_replace",
             "inputs": inputs}
    return {**value, "fingerprint": _fingerprint(value)}


def _local_executable(root: Path, name: str) -> Path:
    target = (root / ".bin" / name).resolve(strict=True)
    if not target.is_relative_to(root) or not target.is_file() or not target.stat().st_mode & 0o111:
        raise ValueError("required local Node executable is unqualified")
    return target


def contract_provenance(worktree: Path, selection: Mapping[str, Any]) -> dict[str, Any]:
    """Require every selected bin's locked package owner, version and bytes."""
    binding = contract_binding(worktree, selection)
    root = worktree / "node_modules"
    if root.is_symlink() or not root.is_dir() or root != root.resolve():
        raise ValueError("installed Node closure is absent or redirected")
    identities = []
    for tool in binding["locked_tools"]:
        package_root = root / tool["package"]
        package_path = package_root / "package.json"
        if (package_root != package_root.resolve() or not package_root.is_dir()
                or package_path.is_symlink() or not package_path.is_file()):
            raise ValueError("required Node package manifest is redirected or absent")
        package = _json(package_path)
        if package.get("name") != tool["package"] or package.get("version") != tool["version"]:
            raise ValueError("required Node package identity/version differs from its lock")
        binaries = package.get("bin")
        binary = binaries.get(tool["executable"]) if isinstance(binaries, Mapping) else (
            binaries if tool["executable"] == tool["package"].split("/")[-1] else None)
        if not isinstance(binary, str) or not binary or Path(binary).is_absolute():
            raise ValueError("required Node executable is not declared by its package")
        target = _local_executable(root, tool["executable"])
        declared = (package_root / binary).resolve(strict=True)
        if not declared.is_relative_to(package_root) or target != declared:
            raise ValueError("required Node executable resolves outside its declared package")
        identities.append({**tool, "package_manifest_sha256": _digest(package_path),
                           "target": str(target.relative_to(root)), "sha256": _digest(target),
                           "mode": stat.S_IMODE(target.stat().st_mode)})
    value = {"binding": binding, "installed_tools": identities}
    return {**value, "fingerprint": _fingerprint(value)}


def dependency_closure(worktree: Path, tool_contract: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
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
    if tool_contract is None:
        for name in ("tsc", "playwright"):
            _local_executable(root, name)
    else:
        contract_provenance(worktree, tool_contract)
    return sorted(entries, key=lambda row: row["path"])


def guard_checks(install_run: Path, run: Path, worktree: Path, snapshot_sha: str | None = None,
                 *, tool_contract: Mapping[str, Any] | None = None) -> tuple[str, str]:
    """Derive exact approved helper/interpreter checks, never from request hashes."""
    helper = Path(__file__).resolve()
    interpreter = Path(sys._base_executable).resolve()
    checks = []
    binding = contract_binding(worktree, tool_contract) if tool_contract is not None else None
    if tool_contract is not None:
        source_binding(worktree, tool_contract)
    for phase in ("preflight", "post-run"):
        operation = ("prepare" if phase == "preflight" else "capture") if run == install_run else "verify"
        argv = [str(interpreter), "-I", "-S", str(helper), operation,
                str(install_run), str(run), str(worktree), phase, snapshot_sha or "-"]
        if binding is not None:
            argv.append(json.dumps(binding, sort_keys=True, separators=(",", ":")))
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
              phase: str, snapshot_sha: str, expected_contract: Mapping[str, Any] | None = None) -> dict[str, Any]:
    install, current = _context(install_run, run, worktree)
    snapshot = install_run / SNAPSHOT
    selection = None
    source = None
    fingerprint = {}
    if expected_contract is not None:
        if (not isinstance(expected_contract, Mapping)
                or not isinstance(expected_contract.get("selection"), Mapping)):
            raise ValueError("Node tool contract binding is malformed")
        selection = expected_contract["selection"]
        actual = contract_binding(worktree, selection)
        if actual != expected_contract:
            raise ValueError("Node frozen tool contract, manifest or lock changed")
        head = current["expected_git_identity"].get("head")
        if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head):
            raise ValueError("app-static Node source authority requires the native frozen Git head")
        source = source_binding(worktree, selection, head)
        fingerprint = {"tool_contract_fingerprint": actual["fingerprint"],
                       "source_binding_fingerprint": source["fingerprint"]}
    if operation == "prepare":
        if run != install_run or phase != "preflight" or snapshot.exists() or snapshot.is_symlink():
            raise ValueError("npm install capture must start without an existing snapshot")
        return {"operation": operation, "run_id": run.name, **fingerprint}
    if operation == "capture":
        if run != install_run or phase != "post-run":
            raise ValueError("Node capture is only an npm install post-check")
        payload = {"schema": APPLICATION_SCHEMA if selection is not None else SCHEMA,
                   "run_id": run.name, "command_sha256": _digest(run / "command.json"),
                   "worktree": str(worktree), "identity": current["expected_git_identity"],
                   "lockfile_sha256": _digest(worktree / "package-lock.json"),
                   "entries": dependency_closure(worktree, selection)}
        if selection is not None:
            payload["source_binding"] = source
            payload["tool_contract"] = contract_provenance(worktree, selection)
            if payload["tool_contract"]["binding"] != expected_contract:
                raise ValueError("Node tool contract changed during capture")
        with snapshot.open("x") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
    elif operation == "verify":
        if run == install_run or phase not in {"preflight", "post-run"}:
            raise ValueError("Node verify is only a dependent command pre/post-check")
        if snapshot.is_symlink() or _digest(snapshot) != snapshot_sha:
            raise ValueError("installed Node capture SHA changed")
        payload = _json(snapshot)
        if (payload.get("schema") != (APPLICATION_SCHEMA if selection is not None else SCHEMA)
                or payload.get("run_id") != install_run.name
                or payload.get("command_sha256") != _digest(install_run / "command.json")
                or payload.get("worktree") != str(worktree) or payload.get("identity") != install["expected_git_identity"]
                or payload.get("lockfile_sha256") != _digest(worktree / "package-lock.json")
                or payload.get("entries") != dependency_closure(worktree, selection)
                or (payload.get("source_binding") != source if selection is not None else "source_binding" in payload)
                or (payload.get("tool_contract") != contract_provenance(worktree, selection) if selection is not None
                    else "tool_contract" in payload)):
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
            "snapshot_sha256": _digest(snapshot), **fingerprint}


if __name__ == "__main__":
    try:
        if len(sys.argv) not in {7, 8}:
            raise ValueError("unsupported Node guard arguments")
        result = run_guard(sys.argv[1], *(Path(p) for p in sys.argv[2:5]), sys.argv[5], sys.argv[6],
                           _decode_json(sys.argv[7]) if len(sys.argv) == 8 else None)
        print(json.dumps(result, sort_keys=True))
    except (OSError, ValueError, RuntimeError, KeyError, IndexError) as exc:
        print("Node execution provenance refused: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
