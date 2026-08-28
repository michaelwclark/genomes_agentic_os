import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "harness" / "bin" / "agentic-os-configuration-migration-gate"

# Migration content satisfying every evidence requirement except the
# regression test, so the test_files check is isolated by the tests below.
FULL_EVIDENCE_MIGRATION = (
    "# jq.compile the full dependency closure of co-dependent templates\n"
    "# preserve tenant custom drift via readback audit\n"
    "# rollback plan: idempotent transaction, reverse supported\n"
    "# rolling deploy: backward compatible with old pod mixed-version reads\n"
    "JQConfiguration.objects.update(transformer=source)\n"
)


def seeded_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=test@example.com", "-c", "user.name=test", "commit", "-qm", "base"], cwd=root, check=True)


class ConfigurationMigrationGateTests(unittest.TestCase):
    def test_partial_reload_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seeded_repo(root)
            migration = root / "app/migrations/0107_reload_jq.py"
            test = root / "tests/test_0107_reload_jq.py"
            migration.parent.mkdir(parents=True)
            test.parent.mkdir(parents=True)
            migration.write_text("JQConfiguration.objects.update(transformer=source)\n")
            test.write_text("def test_rows(): assert count == 3\n")
            result = subprocess.run(["python3", str(SCRIPT), "--root", str(root), "--base", "HEAD"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)

    def test_test_prefix_collisions_do_not_satisfy_the_regression_test_requirement(self):
        # AGE-216 (sibling of AGE-213): TEST_PATH's `(?:tests?|test_)(?:/|[^/]*$)`
        # alternation prefix-matched ANY basename starting with test/tests, so
        # a production module such as testimonial.py or testing_utils.py
        # counted as the migration regression test and the gate PASSED an
        # untested executable-configuration rewrite. Both collision names must
        # be rejected as test evidence and the gate must stay BLOCKED.
        for collision in ("app/services/testimonial.py", "app/config/testing_utils.py"):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                seeded_repo(root)
                migration = root / "app/migrations/0108_reload_jq.py"
                migration.parent.mkdir(parents=True)
                migration.write_text(FULL_EVIDENCE_MIGRATION)
                production = root / collision
                production.parent.mkdir(parents=True)
                production.write_text("VALUE = 1\n")
                result = subprocess.run(["python3", str(SCRIPT), "--root", str(root), "--base", "HEAD"], capture_output=True, text=True)
                self.assertEqual(
                    result.returncode,
                    1,
                    f"{collision} incorrectly satisfied the regression-test requirement: {result.stdout}",
                )
                self.assertIn("a migration regression test", result.stderr)

    def test_test_directory_and_test_prefixed_files_still_satisfy_the_regression_test_requirement(self):
        # Positive pin: the AGE-216 boundary tightening must not regress the
        # legitimate tests/ directory and test_*.py classification that
        # satisfies the migration regression-test requirement.
        for test_path in ("tests/migrations/test_0108_reload_jq.py", "test_0108_reload_jq.py"):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                seeded_repo(root)
                migration = root / "app/migrations/0108_reload_jq.py"
                migration.parent.mkdir(parents=True)
                migration.write_text(FULL_EVIDENCE_MIGRATION)
                test = root / test_path
                test.parent.mkdir(parents=True, exist_ok=True)
                test.write_text("def test_reload(): assert True\n")
                result = subprocess.run(["python3", str(SCRIPT), "--root", str(root), "--base", "HEAD"], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
