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
