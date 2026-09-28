from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RepositoryVisibilityBoundaryTests(unittest.TestCase):
    def test_boundary_is_present_on_authoring_surfaces(self):
        expected = (
            "genomes_agentic",
            "private",
            "LOS",
            "name, link to, or depend",
            "LOS domain",
            "runtime or delivery dependenc",
        )
        surfaces = (
            ROOT / "templates/agent-config/RULES.md",
            ROOT / "harness/rules/os-authoring-rules.md",
            ROOT / "docs/25-source-of-truth.md",
        )

        for surface in surfaces:
            content = " ".join(surface.read_text(encoding="utf-8").split())
            for phrase in expected:
                with self.subTest(surface=surface, phrase=phrase):
                    self.assertIn(phrase, content)

    def test_tools_registry_describes_private_agentic_repo_boundary(self):
        tools = (ROOT / "harness/TOOLS.md").read_text(encoding="utf-8")

        self.assertIn("external-output-sanitization", tools)
        self.assertIn("private `genomes_agentic*` repositories", tools)
