"""Behavioral regressions for the FLYWL-5402 implementation-claim failure."""

import importlib.util
from importlib.machinery import SourceFileLoader
import json
from pathlib import Path
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "harness/bin/agentic-os-jira-claim-check"
spec = importlib.util.spec_from_loader(
    "jira_claim_gate", SourceFileLoader("jira_claim_gate", str(SCRIPT))
)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
ACCOUNT = "required-account"


def issue():
    return {
        "key": "FLYWL-5402",
        "fields": {
            "assignee": {"accountId": ACCOUNT},
            "customfield_10145": [{"accountId": ACCOUNT}],
            "status": {"name": "In Progress"},
            "fixVersions": [{"name": "10.1"}],
        },
    }


def verify(value, site="venturesgo.atlassian.net"):
    calls = []

    def read(argv):
        calls.append(argv)
        return (
            "Authenticated\n Site: " + site
            if argv == ["auth", "status"]
            else json.dumps(value)
        )

    result = gate.verify_claim(
        "FLYWL-5402",
        "venturesgo.atlassian.net",
        ACCOUNT,
        "customfield_10145",
        "10.1",
        reader=read,
    )
    assert calls == [
        ["auth", "status"],
        ["workitem", "view", "FLYWL-5402", "--fields", "*all", "--json"],
    ]
    return result


def test_matching_live_claim_passes_without_any_mutation():
    receipt = verify(issue())
    assert receipt["status"] == "passed"
    assert receipt["workflow_status"] == "In Progress"
    assert receipt["fix_versions"] == ["10.1"]
    assert receipt["source"] == "live_acli_readback"
    assert "summary" not in receipt


def test_original_failure_is_rejected_even_with_developer_set():
    value = issue()
    value["fields"].update(assignee=None, status={"name": "Requirements"})
    with pytest.raises(gate.ClaimError, match="Assignee.*Status"):
        verify(value)


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("assignee", None, "Assignee"),
        ("assignee", {"accountId": "someone-else"}, "Assignee"),
        ("customfield_10145", [], "Developer"),
        ("customfield_10145", [{"accountId": "someone-else"}], "Developer"),
        ("status", {"name": "Requirements"}, "Status"),
        ("status", {"name": "In Review"}, "Status"),
        ("fixVersions", [], "Fix Version"),
        ("fixVersions", [{"name": "10.0"}], "Fix Version"),
        ("fixVersions", None, "Fix Version"),
    ],
)
def test_partial_claims_block(field, value, reason):
    data = issue()
    data["fields"][field] = value
    with pytest.raises(gate.ClaimError, match=reason):
        verify(data)


def test_wrong_site_stops_before_issue_read():
    with pytest.raises(gate.ClaimError, match="site"):
        verify(issue(), site="another.atlassian.net")


@pytest.mark.parametrize("value", [{"key": "FLYWL-1"}, [], {"key": "FLYWL-5402"}])
def test_wrong_or_incomplete_provider_payload_blocks(value):
    with pytest.raises(gate.ClaimError):
        verify(value)


def test_malformed_json_blocks():
    def read(argv):
        return (
            "Site: venturesgo.atlassian.net"
            if argv == ["auth", "status"]
            else "not-json"
        )

    with pytest.raises(gate.ClaimError, match="valid JSON"):
        gate.verify_claim(
            "FLYWL-5402",
            "venturesgo.atlassian.net",
            ACCOUNT,
            "customfield_10145",
            reader=read,
        )


@pytest.mark.parametrize(
    "failure", [FileNotFoundError(), subprocess.TimeoutExpired("acli", 30)]
)
def test_provider_unavailability_blocks_without_echoing_output(monkeypatch, failure):
    def run(*args, **kwargs):
        raise failure

    monkeypatch.setattr(gate.subprocess, "run", run)
    with pytest.raises(gate.ClaimError, match="unavailable"):
        gate.run_acli(["auth", "status"])


def test_provider_failure_does_not_leak_output(monkeypatch):
    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1, "private", "secret"),
    )
    with pytest.raises(gate.ClaimError) as exc:
        gate.run_acli(["auth", "status"])
    assert "private" not in str(exc.value)
    assert "secret" not in str(exc.value)
