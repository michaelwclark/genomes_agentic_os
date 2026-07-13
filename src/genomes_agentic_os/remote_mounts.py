"""SSHFS remote mount namespace support (feature 64).

Provides path detection, path translation, dry-run-first mount/unmount,
remote command execution, and offline doctor checks for remote projects
that declare an optional ``mount`` block in their ``sources.remotes[]``
entries.

SSH_<host> convention
---------------------
Any path component named ``SSH_<host>`` marks an SSHFS remote namespace.
Detection is purely by naming convention — no directory scanning.

Mount metadata in project.yml
------------------------------
A remote entry may include an optional ``mount`` block::

    sources:
      remotes:
        - name: appserver
          host: example-host
          path: /home/operator/projects/appserver
          kind: git
          authority: remote
          mount:
            namespace: SSH_example-host
            local_path: ~/os/SSH_example-host/appserver
            access: sshfs
            execution: remote

Injectable runner
-----------------
All functions that invoke external processes accept an optional *runner*
callable so tests never open real SSH/SSHFS connections::

    def fake_runner(args, *, timeout):
        return FakeResult(stdout="", returncode=0)

The default runner wraps ``subprocess.run`` with ``capture_output=True,
text=True`` and no ``shell=True``.
"""

from __future__ import annotations

import platform
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

import yaml

from .hosts import load_hosts
from .scaffold import domain_path, expand_path

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Runner = Callable[[list[str], Any], Any]  # (args, *, timeout) -> CompletedProcess-like

_SSH_PREFIX = "SSH_"


# ---------------------------------------------------------------------------
# Local remotes extractor
# ---------------------------------------------------------------------------


def _remotes_from_yaml(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract sources.remotes from a parsed project.yml dict.

    Unlike scaffold._remotes_from_yaml, this preserves nested dicts (e.g.
    the ``mount`` block) rather than stringifying every value.  Feature 64
    needs the full dict for mount metadata.
    """
    sources = data.get("sources")
    if not isinstance(sources, dict):
        return []
    remotes = sources.get("remotes")
    if not isinstance(remotes, list):
        return []
    return [r for r in remotes if isinstance(r, dict)]


# ---------------------------------------------------------------------------
# Default runner (real subprocess — never used in tests)
# ---------------------------------------------------------------------------


def _default_runner(args: list[str], *, timeout: int = 20) -> Any:
    """Run *args* via subprocess and return the CompletedProcess.

    Never uses shell=True; args is always an argv list.
    """
    return subprocess.run(  # noqa: S603
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Path detection
# ---------------------------------------------------------------------------


def detect_ssh_namespace(path: str | Path) -> tuple[str, str] | None:
    """Detect an SSH_<host> component in *path*.

    Returns ``(host, relative_suffix)`` where *host* is the part after
    ``SSH_`` in the matching component, and *relative_suffix* is the
    path suffix relative to (and not including) that component.

    Returns ``None`` when no ``SSH_<host>`` component is found.

    Detection is by naming convention only — no directory scanning.

    Examples
    --------
    >>> detect_ssh_namespace("/Users/operator/SSH_example-host/appserver/src/app.ts")
    ('example-host', 'appserver/src/app.ts')
    >>> detect_ssh_namespace("/tmp/normal/path") is None
    True
    """
    p = Path(path)
    parts = p.parts
    for idx, part in enumerate(parts):
        if part.startswith(_SSH_PREFIX) and len(part) > len(_SSH_PREFIX):
            host = part[len(_SSH_PREFIX):]
            suffix_parts = parts[idx + 1:]
            suffix = str(Path(*suffix_parts)) if suffix_parts else ""
            return host, suffix
    return None


# ---------------------------------------------------------------------------
# Path translation
# ---------------------------------------------------------------------------


def translate_local_to_remote(
    local_path: str | Path,
    remotes: list[dict[str, Any]],
    hosts: dict[str, Any],
) -> str:
    """Translate a local path under SSH_<host> to a remote ``host:path`` string.

    Parameters
    ----------
    local_path:
        A path under an ``SSH_<host>`` namespace.
    remotes:
        The ``sources.remotes`` list from the project YAML.
    hosts:
        The host registry (``config/hosts.yml`` loaded as a dict).

    Returns
    -------
    str
        ``"<host>:<remote-path>"`` — e.g. ``"example-host:/home/operator/projects/appserver/src/app.ts"``

    Raises
    ------
    ValueError
        When the path contains no ``SSH_<host>`` component, when the host
        is not in the host registry, when no declared mount matches, or
        when more than one mount matches (ambiguity is refused).
    """
    detection = detect_ssh_namespace(local_path)
    if detection is None:
        raise ValueError(
            f"path contains no SSH_<host> component: {local_path}"
        )
    host_key, relative_suffix = detection

    # Resolve host through the registry
    if host_key not in hosts:
        raise ValueError(
            f"SSH host {host_key!r} not found in config/hosts.yml; "
            "register the host before translating paths"
        )

    # Find all remotes whose mount.namespace matches SSH_<host>
    namespace_label = f"{_SSH_PREFIX}{host_key}"
    matches: list[dict[str, Any]] = []
    for r in remotes:
        mount = r.get("mount") or {}
        if isinstance(mount, dict):
            ns = mount.get("namespace", "")
            if ns == namespace_label:
                matches.append(r)

    if not matches:
        raise ValueError(
            f"no remote declares mount.namespace={namespace_label!r}; "
            "add a mount block to the matching entry in project.yml sources.remotes[]"
        )
    if len(matches) > 1:
        names = [m.get("name", "<unnamed>") for m in matches]
        raise ValueError(
            f"ambiguous: {len(matches)} remotes declare mount.namespace={namespace_label!r} "
            f"({names!r}); make namespace labels unique per project"
        )

    remote = matches[0]
    remote_base = remote.get("path", "").rstrip("/")
    host_entry = hosts.get(host_key, {})
    ssh_alias = host_entry.get("ssh_alias") or host_key

    # Translate the relative suffix onto the remote base path.
    # The suffix from detect_ssh_namespace() is relative to the SSH_<host>
    # component (e.g. "appserver/src/index.ts" for SSH_example-host/appserver/src/…).
    # The mount label dir ("appserver" in that example) is just a local label;
    # it must be stripped before appending to the remote base path.
    #
    # Anchoring strategy:
    # - If mount.local_path is declared, strip that prefix from the full local
    #   path to get the true file-relative suffix, then append to remote_base.
    # - Otherwise strip the first component of relative_suffix (the label dir).
    mount_meta = remote.get("mount") or {}
    local_mount_path = mount_meta.get("local_path", "")

    if local_mount_path:
        # Compute what's left after the local_path mount point
        local_full = Path(local_path)
        local_mount = Path(local_mount_path)
        try:
            file_suffix = str(local_full.relative_to(local_mount))
        except ValueError:
            # Path is not under local_mount; fall through to label-strip
            file_suffix = ""
            if relative_suffix:
                suffix_parts = Path(relative_suffix).parts
                file_suffix = str(Path(*suffix_parts[1:])) if len(suffix_parts) > 1 else ""
    else:
        # Strip the first component of relative_suffix (the mount label dir)
        if relative_suffix:
            suffix_parts = Path(relative_suffix).parts
            file_suffix = str(Path(*suffix_parts[1:])) if len(suffix_parts) > 1 else ""
        else:
            file_suffix = ""

    if file_suffix and file_suffix != ".":
        remote_path = f"{remote_base}/{file_suffix}"
    else:
        remote_path = remote_base

    return f"{ssh_alias}:{remote_path}"


# ---------------------------------------------------------------------------
# Internal SSH helpers (mirrors remote_ops.py)
# ---------------------------------------------------------------------------


def _build_ssh_cmd(alias: str, ssh_options: list[str]) -> list[str]:
    """Return the base ssh command list for *alias* with *ssh_options*."""
    return ["ssh", "-o", "BatchMode=yes"] + list(ssh_options) + [alias]


def _run_remote(
    base: list[str],
    remote_cmd: str,
    *,
    runner: Runner,
    timeout: int,
) -> tuple[bool, str, str]:
    """Run *remote_cmd* on the remote host via *base* ssh args.

    Returns ``(success, stdout, stderr)``.
    """
    args = base + [remote_cmd]
    result = runner(args, timeout=timeout)
    success = result.returncode == 0
    return success, (result.stdout or ""), (result.stderr or "")


# ---------------------------------------------------------------------------
# Mount / unmount helpers
# ---------------------------------------------------------------------------


def _sshfs_command(
    ssh_alias: str,
    remote_path: str,
    local_path: str,
    ssh_options: list[str],
) -> list[str]:
    """Build the sshfs argv list for the given parameters.

    Returns an argv list — never uses shell=True.
    """
    opts = ["reconnect", "ServerAliveInterval=15", "ServerAliveCountMax=3"]
    for opt in ssh_options:
        # Forward host-level ssh_options as -o flags to sshfs
        opts.append(opt)
    opt_flags: list[str] = []
    for o in opts:
        opt_flags += ["-o", o]
    return ["sshfs", f"{ssh_alias}:{remote_path}", local_path] + opt_flags


def _unmount_command(local_path: str) -> list[str]:
    """Return the platform-appropriate unmount argv list."""
    if platform.system() == "Darwin":
        return ["umount", local_path]
    return ["fusermount", "-u", local_path]


def _default_mount_namespace(host_key: str) -> str:
    """Return the default local mount namespace path for *host_key*.

    Uses ``~/SSH_<host>`` — user-writable without sudo on both macOS and
    Linux, and the path itself contains the SSH_<host> component so it
    round-trips through detect_ssh_namespace().

    This is the chosen default (50/50 decision reported to orchestrator):
    ~/SSH_<host> wins over /Volumes/SSH_<host> because /Volumes requires
    elevated permissions and ~/SSH_<host> is writable without sudo.
    """
    return str(Path.home() / f"{_SSH_PREFIX}{host_key}")


# ---------------------------------------------------------------------------
# Public API: mount_remote
# ---------------------------------------------------------------------------


def mount_remote(
    root: str | Path,
    domain: str,
    project: str,
    *,
    name: str | None = None,
    namespace: str | None = None,
    apply: bool = False,
    runner: Runner | None = None,
    timeout: int = 20,
) -> dict[str, Any]:
    """Plan or execute an SSHFS mount for a remote project source.

    Parameters
    ----------
    root:
        The OS root directory.
    domain, project:
        Domain and project slugs.
    name:
        Remote name to mount; when ``None`` the first remote with a mount
        block is used.
    namespace:
        Override the mount namespace path (``~/SSH_<host>/<label>`` by
        default, computed from remote metadata).
    apply:
        When ``False`` (default) the function dry-runs: it prints the
        planned SSHFS command and returns without mounting anything.
        When ``True``, the command is executed only if ``sshfs`` is
        available and the destination is inside an approved
        ``SSH_<host>`` namespace path.
    runner:
        Injectable runner for tests. Defaults to ``subprocess.run``.
    timeout:
        SSH/SSHFS command timeout in seconds.

    Returns
    -------
    dict
        ``{ok, plan, applied, errors, warnings}``
    """
    if runner is None:
        runner = _default_runner

    os_root = expand_path(root)
    project_root = domain_path(os_root, domain) / "02-projects" / project
    project_yml = project_root / "project.yml"

    if not project_yml.is_file():
        return {
            "ok": False,
            "plan": [],
            "applied": False,
            "errors": [f"project.yml not found: {project_yml}"],
            "warnings": [],
        }

    try:
        data = yaml.safe_load(project_yml.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return {
            "ok": False,
            "plan": [],
            "applied": False,
            "errors": [f"project.yml malformed: {exc}"],
            "warnings": [],
        }

    remotes = _remotes_from_yaml(data)
    try:
        hosts = load_hosts(os_root)
    except Exception:
        hosts = {}

    # Select target remote
    mount_remotes = [r for r in remotes if r.get("mount")]
    if name is not None:
        mount_remotes = [r for r in mount_remotes if r.get("name") == name]

    if not mount_remotes:
        label = f"named {name!r} " if name else ""
        return {
            "ok": False,
            "plan": [],
            "applied": False,
            "errors": [
                f"no remote {label}with a mount block found in {project_yml}"
            ],
            "warnings": [],
        }

    errors: list[str] = []
    warnings: list[str] = []
    plan: list[str] = []
    applied = False

    for remote in mount_remotes:
        rname = remote.get("name", project)
        host_key = remote.get("host", "")
        remote_path = remote.get("path", "")
        mount_meta = remote.get("mount") or {}

        host_entry = hosts.get(host_key, {})
        ssh_alias = host_entry.get("ssh_alias") or host_key
        ssh_options: list[str] = host_entry.get("ssh_options") or []

        # Resolve local mount path
        if namespace:
            local_mount = namespace
        elif mount_meta.get("local_path"):
            local_mount = str(mount_meta["local_path"])
        else:
            label = mount_meta.get("namespace") or f"{_SSH_PREFIX}{host_key}"
            local_mount = str(Path.home() / label / rname)

        # Validate the local_mount is inside an approved SSH_<host> namespace
        detection = detect_ssh_namespace(local_mount)
        if detection is None:
            errors.append(
                f"remote {rname!r}: local mount path {local_mount!r} does not "
                "contain an SSH_<host> component; refusing to mount outside an "
                "approved namespace"
            )
            continue

        cmd = _sshfs_command(ssh_alias, remote_path, local_mount, ssh_options)
        plan_line = " ".join(shlex.quote(a) for a in cmd)
        plan.append(f"# remote: {rname} ({host_key}:{remote_path} -> {local_mount})")
        plan.append(plan_line)

        if apply:
            if shutil.which("sshfs") is None:
                errors.append(
                    f"remote {rname!r}: sshfs not found on PATH; "
                    "install sshfs (and macFUSE on macOS) before using --apply"
                )
                continue
            Path(local_mount).mkdir(parents=True, exist_ok=True)
            try:
                result = runner(cmd, timeout=timeout)
                if result.returncode == 0:
                    applied = True
                    plan.append(f"# mounted ok: {local_mount}")
                else:
                    errors.append(
                        f"remote {rname!r}: sshfs exited {result.returncode}: "
                        f"{(result.stderr or '').strip()}"
                    )
            except Exception as exc:
                errors.append(f"remote {rname!r}: sshfs error — {exc}")

    ok = len(errors) == 0
    return {
        "ok": ok,
        "plan": plan,
        "applied": applied,
        "errors": errors,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Public API: unmount_remote
# ---------------------------------------------------------------------------


def unmount_remote(
    root: str | Path,
    domain: str,
    project: str,
    *,
    name: str | None = None,
    apply: bool = False,
    runner: Runner | None = None,
    timeout: int = 20,
) -> dict[str, Any]:
    """Plan or execute an SSHFS unmount for a remote project source.

    Dry-run by default.  With ``--apply`` uses the platform-appropriate
    unmount command (``umount`` on macOS, ``fusermount -u`` on Linux).
    Never installs system software.
    """
    if runner is None:
        runner = _default_runner

    os_root = expand_path(root)
    project_root = domain_path(os_root, domain) / "02-projects" / project
    project_yml = project_root / "project.yml"

    if not project_yml.is_file():
        return {
            "ok": False,
            "plan": [],
            "applied": False,
            "errors": [f"project.yml not found: {project_yml}"],
            "warnings": [],
        }

    try:
        data = yaml.safe_load(project_yml.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return {
            "ok": False,
            "plan": [],
            "applied": False,
            "errors": [f"project.yml malformed: {exc}"],
            "warnings": [],
        }

    remotes = _remotes_from_yaml(data)
    mount_remotes = [r for r in remotes if r.get("mount")]
    if name is not None:
        mount_remotes = [r for r in mount_remotes if r.get("name") == name]

    if not mount_remotes:
        label = f"named {name!r} " if name else ""
        return {
            "ok": False,
            "plan": [],
            "applied": False,
            "errors": [
                f"no remote {label}with a mount block found in {project_yml}"
            ],
            "warnings": [],
        }

    errors: list[str] = []
    warnings: list[str] = []
    plan: list[str] = []
    applied = False

    for remote in mount_remotes:
        rname = remote.get("name", project)
        host_key = remote.get("host", "")
        mount_meta = remote.get("mount") or {}

        if mount_meta.get("local_path"):
            local_mount = str(mount_meta["local_path"])
        else:
            label = mount_meta.get("namespace") or f"{_SSH_PREFIX}{host_key}"
            local_mount = str(Path.home() / label / rname)

        cmd = _unmount_command(local_mount)
        plan_line = " ".join(shlex.quote(a) for a in cmd)
        plan.append(f"# remote: {rname} (unmount {local_mount})")
        plan.append(plan_line)

        if apply:
            try:
                result = runner(cmd, timeout=timeout)
                if result.returncode == 0:
                    applied = True
                    plan.append(f"# unmounted ok: {local_mount}")
                else:
                    errors.append(
                        f"remote {rname!r}: unmount exited {result.returncode}: "
                        f"{(result.stderr or '').strip()}"
                    )
            except Exception as exc:
                errors.append(f"remote {rname!r}: unmount error — {exc}")

    ok = len(errors) == 0
    return {
        "ok": ok,
        "plan": plan,
        "applied": applied,
        "errors": errors,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Public API: exec_remote
# ---------------------------------------------------------------------------


def exec_remote(
    root: str | Path,
    domain: str,
    project: str,
    command: list[str],
    *,
    name: str | None = None,
    runner: Runner | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    """Run *command* on the remote host for a remote-authoritative project.

    Uses ``ssh -o BatchMode=yes <host> 'cd <remote-path> && <command>'``.
    Does NOT depend on SSHFS being mounted — it works from project metadata alone.
    No shell=True locally; the remote command string is built with shlex.quote.

    Parameters
    ----------
    root, domain, project:
        OS root directory and project coordinates.
    command:
        The command to run remotely as a list of strings, e.g.
        ``["git", "status"]`` or ``["pnpm", "test"]``.
    name:
        Which declared remote to use.  When ``None`` uses the first
        remote with ``authority == "remote"`` (or the first remote).
    runner:
        Injectable runner for tests.
    timeout:
        SSH command timeout in seconds.

    Returns
    -------
    dict
        ``{ok, stdout, stderr, returncode, host, remote_path, errors}``
    """
    if runner is None:
        runner = _default_runner

    os_root = expand_path(root)
    project_root = domain_path(os_root, domain) / "02-projects" / project
    project_yml = project_root / "project.yml"

    if not project_yml.is_file():
        return {
            "ok": False,
            "stdout": "",
            "stderr": "",
            "returncode": -1,
            "host": "",
            "remote_path": "",
            "errors": [f"project.yml not found: {project_yml}"],
        }

    try:
        data = yaml.safe_load(project_yml.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return {
            "ok": False,
            "stdout": "",
            "stderr": "",
            "returncode": -1,
            "host": "",
            "remote_path": "",
            "errors": [f"project.yml malformed: {exc}"],
        }

    remotes = _remotes_from_yaml(data)
    try:
        hosts = load_hosts(os_root)
    except Exception:
        hosts = {}

    # Select target remote
    candidates = remotes
    if name is not None:
        candidates = [r for r in remotes if r.get("name") == name]
    if not candidates:
        label = f"named {name!r}" if name else "any"
        return {
            "ok": False,
            "stdout": "",
            "stderr": "",
            "returncode": -1,
            "host": "",
            "remote_path": "",
            "errors": [f"no remote {label} found in {project_yml}"],
        }

    # Prefer a remote with authority=remote; fall back to first
    remote = next(
        (r for r in candidates if r.get("authority", "remote") == "remote"),
        candidates[0],
    )

    host_key = remote.get("host", "")
    remote_path = remote.get("path", "")
    host_entry = hosts.get(host_key, {})
    ssh_alias = host_entry.get("ssh_alias") or host_key
    ssh_options: list[str] = host_entry.get("ssh_options") or []

    qpath = shlex.quote(remote_path)
    remote_cmd_str = f"cd {qpath} && " + " ".join(shlex.quote(c) for c in command)
    base = _build_ssh_cmd(ssh_alias, ssh_options)
    args = base + [remote_cmd_str]

    try:
        result = runner(args, timeout=timeout)
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "returncode": result.returncode,
            "host": ssh_alias,
            "remote_path": remote_path,
            "errors": [],
        }
    except Exception as exc:
        return {
            "ok": False,
            "stdout": "",
            "stderr": "",
            "returncode": -1,
            "host": ssh_alias,
            "remote_path": remote_path,
            "errors": [f"SSH error — {exc}"],
        }


# ---------------------------------------------------------------------------
# Public API: doctor_remote_mounts
# ---------------------------------------------------------------------------


def doctor_remote_mounts(
    root: str | Path,
    domain: str,
    project: str,
    *,
    check_mounts: bool = False,
    runner: Runner | None = None,
    timeout: int = 20,
) -> dict[str, Any]:
    """Run offline (and optionally live) checks on remote mount declarations.

    Offline checks (always run):
    - project.yml is readable and has ``sources.remotes`` entries
    - each remote with a mount block has ``host`` present in config/hosts.yml
    - ``mount.namespace`` matches the ``SSH_<host>`` convention for the declared host
    - ``mount.local_path`` when declared is under an ``SSH_<host>`` namespace
    - no two remotes declare the same ``mount.namespace`` (ambiguity guard)

    Live checks (only with ``check_mounts=True``):
    - probe the remote host to see if it is reachable

    Parameters
    ----------
    root, domain, project:
        OS root directory and project coordinates.
    check_mounts:
        When ``True``, also probe live mount health over SSH.
    runner:
        Injectable runner for tests.
    timeout:
        SSH timeout for live checks.

    Returns
    -------
    dict
        ``{ok, findings, errors, warnings}``
        Each finding is ``{level: "ok"|"warn"|"error", message: str}``.
    """
    if runner is None:
        runner = _default_runner

    os_root = expand_path(root)
    project_root = domain_path(os_root, domain) / "02-projects" / project
    project_yml = project_root / "project.yml"

    findings: list[dict[str, str]] = []
    errors: list[str] = []
    warnings: list[str] = []

    def _finding(level: str, msg: str) -> None:
        findings.append({"level": level, "message": msg})

    if not project_yml.is_file():
        errors.append(f"project.yml not found: {project_yml}")
        return {"ok": False, "findings": findings, "errors": errors, "warnings": warnings}

    try:
        data = yaml.safe_load(project_yml.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        errors.append(f"project.yml malformed: {exc}")
        return {"ok": False, "findings": findings, "errors": errors, "warnings": warnings}

    remotes = _remotes_from_yaml(data)
    try:
        hosts = load_hosts(os_root)
    except Exception:
        hosts = {}

    mount_remotes = [r for r in remotes if r.get("mount")]
    if not mount_remotes:
        _finding("ok", "no remotes with mount blocks declared (feature 63 marker-file baseline)")
        return {"ok": True, "findings": findings, "errors": errors, "warnings": warnings}

    # Check for namespace uniqueness across remotes
    namespace_seen: dict[str, str] = {}
    for r in mount_remotes:
        rname = r.get("name", "<unnamed>")
        mount = r.get("mount") or {}
        ns = mount.get("namespace", "")
        if ns:
            if ns in namespace_seen:
                _finding(
                    "error",
                    f"ambiguous: both {namespace_seen[ns]!r} and {rname!r} declare "
                    f"mount.namespace={ns!r}; translate_local_to_remote will refuse",
                )
            else:
                namespace_seen[ns] = rname

    for r in mount_remotes:
        rname = r.get("name", "<unnamed>")
        host_key = r.get("host", "")
        mount = r.get("mount") or {}
        ns = mount.get("namespace", "")
        local_path = mount.get("local_path", "")

        # host must be in hosts.yml
        if host_key not in hosts:
            _finding(
                "error",
                f"remote {rname!r}: host {host_key!r} not found in config/hosts.yml",
            )
        else:
            _finding("ok", f"remote {rname!r}: host {host_key!r} found in config/hosts.yml")

        # namespace must match SSH_<host> convention
        expected_ns = f"{_SSH_PREFIX}{host_key}"
        if ns and ns != expected_ns:
            _finding(
                "warn",
                f"remote {rname!r}: mount.namespace={ns!r} does not match expected "
                f"{expected_ns!r} for host {host_key!r}",
            )
        elif not ns:
            _finding(
                "warn",
                f"remote {rname!r}: mount.namespace not declared; will default to {expected_ns!r}",
            )
        else:
            _finding("ok", f"remote {rname!r}: mount.namespace={ns!r} matches convention")

        # local_path when declared must be under an SSH_<host> component
        if local_path:
            if detect_ssh_namespace(local_path) is None:
                _finding(
                    "error",
                    f"remote {rname!r}: mount.local_path={local_path!r} does not contain "
                    "an SSH_<host> component; path translation will fail",
                )
            else:
                _finding("ok", f"remote {rname!r}: mount.local_path is inside SSH namespace")

        # Live: probe SSH reachability
        if check_mounts and host_key:
            host_entry = hosts.get(host_key, {})
            ssh_alias = host_entry.get("ssh_alias") or host_key
            ssh_options: list[str] = host_entry.get("ssh_options") or []
            remote_path = r.get("path", "")
            base = _build_ssh_cmd(ssh_alias, ssh_options)
            try:
                ok_probe, _, _ = _run_remote(
                    base,
                    f"test -e {shlex.quote(remote_path)}",
                    runner=runner,
                    timeout=timeout,
                )
                if ok_probe:
                    _finding("ok", f"remote {rname!r}: host reachable and remote path exists")
                else:
                    _finding(
                        "warn",
                        f"remote {rname!r}: host reachable but remote path {remote_path!r} "
                        "not found or test failed",
                    )
            except Exception as exc:
                _finding("warn", f"remote {rname!r}: host probe error — {exc}")

    has_errors = any(f["level"] == "error" for f in findings) or bool(errors)
    return {
        "ok": not has_errors,
        "findings": findings,
        "errors": errors,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Scaffold rule snippet (used by scaffold.py extension)
# ---------------------------------------------------------------------------


def ssh_namespace_rules_section() -> str:
    """Return the managed SSH_<host> convention rule section for AGENTS.md / RULES.md."""
    return (
        "\n## SSH Remote Namespace Rule\n\n"
        "Any path component named `SSH_<host>` is an SSHFS remote namespace. "
        "Files under it may be read or edited locally, but repo commands run on "
        "`<host>` with the remote cwd from the project manifest. "
        "Do not run builds, tests, package installs, git, or watchers locally "
        "from an SSHFS path unless the operator explicitly asks for local-mount execution.\n"
    )
