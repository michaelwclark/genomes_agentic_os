"""Tests for feature 64: SSHFS Remote Mount Namespaces.

All tests run OFFLINE — no real SSH connections, no real SSHFS mounts,
no network access.  External processes are replaced with fake runners.

Acceptance criteria covered:
  AC1 — detect_ssh_namespace: path detection without directory scanning
  AC2 — Feature 63 mount-field additions are optional and additive;
         existing test_remote_sources.py must still pass (separate run)
  AC3 — exec_remote works from metadata alone, no mount required
  AC4 — translate_local_to_remote: deterministic, refuses ambiguity
  AC5 — scaffold adds SSH_<host> rule section when remotes have mount blocks
  AC6 — doctor_remote_mounts: offline metadata validation + opt-in live probe
  AC7 — mount_remote / unmount_remote: dry-run default, --apply guard
  AC8 — full suite passes (verified by pytest run)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from genomes_agentic_os.remote_mounts import (
    detect_ssh_namespace,
    doctor_remote_mounts,
    exec_remote,
    mount_remote,
    translate_local_to_remote,
    unmount_remote,
    ssh_namespace_rules_section,
)
from genomes_agentic_os.scaffold import (
    project_agents,
    project_rules,
    _ssh_namespace_rule_section,
)
from genomes_agentic_os.cli import main


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


def _fake_runner_ok(args: list[str], *, timeout: int = 20) -> FakeResult:
    """Fake runner that always succeeds."""
    return FakeResult(returncode=0, stdout="ok\n")


def _fake_runner_fail(args: list[str], *, timeout: int = 20) -> FakeResult:
    """Fake runner that always fails."""
    return FakeResult(returncode=1, stdout="", stderr="connection refused\n")


def _fake_runner_git(args: list[str], *, timeout: int = 20) -> FakeResult:
    """Fake runner simulating git output for exec_remote tests."""
    if "git" in args[-1] and "status" in args[-1]:
        return FakeResult(returncode=0, stdout=" M src/index.ts\n")
    return FakeResult(returncode=0, stdout="main\nabc123\n")


def _init_root(tmp_path: Path) -> Path:
    """Initialise a minimal OS root with a hosts.yml."""
    assert main(["init", "--target", str(tmp_path)]) == 0
    hosts_file = tmp_path / "config" / "hosts.yml"
    hosts_file.parent.mkdir(parents=True, exist_ok=True)
    hosts_file.write_text(
        "hosts:\n  genomesbox:\n    ssh_alias: genomesbox\n    ssh_options: []\n",
        encoding="utf-8",
    )
    return tmp_path


def _make_project(
    root: Path,
    domain: str = "acme",
    project: str = "losmon",
    with_mount: bool = False,
) -> Path:
    """Create a domain + project and return the project root path."""
    assert main(["domain", "create", domain, "--root", str(root)]) == 0
    assert main(["project", "create", domain, project, "--root", str(root)]) == 0
    project_root = root / "domains" / domain / "02-projects" / project
    if with_mount:
        # Write a project.yml with a remote that has a mount block
        project_yml = project_root / "project.yml"
        data = yaml.safe_load(project_yml.read_text(encoding="utf-8")) or {}
        data.setdefault("sources", {})["remotes"] = [
            {
                "name": project,
                "host": "genomesbox",
                "path": f"/home/genome/projects/{project}",
                "kind": "git",
                "authority": "remote",
                "mount": {
                    "namespace": "SSH_genomesbox",
                    "local_path": str(root / "SSH_genomesbox" / project),
                    "access": "sshfs",
                    "execution": "remote",
                },
            }
        ]
        project_yml.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    return project_root


def _make_project_without_mount(
    root: Path,
    domain: str = "acme",
    project: str = "losmon",
) -> Path:
    """Create a project with a remote but NO mount block (feature 63 baseline)."""
    assert main(["domain", "create", domain, "--root", str(root)]) == 0
    assert main(["project", "create", domain, project, "--root", str(root)]) == 0
    project_root = root / "domains" / domain / "02-projects" / project
    project_yml = project_root / "project.yml"
    data = yaml.safe_load(project_yml.read_text(encoding="utf-8")) or {}
    data.setdefault("sources", {})["remotes"] = [
        {
            "name": project,
            "host": "genomesbox",
            "path": f"/home/genome/projects/{project}",
            "kind": "git",
            "authority": "remote",
        }
    ]
    project_yml.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return project_root


# ---------------------------------------------------------------------------
# AC1: detect_ssh_namespace
# ---------------------------------------------------------------------------


class TestDetectSshNamespace:
    def test_detects_ssh_component_mid_path(self):
        result = detect_ssh_namespace("/Users/genome/SSH_genomesbox/losmon/src/app.ts")
        assert result == ("genomesbox", "losmon/src/app.ts")

    def test_detects_ssh_component_direct_child(self):
        result = detect_ssh_namespace("/home/genome/SSH_genomesbox/losmon")
        assert result == ("genomesbox", "losmon")

    def test_detects_ssh_component_at_root(self):
        # pathological but valid
        result = detect_ssh_namespace("/SSH_myhost/project/file.py")
        assert result == ("myhost", "project/file.py")

    def test_returns_none_for_normal_path(self):
        assert detect_ssh_namespace("/Users/genome/projects/losmon") is None

    def test_returns_none_for_ssh_prefix_only(self):
        # SSH_ with nothing after it is not a valid host marker
        assert detect_ssh_namespace("/Users/genome/SSH_/losmon") is None

    def test_returns_empty_suffix_when_ssh_is_leaf(self):
        result = detect_ssh_namespace("/Users/genome/SSH_genomesbox")
        assert result is not None
        host, suffix = result
        assert host == "genomesbox"
        assert suffix == ""

    def test_uses_nearest_component(self):
        # When multiple SSH_ components exist, the first (nearest) one wins
        result = detect_ssh_namespace("/mnt/SSH_hostA/SSH_hostB/file.txt")
        assert result is not None
        host, suffix = result
        assert host == "hostA"
        assert "SSH_hostB" in suffix

    def test_tilde_path(self, tmp_path: Path):
        p = tmp_path / "SSH_genomesbox" / "losmon" / "src"
        result = detect_ssh_namespace(str(p))
        assert result is not None
        host, suffix = result
        assert host == "genomesbox"
        assert suffix == "losmon/src"


# ---------------------------------------------------------------------------
# AC4: translate_local_to_remote
# ---------------------------------------------------------------------------


class TestTranslateLocalToRemote:
    def _remotes(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "losmon",
                "host": "genomesbox",
                "path": "/home/genome/projects/losmon",
                "kind": "git",
                "authority": "remote",
                "mount": {
                    "namespace": "SSH_genomesbox",
                    "local_path": "/Users/genome/SSH_genomesbox/losmon",
                    "access": "sshfs",
                    "execution": "remote",
                },
            }
        ]

    def _hosts(self) -> dict[str, Any]:
        return {"genomesbox": {"ssh_alias": "genomesbox", "ssh_options": []}}

    def test_translates_file_path(self):
        result = translate_local_to_remote(
            "/Users/genome/SSH_genomesbox/losmon/src/index.ts",
            self._remotes(),
            self._hosts(),
        )
        # local_path="/Users/genome/SSH_genomesbox/losmon" is the mount point;
        # the file suffix relative to that mount point is "src/index.ts",
        # which is appended to the remote base path (not the label dir "losmon").
        assert result == "genomesbox:/home/genome/projects/losmon/src/index.ts"

    def test_translates_root_path(self):
        result = translate_local_to_remote(
            "/Users/genome/SSH_genomesbox/losmon",
            self._remotes(),
            self._hosts(),
        )
        # The local path IS the mount point — relative_to gives "." which
        # collapses to the remote base path exactly.
        assert result == "genomesbox:/home/genome/projects/losmon"

    def test_raises_when_no_ssh_component(self):
        with pytest.raises(ValueError, match="no SSH_<host> component"):
            translate_local_to_remote(
                "/Users/genome/projects/losmon/src/index.ts",
                self._remotes(),
                self._hosts(),
            )

    def test_raises_when_host_not_in_registry(self):
        with pytest.raises(ValueError, match="not found in config/hosts.yml"):
            translate_local_to_remote(
                "/Users/genome/SSH_unknownhost/losmon/file.ts",
                self._remotes(),
                {},  # empty hosts registry
            )

    def test_raises_when_no_matching_remote(self):
        with pytest.raises(ValueError, match="no remote declares"):
            translate_local_to_remote(
                "/Users/genome/SSH_genomesbox/losmon/file.ts",
                [],  # no remotes
                self._hosts(),
            )

    def test_raises_on_ambiguous_match(self):
        # Two remotes declare the same namespace — must refuse
        ambiguous_remotes = [
            {
                "name": "losmon",
                "host": "genomesbox",
                "path": "/home/genome/projects/losmon",
                "mount": {"namespace": "SSH_genomesbox"},
            },
            {
                "name": "ledgerline",
                "host": "genomesbox",
                "path": "/home/genome/projects/ledgerline",
                "mount": {"namespace": "SSH_genomesbox"},
            },
        ]
        with pytest.raises(ValueError, match="ambiguous"):
            translate_local_to_remote(
                "/Users/genome/SSH_genomesbox/losmon/file.ts",
                ambiguous_remotes,
                self._hosts(),
            )

    def test_uses_ssh_alias_from_hosts(self):
        hosts_with_alias = {
            "genomesbox": {"ssh_alias": "gb.example.com", "ssh_options": []}
        }
        result = translate_local_to_remote(
            "/Users/genome/SSH_genomesbox/losmon",
            self._remotes(),
            hosts_with_alias,
        )
        assert result.startswith("gb.example.com:")


# ---------------------------------------------------------------------------
# AC3: exec_remote (works without SSHFS mount)
# ---------------------------------------------------------------------------


class TestExecRemote:
    def test_exec_calls_ssh_with_cd_and_command(self, tmp_path: Path):
        root = _init_root(tmp_path)
        _make_project_without_mount(root)
        captured: list[list[str]] = []

        def capture_runner(args: list[str], *, timeout: int = 60) -> FakeResult:
            captured.append(args)
            return FakeResult(returncode=0, stdout="clean\n")

        result = exec_remote(
            root, "acme", "losmon",
            ["git", "status"],
            runner=capture_runner,
        )
        assert result["ok"] is True
        assert result["returncode"] == 0
        assert result["stdout"] == "clean\n"
        assert len(captured) == 1
        # Must use BatchMode=yes
        assert "-o" in captured[0]
        assert "BatchMode=yes" in captured[0]
        # Remote command must have cd + the quoted command
        remote_cmd = captured[0][-1]
        assert "cd " in remote_cmd
        assert "git" in remote_cmd
        assert "status" in remote_cmd

    def test_exec_does_not_require_mount(self, tmp_path: Path):
        """exec_remote works even when no mount block is declared."""
        root = _init_root(tmp_path)
        _make_project_without_mount(root)

        result = exec_remote(
            root, "acme", "losmon",
            ["echo", "hello"],
            runner=_fake_runner_ok,
        )
        assert result["ok"] is True

    def test_exec_returns_error_on_missing_project(self, tmp_path: Path):
        result = exec_remote(
            tmp_path, "acme", "nonexistent",
            ["git", "status"],
            runner=_fake_runner_ok,
        )
        assert result["ok"] is False
        assert result["errors"]

    def test_exec_reports_ssh_failure(self, tmp_path: Path):
        root = _init_root(tmp_path)
        _make_project_without_mount(root)

        result = exec_remote(
            root, "acme", "losmon",
            ["git", "status"],
            runner=_fake_runner_fail,
        )
        assert result["ok"] is False
        assert result["returncode"] == 1

    def test_exec_selects_by_name(self, tmp_path: Path):
        root = _init_root(tmp_path)
        project_root = _make_project_without_mount(root)
        project_yml = project_root / "project.yml"
        data = yaml.safe_load(project_yml.read_text()) or {}
        data["sources"]["remotes"].append({
            "name": "staging",
            "host": "genomesbox",
            "path": "/home/genome/staging/losmon",
            "kind": "git",
            "authority": "remote",
        })
        project_yml.write_text(yaml.safe_dump(data, sort_keys=False))

        captured: list[list[str]] = []

        def capture_runner(args: list[str], *, timeout: int = 60) -> FakeResult:
            captured.append(args)
            return FakeResult(returncode=0, stdout="")

        exec_remote(root, "acme", "losmon", ["git", "log"], name="staging", runner=capture_runner)
        assert len(captured) == 1
        assert "staging" in captured[0][-1]


# ---------------------------------------------------------------------------
# AC5: scaffold SSH_<host> rule section
# ---------------------------------------------------------------------------


class TestScaffoldSshRules:
    def _remotes_with_mount(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "losmon",
                "host": "genomesbox",
                "path": "/home/genome/projects/losmon",
                "mount": {"namespace": "SSH_genomesbox"},
            }
        ]

    def _remotes_without_mount(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "losmon",
                "host": "genomesbox",
                "path": "/home/genome/projects/losmon",
            }
        ]

    def test_ssh_section_included_when_mount_declared(self):
        section = _ssh_namespace_rule_section(self._remotes_with_mount())
        assert "SSH_<host>" in section
        assert "repo commands run on" in section

    def test_ssh_section_empty_when_no_mount(self):
        section = _ssh_namespace_rule_section(self._remotes_without_mount())
        assert section == ""

    def test_ssh_section_empty_when_no_remotes(self):
        assert _ssh_namespace_rule_section(None) == ""
        assert _ssh_namespace_rule_section([]) == ""

    def test_project_rules_includes_ssh_section_with_mount(self):
        rules = project_rules("acme", "losmon", remotes=self._remotes_with_mount())
        assert "SSH Remote Namespace Rule" in rules
        assert "SSH_<host>" in rules

    def test_project_rules_excludes_ssh_section_without_mount(self):
        rules = project_rules("acme", "losmon", remotes=self._remotes_without_mount())
        assert "SSH Remote Namespace Rule" not in rules

    def test_project_rules_no_remotes(self):
        rules = project_rules("acme", "losmon")
        assert "SSH Remote Namespace Rule" not in rules

    def test_project_agents_includes_ssh_section_with_mount(self):
        agents = project_agents("acme", "losmon", remotes=self._remotes_with_mount())
        assert "SSH Remote Namespace Rule" in agents

    def test_project_agents_mount_info_in_remote_entry(self):
        agents = project_agents("acme", "losmon", remotes=self._remotes_with_mount())
        assert "SSHFS namespace" in agents

    def test_project_agents_no_ssh_section_without_mount(self):
        agents = project_agents("acme", "losmon", remotes=self._remotes_without_mount())
        assert "SSH Remote Namespace Rule" not in agents

    def test_ssh_namespace_rules_section_standalone(self):
        section = ssh_namespace_rules_section()
        assert "SSH_<host>" in section
        assert "builds" in section
        assert "watchers" in section


# ---------------------------------------------------------------------------
# AC6: doctor_remote_mounts
# ---------------------------------------------------------------------------


class TestDoctorRemoteMounts:
    def test_ok_when_no_mount_blocks(self, tmp_path: Path):
        root = _init_root(tmp_path)
        _make_project_without_mount(root)
        result = doctor_remote_mounts(root, "acme", "losmon")
        assert result["ok"] is True
        # Should mention no mount blocks
        messages = [f["message"] for f in result["findings"]]
        assert any("no remotes with mount" in m for m in messages)

    def test_ok_when_well_formed_mount(self, tmp_path: Path):
        root = _init_root(tmp_path)
        _make_project(root, with_mount=True)
        result = doctor_remote_mounts(root, "acme", "losmon")
        assert result["ok"] is True
        levels = [f["level"] for f in result["findings"]]
        assert "error" not in levels

    def test_error_when_host_not_in_registry(self, tmp_path: Path):
        root = _init_root(tmp_path)
        project_root = _make_project(root, with_mount=True)
        # Remove the host entry from hosts.yml
        hosts_file = root / "config" / "hosts.yml"
        hosts_file.write_text("{}\n", encoding="utf-8")

        result = doctor_remote_mounts(root, "acme", "losmon")
        assert result["ok"] is False
        errors = [f for f in result["findings"] if f["level"] == "error"]
        assert any("not found in config/hosts.yml" in e["message"] for e in errors)

    def test_error_when_local_path_outside_ssh_namespace(self, tmp_path: Path):
        root = _init_root(tmp_path)
        project_root = _make_project(root, with_mount=True)
        # Overwrite mount.local_path to a normal path (outside SSH namespace)
        project_yml = project_root / "project.yml"
        data = yaml.safe_load(project_yml.read_text(encoding="utf-8")) or {}
        data["sources"]["remotes"][0]["mount"]["local_path"] = "/tmp/normalpath"
        project_yml.write_text(yaml.safe_dump(data, sort_keys=False))

        result = doctor_remote_mounts(root, "acme", "losmon")
        assert result["ok"] is False
        errors = [f for f in result["findings"] if f["level"] == "error"]
        assert any("SSH_<host> component" in e["message"] for e in errors)

    def test_error_on_ambiguous_namespaces(self, tmp_path: Path):
        root = _init_root(tmp_path)
        _make_project(root, with_mount=True)
        project_root = root / "domains" / "acme" / "02-projects" / "losmon"
        project_yml = project_root / "project.yml"
        data = yaml.safe_load(project_yml.read_text(encoding="utf-8")) or {}
        # Add a second remote with the same namespace
        data["sources"]["remotes"].append({
            "name": "losmon_replica",
            "host": "genomesbox",
            "path": "/home/genome/projects/losmon_replica",
            "kind": "git",
            "authority": "remote",
            "mount": {
                "namespace": "SSH_genomesbox",
                "local_path": str(root / "SSH_genomesbox" / "losmon_replica"),
            },
        })
        project_yml.write_text(yaml.safe_dump(data, sort_keys=False))

        result = doctor_remote_mounts(root, "acme", "losmon")
        assert result["ok"] is False
        errors = [f for f in result["findings"] if f["level"] == "error"]
        assert any("ambiguous" in e["message"] for e in errors)

    def test_live_check_calls_runner(self, tmp_path: Path):
        root = _init_root(tmp_path)
        _make_project(root, with_mount=True)
        calls: list[list[str]] = []

        def capturing_runner(args: list[str], *, timeout: int = 20) -> FakeResult:
            calls.append(args)
            return FakeResult(returncode=0, stdout="")

        result = doctor_remote_mounts(
            root, "acme", "losmon",
            check_mounts=True,
            runner=capturing_runner,
        )
        # Should have made an SSH call for the live probe
        assert len(calls) >= 1
        assert "ssh" in calls[0]

    def test_offline_skips_runner(self, tmp_path: Path):
        root = _init_root(tmp_path)
        _make_project(root, with_mount=True)
        calls: list[list[str]] = []

        def capturing_runner(args: list[str], *, timeout: int = 20) -> FakeResult:
            calls.append(args)
            return FakeResult(returncode=0, stdout="")

        doctor_remote_mounts(
            root, "acme", "losmon",
            check_mounts=False,  # offline (default)
            runner=capturing_runner,
        )
        assert len(calls) == 0

    def test_error_on_missing_project_yml(self, tmp_path: Path):
        result = doctor_remote_mounts(tmp_path, "acme", "nonexistent")
        assert result["ok"] is False
        assert result["errors"]


# ---------------------------------------------------------------------------
# AC7: mount_remote / unmount_remote dry-run and --apply guard
# ---------------------------------------------------------------------------


class TestMountRemote:
    def test_dry_run_prints_plan_no_mount(self, tmp_path: Path):
        root = _init_root(tmp_path)
        _make_project(root, with_mount=True)
        calls: list[list[str]] = []

        def capture_runner(args: list[str], *, timeout: int = 20) -> FakeResult:
            calls.append(args)
            return FakeResult(returncode=0)

        result = mount_remote(
            root, "acme", "losmon",
            apply=False,
            runner=capture_runner,
        )
        assert result["ok"] is True
        assert result["applied"] is False
        # Dry run must not call the runner
        assert len(calls) == 0
        # Plan must include sshfs command
        plan_text = "\n".join(result["plan"])
        assert "sshfs" in plan_text

    def test_apply_refused_when_sshfs_absent(self, tmp_path: Path, monkeypatch):
        root = _init_root(tmp_path)
        _make_project(root, with_mount=True)
        # Ensure sshfs is not found
        monkeypatch.setattr("shutil.which", lambda cmd: None)

        result = mount_remote(
            root, "acme", "losmon",
            apply=True,
            runner=_fake_runner_ok,
        )
        assert result["ok"] is False
        assert any("sshfs not found" in e for e in result["errors"])

    def test_apply_calls_runner_when_sshfs_present(self, tmp_path: Path, monkeypatch):
        root = _init_root(tmp_path)
        _make_project(root, with_mount=True)
        monkeypatch.setattr("shutil.which", lambda cmd: "/usr/local/bin/sshfs" if cmd == "sshfs" else None)
        calls: list[list[str]] = []

        def capture_runner(args: list[str], *, timeout: int = 20) -> FakeResult:
            calls.append(args)
            return FakeResult(returncode=0)

        result = mount_remote(
            root, "acme", "losmon",
            apply=True,
            runner=capture_runner,
        )
        assert len(calls) == 1
        assert "sshfs" in calls[0][0]
        assert result["applied"] is True

    def test_plan_contains_ssh_alias(self, tmp_path: Path):
        root = _init_root(tmp_path)
        _make_project(root, with_mount=True)

        result = mount_remote(root, "acme", "losmon", apply=False, runner=_fake_runner_ok)
        plan_text = "\n".join(result["plan"])
        assert "genomesbox" in plan_text

    def test_error_on_missing_project_yml(self, tmp_path: Path):
        result = mount_remote(tmp_path, "acme", "nonexistent", apply=False)
        assert result["ok"] is False
        assert result["errors"]

    def test_error_on_no_mount_block(self, tmp_path: Path):
        root = _init_root(tmp_path)
        _make_project_without_mount(root)

        result = mount_remote(root, "acme", "losmon", apply=False)
        assert result["ok"] is False
        assert any("mount block" in e for e in result["errors"])

    def test_refused_if_local_path_outside_ssh_namespace(self, tmp_path: Path):
        root = _init_root(tmp_path)
        project_root = _make_project(root, with_mount=True)
        project_yml = project_root / "project.yml"
        data = yaml.safe_load(project_yml.read_text()) or {}
        data["sources"]["remotes"][0]["mount"]["local_path"] = "/tmp/normalpath"
        project_yml.write_text(yaml.safe_dump(data, sort_keys=False))

        result = mount_remote(root, "acme", "losmon", apply=False, runner=_fake_runner_ok)
        assert result["ok"] is False
        assert any("approved namespace" in e for e in result["errors"])


class TestUnmountRemote:
    def test_dry_run_prints_plan_no_unmount(self, tmp_path: Path):
        root = _init_root(tmp_path)
        _make_project(root, with_mount=True)
        calls: list[list[str]] = []

        def capture_runner(args: list[str], *, timeout: int = 20) -> FakeResult:
            calls.append(args)
            return FakeResult(returncode=0)

        result = unmount_remote(
            root, "acme", "losmon",
            apply=False,
            runner=capture_runner,
        )
        assert result["ok"] is True
        assert result["applied"] is False
        assert len(calls) == 0
        plan_text = "\n".join(result["plan"])
        # Plan must show an unmount command
        assert "umount" in plan_text or "fusermount" in plan_text

    def test_apply_calls_runner(self, tmp_path: Path):
        root = _init_root(tmp_path)
        _make_project(root, with_mount=True)
        calls: list[list[str]] = []

        def capture_runner(args: list[str], *, timeout: int = 20) -> FakeResult:
            calls.append(args)
            return FakeResult(returncode=0)

        result = unmount_remote(
            root, "acme", "losmon",
            apply=True,
            runner=capture_runner,
        )
        assert len(calls) == 1
        assert result["applied"] is True

    def test_error_on_missing_project_yml(self, tmp_path: Path):
        result = unmount_remote(tmp_path, "acme", "nonexistent", apply=False)
        assert result["ok"] is False
        assert result["errors"]


# ---------------------------------------------------------------------------
# CLI surface: mount-remote, unmount-remote, exec subcommands
# ---------------------------------------------------------------------------


class TestCLIMountRemote:
    def test_mount_remote_dry_run_exits_zero(self, tmp_path: Path, capsys):
        root = _init_root(tmp_path)
        _make_project(root, with_mount=True)
        ret = main(["project", "mount-remote", "acme", "losmon", "--root", str(root)])
        assert ret == 0
        out = capsys.readouterr().out
        assert "dry-run" in out
        assert "sshfs" in out

    def test_mount_remote_help_exits_zero(self):
        with pytest.raises(SystemExit) as exc_info:
            main(["project", "mount-remote", "--help"])
        assert exc_info.value.code == 0

    def test_unmount_remote_dry_run_exits_zero(self, tmp_path: Path, capsys):
        root = _init_root(tmp_path)
        _make_project(root, with_mount=True)
        ret = main(["project", "unmount-remote", "acme", "losmon", "--root", str(root)])
        assert ret == 0
        out = capsys.readouterr().out
        assert "dry-run" in out

    def test_unmount_remote_help_exits_zero(self):
        with pytest.raises(SystemExit) as exc_info:
            main(["project", "unmount-remote", "--help"])
        assert exc_info.value.code == 0

    def test_exec_help_exits_zero(self):
        with pytest.raises(SystemExit) as exc_info:
            main(["project", "exec", "--help"])
        assert exc_info.value.code == 0

    def test_exec_no_command_returns_one(self, tmp_path: Path, capsys):
        root = _init_root(tmp_path)
        _make_project_without_mount(root)
        # No command supplied after --; handler should print error and return 1
        ret = main(["project", "exec", "acme", "losmon", "--root", str(root), "--"])
        assert ret == 1
        out = capsys.readouterr().out
        assert "no command" in out


# ---------------------------------------------------------------------------
# AC2: Feature 63 baseline is not broken (additive-only check)
# ---------------------------------------------------------------------------


class TestFeature63Baseline:
    def test_remote_without_mount_block_still_works(self, tmp_path: Path):
        """project.yml remotes without a mount block must still parse correctly."""
        root = _init_root(tmp_path)
        project_root = _make_project_without_mount(root)
        project_yml = project_root / "project.yml"
        data = yaml.safe_load(project_yml.read_text(encoding="utf-8")) or {}
        remotes = data.get("sources", {}).get("remotes", [])
        assert len(remotes) == 1
        assert "mount" not in remotes[0]

    def test_doctor_ok_on_no_mount_blocks(self, tmp_path: Path):
        root = _init_root(tmp_path)
        _make_project_without_mount(root)
        result = doctor_remote_mounts(root, "acme", "losmon")
        assert result["ok"] is True

    def test_project_rules_no_ssh_section_for_f63_remote(self):
        remotes_f63 = [{"name": "losmon", "host": "genomesbox", "path": "/home/genome/projects/losmon"}]
        rules = project_rules("acme", "losmon", remotes=remotes_f63)
        assert "SSH Remote Namespace Rule" not in rules
