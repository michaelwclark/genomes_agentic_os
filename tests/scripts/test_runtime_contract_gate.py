from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "harness" / "bin" / "agentic-os-runtime-contract-gate"


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)


def repo() -> Path:
    root = Path(tempfile.mkdtemp(prefix="runtime-contract-gate-"))
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "Runtime Contract Gate Test")
    (root / "los" / "requests" / "api").mkdir(parents=True)
    (root / "los" / "requests" / "api" / "serializers.py").write_text("def payload():\n    return {}\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "baseline")
    return root


def run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(GATE), "--root", str(root), "--base", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )


def test_serializer_contract_change_without_consumer_proof_is_blocked():
    root = repo()
    (root / "los" / "requests" / "api" / "serializers.py").write_text(
        "def canonical_payload():\n    return {'product': {'product_code': 'x'}}\n"
    )
    result = run(root)
    assert result.returncode == 1
    assert "consumer inventory" in result.stderr
    assert "legacy and canonical payload-shape" in result.stderr


def test_contract_change_with_inventory_dual_shape_evaluator_and_result_evidence_passes():
    root = repo()
    (root / "los" / "requests" / "api" / "serializers.py").write_text(
        "def canonical_payload():\n    return {'product': {'product_code': 'x'}}\n"
    )
    tests = root / "tests" / "services"
    tests.mkdir(parents=True)
    (tests / "test_contract.py").write_text(
        "# consumer inventory and tenant impact matrix\n"
        "# legacy flat and canonical nested payload compatibility preserved\n"
        "def test_applicable_documents_rule_evaluate_legacy_and_canonical():\n"
        "    result = ApplicableDocuments.evaluate()\n"
        "    assert result.documents\n"
        "# coordinated consumer migration is not required because backward compatibility is preserved\n"
    )
    result = run(root)
    assert result.returncode == 0, result.stderr


def test_unrelated_model_change_does_not_trigger_contract_gate():
    root = repo()
    model = root / "los" / "models.py"
    model.write_text("class Loan: pass\n")
    result = run(root)
    assert result.returncode == 0, result.stderr


def test_direct_runtime_module_is_not_skipped_by_contract_gate():
    root = repo()
    (root / "views.py").write_text(
        "def canonical_payload():\n"
        "    return {'product': {'product_code': 'x'}}\n"
    )
    result = run(root)
    assert result.returncode == 1
    assert "consumer inventory" in result.stderr


def test_keyword_prefix_collisions_do_not_trigger_contract_gate():
    # views?/api/services?/rules?/config(uration)?/serializers?/requests? must
    # match the complete bare-filename stem, not just a leading substring.
    # Regression guard: apiary.py, ruler.py, serviceability.py, and
    # requester.py are unrelated files whose names happen to start with a
    # gate keyword; a contract-shaped change inside them must not be
    # flagged.
    for name in ("apiary.py", "ruler.py", "serviceability.py", "requester.py"):
        root = repo()
        (root / name).write_text(
            "def canonical_payload():\n"
            "    return {'product': {'product_code': 'x'}}\n"
        )
        result = run(root)
        assert result.returncode == 0, f"{name} incorrectly blocked: {result.stderr}"


def test_direct_runtime_module_with_separator_suffix_is_not_skipped_by_contract_gate():
    # A keyword followed by a `_`/`-`/`.` separator (e.g. views_admin.py) is a
    # legitimate direct runtime module and must still be caught.
    root = repo()
    (root / "views_admin.py").write_text(
        "def canonical_payload():\n"
        "    return {'product': {'product_code': 'x'}}\n"
    )
    result = run(root)
    assert result.returncode == 1
    assert "consumer inventory" in result.stderr


def test_test_prefix_collisions_are_not_exempted_from_contract_gate():
    # AGE-213: TEST_PATH's `(?:tests?|test_)(?:/|[^/]*$)` alternation prefix-
    # matched ANY basename starting with test/tests, so a production module
    # such as testimonial.py or testing_utils.py living inside a runtime-risk
    # directory (services/, config/) was misclassified as a test file and
    # silently excluded from risk_files -- the gate PASSED a real, unproven
    # runtime contract change. Regression guard: both collision names must
    # still be classified as risk and BLOCKED, not exempted.
    cases = ("los/services/testimonial.py", "los/config/testing_utils.py")
    for path in cases:
        root = repo()
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "def canonical_payload():\n"
            "    return {'product': {'product_code': 'x'}}\n"
        )
        result = run(root)
        assert result.returncode == 1, (
            f"{path} incorrectly exempted as a test path: {result.stdout}"
        )
        assert "consumer inventory" in result.stderr, result.stderr


def test_test_directory_and_test_prefixed_files_remain_recognized_as_real_tests():
    # Positive pin: the AGE-213 boundary tightening must not regress the
    # legitimate tests/ directory and test_*.py exemptions used to satisfy
    # the "real consumer regression tests" requirement.
    for path in ("tests/services/test_contract.py", "test_foo.py"):
        root = repo()
        (root / "views.py").write_text(
            "def canonical_payload():\n"
            "    return {'product': {'product_code': 'x'}}\n"
        )
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("def test_something():\n    assert True\n")
        result = run(root)
        assert "real consumer regression tests" not in result.stderr, result.stderr


def test_bare_serializers_file_triggers_the_contract_gate():
    # AGE-213 coverage nit: the existing serializer test only exercises
    # los/requests/api/serializers.py, matched via the requests/ directory
    # boundary. Pin the bare repo-root serializers.py stem match
    # independently so the SERIALIZER_PATH bare-file branch is not only
    # exercised incidentally.
    root = repo()
    (root / "serializers.py").write_text(
        "def canonical_payload():\n"
        "    return {'product': {'product_code': 'x'}}\n"
    )
    result = run(root)
    assert result.returncode == 1
    assert "consumer inventory" in result.stderr
