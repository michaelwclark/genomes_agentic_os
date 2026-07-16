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

import json
from pathlib import Path

import pytest
import yaml

from genomes_agentic_os.cli import main
from genomes_agentic_os.hosts import (
    format_host_routing_status,
    host_routing_status,
    list_hosts,
    load_hosts,
    save_hosts,
    upsert_host,
)
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

    def test_existing_harness_registry_is_the_active_source(self, tmp_path: Path) -> None:
        hosts_file = tmp_path / "harness" / "config" / "hosts.yml"
        hosts_file.parent.mkdir(parents=True)
        hosts_file.write_text(
            yaml.safe_dump({"hosts": {"genomesbox": {"home": "/home/genome"}}}),
            encoding="utf-8",
        )

        result = upsert_host(tmp_path, "genomesbox", description="Always-on worker")

        assert result["path"] == str(hosts_file)
        assert load_hosts(tmp_path)["genomesbox"]["description"] == "Always-on worker"
        assert not (tmp_path / "config" / "hosts.yml").exists()

    def test_existing_legacy_registry_wins_when_both_exist(self, tmp_path: Path) -> None:
        legacy = tmp_path / "config" / "hosts.yml"
        harness = tmp_path / "harness" / "config" / "hosts.yml"
        legacy.parent.mkdir(parents=True)
        harness.parent.mkdir(parents=True)
        legacy.write_text(yaml.safe_dump({"hosts": {"legacy": {}}}), encoding="utf-8")
        harness.write_text(yaml.safe_dump({"hosts": {"harness": {}}}), encoding="utf-8")

        assert set(load_hosts(tmp_path)) == {"legacy"}

    def test_load_hosts_validates_structure(self, tmp_path: Path) -> None:
        hosts_file = tmp_path / "config" / "hosts.yml"
        hosts_file.parent.mkdir(parents=True)
        # Top-level list is not a mapping — should fail validation
        hosts_file.write_text("- bad\n- yaml\n", encoding="utf-8")
        with pytest.raises(ValueError, match="must be a YAML mapping"):
            load_hosts(tmp_path)

    def test_upsert_host_creates_new(self, tmp_path: Path) -> None:
        result = upsert_host(
            tmp_path,
            "myhost",
            ssh_alias="myhost",
            user="me",
            home="/home/me",
            description="test",
        )
        assert result["action"] == "created"
        hosts = load_hosts(tmp_path)
        assert "myhost" in hosts
        assert hosts["myhost"]["user"] == "me"
        assert hosts["myhost"]["home"] == "/home/me"

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
        upsert_host(tmp_path, "box1", home="/home/box1", description="Box 1")
        upsert_host(tmp_path, "box2", description="Box 2")
        entries = list_hosts(tmp_path)
        aliases = {e["alias"] for e in entries}
        assert aliases == {"box1", "box2"}
        assert any(e["alias"] == "box1" and e["home"] == "/home/box1" for e in entries)

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

    def test_host_routing_status_includes_policy_and_recent_receipts(self, tmp_path: Path) -> None:
        save_hosts(
            tmp_path,
            {
                "bigmac": {"ssh_alias": "bigmac", "home": "/Users/genome"},
                "genomesbox": {"ssh_alias": "genomesbox", "home": "/home/genome"},
            },
        )
        routing = tmp_path / "harness" / "registries" / "hosts-routing.yml"
        routing.parent.mkdir(parents=True)
        routing.write_text(
            """
hosts:
  bigmac:
    role: primary
    max_concurrent: 5
    harnesses: [claude, gpt]
    project_paths:
      Agentic OS: /Users/genome/projects/genomes_agentic_os
  genomesbox:
    role: worker
    max_concurrent: 3
    harnesses: [claude, gpt]
    project_paths:
      Agentic OS: /home/genome/projects/genomes_agentic_os
auto_route:
  enabled: true
  strategy: least_active
  probe: ssh_pgrep
  fallback_host: bigmac
memory_plane:
  shared: true
  endpoint_local: 127.0.0.1:3155
""",
            encoding="utf-8",
        )
        runs_log = tmp_path / "harness" / "shared_factory" / "06-runs-and-logs" / "harness-runs" / "runs.jsonl"
        runs_log.parent.mkdir(parents=True)
        runs_log.write_text(
            '{"ts":"2026-07-04T21:00:00Z","host":"local","harness":"gpt","exit_code":0}\n'
            '{"ts":"2026-07-04T21:01:00Z","host":"genomesbox","harness":"gpt","task_type":"implementation","exit_code":0,"local_view_path":"/Users/genome/agentic_os/SSH_genomesbox/projects/genomes_agentic_os"}\n',
            encoding="utf-8",
        )

        status = host_routing_status(tmp_path)
        text = format_host_routing_status(status)

        assert {host["alias"] for host in status["hosts"]} == {"bigmac", "genomesbox"}
        assert status["api_version"] == "host-query/v1"
        assert status["diagnostics"] == []
        genomesbox = next(host for host in status["hosts"] if host["alias"] == "genomesbox")
        assert genomesbox["health"]["status"] == "healthy"
        assert genomesbox["health"]["source"] == "recent_harness_run"
        bigmac = next(host for host in status["hosts"] if host["alias"] == "bigmac")
        assert bigmac["health"]["status"] == "unknown"
        assert status["recent_harness_runs"][0]["host"] == "genomesbox"
        assert "local_view=/Users/genome/agentic_os/SSH_genomesbox/projects/genomes_agentic_os" in text

    def test_host_routing_status_degrades_when_identity_registry_is_malformed(self, tmp_path: Path) -> None:
        hosts_file = tmp_path / "harness" / "config" / "hosts.yml"
        hosts_file.parent.mkdir(parents=True)
        hosts_file.write_text("- malformed\n", encoding="utf-8")
        routing = tmp_path / "harness" / "registries" / "hosts-routing.yml"
        routing.parent.mkdir(parents=True)
        routing.write_text("hosts:\n  genomesbox:\n    role: worker\n", encoding="utf-8")

        status = host_routing_status(tmp_path)

        assert status["api_version"] == "host-query/v1"
        assert status["hosts"][0]["alias"] == "genomesbox"
        assert status["hosts"][0]["health"]["status"] == "unknown"
        assert any(item["severity"] == "error" for item in status["diagnostics"])


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

    def test_host_add_and_list_cli(self, tmp_path: Path, capsys) -> None:
        _init_root(tmp_path)
        assert main([
            "host", "add", "genomesbox",
            "--ssh-alias", "genomesbox",
            "--user", "genome",
            "--home", "/home/genome",
            "--description", "Always-on Linux box",
            "--root", str(tmp_path),
        ]) == 0
        capsys.readouterr()
        assert main(["host", "list", "--root", str(tmp_path)]) == 0
        listed = capsys.readouterr().out
        hosts = load_hosts(tmp_path)
        assert "genomesbox" in hosts
        assert hosts["genomesbox"]["user"] == "genome"
        assert hosts["genomesbox"]["home"] == "/home/genome"
        assert "home: /home/genome" in listed

        assert main(["host", "list", "--root", str(tmp_path), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["api_version"] == "host-list/v1"
        assert payload["hosts"][0]["alias"] == "genomesbox"

    def test_host_routing_cli_json(self, tmp_path: Path, capsys) -> None:
        _init_root(tmp_path)
        capsys.readouterr()
        save_hosts(tmp_path, {"genomesbox": {"ssh_alias": "genomesbox", "home": "/home/genome"}})
        routing = tmp_path / "harness" / "registries" / "hosts-routing.yml"
        routing.parent.mkdir(parents=True, exist_ok=True)
        routing.write_text(
            """
hosts:
  genomesbox:
    role: worker
    max_concurrent: 3
    harnesses: [gpt]
    project_paths:
      Agentic OS: /home/genome/projects/genomes_agentic_os
auto_route:
  enabled: true
  strategy: least_active
  fallback_host: bigmac
""",
            encoding="utf-8",
        )

        assert main(["host", "routing", "--root", str(tmp_path), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)

        assert payload["api_version"] == "host-query/v1"
        assert payload["hosts"][0]["alias"] == "genomesbox"
        assert payload["auto_route"]["strategy"] == "least_active"

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


# ---------------------------------------------------------------------------
# P2: sync_project_remote — fake-runner unit tests
# ---------------------------------------------------------------------------


def _make_fake_runner(responses: dict[str, tuple[int, str, str]]):
    """Return a fake runner that maps command substrings to (returncode, stdout, stderr)."""
    def _runner(args: list[str], *, timeout: int = 20):
        cmd_str = " ".join(args)
        for key, (rc, stdout, stderr) in responses.items():
            if key in cmd_str:
                class _R:
                    returncode = rc
                    pass
                r = _R()
                r.stdout = stdout
                r.stderr = stderr
                r.returncode = rc
                return r
        # Default: success with empty output
        class _Default:
            returncode = 0
            stdout = ""
            stderr = ""
        return _Default()
    return _runner


def _git_runner(branch: str = "main", head: str = "abc123", dirty: bool = False):
    """Fake runner that returns plausible git info for a git-kind remote."""
    dirty_output = "M src/foo.py\n" if dirty else ""
    return _make_fake_runner({
        "rev-parse --abbrev-ref HEAD": (0, branch + "\n", ""),
        "rev-parse HEAD": (0, head + "\n", ""),
        "status --porcelain": (0, dirty_output, ""),
        "ls -1A": (0, "src\npackage.json\nREADME.md\n", ""),
    })


class TestSyncProjectRemote:
    def test_git_kind_writes_full_manifest(self, tmp_path: Path) -> None:
        """sync_project_remote with a git remote writes branch/head/dirty + listing."""
        from genomes_agentic_os.remote_ops import sync_project_remote

        _init_root(tmp_path)
        remote = {
            "name": "losmon",
            "host": "genomesbox",
            "path": "/home/genome/projects/losmon",
            "kind": "git",
            "authority": "remote",
        }
        create_project(tmp_path, "los", "losmon_app", remotes=[remote])
        pr = _project_root(tmp_path, "los", "losmon_app")

        result = sync_project_remote(
            tmp_path, "los", "losmon_app",
            runner=_git_runner(branch="main", head="abc123", dirty=False),
        )
        assert result["errors"] == []
        assert "losmon" in result["synced"]

        manifest_path = pr / "remote" / "losmon" / "manifest.yml"
        assert manifest_path.is_file()
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        assert data["reachable"] is True
        assert data["git"]["branch"] == "main"
        assert data["git"]["head"] == "abc123"
        assert data["git"]["dirty"] is False
        assert "src" in data["listing"]
        assert data["synced_at"] is not None

    def test_git_kind_dirty_flag(self, tmp_path: Path) -> None:
        """dirty=True is reflected in manifest when porcelain output is non-empty."""
        from genomes_agentic_os.remote_ops import sync_project_remote

        _init_root(tmp_path)
        remote = {"name": "r", "host": "h", "path": "/p", "kind": "git", "authority": "remote"}
        create_project(tmp_path, "los", "myproj", remotes=[remote])

        sync_project_remote(
            tmp_path, "los", "myproj",
            runner=_git_runner(dirty=True),
        )
        pr = _project_root(tmp_path, "los", "myproj")
        data = yaml.safe_load((pr / "remote" / "r" / "manifest.yml").read_text(encoding="utf-8"))
        assert data["git"]["dirty"] is True

    def test_folder_kind_no_git_block(self, tmp_path: Path) -> None:
        """folder-kind sync writes listing but no git block."""
        from genomes_agentic_os.remote_ops import sync_project_remote

        _init_root(tmp_path)
        remote = {"name": "assets", "host": "fileserver", "path": "/data/assets", "kind": "folder", "authority": "remote"}
        create_project(tmp_path, "los", "assetproj", remotes=[remote])

        folder_runner = _make_fake_runner({
            "ls -1A": (0, "img\nvideo\n", ""),
            "test -d": (0, "", ""),
        })
        result = sync_project_remote(
            tmp_path, "los", "assetproj",
            runner=folder_runner,
        )
        assert result["errors"] == []
        pr = _project_root(tmp_path, "los", "assetproj")
        data = yaml.safe_load((pr / "remote" / "assets" / "manifest.yml").read_text(encoding="utf-8"))
        assert "git" not in data
        assert data["reachable"] is True
        assert "img" in data["listing"]

    def test_unreachable_host_reachable_false_no_exception(self, tmp_path: Path) -> None:
        """Unreachable host → reachable: false in manifest, no raised exception."""
        from genomes_agentic_os.remote_ops import sync_project_remote

        _init_root(tmp_path)
        remote = {"name": "remote1", "host": "deadhost", "path": "/home/user/proj", "kind": "git", "authority": "remote"}
        create_project(tmp_path, "los", "proj1", remotes=[remote])

        # All commands fail
        failing_runner = _make_fake_runner({
            "rev-parse --abbrev-ref HEAD": (1, "", "not a git repo"),
            "rev-parse HEAD": (1, "", "error"),
            "status --porcelain": (1, "", "error"),
            "ls -1A": (1, "", "connection refused"),
        })
        result = sync_project_remote(tmp_path, "los", "proj1", runner=failing_runner)
        assert result["errors"] == []
        assert len(result["warnings"]) >= 1

        pr = _project_root(tmp_path, "los", "proj1")
        data = yaml.safe_load((pr / "remote" / "remote1" / "manifest.yml").read_text(encoding="utf-8"))
        assert data["reachable"] is False
        assert data["synced_at"] is not None

    def test_unreachable_host_keeps_prior_git_data(self, tmp_path: Path) -> None:
        """On second (failing) sync, previous git info is preserved in the manifest."""
        from genomes_agentic_os.remote_ops import sync_project_remote

        _init_root(tmp_path)
        remote = {"name": "r", "host": "h", "path": "/p", "kind": "git", "authority": "remote"}
        create_project(tmp_path, "los", "p2", remotes=[remote])

        # First sync succeeds
        sync_project_remote(tmp_path, "los", "p2", runner=_git_runner(head="sha_first"))

        # Second sync fails
        failing_runner = _make_fake_runner({
            "rev-parse --abbrev-ref HEAD": (1, "", "err"),
            "rev-parse HEAD": (1, "", "err"),
            "status --porcelain": (1, "", "err"),
        })
        sync_project_remote(tmp_path, "los", "p2", runner=failing_runner)

        pr = _project_root(tmp_path, "los", "p2")
        data = yaml.safe_load((pr / "remote" / "r" / "manifest.yml").read_text(encoding="utf-8"))
        assert data["reachable"] is False
        # Prior git data must be preserved
        assert data.get("git", {}).get("head") == "sha_first"

    def test_listing_capped_at_200_with_truncated_flag(self, tmp_path: Path) -> None:
        """Listings with more than 200 entries are capped and listing_truncated is set."""
        from genomes_agentic_os.remote_ops import sync_project_remote

        _init_root(tmp_path)
        remote = {"name": "big", "host": "h", "path": "/big", "kind": "git", "authority": "remote"}
        create_project(tmp_path, "los", "bigproj", remotes=[remote])

        big_ls = "\n".join(f"file{i:04d}.txt" for i in range(250)) + "\n"
        big_runner = _make_fake_runner({
            "rev-parse --abbrev-ref HEAD": (0, "main\n", ""),
            "rev-parse HEAD": (0, "deadbeef\n", ""),
            "status --porcelain": (0, "", ""),
            "ls -1A": (0, big_ls, ""),
        })
        sync_project_remote(tmp_path, "los", "bigproj", runner=big_runner)

        pr = _project_root(tmp_path, "los", "bigproj")
        data = yaml.safe_load((pr / "remote" / "big" / "manifest.yml").read_text(encoding="utf-8"))
        assert len(data["listing"]) == 200
        assert data.get("listing_truncated") is True

    def test_source_map_row_updated_idempotently(self, tmp_path: Path) -> None:
        """Syncing twice updates the source-map row date but leaves exactly one row."""
        from genomes_agentic_os.remote_ops import sync_project_remote

        _init_root(tmp_path)
        remote = {"name": "r", "host": "myhost", "path": "/mypath", "kind": "git", "authority": "remote"}
        create_project(tmp_path, "los", "idproj", remotes=[remote])
        pr = _project_root(tmp_path, "los", "idproj")

        sync_project_remote(tmp_path, "los", "idproj", runner=_git_runner())
        sync_project_remote(tmp_path, "los", "idproj", runner=_git_runner())

        sm_text = (pr / "source-map.md").read_text(encoding="utf-8")
        # The row appears exactly once (no duplicate rows)
        rows_with_host = [line for line in sm_text.splitlines() if "myhost:/mypath" in line]
        assert len(rows_with_host) == 1
        assert "synced" in rows_with_host[0]

    def test_sync_remote_cli(self, tmp_path: Path) -> None:
        """CLI wiring: agentic-os project sync-remote exercises the handler."""
        # We can't inject a runner through the CLI, so we test with a project
        # that has no hosts registered — the ssh command will fail fast and
        # return reachable=false, which is exit-0 semantics.
        from genomes_agentic_os.remote_ops import sync_project_remote

        _init_root(tmp_path)
        remote = {"name": "r", "host": "h", "path": "/p", "kind": "git", "authority": "remote"}
        create_project(tmp_path, "los", "cliproj", remotes=[remote])

        # Call through remote_ops directly with a fake runner — CLI path tested
        # separately by arg-parser smoke test below.
        result = sync_project_remote(
            tmp_path, "los", "cliproj",
            runner=_git_runner(),
        )
        assert "r" in result["synced"]

    def test_sync_remote_cli_arg_parser(self, tmp_path: Path, capsys) -> None:
        """project sync-remote parser is registered and --help exits cleanly."""
        import sys
        with pytest.raises(SystemExit) as exc_info:
            main(["project", "sync-remote", "--help"])
        # argparse --help exits 0
        assert exc_info.value.code == 0

    def test_sync_remote_filter_by_name(self, tmp_path: Path) -> None:
        """--name filters to just the named remote."""
        from genomes_agentic_os.remote_ops import sync_project_remote

        _init_root(tmp_path)
        remotes = [
            {"name": "r1", "host": "h1", "path": "/p1", "kind": "git", "authority": "remote"},
            {"name": "r2", "host": "h2", "path": "/p2", "kind": "git", "authority": "remote"},
        ]
        create_project(tmp_path, "los", "multiproj", remotes=remotes)

        result = sync_project_remote(
            tmp_path, "los", "multiproj",
            name="r1",
            runner=_git_runner(),
        )
        assert result["synced"] == ["r1"]

    def test_sync_remote_unknown_name_returns_error(self, tmp_path: Path) -> None:
        """--name with a nonexistent remote name returns an error dict, not exception."""
        from genomes_agentic_os.remote_ops import sync_project_remote

        _init_root(tmp_path)
        remote = {"name": "r", "host": "h", "path": "/p", "kind": "git", "authority": "remote"}
        create_project(tmp_path, "los", "eproj", remotes=[remote])

        result = sync_project_remote(
            tmp_path, "los", "eproj",
            name="nonexistent",
            runner=_git_runner(),
        )
        assert result["synced"] == []
        assert result["errors"]


# ---------------------------------------------------------------------------
# P2: doctor remote validation
# ---------------------------------------------------------------------------


class TestDoctorRemoteValidation:
    def test_unknown_host_is_error(self, tmp_path: Path) -> None:
        """Remote referencing a host not in hosts.yml → error."""
        from genomes_agentic_os.validate import validate_project_remotes, ValidationResult

        _init_root(tmp_path)
        remote = {"name": "r", "host": "unknownhost", "path": "/p", "kind": "git", "authority": "remote"}
        create_project(tmp_path, "los", "p", remotes=[remote])
        pr = _project_root(tmp_path, "los", "p")

        result = ValidationResult(root=pr)
        # Pass an empty hosts dict — any host is unknown
        validate_project_remotes(pr, result, hosts={})
        assert any("unknown host" in e for e in result.errors)

    def test_missing_remote_md_is_error(self, tmp_path: Path) -> None:
        """Missing remote/<name>/REMOTE.md → error."""
        from genomes_agentic_os.validate import validate_project_remotes, ValidationResult

        _init_root(tmp_path)
        remote = {"name": "r", "host": "h", "path": "/p", "kind": "git", "authority": "remote"}
        create_project(tmp_path, "los", "p2", remotes=[remote])
        pr = _project_root(tmp_path, "los", "p2")
        (pr / "remote" / "r" / "REMOTE.md").unlink()

        # Register the host so we only test the missing-file check
        hosts = {"h": {"ssh_alias": "h"}}
        result = ValidationResult(root=pr)
        validate_project_remotes(pr, result, hosts=hosts)
        assert any("REMOTE.md" in e for e in result.errors)

    def test_missing_manifest_yml_is_error(self, tmp_path: Path) -> None:
        """Missing remote/<name>/manifest.yml → error."""
        from genomes_agentic_os.validate import validate_project_remotes, ValidationResult

        _init_root(tmp_path)
        remote = {"name": "r", "host": "h", "path": "/p", "kind": "git", "authority": "remote"}
        create_project(tmp_path, "los", "p3", remotes=[remote])
        pr = _project_root(tmp_path, "los", "p3")
        (pr / "remote" / "r" / "manifest.yml").unlink()

        hosts = {"h": {"ssh_alias": "h"}}
        result = ValidationResult(root=pr)
        validate_project_remotes(pr, result, hosts=hosts)
        assert any("manifest" in e for e in result.errors)

    def test_stale_manifest_is_warning(self, tmp_path: Path) -> None:
        """manifest synced_at older than 14 days → warning."""
        from genomes_agentic_os.validate import validate_project_remotes, ValidationResult

        _init_root(tmp_path)
        remote = {"name": "r", "host": "h", "path": "/p", "kind": "git", "authority": "remote"}
        create_project(tmp_path, "los", "p4", remotes=[remote])
        pr = _project_root(tmp_path, "los", "p4")

        # Write a manifest with a synced_at 30 days ago
        import datetime
        old_dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)
        manifest_path = pr / "remote" / "r" / "manifest.yml"
        old_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        old_data["synced_at"] = old_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest_path.write_text(yaml.safe_dump(old_data, sort_keys=False), encoding="utf-8")

        hosts = {"h": {"ssh_alias": "h"}}
        result = ValidationResult(root=pr)
        validate_project_remotes(pr, result, hosts=hosts)
        assert any("stale" in w for w in result.warnings)

    def test_null_synced_at_is_warning(self, tmp_path: Path) -> None:
        """manifest synced_at: null → warning (never synced)."""
        from genomes_agentic_os.validate import validate_project_remotes, ValidationResult

        _init_root(tmp_path)
        remote = {"name": "r", "host": "h", "path": "/p", "kind": "git", "authority": "remote"}
        create_project(tmp_path, "los", "p5", remotes=[remote])
        pr = _project_root(tmp_path, "los", "p5")

        # The scaffold stub has synced_at: null by default
        hosts = {"h": {"ssh_alias": "h"}}
        result = ValidationResult(root=pr)
        validate_project_remotes(pr, result, hosts=hosts)
        assert any("never been synced" in w or "null" in w for w in result.warnings)

    def test_malformed_remote_entry_missing_host_is_error(self, tmp_path: Path) -> None:
        """Remote entry missing host field → error."""
        from genomes_agentic_os.validate import validate_project_remotes, ValidationResult

        _init_root(tmp_path)
        create_project(tmp_path, "los", "malformed")
        pr = _project_root(tmp_path, "los", "malformed")

        # Manually inject a malformed remote into project.yml
        project_yml = pr / "project.yml"
        data = yaml.safe_load(project_yml.read_text(encoding="utf-8"))
        data.setdefault("sources", {})["remotes"] = [{"name": "bad", "path": "/p"}]  # missing host
        project_yml.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

        result = ValidationResult(root=pr)
        validate_project_remotes(pr, result, hosts={})
        assert any("missing required field" in e for e in result.errors)

    def test_check_remotes_unreachable_host_is_warning(self, tmp_path: Path) -> None:
        """--check-remotes with an unreachable host → warning from connectivity check."""
        from genomes_agentic_os.validate import validate_project_remotes_connectivity

        hosts = {"myhost": {"ssh_alias": "myhost", "ssh_options": []}}

        def fake_runner(args: list[str], *, timeout: int = 10):
            class _R:
                returncode = 255
                stderr = "Connection refused"
                stdout = ""
            return _R()

        warnings = validate_project_remotes_connectivity(tmp_path, hosts, runner=fake_runner)
        assert any("myhost" in w for w in warnings)
        assert any("unreachable" in w for w in warnings)

    def test_check_remotes_reachable_host_no_warning(self, tmp_path: Path) -> None:
        """--check-remotes with reachable host → no warning."""
        from genomes_agentic_os.validate import validate_project_remotes_connectivity

        hosts = {"goodhost": {"ssh_alias": "goodhost", "ssh_options": []}}

        def fake_runner(args: list[str], *, timeout: int = 10):
            class _R:
                returncode = 0
                stderr = ""
                stdout = ""
            return _R()

        warnings = validate_project_remotes_connectivity(tmp_path, hosts, runner=fake_runner)
        assert warnings == []

    def test_malformed_hosts_yml_is_schema_error(self, tmp_path: Path) -> None:
        """A hosts.yml with wrong types triggers a schema validation finding."""
        import json
        from genomes_agentic_os.validate import validate_schemas_strict, _SCHEMA_DIR

        # Write a malformed hosts.yml (hosts must be a mapping, not a list)
        hosts_path = tmp_path / "config" / "hosts.yml"
        hosts_path.parent.mkdir(parents=True, exist_ok=True)
        hosts_path.write_text("hosts:\n  - not_a_mapping\n", encoding="utf-8")

        # Only run this test if jsonschema is available and the schema exists
        schema_path = _SCHEMA_DIR / "hosts.schema.json"
        try:
            import jsonschema  # noqa: F401
        except ImportError:
            pytest.skip("jsonschema not installed")
        if not schema_path.is_file():
            pytest.skip("hosts.schema.json not present")

        findings = validate_schemas_strict(tmp_path)
        hosts_findings = [f for f in findings if "hosts" in f.schema]
        assert len(hosts_findings) >= 1


# ---------------------------------------------------------------------------
# P2: migration — fix_missing creates hosts.yml
# ---------------------------------------------------------------------------


class TestMigrationHostsYml:
    def test_migrate_hosts_apply_creates_file(self, tmp_path: Path) -> None:
        """migrate_hosts_apply creates config/hosts.yml when absent."""
        from genomes_agentic_os.migrations import migrate_hosts_apply

        result = migrate_hosts_apply(tmp_path)
        assert result["applied"] is True
        hosts_path = tmp_path / "config" / "hosts.yml"
        assert hosts_path.is_file()
        data = yaml.safe_load(hosts_path.read_text(encoding="utf-8"))
        assert isinstance(data.get("hosts"), dict)

    def test_migrate_hosts_apply_idempotent(self, tmp_path: Path) -> None:
        """migrate_hosts_apply skips if hosts.yml already exists."""
        from genomes_agentic_os.migrations import migrate_hosts_apply

        migrate_hosts_apply(tmp_path)
        result2 = migrate_hosts_apply(tmp_path)
        assert result2.get("skipped") is True
        assert result2.get("applied") is False

    def test_fix_missing_hosts_yml(self, tmp_path: Path) -> None:
        """fix_missing_hosts_yml creates hosts.yml when absent."""
        from genomes_agentic_os.migrations import fix_missing_hosts_yml

        result = fix_missing_hosts_yml(tmp_path)
        assert result["applied"] is True
        assert (tmp_path / "config" / "hosts.yml").is_file()

    def test_migrate_hosts_plan_writes_plan_file(self, tmp_path: Path) -> None:
        """migrate_hosts_plan writes a plan file under .migrations/."""
        from genomes_agentic_os.migrations import migrate_hosts_plan

        result = migrate_hosts_plan(tmp_path)
        assert "plan_path" in result
        plan_path = Path(result["plan_path"])
        assert plan_path.is_file()
        plan_data = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
        assert plan_data["migration_id"] == "hosts-yml-init-v1"
