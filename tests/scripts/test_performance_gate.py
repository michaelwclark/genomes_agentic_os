from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "harness" / "bin" / "agentic-os-performance-gate"


def load_gate():
    loader = importlib.machinery.SourceFileLoader("agentic_os_performance_gate", str(GATE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)


def repo() -> Path:
    root = Path(tempfile.mkdtemp(prefix="performance-gate-"))
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "Performance Gate Test")
    (root / "los" / "services").mkdir(parents=True)
    (root / "los" / "services" / "views.py").write_text("def execute(request):\n    return response\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "baseline")
    return root


def test_request_path_without_budget_is_blocked():
    root = repo()
    (root / "los" / "services" / "views.py").write_text("def execute(request):\n    return LoanSerializer(request.loan).data\n")
    assert load_gate().main(["--root", str(root), "--base", "HEAD"]) == 1


def test_request_path_with_budget_passes():
    root = repo()
    (root / "los" / "services" / "views.py").write_text("def execute(request):\n    return LoanSerializer(request.loan).data\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_services.py").write_text(
        "def test_execute(django_assert_num_queries):\n"
        "    with django_assert_num_queries(3):\n"
        "        execute(request)\n"
    )
    assert load_gate().main(["--root", str(root), "--base", "HEAD"]) == 0


def test_test_prefix_collisions_are_not_exempted_from_performance_gate():
    # AGE-216 (sibling of AGE-213): TEST_PATH's `(?:tests?|test_)(?:/|[^/]*$)`
    # alternation prefix-matched ANY basename starting with test/tests, so a
    # production module such as testimonial.py or testing_utils.py living
    # inside a request-path risk directory (services/, api/) was misclassified
    # as a test file and silently dropped from risk_files -- the gate PASSED a
    # real, unproven request-path change. Regression guard: both collision
    # names must still be classified as risk and BLOCKED, not exempted.
    for path in ("los/services/testimonial.py", "los/api/testing_utils.py"):
        root = repo()
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("def execute(request):\n    return LoanSerializer(request.loan).data\n")
        assert load_gate().main(["--root", str(root), "--base", "HEAD"]) == 1, (
            f"{path} incorrectly exempted as a test path"
        )


def test_test_prefix_collision_does_not_count_as_query_budget_test_evidence():
    # AGE-216: the same prefix collision also let a production testimonial.py
    # count toward the `tests` list, so a risky request-path change shipped
    # with an untested helper containing a query-budget string falsely
    # satisfied the "add a regression test" requirement. It must stay BLOCKED.
    root = repo()
    (root / "los" / "services" / "views.py").write_text(
        "def execute(request):\n    return LoanSerializer(request.loan).data\n"
    )
    (root / "los" / "services" / "testimonial.py").write_text(
        "def warm(django_assert_num_queries):\n"
        "    with django_assert_num_queries(3):\n"
        "        execute(request)\n"
    )
    assert load_gate().main(["--root", str(root), "--base", "HEAD"]) == 1


def test_test_directory_and_test_prefixed_files_remain_recognized_as_real_tests():
    # Positive pin: the AGE-216 boundary tightening must not regress the
    # legitimate tests/ directory and test_*.py classification that satisfies
    # the query-budget regression-test requirement.
    for path in ("tests/services/test_services.py", "test_foo.py"):
        root = repo()
        (root / "los" / "services" / "views.py").write_text(
            "def execute(request):\n    return LoanSerializer(request.loan).data\n"
        )
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "def test_execute(django_assert_num_queries):\n"
            "    with django_assert_num_queries(3):\n"
            "        execute(request)\n"
        )
        assert load_gate().main(["--root", str(root), "--base", "HEAD"]) == 0, (
            f"{path} no longer recognized as a test file"
        )
