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
