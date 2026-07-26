import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("plan_pr_family", ROOT / "scripts" / "plan_pr_family.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class PlanPRFamily(unittest.TestCase):
    def test_only_missing_targets_are_proposed(self):
        topology = {
            "required_targets": [
                {"branch": "hotfix/v9.12.8"},
                {"branch": "release/v10.0.0"},
                {"branch": "develop"},
            ],
            "missing_targets": ["release/v10.0.0"],
            "family_complete": False,
        }
        result = MODULE.plan(
            topology,
            {"key": "FLYWL-4", "title": "Fix edge case"},
            "abc123",
            "feature/flywl-4-fix-edge-case",
            [{"baseRefName": "develop", "number": 1}],
        )
        self.assertEqual(len(result["proposals"]), 1)
        proposal = result["proposals"][0]
        self.assertEqual(proposal["base"], "release/v10.0.0")
        self.assertTrue(proposal["title"].endswith("🍒"))
        self.assertEqual(proposal["idempotency_key"], "FLYWL-4:release/v10.0.0:abc123")

    def test_complete_family_has_no_proposals(self):
        result = MODULE.plan(
            {"required_targets": [{"branch": "main"}], "missing_targets": [], "family_complete": True},
            {"key": "CC-1", "title": "Ship"},
            "def456",
            "feature/cc-1-ship",
            [{"baseRefName": "main", "number": 2}],
        )
        self.assertTrue(result["family_complete"])
        self.assertEqual(result["proposals"], [])


if __name__ == "__main__":
    unittest.main()
