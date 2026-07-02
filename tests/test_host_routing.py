"""Tests for feat/024 cross-host routing logic in agentic-harness-run.

All tests run OFFLINE — no real SSH connections, no network access.
SSH/pgrep runners are replaced with injectable fakes.

Acceptance criteria covered:
  AC1  — --host local produces identical argv/env to the pre-feat/024 path (regression guard).
  AC2  — Path translation: Agentic OS local → /home/genome/projects/genomes_agentic_os.
  AC2b — Path translation: unknown project falls back to path_rewrite /Users/genome→/home/genome.
  AC3  — Eligibility: LOS Django → genomesbox INELIGIBLE (no project_paths entry).
  AC4  — Probe daemon-exclusion: app-server/--serve lines do NOT match probe_pattern.
  AC4b — Probe timeout → returns max_concurrent (at-capacity).
  AC5  — least_active picks the lower-count eligible host.
  AC5b — All hosts at-capacity → fallback to bigmac.
  AC6  — wrap_remote for claude prepends env -u ANTHROPIC_API_KEY inside SSH command string.
  AC7  — wrap_remote for gpt does NOT prepend env -u ANTHROPIC_API_KEY.
  AC8  — local_view_path maps a genomesbox remote_cwd to the SSHFS local path.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Load agentic-harness-run as a module (filename has hyphens, so no regular import).
# ---------------------------------------------------------------------------

_BIN_PATH = Path(__file__).resolve().parent.parent / "harness" / "bin" / "agentic-harness-run"


def _load_harness_run():
    loader = importlib.machinery.SourceFileLoader("harness_run", str(_BIN_PATH))
    spec = importlib.util.spec_from_loader("harness_run", loader)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


hr = _load_harness_run()


# ---------------------------------------------------------------------------
# Fixture data (mirrors SPEC §8.2 and config/hosts.yml)
# ---------------------------------------------------------------------------

ROUTING: dict = {
    "hosts": {
        "bigmac": {
            "role": "primary",
            "max_concurrent": 5,
            "harnesses": ["claude", "gpt"],
            "project_paths": {
                "Agentic OS": "/Users/genome/projects/genomes_agentic_os",
                "Genome's Brain": "/Users/genome/projects/genomes_agentic_os",
                "LOS Django": "/Users/genome/projects/los-app-los-django",
                "LedgerLine": "/Users/genome/projects/ledgerline",
                "LOSMON": "/Users/genome/agentic_os/los/02-projects/losmon",
            },
            "path_rewrite": [],
        },
        "genomesbox": {
            "role": "worker",
            "max_concurrent": 3,
            "harnesses": ["claude", "gpt"],
            "project_paths": {
                "Agentic OS": "/home/genome/projects/genomes_agentic_os",
                "Genome's Brain": "/home/genome/projects/genomes_agentic_os",
                "LedgerLine": "/home/genome/projects/ledgerline",
                "LOSMON": "/home/genome/projects/losmon",
                # NOTE: "LOS Django" intentionally absent
            },
            "path_rewrite": [
                {"from": "/Users/genome", "to": "/home/genome"},
            ],
        },
    },
    "auto_route": {
        "enabled": True,
        "strategy": "least_active",
        "probe": "ssh_pgrep",
        "probe_pattern": "[c]laude -p|[c]odex exec",
        "probe_timeout_sec": 6,
        "on_probe_failure": "treat_at_capacity",
        "candidate_order": ["genomesbox", "bigmac"],
        "fallback_host": "bigmac",
    },
    "artifact_return": {
        "default": "sshfs_visibility",
        "sshfs_mounts": {
            "genomesbox": {
                "remote_root": "/home/genome/projects",
                "local_root": "/Users/genome/agentic_os/SSH_genomesbox/projects",
            },
        },
    },
}

HOSTS: dict = {
    "bigmac": {
        "ssh_alias": "bigmac",
        "user": "genome",
        "home": "/Users/genome",
        "description": "Primary laptop",
    },
    "genomesbox": {
        "ssh_alias": "genomesbox",
        "user": "genome",
        "home": "/home/genome",
        "description": "32-core Linux box",
        "ssh_options": ["-o", "ClearAllForwardings=yes"],
    },
}


# ---------------------------------------------------------------------------
# Fake SSH runner helpers
# ---------------------------------------------------------------------------

@dataclass
class FakeResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


def _runner_count(n: int):
    """Return a runner that reports n active processes (pgrep wc -l output)."""
    def runner(argv, timeout=20):
        return FakeResult(returncode=0, stdout=f"{n}\n")
    return runner


def _runner_timeout():
    """Return a runner that simulates a timeout (subprocess.TimeoutExpired)."""
    import subprocess

    def runner(argv, timeout=20):
        raise subprocess.TimeoutExpired(argv, timeout)
    return runner


def _runner_ssh_fail():
    """Return a runner that simulates SSH connection failure (non-zero exit)."""
    def runner(argv, timeout=20):
        return FakeResult(returncode=255, stdout="", stderr="Connection refused")
    return runner


# ---------------------------------------------------------------------------
# AC1 — Local path regression guard
# ---------------------------------------------------------------------------


def test_build_cmd_claude_unchanged():
    """build_cmd_claude returns identical argv to the pre-feat/024 shape."""
    cmd, env = hr.build_cmd_claude("do something", None)
    assert cmd == ["claude", "-p", "do something"]
    assert "ANTHROPIC_API_KEY" not in env


def test_build_cmd_claude_with_model():
    cmd, env = hr.build_cmd_claude("do something", "haiku")
    assert cmd == ["claude", "-p", "do something", "--model", "haiku"]


def test_build_cmd_gpt_unchanged():
    cmd, env = hr.build_cmd_gpt("do something", None, Path("/tmp"))
    assert cmd == ["codex", "exec", "--skip-git-repo-check", "do something"]


# ---------------------------------------------------------------------------
# AC2 — Path translation (project_paths lookup)
# ---------------------------------------------------------------------------


def test_resolve_remote_cwd_known_project():
    """Agentic OS local cwd → exact genomesbox project_paths entry."""
    result = hr.resolve_remote_cwd(
        "/Users/genome/projects/genomes_agentic_os",
        "genomesbox",
        ROUTING,
    )
    assert result == "/home/genome/projects/genomes_agentic_os"


def test_resolve_remote_cwd_ledgerline():
    result = hr.resolve_remote_cwd(
        "/Users/genome/projects/ledgerline",
        "genomesbox",
        ROUTING,
    )
    assert result == "/home/genome/projects/ledgerline"


def test_resolve_remote_cwd_losmon():
    """LOSMON path on bigmac is non-standard; rewrite fallback applies."""
    result = hr.resolve_remote_cwd(
        "/Users/genome/agentic_os/los/02-projects/losmon",
        "genomesbox",
        ROUTING,
    )
    # Not in bigmac project_paths (it is, but genomesbox project_paths maps it to /home/genome/projects/losmon)
    assert result == "/home/genome/projects/losmon"


# ---------------------------------------------------------------------------
# AC2b — Path translation fallback (path_rewrite)
# ---------------------------------------------------------------------------


def test_resolve_remote_cwd_unknown_project_rewrite():
    """A path not in project_paths falls back to prefix-rewrite."""
    result = hr.resolve_remote_cwd(
        "/Users/genome/projects/some-other-thing",
        "genomesbox",
        ROUTING,
    )
    assert result == "/home/genome/projects/some-other-thing"


def test_resolve_remote_cwd_no_rewrite_bigmac():
    """bigmac has empty path_rewrite; unknown paths pass through unchanged."""
    result = hr.resolve_remote_cwd(
        "/Users/genome/projects/some-thing",
        "bigmac",
        ROUTING,
    )
    assert result == "/Users/genome/projects/some-thing"


# ---------------------------------------------------------------------------
# AC3 — Eligibility: LOS Django → genomesbox ineligible
# ---------------------------------------------------------------------------


def test_eligible_hosts_los_django_excludes_genomesbox():
    """LOS Django is absent from genomesbox.project_paths → genomesbox INELIGIBLE."""
    result = hr.eligible_hosts("LOS Django", "claude", ROUTING)
    assert "genomesbox" not in result
    assert "bigmac" in result


def test_eligible_hosts_agentic_os_includes_genomesbox():
    """Agentic OS is present on both hosts."""
    result = hr.eligible_hosts("Agentic OS", "claude", ROUTING)
    assert "genomesbox" in result
    assert "bigmac" in result


def test_eligible_hosts_unknown_project_includes_no_host():
    """A project not in any host's project_paths → empty eligibility list."""
    result = hr.eligible_hosts("NonExistentProject", "gpt", ROUTING)
    assert result == []


def test_eligible_hosts_no_project_filter():
    """When project is None, only harness filter applies."""
    result = hr.eligible_hosts(None, "claude", ROUTING)
    assert "bigmac" in result
    assert "genomesbox" in result


# ---------------------------------------------------------------------------
# AC4 — Probe daemon-exclusion
# ---------------------------------------------------------------------------

_PROBE_PATTERN = "[c]laude -p|[c]odex exec"


@pytest.mark.parametrize("process_line, should_match", [
    # Real runs — MUST match (processes contain literal "claude -p" or "codex exec")
    ("claude -p 'do something' --model sonnet", True),
    ("codex exec --skip-git-repo-check some prompt", True),
    ("/home/genome/.local/bin/claude -p the prompt here", True),
    # Daemons — MUST NOT match
    ("codex app-server --listen 0.0.0.0:8080", False),
    ("claude --serve --port 9000", False),
    ("node /home/genome/.local/lib/node_modules/codex/server.js", False),
    ("claude server --serve 127.0.0.1:3001", False),
    # Bracket trick: the pgrep/zsh wrapper argv contains the literal pattern string
    # "[c]laude -p|[c]odex exec" — the regex MUST NOT match it (no self-match).
    ("zsh -c pgrep -f '[c]laude -p|[c]odex exec' | wc -l", False),
    ("pgrep -f [c]laude -p|[c]odex exec", False),
])
def test_probe_pattern_daemon_exclusion(process_line, should_match):
    """Probe pattern correctly matches runs and excludes daemons and the pgrep wrapper itself.

    The bracket trick: pattern "[c]laude -p" is a regex that matches "claude -p"
    (character class [c] = literal 'c'), but does NOT match "[c]laude -p" (with
    literal brackets), so the SSH/zsh wrapper process cannot match its own argv.

    Note: pgrep -f matches the full command line; we test the pattern here
    as a substring search to replicate what pgrep does.
    """
    # pgrep -f with a pattern containing '|' treats it as a regex alternation.
    # We replicate that with re.search.
    matched = bool(re.search(_PROBE_PATTERN, process_line))
    assert matched is should_match, (
        f"Pattern {_PROBE_PATTERN!r} vs {process_line!r}: "
        f"expected match={should_match}, got {matched}"
    )


# ---------------------------------------------------------------------------
# AC4b — Probe timeout → at-capacity
# ---------------------------------------------------------------------------


def test_probe_timeout_returns_max_concurrent():
    """Probe timeout → returns max_concurrent (treat as at-capacity)."""
    count = hr.probe_active_count(
        "genomesbox",
        ROUTING,
        HOSTS,
        runner=_runner_timeout(),
    )
    assert count == 3  # genomesbox max_concurrent


def test_probe_ssh_failure_returns_max_concurrent():
    """Non-zero SSH exit → returns max_concurrent."""
    count = hr.probe_active_count(
        "genomesbox",
        ROUTING,
        HOSTS,
        runner=_runner_ssh_fail(),
    )
    assert count == 3


# ---------------------------------------------------------------------------
# AC5 — least_active picks lower-count eligible host
# ---------------------------------------------------------------------------


def test_least_active_picks_genomesbox_when_idle():
    """genomesbox has 0 active, bigmac has 2 → genomesbox wins."""
    call_log: list[str] = []

    def runner(argv, timeout=20):
        host_in_argv = argv[4] if len(argv) > 4 else ""
        call_log.append(host_in_argv)
        # genomesbox returns 0 active; simulate by returning 0
        if "genomesbox" in " ".join(argv):
            return FakeResult(returncode=0, stdout="0\n")
        # bigmac probe uses local pgrep; we won't hit it if genomesbox wins
        return FakeResult(returncode=0, stdout="2\n")

    result = hr.least_active_host(
        ["genomesbox", "bigmac"],
        "Agentic OS",
        "claude",
        ROUTING,
        HOSTS,
        runner=runner,
    )
    assert result == "genomesbox"


def test_least_active_falls_back_when_genomesbox_full():
    """genomesbox at max_concurrent (3) → bigmac wins."""
    def runner(argv, timeout=20):
        if "genomesbox" in " ".join(argv):
            return FakeResult(returncode=0, stdout="3\n")  # at capacity
        return FakeResult(returncode=1, stdout="")  # pgrep no match = 0 on bigmac

    result = hr.least_active_host(
        ["genomesbox", "bigmac"],
        "Agentic OS",
        "claude",
        ROUTING,
        HOSTS,
        runner=runner,
    )
    assert result == "bigmac"


def test_least_active_fallback_when_all_at_capacity():
    """All hosts at-capacity → returns fallback_host (bigmac)."""
    def runner(argv, timeout=20):
        # genomesbox: 3 (full); bigmac local pgrep: timeout
        if "genomesbox" in " ".join(argv):
            return FakeResult(returncode=0, stdout="3\n")
        raise __import__("subprocess").TimeoutExpired(argv, 6)

    result = hr.least_active_host(
        ["genomesbox", "bigmac"],
        "Agentic OS",
        "claude",
        ROUTING,
        HOSTS,
        runner=runner,
    )
    assert result == "bigmac"


def test_least_active_los_django_ineligible_genomesbox():
    """LOS Django → genomesbox ineligible → bigmac must be selected."""
    def runner(argv, timeout=20):
        return FakeResult(returncode=0, stdout="0\n")

    result = hr.least_active_host(
        ["genomesbox", "bigmac"],
        "LOS Django",
        "claude",
        ROUTING,
        HOSTS,
        runner=runner,
    )
    assert result == "bigmac"


# ---------------------------------------------------------------------------
# AC6 — wrap_remote for claude prepends env -u ANTHROPIC_API_KEY remotely
# ---------------------------------------------------------------------------


def test_wrap_remote_claude_strips_api_key_inside_ssh():
    """Claude remote wrap must include env -u ANTHROPIC_API_KEY in the SSH command string."""
    base_cmd = ["claude", "-p", "do the thing"]
    ssh_argv = hr.wrap_remote(base_cmd, "claude", "genomesbox", "/home/genome/projects/foo", ["-o", "ClearAllForwardings=yes"])

    # The SSH command must start with ssh -o BatchMode=yes
    assert ssh_argv[0] == "ssh"
    assert "-o" in ssh_argv
    assert "BatchMode=yes" in ssh_argv
    assert "genomesbox" in ssh_argv

    # The final element is the remote command string
    remote_str = ssh_argv[-1]
    assert "env -u ANTHROPIC_API_KEY" in remote_str
    assert "claude -p" in remote_str
    assert "do the thing" in remote_str
    # Must cd to the remote path first
    assert "cd '/home/genome/projects/foo'" in remote_str or "cd /home/genome/projects/foo" in remote_str


# ---------------------------------------------------------------------------
# AC7 — wrap_remote for gpt does NOT prepend env -u ANTHROPIC_API_KEY
# ---------------------------------------------------------------------------


def test_wrap_remote_gpt_no_api_key_strip():
    """GPT remote wrap must NOT include env -u ANTHROPIC_API_KEY."""
    base_cmd = ["codex", "exec", "--skip-git-repo-check", "the prompt"]
    ssh_argv = hr.wrap_remote(base_cmd, "gpt", "genomesbox", "/home/genome/projects/foo", [])

    remote_str = ssh_argv[-1]
    assert "ANTHROPIC_API_KEY" not in remote_str
    assert "codex exec" in remote_str


# ---------------------------------------------------------------------------
# AC8 — local_view_path maps remote_cwd to SSHFS mount
# ---------------------------------------------------------------------------


def test_local_view_path_genomesbox():
    """A genomesbox remote_cwd under /home/genome/projects maps to the SSHFS mount."""
    view = hr.local_view_path(
        "/home/genome/projects/genomes_agentic_os",
        ROUTING,
    )
    assert view == "/Users/genome/agentic_os/SSH_genomesbox/projects/genomes_agentic_os"


def test_local_view_path_not_in_mount():
    """A path outside any declared SSHFS mount returns None."""
    view = hr.local_view_path(
        "/home/genome/other/path",
        ROUTING,
    )
    assert view is None


def test_local_view_path_empty_routing():
    """No artifact_return config → returns None gracefully."""
    view = hr.local_view_path("/home/genome/projects/foo", {})
    assert view is None


# ---------------------------------------------------------------------------
# Additional: reverse_lookup_project
# ---------------------------------------------------------------------------


def test_reverse_lookup_project_known():
    project = hr.reverse_lookup_project(
        "/Users/genome/projects/genomes_agentic_os",
        ROUTING,
    )
    assert project == "Agentic OS"


def test_reverse_lookup_project_unknown():
    project = hr.reverse_lookup_project(
        "/Users/genome/projects/no-such-project",
        ROUTING,
    )
    assert project is None
