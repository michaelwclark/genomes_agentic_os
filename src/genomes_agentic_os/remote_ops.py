"""Sync engine for remote SSH project sources (feature 63, P2).

Refreshes ``remote/<name>/manifest.yml`` for every declared remote in a project
by running read-only SSH commands against the configured host.  No interactive
SSH, no shell=True, no secrets in arguments.

Injectable runner
-----------------
The public function ``sync_project_remote`` accepts an optional *runner*
callable so tests never open real SSH connections::

    def fake_runner(args, *, timeout):
        return FakeResult(stdout="main\\nabc123\\n", returncode=0)

    result = sync_project_remote(root, domain, project, runner=fake_runner)

The default runner wraps ``subprocess.run`` with ``capture_output=True,
text=True`` and the caller-supplied timeout.
"""

from __future__ import annotations

import datetime
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any, Callable

import yaml

from .hosts import load_hosts
from .scaffold import _remotes_from_config, domain_path, expand_path

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Runner = Callable[[list[str], Any], Any]  # (args, *, timeout) -> CompletedProcess-like


# ---------------------------------------------------------------------------
# Default runner (real subprocess — never used in tests)
# ---------------------------------------------------------------------------

def _default_runner(args: list[str], *, timeout: int = 20) -> Any:
    """Run *args* via subprocess and return the CompletedProcess."""
    return subprocess.run(  # noqa: S603
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_base_cmd(alias: str, ssh_options: list[str]) -> list[str]:
    """Return the base ssh command list for *alias* with *ssh_options*."""
    return ["ssh", "-o", "BatchMode=yes"] + list(ssh_options) + [alias]


def _run_remote(
    base: list[str],
    remote_cmd: str,
    *,
    runner: Runner,
    timeout: int,
) -> tuple[bool, str, str]:
    """Run *remote_cmd* on the remote host.

    Returns (success, stdout, stderr).  Raises SubprocessError / TimeoutExpired
    only for the caller to catch; callers treat any exception as unreachable.
    """
    args = base + [remote_cmd]
    result = runner(args, timeout=timeout)
    success = result.returncode == 0
    return success, (result.stdout or ""), (result.stderr or "")


def _gather_git_info(
    base: list[str],
    remote_path: str,
    *,
    runner: Runner,
    timeout: int,
) -> dict[str, Any] | None:
    """Collect branch / head / dirty via SSH git commands.

    Returns None when any command fails (treat as unreachable).
    """
    qpath = shlex.quote(remote_path)

    ok, branch_out, _ = _run_remote(
        base,
        f"git -C {qpath} rev-parse --abbrev-ref HEAD",
        runner=runner,
        timeout=timeout,
    )
    if not ok:
        return None
    branch = branch_out.strip()

    ok, sha_out, _ = _run_remote(
        base,
        f"git -C {qpath} rev-parse HEAD",
        runner=runner,
        timeout=timeout,
    )
    if not ok:
        return None
    head = sha_out.strip()

    ok, status_out, _ = _run_remote(
        base,
        f"git -C {qpath} status --porcelain",
        runner=runner,
        timeout=timeout,
    )
    if not ok:
        return None
    dirty = bool(status_out.strip())

    return {"branch": branch, "head": head, "dirty": dirty}


def _gather_listing(
    base: list[str],
    remote_path: str,
    *,
    runner: Runner,
    timeout: int,
) -> tuple[list[str], bool]:
    """Return (entries, truncated) from a depth-1 ls on the remote path."""
    qpath = shlex.quote(remote_path)
    ok, out, _ = _run_remote(
        base,
        f"ls -1A {qpath}",
        runner=runner,
        timeout=timeout,
    )
    if not ok:
        return [], False
    entries = [e for e in out.splitlines() if e]
    truncated = len(entries) > 200
    return entries[:200], truncated


def _load_existing_manifest(manifest_path: Path) -> dict[str, Any]:
    """Load manifest.yml if it exists, else return empty dict."""
    if not manifest_path.is_file():
        return {}
    try:
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError:
        return {}


def _write_manifest(manifest_path: Path, payload: dict[str, Any]) -> None:
    """Write *payload* to *manifest_path* as YAML."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _update_source_map_row(
    source_map: Path,
    remote: dict[str, str],
    date_label: str,
) -> None:
    """Update the source-map row for *remote* in-place, idempotently.

    The row written by ``append_project_remote_refs`` looks like:
        | Remote (host) | host:path | purpose | pending sync |

    We replace the last cell with ``synced YYYY-MM-DD`` or
    ``unreachable YYYY-MM-DD`` idempotently (any subsequent sync just updates
    the date).
    """
    if not source_map.is_file():
        return
    host = remote.get("host", "")
    path = remote.get("path", "")
    text = source_map.read_text(encoding="utf-8")
    # Match any row that starts with "| Remote (<host>) | <host>:<path> |"
    prefix_re = re.compile(
        r"(\| Remote \("
        + re.escape(host)
        + r"\) \| "
        + re.escape(host)
        + ":"
        + re.escape(path)
        + r" \| [^|]* \| )[^|]*(\|)",
        re.MULTILINE,
    )
    updated = prefix_re.sub(r"\g<1>" + date_label + r" \g<2>", text)
    if updated != text:
        source_map.write_text(updated, encoding="utf-8")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def sync_project_remote(
    root: str | Path,
    domain: str,
    project: str,
    *,
    name: str | None = None,
    timeout: int = 20,
    runner: Runner | None = None,
) -> dict[str, Any]:
    """Refresh manifest.yml for all matching remotes in *project*.

    Parameters
    ----------
    root:
        The OS root directory.
    domain:
        Domain slug (e.g. ``"work"``).
    project:
        Project slug (e.g. ``"appserver"``).
    name:
        When given, sync only the remote with this name; otherwise sync all.
    timeout:
        SSH command timeout in seconds.
    runner:
        Injectable runner callable ``(args: list[str], *, timeout: int) ->
        CompletedProcess-like``.  Defaults to ``subprocess.run``.

    Returns
    -------
    dict
        ``{synced: [name, ...], warnings: [str, ...], errors: [str, ...]}``.
        Exit-0 semantics: unreachable hosts are *warnings*, not errors.
    """
    if runner is None:
        runner = _default_runner

    os_root = expand_path(root)
    project_root = domain_path(os_root, domain) / "02-projects" / project

    # Load project.yml
    project_yml = project_root / "project.yml"
    if not project_yml.is_file():
        return {
            "synced": [],
            "warnings": [],
            "errors": [f"project.yml not found: {project_yml}"],
        }
    try:
        data = yaml.safe_load(project_yml.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return {
            "synced": [],
            "warnings": [],
            "errors": [f"project.yml malformed ({project_yml}): {exc}"],
        }

    remotes = _remotes_from_config(data)
    if name is not None:
        remotes = [r for r in remotes if r.get("name") == name]
        if not remotes:
            return {
                "synced": [],
                "warnings": [],
                "errors": [f"no remote named {name!r} in {project_yml}"],
            }

    # Load the hosts registry (fall back gracefully if absent)
    try:
        hosts = load_hosts(os_root)
    except Exception:
        hosts = {}

    source_map = project_root / "source-map.md"
    synced: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    synced_at_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    date_str = now_utc.strftime("%Y-%m-%d")

    for remote in remotes:
        rname = remote.get("name", project)
        host_key = remote.get("host", "")
        remote_path = remote.get("path", "")
        kind = remote.get("kind", "git")
        authority = remote.get("authority", "remote")
        manifest_path = project_root / "remote" / rname / "manifest.yml"

        # Resolve host entry; fall back to using host_key as the ssh alias
        host_entry = hosts.get(host_key, {})
        ssh_alias = host_entry.get("ssh_alias") or host_key
        ssh_options: list[str] = host_entry.get("ssh_options") or []

        base_cmd = _build_base_cmd(ssh_alias, ssh_options)
        existing = _load_existing_manifest(manifest_path)

        try:
            reachable: bool
            git_info: dict[str, Any] | None = None
            listing: list[str] = []
            listing_truncated = False

            if kind == "git":
                git_info = _gather_git_info(
                    base_cmd, remote_path, runner=runner, timeout=timeout
                )
                if git_info is None:
                    reachable = False
                else:
                    reachable = True
                    listing, listing_truncated = _gather_listing(
                        base_cmd, remote_path, runner=runner, timeout=timeout
                    )
            else:
                # folder kind: only listing
                listing, listing_truncated = _gather_listing(
                    base_cmd, remote_path, runner=runner, timeout=timeout
                )
                # A successful listing with returncode=0 means reachable;
                # but _gather_listing swallows errors.  We do a quick probe.
                probe_ok, _, _ = _run_remote(
                    base_cmd,
                    f"test -d {shlex.quote(remote_path)}",
                    runner=runner,
                    timeout=timeout,
                )
                reachable = probe_ok

        except Exception as exc:
            reachable = False
            warnings.append(
                f"remote {rname!r} (host={host_key!r}): SSH error — {exc}"
            )

        # Build payload
        payload: dict[str, Any] = {
            "name": rname,
            "host": host_key,
            "path": remote_path,
            "kind": kind,
            "authority": authority,
            "reachable": reachable,
            "synced_at": synced_at_str,
        }

        if reachable:
            if git_info is not None:
                payload["git"] = git_info
            payload["listing"] = listing
            if listing_truncated:
                payload["listing_truncated"] = True
            date_label = f"synced {date_str}"
        else:
            # Keep prior git/listing if present
            if "git" in existing:
                payload["git"] = existing["git"]
            if "listing" in existing:
                payload["listing"] = existing["listing"]
            if existing.get("listing_truncated"):
                payload["listing_truncated"] = True
            date_label = f"unreachable {date_str}"
            if not any(rname in w for w in warnings):
                warnings.append(
                    f"remote {rname!r} (host={host_key!r}): host unreachable; "
                    "manifest marked reachable=false"
                )

        _write_manifest(manifest_path, payload)
        _update_source_map_row(source_map, remote, date_label)
        synced.append(rname)

    return {"synced": synced, "warnings": warnings, "errors": errors}
