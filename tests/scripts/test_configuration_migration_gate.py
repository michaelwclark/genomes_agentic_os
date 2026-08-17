import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "harness" / "bin" / "agentic-os-configuration-migration-gate"


class ConfigurationMigrationGateTests(unittest.TestCase):
    def test_partial_reload_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "README.md").write_text("base\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "-c", "user.email=test@example.com", "-c", "user.name=test", "commit", "-qm", "base"], cwd=root, check=True)
            migration = root / "app/migrations/0107_reload_jq.py"
            test = root / "tests/test_0107_reload_jq.py"
            migration.parent.mkdir(parents=True)
            test.parent.mkdir(parents=True)
            migration.write_text("JQConfiguration.objects.update(transformer=source)\n")
            test.write_text("def test_rows(): assert count == 3\n")
            result = subprocess.run(["python3", str(SCRIPT), "--root", str(root), "--base", "HEAD"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
