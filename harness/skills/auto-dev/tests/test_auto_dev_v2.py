from __future__ import annotations

import json
import argparse
import contextlib
import datetime as dt
import io
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "harness" / "skills" / "auto-dev" / "scripts" / "auto_dev_state.py"
FIXTURES = ROOT / "harness" / "skills" / "auto-dev" / "fixtures"
sys.path.insert(0, str(ROOT / "harness" / "skills" / "auto-dev" / "scripts"))

from tracker.jira import JiraFixtureAdapter
from tracker.linear import LinearFixtureAdapter
from notion_projector import project
from copilot_loop import reduce_threads
import auto_dev_state
import copilot_loop


class AutoDevV2Tests(unittest.TestCase):
    def run_helper(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True,
            capture_output=True,
            check=False,
        )
        if check and completed.returncode != 0:
            self.fail(f"helper failed: {completed.stderr}\n{completed.stdout}")
        return completed

    def test_fixture_suite(self) -> None:
        completed = self.run_helper("fixture-test", "--fixtures", str(FIXTURES))
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])

    def test_scrub_blocks_local_path_and_notion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "note.md"
            out = Path(tmp) / "out.md"
            src.write_text("See /Users/genome/private and https://app.notion.com/p/private", encoding="utf-8")
            completed = self.run_helper("scrub-external-output", "--input", str(src), "--output", str(out), check=False)
            self.assertEqual(completed.returncode, 2)
            payload = json.loads(completed.stdout)
            self.assertIn("local_path", payload["findings"])
            self.assertIn("private_notion_link", payload["findings"])

    def test_tracker_adapters_claim_by_reread(self) -> None:
        jira = JiraFixtureAdapter.from_file(FIXTURES / "tracker" / "jira-work-item.json")
        claimed_jira = jira.claim("FLYWL-0001", "autodev", "autodev-claimed", "In Progress")
        self.assertEqual(claimed_jira.assignee, "autodev")
        self.assertIn("autodev-claimed", claimed_jira.labels)
        self.assertEqual(claimed_jira.workflow_state, "In Progress")

        linear = LinearFixtureAdapter.from_file(FIXTURES / "tracker" / "linear-work-item.json")
        claimed_linear = linear.claim("LIN-42", "autodev@example.com", "autodev-claimed", "started")
        self.assertEqual(claimed_linear.assignee, "autodev@example.com")
        self.assertIn("autodev-claimed", claimed_linear.labels)
        self.assertEqual(claimed_linear.workflow_state, "started")

    def test_projector_failure_is_non_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = project(Path(tmp) / "missing", Path(tmp) / "projection.md")
            self.assertFalse(result["ok"])

    def test_copilot_loop_blocks_after_repeated_actionable_findings(self) -> None:
        result = reduce_threads(
            {
                "rounds": 2,
                "max_rounds_without_progress": 2,
                "threads": [{"id": "thread-1", "body": "This is a failing test regression."}],
            }
        )

        self.assertEqual(result["decision"], "blocked_loop_limit")
        self.assertEqual(result["threads"][0]["action"], "fix_required")

    def test_skill_contract_requires_pr_watch_repair_loop(self) -> None:
        skill_text = (ROOT / "harness" / "skills" / "auto-dev" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("Starting a watcher is not a", skill_text)
        self.assertIn("failed checks must be inspected, fixed, pushed, and", skill_text)
        self.assertIn("copilot_clean=passed", skill_text)

    def prepare_review(self, run_dir: Path, mode: str = "pre_pr") -> Path:
        init_args = auto_dev_state.fixture_init_args(run_dir, {"name": "cli_review"})
        with contextlib.redirect_stdout(io.StringIO()):
            auto_dev_state.command_init(init_args)
        state = auto_dev_state.load_state(run_dir)
        state["current_state"] = "finishing_review"
        state["previous_state"] = "local_validation"
        repo_path = run_dir.parent / "repo"
        worktree_path = run_dir.parent / "worktree"
        repo_path.mkdir(exist_ok=True)
        worktree_path.mkdir(exist_ok=True)
        state["context"]["repo_path"] = str(repo_path)
        state["context"]["worktree"] = str(worktree_path)
        auto_dev_state.save_state(run_dir, state)
        args = argparse.Namespace(
            run_dir=run_dir,
            mode=mode,
            review_run_id=None,
            review_run_dir=None,
            builder_model="gpt-5.6-codex",
            reviewer_model="claude-opus",
            builder_family="gpt",
            reviewer_family="opus",
            reviewer_transport="claude_cli",
            review_unavailable_policy="continue_with_receipt",
            actor="test",
            implementation_summary="fixture",
            validation_status="passed",
            pr_check_status="not_applicable" if mode == "pre_pr" else "passed",
            copilot_status="not_applicable" if mode == "pre_pr" else "resolved",
            loop_limit=3,
            base_sha="base",
            head_sha="head",
            diff_hash="fixture",
            pr_url=None,
            spec="fixture spec",
            acceptance_criteria="fixture AC",
            validation_summary="fixture validation passed",
            ci_status="not_applicable",
            diff_or_file_list="fixture files",
            tokens="none",
            idempotency_key="prepare:cli-review",
        )
        with contextlib.redirect_stdout(io.StringIO()):
            auto_dev_state.command_prepare_review(args)
        state = auto_dev_state.load_state(run_dir)
        return run_dir / Path(state["finishing"][mode]["ref"]).parent

    def test_prepare_review_records_cli_native_transport_and_fallback_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            review_dir = self.prepare_review(run_dir)
            request = auto_dev_state.read_json(review_dir / "review-request.json")
            plan = auto_dev_state.read_json(review_dir / "validation-plan.json")

            self.assertEqual(request["reviewer_transport"], "claude_cli")
            self.assertEqual(request["reviewer_auth"], "cli_native")
            self.assertEqual(
                request["reviewer_environment_removed"],
                ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"],
            )
            self.assertEqual(request["reviewed_repo_path"], str((run_dir.parent / "worktree").resolve()))
            self.assertEqual(request["expected_head_sha"], "head")
            self.assertEqual(plan["review_unavailable_policy"], "continue_with_receipt")

    def test_record_cli_unavailable_sanitizes_receipt_and_resumes_ready_pre_pr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            review_dir = self.prepare_review(run_dir)

            def ready_decision(path: Path) -> dict[str, str]:
                auto_dev_state.atomic_write_json(
                    path / "readiness-decision.json", {"decision": "ready_pre_pr"}
                )
                return {"decision": "ready_pre_pr"}

            args = argparse.Namespace(
                run_dir=run_dir,
                review_run_dir=review_dir,
                failure_code="cli_auth_failed",
                failure_summary=(
                    "ANTHROPIC_API_KEY=secret /Users/genome/private auth failed\n"
                    "Authorization: Bearer also-secret"
                ),
                review_unavailable_policy="continue_with_receipt",
                actor="test",
                idempotency_key="unavailable:cli-review",
            )
            with mock.patch.object(auto_dev_state, "run_finishing_decide", side_effect=ready_decision):
                with contextlib.redirect_stdout(io.StringIO()):
                    auto_dev_state.command_record_review_unavailable(args)

            self.assertEqual(auto_dev_state.load_state(run_dir)["current_state"], "pr_open")
            receipt = (review_dir / "model-receipt.md").read_text(encoding="utf-8")
            self.assertIn("Transport: `claude_cli`", receipt)
            self.assertIn("Unavailable policy: `continue_with_receipt`", receipt)
            self.assertNotIn("also-secret", receipt)
            self.assertNotIn("/Users/genome/private", receipt)

    def test_record_cli_unavailable_honors_block_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            review_dir = self.prepare_review(run_dir)
            args = argparse.Namespace(
                run_dir=run_dir,
                review_run_dir=review_dir,
                failure_code="cli_timeout",
                failure_summary="Claude CLI timed out",
                review_unavailable_policy="block",
                actor="test",
                idempotency_key="unavailable:block",
            )
            with mock.patch.object(
                auto_dev_state,
                "run_finishing_decide",
                return_value={"decision": "blocked_reviewer_unavailable"},
            ):
                with contextlib.redirect_stdout(io.StringIO()):
                    auto_dev_state.command_record_review_unavailable(args)

            self.assertEqual(
                auto_dev_state.load_state(run_dir)["current_state"], "awaiting_human_review"
            )
            plan = auto_dev_state.read_json(review_dir / "validation-plan.json")
            self.assertEqual(plan["review_unavailable_policy"], "block")

    def test_record_cli_unavailable_cannot_replace_review_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            review_dir = self.prepare_review(run_dir)
            auto_dev_state.append_jsonl(
                review_dir / "review-ledger.jsonl",
                {
                    "event_type": "finding_opened",
                    "created_at": auto_dev_state.utc_now(),
                    "id": "finding-1",
                },
            )
            args = argparse.Namespace(
                run_dir=run_dir,
                review_run_dir=review_dir,
                failure_code="unknown",
                failure_summary="review unavailable",
                review_unavailable_policy="continue_with_receipt",
                actor="test",
                idempotency_key="unavailable:blocked-by-finding",
            )
            with self.assertRaises(auto_dev_state.AutoDevStateError):
                auto_dev_state.command_record_review_unavailable(args)

    def run_review_args(self, run_dir: Path, review_dir: Path) -> argparse.Namespace:
        return argparse.Namespace(
            run_dir=run_dir,
            review_run_dir=review_dir,
            reviewer_model="opus",
            timeout_seconds=30,
            review_unavailable_policy="continue_with_receipt",
            attested_by="test runner",
            actor="test",
            idempotency_key="run-review:test",
        )

    def test_run_review_uses_claude_cli_native_auth_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            review_dir = self.prepare_review(run_dir)
            args = self.run_review_args(run_dir, review_dir)
            response = "```json\n[]\n```\nVERDICT: ready\n"
            completed = subprocess.CompletedProcess(
                args=["/usr/local/bin/claude"],
                returncode=0,
                stdout=response,
                stderr="diagnostic stderr must not be persisted",
            )
            with mock.patch.dict(
                auto_dev_state.os.environ,
                {"ANTHROPIC_API_KEY": "wrong-key", "ANTHROPIC_AUTH_TOKEN": "wrong-token"},
            ):
                with mock.patch.object(auto_dev_state.shutil, "which", return_value="/usr/local/bin/claude"):
                    git_head = subprocess.CompletedProcess(
                        args=["git"], returncode=0, stdout="head\n", stderr=""
                    )
                    with mock.patch.object(
                        auto_dev_state.subprocess, "run", side_effect=[git_head, completed]
                    ) as run:
                        with mock.patch.object(
                            auto_dev_state, "command_ingest_review", return_value=0
                        ) as ingest:
                            auto_dev_state.command_run_review(args)

            call = run.call_args_list[1]
            self.assertEqual(
                call.args[0],
                [
                    "/usr/local/bin/claude",
                    "-p",
                    "--model",
                    "opus",
                    "--safe-mode",
                    "--permission-mode",
                    "dontAsk",
                    "--tools",
                    "Read,Grep,Glob,Bash",
                    "--allowedTools",
                    auto_dev_state.CLAUDE_REVIEW_ALLOWED_TOOLS,
                    "--no-session-persistence",
                ],
            )
            self.assertNotIn("ANTHROPIC_API_KEY", call.kwargs["env"])
            self.assertNotIn("ANTHROPIC_AUTH_TOKEN", call.kwargs["env"])
            self.assertEqual(call.kwargs["cwd"], str((run_dir.parent / "worktree").resolve()))
            self.assertEqual(
                (review_dir / "reviewer-response.md").read_text(encoding="utf-8"), response
            )
            self.assertNotIn(
                "diagnostic stderr must not be persisted",
                (review_dir / "reviewer-response.md").read_text(encoding="utf-8"),
            )
            ingest.assert_called_once()

    def test_run_review_credit_failure_records_sanitized_nonblocking_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            review_dir = self.prepare_review(run_dir)
            args = self.run_review_args(run_dir, review_dir)
            completed = subprocess.CompletedProcess(
                args=["/usr/local/bin/claude"],
                returncode=1,
                stdout="",
                stderr=(
                    "Anthropic API: Credit balance is too low "
                    "ANTHROPIC_API_KEY=secret /Users/genome/private"
                ),
            )
            with mock.patch.object(auto_dev_state.shutil, "which", return_value="/usr/local/bin/claude"):
                git_head = subprocess.CompletedProcess(
                    args=["git"], returncode=0, stdout="head\n", stderr=""
                )
                with mock.patch.object(
                    auto_dev_state.subprocess, "run", side_effect=[git_head, completed]
                ):
                    with mock.patch.object(
                        auto_dev_state, "command_record_review_unavailable", return_value=0
                    ) as record:
                        auto_dev_state.command_run_review(args)

            receipt_args = record.call_args.args[0]
            self.assertEqual(receipt_args.failure_code, "cli_credit_or_api_route")
            self.assertEqual(receipt_args.review_unavailable_policy, "continue_with_receipt")
            self.assertNotIn("secret", receipt_args.failure_summary)
            self.assertNotIn("/Users/genome/private", receipt_args.failure_summary)
            self.assertFalse((review_dir / "reviewer-response.md").exists())

    def test_run_review_malformed_nonempty_output_pauses_without_downgrade(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            review_dir = self.prepare_review(run_dir)
            args = self.run_review_args(run_dir, review_dir)
            malformed = "```json\n[]\n```\nVERDICT: changes_required\n"
            git_head = subprocess.CompletedProcess(
                args=["git"], returncode=0, stdout="head\n", stderr=""
            )
            completed = subprocess.CompletedProcess(
                args=["/usr/local/bin/claude"], returncode=0, stdout=malformed, stderr=""
            )
            with mock.patch.object(auto_dev_state.shutil, "which", return_value="/usr/local/bin/claude"):
                with mock.patch.object(
                    auto_dev_state.subprocess, "run", side_effect=[git_head, completed]
                ):
                    with mock.patch.object(
                        auto_dev_state, "command_record_review_unavailable"
                    ) as unavailable:
                        with contextlib.redirect_stdout(io.StringIO()):
                            result = auto_dev_state.command_run_review(args)

            self.assertEqual(result, 2)
            unavailable.assert_not_called()
            self.assertEqual(
                auto_dev_state.load_state(run_dir)["current_state"], "awaiting_human_review"
            )
            self.assertEqual(
                (review_dir / "reviewer-response.md").read_text(encoding="utf-8"), malformed
            )
            error = auto_dev_state.read_json(review_dir / "review-output-error.json")
            self.assertEqual(error["decision"], "malformed_reviewer_output")
            plan = auto_dev_state.read_json(review_dir / "validation-plan.json")
            self.assertEqual(plan["reviewer_status"], "available")
            self.assertEqual(plan["review_output_status"], "malformed")
            self.assertFalse((review_dir / "model-receipt.md").exists())

    def test_ingest_rejects_empty_findings_with_changes_required_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            review_dir = self.prepare_review(run_dir)
            response_path = review_dir / "reviewer-response.md"
            response_path.write_text(
                "```json\n[]\n```\nVERDICT: changes_required\n", encoding="utf-8"
            )
            args = argparse.Namespace(
                run_dir=run_dir,
                review_run_dir=review_dir,
                response=response_path,
                reviewer_model="opus",
                reviewer_transport="claude_cli",
                attested_by="test runner",
                actor="test",
                idempotency_key="ingest:contradictory-empty",
            )
            with self.assertRaisesRegex(
                auto_dev_state.AutoDevStateError,
                "changes_required is invalid when the findings array is empty",
            ):
                auto_dev_state.command_ingest_review(args)

            self.assertEqual(
                auto_dev_state.load_state(run_dir)["current_state"], "awaiting_human_review"
            )
            self.assertFalse((review_dir / "model-receipt.md").exists())

    def test_run_review_rejects_request_repo_that_is_not_canonical_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            review_dir = self.prepare_review(run_dir)
            request_path = review_dir / "review-request.json"
            request = auto_dev_state.read_json(request_path)
            request["reviewed_repo_path"] = str(run_dir.parent / "repo")
            auto_dev_state.atomic_write_json(request_path, request)
            args = self.run_review_args(run_dir, review_dir)

            with mock.patch.object(auto_dev_state.subprocess, "run") as run:
                with mock.patch.object(auto_dev_state, "command_record_review_unavailable") as unavailable:
                    with contextlib.redirect_stdout(io.StringIO()):
                        result = auto_dev_state.command_run_review(args)

            self.assertEqual(result, 2)
            run.assert_not_called()
            unavailable.assert_not_called()
            error = auto_dev_state.read_json(review_dir / "review-input-error.json")
            self.assertEqual(error["decision"], "review_input_error")
            self.assertEqual(error["error_code"], "canonical_repo_mismatch")
            self.assertEqual(
                auto_dev_state.load_state(run_dir)["current_state"], "awaiting_human_review"
            )
            self.assertFalse((review_dir / "model-receipt.md").exists())

    def test_run_review_rejects_head_mismatch_before_claude(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            review_dir = self.prepare_review(run_dir)
            args = self.run_review_args(run_dir, review_dir)
            mismatched_head = subprocess.CompletedProcess(
                args=["git"], returncode=0, stdout="different-head\n", stderr=""
            )
            with mock.patch.object(
                auto_dev_state.subprocess, "run", return_value=mismatched_head
            ) as run:
                with mock.patch.object(auto_dev_state, "command_record_review_unavailable") as unavailable:
                    with contextlib.redirect_stdout(io.StringIO()):
                        result = auto_dev_state.command_run_review(args)

            self.assertEqual(result, 2)
            self.assertEqual(run.call_count, 1)
            unavailable.assert_not_called()
            error = auto_dev_state.read_json(review_dir / "review-input-error.json")
            self.assertEqual(error["error_code"], "git_head_mismatch")
            self.assertEqual(error["expected_head_sha"], "head")
            self.assertEqual(error["observed_head_sha"], "different-head")
            self.assertEqual(
                auto_dev_state.load_state(run_dir)["current_state"], "awaiting_human_review"
            )

    def test_run_review_unverifiable_head_is_hard_input_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            review_dir = self.prepare_review(run_dir)
            args = self.run_review_args(run_dir, review_dir)
            git_failure = subprocess.CompletedProcess(
                args=["git"], returncode=128, stdout="", stderr="not a repository"
            )
            with mock.patch.object(auto_dev_state.subprocess, "run", return_value=git_failure):
                with mock.patch.object(auto_dev_state, "command_record_review_unavailable") as unavailable:
                    with contextlib.redirect_stdout(io.StringIO()):
                        result = auto_dev_state.command_run_review(args)

            self.assertEqual(result, 2)
            unavailable.assert_not_called()
            error = auto_dev_state.read_json(review_dir / "review-input-error.json")
            self.assertEqual(error["error_code"], "git_head_unverifiable")
            self.assertEqual(
                auto_dev_state.load_state(run_dir)["current_state"], "awaiting_human_review"
            )

    def test_allowed_tools_has_no_unrestricted_bash_entry(self) -> None:
        allowed = auto_dev_state.CLAUDE_REVIEW_ALLOWED_TOOLS.split(",")
        self.assertNotIn("Bash", allowed)
        self.assertIn("Bash(git diff *)", allowed)
        self.assertIn("Bash(git show *)", allowed)
        self.assertIn("Bash(git status *)", allowed)
        self.assertIn("Bash(git log *)", allowed)

    def test_receipt_summary_redacts_generic_and_provider_credentials(self) -> None:
        openai_fixture = "sk" + "-proj-openaiSecretValue123"
        github_fixture = "gh" + "p_abcdefghijklmnopqrstuvwxyz123456"
        slack_fixture = "xo" + "xb-1234567890-abcdefghijklmnop"
        aws_fixture = "AK" + "IA1234567890ABCDEF"
        summary = auto_dev_state.sanitize_receipt_summary(
            " ".join(
                [
                    f"OPENAI_API_KEY={openai_fixture}",
                    "AWS_SECRET_ACCESS_KEY=awsSecretValue123",
                    "AWS_SESSION_TOKEN=awsSessionValue123",
                    '"database_password": "hunter2"',
                    "MY_CUSTOM_TOKEN=customTokenValue123",
                    'SERVICE_SECRET="multi word secret value"',
                    "Authorization: Bearer bearerSecretValue123",
                    "--password commandSecretValue123",
                    "--token 'multi word command token'",
                    "https://user:urlSecretValue123@example.test/path",
                    github_fixture,
                    slack_fixture,
                    aws_fixture,
                ]
            )
        )
        for secret in [
            "openaiSecretValue123",
            "awsSecretValue123",
            "awsSessionValue123",
            "hunter2",
            "customTokenValue123",
            "multi word secret value",
            "bearerSecretValue123",
            "commandSecretValue123",
            "multi word command token",
            "urlSecretValue123",
            github_fixture,
            slack_fixture,
            aws_fixture,
        ]:
            self.assertNotIn(secret, summary)
        self.assertIn("[REDACTED_CREDENTIAL]", summary)

    def test_duplicate_claim_and_stale_recover(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            init_args = auto_dev_state.fixture_init_args(run_dir, {"name": "duplicate_claim"})
            with contextlib.redirect_stdout(io.StringIO()):
                auto_dev_state.command_init(init_args)
                first = auto_dev_state.command_claim(
                    argparse.Namespace(
                        run_dir=run_dir,
                        owner_run_id="owner-1",
                        heartbeat_ttl_seconds=900,
                        distributed_token="fixture:claim",
                        actor="test",
                        receipt="claim receipt",
                        idempotency_key="claim:test",
                    )
                )
                second = auto_dev_state.command_claim(
                    argparse.Namespace(
                        run_dir=run_dir,
                        owner_run_id="owner-2",
                        heartbeat_ttl_seconds=900,
                        distributed_token="fixture:claim",
                        actor="test",
                        receipt="claim receipt 2",
                        idempotency_key="claim:test-2",
                    )
                )
            self.assertEqual(first, 0)
            self.assertEqual(second, 2)

            state = auto_dev_state.load_state(run_dir)
            state["claim"]["pid"] = 999999
            state["claim"]["heartbeat_at"] = (
                dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
            ).isoformat().replace("+00:00", "Z")
            auto_dev_state.save_state(run_dir, state)
            with contextlib.redirect_stdout(io.StringIO()):
                recovered = auto_dev_state.command_recover(
                    argparse.Namespace(
                        run_dir=run_dir,
                        owner_run_id="owner-recovered",
                        heartbeat_ttl_seconds=900,
                    )
                )
            self.assertEqual(recovered, 0)
            self.assertEqual(auto_dev_state.load_state(run_dir)["claim"]["owner_run_id"], "owner-recovered")

    def test_copilot_loop_classifies_and_blocks_product_decision(self) -> None:
        payload = json.loads((FIXTURES / "copilot" / "threads.json").read_text(encoding="utf-8"))
        result = copilot_loop.reduce_threads(payload)
        actions = {thread["id"]: thread["action"] for thread in result["threads"]}
        self.assertEqual(actions["T1"], "fix_required")
        self.assertEqual(actions["T2"], "reply_and_resolve")
        self.assertEqual(actions["T3"], "block_for_product_decision")
        self.assertEqual(result["decision"], "blocked_product_decision")


if __name__ == "__main__":
    unittest.main()
