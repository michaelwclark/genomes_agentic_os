"""Offline tests for the cross-review command's shared GitHub read boundary."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import SimpleNamespace

import pytest

from genomes_agentic_os.github_bridge import GitHubBridgeError


def _load_crossreview():
    script = Path(__file__).parents[1] / "harness/bin/agentic-os-pr-crossreview"
    spec = importlib.util.spec_from_loader(
        "agentic_os_pr_crossreview_test", SourceFileLoader("agentic_os_pr_crossreview_test", str(script))
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_metadata_read_uses_the_shared_bridge_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    crossreview = _load_crossreview()
    monkeypatch.setattr(
        crossreview,
        "_bridge_pull_request",
        lambda repo, pr: {
            "title": "Bridge migration",
            "body": "Read only",
            "headBranch": "feature/read",
            "headSha": "exact-head",
            "baseBranch": "main",
            "baseSha": "exact-base",
            "author": "octocat",
        },
    )

    assert crossreview.get_pr_meta("acme/widgets", 42) == {
        "title": "Bridge migration",
        "body": "Read only",
        "head_branch": "feature/read",
        "head_sha": "exact-head",
        "base_branch": "main",
        "base_sha": "exact-base",
        "author_login": "octocat",
    }


def test_metadata_read_rejects_an_absent_head_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    crossreview = _load_crossreview()
    monkeypatch.setattr(crossreview, "_bridge_pull_request", lambda _repo, _pr: {"headSha": ""})

    with pytest.raises(SystemExit):
        crossreview.get_pr_meta("acme/widgets", 42)


def test_commit_read_is_bounded_and_keeps_the_legacy_message_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crossreview = _load_crossreview()
    observed: dict[str, object] = {}
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(crossreview, "github_command_from_environment", lambda: ["node", "bridge.mjs"])

    def list_commits(command, **kwargs):
        observed["command"] = command
        observed.update(kwargs)
        return [{"sha": "exact-commit", "message": "Subject\\n\\nCo-Authored-By: Claude"}]

    monkeypatch.setattr(crossreview, "bridge_list_pull_request_commits", list_commits)

    assert crossreview.get_pr_commits("acme/widgets", 42) == [
        {"sha": "exact-commit", "commit": {"message": "Subject\\n\\nCo-Authored-By: Claude"}}
    ]
    assert observed == {
        "command": ["node", "bridge.mjs"],
        "owner": "acme",
        "repo": "widgets",
        "number": 42,
        "token": "test-token",
        "limit": crossreview.MAX_COMMIT_SCAN,
    }


def test_diff_read_keeps_the_legacy_unavailable_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    crossreview = _load_crossreview()
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(crossreview, "github_command_from_environment", lambda: ["node", "bridge.mjs"])

    def unavailable(*_args, **_kwargs):
        raise GitHubBridgeError("UPSTREAM_TIMEOUT", "safe timeout")

    monkeypatch.setattr(crossreview, "bridge_get_pull_request_diff", unavailable)

    assert crossreview.get_pr_diff("acme/widgets", 42) == "(diff unavailable)"


def test_consistent_input_read_guards_author_evidence_and_diff(monkeypatch: pytest.MonkeyPatch) -> None:
    crossreview = _load_crossreview()
    calls: list[str] = []
    metas = iter([
        {"head_sha": "first", "head_branch": "feature/read"},
        {"head_sha": "second", "head_branch": "feature/read"},
    ])
    monkeypatch.setattr(crossreview, "get_pr_meta", lambda _repo, _pr: (calls.append("meta"), next(metas))[1])
    monkeypatch.setattr(crossreview, "get_pr_commits", lambda _repo, _pr: calls.append("commits") or [])
    monkeypatch.setattr(crossreview, "get_pr_diff", lambda _repo, _pr: calls.append("diff") or "diff")

    assert crossreview.read_consistent_pr_inputs("acme/widgets", 42, include_commits=True) is None
    assert calls == ["meta", "commits", "diff", "meta"]


def test_commit_scan_fails_closed_at_the_explicit_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    crossreview = _load_crossreview()
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(crossreview, "github_command_from_environment", lambda: ["node", "bridge.mjs"])
    monkeypatch.setattr(
        crossreview,
        "bridge_list_pull_request_commits",
        lambda *_args, **_kwargs: [{"sha": str(i), "message": "message"} for i in range(crossreview.MAX_COMMIT_SCAN)],
    )

    with pytest.raises(SystemExit):
        crossreview.get_pr_commits("acme/widgets", 42)


def test_direct_script_help_bootstraps_the_source_package(tmp_path: Path) -> None:
    script = Path(__file__).parents[1] / "harness/bin/agentic-os-pr-crossreview"
    base_python = Path(sys.base_prefix) / "bin" / f"python{sys.version_info.major}.{sys.version_info.minor}"
    assert base_python.exists()
    (tmp_path / "yaml.py").write_text("def safe_load(_value):\n    return {}\n", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(tmp_path)}
    result = subprocess.run(
        [str(base_python), str(script), "--help"], capture_output=True, text=True, check=False, env=env
    )

    assert result.returncode == 0
    assert "Run a senior-engineer PR review" in result.stdout


def test_review_outcome_is_terminal_and_findings_are_not_reclassified_clean() -> None:
    crossreview = _load_crossreview()

    clean = "No blockers found.\n\nAGENTIC_OS_REVIEW_VERDICT: CLEAN"
    findings = "WARNING: stale state\n\nAGENTIC_OS_REVIEW_VERDICT: FINDINGS"
    assert crossreview.classify_review_outcome(0, clean, True) == "clean"
    assert crossreview.classify_review_outcome(0, findings, True) == "findings"
    assert crossreview.classify_review_outcome(1, "review failed", True) == "unavailable"
    assert crossreview.classify_review_outcome(0, findings, False) == "findings"
    assert crossreview.classify_review_outcome(0, clean, False) == "unavailable"


@pytest.mark.parametrize(
    ("text", "expected", "structured"),
    [
        ("No issues found", "findings", False),
        ("AGENTIC_OS_REVIEW_VERDICT: MAYBE", "findings", False),
        (
            "AGENTIC_OS_REVIEW_VERDICT: CLEAN\nAGENTIC_OS_REVIEW_VERDICT: CLEAN",
            "clean",
            True,
        ),
        (
            "AGENTIC_OS_REVIEW_VERDICT: CLEAN\nAGENTIC_OS_REVIEW_VERDICT: FINDINGS",
            "findings",
            True,
        ),
        (
            "WARNING: problem\nAGENTIC_OS_REVIEW_VERDICT: CLEAN",
            "findings",
            True,
        ),
        (
            "### BLOCKER — unsafe write\nAGENTIC_OS_REVIEW_VERDICT: CLEAN",
            "findings",
            True,
        ),
        (
            "- **WARNING**: stale state\nAGENTIC_OS_REVIEW_VERDICT: CLEAN",
            "findings",
            True,
        ),
        (
            "No BLOCKER or WARNING findings were found.\n"
            "AGENTIC_OS_REVIEW_VERDICT: CLEAN",
            "clean",
            True,
        ),
        (
            "The prompt mentioned BLOCKER: as a label.\n"
            "AGENTIC_OS_REVIEW_VERDICT: CLEAN",
            "clean",
            True,
        ),
        (
            "AGENTIC_OS_REVIEW_VERDICT: CLEAN\ntrailing prose",
            "findings",
            False,
        ),
    ],
)
def test_review_verdict_parser_uses_only_the_final_non_empty_line(
    text: str, expected: str, structured: bool
) -> None:
    crossreview = _load_crossreview()

    assert crossreview.parse_review_verdict(text) == (expected, structured)


def test_purpose_and_scope_aliases_share_one_bounded_family() -> None:
    crossreview = _load_crossreview()

    aliases = ["review_self", "review-repair", "review_others", "finalize"]
    assert {
        crossreview.normalize_review_purpose(alias, "full_pr") for alias in aliases
    } == {("review_self", "full-pr")}
    with pytest.raises(crossreview.ReviewCoordinationError, match="purpose"):
        crossreview.normalize_review_purpose("second-opinion", "full-pr")
    with pytest.raises(crossreview.ReviewCoordinationError, match="scope"):
        crossreview.normalize_review_purpose("review_self", "changed-files")


def test_provider_marker_requires_the_exact_hidden_marker_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crossreview = _load_crossreview()
    marker = "<!-- agentic-os-review:stable-key -->"
    monkeypatch.setattr(
        crossreview,
        "list_provider_comments",
        lambda _repo, _pr: [
            {"id": 1, "body": f"quoted {marker} suffix"},
            {"id": 2, "body": f"review body\n  {marker}  \n"},
        ],
    )

    assert crossreview.existing_provider_marker("acme/widgets", 42, marker)["id"] == 2


def test_post_result_is_recorded_without_replacing_review_result(tmp_path: Path) -> None:
    crossreview = _load_crossreview()
    review_receipt = {
        "outcome": "clean",
        "review": {"text": "canonical review", "scrub_passed": True},
        "provider_post": {"status": "not_requested"},
    }
    posted_receipt = {
        **review_receipt,
        "provider_post": {"status": "posted", "result": {"comment_id": 92}},
    }
    review_result = SimpleNamespace(
        key="stable-key",
        receipt_path=tmp_path / "canonical.json",
        receipt=review_receipt,
        reused=False,
    )
    post_result = SimpleNamespace(receipt=posted_receipt)
    output = tmp_path / "compat.json"

    payload = crossreview.write_legacy_receipt(
        output,
        review_result=review_result,
        post_result=post_result,
        repo="acme/widgets",
        pr_number=42,
        meta={"title": "Repair", "head_sha": "a" * 40},
        base_sha="b" * 40,
        review_mode="full",
    )

    assert payload["text"] == "canonical review"
    assert payload["provider_post"]["status"] == "posted"
    assert json.loads(output.read_text(encoding="utf-8")) == payload


def test_delta_diff_requires_ancestry_and_defers_size_bound_to_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crossreview = _load_crossreview()
    responses = iter(["ahead", "bounded diff"])
    monkeypatch.setattr(crossreview, "gh", lambda *_args, **_kwargs: next(responses))

    assert crossreview.get_revision_diff("acme/widgets", "a" * 40, "b" * 40) == "bounded diff"

    monkeypatch.setattr(crossreview, "gh", lambda *_args, **_kwargs: "diverged")
    with pytest.raises(crossreview.ReviewCoordinationError, match="ancestor"):
        crossreview.get_revision_diff("acme/widgets", "a" * 40, "c" * 40)

    oversized = "x" * (crossreview.MAX_DIFF_CHARS + 1)
    responses = iter(["ahead", oversized])
    monkeypatch.setattr(crossreview, "gh", lambda *_args, **_kwargs: next(responses))
    delta = crossreview.get_revision_diff("acme/widgets", "a" * 40, "d" * 40)
    prompt = crossreview.build_review_prompt(
        "acme/widgets",
        42,
        {
            "title": "Repair review coordination",
            "body": "Bound duplicate review work.",
            "base_branch": "main",
            "head_branch": "repair",
            "head_sha": "d" * 40,
        },
        delta,
    )

    assert delta == oversized
    assert "DIFF TRUNCATED" in prompt
    assert f"showing first {crossreview.MAX_DIFF_CHARS:,}" in prompt


def test_terminal_provider_post_reuses_existing_marker_without_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crossreview = _load_crossreview()
    marker = "<!-- agentic-os-review:stable-key -->"
    monkeypatch.setattr(
        crossreview,
        "get_pr_meta",
        lambda _repo, _pr: {"head_sha": "a" * 40},
    )
    monkeypatch.setattr(
        crossreview,
        "existing_provider_marker",
        lambda _repo, _pr, _marker: {
            "id": 91,
            "html_url": "https://github.test/comment/91",
            "body": marker,
        },
    )
    monkeypatch.setattr(
        crossreview,
        "gh",
        lambda *_args, **_kwargs: pytest.fail("provider write must be reused"),
    )

    result = crossreview.post_terminal_review(
        "acme/widgets",
        42,
        "a" * 40,
        marker,
        {"status": "completed", "outcome": "clean", "review": {"text": "clean"}},
        post_mode="comment",
    )

    assert result == {
        "action": "reused",
        "comment_id": 91,
        "url": "https://github.test/comment/91",
        "head_sha": "a" * 40,
        "readback_verified": True,
    }


def test_terminal_provider_post_rereads_head_before_any_provider_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crossreview = _load_crossreview()
    monkeypatch.setattr(
        crossreview,
        "get_pr_meta",
        lambda _repo, _pr: {"head_sha": "b" * 40},
    )
    monkeypatch.setattr(
        crossreview,
        "existing_provider_marker",
        lambda *_args: pytest.fail("marker read must wait for exact-head proof"),
    )

    with pytest.raises(crossreview.ReviewCoordinationError, match="head changed"):
        crossreview.post_terminal_review(
            "acme/widgets",
            42,
            "a" * 40,
            "<!-- agentic-os-review:stable-key -->",
            {"status": "completed", "outcome": "clean", "review": {"text": "clean"}},
            post_mode="comment",
        )


def test_terminal_provider_post_writes_one_marked_comment_and_reads_it_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crossreview = _load_crossreview()
    marker = "<!-- agentic-os-review:stable-key -->"
    writes: list[tuple[str, ...]] = []
    comments = iter([None, {"id": 92, "html_url": "https://github.test/comment/92"}])
    monkeypatch.setattr(
        crossreview,
        "get_pr_meta",
        lambda _repo, _pr: {"head_sha": "a" * 40},
    )
    monkeypatch.setattr(
        crossreview,
        "existing_provider_marker",
        lambda _repo, _pr, _marker: next(comments),
    )
    monkeypatch.setattr(
        crossreview,
        "gh",
        lambda *args, **_kwargs: writes.append(args) or "",
    )

    result = crossreview.post_terminal_review(
        "acme/widgets",
        42,
        "a" * 40,
        marker,
        {
            "status": "completed",
            "outcome": "clean",
            "review": {
                "text": "No blockers.\nAGENTIC_OS_REVIEW_VERDICT: CLEAN",
                "scrub_passed": True,
            },
        },
        post_mode="comment",
    )

    assert result["action"] == "posted"
    assert result["readback_verified"] is True
    assert len(writes) == 1
    assert writes[0][:4] == ("pr", "comment", "42", "--repo")
    assert marker in writes[0][-1]


@pytest.mark.parametrize(
    "receipt",
    [
        {
            "status": "completed",
            "outcome": "findings",
            "review": {"text": "WARNING: fix me", "scrub_passed": True},
        },
        {
            "status": "completed",
            "outcome": "clean",
            "review": {"text": "clean", "scrub_passed": False},
        },
    ],
)
def test_terminal_provider_post_blocks_findings_and_scrub_failures_before_write(
    monkeypatch: pytest.MonkeyPatch, receipt: dict
) -> None:
    crossreview = _load_crossreview()
    monkeypatch.setattr(crossreview, "get_pr_meta", lambda *_args: {"head_sha": "a" * 40})
    monkeypatch.setattr(crossreview, "existing_provider_marker", lambda *_args: None)
    monkeypatch.setattr(
        crossreview, "gh", lambda *_args, **_kwargs: pytest.fail("provider write must be blocked")
    )

    with pytest.raises(crossreview.ReviewCoordinationError):
        crossreview.post_terminal_review(
            "acme/widgets",
            42,
            "a" * 40,
            "<!-- agentic-os-review:stable-key -->",
            receipt,
            post_mode="comment",
        )
