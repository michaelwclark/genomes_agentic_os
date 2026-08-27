from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class TrackerContentReadinessPolicyTest(unittest.TestCase):
    def test_auto_dev_policy_makes_jira_and_linear_status_advisory(self) -> None:
        rules = _read("harness/shared_factory/00-programs/auto_dev/RULES.md")
        general = _read(
            "harness/shared_factory/05-knowledge/auto_dev/00-auto-dev-general.md"
        )
        readiness = _read("harness/skills/auto-dev-readiness/SKILL.md")

        for text in (rules, general, readiness):
            self.assertIn("Jira", text)
            self.assertIn("Linear", text)
            self.assertIn("advisory", text)
            self.assertTrue("content-ready" in text or "content_ready" in text)
            self.assertTrue("status label" in text or "workflow label" in text)

    def test_installed_rule_template_preserves_content_based_readiness(self) -> None:
        template = _read("templates/agent-config/RULES.md")

        self.assertIn("Jira and Linear workflow status is advisory", template)
        self.assertIn("acceptance behavior", template)
        self.assertIn("never on the status label itself", template)


if __name__ == "__main__":
    unittest.main()
