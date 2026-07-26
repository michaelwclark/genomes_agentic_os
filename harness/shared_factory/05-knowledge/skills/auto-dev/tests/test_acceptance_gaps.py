"""Executable tests for the three §12 AC slices flagged in the 2026-07-06 DoD verification.

- AC3 hybrid specifics: scrubber rejects Linear personal-board URLs in writeback
  text; Linear personal-card movement never derives or propagates a Jira transition.
- AC4 slice: resume after step-ledger truncation (crash mid-append) without
  duplicating side-effect steps — idempotency keys respected.
- AC10 slice: missing required dev_factory config (spec_source: linear with a
  null linear team_id) must block with config_missing, never fall back to LOS.

All three slices are implemented as of 2026-07-08 (linear_url scrub check,
project_context dev_factory loader + context-load CLI); every test here asserts
the real behavior — no expectedFailure/skip markers remain.
"""

from __future__ import annotations

import json
import argparse
import contextlib
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
from tracker.hybrid import HybridFixtureAdapter
from tracker.scrub import scrub_text as tracker_scrub_text
import auto_dev_state
import project_context

LINEAR_PERSONAL_URL = "https://linear.app/example/issue/LIN-42/fixture-linear-item"


def transition_args(run_dir: Path, to: str, key: str) -> argparse.Namespace:
    return argparse.Namespace(
        run_dir=run_dir,
        to=to,
        from_state=None,
        actor="test",
        reason=f"test to {to}",
        receipt=f"test:{to}",
        idempotency_key=key,
        ref=None,
    )


class AcceptanceGapTests(unittest.TestCase):
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

    def test_ac3_scrubber_rejects_linear_personal_board_url(self) -> None:
        """AC3: the scrubber blocks any writeback containing a Linear personal-board URL.

        Hybrid projects treat the personal Linear board as a private surface, so a
        linear.app URL is flagged/blocked exactly like a private Notion link — in
        both tracker/scrub.py CHECKS and auto_dev_state's scrub_text.
        """
        writeback = f"Status update: implementation complete. Personal mirror: {LINEAR_PERSONAL_URL}"

        self.assertIn("linear_url", tracker_scrub_text(writeback))

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "writeback.md"
            out = Path(tmp) / "writeback.scrubbed.md"
            src.write_text(writeback, encoding="utf-8")
            completed = self.run_helper(
                "scrub-external-output", "--input", str(src), "--output", str(out), check=False
            )
            self.assertEqual(completed.returncode, 2)
            payload = json.loads(completed.stdout)
            self.assertIn("linear_url", payload["findings"])
            self.assertNotIn(LINEAR_PERSONAL_URL, out.read_text(encoding="utf-8"))

    def test_ac3_linear_card_movement_never_transitions_jira(self) -> None:
        jira = JiraFixtureAdapter.from_file(FIXTURES / "tracker" / "jira-work-item.json")
        linear = LinearFixtureAdapter.from_file(FIXTURES / "tracker" / "linear-work-item.json")
        hybrid = HybridFixtureAdapter(jira, linear)

        jira_before = json.dumps(jira.payload, sort_keys=True)

        # Personal-card movement, both directly and via the hybrid mirror path.
        moved = linear.transition("LIN-42", "completed", note="personal done")
        self.assertEqual(moved.workflow_state, "completed")
        mirrored = hybrid.mirror_linear("LIN-42", "started")
        self.assertEqual(mirrored.workflow_state, "started")

        # Jira state was never derived from any of it.
        self.assertEqual(json.dumps(jira.payload, sort_keys=True), jira_before)
        self.assertEqual(jira.fetch("FLYWL-0001").workflow_state, "To Do")

        # Company workflow transition goes to Jira only; Linear stays untouched.
        linear_before = json.dumps(linear.payload, sort_keys=True)
        transitioned = hybrid.transition("FLYWL-0001", "In Progress")
        self.assertEqual(transitioned.workflow_state, "In Progress")
        self.assertEqual(json.dumps(linear.payload, sort_keys=True), linear_before)

    def test_ac4_resume_after_ledger_truncation_without_duplicate_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            init_args = auto_dev_state.fixture_init_args(run_dir, {"name": "ac4_ledger_truncation"})
            with contextlib.redirect_stdout(io.StringIO()):
                auto_dev_state.command_init(init_args)
                auto_dev_state.command_claim(
                    argparse.Namespace(
                        run_dir=run_dir,
                        owner_run_id="owner-ac4",
                        heartbeat_ttl_seconds=900,
                        distributed_token="fixture:claim",
                        actor="test",
                        receipt="claim receipt",
                        idempotency_key="claim:ac4",
                    )
                )
                auto_dev_state.command_transition(transition_args(run_dir, "context_loaded", "context:ac4"))
                auto_dev_state.command_transition(transition_args(run_dir, "planned", "plan:ac4"))
                auto_dev_state.command_transition(
                    transition_args(run_dir, "worktree_ready", "branch:feature/FIX-1-fixture")
                )

            ledger = auto_dev_state.ledger_path(run_dir)
            durable_ledger = ledger.read_text(encoding="utf-8")
            durable_state = auto_dev_state.load_state(run_dir)

            # Crash window A: the pr_open ledger append was torn away mid-write
            # (truncate back to the last recorded entry); state.json — written
            # after the append — was never persisted either.
            with contextlib.redirect_stdout(io.StringIO()):
                auto_dev_state.command_transition(transition_args(run_dir, "pr_open", "pr:FIX-1"))
            ledger.write_text(durable_ledger, encoding="utf-8")
            auto_dev_state.save_state(run_dir, durable_state)

            # Recovery reattaches from the last durable state.
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                validated = auto_dev_state.command_validate(argparse.Namespace(run_dir=run_dir))
            self.assertEqual(validated, 0)
            self.assertEqual(json.loads(buffer.getvalue())["state"], "worktree_ready")

            # Replaying the interrupted step with its idempotency key records it once.
            with contextlib.redirect_stdout(io.StringIO()):
                resumed = auto_dev_state.command_transition(transition_args(run_dir, "pr_open", "pr:FIX-1"))
            self.assertEqual(resumed, 0)

            events = auto_dev_state.read_jsonl(ledger)
            keys = [event["idempotency_key"] for event in events]
            self.assertEqual(len(keys), len(set(keys)))
            self.assertEqual(keys.count("pr:FIX-1"), 1)
            self.assertEqual(keys.count("branch:feature/FIX-1-fixture"), 1)

            state = auto_dev_state.load_state(run_dir)
            self.assertEqual(state["current_state"], "pr_open")
            # No re-claim happened: the original claim survived the crash-resume.
            self.assertEqual(state["claim"]["owner_run_id"], "owner-ac4")

            # Crash window B: the append was durable but state.json was not yet
            # saved. Replaying the step must be an idempotency-key no-op — no
            # duplicate side-effect entry.
            recovered_state = state
            auto_dev_state.save_state(run_dir, durable_state)
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                replayed = auto_dev_state.command_transition(transition_args(run_dir, "pr_open", "pr:FIX-1"))
            self.assertEqual(replayed, 0)
            self.assertTrue(json.loads(buffer.getvalue())["noop"])
            self.assertEqual(len(auto_dev_state.read_jsonl(ledger)), len(events))

            # Replaying an already-completed step (state.json == pr_open) is
            # refused outright — the guard rails also prevent duplication there.
            auto_dev_state.save_state(run_dir, recovered_state)
            with self.assertRaises(auto_dev_state.AutoDevStateError):
                auto_dev_state.command_transition(transition_args(run_dir, "pr_open", "pr:FIX-1"))
            self.assertEqual(len(auto_dev_state.read_jsonl(ledger)), len(events))

            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                self.assertEqual(auto_dev_state.command_validate(argparse.Namespace(run_dir=run_dir)), 0)
            self.assertEqual(json.loads(buffer.getvalue())["state"], "pr_open")

    def test_ac10_missing_required_config_blocks_with_config_missing(self) -> None:
        """AC10: spec_source: linear with a null linear team_id blocks with config_missing.

        The dev_factory loader fails closed — no defaults, no LOS fallback — and
        the context-load CLI reports ok:false with the config_missing reason (exit 2).
        """
        import yaml

        config_path = FIXTURES / "project-configs" / "linear-primary-missing-team-id.yml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        tracker = config["dev_factory"]["tracker"]
        self.assertEqual(tracker["kind"], "linear")
        self.assertEqual(tracker["spec_source"], "linear")
        self.assertIsNone(tracker["team_id"])

        # API path: the loader raises config_missing naming the offending key.
        with self.assertRaises(project_context.ConfigMissingError) as caught:
            project_context.load_dev_factory(config_path)
        self.assertTrue(str(caught.exception).startswith("config_missing:"))
        self.assertIn("team_id", str(caught.exception))

        # CLI path: context-load blocks with ok:false + config_missing, exit 2.
        completed = self.run_helper(
            "context-load", "--project-config", str(config_path), check=False
        )
        self.assertEqual(completed.returncode, 2)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["reason"].startswith("config_missing:"))
        self.assertIn("team_id", payload["reason"])

    def test_ac10_valid_configs_load_without_defaults(self) -> None:
        """AC10 positive: complete linear-primary and hybrid configs load cleanly."""
        for name, spec_source in [("linear-primary.yml", "linear"), ("hybrid.yml", "jira")]:
            config_path = FIXTURES / "project-configs" / name
            dev_factory = project_context.load_dev_factory(config_path)
            self.assertEqual(dev_factory["tracker"]["spec_source"], spec_source)

            completed = self.run_helper("context-load", "--project-config", str(config_path))
            payload = json.loads(completed.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["summary"]["spec_source"], spec_source)
            self.assertEqual(payload["summary"]["merge_policy"], "never_auto")
            self.assertIsNotNone(payload["summary"]["repo_path"])
            self.assertIsNotNone(payload["summary"]["base_branch"])


if __name__ == "__main__":
    unittest.main()
