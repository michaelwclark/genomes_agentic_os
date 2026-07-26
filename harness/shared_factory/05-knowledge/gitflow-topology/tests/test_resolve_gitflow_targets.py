import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("gitflow_topology", ROOT / "resolve_gitflow_targets.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class GitFlowTopologyFixtures(unittest.TestCase):
    def test_fixtures(self):
        for path in sorted((ROOT / "fixtures").glob("*.json")):
            with self.subTest(fixture=path.name):
                fixture = json.loads(path.read_text(encoding="utf-8"))
                result = MODULE.resolve(
                    fixture["project"],
                    fixture["ticket"],
                    fixture.get("registry"),
                    fixture.get("existing_targets"),
                )
                expected = fixture["expected"]
                self.assertEqual(result["route"], expected["route"])
                self.assertEqual(
                    [item["branch"] for item in result["required_targets"]],
                    expected["required_branches"],
                )
                self.assertEqual(result["missing_targets"], expected["missing_targets"])
                self.assertEqual(result["family_complete"], expected["family_complete"])

    def test_missing_fix_version_does_not_match_missing_hotfix_version(self):
        project = {
            "id": "kanga",
            "dev_factory": {
                "pull_request": {
                    "target_policy": {
                        "profile": "promote",
                        "development_branch": "develop",
                        "production_branch": "main",
                        "default_targets": ["develop"],
                    }
                }
            },
        }
        result = MODULE.resolve(
            project,
            {"key": "KAN-154", "type": "Task"},
            {},
            ["develop"],
        )
        self.assertEqual(result["route"], "default")
        self.assertTrue(result["family_complete"])


if __name__ == "__main__":
    unittest.main()
