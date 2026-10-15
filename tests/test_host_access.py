"""Behavior and secret boundaries of the portable host transport."""

import importlib.machinery
import importlib.util
import os
from pathlib import Path
import shlex
import subprocess

import pytest


PATH = Path(__file__).resolve().parents[1] / "harness/bin/agentic-os-host"
loader = importlib.machinery.SourceFileLoader("host_access", str(PATH))
spec = importlib.util.spec_from_loader(loader.name, loader)
host = importlib.util.module_from_spec(spec)
loader.exec_module(host)


@pytest.fixture
def credentials(tmp_path):
    path = tmp_path / "hosts.env"
    path.write_text("\n".join(f'{h}_{f}={v}' for h in host.HOSTS for f, v in
                             [("HOST_NAME", h.lower()), ("USER", "operator"), ("PASS", "'p@ss $(touch nope) # literal'")]))
    path.chmod(0o600)
    return path


def test_literal_credentials_and_private_mode(credentials):
    values = host.load_credentials(credentials)
    assert values["WORKMAC_PASS"] == "p@ss $(touch nope) # literal"
    credentials.chmod(0o644)
    with pytest.raises(host.AccessError, match="0600"):
        host.load_credentials(credentials)


def test_reject_symlink(credentials, tmp_path):
    link = tmp_path / "link"
    link.symlink_to(credentials)
    with pytest.raises(host.AccessError, match="cannot read"):
        host.load_credentials(link)


@pytest.mark.parametrize("extra", ["BIGMAC_USER=duplicate", "WORKMAC_PASS='unterminated"])
def test_invalid_file_never_discloses_values(credentials, extra):
    credentials.write_text(credentials.read_text() + "\n" + extra)
    with pytest.raises(host.AccessError) as exc:
        host.load_credentials(credentials)
    assert "p@ss" not in str(exc.value)
    assert "unterminated" not in str(exc.value)


def test_reject_option_injection(credentials):
    credentials.write_text(credentials.read_text().replace("BIGMAC_HOST_NAME=bigmac", "BIGMAC_HOST_NAME=-oProxyCommand=evil"))
    with pytest.raises(host.AccessError, match="invalid host"):
        host.load_credentials(credentials)


def test_ssh_transport_quotes_and_requires_trust(credentials):
    values = host.load_credentials(credentials)
    command = ["printf", "%s", "$(touch forbidden); 'quote'"]
    args = host.ssh_argv("BIGMAC", values, command, False)
    assert shlex.split(args[-1]) == command
    for setting in ["BatchMode=yes", "StrictHostKeyChecking=yes", "IdentityAgent=none", "ControlPath=none"]:
        assert setting in args
    assert values["BIGMAC_PASS"] not in " ".join(args)


def test_sudo_password_is_private_stdin_and_output_redacted(credentials, monkeypatch):
    values = host.load_credentials(credentials)
    secret = values["BIGMAC_PASS"].encode()
    class Process:
        returncode = 17
        def __init__(self, args, **kwargs):
            assert secret.decode() not in repr(args)
            assert "env" not in kwargs
            command = shlex.split(args[-1])
            assert command[:3] == ["/usr/bin/sudo", "-k", "-S"]
            assert 'exec </dev/null; exec "$@"' in command
        def communicate(self, payload, timeout):
            assert payload == secret + b"\n"
            return b"result " + secret, secret + b" error"
    monkeypatch.setattr(host.subprocess, "Popen", Process)
    code, output, error = host.execute("BIGMAC", values, ["id", "-u"], sudo=True)
    assert code == 17
    assert output == b"result [REDACTED]"
    assert error == b"[REDACTED] error"


def test_nopasswd_command_cannot_read_unused_password(credentials):
    values = host.load_credentials(credentials)
    args = shlex.split(host.ssh_argv("BIGMAC", values, ["cat"], True)[-1])
    # Model sudo granting NOPASSWD by skipping its prefix and executing the
    # exact privileged shell with the unconsumed password still on stdin.
    completed = subprocess.run(args[args.index("/bin/sh"):], input=b"private-password\n", capture_output=True)
    assert completed.returncode == 0
    assert completed.stdout == b""


def test_timeout_stops_local_process_group(credentials, monkeypatch):
    values = host.load_credentials(credentials)
    signals = []
    class Process:
        pid = 12345
        calls = 0
        def __init__(self, *args, **kwargs):
            assert kwargs["start_new_session"]
        def communicate(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired("ssh", 1)
            return b"", b""
    monkeypatch.setattr(host.subprocess, "Popen", Process)
    monkeypatch.setattr(os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    code, output, error = host.execute("BIGMAC", values, ["sleep", "10"], timeout=1)
    assert code == 124 and signals and not output
    assert b"inspect remote state" in error


def test_deadline_and_sudo_stdin_are_bounded(credentials):
    values = host.load_credentials(credentials)
    with pytest.raises(host.AccessError, match="120"):
        host.execute("BIGMAC", values, ["true"], timeout=121)
    with pytest.raises(host.AccessError, match="/dev/null"):
        host.execute("BIGMAC", values, ["cat"], sudo=True, input_data=b"input")


def test_existing_harness_discovery_is_additive_and_idempotent(tmp_path):
    from genomes_agentic_os.scaffold import ScaffoldResult, ensure_host_access_contract
    harness = tmp_path / "harness"
    harness.mkdir()
    for name in ("AGENTS.md", "RULES.md", "TOOLS.md"):
        (harness / name).write_text("# Operator-owned text\nKeep this setting.\n")
    result = ScaffoldResult()
    ensure_host_access_contract(tmp_path, result)
    assert len(result.updated) == 3
    for name in ("AGENTS.md", "RULES.md", "TOOLS.md"):
        text = (harness / name).read_text()
        assert text.startswith("# Operator-owned text\nKeep this setting.")
        assert text.count("<!-- agentic-os-host-access:start -->") == 1
    again = ScaffoldResult()
    ensure_host_access_contract(tmp_path, again)
    assert again.updated == []


def test_fresh_root_exposes_host_access_without_credentials(tmp_path):
    from genomes_agentic_os.scaffold import ScaffoldResult, ensure_root_files
    ensure_root_files(tmp_path, ScaffoldResult(), domains=["personal"])
    assert not (tmp_path / "hosts.env").exists()
    for name in ("AGENTS.md", "RULES.md", "TOOLS.md"):
        assert "agentic-os-host" in (tmp_path / "harness" / name).read_text()


def test_check_accepts_password_matching_identity_without_disclosing_it(credentials, monkeypatch):
    values = host.load_credentials(credentials)
    values["BIGMAC_PASS"] = "operator"
    def execute(label, values, command, **kwargs):
        assert kwargs["redact_output"] is False
        return 0, b"0\n" if kwargs.get("sudo") else b"operator\n", b""
    monkeypatch.setattr(host, "execute", execute)
    result = host.check("BIGMAC", values, True, 10)
    assert result["passed"]
    assert "operator" not in str(result)
