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
