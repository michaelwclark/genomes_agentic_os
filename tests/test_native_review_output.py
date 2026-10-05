"""Native schema transport authority and immutable stdout regression guards."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from genomes_agentic_os.native_review_output import (
    NATIVE_REVIEW_SCHEMA,
    NativeReviewOutputError,
    parse_native_review_output,
    project_native_review,
)
from test_opposing_model_review_runner import _load_runner


def finding(**changes):
    return {
        "id": "F1", "severity": "high", "category": "tests", "file": "tests/test_review.py",
        "line": 3, "title": "Missing guard", "detail": "The failure path is untested.",
        "suggested_fix": "Add the regression guard.", "blocking": True, **changes,
    }


def envelope(verdict="CLEAN", findings=None, **changes):
    return {
        "type": "result", "subtype": "success", "is_error": False,
        "result": "Review completed. Commentary may follow the verdict.",
        "structured_output": {"verdict": verdict, "findings": findings or []},
        "session_id": "fixture-session", "usage": {"output_tokens": 20}, **changes,
    }


def encoded(value):
    return json.dumps(value).encode()


@pytest.mark.parametrize("verdict,findings", [
    ("CLEAN", []), ("CLEAN", [finding(blocking=False)]),
    ("FINDINGS", [finding()]), ("FINDINGS", [finding(blocking=False)]),
])
def test_typed_native_verdict_and_findings_project_deterministically(verdict, findings):
    payload = parse_native_review_output(encoded(envelope(verdict, findings)))
    assert payload == {"verdict": verdict, "findings": findings}
    projection = project_native_review(payload)
    runner = _load_runner()
    assert runner.parse_review_verdict(projection) == (verdict.lower(), True)
    assert runner.parse_structured_findings(projection) == findings


@pytest.mark.parametrize("changes", [
    {"type": "system"}, {"subtype": "error_during_execution"}, {"subtype": "error_max_turns"},
    {"subtype": "error_max_structured_output_retries"}, {"is_error": True}, {"is_error": 0},
    {"is_error": "false"}, {"errors": ["authentication unavailable"]}, {"error": "failed"},
    {"structured_output": None}, {"structured_output": []}, {"result": 42},
    {"verdict": "CLEAN"}, {"findings": []},
])
def test_native_error_missing_and_ambiguous_envelopes_are_rejected(changes):
    value = envelope()
    value.update(changes)
    with pytest.raises(NativeReviewOutputError):
        parse_native_review_output(encoded(value))


@pytest.mark.parametrize("field", ["type", "subtype", "is_error", "result", "structured_output"])
def test_native_success_envelope_requires_each_authority_field(field):
    value = envelope()
    del value[field]
    with pytest.raises(NativeReviewOutputError):
        parse_native_review_output(encoded(value))


@pytest.mark.parametrize("stdout", [
    b"", b"not json", b"[]", b"null", b"{}\n{}", b"\xff",
    b'{"type":"result","type":"result"}',
    encoded(envelope()).replace(b'"verdict": "CLEAN"', b'"verdict": "CLEAN", "verdict": "CLEAN"'),
    encoded(envelope()).replace(b'"output_tokens": 20', b'"output_tokens": NaN'),
])
def test_invalid_json_and_duplicate_keys_never_establish_authority(stdout):
    with pytest.raises(NativeReviewOutputError):
        parse_native_review_output(stdout)


@pytest.mark.parametrize("payload", [
    {}, {"verdict": "CLEAN"}, {"findings": []},
    {"verdict": "clean", "findings": []}, {"verdict": True, "findings": []},
    {"verdict": "CLEAN", "findings": {}}, {"verdict": "CLEAN", "findings": [42]},
    {"verdict": "CLEAN", "findings": [finding()]},
    {"verdict": "FINDINGS", "findings": []},
    {"verdict": "CLEAN", "findings": [], "other_verdict": "FINDINGS"},
    {"verdict": "CLEAN", "findings": [], "summary": 3},
])
def test_invalid_or_contradictory_structured_payload_is_rejected(payload):
    with pytest.raises(NativeReviewOutputError):
        parse_native_review_output(encoded(envelope(structured_output=payload)))


@pytest.mark.parametrize("field,value", [
    ("id", 1), ("id", "  "), ("severity", "HIGH"), ("category", "other"),
    ("file", []), ("file", ""), ("line", 0), ("line", -1), ("line", "3"),
    ("line", True), ("line", 3.0), ("title", None), ("detail", " "),
    ("suggested_fix", False), ("blocking", "false"), ("blocking", 1),
    ("severity", "medium"), ("severity", "low"),
])
def test_finding_fields_are_strictly_typed_and_blockers_have_valid_severity(field, value):
    with pytest.raises(NativeReviewOutputError):
        parse_native_review_output(encoded(envelope("FINDINGS", [finding(**{field: value})])))


@pytest.mark.parametrize("field", [*NATIVE_REVIEW_SCHEMA["properties"]["findings"]["items"]["required"]])
def test_findings_require_existing_fields(field):
    row = finding()
    del row[field]
    with pytest.raises(NativeReviewOutputError):
        parse_native_review_output(encoded(envelope("FINDINGS", [row])))


def test_duplicate_ids_are_rejected_after_whitespace_normalization():
    with pytest.raises(NativeReviewOutputError, match="duplicate IDs"):
        parse_native_review_output(encoded(envelope("FINDINGS", [finding(), finding(id=" F1 ")])))
    parsed = parse_native_review_output(encoded(envelope("FINDINGS", [finding(id=" F1 ")])))
    assert parsed["findings"][0]["id"] == "F1"


@pytest.mark.parametrize("commentary", [
    "AGENTIC_OS_REVIEW_VERDICT: FINDINGS", "AGENTIC_OS_REVIEW_VERDICT: UNKNOWN",
    "AGENTIC_OS_REVIEW_VERDICT: CLEAN\nAGENTIC_OS_REVIEW_VERDICT: CLEAN",
    "AGENTIC_OS_REVIEW_VERDICT: CLEAN\nAGENTIC_OS_REVIEW_VERDICT: FINDINGS",
    "AGENTIC_OS_REVIEW_VERDICT CLEAN",
])
def test_explicit_commentary_markers_must_not_be_ambiguous_or_contradictory(commentary):
    with pytest.raises(NativeReviewOutputError, match="verdict markers"):
        parse_native_review_output(encoded(envelope(result=commentary)))


def test_one_matching_marker_is_commentary_and_summary_also_gets_checked():
    value = envelope(result="AGENTIC_OS_REVIEW_VERDICT: CLEAN\nTrailing prose")
    assert parse_native_review_output(encoded(value))["verdict"] == "CLEAN"
    value["structured_output"]["summary"] = "AGENTIC_OS_REVIEW_VERDICT: FINDINGS"
    with pytest.raises(NativeReviewOutputError, match="verdict markers"):
        parse_native_review_output(encoded(value))


def test_actual_legacy_trailing_summary_response_remains_rejected():
    stdout = (Path(__file__).parent / "fixtures/native-review/age221-trailing-summary.md").read_bytes()
    assert hashlib.sha256(stdout).hexdigest() == "f37759448eb09db11e591afe310f0ddf6889a024465ca4dca1c40f3c93ed27a0"
    runner = _load_runner()
    assert runner.parse_review_verdict(stdout.decode()) == ("findings", False)
    assert len(runner.parse_structured_findings(stdout.decode())) == 4
    with pytest.raises(NativeReviewOutputError):
        parse_native_review_output(stdout)


@pytest.fixture
def offline_runner(monkeypatch, tmp_path):
    runner = _load_runner()
    work_item, worktree = tmp_path / "packet", tmp_path / "worktree"
    work_item.mkdir()
    worktree.mkdir()
    head, base = "b" * 40, "a" * 40
    source = {
        "work_item_id": "AGE-234", "repo_path": str(worktree), "worktree": str(worktree),
        "implementation_summary": "Framing fixture", "spec_source": "fixture ticket",
        "builder_model": "gpt", "selected_reviewer_model": "opus", "reviewer_selection_source": "policy",
        "target_branch": "main", "base_sha": base, "head_sha": head, "diff_hash": "d" * 64,
        "pr_number": 42, "mode": "post_pr",
    }
    provider = {"number": 42, "url": "https://example.test/acme/widgets/pull/42", "state": "OPEN",
                "headRefOid": head, "baseRefName": "main", "statusCheckRollup": []}
    reviews = []

    class FakeCoordinator:
        def __init__(self, _root):
            pass

        def execute(self, subject, callback, **kwargs):
            reviews.append(callback())
            return SimpleNamespace(key="fixture-key", receipt={"review": reviews[-1], "outcome": reviews[-1]["outcome"]},
                                   receipt_path=tmp_path / "coordination.json", reused=False)

    monkeypatch.setattr(runner, "resolve_os_root", lambda _: tmp_path)
    monkeypatch.setattr(runner, "project_identity", lambda *_: ("acme", "widgets"))
    monkeypatch.setattr(runner, "load_development_profile", lambda *_: ({"repository": {"root": str(worktree)}}, tmp_path / "profile"))
    monkeypatch.setattr(runner, "prior_request", lambda *_: source)
    monkeypatch.setattr(runner, "provider_pr", lambda *_: provider)
    monkeypatch.setattr(runner, "git_head", lambda *_: head)
    monkeypatch.setattr(runner, "git_repository", lambda *_: "acme/widgets")
    monkeypatch.setattr(runner, "stable_review_key", lambda *_: "fixture-key")
    monkeypatch.setattr(runner, "diff_hash", lambda *_: "d" * 64)
    monkeypatch.setattr(runner, "ReviewCoordinator", FakeCoordinator)
    monkeypatch.setattr(runner.shutil, "which", lambda _: "/fixture/claude")
    monkeypatch.setattr(runner, "decide", lambda _: {"decision": "ready_post_pr_checks"})
    monkeypatch.setattr(sys, "argv", ["runner", "AGE-234", "--work-item", str(work_item), "--worktree", str(worktree)])
    return runner, work_item / "artifacts/finishing-touches/review-runs/fixture-key", reviews


@pytest.mark.parametrize("case", ["clean", "findings", "invalid", "error", "empty", "exit", "timeout", "oserror"])
def test_native_runner_preserves_original_bytes_and_projects_only_valid_authority(offline_runner, monkeypatch, case):
    runner, run_dir, reviews = offline_runner
    stdout = encoded(envelope("FINDINGS", [finding()])) if case == "findings" else encoded(envelope()) + b"\r\n"
    if case == "invalid":
        stdout = b'{"type":"result","subtype":"success","is_error":false}'
    elif case == "error":
        stdout = encoded(envelope(subtype="error_during_execution", is_error=True))
    elif case == "empty":
        stdout = b""
    calls = []
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-key-only")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "fixture-token-only")

    def invoke(command, **kwargs):
        calls.append((command, kwargs))
        if case == "timeout":
            raise subprocess.TimeoutExpired(command, 180, output=stdout)
        if case == "oserror":
            raise OSError("fixture unavailable")
        return subprocess.CompletedProcess(command, 1 if case == "exit" else 0, stdout, b"")

    monkeypatch.setattr(runner, "run_native_review", invoke)
    assert runner.main() == (0 if case == "clean" else 2)
    command, kwargs = calls[0]
    assert command[command.index("--output-format") + 1] == "json"
    assert json.loads(command[command.index("--json-schema") + 1]) == NATIVE_REVIEW_SCHEMA
    assert "--bare" not in command and "--safe-mode" in command
    assert command[command.index("--allowedTools") + 1] == runner.CLAUDE_TOOLS
    assert "AGENTIC_OS_REVIEW_VERDICT" not in command[-1]
    assert kwargs["timeout"] == 180
    assert not any(key in kwargs["env"] for key in runner.CLAUDE_ENV_REMOVED)
    if case != "oserror":
        assert (run_dir / "reviewer-stdout.bin").read_bytes() == stdout
        assert reviews[0]["native_stdout"]["sha256"] == hashlib.sha256(stdout).hexdigest()
    if case in {"clean", "findings"}:
        projection = (run_dir / "reviewer-response.md").read_text()
        assert projection == reviews[0]["response"]
        assert reviews[0]["projection_sha256"] == hashlib.sha256(projection.encode()).hexdigest()
        assert reviews[0]["native_stdout"]["sha256"] != reviews[0]["projection_sha256"]
        assert reviews[0]["verdict_structured"] is True
    else:
        assert not (run_dir / "reviewer-response.md").exists()
        assert reviews[0]["outcome"] == "unavailable"
        assert reviews[0]["verdict_structured"] is False


def test_native_capture_uses_binary_subprocess_output(monkeypatch, tmp_path):
    runner = _load_runner()
    calls = []
    monkeypatch.setattr(runner.subprocess, "run", lambda command, **kwargs: calls.append(kwargs) or "fixture")
    assert runner.run_native_review(["fixture"], cwd=tmp_path, timeout=3, env={}) == "fixture"
    assert calls[0]["capture_output"] is True
    assert "text" not in calls[0]


def test_retry_artifacts_preserve_old_response_without_changing_subject_key(tmp_path):
    runner = _load_runner()
    old = runner.allocate_review_run_dir(tmp_path, "same-subject-key")
    response = old / "reviewer-response.md"
    response.write_bytes(b"historical failed response\r\n")
    retry = runner.allocate_review_run_dir(tmp_path, "same-subject-key")
    assert old.name == "same-subject-key"
    assert retry.name.startswith("same-subject-key-attempt-")
    assert retry != old
    assert response.read_bytes() == b"historical failed response\r\n"


def test_same_subject_retry_never_rewrites_historical_attempt_artifacts(offline_runner, monkeypatch):
    runner, old_dir, reviews = offline_runner
    old_dir.mkdir(parents=True)
    old_response = old_dir / "reviewer-response.md"
    old_response.write_bytes(b"old failed framing\r\n")
    old_receipt = old_dir / "opposing-model-review-receipt.json"
    old_receipt.write_bytes(b'{"outcome":"unavailable"}\n')
    before = {path.name: path.read_bytes() for path in old_dir.iterdir()}
    monkeypatch.setattr(runner, "run_native_review", lambda command, **kwargs: subprocess.CompletedProcess(command, 0, encoded(envelope()), b""))
    assert runner.main() == 0
    assert {path.name: path.read_bytes() for path in old_dir.iterdir()} == before
    retry_dir = Path(reviews[0]["review_run_dir"])
    assert retry_dir.name.startswith("fixture-key-attempt-")
    request = json.loads((retry_dir / "review-request.json").read_text())
    assert request["review_key"] == "fixture-key"
    assert request["run_id"] == retry_dir.name
    assert f"Review run: `{retry_dir.name}`" in (retry_dir / "model-receipt.md").read_text()
    validation = subprocess.run([sys.executable, str(runner.HELPER), "validate", "--run-dir", str(retry_dir)], capture_output=True)
    assert validation.returncode == 0, validation.stderr
    assert (retry_dir / "opposing-model-review-receipt.json").is_file()


def test_terminal_coordinator_reuse_leaves_all_attempt_artifacts_unchanged(offline_runner, monkeypatch):
    runner, run_dir, reviews = offline_runner
    monkeypatch.setattr(runner, "run_native_review", lambda command, **kwargs: subprocess.CompletedProcess(command, 0, encoded(envelope()), b""))
    assert runner.main() == 0
    before = {path.name: path.read_bytes() for path in run_dir.iterdir()}

    def reuse(subject, callback, **kwargs):
        return SimpleNamespace(key="fixture-key", receipt={"review": reviews[0], "outcome": "clean"},
                               receipt_path=run_dir / "coordination.json", reused=True)

    monkeypatch.setattr(runner, "ReviewCoordinator", lambda _: SimpleNamespace(execute=reuse))
    monkeypatch.setattr(runner, "run_native_review", lambda *_args, **_kwargs: pytest.fail("reused authority must not invoke native CLI"))
    assert runner.main() == 0
    assert {path.name: path.read_bytes() for path in run_dir.iterdir()} == before
