"""Focused offline guards for the opposing-model review transport."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from types import SimpleNamespace
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest


@pytest.fixture
def offline_review(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Execute the actual closure with all model/provider transports replaced."""
    runner = _load_runner()
    work_item = tmp_path / "work-item"
    worktree = tmp_path / "worktree"
    work_item.mkdir()
    worktree.mkdir()
    head = "b" * 40
    key = "offline-diagnostic-key"
    source = {
        "work_item_id": "AGE-210",
        "worktree": str(worktree),
        "repo_path": str(worktree),
        "implementation_summary": "Record closed failure metadata.",
        "spec_source": "Offline diagnostic fixture",
        "builder_model": "gpt-5.6",
        "reviewer_model": "opus",
        "selected_reviewer_model": "opus",
        "reviewer_selection_source": "project-policy",
        "target_branch": "main",
        "base_sha": "a" * 40,
        "head_sha": head,
        "diff_hash": "d" * 64,
        "pr_number": 42,
        "mode": "post_pr",
    }
    provider = {
        "number": 42,
        "url": "https://example.test/acme/widgets/pull/42",
        "state": "OPEN",
        "headRefOid": head,
        "baseRefName": "main",
        "statusCheckRollup": [],
    }
    captured = {"calls": [], "provider_reads": 0}
    options = {}

    class FakeCoordinator:
        def __init__(self, _root):
            pass

        def execute(self, subject, execute_review, **kwargs):
            captured["subject"] = subject
            captured["coordination_options"] = kwargs
            reused = options.get("reused", False)
            review = (
                {"outcome": "unavailable", "failure_code": "prior_sealed_failure"}
                if reused
                else execute_review()
            )
            captured["review"] = review
            return SimpleNamespace(
                key=key,
                receipt={"review": review, "outcome": review["outcome"]},
                receipt_path=tmp_path / "coordination-receipt.json",
                reused=reused,
            )

    def fake_provider(*_args):
        captured["provider_reads"] += 1
        result = dict(provider)
        if options.get("changed_head") and captured["provider_reads"] > 1:
            result["headRefOid"] = "e" * 40
        return result

    def fake_run(command, **kwargs):
        assert command[0] == "/offline/claude", "unexpected executable"
        captured["calls"].append((command, kwargs))
        result = options["result"]
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(runner, "resolve_os_root", lambda _explicit: tmp_path)
    monkeypatch.setattr(runner, "prior_request", lambda *_args: dict(source))
    monkeypatch.setattr(runner, "project_identity", lambda *_args: ("acme", "widgets"))
    monkeypatch.setattr(
        runner, "load_development_profile",
        lambda *_args: (
            {"repository": {"root": str(worktree), "base_branch": "main"}},
            tmp_path / "development.yml",
        ),
    )
    monkeypatch.setattr(runner, "provider_pr", fake_provider)
    monkeypatch.setattr(runner, "git_head", lambda _path: head)
    monkeypatch.setattr(runner, "git_repository", lambda _path: "acme/widgets")
    monkeypatch.setattr(runner, "stable_review_key", lambda _subject: key)
    monkeypatch.setattr(runner, "diff_hash", lambda *_args: "d" * 64)
    monkeypatch.setattr(runner, "render_prompt", lambda *_args: "Offline review prompt")
    monkeypatch.setattr(runner, "ReviewCoordinator", FakeCoordinator)
    monkeypatch.setattr(runner, "run", fake_run)
    monkeypatch.setattr(
        runner.shutil, "which",
        lambda _name: None if options.get("missing_cli") else "/offline/claude",
    )
    monkeypatch.setattr(runner, "decide", lambda _path: {"decision": "ready_for_merge"})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-api-key-private")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "fixture-oauth-private")
    monkeypatch.setattr(
        sys, "argv",
        [
            "run_opposing_model_review.py", "AGE-210", "--os-root", str(tmp_path),
            "--work-item", str(work_item), "--worktree", str(worktree),
            "--timeout-seconds", "7",
        ],
    )

    def execute(result=None, **settings):
        options.update(result=result, **settings)
        if settings.get("diagnostic_write_fails"):
            original_write = runner.write_json

            def guarded_write(path, value):
                if path.name == "reviewer-failure-diagnostics.json":
                    raise OSError("fixture-oauth-private: /private/credential-path")
                original_write(path, value)

            monkeypatch.setattr(runner, "write_json", guarded_write)
        exit_code = runner.main()
        run_dir = work_item / "artifacts/finishing-touches/review-runs" / key
        return SimpleNamespace(
            runner=runner, exit_code=exit_code, run_dir=run_dir,
            captured=captured, review=captured["review"], head=head, key=key,
        )

    execute.runner = runner
    return execute


@pytest.mark.parametrize(
    ("marker", "category"),
    [
        ("Unknown option --private-value", "cli_argument_rejected"),
        ("Authentication required", "cli_auth_required"),
        ("You’ve hit your limit", "cli_account_limited"),
        ("Operation not permitted", "cli_permission_refused"),
        ("ECONNRESET", "cli_network_unavailable"),
        ("unrecognized private failure", "cli_process_exit_unknown"),
        ("Authentication failed; network error", "cli_process_exit_unknown"),
        ("\x1b[31mPermission denied\x1b[0m\x00", "cli_permission_refused"),
    ],
)
def test_failure_categories_suppress_secret_output(marker, category) -> None:
    runner = _load_runner()
    secret = "fixture-oauth-private"
    result = runner.failure_diagnostics(
        review_key="key", head_sha="b" * 40, failure_code="cli_runtime_failed",
        stdout=secret, stderr=marker + " " + secret, returncode=-15,
    )

    assert result["category"] == category
    assert result["exit_code"] == -15
    assert result["signal"] == 15
    assert result["raw_output_retained"] is False
    assert secret not in json.dumps(result)
    digest = result.pop("metadata_sha256")
    assert digest == hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_failure_metadata_is_bounded_and_counts_unicode_bytes() -> None:
    runner = _load_runner()
    output = "😀" * 300_000 + "fixture-oauth-private"
    stderr = b"x" * 2_000_000 + b"authentication failed fixture-oauth-private"
    result = runner.failure_diagnostics(
        review_key="key", head_sha="b" * 40, failure_code="cli_runtime_failed",
        stdout=output, stderr=stderr, returncode=1,
    )

    assert result["category"] == "cli_process_exit_unknown"
    assert result["stdout"]["byte_count"] == len(output.encode())
    assert result["stderr"]["byte_count"] == len(stderr)
    for stream in ("stdout", "stderr"):
        assert result[stream]["inspected_bytes"] == runner.DIAGNOSTIC_WINDOW_BYTES
        assert result[stream]["truncated"] is True
        assert result[stream]["content_suppressed"] is True
    assert len(json.dumps(result).encode()) < 2_000
    assert "fixture-oauth-private" not in json.dumps(result)


def test_diagnostics_reject_open_failure_codes_without_echoing_them() -> None:
    runner = _load_runner()
    with pytest.raises(ValueError, match="^unsupported diagnostic failure code$"):
        runner.failure_diagnostics(
            review_key="key", head_sha="b" * 40,
            failure_code="fixture-oauth-private",
        )


@pytest.mark.parametrize(
    ("result", "failure", "category"),
    [
        (subprocess.CompletedProcess([], 3, "fixture-oauth-private", "Unknown option"), "cli_runtime_failed", "cli_argument_rejected"),
        (subprocess.CompletedProcess([], -9, "", "fixture-oauth-private"), "cli_runtime_failed", "cli_process_exit_unknown"),
        (subprocess.CompletedProcess([], 0, "", "fixture-oauth-private"), "cli_output_invalid", "cli_output_invalid"),
        (subprocess.CompletedProcess([], 0, " \n", ""), "cli_output_invalid", "cli_output_invalid"),
        (subprocess.CompletedProcess([], 0, None, ""), "cli_output_invalid", "cli_output_invalid"),
        (subprocess.CompletedProcess([], 0, b"fixture-oauth-private", b""), "cli_output_invalid", "cli_output_invalid"),
        (subprocess.CompletedProcess([], 0, "fixture-oauth-private\nAGENTIC_OS_REVIEW_VERDICT: MAYBE", ""), "cli_output_invalid", "cli_output_invalid"),
        (subprocess.CompletedProcess([], 0, "```json\n[{\"id\":\"fixture-oauth-private\"}]\n```\nAGENTIC_OS_REVIEW_VERDICT: CLEAN", ""), "cli_output_invalid", "cli_output_invalid"),
        (subprocess.TimeoutExpired(["fixture-oauth-private"], 7, output=b"fixture-oauth-private", stderr=b"fixture-api-key-private"), "cli_timeout", "cli_timeout"),
        (OSError(13, "fixture-oauth-private: private path"), "cli_runtime_failed", "cli_launch_failed"),
        (UnicodeDecodeError("utf8", b"\xff", 0, 1, "fixture-oauth-private"), "cli_output_invalid", "cli_output_invalid"),
    ],
    ids=["nonzero", "signal", "empty", "whitespace", "none", "bytes", "bad-verdict", "bad-findings", "timeout", "launch-error", "decode-error"],
)
def test_actual_failure_receipts_remain_unavailable_and_private(
    offline_review, capsys, result, failure, category
) -> None:
    execution = offline_review(result)
    diagnostic_path = execution.run_dir / "reviewer-failure-diagnostics.json"
    diagnostic = json.loads(diagnostic_path.read_text())
    reference = execution.review["failure_diagnostics"]

    assert execution.exit_code == 2
    assert execution.review["outcome"] == "unavailable"
    assert execution.review["reviewer_status"] == "runtime_failure"
    assert execution.review["failure_code"] == failure
    assert execution.review["response"] == ""
    assert execution.review["findings"] == []
    assert execution.review["readback_verified"] is True
    assert diagnostic["category"] == category
    assert diagnostic["review_key"] == execution.key
    assert diagnostic["head_sha"] == execution.head
    assert reference["artifact"] == diagnostic_path.name
    assert reference["sha256"] == hashlib.sha256(diagnostic_path.read_bytes()).hexdigest()
    assert reference["metadata"] == diagnostic
    assert not (execution.run_dir / "reviewer-response.md").exists()
    assert (execution.run_dir / "review-ledger.jsonl").read_text() == ""
    assert execution.captured["provider_reads"] == 2
    serialized = capsys.readouterr().out + json.dumps(execution.review)
    for path in execution.run_dir.iterdir():
        serialized += path.read_text()
    for secret in ("fixture-api-key-private", "fixture-oauth-private"):
        assert secret not in serialized


@pytest.mark.parametrize("verdict", ["CLEAN", "FINDINGS"])
@pytest.mark.parametrize("parser_limit", ["nesting", "integer"])
def test_parser_limit_output_completes_closed_unavailable_receipt(
    offline_review, monkeypatch, capsys, verdict, parser_limit
) -> None:
    if parser_limit == "nesting":
        # The accelerated decoder in Python 3.14 accepts deeply nested input.
        # Exercise the stdlib recursive backend only for this fake response;
        # production parsing and all other loads retain their normal backend.
        depth = max(sys.getrecursionlimit() * 4, 10_000)
        value = "[" * depth + "0" + "]" * depth
        expected_error = RecursionError
    else:
        get_limit = getattr(sys, "get_int_max_str_digits", None)
        if get_limit is None or get_limit() == 0:
            pytest.skip("interpreter has no active integer-conversion limit")
        value = "9" * (get_limit() + 1)
        expected_error = ValueError
    payload = '[{"id":"fixture-oauth-private","line":' + value + "}]"
    if parser_limit == "nesting":
        decoder = json.JSONDecoder()
        decoder.scan_once = json.scanner.py_make_scanner(decoder)
        original_loads = json.loads

        def recursive_fixture_loads(raw, *args, **kwargs):
            if raw == payload:
                return decoder.decode(raw)
            return original_loads(raw, *args, **kwargs)

        monkeypatch.setattr(json, "loads", recursive_fixture_loads)
    with pytest.raises(expected_error):
        json.loads(payload)
    response = "```json\n" + payload + "\n```\nAGENTIC_OS_REVIEW_VERDICT: " + verdict
    runner = offline_review.runner
    parser_calls = []
    original_verdict = runner.parse_review_verdict
    original_findings = runner.parse_structured_findings

    def verdict_parser(text):
        parser_calls.append("verdict")
        return original_verdict(text)

    def findings_parser(text):
        parser_calls.append("findings")
        return original_findings(text)

    monkeypatch.setattr(runner, "parse_review_verdict", verdict_parser)
    monkeypatch.setattr(runner, "parse_structured_findings", findings_parser)
    execution = offline_review(subprocess.CompletedProcess([], 0, response, ""))
    diagnostic_path = execution.run_dir / "reviewer-failure-diagnostics.json"
    diagnostic = json.loads(diagnostic_path.read_text())

    # CLEAN inspects JSON while reconciling its verdict; FINDINGS reaches the
    # separate findings parser. Both actual limit paths must finish a receipt.
    assert parser_calls == (["verdict"] if verdict == "CLEAN" else ["verdict", "findings"])
    assert execution.exit_code == 2
    assert execution.review["outcome"] == "unavailable"
    assert execution.review["failure_code"] == "cli_output_invalid"
    assert execution.review["reviewer_status"] == "runtime_failure"
    assert execution.review["response"] == ""
    assert execution.review["findings"] == []
    assert execution.review["readback_verified"] is True
    assert execution.captured["provider_reads"] == 2
    assert diagnostic["category"] == "cli_output_invalid"
    assert diagnostic["raw_output_retained"] is False
    assert diagnostic["stdout"]["byte_count"] == len(response.encode())
    assert execution.review["failure_diagnostics"]["sha256"] == hashlib.sha256(
        diagnostic_path.read_bytes()
    ).hexdigest()
    assert (execution.run_dir / "review-ledger.jsonl").read_text() == ""
    assert not (execution.run_dir / "reviewer-response.md").exists()
    assert (execution.run_dir / "opposing-model-review-receipt.json").exists()
    retained = capsys.readouterr().out
    retained += "".join(path.read_text() for path in execution.run_dir.iterdir())
    for suppressed in ("fixture-oauth-private", "maximum recursion depth", "Exceeds the limit", payload):
        assert suppressed not in retained


@pytest.mark.parametrize("failure_site", ["post_provider", "decision"])
def test_parser_guard_does_not_hide_unrelated_state_failures(
    offline_review, monkeypatch, failure_site
) -> None:
    runner = offline_review.runner
    if failure_site == "post_provider":
        original_provider = runner.provider_pr
        reads = 0

        def provider_failure(*args):
            nonlocal reads
            reads += 1
            if reads == 2:
                raise ValueError("unrelated state failure")
            return original_provider(*args)

        monkeypatch.setattr(runner, "provider_pr", provider_failure)
    else:
        def decision_failure(_path):
            raise ValueError("unrelated state failure")

        monkeypatch.setattr(runner, "decide", decision_failure)
    response = "```json\n[]\n```\nAGENTIC_OS_REVIEW_VERDICT: CLEAN"

    with pytest.raises(ValueError, match="^unrelated state failure$"):
        offline_review(subprocess.CompletedProcess([], 0, response, ""))


def test_actual_large_failure_retains_only_small_metadata(offline_review) -> None:
    output = "x" * 2_000_000 + "fixture-oauth-private"
    execution = offline_review(subprocess.CompletedProcess([], 1, output, output))
    diagnostic = execution.review["failure_diagnostics"]["metadata"]

    assert diagnostic["stdout"]["byte_count"] == len(output)
    assert diagnostic["stdout"]["truncated"] is True
    assert diagnostic["stderr"]["truncated"] is True
    assert (execution.run_dir / "reviewer-failure-diagnostics.json").stat().st_size < 2_000
    assert "fixture-oauth-private" not in json.dumps(execution.review)


def test_missing_cli_receipt_records_closed_diagnostic_without_invocation(offline_review) -> None:
    execution = offline_review(missing_cli=True)

    assert execution.exit_code == 2
    assert execution.review["outcome"] == "unavailable"
    assert execution.review["reviewer_status"] == "unavailable"
    assert execution.review["failure_code"] == "cli_not_found"
    assert execution.review["failure_diagnostics"]["metadata"]["category"] == "cli_not_found"
    assert execution.captured["calls"] == []


def test_optional_diagnostic_write_failure_stays_safe_and_unavailable(
    offline_review, capsys
) -> None:
    execution = offline_review(
        subprocess.CompletedProcess([], 1, "", "fixture-oauth-private"),
        diagnostic_write_fails=True,
    )

    assert execution.exit_code == 2
    assert execution.review["failure_code"] == "cli_runtime_failed"
    assert execution.review["outcome"] == "unavailable"
    assert execution.review["failure_diagnostics"]["status"] == "write_failed"
    assert not (execution.run_dir / "reviewer-failure-diagnostics.json").exists()
    assert "fixture-oauth-private" not in capsys.readouterr().out
    assert "/private/credential-path" not in json.dumps(execution.review)


def test_post_review_head_mismatch_keeps_existing_readback_block(offline_review) -> None:
    execution = offline_review(
        subprocess.CompletedProcess([], 1, "", "Unknown option"), changed_head=True,
    )

    assert execution.exit_code == 2
    assert execution.review["outcome"] == "unavailable"
    assert execution.review["failure_code"] == "head_changed_after_review"
    assert execution.review["readback_verified"] is False
    assert execution.review["failure_diagnostics"]["metadata"]["failure_code"] == "cli_runtime_failed"


def test_terminal_receipt_reuse_does_not_invoke_or_reclassify(offline_review) -> None:
    execution = offline_review(reused=True)

    assert execution.exit_code == 2
    assert execution.review == {"outcome": "unavailable", "failure_code": "prior_sealed_failure"}
    assert execution.captured["calls"] == []
    assert execution.captured["provider_reads"] == 1
    assert not (execution.run_dir / "reviewer-failure-diagnostics.json").exists()


@pytest.mark.parametrize("verdict", ["CLEAN", "FINDINGS"])
def test_successful_transport_preserves_command_auth_and_verdict_path(
    offline_review, verdict
) -> None:
    findings = [] if verdict == "CLEAN" else [{
        "id": "F1", "severity": "high", "category": "tests",
        "file": "tests/example.py", "line": 1, "title": "Missing guard",
        "detail": "A required guard is absent.", "suggested_fix": "Add guard.",
        "blocking": True,
    }]
    response = "```json\n" + json.dumps(findings) + "\n```\nAGENTIC_OS_REVIEW_VERDICT: " + verdict
    execution = offline_review(subprocess.CompletedProcess([], 0, response, "unused stderr"))
    command, kwargs = execution.captured["calls"][0]

    assert command == [
        "/offline/claude", "-p", "--model", "opus", "--safe-mode",
        "--permission-mode", "dontAsk", "--tools", "Read,Grep,Glob,Bash",
        "--allowedTools", execution.runner.CLAUDE_TOOLS,
        "--no-session-persistence", "Offline review prompt",
    ]
    assert kwargs["timeout"] == 7
    assert "ANTHROPIC_API_KEY" not in kwargs["env"]
    assert "ANTHROPIC_AUTH_TOKEN" not in kwargs["env"]
    assert execution.review["failure_code"] is None
    assert execution.review["failure_diagnostics"] is None
    assert execution.review["reviewer_status"] == "available"
    assert execution.review["readback_verified"] is True
    assert execution.review["response"] == response
    assert execution.review["outcome"] == ("clean" if verdict == "CLEAN" else "findings")
    assert execution.exit_code == (0 if verdict == "CLEAN" else 2)
    assert (execution.run_dir / "reviewer-response.md").read_text() == response + "\n"
    assert not (execution.run_dir / "reviewer-failure-diagnostics.json").exists()
    assert execution.captured["subject"].head_sha == execution.head
    assert execution.captured["coordination_options"]["mode"] == "full"
    assert execution.captured["provider_reads"] == 2


def _load_runner():
    script = (
        Path(__file__).parents[1]
        / "harness/skills/auto-dev-review-self-opposing-model/scripts/run_opposing_model_review.py"
    )
    spec = importlib.util.spec_from_file_location("opposing_model_review_runner_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _completed(returncode: int, stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, "")


def _load_crossreview():
    script = Path(__file__).parents[1] / "harness/bin/agentic-os-pr-crossreview"
    spec = importlib.util.spec_from_loader(
        "opposing_crossreview_key_test",
        SourceFileLoader("opposing_crossreview_key_test", str(script)),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_both_entrypoints_build_the_same_key_for_every_alias() -> None:
    runner = _load_runner()
    crossreview = _load_crossreview()
    aliases = [
        ("review_self", "full-pr"),
        ("review-repair", "full_pr"),
        ("review_others", "pr"),
        ("finalize", "full-pr"),
    ]
    keys: set[str] = set()
    for purpose, scope in aliases:
        cross_purpose, _ = crossreview.normalize_review_purpose(purpose, scope)
        runner_purpose, _ = runner.normalize_review_purpose(purpose, scope)
        assert cross_purpose == runner_purpose == "review_self"
        keys.add(
            runner.stable_review_key(
                runner.ReviewSubject(
                    repository="acme/widgets",
                    pull_request="github:acme/widgets#42",
                    base_branch="main",
                    base_sha="a" * 40,
                    head_sha="b" * 40,
                    policy_fingerprint="c" * 64,
                    purpose=runner_purpose,
                )
            )
        )

    assert len(keys) == 1


def test_runner_verdict_uses_final_line_and_template_uses_shared_vocabulary() -> None:
    runner = _load_runner()
    echoed_prompt = (
        "AGENTIC_OS_REVIEW_VERDICT: CLEAN\n"
        "AGENTIC_OS_REVIEW_VERDICT: FINDINGS\n"
        "```json\n[]\n```\nAGENTIC_OS_REVIEW_VERDICT: CLEAN"
    )

    assert runner.parse_review_verdict(echoed_prompt) == ("clean", True)
    assert runner.parse_review_verdict(
        "```json\n[]\n```\nAGENTIC_OS_REVIEW_VERDICT: CLEAN\ntrailing text"
    ) == ("findings", False)
    assert runner.parse_review_verdict(
        "```json\n[{\"id\": \"F1\"}]\n```\nAGENTIC_OS_REVIEW_VERDICT: CLEAN"
    ) == ("clean", True)
    assert runner.parse_review_verdict(
        "```json\n[{\"id\": \"F1\", \"severity\": \"low\", "
        "\"blocking\": false}]\n```\nAGENTIC_OS_REVIEW_VERDICT: CLEAN"
    ) == ("clean", True)
    assert runner.parse_review_verdict(
        "```json\n[{\"id\": \"F1\", \"severity\": \"high\", "
        "\"blocking\": false}]\n```\nAGENTIC_OS_REVIEW_VERDICT: CLEAN"
    ) == ("clean", True)
    assert runner.parse_review_verdict(
        "```json\n[{\"id\": \"F1\", \"severity\": \"high\"}]\n```\n"
        "AGENTIC_OS_REVIEW_VERDICT: CLEAN"
    ) == ("findings", True)
    assert runner.parse_review_verdict(
        "```json\n[{\"id\": \"F1\", \"severity\": \"low\", "
        "\"blocking\": true}]\n```\nAGENTIC_OS_REVIEW_VERDICT: CLEAN"
    ) == ("findings", True)
    assert runner.parse_review_verdict(
        "```json\n[{\"id\": \"F1\", \"blocking\": true, "
        "\"status\": \"resolved\"}]\n```\nAGENTIC_OS_REVIEW_VERDICT: CLEAN"
    ) == ("clean", True)
    assert runner.parse_review_verdict(
        "```json\n[{\"id\": \"F1\", \"blocking\": true}]\n```\n"
        "```json\n[]\n```\nAGENTIC_OS_REVIEW_VERDICT: CLEAN"
    ) == ("findings", True)
    assert runner.parse_review_verdict(
        "```json\n[{\"id\": \"F1\", "
        "\"severity\": \"critical | high | medium | low\", "
        "\"category\": \"correctness | tests\", \"blocking\": true}]\n```\n"
        "```json\n[]\n```\nAGENTIC_OS_REVIEW_VERDICT: CLEAN"
    ) == ("clean", True)
    template = runner.TEMPLATE.read_text(encoding="utf-8")
    assert "AGENTIC_OS_REVIEW_VERDICT: CLEAN" in template
    assert "AGENTIC_OS_REVIEW_VERDICT: FINDINGS" in template
    assert "VERDICT: ready" not in template


def test_runner_uses_routed_unavailable_policy_and_rejects_unknown_values() -> None:
    runner = _load_runner()

    assert runner.review_unavailable_policy({}) == "continue_with_receipt"
    assert runner.review_unavailable_policy(
        {"effective_policy": {"unavailable_policy": "block"}}
    ) == "block"
    with pytest.raises(runner.ReviewError, match="review_unavailable_policy"):
        runner.review_unavailable_policy({"review_unavailable_policy": "permit_anything"})


def test_review_repository_selector_omits_singleton_and_requires_catalog_choice() -> None:
    runner = _load_runner()
    singleton = {
        "repository": {"root": "/tmp/widgets", "base_branch": "main"}
    }
    catalog = {
        "repository": {
            "catalog": [
                {"id": "api", "root": "/tmp/api", "base_branch": "main"},
                {"id": "web", "root": "/tmp/web", "base_branch": "main"},
            ]
        }
    }

    assert runner.validate_review_repository_selection(singleton, None)["repository"] == {
        "root": "/tmp/widgets",
        "base_branch": "main",
    }
    with pytest.raises(runner.ReviewError, match="only valid when repository.catalog"):
        runner.validate_review_repository_selection(singleton, "widgets")
    with pytest.raises(runner.ReviewError, match="selection is required"):
        runner.validate_review_repository_selection(catalog, None)
    with pytest.raises(runner.ReviewError, match="unknown repository"):
        runner.validate_review_repository_selection(catalog, "invalid")
    assert runner.validate_review_repository_selection(catalog, "api")["repository"][
        "id"
    ] == "api"


def test_invalid_selector_writes_terminal_preflight_before_provider_action(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = _load_runner()
    os_root = _installed_root(tmp_path / "os")
    project = os_root / "domains/acme/02-projects/widgets"
    work_item = project / "work-items/age-204"
    worktree = project / "worktrees/age-204"
    work_item.mkdir(parents=True)
    worktree.mkdir(parents=True)
    head = "b" * 40
    source = {
        "work_item_id": "AGE-204",
        "base_sha": "a" * 40,
        "policy_fingerprint": "c" * 64,
        "pr_number": 42,
        "repository_id": "github:acme/widgets",
    }
    provider_calls = 0

    def provider_must_not_run(*_args: object) -> dict[str, object]:
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("provider read must not occur before selector admission")

    monkeypatch.setattr(runner, "prior_request", lambda *_args: source)
    monkeypatch.setattr(runner, "git_head", lambda _worktree: head)
    monkeypatch.setattr(
        runner,
        "load_development_profile",
        lambda *_args: (
            {"repository": {"root": str(worktree), "base_branch": "main"}},
            project / "config/development.yml",
        ),
    )
    monkeypatch.setattr(runner, "provider_pr", provider_must_not_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_opposing_model_review.py",
            "AGE-204",
            "--os-root",
            str(os_root),
            "--work-item",
            str(work_item),
            "--worktree",
            str(worktree),
            "--repository",
            "widgets",
        ],
    )

    assert runner.main() == 2
    assert provider_calls == 0
    receipts = list(
        (work_item / "artifacts/finishing-touches/review-preflight").glob("*.json")
    )
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert receipt["schema"] == "opposing-model-review-preflight-receipt/v1"
    assert receipt["outcome"] == "unavailable"
    assert receipt["terminal"] is True
    assert receipt["subject"] == {
        "repository": "github:acme/widgets",
        "base_sha": "a" * 40,
        "head_sha": head,
        "policy_fingerprint": "c" * 64,
    }
    assert not any(receipt["external_actions"].values())


def _installed_root(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / ".agentic_root").write_text("installed\n", encoding="utf-8")
    (path / "harness").mkdir()
    (path / "domains").mkdir()
    return path


def test_runner_default_root_uses_environment_not_current_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = _load_runner()
    canonical = _installed_root(tmp_path / "canonical")
    private_cwd = tmp_path / "worktree"
    private_cwd.mkdir()
    monkeypatch.chdir(private_cwd)
    monkeypatch.setenv("AGENTIC_OS_ROOT", str(canonical))

    assert runner.resolve_os_root(None) == canonical.resolve()


def test_runner_default_root_fails_closed_instead_of_using_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = _load_runner()
    private_cwd = tmp_path / "worktree"
    private_cwd.mkdir()
    monkeypatch.chdir(private_cwd)
    monkeypatch.delenv("AGENTIC_OS_ROOT", raising=False)
    monkeypatch.setattr(runner, "INSTALLED_OS_ROOT", tmp_path / "missing-installed-root")

    with pytest.raises(runner.ReviewError, match="installed Agentic OS root"):
        runner.resolve_os_root(None)


def test_runner_explicit_root_must_match_configured_canonical_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = _load_runner()
    canonical = _installed_root(tmp_path / "canonical")
    other = _installed_root(tmp_path / "other")
    monkeypatch.setenv("AGENTIC_OS_ROOT", str(canonical))

    with pytest.raises(runner.ReviewCoordinationError, match="disagrees"):
        runner.resolve_os_root(other)


def test_runner_locates_shared_factory_packet_and_worktree(tmp_path: Path) -> None:
    runner = _load_runner()
    project = tmp_path / "harness/shared_factory/02-projects/genomes_agentic_lib"
    packet = project / "work-items/082526_pr_57_checked_review"
    worktree = project / "worktrees/082526-pr-57-checked-review"
    packet.mkdir(parents=True)
    worktree.mkdir(parents=True)
    (packet / "autodev.json").write_text("{}\n", encoding="utf-8")

    assert runner.locate_work_item(tmp_path, "PR-57") == packet
    assert runner.locate_worktree(tmp_path, "PR-57") == worktree


def test_initial_review_request_uses_exact_pr_create_readback(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    packet = tmp_path / "work-item"
    worktree = tmp_path / "worktree"
    readback = packet / "artifacts/auto-dev-pr-create/pull-request-provider-readback.json"
    readback.parent.mkdir(parents=True)
    worktree.mkdir()
    head = "b" * 40
    base = "a" * 40
    (packet / "SPEC.md").write_text("# Spec\n", encoding="utf-8")
    (packet / "autodev.json").write_text(
        json.dumps(
            {
                "subject_revision": head,
                "delivery": {"policy_fingerprint": "c" * 64},
            }
        ),
        encoding="utf-8",
    )
    readback.write_text(
        json.dumps(
            {
                "repository": "acme/widgets",
                "number": 57,
                "url": "https://example.test/acme/widgets/pull/57",
                "state": "OPEN",
                "title": "Guarantee checked review delivery",
                "base_branch": "main",
                "base_sha": base,
                "head_sha": head,
            }
        ),
        encoding="utf-8",
    )

    request = runner.initial_request(packet, "PR-57", worktree)

    assert request["pr_number"] == 57
    assert request["base_sha"] == base
    assert request["head_sha"] == head
    assert request["policy_fingerprint"] == "c" * 64
    assert request["request_origin"] == "auto-dev-pr-create-provider-readback"
    assert request["mode"] == "post_pr"


def test_initial_review_request_rejects_stale_packet_subject(tmp_path: Path) -> None:
    runner = _load_runner()
    packet = tmp_path / "work-item"
    worktree = tmp_path / "worktree"
    readback = packet / "artifacts/auto-dev-pr-create/pull-request-provider-readback.json"
    readback.parent.mkdir(parents=True)
    worktree.mkdir()
    (packet / "autodev.json").write_text(
        json.dumps(
            {
                "subject_revision": "b" * 40,
                "delivery": {"policy_fingerprint": "c" * 64},
            }
        ),
        encoding="utf-8",
    )
    readback.write_text(
        json.dumps(
            {
                "repository": "acme/widgets",
                "number": 57,
                "url": "https://example.test/acme/widgets/pull/57",
                "state": "OPEN",
                "base_branch": "main",
                "base_sha": "a" * 40,
                "head_sha": "d" * 40,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(runner.ReviewError, match="packet subject revision"):
        runner.initial_request(packet, "PR-57", worktree)


def test_delta_validation_requires_parent_ancestry(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _load_runner()
    monkeypatch.setattr(runner, "run", lambda *_args, **_kwargs: _completed(1))

    with pytest.raises(runner.ReviewError, match="not an ancestor"):
        runner.validated_delta_hash(Path("/tmp/repo"), "a" * 40, "b" * 40)


def test_delta_validation_hashes_complete_oversized_descendant_diff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    results = iter(
        [_completed(0), _completed(0, "x" * (runner.MAX_DIFF_CHARS + 1))]
    )
    monkeypatch.setattr(runner, "run", lambda *_args, **_kwargs: next(results))

    assert runner.validated_delta_hash(
        Path("/tmp/repo"), "a" * 40, "b" * 40
    ) == runner.hashlib.sha256(
        ("x" * (runner.MAX_DIFF_CHARS + 1)).encode()
    ).hexdigest()


def test_delta_validation_returns_hash_for_one_bounded_descendant_diff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    delta = "diff --git a/file b/file\n+fixed\n"
    results = iter([_completed(0), _completed(0, delta)])
    monkeypatch.setattr(runner, "run", lambda *_args, **_kwargs: next(results))

    assert runner.validated_delta_hash(
        Path("/tmp/repo"), "a" * 40, "b" * 40
    ) == hashlib.sha256(delta.encode()).hexdigest()


def test_runner_request_run_id_matches_created_artifact_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = _load_runner()
    work_item = tmp_path / "work-item"
    worktree = tmp_path / "worktree"
    work_item.mkdir()
    worktree.mkdir()
    head = "b" * 40
    review_key = "review-key"
    source = {
        "work_item_id": "AGE-196",
        "worktree": str(worktree),
        "repo_path": str(worktree),
        "implementation_summary": "Bind the review receipt to its artifact directory.",
        "spec_source": "AGE-196 acceptance criteria",
        "builder_model": "gpt-5.6",
        "reviewer_model": "opus",
        "selected_reviewer_model": "opus",
        "reviewer_selection_source": "project-policy",
        "target_branch": "main",
        "base_sha": "a" * 40,
        "head_sha": head,
        "diff_hash": "d" * 64,
        "pr_number": 42,
        "artifact_dir": "stale-artifact-dir",
        "mode": "post_pr",
    }
    provider = {
        "number": 42,
        "url": "https://example.test/acme/widgets/pull/42",
        "state": "OPEN",
        "headRefOid": head,
        "baseRefName": "main",
        "statusCheckRollup": [],
    }

    class FakeCoordinator:
        def __init__(self, _root: Path) -> None:
            pass

        def execute(self, _subject, execute_review, **_kwargs):
            review = execute_review()
            return SimpleNamespace(
                key=review_key,
                receipt={"review": review, "outcome": review["outcome"]},
                receipt_path=tmp_path / "coordination-receipt.json",
                reused=False,
            )

    monkeypatch.setattr(runner, "resolve_os_root", lambda _explicit: tmp_path)
    monkeypatch.setattr(runner, "prior_request", lambda *_args: source)
    monkeypatch.setattr(runner, "project_identity", lambda *_args: ("acme", "widgets"))
    monkeypatch.setattr(
        runner,
        "load_development_profile",
        lambda *_args: (
            {"repository": {"root": str(worktree), "base_branch": "main"}},
            tmp_path / "development.yml",
        ),
    )
    monkeypatch.setattr(runner, "provider_pr", lambda *_args: provider)
    monkeypatch.setattr(runner, "git_head", lambda _worktree: head)
    monkeypatch.setattr(runner, "git_repository", lambda _worktree: "acme/widgets")
    monkeypatch.setattr(runner, "stable_review_key", lambda _subject: review_key)
    monkeypatch.setattr(runner, "diff_hash", lambda *_args: "d" * 64)
    monkeypatch.setattr(runner, "ReviewCoordinator", FakeCoordinator)
    monkeypatch.setattr(runner.shutil, "which", lambda _name: None)
    monkeypatch.setattr(runner, "decide", lambda _run_dir: {"decision": "blocked_model_identity"})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_opposing_model_review.py",
            "AGE-196",
            "--os-root",
            str(tmp_path),
            "--work-item",
            str(work_item),
            "--worktree",
            str(worktree),
        ],
    )

    assert runner.main() == 2
    run_dir = work_item / "artifacts/finishing-touches/review-runs" / review_key
    request = json.loads((run_dir / "review-request.json").read_text(encoding="utf-8"))

    assert request["run_id"] == run_dir.name == review_key
    validation = subprocess.run(
        [sys.executable, str(runner.HELPER), "validate", "--run-dir", str(run_dir)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert validation.returncode == 0, validation.stderr


def test_advisory_findings_are_preserved_without_becoming_helper_blockers(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    response = """```json
[
  {
    "id": "F-advice",
    "severity": "low",
    "category": "tests",
    "file": "tests/test_runner.py",
    "line": 42,
    "title": "Add a clarifying assertion",
    "detail": "The existing test already covers the contract.",
    "suggested_fix": "Optionally name the assertion.",
    "blocking": false
  }
]
```
AGENTIC_OS_REVIEW_VERDICT: FINDINGS"""

    findings = runner.parse_structured_findings(response)
    events = runner.ledger_events(findings)
    coordination = runner.coordination_findings(findings)

    assert [event["event_type"] for event in events] == [
        "finding_opened",
        "finding_verified",
    ]
    assert events[-1]["status"] == "VERIFIED"
    assert events[-1]["advisory"] is True
    assert coordination == [
        {
            "id": "F-advice",
            "severity": "low",
            "summary": "Add a clarifying assertion",
            "evidence": [
                "tests/test_runner.py:42 The existing test already covers the contract."
            ],
            "status": "resolved",
            "resolution_refs": ["reviewer-nonblocking-advisory:F-advice"],
            "advisory": True,
        }
    ]
    run_dir = tmp_path / "review-run"
    run_dir.mkdir()
    (run_dir / "review-request.json").write_text(
        json.dumps(
            {
                "work_item_id": "AGE-196",
                "run_id": run_dir.name,
                "repo_path": "repository",
                "implementation_summary": "advisory ingestion",
                "spec_source": "ticket",
                "builder_model": "gpt-5.6",
                "selected_reviewer_model": "opus",
                "reviewer_selection_source": "policy",
                "target_branch": "main",
                "base_sha": "a" * 40,
                "head_sha": "b" * 40,
                "diff_hash": "c" * 64,
                "pr_number": 42,
                "artifact_dir": f"artifacts/{run_dir.name}",
                "mode": "post_pr",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "validation-plan.json").write_text(
        json.dumps(
            {
                "model_identity_status": "proven",
                "reviewer_status": "available",
                "validation_status": "passed",
                "pr_check_status": "passed",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "review-ledger.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
    )
    completed = subprocess.run(
        [sys.executable, str(runner.HELPER), "decide", "--run-dir", str(run_dir)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    decision = json.loads((run_dir / "readiness-decision.json").read_text())
    assert decision["decision"] == "ready_post_pr_checks"
    assert decision["active_blocker_count"] == 0

    blocking_events = [dict(event) for event in events]
    for event in blocking_events:
        event["severity"] = "High"
        event["blocking"] = True
    (run_dir / "review-ledger.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in blocking_events),
        encoding="utf-8",
    )
    blocked = subprocess.run(
        [sys.executable, str(runner.HELPER), "decide", "--run-dir", str(run_dir)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert blocked.returncode != 0
    assert "OPEN -> VERIFIED is reserved" in blocked.stderr
