"""Tests for feature 63 — remote SSH project sources (P1).

Covers:
- hosts.py: load, save, upsert, list, validation
- scaffold: create_project with remotes materialises REMOTE.md + manifest + source-map + project.yml
- scaffold: defaults (name/kind/authority)
- scaffold: link_project_remote on existing project
- scaffold: link-remote name conflict without --force errors; with --force replaces
- scaffold: yaml round-trip through set_project_repo preserves remotes
- scaffold: project without remotes unchanged (no remote/ dir)
- scaffold: AGENTS.md / CONTEXT.md contain remote section only for remote projects
- scaffold: manifest stub not overwritten on re-run (idempotency)
- CLI: project create --remote-host / --remote-path
- CLI: project link-remote
- CLI: host add / host list
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os.hosts import list_hosts, load_hosts, save_hosts, upsert_host
from genomes_agentic_os.scaffold import (
    _remotes_from_config,
    append_project_remote_refs,
    create_project,
    domain_path,
    ensure_project_remote_dirs,
    link_project_remote,
    onboard_project,
    project_agents,
    project_context,
    remote_manifest_stub,
    remote_readme_content,
    set_project_repo,
)
from genomes_agentic_os.scaffold import ScaffoldResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _project_root(root: Path, domain: str, project: str) -> Path:
    return domain_path(root, domain) / "02-projects" / project


def _init_root(root: Path) -> None:
    """Run init so domain structure is present."""
    assert main(["init", "--target", str(root), "--projects-source", str(root / "projects")]) == 0


# ---------------------------------------------------------------------------
# hosts.py unit tests
# ---------------------------------------------------------------------------


class TestHostsModule:
    def test_load_hosts_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert load_hosts(tmp_path) == {}

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        data = {
            "genomesbox": {
                "ssh_alias": "genomesbox",
                "user": "genome",
                "description": "Always-on Linux box.",
                "ssh_options": ["-o", "ClearAllForwardings=yes"],
            }
        }
        save_hosts(tmp_path, data)
        loaded = load_hosts(tmp_path)
        assert loaded == data

    def test_load_hosts_validates_structure(self, tmp_path: Path) -> None:
        hosts_file = tmp_path / "config" / "hosts.yml"
        hosts_file.parent.mkdir(parents=True)
        # Top-level list is not a mapping — should fail validation
        hosts_file.write_text("- bad\n- yaml\n", encoding="utf-8")
        with pytest.raises(ValueError, match="must be a YAML mapping"):
            load_hosts(tmp_path)

    def test_upsert_host_creates_new(self, tmp_path: Path) -> None:
        result = upsert_host(tmp_path, "myhost", ssh_alias="myhost", user="me", description="test")
        assert result["action"] == "created"
        hosts = load_hosts(tmp_path)
        assert "myhost" in hosts
        assert hosts["myhost"]["user"] == "me"

    def test_upsert_host_updates_existing(self, tmp_path: Path) -> None:
        upsert_host(tmp_path, "myhost", description="old")
        result = upsert_host(tmp_path, "myhost", description="new")
        assert result["action"] == "updated"
        assert load_hosts(tmp_path)["myhost"]["description"] == "new"

    def test_upsert_host_skips_when_unchanged(self, tmp_path: Path) -> None:
        upsert_host(tmp_path, "myhost", description="same")
        result = upsert_host(tmp_path, "myhost", description="same")
        assert result["action"] == "skipped"

    def test_list_hosts_empty(self, tmp_path: Path) -> None:
        assert list_hosts(tmp_path) == []

    def test_list_hosts_returns_entries_with_alias(self, tmp_path: Path) -> None:
        upsert_host(tmp_path, "box1", description="Box 1")
        upsert_host(tmp_path, "box2", description="Box 2")
        entries = list_hosts(tmp_path)
        aliases = {e["alias"] for e in entries}
        assert aliases == {"box1", "box2"}

    def test_upsert_host_rejects_bad_alias(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Host alias must be"):
            upsert_host(tmp_path, "has spaces")

    def test_hosts_yml_with_paths(self, tmp_path: Path) -> None:
        data = {
            "myhost": {
                "paths": [
                    {"path": "/home/user/projects/myproject", "purpose": "Main project"},
                ]
            }
        }
        save_hosts(tmp_path, data)
        loaded = load_hosts(tmp_path)
        assert loaded["myhost"]["paths"][0]["path"] == "/home/user/projects/myproject"


# ---------------------------------------------------------------------------
# scaffold: remote helpers
# ---------------------------------------------------------------------------


class TestRemoteHelpers:
    def test_remote_readme_content_has_authority_statement(self, tmp_path: Path) -> None:
        remote = {"name": "losmon", "host": "genomesbox", "path": "/home/genome/projects/losmon", "kind": "git", "authority": "remote"}
        content = remote_readme_content("losmon", remote, tmp_path)
        assert "authoritative on genomesbox" in content
        assert "ClearAllForwardings" not in content  # no ssh_options in hosts.yml yet
        assert "ssh genomesbox" in content
        assert "cd /home/genome/projects/losmon" in content
        assert "BatchMode=yes" in content

    def test_remote_readme_content_pulls_ssh_options_from_hosts(self, tmp_path: Path) -> None:
        upsert_host(tmp_path, "genomesbox", ssh_alias="genomesbox")
        # Manually write ssh_options
        data = load_hosts(tmp_path)
        data["genomesbox"]["ssh_options"] = ["-o", "ClearAllForwardings=yes"]
        save_hosts(tmp_path, data)

        remote = {"name": "losmon", "host": "genomesbox", "path": "/home/genome/projects/losmon", "kind": "git", "authority": "remote"}
        content = remote_readme_content("losmon", remote, tmp_path)
        assert "ClearAllForwardings=yes" in content

    def test_remote_readme_local_authority(self, tmp_path: Path) -> None:
        remote = {"name": "deploy", "host": "prod", "path": "/srv/app", "kind": "folder", "authority": "local"}
        content = remote_readme_content("myproject", remote, tmp_path)
        assert "Local copy is" in content

    def test_remote_readme_reference_only_warning(self, tmp_path: Path) -> None:
        remote = {"name": "losmon", "host": "genomesbox", "path": "/home/genome/projects/losmon", "kind": "git", "authority": "remote"}
        content = remote_readme_content("losmon", remote, tmp_path, local_repo="~/projects/losmon")
        assert "Reference-only warning" in content
        assert "~/projects/losmon" in content

    def test_remote_manifest_stub_structure(self, tmp_path: Path) -> None:
        remote = {"name": "losmon", "host": "genomesbox", "path": "/home/genome/projects/losmon", "kind": "git", "authority": "remote"}
        content = remote_manifest_stub("losmon", remote)
        data = yaml.safe_load(content)
        assert data["name"] == "losmon"
        assert data["host"] == "genomesbox"
        assert data["reachable"] == "unknown"
        assert data["synced_at"] is None

    def test_project_agents_no_remotes(self) -> None:
        content = project_agents("los", "myproject")
        assert "Remote Sources" not in content
        # marker phrase must be present for replace_markers to fire on re-run
        assert "harness-neutral entrypoint" in content

    def test_project_agents_with_remotes(self) -> None:
        remotes = [{"name": "losmon", "host": "genomesbox", "path": "/home/genome/projects/losmon", "authority": "remote"}]
        content = project_agents("los", "losmon", remotes=remotes)
        assert "Remote Sources" in content
        assert "genomesbox:/home/genome/projects/losmon" in content
        assert "Artifacts, work-items" in content

    def test_project_context_no_remotes(self) -> None:
        content = project_context("los", "myproject")
        assert "Remote Sources" not in content
        # marker phrase must be present for replace_markers to fire on re-run
        assert "Describe the local room" in content

    def test_project_context_with_remotes(self) -> None:
        remotes = [{"name": "losmon", "host": "genomesbox", "path": "/home/genome/projects/losmon", "authority": "remote"}]
        content = project_context("los", "losmon", remotes=remotes)
        assert "Remote Sources" in content
        assert "genomesbox:/home/genome/projects/losmon" in content


# ---------------------------------------------------------------------------
# scaffold: create_project with remotes
# ---------------------------------------------------------------------------


class TestCreateProjectWithRemotes:
    def test_create_with_remote_materialises_files(self, tmp_path: Path) -> None:
        _init_root(tmp_path)
        remote = {"name": "losmon", "host": "genomesbox", "path": "/home/genome/projects/losmon", "kind": "git", "authority": "remote"}
        result = create_project(tmp_path, "los", "losmon_app", remotes=[remote])
        pr = _project_root(tmp_path, "los", "losmon_app")

        assert (pr / "remote" / "losmon" / "REMOTE.md").is_file()
        assert (pr / "remote" / "losmon" / "manifest.yml").is_file()
        assert any(pr / "remote" / "losmon" / "REMOTE.md" == p for p in result.created + result.updated)

    def test_source_map_gets_remote_row(self, tmp_path: Path) -> None:
        _init_root(tmp_path)
        remote = {"name": "losmon", "host": "genomesbox", "path": "/home/genome/projects/losmon", "kind": "git", "authority": "remote"}
        create_project(tmp_path, "los", "losmon_app", remotes=[remote])
        pr = _project_root(tmp_path, "los", "losmon_app")
        source_map = (pr / "source-map.md").read_text(encoding="utf-8")
        assert "genomesbox:/home/genome/projects/losmon" in source_map
        assert "Authoritative working tree" in source_map

    def test_project_yml_has_remotes_block(self, tmp_path: Path) -> None:
        _init_root(tmp_path)
        remote = {"name": "losmon", "host": "genomesbox", "path": "/home/genome/projects/losmon", "kind": "git", "authority": "remote"}
        create_project(tmp_path, "los", "losmon_app", remotes=[remote])
        pr = _project_root(tmp_path, "los", "losmon_app")
        data = yaml.safe_load((pr / "project.yml").read_text(encoding="utf-8"))
        remotes = data["sources"]["remotes"]
        assert len(remotes) == 1
        assert remotes[0]["host"] == "genomesbox"
        assert remotes[0]["path"] == "/home/genome/projects/losmon"

    def test_agents_md_has_remote_section(self, tmp_path: Path) -> None:
        _init_root(tmp_path)
        remote = {"name": "losmon", "host": "genomesbox", "path": "/home/genome/projects/losmon", "kind": "git", "authority": "remote"}
        create_project(tmp_path, "los", "losmon_app", remotes=[remote])
        pr = _project_root(tmp_path, "los", "losmon_app")
        agents = (pr / "AGENTS.md").read_text(encoding="utf-8")
        assert "Remote Sources" in agents
        assert "genomesbox:/home/genome/projects/losmon" in agents

    def test_context_md_has_remote_section(self, tmp_path: Path) -> None:
        _init_root(tmp_path)
        remote = {"name": "losmon", "host": "genomesbox", "path": "/home/genome/projects/losmon", "kind": "git", "authority": "remote"}
        create_project(tmp_path, "los", "losmon_app", remotes=[remote])
        pr = _project_root(tmp_path, "los", "losmon_app")
        context = (pr / "CONTEXT.md").read_text(encoding="utf-8")
        assert "Remote Sources" in context

    def test_defaults_name_kind_authority(self, tmp_path: Path) -> None:
        """name defaults to project, kind defaults to git, authority defaults to remote."""
        _init_root(tmp_path)
        # Only host+path provided; name/kind/authority should default
        remote = {"host": "genomesbox", "path": "/home/genome/projects/myproject"}
        create_project(tmp_path, "los", "myproject", remotes=[remote])
        pr = _project_root(tmp_path, "los", "myproject")
        # remote dir should use project name as default
        assert (pr / "remote" / "myproject" / "REMOTE.md").is_file()
        manifest = yaml.safe_load((pr / "remote" / "myproject" / "manifest.yml").read_text())
        assert manifest["name"] == "myproject"
        assert manifest["kind"] == "git"
        assert manifest["authority"] == "remote"

    def test_project_without_remotes_no_remote_dir(self, tmp_path: Path) -> None:
        _init_root(tmp_path)
        create_project(tmp_path, "los", "plain_project")
        pr = _project_root(tmp_path, "los", "plain_project")
        assert not (pr / "remote").exists()

    def test_manifest_not_overwritten_on_rerun(self, tmp_path: Path) -> None:
        """manifest.yml is write_file_once — a second create call must not overwrite it."""
        _init_root(tmp_path)
        remote = {"name": "losmon", "host": "genomesbox", "path": "/home/genome/projects/losmon", "kind": "git", "authority": "remote"}
        create_project(tmp_path, "los", "losmon_app", remotes=[remote])
        pr = _project_root(tmp_path, "los", "losmon_app")
        manifest_path = pr / "remote" / "losmon" / "manifest.yml"

        # Simulate sync-remote writing state into manifest
        synced_content = "name: losmon\nhost: genomesbox\nreachable: true\n"
        manifest_path.write_text(synced_content, encoding="utf-8")

        # Re-run create (idempotent) — must not overwrite manifest
        create_project(tmp_path, "los", "losmon_app", remotes=[remote])
        assert manifest_path.read_text(encoding="utf-8") == synced_content

    def test_idempotent_rerun_no_duplicate_source_map_rows(self, tmp_path: Path) -> None:
        """Running create twice must not append duplicate source-map rows."""
        _init_root(tmp_path)
        remote = {"name": "losmon", "host": "genomesbox", "path": "/home/genome/projects/losmon", "kind": "git", "authority": "remote"}
        create_project(tmp_path, "los", "losmon_app", remotes=[remote])
        create_project(tmp_path, "los", "losmon_app", remotes=[remote])
        pr = _project_root(tmp_path, "los", "losmon_app")
        source_map = (pr / "source-map.md").read_text(encoding="utf-8")
        count = source_map.count("genomesbox:/home/genome/projects/losmon")
        assert count == 1, f"Expected 1 row, found {count}"


# ---------------------------------------------------------------------------
# scaffold: link_project_remote
# ---------------------------------------------------------------------------


class TestLinkProjectRemote:
    def test_link_remote_on_existing_project(self, tmp_path: Path) -> None:
        _init_root(tmp_path)
        create_project(tmp_path, "los", "losmon_app")
        pr = _project_root(tmp_path, "los", "losmon_app")
        assert not (pr / "remote").exists()

        link_project_remote(
            tmp_path, "los", "losmon_app",
            host="genomesbox",
            path="/home/genome/projects/losmon",
            name="losmon",
        )
        assert (pr / "remote" / "losmon" / "REMOTE.md").is_file()
        assert (pr / "remote" / "losmon" / "manifest.yml").is_file()

        data = yaml.safe_load((pr / "project.yml").read_text(encoding="utf-8"))
        remotes = data["sources"]["remotes"]
        assert remotes[0]["host"] == "genomesbox"

    def test_link_remote_updates_source_map(self, tmp_path: Path) -> None:
        _init_root(tmp_path)
        create_project(tmp_path, "los", "losmon_app")
        link_project_remote(
            tmp_path, "los", "losmon_app",
            host="genomesbox",
            path="/home/genome/projects/losmon",
        )
        pr = _project_root(tmp_path, "los", "losmon_app")
        source_map = (pr / "source-map.md").read_text(encoding="utf-8")
        assert "genomesbox:/home/genome/projects/losmon" in source_map

    def test_link_remote_updates_agents_context(self, tmp_path: Path) -> None:
        _init_root(tmp_path)
        create_project(tmp_path, "los", "losmon_app")
        link_project_remote(
            tmp_path, "los", "losmon_app",
            host="genomesbox",
            path="/home/genome/projects/losmon",
        )
        pr = _project_root(tmp_path, "los", "losmon_app")
        assert "Remote Sources" in (pr / "AGENTS.md").read_text(encoding="utf-8")
        assert "Remote Sources" in (pr / "CONTEXT.md").read_text(encoding="utf-8")

    def test_link_remote_name_conflict_without_force_raises(self, tmp_path: Path) -> None:
        _init_root(tmp_path)
        create_project(tmp_path, "los", "losmon_app")
        link_project_remote(tmp_path, "los", "losmon_app", host="genomesbox", path="/home/genome/projects/losmon", name="losmon")
        with pytest.raises(ValueError, match="already exists"):
            link_project_remote(tmp_path, "los", "losmon_app", host="otherhost", path="/other/path", name="losmon")

    def test_link_remote_name_conflict_with_force_replaces(self, tmp_path: Path) -> None:
        _init_root(tmp_path)
        create_project(tmp_path, "los", "losmon_app")
        link_project_remote(tmp_path, "los", "losmon_app", host="genomesbox", path="/home/genome/projects/losmon", name="losmon")
        link_project_remote(tmp_path, "los", "losmon_app", host="otherhost", path="/other/path", name="losmon", force=True)
        pr = _project_root(tmp_path, "los", "losmon_app")
        data = yaml.safe_load((pr / "project.yml").read_text(encoding="utf-8"))
        remotes = data["sources"]["remotes"]
        # Should still be exactly one remote named "losmon"
        losmon_remotes = [r for r in remotes if r.get("name") == "losmon"]
        assert len(losmon_remotes) == 1
        assert losmon_remotes[0]["host"] == "otherhost"


# ---------------------------------------------------------------------------
# YAML round-trip: set_project_repo preserves remotes
# ---------------------------------------------------------------------------


class TestYamlRoundTrip:
    def test_set_project_repo_preserves_remotes(self, tmp_path: Path) -> None:
        """set_project_repo does yaml.safe_load/safe_dump — remotes must survive."""
        _init_root(tmp_path)
        remote = {"name": "losmon", "host": "genomesbox", "path": "/home/genome/projects/losmon", "kind": "git", "authority": "remote"}
        create_project(tmp_path, "los", "losmon_app", remotes=[remote])
        pr = _project_root(tmp_path, "los", "losmon_app")

        result = ScaffoldResult()
        set_project_repo(pr, "~/projects/losmon_mirror", result)

        data = yaml.safe_load((pr / "project.yml").read_text(encoding="utf-8"))
        assert data["sources"]["repo"] == "~/projects/losmon_mirror"
        remotes = data["sources"].get("remotes", [])
        assert len(remotes) == 1
        assert remotes[0]["host"] == "genomesbox"

    def test_remotes_from_config_parses_correctly(self, tmp_path: Path) -> None:
        _init_root(tmp_path)
        remote = {"name": "losmon", "host": "genomesbox", "path": "/home/genome/projects/losmon", "kind": "git", "authority": "remote"}
        create_project(tmp_path, "los", "losmon_app", remotes=[remote])
        pr = _project_root(tmp_path, "los", "losmon_app")
        data = yaml.safe_load((pr / "project.yml").read_text(encoding="utf-8"))
        parsed = _remotes_from_config(data)
        assert len(parsed) == 1
        assert parsed[0]["host"] == "genomesbox"

    def test_remotes_from_config_empty_for_no_remotes(self, tmp_path: Path) -> None:
        _init_root(tmp_path)
        create_project(tmp_path, "los", "plain_project")
        pr = _project_root(tmp_path, "los", "plain_project")
        data = yaml.safe_load((pr / "project.yml").read_text(encoding="utf-8"))
        assert _remotes_from_config(data) == []


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


class TestCLI:
    def test_project_create_with_remote_host_and_path(self, tmp_path: Path) -> None:
        _init_root(tmp_path)
        assert main([
            "project", "create", "los", "losmon_app",
            "--root", str(tmp_path),
            "--remote-host", "genomesbox",
            "--remote-path", "/home/genome/projects/losmon",
        ]) == 0
        pr = _project_root(tmp_path, "los", "losmon_app")
        assert (pr / "remote" / "losmon_app" / "REMOTE.md").is_file()

    def test_project_create_with_remote_name(self, tmp_path: Path) -> None:
        _init_root(tmp_path)
        assert main([
            "project", "create", "los", "losmon_app",
            "--root", str(tmp_path),
            "--remote-host", "genomesbox",
            "--remote-path", "/home/genome/projects/losmon",
            "--remote-name", "losmon",
        ]) == 0
        pr = _project_root(tmp_path, "los", "losmon_app")
        assert (pr / "remote" / "losmon" / "REMOTE.md").is_file()

    def test_project_create_without_remote_args_no_remote_dir(self, tmp_path: Path) -> None:
        _init_root(tmp_path)
        assert main(["project", "create", "los", "plain_project", "--root", str(tmp_path)]) == 0
        pr = _project_root(tmp_path, "los", "plain_project")
        assert not (pr / "remote").exists()

    def test_project_link_remote_cli(self, tmp_path: Path) -> None:
        _init_root(tmp_path)
        assert main(["project", "create", "los", "losmon_app", "--root", str(tmp_path)]) == 0
        assert main([
            "project", "link-remote", "los", "losmon_app",
            "--host", "genomesbox",
            "--path", "/home/genome/projects/losmon",
            "--name", "losmon",
            "--root", str(tmp_path),
        ]) == 0
        pr = _project_root(tmp_path, "los", "losmon_app")
        assert (pr / "remote" / "losmon" / "REMOTE.md").is_file()
        assert (pr / "remote" / "losmon" / "manifest.yml").is_file()

    def test_project_link_remote_force_flag(self, tmp_path: Path) -> None:
        _init_root(tmp_path)
        assert main(["project", "create", "los", "losmon_app", "--root", str(tmp_path)]) == 0
        assert main([
            "project", "link-remote", "los", "losmon_app",
            "--host", "genomesbox", "--path", "/home/genome/projects/losmon",
            "--name", "losmon", "--root", str(tmp_path),
        ]) == 0
        # Without --force should raise (CLI catches and returns non-zero)
        rc = main([
            "project", "link-remote", "los", "losmon_app",
            "--host", "otherhost", "--path", "/other", "--name", "losmon",
            "--root", str(tmp_path),
        ])
        assert rc != 0

        # With --force should succeed
        assert main([
            "project", "link-remote", "los", "losmon_app",
            "--host", "otherhost", "--path", "/other", "--name", "losmon",
            "--root", str(tmp_path), "--force",
        ]) == 0
        pr = _project_root(tmp_path, "los", "losmon_app")
        data = yaml.safe_load((pr / "project.yml").read_text(encoding="utf-8"))
        remotes = data["sources"]["remotes"]
        assert remotes[-1]["host"] == "otherhost"

    def test_host_add_and_list_cli(self, tmp_path: Path) -> None:
        _init_root(tmp_path)
        assert main([
            "host", "add", "genomesbox",
            "--ssh-alias", "genomesbox",
            "--user", "genome",
            "--description", "Always-on Linux box",
            "--root", str(tmp_path),
        ]) == 0
        assert main(["host", "list", "--root", str(tmp_path)]) == 0
        hosts = load_hosts(tmp_path)
        assert "genomesbox" in hosts
        assert hosts["genomesbox"]["user"] == "genome"

    def test_project_onboard_with_existing_remotes_materialises(self, tmp_path: Path) -> None:
        """onboard_project re-runs ensure_project_operating_surface with remotes from project.yml."""
        _init_root(tmp_path)
        remote = {"name": "losmon", "host": "genomesbox", "path": "/home/genome/projects/losmon", "kind": "git", "authority": "remote"}
        create_project(tmp_path, "los", "losmon_app", remotes=[remote])
        pr = _project_root(tmp_path, "los", "losmon_app")

        # Delete REMOTE.md to simulate a missing file scenario
        (pr / "remote" / "losmon" / "REMOTE.md").unlink()
        assert not (pr / "remote" / "losmon" / "REMOTE.md").exists()

        # onboard should re-create the missing REMOTE.md
        onboard_project(tmp_path, "los", "losmon_app")
        assert (pr / "remote" / "losmon" / "REMOTE.md").is_file()
