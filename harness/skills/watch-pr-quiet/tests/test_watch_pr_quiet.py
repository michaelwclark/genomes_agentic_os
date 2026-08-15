from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "watch_pr_quiet.py"
SKILL = Path(__file__).parents[1] / "SKILL.md"
DASHBOARD = (
    Path(__file__).parents[3]
    / "shared_factory"
    / "00-control-plane"
    / "operator-attention-dashboard.yml"
)
SPEC = importlib.util.spec_from_file_location("watch_pr_quiet", SCRIPT)
assert SPEC and SPEC.loader
watcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watcher)


def pr(sha: str = "expected-sha", state: str = "open") -> dict:
    return {
        "headBranch": "feature/test",
        "headSha": sha,
        "state": state,
    }


def successful_check(name: str, sha: str = "expected-sha") -> dict:
    return {
        "conclusion": "success",
        "headSha": sha,
        "name": name,
        "status": "completed",
    }


def completed_check(name: str, conclusion: str, sha: str = "expected-sha") -> dict:
    return {
        "conclusion": conclusion,
        "headSha": sha,
        "name": name,
        "status": "completed",
    }


def running_check(name: str, sha: str = "expected-sha") -> dict:
    return {
        "conclusion": None,
        "headSha": sha,
        "name": name,
        "status": "in_progress",
    }


class WatchPrQuietTests(unittest.TestCase):
    def test_waits_for_expected_head_instead_of_accepting_stale_checks(self) -> None:
        state = watcher.summarize_checks(
            pr("stale-sha"),
            [successful_check("CodeQL")],
            min_checks=1,
            expected_head_sha="expected-sha",
            required_checks=["PR Smoke"],
        )

        self.assertEqual(state["status"], "pending")
        self.assertFalse(state["head_matches_expected"])
        self.assertEqual(state["missing_required_checks"], ["PR Smoke"])
        self.assertIn("waiting for expected PR head SHA", state["pending"])
        self.assertEqual(state["observed_count"], 0)
        self.assertEqual(state["checks"], [])

    def test_ignores_stale_head_failures_until_expected_head_appears(self) -> None:
        state = watcher.summarize_checks(
            pr("stale-sha"),
            [completed_check("CodeQL", "failure")],
            min_checks=1,
            expected_head_sha="expected-sha",
            required_checks=["PR Smoke"],
        )

        self.assertEqual(state["status"], "pending")
        self.assertEqual(state["failures"], [])
        self.assertEqual(state["observed_count"], 0)
        self.assertEqual(state["checks"], [])

    def test_fails_when_head_changes_after_expected_head_was_seen(self) -> None:
        state = watcher.summarize_checks(
            pr("newer-sha"),
            [successful_check("PR Smoke")],
            min_checks=1,
            expected_head_sha="expected-sha",
            required_checks=["PR Smoke"],
            expected_head_seen=True,
        )

        self.assertEqual(state["status"], "failure")
        self.assertEqual(state["failures"], ["PR head changed from expected SHA"])

    def test_waits_for_required_check_while_exact_head_context_is_not_settled(self) -> None:
        state = watcher.summarize_checks(
            pr(),
            [successful_check("CodeQL"), running_check("Python suite and packaging")],
            min_checks=1,
            expected_head_sha="expected-sha",
            required_checks=["PR Smoke"],
        )

        self.assertEqual(state["status"], "pending")
        self.assertEqual(state["missing_required_checks"], ["PR Smoke"])
        self.assertEqual(state["invalid_required_checks"], [])

    def test_rejects_stale_workflow_display_labels_after_exact_head_context_settles(self) -> None:
        state = watcher.summarize_checks(
            pr(),
            [successful_check("Docs link policy"), successful_check("Python suite and packaging")],
            min_checks=1,
            expected_head_sha="expected-sha",
            required_checks=["Docs", "Test", "Python suite"],
        )

        first, missing, observations = watcher.apply_required_check_emission_grace(state)

        self.assertEqual(first["status"], "pending")
        self.assertEqual(state["missing_required_checks"], ["Docs", "Python suite", "Test"])
        self.assertEqual(first["invalid_required_checks"], [])
        self.assertEqual(observations, 1)

        second, _, observations = watcher.apply_required_check_emission_grace(
            state,
            previous_missing_required_checks=missing,
            settled_missing_required_observations=observations,
        )

        self.assertEqual(second["status"], "failure")
        self.assertEqual(second["invalid_required_checks"], ["Docs", "Python suite", "Test"])
        self.assertEqual(observations, 2)
        self.assertEqual(
            second["observed_check_names"],
            ["Docs link policy", "Python suite and packaging"],
        )
        self.assertEqual(
            second["failures"],
            [
                "required check label not emitted at exact head: Docs",
                "required check label not emitted at exact head: Python suite",
                "required check label not emitted at exact head: Test",
            ],
        )

    def test_waits_for_a_required_check_during_the_settled_emission_gap(self) -> None:
        first = watcher.summarize_checks(
            pr(),
            [successful_check("Docs link policy")],
            min_checks=1,
            expected_head_sha="expected-sha",
            required_checks=["Python suite and packaging"],
        )
        first, missing, observations = watcher.apply_required_check_emission_grace(first)

        self.assertEqual(first["status"], "pending")
        self.assertEqual(first["invalid_required_checks"], [])
        self.assertEqual(missing, ["Python suite and packaging"])
        self.assertEqual(observations, 1)

        second = watcher.summarize_checks(
            pr(),
            [
                successful_check("Docs link policy"),
                successful_check("Python suite and packaging"),
            ],
            min_checks=1,
            expected_head_sha="expected-sha",
            required_checks=["Python suite and packaging"],
        )
        second, missing, observations = watcher.apply_required_check_emission_grace(
            second,
            previous_missing_required_checks=missing,
            settled_missing_required_observations=observations,
        )

        self.assertEqual(second["status"], "success")
        self.assertEqual(second["invalid_required_checks"], [])
        self.assertEqual(missing, [])
        self.assertEqual(observations, 0)

    def test_succeeds_only_when_expected_head_and_required_checks_pass(self) -> None:
        state = watcher.summarize_checks(
            pr(),
            [successful_check("CodeQL"), successful_check("PR Smoke")],
            min_checks=1,
            expected_head_sha="expected-sha",
            required_checks=["PR Smoke"],
        )

        self.assertEqual(state["status"], "success")
        self.assertTrue(state["head_matches_expected"])
        self.assertEqual(state["missing_required_checks"], [])

    def test_required_check_must_conclude_success(self) -> None:
        for conclusion in ("neutral", "skipped"):
            with self.subTest(conclusion=conclusion):
                state = watcher.summarize_checks(
                    pr(),
                    [completed_check("PR Smoke", conclusion)],
                    min_checks=1,
                    expected_head_sha="expected-sha",
                    required_checks=["PR Smoke"],
                )

                self.assertEqual(state["status"], "failure")
                self.assertEqual(
                    state["failures"],
                    [f"required check did not pass: PR Smoke ({conclusion})"],
                )

    def test_ignores_workflow_runs_from_an_older_head_on_the_same_branch(self) -> None:
        state = watcher.summarize_checks(
            pr(),
            [successful_check("PR Smoke", sha="older-sha")],
            min_checks=1,
            expected_head_sha="expected-sha",
            required_checks=["PR Smoke"],
        )

        self.assertEqual(state["status"], "pending")
        self.assertEqual(state["observed_count"], 0)
        self.assertEqual(state["checks"], [])
        self.assertEqual(state["missing_required_checks"], ["PR Smoke"])

    def test_resolves_bridge_token_without_invoking_gh(self) -> None:
        self.assertEqual(
            watcher.github_token_from_environment({"GH_TOKEN": "bridge-token"}),
            "bridge-token",
        )
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn('["gh",', source)

    def test_cli_accepts_expected_head_and_repeatable_required_checks(self) -> None:
        args = watcher.parse_args(
            [
                "--pr",
                "57",
                "--output-dir",
                "/tmp/pr-watch",
                "--timeout-minutes",
                "60",
                "--expected-head-sha",
                "expected-sha",
                "--required-check",
                "PR Smoke",
                "--required-check",
                "CodeQL",
            ]
        )

        self.assertEqual(args.expected_head_sha, "expected-sha")
        self.assertEqual(args.required_check, ["PR Smoke", "CodeQL"])

    def test_skill_routes_long_watchers_through_governed_long_run(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")

        self.assertIn("agentic-os long-run start", skill)
        self.assertNotIn("nohup python3", skill)

    def test_operator_dashboard_surfaces_delivery_gate_failures(self) -> None:
        dashboard = DASHBOARD.read_text(encoding="utf-8")

        self.assertIn("id: watch_pr_quiet", dashboard)
        self.assertIn("the PR head differs from the exact SHA bound to the watcher", dashboard)
        self.assertIn(
            "a required workflow check completes without an explicit success conclusion",
            dashboard,
        )


if __name__ == "__main__":
    unittest.main()
